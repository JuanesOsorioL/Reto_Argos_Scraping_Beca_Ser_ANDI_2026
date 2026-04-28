"""
services/matching.py - Detección de duplicados con múltiples reglas
"""

from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


def detectar_todos_los_matches(db) -> dict:
    """
    Ejecuta todas las reglas de deduplicación en orden de prioridad.
    Retorna conteos por regla.
    """
    logger.info("🔍 Iniciando detección de duplicados...")
    conteos = {}

    # Reglas fuertes (score 100) → auto_match
    conteos['mismo_nit'] = _detectar_matches_nit(db)
    conteos['mismo_id_rm'] = _detectar_matches_id_rm(db)

    # Reglas media-altas (score 85) → auto_match
    conteos['mismo_email'] = _detectar_matches_email(db)
    conteos['mismo_telefono'] = _detectar_matches_telefono(db)

    # Reglas medias (score 70-85) → pendiente_revision
    conteos['nombre_similar'] = _detectar_matches_nombre(db)
    conteos['direccion_similar'] = _detectar_matches_direccion(db)
    conteos['coordenadas'] = _detectar_matches_coordenadas(db)

    total = sum(conteos.values())
    logger.info(f"✅ Detección completada. Total matches: {total}")
    return conteos


def _detectar_matches_nit(db) -> int:
    """Regla 1: Mismo NIT → score 100, auto_match"""
    result = db.execute(text("""
        INSERT INTO staging.posibles_matches
            (staging_id_a, staging_id_b, regla_match, score_match, decision, razon_decision)
        SELECT
            a.staging_id,
            b.staging_id,
            'MISMO_NIT',
            100,
            'auto_match',
            'NIT idéntico - misma empresa legalmente'
        FROM staging.empresas_unificadas a
        JOIN staging.empresas_unificadas b
            ON a.match_key_nit = b.match_key_nit
            AND a.staging_id < b.staging_id
        WHERE a.match_key_nit IS NOT NULL
          AND a.match_key_nit != ''
          AND length(a.match_key_nit) >= 8
        ON CONFLICT (staging_id_a, staging_id_b) DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ MISMO_NIT: {n} matches")
    return n


def _detectar_matches_id_rm(db) -> int:
    """Regla 2: Mismo ID_RM (RUES) → score 100, auto_match"""
    result = db.execute(text("""
        INSERT INTO staging.posibles_matches
            (staging_id_a, staging_id_b, regla_match, score_match, decision, razon_decision)
        SELECT
            a.staging_id,
            b.staging_id,
            'MISMO_ID_RM',
            100,
            'auto_match',
            'ID RUES idéntico'
        FROM staging.empresas_unificadas a
        JOIN staging.empresas_unificadas b
            ON a.id_rm = b.id_rm
            AND a.staging_id < b.staging_id
        WHERE a.id_rm IS NOT NULL
          AND a.id_rm != ''
        ON CONFLICT (staging_id_a, staging_id_b) DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ MISMO_ID_RM: {n} matches")
    return n


def _detectar_matches_email(db) -> int:
    """Regla 3: Mismo email + municipio → score 85, auto_match"""
    result = db.execute(text("""
        INSERT INTO staging.posibles_matches
            (staging_id_a, staging_id_b, regla_match, score_match, decision, razon_decision)
        SELECT
            a.staging_id,
            b.staging_id,
            'MISMO_EMAIL_MUNICIPIO',
            85,
            'auto_match',
            'Email idéntico en mismo municipio'
        FROM staging.empresas_unificadas a
        JOIN staging.empresas_unificadas b
            ON a.match_key_email = b.match_key_email
            AND a.municipio_norm = b.municipio_norm
            AND a.staging_id < b.staging_id
        WHERE a.match_key_email IS NOT NULL
          AND a.match_key_email != ''
        ON CONFLICT (staging_id_a, staging_id_b) DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ MISMO_EMAIL_MUNICIPIO: {n} matches")
    return n


def _detectar_matches_telefono(db) -> int:
    """Regla 4: Mismo teléfono + municipio → score 85, auto_match"""
    result = db.execute(text("""
        INSERT INTO staging.posibles_matches
            (staging_id_a, staging_id_b, regla_match, score_match, decision, razon_decision)
        SELECT
            a.staging_id,
            b.staging_id,
            'MISMO_TELEFONO_MUNICIPIO',
            85,
            'auto_match',
            'Teléfono idéntico en mismo municipio'
        FROM staging.empresas_unificadas a
        JOIN staging.empresas_unificadas b
            ON a.match_key_telefono = b.match_key_telefono
            AND a.municipio_norm = b.municipio_norm
            AND a.staging_id < b.staging_id
        WHERE a.match_key_telefono IS NOT NULL
          AND a.match_key_telefono != ''
          AND length(a.match_key_telefono) >= 7
        ON CONFLICT (staging_id_a, staging_id_b) DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ MISMO_TELEFONO_MUNICIPIO: {n} matches")
    return n


def _detectar_matches_nombre(db) -> int:
    """Regla 5: Nombre parecido + municipio → score 70-85, pendiente_revision"""
    result = db.execute(text("""
        INSERT INTO staging.posibles_matches
            (staging_id_a, staging_id_b, regla_match, score_match, decision, razon_decision)
        SELECT
            a.staging_id,
            b.staging_id,
            'NOMBRE_SIMILAR_MUNICIPIO',
            CASE
                WHEN similarity(a.nombre_normalizado, b.nombre_normalizado) >= 0.85 THEN 85
                WHEN similarity(a.nombre_normalizado, b.nombre_normalizado) >= 0.80 THEN 80
                ELSE 75
            END,
            'pendiente_revision',
            'Nombres similares en mismo municipio'
        FROM staging.empresas_unificadas a
        JOIN staging.empresas_unificadas b
            ON a.municipio_norm = b.municipio_norm
            AND a.staging_id < b.staging_id
        WHERE a.nombre_normalizado IS NOT NULL
          AND b.nombre_normalizado IS NOT NULL
          AND length(a.nombre_normalizado) >= 4
          AND length(b.nombre_normalizado) >= 4
          AND similarity(a.nombre_normalizado, b.nombre_normalizado) >= 0.75
          AND NOT EXISTS (
              SELECT 1 FROM staging.posibles_matches pm
              WHERE pm.staging_id_a = a.staging_id
                AND pm.staging_id_b = b.staging_id
          )
        ON CONFLICT (staging_id_a, staging_id_b) DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ NOMBRE_SIMILAR_MUNICIPIO: {n} matches")
    return n


def _detectar_matches_direccion(db) -> int:
    """Regla 6: Dirección parecida + municipio → score 70, pendiente_revision"""
    result = db.execute(text("""
        INSERT INTO staging.posibles_matches
            (staging_id_a, staging_id_b, regla_match, score_match, decision, razon_decision)
        SELECT
            a.staging_id,
            b.staging_id,
            'DIRECCION_SIMILAR_MUNICIPIO',
            70,
            'pendiente_revision',
            'Direcciones similares en mismo municipio'
        FROM staging.empresas_unificadas a
        JOIN staging.empresas_unificadas b
            ON a.municipio_norm = b.municipio_norm
            AND a.staging_id < b.staging_id
        WHERE a.direccion_normalizada IS NOT NULL
          AND b.direccion_normalizada IS NOT NULL
          AND length(a.direccion_normalizada) >= 8
          AND similarity(a.direccion_normalizada, b.direccion_normalizada) >= 0.80
          AND NOT EXISTS (
              SELECT 1 FROM staging.posibles_matches pm
              WHERE pm.staging_id_a = a.staging_id
                AND pm.staging_id_b = b.staging_id
          )
        ON CONFLICT (staging_id_a, staging_id_b) DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ DIRECCION_SIMILAR_MUNICIPIO: {n} matches")
    return n


def _detectar_matches_coordenadas(db) -> int:
    """Regla 7: Coordenadas cercanas (<50m) + nombre parecido → score 80"""
    result = db.execute(text("""
        INSERT INTO staging.posibles_matches
            (staging_id_a, staging_id_b, regla_match, score_match, decision, razon_decision)
        SELECT
            a.staging_id,
            b.staging_id,
            'COORDENADAS_CERCANAS_NOMBRE',
            80,
            'pendiente_revision',
            'Ubicaciones cercanas (<50m) con nombre similar'
        FROM staging.empresas_unificadas a
        JOIN staging.empresas_unificadas b ON a.staging_id < b.staging_id
        WHERE a.latitud IS NOT NULL AND a.longitud IS NOT NULL
          AND b.latitud IS NOT NULL AND b.longitud IS NOT NULL
          AND abs(a.latitud - b.latitud) < 0.001
          AND abs(a.longitud - b.longitud) < 0.001
          AND (
              acos(LEAST(1.0,
                  sin(radians(a.latitud))*sin(radians(b.latitud)) +
                  cos(radians(a.latitud))*cos(radians(b.latitud))*
                  cos(radians(a.longitud - b.longitud))
              )) * 6371000
          ) < 50
          AND similarity(
              coalesce(a.nombre_normalizado, ''),
              coalesce(b.nombre_normalizado, '')
          ) >= 0.70
          AND NOT EXISTS (
              SELECT 1 FROM staging.posibles_matches pm
              WHERE pm.staging_id_a = a.staging_id
                AND pm.staging_id_b = b.staging_id
          )
        ON CONFLICT (staging_id_a, staging_id_b) DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ COORDENADAS_CERCANAS_NOMBRE: {n} matches")
    return n


def obtener_stats_matches(db) -> dict:
    """Retorna estadísticas de posibles_matches"""
    row = db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE decision = 'auto_match') as auto_match,
            COUNT(*) FILTER (WHERE decision = 'no_match') as no_match,
            COUNT(*) FILTER (WHERE decision = 'pendiente_revision') as pendiente,
            COUNT(*) FILTER (WHERE decision = 'ia_match') as ia_match,
            COUNT(*) as total
        FROM staging.posibles_matches
    """)).fetchone()
    return {
        'auto_match': row[0] or 0,
        'no_match': row[1] or 0,
        'pendiente_revision': row[2] or 0,
        'ia_match': row[3] or 0,
        'total': row[4] or 0,
    }
