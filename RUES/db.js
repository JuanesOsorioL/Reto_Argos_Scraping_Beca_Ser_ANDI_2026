/**
 * db.js — PostgreSQL para RUES API
 *
 * 4 tablas en schema raw — TODAS incluyen raw_response (respuesta cruda completa):
 *   raw.rues_busqueda     — resultados de BusquedaAvanzadaRM
 *   raw.rues_detalle      — detalle completo de DetalleRM + columnas Argos + score
 *   raw.rues_facultades   — ConsultFacultadesXCamYMatricula
 *   raw.rues_propietarios — PropietarioEstXCamaraYMatricula
 */
// Importa `Pool` desde `pg` para gestionar conexiones PostgreSQL reutilizables.
const { Pool }   = require('pg');
// Importa la configuración central para acceder a los parámetros de conexión a BD.
const { CONFIG } = require('./config');
// Importa el logger para dejar trazabilidad de inicialización e inserciones fallidas.
const { logger } = require('./logger');

// Declara una referencia singleton al pool de conexiones.
let pool = null;

// Obtiene el pool de PostgreSQL, creándolo solo una vez cuando sea necesario.
function getPool() {
  // Si todavía no existe un pool, lo inicializa con la configuración DB del proyecto.
  if (!pool) {
    // Crea el pool de conexiones reutilizable.
    pool = new Pool(CONFIG.DB);
    // Registra un handler de error a nivel de pool para observabilidad de fallas persistentes.
    pool.on('error', (e) => logger.error(`[BD] Pool error: ${e.message}`));
  }
  // Retorna el pool singleton ya existente o recién creado.
  return pool;
}

// Inicializa schema, tablas e índices necesarios para el scraper RUES.
async function initDb() {
  // Obtiene una conexión dedicada del pool para ejecutar el bootstrap de esquema.
  const client = await getPool().connect();
  try {
    // Crea el schema `raw` si todavía no existe.
    await client.query(`CREATE SCHEMA IF NOT EXISTS raw;`);

    // Crea y verifica la tabla de búsqueda junto con sus índices.
    await client.query(`
      CREATE TABLE IF NOT EXISTS raw.rues_busqueda (
        id                    SERIAL PRIMARY KEY,
        run_id                UUID        NOT NULL,
        fecha_extraccion      TIMESTAMP   NOT NULL DEFAULT NOW(),
        keyword_busqueda      TEXT,
        id_rm                 TEXT,
        tipo_documento        TEXT,
        nit                   TEXT,
        dv                    TEXT,
        razon_social          TEXT,
        sigla                 TEXT,
        cod_camara            TEXT,
        nom_camara            TEXT,
        matricula             TEXT,
        organizacion_juridica TEXT,
        estado_matricula      TEXT,
        ultimo_ano_renovado   TEXT,
        categoria             TEXT,
        raw_response          JSONB,
        UNIQUE(id_rm, keyword_busqueda)
      );
      CREATE INDEX IF NOT EXISTS idx_rb_nit     ON raw.rues_busqueda (nit);
      CREATE INDEX IF NOT EXISTS idx_rb_id_rm   ON raw.rues_busqueda (id_rm);
      CREATE INDEX IF NOT EXISTS idx_rb_keyword ON raw.rues_busqueda (keyword_busqueda);
      CREATE INDEX IF NOT EXISTS idx_rb_run     ON raw.rues_busqueda (run_id);
      CREATE INDEX IF NOT EXISTS idx_rb_estado  ON raw.rues_busqueda (estado_matricula);
    `);

    // Crea y verifica la tabla de detalle junto con sus índices.
    await client.query(`
      CREATE TABLE IF NOT EXISTS raw.rues_detalle (
        id                              SERIAL PRIMARY KEY,
        run_id                          UUID      NOT NULL,
        fecha_extraccion                TIMESTAMP NOT NULL DEFAULT NOW(),
        id_rm                           TEXT UNIQUE,
        keyword_busqueda                TEXT,
        nit                             TEXT,
        nombre                          TEXT,
        departamento                    TEXT,
        municipio                       TEXT,
        direccion                       TEXT,
        latitud                         DOUBLE PRECISION,
        longitud                        DOUBLE PRECISION,
        telefono                        TEXT,
        whatsapp                        TEXT,
        correo_electronico              TEXT,
        fecha_actualizacion_argos       TIMESTAMP,
        fuente                          TEXT DEFAULT 'rues',
        score                           INTEGER,
        aprobado_argos                  BOOLEAN,
        cod_camara                      TEXT,
        camara                          TEXT,
        matricula                       TEXT,
        razon_social                    TEXT,
        sigla                           TEXT,
        clase_identificacion            TEXT,
        numero_identificacion           TEXT,
        numero_identificacion_2         TEXT,
        dv                              TEXT,
        dir_comercial                   TEXT,
        mun_comercial                   TEXT,
        tel_com_1                       TEXT,
        tel_com_2                       TEXT,
        tel_com_3                       TEXT,
        email_com                       TEXT,
        dir_fiscal                      TEXT,
        mun_fiscal                      TEXT,
        tel_fiscal_1                    TEXT,
        tel_fiscal_2                    TEXT,
        tel_fiscal_3                    TEXT,
        email_fiscal                    TEXT,
        cod_ciiu_pri                    TEXT,
        desc_ciiu_pri                   TEXT,
        cod_ciiu_sec                    TEXT,
        desc_ciiu_sec                   TEXT,
        ciiu3                           TEXT,
        desc_ciiu3                      TEXT,
        ciiu4                           TEXT,
        desc_ciiu4                      TEXT,
        fecha_matricula                 DATE,
        fecha_renovacion                DATE,
        ultimo_ano_renovado             TEXT,
        fecha_vigencia                  DATE,
        fecha_cancelacion               DATE,
        motivo_cancelacion              TEXT,
        fecha_actualizacion             DATE,
        cod_tipo_sociedad               TEXT,
        tipo_sociedad                   TEXT,
        organizacion_juridica           TEXT,
        categoria_matricula             TEXT,
        estado                          TEXT,
        indicador_emprendimiento_social TEXT,
        extincion_dominio               TEXT,
        control_inactivacion_sipref     TEXT,
        indicador_ley_1780              TEXT,
        indicador_empresa_bic           TEXT,
        indicador_transporte            TEXT,
        url_venta_certificados          TEXT,
        raw_response                    JSONB
      );
      CREATE INDEX IF NOT EXISTS idx_rd_nit      ON raw.rues_detalle (numero_identificacion);
      CREATE INDEX IF NOT EXISTS idx_rd_camara   ON raw.rues_detalle (cod_camara);
      CREATE INDEX IF NOT EXISTS idx_rd_estado   ON raw.rues_detalle (estado);
      CREATE INDEX IF NOT EXISTS idx_rd_ciiu     ON raw.rues_detalle (cod_ciiu_pri);
      CREATE INDEX IF NOT EXISTS idx_rd_run      ON raw.rues_detalle (run_id);
      CREATE INDEX IF NOT EXISTS idx_rd_aprobado ON raw.rues_detalle (aprobado_argos);
      CREATE INDEX IF NOT EXISTS idx_rd_mun      ON raw.rues_detalle (municipio);
    `);

    // Crea y verifica la tabla de facultades junto con su índice principal.
    await client.query(`
      CREATE TABLE IF NOT EXISTS raw.rues_facultades (
        id               SERIAL PRIMARY KEY,
        run_id           UUID      NOT NULL,
        fecha_extraccion TIMESTAMP NOT NULL DEFAULT NOW(),
        id_rm            TEXT UNIQUE,
        cod_camara       TEXT,
        matricula        TEXT,
        facultades_html  TEXT,
        facultades_texto TEXT,
        error            TEXT,
        raw_response     JSONB
      );
      CREATE INDEX IF NOT EXISTS idx_rf_id_rm ON raw.rues_facultades (id_rm);
    `);

    // Crea y verifica la tabla de propietarios junto con sus índices.
    await client.query(`
      CREATE TABLE IF NOT EXISTS raw.rues_propietarios (
        id                           SERIAL PRIMARY KEY,
        run_id                       UUID      NOT NULL,
        fecha_extraccion             TIMESTAMP NOT NULL DEFAULT NOW(),
        id_rm                        TEXT,
        cod_camara                   TEXT,
        matricula                    TEXT,
        codigo_clase_identificacion  TEXT,
        numero_identificacion        TEXT,
        digito_verificacion          TEXT,
        razon_social_propietario     TEXT,
        sigla_propietario            TEXT,
        codigo_camara_prop           TEXT,
        desc_camara_prop             TEXT,
        matricula_prop               TEXT,
        codigo_tipo_sociedad         TEXT,
        desc_tipo_sociedad           TEXT,
        codigo_organizacion_juridica TEXT,
        desc_organizacion_juridica   TEXT,
        codigo_categoria_matricula   TEXT,
        categoria_matricula          TEXT,
        codigo_estado_matricula      TEXT,
        desc_estado_matricula        TEXT,
        fecha_matricula_prop         DATE,
        fecha_renovacion_prop        DATE,
        ultimo_ano_renovado_prop     TEXT,
        raw_response                 JSONB,
        error                        TEXT
      );
      CREATE INDEX IF NOT EXISTS idx_rp_id_rm ON raw.rues_propietarios (id_rm);
      CREATE INDEX IF NOT EXISTS idx_rp_nit   ON raw.rues_propietarios (numero_identificacion);
    `);

    // Registra en logs que las tablas y su esquema quedaron verificadas.
    logger.ok('[DB] Tablas RUES verificadas (4 tablas, todas con raw_response).');
  } finally {
    // Libera la conexión dedicada aunque ocurra un error.
    client.release();
  }
}

// Convierte distintas representaciones de fecha a un formato seguro para PostgreSQL o null.
function safeDate(v) {
  // Retorna null para valores vacíos o sentinels conocidos de RUES.
  if (!v || v === '99991231' || v === '00000000' || v === '0') return null;
  // Normaliza el valor a string trimmeado.
  const s = String(v).trim();
  // Si el valor es YYYYMMDD, lo transforma a YYYY-MM-DD.
  if (/^\d{8}$/.test(s)) return `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}`;
  // Si ya viene en formato ISO simple, lo retorna tal cual.
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  // Para cualquier otro formato no reconocido, retorna null.
  return null;
}

// Convierte un valor arbitrario a JSON serializado o null si no es serializable.
function toJson(v) {
  // Retorna null si el valor es null o undefined.
  if (v === null || v === undefined) return null;
  try {
    // Intenta serializar el valor a string JSON.
    return JSON.stringify(v);
  } catch {
    // Si falla la serialización, retorna null como fallback seguro.
    return null;
  }
}

// Inserta un registro de búsqueda normalizado en la tabla `raw.rues_busqueda`.
async function insertarBusqueda(run_id, keyword, r) {
  // Si no existe el registro o no tiene id_rm, no inserta nada y retorna false.
  if (!r || !r.id_rm) return false;
  try {
    // Ejecuta el INSERT ignorando conflictos por `(id_rm, keyword_busqueda)`.
    const res = await getPool().query(`
      INSERT INTO raw.rues_busqueda (
        run_id, keyword_busqueda,
        id_rm, tipo_documento, nit, dv, razon_social, sigla,
        cod_camara, nom_camara, matricula, organizacion_juridica,
        estado_matricula, ultimo_ano_renovado, categoria,
        raw_response
      ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
      ON CONFLICT (id_rm, keyword_busqueda) DO NOTHING
    `, [
      run_id, keyword,
      r.id_rm,
      r.tipo_documento   ?? null,
      String(r.nit ?? ''),
      r.dv               ?? null,
      r.razon_social     ?? null,
      r.sigla            ?? null,
      r.cod_camara       ?? null,
      r.nom_camara       ?? null,
      r.matricula        ?? null,
      r.organizacion_juridica ?? null,
      r.estado_matricula ?? null,
      r.ultimo_ano_renovado ?? null,
      r.categoria        ?? null,
      toJson(r.raw ?? r)
    ]);
    // Retorna true únicamente si se insertó exactamente una fila.
    return res.rowCount === 1;
  } catch (e) {
    // Registra el error específico de inserción para este id_rm.
    logger.error(`[DB] insertarBusqueda id_rm=${r.id_rm}: ${e.message}`);
    // Retorna false para indicar que la inserción no fue efectiva.
    return false;
  }
}

// Inserta o actualiza un detalle normalizado en `raw.rues_detalle`.
async function insertarDetalle(run_id, id_rm, d, detalleRaw, keyword, score, aprobado_argos) {
  // Si no existe detalle o no hay id_rm, retorna false inmediatamente.
  if (!d || !id_rm) return false;
  try {
    // Ejecuta el INSERT con `ON CONFLICT (id_rm)` para refrescar campos clave en reruns.
    await getPool().query(`
      INSERT INTO raw.rues_detalle (
        run_id, id_rm, keyword_busqueda,
        nit, nombre, municipio, direccion, telefono, correo_electronico, fuente,
        score, aprobado_argos,
        cod_camara, camara, matricula, razon_social, sigla,
        clase_identificacion, numero_identificacion, numero_identificacion_2, dv,
        dir_comercial, mun_comercial, tel_com_1, tel_com_2, tel_com_3, email_com,
        dir_fiscal, mun_fiscal, tel_fiscal_1, tel_fiscal_2, tel_fiscal_3, email_fiscal,
        cod_ciiu_pri, desc_ciiu_pri, cod_ciiu_sec, desc_ciiu_sec,
        ciiu3, desc_ciiu3, ciiu4, desc_ciiu4,
        fecha_matricula, fecha_renovacion, ultimo_ano_renovado,
        fecha_vigencia, fecha_cancelacion, motivo_cancelacion, fecha_actualizacion,
        cod_tipo_sociedad, tipo_sociedad, organizacion_juridica, categoria_matricula, estado,
        indicador_emprendimiento_social, extincion_dominio, control_inactivacion_sipref,
        indicador_ley_1780, indicador_empresa_bic, indicador_transporte,
        url_venta_certificados,
        raw_response
      ) VALUES (
        $1,$2,$3,
        $4,$5,$6,$7,$8,$9,$10,
        $11,$12,
        $13,$14,$15,$16,$17,
        $18,$19,$20,$21,
        $22,$23,$24,$25,$26,$27,
        $28,$29,$30,$31,$32,$33,
        $34,$35,$36,$37,
        $38,$39,$40,$41,
        $42,$43,$44,
        $45,$46,$47,$48,
        $49,$50,$51,$52,$53,
        $54,$55,$56,
        $57,$58,$59,
        $60,$61
      )
      ON CONFLICT (id_rm) DO UPDATE SET
        raw_response     = EXCLUDED.raw_response,
        score            = EXCLUDED.score,
        aprobado_argos   = EXCLUDED.aprobado_argos,
        fecha_extraccion = NOW()
    `, [
      run_id, id_rm, keyword ?? null,
      d.numero_identificacion ?? null,
      d.razon_social          ?? null,
      d.mun_comercial ?? d.mun_fiscal ?? null,
      d.dir_comercial ?? d.dir_fiscal ?? null,
      d.tel_com_1     ?? d.tel_fiscal_1 ?? null,
      d.email_com     ?? d.email_fiscal ?? null,
      'rues',
      score ?? null,
      aprobado_argos ?? null,
      d.cod_camara              ?? null,
      d.camara                  ?? null,
      d.matricula               ?? null,
      d.razon_social            ?? null,
      d.sigla                   ?? null,
      d.clase_identificacion    ?? null,
      d.numero_identificacion   ?? null,
      d.numero_identificacion_2 ?? null,
      d.dv                      ?? null,
      d.dir_comercial ?? null,
      d.mun_comercial ?? null,
      d.tel_com_1     ?? null,
      d.tel_com_2     ?? null,
      d.tel_com_3     ?? null,
      d.email_com     ?? null,
      d.dir_fiscal   ?? null,
      d.mun_fiscal   ?? null,
      d.tel_fiscal_1 ?? null,
      d.tel_fiscal_2 ?? null,
      d.tel_fiscal_3 ?? null,
      d.email_fiscal ?? null,
      d.cod_ciiu_act_econ_pri  ?? null,
      d.desc_ciiu_act_econ_pri ?? null,
      d.cod_ciiu_act_econ_sec  ?? null,
      d.desc_ciiu_act_econ_sec ?? null,
      d.ciiu3      ?? null,
      d.desc_ciiu3 ?? null,
      d.ciiu4      ?? null,
      d.desc_ciiu4 ?? null,
      safeDate(d.fecha_matricula),
      safeDate(d.fecha_renovacion),
      d.ultimo_ano_renovado ?? null,
      safeDate(d.fecha_vigencia),
      safeDate(d.fecha_cancelacion),
      d.motivo_cancelacion ?? null,
      safeDate(d.fecha_actualizacion),
      d.cod_tipo_sociedad    ?? null,
      d.tipo_sociedad        ?? null,
      d.organizacion_juridica?? null,
      d.categoria_matricula  ?? null,
      d.estado               ?? null,
      d.indicador_emprendimiento_social ?? null,
      d.extincion_dominio               ?? null,
      d.control_inactivacion_sipref     ?? null,
      d.indicador_ley_1780              ?? null,
      d.indicador_empresa_bic           ?? null,
      d.indicador_transporte            ?? null,
      d.url_venta_certificados          ?? null,
      toJson(detalleRaw ?? d.raw ?? d)
    ]);
    // Retorna true si el query se ejecutó sin lanzar error.
    return true;
  } catch (e) {
    // Registra el error específico de inserción de detalle.
    logger.error(`[DB] insertarDetalle id_rm=${id_rm}: ${e.message}`);
    // Retorna false para indicar fallo de persistencia.
    return false;
  }
}

// Inserta o actualiza facultades para un registro dado.
async function insertarFacultades(run_id, id_rm, cod_camara, matricula, html, texto, rawResponse, error) {
  try {
    // Ejecuta el upsert de facultades por `id_rm`.
    await getPool().query(`
      INSERT INTO raw.rues_facultades
        (run_id, id_rm, cod_camara, matricula, facultades_html, facultades_texto, raw_response, error)
      VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
      ON CONFLICT (id_rm) DO UPDATE SET
        facultades_html  = EXCLUDED.facultades_html,
        facultades_texto = EXCLUDED.facultades_texto,
        raw_response     = EXCLUDED.raw_response,
        error            = EXCLUDED.error,
        fecha_extraccion = NOW()
    `, [
      run_id, id_rm, cod_camara, matricula,
      html   ?? null,
      texto  ?? null,
      toJson(rawResponse),
      error  ?? null
    ]);
    // Retorna true si el query se ejecutó correctamente.
    return true;
  } catch (e) {
    // Registra el error específico de inserción de facultades.
    logger.error(`[DB] insertarFacultades id_rm=${id_rm}: ${e.message}`);
    // Retorna false si hubo fallo de persistencia.
    return false;
  }
}

// Inserta propietarios en la tabla correspondiente guardando también errores y raw response.
async function insertarPropietarios(run_id, id_rm, cod_camara, matricula, props, rawResponse, error) {
  // Selecciona el primer propietario si existe para aplanar campos principales en columnas rápidas.
  const p = (props && props.length > 0) ? props[0] : {};
  try {
    // Ejecuta el INSERT del registro de propietarios.
    await getPool().query(`
      INSERT INTO raw.rues_propietarios (
        run_id, id_rm, cod_camara, matricula,
        codigo_clase_identificacion, numero_identificacion, digito_verificacion,
        razon_social_propietario, sigla_propietario, codigo_camara_prop, desc_camara_prop,
        matricula_prop, codigo_tipo_sociedad, desc_tipo_sociedad,
        codigo_organizacion_juridica, desc_organizacion_juridica,
        codigo_categoria_matricula, categoria_matricula,
        codigo_estado_matricula, desc_estado_matricula,
        fecha_matricula_prop, fecha_renovacion_prop, ultimo_ano_renovado_prop,
        raw_response, error
      ) VALUES (
        $1,$2,$3,$4,
        $5,$6,$7,$8,$9,$10,$11,
        $12,$13,$14,$15,$16,$17,$18,$19,$20,
        $21,$22,$23,$24,$25
      )
    `, [
      run_id, id_rm, cod_camara, matricula,
      p.CODIGO_CLASE_IDENTIFICACION  ?? null,
      p.NUMERO_IDENTIFICACION        ?? null,
      p.DIGITO_VERIFICACION          ?? null,
      p.RAZON_SOCIAL                 ?? null,
      p.SIGLA                        ?? null,
      p.CODIGO_CAMARA                ?? null,
      p.DESC_CAMARA                  ?? null,
      p.MATRICULA                    ?? null,
      p.CODIGO_TIPO_SOCIEDAD         ?? null,
      p.DESC_TIPO_SOCIEDAD           ?? null,
      p.CODIGO_ORGANIZACION_JURIDICA ?? null,
      p.DESC_ORGANIZACION_JURIDICA   ?? null,
      p.CODIGO_CATEGORIA_MATRICULA   ?? null,
      p.CATEGORIA_MATRICULA          ?? null,
      p.CODIGO_ESTADO_MATRICULA      ?? null,
      p.DESC_ESTADO_MATRICULA        ?? null,
      safeDate(p.FECHA_MATRICULA),
      safeDate(p.FECHA_RENOVACION),
      p.ULTIMO_ANO_RENOVADO          ?? null,
      toJson(rawResponse ?? props),
      error ?? null
    ]);
    // Retorna true si la operación fue exitosa.
    return true;
  } catch (e) {
    // Registra el error específico de inserción de propietarios.
    logger.error(`[DB] insertarPropietarios id_rm=${id_rm}: ${e.message}`);
    // Retorna false cuando no pudo persistirse el registro.
    return false;
  }
}

// Carga desde la tabla de detalle el conjunto de `id_rm` ya procesados.
async function cargarIdRmProcesados() {
  try {
    // Consulta todos los `id_rm` no nulos de la tabla de detalle.
    const r = await getPool().query(
      `SELECT id_rm FROM raw.rues_detalle WHERE id_rm IS NOT NULL`
    );
    // Retorna un `Set` para búsquedas O(1) durante el pipeline.
    return new Set(r.rows.map(x => x.id_rm));
  } catch (e) {
    // Registra una advertencia si no se pudo cargar la lista histórica.
    logger.warn(`[DB] No se pudo cargar procesados: ${e.message}`);
    // Retorna un Set vacío para permitir continuar el proceso.
    return new Set();
  }
}

// Cierra el pool de PostgreSQL si existe uno abierto.
async function closePool() {
  // Si el pool existe, lo cierra y limpia la referencia singleton.
  if (pool) { await pool.end(); pool = null; }
}

// Exporta las funciones públicas de la capa de persistencia.
module.exports = {
  // Exporta la inicialización de schema y tablas.
  initDb,
  // Exporta la inserción de resultados de búsqueda.
  insertarBusqueda,
  // Exporta la inserción de detalle.
  insertarDetalle,
  // Exporta la inserción de facultades.
  insertarFacultades,
  // Exporta la inserción de propietarios.
  insertarPropietarios,
  // Exporta la carga del set de `id_rm` ya procesados.
  cargarIdRmProcesados,
  // Exporta el cierre del pool.
  closePool,
  // Exporta el acceso al pool por si otros módulos lo necesitan.
  getPool,
};