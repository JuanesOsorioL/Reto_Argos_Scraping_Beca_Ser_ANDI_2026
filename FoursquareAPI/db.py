"""
db.py — PostgreSQL para Foursquare Places API
Tabla: raw.foursquare_ferreterias

Funciones:
  - init_db()                     → crear esquema y tablas
  - cargar_fsq_ids_procesados()  → caché de IDs ya insertados
  - insertar_lugar()              → insertar o skip si duplicado
  - cargar_progreso()             → cargar estado de pausa
  - guardar_progreso()            → guardar estado de pausa
  - obtener_estadisticas()        → contar registros
"""
import psycopg2
from psycopg2.extras import Json
from config import DB_CONFIG
import json
from datetime import datetime


def get_connection():
    """Crea y retorna conexión a PostgreSQL."""
    return psycopg2.connect(**DB_CONFIG)


def init_db():
    """
    Inicializa esquema y tabla raw.foursquare_ferreterias.
    Se ejecuta al inicio de cada scraping.
    """
    ddl = """
    CREATE SCHEMA IF NOT EXISTS raw;

    CREATE TABLE IF NOT EXISTS raw.foursquare_ferreterias (
        -- ── Identidad y trazabilidad ─────────────────────────────────────
        id                    SERIAL PRIMARY KEY,
        hash_id               TEXT UNIQUE,
        run_id                UUID        NOT NULL,
        fecha_extraccion      TIMESTAMP   NOT NULL DEFAULT NOW(),

        -- ── Columnas requeridas por Argos ────────────────────────────────
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
        fuente                TEXT DEFAULT 'foursquare',

        -- ── Columnas adicionales de calidad ──────────────────────────────
        keyword_busqueda      TEXT,
        score                 INTEGER,
        aprobado_argos        BOOLEAN,

        -- ── Columnas exclusivas de Foursquare ────────────────────────────
        fsq_place_id          TEXT,
        fsq_link              TEXT,
        fsq_categories        TEXT,
        fsq_category_ids      TEXT,
        fsq_distance          INTEGER,
        fsq_date_created      TEXT,
        fsq_date_refreshed    TEXT,
        fsq_website           TEXT,
        fsq_twitter           TEXT,
        fsq_instagram         TEXT,
        fsq_facebook          TEXT,
        fsq_description       TEXT,
        fsq_rating            DOUBLE PRECISION,
        fsq_price             INTEGER,
        fsq_hours             TEXT,
        fsq_verified          BOOLEAN,
        fsq_postal_code       TEXT,
        fsq_locality          TEXT,
        fsq_region            TEXT,
        fsq_country           TEXT DEFAULT 'CO',

        -- ── RAW JSON ─────────────────────────────────────────────────────
        raw_place             JSONB
    );

    -- Índices para búsquedas rápidas
    CREATE INDEX IF NOT EXISTS idx_fsq_municipio    ON raw.foursquare_ferreterias (municipio);
    CREATE INDEX IF NOT EXISTS idx_fsq_departamento ON raw.foursquare_ferreterias (departamento);
    CREATE INDEX IF NOT EXISTS idx_fsq_aprobado     ON raw.foursquare_ferreterias (aprobado_argos);
    CREATE INDEX IF NOT EXISTS idx_fsq_run_id       ON raw.foursquare_ferreterias (run_id);
    CREATE INDEX IF NOT EXISTS idx_fsq_fsq_id       ON raw.foursquare_ferreterias (fsq_place_id);
    CREATE INDEX IF NOT EXISTS idx_fsq_nombre       ON raw.foursquare_ferreterias (nombre);
    
    -- Tabla de progreso para pausas
    CREATE TABLE IF NOT EXISTS raw.foursquare_progress (
        id                SERIAL PRIMARY KEY,
        run_id            UUID        UNIQUE,
        estado            TEXT,  -- 'corriendo', 'pausado', 'completado', 'error'
        fecha_ultima_pausa TIMESTAMP,
        fecha_reanudacion  TIMESTAMP,
        combinacion_actual TEXT,  -- '{"keyword": "ferretería", "ciudad": "Bogotá"}'
        total_procesadas   INTEGER,
        total_insertadas   INTEGER,
        total_duplicadas   INTEGER,
        total_aprobadas    INTEGER,
        rate_limit_count   INTEGER DEFAULT 0,
        ultimo_error       TEXT,
        fecha_creacion     TIMESTAMP DEFAULT NOW(),
        fecha_actualizacion TIMESTAMP DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_progress_run_id ON raw.foursquare_progress (run_id);
    CREATE INDEX IF NOT EXISTS idx_progress_estado ON raw.foursquare_progress (estado);
    """

    migraciones = """
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_distance       INTEGER;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_date_created   TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_date_refreshed TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_website        TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_twitter        TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_instagram      TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_facebook       TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_description    TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_rating         DOUBLE PRECISION;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_price          INTEGER;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_hours          TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_verified       BOOLEAN;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_postal_code    TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_locality       TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_region         TEXT;
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS fsq_country        TEXT DEFAULT 'CO';
    ALTER TABLE raw.foursquare_ferreterias ADD COLUMN IF NOT EXISTS raw_place          JSONB;
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
                cur.execute(migraciones)
            conn.commit()
        print("[DB] ✅ Tabla raw.foursquare_ferreterias verificada.")
    except Exception as e:
        print(f"[DB] ❌ Error inicializando DB: {e}")


def cargar_fsq_ids_procesados() -> set:
    """
    Carga todos los fsq_place_ids ya guardados en BD.
    Evita insertar duplicados.
    
    Returns:
        set: IDs de Foursquare ya en la BD
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT fsq_place_id FROM raw.foursquare_ferreterias WHERE fsq_place_id IS NOT NULL;"
                )
                return {row[0] for row in cur.fetchall()}
    except Exception as e:
        print(f"[DB] ⚠️  No se pudo cargar caché: {e}")
        return set()


def insertar_lugar(datos: dict) -> bool:
    """
    Inserta un lugar en la BD.
    Si ya existe (hash_id duplicado), lo ignora.
    
    Args:
        datos: dict con todos los campos del registro
    
    Returns:
        True si se insertó, False si era duplicado
    """
    sql = """
    INSERT INTO raw.foursquare_ferreterias (
        hash_id, run_id, fecha_extraccion,
        nit, nombre, departamento, municipio, direccion,
        latitud, longitud, telefono, whatsapp, correo_electronico,
        fecha_actualizacion, fuente,
        keyword_busqueda, score, aprobado_argos,
        fsq_place_id, fsq_link, fsq_categories, fsq_category_ids,
        fsq_distance, fsq_date_created, fsq_date_refreshed,
        fsq_website, fsq_twitter, fsq_instagram, fsq_facebook,
        fsq_description, fsq_rating, fsq_price, fsq_hours, fsq_verified,
        fsq_postal_code, fsq_locality, fsq_region, fsq_country,
        raw_place
    ) VALUES (
        %(hash_id)s, %(run_id)s, %(fecha_extraccion)s,
        %(nit)s, %(nombre)s, %(departamento)s, %(municipio)s, %(direccion)s,
        %(latitud)s, %(longitud)s, %(telefono)s, %(whatsapp)s, %(correo_electronico)s,
        %(fecha_actualizacion)s, %(fuente)s,
        %(keyword_busqueda)s, %(score)s, %(aprobado_argos)s,
        %(fsq_place_id)s, %(fsq_link)s, %(fsq_categories)s, %(fsq_category_ids)s,
        %(fsq_distance)s, %(fsq_date_created)s, %(fsq_date_refreshed)s,
        %(fsq_website)s, %(fsq_twitter)s, %(fsq_instagram)s, %(fsq_facebook)s,
        %(fsq_description)s, %(fsq_rating)s, %(fsq_price)s, %(fsq_hours)s, %(fsq_verified)s,
        %(fsq_postal_code)s, %(fsq_locality)s, %(fsq_region)s, %(fsq_country)s,
        %(raw_place)s
    ) ON CONFLICT (hash_id) DO NOTHING;
    """
    
    try:
        payload = {**datos, "raw_place": Json(datos.get("raw_place"))}
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, payload)
                inserted = cur.rowcount
            conn.commit()
        return inserted == 1
    except Exception as e:
        print(f"[DB] ❌ Error insertando {datos.get('nombre','?')}: {e}")
        return False


def guardar_progreso(run_id: str, progreso: dict):
    """
    Guarda el estado actual del scraping en BD.
    Usado cuando se pausa por rate limit.
    
    Args:
        run_id: UUID de la corrida
        progreso: dict con {
            'estado': 'pausado|corriendo|completado',
            'combinacion_actual': {'keyword': '...', 'ciudad': '...'},
            'total_procesadas': int,
            'total_insertadas': int,
            'total_duplicadas': int,
            'total_aprobadas': int,
            'rate_limit_count': int,
            'ultimo_error': str
        }
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Si existe, actualizar; si no, insertar
                cur.execute("""
                    INSERT INTO raw.foursquare_progress (
                        run_id, estado, fecha_ultima_pausa,
                        combinacion_actual, total_procesadas, total_insertadas,
                        total_duplicadas, total_aprobadas, rate_limit_count,
                        ultimo_error
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (run_id) DO UPDATE SET
                        estado = EXCLUDED.estado,
                        fecha_ultima_pausa = EXCLUDED.fecha_ultima_pausa,
                        combinacion_actual = EXCLUDED.combinacion_actual,
                        total_procesadas = EXCLUDED.total_procesadas,
                        total_insertadas = EXCLUDED.total_insertadas,
                        total_duplicadas = EXCLUDED.total_duplicadas,
                        total_aprobadas = EXCLUDED.total_aprobadas,
                        rate_limit_count = EXCLUDED.rate_limit_count,
                        ultimo_error = EXCLUDED.ultimo_error,
                        fecha_actualizacion = NOW()
                """, (
                    run_id,
                    progreso.get('estado', 'corriendo'),
                    datetime.now(),
                    json.dumps(progreso.get('combinacion_actual', {})),
                    progreso.get('total_procesadas', 0),
                    progreso.get('total_insertadas', 0),
                    progreso.get('total_duplicadas', 0),
                    progreso.get('total_aprobadas', 0),
                    progreso.get('rate_limit_count', 0),
                    progreso.get('ultimo_error', ''),
                ))
            conn.commit()
        print(f"[DB] ✅ Progreso guardado para run_id: {run_id}")
    except Exception as e:
        print(f"[DB] ❌ Error guardando progreso: {e}")


def cargar_progreso(run_id: str) -> dict | None:
    """
    Carga el estado guardado de un scraping.
    
    Args:
        run_id: UUID de la corrida
    
    Returns:
        dict con el progreso, o None si no existe
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT estado, combinacion_actual, total_procesadas, total_insertadas, "
                    "total_duplicadas, total_aprobadas, rate_limit_count FROM raw.foursquare_progress "
                    "WHERE run_id = %s",
                    (run_id,)
                )
                row = cur.fetchone()
                if row:
                    return {
                        'estado': row[0],
                        'combinacion_actual': json.loads(row[1]) if row[1] else {},
                        'total_procesadas': row[2],
                        'total_insertadas': row[3],
                        'total_duplicadas': row[4],
                        'total_aprobadas': row[5],
                        'rate_limit_count': row[6],
                    }
        return None
    except Exception as e:
        print(f"[DB] ⚠️  Error cargando progreso: {e}")
        return None


def obtener_estadisticas() -> dict:
    """
    Retorna estadísticas globales de la BD.
    
    Returns:
        dict con conteos totales
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(CASE WHEN aprobado_argos = TRUE THEN 1 END) as aprobados,
                        COUNT(DISTINCT municipio) as municipios,
                        COUNT(CASE WHEN telefono != '' AND telefono IS NOT NULL THEN 1 END) as con_telefono,
                        COUNT(CASE WHEN fsq_website != '' AND fsq_website IS NOT NULL THEN 1 END) as con_website
                    FROM raw.foursquare_ferreterias
                """)
                row = cur.fetchone()
                return {
                    'total_registros': row[0],
                    'aprobados_argos': row[1],
                    'municipios_unicos': row[2],
                    'con_telefono': row[3],
                    'con_website': row[4],
                }
    except Exception as e:
        print(f"[DB] ⚠️  Error obteniendo estadísticas: {e}")
        return {}
