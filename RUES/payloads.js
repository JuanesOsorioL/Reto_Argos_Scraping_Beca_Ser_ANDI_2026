// Importa la configuración central del proyecto para reutilizar límites y offsets por defecto.
const { CONFIG } = require('./config');

// Construye la estructura base del payload para el endpoint de búsqueda de registro mercantil.
function baseBusquedaRmPayload() {
  // Retorna un objeto con todos los campos esperados por el endpoint inicializados.
  return {
    // Campo para búsqueda por razón social o palabra clave.
    Razon: null,
    // Campo para búsqueda por NIT.
    Nit: null,
    // Campo para filtrar por departamento.
    Dpto: null,
    // Campo para filtrar por código de cámara.
    Cod_Camara: null,
    // Campo de matrícula mantenido por compatibilidad aunque no se use en esta búsqueda base.
    Matricula: null,
    // Offset inicial de paginación tomado desde la configuración por defecto.
    Offset: CONFIG.DEFAULT_OFFSET,
    // Límite de resultados tomado desde la configuración por defecto.
    Limit: CONFIG.DEFAULT_LIMIT
  };
}

// Construye un payload de búsqueda usando razón social o palabra clave.
function buildPayloadByRazon(razon, options = {}) {
  // Valida que exista una razón social y que no quede vacía al hacer trim.
  if (!razon || !String(razon).trim()) {
    // Lanza un error explícito si el dato obligatorio no fue enviado.
    throw new Error('La razón social / palabra clave es obligatoria');
  }

  // Retorna el payload final combinando la base con filtros y paginación opcionales.
  return {
    // Expande la estructura base para mantener el shape esperado por el endpoint.
    ...baseBusquedaRmPayload(),
    // Asigna la razón social normalizada a string sin espacios extremos.
    Razon: String(razon).trim(),
    // Usa el departamento recibido o null si no fue enviado.
    Dpto: options.departamento ?? null,
    // Usa el código de cámara recibido o null si no fue enviado.
    Cod_Camara: options.codCamara ?? null,
    // Usa offset explícito si es entero; si no, aplica el default configurado.
    Offset: Number.isInteger(options.offset) ? options.offset : CONFIG.DEFAULT_OFFSET,
    // Usa limit explícito si es entero; si no, aplica el default configurado.
    Limit: Number.isInteger(options.limit) ? options.limit : CONFIG.DEFAULT_LIMIT
  };
}

// Construye un payload de búsqueda usando NIT.
function buildPayloadByNit(nit, options = {}) {
  // Valida que el NIT exista y no quede vacío tras convertirlo a texto.
  if (nit === undefined || nit === null || String(nit).trim() === '') {
    // Lanza un error si el NIT es obligatorio y no fue suministrado.
    throw new Error('El NIT es obligatorio');
  }

  // Limpia el NIT dejando únicamente caracteres numéricos.
  const normalizedNit = String(nit).replace(/\D/g, '');
  // Verifica que el NIT normalizado conserve al menos un dígito válido.
  if (!normalizedNit) {
    // Lanza error si el input no contenía dígitos útiles.
    throw new Error('El NIT no contiene dígitos válidos');
  }

  // Retorna el payload final combinando la base con el NIT y filtros opcionales.
  return {
    // Expande la estructura base para conservar todas las llaves esperadas por el endpoint.
    ...baseBusquedaRmPayload(),
    // Envía el NIT ya limpio convertido a número.
    Nit: Number(normalizedNit),
    // Usa el departamento recibido o null si no fue enviado.
    Dpto: options.departamento ?? null,
    // Usa el código de cámara recibido o null si no fue enviado.
    Cod_Camara: options.codCamara ?? null,
    // Usa offset explícito si es entero; en caso contrario aplica el default.
    Offset: Number.isInteger(options.offset) ? options.offset : CONFIG.DEFAULT_OFFSET,
    // Usa limit explícito si es entero; en caso contrario aplica el default.
    Limit: Number.isInteger(options.limit) ? options.limit : CONFIG.DEFAULT_LIMIT
  };
}

// Construye el payload para endpoints que requieren código de cámara y matrícula.
function buildPayloadByCamaraMatricula(codigoCamara, matricula) {
  // Valida que el código de cámara exista y no quede vacío al hacer trim.
  if (!codigoCamara || !String(codigoCamara).trim()) {
    // Lanza error si falta el código de cámara requerido.
    throw new Error('codigo_camara es obligatorio');
  }
  // Valida que la matrícula exista y no quede vacía al hacer trim.
  if (!matricula || !String(matricula).trim()) {
    // Lanza error si falta la matrícula requerida.
    throw new Error('matricula es obligatoria');
  }

  // Retorna el payload mínimo esperado por los endpoints extendidos.
  return {
    // Normaliza y asigna el código de cámara como string limpio.
    codigo_camara: String(codigoCamara).trim(),
    // Normaliza y asigna la matrícula como string limpia.
    matricula: String(matricula).trim()
  };
}

// Construye el payload para consultar detalle usando el identificador interno del registro.
function buildPayloadDetalleById(id) {
  // Valida que el id exista y no quede vacío al convertirlo a string.
  if (id === undefined || id === null || String(id).trim() === '') {
    // Lanza error si falta el identificador obligatorio para DetalleRM.
    throw new Error('id es obligatorio para DetalleRM');
  }
  // Retorna la forma exacta esperada por el endpoint de detalle.
  return { id: String(id).trim() };
}

// Exporta todos los builders de payload del módulo.
module.exports = {
  // Exporta la estructura base reutilizable para búsquedas.
  baseBusquedaRmPayload,
  // Exporta el builder de búsqueda por razón social.
  buildPayloadByRazon,
  // Exporta el builder de búsqueda por NIT.
  buildPayloadByNit,
  // Exporta el builder para endpoints extendidos por cámara y matrícula.
  buildPayloadByCamaraMatricula,
  // Exporta el builder para DetalleRM por id.
  buildPayloadDetalleById
};