"""
workers/pipeline.py - Orquestador del pipeline completo v2
"""

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import text

logger = logging.getLogger(__name__)


def ejecutar_pipeline_completo_v2(
    db,
    config,
    execution_id: str,
    municipios: list = None,
    limpiar_staging: bool = True,
    usar_ia: bool = None,
    preferir_openrouter: bool = True,
    validar_sin_rues: bool = True,
    validar_con_ia: bool = True,
    incluir_rues_inactivos: bool = True,
    crear_json_campos_dudosos: bool = None,
    crear_json_posibles_matches: bool = None,
    webhook_url: str = None,
) -> dict:
    from workers.etl_loader import cargar_todo_a_staging
    from services.normalizacion import normalizar_staging
    from services.matching import detectar_todos_los_matches, obtener_stats_matches
    from services.campos_dudosos import (
        detectar_todos_campos_dudosos,
        exportar_campos_dudosos_json,
        exportar_posibles_matches_json,
    )
    from services.consolidacion import consolidar_empresas
    from services.calidad import calcular_scores_calidad, distribucion_scores
    from services.webhook_service import notificar_n8n

    ts_inicio = time.time()
    reporte = {
        "execution_id": execution_id,
        "timestamp_inicio": datetime.now(timezone.utc).isoformat(),
        "estado": "en_proceso",
        "scope_municipios": f"{len(municipios)} municipios" if municipios else "todos",
    }

    def set_fase(fase: str, pct: int):
        try:
            db.execute(text("""
                UPDATE staging.ejecuciones
                SET fase_actual = :fase, progreso_pct = :pct
                WHERE execution_id = :eid
            """), {"fase": fase, "pct": pct, "eid": execution_id})
            db.commit()
        except Exception:
            pass
        logger.info(f"[{execution_id}] {fase} ({pct}%)")

    def resolver_duplicado_ia(reg_a, reg_b, score):
        if preferir_openrouter:
            try:
                from services.openrouter_service import get_openrouter_service
                svc = get_openrouter_service()
                if svc.disponible:
                    return svc.resolver_duplicado(
                        nombre_a=reg_a.get("nombre_normalizado", ""),
                        municipio_a=reg_a.get("municipio_norm", ""),
                        fuente_a=reg_a.get("fuente", ""),
                        nombre_b=reg_b.get("nombre_normalizado", ""),
                        municipio_b=reg_b.get("municipio_norm", ""),
                        fuente_b=reg_b.get("fuente", ""),
                        score_actual=score,
                    )
            except Exception:
                pass

        if config.ANTHROPIC_API_KEY:
            from services.ia_service import IAService
            ia = IAService(
                api_key=config.ANTHROPIC_API_KEY,
                model=config.IA_MODEL,
                max_tokens=config.IA_MAX_TOKENS,
            )
            return ia.resolver_duplicado(reg_a, reg_b, score)

        return {"decision": "error", "confianza": 0, "razon": "Sin IA configurada"}

    try:
        # FASE 1: Cargar
        set_fase("Cargando fuentes raw", 5)
        conteos = cargar_todo_a_staging(db, limpiar_antes=limpiar_staging, municipios=municipios)
        total = sum(conteos.values())
        reporte["fase_1_carga"] = {**conteos, "total_staging": total}
        try:
            db.execute(text("UPDATE staging.ejecuciones SET registros_staging=:n WHERE execution_id=:eid"),
                       {"n": total, "eid": execution_id})
            db.commit()
        except Exception:
            pass

        if total == 0:
            raise ValueError("No se cargaron registros. Verifica que las tablas raw.* tengan datos.")

        # FASE 2: Normalizar
        set_fase("Normalizando datos", 18)
        reporte["fase_2_normalizacion"] = normalizar_staging(db)

        # FASE 3: Validar sin RUES
        reporte["fase_3_validacion_sin_rues"] = {"activo": False}
        if validar_sin_rues:
            set_fase("Validando registros sin RUES (Google + IA gratuita)", 30)
            try:
                from services.validacion import validar_y_enriquecer_staging
                stats_val = validar_y_enriquecer_staging(
                    db=db, usar_ia=validar_con_ia, usar_serper=True,
                    solo_sin_nit=True, limite=500,
                )
                reporte["fase_3_validacion_sin_rues"] = {**stats_val, "activo": True}
            except Exception as e:
                logger.warning(f"Validacion sin RUES omitida: {e}")

        # FASE 4: Matching
        set_fase("Detectando duplicados (7 reglas)", 42)
        conteos_match = detectar_todos_los_matches(db)
        stats_match = obtener_stats_matches(db)
        reporte["fase_4_matching"] = {**conteos_match, **stats_match}
        try:
            db.execute(text("UPDATE staging.ejecuciones SET matches_detectados=:n WHERE execution_id=:eid"),
                       {"n": stats_match["total"], "eid": execution_id})
            db.commit()
        except Exception:
            pass

        # FASE 5: Campos dudosos
        set_fase("Detectando campos dudosos", 55)
        conteos_cd = detectar_todos_campos_dudosos(db)
        usar_cd = crear_json_campos_dudosos if crear_json_campos_dudosos is not None else config.CREAR_JSON_CAMPOS_DUDOSOS
        usar_pm = crear_json_posibles_matches if crear_json_posibles_matches is not None else config.CREAR_JSON_POSIBLES_MATCHES
        ruta_cd = exportar_campos_dudosos_json(db, config) if usar_cd else None
        ruta_pm = exportar_posibles_matches_json(db, config) if usar_pm else None
        reporte["fase_5_campos_dudosos"] = {
            **conteos_cd, "total": sum(conteos_cd.values()), "archivo": ruta_cd
        }

        # FASE 6: IA duplicados
        usar_ia_real = usar_ia if usar_ia is not None else config.USAR_IA_DUPLICADOS
        reporte["fase_6_ia"] = {"activa": usar_ia_real}

        if usar_ia_real:
            proveedor = "OpenRouter (gratis)" if preferir_openrouter else "Claude"
            set_fase(f"Resolviendo duplicados con {proveedor}", 65)
            ia_stats = _procesar_matches_con_ia(db, config, resolver_duplicado_ia, preferir_openrouter)
            reporte["fase_6_ia"].update(ia_stats)

        # FASE 7: Consolidacion
        set_fase("Consolidando en clean.empresas", 75)
        stats_consolid = consolidar_empresas(db)
        reporte["fase_7_consolidacion"] = stats_consolid
        try:
            db.execute(text("UPDATE staging.ejecuciones SET empresas_consolidadas=:n WHERE execution_id=:eid"),
                       {"n": stats_consolid["empresas_consolidadas"], "eid": execution_id})
            db.commit()
        except Exception:
            pass

        # FASE 8: Scoring
        set_fase("Calculando scores de calidad", 88)
        stats_calidad = calcular_scores_calidad(db)
        reporte["fase_8_scoring"] = {**stats_calidad, "distribucion": distribucion_scores(db)}

        if not incluir_rues_inactivos:
            _eliminar_inactivos_clean(db)
            reporte["rues_inactivos"] = "eliminados segun configuracion"
        else:
            reporte["rues_inactivos"] = {"incluidos": True, "con_penalizacion": True}

        # Exportadores
        archivos = {
            "campos_dudosos_json": {"creado": bool(ruta_cd), "ruta": ruta_cd},
            "posibles_matches_json": {"creado": bool(ruta_pm), "ruta": ruta_pm},
        }
        if getattr(config, "CREAR_CSV_CLEAN_EMPRESAS", False):
            ruta_csv = _exportar_csv(db, config)
            archivos["clean_csv"] = {"creado": bool(ruta_csv), "ruta": ruta_csv}
        reporte["archivos_generados"] = archivos

        # Finalizar
        duracion = int(time.time() - ts_inicio)
        reporte["estado"] = "completado"
        reporte["timestamp_fin"] = datetime.now(timezone.utc).isoformat()
        reporte["duracion_segundos"] = duracion

        _guardar_reporte(reporte, config, execution_id)

        try:
            db.execute(text("""
                UPDATE staging.ejecuciones
                SET estado='completado', fase_actual='Enviando webhook a n8n',
                    progreso_pct=99, reporte_json=:rep,
                    timestamp_fin=NOW(), duracion_segundos=:dur
                WHERE execution_id=:eid
            """), {"rep": json.dumps(reporte, default=str), "dur": duracion, "eid": execution_id})
            db.commit()
        except Exception:
            pass

        # WEBHOOK n8n al finalizar
        set_fase("Notificando a n8n", 99)
        wh_result = notificar_n8n(execution_id=execution_id, reporte=reporte, db=db)
        reporte["webhook_n8n"] = wh_result

        try:
            db.execute(text("""
                UPDATE staging.ejecuciones
                SET fase_actual='finalizado', progreso_pct=100,
                    webhook_n8n_enviado=:env, webhook_n8n_url=:url
                WHERE execution_id=:eid
            """), {
                "env": wh_result.get("enviado", False),
                "url": wh_result.get("url", ""),
                "eid": execution_id,
            })
            db.commit()
        except Exception:
            pass

        logger.info(
            f"Pipeline completado en {duracion}s. "
            f"Empresas: {stats_consolid['empresas_consolidadas']}. "
            f"Webhook n8n: {'OK' if wh_result.get('enviado') else 'no enviado'}"
        )

    except Exception as e:
        logger.exception(f"Error pipeline [{execution_id}]: {e}")
        reporte["estado"] = "error"
        reporte["error"] = str(e)

        # Notificar error a n8n tambien
        try:
            from services.webhook_service import notificar_n8n
            notificar_n8n(execution_id=execution_id, reporte=reporte, db=db)
        except Exception:
            pass

        try:
            db.execute(text("""
                UPDATE staging.ejecuciones
                SET estado='error', error_mensaje=:err, timestamp_fin=NOW()
                WHERE execution_id=:eid
            """), {"err": str(e), "eid": execution_id})
            db.commit()
        except Exception:
            pass

    return reporte


def _procesar_matches_con_ia(db, config, resolver_fn, preferir_openrouter) -> dict:
    from services.ia_service import _obtener_registro

    matches = db.execute(text("""
        SELECT match_id, staging_id_a, staging_id_b, score_match
        FROM staging.posibles_matches
        WHERE decision = 'pendiente_revision'
          AND score_match BETWEEN :min AND :max
        ORDER BY score_match DESC
        LIMIT :batch
    """), {
        "min": config.IA_MIN_SCORE,
        "max": config.IA_MAX_SCORE,
        "batch": config.IA_BATCH_SIZE,
    }).fetchall()

    if not matches:
        return {"procesados": 0}

    procesados = 0
    errores = 0

    for match_id, sid_a, sid_b, score in matches:
        reg_a = _obtener_registro(db, sid_a)
        reg_b = _obtener_registro(db, sid_b)
        if not reg_a or not reg_b:
            continue

        resultado = resolver_fn(reg_a, reg_b, score)
        if resultado.get("decision") == "error":
            errores += 1
            continue

        try:
            db.execute(text("""
                INSERT INTO staging.ia_validaciones
                    (tipo_validacion, staging_id_a, staging_id_b,
                     input_json, output_json, decision, confianza, modelo, tokens_usados)
                VALUES ('deduplicacion_dudosa', :a, :b, :inp, :out, :dec, :conf, :mod, 0)
            """), {
                "a": sid_a, "b": sid_b,
                "inp": json.dumps({"a": reg_a, "b": reg_b}),
                "out": json.dumps(resultado),
                "dec": resultado["decision"],
                "conf": resultado.get("confianza", 0),
                "mod": resultado.get("modelo", "openrouter"),
            })

            nueva = "ia_match" if resultado["decision"] == "same_business" else "no_match"
            db.execute(text("""
                UPDATE staging.posibles_matches
                SET decision=:dec, creado_por_ia=true,
                    confianza_ia=:conf, razon_decision=:razon, updated_at=NOW()
                WHERE match_id=:mid
            """), {
                "dec": nueva, "conf": resultado.get("confianza", 0),
                "razon": resultado.get("razon", ""), "mid": match_id,
            })
            procesados += 1

            if procesados % 10 == 0:
                db.commit()
        except Exception:
            errores += 1

    db.commit()
    return {
        "procesados": procesados,
        "errores": errores,
        "proveedor": "openrouter" if preferir_openrouter else "claude",
    }


def _eliminar_inactivos_clean(db):
    try:
        db.execute(text("""
            DELETE FROM clean.empresas
            WHERE empresa_id IN (
                SELECT e.empresa_id FROM clean.empresas e
                WHERE e.aprobado_argos = false AND e.fuentes = ARRAY['rues']
            )
        """))
        db.commit()
    except Exception as e:
        logger.warning(f"Error eliminando inactivos: {e}")


def _exportar_csv(db, config) -> str:
    try:
        import csv
        rows = db.execute(text("""
            SELECT empresa_id::text, nit, nombre_comercial, razon_social,
                   departamento, municipio, direccion_principal,
                   telefono_principal, correo_principal,
                   score_calidad, aprobado_argos::text, fuente_principal
            FROM clean.empresas ORDER BY score_calidad DESC NULLS LAST
        """)).fetchall()
        path = Path(config.RUTA_CSV_CLEAN_EMPRESAS)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(["empresa_id","nit","nombre_comercial","razon_social",
                        "departamento","municipio","direccion",
                        "telefono","correo","score_calidad","aprobado_argos","fuente_principal"])
            w.writerows(rows)
        return str(path)
    except Exception as e:
        logger.error(f"Error CSV: {e}")
        return None


def _guardar_reporte(reporte: dict, config, execution_id: str):
    try:
        path = Path(config.RUTA_REPORTE_EJECUCION)
        path.mkdir(parents=True, exist_ok=True)
        with open(path / f"reporte_{execution_id}.json", 'w', encoding='utf-8') as f:
            json.dump(reporte, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"Error guardando reporte: {e}")
