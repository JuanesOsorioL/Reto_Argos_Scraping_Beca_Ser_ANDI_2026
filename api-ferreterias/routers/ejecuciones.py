"""
routers/ejecuciones.py - Endpoints del pipeline de limpieza
"""

import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.connection import get_db
from config import config

router = APIRouter(prefix="/ejecuciones", tags=["Ejecuciones"])
logger = logging.getLogger(__name__)


class MunicipioItem(BaseModel):
    municipio: str
    departamento: str


class LimpiezaRequest(BaseModel):
    # Municipios del api_runner ({"municipio": ..., "departamento": ...})
    municipios: Optional[List[MunicipioItem]] = Field(
        default=None,
        description="Lista de municipios del api_runner. null o [] = todos."
    )

    # Control pipeline
    limpiar_staging_anterior: bool = True
    crear_json_campos_dudosos: Optional[bool] = None
    crear_json_posibles_matches: Optional[bool] = None
    crear_csv_clean_empresas: Optional[bool] = None
    crear_excel_clean_empresas: Optional[bool] = None

    # IA
    usar_ia_duplicados: Optional[bool] = None
    preferir_openrouter: bool = Field(default=True,
        description="true=OpenRouter gratis primero, false=Claude primero")

    # Validacion sin RUES
    validar_sin_rues: bool = Field(default=True,
        description="Buscar en Google registros que no estan en RUES")
    validar_con_ia: bool = True

    # RUES inactivos
    incluir_rues_inactivos: bool = Field(default=True,
        description="Incluir RUES cancelados/disueltos con penalizacion de score")

    # Webhook n8n
    n8n_webhook_url: Optional[str] = Field(
        default=None,
        description="URL del webhook de n8n para notificar cuando termine. "
                    "Ej: https://tu-n8n.com/webhook/abc123. "
                    "Si no se envía usa la variable N8N_WEBHOOK_URL del .env"
    )

    # Batch IA
    ia_batch_size: Optional[int] = None
    ia_min_score: Optional[int] = None
    ia_max_score: Optional[int] = None


@router.post("/iniciar", status_code=202, summary="Iniciar pipeline de limpieza y consolidacion")
async def iniciar_limpieza(
    request: LimpiezaRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Inicia el pipeline completo en background.

    Al terminar envia un POST al webhook de n8n con el resultado completo.

    **Ejemplo minimo:**
    ```json
    {
      "municipios": [{"municipio": "Medellin", "departamento": "Antioquia"}],
      "n8n_webhook_url": "https://tu-n8n.com/webhook/xyz"
    }
    ```

    **Para todos los municipios:** no enviar `municipios` o enviar `null`.
    """
    if not request.municipios:
        scope = "TODOS los municipios"
    elif len(request.municipios) == 1:
        m = request.municipios[0]
        scope = f"1 municipio: {m.municipio} ({m.departamento})"
    else:
        nombres = [m.municipio for m in request.municipios[:3]]
        extra = "..." if len(request.municipios) > 3 else ""
        scope = f"{len(request.municipios)} municipios: {', '.join(nombres)}{extra}"

    execution_id = f"exec-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    cfg_json = {
        "scope": scope,
        "municipios_count": len(request.municipios) if request.municipios else "todos",
        "limpiar_staging": request.limpiar_staging_anterior,
        "usar_ia": request.usar_ia_duplicados,
        "preferir_openrouter": request.preferir_openrouter,
        "validar_sin_rues": request.validar_sin_rues,
        "incluir_rues_inactivos": request.incluir_rues_inactivos,
        "webhook_configurado": bool(request.n8n_webhook_url or config.N8N_WEBHOOK_URL),
    }

    db.execute(text("""
        INSERT INTO staging.ejecuciones
            (execution_id, estado, config_json, webhook_url)
        VALUES (:eid, 'iniciado', :cfg, :wh)
    """), {
        "eid": execution_id,
        "cfg": json.dumps(cfg_json),
        "wh": request.n8n_webhook_url or config.N8N_WEBHOOK_URL or None,
    })
    db.commit()

    municipios_dict = [m.model_dump() for m in request.municipios] if request.municipios else None

    background_tasks.add_task(
        _run_pipeline_background,
        execution_id=execution_id,
        request_dict=request.model_dump(),
        municipios_dict=municipios_dict,
        webhook_url=request.n8n_webhook_url or config.N8N_WEBHOOK_URL or "",
    )

    return {
        "status": "iniciado",
        "execution_id": execution_id,
        "scope": scope,
        "webhook_configurado": bool(request.n8n_webhook_url or config.N8N_WEBHOOK_URL),
        "mensaje": (
            f"Pipeline iniciado para {scope}. "
            f"Consulta el estado en GET /ejecuciones/{execution_id}. "
            f"n8n sera notificado al finalizar."
        ),
    }


@router.get("/{execution_id}", summary="Estado de ejecucion")
def obtener_estado(execution_id: str, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT execution_id, estado, fase_actual, progreso_pct,
               registros_staging, matches_detectados, empresas_consolidadas,
               error_mensaje, config_json, webhook_enviado, webhook_respuesta,
               timestamp_inicio, timestamp_fin, duracion_segundos
        FROM staging.ejecuciones WHERE execution_id = :eid
    """), {"eid": execution_id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Ejecucion no encontrada")

    ts_inicio = row[11]
    ts_fin = row[12]
    duracion = row[13]
    if not duracion and ts_inicio:
        duracion = int((datetime.now(timezone.utc)
                        - ts_inicio.replace(tzinfo=timezone.utc)).total_seconds())

    return {
        "execution_id": row[0],
        "estado": row[1],
        "fase_actual": row[2],
        "progreso_pct": row[3],
        "registros_staging": row[4],
        "matches_detectados": row[5],
        "empresas_consolidadas": row[6],
        "error": row[7],
        "config": row[8],
        "webhook_enviado": row[9],
        "webhook_respuesta": row[10],
        "timestamp_inicio": ts_inicio.isoformat() if ts_inicio else None,
        "timestamp_fin": ts_fin.isoformat() if ts_fin else None,
        "duracion_segundos": duracion,
    }


@router.get("/{execution_id}/reporte", summary="Reporte completo JSON")
def obtener_reporte(execution_id: str, db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT reporte_json FROM staging.ejecuciones WHERE execution_id = :eid
    """), {"eid": execution_id}).fetchone()

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Reporte no disponible aun")

    return row[0]


@router.post("/{execution_id}/reenviar-webhook", summary="Reenviar webhook a n8n manualmente")
def reenviar_webhook(
    execution_id: str,
    webhook_url: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Reenvía el webhook a n8n por si no llego la primera vez."""
    row = db.execute(text("""
        SELECT reporte_json, webhook_url FROM staging.ejecuciones
        WHERE execution_id = :eid
    """), {"eid": execution_id}).fetchone()

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Reporte no disponible")

    from services.webhook import enviar_webhook_n8n
    url = webhook_url or row[1] or config.N8N_WEBHOOK_URL
    if not url:
        raise HTTPException(status_code=400, detail="No hay webhook_url configurada")

    reporte = row[0]
    estado = reporte.get("estado", "completado")
    result = enviar_webhook_n8n(reporte, webhook_url=url, estado=estado)

    db.execute(text("""
        UPDATE staging.ejecuciones
        SET webhook_enviado=:env, webhook_respuesta=:resp
        WHERE execution_id=:eid
    """), {
        "env": result.get("enviado", False),
        "resp": json.dumps(result)[:500],
        "eid": execution_id,
    })
    db.commit()

    return {"resultado_webhook": result}


@router.get("/", summary="Ultimas ejecuciones")
def listar_ejecuciones(limit: int = 10, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT execution_id, estado, fase_actual, progreso_pct,
               registros_staging, empresas_consolidadas,
               timestamp_inicio, duracion_segundos,
               config_json->>'scope' AS scope,
               webhook_enviado
        FROM staging.ejecuciones
        ORDER BY timestamp_inicio DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    return {
        "ejecuciones": [
            {
                "execution_id": r[0],
                "estado": r[1],
                "fase_actual": r[2],
                "progreso_pct": r[3],
                "registros_staging": r[4],
                "empresas_consolidadas": r[5],
                "timestamp_inicio": r[6].isoformat() if r[6] else None,
                "duracion_segundos": r[7],
                "scope": r[8],
                "webhook_enviado": r[9],
            }
            for r in rows
        ]
    }


def _run_pipeline_background(execution_id, request_dict, municipios_dict, webhook_url):
    from db.connection import SessionLocal
    from workers.pipeline import ejecutar_pipeline_completo_v2

    db = SessionLocal()
    try:
        ejecutar_pipeline_completo_v2(
            db=db,
            config=config,
            execution_id=execution_id,
            municipios=municipios_dict,
            limpiar_staging=request_dict.get("limpiar_staging_anterior", True),
            usar_ia=request_dict.get("usar_ia_duplicados"),
            preferir_openrouter=request_dict.get("preferir_openrouter", True),
            validar_sin_rues=request_dict.get("validar_sin_rues", True),
            validar_con_ia=request_dict.get("validar_con_ia", True),
            incluir_rues_inactivos=request_dict.get("incluir_rues_inactivos", True),
            crear_json_campos_dudosos=request_dict.get("crear_json_campos_dudosos"),
            crear_json_posibles_matches=request_dict.get("crear_json_posibles_matches"),
            webhook_url=webhook_url,
        )
    finally:
        db.close()
