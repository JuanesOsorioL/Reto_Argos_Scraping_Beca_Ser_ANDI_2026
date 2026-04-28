"""
routers/staging.py - Endpoints para campos dudosos, posibles matches y validación manual
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.connection import get_db

router = APIRouter(tags=["Staging / Revisión"])


# ─── Campos Dudosos ──────────────────────────────────────────────────────────

@router.get("/campos-dudosos", summary="Listar campos con inconsistencias detectadas")
def listar_campos_dudosos(
    campo: Optional[str] = None,
    tipo_conflicto: Optional[str] = None,
    severidad: Optional[str] = None,
    revisado_ia: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """
    Lista campos con problemas detectados durante el pipeline.

    - **campo**: nombre, telefono, email, municipio, direccion
    - **tipo_conflicto**: inconsistencia_multifuente, formato_invalido, faltan_datos
    - **severidad**: baja, media, alta, critica
    """
    conds = ["1=1"]
    params = {"skip": skip, "limit": limit}

    if campo:
        conds.append("campo = :campo")
        params["campo"] = campo
    if tipo_conflicto:
        conds.append("tipo_conflicto = :tipo")
        params["tipo"] = tipo_conflicto
    if severidad:
        conds.append("severidad = :severidad")
        params["severidad"] = severidad
    if revisado_ia is not None:
        conds.append("fue_revisado_ia = :rev")
        params["rev"] = revisado_ia

    where = " AND ".join(conds)

    total = db.execute(
        text(f"SELECT COUNT(*) FROM staging.campos_dudosos WHERE {where}"), params
    ).scalar()

    rows = db.execute(text(f"""
        SELECT id, staging_id, empresa_id::text, campo,
               valor_conflictivo, valores_alternativos,
               fuentes_conflictivas, tipo_conflicto, severidad,
               fue_revisado_ia, resolucion_ia, valor_final_elegido,
               created_at
        FROM staging.campos_dudosos
        WHERE {where}
        ORDER BY
            CASE severidad WHEN 'critica' THEN 1 WHEN 'alta' THEN 2
                           WHEN 'media' THEN 3 ELSE 4 END,
            campo
        OFFSET :skip LIMIT :limit
    """), params).fetchall()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "campos_dudosos": [
            {
                "id": r[0], "staging_id": r[1], "empresa_id": r[2],
                "campo": r[3], "valor_conflictivo": r[4],
                "valores_alternativos": r[5] or [],
                "fuentes_conflictivas": r[6] or [],
                "tipo_conflicto": r[7], "severidad": r[8],
                "fue_revisado_ia": r[9], "resolucion_ia": r[10],
                "valor_final_elegido": r[11],
                "created_at": r[12].isoformat() if r[12] else None,
            }
            for r in rows
        ],
    }


@router.get("/campos-dudosos/resumen", summary="Resumen estadístico de campos dudosos")
def resumen_campos_dudosos(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT
            campo,
            tipo_conflicto,
            severidad,
            COUNT(*) AS n
        FROM staging.campos_dudosos
        GROUP BY campo, tipo_conflicto, severidad
        ORDER BY n DESC
    """)).fetchall()

    por_campo = {}
    por_tipo = {}
    por_severidad = {}

    for r in rows:
        campo, tipo, sev, n = r[0], r[1], r[2], r[3]
        por_campo[campo] = por_campo.get(campo, 0) + n
        por_tipo[tipo] = por_tipo.get(tipo, 0) + n
        por_severidad[sev] = por_severidad.get(sev, 0) + n

    return {
        "total": sum(por_campo.values()),
        "por_campo": por_campo,
        "por_tipo_conflicto": por_tipo,
        "por_severidad": por_severidad,
    }


# ─── Posibles Matches ─────────────────────────────────────────────────────────

@router.get("/posibles-matches", summary="Listar duplicados detectados")
def listar_posibles_matches(
    decision: Optional[str] = None,
    regla: Optional[str] = None,
    score_min: Optional[int] = None,
    score_max: Optional[int] = None,
    solo_ia: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """
    Lista los pares de registros que podrían ser duplicados.

    - **decision**: auto_match, no_match, pendiente_revision, ia_match
    - **regla**: MISMO_NIT, MISMO_EMAIL_MUNICIPIO, NOMBRE_SIMILAR_MUNICIPIO, etc.
    - **score_min/score_max**: rango de score del match
    - **solo_ia**: true = solo los que fueron procesados por IA
    """
    conds = ["1=1"]
    params = {"skip": skip, "limit": limit}

    if decision:
        conds.append("pm.decision = :decision")
        params["decision"] = decision
    if regla:
        conds.append("pm.regla_match = :regla")
        params["regla"] = regla
    if score_min is not None:
        conds.append("pm.score_match >= :score_min")
        params["score_min"] = score_min
    if score_max is not None:
        conds.append("pm.score_match <= :score_max")
        params["score_max"] = score_max
    if solo_ia:
        conds.append("pm.creado_por_ia = true")

    where = " AND ".join(conds)

    total = db.execute(
        text(f"SELECT COUNT(*) FROM staging.posibles_matches pm WHERE {where}"), params
    ).scalar()

    # Stats globales
    stats = db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE decision = 'auto_match') AS auto_match,
            COUNT(*) FILTER (WHERE decision = 'no_match') AS no_match,
            COUNT(*) FILTER (WHERE decision = 'pendiente_revision') AS pendiente,
            COUNT(*) FILTER (WHERE decision = 'ia_match') AS ia_match,
            COUNT(*) AS total
        FROM staging.posibles_matches
    """)).fetchone()

    rows = db.execute(text(f"""
        SELECT
            pm.match_id, pm.staging_id_a, pm.staging_id_b,
            pm.regla_match, pm.score_match, pm.decision,
            pm.razon_decision, pm.creado_por_ia, pm.confianza_ia,
            a.nombre_normalizado, a.fuente, a.municipio_norm,
            b.nombre_normalizado, b.fuente, b.municipio_norm,
            pm.created_at
        FROM staging.posibles_matches pm
        JOIN staging.empresas_unificadas a ON pm.staging_id_a = a.staging_id
        JOIN staging.empresas_unificadas b ON pm.staging_id_b = b.staging_id
        WHERE {where}
        ORDER BY pm.score_match DESC
        OFFSET :skip LIMIT :limit
    """), params).fetchall()

    return {
        "total_filtrado": total,
        "skip": skip,
        "limit": limit,
        "resumen_global": {
            "auto_match": stats[0], "no_match": stats[1],
            "pendiente_revision": stats[2], "ia_match": stats[3], "total": stats[4],
        },
        "matches": [
            {
                "match_id": r[0],
                "staging_id_a": r[1], "staging_id_b": r[2],
                "regla_match": r[3], "score_match": r[4],
                "decision": r[5], "razon_decision": r[6],
                "creado_por_ia": r[7],
                "confianza_ia": float(r[8]) if r[8] else None,
                "empresa_a": {"nombre": r[9], "fuente": r[10], "municipio": r[11]},
                "empresa_b": {"nombre": r[12], "fuente": r[13], "municipio": r[14]},
                "created_at": r[15].isoformat() if r[15] else None,
            }
            for r in rows
        ],
    }


# ─── Validación Manual ────────────────────────────────────────────────────────

class ValidacionManualRequest(BaseModel):
    match_id: int
    decision: str  # same_business → auto_match, different_business → no_match
    razon_usuario: Optional[str] = None


@router.post("/validar-manualmente", summary="Validar manualmente un match")
def validar_manualmente(
    request: ValidacionManualRequest,
    db: Session = Depends(get_db),
):
    """
    Marca un match pendiente como confirmado o rechazado manualmente.

    - **decision**: `same_business` (confirmar) o `different_business` (rechazar)
    """
    if request.decision not in ("same_business", "different_business"):
        raise HTTPException(
            status_code=400,
            detail="decision debe ser 'same_business' o 'different_business'"
        )

    row = db.execute(text("""
        SELECT match_id, decision FROM staging.posibles_matches WHERE match_id = :mid
    """), {"mid": request.match_id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Match no encontrado")

    decision_anterior = row[1]
    nueva_decision = "auto_match" if request.decision == "same_business" else "no_match"

    db.execute(text("""
        UPDATE staging.posibles_matches
        SET decision = :decision,
            razon_decision = :razon,
            updated_at = NOW()
        WHERE match_id = :mid
    """), {
        "decision": nueva_decision,
        "razon": request.razon_usuario or "Validación manual por usuario",
        "mid": request.match_id,
    })
    db.commit()

    return {
        "status": "actualizado",
        "match_id": request.match_id,
        "decision_anterior": decision_anterior,
        "decision_nueva": nueva_decision,
        "mensaje": "Match validado manualmente. Ejecuta de nuevo la consolidación para que tome efecto.",
    }


# ─── Staging Stats ────────────────────────────────────────────────────────────

@router.get("/staging/stats", summary="Estadísticas del staging actual")
def staging_stats(db: Session = Depends(get_db)):
    """Estadísticas del staging en memoria."""
    try:
        row = db.execute(text("""
            SELECT
                COUNT(*) AS total,
                COUNT(DISTINCT fuente) AS fuentes,
                COUNT(*) FILTER (WHERE nit IS NOT NULL) AS con_nit,
                COUNT(*) FILTER (WHERE correo_normalizado IS NOT NULL) AS con_email,
                COUNT(*) FILTER (WHERE telefono_normalizado IS NOT NULL) AS con_telefono,
                COUNT(*) FILTER (WHERE latitud IS NOT NULL) AS con_coordenadas
            FROM staging.empresas_unificadas
        """)).fetchone()

        por_fuente = db.execute(text("""
            SELECT fuente, COUNT(*) FROM staging.empresas_unificadas GROUP BY fuente ORDER BY COUNT(*) DESC
        """)).fetchall()

        return {
            "total_staging": row[0],
            "fuentes_distintas": row[1],
            "con_nit": row[2],
            "con_email": row[3],
            "con_telefono": row[4],
            "con_coordenadas": row[5],
            "por_fuente": [{"fuente": r[0], "n": r[1]} for r in por_fuente],
        }
    except Exception as e:
        return {"error": str(e), "mensaje": "Staging vacío o tabla no existe. Ejecuta el pipeline primero."}
