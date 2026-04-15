"""
api_runner.py — Servidor FastAPI para control remoto del scraping Foursquare
Puerto: 8006 (configurable en .env API_PORT)

Endpoints:
  POST /scrape/foursquare        → Iniciar scraping completo
  GET  /status                   → Estado actual
  GET  /progress                 → Ver progreso en tiempo real
  POST /pause                    → Pausar (manual)
  POST /resume                   → Reanudar (manual)
  POST /reset                    → Borrar archivos de progreso (NO BD)
  GET  /health                   → Health check
  GET  /stats                    → Estadísticas de BD
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import uvicorn
import uuid
import json
import os
from datetime import datetime

from config import API_PORT, API_HOST, OUTPUT_FILE, JSON_RAW_FILE, JSON_FLAT_FILE, PROGRESS_FILE
from db import init_db, obtener_estadisticas
from main import do_scrape

# ──────────────────────────────────────────────────────────────────────────────
# INICIALIZACIÓN DE FASTAPI
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Argos Foursquare API",
    description="API para scraping automático de ferreterías en Foursquare",
    version="1.0.0",
)

# CORS para permitir requests desde n8n
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────────────────────
# ESTADO GLOBAL
# ──────────────────────────────────────────────────────────────────────────────

estado_global = {
    "scraping_en_curso": False,
    "run_id": None,
    "inicio": None,
    "fin": None,
    "duracion": None,
    "ultimo_status": "sin_correr",
    "ultimo_error": None,
    "en_pausa": False,
    "pausa_razon": None,
}


async def ejecutar_background(run_id: str):
    """
    Ejecuta el scraping en background (no bloquea la API).
    
    Args:
        run_id: UUID de la corrida
    """
    global estado_global
    try:
        print(f"\n[API] 🚀 Iniciando scraping con run_id: {run_id}")
        await do_scrape()
        
        fin = datetime.now()
        duracion = (fin - datetime.fromisoformat(estado_global["inicio"])).total_seconds()
        
        estado_global.update({
            "scraping_en_curso": False,
            "fin": fin.isoformat(),
            "duracion": f"{duracion:.0f}s",
            "ultimo_status": "ok",
            "ultimo_error": None,
            "en_pausa": False,
        })
        print(f"[API] ✅ Scraping completado en {duracion:.0f}s")
    
    except Exception as e:
        fin = datetime.now()
        estado_global.update({
            "scraping_en_curso": False,
            "fin": fin.isoformat(),
            "ultimo_status": "error",
            "ultimo_error": str(e),
            "en_pausa": False,
        })
        print(f"[API] ❌ Error en scraping: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT: Health Check
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Status"])
def health():
    """
    Health check de la API.
    
    Returns:
        {"status": "ok"}
    """
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT: GET /status
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/status", tags=["Status"])
def get_status():
    """
    Obtiene estado actual del scraping.
    
    Returns:
        {
            "status": "ok|error|corriendo",
            "en_curso": bool,
            "run_id": str,
            "inicio": ISO datetime,
            "fin": ISO datetime,
            "duracion": str,
            "en_pausa": bool,
            "pausa_razon": str
        }
    """
    return {
        "status": estado_global["ultimo_status"],
        "en_curso": estado_global["scraping_en_curso"],
        "run_id": estado_global["run_id"],
        "inicio": estado_global["inicio"],
        "fin": estado_global["fin"],
        "duracion": estado_global["duracion"],
        "en_pausa": estado_global["en_pausa"],
        "pausa_razon": estado_global["pausa_razon"],
        "error": estado_global["ultimo_error"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT: GET /progress
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/progress", tags=["Status"])
def get_progress():
    """
    Obtiene progreso detallado desde el archivo foursquare_progress.json.
    
    Returns:
        dict con progreso actual
    """
    if not os.path.exists(PROGRESS_FILE):
        return {
            "status": "sin_datos",
            "mensaje": "No hay progreso guardado aún"
        }
    
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            progreso = json.load(f)
        return progreso
    except Exception as e:
        return {
            "status": "error",
            "mensaje": f"Error leyendo progreso: {e}"
        }


# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT: POST /scrape/foursquare
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/scrape/foursquare", tags=["Scraping"])
async def run_scraper():
    """
    Inicia un nuevo scraping de Foursquare.
    
    Returns:
        {
            "status": "iniciado",
            "run_id": UUID,
            "mensaje": str
        }
    
    Raises:
        409: Si hay un scraping en curso
    """
    global estado_global
    
    # Validar que no haya otro scraping en curso
    if estado_global["scraping_en_curso"]:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "ocupado",
                "run_id": estado_global["run_id"],
                "mensaje": "Scraping ya en curso. Espera a que termine."
            }
        )
    
    # Generar nuevo run_id
    run_id = str(uuid.uuid4())
    inicio = datetime.now()
    
    # Actualizar estado global
    estado_global.update({
        "scraping_en_curso": True,
        "run_id": run_id,
        "inicio": inicio.isoformat(),
        "fin": None,
        "duracion": None,
        "ultimo_status": "corriendo",
        "ultimo_error": None,
        "en_pausa": False,
    })
    
    # Inicializar BD
    init_db()
    
    # Ejecutar en background (no bloquea la API)
    asyncio.create_task(ejecutar_background(run_id))
    
    return {
        "status": "iniciado",
        "mensaje": "Scraping disparado. Consulta /status para ver progreso.",
        "run_id": run_id,
        "inicio": inicio.isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT: POST /pause
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/pause", tags=["Control"])
def pause_scraper():
    """
    Pausa manualmente el scraping en curso.
    Nota: Implementación actual es cosmética.
    El scraping puede pausarse automáticamente por 403.
    
    Returns:
        {"status": "pausado"}
    """
    global estado_global
    
    if not estado_global["scraping_en_curso"]:
        raise HTTPException(
            status_code=400,
            detail="No hay scraping en curso"
        )
    
    estado_global["en_pausa"] = True
    estado_global["pausa_razon"] = "manual"
    
    return {
        "status": "pausado",
        "razon": "manual",
        "run_id": estado_global["run_id"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT: POST /resume
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/resume", tags=["Control"])
def resume_scraper():
    """
    Reanuda un scraping pausado manualmente.
    
    Returns:
        {"status": "reanudado"}
    """
    global estado_global
    
    if not estado_global["en_pausa"]:
        raise HTTPException(
            status_code=400,
            detail="Scraping no está en pausa"
        )
    
    estado_global["en_pausa"] = False
    estado_global["pausa_razon"] = None
    
    return {
        "status": "reanudado",
        "run_id": estado_global["run_id"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT: POST /reset
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/reset", tags=["Control"])
def reset_all():
    """
    Borra todos los archivos de progreso y respaldo (JSONs).
    NO borra la base de datos PostgreSQL.
    
    Archivos borrados:
      - foursquare_progress.json
      - foursquare_ferreterias.jsonl
      - output/foursquare_raw_responses.json
      - output/foursquare_flat_results.json
    
    Returns:
        {"status": "reset", "archivos_borrados": [...]}
    """
    global estado_global
    
    if estado_global["scraping_en_curso"]:
        raise HTTPException(
            status_code=409,
            detail="No se puede hacer reset mientras hay scraping en curso"
        )
    
    archivos_borrados = []
    
    # Archivos a borrar
    archivos = [
        PROGRESS_FILE,
        OUTPUT_FILE,
        JSON_RAW_FILE,
        JSON_FLAT_FILE,
    ]
    
    for archivo in archivos:
        try:
            if os.path.exists(archivo):
                os.remove(archivo)
                archivos_borrados.append(archivo)
                print(f"[RESET] ✓ Borrado: {archivo}")
        except Exception as e:
            print(f"[RESET] ❌ Error borrando {archivo}: {e}")
    
    # Reset estado global
    estado_global.update({
        "scraping_en_curso": False,
        "run_id": None,
        "inicio": None,
        "fin": None,
        "duracion": None,
        "ultimo_status": "sin_correr",
        "ultimo_error": None,
        "en_pausa": False,
        "pausa_razon": None,
    })
    
    return {
        "status": "reset",
        "mensaje": "Archivos de progreso borrados (BD intacta)",
        "archivos_borrados": archivos_borrados,
        "nota": "PostgreSQL no fue borrado. Para limpiar BD, ejecuta SQL manualmente.",
    }


# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT: GET /stats
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/stats", tags=["Status"])
def get_stats():
    """
    Obtiene estadísticas de la base de datos.
    
    Returns:
        {
            "total_registros": int,
            "aprobados_argos": int,
            "municipios_unicos": int,
            "con_telefono": int,
            "con_website": int
        }
    """
    try:
        init_db()
        stats = obtener_estadisticas()
        return {
            "status": "ok",
            "datos": stats,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo estadísticas: {e}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# STARTUP EVENT
# ──────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    """Se ejecuta cuando inicia el servidor."""
    print(f"\n[API] 🚀 Foursquare Scraper API en http://0.0.0.0:{API_PORT}")
    print(f"[API] Documentación: http://0.0.0.0:{API_PORT}/docs")
    print(f"[API] Health: http://0.0.0.0:{API_PORT}/health")
    init_db()
    print(f"[API] ✓ Base de datos inicializada")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print(f"Foursquare Places API — Servidor HTTP")
    print(f"Puerto: {API_PORT}")
    print(f"Host: {API_HOST}")
    print(f"{'='*70}\n")
    
    uvicorn.run(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level="info",
    )



