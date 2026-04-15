"""
═══════════════════════════════════════════════════════════════════════════════
db.py — PostgreSQL: Crear tablas, insertar consultas y resultados
═══════════════════════════════════════════════════════════════════════════════

Responsabilidades:
  ✓ Crear/verificar esquema "raw" y tablas de Serper
  ✓ Insertar consultas (queries hechas a Serper)
  ✓ Insertar resultados (registros encontrados)
  ✓ Verificar si una query ya fue procesada (para reanudación)
  ✓ Manejo de duplicados (ON CONFLICT DO NOTHING)
"""

import psycopg2
from psycopg2.extras import Json
from config import DB_CONFIG


# ═══════════════════════════════════════════════════════════════════════════════
# CONEXIÓN A POSTGRESQL
# ═══════════════════════════════════════════════════════════════════════════════

def get_connection():
    """
    Abre una conexión a PostgreSQL.
    
    Usa las credenciales de DB_CONFIG (del .env).
    
    Returns:
        psycopg2.connection: Conexión a la BD
    
    Nota: Siempre usar con context manager (with):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
            conn.commit()
    """
    return psycopg2.connect(**DB_CONFIG)


# ═══════════════════════════════════════════════════════════════════════════════
# INICIALIZACIÓN: CREAR TABLAS
# ═══════════════════════════════════════════════════════════════════════════════

def init_db():
    """
    Verifica y crea las tablas si no existen.
    
    Crea:
      1. Esquema "raw" (si no existe)
      2. Tabla serper_consultas_construccion (queries hechas a Serper)
      3. Tabla serper_resultados_construccion (resultados encontrados)
      4. Índices para búsquedas rápidas
    
    Safe: Usa CREATE IF NOT EXISTS, nunca elimina datos.
    
    Llamar una sola vez al inicio, es idempotente.
    
    Ejemplo:
        >>> from db import init_db
        >>> init_db()
        >>> # Tablas creadas o verificadas ✓
    """
    
    ddl = """
    -- ─────────────────────────────────────────────────────────────────────────
    -- CREAR ESQUEMA "raw"
    -- Organizamos los datos de scraping en un esquema separado
    -- ─────────────────────────────────────────────────────────────────────────
    CREATE SCHEMA IF NOT EXISTS raw;

    -- ─────────────────────────────────────────────────────────────────────────
    -- TABLA: serper_consultas_construccion
    -- Registra cada query enviada a Serper (para auditoría y reanudación)
    -- ─────────────────────────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS raw.serper_consultas_construccion (
        -- Identificadores
        id               SERIAL PRIMARY KEY,             -- Auto-incremento
        run_id           UUID        NOT NULL,           -- UUID de la ejecución
        
        -- Información de la query
        query            TEXT        NOT NULL,           -- Texto exacto enviado a Serper
        keyword_busqueda TEXT,                          -- Palabra clave original
        ciudad           TEXT,                          -- Ciudad buscar
        departamento     TEXT,                          -- Departamento
        page             INTEGER,                       -- Página de resultados (1, 2, 3...)
        tipo_consulta    TEXT        DEFAULT 'search',  -- Tipo: 'search' por ahora
        
        -- Timestamps
        fecha_extraccion TIMESTAMP   NOT NULL DEFAULT NOW(),  -- Cuándo se ejecutó
        
        -- Respuesta JSON
        raw_response     JSONB                          -- Respuesta completa de Serper
    );

    -- ─────────────────────────────────────────────────────────────────────────
    -- TABLA: serper_resultados_construccion
    -- Cada negocio/resultado encontrado (filas principales)
    -- ─────────────────────────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS raw.serper_resultados_construccion (
        -- Identificadores
        id               SERIAL PRIMARY KEY,            -- Auto-incremento
        hash_id          TEXT UNIQUE,                   -- Hash para deduplicación
        run_id           UUID        NOT NULL,          -- UUID de ejecución
        consulta_id      INTEGER REFERENCES raw.serper_consultas_construccion(id),
        
        -- Timestamps
        fecha_extraccion TIMESTAMP   NOT NULL DEFAULT NOW(),

        -- ════════════════════════════════════════════════════════════════════
        -- COLUMNAS ARGOS ESTÁNDAR (compatible con otros proyectos)
        -- ════════════════════════════════════════════════════════════════════
        nit                   TEXT,                    -- Número identificación
        nombre                TEXT,                    -- Nombre del negocio
        departamento          TEXT,                    -- Departamento
        municipio             TEXT,                    -- Ciudad
        direccion             TEXT,                    -- Dirección física
        latitud               DOUBLE PRECISION,        -- Geo: latitud
        longitud              DOUBLE PRECISION,        -- Geo: longitud
        telefono              TEXT,                    -- Teléfono principal
        whatsapp              TEXT,                    -- Link WhatsApp
        correo_electronico    TEXT,                    -- Email
        fecha_actualizacion   TIMESTAMP,               -- Cuándo se actualizó
        fuente                TEXT DEFAULT 'serper',   -- Siempre 'serper'

        -- ════════════════════════════════════════════════════════════════════
        -- COLUMNAS DE CALIDAD
        -- ════════════════════════════════════════════════════════════════════
        telefonos_adicionales TEXT,                    -- Teléfonos extra (1|2|3)
        descripcion           TEXT,                    -- Descripción negocio
        categoria_busqueda    TEXT,                    -- organic/knowledge_graph
        keyword_busqueda      TEXT,                    -- Keyword original
        url                   TEXT,                    -- URL del sitio
        score                 INTEGER,                 -- Score Argos (0-10+)
        aprobado_argos        BOOLEAN,                 -- Pasó filtro Argos

        -- ════════════════════════════════════════════════════════════════════
        -- COLUMNAS METADATOS SERPER
        -- ════════════════════════════════════════════════════════════════════
        result_type           TEXT,                    -- organic/knowledgeGraph
        position              INTEGER,                 -- Posición en results
        title                 TEXT,                    -- Título del resultado
        snippet               TEXT,                    -- Resumen/snippet
        link                  TEXT,                    -- Link del resultado
        display_query         TEXT,                    -- Query mostrada
        ciudad_busqueda       TEXT,                    -- Ciudad (repeat)
        pais_busqueda         TEXT DEFAULT 'Colombia', -- País fijo

        -- ════════════════════════════════════════════════════════════════════
        -- COLUMNAS DE ENRIQUECIMIENTO (Visita a URL)
        -- ════════════════════════════════════════════════════════════════════
        scraped_email         TEXT,                    -- Email extraído
        scraped_phone         TEXT,                    -- Teléfono extraído
        scraped_whatsapp      TEXT,                    -- WhatsApp extraído
        meta_description      TEXT,                    -- Meta description
        is_enriched           BOOLEAN DEFAULT FALSE,   -- ¿Se enriqueció?
        contact_page_url      TEXT,                    -- URL página contacto

        -- ════════════════════════════════════════════════════════════════════
        -- COLUMNAS RAW JSON (Datos crudos para análisis futuro)
        -- ════════════════════════════════════════════════════════════════════
        raw_item              JSONB,                   -- Item crudo individual
        raw_search_parameters JSONB,                   -- Parámetros de búsqueda
        raw_knowledge_graph   JSONB,                   -- Knowledge Graph completo
        raw_people_also_ask   JSONB,                   -- Preguntas relacionadas
        raw_related_searches  JSONB                    -- Búsquedas relacionadas
    );

    -- ─────────────────────────────────────────────────────────────────────────
    -- ÍNDICES para búsquedas rápidas
    -- ─────────────────────────────────────────────────────────────────────────
    CREATE INDEX IF NOT EXISTS idx_sc_run_id       ON raw.serper_consultas_construccion (run_id);
    CREATE INDEX IF NOT EXISTS idx_sr_run_id       ON raw.serper_resultados_construccion (run_id);
    CREATE INDEX IF NOT EXISTS idx_sr_hash_id      ON raw.serper_resultados_construccion (hash_id);
    CREATE INDEX IF NOT EXISTS idx_sr_municipio    ON raw.serper_resultados_construccion (municipio);
    CREATE INDEX IF NOT EXISTS idx_sr_departamento ON raw.serper_resultados_construccion (departamento);
    CREATE INDEX IF NOT EXISTS idx_sr_keyword      ON raw.serper_resultados_construccion (keyword_busqueda);
    CREATE INDEX IF NOT EXISTS idx_sr_aprobado     ON raw.serper_resultados_construccion (aprobado_argos);
    CREATE INDEX IF NOT EXISTS idx_sr_result_type  ON raw.serper_resultados_construccion (result_type);
    """
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Ejecutar todo el DDL de una vez
            cur.execute(ddl)
        conn.commit()
    
    print("[DB] ✅ Tablas Serper verificadas o creadas.")


# ═══════════════════════════════════════════════════════════════════════════════
# VERIFICAR REANUDACIÓN: ¿Ya se procesó esta query?
# ═══════════════════════════════════════════════════════════════════════════════

def consulta_ya_procesada(query: str, page: int) -> bool:
    """
    Verifica si una query ya fue procesada.
    
    Usada para reanudación: si la app se cae y vuelve a encender,
    no queremos procesar de nuevo las queries que ya se hicieron.
    
    Args:
        query (str): Texto exacto de la query
        page (int): Página de resultados
    
    Returns:
        bool: True si ya existe en la BD, False si es nueva
    
    Ejemplo:
        >>> if not consulta_ya_procesada("ferreterías en Bogotá", 1):
        ...     response = call_serper(...)  # Llamar solo si es nueva
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    # Buscar si existe exactamente esta query y página
                    "SELECT 1 FROM raw.serper_consultas_construccion "
                    "WHERE query = %s AND page = %s LIMIT 1;",
                    (query, page)
                )
                return cur.fetchone() is not None
    except Exception as e:
        print(f"[DB] ⚠️  Error verificando consulta: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# INSERTAR CONSULTA (Query hecha a Serper)
# ═══════════════════════════════════════════════════════════════════════════════

def insertar_consulta(datos: dict) -> int:
    """
    Inserta una consulta (query) en la tabla de consultas.
    
    Se llama DESPUÉS de cada llamada exitosa a Serper,
    antes de procesar los resultados.
    
    Args:
        datos (dict): Diccionario con:
            {
                "run_id": "uuid-aqui",
                "query": "ferreterías en Bogotá, Colombia",
                "keyword_busqueda": "ferreterías",
                "ciudad": "Bogotá",
                "departamento": "Cundinamarca",
                "page": 1,
                "tipo_consulta": "search",
                "raw_response": {respuesta completa JSON}
            }
    
    Returns:
        int: ID de la consulta insertada (consulta_id)
             Usado luego para referenciar en la tabla de resultados
    
    Ejemplo:
        >>> consulta_id = insertar_consulta({
        ...     "run_id": "abc-123",
        ...     "query": "ferreterías en Bogotá, Colombia",
        ...     "raw_response": {...}
        ... })
        >>> print(consulta_id)  # 42
    """
    
    sql = """
    -- Insertar una nueva fila en la tabla de consultas
    INSERT INTO raw.serper_consultas_construccion (
        run_id,
        query,
        keyword_busqueda,
        ciudad,
        departamento,
        page,
        tipo_consulta,
        raw_response
    ) VALUES (
        %(run_id)s,
        %(query)s,
        %(keyword_busqueda)s,
        %(ciudad)s,
        %(departamento)s,
        %(page)s,
        %(tipo_consulta)s,
        %(raw_response)s
    ) RETURNING id;  -- Devolver el ID autoincrement
    """
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Pasar raw_response como JSON (psycopg2.extras.Json)
            cur.execute(sql, {**datos, "raw_response": Json(datos["raw_response"])})
            
            # Obtener el ID que se acaba de insertar
            consulta_id = cur.fetchone()[0]
        
        # Confirmar la transacción
        conn.commit()
    
    return consulta_id


# ═══════════════════════════════════════════════════════════════════════════════
# INSERTAR RESULTADO (Negocio/Resultado encontrado)
# ═══════════════════════════════════════════════════════════════════════════════

def insertar_resultado(datos: dict) -> bool:
    """
    Inserta un resultado (negocio encontrado) en la tabla de resultados.
    
    Si el hash_id ya existe (duplicado), la inserción se ignora (ON CONFLICT).
    
    Args:
        datos (dict): Diccionario con todos los campos del resultado
            {
                "hash_id": "sha256-hash-aqui",
                "run_id": "uuid-aqui",
                "consulta_id": 42,
                "nombre": "Ferretería El Constructor",
                "telefono": "3001234567",
                "email": "info@ferreteria.com",
                ... (muchos campos más)
            }
    
    Returns:
        bool: True si se insertó (nueva fila)
              False si se ignoró (duplicado)
    
    Ejemplo:
        >>> if insertar_resultado(datos):
        ...     print("Nuevo registro")
        ... else:
        ...     print("Duplicado, ignorado")
    """
    
    sql = """
    -- Insertar resultado, ignorar si el hash_id ya existe
    INSERT INTO raw.serper_resultados_construccion (
        hash_id, run_id, consulta_id, fecha_extraccion,
        nit, nombre, departamento, municipio, direccion,
        latitud, longitud, telefono, whatsapp, correo_electronico,
        fecha_actualizacion, fuente,
        telefonos_adicionales, descripcion, categoria_busqueda, keyword_busqueda,
        url, score, aprobado_argos,
        result_type, position, title, snippet, link, display_query,
        ciudad_busqueda, pais_busqueda,
        scraped_email, scraped_phone, scraped_whatsapp, meta_description,
        is_enriched, contact_page_url,
        raw_item, raw_search_parameters, raw_knowledge_graph,
        raw_people_also_ask, raw_related_searches
    ) VALUES (
        %(hash_id)s, %(run_id)s, %(consulta_id)s, %(fecha_extraccion)s,
        %(nit)s, %(nombre)s, %(departamento)s, %(municipio)s, %(direccion)s,
        %(latitud)s, %(longitud)s, %(telefono)s, %(whatsapp)s, %(correo_electronico)s,
        %(fecha_actualizacion)s, %(fuente)s,
        %(telefonos_adicionales)s, %(descripcion)s, %(categoria_busqueda)s, %(keyword_busqueda)s,
        %(url)s, %(score)s, %(aprobado_argos)s,
        %(result_type)s, %(position)s, %(title)s, %(snippet)s, %(link)s, %(display_query)s,
        %(ciudad_busqueda)s, %(pais_busqueda)s,
        %(scraped_email)s, %(scraped_phone)s, %(scraped_whatsapp)s, %(meta_description)s,
        %(is_enriched)s, %(contact_page_url)s,
        %(raw_item)s, %(raw_search_parameters)s, %(raw_knowledge_graph)s,
        %(raw_people_also_ask)s, %(raw_related_searches)s
    ) ON CONFLICT (hash_id) DO NOTHING;  -- Ignorar duplicados
    """
    
    try:
        # Preparar payload: convertir dicts a JSON
        payload = datos.copy()
        for key in ["raw_item", "raw_search_parameters", "raw_knowledge_graph",
                    "raw_people_also_ask", "raw_related_searches"]:
            payload[key] = Json(payload.get(key))
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, payload)
                
                # rowcount nos dice si se insertó (1) o se ignoró (0)
                inserted = cur.rowcount
            
            conn.commit()
        
        # Retornar True si se insertó, False si fue duplicado
        return inserted == 1
    
    except Exception as e:
        print(f"[DB] ⚠️  Error insertando {datos.get('nombre','?')}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# LIMPIAR TODO (Reset)
# ═══════════════════════════════════════════════════════════════════════════════

def reset_all():
    """
    ⚠️  PELIGROSO: Borra TODOS los datos de las tablas Serper.
    
    Se usa para empezar desde cero (endpoint POST /reset).
    
    ADVERTENCIA: Esta operación es IRREVERSIBLE.
    
    Returns:
        bool: True si tuvo éxito
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Eliminar todas las filas (manteniendo la estructura)
                cur.execute("DELETE FROM raw.serper_resultados_construccion;")
                cur.execute("DELETE FROM raw.serper_consultas_construccion;")
            conn.commit()
        print("[DB] ✅ Todas las tablas Serper limpiadas.")
        return True
    except Exception as e:
        print(f"[DB] ❌ Error durante reset: {e}")
        return False
