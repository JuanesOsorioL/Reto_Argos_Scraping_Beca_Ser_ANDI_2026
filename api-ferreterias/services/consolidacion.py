"""
services/consolidacion.py - Consolidar staging en clean.empresas
"""

import uuid
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Prioridades para seleccionar el mejor dato por campo
PRIORIDAD_NIT           = ['rues', 'google_maps', 'paginas_amarillas', 'serper', 'foursquare', 'openstreetmap']
PRIORIDAD_RAZON_SOCIAL  = ['rues', 'serper', 'google_maps', 'paginas_amarillas', 'foursquare', 'openstreetmap']
PRIORIDAD_NOMBRE_COM    = ['google_maps', 'paginas_amarillas', 'foursquare', 'serper', 'rues', 'openstreetmap']
PRIORIDAD_DIRECCION     = ['google_maps', 'rues', 'paginas_amarillas', 'openstreetmap', 'foursquare', 'serper']
PRIORIDAD_COORDENADAS   = ['google_maps', 'foursquare', 'openstreetmap', 'serper', 'rues', 'paginas_amarillas']
PRIORIDAD_TELEFONO      = ['rues', 'google_maps', 'paginas_amarillas', 'serper', 'foursquare', 'openstreetmap']
PRIORIDAD_EMAIL         = ['rues', 'serper', 'paginas_amarillas', 'openstreetmap', 'google_maps', 'foursquare']


def consolidar_empresas(db, merge_log_detalle: int = 10) -> dict:
    """
    Fase de consolidación:
    1. Crear staging.entidad_resuelta (grupos de staging_id que son el mismo negocio)
    2. Insertar en clean.empresas con field-level merging
    3. Insertar en tablas auxiliares
    4. Log de merging (opcional)
    """
    logger.info("🔗 Iniciando consolidación de empresas...")

    # Limpiar entidad_resuelta anterior
    db.execute(text("TRUNCATE staging.entidad_resuelta"))
    db.commit()

    # Paso 1: Crear grupos usando Union-Find en SQL
    _crear_grupos_empresas(db)

    # Paso 2: Insertar en clean.empresas
    n_empresas = _insertar_clean_empresas(db)
    logger.info(f"  ✓ Empresas insertadas en clean.empresas: {n_empresas}")

    # Paso 3: Tablas auxiliares
    n_tels   = _insertar_telefonos(db)
    n_emails = _insertar_emails(db)
    n_dirs   = _insertar_direcciones(db)
    n_fuentes= _insertar_fuentes(db)

    db.commit()

    # Paso 4: Log de merging (nunca debe romper el pipeline)
    if merge_log_detalle != 0:
        try:
            _log_merging_stats(db, merge_log_detalle)
        except Exception as e:
            logger.warning(f"⚠ Log de merging omitido por error: {e}")
            db.rollback()

    stats = {
        "empresas_consolidadas": n_empresas,
        "telefonos": n_tels,
        "emails": n_emails,
        "direcciones": n_dirs,
        "fuentes": n_fuentes,
    }
    logger.info(f"✅ Consolidación completada: {stats}")
    return stats


def _crear_grupos_empresas(db):
    """
    Asigna empresa_id a cada staging_id usando los matches confirmados.
    Registros sin matches → empresa_id propio.
    """
    logger.info("  Creando grupos de empresas...")

    # Obtener todos los matches confirmados (auto_match + ia_match)
    matches = db.execute(text("""
        SELECT staging_id_a, staging_id_b
        FROM staging.posibles_matches
        WHERE decision IN ('auto_match', 'ia_match')
        ORDER BY score_match DESC
    """)).fetchall()

    # Union-Find en Python
    parent: dict[int, int] = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for sid_a, sid_b in matches:
        union(sid_a, sid_b)

    # Obtener todos los staging_ids
    all_ids = db.execute(
        text("SELECT staging_id, fuente FROM staging.empresas_unificadas ORDER BY staging_id")
    ).fetchall()

    # Asignar empresa_id por grupo
    grupo_a_empresa: dict[int, str] = {}
    filas_resuelta = []

    for (staging_id, fuente) in all_ids:
        root = find(staging_id)
        if root not in grupo_a_empresa:
            grupo_a_empresa[root] = str(uuid.uuid4())
        empresa_id = grupo_a_empresa[root]
        filas_resuelta.append({
            "empresa_id": empresa_id,
            "staging_id": staging_id,
            "fuente": fuente,
        })

    # Insertar en staging.entidad_resuelta por lotes
    LOTE = 1000
    for i in range(0, len(filas_resuelta), LOTE):
        lote = filas_resuelta[i:i+LOTE]
        for fila in lote:
            db.execute(text("""
                INSERT INTO staging.entidad_resuelta
                    (empresa_id, staging_id, fuente, score_match, regla_principal)
                VALUES (:empresa_id, :staging_id, :fuente, NULL, NULL)
                ON CONFLICT (empresa_id, staging_id) DO NOTHING
            """), fila)
        db.commit()

    logger.info(f"  ✓ {len(filas_resuelta)} staging_ids agrupados en {len(grupo_a_empresa)} empresas")


def _insertar_clean_empresas(db) -> int:
    """
    Inserta empresas consolidadas en clean.empresas con field-level merging:
    cada campo se toma del mejor source disponible para ese campo específico,
    en lugar de tomar todo del source de mayor prioridad general.
    """

    db.execute(text("TRUNCATE clean.empresa_fuentes, clean.empresa_telefonos, clean.empresa_emails, clean.empresa_direcciones, clean.empresas CASCADE"))
    db.commit()

    result = db.execute(text("""
        INSERT INTO clean.empresas (
            empresa_id, nit, dv, id_rm, matricula,
            razon_social, nombre_comercial, nombre_normalizado,
            departamento, municipio, codigo_dane_municipio,
            direccion_principal, direccion_normalizada,
            latitud, longitud,
            telefono_principal, whatsapp_principal, correo_principal, sitio_web,
            cod_ciiu_principal, desc_ciiu_principal, tipo_negocio,
            estado_legal, fecha_matricula, fecha_renovacion, ultimo_ano_renovado,
            fuente_principal, fuentes, fecha_primera_extraccion, fecha_ultima_extraccion,
            cantidad_fuentes, cantidad_matches
        )
        WITH grupo_stats AS (
            SELECT
                er.empresa_id,
                array_agg(DISTINCT eu.fuente ORDER BY eu.fuente) AS fuentes_arr,
                count(DISTINCT eu.fuente)                        AS cnt_fuentes,
                min(eu.fecha_extraccion)                         AS primera_ext,
                max(eu.fecha_extraccion)                         AS ultima_ext,
                count(DISTINCT pm.match_id)                      AS cnt_matches
            FROM staging.entidad_resuelta er
            JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
            LEFT JOIN staging.posibles_matches pm
                ON (pm.staging_id_a = eu.staging_id OR pm.staging_id_b = eu.staging_id)
                AND pm.decision IN ('auto_match', 'ia_match')
            GROUP BY er.empresa_id
        ),
        por_empresa AS (
            SELECT
                er.empresa_id,
                eu.fuente,
                eu.nit, eu.dv, eu.id_rm, eu.matricula,
                eu.razon_social_original,
                eu.nombre_original,
                eu.nombre_normalizado,
                eu.departamento_norm, eu.municipio_norm, eu.codigo_dane_municipio,
                eu.direccion_original, eu.direccion_normalizada,
                eu.latitud, eu.longitud,
                eu.telefono_normalizado,
                eu.whatsapp_normalizado,
                eu.correo_normalizado,
                eu.sitio_web,
                eu.ciiu_codigo, eu.ciiu_descripcion,
                eu.score_origen, eu.aprobado_origen,
                CASE eu.fuente
                    WHEN 'rues'              THEN 1
                    WHEN 'google_maps'       THEN 2
                    WHEN 'paginas_amarillas' THEN 3
                    WHEN 'serper'            THEN 4
                    WHEN 'foursquare'        THEN 5
                    ELSE 6
                END AS prio
            FROM staging.entidad_resuelta er
            JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
        ),
        fuente_ppal AS (
            -- fuente principal = source de mayor prioridad presente en el grupo
            SELECT DISTINCT ON (empresa_id)
                empresa_id, fuente, score_origen, aprobado_origen
            FROM por_empresa
            ORDER BY empresa_id, prio
        ),
        mejor_dato AS (
            SELECT
                pe.empresa_id,

                -- NIT y campos registrales: RUES es la única fuente confiable
                NULLIF(COALESCE(
                    MAX(pe.nit) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.nit) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.nit) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.nit) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.nit)
                ), '') AS nit,
                NULLIF(COALESCE(
                    MAX(pe.dv) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.dv)
                ), '') AS dv,
                NULLIF(COALESCE(
                    MAX(pe.id_rm) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.id_rm)
                ), '') AS id_rm,
                NULLIF(COALESCE(
                    MAX(pe.matricula) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.matricula)
                ), '') AS matricula,

                -- Razón social: RUES > serper > google_maps > otros
                COALESCE(
                    MAX(pe.razon_social_original) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.razon_social_original) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.razon_social_original) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.razon_social_original)
                ) AS razon_social,

                -- Nombre comercial: Google Maps > PA > Foursquare > Serper > RUES
                COALESCE(
                    MAX(pe.nombre_original) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.nombre_original) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.nombre_original) FILTER (WHERE pe.fuente = 'foursquare'),
                    MAX(pe.nombre_original) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.nombre_original) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.nombre_original)
                ) AS nombre_comercial,

                -- Nombre normalizado: misma prioridad que nombre comercial
                COALESCE(
                    MAX(pe.nombre_normalizado) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.nombre_normalizado) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.nombre_normalizado) FILTER (WHERE pe.fuente = 'foursquare'),
                    MAX(pe.nombre_normalizado) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.nombre_normalizado) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.nombre_normalizado)
                ) AS nombre_normalizado,

                -- Ubicación: RUES > Google Maps > PA > OSM
                COALESCE(
                    MAX(pe.departamento_norm) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.departamento_norm) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.departamento_norm) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.departamento_norm) FILTER (WHERE pe.fuente = 'openstreetmap'),
                    MAX(pe.departamento_norm)
                ) AS departamento,
                COALESCE(
                    MAX(pe.municipio_norm) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.municipio_norm) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.municipio_norm) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.municipio_norm) FILTER (WHERE pe.fuente = 'openstreetmap'),
                    MAX(pe.municipio_norm)
                ) AS municipio,
                COALESCE(
                    MAX(pe.codigo_dane_municipio) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.codigo_dane_municipio)
                ) AS codigo_dane_municipio,

                -- Dirección: Google Maps > RUES > PA > OSM > otros
                COALESCE(
                    MAX(pe.direccion_original) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.direccion_original) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.direccion_original) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.direccion_original) FILTER (WHERE pe.fuente = 'openstreetmap'),
                    MAX(pe.direccion_original)
                ) AS direccion_principal,
                COALESCE(
                    MAX(pe.direccion_normalizada) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.direccion_normalizada) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.direccion_normalizada) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.direccion_normalizada) FILTER (WHERE pe.fuente = 'openstreetmap'),
                    MAX(pe.direccion_normalizada)
                ) AS direccion_normalizada,

                -- Coordenadas: Google Maps > Foursquare > OSM > Serper (RUES casi no tiene)
                COALESCE(
                    MAX(pe.latitud) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.latitud) FILTER (WHERE pe.fuente = 'foursquare'),
                    MAX(pe.latitud) FILTER (WHERE pe.fuente = 'openstreetmap'),
                    MAX(pe.latitud) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.latitud)
                ) AS latitud,
                COALESCE(
                    MAX(pe.longitud) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.longitud) FILTER (WHERE pe.fuente = 'foursquare'),
                    MAX(pe.longitud) FILTER (WHERE pe.fuente = 'openstreetmap'),
                    MAX(pe.longitud) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.longitud)
                ) AS longitud,

                -- Teléfono: RUES > Google Maps > PA > Serper > Foursquare
                COALESCE(
                    MAX(pe.telefono_normalizado) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.telefono_normalizado) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.telefono_normalizado) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.telefono_normalizado) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.telefono_normalizado) FILTER (WHERE pe.fuente = 'foursquare'),
                    MAX(pe.telefono_normalizado)
                ) AS telefono_principal,

                -- WhatsApp: Google Maps > PA > Serper (RUES no tiene)
                COALESCE(
                    MAX(pe.whatsapp_normalizado) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.whatsapp_normalizado) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.whatsapp_normalizado) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.whatsapp_normalizado)
                ) AS whatsapp_principal,

                -- Email: RUES > Serper > PA > OSM > Google Maps
                COALESCE(
                    MAX(pe.correo_normalizado) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.correo_normalizado) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.correo_normalizado) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.correo_normalizado) FILTER (WHERE pe.fuente = 'openstreetmap'),
                    MAX(pe.correo_normalizado) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.correo_normalizado)
                ) AS correo_principal,

                -- Sitio web: Google Maps > PA > Foursquare > Serper
                COALESCE(
                    MAX(pe.sitio_web) FILTER (WHERE pe.fuente = 'google_maps'),
                    MAX(pe.sitio_web) FILTER (WHERE pe.fuente = 'paginas_amarillas'),
                    MAX(pe.sitio_web) FILTER (WHERE pe.fuente = 'foursquare'),
                    MAX(pe.sitio_web) FILTER (WHERE pe.fuente = 'serper'),
                    MAX(pe.sitio_web)
                ) AS sitio_web,

                -- CIIU: solo RUES tiene clasificación oficial
                COALESCE(
                    MAX(pe.ciiu_codigo) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.ciiu_codigo)
                ) AS cod_ciiu_principal,
                COALESCE(
                    MAX(pe.ciiu_descripcion) FILTER (WHERE pe.fuente = 'rues'),
                    MAX(pe.ciiu_descripcion)
                ) AS desc_ciiu_principal,

                fp.fuente        AS fuente_principal,
                fp.score_origen,
                fp.aprobado_origen

            FROM por_empresa pe
            JOIN fuente_ppal fp ON pe.empresa_id = fp.empresa_id
            GROUP BY pe.empresa_id, fp.fuente, fp.score_origen, fp.aprobado_origen
        )
        SELECT
            md.empresa_id::uuid,
            md.nit, md.dv, md.id_rm, md.matricula,
            md.razon_social,
            md.nombre_comercial,
            coalesce(md.nombre_normalizado, md.nombre_comercial, 'Sin nombre'),
            md.departamento, md.municipio, md.codigo_dane_municipio,
            md.direccion_principal, md.direccion_normalizada,
            md.latitud, md.longitud,
            md.telefono_principal, md.whatsapp_principal, md.correo_principal, md.sitio_web,
            md.cod_ciiu_principal, md.desc_ciiu_principal, NULL AS tipo_negocio,
            NULL AS estado_legal, NULL AS fecha_matricula, NULL AS fecha_renovacion, NULL AS ultimo_ano_renovado,
            md.fuente_principal, gs.fuentes_arr, gs.primera_ext, gs.ultima_ext,
            gs.cnt_fuentes, gs.cnt_matches AS cantidad_matches
        FROM mejor_dato md
        JOIN grupo_stats gs ON md.empresa_id = gs.empresa_id
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    return result.rowcount


def _insertar_telefonos(db) -> int:
    """Inserta todos los teléfonos únicos por empresa"""
    result = db.execute(text("""
        INSERT INTO clean.empresa_telefonos
            (empresa_id, telefono, tipo, fuente, es_principal, confianza)
        SELECT DISTINCT
            er.empresa_id::uuid,
            eu.telefono_normalizado,
            CASE
                WHEN eu.telefono_normalizado ~ '^3[0-9]{9}$' THEN 'celular'
                WHEN eu.telefono_normalizado ~ '^6' THEN 'fijo'
                ELSE 'desconocido'
            END,
            eu.fuente,
            -- es_principal = true si es el teléfono de la empresa en clean.empresas
            eu.telefono_normalizado = c.telefono_principal,
            CASE eu.fuente
                WHEN 'rues' THEN 95
                WHEN 'google_maps' THEN 85
                WHEN 'paginas_amarillas' THEN 80
                ELSE 70
            END
        FROM staging.entidad_resuelta er
        JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
        JOIN clean.empresas c ON er.empresa_id::uuid = c.empresa_id
        WHERE eu.telefono_normalizado IS NOT NULL
          AND eu.telefono_normalizado != ''
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    return result.rowcount


def _insertar_emails(db) -> int:
    """Inserta todos los emails únicos por empresa"""
    result = db.execute(text("""
        INSERT INTO clean.empresa_emails
            (empresa_id, email, fuente, es_principal, confianza)
        SELECT DISTINCT
            er.empresa_id::uuid,
            eu.correo_normalizado,
            eu.fuente,
            eu.correo_normalizado = c.correo_principal,
            CASE eu.fuente
                WHEN 'rues' THEN 95
                WHEN 'serper' THEN 85
                WHEN 'paginas_amarillas' THEN 80
                ELSE 70
            END
        FROM staging.entidad_resuelta er
        JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
        JOIN clean.empresas c ON er.empresa_id::uuid = c.empresa_id
        WHERE eu.correo_normalizado IS NOT NULL
          AND eu.correo_normalizado != ''
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    return result.rowcount


def _insertar_direcciones(db) -> int:
    """Inserta todas las direcciones únicas por empresa"""
    result = db.execute(text("""
        INSERT INTO clean.empresa_direcciones
            (empresa_id, direccion_original, direccion_normalizada,
             departamento, municipio, latitud, longitud,
             fuente, es_principal, confianza)
        SELECT DISTINCT ON (er.empresa_id, eu.direccion_normalizada)
            er.empresa_id::uuid,
            eu.direccion_original,
            eu.direccion_normalizada,
            eu.departamento_norm,
            eu.municipio_norm,
            eu.latitud, eu.longitud,
            eu.fuente,
            eu.direccion_normalizada = c.direccion_normalizada,
            CASE eu.fuente
                WHEN 'google_maps' THEN 90
                WHEN 'rues' THEN 85
                ELSE 70
            END
        FROM staging.entidad_resuelta er
        JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
        JOIN clean.empresas c ON er.empresa_id::uuid = c.empresa_id
        WHERE eu.direccion_normalizada IS NOT NULL
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    return result.rowcount


def _insertar_fuentes(db) -> int:
    """Inserta auditoría de fuentes por empresa"""
    result = db.execute(text("""
        INSERT INTO clean.empresa_fuentes
            (empresa_id, fuente, raw_table, raw_id, run_id,
             fecha_extraccion, score_origen, aprobado_origen,
             regla_principal, score_match)
        SELECT
            er.empresa_id::uuid,
            eu.fuente,
            eu.raw_table,
            eu.raw_id,
            eu.run_id,
            eu.fecha_extraccion,
            eu.score_origen,
            eu.aprobado_origen,
            er.regla_principal,
            er.score_match
        FROM staging.entidad_resuelta er
        JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
        JOIN clean.empresas c ON er.empresa_id::uuid = c.empresa_id
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    return result.rowcount


def _log_merging_stats(db, limite: int = 10):
    """
    Imprime en el log un resumen del field-level merging:
    - Cuántas empresas vinieron de 1, 2, 3+ fuentes
    - Contribución por fuente (qué campos aportó cada API)
    - Ejemplos detallados campo por campo con su fuente de origen
    """

    # ── Bloque 1: Resumen general ─────────────────────────────────────────────
    resumen = db.execute(text("""
        SELECT COALESCE(cantidad_fuentes, 1), COUNT(*) AS empresas
        FROM clean.empresas
        GROUP BY COALESCE(cantidad_fuentes, 1)
        ORDER BY 1
    """)).fetchall()

    logger.info("📊 Resumen de unificación de fuentes:")
    total_unificadas = 0
    for row in resumen:
        icono = "✓" if row[0] == 1 else "🔀"
        logger.info(f"  {icono}  {row[1]:>4} empresas de {row[0]} fuente(s)")
        if row[0] > 1:
            total_unificadas += row[1]
    logger.info(f"  → Total empresas con datos unificados: {total_unificadas}")

    if total_unificadas == 0:
        logger.info("  ℹ️  Ninguna empresa unificó datos de múltiples fuentes en esta ejecución.")
        return

    # ── Bloque 2: Contribución por fuente ────────────────────────────────────
    contrib = db.execute(text("""
        SELECT
            eu.fuente,
            COUNT(*)                            AS registros,
            COUNT(eu.nit)                       AS con_nit,
            COUNT(eu.telefono_normalizado)      AS con_telefono,
            COUNT(eu.whatsapp_normalizado)      AS con_whatsapp,
            COUNT(eu.latitud)                   AS con_coords,
            COUNT(eu.correo_normalizado)        AS con_email,
            COUNT(eu.sitio_web)                 AS con_web,
            COUNT(eu.direccion_normalizada)     AS con_direccion
        FROM staging.entidad_resuelta er
        JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
        JOIN clean.empresas c ON c.empresa_id = er.empresa_id::uuid
        WHERE c.cantidad_fuentes > 1
        GROUP BY eu.fuente
        ORDER BY COUNT(*) DESC
    """)).fetchall()

    logger.info("📋 Contribución por API (solo empresas unificadas):")
    logger.info(f"  {'Fuente':<22} {'Regs':>5}  {'NIT':>5}  {'TEL':>5}  {'WA':>5}  {'GPS':>5}  {'EMAIL':>5}  {'WEB':>5}  {'DIR':>5}")
    logger.info(f"  {'-'*22} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}")
    for row in contrib:
        fuente, regs, nit, tel, wa, coords, email, web, direccion = row
        logger.info(
            f"  {fuente:<22} {regs:>5}  {nit:>5}  {tel:>5}  {wa:>5}  "
            f"{coords:>5}  {email:>5}  {web:>5}  {direccion:>5}"
        )

    # ── Bloque 3: Ejemplos detallados campo por campo ─────────────────────────
    if limite == 0:
        return

    limit_sql = "" if limite == -1 else f"LIMIT {limite}"

    empresas = db.execute(text(f"""
        SELECT
            e.empresa_id::text, e.nombre_comercial, e.municipio,
            e.fuentes, e.cantidad_fuentes, e.cantidad_matches,
            e.nit, e.telefono_principal, e.whatsapp_principal,
            e.latitud, e.correo_principal, e.sitio_web, e.direccion_principal
        FROM clean.empresas e
        WHERE e.cantidad_fuentes > 1
        ORDER BY e.cantidad_fuentes DESC, e.score_calidad DESC NULLS LAST
        {limit_sql}
    """)).fetchall()

    logger.info(f"🔀 Detalle de empresas unificadas ({len(empresas)} ejemplos):")

    LABELS  = ["NIT", "Teléfono", "WhatsApp", "Coordenadas", "Email", "Web", "Dirección"]
    CLEAN_IDX = [6, 7, 8, 9, 10, 11, 12]   # índices en la fila de clean.empresas
    STG_IDX   = [1, 2, 3, 4, 5, 6, 7]       # índices en la fila de staging

    for emp in empresas:
        empresa_id = emp[0]
        nombre     = emp[1] or "Sin nombre"
        municipio  = emp[2] or "?"
        cnt_f      = emp[4]
        cnt_m      = emp[5] or 0

        logger.info(f"  ┌─ '{nombre}' ({municipio})  [{cnt_f} fuentes · {cnt_m} matches]")

        staging_rows = db.execute(text("""
            SELECT eu.fuente, eu.nit, eu.telefono_normalizado,
                   eu.whatsapp_normalizado, eu.latitud,
                   eu.correo_normalizado, eu.sitio_web,
                   eu.direccion_normalizada
            FROM staging.entidad_resuelta er
            JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
            WHERE er.empresa_id::uuid = CAST(:eid AS uuid)
            ORDER BY CASE eu.fuente
                WHEN 'rues'              THEN 1
                WHEN 'google_maps'       THEN 2
                WHEN 'paginas_amarillas' THEN 3
                WHEN 'serper'            THEN 4
                WHEN 'foursquare'        THEN 5
                ELSE 6
            END
        """), {"eid": empresa_id}).fetchall()

        for label, ci, si in zip(LABELS, CLEAN_IDX, STG_IDX):
            valor = emp[ci]
            if valor is None:
                logger.info(f"  │  {label:<14} NULL")
                continue

            # Encontrar qué fuente tiene ese valor en staging
            fuente_origen = "?"
            for srow in staging_rows:
                if srow[si] is not None and str(srow[si]) == str(valor):
                    fuente_origen = srow[0]
                    break

            val_str = str(valor)[:35] + ("..." if len(str(valor)) > 35 else "")
            logger.info(f"  │  {label:<14} {val_str:<38} ← {fuente_origen}")

        logger.info(f"  └{'─'*62}")
