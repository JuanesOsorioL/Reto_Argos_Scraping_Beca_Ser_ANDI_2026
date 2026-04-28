"""
routers/openrouter_router.py

Endpoints para usar y monitorear los modelos gratis de OpenRouter.
Incorpora la funcionalidad del main.py de OpenRouter existente.
"""

import os
import logging
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/openrouter", tags=["OpenRouter (Modelos Gratis)"])
logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _headers():
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY no configurada")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


# ─── Schemas ─────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    prompt: str
    model: Optional[str] = "qwen/qwen3-coder:free"
    max_tokens: Optional[int] = 500


class RotateChatRequest(BaseModel):
    prompt: str
    max_tokens: Optional[int] = 500
    max_models_to_try: Optional[int] = 3
    esperar_json: Optional[bool] = False


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/key-status", summary="Estado y límites de la API Key de OpenRouter")
def key_status():
    """
    Muestra si estás en free tier y cuántas requests tienes disponibles.
    is_free_tier=false → tenés créditos y límite más alto para modelos :free
    """
    try:
        resp = requests.get(
            f"{OPENROUTER_BASE_URL}/key",
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        data = resp.json().get("data", {})
        is_free_tier = data.get("is_free_tier")

        return {
            "status": "ok",
            "is_free_tier": is_free_tier,
            "limite_diario_estimado_modelos_free": 50 if is_free_tier else 1000,
            "usage": data.get("usage"),
            "usage_daily": data.get("usage_daily"),
            "limit_remaining": data.get("limit_remaining"),
            "message": (
                "Cuenta con créditos → límite alto para modelos :free"
                if is_free_tier is False
                else "Free tier básico → ~50 requests/día con modelos :free"
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models", summary="Listar modelos :free disponibles con categorías")
def listar_modelos():
    """
    Lista todos los modelos gratuitos disponibles en OpenRouter,
    organizados por categorías.
    """
    try:
        resp = requests.get(
            f"{OPENROUTER_BASE_URL}/models",
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        models = resp.json().get("data", [])
        free_models = [
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "context_length": m.get("context_length"),
                "descripcion": m.get("description", "")[:100],
            }
            for m in models
            if m.get("id", "").endswith(":free")
        ]

        return {
            "total": len(free_models),
            "modelos": free_models,
            "recomendados_para_pipeline": [
                "qwen/qwen3-coder:free",
                "meta-llama/llama-3.3-70b-instruct:free",
                "google/gemma-3-27b-it:free",
                "openai/gpt-oss-20b:free",
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat", summary="Chat con un modelo :free específico")
def chat(request: ChatRequest):
    """
    Llama a un modelo :free específico.
    Solo permite modelos que terminan en :free (por seguridad de créditos).
    """
    if not request.model.endswith(":free"):
        raise HTTPException(
            status_code=400,
            detail="Solo se permiten modelos terminados en :free",
        )

    try:
        resp = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=_headers(),
            json={
                "model": request.model,
                "max_tokens": request.max_tokens,
                "messages": [
                    {"role": "system", "content": "Responde siempre en español, de forma clara y concisa."},
                    {"role": "user", "content": request.prompt},
                ],
            },
            timeout=30,
        )

        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        data = resp.json()
        return {
            "status": "ok",
            "model_used": data.get("model"),
            "answer": data["choices"][0]["message"]["content"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/rotate", summary="Chat con rotación automática de modelos :free")
def chat_rotate(request: RotateChatRequest):
    """
    Prueba modelos :free en orden de prioridad hasta que uno responda.
    Ideal para tareas donde la disponibilidad es más importante que el modelo específico.
    """
    from services.openrouter_service import get_openrouter_service

    svc = get_openrouter_service()
    if not svc.disponible:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY no configurada")

    resultado = svc.preguntar_con_rotacion(
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        esperar_json=request.esperar_json,
    )

    if not resultado["exito"]:
        raise HTTPException(
            status_code=500,
            detail={
                "mensaje": "Ningún modelo respondió",
                "errores": resultado.get("errores", []),
            },
        )

    return {
        "status": "ok",
        "model_used": resultado["modelo_usado"],
        "answer": resultado["respuesta"],
        "texto_raw": resultado.get("texto_raw"),
    }


@router.get("/categories", summary="Categorías de modelos configurados")
def model_categories():
    """Muestra las listas de modelos por categoría usadas en el pipeline."""
    from services.openrouter_service import (
        PREFERRED_FREE_MODELS,
        BACKUP_FREE_MODELS,
        LIGHTWEIGHT_FREE_MODELS,
        EXCLUDED_FROM_GENERAL_ROTATION,
    )
    return {
        "preferred": PREFERRED_FREE_MODELS,
        "backup": BACKUP_FREE_MODELS,
        "lightweight": LIGHTWEIGHT_FREE_MODELS,
        "excluidos_rotacion_general": EXCLUDED_FROM_GENERAL_ROTATION,
        "nota": "El pipeline usa: preferred → backup → lightweight en ese orden",
    }


@router.get("/stats", summary="Estadísticas de uso de OpenRouter en esta sesión")
def stats():
    """Cuántas llamadas se hicieron y cuántas fallaron en esta sesión."""
    from services.openrouter_service import get_openrouter_service
    svc = get_openrouter_service()
    return {
        "disponible": svc.disponible,
        **svc.resumen(),
    }
