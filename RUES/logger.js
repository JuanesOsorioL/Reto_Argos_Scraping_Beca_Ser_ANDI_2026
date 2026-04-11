/**
 * logger.js — Sistema de logging con niveles, colores en consola y archivo.
 *
 * Niveles:
 *   INFO  → progreso normal del pipeline
 *   OK    → inserción/guardado exitoso
 *   WARN  → advertencia no fatal (campo vacío, dato faltante)
 *   ERROR → error recuperable (reintento posible)
 *   FATAL → error no recuperable
 *   DEBUG → detalle técnico (solo si DEBUG_MODE=true)
 *
 * Salida:
 *   - Consola con colores
 *   - logs/rues-YYYY-MM-DD.log (texto plano)
 */

// Importa el módulo nativo `fs` para crear directorios y escribir archivos de log.
const fs   = require('fs');
// Importa el módulo nativo `path` para construir rutas seguras entre sistemas operativos.
const path = require('path');

require('dotenv').config();

const WRITE_LOG_FILE = process.env.WRITE_LOG_FILE !== 'false';
console.log('WRITE_LOG_FILE =', process.env.WRITE_LOG_FILE);


// Define el mapa de colores ANSI usado para colorear la salida en consola por nivel de log.
const COLORS = {
  // Código ANSI para resetear el color/estilo actual.
  RESET:  '\x1b[0m',
  // Código ANSI para mensajes informativos en cyan.
  INFO:   '\x1b[36m',
  // Código ANSI para mensajes exitosos en verde.
  OK:     '\x1b[32m',
  // Código ANSI para advertencias en amarillo.
  WARN:   '\x1b[33m',
  // Código ANSI para errores en rojo.
  ERROR:  '\x1b[31m',
  // Código ANSI para errores fatales en magenta.
  FATAL:  '\x1b[35m',
  // Código ANSI para mensajes de debug en gris.
  DEBUG:  '\x1b[90m',
  // Código ANSI para encabezados en azul y negrita.
  HEADER: '\x1b[1;34m',
  // Código ANSI para texto atenuado.
  DIM:    '\x1b[2m',
};

// Activa el modo debug únicamente cuando la variable de entorno DEBUG_MODE vale exactamente 'true'.
const DEBUG_MODE = process.env.DEBUG_MODE === 'true';
// Construye la ruta absoluta del directorio `logs` dentro del directorio actual del proceso.
const LOG_DIR    = path.join(process.cwd(), 'logs');

// Declara una referencia compartida al stream de escritura del archivo de logs.
let logStream = null;



/*
// Obtiene o inicializa el stream hacia el archivo diario de log.
function getLogStream() {
  // Si todavía no existe un stream abierto, crea directorio y archivo.
  if (!logStream) {
    // Garantiza que el directorio de logs exista antes de escribir el archivo.
    fs.mkdirSync(LOG_DIR, { recursive: true });
    // Calcula la fecha actual en formato YYYY-MM-DD para usarla en el nombre del archivo.
    const date    = new Date().toISOString().slice(0, 10);
    // Construye la ruta del archivo de log diario.
    const logFile = path.join(LOG_DIR, `rues-${date}.log`);
    // Abre el stream en modo append para no sobrescribir logs previos del mismo día.
    logStream     = fs.createWriteStream(logFile, { flags: 'a', encoding: 'utf8' });
  }
  // Retorna el stream ya existente o recién creado.
  return logStream;
}
*/
function getLogStream() {
  if (!WRITE_LOG_FILE) return null;

  if (!logStream) {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    const date = new Date().toISOString().slice(0, 10);
    const logFile = path.join(LOG_DIR, `rues-${date}.log`);
    logStream = fs.createWriteStream(logFile, { flags: 'a', encoding: 'utf8' });
  }
  return logStream;
}





// Genera un timestamp legible con milisegundos para consola y archivo.
function timestamp() {
  // Convierte el ISO timestamp reemplazando la T por espacio y recortando a milisegundos.
  return new Date().toISOString().replace('T', ' ').slice(0, 23);
}

// Escribe un log tanto en archivo como en consola usando el nivel indicado.
function write(level, msg, extra) {
  // Captura la marca de tiempo del momento del log.
  const ts      = timestamp();
  // Serializa el objeto `extra` si existe para adjuntarlo en una sola cadena.
  const extraStr = extra ? `  ${JSON.stringify(extra)}` : '';

  // Escribe la línea de log en archivo sin colores ANSI.
  //getLogStream().write(`[${ts}] [${level.padEnd(5)}] ${msg}${extraStr}\n`);
  const stream = getLogStream();
  if (stream) {
    stream.write(`[${ts}] [${level.padEnd(5)}] ${msg}${extraStr}\n`);
  }



  // Obtiene el color asociado al nivel o reset si no existe uno definido.
  const color = COLORS[level] || COLORS.RESET;
  // Obtiene el estilo atenuado para el timestamp y extras.
  const dim   = COLORS.DIM;
  // Obtiene el código de reset para cerrar estilos ANSI.
  const reset = COLORS.RESET;
  // Imprime la línea en consola con timestamp atenuado, nivel coloreado y extras si existen.
  console.log(`${dim}[${ts}]${reset} ${color}[${level.padEnd(5)}]${reset} ${msg}${extra ? `${dim}${extraStr}${reset}` : ''}`);
}

// Define el objeto público del logger con sus métodos por nivel y utilidades de presentación.
const logger = {
  // Expone el método `info` que delega a `write` con nivel INFO.
  info:  (msg, extra) => write('INFO',  msg, extra),
  // Expone el método `ok` que delega a `write` con nivel OK.
  ok:    (msg, extra) => write('OK',    msg, extra),
  // Expone el método `warn` que delega a `write` con nivel WARN.
  warn:  (msg, extra) => write('WARN',  msg, extra),
  // Expone el método `error` que delega a `write` con nivel ERROR.
  error: (msg, extra) => write('ERROR', msg, extra),
  // Expone el método `fatal` que delega a `write` con nivel FATAL.
  fatal: (msg, extra) => write('FATAL', msg, extra),
  // Expone el método `debug` condicionado al flag DEBUG_MODE para evitar ruido en producción.
  debug: (msg, extra) => { if (DEBUG_MODE) write('DEBUG', msg, extra); },

  // Declara un método para imprimir un separador visual de secciones en la consola y en el archivo.
  section(title) {
    // Construye una línea larga con caracteres de caja para delimitar visualmente la sección.
    const line = '═'.repeat(60);
    // Captura el timestamp de apertura de la sección.
    const ts   = timestamp();
    // Construye el bloque de texto coloreado que se mostrará en consola.
    const text = `\n${COLORS.HEADER}${line}\n  ${title}\n${line}${COLORS.RESET}`;
    // Escribe la apertura de sección también en el archivo de log en formato plano.
   //getLogStream().write(`\n[${ts}] [${'SEC'.padEnd(5)}] ${title}\n`);

   const stream = getLogStream();
  if (stream) {
    stream.write(`\n[${ts}] [${'SEC'.padEnd(5)}] ${title}\n`);
  }


    // Imprime el bloque visual en consola.
    console.log(text);
  },

  // Declara un método para imprimir un resumen de métricas al final del run.
  summary(metrics) {
    // Construye una línea divisoria más ligera para el resumen final.
    const line = '─'.repeat(60);
    // Imprime la línea superior del resumen con estilo de encabezado.
    console.log(`\n${COLORS.HEADER}${line}${COLORS.RESET}`);
    // Imprime el título del resumen.
    console.log(`${COLORS.HEADER}  RESUMEN FINAL${COLORS.RESET}`);
    // Imprime la línea inferior del encabezado del resumen.
    console.log(`${COLORS.HEADER}${line}${COLORS.RESET}`);
    // Recorre cada par clave/valor de las métricas para mostrarlo en columnas simples.
    for (const [k, v] of Object.entries(metrics)) {
      // Imprime cada métrica alineando la clave y resaltando el valor en verde.
      console.log(`  ${COLORS.DIM}${k.padEnd(30)}${COLORS.RESET} ${COLORS.OK}${v}${COLORS.RESET}`);
    }
    // Imprime la línea final del bloque de resumen.
    console.log(`${COLORS.HEADER}${line}${COLORS.RESET}\n`);
    // Escribe también las métricas completas serializadas en el archivo de log.
    //getLogStream().write(`\n[RESUMEN] ${JSON.stringify(metrics)}\n`);

    const stream = getLogStream();
  if (stream) {
    stream.write(`\n[RESUMEN] ${JSON.stringify(metrics)}\n`);
  }
  },

  // Declara un método para cerrar el stream de archivo cuando termina la corrida.
  close() {
    // Verifica que exista un stream abierto antes de intentar cerrarlo.
    if (logStream) {
      // Cierra el stream actual para flush y liberación de recursos.
      logStream.end();
      // Limpia la referencia compartida para permitir reapertura futura si hace falta.
      logStream = null;
    }
  }
};

// Exporta el logger como API pública del módulo.
module.exports = { logger };
