"""
db/setup.py - Auto-creacion de esquemas, extensiones y tablas al iniciar la API.
Se ejecuta una sola vez en el lifespan de FastAPI.
No falla si las tablas ya existen (IF NOT EXISTS en todo).
"""

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ─── DDL completo en orden de dependencias ────────────────────────────────────

DDL_STEPS = [

    # 1. Extensiones PostgreSQL
    ("extensiones", """
        CREATE EXTENSION IF NOT EXISTS unaccent;
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
        CREATE EXTENSION IF NOT EXISTS pgcrypto;
    """),

    # 2. Esquemas
    ("esquemas", """
        CREATE SCHEMA IF NOT EXISTS staging;
        CREATE SCHEMA IF NOT EXISTS ref;
        CREATE SCHEMA IF NOT EXISTS clean;
    """),

    # 3. staging.empresas_unificadas
    ("staging.empresas_unificadas", """
        CREATE TABLE IF NOT EXISTS staging.empresas_unificadas (
            staging_id              BIGSERIAL PRIMARY KEY,
            fuente                  TEXT NOT NULL,
            raw_table               TEXT NOT NULL,
            raw_id                  INTEGER NOT NULL,
            run_id                  UUID,
            fecha_extraccion        TIMESTAMP,
            raw_hash_id             TEXT,
            nit                     TEXT,
            dv                      TEXT,
            id_rm                   TEXT,
            matricula               TEXT,
            nombre_original         TEXT,
            razon_social_original   TEXT,
            nombre_normalizado      TEXT,
            departamento_original   TEXT,
            municipio_original      TEXT,
            departamento_norm       TEXT,
            municipio_norm          TEXT,
            codigo_dane_municipio   TEXT,
            direccion_original      TEXT,
            direccion_normalizada   TEXT,
            latitud                 DOUBLE PRECISION,
            longitud                DOUBLE PRECISION,
            telefono_original       TEXT,
            telefono_normalizado    TEXT,
            whatsapp_original       TEXT,
            whatsapp_normalizado    TEXT,
            correo_original         TEXT,
            correo_normalizado      TEXT,
            sitio_web               TEXT,
            categoria_original      TEXT,
            ciiu_codigo             TEXT,
            ciiu_descripcion        TEXT,
            descripcion             TEXT,
            keyword_busqueda        TEXT,
            score_origen            INTEGER,
            aprobado_origen         BOOLEAN,
            match_key_nit           TEXT,
            match_key_email         TEXT,
            match_key_telefono      TEXT,
            match_key_nombre_municipio TEXT,
            created_at              TIMESTAMP DEFAULT NOW(),
            updated_at              TIMESTAMP DEFAULT NOW()
        );
    """),

    # 4. Indices staging.empresas_unificadas
    ("indices.staging.empresas_unificadas", """
        CREATE INDEX IF NOT EXISTS idx_staging_nit
            ON staging.empresas_unificadas(nit);
        CREATE INDEX IF NOT EXISTS idx_staging_email
            ON staging.empresas_unificadas(correo_normalizado);
        CREATE INDEX IF NOT EXISTS idx_staging_telefono
            ON staging.empresas_unificadas(telefono_normalizado);
        CREATE INDEX IF NOT EXISTS idx_staging_fuente
            ON staging.empresas_unificadas(fuente);
        CREATE INDEX IF NOT EXISTS idx_staging_municipio
            ON staging.empresas_unificadas(municipio_norm);
        CREATE INDEX IF NOT EXISTS idx_staging_nombre_trgm
            ON staging.empresas_unificadas
            USING gin(nombre_normalizado gin_trgm_ops);
    """),

    # 5. staging.posibles_matches
    ("staging.posibles_matches", """
        CREATE TABLE IF NOT EXISTS staging.posibles_matches (
            match_id            BIGSERIAL PRIMARY KEY,
            staging_id_a        BIGINT NOT NULL
                REFERENCES staging.empresas_unificadas(staging_id),
            staging_id_b        BIGINT NOT NULL
                REFERENCES staging.empresas_unificadas(staging_id),
            regla_match         TEXT NOT NULL,
            score_match         INTEGER NOT NULL DEFAULT 0,
            decision            TEXT DEFAULT 'pendiente',
            razon_decision      TEXT,
            creado_por_ia       BOOLEAN DEFAULT FALSE,
            confianza_ia        NUMERIC DEFAULT 0,
            created_at          TIMESTAMP DEFAULT NOW(),
            updated_at          TIMESTAMP DEFAULT NOW(),
            UNIQUE(staging_id_a, staging_id_b)
        );
        CREATE INDEX IF NOT EXISTS idx_matches_decision
            ON staging.posibles_matches(decision);
        CREATE INDEX IF NOT EXISTS idx_matches_score
            ON staging.posibles_matches(score_match);
        CREATE INDEX IF NOT EXISTS idx_matches_sid_a
            ON staging.posibles_matches(staging_id_a);
        CREATE INDEX IF NOT EXISTS idx_matches_sid_b
            ON staging.posibles_matches(staging_id_b);
    """),

    # 6. staging.ia_validaciones
    ("staging.ia_validaciones", """
        CREATE TABLE IF NOT EXISTS staging.ia_validaciones (
            id                  BIGSERIAL PRIMARY KEY,
            tipo_validacion     TEXT NOT NULL,
            staging_id_a        BIGINT,
            staging_id_b        BIGINT,
            input_json          JSONB NOT NULL,
            output_json         JSONB,
            decision            TEXT,
            confianza           NUMERIC,
            modelo              TEXT DEFAULT 'openrouter',
            tokens_usados       INTEGER,
            costo_estimado      NUMERIC,
            created_at          TIMESTAMP DEFAULT NOW()
        );
    """),

    # 7. staging.campos_dudosos
    ("staging.campos_dudosos", """
        CREATE TABLE IF NOT EXISTS staging.campos_dudosos (
            id                      BIGSERIAL PRIMARY KEY,
            staging_id              BIGINT
                REFERENCES staging.empresas_unificadas(staging_id),
            empresa_id              UUID,
            campo                   TEXT NOT NULL,
            valor_conflictivo       TEXT,
            valores_alternativos    TEXT[],
            fuentes_conflictivas    TEXT[],
            tipo_conflicto          TEXT,
            severidad               TEXT DEFAULT 'media',
            fue_revisado_ia         BOOLEAN DEFAULT FALSE,
            resolucion_ia           TEXT,
            valor_final_elegido     TEXT,
            created_at              TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_campos_dudosos_staging
            ON staging.campos_dudosos(staging_id);
        CREATE INDEX IF NOT EXISTS idx_campos_dudosos_campo
            ON staging.campos_dudosos(campo);
    """),

    # 8. staging.entidad_resuelta
    ("staging.entidad_resuelta", """
        CREATE TABLE IF NOT EXISTS staging.entidad_resuelta (
            id                      BIGSERIAL PRIMARY KEY,
            empresa_id              UUID NOT NULL,
            staging_id              BIGINT NOT NULL
                REFERENCES staging.empresas_unificadas(staging_id),
            fuente                  TEXT NOT NULL,
            score_match             INTEGER,
            regla_principal         TEXT,
            creado_en               TIMESTAMP DEFAULT NOW(),
            UNIQUE(empresa_id, staging_id)
        );
        CREATE INDEX IF NOT EXISTS idx_entidad_staging
            ON staging.entidad_resuelta(staging_id);
        CREATE INDEX IF NOT EXISTS idx_entidad_empresa
            ON staging.entidad_resuelta(empresa_id);
    """),

    # 9. staging.ejecuciones (control de pipeline)
    ("staging.ejecuciones", """
        CREATE TABLE IF NOT EXISTS staging.ejecuciones (
            id                      BIGSERIAL PRIMARY KEY,
            execution_id            TEXT UNIQUE NOT NULL,
            estado                  TEXT DEFAULT 'iniciado',
            fase_actual             TEXT,
            progreso_pct            INTEGER DEFAULT 0,
            config_json             JSONB,
            reporte_json            JSONB,
            error_mensaje           TEXT,
            registros_staging       INTEGER DEFAULT 0,
            matches_detectados      INTEGER DEFAULT 0,
            empresas_consolidadas   INTEGER DEFAULT 0,
            webhook_url             TEXT,
            webhook_enviado         BOOLEAN DEFAULT FALSE,
            webhook_respuesta       TEXT,
            timestamp_inicio        TIMESTAMP DEFAULT NOW(),
            timestamp_fin           TIMESTAMP,
            duracion_segundos       INTEGER
        );
    """),

    # 10. ref.municipios_colombia
    ("ref.municipios_colombia", """
        CREATE TABLE IF NOT EXISTS ref.municipios_colombia (
            codigo_dane_departamento TEXT,
            departamento_oficial    TEXT,
            departamento_norm       TEXT,
            codigo_dane_municipio   TEXT UNIQUE,
            municipio_oficial       TEXT,
            municipio_norm          TEXT,
            PRIMARY KEY (codigo_dane_departamento, codigo_dane_municipio)
        );
    """),

    # 11. clean.empresas
    ("clean.empresas", """
        CREATE TABLE IF NOT EXISTS clean.empresas (
            empresa_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            nit                     TEXT,
            dv                      TEXT,
            id_rm                   TEXT,
            matricula               TEXT,
            razon_social            TEXT,
            nombre_comercial        TEXT,
            nombre_normalizado      TEXT NOT NULL,
            departamento            TEXT,
            municipio               TEXT,
            codigo_dane_municipio   TEXT,
            direccion_principal     TEXT,
            direccion_normalizada   TEXT,
            latitud                 DOUBLE PRECISION,
            longitud                DOUBLE PRECISION,
            telefono_principal      TEXT,
            whatsapp_principal      TEXT,
            correo_principal        TEXT,
            sitio_web               TEXT,
            cod_ciiu_principal      TEXT,
            desc_ciiu_principal     TEXT,
            tipo_negocio            TEXT,
            estado_legal            TEXT,
            fecha_matricula         DATE,
            fecha_renovacion        DATE,
            ultimo_ano_renovado     TEXT,
            score_calidad           INTEGER,
            score_match             INTEGER,
            aprobado_argos          BOOLEAN DEFAULT FALSE,
            fuente_principal        TEXT,
            fuentes                 TEXT[] DEFAULT ARRAY[]::TEXT[],
            fecha_primera_extraccion TIMESTAMP,
            fecha_ultima_extraccion TIMESTAMP,
            cantidad_fuentes        INTEGER,
            cantidad_matches        INTEGER,
            created_at              TIMESTAMP DEFAULT NOW(),
            updated_at              TIMESTAMP DEFAULT NOW()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_clean_nit
            ON clean.empresas(nit) WHERE nit IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_clean_id_rm
            ON clean.empresas(id_rm) WHERE id_rm IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_clean_municipio
            ON clean.empresas(municipio);
        CREATE INDEX IF NOT EXISTS idx_clean_aprobado
            ON clean.empresas(aprobado_argos);
        CREATE INDEX IF NOT EXISTS idx_clean_score
            ON clean.empresas(score_calidad DESC);
    """),

    # 12. clean.empresa_telefonos
    ("clean.empresa_telefonos", """
        CREATE TABLE IF NOT EXISTS clean.empresa_telefonos (
            id          BIGSERIAL PRIMARY KEY,
            empresa_id  UUID NOT NULL
                REFERENCES clean.empresas(empresa_id) ON DELETE CASCADE,
            telefono    TEXT NOT NULL,
            tipo        TEXT,
            fuente      TEXT NOT NULL,
            es_principal BOOLEAN DEFAULT FALSE,
            confianza   INTEGER DEFAULT 50,
            creado_en   TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_tels_empresa
            ON clean.empresa_telefonos(empresa_id);
    """),

    # 13. clean.empresa_emails
    ("clean.empresa_emails", """
        CREATE TABLE IF NOT EXISTS clean.empresa_emails (
            id          BIGSERIAL PRIMARY KEY,
            empresa_id  UUID NOT NULL
                REFERENCES clean.empresas(empresa_id) ON DELETE CASCADE,
            email       TEXT NOT NULL,
            fuente      TEXT NOT NULL,
            es_principal BOOLEAN DEFAULT FALSE,
            confianza   INTEGER DEFAULT 50,
            creado_en   TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_emails_empresa
            ON clean.empresa_emails(empresa_id);
    """),

    # 14. clean.empresa_direcciones
    ("clean.empresa_direcciones", """
        CREATE TABLE IF NOT EXISTS clean.empresa_direcciones (
            id                  BIGSERIAL PRIMARY KEY,
            empresa_id          UUID NOT NULL
                REFERENCES clean.empresas(empresa_id) ON DELETE CASCADE,
            direccion_original  TEXT,
            direccion_normalizada TEXT,
            departamento        TEXT,
            municipio           TEXT,
            latitud             DOUBLE PRECISION,
            longitud            DOUBLE PRECISION,
            fuente              TEXT NOT NULL,
            es_principal        BOOLEAN DEFAULT FALSE,
            tipo_direccion      TEXT,
            confianza           INTEGER DEFAULT 50,
            creado_en           TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_dirs_empresa
            ON clean.empresa_direcciones(empresa_id);
    """),

    # 15. clean.empresa_fuentes
    ("clean.empresa_fuentes", """
        CREATE TABLE IF NOT EXISTS clean.empresa_fuentes (
            id              BIGSERIAL PRIMARY KEY,
            empresa_id      UUID NOT NULL
                REFERENCES clean.empresas(empresa_id) ON DELETE CASCADE,
            fuente          TEXT NOT NULL,
            raw_table       TEXT NOT NULL,
            raw_id          INTEGER NOT NULL,
            run_id          UUID,
            fecha_extraccion TIMESTAMP,
            score_origen    INTEGER,
            aprobado_origen BOOLEAN,
            regla_principal TEXT,
            score_match     INTEGER,
            creado_en       TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_fuentes_empresa
            ON clean.empresa_fuentes(empresa_id);
        CREATE INDEX IF NOT EXISTS idx_fuentes_raw
            ON clean.empresa_fuentes(raw_table, raw_id);
    """),

    # 16. Tablas raw (se crean si no existen, nunca se tocan)
    ("raw.esquema", """
        CREATE SCHEMA IF NOT EXISTS raw;
    """),

    ("raw.google_maps_ferreterias", """
        CREATE TABLE IF NOT EXISTS raw.google_maps_ferreterias (
            id                    SERIAL PRIMARY KEY,
            hash_id               TEXT UNIQUE,
            run_id                UUID NOT NULL,
            fecha_extraccion      TIMESTAMP NOT NULL DEFAULT NOW(),
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
            sucursal_tipo         TEXT DEFAULT 'Principal',
            categorias_maps       TEXT[],
            descripcion           TEXT,
            keyword_busqueda      TEXT,
            url                   TEXT,
            score                 INTEGER,
            aprobado_argos        BOOLEAN
        );
    """),

    ("raw.paginas_amarillas_ferreterias", """
        CREATE TABLE IF NOT EXISTS raw.paginas_amarillas_ferreterias (
            id                    SERIAL PRIMARY KEY,
            hash_id               TEXT UNIQUE,
            run_id                UUID NOT NULL,
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
            fuente                TEXT DEFAULT 'paginas_amarillas',
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
    """),

    ("raw.foursquare_ferreterias", """
        CREATE TABLE IF NOT EXISTS raw.foursquare_ferreterias (
            id                    SERIAL PRIMARY KEY,
            hash_id               TEXT UNIQUE,
            run_id                UUID NOT NULL,
            fecha_extraccion      TIMESTAMP NOT NULL DEFAULT NOW(),
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
            keyword_busqueda      TEXT,
            score                 INTEGER,
            aprobado_argos        BOOLEAN,
            fsq_place_id          TEXT,
            fsq_link              TEXT,
            fsq_categories        TEXT,
            fsq_category_ids      TEXT,
            fsq_distance          INTEGER,
            fsq_website           TEXT,
            fsq_description       TEXT,
            fsq_rating            DOUBLE PRECISION,
            fsq_hours             TEXT,
            fsq_verified          BOOLEAN,
            fsq_postal_code       TEXT,
            fsq_locality          TEXT,
            fsq_region            TEXT,
            fsq_country           TEXT DEFAULT 'CO',
            raw_place             JSONB
        );
    """),

    ("raw.overpass_ferreterias", """
        CREATE TABLE IF NOT EXISTS raw.overpass_ferreterias (
            id               SERIAL PRIMARY KEY,
            hash_id          TEXT UNIQUE,
            run_id           UUID NOT NULL,
            fecha_extraccion TIMESTAMP NOT NULL DEFAULT NOW(),
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
            score            INTEGER,
            aprobado_argos   BOOLEAN,
            osm_type         TEXT,
            osm_id           BIGINT,
            website          TEXT,
            email_osm        TEXT,
            addr_street      TEXT,
            addr_city        TEXT,
            addr_state       TEXT,
            description_osm  TEXT,
            raw_response     JSONB
        );
    """),

    ("raw.rues_busqueda", """
        CREATE TABLE IF NOT EXISTS raw.rues_busqueda (
            id                    SERIAL PRIMARY KEY,
            run_id                UUID NOT NULL,
            fecha_extraccion      TIMESTAMP NOT NULL DEFAULT NOW(),
            keyword_busqueda      TEXT,
            id_rm                 TEXT,
            tipo_documento        TEXT,
            nit                   TEXT,
            dv                    TEXT,
            razon_social          TEXT,
            sigla                 TEXT,
            cod_camara            TEXT,
            nom_camara            TEXT,
            matricula             TEXT,
            organizacion_juridica TEXT,
            estado_matricula      TEXT,
            ultimo_ano_renovado   TEXT,
            categoria             TEXT,
            raw_response          JSONB,
            UNIQUE(id_rm, keyword_busqueda)
        );
    """),

    ("raw.rues_detalle", """
        CREATE TABLE IF NOT EXISTS raw.rues_detalle (
            id                              SERIAL PRIMARY KEY,
            run_id                          UUID NOT NULL,
            fecha_extraccion                TIMESTAMP NOT NULL DEFAULT NOW(),
            id_rm                           TEXT UNIQUE,
            keyword_busqueda                TEXT,
            nit                             TEXT,
            nombre                          TEXT,
            departamento                    TEXT,
            municipio                       TEXT,
            direccion                       TEXT,
            latitud                         DOUBLE PRECISION,
            longitud                        DOUBLE PRECISION,
            telefono                        TEXT,
            whatsapp                        TEXT,
            correo_electronico              TEXT,
            fecha_actualizacion_argos       TIMESTAMP,
            fuente                          TEXT DEFAULT 'rues',
            score                           INTEGER,
            aprobado_argos                  BOOLEAN,
            cod_camara                      TEXT,
            camara                          TEXT,
            matricula                       TEXT,
            razon_social                    TEXT,
            sigla                           TEXT,
            dir_comercial                   TEXT,
            mun_comercial                   TEXT,
            tel_com_1                       TEXT,
            tel_com_2                       TEXT,
            tel_com_3                       TEXT,
            email_com                       TEXT,
            dir_fiscal                      TEXT,
            tel_fiscal_1                    TEXT,
            email_fiscal                    TEXT,
            cod_ciiu_pri                    TEXT,
            desc_ciiu_pri                   TEXT,
            cod_ciiu_sec                    TEXT,
            desc_ciiu_sec                   TEXT,
            fecha_matricula                 DATE,
            fecha_renovacion                DATE,
            ultimo_ano_renovado             TEXT,
            estado                          TEXT,
            organizacion_juridica           TEXT,
            raw_response                    JSONB
        );
    """),

    ("raw.serper_resultados_construccion", """
        CREATE TABLE IF NOT EXISTS raw.serper_resultados_construccion (
            id               SERIAL PRIMARY KEY,
            hash_id          TEXT UNIQUE,
            run_id           UUID NOT NULL,
            consulta_id      INTEGER,
            fecha_extraccion TIMESTAMP NOT NULL DEFAULT NOW(),
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
            fuente           TEXT DEFAULT 'serper',
            descripcion      TEXT,
            keyword_busqueda TEXT,
            url              TEXT,
            score            INTEGER,
            aprobado_argos   BOOLEAN,
            result_type      TEXT,
            title            TEXT,
            snippet          TEXT,
            link             TEXT,
            scraped_email    TEXT,
            scraped_phone    TEXT,
            scraped_whatsapp TEXT,
            is_enriched      BOOLEAN DEFAULT FALSE,
            raw_item         JSONB
        );
    """),
]


def crear_todas_las_tablas(engine) -> dict:
    """
    Crea todos los esquemas, extensiones y tablas si no existen.
    Se llama al arrancar la API. Es idempotente (IF NOT EXISTS en todo).
    Retorna dict con resultado de cada paso.
    """
    resultado = {}
    errores = []

    with engine.connect() as conn:
        for nombre, ddl in DDL_STEPS:
            try:
                # Ejecutar cada statement por separado para mejor manejo de errores
                for stmt in ddl.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(text(stmt))
                conn.commit()
                resultado[nombre] = "ok"
                logger.debug(f"  ✓ {nombre}")
            except Exception as e:
                conn.rollback()
                msg = str(e)[:120]
                resultado[nombre] = f"error: {msg}"
                errores.append(f"{nombre}: {msg}")
                logger.warning(f"  ⚠ {nombre}: {msg}")

    if errores:
        logger.warning(f"⚠ {len(errores)} errores al crear tablas (pueden ser normales si ya existen):")
        for e in errores[:5]:
            logger.warning(f"   {e}")
    else:
        logger.info(f"✅ {len(DDL_STEPS)} tablas/indices verificados correctamente")

    return resultado
