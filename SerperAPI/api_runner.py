"""
═══════════════════════════════════════════════════════════════════════════════
api_runner.py — API FastAPI para controlar el scraper Serper
═══════════════════════════════════════════════════════════════════════════════

Endpoints:
  POST   /scrape/serper          → Iniciar scraping producción completo
  POST   /scrape/serper/prueba   → Prueba rápida (2 keywords × 2 ciudades)
  POST   /pause                  → Pausar scraping actual
  POST   /resume                 → Reanudar desde donde se pausó
  GET    /progress               → Ver estado actual (para n8n polling)
  GET    /status                 → Estado sin progreso file
  GET    /health                 → Health check simple
  GET    /endpoints              → Listar todos los endpoints
  POST   /reset                  → ⚠️ Borra TODO y empieza de cero
  POST   /test/callback          → Testear webhook a n8n

Para n8n:
  - Hacer polling a GET /progress cada 1-2 minutos
  - Detectar status = "pausado_sin_tokens" para reanudar automáticamente
  - Enviar notificaciones cuando status = "ok" o "error"
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import asyncio
import uvicorn
import uuid
import os
import json
from datetime import datetime, timedelta
import httpx

from config import PORT, N8N_WEBHOOK_URL, PROGRESS_FILE, CIUDAD_DEPARTAMENTO, KEYWORDS_BUSQUEDA
from db import reset_all

from pydantic import BaseModel
from typing import List

class UbicacionModel(BaseModel):
    municipio: str
    departamento: str
    total_registros: int | None = None
    detalle: str | None = None

class ScrapSerperRequest(BaseModel):
    """Body para POST /scrape/serper — todos los campos son opcionales"""
    selected_locations: List[UbicacionModel] | None = None
    keywords: List[str] | None = None

# ═══════════════════════════════════════════════════════════════════════════════
# CREAR APP FASTAPI
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Argos Serper Scraper API",
    description="API para scraping de Serper con pausa automática y webhooks",
    version="2.0.0"
)


# ═══════════════════════════════════════════════════════════════════════════════
# ESTADO GLOBAL DE LA APLICACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

# Este diccionario guarda el estado actual del scraper en memoria
# Se actualiza continuamente mientras corre main.py
estado = {
    "scraping_en_curso": False,    # ¿Hay un scraping activo?
    "run_id": None,                # UUID del run actual
    "inicio": None,                # Timestamp de inicio
    "fin": None,                   # Timestamp de fin
    "duracion": None,              # Duración en formato "1h 15m"
    "ultimo_status": "sin_correr", # sin_correr | corriendo | pausado_* | ok | error
    "ultimo_error": None,          # Último error si hubo
    "metricas": None,              # Diccionario con métricas finales
    "tipo_ejecucion": None,        # produccion | prueba | resume
    "limit_keywords": None,        # Si es prueba, cuántos keywords
    "limit_cities": None,          # Si es prueba, cuántas ciudades
}


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES
# ═══════════════════════════════════════════════════════════════════════════════

def calcular_duracion(inicio_iso, fin_iso):
    """
    Calcula la duración entre dos timestamps ISO.
    
    Args:
        inicio_iso (str): Timestamp inicio (ISO format)
        fin_iso (str): Timestamp fin (ISO format)
    
    Returns:
        str: Duración en formato "1h 15m 30s"
    """
    if not inicio_iso or not fin_iso:
        return None
    try:
        inicio = datetime.fromisoformat(inicio_iso)
        fin = datetime.fromisoformat(fin_iso)
        duracion_s = max(0, round((fin - inicio).total_seconds()))
        
        horas = duracion_s // 3600
        minutos = (duracion_s % 3600) // 60
        segundos = duracion_s % 60
        
        if horas > 0:
            return f"{horas}h {minutos}m {segundos}s"
        else:
            return f"{minutos}m {segundos}s"
    except Exception:
        return None


def leer_progress():
    """
    Lee el archivo serper_progress.json.
    
    Returns:
        dict: Diccionario con el progreso, o None si no existe
    """
    if not os.path.exists(PROGRESS_FILE):
        return None
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"status": "error_leyendo_progress", "error": str(e)}


async def enviar_callback(payload: dict, headers: dict | None = None):
    """
    Envía un callback (webhook) a n8n.
    
    Args:
        payload (dict): Datos a enviar
        headers (dict): Headers HTTP adicionales
    
    Raises:
        ValueError: Si N8N_WEBHOOK_URL no está configurada
        httpx.RequestException: Si la petición falla
    """
    if not N8N_WEBHOOK_URL:
        raise ValueError("N8N_WEBHOOK_URL no está configurada en .env")
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            N8N_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json", **(headers or {})}
        )
        response.raise_for_status()


async def notificar_fin_run(payload: dict):
    """
    Notifica a n8n que un run finalizó (éxito o error).
    
    Args:
        payload (dict): Datos con evento, status, run_id, métricas, etc
    """
    try:
        await enviar_callback(payload)
        print(f"[WEBHOOK] ✅ Enviado a n8n. evento={payload.get('evento')} run_id={payload.get('run_id')}")
    except Exception as e:
        print(f"[WEBHOOK] ❌ Error enviando a n8n: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL: Ejecutar background
# ═══════════════════════════════════════════════════════════════════════════════

async def ejecutar_background(run_id, ciudades: list, limit_keywords=None, limit_cities=None, tipo_ejecucion="produccion", keywords=None):
    """
    Ejecuta el scraping en background (no bloquea la API).

    Importa main.py, llama do_scrape(), captura excepciones,
    actualiza estado global y notifica a n8n.

    Args:
        run_id (str): UUID único del run
        limit_keywords (int): Si prueba, cuántos keywords
        limit_cities (int): Si prueba, cuántas ciudades
        tipo_ejecucion (str): "produccion" | "prueba" | "resume"
        keywords (list[str]): Keywords personalizadas; si None usa las de config
    """
    global estado

    try:
        # Importar aquí para evitar circular imports
        from main import do_scrape, PauseRequested, TokensDepletedPause

        # Llamar la función principal
        metricas = await do_scrape(ciudades=ciudades, limit_keywords=limit_keywords, page=1, keywords=keywords)
        
        # Calcular fin y duración
        fin = datetime.now().isoformat()
        duracion = metricas.get("duracion") if isinstance(metricas, dict) else \
                   calcular_duracion(estado["inicio"], fin)
        
        # Actualizar estado global
        estado.update({
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": duracion,
            "ultimo_status": "ok",
            "ultimo_error": None,
            "metricas": metricas if isinstance(metricas, dict) else None,
        })
        
        # Notificar a n8n
        await notificar_fin_run({
            "evento": "serper.finalizado",
            "status": "ok",
            "run_id": run_id,
            "inicio": estado["inicio"],
            "fin": fin,
            "duracion": duracion,
            "metricas": estado["metricas"],
            "origen": "api_runner",
            "tipo_ejecucion": tipo_ejecucion,
        })
    
    # ─── PAUSA POR TOKENS AGOTADOS ──────────────────────────────────────────
    except TokensDepletedPause as e:
        fin = datetime.now().isoformat()
        estado.update({
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": calcular_duracion(estado["inicio"], fin),
            "ultimo_status": "pausado_sin_tokens",
            "ultimo_error": str(e),
            "metricas": leer_progress(),
        })
        
        # Notificar a n8n para que reintente después
        await notificar_fin_run({
            "evento": "serper.pausado_tokens",
            "status": "pausado_sin_tokens",
            "run_id": run_id,
            "inicio": estado["inicio"],
            "fin": fin,
            "duracion": estado["duracion"],
            "error": str(e),
            "origen": "api_runner",
            "tipo_ejecucion": tipo_ejecucion,
        })
    
    # ─── PAUSA MANUAL ──────────────────────────────────────────────────────
    except PauseRequested as e:
        fin = datetime.now().isoformat()
        estado.update({
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": calcular_duracion(estado["inicio"], fin),
            "ultimo_status": "pausado_manual",
            "ultimo_error": str(e),
            "metricas": leer_progress(),
        })
    
    # ─── ERROR CRÍTICO ──────────────────────────────────────────────────────
    except Exception as e:
        fin = datetime.now().isoformat()
        estado.update({
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": calcular_duracion(estado["inicio"], fin),
            "ultimo_status": "error",
            "ultimo_error": str(e),
            "metricas": leer_progress(),
        })
        
        # Notificar error a n8n
        await notificar_fin_run({
            "evento": "serper.finalizado",
            "status": "error",
            "run_id": run_id,
            "inicio": estado["inicio"],
            "fin": fin,
            "duracion": estado["duracion"],
            "error": str(e),
            "origen": "api_runner",
            "tipo_ejecucion": tipo_ejecucion,
        })


def iniciar(ciudades: list, limit_keywords=None, limit_cities=None, tipo_ejecucion="produccion", keywords=None):
    """
    Inicia un nuevo scraping en background.

    Args:
        ciudades (list[dict]): REQUERIDO. Lista de ciudades a procesar
        limit_keywords (int): Si int, solo procesar primeros N keywords
        limit_cities (int): Si int, solo procesar primeras N ciudades
        tipo_ejecucion (str): "produccion" | "prueba" | "resume"
        keywords (list[str]): Keywords personalizadas; si None usa las de config

    Returns:
        tuple: (run_id, inicio) o None si ya hay uno en curso
    """
    global estado
    
    # Verificar si ya hay uno en curso
    if estado["scraping_en_curso"]:
        return None
    
    # Generar nuevo run_id
    run_id = str(uuid.uuid4())
    inicio = datetime.now().isoformat()
    
    # Actualizar estado
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
        "limit_keywords": limit_keywords,
        "limit_cities": limit_cities,
    })
    
    # Crear tarea en background (no bloquea)
    asyncio.create_task(
        ejecutar_background(
            run_id=run_id,
            ciudades=ciudades,
            limit_keywords=limit_keywords,
            limit_cities=limit_cities,
            tipo_ejecucion=tipo_ejecucion,
            keywords=keywords,
        )
    )
    
    return run_id, inicio


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS HTTP
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    """
    Health check simple.
    
    Usado por:
      - Kubernetes/Docker para verificar que la app está viva
      - n8n para ver si está accesible
    
    Returns:
        dict: {"status": "ok", "code": 200}
    """
    return {"status": "ok", "code": 200}


@app.get("/status")
def status():
    """
    Estado actual del scraper sin incluir el progreso file.
    
    Retorna lo que hay en memoria (rápido).
    
    Returns:
        dict: Estado con run_id, inicio, fin, duracion, error, métricas
    """
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


@app.get("/progress")
def progress():
    """
    Estado detallado leyendo el archivo serper_progress.json.
    
    Usado por n8n para polling cada 1-2 minutos.
    Contiene información granular: índice actual, queries_hechas, etc.
    
    Returns:
        dict: Contenido de serper_progress.json (actualizado en tiempo real)
    """
    return leer_progress() or {"status": "sin_progress_file"}


@app.get("/endpoints")
def endpoints():
    """
    Lista todos los endpoints disponibles en la API.
    
    Útil para discovery y documentación.
    
    Returns:
        list: Lista de {"path": "/...", "methods": ["GET", "POST"]}
    """
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


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS DE SCRAPING
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/scrape/serper")
async def run_completo(request: ScrapSerperRequest):
    """
    Inicia un scraping PRODUCCIÓN COMPLETO con ciudades dinámicas.
    
    Body REQUERIDO:
    {
        "selected_locations": [
            {"municipio": "bogota", "departamento": "Cundinamarca"},
            {"municipio": "cali", "departamento": "Valle del Cauca"}
        ]
    }
    
    Returns:
        dict: {"status": "iniciado", "run_id": "uuid", "inicio": timestamp}
    
    Ejemplo (curl):
        curl -X POST http://localhost:8004/scrape/serper \\
            -H "Content-Type: application/json" \\
            -d '{"selected_locations": [{"municipio": "bogota", "departamento": "Cundinamarca"}]}'
    """
    
    # Construir lista de ciudades — si no llega nada, usar defaults de config
    if not request.selected_locations:
        ciudades = [{"municipio": k, "departamento": v} for k, v in CIUDAD_DEPARTAMENTO.items()]
        print(f"  ⚠️  selected_locations no enviado — usando {len(ciudades)} ciudades por defecto")
    else:
        ciudades = [
            {"municipio": loc.municipio.lower(), "departamento": loc.departamento}
            for loc in request.selected_locations
        ]

    keywords_efectivos = request.keywords if request.keywords else KEYWORDS_BUSQUEDA
    print(f"  📍 Municipios recibidos: {len(ciudades)}")
    print(f"  🔑 Keywords recibidas:   {len(keywords_efectivos)}")
    print(f"  🔢 Total queries:        {len(ciudades) * len(keywords_efectivos)}")

    # Verificar si ya hay uno en curso
    if estado["scraping_en_curso"]:
        return JSONResponse(status_code=409, content={
            "status": "ocupado",
            "mensaje": "Ya hay un scraping en curso",
            "run_id": estado["run_id"]
        })
    
    result = iniciar(
        ciudades=ciudades,
        limit_keywords=None,
        limit_cities=None,
        tipo_ejecucion="produccion",
        keywords=request.keywords or None,
    )
    
    if not result:
        return JSONResponse(status_code=409, content={
            "status": "ocupado",
            "mensaje": "Ya hay un scraping en curso",
            "run_id": estado["run_id"],
            "inicio": estado["inicio"]
        })
    
    run_id, inicio = result
    
    return {
        "status": "iniciado",
        "mensaje": "Scraper disparado con ciudades dinámicas. Consulta /status para ver el progreso.",
        "run_id": run_id,
        "inicio": inicio,
        "ciudades": ciudades,  # ✅ AGREGAR
        "cantidad_ciudades": len(ciudades),  # ✅ AGREGAR
    }


@app.post("/scrape/serper/prueba")
async def run_prueba():
    """
    Inicia una PRUEBA RÁPIDA.
    
    Procesa solo 2 keywords × 2 ciudades = 4 queries.
    Perfecto para testear antes de lanzar producción.
    
    Tiempo: ~30 segundos
    
    Returns:
        dict: {"status": "iniciado", "run_id": "uuid", ...}
    
    Ejemplo (curl):
        curl -X POST http://localhost:8004/scrape/serper/prueba
    """
    
    if estado["scraping_en_curso"]:
        return JSONResponse(status_code=409, content={
            "status": "ocupado",
            "run_id": estado["run_id"]
        })
    
    result = iniciar(limit_keywords=2, limit_cities=2, tipo_ejecucion="prueba")
    run_id, inicio = result
    
    return {
        "status": "iniciado",
        "run_id": run_id,
        "inicio": inicio,
        "tipo_ejecucion": "prueba",
        "mensaje": "Prueba iniciada (2 keywords × 2 ciudades)."
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS DE CONTROL (PAUSE / RESUME)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/pause")
async def pause():
    """
    Solicita una PAUSA MANUAL del scraping actual.
    
    El scraper se detiene de forma limpia:
      - Guarda progreso
      - Guarda estado en serper_progress.json
      - No pierde datos en PostgreSQL
    
    Luego puedes llamar POST /resume para continuar.
    
    Returns:
        dict: {"status": "ok", "mensaje": "Pausa solicitada"}
    
    Ejemplo (curl):
        curl -X POST http://localhost:8004/pause
    """
    try:
        # Importar la función de main.py
        from main import request_pause
        
        # Activar la bandera
        request_pause()
        
        return {"status": "ok", "mensaje": "Pausa solicitada."}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)}
        )


@app.post("/resume")
async def resume():
    """
    REANUDA un scraping pausado.
    
    Continúa exactamente donde se quedó:
      - Lee serper_progress.json
      - Salta queries ya procesadas
      - Continúa desde la siguiente
    
    Útil después de:
      - POST /pause (pausa manual)
      - Rate limit automático (pausado_sin_tokens)
      - Crash de la app (reanudación automática)
    
    Returns:
        dict: {"status": "iniciado", "run_id": "nuevo_uuid", ...}
    
    Ejemplo (curl):
        curl -X POST http://localhost:8004/resume
    """
    
    # No permitir resume si ya hay uno en curso
    if estado["scraping_en_curso"]:
        return JSONResponse(status_code=409, content={
            "status": "ocupado",
            "run_id": estado["run_id"]
        })
    
    # Iniciar con mismos parámetros de antes
    result = iniciar(
        limit_keywords=estado.get("limit_keywords"),
        limit_cities=estado.get("limit_cities"),
        tipo_ejecucion="resume"
    )
    
    if result is None:
        return JSONResponse(status_code=409, content={
            "status": "error",
            "error": "No se pudo iniciar el resume"
        })
    
    run_id, inicio = result
    
    return {
        "status": "iniciado",
        "run_id": run_id,
        "inicio": inicio,
        "tipo_ejecucion": "resume",
        "mensaje": "Reanudación disparada. Continúa desde donde se pausó."
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT DE RESET (⚠️ PELIGROSO)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/reset")
async def reset():
    """
    ⚠️ PELIGROSO: Borra TODO y empieza de cero.
    
    Acciones:
      1. Detiene el scraping en curso (si hay)
      2. Borra TODOS los registros de PostgreSQL
      3. Borra serper_progress.json
      4. Borra archivos JSON (si existen)
    
    Datos PERDIDOS:
      - Todas las consultas (raw.serper_consultas_construccion)
      - Todos los resultados (raw.serper_resultados_construccion)
      - El progreso guardado
    
    ⚠️ CUIDADO: Esta operación es IRREVERSIBLE.
    
    Casos de uso:
      - Limpiar testing fallido
      - Empezar de cero
      - Cambiar parámetros de búsqueda
    
    Returns:
        dict: {"status": "ok", "mensaje": "Todo borrado y reseteado"}
    
    Ejemplo (curl):
        curl -X POST http://localhost:8004/reset
    """
    global estado
    
    try:
        # Parar scraping en curso
        from main import CONTROL
        CONTROL["pause_requested"] = True
        estado["scraping_en_curso"] = False
        
        # Borrar datos de PostgreSQL
        reset_all()
        
        # Borrar archivo de progreso
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
        
        # Borrar archivos JSON locales
        from config import RAW_JSON_FILE, FLAT_JSON_FILE
        for file in [RAW_JSON_FILE, FLAT_JSON_FILE]:
            if os.path.exists(file):
                os.remove(file)
        
        # Resetear estado global
        estado.update({
            "scraping_en_curso": False,
            "run_id": None,
            "inicio": None,
            "fin": None,
            "duracion": None,
            "ultimo_status": "sin_correr",
            "ultimo_error": None,
            "metricas": None,
            "tipo_ejecucion": None,
        })
        
        return {
            "status": "ok",
            "mensaje": "⚠️ Todo reseteado. PostgreSQL, progress.json y JSON locales borrados."
        }
    
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)}
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT DE TEST: Callback a n8n
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/test/callback")
async def test_callback(request: Request):
    """
    Testea el webhook a n8n sin hacer scraping.
    
    Simula un evento "serper.finalizado" y lo envía a N8N_WEBHOOK_URL.
    Útil para verificar que n8n está escuchando.
    
    Returns:
        dict: {"status": "ok", "webhook_n8n": "url", "payload_enviado": {...}}
    
    Ejemplo (curl):
        curl -X POST http://localhost:8004/test/callback \
             -H "Content-Type: application/json" \
             -d '{"status": "ok"}'
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    try:
        # Crear payload de ejemplo
        now = datetime.now()
        payload = {
            "evento": "serper.finalizado",
            "status": body.get("status", "ok"),
            "run_id": body.get("run_id", "test-run-001"),
            "inicio": body.get("inicio", (now - timedelta(seconds=65)).isoformat()),
            "fin": body.get("fin", now.isoformat()),
            "duracion": body.get("duracion", "1m 5s"),
            "metricas": body.get("metricas", {
                "queries_total": 4,
                "queries_hechas": 2,
                "registros_nuevos": 45,
                "aprobados_argos": 12
            }),
            "origen": "api_runner",
            "tipo_ejecucion": body.get("tipo_ejecucion", "test_callback")
        }
        
        # Agregar error si status es error
        if payload["status"] == "error":
            payload["error"] = body.get("error", "Error de prueba")
        
        # Enviar el callback
        await enviar_callback(payload)
        
        return {
            "status": "ok",
            "mensaje": "✅ Callback enviado a n8n",
            "webhook_n8n": N8N_WEBHOOK_URL,
            "payload_enviado": payload
        }
    
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "webhook_url": N8N_WEBHOOK_URL
            }
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA: main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  🚀 SERPER API — INICIANDO")
    print("="*80)
    print(f"  Puerto:           http://localhost:{PORT}")
    print(f"  Swagger:          http://localhost:{PORT}/docs")
    print(f"  Webhook n8n:      {N8N_WEBHOOK_URL if N8N_WEBHOOK_URL else '(no configurado)'}")
    print(f"  Progress file:    {PROGRESS_FILE}")
    print("="*80 + "\n")
    
    # Iniciar servidor
    uvicorn.run(
        app,
        host="0.0.0.0",  # Escuchar en todas las interfaces
        port=PORT,
        log_level="info"
    )
