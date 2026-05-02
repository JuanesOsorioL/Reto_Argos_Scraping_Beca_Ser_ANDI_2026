"""
api_runner.py — Endpoint HTTP para que n8n dispare el scraper Overpass
Puerto: 8007

Endpoints:
  GET  /health
  POST /scrape/overpass
  POST /scrape/overpass/prueba
  POST /scrape/overpass/depto
  GET  /status
  GET  /resultado
  POST /test/callback
  GET  /endpoints
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import asyncio
import uvicorn
import uuid
import os
from datetime import datetime, timedelta
import httpx

from pydantic import BaseModel
from typing import List, Optional

class UbicacionModel(BaseModel):
    municipio: str
    departamento: str

class ScrapOpenstreetmapRequest(BaseModel):
    """Body opcional para POST /scrape/overpass — ambos campos tienen fallback"""
    selected_locations: Optional[List[UbicacionModel]] = None
    keywords: Optional[List[str]] = None
    
app = FastAPI(title="Argos Scraper — Overpass API")

PORT = int(os.getenv("PORT", "8007"))
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")

estado = {
    "scraping_en_curso": False,
    "run_id": None,
    "inicio": None,
    "fin": None,
    "duracion": None,
    "ultimo_status": "sin_correr",
    "ultimo_error": None,
    "metricas": None,
    "tipo_ejecucion": None,
    "opciones": None,
}

MUNICIPIOS_PRUEBA = [
    {"departamento": "Antioquia", "municipio": "Medellín"},
]


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
    try:
        await enviar_callback(payload, headers)
        print(f"[CALLBACK] Notificación enviada a n8n. evento={payload.get('evento')} run_id={payload.get('run_id')}")
    except Exception as e:
        print(f"[CALLBACK] Falló envío a n8n: {e}")


async def ejecutar_background(run_id: str, opciones: dict, tipo_ejecucion: str):
    """
    Ejecuta el scraping en background.
    
    Args:
        run_id: UUID único generado en iniciar()  ← NUEVO PARÁMETRO
        opciones: dict con configuración
        tipo_ejecucion: "produccion" | "prueba" | "departamento"
    """
    global estado
    try:
        from main import do_scrape

        municipios = opciones.get("municipios", [])
        keywords = opciones.get("keywords", None)
        metricas = await do_scrape(run_id=run_id, municipios=municipios, keywords=keywords)

        fin = datetime.now().isoformat()
        duracion = None

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

        run_id_callback = (
            metricas.get("run_id")
            if isinstance(metricas, dict) and metricas.get("run_id")
            else estado["run_id"]
        )

        print(f"\n[✓] Overpass completado. run_id: {run_id_callback}")

        await notificar_fin_run({
            "evento": "overpass.finalizado",
            "status": "ok",
            "run_id": run_id_callback,
            "inicio": estado["inicio"],
            "fin": estado["fin"],
            "duracion": estado["duracion"],
            "metricas": estado["metricas"],
            "origen": "api_runner",
            "tipo_ejecucion": tipo_ejecucion
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
        })

        print(f"\n[✗] Error Overpass: {e}")

        await notificar_fin_run({
            "evento": "overpass.finalizado",
            "status": "error",
            "run_id": estado["run_id"],
            "inicio": estado["inicio"],
            "fin": estado["fin"],
            "duracion": estado["duracion"],
            "error": str(e),
            "origen": "api_runner",
            "tipo_ejecucion": tipo_ejecucion
        })


def iniciar(opciones: dict, tipo_ejecucion: str) -> dict:
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
        "tipo_ejecucion": tipo_ejecucion,
        "opciones": opciones,
    })

    asyncio.create_task(ejecutar_background(run_id, opciones, tipo_ejecucion))

    return {
        "status": "iniciado",
        "run_id": run_id,
        "inicio": inicio,
        "mensaje": "Consulta GET /status para ver el progreso.",
        "webhook_n8n": N8N_WEBHOOK_URL,
        "tipo_ejecucion": tipo_ejecucion,
    }


@app.get("/health")
def health():
    return {"status": "ok", "code": "200"}


@app.get("/status")
def status():
    return {
        "status": estado["ultimo_status"],
        "en_curso": estado["scraping_en_curso"],
        "run_id": estado["run_id"],
        "inicio": estado["inicio"],
        "fin": estado["fin"],
        "duracion": estado["duracion"],
        "error": estado["ultimo_error"],
        "metricas": estado["metricas"],
        "tipo_ejecucion": estado["tipo_ejecucion"],
    }


@app.post("/scrape/overpass")
async def run_scraper(request: ScrapOpenstreetmapRequest):
    if estado["scraping_en_curso"]:
        return JSONResponse(
            status_code=409,
            content={"status": "ocupado", "run_id": estado["run_id"]}
        )

    # Fallback municipios: si no llegan, usar todos los de Colombia
    if request.selected_locations:
        municipios = [
            {"municipio": loc.municipio, "departamento": loc.departamento}
            for loc in request.selected_locations
        ]
    else:
        from municipios_colombia import get_municipios
        municipios = get_municipios()

    # Fallback keywords: si no llegan, main.py usará TEXT_REGEX por defecto
    keywords = request.keywords if request.keywords else None

    return iniciar({"municipios": municipios, "keywords": keywords}, "produccion")


@app.post("/scrape/overpass/prueba")
async def run_prueba():
    if estado["scraping_en_curso"]:
        return JSONResponse(
            status_code=409,
            content={"status": "ocupado", "run_id": estado["run_id"]}
        )

    return iniciar({"municipios": MUNICIPIOS_PRUEBA}, "prueba")


@app.post("/scrape/overpass/depto")
async def run_departamento(body: dict):
    if estado["scraping_en_curso"]:
        return JSONResponse(
            status_code=409,
            content={"status": "ocupado", "run_id": estado["run_id"]}
        )

    dept = body.get("departamento")
    if not dept:
        return JSONResponse(
            status_code=400,
            content={"error": "Falta el campo 'departamento'"}
        )

    from municipios_colombia import get_municipios
    municipios = [m for m in get_municipios() if m["departamento"].lower() == dept.lower()]

    if not municipios:
        return JSONResponse(
            status_code=404,
            content={"error": f"No se encontraron municipios para '{dept}'"}
        )

    return iniciar({"municipios": municipios}, "departamento")


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
        "metricas": estado["metricas"],
        "tipo_ejecucion": estado["tipo_ejecucion"],
    }


@app.post("/test/callback")
async def test_callback(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        now = datetime.now()
        inicio_default = (now - timedelta(seconds=65)).isoformat()
        fin_default = now.isoformat()

        payload = {
            "evento": "overpass.finalizado",
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
                "municipios": 5,
                "queries_ok": 10,
                "queries_err": 2,
                "elementos_total": 40,
                "insertados": 20,
                "duplicados": 5,
                "aprobados": 12,
                "fallidos": 2
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
    print(f"🚀 Overpass API en http://localhost:{PORT}")
    print(f"   n8n: http://host.docker.internal:{PORT}")
    print(f"   webhook n8n: {N8N_WEBHOOK_URL}")
    print("   POST /scrape/overpass")
    print("   POST /scrape/overpass/prueba")
    print("   POST /scrape/overpass/depto")
    print("   GET  /status")
    print("   GET  /resultado")
    print("   GET  /health")
    print("   POST /test/callback")
    print("   GET  /endpoints\n")

    uvicorn.run(app, host="0.0.0.0", port=PORT)