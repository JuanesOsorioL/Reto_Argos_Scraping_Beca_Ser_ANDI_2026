// Importa axios para realizar llamadas HTTP hacia los endpoints de RUES.
const axios = require('axios');
// Importa el wrapper que permite a axios trabajar con cookie jars.
const { wrapper } = require('axios-cookiejar-support');
// Importa la implementación de CookieJar para persistir cookies de sesión entre requests.
const { CookieJar } = require('tough-cookie');
// Importa la configuración central del proyecto.
const { CONFIG } = require('./config');
// Importa el helper que cifra payloads exactamente como lo espera el backend.
const { encryptPayload } = require('./crypto');
// Importa los builders de payload para cada tipo de operación soportada.
const {
  buildPayloadByRazon,
  buildPayloadByNit,
  buildPayloadByCamaraMatricula,
  buildPayloadDetalleById
} = require('./payloads');
// Importa utilidades de espera y jitter usadas por la lógica de reintentos.
const { sleep, randomJitter } = require('./utils');

// Crea una instancia de cliente RUES con soporte de cookies, headers y retries.
function createRuesClient(options = {}) {
  // Crea un cookie jar aislado para esta instancia del cliente.
  const jar = new CookieJar();

  // Crea la instancia base de axios y la envuelve para soportar cookie jar.
  const http = wrapper(axios.create({
    // Configura la URL base del backend real de RUES.
    baseURL: CONFIG.API_BASE_URL,
    // Configura el timeout global con posibilidad de override por opciones.
    timeout: options.timeoutMs ?? CONFIG.DEFAULT_TIMEOUT_MS,
    // Asocia el cookie jar a la instancia.
    jar,
    // Permite enviar y recibir cookies automáticamente.
    withCredentials: true,
    // Compone los headers por defecto del backend y los sobrescribe con headers personalizados si se envían.
    headers: {
      ...CONFIG.DEFAULT_HEADERS,
      ...(options.headers || {})
    }
  }));

  // Construye los headers dinámicos que acompañan cada request cifrada.
  function requestHeaders() {
    // Retorna headers alineados al frontend real de RUES.
    return {
      // Informa el origen esperado por el backend.
      Origin: CONFIG.FRONTEND_BASE_URL,
      // Informa el referer del frontend raíz.
      Referer: `${CONFIG.FRONTEND_BASE_URL}/`,
      // Usa el User-Agent indicado en opciones o el default de navegador simulado.
      'User-Agent': options.userAgent || CONFIG.DEFAULT_BROWSER_HEADERS['User-Agent'],
      // Usa el Accept-Language indicado en opciones o el default en español.
      'Accept-Language': options.acceptLanguage || CONFIG.DEFAULT_BROWSER_HEADERS['Accept-Language']
    };
  }

  // Inicializa la sesión visitando primero el frontend para obtener cookies y contexto de navegador.
  async function bootstrapSession() {
    // Ejecuta un GET directo al frontend base evitando la baseURL del backend.
    await http.get(CONFIG.FRONTEND_BASE_URL, {
      // Deshabilita temporalmente la baseURL de axios para usar la URL absoluta del frontend.
      baseURL: undefined,
      // Envía headers de navegador simulados y referer correspondiente.
      headers: {
        ...CONFIG.DEFAULT_BROWSER_HEADERS,
        Referer: CONFIG.FRONTEND_BASE_URL
      }
    });
  }

  // Envía un POST cifrado al path indicado y devuelve request + response para máxima trazabilidad.
  async function postEncrypted(path, payload) {
    // Cifra el payload y conserva tanto el texto plano como el cuerpo cifrado.
    const { plaintext, dataBody } = encryptPayload(payload);
    // Ejecuta el POST enviando el cuerpo en el formato exacto esperado por la API.
    const response = await http.post(path, { dataBody }, {
      // Adjunta los headers dinámicos compatibles con el frontend.
      headers: requestHeaders()
    });
    // Retorna una estructura rica que incluye request serializada y response recibida.
    return {
      request: {
        // Guarda el endpoint absoluto invocado para trazabilidad.
        endpoint: `${CONFIG.API_BASE_URL}${path}`,
        // Guarda el payload original en texto estructurado.
        plaintextPayload: payload,
        // Guarda el payload serializado antes del cifrado.
        serializedPayload: plaintext,
        // Guarda el string cifrado que realmente se envió en dataBody.
        encryptedDataBody: dataBody
      },
      // Guarda el cuerpo de la respuesta HTTP.
      response: response.data,
      // Guarda el status HTTP.
      status: response.status,
      // Guarda los headers de respuesta.
      headers: response.headers
    };
  }

  // Ejecuta una búsqueda por razón social/palabra clave usando el builder correspondiente.
  async function searchByRazon(razon, searchOptions = {}) {
    // Construye el payload de búsqueda por razón social.
    const payload = buildPayloadByRazon(razon, searchOptions);
    // Envía el payload cifrado al endpoint de búsqueda avanzada.
    return postEncrypted(CONFIG.BUSQUEDA_RM_PATH, payload);
  }

  // Ejecuta una búsqueda por NIT usando el builder correspondiente.
  async function searchByNit(nit, searchOptions = {}) {
    // Construye el payload de búsqueda por NIT.
    const payload = buildPayloadByNit(nit, searchOptions);
    // Envía el payload cifrado al endpoint de búsqueda avanzada.
    return postEncrypted(CONFIG.BUSQUEDA_RM_PATH, payload);
  }

  // Solicita el detalle de un expediente usando el identificador interno `id_rm`.
  async function getDetalleById(id) {
    // Construye el payload específico del endpoint de detalle.
    const payload = buildPayloadDetalleById(id);
    // Envía el request cifrado al endpoint de detalle.
    return postEncrypted(CONFIG.DETALLE_RM_PATH, payload);
  }

  // Solicita las facultades usando el código de cámara y la matrícula del registro.
  async function getFacultadesByCamaraMatricula(codigoCamara, matricula) {
    // Construye el payload mínimo requerido para el endpoint extendido.
    const payload = buildPayloadByCamaraMatricula(codigoCamara, matricula);
    // Envía el request cifrado al endpoint de facultades.
    return postEncrypted(CONFIG.FACULTADES_PATH, payload);
  }

  // Solicita la información de propietario/establecimiento usando código de cámara y matrícula.
  async function getPropietarioEstByCamaraMatricula(codigoCamara, matricula) {
    // Construye el payload mínimo requerido para el endpoint de propietario.
    const payload = buildPayloadByCamaraMatricula(codigoCamara, matricula);
    // Envía el request cifrado al endpoint de propietario/establecimiento.
    return postEncrypted(CONFIG.PROPIETARIO_EST_PATH, payload);
  }

  // Ejecuta una función asíncrona con reintentos automáticos y backoff exponencial.
  async function withRetries(fn, retryOptions = {}) {
    // Determina la cantidad máxima de reintentos desde opciones o config por defecto.
    const maxRetries = retryOptions.maxRetries ?? CONFIG.DEFAULT_MAX_RETRIES;
    // Determina la base del backoff exponencial desde opciones o config por defecto.
    const baseDelayMs = retryOptions.retryBaseMs ?? CONFIG.DEFAULT_RETRY_BASE_MS;

    // Inicializa una referencia para el último error capturado.
    let lastError = null;

    // Recorre desde el intento 0 hasta el máximo configurado inclusive.
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        // Intenta ejecutar la función y retorna inmediatamente si resulta exitosa.
        return await fn(attempt);
      } catch (error) {
        // Guarda el error capturado para re-lanzarlo si finalmente se agotan los intentos.
        lastError = error;
        // Extrae el status HTTP si existe.
        const status = error?.response?.status;
        // Determina si el error es transitorio/reintentable según status o ausencia de él.
        const retriable = status === 429 || status === 408 || status === 503 || status === 502 || !status;

        // Si el error no es reintentable o ya se agotaron los intentos, relanza el error inmediatamente.
        if (!retriable || attempt === maxRetries) {
          throw error;
        }

        // Calcula la espera usando backoff exponencial más jitter aleatorio.
        const waitMs = baseDelayMs * Math.pow(2, attempt) + randomJitter(500);
        // Espera el tiempo calculado antes del siguiente intento.
        await sleep(waitMs);
      }
    }

    // Como fallback defensivo, relanza el último error registrado.
    throw lastError;
  }

  // Retorna la API pública de esta instancia del cliente.
  return {
    // Expone el cookie jar por si se necesita inspección o reutilización externa.
    jar,
    // Expone la instancia axios ya configurada.
    http,
    // Expone el método de bootstrap de sesión.
    bootstrapSession,
    // Expone el método genérico de POST cifrado.
    postEncrypted,
    // Expone la búsqueda por razón social.
    searchByRazon,
    // Expone la búsqueda por NIT.
    searchByNit,
    // Expone la consulta de detalle por id.
    getDetalleById,
    // Expone la consulta de facultades.
    getFacultadesByCamaraMatricula,
    // Expone la consulta de propietario/establecimiento.
    getPropietarioEstByCamaraMatricula,
    // Expone el helper de reintentos para requests o funciones externas.
    withRetries
  };
}

// Exporta el factory del cliente para uso por el resto del proyecto.
module.exports = { createRuesClient };