"""
═══════════════════════════════════════════════════════════════════════════════
api_runner.py — API de Análisis de Cobertura por Municipio
═══════════════════════════════════════════════════════════════════════════════

Endpoints:
  POST  /analizar/cobertura  → Analiza municipios y retorna los de baja cobertura
  GET   /health              → Health check
  GET   /status              → Info del servicio

Flujo:
  1. n8n envía los 1,123 municipios en el body
  2. Esta API consulta las 4 tablas de BD (RUES, Google Maps, Páginas Amarillas, OSM)
  3. Cuenta registros por municipio en cada fuente
  4. Retorna municipios con total < umbral + las keywords recomendadas para Serper
  5. n8n toma esa respuesta y dispara SerperAPI con esos municipios y keywords
"""

import unicodedata
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional

from config import PORT, UMBRAL_BAJO_COBERTURA, KEYWORDS_SERPER, TABLAS_FUENTES, GRANDES_CIUDADES
from db import contar_registros_por_municipio, test_connection


# ═══════════════════════════════════════════════════════════════════════════════
# MODELOS
# ═══════════════════════════════════════════════════════════════════════════════

class MunicipioInput(BaseModel):
    municipio:    str
    departamento: str

class AnalisisRequest(BaseModel):
    municipios: List[MunicipioInput]
    umbral: Optional[int] = None            # Si no se envía, usa UMBRAL_BAJO_COBERTURA de config
    ignorar_umbral: bool = False            # True → retorna TODOS los municipios sin filtrar (modo prueba)
    keywords: Optional[List[str]] = None   # Si no se envía, usa KEYWORDS_SERPER de config
    solo_grandes_ciudades: bool = False    # True (con ignorar_umbral=False) → intersecta body con GRANDES_CIUDADES


# ═══════════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════════════════════

def _normalizar(texto: str) -> str:
    texto = texto.lower().strip()
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Argos — Análisis de Cobertura API",
    description="Identifica municipios con baja cobertura de datos para dirigir Serper estratégicamente.",
    version="1.0.0",
)


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    db_ok = test_connection()
    return {
        "status": "ok" if db_ok else "db_error",
        "db_conectada": db_ok,
        "port": PORT,
    }


@app.get("/status")
def status():
    return {
        "servicio":               "analisis-cobertura-api",
        "puerto":                 PORT,
        "umbral_default":         UMBRAL_BAJO_COBERTURA,
        "keywords_recomendadas":  KEYWORDS_SERPER,
        "fuentes_consultadas":    list(TABLAS_FUENTES.keys()),
    }


@app.post("/analizar/cobertura")
def analizar_cobertura(body: AnalisisRequest):
    """
    Recibe la lista de municipios, consulta las 4 fuentes en BD
    y retorna los municipios con baja cobertura + keywords para Serper.

    Body:
    {
        "municipios": [
            {"municipio": "Medellín", "departamento": "Antioquia"},
            ...
        ],
        "umbral": 5   // opcional, default: UMBRAL_BAJO_COBERTURA en config
    }

    Respuesta:
    {
        "resumen": {
            "total_municipios_analizados": 1123,
            "municipios_bajo_cobertura":   412,
            "municipios_cubiertos":        711,
            "umbral_usado":                5
        },
        "keywords": ["ferreterias", ...],
        "municipios_bajo_cobertura": [
            {
                "municipio":      "Támesis",
                "departamento":   "Antioquia",
                "total_registros": 1,
                "detalle": {
                    "rues": 1, "google_maps": 0,
                    "paginas_amarillas": 0, "openstreetmap": 0
                }
            },
            ...
        ]
    }
    """
    if not body.municipios:
        return JSONResponse(status_code=400, content={
            "status": "error",
            "detail": "municipios no puede estar vacío"
        })

    umbral = body.umbral if body.umbral is not None else UMBRAL_BAJO_COBERTURA

    municipios_dict = [
        {"municipio": m.municipio, "departamento": m.departamento}
        for m in body.municipios
    ]

    # Modo grandes ciudades: intersecta el body con la lista interna GRANDES_CIUDADES
    if not body.ignorar_umbral and body.solo_grandes_ciudades:
        grandes_norm = set(GRANDES_CIUDADES)
        coincidencias = [
            m for m in municipios_dict
            if _normalizar(m["municipio"]) in grandes_norm
        ]
        return {
            "resumen": {
                "total_municipios_analizados": len(municipios_dict),
                "total_retornados":            len(coincidencias),
                "modo":                        "grandes_ciudades",
            },
            "keywords":                    body.keywords if body.keywords else KEYWORDS_SERPER,
            "municipios_grandes_ciudades": coincidencias,
        }

    # Modo prueba: ignorar umbral y retornar todos los municipios tal como llegaron
    if body.ignorar_umbral:
        todos = [
            {
                "municipio":       m["municipio"],
                "departamento":    m["departamento"],
                "total_registros": None,
                "detalle":         None,
            }
            for m in municipios_dict
        ]
        return {
            "resumen": {
                "total_municipios_analizados": len(body.municipios),
                "municipios_bajo_cobertura":   len(todos),
                "municipios_cubiertos":        0,
                "umbral_usado":                "ignorado",
                "modo":                        "prueba_sin_filtro",
            },
            "keywords": body.keywords if body.keywords else KEYWORDS_SERPER,
            "municipios_bajo_cobertura": todos,
        }

    try:
        conteos = contar_registros_por_municipio(municipios_dict)
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "status": "error",
            "detail": f"Error consultando BD: {str(e)}"
        })

    bajo_cobertura = []
    cubiertos = 0

    for key, datos in conteos.items():
        if datos["total"] < umbral:
            bajo_cobertura.append({
                "municipio":       datos["municipio"],
                "departamento":    datos["departamento"],
                "total_registros": datos["total"],
                "detalle": {
                    "rues":              datos["rues"],
                    "google_maps":       datos["google_maps"],
                    "paginas_amarillas": datos["paginas_amarillas"],
                    "openstreetmap":     datos["openstreetmap"],
                }
            })
        else:
            cubiertos += 1

    # Ordenar de menor a mayor cobertura (los más críticos primero)
    bajo_cobertura.sort(key=lambda x: x["total_registros"])

    return {
        "resumen": {
            "total_municipios_analizados": len(body.municipios),
            "municipios_bajo_cobertura":   len(bajo_cobertura),
            "municipios_cubiertos":        cubiertos,
            "umbral_usado":                umbral,
            "modo":                        "filtro_activo",
        },
        "keywords": body.keywords if body.keywords else KEYWORDS_SERPER,
        "municipios_bajo_cobertura": bajo_cobertura,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*70)
    print("  ANÁLISIS DE COBERTURA API — INICIANDO")
    print("="*70)
    print(f"  Puerto:   http://localhost:{PORT}")
    print(f"  Swagger:  http://localhost:{PORT}/docs")
    print(f"  Umbral:   {UMBRAL_BAJO_COBERTURA} registros")
    print("="*70 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
