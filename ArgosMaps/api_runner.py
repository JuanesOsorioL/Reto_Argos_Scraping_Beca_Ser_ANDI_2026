"""
api_runner.py — Expone el scraper como endpoint HTTP
Arquitectura "dispara y olvida":
  - n8n llama a /scrape/google-maps
  - El servidor responde INMEDIATAMENTE con run_id
  - El scraper corre en segundo plano
  - n8n consulta /status para saber si terminó
  - opcionalmente se notifica a n8n vía webhook al finalizar

Endpoints:
    GET  /health               → healthcheck simple
    POST /scrape/google-maps   → dispara el scraper (responde al instante)
    GET  /status               → estado actual del scraper
    GET  /resultado            → resultado de la última corrida
    POST /test/callback        → prueba manual del callback a n8n
    GET  /endpoints            → lista endpoints expuestos
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import asyncio
import uvicorn
import uuid
import os
from typing import List, Optional
from datetime import datetime, timedelta
import httpx
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Argos Scraper API - CIUDADES OBLIGATORIAS")



# ──────────────────────────────────────────────────────────────────────────────
# MODELOS PYDANTIC — Ciudades OBLIGATORIAS en body
# ──────────────────────────────────────────────────────────────────────────────

class UbicacionModel(BaseModel):
    """Modelo para cada ciudad/municipio."""
    municipio: str
    departamento: str


class ScrapGoogleMapsRequest(BaseModel):
    """
    Body REQUERIDO para POST /scrape/google-maps

    selected_locations es obligatorio.
    keywords es opcional — si se omite usa los defaults de config.py.

    Ejemplo:
    {
        "selected_locations": [
            {"municipio": "cali", "departamento": "Valle del Cauca"}
        ],
        "keywords": ["ferreterias", "cemento"]   // opcional
    }
    """
    selected_locations: List[UbicacionModel]
    keywords: Optional[List[str]] = None



# URL fija del webhook de n8n.
# todo en docker
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")

# Estado global del scraper
estado = {
    "scraping_en_curso": False,
    "run_id": None,
    "inicio": None,
    "fin": None,
    "duracion": None,
    "ultimo_status": "sin_correr",  # sin_correr | corriendo | ok | error
    "ultimo_error": None,
    "metricas": None,
    "ciudades_actual": None,  # ← Guardar qué ciudades se están procesando
}


def calcular_duracion(inicio_iso: str | None, fin_iso: str | None):
    if not inicio_iso or not fin_iso:
        return None
    try:
        inicio = datetime.fromisoformat(inicio_iso)
        fin = datetime.fromisoformat(fin_iso)
        duracion_s = max(0, round((fin - inicio).total_seconds()))
        return f"{duracion_s // 60}m {duracion_s % 60}s"
    except Exception:
        return None


async def enviar_callback(payload: dict, headers: dict | None = None):
    """
    Envía el callback al webhook de n8n si está configurado.
    """
    if not N8N_WEBHOOK_URL:
        raise ValueError("N8N_WEBHOOK_URL no está configurado")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            N8N_WEBHOOK_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                **(headers or {})
            }
        )
        response.raise_for_status()


async def notificar_fin_run(payload: dict, headers: dict | None = None):
    """
    Intenta notificar a n8n, pero no rompe el flujo principal si falla.
    """
    try:
        await enviar_callback(payload, headers)
        print(f"[CALLBACK] Notificación enviada a n8n. evento={payload.get('evento')} run_id={payload.get('run_id')}")
    except Exception as e:
        print(f"[CALLBACK] Falló envío a n8n: {e}")


async def ejecutar_scraper_background(run_id: str, ciudades: List[dict], keywords: Optional[List[str]] = None):
    """
    Corre el scraper en segundo plano sin bloquear la respuesta HTTP.
    Al finalizar, actualiza estado y notifica a n8n.
    """
    global estado
    try:
        from main import do_scrape

        metricas = await do_scrape(ciudades=ciudades, keywords=keywords)

        fin = datetime.now().isoformat()
        duracion = None

        # Si do_scrape ya trae duracion, la usamos
        if isinstance(metricas, dict):
            duracion = metricas.get("duracion")

        if not duracion:
            duracion = calcular_duracion(estado["inicio"], fin)

        estado.update({
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": duracion,
            "ultimo_status": "ok",
            "ultimo_error": None,
            "metricas": metricas if isinstance(metricas, dict) else None,
        })

        print(f"\n[✓] Scraping completado. run_id: {run_id}")

        await notificar_fin_run({
            "evento": "google_maps.finalizado",
            "status": "ok",
            "run_id": run_id,
            "inicio": estado["inicio"],
            "fin": estado["fin"],
            "duracion": estado["duracion"],
            "ciudades": estado["ciudades_actual"],  # ← Incluir ciudades
            "metricas": estado["metricas"],
            "origen": "api_runner",
            "tipo_ejecucion": "produccion"
        })

    except Exception as e:
        fin = datetime.now().isoformat()
        duracion = calcular_duracion(estado["inicio"], fin)

        estado.update({
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": duracion,
            "ultimo_status": "error",
            "ultimo_error": str(e),
            "metricas": None,
        })

        print(f"\n[✗] Error en scraping: {e}")

        await notificar_fin_run({
            "evento": "google_maps.finalizado",
            "status": "error",
            "run_id": run_id,
            "inicio": estado["inicio"],
            "fin": estado["fin"],
            "duracion": estado["duracion"],
            "ciudades": estado["ciudades_actual"],  # ← Incluir ciudades
            "error": str(e),
            "origen": "api_runner",
            "tipo_ejecucion": "produccion"
        })


@app.get("/health")
def health():
    return {"status": "ok", "code": "200"}


@app.get("/status")
def status():
    """
    Retorna estado actual.
    """
    return {
        "statusGeneral": estado["ultimo_status"],
        "status": estado["ultimo_status"],
        "en_curso": estado["scraping_en_curso"],
        "run_id": estado["run_id"],
        "inicio": estado["inicio"],
        "fin": estado["fin"],
        "duracion": estado["duracion"],
        "ciudades_actual": estado["ciudades_actual"],  # ← Nuevo
        "error": estado["ultimo_error"],
        "metricas": estado["metricas"],
    }


@app.post("/scrape/google-maps")
async def run_scraper(request: ScrapGoogleMapsRequest):
    """
    Dispara el scraper con ciudades OBLIGATORIAS en body.
    
    Body REQUERIDO:
    {
        "selected_locations": [
            {"municipio": "cali", "departamento": "Valle del Cauca"},
            {"municipio": "bogota", "departamento": "Cundinamarca"}
        ]
    }
    
    Retorna: run_id inmediatamente (scraper corre en background)
    """
    global estado

    if estado["scraping_en_curso"]:
        return JSONResponse(
            status_code=409,
            content={
                "status": "ocupado",
                "mensaje": "Ya hay un scraping en curso.",
                "run_id": estado["run_id"],
                "inicio": estado["inicio"],
            }
        )
    
    # ✅ Validar que haya al menos una ciudad
    if not request.selected_locations or len(request.selected_locations) == 0:
        raise HTTPException(
            status_code=400,
            detail="selected_locations es obligatorio y debe tener al menos una ciudad"
        )

    # Convertir a list[dict] para do_scrape()
    ciudades = [
        {
       
            "municipio": loc.municipio.lower(),  # Normalizar a lowercase
            "departamento": loc.departamento
        }
        for loc in request.selected_locations
    ]



    run_id = str(uuid.uuid4())
    inicio = datetime.now().isoformat()

    estado.update({
        "scraping_en_curso": True,
        "run_id": run_id,
        "inicio": inicio,
        "fin": None,
        "duracion": None,
        "ultimo_status": "corriendo",
        "ultimo_error": None,
        "metricas": None,
        "ciudades_actual": ciudades,  # ← Guardar ciudades
    })

    asyncio.create_task(ejecutar_scraper_background(run_id, ciudades, request.keywords))

    return {
        "status": "iniciado",
        "mensaje": "Scraper disparado con ciudades dinámicas.",
        "run_id": run_id,
        "inicio": inicio,
        "ciudades": ciudades,
        "cantidad_ciudades": len(ciudades),
        "keywords": request.keywords or "defaults (config.py)",
        "webhook_n8n": N8N_WEBHOOK_URL,
    }


@app.get("/resultado")
def resultado():
    return {
        "status": estado["ultimo_status"],
        "run_id": estado["run_id"],
        "inicio": estado["inicio"],
        "fin": estado["fin"],
        "duracion": estado["duracion"],
        "error": estado["ultimo_error"],
        "en_curso": estado["scraping_en_curso"],
        "ciudades": estado["ciudades_actual"],  # ← Nuevo
        "metricas": estado["metricas"],
    }


@app.post("/test/callback")
async def test_callback(request: Request):
    """
    Prueba manual del callback hacia n8n sin ejecutar el scraper.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        now = datetime.now()
        inicio_default = (now - timedelta(seconds=65)).isoformat()
        fin_default = now.isoformat()

        payload = {
            "evento": "google_maps.finalizado",
            "status": body.get("status", "ok"),
            "run_id": body.get("run_id", "test-run-001"),
            "inicio": body.get("inicio", inicio_default),
            "fin": body.get("fin", fin_default),
            "duracion": body.get("duracion", "1m 5s"),
            "metricas": body.get("metricas", {
                "run_id": body.get("run_id", "test-run-001"),
                "inicio": body.get("inicio", inicio_default),
                "fin": body.get("fin", fin_default),
                "duracion": body.get("duracion", "1m 5s"),
                "keywords_total": 1,
                "keywords_procesadas": 1,
                "busqueda_total": 5,
                "detalle_ok": 4,
                "detalle_error": 1,
                "detalle_saltado": 0,
                "aprobados_argos": 2,
                "errores_totales": 1
            }),
            "origen": "api_runner",
            "tipo_ejecucion": body.get("tipo_ejecucion", "prueba_callback")
        }

        if payload["status"] == "error":
            payload.pop("metricas", None)
            payload["error"] = body.get("error", "Error de prueba enviado manualmente")

        await enviar_callback(payload)

        return {
            "status": "ok",
            "mensaje": "Callback de prueba enviado a n8n correctamente",
            "webhook_n8n": N8N_WEBHOOK_URL,
            "payload_enviado": payload
        }

    except Exception as e:
        print(f"[TEST_CALLBACK] Falló envío de prueba a n8n: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "mensaje": "No se pudo enviar el callback de prueba a n8n",
                "error": str(e)
            }
        )


@app.get("/endpoints")
def endpoints():
    rutas = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)

        if path and methods:
            rutas.append({
                "path": path,
                "methods": sorted([m for m in methods if m not in {"HEAD", "OPTIONS"}])
            })

    return rutas


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8001"))

    print(f"🚀 Argos Scraper API — CIUDADES OBLIGATORIAS")
    print(f"🚀 Argos Scraper API corriendo en http://localhost:{port}")
    print(f"   n8n debe usar: http://host.docker.internal:{port}")
    print(f"   Prueba local:  http://localhost:{port}/status")
    print(f"   Webhook n8n:   {N8N_WEBHOOK_URL}")
    print(f"\n📍 IMPORTANTE: POST /scrape/google-maps REQUIERE:")
    print(f'   {{"selected_locations": [{{"municipio": "...", "departamento": "..."}}]}}')


    print(f"\n    GET  /health")
    print(f"   POST /scrape/google-maps  ← REQUIERE ciudades")
    print(f"   GET  /status")
    print(f"   GET  /resultado")
    print(f"   POST /test/callback")
    print(f"   GET  /endpoints\n")

    uvicorn.run(app, host="0.0.0.0", port=port)