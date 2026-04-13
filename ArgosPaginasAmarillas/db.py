"""
db.py — PostgreSQL para scraper Páginas Amarillas
Tabla destino: raw.paginas_amarillas_ferreterias

Columnas requeridas por Argos:
  nit, nombre, departamento, municipio, direccion,
  latitud, longitud, telefono, whatsapp, correo_electronico,
  fecha_actualizacion, fuente

Columnas adicionales de trazabilidad y calidad:
  id, run_id, fecha_extraccion, sucursal_tipo,
  telefonos_adicionales, descripcion, categoria_busqueda,
  keyword_busqueda, url, score, aprobado_argos, hash_id
"""
import psycopg2
from config import DB_CONFIG


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def init_db():
    """Crea el esquema raw y la tabla si no existen."""
    ddl = """
    CREATE SCHEMA IF NOT EXISTS raw;

    CREATE TABLE IF NOT EXISTS raw.paginas_amarillas_ferreterias (

        -- ── Identidad ────────────────────────────────────────────────────
        id                    SERIAL PRIMARY KEY,
        hash_id               TEXT UNIQUE,          -- deduplicación
        run_id                UUID NOT NULL,         -- trazabilidad por corrida

        -- ── Columnas requeridas por Argos ────────────────────────────────
        nit                   TEXT,                  -- no disponible en PA, queda vacío para cruce posterior
        nombre                TEXT,
        departamento          TEXT,
        municipio             TEXT,                  -- equivale a ciudad
        direccion             TEXT,
        latitud               DOUBLE PRECISION,
        longitud              DOUBLE PRECISION,
        telefono              TEXT,
        whatsapp              TEXT,
        correo_electronico    TEXT,                  -- equivale a email
        fecha_actualizacion   TIMESTAMP,             -- cuándo se actualizó este registro
        fuente                TEXT DEFAULT 'paginas_amarillas',

        -- ── Columnas adicionales de calidad ──────────────────────────────
        sucursal_tipo         TEXT,
        telefonos_adicionales TEXT,
        descripcion           TEXT,
        categoria_busqueda    TEXT,
        keyword_busqueda      TEXT,
        url                   TEXT,
        score                 INTEGER,
        aprobado_argos        BOOLEAN,
        fecha_extraccion      TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_pa_municipio   ON raw.paginas_amarillas_ferreterias (municipio);
    CREATE INDEX IF NOT EXISTS idx_pa_departamento ON raw.paginas_amarillas_ferreterias (departamento);
    CREATE INDEX IF NOT EXISTS idx_pa_aprobado    ON raw.paginas_amarillas_ferreterias (aprobado_argos);
    CREATE INDEX IF NOT EXISTS idx_pa_run_id      ON raw.paginas_amarillas_ferreterias (run_id);
    CREATE INDEX IF NOT EXISTS idx_pa_nombre      ON raw.paginas_amarillas_ferreterias (nombre);
    CREATE INDEX IF NOT EXISTS idx_pa_nit         ON raw.paginas_amarillas_ferreterias (nit);
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    print("[DB] Tabla raw.paginas_amarillas_ferreterias verificada.")


def cargar_urls_procesadas() -> set:
    """Carga URLs ya guardadas para usarlas como caché."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT url FROM raw.paginas_amarillas_ferreterias WHERE url IS NOT NULL;")
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
    INSERT INTO raw.paginas_amarillas_ferreterias (
        hash_id, run_id,
        nit, nombre, departamento, municipio, direccion,
        latitud, longitud,
        telefono, telefonos_adicionales, whatsapp, correo_electronico,
        fecha_actualizacion, fuente,
        sucursal_tipo, descripcion, categoria_busqueda, keyword_busqueda,
        url, score, aprobado_argos, fecha_extraccion
    ) VALUES (
        %(hash_id)s, %(run_id)s,
        %(nit)s, %(nombre)s, %(departamento)s, %(municipio)s, %(direccion)s,
        %(latitud)s, %(longitud)s,
        %(telefono)s, %(telefonos_adicionales)s, %(whatsapp)s, %(correo_electronico)s,
        %(fecha_actualizacion)s, %(fuente)s,
        %(sucursal_tipo)s, %(descripcion)s, %(categoria_busqueda)s, %(keyword_busqueda)s,
        %(url)s, %(score)s, %(aprobado_argos)s, %(fecha_extraccion)s
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