/**
 * main.js — Orquestador principal del proyecto RUES API
 *
 * Guarda resultados en:
 *   PostgreSQL:
 *     raw.rues_busqueda      — cada registro de búsqueda
 *     raw.rues_detalle       — expediente completo + columnas Argos
 *     raw.rues_facultades    — facultades/representantes
 *     raw.rues_propietarios  — propietarios/establecimientos
 *
 *   JSON (output/):
 *     rues-busqueda-{run_id}.jsonl    — búsquedas línea a línea (en tiempo real)
 *     rues-detalle-{run_id}.jsonl     — detalles línea a línea (en tiempo real)
 *     rues-facultades-{run_id}.jsonl  — facultades línea a línea
 *     rues-propietarios-{run_id}.jsonl — propietarios línea a línea
 *     rues-errores-{run_id}.jsonl     — errores línea a línea
 *     rues-raw-{run_id}.json          — respuestas crudas agrupadas por keyword
 *     rues-resumen-{run_id}.json      — métricas finales del run
 *
 *   Logs:
 *     logs/rues-FECHA.log             — log completo con niveles
 */
// Importa `fs` para crear directorios y escribir archivos JSON de salida.
const fs   = require('fs');
// Importa `path` para construir rutas absolutas de forma portable.
const path = require('path');
// Importa uuid v4 para generar un identificador único por corrida.
const { v4: uuidv4 }   = require('uuid');
// Importa la configuración central del proyecto.
const { CONFIG }       = require('./config');
// Importa el logger compartido para trazabilidad del orquestador.
const { logger }       = require('./logger');
// Importa el factory del cliente RUES para crear una sesión HTTP aislada.
const { createRuesClient } = require('./client');
// Importa el pipeline unitario que procesa una keyword de extremo a extremo.
const { runSearchPipeline } = require('./pipeline');
// Importa la capa de persistencia PostgreSQL.
const db = require('./db');

// Garantiza que el directorio indicado exista dentro del working directory actual.
function ensureDir(dir) {
  // Crea el directorio y sus padres si aún no existen.
  fs.mkdirSync(path.join(process.cwd(), dir), { recursive: true });
}

// Construye la ruta absoluta de un archivo dentro del directorio de salida configurado.
function outPath(filename) {
  // Retorna la ruta final usando el OUTPUT_DIR definido en config.
  return path.join(process.cwd(), CONFIG.OUTPUT_DIR, filename);
}

// Serializa y escribe un archivo JSON con indentación legible.
function writeJson(filename, data) {
  // Calcula la ruta absoluta del archivo de salida.
  const fp = outPath(filename);
  // Escribe el JSON completo con indentación de dos espacios.
  fs.writeFileSync(fp, JSON.stringify(data, null, 2), 'utf8');
  // Registra en logs la ubicación del archivo guardado.
  logger.info(`[JSON] Guardado: output/${filename}`);
}

// Ejecuta una corrida completa del scraper RUES con las opciones indicadas.
async function do_scrape(opciones = {}) {
  // Desestructura las opciones aplicando defaults sensatos del sistema.
  const {
    // Define el modo de búsqueda por defecto como `razon`.
    mode        = 'razon',
    // Define el conjunto de keywords por defecto desde la configuración central.
    keywords    = CONFIG.KEYWORDS_BUSQUEDA,
    // Activa detalle por defecto en la corrida principal.
    details     = true,
    // Activa endpoints extendidos por defecto.
    extended    = true,
    // Permite limitar la cantidad de detalles procesados por keyword.
    limit       = undefined,
    // Permite controlar el limit del endpoint de búsqueda.
    searchLimit = undefined,
    // Define la concurrencia del pipeline con fallback a config.
    concurrency = CONFIG.DEFAULT_CONCURRENCY,
    // Define el delay entre llamadas con fallback a config.
    delayMs     = CONFIG.DEFAULT_DELAY_MS,
    // Define la cantidad máxima de reintentos con fallback a config.
    maxRetries  = CONFIG.DEFAULT_MAX_RETRIES,
    // Define la base del backoff exponencial con fallback a config.
    retryBaseMs = CONFIG.DEFAULT_RETRY_BASE_MS,
  } = opciones;

  // Genera un identificador único para esta corrida completa.
  const run_id   = uuidv4();
  // Captura el timestamp de inicio de la corrida.
  const inicioAt = new Date();

  // Imprime un encabezado visual de apertura del run.
  logger.section(`RUES SCRAPER — run_id: ${run_id}`);
  // Registra la fecha/hora de inicio en formato ISO.
  logger.info(`Inicio:      ${inicioAt.toISOString()}`);
  // Registra el resumen operativo de keywords, detalle y extendido.
  logger.info(`Keywords:    ${keywords.length} | Detalle: ${details} | Extendido: ${extended}`);
  // Registra la configuración de concurrencia, delay y retries.
  logger.info(`Concurrencia:${concurrency} | Delay: ${delayMs}ms | Retries: ${maxRetries}`);

  // Garantiza que el directorio de salida exista antes de escribir artefactos.
  //ensureDir(CONFIG.OUTPUT_DIR);
  if (CONFIG.WRITE_OUTPUT) {
    ensureDir(CONFIG.OUTPUT_DIR);
  }

  // Intenta inicializar la base de datos y sus tablas necesarias.
  try {
    // Verifica/crea schema y tablas raw del proyecto.
    await db.initDb();
  } catch (e) {
    // Registra el error como fatal si la base no pudo inicializarse.
    logger.fatal(`[BD] No se pudo inicializar: ${e.message}`);
    // Relanza el error para abortar la corrida.
    throw e;
  }

  // Carga desde la base el conjunto de `id_rm` ya detallados en corridas previas.
  const procesados = await db.cargarIdRmProcesados();
  // Registra cuántos registros ya estaban procesados de antemano.
  logger.info(`[BD] ${procesados.size} registros ya procesados previamente`);

  // Define las rutas de los JSONL de escritura en tiempo real para cada tipo de evento.
  //const jsonlPaths = {
  const jsonlPaths = CONFIG.WRITE_OUTPUT ? {
    // Ruta del JSONL de resultados de búsqueda.
    busqueda:     outPath(`rues-busqueda-${run_id}.jsonl`),
    // Ruta del JSONL de resultados de detalle.
    detalle:      outPath(`rues-detalle-${run_id}.jsonl`),
    // Ruta del JSONL de facultades.
    facultades:   outPath(`rues-facultades-${run_id}.jsonl`),
    // Ruta del JSONL de propietarios.
    propietarios: outPath(`rues-propietarios-${run_id}.jsonl`),
    // Ruta del JSONL de errores.
    errores:      outPath(`rues-errores-${run_id}.jsonl`),
  //};
  } : {};

  // Registra la apertura de los archivos JSONL operativos.
  logger.info(`[JSON] JSONL en tiempo real:`);
  // Documenta la ruta del archivo de búsquedas.
  logger.info(`       Búsquedas:    output/rues-busqueda-${run_id}.jsonl`);
  // Documenta la ruta del archivo de detalles.
  logger.info(`       Detalles:     output/rues-detalle-${run_id}.jsonl`);
  // Documenta la ruta del archivo de facultades.
  logger.info(`       Facultades:   output/rues-facultades-${run_id}.jsonl`);
  // Documenta la ruta del archivo de propietarios.
  logger.info(`       Propietarios: output/rues-propietarios-${run_id}.jsonl`);
  // Documenta la ruta del archivo de errores.
  logger.info(`       Errores:      output/rues-errores-${run_id}.jsonl`);

  // Crea una instancia del cliente RUES para esta corrida.
  const client = createRuesClient();
  // Imprime una sección visual para la inicialización de sesión.
  logger.section('INICIALIZANDO SESIÓN RUES');
  try {
    // Ejecuta el bootstrap inicial contra el frontend real para obtener cookies/sesión.
    await client.bootstrapSession();
    // Registra que la sesión quedó inicializada correctamente.
    logger.ok('[SESSION] Sesión inicializada correctamente');
  } catch (e) {
    // Registra el fallo de bootstrap como error fatal.
    logger.fatal(`[SESSION] Falló bootstrap: ${e.message}`);
    // Relanza el error para abortar el run.
    throw e;
  }

  // Inicializa el arreglo que agrupará respuestas raw por keyword para el JSON final.
  const rawAgrupado = [];
  // Inicializa el objeto de métricas acumuladas del run completo.
  const metricas = {
    // Guarda el identificador único de esta corrida.
    run_id,
    // Guarda el instante de inicio en formato ISO.
    inicio:               inicioAt.toISOString(),
    // Reserva el instante de fin, que será completado al cierre.
    fin:                  null,
    // Reserva la duración legible final del proceso.
    duracion:             null,
    // Guarda cuántas keywords había planeadas.
    keywords_total:       keywords.length,
    // Inicializa el contador de keywords procesadas exitosamente.
    keywords_procesadas:  0,
    // Inicializa el acumulador total de resultados de búsqueda normalizados.
    busqueda_total:       0,
    // Inicializa el contador de detalles exitosos.
    detalle_ok:           0,
    // Inicializa el contador de errores de detalle.
    detalle_error:        0,
    // Inicializa el contador de detalles saltados por ya procesados.
    detalle_saltado:      0,
    // Inicializa el contador de facultades exitosas.
    facultades_ok:        0,
    // Inicializa el contador de errores de facultades.
    facultades_error:     0,
    // Inicializa el contador de propietarios exitosos.
    propietarios_ok:      0,
    // Inicializa el contador de errores de propietarios.
    propietarios_error:   0,
    // Inicializa el contador de registros aprobados por score Argos.
    aprobados_argos:      0,
    // Inicializa el contador total de errores operativos.
    errores_totales:      0,
  };

  // Recorre secuencialmente todas las keywords planificadas para la corrida.
  for (let ki = 0; ki < keywords.length; ki++) {
    // Obtiene la keyword actual del índice del bucle.
    const keyword = keywords[ki];
    // Imprime una sección visual indicando el progreso dentro del lote de keywords.
    logger.section(`[${ki+1}/${keywords.length}] keyword: "${keyword}"`);

    try {
      // Ejecuta el pipeline completo para la keyword actual pasando cliente, opciones y rutas auxiliares.
      const pipeline = await runSearchPipeline(
        client, mode, keyword,
        { details, extended, limit, searchLimit, concurrency, delayMs, maxRetries, retryBaseMs },
        run_id,
        procesados,
        jsonlPaths
      );

      // Agrega la respuesta raw agrupada por keyword para consolidarla al final del run.
      rawAgrupado.push({
        // Guarda la keyword fuente.
        keyword,
        // Guarda el identificador de corrida.
        run_id,
        // Guarda el instante de ejecución reportado por el pipeline.
        executedAt:     pipeline.executedAt,
        // Guarda la cantidad reportada por el backend.
        cantReportados: pipeline.search.cantReportados,
        // Guarda el tamaño real del arreglo normalizado.
        cantArray:      pipeline.search.normalized.length,
        // Guarda cuántos registros fueron seleccionados para detalle.
        selectedCount:  pipeline.search.selectedCount,
        // Guarda la respuesta raw completa del search.
        raw_response:   pipeline.search.raw,
      });

      // Incrementa la cantidad de keywords procesadas con éxito lógico.
      metricas.keywords_procesadas++;
      // Acumula la cantidad total de resultados de búsqueda normalizados.
      metricas.busqueda_total  += pipeline.search.normalized.length;

      // Obtiene el arreglo de resultados de detalle o un arreglo vacío si no existe.
      const results = pipeline.details?.results ?? [];
      // Obtiene el arreglo de errores de detalle o un arreglo vacío si no existe.
      const errors  = pipeline.details?.errors  ?? [];

      // Cuenta como detalle_ok los resultados que no tienen error ni fueron saltados.
      metricas.detalle_ok      += results.filter(r => !r.error && !r.skipped).length;
      // Cuenta los resultados que fueron saltados por ya existir en base.
      metricas.detalle_saltado += results.filter(r => r.skipped).length;
      // Acumula el total de errores de detalle.
      metricas.detalle_error   += errors.length;
      // Cuenta como facultades exitosas los resultados que traen texto y no registran error de facultades.
      metricas.facultades_ok   += results.filter(r => r.facultades_text && !r.facultades_error).length;
      // Cuenta los errores de facultades detectados en resultados.
      metricas.facultades_error+= results.filter(r => r.facultades_error).length;
      // Cuenta como propietarios exitosos los resultados que traen respuesta normalizada y no registran error.
      metricas.propietarios_ok += results.filter(r => r.propietario_normalized && !r.propietario_error).length;
      // Cuenta los errores de propietario detectados en resultados.
      metricas.propietarios_error += results.filter(r => r.propietario_error).length;
      // Acumula la cantidad de registros aprobados por la heurística Argos.
      metricas.aprobados_argos += results.filter(r => r.aprobado_argos).length;
      // Acumula el total de errores operativos de esta keyword.
      metricas.errores_totales += errors.length;

      // Registra un resumen de la keyword recién procesada.
      logger.ok(`[KEYWORD] "${keyword}" → búsqueda:${pipeline.search.normalized.length} det_ok:${results.filter(r => !r.error && !r.skipped).length} aprobados:${results.filter(r => r.aprobado_argos).length}`);

    } catch (e) {
      // Registra el fallo completo de la keyword actual sin detener necesariamente todo el lote.
      logger.error(`[KEYWORD] "${keyword}" falló: ${e.message}`);
      // Incrementa el contador global de errores si la keyword falló a nivel macro.
      metricas.errores_totales++;
    }
  }

  // Imprime la sección visual de guardado de resultados finales.
  logger.section('GUARDANDO RESULTADOS FINALES');

  // Guarda el JSON agrupado por keyword con las respuestas raw de búsqueda.
  //writeJson(`rues-raw-${run_id}.json`, rawAgrupado);

  // Captura el timestamp real de finalización del run.
  const finAt     = new Date();
  // Calcula la duración total del run en segundos enteros.
  const duracionS = Math.round((finAt - inicioAt) / 1000);
  // Completa el campo `fin` de las métricas con formato ISO.
  metricas.fin     = finAt.toISOString();
  // Completa el campo `duracion` con un formato humano simple de minutos y segundos.
  metricas.duracion = `${Math.floor(duracionS/60)}m ${duracionS%60}s`;

  // Guarda el archivo JSON de resumen final de la corrida.
  //writeJson(`rues-resumen-${run_id}.json`, metricas);


  if (CONFIG.WRITE_OUTPUT) {
  writeJson(`rues-raw-${run_id}.json`, rawAgrupado);
  writeJson(`rues-resumen-${run_id}.json`, metricas);
  }


  // Imprime el resumen final de métricas en consola y archivo de log.
  logger.summary(metricas);

  // Cierra el pool de conexiones PostgreSQL al terminar el run.
  await db.closePool();
  // Cierra el stream del logger para flush y liberación de recursos.
  logger.close();

  // Retorna las métricas finales para consumo por API runner u otros llamadores.
  return metricas;
}

// Verifica si este archivo fue ejecutado directamente desde Node y no importado como módulo.
if (require.main === module) {
  // Detecta si se pidió modo test mediante el flag `--test`.
  const modoTest = process.argv.includes('--test');
  // Ejecuta el scraper con configuración estándar o reducida si es modo test.
  do_scrape({
    // Mantiene activado el detalle en la ejecución directa.
    details:    true,
    // Mantiene activados los endpoints extendidos en la ejecución directa.
    extended:   true,
    // Usa solo la primera keyword en test o todas en producción.
    keywords:   modoTest ? [CONFIG.KEYWORDS_BUSQUEDA[0]] : CONFIG.KEYWORDS_BUSQUEDA,
    // Reduce el límite de detalles cuando es modo test.
    limit:      modoTest ? 3 : undefined,
    // Fija concurrencia 1 para comportamiento conservador.
    concurrency:1,
    // Fija delay entre requests para no presionar demasiado al origen.
    delayMs:    1200,
  }).catch(e => {
    // Registra el error fatal si la ejecución directa falla.
    logger.fatal(e.message);
    // Finaliza el proceso con código de error.
    process.exit(1);
  });
}

// Exporta el orquestador principal para uso por `api_runner.js` u otros consumidores.
module.exports = { do_scrape };