/**
 * pipeline.js — Pipeline RUES con logging completo paso a paso.
 *
 * Flujo por keyword:
 *   1. BusquedaAvanzadaRM  → guarda en BD + JSONL inmediatamente
 *   2. DetalleRM           → guarda en BD + JSONL inmediatamente
 *   3. ConsultFacultades   → guarda en BD + JSONL (si extended)
 *   4. PropietarioEst      → guarda en BD + JSONL (si extended)
 *
 * Fixes aplicados:
 *   - Timeout reducido para propietario (15s, no 60s) — esos endpoints son lentos
 *   - raw_response se pasa explícitamente a cada insert de BD
 *   - JSONL de búsquedas se escribe aquí, no en main.js
 */

// Importa `fs` para escritura incremental de archivos JSONL.
const fs   = require('fs');
// Importa `path` para resolver directorios de salida de forma segura.
const path = require('path');
// Importa la configuración global del proyecto.
const { CONFIG } = require('./config');
// Importa el logger centralizado para observabilidad del pipeline.
const { logger } = require('./logger');
// Importa utilidades de espera, normalización, limpieza y scoring.
const {
  sleep,
  normalizeBusquedaRecord,
  normalizeDetalleRecord,
  cleanHtmlToText,
  normalizePropietarioResponse,
  calcularScoreArgos,
} = require('./utils');
// Importa la capa de persistencia PostgreSQL para guardar resultados y errores.
const db = require('./db');

// Define un timeout más agresivo para endpoints extendidos que suelen ser más lentos o inestables.
const TIMEOUT_EXTENDIDO_MS = 15000;

// Procesa una colección usando una función worker con concurrencia controlada.
async function processWithConcurrency(items, worker, options = {}) {
  // Calcula la concurrencia efectiva asegurando un mínimo de 1.
  const concurrency = Math.max(1, Number(options.concurrency ?? CONFIG.DEFAULT_CONCURRENCY));
  // Calcula el delay efectivo asegurando que no sea negativo.
  const delayMs     = Math.max(0, Number(options.delayMs ?? CONFIG.DEFAULT_DELAY_MS));
  // Preasigna el arreglo de resultados para conservar el orden original.
  const results     = new Array(items.length);
  // Inicializa el cursor compartido entre workers.
  let cursor        = 0;

  // Define el worker interno que irá tomando elementos hasta agotar la colección.
  async function runWorker() {
    // Mantiene el worker activo hasta quedarse sin índices pendientes.
    while (true) {
      // Toma el índice actual y luego incrementa el cursor global.
      const idx = cursor++;
      // Si el índice se sale del arreglo, termina este worker.
      if (idx >= items.length) break;
      // Si no es el primer elemento global y hay delay configurado, espera antes de ejecutar.
      if (idx > 0 && delayMs > 0) await sleep(delayMs);
      // Ejecuta el worker real sobre el elemento actual y guarda el resultado en su posición.
      results[idx] = await worker(items[idx], idx);
    }
  }

  // Lanza la cantidad de workers indicada y espera a que todos finalicen.
  await Promise.all(Array.from({ length: concurrency }, () => runWorker()));
  // Retorna los resultados en el mismo orden que la colección de entrada.
  return results;
}

// Agrega un objeto serializado como una línea JSONL al archivo indicado.
function appendJsonl(filePath, obj) {
  try {
    // Garantiza que exista el directorio padre del archivo a escribir.
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    // Escribe el objeto serializado como una sola línea JSON más salto de línea.
    fs.appendFileSync(filePath, JSON.stringify(obj) + '\n', 'utf8');
  } catch (e) {
    // Registra una advertencia si falla la escritura del archivo JSONL.
    logger.warn(`[JSONL] Error escribiendo: ${e.message}`);
  }
}

// Ejecuta el pipeline completo de búsqueda y, opcionalmente, detalle y endpoints extendidos.
async function runSearchPipeline(client, mode, value, options = {}, run_id, procesados = new Set(), jsonlPaths = {}) {
  // Registra el inicio de búsqueda para la keyword o valor actual.
  logger.info(`[BUSQUEDA] keyword="${value}" modo=${mode}`);

  // Construye las opciones específicas del endpoint de búsqueda.
  const searchOptions = {
    // Propaga el departamento si viene configurado; si no, usa null.
    departamento: options.departamento ?? null,
    // Propaga el código de cámara si viene configurado; si no, usa null.
    codCamara:    options.codCamara    ?? null,
    // Propaga offset solo si es entero válido.
    offset:       Number.isInteger(options.offset)      ? options.offset      : undefined,
    // Propaga el limit del endpoint de búsqueda solo si es entero válido.
    limit:        Number.isInteger(options.searchLimit) ? options.searchLimit : undefined,
  };

  // Declara una variable que contendrá la respuesta raw del endpoint de búsqueda.
  let searchResult;
  try {
    // Ejecuta la búsqueda por razón o por NIT según el modo seleccionado.
    searchResult = mode === 'razon'
      ? await client.searchByRazon(value, searchOptions)
      : await client.searchByNit(value, searchOptions);
  } catch (e) {
    // Registra el fallo de búsqueda a nivel de logs.
    logger.error(`[BUSQUEDA] Falló "${value}": ${e.message}`);
    // Si existe JSONL de errores, persiste inmediatamente una línea con el incidente.
    if (jsonlPaths.errores) appendJsonl(jsonlPaths.errores, { tipo: 'busqueda_error', run_id, keyword: value, error: e.message, ts: new Date().toISOString() });
    // Retorna una estructura consistente incluso en caso de error para no romper consumidores.
    return { mode, value, executedAt: new Date().toISOString(), search: { raw: null, normalized: [], selectedCount: 0 }, error: e.message };
  }

  // Extrae el arreglo raw de registros del search o usa arreglo vacío si no está presente.
  const rawRegistros     = Array.isArray(searchResult?.response?.registros) ? searchResult.response.registros : [];
  // Normaliza cada registro de búsqueda y descarta nulos.
  const normalizedSearch = rawRegistros.map(normalizeBusquedaRecord).filter(Boolean);
  // Toma la cantidad reportada por el backend o usa el tamaño real del arreglo como fallback.
  const cantReportados   = searchResult?.response?.cant_registros ?? rawRegistros.length;

  // Registra cuántos resultados fueron reportados y cuántos llegaron realmente en el array.
  logger.ok(`[BUSQUEDA] "${value}" → ${cantReportados} reportados, ${rawRegistros.length} en array`);

  // Inicializa el contador de inserts exitosos de búsqueda en base de datos.
  let busqIns = 0;
  // Recorre los resultados normalizados para persistirlos uno por uno.
  for (const r of normalizedSearch) {
    // Inserta el registro de búsqueda en PostgreSQL.
    const ok = await db.insertarBusqueda(run_id, value, r);
    // Si la inserción fue efectiva, incrementa el contador.
    if (ok) busqIns++;

    // Si existe ruta JSONL de búsqueda, escribe una línea inmediata con el registro resumido.
    if (jsonlPaths.busqueda) {
      appendJsonl(jsonlPaths.busqueda, {
        // Etiqueta el tipo de evento para facilitar análisis posterior.
        tipo:            'busqueda',
        // Guarda el identificador del run.
        run_id,
        // Guarda la keyword de origen.
        keyword:         value,
        // Guarda el timestamp de extracción.
        fecha_extraccion: new Date().toISOString(),
        // Guarda el id interno RUES.
        id_rm:           r.id_rm,
        // Guarda el NIT.
        nit:             r.nit,
        // Guarda la razón social.
        razon_social:    r.razon_social,
        // Guarda el código de cámara.
        cod_camara:      r.cod_camara,
        // Guarda el nombre de cámara.
        nom_camara:      r.nom_camara,
        // Guarda la matrícula.
        matricula:       r.matricula,
        // Guarda el estado de la matrícula.
        estado_matricula:r.estado_matricula,
        // Guarda la organización jurídica.
        organizacion_juridica: r.organizacion_juridica,
        // Guarda la categoría mercantil.
        categoria:       r.categoria,
        // Guarda el último año renovado.
        ultimo_ano_renovado: r.ultimo_ano_renovado,
      });
    }
  }
  // Registra en debug cuántos registros se insertaron y cuántos quedaron como duplicados/no insertados.
  logger.debug(`[BD] busqueda "${value}" → ins:${busqIns} dup:${normalizedSearch.length - busqIns}`);

  // Filtra solo registros que tengan `id_rm`, requisito para solicitar detalle.
  let selected = normalizedSearch.filter(r => r.id_rm);
  // Si hay un limit de detalle configurado, recorta el arreglo seleccionado.
  if (Number.isInteger(options.limit) && options.limit >= 0) {
    // Mantiene solo los primeros `limit` elementos.
    selected = selected.slice(0, options.limit);
  }

  // Construye la estructura base del pipeline que se devolverá al llamador.
  const pipeline = {
    // Conserva el modo de búsqueda usado.
    mode,
    // Conserva el valor/keyword buscado.
    value,
    // Guarda el momento de ejecución del pipeline.
    executedAt:  new Date().toISOString(),
    // Agrupa la información del search ejecutado.
    search: {
      // Conserva la respuesta raw completa del search.
      raw:           searchResult,
      // Conserva los registros normalizados de búsqueda.
      normalized:    normalizedSearch,
      // Guarda cuántos registros quedaron seleccionados para detalle.
      selectedCount: selected.length,
      // Guarda la cantidad reportada por el backend.
      cantReportados,
    }
  };

  // Si no se pidió detalle, retorna el pipeline construido hasta esta etapa.
  if (!options.details) return pipeline;

  // Registra el inicio del procesamiento de detalle para la keyword actual.
  logger.info(`[DETALLE] Procesando ${selected.length} registros de "${value}"...`);

  // Inicializa el acumulador de resultados de detalle exitosos o parciales.
  const detailResults = [];
  // Inicializa el acumulador de errores de detalle.
  const detailErrors  = [];

  // Procesa los registros seleccionados con concurrencia controlada.
  await processWithConcurrency(selected, async (row, idx) => {
    // Extrae el id interno del registro actual.
    const id_rm = row.id_rm;

    // Si el id ya estaba procesado previamente, lo salta para evitar trabajo redundante.
    if (procesados.has(id_rm)) {
      // Registra el salto únicamente en nivel debug.
      logger.debug(`[DETALLE] id_rm=${id_rm} ya procesado, saltando`);
      // Retorna un objeto explícito que marca el registro como saltado.
      return { id_rm, skipped: true };
    }

    // Registra qué elemento del lote se está procesando y su razón social si existe.
    logger.debug(`[DETALLE] [${idx+1}/${selected.length}] id_rm=${id_rm} "${row.razon_social ?? ''}"`);

    // Declara referencias para la respuesta raw y normalizada del detalle.
    let detalleRaw, detalleNorm;
    try {
      // Solicita el detalle con política de reintentos definida por el cliente.
      detalleRaw  = await client.withRetries(() => client.getDetalleById(id_rm), options);
      // Normaliza el objeto `registros` devuelto por el endpoint de detalle.
      detalleNorm = normalizeDetalleRecord(detalleRaw?.response?.registros);

      // Calcula el score Argos y la bandera de aprobación usando razón social y CIIU principal.
      const { score, aprobado_argos } = calcularScoreArgos(
        detalleNorm?.razon_social || row.razon_social,
        detalleNorm?.cod_ciiu_act_econ_pri
      );

      // Inserta el detalle normalizado y la respuesta raw en base de datos.
      await db.insertarDetalle(run_id, id_rm, detalleNorm, detalleRaw?.response, value, score, aprobado_argos);
      // Marca el id actual como procesado para evitar duplicidad dentro del mismo run o siguientes keywords del run.
      procesados.add(id_rm);
      // Registra en debug el score y la aprobación calculada.
      logger.debug(`[BD] detalle id_rm=${id_rm} score=${score} aprobado=${aprobado_argos}`);

      // Si existe ruta JSONL para detalle, escribe una línea inmediata con el resultado normalizado.
      if (jsonlPaths.detalle) {
        appendJsonl(jsonlPaths.detalle, {
          // Etiqueta el evento como detalle.
          tipo:            'detalle',
          // Guarda el run_id actual.
          run_id,
          // Guarda la keyword origen.
          keyword:         value,
          // Guarda la fecha de extracción.
          fecha_extraccion: new Date().toISOString(),
          // Guarda el id interno RUES.
          id_rm,
          // Guarda el score calculado.
          score,
          // Guarda la bandera de aprobación Argos.
          aprobado_argos,
          // Guarda el detalle ya normalizado.
          detalle:         detalleNorm,
        });
      }

      // Construye el item base del resultado de este registro.
      const item = { id_rm, keyword: value, detalle_raw: detalleRaw, detalle_normalized: detalleNorm, score, aprobado_argos };

      // Solo entra a endpoints extendidos si están habilitados y si el detalle trae cámara y matrícula.
      if (options.extended && detalleNorm?.cod_camara && detalleNorm?.matricula) {
        // Extrae el código de cámara del detalle normalizado.
        const cod = detalleNorm.cod_camara;
        // Extrae la matrícula del detalle normalizado.
        const mat = detalleNorm.matricula;

        // Intenta obtener la información de facultades.
        try {
          // Registra en debug la invocación del endpoint de facultades.
          logger.debug(`[FACULTADES] id_rm=${id_rm} camara=${cod} mat=${mat}`);
          // Llama al endpoint de facultades con retries y timeout reducido para esta etapa.
          const facRaw  = await client.withRetries(
            () => client.getFacultadesByCamaraMatricula(cod, mat),
            { ...options, timeoutMs: TIMEOUT_EXTENDIDO_MS }
          );
          // Si la respuesta es un string HTML plano, la conserva; en otro caso asigna null.
          const facHtml = typeof facRaw?.response === 'string' ? facRaw.response : null;
          // Limpia el HTML y lo convierte a texto plano utilizable.
          const facText = cleanHtmlToText(facHtml);

          // Guarda la respuesta raw de facultades dentro del item consolidado.
          item.facultades_raw  = facRaw;
          // Guarda el texto limpio de facultades dentro del item consolidado.
          item.facultades_text = facText;

          // Inserta facultades en base incluyendo raw_response y error null.
          await db.insertarFacultades(run_id, id_rm, cod, mat, facHtml, facText, facRaw?.response, null);
          // Registra la cantidad de caracteres extraídos del HTML limpio.
          logger.debug(`[BD] facultades id_rm=${id_rm} chars=${facText?.length ?? 0}`);

          // Si existe JSONL de facultades, escribe una línea inmediata con el texto ya limpio.
          if (jsonlPaths.facultades) {
            appendJsonl(jsonlPaths.facultades, {
              // Etiqueta el tipo de evento como facultades.
              tipo: 'facultades', run_id, keyword: value, id_rm, cod_camara: cod, matricula: mat,
              // Guarda el texto de facultades ya transformado a plano.
              facultades_texto: facText,
              // Guarda la fecha de extracción del evento.
              fecha_extraccion: new Date().toISOString(),
            });
          }

        } catch (e) {
          // Guarda el mensaje del error de facultades en el item consolidado.
          item.facultades_error = e.message;
          // Inserta igualmente un registro en base con el error para no perder trazabilidad.
          await db.insertarFacultades(run_id, id_rm, cod, mat, null, null, null, e.message);
          // Registra una advertencia del fallo de facultades.
          logger.warn(`[FACULTADES] id_rm=${id_rm}: ${e.message}`);
          // Si existe JSONL de errores, persiste inmediatamente el incidente.
          if (jsonlPaths.errores) appendJsonl(jsonlPaths.errores, { tipo: 'facultades_error', run_id, id_rm, error: e.message, ts: new Date().toISOString() });
        }

        // Intenta obtener la información de propietario/establecimiento.
        try {
          // Registra en debug la llamada al endpoint de propietario.
          logger.debug(`[PROPIETARIO] id_rm=${id_rm} camara=${cod} mat=${mat}`);
          // Llama al endpoint con menos reintentos y timeout reducido para limitar el costo de esta etapa.
          const propRaw  = await client.withRetries(
            () => client.getPropietarioEstByCamaraMatricula(cod, mat),
            { ...options, maxRetries: 2, timeoutMs: TIMEOUT_EXTENDIDO_MS }
          );
          // Normaliza la respuesta completa del endpoint de propietario.
          const propNorm = normalizePropietarioResponse(propRaw?.response);
          // Extrae el arreglo de registros normalizados o usa arreglo vacío.
          const registros = propNorm?.registros ?? [];

          // Guarda la respuesta raw de propietario dentro del item consolidado.
          item.propietario_raw        = propRaw;
          // Guarda la versión normalizada de propietario dentro del item consolidado.
          item.propietario_normalized = propNorm;

          // Inserta propietarios en base de datos con respuesta raw incluida.
          await db.insertarPropietarios(run_id, id_rm, cod, mat, registros, propRaw?.response, null);
          // Registra en debug cuántos propietarios fueron detectados.
          logger.debug(`[BD] propietarios id_rm=${id_rm} cant=${registros.length}`);

          // Si existe JSONL de propietarios, escribe una línea inmediata con todos los propietarios normalizados.
          if (jsonlPaths.propietarios) {
            appendJsonl(jsonlPaths.propietarios, {
              // Etiqueta el evento como propietario.
              tipo: 'propietario', run_id, keyword: value, id_rm, cod_camara: cod, matricula: mat,
              // Guarda la cantidad de propietarios encontrados.
              cant_propietarios: registros.length,
              // Guarda la lista completa de propietarios normalizados.
              propietarios: registros,
              // Guarda la fecha de extracción del evento.
              fecha_extraccion: new Date().toISOString(),
            });
          }

        } catch (e) {
          // Guarda el mensaje del error de propietario dentro del item consolidado.
          item.propietario_error = e.message;
          // Inserta igualmente un registro en base con arreglo vacío y error para no perder trazabilidad.
          await db.insertarPropietarios(run_id, id_rm, cod, mat, [], null, e.message);
          // Registra una advertencia del fallo de propietario.
          logger.warn(`[PROPIETARIO] id_rm=${id_rm}: ${e.message}`);
          // Si existe JSONL de errores, persiste inmediatamente el incidente.
          if (jsonlPaths.errores) appendJsonl(jsonlPaths.errores, { tipo: 'propietario_error', run_id, id_rm, error: e.message, ts: new Date().toISOString() });
        }
      }

      // Acumula el item exitoso o parcialmente exitoso en el arreglo de resultados.
      detailResults.push(item);
      // Retorna el item al worker concurrente.
      return item;

    } catch (e) {
      // Construye un objeto de error estandarizado para fallos de detalle.
      const err = { tipo: 'detalle_error', stage: 'detalle', id_rm, error: true, status: e?.response?.status ?? null, message: e.message };
      // Acumula el error en el arreglo de errores del pipeline.
      detailErrors.push(err);
      // Registra el error en logs incluyendo status HTTP si existe.
      logger.error(`[DETALLE] id_rm=${id_rm}: ${e.message}`, { status: e?.response?.status });
      // Si existe JSONL de errores, persiste inmediatamente la línea del incidente.
      if (jsonlPaths.errores) appendJsonl(jsonlPaths.errores, { ...err, run_id, keyword: value, ts: new Date().toISOString() });
      // Retorna el error al worker para conservar trazabilidad del elemento procesado.
      return err;
    }

  }, options);

  // Adjunta al objeto pipeline el bloque final de resultados y errores de detalle.
  pipeline.details = { results: detailResults, errors: detailErrors };
  // Registra un resumen agregado del detalle para esta keyword.
  logger.ok(`[DETALLE] "${value}" → ok:${detailResults.length} err:${detailErrors.length}`);

  // Retorna el pipeline completo al llamador.
  return pipeline;
}

// Exporta las funciones principales del módulo para reutilización externa.
module.exports = { runSearchPipeline, processWithConcurrency, appendJsonl };