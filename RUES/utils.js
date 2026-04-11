// Define un helper asíncrono que espera una cantidad de milisegundos antes de resolver.
function sleep(ms) {
  // Retorna una promesa que se resuelve mediante `setTimeout` tras el tiempo indicado.
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Genera un valor aleatorio entero desde 0 hasta `max - 1` para jitter de reintentos.
function randomJitter(max = 250) {
  // Calcula el entero aleatorio multiplicando `Math.random()` por `max`.
  return Math.floor(Math.random() * max);
}

// Sanitiza un fragmento de texto para poder usarlo en nombres de archivo sin caracteres conflictivos.
function sanitizeFileFragment(value) {
  // Reemplaza cualquier secuencia no alfanumérica, guion o guion bajo por `_`.
  return String(value).replace(/[^a-zA-Z0-9_-]+/g, '_');
}

// Convierte fechas RUES en formato `YYYYMMDD` a `YYYY-MM-DD` con tolerancia a sentinels y formatos ya válidos.
function parseDateYYYYMMDD(value) {
  // Normaliza el valor a string limpio para validarlo.
  const s = String(value || '').trim();
  // Retorna null si está vacío o coincide con fechas sentinel usadas por RUES.
  if (!s || s === '99991231' || s === '0' || s === '00000000') return null;
  // Si viene como ocho dígitos, reordena a formato ISO básico con guiones.
  if (/^\d{8}$/.test(s)) return `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}`;
  // Si ya viene en formato YYYY-MM-DD, lo retorna tal cual.
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  // Para cualquier otro formato no reconocido, retorna null.
  return null;
}

// Limpia un bloque HTML y lo transforma en texto plano legible.
function cleanHtmlToText(html) {
  // Si el valor es null o undefined, retorna cadena vacía.
  if (html == null) return '';
  // Encadena múltiples reemplazos para limpiar HTML y entidades comunes.
  return String(html)
    // Convierte saltos de línea HTML en saltos reales de texto.
    .replace(/<br\s*\/?>/gi, '\n')
    // Convierte `&nbsp;` a espacio normal.
    .replace(/&nbsp;/gi, ' ')
    // Convierte `&amp;` a ampersand real.
    .replace(/&amp;/gi, '&')
    // Convierte `&quot;` a comilla doble.
    .replace(/&quot;/gi, '"')
    // Convierte `&#39;` a comilla simple/apóstrofe.
    .replace(/&#39;/gi, "'")
    // Elimina cualquier tag HTML restante.
    .replace(/<[^>]+>/g, ' ')
    // Elimina retornos de carro.
    .replace(/\r/g, '')
    // Colapsa espacios y tabs repetidos.
    .replace(/[ \t]+/g, ' ')
    // Limpia espacios al inicio de línea tras saltos.
    .replace(/\n[ \t]+/g, '\n')
    // Reduce bloques de muchos saltos a dobles saltos.
    .replace(/\n{3,}/g, '\n\n')
    // Recorta espacios al inicio y fin del texto resultante.
    .trim();
}

// Normaliza teléfonos colombianos a un formato consistente y utilizable.
function normalizarTelefono(tel) {
  // Si no hay teléfono, retorna null.
  if (!tel) return null;
  // Extrae únicamente los dígitos del valor recibido.
  const digits = String(tel).replace(/\D/g, '');
  // Si no quedan dígitos, retorna null.
  if (digits.length === 0) return null;
  // Si ya trae prefijo 57 y tiene longitud 12, lo devuelve con `+` al inicio.
  if (digits.startsWith('57') && digits.length === 12) return `+${digits}`;
  // Si parece un celular colombiano de 10 dígitos comenzando en 3, le antepone `+57`.
  if (digits.startsWith('3') && digits.length === 10) return `+57${digits}`;
  // En cualquier otro caso retorna el valor original trimmeado o null si quedó vacío.
  return String(tel).trim() || null;
}

// Define el conjunto de palabras de alta afinidad para score Argos.
const PALABRAS_ALTA = [
  // Incluye variantes ligadas al rubro ferretero y materiales de construcción.
  'ferreter', 'deposito materiales', 'materiales construccion',
  // Incluye términos de cemento, concreto, mortero y prefabricados.
  'cemento', 'concreto', 'mortero', 'prefabricado', 'bloquera',
  // Incluye términos de ladrilleras, distribuidores y agregados.
  'ladrillera', 'distribuidor cemento', 'obra gris', 'hierro cemento',
  // Incluye agregados y centros ferreteros.
  'agregados', 'ferredeposito', 'centro ferretero',
];
// Define el conjunto de palabras de afinidad media para score Argos.
const PALABRAS_MEDIA  = ['construccion', 'deposito', 'materiales', 'hierro', 'hardware'];
// Define palabras negativas que restan score por pertenecer a rubros no objetivo.
const PALABRAS_NEG    = ['restaurante', 'salon belleza', 'spa', 'medico', 'farmacia', 'ropa', 'hotel'];
// Define CIIUs directamente relevantes para ferreterías y construcción.
const CIIU_RELEVANTES = ['4752', '4753', '4659', '4690', '2394', '2395', '2310', '1610', '2399'];

// Calcula el score Argos combinando texto comercial y CIIU principal.
function calcularScoreArgos(razon, ciiu, descripcion = '') {
  // Construye un texto unificado en minúsculas para evaluación por palabras clave.
  const texto = `${razon || ''} ${descripcion || ''}`.toLowerCase();
  // Inicializa el score en cero.
  let score   = 0;

  // Suma 3 puntos por cada palabra de alta afinidad encontrada en el texto.
  for (const p of PALABRAS_ALTA)  if (texto.includes(p)) score += 3;
  // Suma 2 puntos por cada palabra de afinidad media encontrada en el texto.
  for (const p of PALABRAS_MEDIA) if (texto.includes(p)) score += 2;
  // Resta 5 puntos por cada palabra negativa encontrada en el texto.
  for (const p of PALABRAS_NEG)   if (texto.includes(p)) score -= 5;
  // Suma 5 puntos adicionales si el CIIU pertenece a la lista relevante.
  if (ciiu && CIIU_RELEVANTES.includes(String(ciiu))) score += 5;

  // Retorna el score calculado junto con la bandera de aprobación según threshold >= 2.
  return { score, aprobado_argos: score >= 2 };
}

// Normaliza un registro crudo devuelto por el endpoint de búsqueda.
function normalizeBusquedaRecord(r) {
  // Si no existe el registro, retorna null para poder filtrarlo luego.
  if (!r) return null;
  // Retorna una estructura consistente con los campos relevantes del search.
  return {
    // Conserva el identificador interno del registro mercantil.
    id_rm:                r.id_rm                ?? null,
    // Conserva el tipo de documento reportado por RUES.
    tipo_documento:       r.tipo_documento        ?? null,
    // Conserva el NIT reportado por RUES.
    nit:                  r.nit                   ?? null,
    // Conserva el dígito de verificación si existe.
    dv:                   r.dv                    ?? null,
    // Conserva la razón social.
    razon_social:         r.razon_social          ?? null,
    // Conserva la sigla si existe.
    sigla:                r.sigla                 ?? null,
    // Conserva el código de cámara.
    cod_camara:           r.cod_camara            ?? null,
    // Conserva el nombre de la cámara.
    nom_camara:           r.nom_camara            ?? null,
    // Conserva la matrícula mercantil.
    matricula:            r.matricula             ?? null,
    // Conserva la organización jurídica.
    organizacion_juridica:r.organizacion_juridica ?? null,
    // Conserva el estado de la matrícula.
    estado_matricula:     r.estado_matricula      ?? null,
    // Conserva el último año renovado.
    ultimo_ano_renovado:  r.ultimo_ano_renovado   ?? null,
    // Conserva la categoría de matrícula.
    categoria:            r.categoria             ?? null,
    // Conserva el registro raw completo sin excepciones.
    raw: r
  };
}

// Normaliza la estructura de detalle devuelta por `DetalleRM`.
function normalizeDetalleRecord(registros) {
  // Si la respuesta no existe, retorna null.
  if (!registros) return null;
  // Retorna el objeto normalizado de detalle con transformación de fechas y teléfonos.
  return {
    // Conserva el id interno de detalle si viene presente.
    id:                             registros.id                             ?? null,
    // Conserva el código de cámara.
    cod_camara:                     registros.cod_camara                     ?? null,
    // Conserva la descripción/nombre de cámara.
    camara:                         registros.camara                         ?? null,
    // Conserva la matrícula.
    matricula:                      registros.matricula                      ?? null,
    // Conserva la razón social.
    razon_social:                   registros.razon_social                   ?? null,
    // Conserva la sigla.
    sigla:                          registros.sigla                          ?? null,
    // Conserva la clase de identificación.
    clase_identificacion:           registros.clase_identificacion           ?? null,
    // Conserva el número principal de identificación.
    numero_identificacion:          registros.numero_identificacion          ?? null,
    // Conserva el número alterno de identificación.
    numero_identificacion_2:        registros.numero_identificacion_2        ?? null,
    // Conserva el dígito de verificación.
    dv:                             registros.dv                             ?? null,
    // Conserva la dirección comercial.
    dir_comercial:                  registros.dir_comercial                  ?? null,
    // Conserva el municipio comercial.
    mun_comercial:                  registros.mun_comercial                  ?? null,
    // Normaliza el teléfono comercial 1.
    tel_com_1:                      normalizarTelefono(registros.tel_com_1),
    // Normaliza el teléfono comercial 2.
    tel_com_2:                      normalizarTelefono(registros.tel_com_2),
    // Normaliza el teléfono comercial 3.
    tel_com_3:                      normalizarTelefono(registros.tel_com_3),
    // Conserva el email comercial.
    email_com:                      registros.email_com                      ?? null,
    // Conserva la dirección fiscal.
    dir_fiscal:                     registros.dir_fiscal                     ?? null,
    // Conserva el municipio fiscal.
    mun_fiscal:                     registros.mun_fiscal                     ?? null,
    // Normaliza el teléfono fiscal 1.
    tel_fiscal_1:                   normalizarTelefono(registros.tel_fiscal_1),
    // Normaliza el teléfono fiscal 2.
    tel_fiscal_2:                   normalizarTelefono(registros.tel_fiscal_2),
    // Normaliza el teléfono fiscal 3.
    tel_fiscal_3:                   normalizarTelefono(registros.tel_fiscal_3),
    // Conserva el email fiscal.
    email_fiscal:                   registros.email_fiscal                   ?? null,
    // Conserva el CIIU principal.
    cod_ciiu_act_econ_pri:          registros.cod_ciiu_act_econ_pri          ?? null,
    // Conserva la descripción del CIIU principal.
    desc_ciiu_act_econ_pri:         registros.desc_ciiu_act_econ_pri         ?? null,
    // Conserva el CIIU secundario.
    cod_ciiu_act_econ_sec:          registros.cod_ciiu_act_econ_sec          ?? null,
    // Conserva la descripción del CIIU secundario.
    desc_ciiu_act_econ_sec:         registros.desc_ciiu_act_econ_sec         ?? null,
    // Conserva CIIU 3.
    ciiu3:                          registros.ciiu3                          ?? null,
    // Conserva descripción de CIIU 3.
    desc_ciiu3:                     registros.desc_ciiu3                     ?? null,
    // Conserva CIIU 4.
    ciiu4:                          registros.ciiu4                          ?? null,
    // Conserva descripción de CIIU 4.
    desc_ciiu4:                     registros.desc_ciiu4                     ?? null,
    // Normaliza la fecha de matrícula.
    fecha_matricula:                parseDateYYYYMMDD(registros.fecha_matricula),
    // Normaliza la fecha de renovación.
    fecha_renovacion:               parseDateYYYYMMDD(registros.fecha_renovacion),
    // Conserva el último año renovado.
    ultimo_ano_renovado:            registros.ultimo_ano_renovado            ?? null,
    // Normaliza la fecha de vigencia.
    fecha_vigencia:                 parseDateYYYYMMDD(registros.fecha_vigencia),
    // Normaliza la fecha de cancelación.
    fecha_cancelacion:              parseDateYYYYMMDD(registros.fecha_cancelacion),
    // Conserva el motivo de cancelación.
    motivo_cancelacion:             registros.motivo_cancelacion             ?? null,
    // Conserva el código del tipo de sociedad.
    cod_tipo_sociedad:              registros.cod_tipo_sociedad              ?? null,
    // Conserva la descripción del tipo de sociedad.
    tipo_sociedad:                  registros.tipo_sociedad                  ?? null,
    // Conserva la organización jurídica.
    organizacion_juridica:          registros.organizacion_juridica          ?? null,
    // Conserva la categoría de matrícula.
    categoria_matricula:            registros.categoria_matricula            ?? null,
    // Conserva el indicador de emprendimiento social.
    indicador_emprendimiento_social:registros.indicador_emprendimiento_social?? null,
    // Conserva el indicador de extinción de dominio.
    extincion_dominio:              registros.extincion_dominio              ?? null,
    // Conserva el estado de la matrícula/expediente.
    estado:                         registros.estado                         ?? null,
    // Normaliza la fecha de actualización.
    fecha_actualizacion:            parseDateYYYYMMDD(registros.fecha_actualizacion),
    // Conserva el control de inactivación SIPREF.
    control_inactivacion_sipref:    registros.control_inactivacion_sipref    ?? null,
    // Conserva el indicador ley 1780.
    indicador_ley_1780:             registros.indicador_ley_1780             ?? null,
    // Conserva el indicador empresa BIC.
    indicador_empresa_bic:          registros.indicador_empresa_bic          ?? null,
    // Conserva el indicador de transporte.
    indicador_transporte:           registros.indicador_transporte           ?? null,
    // Conserva la URL de venta de certificados.
    url_venta_certificados:         registros.url_venta_certificados         ?? null,
    // Conserva el objeto raw completo del detalle.
    raw: registros
  };
}

// Normaliza la respuesta del endpoint de propietarios/establecimientos.
function normalizePropietarioResponse(resp) {
  // Retorna una estructura consistente de metadata y arreglo de registros normalizados.
  return {
    // Conserva el código de respuesta si existe.
    code:            resp?.code            ?? null,
    // Conserva el mensaje de respuesta si existe.
    message:         resp?.message         ?? null,
    // Conserva la cantidad de registros reportada o cero por defecto.
    cant_Registros:  resp?.cant_Registros  ?? 0,
    // Conserva la fecha de respuesta si existe.
    fecha_respuesta: resp?.fecha_respuesta ?? null,
    // Conserva la hora de respuesta si existe.
    hora_respuesta:  resp?.hora_respuesta  ?? null,
    // Si `registros` es arreglo, lo mapea a una estructura saneada; si no, devuelve arreglo vacío.
    registros: Array.isArray(resp?.registros) ? resp.registros.map(r => ({
      // Conserva el código de clase de identificación.
      CODIGO_CLASE_IDENTIFICACION:  r.CODIGO_CLASE_IDENTIFICACION  ?? null,
      // Conserva el número de identificación.
      NUMERO_IDENTIFICACION:        r.NUMERO_IDENTIFICACION         ?? null,
      // Conserva el dígito de verificación.
      DIGITO_VERIFICACION:          r.DIGITO_VERIFICACION           ?? null,
      // Conserva la razón social del propietario.
      RAZON_SOCIAL:                 r.RAZON_SOCIAL                  ?? null,
      // Conserva la sigla del propietario.
      SIGLA:                        r.SIGLA                         ?? null,
      // Conserva el código de cámara del propietario.
      CODIGO_CAMARA:                r.CODIGO_CAMARA                 ?? null,
      // Conserva la descripción de cámara.
      DESC_CAMARA:                  r.DESC_CAMARA                   ?? null,
      // Conserva la matrícula del propietario.
      MATRICULA:                    r.MATRICULA                     ?? null,
      // Conserva el código del tipo de sociedad.
      CODIGO_TIPO_SOCIEDAD:         r.CODIGO_TIPO_SOCIEDAD          ?? null,
      // Conserva la descripción del tipo de sociedad.
      DESC_TIPO_SOCIEDAD:           r.DESC_TIPO_SOCIEDAD            ?? null,
      // Conserva el código de organización jurídica.
      CODIGO_ORGANIZACION_JURIDICA: r.CODIGO_ORGANIZACION_JURIDICA  ?? null,
      // Conserva la descripción de organización jurídica.
      DESC_ORGANIZACION_JURIDICA:   r.DESC_ORGANIZACION_JURIDICA    ?? null,
      // Conserva el código de categoría de matrícula.
      CODIGO_CATEGORIA_MATRICULA:   r.CODIGO_CATEGORIA_MATRICULA    ?? null,
      // Conserva la categoría de matrícula.
      CATEGORIA_MATRICULA:          r.CATEGORIA_MATRICULA           ?? null,
      // Conserva el código de estado de matrícula.
      CODIGO_ESTADO_MATRICULA:      r.CODIGO_ESTADO_MATRICULA       ?? null,
      // Conserva la descripción de estado de matrícula.
      DESC_ESTADO_MATRICULA:        r.DESC_ESTADO_MATRICULA         ?? null,
      // Normaliza la fecha de matrícula.
      FECHA_MATRICULA:              parseDateYYYYMMDD(r.FECHA_MATRICULA),
      // Normaliza la fecha de renovación.
      FECHA_RENOVACION:             parseDateYYYYMMDD(r.FECHA_RENOVACION),
      // Conserva el último año renovado.
      ULTIMO_ANO_RENOVADO:          r.ULTIMO_ANO_RENOVADO           ?? null,
      // Conserva el registro raw completo del propietario.
      raw: r
    })) : []
  };
}

// Exporta todas las utilidades del módulo.
module.exports = {
  // Exporta el helper de espera asíncrona.
  sleep,
  // Exporta el helper de jitter aleatorio.
  randomJitter,
  // Exporta el helper de sanitización de fragmentos para archivo.
  sanitizeFileFragment,
  // Exporta el normalizador de fechas RUES.
  parseDateYYYYMMDD,
  // Exporta el limpiador de HTML a texto plano.
  cleanHtmlToText,
  // Exporta el normalizador de teléfonos.
  normalizarTelefono,
  // Exporta el cálculo del score Argos.
  calcularScoreArgos,
  // Exporta el normalizador de registros de búsqueda.
  normalizeBusquedaRecord,
  // Exporta el normalizador de detalle.
  normalizeDetalleRecord,
  // Exporta el normalizador de propietarios.
  normalizePropietarioResponse,
};