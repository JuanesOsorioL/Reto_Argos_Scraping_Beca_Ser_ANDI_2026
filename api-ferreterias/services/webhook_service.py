"""
services/webhook_service.py

Envia notificacion a n8n (o cualquier webhook) cuando el pipeline termina.
Incluye en el payload todos los datos relevantes del resultado.
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")


def notificar_n8n(
    execution_id: str,
    reporte: dict[str, Any],
    db=None,
) -> dict[str, Any]:
    """
    Envia el resultado del pipeline a n8n via webhook POST.

    El payload incluye:
    - Resumen ejecutivo (empresas consolidadas, aprobadas, score)
    - Estado del pipeline (fases, duracion, errores)
    - URLs para consumir los resultados
    - Archivos generados
    - Municipios procesados

    Retorna dict con: enviado, status_code, response
    """
    webhook_url = N8N_WEBHOOK_URL or os.getenv("N8N_WEBHOOK_URL", "")

    if not webhook_url:
        logger.info("⊘ N8N_WEBHOOK_URL no configurada. Saltando notificacion.")
        return {"enviado": False, "razon": "N8N_WEBHOOK_URL no configurada"}

    # Construir payload enriquecido
    payload = _construir_payload(execution_id, reporte, db)

    try:
        logger.info(f"📡 Enviando webhook a n8n: {webhook_url}")
        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        resultado = {
            "enviado": True,
            "status_code": resp.status_code,
            "response": resp.text[:500] if resp.text else "",
            "url": webhook_url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if resp.status_code in (200, 201, 202):
            logger.info(f"✅ Webhook n8n enviado correctamente ({resp.status_code})")
        else:
            logger.warning(f"⚠ Webhook n8n devolvio {resp.status_code}: {resp.text[:200]}")

        # Guardar resultado en DB si se pasa session
        if db:
            _guardar_resultado_webhook(db, execution_id, resultado)

        return resultado

    except requests.exceptions.Timeout:
        msg = "Timeout al enviar webhook (>30s)"
        logger.error(f"❌ {msg}")
        return {"enviado": False, "razon": msg}
    except Exception as e:
        msg = str(e)
        logger.error(f"❌ Error enviando webhook: {msg}")
        return {"enviado": False, "razon": msg}


def _construir_payload(
    execution_id: str,
    reporte: dict[str, Any],
    db=None,
) -> dict[str, Any]:
    """Construye el payload completo para n8n"""

    # Datos del scoring
    scoring = reporte.get("fase_8_scoring") or reporte.get("fase_7_scoring", {})
    consolidacion = reporte.get("fase_7_consolidacion") or reporte.get("fase_6_consolidacion", {})
    carga = reporte.get("fase_1_carga", {})

    # Stats adicionales de DB si esta disponible
    stats_db = {}
    if db:
        try:
            from sqlalchemy import text
            row = db.execute(text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE aprobado_argos = true) AS aprobadas,
                    COUNT(*) FILTER (WHERE nit IS NOT NULL) AS con_nit,
                    COUNT(*) FILTER (WHERE telefono_principal IS NOT NULL) AS con_telefono,
                    COUNT(*) FILTER (WHERE correo_principal IS NOT NULL) AS con_email,
                    ROUND(AVG(score_calidad)::numeric, 1) AS score_promedio,
                    COUNT(DISTINCT municipio) AS municipios
                FROM clean.empresas
            """)).fetchone()

            if row and row[0]:
                stats_db = {
                    "total_empresas": row[0],
                    "aprobadas_argos": row[1],
                    "tasa_aprobacion_pct": round((row[1] / row[0] * 100), 1) if row[0] > 0 else 0,
                    "con_nit": row[2],
                    "con_telefono": row[3],
                    "con_email": row[4],
                    "score_promedio": float(row[5]) if row[5] else 0,
                    "municipios_cubiertos": row[6],
                }

            # Top 5 municipios con mas empresas
            municipios_top = db.execute(text("""
                SELECT municipio, COUNT(*) AS n
                FROM clean.empresas
                WHERE municipio IS NOT NULL
                GROUP BY municipio
                ORDER BY n DESC
                LIMIT 5
            """)).fetchall()

            stats_db["top_municipios"] = [
                {"municipio": r[0], "empresas": r[1]} for r in municipios_top
            ]

        except Exception as e:
            logger.warning(f"No se pudieron obtener stats adicionales: {e}")

    # Archivos generados
    archivos = reporte.get("archivos_generados", {})

    # URLs base de la API
    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    payload = {
        # Identificacion
        "evento": "pipeline_completado",
        "execution_id": execution_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),

        # Estado general
        "estado": reporte.get("estado", "completado"),
        "duracion_segundos": reporte.get("duracion_segundos", 0),
        "scope": reporte.get("scope_municipios", "todos"),

        # Resumen ejecutivo
        "resumen": {
            **stats_db,
            "total_staging_procesados": carga.get("total_staging", 0),
            "empresas_consolidadas": consolidacion.get("empresas_consolidadas", 0),
            "aprobadas_argos": scoring.get("aprobadas_argos", 0),
            "en_revision": scoring.get("en_revision", 0),
            "rechazadas": scoring.get("rechazadas", 0),
            "score_calidad_promedio": scoring.get("score_promedio", 0),
            "distribucion_scores": scoring.get("distribucion", {}),
        },

        # Fuentes procesadas
        "fuentes": {
            "google_maps": carga.get("google_maps", 0),
            "paginas_amarillas": carga.get("paginas_amarillas", 0),
            "foursquare": carga.get("foursquare", 0),
            "overpass": carga.get("overpass", 0),
            "rues": carga.get("rues", 0),
            "serper": carga.get("serper", 0),
        },

        # Deduplicacion
        "deduplicacion": reporte.get("fase_4_matching") or reporte.get("fase_3_matching", {}),

        # IA usada
        "ia": reporte.get("fase_6_ia") or reporte.get("fase_5_ia", {}),

        # Archivos disponibles para descarga
        "archivos_disponibles": {
            nombre: {
                "creado": bool(info.get("ruta") or info.get("creado")),
                "url_descarga": (
                    f"{api_base}/descargar/respaldos/{info['ruta'].replace('/respaldos/', '')}"
                    if info.get("ruta") else None
                ),
            }
            for nombre, info in archivos.items()
            if isinstance(info, dict)
        },

        # URLs directas para consumir resultados
        "urls": {
            "todas_las_empresas":
                f"{api_base}/empresas?limit=100",
            "aprobadas_argos":
                f"{api_base}/empresas?aprobado_argos=true&limit=100",
            "pendientes_revision":
                f"{api_base}/empresas?aprobado_argos=false&limit=100",
            "campos_dudosos":
                f"{api_base}/campos-dudosos?severidad=alta",
            "posibles_matches_pendientes":
                f"{api_base}/posibles-matches?decision=pendiente_revision",
            "estado_ejecucion":
                f"{api_base}/ejecuciones/{execution_id}",
            "reporte_completo":
                f"{api_base}/ejecuciones/{execution_id}/reporte",
            "docs":
                f"{api_base}/docs",
        },

        # Error si hubo
        "error": reporte.get("error"),
    }

    return payload


def _guardar_resultado_webhook(db, execution_id: str, resultado: dict):
    """Guarda el resultado del webhook en la tabla de ejecuciones"""
    try:
        from sqlalchemy import text
        db.execute(text("""
            UPDATE staging.ejecuciones
            SET webhook_enviado = :enviado,
                webhook_url = :url,
                webhook_respuesta = :resp
            WHERE execution_id = :eid
        """), {
            "enviado": resultado.get("enviado", False),
            "url": resultado.get("url", ""),
            "resp": json.dumps(resultado, default=str)[:1000],
            "eid": execution_id,
        })
        db.commit()
    except Exception as e:
        logger.warning(f"No se pudo guardar resultado webhook: {e}")
