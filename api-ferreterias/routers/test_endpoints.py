"""
routers/test_endpoints.py - Endpoints de prueba / desarrollo

Solo para simular comportamiento sin ejecutar el pipeline completo.
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.connection import get_db
from config import config

router = APIRouter(prefix="/test", tags=["🧪 Test / Desarrollo"])
logger = logging.getLogger(__name__)


# ─── Endpoint 1: Simular webhook final ───────────────────────────────────────

class WebhookSimRequest(BaseModel):
    webhook_url: Optional[str] = Field(
        default=None,
        description="URL destino. Si no se envía usa N8N_WEBHOOK_URL del .env"
    )
    execution_id: Optional[str] = Field(
        default=None,
        description="ID de ejecución real para tomar datos reales. "
                    "Si no se envía usa datos simulados."
    )


@router.post("/simular-webhook", summary="Simular envío de webhook final a n8n")
def simular_webhook(req: WebhookSimRequest, db: Session = Depends(get_db)):
    """
    Simula el POST que hace el pipeline al terminar.
    Útil para probar que n8n recibe y procesa el payload correctamente
    sin tener que ejecutar el pipeline completo.

    - Con `execution_id` real → toma los datos reales de esa ejecución.
    - Sin `execution_id` → genera datos de prueba ficticios.
    """
    from services.webhook_service import notificar_n8n

    webhook_url = req.webhook_url or config.N8N_WEBHOOK_URL
    if not webhook_url:
        raise HTTPException(
            status_code=400,
            detail="No hay webhook_url. Envíala en el body o configura N8N_WEBHOOK_URL en .env"
        )

    # Intentar tomar datos de una ejecución real
    if req.execution_id:
        row = db.execute(text("""
            SELECT reporte_json FROM staging.ejecuciones
            WHERE execution_id = :eid
        """), {"eid": req.execution_id}).fetchone()

        if not row or not row[0]:
            raise HTTPException(
                status_code=404,
                detail=f"Ejecución '{req.execution_id}' no encontrada o sin reporte."
            )
        reporte = row[0]
        execution_id = req.execution_id
        logger.info(f"📋 Usando reporte real de {execution_id}")

    else:
        # Datos simulados
        execution_id = f"test-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"
        reporte = _build_reporte_simulado(execution_id, db)
        logger.info(f"🧪 Usando reporte simulado: {execution_id}")

    # Sobreescribir webhook_url si se envió en el body
    import os
    original_url = os.environ.get("N8N_WEBHOOK_URL", "")
    if req.webhook_url:
        os.environ["N8N_WEBHOOK_URL"] = req.webhook_url

    resultado = notificar_n8n(
        execution_id=execution_id,
        reporte=reporte,
        db=db,
    )

    # Restaurar variable de entorno
    if req.webhook_url:
        os.environ["N8N_WEBHOOK_URL"] = original_url

    return {
        "simulacion": True,
        "execution_id": execution_id,
        "webhook_url": webhook_url,
        "resultado": resultado,
        "payload_enviado": "Ver webhook_service logs",
    }


# ─── Endpoint 2: Status general del sistema ──────────────────────────────────

@router.get("/status", summary="Estado general del sistema y datos actuales")
def status_sistema(db: Session = Depends(get_db)):
    """
    Muestra un resumen del estado actual del sistema:
    - Conteos de clean.empresas
    - Última ejecución
    - Estado de las tablas raw
    - Configuración activa
    """

    # ── clean.empresas ──
    clean = {}
    try:
        row = db.execute(text("""
            SELECT
                COUNT(*)                                        AS total,
                COUNT(*) FILTER (WHERE aprobado_argos = true)  AS aprobadas,
                COUNT(*) FILTER (WHERE nit IS NOT NULL)         AS con_nit,
                COUNT(*) FILTER (WHERE telefono_principal IS NOT NULL) AS con_telefono,
                COUNT(*) FILTER (WHERE latitud IS NOT NULL)     AS con_coords,
                COUNT(*) FILTER (WHERE correo_principal IS NOT NULL)   AS con_email,
                COUNT(*) FILTER (WHERE sitio_web IS NOT NULL)   AS con_web,
                ROUND(AVG(score_calidad)::numeric, 1)           AS score_promedio,
                COUNT(*) FILTER (WHERE cantidad_fuentes > 1)    AS unificadas_multi_fuente,
                COUNT(DISTINCT municipio)                       AS municipios
            FROM clean.empresas
        """)).fetchone()

        if row:
            clean = {
                "total_empresas":          row[0],
                "aprobadas_argos":         row[1],
                "tasa_aprobacion_pct":     round(row[1] / row[0] * 100, 1) if row[0] else 0,
                "con_nit":                 row[2],
                "con_telefono":            row[3],
                "con_coordenadas":         row[4],
                "con_email":               row[5],
                "con_web":                 row[6],
                "score_calidad_promedio":  float(row[7]) if row[7] else 0,
                "unificadas_multi_fuente": row[8],
                "municipios_cubiertos":    row[9],
            }
    except Exception as e:
        clean = {"error": str(e)}

    # ── Fuentes en staging actual ──
    staging = {}
    try:
        rows = db.execute(text("""
            SELECT fuente, COUNT(*) AS registros
            FROM staging.empresas_unificadas
            GROUP BY fuente ORDER BY registros DESC
        """)).fetchall()
        staging = {r[0]: r[1] for r in rows}
        staging["_total"] = sum(staging.values())
    except Exception as e:
        staging = {"error": str(e)}

    # ── Última ejecución ──
    ultima_ejecucion = {}
    try:
        row = db.execute(text("""
            SELECT execution_id, estado, fase_actual, progreso_pct,
                   registros_staging, empresas_consolidadas,
                   timestamp_inicio, duracion_segundos,
                   config_json->>'scope' AS scope
            FROM staging.ejecuciones
            ORDER BY timestamp_inicio DESC
            LIMIT 1
        """)).fetchone()

        if row:
            ultima_ejecucion = {
                "execution_id":        row[0],
                "estado":              row[1],
                "fase_actual":         row[2],
                "progreso_pct":        row[3],
                "registros_staging":   row[4],
                "empresas_consolidadas": row[5],
                "timestamp_inicio":    row[6].isoformat() if row[6] else None,
                "duracion_segundos":   row[7],
                "scope":               row[8],
            }
    except Exception as e:
        ultima_ejecucion = {"error": str(e)}

    # ── Tablas raw ──
    raw_tables = {}
    tablas = [
        "google_maps_ferreterias",
        "paginas_amarillas_ferreterias",
        "foursquare_ferreterias",
        "overpass_ferreterias",
        "rues_detalle",
        "serper_resultados_construccion",
    ]
    for tabla in tablas:
        try:
            n = db.execute(text(f"SELECT COUNT(*) FROM raw.{tabla}")).scalar()
            raw_tables[tabla] = n
        except Exception:
            raw_tables[tabla] = "no existe"

    # ── Config activa ──
    cfg = {
        "environment":         config.ENV,
        "ia_duplicados":       config.USAR_IA_DUPLICADOS,
        "ia_min_score":        config.IA_MIN_SCORE,
        "ia_max_score":        config.IA_MAX_SCORE,
        "ia_model":            config.IA_MODEL,
        "openrouter":          bool(config.OPENROUTER_API_KEY),
        "anthropic":           bool(config.ANTHROPIC_API_KEY),
        "serper":              bool(config.SERPER_API_KEY),
        "n8n_webhook":         bool(config.N8N_WEBHOOK_URL),
        "incluir_liquidacion": config.INCLUIR_EN_LIQUIDACION,
        "similarity_threshold": config.SIMILARITY_THRESHOLD_NOMBRE,
    }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clean_empresas":   clean,
        "staging_actual":   staging,
        "ultima_ejecucion": ultima_ejecucion,
        "raw_tables":       raw_tables,
        "configuracion":    cfg,
    }


# ─── Helper: reporte simulado ────────────────────────────────────────────────

def _build_reporte_simulado(execution_id: str, db) -> dict:
    """Construye un reporte de prueba con datos reales de clean.empresas"""
    total = 0
    aprobadas = 0
    score_prom = 0.0

    try:
        row = db.execute(text("""
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE aprobado_argos = true),
                   ROUND(AVG(score_calidad)::numeric, 1)
            FROM clean.empresas
        """)).fetchone()
        if row and row[0]:
            total, aprobadas, score_prom = row[0], row[1], float(row[2] or 0)
    except Exception:
        pass

    return {
        "execution_id":    execution_id,
        "estado":          "completado",
        "timestamp_inicio": datetime.now(timezone.utc).isoformat(),
        "timestamp_fin":    datetime.now(timezone.utc).isoformat(),
        "duracion_segundos": 0,
        "scope_municipios": "simulado",
        "fase_1_carga": {
            "google_maps": 100, "paginas_amarillas": 80,
            "foursquare": 50, "overpass": 30,
            "rues": 150, "serper": 40,
            "total_staging": 450,
        },
        "fase_7_consolidacion": {"empresas_consolidadas": total},
        "fase_8_scoring": {
            "aprobadas_argos": aprobadas,
            "en_revision": 0,
            "rechazadas": total - aprobadas,
            "score_promedio": score_prom,
            "distribucion": {},
        },
        "archivos_generados": {},
        "_simulado": True,
    }
