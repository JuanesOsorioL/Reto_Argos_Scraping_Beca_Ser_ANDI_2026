"""
services/calidad.py - Cálculo de score de calidad y aprobación
"""

from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


def calcular_scores_calidad(db) -> dict:
    """
    Calcula score_calidad para cada empresa en clean.empresas y
    actualiza aprobado_argos según el score.

    Criterios de puntuación:
    - Tiene NIT: +25
    - Tiene nombre: +15
    - Tiene municipio: +10
    - Tiene dirección: +10
    - Tiene teléfono: +15
    - Tiene email: +10
    - Tiene coordenadas: +10
    - Fuente RUES: +20
    - 2+ fuentes: +15
    """
    logger.info("📊 Calculando scores de calidad...")

    db.execute(text("""
        UPDATE clean.empresas
        SET score_calidad = (
            -- Datos básicos de identificación
            CASE WHEN nit IS NOT NULL AND nit != '' THEN 25 ELSE 0 END +
            -- Nombre
            CASE WHEN nombre_normalizado IS NOT NULL AND nombre_normalizado != '' THEN 15 ELSE 0 END +
            -- Ubicación
            CASE WHEN municipio IS NOT NULL THEN 10 ELSE 0 END +
            -- Dirección
            CASE WHEN direccion_principal IS NOT NULL THEN 10 ELSE 0 END +
            -- Contacto teléfono
            CASE WHEN telefono_principal IS NOT NULL THEN 15 ELSE 0 END +
            -- Contacto email
            CASE WHEN correo_principal IS NOT NULL THEN 10 ELSE 0 END +
            -- Coordenadas geo
            CASE WHEN latitud IS NOT NULL AND longitud IS NOT NULL THEN 10 ELSE 0 END +
            -- Calidad de fuente
            CASE WHEN 'rues' = ANY(fuentes) THEN 20 ELSE 0 END +
            -- Múltiples fuentes
            CASE WHEN cantidad_fuentes >= 2 THEN 15 ELSE 0 END
        )
        WHERE TRUE
    """))

    db.execute(text("""
        UPDATE clean.empresas
        SET aprobado_argos = CASE
            WHEN score_calidad >= 80 THEN TRUE
            ELSE FALSE
        END
    """))

    db.execute(text("""
        UPDATE clean.empresas c
        SET cantidad_matches = (
            SELECT COUNT(*)
            FROM staging.posibles_matches pm
            JOIN staging.entidad_resuelta er_a ON pm.staging_id_a = er_a.staging_id
            WHERE er_a.empresa_id::uuid = c.empresa_id
              AND pm.decision IN ('auto_match', 'ia_match')
        )
    """))

    db.commit()

    stats = db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE aprobado_argos = true) AS aprobadas,
            COUNT(*) FILTER (WHERE score_calidad BETWEEN 60 AND 79) AS revision,
            COUNT(*) FILTER (WHERE score_calidad < 60) AS rechazadas,
            round(avg(score_calidad)::numeric, 1) AS score_promedio,
            min(score_calidad) AS score_min,
            max(score_calidad) AS score_max
        FROM clean.empresas
    """)).fetchone()

    result = {
        "total": stats[0],
        "aprobadas_argos": stats[1],
        "en_revision": stats[2],
        "rechazadas": stats[3],
        "score_promedio": float(stats[4]) if stats[4] else 0,
        "score_min": stats[5],
        "score_max": stats[6],
    }

    logger.info(
        f"✅ Scoring completado. "
        f"Aprobadas: {result['aprobadas_argos']}, "
        f"Score promedio: {result['score_promedio']}"
    )
    return result


def distribucion_scores(db) -> dict:
    """Retorna distribución de scores por rangos"""
    rows = db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE score_calidad >= 90) AS rango_90_100,
            COUNT(*) FILTER (WHERE score_calidad BETWEEN 80 AND 89) AS rango_80_89,
            COUNT(*) FILTER (WHERE score_calidad BETWEEN 70 AND 79) AS rango_70_79,
            COUNT(*) FILTER (WHERE score_calidad BETWEEN 60 AND 69) AS rango_60_69,
            COUNT(*) FILTER (WHERE score_calidad < 60) AS rango_menos_60
        FROM clean.empresas
    """)).fetchone()

    return {
        "90-100": rows[0] or 0,
        "80-89": rows[1] or 0,
        "70-79": rows[2] or 0,
        "60-69": rows[3] or 0,
        "<60": rows[4] or 0,
    }
