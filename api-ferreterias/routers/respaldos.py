"""
routers/respaldos.py - Descarga de archivos de respaldo generados
"""

import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/descargar", tags=["Respaldos"])

RUTAS_PERMITIDAS = [
    "/respaldos",
]


@router.get("/respaldos/{archivo:path}", summary="Descargar archivo de respaldo")
def descargar_respaldo(archivo: str):
    """
    Descarga un archivo de respaldo por nombre.

    Ejemplos:
    - `GET /descargar/respaldos/campos_dudosos/campos_dudosos_20240115_103000.json`
    - `GET /descargar/respaldos/posibles_matches/posibles_matches_20240115_103000.json`
    - `GET /descargar/respaldos/reporte_ejecucion/reporte_exec-20240115-abc123.json`
    """
    # Seguridad: prevenir path traversal
    archivo_limpio = archivo.replace("..", "").lstrip("/")
    ruta = Path(f"/respaldos/{archivo_limpio}")

    # Verificar que está dentro de /respaldos
    try:
        ruta_abs = ruta.resolve()
        if not str(ruta_abs).startswith("/respaldos"):
            raise HTTPException(status_code=403, detail="Acceso denegado")
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    if not ruta.exists():
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {archivo}")

    if not ruta.is_file():
        raise HTTPException(status_code=400, detail="La ruta no es un archivo")

    # Determinar media type
    media_type = "application/octet-stream"
    if archivo.endswith(".json"):
        media_type = "application/json"
    elif archivo.endswith(".csv"):
        media_type = "text/csv"
    elif archivo.endswith(".xlsx"):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return FileResponse(
        path=str(ruta),
        filename=ruta.name,
        media_type=media_type,
    )


@router.get("/respaldos", summary="Listar archivos de respaldo disponibles")
def listar_respaldos():
    """Lista todos los archivos de respaldo disponibles para descarga."""
    base = Path("/respaldos")
    if not base.exists():
        return {"archivos": [], "mensaje": "Directorio de respaldos vacío"}

    archivos = []
    for archivo in sorted(base.rglob("*"), reverse=True):
        if archivo.is_file():
            rel = str(archivo.relative_to(base))
            stat = archivo.stat()
            archivos.append({
                "nombre": archivo.name,
                "ruta_relativa": rel,
                "url_descarga": f"/descargar/respaldos/{rel}",
                "tamaño_kb": round(stat.st_size / 1024, 1),
                "modificado": archivo.stat().st_mtime,
            })

    return {
        "total": len(archivos),
        "archivos": archivos[:100],  # máx 100
    }
