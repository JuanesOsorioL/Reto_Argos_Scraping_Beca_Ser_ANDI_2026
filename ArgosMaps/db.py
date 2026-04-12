"""
db.py — PostgreSQL para scraper Google Maps
Tabla destino: raw.google_maps_ferreterias

Columnas requeridas por Argos:
  nit, nombre, departamento, municipio, direccion,
  latitud, longitud, telefono, whatsapp, correo_electronico,
  fecha_actualizacion, fuente

Columnas adicionales de trazabilidad y calidad:
  id, hash_id, run_id, fecha_extraccion, sucursal_tipo,
  categorias_maps, descripcion, keyword_busqueda,
  url, score, aprobado_argos
"""
import psycopg2
from config import DB_CONFIG


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def init_db():
    """Crea el esquema raw y la tabla si no existen."""
    ddl = """
    CREATE SCHEMA IF NOT EXISTS raw;

    CREATE TABLE IF NOT EXISTS raw.google_maps_ferreterias (

        -- ── Identidad y trazabilidad ─────────────────────────────────────
        id                    SERIAL PRIMARY KEY,
        hash_id               TEXT UNIQUE,
        run_id                UUID        NOT NULL,
        fecha_extraccion      TIMESTAMP   NOT NULL DEFAULT NOW(),

        -- ── Columnas requeridas por Argos (mismo orden que PA) ───────────
        nit                   TEXT,
        nombre                TEXT,
        departamento          TEXT,
        municipio             TEXT,
        direccion             TEXT,
        latitud               DOUBLE PRECISION,
        longitud              DOUBLE PRECISION,
        telefono              TEXT,
        whatsapp              TEXT,
        correo_electronico    TEXT,
        fecha_actualizacion   TIMESTAMP,
        fuente                TEXT DEFAULT 'google_maps',

        -- ── Columnas adicionales de calidad ──────────────────────────────
        sucursal_tipo         TEXT DEFAULT 'Principal',
        categorias_maps       TEXT[],
        descripcion           TEXT,
        keyword_busqueda      TEXT,
        url                   TEXT,
        score                 INTEGER,
        aprobado_argos        BOOLEAN
    );

    CREATE INDEX IF NOT EXISTS idx_gm_municipio    ON raw.google_maps_ferreterias (municipio);
    CREATE INDEX IF NOT EXISTS idx_gm_departamento ON raw.google_maps_ferreterias (departamento);
    CREATE INDEX IF NOT EXISTS idx_gm_aprobado     ON raw.google_maps_ferreterias (aprobado_argos);
    CREATE INDEX IF NOT EXISTS idx_gm_run_id       ON raw.google_maps_ferreterias (run_id);
    CREATE INDEX IF NOT EXISTS idx_gm_nombre       ON raw.google_maps_ferreterias (nombre);
    CREATE INDEX IF NOT EXISTS idx_gm_nit          ON raw.google_maps_ferreterias (nit);
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    print("[DB] Tabla raw.google_maps_ferreterias verificada.")


def cargar_urls_procesadas() -> set:
    """Carga URLs ya guardadas para usarlas como caché."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT url FROM raw.google_maps_ferreterias WHERE url IS NOT NULL;")
                return {row[0] for row in cur.fetchall()}
    except Exception as e:
        print(f"[DB] No se pudo cargar caché: {e}")
        return set()


def insertar_negocio(datos: dict) -> bool:
    """
    Inserta un registro. Si el hash_id ya existe lo ignora.
    Retorna True si insertó, False si era duplicado.
    """
    sql = """
    INSERT INTO raw.google_maps_ferreterias (
        hash_id, run_id, fecha_extraccion,
        nit, nombre, departamento, municipio, direccion,
        latitud, longitud, telefono, whatsapp, correo_electronico,
        fecha_actualizacion, fuente,
        sucursal_tipo, categorias_maps, descripcion,
        keyword_busqueda, url, score, aprobado_argos
    ) VALUES (
        %(hash_id)s, %(run_id)s, %(fecha_extraccion)s,
        %(nit)s, %(nombre)s, %(departamento)s, %(municipio)s, %(direccion)s,
        %(latitud)s, %(longitud)s, %(telefono)s, %(whatsapp)s, %(correo_electronico)s,
        %(fecha_actualizacion)s, %(fuente)s,
        %(sucursal_tipo)s, %(categorias_maps)s, %(descripcion)s,
        %(keyword_busqueda)s, %(url)s, %(score)s, %(aprobado_argos)s
    )
    ON CONFLICT (hash_id) DO NOTHING;
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, datos)
                inserted = cur.rowcount
            conn.commit()
        return inserted == 1
    except Exception as e:
        print(f"[DB] Error insertando {datos.get('nombre','?')}: {e}")
        return False