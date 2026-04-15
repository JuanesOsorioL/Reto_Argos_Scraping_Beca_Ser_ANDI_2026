"""
main.py — Scraper Overpass API para el proyecto Argos
======================================================

Fixes aplicados:
  1. text_search separado en query propia más liviana (sin regex complejo)
  2. Backoff exponencial con cap en 30s
  3. Si todos los endpoints fallan con 504/429, espera 60s y reintenta 1 vez
  4. JSON de fallidos (overpass-fallidos-RUNID.json) para trazabilidad
  5. Pausa entre queries aumentada a 2s para no saturar la API pública

Uso:
  python main.py              # todas las ciudades
  python main.py --test       # 5 ciudades de prueba
  python main.py --dept Antioquia
  python main.py --limit 50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg2
import requests
from psycopg2.extras import Json
from dotenv import load_dotenv

load_dotenv()

# ─── Configuración ────────────────────────────────────────────────────────────

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]

TIMEOUT_QUERY       = 90    # segundos por query
PAUSE_ENTRE_QUERIES = 2.0   # subido a 2s para respetar la API pública
MAX_INTENTOS        = 4     # intentos totales (no por endpoint)
ESPERA_SOBRECARGA   = 60    # si todos fallan, esperar 60s antes del último reintento

# Regex para text_search — más simple = más rápido en el servidor
TEXT_REGEX = r"(ferreter|cement|concret|morter|bloquera|ladriller|prefabric|deposito|material)"

# 5 familias de tags OSM
FAMILIAS_OSM = {
    "hardware": {
        "descripcion": "Ferreterías (shop=hardware)",
        "tags":        'nwr["shop"="hardware"](area.a);',
        "es_regex":    False,
    },
    "building_materials": {
        "descripcion": "Materiales de construcción (shop=building_materials)",
        "tags":        'nwr["shop"="building_materials"](area.a);',
        "es_regex":    False,
    },
    "trade_supplies": {
        "descripcion": "Trade / distribuidoras (shop=trade)",
        "tags":        'nwr["shop"="trade"](area.a); nwr["shop"="trade"]["trade"="building_supplies"](area.a);',
        "es_regex":    False,
    },
    "doityourself": {
        "descripcion": "Mejoramiento del hogar (shop=doityourself)",
        "tags":        'nwr["shop"="doityourself"](area.a);',
        "es_regex":    False,
    },
    "text_search": {
        "descripcion": "Búsqueda por nombre (regex)",
        "tags":        f'nwr["name"~"{TEXT_REGEX}", i](area.a);',
        "es_regex":    True,   # marcado para pausas extra
    },
}

# Score Argos
CIIU_RELEVANTES = {"4752", "4753", "4659", "4690", "2394", "2395"}
PALABRAS_ALTA   = ["ferreter", "cemento", "concreto", "mortero", "prefabric",
                   "bloquera", "ladriller", "deposito", "material construccion"]
ARGOS_THRESHOLD = 2

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME",     "postgres"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "password": os.getenv("DB_PASSWORD", "1234"),
}

OUTPUT_DIR = Path("output")
LOG_DIR    = Path("logs")

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "si", "sí", "on")


SAVE_LOG_FILES = env_bool("SAVE_LOG_FILES", False)
SAVE_OUTPUT_FILES = env_bool("SAVE_OUTPUT_FILES", False)

# ─── Logging ─────────────────────────────────────────────────────────────────
def setup_logging():
    handlers = [logging.StreamHandler(sys.stdout)]

    if SAVE_LOG_FILES:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fecha = datetime.now().strftime("%Y-%m-%d")
        handlers.append(
            logging.FileHandler(LOG_DIR / f"overpass-{fecha}.log", encoding="utf-8")
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


"""
Antes

def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now().strftime("%Y-%m-%d")
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / f"overpass-{fecha}.log", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
"""


log = logging.getLogger(__name__)

# ─── PostgreSQL ───────────────────────────────────────────────────────────────

_conn = None

def get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(**DB_CONFIG)
    return _conn

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS raw;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS raw.overpass_ferreterias (
                    id               SERIAL PRIMARY KEY,
                    hash_id          TEXT UNIQUE,
                    run_id           UUID        NOT NULL,
                    fecha_extraccion TIMESTAMP   NOT NULL DEFAULT NOW(),

                    -- Columnas requeridas por Argos
                    nit              TEXT,
                    nombre           TEXT,
                    departamento     TEXT,
                    municipio        TEXT,
                    direccion        TEXT,
                    latitud          DOUBLE PRECISION,
                    longitud         DOUBLE PRECISION,
                    telefono         TEXT,
                    whatsapp         TEXT,
                    correo_electronico TEXT,
                    fecha_actualizacion TIMESTAMP,
                    fuente           TEXT DEFAULT 'openstreetmap',

                    -- Score Argos
                    score            INTEGER,
                    aprobado_argos   BOOLEAN,

                    -- Datos OSM
                    osm_type         TEXT,
                    osm_id           BIGINT,
                    familia_osm      TEXT,
                    shop_tag         TEXT,
                    trade_tag        TEXT,
                    brand            TEXT,
                    operator_osm     TEXT,
                    opening_hours    TEXT,
                    website          TEXT,
                    email_osm        TEXT,
                    instagram        TEXT,
                    facebook         TEXT,
                    twitter          TEXT,
                    addr_street      TEXT,
                    addr_number      TEXT,
                    addr_city        TEXT,
                    addr_state       TEXT,
                    addr_postcode    TEXT,
                    description_osm  TEXT,

                    -- RAW completo (todos los tags sin excepción)
                    raw_response     JSONB
                );
                CREATE INDEX IF NOT EXISTS idx_ov_municipio  ON raw.overpass_ferreterias (municipio);
                CREATE INDEX IF NOT EXISTS idx_ov_dept       ON raw.overpass_ferreterias (departamento);
                CREATE INDEX IF NOT EXISTS idx_ov_aprobado   ON raw.overpass_ferreterias (aprobado_argos);
                CREATE INDEX IF NOT EXISTS idx_ov_run        ON raw.overpass_ferreterias (run_id);
                CREATE INDEX IF NOT EXISTS idx_ov_osm        ON raw.overpass_ferreterias (osm_type, osm_id);
                CREATE INDEX IF NOT EXISTS idx_ov_familia    ON raw.overpass_ferreterias (familia_osm);
            """)
        conn.commit()
    log.info("[DB] Tabla raw.overpass_ferreterias verificada.")

def cargar_hashes_procesados() -> Set[str]:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT hash_id FROM raw.overpass_ferreterias WHERE hash_id IS NOT NULL")
                return {row[0] for row in cur.fetchall()}
    except Exception as e:
        log.warning(f"[DB] No se pudo cargar hashes: {e}")
        return set()

def insertar_lugar(run_id: str, registro: dict) -> bool:
    sql = """
        INSERT INTO raw.overpass_ferreterias (
            hash_id, run_id,
            nit, nombre, departamento, municipio, direccion,
            latitud, longitud, telefono, whatsapp, correo_electronico, fuente,
            score, aprobado_argos,
            osm_type, osm_id, familia_osm, shop_tag, trade_tag,
            brand, operator_osm, opening_hours, website, email_osm,
            instagram, facebook, twitter,
            addr_street, addr_number, addr_city, addr_state, addr_postcode,
            description_osm, raw_response
        ) VALUES (
            %(hash_id)s, %(run_id)s,
            %(nit)s, %(nombre)s, %(departamento)s, %(municipio)s, %(direccion)s,
            %(latitud)s, %(longitud)s, %(telefono)s, %(whatsapp)s,
            %(correo_electronico)s, %(fuente)s,
            %(score)s, %(aprobado_argos)s,
            %(osm_type)s, %(osm_id)s, %(familia_osm)s, %(shop_tag)s, %(trade_tag)s,
            %(brand)s, %(operator_osm)s, %(opening_hours)s, %(website)s, %(email_osm)s,
            %(instagram)s, %(facebook)s, %(twitter)s,
            %(addr_street)s, %(addr_number)s, %(addr_city)s, %(addr_state)s,
            %(addr_postcode)s, %(description_osm)s, %(raw_response)s
        ) ON CONFLICT (hash_id) DO NOTHING
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                payload = {**registro, "raw_response": Json(registro.get("raw_response"))}
                cur.execute(sql, payload)
                inserted = cur.rowcount
            conn.commit()
        return inserted == 1
    except Exception as e:
        log.error(f"[DB] insertarLugar {registro.get('nombre')}: {e}")
        return False

# ─── Overpass Client ──────────────────────────────────────────────────────────

class OverpassClient:
    """
    Cliente con rotación de endpoints y backoff exponencial.
    Lógica mejorada:
      - Rota endpoints en cada intento
      - Backoff: 5s, 10s, 20s, 30s (cap)
      - Si todos los intentos fallan con 504/429, espera 60s extra y reintenta una vez
    """
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "argos-overpass-scraper/2.0"
        self._ep_idx = 0

    def _next_endpoint(self) -> str:
        ep = OVERPASS_ENDPOINTS[self._ep_idx % len(OVERPASS_ENDPOINTS)]
        self._ep_idx += 1
        return ep

    def query(self, ql: str, es_regex: bool = False) -> Tuple[dict, str]:
        """
        Ejecuta una query con reintentos inteligentes.
        Las queries regex tienen una pausa extra antes de ejecutarse.
        """
        if es_regex:
            time.sleep(1.0)  # pausa extra para queries regex — son más caras

        last_err = None

        for intento in range(MAX_INTENTOS):
            endpoint = self._next_endpoint()
            wait     = min(5 * (2 ** intento), 30)  # 5, 10, 20, 30

            try:
                resp = self.session.post(
                    endpoint,
                    data={"data": ql},
                    timeout=TIMEOUT_QUERY,
                )

                if resp.status_code == 429:
                    log.warning(f"  [429] Rate limit en {endpoint}, esperando {wait}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code in (502, 503, 504):
                    log.warning(f"  [{resp.status_code}] {endpoint}, esperando {wait}s...")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                time.sleep(PAUSE_ENTRE_QUERIES)
                return resp.json(), endpoint

            except requests.Timeout:
                log.warning(f"  [TIMEOUT] {endpoint}, esperando {wait}s...")
                last_err = "timeout"
                time.sleep(wait)
            except Exception as e:
                log.warning(f"  [ERROR] {endpoint}: {e}, esperando {wait}s...")
                last_err = str(e)
                time.sleep(wait)

        # Todos los intentos fallaron — pausa larga y un último intento
        log.warning(f"  [SOBRECARGA] Todos los endpoints fallaron. Esperando {ESPERA_SOBRECARGA}s antes de último reintento...")
        time.sleep(ESPERA_SOBRECARGA)

        endpoint = self._next_endpoint()
        try:
            resp = self.session.post(endpoint, data={"data": ql}, timeout=TIMEOUT_QUERY)
            resp.raise_for_status()
            time.sleep(PAUSE_ENTRE_QUERIES)
            log.info(f"  [RECUPERADO] {endpoint} respondió tras espera.")
            return resp.json(), endpoint
        except Exception as e:
            raise RuntimeError(f"Overpass no respondió después de {MAX_INTENTOS} intentos + 60s espera. Último: {e}")

# ─── Queries ─────────────────────────────────────────────────────────────────

def build_query(area_name: str, tags_body: str) -> str:
    safe = area_name.replace('"', '\\"')
    return f"""[out:json][timeout:{TIMEOUT_QUERY}];
area["name"="{safe}"]["boundary"="administrative"]->.a;
({tags_body});
out center tags qt;""".strip()

def area_candidates(municipio: str, departamento: str) -> List[str]:
    return list(dict.fromkeys([
        municipio,
        f"{municipio}, {departamento}",
        f"Municipio de {municipio}",
    ]))

# ─── Normalización ────────────────────────────────────────────────────────────

def calcular_score(nombre: str, familia: str) -> Tuple[int, bool]:
    score = 0
    if familia in ("hardware", "building_materials"):
        score += 5
    elif familia in ("trade_supplies", "doityourself"):
        score += 2

    texto = (nombre or "").lower()
    for p in PALABRAS_ALTA:
        if p in texto:
            score += 2

    return score, score >= ARGOS_THRESHOLD

def normalizar_elemento(element: dict, municipio: str, departamento: str, familia: str, run_id: str) -> Optional[dict]:
    tags     = element.get("tags") or {}
    osm_type = element.get("type")
    osm_id   = element.get("id")
    if not osm_type or osm_id is None:
        return None

    lat = element.get("lat") or (element.get("center") or {}).get("lat")
    lon = element.get("lon") or (element.get("center") or {}).get("lon")

    nombre   = tags.get("name") or tags.get("brand") or tags.get("operator") or ""
    telefono = tags.get("phone") or tags.get("contact:phone") or tags.get("phone_1") or ""
    whatsapp = tags.get("contact:whatsapp") or ""
    email    = tags.get("email") or tags.get("contact:email") or ""
    website  = tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
    calle    = tags.get("addr:street") or ""
    numero   = tags.get("addr:housenumber") or ""
    direccion= f"{calle} {numero}".strip() or tags.get("addr:full") or ""

    score, aprobado = calcular_score(nombre, familia)
    hash_id = hashlib.md5(f"overpass|{osm_type}|{osm_id}".encode()).hexdigest()

    return {
        "hash_id":           hash_id,
        "run_id":            run_id,
        "nit":               None,
        "nombre":            nombre or None,
        "departamento":      departamento,
        "municipio":         municipio,
        "direccion":         direccion or None,
        "latitud":           float(lat) if lat is not None else None,
        "longitud":          float(lon) if lon is not None else None,
        "telefono":          telefono or None,
        "whatsapp":          whatsapp or None,
        "correo_electronico": email or None,
        "fecha_actualizacion": None,
        "fuente":            "openstreetmap",
        "score":             score,
        "aprobado_argos":    aprobado,
        "osm_type":          osm_type,
        "osm_id":            int(osm_id),
        "familia_osm":       familia,
        "shop_tag":          tags.get("shop") or None,
        "trade_tag":         tags.get("trade") or None,
        "brand":             tags.get("brand") or None,
        "operator_osm":      tags.get("operator") or None,
        "opening_hours":     tags.get("opening_hours") or None,
        "website":           website or None,
        "email_osm":         email or None,
        "instagram":         tags.get("contact:instagram") or tags.get("instagram") or None,
        "facebook":          tags.get("contact:facebook") or tags.get("facebook") or None,
        "twitter":           tags.get("contact:twitter") or tags.get("twitter") or None,
        "addr_street":       tags.get("addr:street") or None,
        "addr_number":       tags.get("addr:housenumber") or None,
        "addr_city":         tags.get("addr:city") or None,
        "addr_state":        tags.get("addr:state") or None,
        "addr_postcode":     tags.get("addr:postcode") or None,
        "description_osm":   tags.get("description") or None,
        "raw_response":      {
            "osm_type": osm_type, "osm_id": osm_id,
            "lat": lat, "lon": lon,
            "familia": familia, "municipio": municipio, "departamento": departamento,
            "tags": tags,   # todos los tags sin excepción
        },
    }

# ─── JSONL helper ─────────────────────────────────────────────────────────────

def append_jsonl(filepath: Path, obj: dict):
    if not SAVE_OUTPUT_FILES:
        return
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        log.warning(f"[JSONL] Error: {e}")

"""
Antes

def append_jsonl(filepath: Path, obj: dict):
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        log.warning(f"[JSONL] Error: {e}")
"""

# ─── Orquestador ─────────────────────────────────────────────────────────────

async def do_scrape(opciones: dict = None):
    if opciones is None:
        opciones = {}

    from municipios_colombia import get_municipios
    municipios = opciones.get("municipios", get_municipios())

    run_id    = str(uuid.uuid4())
    inicio_at = datetime.now(timezone.utc)

    setup_logging()

    if SAVE_OUTPUT_FILES:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


    """
    Antes
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging()
    """
    

    log.info("=" * 60)
    log.info(f"OVERPASS SCRAPER — run_id: {run_id}")
    log.info(f"Inicio:            {inicio_at.isoformat()}")
    log.info(f"Municipios:        {len(municipios)}")
    log.info(f"Familias OSM:      {len(FAMILIAS_OSM)}")
    log.info(f"Queries estimadas: {len(municipios) * len(FAMILIAS_OSM)}")
    log.info(f"Pausa entre queries: {PAUSE_ENTRE_QUERIES}s")
    log.info("=" * 60)

    init_db()
    procesados = cargar_hashes_procesados()
    log.info(f"[BD] {len(procesados)} registros ya procesados")

    client     = OverpassClient()
    #jsonl_path = OUTPUT_DIR / f"overpass-{run_id}.jsonl"
    jsonl_path = OUTPUT_DIR / f"overpass-{run_id}.jsonl" if SAVE_OUTPUT_FILES else None


    # Acumuladores
    fallidos  = []   # queries que no respondieron — para JSON de trazabilidad
    raw_acum  = []   # respuestas crudas agrupadas

    metricas = {
        "run_id":          run_id,
        "inicio":          inicio_at.isoformat(),
        "municipios":      len(municipios),
        "queries_ok":      0,
        "queries_err":     0,
        "elementos_total": 0,
        "insertados":      0,
        "duplicados":      0,
        "aprobados":       0,
    }

    total_jobs = len(municipios) * len(FAMILIAS_OSM)
    job_num    = 0

    for muni_info in municipios:
        muni = muni_info["municipio"]
        dept = muni_info["departamento"]

        for familia_id, familia_meta in FAMILIAS_OSM.items():
            job_num += 1
            es_regex = familia_meta.get("es_regex", False)
            log.info(f"[{job_num}/{total_jobs}] {muni} ({dept}) | {familia_id}")

            resultado_ok  = False
            area_usada    = None
            error_final   = None

            for area_name in area_candidates(muni, dept):
                ql = build_query(area_name, familia_meta["tags"])
                try:
                    data, endpoint_used = client.query(ql, es_regex=es_regex)
                    elementos = data.get("elements", [])
                    log.info(f"  [OK] area='{area_name}' elementos={len(elementos)}")

                    raw_acum.append({
                        "municipio":       muni,
                        "departamento":    dept,
                        "familia":         familia_id,
                        "area_usada":      area_name,
                        "cant_elementos":  len(elementos),
                        "endpoint":        endpoint_used,
                        "raw_response":    data,
                    })

                    metricas["queries_ok"]      += 1
                    metricas["elementos_total"] += len(elementos)
                    area_usada   = area_name
                    resultado_ok = True

                    for element in elementos:
                        registro = normalizar_elemento(element, muni, dept, familia_id, run_id)
                        if not registro:
                            continue
                        if registro["hash_id"] in procesados:
                            metricas["duplicados"] += 1
                            continue
                        ok = insertar_lugar(run_id, registro)
                        if ok:
                            procesados.add(registro["hash_id"])
                            metricas["insertados"] += 1
                            if registro["aprobado_argos"]:
                                metricas["aprobados"] += 1
                            # JSONL en tiempo real
                            append_jsonl(jsonl_path, {
                                "tipo":          "lugar",
                                "run_id":        run_id,
                                "municipio":     muni,
                                "departamento":  dept,
                                "familia":       familia_id,
                                "nombre":        registro["nombre"],
                                "latitud":       registro["latitud"],
                                "longitud":      registro["longitud"],
                                "telefono":      registro["telefono"],
                                "score":         registro["score"],
                                "aprobado_argos":registro["aprobado_argos"],
                                "osm_type":      registro["osm_type"],
                                "osm_id":        registro["osm_id"],
                            })
                        else:
                            metricas["duplicados"] += 1

                    break  # área encontrada, no probar las otras variantes

                except Exception as e:
                    error_final = str(e)
                    log.warning(f"  [WARN] area='{area_name}' falló: {e}")
                    continue

            # Si ninguna variante funcionó — registrar como fallido
            if not resultado_ok:
                log.error(f"  [FALLIDO] {muni}/{dept}/{familia_id}")
                metricas["queries_err"] += 1
                fallido = {
                    "municipio":      muni,
                    "departamento":   dept,
                    "familia":        familia_id,
                    "descripcion":    familia_meta["descripcion"],
                    "error":          error_final,
                    "areas_probadas": area_candidates(muni, dept),
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                }
                fallidos.append(fallido)
                # También al JSONL para no perder nada
                append_jsonl(jsonl_path, {"tipo": "fallido", "run_id": run_id, **fallido})

    # ── Guardar todos los JSONs ───────────────────────────────────────────────
    fin_at     = datetime.now(timezone.utc)
    duracion_s = int((fin_at - inicio_at).total_seconds())
    metricas["fin"]      = fin_at.isoformat()
    metricas["duracion"] = f"{duracion_s // 60}m {duracion_s % 60}s"
    metricas["fallidos"] = len(fallidos)

    
    """
    
    
    
    
    
    
    
    # 1. Respuestas crudas agrupadas
    (OUTPUT_DIR / f"overpass-raw-{run_id}.json").write_text(
        json.dumps(raw_acum, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    log.info(f"[JSON] Guardado: output/overpass-raw-{run_id}.json")

    # 2. Fallidos — para retomar manualmente o en próxima corrida
    (OUTPUT_DIR / f"overpass-fallidos-{run_id}.json").write_text(
        json.dumps({
            "run_id":        run_id,
            "total_fallidos":len(fallidos),
            "generado":      fin_at.isoformat(),
            "nota":          "Estas queries no obtuvieron respuesta de Overpass. Pueden reintentarse en otra corrida.",
            "fallidos":      fallidos,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    log.info(f"[JSON] Guardado: output/overpass-fallidos-{run_id}.json ({len(fallidos)} queries fallidas)")

    # 3. Resumen
    (OUTPUT_DIR / f"overpass-resumen-{run_id}.json").write_text(
        json.dumps(metricas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(f"[JSON] Guardado: output/overpass-resumen-{run_id}.json")

    log.info("=" * 60)
    log.info("COMPLETADO")
    for k, v in metricas.items():
        log.info(f"  {k:<28} {v}")
    log.info(f"  JSONL (tiempo real):         output/overpass-{run_id}.jsonl")
    log.info("=" * 60)

    return metricas

    """

    if SAVE_OUTPUT_FILES:
        (OUTPUT_DIR / f"overpass-raw-{run_id}.json").write_text(
            json.dumps(raw_acum, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8"
        )
        log.info(f"[JSON] Guardado: output/overpass-raw-{run_id}.json")

        (OUTPUT_DIR / f"overpass-fallidos-{run_id}.json").write_text(
            json.dumps({
                "run_id": run_id,
                "total_fallidos": len(fallidos),
                "generado": fin_at.isoformat(),
                "nota": "Estas queries no obtuvieron respuesta de Overpass. Pueden reintentarse en otra corrida.",
                "fallidos": fallidos,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        log.info(f"[JSON] Guardado: output/overpass-fallidos-{run_id}.json ({len(fallidos)} queries fallidas)")

        (OUTPUT_DIR / f"overpass-resumen-{run_id}.json").write_text(
            json.dumps(metricas, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        log.info(f"[JSON] Guardado: output/overpass-resumen-{run_id}.json")
    else:
        log.info("[JSON] SAVE_OUTPUT_FILES=false → no se guardaron archivos output/")
    
    log.info("=" * 60)
    log.info("COMPLETADO")
    for k, v in metricas.items():
        log.info(f"  {k:<28} {v}")
    if SAVE_OUTPUT_FILES:
        log.info(f"  JSONL (tiempo real):         output/overpass-{run_id}.jsonl")
    else:
        log.info("  JSONL (tiempo real):         deshabilitado por SAVE_OUTPUT_FILES=false")

    log.info("=" * 60)

    return metricas


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="Overpass scraper para proyecto Argos")
    parser.add_argument("--test",  action="store_true", help="Solo 5 municipios de prueba")
    parser.add_argument("--dept",  type=str,            help="Solo un departamento específico")
    parser.add_argument("--limit", type=int,            help="Límite de municipios")
    args = parser.parse_args()

    from municipios_colombia import get_municipios
    municipios = get_municipios()

    if args.test:
        municipios = [
            {"departamento": "Antioquia",       "municipio": "Medellín"},
            {"departamento": "Cundinamarca",     "municipio": "Bogotá"},
            {"departamento": "Valle del Cauca",  "municipio": "Cali"},
            {"departamento": "Atlántico",        "municipio": "Barranquilla"},
            {"departamento": "Santander",        "municipio": "Bucaramanga"},
        ]
    elif args.dept:
        municipios = [m for m in municipios if m["departamento"].lower() == args.dept.lower()]
    elif args.limit:
        municipios = municipios[:args.limit]

    asyncio.run(do_scrape({"municipios": municipios}))