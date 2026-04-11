// Importa `fs` para escribir archivos JSON de salida en disco.
const fs = require('fs');
// Importa `path` para construir rutas de salida de forma segura.
const path = require('path');
// Importa el cliente RUES para inicializar sesión y ejecutar consultas.
const { createRuesClient } = require('./client');
// Importa el pipeline principal de búsqueda y detalle.
const { runSearchPipeline } = require('./pipeline');
// Importa el helper que sanea fragmentos usados en nombres de archivo.
const { sanitizeFileFragment } = require('./utils');

// Parsea argumentos de línea de comandos y los convierte en un objeto de opciones.
function parseArgs(argv) {
  // Inicializa el objeto de opciones con defaults neutros para flags opcionales.
  const options = {
    // Indica si se deben consultar detalles por id_rm.
    details: false,
    // Indica si además se deben consultar endpoints extendidos.
    extended: false,
    // Límite de registros a procesar en detalle.
    limit: undefined,
    // Límite del endpoint de búsqueda.
    searchLimit: undefined,
    // Concurrencia del pipeline.
    concurrency: undefined,
    // Delay entre peticiones.
    delayMs: undefined,
    // Máximo de reintentos.
    maxRetries: undefined,
    // Base del backoff de reintentos.
    retryBaseMs: undefined,
    // Filtro de departamento.
    departamento: undefined,
    // Filtro de cámara.
    codCamara: undefined,
    // Offset de paginación.
    offset: undefined
  };

  // Recorre los argumentos a partir del índice 4 porque 0 y 1 son node/script y 2/3 son modo/valor.
  for (const arg of argv.slice(4)) {
    // Activa solo el modo detalle si el flag coincide exactamente.
    if (arg === '--details') options.details = true;
    // Activa el modo extendido y fuerza `details` porque depende del detalle previo.
    else if (arg === '--extended') {
      options.details = true;
      options.extended = true;
    }
    // Parsea el límite de detalle desde `--limit=`.
    else if (arg.startsWith('--limit=')) options.limit = Number(arg.split('=')[1]);
    // Parsea el límite del endpoint de búsqueda desde `--search-limit=`.
    else if (arg.startsWith('--search-limit=')) options.searchLimit = Number(arg.split('=')[1]);
    // Parsea la concurrencia desde `--concurrency=`.
    else if (arg.startsWith('--concurrency=')) options.concurrency = Number(arg.split('=')[1]);
    // Parsea el delay en milisegundos desde `--delay=`.
    else if (arg.startsWith('--delay=')) options.delayMs = Number(arg.split('=')[1]);
    // Parsea el máximo de reintentos desde `--max-retries=`.
    else if (arg.startsWith('--max-retries=')) options.maxRetries = Number(arg.split('=')[1]);
    // Parsea la base del backoff desde `--retry-base=`.
    else if (arg.startsWith('--retry-base=')) options.retryBaseMs = Number(arg.split('=')[1]);
    // Parsea el filtro de departamento desde `--departamento=`.
    else if (arg.startsWith('--departamento=')) options.departamento = arg.split('=')[1];
    // Parsea el código de cámara desde `--cod-camara=`.
    else if (arg.startsWith('--cod-camara=')) options.codCamara = arg.split('=')[1];
    // Parsea el offset de paginación desde `--offset=`.
    else if (arg.startsWith('--offset=')) options.offset = Number(arg.split('=')[1]);
  }

  // Retorna el objeto de opciones final ya parseado.
  return options;
}

// Define la función principal ejecutada desde la CLI.
async function main() {
  // Obtiene el modo desde el tercer argumento del proceso (`razon` o `nit`).
  const mode = process.argv[2];
  // Obtiene el valor de búsqueda desde el cuarto argumento del proceso.
  const value = process.argv[3];
  // Parsea el resto de argumentos opcionales de línea de comandos.
  const options = parseArgs(process.argv);

  // Valida que modo y valor existan y que el modo pertenezca al conjunto soportado.
  if (!mode || !value || !['razon', 'nit'].includes(mode)) {
    // Imprime encabezado básico de uso.
    console.log('Uso:');
    // Muestra ejemplo de búsqueda por razón social.
    console.log('  node src/cli.js razon "ferreteria"');
    // Muestra ejemplo de búsqueda por NIT.
    console.log('  node src/cli.js nit 901362593');
    // Imprime una línea en blanco para separar visualmente la ayuda.
    console.log('');
    // Imprime encabezado de opciones disponibles.
    console.log('Opciones:');
    // Describe la bandera de detalle.
    console.log('  --details              Trae DetalleRM por id');
    // Describe la bandera de extendido.
    console.log('  --extended             Ademas trae facultades y propietario por camara+matricula');
    // Describe el límite de detalle.
    console.log('  --limit=10             Limita cuantos registros del search se procesan en detalle');
    // Describe el límite del endpoint de búsqueda.
    console.log('  --search-limit=500     Limit del endpoint de busqueda');
    // Describe la concurrencia.
    console.log('  --concurrency=1        Concurrencia del pipeline de detalle');
    // Describe el delay.
    console.log('  --delay=1200           Delay en ms entre llamadas de detalle');
    // Describe el número de reintentos.
    console.log('  --max-retries=5        Reintentos ante 429/errores transitorios');
    // Describe la base del backoff.
    console.log('  --retry-base=1500      Base del backoff exponencial');
    // Finaliza el proceso indicando error de uso.
    process.exit(1);
  }

  // Crea una instancia del cliente RUES.
  const client = createRuesClient();

  try {
    // Informa el inicio del bootstrap de sesión HTTP.
    console.log('1) Inicializando sesión...');
    // Inicializa la sesión/cookies contra el frontend antes de usar la API.
    await client.bootstrapSession();

    // Informa la búsqueda puntual que se va a ejecutar.
    console.log(`2) Ejecutando búsqueda por ${mode}: ${value}`);
    // Si se activó detalle, informa esta etapa.
    if (options.details) console.log('3) Detalle activado.');
    // Si se activó extendido, informa esta etapa adicional.
    if (options.extended) console.log('4) Modo extendido activado (facultades + propietario).');

    // Ejecuta el pipeline principal con el cliente, modo, valor y opciones parseadas.
    const pipeline = await runSearchPipeline(client, mode, value, options);

    // Construye la ruta absoluta del directorio de salida.
    const outputDir = path.join(process.cwd(), 'output');
    // Garantiza que el directorio exista.
    fs.mkdirSync(outputDir, { recursive: true });

    // Genera una etiqueta de archivo segura a partir del valor buscado.
    const tag = sanitizeFileFragment(value);

    // Guarda la respuesta raw del search en disco.
    writeJson(outputDir, `resultado-${mode}-${tag}-search-raw.json`, pipeline.search.raw);
    // Guarda la versión normalizada del search en disco.
    writeJson(outputDir, `resultado-${mode}-${tag}-search-normalized.json`, pipeline.search.normalized);

    // Si hubo etapa de detalle, guarda todos sus artefactos asociados.
    if (pipeline.details) {
      // Guarda el conjunto completo de resultados de detalle, incluyendo parciales.
      writeJson(outputDir, `resultado-${mode}-${tag}-details-all.json`, pipeline.details.all);
      // Guarda solo los resultados de detalle exitosos o parcialmente exitosos.
      writeJson(outputDir, `resultado-${mode}-${tag}-details-results.json`, pipeline.details.results);
      // Guarda los errores de detalle.
      writeJson(outputDir, `resultado-${mode}-${tag}-details-errors.json`, pipeline.details.errors);

      // Construye un arreglo simplificado con facultades limpias por registro.
      const facultades = pipeline.details.results
        // Filtra los resultados que tengan la propiedad `facultades_text`.
        .filter(x => x && Object.prototype.hasOwnProperty.call(x, 'facultades_text'))
        // Mapea cada resultado a una estructura compacta para exportación.
        .map(x => ({
          // Conserva el identificador interno del registro.
          id_rm: x.id_rm,
          // Conserva el código de cámara si existe dentro del detalle normalizado.
          cod_camara: x.detalle_normalized?.cod_camara ?? null,
          // Conserva la matrícula si existe dentro del detalle normalizado.
          matricula: x.detalle_normalized?.matricula ?? null,
          // Guarda el texto limpio de facultades.
          facultades_text: x.facultades_text ?? '',
          // Guarda el error de facultades si existió.
          facultades_error: x.facultades_error ?? null
        }));
      // Escribe el archivo JSON simplificado de facultades.
      writeJson(outputDir, `resultado-${mode}-${tag}-facultades-clean.json`, facultades);

      // Construye un arreglo simplificado con propietarios normalizados por registro.
      const propietarios = pipeline.details.results
        // Filtra los resultados que tengan la propiedad `propietario_normalized`.
        .filter(x => x && Object.prototype.hasOwnProperty.call(x, 'propietario_normalized'))
        // Mapea cada resultado a una estructura compacta para exportación.
        .map(x => ({
          // Conserva el identificador interno del registro.
          id_rm: x.id_rm,
          // Conserva el código de cámara si existe dentro del detalle normalizado.
          cod_camara: x.detalle_normalized?.cod_camara ?? null,
          // Conserva la matrícula si existe dentro del detalle normalizado.
          matricula: x.detalle_normalized?.matricula ?? null,
          // Guarda la respuesta de propietario ya normalizada.
          propietario: x.propietario_normalized ?? null,
          // Guarda el error de propietario si existió.
          propietario_error: x.propietario_error ?? null
        }));
      // Escribe el archivo JSON simplificado de propietarios.
      writeJson(outputDir, `resultado-${mode}-${tag}-propietario-normalized.json`, propietarios);
    }

    // Calcula el total reportado usando la respuesta raw o el largo del arreglo como fallback.
    const total = pipeline.search.raw?.response?.cant_registros ?? pipeline.search.raw?.response?.registros?.length ?? 0;
    // Informa la finalización exitosa del proceso.
    console.log('Proceso finalizado.');
    // Informa cuántos registros reportó el endpoint de búsqueda.
    console.log(`Registros reportados por búsqueda: ${total}`);
    // Informa cuántos registros fueron seleccionados para detalle.
    console.log(`Registros seleccionados para detalle: ${pipeline.search.selectedCount}`);
    // Informa dónde quedaron guardados los archivos de salida.
    console.log(`Salida guardada en: ${outputDir}`);
  } catch (error) {
    // Informa un error general del pipeline en consola de error.
    console.error('Error en el pipeline RUES');
    // Si el error proviene de axios con respuesta HTTP, imprime status y data.
    if (error.response) {
      // Imprime el código de estado HTTP asociado al fallo.
      console.error('Status:', error.response.status);
      // Imprime el cuerpo del error en formato JSON legible.
      console.error('Data:', JSON.stringify(error.response.data, null, 2));
    } else {
      // Si no existe `response`, imprime stack trace o al menos el mensaje simple.
      console.error(error.stack || error.message);
    }
    // Finaliza el proceso con código de error.
    process.exit(1);
  }
}

// Define un helper para escribir cualquier objeto JSON en disco.
function writeJson(dir, filename, value) {
  // Serializa el valor con indentación de 2 espacios y lo escribe en la ruta final.
  fs.writeFileSync(path.join(dir, filename), JSON.stringify(value, null, 2), 'utf8');
}

// Ejecuta la función principal al cargar el archivo desde la CLI.
main();