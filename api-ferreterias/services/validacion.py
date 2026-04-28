"""
services/validacion.py

Valida registros que NO están en RUES para determinar si son negocios reales.

Estrategia (de más barata a más cara):
  1. Reglas determinísticas rápidas (gratis)
  2. Búsqueda en Google via Serper (si ya se tienen resultados en raw.serper_*)
  3. Búsqueda Serper en tiempo real (1 request = bajo costo)
  4. IA gratuita OpenRouter para analizar resultados

RUES inactivos:
  - Se mantienen pero con penalización de score
  - Estado registrado en clean.empresas.estado_legal
"""

import os
import re
import json
import logging
import requests
from typing import Any, Optional
from sqlalchemy import text

logger = logging.getLogger(__name__)

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPER_URL = "https://google.serper.dev/search"


# ─── Validación de RUES inactivos ────────────────────────────────────────────

# Estados RUES que se consideran activos
ESTADOS_RUES_ACTIVOS = {
    "activo", "renovado", "inscrito", "vigente", "activa",
    "active", "registrado"
}

# Estados que reducen el score pero NO descartan
ESTADOS_RUES_INACTIVOS = {
    "cancelado", "disuelto", "liquidado", "inactivo",
    "suspendido", "revocado", "cancelada", "disuelta", "liquidada",
}


def evaluar_estado_rues(estado: str | None, ultimo_ano_renovado: str | None) -> dict[str, Any]:
    """
    Evalúa el estado de un registro RUES y retorna:
    - activo: bool
    - penalizacion_score: int (se resta al score final)
    - descripcion: str
    - incluir: bool (si False, no pasa a clean.empresas)
    
    Lógica de negocio:
    - Activo/Renovado → incluir, sin penalización
    - Sin renovar hace 2-3 años → incluir, penalización media
    - Sin renovar hace 4+ años → incluir con penalización alta (pueden seguir operando)
    - Cancelado/Disuelto → incluir con penalización, marcado como inactivo
      (pueden seguir operando informalmente o ser útiles para cruce)
    
    ¿Por qué no descartar cancelados?
    En Colombia muchos negocios siguen operando sin renovar su matrícula.
    La información de contacto sigue siendo valiosa.
    """
    from datetime import datetime

    estado_norm = (estado or "").lower().strip()
    ano_actual = datetime.now().year

    # Evaluar año de renovación
    anos_sin_renovar = None
    if ultimo_ano_renovado:
        try:
            ano_renovado = int(str(ultimo_ano_renovado)[:4])
            anos_sin_renovar = ano_actual - ano_renovado
        except (ValueError, TypeError):
            pass

    # Caso: cancelado/disuelto/liquidado
    if estado_norm in ESTADOS_RUES_INACTIVOS:
        return {
            "activo": False,
            "penalizacion_score": 15,
            "descripcion": f"RUES: {estado or 'inactivo'} — incluido con penalización",
            "incluir": True,   # Incluir de todas formas
            "razon_inclusion": "Negocio puede operar informalmente; contacto puede ser válido",
        }

    # Caso: sin información de estado
    if not estado_norm:
        penalizacion = 5
        return {
            "activo": None,
            "penalizacion_score": penalizacion,
            "descripcion": "Estado RUES no disponible",
            "incluir": True,
        }

    # Caso: activo pero sin renovar hace tiempo
    if anos_sin_renovar is not None:
        if anos_sin_renovar >= 4:
            return {
                "activo": True,
                "penalizacion_score": 10,
                "descripcion": f"Sin renovar desde {ultimo_ano_renovado} ({anos_sin_renovar} años)",
                "incluir": True,
            }
        elif anos_sin_renovar >= 2:
            return {
                "activo": True,
                "penalizacion_score": 5,
                "descripcion": f"Sin renovar desde {ultimo_ano_renovado}",
                "incluir": True,
            }

    # Activo y renovado recientemente
    return {
        "activo": True,
        "penalizacion_score": 0,
        "descripcion": f"RUES activo: {estado}",
        "incluir": True,
    }


# ─── Búsqueda Serper en tiempo real ──────────────────────────────────────────

def buscar_en_google(nombre: str, municipio: str, nit: str = None) -> list[dict]:
    """
    Busca en Google via Serper API.
    Construye query inteligente: "nombre municipio colombia" o "NIT xxx"
    
    Costo: ~$0.001 por búsqueda (muy bajo).
    Solo se llama si no hay datos Serper en raw ya.
    """
    if not SERPER_API_KEY:
        logger.debug("⊘ SERPER_API_KEY no configurada. Salteando búsqueda Google.")
        return []

    # Query con NIT es más precisa
    if nit and re.match(r'^\d{8,10}$', nit):
        query = f'NIT {nit} ferreteria Colombia'
    else:
        query = f'"{nombre}" {municipio} Colombia ferreteria materiales'

    try:
        resp = requests.post(
            SERPER_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "gl": "co", "hl": "es", "num": 5},
            timeout=15,
        )

        if resp.status_code == 200:
            data = resp.json()
            resultados = []

            # Knowledge Graph (más confiable)
            kg = data.get("knowledgeGraph", {})
            if kg.get("title"):
                resultados.append({
                    "tipo": "knowledge_graph",
                    "title": kg.get("title"),
                    "snippet": kg.get("description", ""),
                    "link": kg.get("website", ""),
                    "address": kg.get("address", ""),
                    "phone": kg.get("phoneNumber", ""),
                })

            # Resultados orgánicos
            for r in data.get("organic", [])[:4]:
                resultados.append({
                    "tipo": "organic",
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                    "link": r.get("link", ""),
                })

            return resultados

    except Exception as e:
        logger.warning(f"⚠ Error búsqueda Serper para '{nombre}': {e}")

    return []


def extraer_datos_de_resultados(resultados: list[dict]) -> dict[str, Any]:
    """
    Extrae NIT, teléfono, dirección de los resultados de Google
    sin necesidad de IA (regex básico).
    """
    texto_completo = " ".join([
        f"{r.get('title','')} {r.get('snippet','')} {r.get('address','')}"
        for r in resultados
    ])

    nit = None
    telefono = None
    email = None

    # Buscar NIT en texto
    nit_match = re.search(r'\bNIT\s*:?\s*(\d{8,10})[-.]?\d?\b', texto_completo, re.IGNORECASE)
    if nit_match:
        nit = nit_match.group(1)

    # Buscar teléfono
    tel_match = re.search(r'\b(?:\+57\s?)?[36]\d{9}\b', texto_completo)
    if tel_match:
        telefono = re.sub(r'\D', '', tel_match.group())

    # Buscar email
    email_match = re.search(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b', texto_completo)
    if email_match:
        email = email_match.group().lower()

    # Teléfono desde knowledge graph
    for r in resultados:
        if r.get("tipo") == "knowledge_graph" and r.get("phone"):
            telefono = re.sub(r'\D', '', r["phone"])
            if telefono.startswith("57"):
                telefono = telefono[2:]
            break

    return {
        "nit_google": nit,
        "telefono_google": telefono,
        "email_google": email,
        "fuentes_google": len(resultados),
    }


# ─── Validador principal ──────────────────────────────────────────────────────

def validar_registro_sin_rues(
    staging_id: int,
    nombre: str,
    municipio: str,
    fuente: str,
    telefono: str = None,
    email: str = None,
    nit: str = None,
    usar_ia: bool = True,
    usar_serper: bool = True,
) -> dict[str, Any]:
    """
    Valida un registro que NO tiene equivalente en RUES.
    
    Niveles de confianza:
    - ALTA (80+): múltiples fuentes + datos de contacto + encontrado en Google
    - MEDIA (50-79): 2+ fuentes pero sin confirmación Google
    - BAJA (<50): fuente única, sin contacto, no encontrado en Google
    
    Retorna:
    - es_valido: bool
    - score_validacion: int (0-100)
    - datos_enriquecidos: dict (NIT, tel, email encontrados en Google)
    - metodo_validacion: str
    """
    score = 0
    datos_enriquecidos = {}
    metodo = "reglas_basicas"

    # 1. Puntaje base por tener datos de contacto
    if telefono:
        score += 20
    if email:
        score += 15
    if nit:
        score += 30  # Si tiene NIT es casi seguro válido

    # 2. Puntaje por fuente
    fuente_scores = {
        "google_maps": 25,
        "paginas_amarillas": 20,
        "foursquare": 15,
        "openstreetmap": 15,
        "serper": 10,
    }
    score += fuente_scores.get(fuente, 10)

    # Si ya tiene NIT con score alto, no necesita más validación
    if score >= 80:
        return {
            "es_valido": True,
            "score_validacion": min(score, 100),
            "datos_enriquecidos": datos_enriquecidos,
            "metodo_validacion": "reglas_basicas_nit",
            "incluir": True,
        }

    # 3. Búsqueda en Google para enriquecer y validar
    resultados_google = []
    if usar_serper and SERPER_API_KEY:
        resultados_google = buscar_en_google(nombre, municipio, nit)
        datos_google = extraer_datos_de_resultados(resultados_google)
        datos_enriquecidos.update(datos_google)
        metodo = "serper_google"

        if resultados_google:
            score += 20  # Existe en Google → buen indicador
            if datos_google.get("nit_google"):
                score += 20
                datos_enriquecidos["nit_google_confianza"] = "alta"
            if datos_google.get("telefono_google"):
                score += 10

    # 4. IA para casos intermedios (solo si score entre 30-65 y hay resultados Google)
    if usar_ia and resultados_google and 30 <= score <= 65:
        from services.openrouter_service import get_openrouter_service
        or_service = get_openrouter_service()

        if or_service.disponible:
            ia_result = or_service.validar_empresa_con_serper(
                nombre=nombre,
                municipio=municipio,
                resultados_serper=resultados_google,
            )

            if ia_result.get("validada"):
                score += int(ia_result.get("confianza", 0.5) * 20)
                metodo = f"serper+ia({ia_result.get('modelo','?')})"

                if ia_result.get("nit_encontrado"):
                    datos_enriquecidos["nit_ia"] = ia_result["nit_encontrado"]
                if ia_result.get("telefono_encontrado"):
                    datos_enriquecidos["telefono_ia"] = ia_result["telefono_encontrado"]

    score = min(score, 100)
    es_valido = score >= 40  # Umbral mínimo para incluir

    return {
        "es_valido": es_valido,
        "score_validacion": score,
        "datos_enriquecidos": datos_enriquecidos,
        "metodo_validacion": metodo,
        "incluir": es_valido,
        "resultados_google": len(resultados_google),
    }


# ─── Lógica de sucursales ─────────────────────────────────────────────────────

def es_sucursal_independiente(
    nombre: str,
    municipio_actual: str,
    otros_municipios: list[str],
) -> bool:
    """
    Determina si un registro con el mismo nombre en diferente municipio
    es una sucursal independiente (debe guardarse como empresa separada).
    
    Regla simple: mismo nombre + diferente municipio = siempre sucursal separada.
    La matching rule ya lo maneja: solo matchea si MISMO municipio.
    
    Esta función es para documentar la decisión de diseño.
    """
    # En nuestra arquitectura, el matching requiere MISMO municipio para
    # NOMBRE_SIMILAR_MUNICIPIO. Por lo tanto sucursales en diferentes ciudades
    # ya se tratan automáticamente como empresas independientes.
    # Solo las une MISMO_NIT (si tienen el mismo NIT legal = misma empresa matriz)
    return True


# ─── Función para DB: enriquecer y validar registros sin RUES en staging ─────

def validar_y_enriquecer_staging(
    db,
    usar_ia: bool = True,
    usar_serper: bool = True,
    solo_sin_nit: bool = True,
    limite: int = 500,
) -> dict[str, Any]:
    """
    Para registros en staging que NO tienen equivalente en RUES:
    1. Busca en Google via Serper
    2. Extrae NIT/tel/email si aparece
    3. Actualiza staging con datos enriquecidos
    4. Registra score_validacion
    
    solo_sin_nit=True → solo enriquece registros sin NIT (los de RUES ya tienen)
    """
    logger.info(f"🔍 Validando registros sin RUES (limite={limite})...")

    # Obtener candidatos: registros sin NIT, sin equivalente en RUES
    where_nit = "AND nit IS NULL" if solo_sin_nit else ""
    rows = db.execute(text(f"""
        SELECT staging_id, nombre_normalizado, municipio_norm,
               fuente, telefono_normalizado, correo_normalizado, nit
        FROM staging.empresas_unificadas
        WHERE fuente != 'rues'
          {where_nit}
          AND nombre_normalizado IS NOT NULL
          AND aprobado_origen = true  -- solo registros que pasaron filtro origen
        ORDER BY fuente, staging_id
        LIMIT :lim
    """), {"lim": limite}).fetchall()

    if not rows:
        logger.info("⊘ No hay registros para validar")
        return {"validados": 0, "enriquecidos": 0}

    validados = 0
    enriquecidos = 0

    for row in rows:
        staging_id, nombre, municipio, fuente, telefono, email, nit = row

        resultado = validar_registro_sin_rues(
            staging_id=staging_id,
            nombre=nombre or "",
            municipio=municipio or "",
            fuente=fuente,
            telefono=telefono,
            email=email,
            nit=nit,
            usar_ia=usar_ia,
            usar_serper=usar_serper,
        )

        # Actualizar score_origen con el score de validación
        nuevo_score = resultado["score_validacion"]
        db.execute(text("""
            UPDATE staging.empresas_unificadas
            SET score_origen = GREATEST(COALESCE(score_origen, 0), :score),
                aprobado_origen = :aprobado
            WHERE staging_id = :sid
        """), {
            "score": nuevo_score,
            "aprobado": resultado["es_valido"],
            "sid": staging_id,
        })

        # Si se encontraron datos enriquecidos, actualizar
        datos = resultado.get("datos_enriquecidos", {})
        if datos.get("nit_google") or datos.get("nit_ia"):
            nit_nuevo = datos.get("nit_google") or datos.get("nit_ia")
            db.execute(text("""
                UPDATE staging.empresas_unificadas
                SET nit = :nit, match_key_nit = regexp_replace(:nit, '[^0-9]', '', 'g')
                WHERE staging_id = :sid AND nit IS NULL
            """), {"nit": nit_nuevo, "sid": staging_id})
            enriquecidos += 1

        if datos.get("telefono_google"):
            db.execute(text("""
                UPDATE staging.empresas_unificadas
                SET telefono_normalizado = :tel,
                    match_key_telefono = :tel
                WHERE staging_id = :sid AND telefono_normalizado IS NULL
            """), {"tel": datos["telefono_google"], "sid": staging_id})
            enriquecidos += 1

        if datos.get("email_google"):
            db.execute(text("""
                UPDATE staging.empresas_unificadas
                SET correo_normalizado = :email,
                    match_key_email = :email
                WHERE staging_id = :sid AND correo_normalizado IS NULL
            """), {"email": datos["email_google"], "sid": staging_id})
            enriquecidos += 1

        validados += 1

        if validados % 50 == 0:
            db.commit()
            logger.info(f"  Validados {validados}/{len(rows)}, enriquecidos: {enriquecidos}")

    db.commit()
    logger.info(f"✅ Validación completada. Validados: {validados}, Enriquecidos: {enriquecidos}")

    return {
        "validados": validados,
        "enriquecidos": enriquecidos,
        "total_candidatos": len(rows),
    }
