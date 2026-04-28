"""
services/webhook.py - Envia notificacion a n8n cuando el pipeline termina.

El webhook se configura en:
  - Variable de entorno: N8N_WEBHOOK_URL
  - O en el body del request: {"n8n_webhook_url": "https://..."}

Payload que se envia a n8n:
{
  "evento": "pipeline_completado" | "pipeline_error",
  "execution_id": "exec-...",
  "estado": "completado" | "error",
  "timestamp": "2024-01-15T10:45:00Z",
  "resumen": {
    "scope": "2 municipios: Medellin, Cali",
    "total_staging": 8400,
    "empresas_consolidadas": 3200,
    "aprobadas_argos": 2800,
    "score_promedio": 74.5,
    "duracion_segundos": 245
  },
  "estadisticas": { ... detalle completo ... },
  "archivos_generados": [ ... ],
  "error": null | "mensaje de error"
}
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")
N8N_WEBHOOK_TIMEOUT = int(os.getenv("N8N_WEBHOOK_TIMEOUT", "15"))


def enviar_webhook_n8n(
    reporte: dict,
    webhook_url: str = None,
    estado: str = "completado",
) -> dict:
    """
    Envia el resultado del pipeline a n8n via webhook POST.

    Args:
        reporte: Reporte completo del pipeline
        webhook_url: URL del webhook (prioridad sobre env var)
        estado: 'completado' o 'error'

    Returns:
        {"enviado": bool, "status_code": int|None, "error": str|None}
    """
    url = webhook_url or N8N_WEBHOOK_URL

    if not url:
        logger.info("⊘ N8N_WEBHOOK_URL no configurada. Saltando notificacion.")
        return {"enviado": False, "razon": "webhook_url no configurada"}

    # Construir payload limpio para n8n
    payload = _construir_payload(reporte, estado)

    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=N8N_WEBHOOK_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )

        if resp.status_code in (200, 201, 202):
            logger.info(f"✅ Webhook n8n enviado exitosamente → {url} ({resp.status_code})")
            return {
                "enviado": True,
                "status_code": resp.status_code,
                "respuesta": resp.text[:200] if resp.text else "",
            }
        else:
            logger.warning(f"⚠ Webhook n8n respondio {resp.status_code}: {resp.text[:100]}")
            return {
                "enviado": False,
                "status_code": resp.status_code,
                "error": resp.text[:200],
            }

    except requests.Timeout:
        logger.warning(f"⚠ Timeout enviando webhook a {url}")
        return {"enviado": False, "error": "timeout"}
    except Exception as e:
        logger.warning(f"⚠ Error enviando webhook: {e}")
        return {"enviado": False, "error": str(e)}


def _construir_payload(reporte: dict, estado: str) -> dict:
    """Construye el payload que n8n recibe, con los datos mas utiles primero."""

    execution_id = reporte.get("execution_id", "")
    duracion = reporte.get("duracion_segundos", 0)

    # Datos de carga
    carga = reporte.get("fase_1_carga", {})
    total_staging = carga.get("total_staging", 0)

    # Datos de consolidacion
    consolid = reporte.get("fase_7_consolidacion", {})
    empresas = consolid.get("empresas_consolidadas", 0)

    # Datos de scoring
    scoring = reporte.get("fase_8_scoring", {})
    aprobadas = scoring.get("aprobadas_argos", 0)
    score_prom = scoring.get("score_promedio", 0)

    # Archivos generados
    archivos = reporte.get("archivos_generados", {})

    # IA stats
    ia = reporte.get("fase_6_ia", {})

    return {
        # Metadatos del evento
        "evento": "pipeline_completado" if estado == "completado" else "pipeline_error",
        "execution_id": execution_id,
        "estado": estado,
        "timestamp": datetime.now(timezone.utc).isoformat(),

        # Resumen ejecutivo (lo mas importante para n8n)
        "resumen": {
            "scope": reporte.get("scope_municipios", "todos"),
            "total_registros_procesados": total_staging,
            "empresas_consolidadas": empresas,
            "aprobadas_argos": aprobadas,
            "tasa_aprobacion_pct": round(aprobadas / empresas * 100, 1) if empresas > 0 else 0,
            "score_promedio": score_prom,
            "duracion_segundos": duracion,
            "duracion_minutos": round(duracion / 60, 1),
        },

        # Detalle por fuente
        "fuentes_cargadas": {
            k: v for k, v in carga.items()
            if k not in ("total_staging",) and isinstance(v, int)
        },

        # Detalle matching
        "matching": {
            "total_matches": reporte.get("fase_4_matching", {}).get("total", 0),
            "auto_match": reporte.get("fase_4_matching", {}).get("auto_match", 0),
            "ia_match": reporte.get("fase_4_matching", {}).get("ia_match", 0),
            "pendientes": reporte.get("fase_4_matching", {}).get("pendiente_revision", 0),
        },

        # IA usage
        "ia": {
            "activa": ia.get("activa", False),
            "proveedor": ia.get("proveedor"),
            "procesados": ia.get("procesados", 0),
        },

        # Tablas auxiliares
        "tablas_auxiliares": {
            "telefonos": consolid.get("telefonos", 0),
            "emails": consolid.get("emails", 0),
            "direcciones": consolid.get("direcciones", 0),
            "fuentes_auditoria": consolid.get("fuentes", 0),
        },

        # Distribucion de scores
        "distribucion_scores": scoring.get("distribucion", {}),

        # Campos dudosos
        "campos_dudosos": {
            "total": reporte.get("fase_5_campos_dudosos", {}).get("total", 0),
            "archivo": reporte.get("fase_5_campos_dudosos", {}).get("archivo"),
        },

        # Archivos generados para descarga
        "archivos_disponibles": {
            k: v for k, v in archivos.items()
            if isinstance(v, dict) and v.get("creado")
        },

        # URLs para consulta directa
        "urls_consulta": {
            "empresas_aprobadas": "/empresas?aprobado_argos=true",
            "detalle_ejecucion": f"/ejecuciones/{execution_id}",
            "reporte_completo": f"/ejecuciones/{execution_id}/reporte",
            "descargar_respaldos": "/descargar/respaldos",
        },

        # Error si aplica
        "error": reporte.get("error") if estado == "error" else None,
    }
