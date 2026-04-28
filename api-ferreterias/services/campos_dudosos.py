"""
services/campos_dudosos.py - Detección de campos conflictivos
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import text

logger = logging.getLogger(__name__)


def detectar_todos_campos_dudosos(db) -> dict:
    """Detecta todos los tipos de campos dudosos en staging"""
    logger.info("🔎 Detectando campos dudosos...")
    conteos = {}

    conteos['nombre'] = _detectar_conflictos_nombre(db)
    conteos['telefono'] = _detectar_conflictos_telefono(db)
    conteos['email'] = _detectar_conflictos_email(db)
    conteos['municipio'] = _detectar_conflictos_municipio(db)
    conteos['formatos_invalidos'] = _detectar_formatos_invalidos(db)

    total = sum(conteos.values())
    logger.info(f"✅ Campos dudosos detectados: {total}")
    return conteos


def _detectar_conflictos_nombre(db) -> int:
    """Detecta nombres conflictivos para el mismo NIT"""
    result = db.execute(text("""
        INSERT INTO staging.campos_dudosos
            (staging_id, campo, valor_conflictivo, valores_alternativos,
             fuentes_conflictivas, tipo_conflicto, severidad)
        SELECT DISTINCT
            e.staging_id,
            'nombre',
            e.nombre_normalizado,
            n.nombres,
            n.fuentes,
            'inconsistencia_multifuente',
            'media'
        FROM staging.empresas_unificadas e
        JOIN (
            SELECT
                nit,
                array_agg(DISTINCT nombre_normalizado) AS nombres,
                array_agg(DISTINCT fuente) AS fuentes
            FROM staging.empresas_unificadas
            WHERE nit IS NOT NULL AND nombre_normalizado IS NOT NULL
            GROUP BY nit
            HAVING count(DISTINCT nombre_normalizado) > 1
        ) n ON e.nit = n.nit
        WHERE e.nombre_normalizado IS NOT NULL
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ Conflictos nombre: {n}")
    return n


def _detectar_conflictos_telefono(db) -> int:
    """Detecta teléfonos conflictivos para mismo NIT"""
    result = db.execute(text("""
        INSERT INTO staging.campos_dudosos
            (staging_id, campo, valor_conflictivo, valores_alternativos,
             fuentes_conflictivas, tipo_conflicto, severidad)
        SELECT DISTINCT
            e.staging_id,
            'telefono',
            e.telefono_normalizado,
            t.telefonos,
            t.fuentes,
            'inconsistencia_multifuente',
            'media'
        FROM staging.empresas_unificadas e
        JOIN (
            SELECT
                nit,
                array_agg(DISTINCT telefono_normalizado) AS telefonos,
                array_agg(DISTINCT fuente) AS fuentes
            FROM staging.empresas_unificadas
            WHERE nit IS NOT NULL AND telefono_normalizado IS NOT NULL
            GROUP BY nit
            HAVING count(DISTINCT telefono_normalizado) > 1
        ) t ON e.nit = t.nit
        WHERE e.telefono_normalizado IS NOT NULL
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ Conflictos teléfono: {n}")
    return n


def _detectar_conflictos_email(db) -> int:
    """Detecta emails conflictivos para mismo NIT"""
    result = db.execute(text("""
        INSERT INTO staging.campos_dudosos
            (staging_id, campo, valor_conflictivo, valores_alternativos,
             fuentes_conflictivas, tipo_conflicto, severidad)
        SELECT DISTINCT
            e.staging_id,
            'email',
            e.correo_normalizado,
            em.correos,
            em.fuentes,
            'inconsistencia_multifuente',
            'baja'
        FROM staging.empresas_unificadas e
        JOIN (
            SELECT
                nit,
                array_agg(DISTINCT correo_normalizado) AS correos,
                array_agg(DISTINCT fuente) AS fuentes
            FROM staging.empresas_unificadas
            WHERE nit IS NOT NULL AND correo_normalizado IS NOT NULL
            GROUP BY nit
            HAVING count(DISTINCT correo_normalizado) > 1
        ) em ON e.nit = em.nit
        WHERE e.correo_normalizado IS NOT NULL
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ Conflictos email: {n}")
    return n


def _detectar_conflictos_municipio(db) -> int:
    """Detecta municipios conflictivos para mismo NIT"""
    result = db.execute(text("""
        INSERT INTO staging.campos_dudosos
            (staging_id, campo, valor_conflictivo, valores_alternativos,
             fuentes_conflictivas, tipo_conflicto, severidad)
        SELECT DISTINCT
            e.staging_id,
            'municipio',
            e.municipio_norm,
            m.municipios,
            m.fuentes,
            'inconsistencia_multifuente',
            'alta'
        FROM staging.empresas_unificadas e
        JOIN (
            SELECT
                nit,
                array_agg(DISTINCT municipio_norm) AS municipios,
                array_agg(DISTINCT fuente) AS fuentes
            FROM staging.empresas_unificadas
            WHERE nit IS NOT NULL AND municipio_norm IS NOT NULL
            GROUP BY nit
            HAVING count(DISTINCT municipio_norm) > 1
        ) m ON e.nit = m.nit
        WHERE e.municipio_norm IS NOT NULL
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ Conflictos municipio: {n}")
    return n


def _detectar_formatos_invalidos(db) -> int:
    """Detecta emails/teléfonos con formato inválido (correo_original vs correo_normalizado)"""
    result = db.execute(text("""
        INSERT INTO staging.campos_dudosos
            (staging_id, campo, valor_conflictivo,
             fuentes_conflictivas, tipo_conflicto, severidad)
        SELECT
            staging_id,
            'email',
            correo_original,
            ARRAY[fuente],
            'formato_invalido',
            'media'
        FROM staging.empresas_unificadas
        WHERE correo_original IS NOT NULL
          AND correo_normalizado IS NULL
          AND trim(correo_original) != ''
        ON CONFLICT DO NOTHING
    """))
    db.commit()
    n = result.rowcount
    logger.info(f"  ✓ Formatos inválidos: {n}")
    return n


def exportar_campos_dudosos_json(db, config) -> str | None:
    """Exporta campos dudosos a JSON. Retorna la ruta del archivo o None."""
    if not config.CREAR_JSON_CAMPOS_DUDOSOS:
        logger.info("⊘ JSON de campos dudosos deshabilitado (bandera=false)")
        return None

    rows = db.execute(text("""
        SELECT id, staging_id, empresa_id::text, campo, valor_conflictivo,
               valores_alternativos, fuentes_conflictivas,
               tipo_conflicto, severidad, fue_revisado_ia, resolucion_ia
        FROM staging.campos_dudosos
        ORDER BY
            CASE severidad WHEN 'critica' THEN 1 WHEN 'alta' THEN 2
                           WHEN 'media' THEN 3 ELSE 4 END,
            campo
    """)).fetchall()

    campos = []
    por_tipo = {}
    por_severidad = {}
    por_campo = {}

    for r in rows:
        item = {
            "id": r[0],
            "staging_id": r[1],
            "empresa_id": r[2],
            "campo": r[3],
            "valor_conflictivo": r[4],
            "valores_alternativos": r[5] or [],
            "fuentes_conflictivas": r[6] or [],
            "tipo_conflicto": r[7],
            "severidad": r[8],
            "fue_revisado_ia": r[9],
            "resolucion_ia": r[10],
        }
        campos.append(item)
        por_tipo[r[7]] = por_tipo.get(r[7], 0) + 1
        por_severidad[r[8]] = por_severidad.get(r[8], 0) + 1
        por_campo[r[3]] = por_campo.get(r[3], 0) + 1

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_campos_dudosos": len(campos),
        "campos_dudosos": campos,
        "resumen": {
            "por_tipo": por_tipo,
            "por_severidad": por_severidad,
            "por_campo": por_campo,
        }
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(config.RUTA_CAMPOS_DUDOSOS)
    path.mkdir(parents=True, exist_ok=True)
    filepath = path / f"campos_dudosos_{ts}.json"

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"✓ Campos dudosos exportados → {filepath}")
    return str(filepath)


def exportar_posibles_matches_json(db, config) -> str | None:
    """Exporta posibles matches a JSON. Retorna la ruta del archivo o None."""
    if not config.CREAR_JSON_POSIBLES_MATCHES:
        logger.info("⊘ JSON de posibles matches deshabilitado (bandera=false)")
        return None

    rows = db.execute(text("""
        SELECT
            pm.match_id, pm.staging_id_a, pm.staging_id_b,
            pm.regla_match, pm.score_match, pm.decision,
            pm.razon_decision, pm.creado_por_ia, pm.confianza_ia,
            a.nombre_normalizado AS nombre_a, a.fuente AS fuente_a, a.municipio_norm AS mun_a,
            b.nombre_normalizado AS nombre_b, b.fuente AS fuente_b, b.municipio_norm AS mun_b
        FROM staging.posibles_matches pm
        JOIN staging.empresas_unificadas a ON pm.staging_id_a = a.staging_id
        JOIN staging.empresas_unificadas b ON pm.staging_id_b = b.staging_id
        ORDER BY pm.score_match DESC
        LIMIT 50000
    """)).fetchall()

    matches = []
    stats = {}
    for r in rows:
        decision = r[5]
        stats[decision] = stats.get(decision, 0) + 1
        matches.append({
            "match_id": r[0],
            "staging_id_a": r[1],
            "staging_id_b": r[2],
            "regla_match": r[3],
            "score_match": r[4],
            "decision": decision,
            "razon_decision": r[6],
            "creado_por_ia": r[7],
            "confianza_ia": float(r[8]) if r[8] else None,
            "empresa_a": {"nombre": r[9], "fuente": r[10], "municipio": r[11]},
            "empresa_b": {"nombre": r[12], "fuente": r[13], "municipio": r[14]},
        })

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_matches": len(matches),
        "distribucion_decisiones": stats,
        "matches": matches,
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(config.RUTA_POSIBLES_MATCHES)
    path.mkdir(parents=True, exist_ok=True)
    filepath = path / f"posibles_matches_{ts}.json"

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"✓ Posibles matches exportados → {filepath}")
    return str(filepath)
