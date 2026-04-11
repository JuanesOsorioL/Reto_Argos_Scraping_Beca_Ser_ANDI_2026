// Importa el factory del cliente principal de RUES para exponerlo como API pública.
const { createRuesClient } = require('./client');
// Importa la función de cifrado de payloads para exponerla externamente.
const { encryptPayload } = require('./crypto');
// Importa los builders de payload para que terceros puedan construir requests válidos sin duplicar lógica.
const {
  baseBusquedaRmPayload,
  buildPayloadByRazon,
  buildPayloadByNit,
  buildPayloadByCamaraMatricula,
  buildPayloadDetalleById
} = require('./payloads');
// Importa el pipeline principal para exponer la orquestación programática.
const { runSearchPipeline } = require('./pipeline');

// Exporta la superficie pública del módulo/package.
module.exports = {
  // Expone el factory del cliente HTTP listo para crear sesiones y hacer consultas.
  createRuesClient,
  // Expone el helper de cifrado AES compatible con el frontend.
  encryptPayload,
  // Expone el builder base de búsqueda para reutilización avanzada.
  baseBusquedaRmPayload,
  // Expone el builder de búsqueda por razón social.
  buildPayloadByRazon,
  // Expone el builder de búsqueda por NIT.
  buildPayloadByNit,
  // Expone el builder por cámara y matrícula para endpoints extendidos.
  buildPayloadByCamaraMatricula,
  // Expone el builder por id usado por DetalleRM.
  buildPayloadDetalleById,
  // Expone el pipeline orquestado de búsqueda y detalle.
  runSearchPipeline
};