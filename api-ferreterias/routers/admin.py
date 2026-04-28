"""
routers/admin.py - Endpoints de administracion y verificacion de BD
"""
from fastapi import APIRouter
from sqlalchemy import text
from db.connection import engine

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/tablas", summary="Verificar que todas las tablas existen en la BD")
def verificar_tablas():
    """
    Muestra todas las tablas creadas en la BD agrupadas por esquema.
    Util para confirmar que la inicializacion automatica funciono.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema IN ('raw','staging','ref','clean')
            ORDER BY table_schema, table_name
        """)).fetchall()

    resultado = {}
    for schema, tabla in rows:
        resultado.setdefault(schema, []).append(tabla)

    total = sum(len(v) for v in resultado.values())
    esperadas = {
        "raw":     ["google_maps_ferreterias","paginas_amarillas_ferreterias",
                    "foursquare_ferreterias","overpass_ferreterias",
                    "rues_busqueda","rues_detalle",
                    "serper_consultas_construccion","serper_resultados_construccion"],
        "staging": ["empresas_unificadas","posibles_matches","ia_validaciones",
                    "campos_dudosos","entidad_resuelta","ejecuciones"],
        "ref":     ["municipios_colombia"],
        "clean":   ["empresas","empresa_telefonos","empresa_emails",
                    "empresa_direcciones","empresa_fuentes"],
    }

    faltantes = {}
    for schema, tablas in esperadas.items():
        existentes = resultado.get(schema, [])
        f = [t for t in tablas if t not in existentes]
        if f:
            faltantes[schema] = f

    return {
        "status":    "ok" if not faltantes else "incompleto",
        "total_tablas_creadas": total,
        "tablas_por_esquema": resultado,
        "faltantes": faltantes if faltantes else "ninguna — todo OK",
    }


@router.post("/crear-tablas", summary="Forzar la creacion de tablas (si algo fallo al iniciar)")
def forzar_creacion():
    """
    Vuelve a ejecutar el SQL de inicializacion.
    Usa CREATE TABLE IF NOT EXISTS, asi que es seguro correrlo multiples veces.
    """
    from db.init_db import init_database
    ok = init_database(engine)
    return {
        "status":  "ok" if ok else "error",
        "mensaje": "Tablas creadas/verificadas correctamente" if ok else "Hubo un error, revisa los logs",
    }


@router.get("/conteos", summary="Conteo de registros en cada tabla")
def conteos():
    """Cuantos registros hay en cada tabla principal."""
    tablas = [
        ("raw.google_maps_ferreterias",            "raw_google"),
        ("raw.paginas_amarillas_ferreterias",      "raw_pa"),
        ("raw.foursquare_ferreterias",             "raw_foursquare"),
        ("raw.overpass_ferreterias",               "raw_osm"),
        ("raw.rues_detalle",                       "raw_rues"),
        ("raw.serper_resultados_construccion",     "raw_serper"),
        ("staging.empresas_unificadas",            "staging"),
        ("staging.posibles_matches",               "matches"),
        ("staging.ejecuciones",                    "ejecuciones"),
        ("clean.empresas",                         "clean_empresas"),
        ("clean.empresa_telefonos",                "clean_telefonos"),
        ("clean.empresa_emails",                   "clean_emails"),
    ]

    resultado = {}
    with engine.connect() as conn:
        for tabla, alias in tablas:
            try:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar()
                resultado[alias] = n
            except Exception:
                resultado[alias] = "tabla no existe o error"

    return resultado
