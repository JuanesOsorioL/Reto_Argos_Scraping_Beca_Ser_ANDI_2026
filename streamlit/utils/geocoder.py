"""
geocoder.py — Geocodificación de direcciones usando Nominatim (OpenStreetMap).

Convierte dirección + municipio + departamento en coordenadas lat/lon.
Usa un caché JSON persistente para evitar llamadas repetidas a la API.
Nominatim: gratuito, sin API key, límite 1 req/seg.
"""

import json
import os
import time

import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(_DIR, '..', 'data', 'geocoding_cache.json')
_USER_AGENT = "ArgosOpportunityDashboard/1.0 (reto-beca-andi-argos)"
_DELAY = 1.1  # segundos entre requests (Nominatim exige máx 1 req/seg)


# ── Caché ─────────────────────────────────────────────────────────────────────

def _leer_cache() -> dict:
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _guardar_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(CACHE_FILE)), exist_ok=True)
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ── Nominatim ─────────────────────────────────────────────────────────────────

def _nominatim(query: str) -> tuple[float, float] | None:
    """Llama a Nominatim. Retorna (lat, lon) o None si no encuentra."""
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "co"},
            headers={"User-Agent": _USER_AGENT},
            timeout=8,
        )
        results = resp.json()
        if results:
            return float(results[0]['lat']), float(results[0]['lon'])
    except Exception:
        pass
    return None


def geocodificar_uno(clave: str, direccion: str, municipio: str, departamento: str,
                     cache: dict | None = None, guardar: bool = True) -> tuple[float, float] | None:
    """
    Geocodifica un cliente. Usa caché si ya fue procesado.

    Args:
        clave:       Identificador único del cliente (código o hash dirección+ciudad)
        direccion:   Dirección (calle, número, etc.)
        municipio:   Nombre del municipio
        departamento: Nombre del departamento
        cache:       Dict de caché ya cargado (evita releer el JSON en bucles)
        guardar:     Si True, persiste el caché después de cada llamada
    Returns:
        (lat, lon) o None
    """
    if cache is None:
        cache = _leer_cache()

    if clave in cache:
        v = cache[clave]
        return (v['lat'], v['lon']) if v else None

    # Intento 1: dirección completa
    coords = None
    if direccion and municipio:
        coords = _nominatim(f"{direccion}, {municipio}, {departamento}, Colombia")
        time.sleep(_DELAY)

    # Intento 2: solo municipio + departamento
    if coords is None and municipio:
        coords = _nominatim(f"{municipio}, {departamento}, Colombia")
        time.sleep(_DELAY)

    cache[clave] = {"lat": coords[0], "lon": coords[1]} if coords else None
    if guardar:
        _guardar_cache(cache)

    return coords


def contar_sin_geocodificar(df, col_codigo: str) -> int:
    """Retorna cuántos clientes del df todavía no tienen coordenadas en el caché."""
    cache = _leer_cache()
    sin_geo = 0
    for _, row in df.iterrows():
        clave = str(row.get(col_codigo, ''))
        if not clave or clave == 'nan':
            clave = f"{row.get('dir_argos','')}|{row.get('ciudad_argos','')}|{row.get('depto_argos','')}"
        if clave not in cache:
            sin_geo += 1
    return sin_geo


def geocodificar_dataframe(df, col_codigo: str, progress_callback=None) -> None:
    """
    Agrega columnas 'geo_lat' y 'geo_lon' al df in-place con coordenadas geocodificadas.
    Solo llama a la API para clientes sin entrada en el caché.

    Args:
        df:               DataFrame con columnas dir_argos, ciudad_argos, depto_argos
        col_codigo:       Nombre de la columna que identifica al cliente (clave de caché)
        progress_callback: función(actual, total) llamada en cada paso (para barra de progreso)
    """
    if 'geo_lat' not in df.columns:
        df['geo_lat'] = None
    if 'geo_lon' not in df.columns:
        df['geo_lon'] = None

    cache = _leer_cache()
    total = len(df)

    for i, (idx, row) in enumerate(df.iterrows()):
        clave = str(row.get(col_codigo, ''))
        if not clave or clave == 'nan':
            clave = f"{row.get('dir_argos','')}|{row.get('ciudad_argos','')}|{row.get('depto_argos','')}"

        coords = geocodificar_uno(
            clave=clave,
            direccion=str(row.get('dir_argos', '')),
            municipio=str(row.get('ciudad_argos', '')),
            departamento=str(row.get('depto_argos', '')),
            cache=cache,
            guardar=False,   # guardamos al final en bloque
        )

        if coords:
            df.at[idx, 'geo_lat'] = coords[0]
            df.at[idx, 'geo_lon'] = coords[1]

        if progress_callback:
            progress_callback(i + 1, total)

    _guardar_cache(cache)
