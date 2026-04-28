"""
main.py - API de Consolidacion de Ferreterias

Al iniciar crea AUTOMATICAMENTE todas las tablas necesarias en PostgreSQL.
No se necesita correr ningun SQL manual.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import config
from db.connection import engine, test_connection
from db.init_db import wait_for_db, init_database
from routers import ejecuciones, empresas, staging, respaldos, openrouter_router, admin

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Iniciando API Ferreterias ===")

    # 1. Esperar a que PostgreSQL este disponible (util en Docker)
    db_ok = wait_for_db(engine, max_intentos=30, espera=2)

    if db_ok:
        # 2. Crear TODAS las tablas automaticamente si no existen
        init_database(engine)
    else:
        logger.warning("Sin conexion a DB al iniciar. Los endpoints de DB fallaran.")

    yield
    logger.info("=== API detenida ===")


app = FastAPI(
    title="API Consolidacion Ferreterias",
    description="""
## Pipeline de limpieza y consolidacion de datos de ferreterias

**Flujo desde n8n:**
```
n8n → POST /ejecuciones/iniciar (con municipios) → pipeline corre en background → webhook notifica a n8n
```

**Fases del pipeline:**
1. Carga raw.* (6 fuentes) → staging
2. Normalizacion de datos
3. Validacion sin RUES (Google + IA gratuita)
4. Deduplicacion con 7 reglas
5. Campos dudosos → JSON
6. IA para duplicados ambiguos (OpenRouter gratis)
7. Consolidacion → clean.empresas
8. Scoring + aprobacion (score >= 80 = aprobado_argos)
9. Webhook a n8n con resultado
""",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ejecuciones.router)
app.include_router(empresas.router)
app.include_router(staging.router)
app.include_router(respaldos.router)
app.include_router(openrouter_router.router)
app.include_router(admin.router)


@app.get("/", tags=["Info"])
def root():
    return {
        "api": "Consolidacion Ferreterias v2",
        "status": "running",
        "endpoints_principales": {
            "iniciar_pipeline":    "POST /ejecuciones/iniciar",
            "estado_pipeline":     "GET  /ejecuciones/{execution_id}",
            "listar_empresas":     "GET  /empresas",
            "detalle_empresa":     "GET  /empresas/{id}",
            "campos_dudosos":      "GET  /campos-dudosos",
            "posibles_matches":    "GET  /posibles-matches",
            "modelos_ia_gratis":   "GET  /openrouter/models",
            "docs":                "GET  /docs",
        },
    }


@app.get("/health", tags=["Info"])
def health():
    db_ok = test_connection()
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "status":      "ok" if db_ok else "sin_db",
            "database":    "conectada" if db_ok else "desconectada",
            "openrouter":  bool(config.OPENROUTER_API_KEY),
            "anthropic":   bool(config.ANTHROPIC_API_KEY),
            "n8n_webhook": bool(config.N8N_WEBHOOK_URL),
            "serper":      bool(config.SERPER_API_KEY),
        }
    )
