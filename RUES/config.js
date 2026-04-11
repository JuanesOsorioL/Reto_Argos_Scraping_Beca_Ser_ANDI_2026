// Carga automáticamente las variables de entorno desde un archivo `.env` al iniciar el proceso.
require('dotenv').config();

// Define el objeto central de configuración reutilizado por todo el proyecto.
const CONFIG = {
  // URL base del frontend oficial de RUES usada para bootstrap de sesión y para construir headers válidos.
  FRONTEND_BASE_URL:    'https://www.rues.org.co',
  // URL base del backend/API real al que se le hacen las consultas cifradas.
  API_BASE_URL:         'https://elasticprd.rues.org.co',
  // Ruta del endpoint de búsqueda avanzada de registro mercantil.
  BUSQUEDA_RM_PATH:     '/api/ConsultasRUES/BusquedaAvanzadaRM',
  // Ruta del endpoint que devuelve el detalle de un expediente mercantil.
  DETALLE_RM_PATH:      '/api/Expediente/DetalleRM',
  // Ruta del endpoint que devuelve facultades por cámara y matrícula.
  FACULTADES_PATH:      '/api/ConsultFacultadesXCamYMatricula',
  // Ruta del endpoint que devuelve propietario/establecimiento por cámara y matrícula.
  PROPIETARIO_EST_PATH: '/api/PropietarioEstXCamaraYMatricula',
  // Llave AES usada para replicar exactamente el cifrado esperado por el backend de RUES.
  AES_KEY:              'ac1244b5-8bee-47b2-a4a5-924a748d907f',

  // Timeout por defecto de cada request HTTP en milisegundos.
  DEFAULT_TIMEOUT_MS:    60000,
  // Límite por defecto de resultados cuando se invoca el endpoint de búsqueda.
  DEFAULT_LIMIT:         500,
  // Offset por defecto de paginación para búsquedas.
  DEFAULT_OFFSET:        0,
  // Concurrencia por defecto usada por el pipeline de detalle.
  DEFAULT_CONCURRENCY:   1,
  // Delay por defecto entre llamadas consecutivas en milisegundos.
  DEFAULT_DELAY_MS:      1200,
  // Número máximo de reintentos por defecto para errores transitorios.
  DEFAULT_MAX_RETRIES:   5,
  // Base del backoff exponencial para reintentos.
  DEFAULT_RETRY_BASE_MS: 1500,

  // Define los headers base usados por el backend de RUES para requests JSON cifrados.
  DEFAULT_HEADERS: {
    // Declara que se aceptan respuestas JSON, texto plano o cualquier otro formato.
    Accept:         'application/json, text/plain, */*',
    // Declara que el cuerpo enviado por el cliente se transmite en JSON.
    'Content-Type': 'application/json',
    // Identifica el nombre de la app cliente tal como lo espera el backend.
    'app-name':     'RuesFront',
    // Reserva un header para request id aunque aquí queda vacío por defecto.
    'x-request-id': ''
  },

  // Define headers de navegador simulados para parecer tráfico legítimo del frontend.
  DEFAULT_BROWSER_HEADERS: {
    // Define un User-Agent moderno para minimizar bloqueos triviales por anti-bot o validaciones simples.
    'User-Agent':     'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    // Declara preferencia de idioma en español para las respuestas.
    'Accept-Language':'es-ES,es;q=0.8'
  },


KEYWORDS_BUSQUEDA: [
    'A&C FERRETERIA S.A.S'
  ],




/*
  // Lista de keywords objetivo alineadas al universo de negocio del proyecto Argos.
  KEYWORDS_BUSQUEDA: [
    // Keyword genérica del rubro ferretero.
    'ferreterias',
    // Keyword orientada a depósitos de materiales.
    'depositos de materiales',
    // Keyword híbrida de depósitos y ferretería.
    'depositos y ferreteria',
    // Keyword asociada a bodegas de construcción.
    'bodegas de construccion',
    // Keyword asociada a centros ferreteros.
    'centro ferretero',
    // Keyword amplia sobre materiales para construcción.
    'materiales para construccion',
    // Keyword específica sobre cemento.
    'cemento',
    // Keyword específica sobre concreto.
    'concreto',
    // Keyword específica sobre concreto premezclado.
    'concreto premezclado',
    // Keyword específica sobre morteros.
    'morteros',
    // Keyword específica sobre mortero seco.
    'mortero seco',
    // Keyword específica sobre agregados de construcción.
    'agregados para construccion',
    // Keyword sobre arena y balasto.
    'arena y balasto',
    // Keyword sobre obra gris.
    'obra gris',
    // Keyword sobre hierro y cemento.
    'hierro y cemento',
    // Keyword sobre bloqueras.
    'bloqueras',
    // Keyword sobre ladrilleras.
    'ladrilleras',
    // Keyword sobre prefabricados de concreto.
    'prefabricados de concreto',
    // Keyword sobre distribuidoras de cemento.
    'distribuidoras de cemento'
  ],
*/
  // Agrupa la configuración de conexión a PostgreSQL.
  DB: {
    // Define el host de la base de datos con fallback a localhost.
    host:     process.env.DB_HOST     || 'localhost',
    // Define el puerto de la base de datos con fallback a 5432 y lo convierte a entero.
    port:     parseInt(process.env.DB_PORT || '5432'),
    // Define el nombre de la base de datos con fallback a `postgres`.
    database: process.env.DB_NAME     || 'postgres',
    // Define el usuario de la base de datos con fallback a `postgres`.
    user:     process.env.DB_USER     || 'postgres',
    // Define la contraseña de la base de datos con fallback simple.
    password: process.env.DB_PASSWORD || '1234',
  },

  // Define el directorio de salida para archivos generados por el scraper.
  OUTPUT_DIR: 'output',
  // Define el directorio base para los logs del sistema.
  LOG_DIR:    'logs',

};

// Exporta el objeto CONFIG para su reutilización en todos los módulos del proyecto.
module.exports = { CONFIG };