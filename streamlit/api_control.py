"""
api_control.py — FastAPI de control del dashboard Argos.

Endpoints:
  GET  /health           → healthcheck para Docker
  GET  /status           → estado detallado del servicio
  POST /webhook/refresh  → recibe webhook de n8n, actualiza state file
  POST /control/stop     → detiene el servicio graciosamente
"""

import json
import os
import signal
import sys
from datetime import datetime, timezone

import psycopg2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Argos Dashboard Control API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE_FILE = os.getenv("STATE_FILE", os.path.join(os.path.dirname(__file__), "state", "refresh.json"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost:1111/postgres")
_START_TIME = datetime.now(timezone.utc)


# ── Modelos ──────────────────────────────────────────────────────────────────

class RefreshPayload(BaseModel):
    municipios: list[str] = []
    execution_id: str = ""
    empresas_consolidadas: int = 0
    triggered_by: str = "n8n"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _leer_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _escribir_state(data: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _check_db() -> bool:
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    state = _leer_state()
    uptime_sec = int((datetime.now(timezone.utc) - _START_TIME).total_seconds())
    db_ok = _check_db()

    return {
        "status": "running",
        "uptime_seconds": uptime_sec,
        "database_connected": db_ok,
        "last_refresh": {
            "timestamp":            state.get("timestamp"),
            "municipios":           state.get("municipios", []),
            "execution_id":         state.get("execution_id"),
            "empresas_consolidadas": state.get("empresas_consolidadas"),
            "triggered_by":         state.get("triggered_by"),
        },
    }


@app.post("/webhook/refresh")
def webhook_refresh(payload: RefreshPayload):
    """
    Recibe el webhook de n8n al finalizar el pipeline.
    Escribe state/refresh.json → Streamlit lo detecta y se refresca.
    """
    state = {
        "timestamp":             datetime.now(timezone.utc).isoformat(),
        "municipios":            payload.municipios,
        "execution_id":          payload.execution_id,
        "empresas_consolidadas": payload.empresas_consolidadas,
        "triggered_by":          payload.triggered_by,
    }
    _escribir_state(state)

    muns_str = ",".join(payload.municipios)
    return {
        "ok": True,
        "message": "Dashboard refresh programado",
        "municipios_count": len(payload.municipios),
        "dashboard_url": f"http://localhost:8050?municipios={muns_str}",
    }


@app.post("/control/stop")
def control_stop():
    """Detiene el proceso graciosamente (útil desde n8n)."""
    def _shutdown():
        import time
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

    import threading
    threading.Thread(target=_shutdown, daemon=True).start()
    return {"ok": True, "message": "Servicio deteniendo..."}
