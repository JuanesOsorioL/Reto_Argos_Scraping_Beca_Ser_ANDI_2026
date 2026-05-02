"""
workers/etl_loader_v2.py

ETL actualizado con:
1. Filtro por municipios seleccionados (del body del request)
2. Manejo correcto de RUES inactivos (se guardan con penalización)
3. RUES NO filtra por municipio (trae todo) — las otras sí filtran
4. Sucursales (mismo nombre, diferente municipio) = empresas separadas ✓
"""

import os
import uuid
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Schema de tablas fuente. Cambia aqui o en .env con RAW_SCHEMA=rawantes
RAW_SCHEMA = os.getenv("RAW_SCHEMA", "raw")

DEFAULT_KEYWORDS_RUES = [
    "ferreterias",
    "depositos de materiales",
    "materiales de construccion",
    "cemento",
    "venta de cemento",
    "distribuidoras de cemento",
    "hierro y cemento",
    "concreto",
    "agregados para construccion",
    "bloqueras",
]


def cargar_todo_a_staging(
    db,
    limpiar_antes: bool = True,
    municipios: list[dict] | None = None,
    keywords_rues: list[str] | None = None,
) -> dict:
    """
    Carga todas las fuentes raw.* a staging.empresas_unificadas.
    
    Args:
        municipios: Lista de {"municipio": str, "departamento": str}
                    Si None o vacío → carga TODOS los municipios.
                    Si tiene valores → filtra por esos municipios en las APIs
                    que sí soportan filtro (Google, PA, Foursquare, OSM, Serper).
                    RUES siempre carga todo y se filtra en normalización.
    
    Nota sobre sucursales (Páginas Amarillas y otras):
        "Ferretería El Diamante" en Cali ≠ "Ferretería El Diamante" en Bogotá
        Son staging_ids distintos que NO matchean entre sí porque la regla
        NOMBRE_SIMILAR_MUNICIPIO requiere mismo municipio.
        Si comparten NIT → se unen como misma empresa con múltiples ubicaciones.
    """
    if limpiar_antes:
        logger.info("🗑️ Limpiando staging anterior...")
        db.execute(text("""
            TRUNCATE staging.campos_dudosos, staging.ia_validaciones,
                     staging.posibles_matches, staging.entidad_resuelta,
                     staging.empresas_unificadas CASCADE
        """))
        db.commit()

    run_id = str(uuid.uuid4())

    # Construir listas de municipios para filtro SQL
    municipios_norm = _normalizar_lista_municipios(municipios)
    tiene_filtro = bool(municipios_norm)

    if tiene_filtro:
        logger.info(f"📍 Filtrando por {len(municipios_norm)} municipios: {municipios_norm[:5]}{'...' if len(municipios_norm)>5 else ''}")
    else:
        logger.info("🌎 Sin filtro de municipio — cargando todos los registros")

    conteos = {}
    conteos['google_maps']       = _cargar_google_maps(db, run_id, municipios_norm)
    conteos['paginas_amarillas'] = _cargar_paginas_amarillas(db, run_id, municipios_norm)
    conteos['foursquare']        = _cargar_foursquare(db, run_id, municipios_norm)
    conteos['overpass']          = _cargar_overpass(db, run_id, municipios_norm)
    conteos['rues']              = _cargar_rues(db, run_id, municipios_norm, keywords_rues)
    conteos['serper']            = _cargar_serper(db, run_id, municipios_norm)

    # Excluir empresas en liquidación si la bandera está desactivada
    incluir_liquidacion = os.getenv("INCLUIR_EN_LIQUIDACION", "true").lower() == "true"
    if not incluir_liquidacion:
        result = db.execute(text(r"""
            DELETE FROM staging.empresas_unificadas
            WHERE nombre_original ~* 'en\s+liquidaci[oó]n'
               OR razon_social_original ~* 'en\s+liquidaci[oó]n'
        """))
        db.commit()
        eliminadas = result.rowcount
        if eliminadas:
            logger.info(f"  🗑️ Excluidas {eliminadas} empresas en liquidación (INCLUIR_EN_LIQUIDACION=false)")

    total = sum(conteos.values())
    logger.info(f"✅ Carga completada. Total en staging: {total}")
    return conteos


def _normalizar_lista_municipios(municipios: list[dict] | None) -> list[str]:
    """
    Convierte [{"municipio": "Medellín", "departamento": "Antioquia"}, ...]
    en ["medellin", "bogota", ...] para comparación normalizada.
    """
    if not municipios:
        return []

    import unicodedata

    def norm(s: str) -> str:
        s = s.strip().lower()
        nfkd = unicodedata.normalize('NFKD', s)
        return ''.join(c for c in nfkd if not unicodedata.combining(c))

    return [norm(m.get("municipio", "")) for m in municipios if m.get("municipio")]


def _where_municipio(municipios_norm: list[str], campo: str = "municipio") -> tuple[str, dict]:
    """
    Genera la cláusula WHERE para filtrar por municipios.
    Usa unaccent + lower para comparación robusta.

    Si la lista está vacía, no filtra (trae todo).
    """
    if not municipios_norm:
        return "", {}

    placeholders = ", ".join([f"'{m}'" for m in municipios_norm])
    where = f"AND unaccent(lower(trim({campo}))) = ANY(ARRAY[{placeholders}])"
    return where, {}


def _normalizar_camara_rues_sql(campo: str) -> str:
    """
    Genera expresión SQL que normaliza nombres de cámaras RUES:
      "FLORENCIA PARA EL CAQUETA"     → "florencia"
      "MEDELLIN PARA ANTIOQUIA"       → "medellin"
      "SANTA MARTA PARA EL MAGDALENA" → "santa marta"
      "SUR Y ORIENTE DEL TOLIMA"      → "tolima"
      "SINCELEJO"                     → "sincelejo"

    Nota: lower() se aplica ANTES de split_part para que el delimitador
    siempre sea minúscula, independiente de cómo llegue el valor desde RUES.
    """
    return f"""unaccent(trim(
        CASE
            WHEN {campo} ILIKE '% para %'
                THEN split_part(lower({campo}), ' para ', 1)
            WHEN {campo} ILIKE '% del %'
                THEN split_part(lower({campo}), ' del ', 2)
            WHEN {campo} ILIKE '% de la %'
                THEN split_part(lower({campo}), ' de la ', 2)
            WHEN {campo} ILIKE '% de los %'
                THEN split_part(lower({campo}), ' de los ', 2)
            ELSE lower({campo})
        END
    ))"""


def _where_municipio_rues(municipios_norm: list[str]) -> tuple[str, dict]:
    """
    WHERE especial para RUES: normaliza el nombre de cámara/municipio
    antes de comparar, extrayendo solo la ciudad o departamento principal.
    """
    if not municipios_norm:
        return "", {}

    placeholders = ", ".join([f"'{m}'" for m in municipios_norm])
    expr_municipio = _normalizar_camara_rues_sql("municipio")
    expr_camara    = _normalizar_camara_rues_sql("camara")

    where = f"""AND (
        {expr_municipio} = ANY(ARRAY[{placeholders}])
        OR {expr_camara}  = ANY(ARRAY[{placeholders}])
    )"""
    return where, {}


def _cargar_google_maps(db, run_id: str, municipios_norm: list[str]) -> int:
    """Google Maps → staging. Filtra por municipio si se especificó."""
    try:
        where_mun, _ = _where_municipio(municipios_norm, "municipio")
        result = db.execute(text(f"""
            INSERT INTO staging.empresas_unificadas (
                fuente, raw_table, raw_id, run_id, fecha_extraccion, raw_hash_id,
                nit, nombre_original, departamento_original, municipio_original,
                direccion_original, latitud, longitud,
                telefono_original, whatsapp_original, correo_original, sitio_web,
                categoria_original, descripcion, keyword_busqueda,
                score_origen, aprobado_origen
            )
            SELECT
                'google_maps','{RAW_SCHEMA}.google_maps_ferreterias', id,   CAST(:run_id AS uuid),
                fecha_extraccion, hash_id, nit, nombre,
                departamento, municipio, direccion, latitud, longitud,
                telefono, whatsapp, correo_electronico, url,
                CASE WHEN categorias_maps IS NOT NULL
                     THEN array_to_string(categorias_maps, ', ')
                     ELSE NULL END,
                descripcion, keyword_busqueda, score, aprobado_argos
            FROM {RAW_SCHEMA}.google_maps_ferreterias
            WHERE nombre IS NOT NULL {where_mun}
            ON CONFLICT DO NOTHING
        """), {"run_id": run_id})
        db.commit()
        n = result.rowcount
        logger.info(f"  ✓ Google Maps: {n} registros")
        return n
    except Exception as e:
        logger.warning(f"  ⚠ Google Maps: {e}")
        db.rollback()
        return 0


def _cargar_paginas_amarillas(db, run_id: str, municipios_norm: list[str]) -> int:
    """
    Páginas Amarillas → staging.
    
    SUCURSALES: Si "Ferretería X" aparece en Cali Y Bogotá, se cargan
    como DOS staging_ids distintos. El matching por municipio garantiza
    que NO se unan a menos que compartan NIT o teléfono.
    """
    try:
        where_mun, _ = _where_municipio(municipios_norm, "municipio")
        result = db.execute(text(f"""
            INSERT INTO staging.empresas_unificadas (
                fuente, raw_table, raw_id, run_id, fecha_extraccion, raw_hash_id,
                nit, nombre_original, departamento_original, municipio_original,
                direccion_original, latitud, longitud,
                telefono_original, whatsapp_original, correo_original,
                descripcion, keyword_busqueda, score_origen, aprobado_origen
            )
            SELECT
                'paginas_amarillas','{RAW_SCHEMA}.paginas_amarillas_ferreterias', id,   CAST(:run_id AS uuid),
                fecha_extraccion, hash_id, nit, nombre,
                departamento, municipio, direccion, latitud, longitud,
                telefono, whatsapp, correo_electronico,
                descripcion, keyword_busqueda, score, aprobado_argos
            FROM {RAW_SCHEMA}.paginas_amarillas_ferreterias
            WHERE nombre IS NOT NULL {where_mun}
            ON CONFLICT DO NOTHING
        """), {"run_id": run_id})
        db.commit()
        n = result.rowcount
        logger.info(f"  ✓ Páginas Amarillas: {n} registros (incl. posibles sucursales)")
        return n
    except Exception as e:
        logger.warning(f"  ⚠ Páginas Amarillas: {e}")
        db.rollback()
        return 0


def _cargar_foursquare(db, run_id: str, municipios_norm: list[str]) -> int:
    try:
        where_mun, _ = _where_municipio(municipios_norm, "municipio")
        result = db.execute(text(f"""
            INSERT INTO staging.empresas_unificadas (
                fuente, raw_table, raw_id, run_id, fecha_extraccion, raw_hash_id,
                nombre_original, departamento_original, municipio_original,
                direccion_original, latitud, longitud,
                telefono_original, correo_original, sitio_web,
                categoria_original, descripcion, keyword_busqueda,
                score_origen, aprobado_origen
            )
            SELECT
                'foursquare','{RAW_SCHEMA}.foursquare_ferreterias', id,   CAST(:run_id AS uuid),
                fecha_extraccion, hash_id, nombre,
                departamento, municipio, direccion, latitud, longitud,
                telefono, correo_electronico, fsq_website,
                fsq_categories, fsq_description, keyword_busqueda,
                score, aprobado_argos
            FROM {RAW_SCHEMA}.foursquare_ferreterias
            WHERE nombre IS NOT NULL {where_mun}
            ON CONFLICT DO NOTHING
        """), {"run_id": run_id})
        db.commit()
        n = result.rowcount
        logger.info(f"  ✓ Foursquare: {n} registros")
        return n
    except Exception as e:
        logger.warning(f"  ⚠ Foursquare: {e}")
        db.rollback()
        return 0


def _cargar_overpass(db, run_id: str, municipios_norm: list[str]) -> int:
    try:
        where_mun, _ = _where_municipio(municipios_norm, "municipio")
        result = db.execute(text(f"""
            INSERT INTO staging.empresas_unificadas (
                fuente, raw_table, raw_id, run_id, fecha_extraccion, raw_hash_id,
                nombre_original, departamento_original, municipio_original,
                direccion_original, latitud, longitud,
                telefono_original, correo_original, sitio_web,
                score_origen, aprobado_origen
            )
            SELECT
                'openstreetmap','{RAW_SCHEMA}.overpass_ferreterias', id,   CAST(:run_id AS uuid),
                fecha_extraccion, hash_id, nombre,
                departamento, municipio, direccion, latitud, longitud,
                telefono, correo_electronico, website,
                score, aprobado_argos
            FROM {RAW_SCHEMA}.overpass_ferreterias
            WHERE nombre IS NOT NULL {where_mun}
            ON CONFLICT DO NOTHING
        """), {"run_id": run_id})
        db.commit()
        n = result.rowcount
        logger.info(f"  ✓ Overpass/OSM: {n} registros")
        return n
    except Exception as e:
        logger.warning(f"  ⚠ Overpass: {e}")
        db.rollback()
        return 0


def _cargar_rues(db, run_id: str, municipios_norm: list[str], keywords_rues: list[str] | None = None) -> int:
    """
    RUES → staging.

    Usa DISTINCT ON (nit) para evitar que la misma empresa aparezca
    múltiples veces por haber sido encontrada con distintas keywords.
    Cuando no hay NIT se usa el id de la fila como partición (sin dedup).

    - keywords_rues: lista de keywords a incluir. None = usar DEFAULT_KEYWORDS_RUES.
    """
    try:
        where_mun, _ = _where_municipio_rues(municipios_norm)

        kw_list = keywords_rues if keywords_rues else DEFAULT_KEYWORDS_RUES
        kw_placeholders = ", ".join([f"'{k}'" for k in kw_list])
        where_kw = f"AND keyword_busqueda = ANY(ARRAY[{kw_placeholders}])"

        result = db.execute(text(f"""
            INSERT INTO staging.empresas_unificadas (
                fuente, raw_table, raw_id, run_id, fecha_extraccion,
                nit, dv, id_rm, matricula,
                nombre_original, razon_social_original,
                departamento_original, municipio_original,
                direccion_original, latitud, longitud,
                telefono_original, correo_original,
                ciiu_codigo, ciiu_descripcion, keyword_busqueda,
                score_origen, aprobado_origen
            )
            SELECT
                'rues', '{RAW_SCHEMA}.rues_detalle', id, CAST(:run_id AS uuid), fecha_extraccion,
                nit, dv, id_rm, matricula,
                nombre, razon_social,
                departamento, municipio,
                coalesce(dir_comercial, direccion),
                latitud, longitud,
                coalesce(tel_com_1, telefono),
                coalesce(email_com, correo_electronico),
                cod_ciiu_pri, desc_ciiu_pri, keyword_busqueda,
                CASE
                    WHEN lower(coalesce(estado, '')) = ANY(ARRAY[
                        'cancelado','disuelto','liquidado','inactivo',
                        'cancelada','disuelta','liquidada','suspendido'
                    ]) THEN GREATEST(0, coalesce(score, 50) - 15)
                    ELSE coalesce(score, 50)
                END,
                CASE
                    WHEN lower(coalesce(estado, '')) = ANY(ARRAY[
                        'cancelado','disuelto','liquidado','liquidada','disuelta'
                    ]) THEN false
                    ELSE true
                END
            FROM (
                SELECT DISTINCT ON (COALESCE(nit, id::text)) *
                FROM {RAW_SCHEMA}.rues_detalle
                WHERE (nombre IS NOT NULL OR razon_social IS NOT NULL)
                {where_mun}
                {where_kw}
                ORDER BY
                    COALESCE(nit, id::text),
                    -- Activos primero
                    CASE WHEN lower(coalesce(estado, '')) = ANY(ARRAY[
                        'cancelado','disuelto','liquidado','liquidada','disuelta','inactivo','cancelada','suspendido'
                    ]) THEN 0 ELSE 1 END DESC,
                    COALESCE(score, 0) DESC
            ) sub
            ON CONFLICT DO NOTHING
        """), {"run_id": run_id})
        db.commit()

        n = result.rowcount

        inactivos = db.execute(text("""
            SELECT COUNT(*) FROM staging.empresas_unificadas
            WHERE fuente = 'rues' AND aprobado_origen = false
        """)).scalar() or 0

        logger.info(f"  ✓ RUES: {n} registros ({inactivos} inactivos, incluidos con penalización)")
        return n

    except Exception as e:
        logger.warning(f"  ⚠ RUES: {e}")
        db.rollback()
        return 0


def _cargar_serper(db, run_id: str, municipios_norm: list[str]) -> int:
    try:
        where_mun, _ = _where_municipio(municipios_norm, "municipio")
        result = db.execute(text(f"""
            INSERT INTO staging.empresas_unificadas (
                fuente, raw_table, raw_id, run_id, fecha_extraccion, raw_hash_id,
                nit, nombre_original, departamento_original, municipio_original,
                direccion_original, latitud, longitud,
                telefono_original, whatsapp_original, correo_original, sitio_web,
                descripcion, keyword_busqueda, score_origen, aprobado_origen
            )
            SELECT
                'serper','{RAW_SCHEMA}.serper_resultados_construccion', id,   CAST(:run_id AS uuid),
                fecha_extraccion, hash_id, nit, nombre,
                departamento, municipio, direccion, latitud, longitud,
                coalesce(scraped_phone, telefono),
                coalesce(scraped_whatsapp, whatsapp),
                coalesce(scraped_email, correo_electronico),
                url, snippet, keyword_busqueda, score, aprobado_argos
            FROM {RAW_SCHEMA}.serper_resultados_construccion
            WHERE nombre IS NOT NULL {where_mun}
            ON CONFLICT DO NOTHING
        """), {"run_id": run_id})
        db.commit()
        n = result.rowcount
        logger.info(f"  ✓ Serper: {n} registros")
        return n
    except Exception as e:
        logger.warning(f"  ⚠ Serper: {e}")
        db.rollback()
        return 0
