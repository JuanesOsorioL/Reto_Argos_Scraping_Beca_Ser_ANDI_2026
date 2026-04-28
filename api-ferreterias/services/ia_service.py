"""
services/ia_service.py - Integración con Anthropic API para resolver duplicados dudosos
"""

import json
import time
import logging
from typing import Any
from datetime import datetime
from sqlalchemy import text

logger = logging.getLogger(__name__)


class IAService:
    """Servicio para usar Claude en casos de deduplicación ambigua"""

    def __init__(self, api_key: str, model: str = "claude-opus-4-5", max_tokens: int = 500):
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            self.disponible = True
        except ImportError:
            logger.warning("⚠ anthropic no instalado. IA no disponible.")
            self.client = None
            self.disponible = False

        self.model = model
        self.max_tokens = max_tokens
        self.tokens_input_total = 0
        self.tokens_output_total = 0
        self.llamadas_totales = 0
        self.errores_totales = 0

    @property
    def costo_estimado_usd(self) -> float:
        """Estimado de costo basado en tokens (precios aprox. claude-opus)"""
        # ~$15 por millón input, ~$75 por millón output
        return (self.tokens_input_total * 15 + self.tokens_output_total * 75) / 1_000_000

    def resolver_duplicado(
        self,
        registro_a: dict[str, Any],
        registro_b: dict[str, Any],
        score_actual: int
    ) -> dict[str, Any]:
        """
        Pregunta a Claude si dos registros son el mismo negocio.
        Usa prompt corto para ahorrar tokens.
        """
        if not self.disponible:
            return {"decision": "error", "confianza": 0, "razon": "IA no disponible"}

        def v(reg, campo):
            val = reg.get(campo)
            return val if val else "N/A"

        prompt = (
            f"¿Son el MISMO NEGOCIO?\n\n"
            f"A: \"{v(registro_a,'nombre_normalizado')}\" | {v(registro_a,'municipio_norm')} | "
            f"{v(registro_a,'direccion_normalizada')} | Tel:{v(registro_a,'telefono_normalizado')} | "
            f"Fuente:{v(registro_a,'fuente')}\n\n"
            f"B: \"{v(registro_b,'nombre_normalizado')}\" | {v(registro_b,'municipio_norm')} | "
            f"{v(registro_b,'direccion_normalizada')} | Tel:{v(registro_b,'telefono_normalizado')} | "
            f"Fuente:{v(registro_b,'fuente')}\n\n"
            f"Score actual: {score_actual}/100\n\n"
            f"Responde SOLO con JSON sin markdown:\n"
            f'{{\"decision\":\"same_business\" o \"different_business\",\"confianza\":0.0-1.0,\"razon\":\"breve\"}}'
        )

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )

            ti = message.usage.input_tokens
            to = message.usage.output_tokens
            self.tokens_input_total += ti
            self.tokens_output_total += to
            self.llamadas_totales += 1

            text_resp = message.content[0].text.strip()
            # Limpiar markdown si existe
            if "```" in text_resp:
                text_resp = text_resp.split("```")[1]
                if text_resp.startswith("json"):
                    text_resp = text_resp[4:]
                text_resp = text_resp.strip()

            result = json.loads(text_resp)
            return {
                "decision": result.get("decision", "error"),
                "confianza": int(float(result.get("confianza", 0.5)) * 100),
                "razon": result.get("razon", ""),
                "tokens_input": ti,
                "tokens_output": to,
            }

        except json.JSONDecodeError as e:
            self.errores_totales += 1
            logger.warning(f"Error parseando JSON de IA: {e}")
            return {"decision": "error", "confianza": 0, "razon": f"JSON inválido: {e}"}
        except Exception as e:
            self.errores_totales += 1
            logger.warning(f"Error llamando IA: {e}")
            return {"decision": "error", "confianza": 0, "razon": str(e)}

    def procesar_matches_pendientes(
        self,
        db,
        min_score: int = 60,
        max_score: int = 74,
        batch_size: int = 100
    ) -> dict[str, Any]:
        """
        Procesa matches pendientes en el rango de score especificado.
        Llama a Claude por cada par y actualiza la DB.
        """
        if not self.disponible:
            logger.warning("⚠ IA no disponible. Saltando procesamiento.")
            return {"procesados": 0, "errores": 0}

        logger.info(f"🤖 Procesando matches pendientes con IA (score {min_score}-{max_score}, batch={batch_size})")

        matches = db.execute(text("""
            SELECT match_id, staging_id_a, staging_id_b, score_match
            FROM staging.posibles_matches
            WHERE decision = 'pendiente_revision'
              AND score_match BETWEEN :min_score AND :max_score
            ORDER BY score_match DESC
            LIMIT :batch_size
        """), {"min_score": min_score, "max_score": max_score, "batch_size": batch_size}).fetchall()

        if not matches:
            logger.info("⊘ No hay matches pendientes en el rango")
            return {"procesados": 0, "errores": 0}

        procesados = 0
        errores = 0

        for i, (match_id, sid_a, sid_b, score) in enumerate(matches):
            reg_a = _obtener_registro(db, sid_a)
            reg_b = _obtener_registro(db, sid_b)

            if not reg_a or not reg_b:
                continue

            resultado = self.resolver_duplicado(reg_a, reg_b, score)

            if resultado["decision"] == "error":
                errores += 1
                continue

            # Guardar en ia_validaciones
            db.execute(text("""
                INSERT INTO staging.ia_validaciones
                    (tipo_validacion, staging_id_a, staging_id_b,
                     input_json, output_json, decision, confianza,
                     modelo, tokens_usados)
                VALUES
                    ('deduplicacion_dudosa', :sid_a, :sid_b,
                     :input_j, :output_j, :decision, :confianza,
                     :modelo, :tokens)
            """), {
                "sid_a": sid_a,
                "sid_b": sid_b,
                "input_j": json.dumps({"a": reg_a, "b": reg_b}),
                "output_j": json.dumps(resultado),
                "decision": resultado["decision"],
                "confianza": resultado["confianza"],
                "modelo": self.model,
                "tokens": resultado.get("tokens_input", 0) + resultado.get("tokens_output", 0),
            })

            # Actualizar decisión del match
            nueva_decision = "ia_match" if resultado["decision"] == "same_business" else "no_match"
            db.execute(text("""
                UPDATE staging.posibles_matches
                SET decision = :decision,
                    creado_por_ia = true,
                    confianza_ia = :confianza,
                    razon_decision = :razon,
                    updated_at = NOW()
                WHERE match_id = :match_id
            """), {
                "decision": nueva_decision,
                "confianza": resultado["confianza"],
                "razon": resultado.get("razon", ""),
                "match_id": match_id,
            })

            procesados += 1

            # Commit cada 10 para no perder todo si falla
            if procesados % 10 == 0:
                db.commit()
                logger.info(f"  Procesados {procesados}/{len(matches)}, tokens: {self.tokens_input_total + self.tokens_output_total}")

            # Rate limit simple
            if procesados % 20 == 0:
                time.sleep(1)

        db.commit()
        logger.info(
            f"✅ IA completada. Procesados: {procesados}, Errores: {errores}, "
            f"Tokens: {self.tokens_input_total + self.tokens_output_total}, "
            f"Costo est.: ${self.costo_estimado_usd:.4f}"
        )

        return {
            "procesados": procesados,
            "errores": errores,
            "tokens_input": self.tokens_input_total,
            "tokens_output": self.tokens_output_total,
            "costo_usd": round(self.costo_estimado_usd, 4),
        }

    def resumen(self) -> dict:
        return {
            "llamadas_totales": self.llamadas_totales,
            "errores_totales": self.errores_totales,
            "tokens_input_total": self.tokens_input_total,
            "tokens_output_total": self.tokens_output_total,
            "costo_estimado_usd": round(self.costo_estimado_usd, 4),
        }


def _obtener_registro(db, staging_id: int) -> dict | None:
    """Obtiene datos de un registro de staging"""
    row = db.execute(text("""
        SELECT staging_id, nit, nombre_normalizado, departamento_norm,
               municipio_norm, direccion_normalizada, latitud, longitud,
               telefono_normalizado, correo_normalizado, fuente
        FROM staging.empresas_unificadas
        WHERE staging_id = :id
    """), {"id": staging_id}).fetchone()

    if not row:
        return None

    return {
        "staging_id": row[0],
        "nit": row[1],
        "nombre_normalizado": row[2],
        "departamento_norm": row[3],
        "municipio_norm": row[4],
        "direccion_normalizada": row[5],
        "latitud": row[6],
        "longitud": row[7],
        "telefono_normalizado": row[8],
        "correo_normalizado": row[9],
        "fuente": row[10],
    }
