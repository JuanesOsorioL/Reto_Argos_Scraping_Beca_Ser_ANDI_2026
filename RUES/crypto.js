// Importa la librería CryptoJS para cifrado AES.
const CryptoJS = require('crypto-js');
// Importa la configuración central para acceder a la llave AES.
const { CONFIG } = require('./config');

/**
 * Replica exacta del frontend hallada en el bundle:
 * CryptoJS.AES.encrypt(JSON.stringify(obj), AES_KEY).toString()
 */

// Declara una función que cifra un payload plano replicando exactamente la estrategia del frontend.
function encryptPayload(payload) {
  // Verifica que el payload exista, sea objeto y no sea un arreglo.
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
    // Lanza un TypeError si el valor recibido no cumple el contrato esperado por esta función.
    throw new TypeError('payload debe ser un objeto plano');
  }

  // Serializa el payload a JSON para cifrar la representación textual exacta del objeto.
  const plaintext = JSON.stringify(payload);
  // Cifra el JSON serializado con AES usando la llave configurada y retorna la cadena cifrada.
  const dataBody = CryptoJS.AES.encrypt(plaintext, CONFIG.AES_KEY).toString();

  // Retorna tanto el texto plano como el cuerpo cifrado para trazabilidad y debugging.
  return { plaintext, dataBody };
}

// Exporta la función de cifrado para uso por el cliente HTTP.
module.exports = { encryptPayload };