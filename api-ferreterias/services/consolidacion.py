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


def consolidar_empresas(db) -> dict:
    """
    Fase de consolidación:
    1. Crear staging.entidad_resuelta (grupos de staging_id que son el mismo negocio)
    2. Insertar en clean.empresas
    3. Insertar en tablas auxiliares
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
    """Inserta empresas consolidadas en clean.empresas"""

    # Limpiar clean para re-inserción
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
                count(DISTINCT eu.fuente) AS cnt_fuentes,
                min(eu.fecha_extraccion) AS primera_ext,
                max(eu.fecha_extraccion) AS ultima_ext
            FROM staging.entidad_resuelta er
            JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
            GROUP BY er.empresa_id
        ),
        mejor_dato AS (
            SELECT DISTINCT ON (er.empresa_id)
                er.empresa_id,
                eu.nit, eu.dv, eu.id_rm, eu.matricula,
                eu.razon_social_original AS razon_social,
                eu.nombre_original AS nombre_comercial,
                eu.nombre_normalizado,
                eu.departamento_norm AS departamento,
                eu.municipio_norm AS municipio,
                eu.codigo_dane_municipio,
                eu.direccion_original AS direccion_principal,
                eu.direccion_normalizada,
                eu.latitud, eu.longitud,
                eu.telefono_normalizado AS telefono_principal,
                eu.whatsapp_normalizado AS whatsapp_principal,
                eu.correo_normalizado AS correo_principal,
                eu.sitio_web,
                eu.ciiu_codigo AS cod_ciiu_principal,
                eu.ciiu_descripcion AS desc_ciiu_principal,
                eu.fuente AS fuente_principal,
                eu.score_origen, eu.aprobado_origen
            FROM staging.entidad_resuelta er
            JOIN staging.empresas_unificadas eu ON er.staging_id = eu.staging_id
            ORDER BY er.empresa_id,
                CASE eu.fuente
                    WHEN 'rues'             THEN 1
                    WHEN 'google_maps'      THEN 2
                    WHEN 'paginas_amarillas' THEN 3
                    WHEN 'serper'           THEN 4
                    WHEN 'foursquare'       THEN 5
                    ELSE 6
                END
        )
        SELECT
            md.empresa_id::uuid,
            NULLIF(md.nit, ''), NULLIF(md.dv, ''), NULLIF(md.id_rm, ''), NULLIF(md.matricula, ''),
            md.razon_social, md.nombre_comercial,
            coalesce(md.nombre_normalizado, md.nombre_comercial, 'Sin nombre'),
            md.departamento, md.municipio, md.codigo_dane_municipio,
            md.direccion_principal, md.direccion_normalizada,
            md.latitud, md.longitud,
            md.telefono_principal, md.whatsapp_principal, md.correo_principal, md.sitio_web,
            md.cod_ciiu_principal, md.desc_ciiu_principal, NULL AS tipo_negocio,
            NULL AS estado_legal, NULL AS fecha_matricula, NULL AS fecha_renovacion, NULL AS ultimo_ano_renovado,
            md.fuente_principal, gs.fuentes_arr, gs.primera_ext, gs.ultima_ext,
            gs.cnt_fuentes, NULL AS cantidad_matches
        FROM mejor_dato md
        JOIN grupo_stats gs ON md.empresa_id = gs.empresa_id
        ON CONFLICT (empresa_id) DO NOTHING
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
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    return result.rowcount
