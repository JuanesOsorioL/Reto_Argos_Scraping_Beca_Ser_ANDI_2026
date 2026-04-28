"""
services/openrouter_service.py

Integración con OpenRouter para usar modelos GRATIS.
Incorpora la lógica del main.py de OpenRouter existente:
- Rotación automática de modelos
- Categorías de modelos por capacidad
- Fallback automático si un modelo falla
- Ahorro máximo de tokens con prompts cortos
"""

import os
import json
import time
import logging
import requests
from typing import Any, Optional

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ── Modelos por categoría (del main.py existente) ──────────────────────────

PREFERRED_FREE_MODELS = [
    "qwen/qwen3-coder:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "z-ai/glm-4.5-air:free",
]

BACKUP_FREE_MODELS = [
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "minimax/minimax-m2.5:free",
    "google/gemma-3-12b-it:free",
    "google/gemma-3-4b-it:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
]

LIGHTWEIGHT_FREE_MODELS = [
    "liquid/lfm-2.5-1.2b-instruct:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "google/gemma-3-4b-it:free",
]

# Excluidos de la rotación general (OCR, visión, preview, experimentales)
EXCLUDED_FROM_GENERAL_ROTATION = [
    "baidu/qianfan-ocr-fast:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "tencent/hy3-preview:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
]

# Cache de modelos disponibles (evita llamar a /models en cada request)
_models_cache: list[str] = []
_models_cache_ts: float = 0
_CACHE_TTL = 300  # 5 minutos


class OpenRouterService:
    """
    Servicio de IA gratuita usando OpenRouter.
    
    Estrategia de uso económico:
    - Prompts muy cortos (< 200 tokens)
    - Respuestas JSON compactas (< 100 tokens)
    - Rotación automática si un modelo falla
    - Máximo 3 modelos por intento
    """

    def __init__(self, api_key: str = None, max_models_to_try: int = 3):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.max_models_to_try = max_models_to_try
        self.llamadas_totales = 0
        self.errores_totales = 0
        self.disponible = bool(self.api_key)

        if not self.disponible:
            logger.warning("⚠ OPENROUTER_API_KEY no configurada. Modelos gratis no disponibles.")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get_available_models(self) -> list[str]:
        """Obtiene modelos disponibles con cache de 5 minutos"""
        global _models_cache, _models_cache_ts

        if _models_cache and (time.time() - _models_cache_ts) < _CACHE_TTL:
            return _models_cache

        try:
            resp = requests.get(
                f"{OPENROUTER_BASE_URL}/models",
                headers=self._headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                all_models = resp.json().get("data", [])
                _models_cache = [m["id"] for m in all_models if m.get("id", "").endswith(":free")]
                _models_cache_ts = time.time()
                logger.info(f"✓ {len(_models_cache)} modelos :free disponibles en OpenRouter")
                return _models_cache
        except Exception as e:
            logger.warning(f"⚠ No se pudo consultar modelos OpenRouter: {e}")

        # Fallback: usar lista hardcodeada
        return PREFERRED_FREE_MODELS + BACKUP_FREE_MODELS

    def _build_rotation_list(self) -> list[str]:
        """Construye lista de modelos ordenada por prioridad"""
        available = set(self._get_available_models())

        ordered = []
        for model_id in PREFERRED_FREE_MODELS + BACKUP_FREE_MODELS + LIGHTWEIGHT_FREE_MODELS:
            if (
                model_id in available
                and model_id not in EXCLUDED_FROM_GENERAL_ROTATION
                and model_id not in ordered
            ):
                ordered.append(model_id)

        # Agrega cualquier otro :free no excluido
        for model_id in available:
            if model_id not in EXCLUDED_FROM_GENERAL_ROTATION and model_id not in ordered:
                ordered.append(model_id)

        return ordered[: self.max_models_to_try]

    def _llamar_modelo(self, model_id: str, prompt: str, max_tokens: int = 200) -> str | None:
        """Llama a un modelo específico. Retorna el texto o None si falla."""
        try:
            resp = requests.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=self._headers(),
                json={
                    "model": model_id,
                    "max_tokens": max_tokens,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Responde SOLO con JSON válido. Sin markdown. Sin explicaciones.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=30,
            )

            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                self.llamadas_totales += 1
                return content.strip()
            else:
                logger.debug(f"  Modelo {model_id} devolvió {resp.status_code}")
                return None

        except Exception as e:
            logger.debug(f"  Error con {model_id}: {e}")
            self.errores_totales += 1
            return None

    def preguntar_con_rotacion(
        self,
        prompt: str,
        max_tokens: int = 200,
        esperar_json: bool = True,
    ) -> dict[str, Any]:
        """
        Pregunta a modelos gratis con rotación automática.
        Retorna dict con: respuesta, modelo_usado, exito
        """
        if not self.disponible:
            return {"exito": False, "razon": "Sin API key OpenRouter", "respuesta": None}

        modelos = self._build_rotation_list()
        errores = []

        for model_id in modelos:
            logger.debug(f"  Intentando: {model_id}")
            texto = self._llamar_modelo(model_id, prompt, max_tokens)

            if texto:
                if esperar_json:
                    # Limpiar markdown si viene envuelto
                    clean = texto
                    if "```" in clean:
                        parts = clean.split("```")
                        for part in parts:
                            if part.startswith("json"):
                                clean = part[4:].strip()
                            elif "{" in part:
                                clean = part.strip()

                    try:
                        parsed = json.loads(clean)
                        return {
                            "exito": True,
                            "modelo_usado": model_id,
                            "respuesta": parsed,
                            "texto_raw": texto,
                        }
                    except json.JSONDecodeError:
                        errores.append({"model": model_id, "error": "JSON inválido", "texto": texto[:100]})
                        continue
                else:
                    return {
                        "exito": True,
                        "modelo_usado": model_id,
                        "respuesta": texto,
                        "texto_raw": texto,
                    }

            errores.append({"model": model_id, "error": "Sin respuesta"})

        return {
            "exito": False,
            "razon": "Ningún modelo respondió",
            "modelos_intentados": modelos,
            "errores": errores,
            "respuesta": None,
        }

    # ── Tareas específicas para el pipeline ─────────────────────────────────

    def resolver_duplicado(
        self,
        nombre_a: str,
        municipio_a: str,
        fuente_a: str,
        nombre_b: str,
        municipio_b: str,
        fuente_b: str,
        score_actual: int,
    ) -> dict[str, Any]:
        """
        Pregunta si dos registros son el mismo negocio.
        Prompt ultra-compacto para ahorrar tokens.
        """
        prompt = (
            f"¿Mismo negocio?\n"
            f"A:\"{nombre_a}\" {municipio_a} [{fuente_a}]\n"
            f"B:\"{nombre_b}\" {municipio_b} [{fuente_b}]\n"
            f"Score:{score_actual}\n"
            f'JSON:{{\"igual\":true/false,\"confianza\":0.0-1.0,\"nota\":\"breve\"}}'
        )

        resultado = self.preguntar_con_rotacion(prompt, max_tokens=80)

        if resultado["exito"]:
            resp = resultado["respuesta"]
            igual = resp.get("igual", False)
            return {
                "decision": "same_business" if igual else "different_business",
                "confianza": int(float(resp.get("confianza", 0.5)) * 100),
                "razon": resp.get("nota", ""),
                "modelo": resultado["modelo_usado"],
            }

        return {"decision": "error", "confianza": 0, "razon": resultado.get("razon", ""), "modelo": None}

    def validar_empresa_con_serper(
        self,
        nombre: str,
        municipio: str,
        resultados_serper: list[dict],
    ) -> dict[str, Any]:
        """
        Dado un nombre+municipio y resultados de Google (via Serper),
        pregunta a la IA si la empresa existe y extrae NIT/teléfono si los hay.
        Prompt muy corto para no gastar tokens.
        """
        if not resultados_serper:
            return {"validada": False, "razon": "Sin resultados de búsqueda"}

        # Solo tomar los primeros 3 snippets para no gastar tokens
        snippets = []
        for r in resultados_serper[:3]:
            s = r.get("snippet", "") or r.get("title", "")
            if s:
                snippets.append(s[:120])

        contexto = " | ".join(snippets)

        prompt = (
            f"Empresa:\"{nombre}\" en {municipio}\n"
            f"Resultados Google:{contexto}\n"
            f'JSON:{{\"existe\":true/false,\"nit\":\"..o null\",\"telefono\":\"..o null\",\"confianza\":0-1}}'
        )

        resultado = self.preguntar_con_rotacion(prompt, max_tokens=100)

        if resultado["exito"]:
            resp = resultado["respuesta"]
            return {
                "validada": bool(resp.get("existe", False)),
                "nit_encontrado": resp.get("nit"),
                "telefono_encontrado": resp.get("telefono"),
                "confianza": float(resp.get("confianza", 0)),
                "modelo": resultado["modelo_usado"],
            }

        return {"validada": False, "razon": resultado.get("razon", ""), "modelo": None}

    def clasificar_sucursal(
        self,
        nombre: str,
        municipio: str,
        otras_sucursales: list[str],
    ) -> dict[str, Any]:
        """
        Determina si un registro es una sucursal distinta de la misma empresa
        o la misma tienda en diferente fuente.
        """
        sucursales_str = ", ".join(otras_sucursales[:5])
        prompt = (
            f"Empresa:\"{nombre}\"\n"
            f"Ciudad actual:{municipio}\n"
            f"Otras ciudades conocidas:{sucursales_str}\n"
            f'¿Es sucursal independiente?\n'
            f'JSON:{{\"es_sucursal\":true/false,\"tipo\":\"sucursal|sede_principal|duplicado\"}}'
        )

        resultado = self.preguntar_con_rotacion(prompt, max_tokens=80)

        if resultado["exito"]:
            resp = resultado["respuesta"]
            return {
                "es_sucursal": bool(resp.get("es_sucursal", True)),
                "tipo": resp.get("tipo", "sucursal"),
                "modelo": resultado["modelo_usado"],
            }

        return {"es_sucursal": True, "tipo": "sucursal", "modelo": None}

    def resumen(self) -> dict:
        return {
            "llamadas_totales": self.llamadas_totales,
            "errores_totales": self.errores_totales,
        }


# ── Singleton global ─────────────────────────────────────────────────────────
_openrouter_instance: OpenRouterService | None = None


def get_openrouter_service() -> OpenRouterService:
    global _openrouter_instance
    if _openrouter_instance is None:
        _openrouter_instance = OpenRouterService(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
            max_models_to_try=int(os.getenv("OPENROUTER_MAX_MODELS", "3")),
        )
    return _openrouter_instance
