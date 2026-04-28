"""
routers/empresas.py - Endpoints para consultar clean.empresas
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.connection import get_db

router = APIRouter(prefix="/empresas", tags=["Empresas"])


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", summary="Listar empresas limpias con filtros")
def listar_empresas(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=5000),
    aprobado_argos: Optional[bool] = None,
    municipio: Optional[str] = None,
    departamento: Optional[str] = None,
    fuente: Optional[str] = None,
    score_min: Optional[int] = None,
    score_max: Optional[int] = None,
    con_nit: Optional[bool] = None,
    con_telefono: Optional[bool] = None,
    con_email: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """
    Lista empresas de clean.empresas con filtros opcionales.

    - **aprobado_argos**: true/false para filtrar por aprobación
    - **municipio**: filtro parcial por municipio (ILIKE)
    - **departamento**: filtro parcial por departamento
    - **score_min/score_max**: rango de score de calidad (0-140)
    - **con_nit**: true = solo con NIT, false = solo sin NIT
    """
    # Construir filtros dinámicos
    condiciones = ["1=1"]
    params = {"skip": skip, "limit": limit}

    if aprobado_argos is not None:
        condiciones.append("aprobado_argos = :aprobado")
        params["aprobado"] = aprobado_argos

    if municipio:
        condiciones.append("municipio ILIKE :municipio")
        params["municipio"] = f"%{municipio}%"

    if departamento:
        condiciones.append("departamento ILIKE :departamento")
        params["departamento"] = f"%{departamento}%"

    if fuente:
        condiciones.append(":fuente = ANY(fuentes)")
        params["fuente"] = fuente

    if score_min is not None:
        condiciones.append("score_calidad >= :score_min")
        params["score_min"] = score_min

    if score_max is not None:
        condiciones.append("score_calidad <= :score_max")
        params["score_max"] = score_max

    if con_nit is True:
        condiciones.append("nit IS NOT NULL")
    elif con_nit is False:
        condiciones.append("nit IS NULL")

    if con_telefono is True:
        condiciones.append("telefono_principal IS NOT NULL")
    elif con_telefono is False:
        condiciones.append("telefono_principal IS NULL")

    if con_email is True:
        condiciones.append("correo_principal IS NOT NULL")
    elif con_email is False:
        condiciones.append("correo_principal IS NULL")

    where = " AND ".join(condiciones)

    total = db.execute(
        text(f"SELECT COUNT(*) FROM clean.empresas WHERE {where}"), params
    ).scalar()

    rows = db.execute(text(f"""
        SELECT
            empresa_id::text, nit, nombre_comercial, razon_social, nombre_normalizado,
            departamento, municipio, codigo_dane_municipio,
            direccion_principal, latitud, longitud,
            telefono_principal, whatsapp_principal, correo_principal, sitio_web,
            cod_ciiu_principal, desc_ciiu_principal, tipo_negocio,
            estado_legal, ultimo_ano_renovado,
            score_calidad, aprobado_argos,
            fuente_principal, fuentes, cantidad_fuentes, cantidad_matches,
            fecha_primera_extraccion, fecha_ultima_extraccion,
            created_at
        FROM clean.empresas
        WHERE {where}
        ORDER BY score_calidad DESC NULLS LAST
        OFFSET :skip LIMIT :limit
    """), params).fetchall()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "empresas": [_row_a_empresa(r) for r in rows],
    }


@router.get("/stats", summary="Estadísticas generales de clean.empresas")
def estadisticas(db: Session = Depends(get_db)):
    """Retorna estadísticas del dataset limpio."""
    row = db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE aprobado_argos = true) AS aprobadas,
            COUNT(*) FILTER (WHERE nit IS NOT NULL) AS con_nit,
            COUNT(*) FILTER (WHERE telefono_principal IS NOT NULL) AS con_telefono,
            COUNT(*) FILTER (WHERE correo_principal IS NOT NULL) AS con_email,
            COUNT(*) FILTER (WHERE latitud IS NOT NULL) AS con_coordenadas,
            round(avg(score_calidad)::numeric, 1) AS score_promedio,
            COUNT(DISTINCT municipio) AS municipios_distintos,
            COUNT(DISTINCT departamento) AS departamentos_distintos
        FROM clean.empresas
    """)).fetchone()

    if not row or row[0] == 0:
        return {"mensaje": "Sin datos en clean.empresas. Ejecuta el pipeline primero."}

    fuentes_row = db.execute(text("""
        SELECT unnest(fuentes) AS fuente, COUNT(*) AS n
        FROM clean.empresas
        GROUP BY fuente
        ORDER BY n DESC
    """)).fetchall()

    return {
        "total_empresas": row[0],
        "aprobadas_argos": row[1],
        "tasa_aprobacion_pct": round((row[1] / row[0] * 100), 1) if row[0] > 0 else 0,
        "con_nit": row[2],
        "con_telefono": row[3],
        "con_email": row[4],
        "con_coordenadas": row[5],
        "score_calidad_promedio": float(row[6]) if row[6] else 0,
        "municipios_distintos": row[7],
        "departamentos_distintos": row[8],
        "distribucion_fuentes": [{"fuente": r[0], "empresas": r[1]} for r in fuentes_row],
    }


@router.get("/{empresa_id}", summary="Detalle completo de una empresa")
def obtener_empresa(empresa_id: UUID, db: Session = Depends(get_db)):
    """
    Retorna la empresa con:
    - Todos sus teléfonos
    - Todos sus emails
    - Todas sus direcciones
    - Todas las fuentes raw (auditoría)
    """
    row = db.execute(text("""
        SELECT
            empresa_id::text, nit, dv, id_rm, matricula,
            razon_social, nombre_comercial, nombre_normalizado,
            departamento, municipio, codigo_dane_municipio,
            direccion_principal, direccion_normalizada, latitud, longitud,
            telefono_principal, whatsapp_principal, correo_principal, sitio_web,
            cod_ciiu_principal, desc_ciiu_principal, tipo_negocio,
            estado_legal, fecha_matricula, fecha_renovacion, ultimo_ano_renovado,
            score_calidad, score_match, aprobado_argos,
            fuente_principal, fuentes, cantidad_fuentes, cantidad_matches,
            fecha_primera_extraccion, fecha_ultima_extraccion,
            created_at, updated_at
        FROM clean.empresas
        WHERE empresa_id = :eid
    """), {"eid": str(empresa_id)}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    empresa = {
        "empresa_id": row[0],
        "identificadores": {
            "nit": row[1], "dv": row[2], "id_rm": row[3], "matricula": row[4],
        },
        "nombres": {
            "razon_social": row[5],
            "nombre_comercial": row[6],
            "nombre_normalizado": row[7],
        },
        "ubicacion": {
            "departamento": row[8], "municipio": row[9],
            "codigo_dane": row[10],
            "direccion_principal": row[11],
            "direccion_normalizada": row[12],
            "latitud": row[13], "longitud": row[14],
        },
        "contacto_principal": {
            "telefono": row[15], "whatsapp": row[16],
            "correo": row[17], "sitio_web": row[18],
        },
        "clasificacion": {
            "cod_ciiu": row[19], "desc_ciiu": row[20], "tipo_negocio": row[21],
        },
        "legal": {
            "estado": row[22],
            "fecha_matricula": str(row[23]) if row[23] else None,
            "fecha_renovacion": str(row[24]) if row[24] else None,
            "ultimo_ano_renovado": row[25],
        },
        "calidad": {
            "score_calidad": row[26],
            "score_match": row[27],
            "aprobado_argos": row[28],
        },
        "trazabilidad": {
            "fuente_principal": row[29],
            "fuentes": row[30],
            "cantidad_fuentes": row[31],
            "cantidad_matches": row[32],
            "fecha_primera_extraccion": row[33].isoformat() if row[33] else None,
            "fecha_ultima_extraccion": row[34].isoformat() if row[34] else None,
        },
        "metadata": {
            "created_at": row[35].isoformat() if row[35] else None,
            "updated_at": row[36].isoformat() if row[36] else None,
        },
    }

    # Teléfonos
    tels = db.execute(text("""
        SELECT id, telefono, tipo, fuente, es_principal, confianza
        FROM clean.empresa_telefonos
        WHERE empresa_id = :eid ORDER BY es_principal DESC, confianza DESC
    """), {"eid": str(empresa_id)}).fetchall()

    empresa["telefonos"] = [
        {"id": r[0], "telefono": r[1], "tipo": r[2],
         "fuente": r[3], "es_principal": r[4], "confianza": r[5]}
        for r in tels
    ]

    # Emails
    emails = db.execute(text("""
        SELECT id, email, fuente, es_principal, confianza
        FROM clean.empresa_emails
        WHERE empresa_id = :eid ORDER BY es_principal DESC, confianza DESC
    """), {"eid": str(empresa_id)}).fetchall()

    empresa["emails"] = [
        {"id": r[0], "email": r[1], "fuente": r[2],
         "es_principal": r[3], "confianza": r[4]}
        for r in emails
    ]

    # Direcciones
    dirs = db.execute(text("""
        SELECT id, direccion_original, direccion_normalizada,
               departamento, municipio, latitud, longitud,
               fuente, es_principal, confianza
        FROM clean.empresa_direcciones
        WHERE empresa_id = :eid ORDER BY es_principal DESC, confianza DESC
    """), {"eid": str(empresa_id)}).fetchall()

    empresa["direcciones"] = [
        {"id": r[0], "direccion_original": r[1], "direccion_normalizada": r[2],
         "departamento": r[3], "municipio": r[4],
         "latitud": r[5], "longitud": r[6],
         "fuente": r[7], "es_principal": r[8], "confianza": r[9]}
        for r in dirs
    ]

    # Fuentes (auditoría)
    fuentes = db.execute(text("""
        SELECT id, fuente, raw_table, raw_id, run_id::text,
               fecha_extraccion, score_origen, aprobado_origen,
               regla_principal, score_match
        FROM clean.empresa_fuentes
        WHERE empresa_id = :eid ORDER BY fuente
    """), {"eid": str(empresa_id)}).fetchall()

    empresa["fuentes_raw"] = [
        {"id": r[0], "fuente": r[1], "raw_table": r[2], "raw_id": r[3],
         "run_id": r[4],
         "fecha_extraccion": r[5].isoformat() if r[5] else None,
         "score_origen": r[6], "aprobado_origen": r[7],
         "regla_principal": r[8], "score_match": r[9]}
        for r in fuentes
    ]

    return empresa


@router.get("/{empresa_id}/historial", summary="Historial de fuentes de una empresa")
def historial_empresa(empresa_id: UUID, db: Session = Depends(get_db)):
    """Ver qué registros raw alimentan esta empresa."""
    rows = db.execute(text("""
        SELECT
            ef.fuente, ef.raw_table, ef.raw_id, ef.run_id::text,
            ef.fecha_extraccion, ef.score_origen, ef.aprobado_origen,
            ef.regla_principal, ef.score_match,
            eu.nombre_original, eu.municipio_original, eu.telefono_original
        FROM clean.empresa_fuentes ef
        JOIN staging.entidad_resuelta er ON er.empresa_id::uuid = :eid
        JOIN staging.empresas_unificadas eu ON eu.staging_id = er.staging_id
            AND eu.fuente = ef.fuente AND eu.raw_id = ef.raw_id
        WHERE ef.empresa_id = :eid
        ORDER BY ef.score_origen DESC NULLS LAST
    """), {"eid": str(empresa_id)}).fetchall()

    return {
        "empresa_id": str(empresa_id),
        "total_fuentes": len(rows),
        "historial": [
            {
                "fuente": r[0], "raw_table": r[1], "raw_id": r[2],
                "run_id": r[3],
                "fecha_extraccion": r[4].isoformat() if r[4] else None,
                "score_origen": r[5], "aprobado_origen": r[6],
                "regla_principal": r[7], "score_match": r[8],
                "nombre_original": r[9],
                "municipio_original": r[10],
                "telefono_original": r[11],
            }
            for r in rows
        ],
    }


# ─── Helper ──────────────────────────────────────────────────────────────────

def _row_a_empresa(r) -> dict:
    return {
        "empresa_id": r[0],
        "nit": r[1],
        "nombre_comercial": r[2],
        "razon_social": r[3],
        "nombre_normalizado": r[4],
        "departamento": r[5],
        "municipio": r[6],
        "codigo_dane_municipio": r[7],
        "direccion": r[8],
        "latitud": r[9],
        "longitud": r[10],
        "telefono": r[11],
        "whatsapp": r[12],
        "correo": r[13],
        "sitio_web": r[14],
        "cod_ciiu": r[15],
        "desc_ciiu": r[16],
        "tipo_negocio": r[17],
        "estado_legal": r[18],
        "ultimo_ano_renovado": r[19],
        "score_calidad": r[20],
        "aprobado_argos": r[21],
        "fuente_principal": r[22],
        "fuentes": r[23],
        "cantidad_fuentes": r[24],
        "cantidad_matches": r[25],
        "fecha_primera_extraccion": r[26].isoformat() if r[26] else None,
        "fecha_ultima_extraccion": r[27].isoformat() if r[27] else None,
        "created_at": r[28].isoformat() if r[28] else None,
    }
