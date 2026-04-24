"""
═══════════════════════════════════════════════════════════════════════════════
main.py — Orquestador del scraping Serper con pausa automática
═══════════════════════════════════════════════════════════════════════════════

Flujo principal:
  1. Genera todas las queries (keyword × ciudad)
  2. Salta queries ya procesadas (permite reanudación)
  3. Llama a Serper para cada query
  4. Maneja automáticamente 429 (rate limit) con reintentos y pausa
  5. Aplana y enriquece resultados
  6. Inserta en PostgreSQL
  7. Guarda progreso después de cada query
  8. Guarda JSON local si SAVE_JSON_BACKUP=true

Pausas:
  - SerperRateLimitError (429): Pausa automática, espera, reintenta
  - Manual (POST /pause): Se detiene inmediatamente
  - Error crítico: Se reporta y pausa
"""

import os
import json
import time
import uuid
from datetime import datetime, timezone

from config import (
    OUTPUT_DIR, RAW_JSON_FILE, FLAT_JSON_FILE,
    SERPER_SLEEP_SECONDS, KEYWORDS_BUSQUEDA, CIUDAD_DEPARTAMENTO,
    SAVE_JSON_BACKUP, PROGRESS_FILE, SAVE_PROGRESS_FILE,
    AUTO_RESUME_ON_RATE_LIMIT, RATE_LIMIT_SLEEP_SECONDS, MAX_CONSECUTIVE_RATE_LIMITS,
)
from db import init_db, insertar_consulta, insertar_resultado, consulta_ya_procesada
from scraper import (
    call_serper, flatten_response, enrich_records,
    SerperRateLimitError, SerperAuthError, SerperApiError
)
from utils import normalize_city


# ═══════════════════════════════════════════════════════════════════════════════
# EXCEPCIONES PERSONALIZADAS DEL ORQUESTADOR
# ═══════════════════════════════════════════════════════════════════════════════

class PauseRequested(Exception):
    """Usuario llamó POST /pause — detener inmediatamente."""
    pass


class TokensDepletedPause(Exception):
    """Demasiados reintentos por 429 — pausa hasta manual resume."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# VARIABLE GLOBAL: Control de pausa manual
# ═══════════════════════════════════════════════════════════════════════════════

CONTROL = {
    "pause_requested": False,  # Se activa cuando usuario llama POST /pause
}


def request_pause():
    """
    Solicita una pausa manual (llamado por POST /pause endpoint).
    
    La siguiente iteración del loop detectará esto y levantará PauseRequested.
    """
    CONTROL["pause_requested"] = True


def clear_pause():
    """Limpia la bandera de pausa (cuando se reanuda)."""
    CONTROL["pause_requested"] = False


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES
# ═══════════════════════════════════════════════════════════════════════════════

def ensure_output_dir():
    """Crea el directorio 'output' si no existe."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def save_json(path, data):
    """
    Guarda datos en JSON de forma segura.
    
    Args:
        path (str): Ruta del archivo
        data: Datos a guardar (se serializan con json.dump)
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def save_progress(data: dict):
    """
    Guarda el archivo de progreso (serper_progress.json).
    
    Se llama después de cada query para poder reanudar exactamente 
    donde se quedó si la app se cae.
    
    Args:
        data (dict): Diccionario con estado actual:
            {
                "run_id": "uuid",
                "inicio": "2024-01-20T10:30:00",
                "indice_actual": 5,
                "queries_total": 2000,
                "queries_hechas": 4,
                "registros_nuevos": 120,
                "status": "corriendo" | "pausado_sin_tokens" | "ok"
                ...
            }
    """
    if not SAVE_PROGRESS_FILE:
        return
    
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def build_queries(ciudades: list, limit_keywords=None):
    """
    Genera todas las combinaciones de keyword × ciudad.
    
    Args:
        ciudades (list[dict]): REQUERIDO. Lista de ciudades a procesar
            Ej: [{"municipio": "bogota", "departamento": "Cundinamarca"}, ...]
        limit_keywords (int): Si es int, tomar solo los primeros N keywords
    
    Returns:
        list: Lista de dicts con estructura:
            [
                {
                    "keyword": "ferreterías",
                    "ciudad": "bogota",
                    "departamento": "Cundinamarca",
                    "query": "ferreterías en Bogotá, Colombia"
                },
                ...
            ]
    
    Ejemplo:
        >>> ciudades = [{"municipio": "bogota", "departamento": "Cundinamarca"}]
        >>> queries = build_queries(ciudades, limit_keywords=2)
        >>> len(queries)  # 2 queries
        2
    """
    # Validar ciudades
    if not ciudades or not isinstance(ciudades, list):
        raise ValueError("ciudades debe ser una lista no vacía")
    
    # Limitar keywords si se especifica (útil para modo prueba)
    keywords = KEYWORDS_BUSQUEDA[:limit_keywords] if limit_keywords else KEYWORDS_BUSQUEDA
    
    queries = []
    for keyword in keywords:
        for ciudad_obj in ciudades:  # ✅ Ahora ciudad_obj es dict
            ciudad = ciudad_obj["municipio"]  # Extraer nombre
            departamento = ciudad_obj["departamento"]  # Extraer departamento
            ciudad_texto = normalize_city(ciudad)
            queries.append({
                "keyword":     keyword,
                "ciudad":      ciudad,
                "departamento": departamento,  # ✅ Del parámetro, no de CIUDAD_DEPARTAMENTO
                "query":       f"{keyword} en {ciudad_texto}, Colombia",
            })
    return queries


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL: do_scrape
# ═══════════════════════════════════════════════════════════════════════════════

async def do_scrape(ciudades: list, limit_keywords=None, page=1):
    """
    Función principal del scraping Serper.
    
    Flujo:
        1. Inicializar BD y directorios
        2. Generar todas las queries con ciudades dinámicas
        3. Para cada query:
            a. Verificar si ya fue procesada (reanudación)
            b. Llamar a Serper
            c. Manejar 429 con reintentos automáticos
            d. Aplana y enriquece resultados
            e. Inserta en PostgreSQL
            f. Guarda progreso
        4. Guarda JSON local si está habilitado
        5. Retorna métricas finales
    
    Args:
        ciudades (list[dict]): REQUERIDO. Lista de ciudades a procesar
            Ej: [{"municipio": "bogota", "departamento": "Cundinamarca"}, ...]
        limit_keywords (int): Opcional, solo procesar primeros N keywords
        page (int): Página de resultados a scraping (defecto: 1)
    
    Raises:
        PauseRequested: Usuario llamó POST /pause
        TokensDepletedPause: Demasiados 429 consecutivos
        SerperAuthError: API key inválida (error crítico)
    
    Returns:
        dict: Métricas finales:
            {
                "run_id": "uuid",
                "inicio": "2024-01-20T10:30:00",
                "fin": "2024-01-20T11:45:00",
                "duracion": "1h 15m",
                "queries_total": 2000,
                "queries_hechas": 1950,
                "queries_saltadas": 50,
                "registros_nuevos": 3500,
                "duplicados": 200,
                "aprobados_argos": 1200,
                "errores_totales": 3
            }
    
    Ejemplo de uso (en api_runner.py):
        >>> metricas = await do_scrape(limit_keywords=2, limit_cities=2)
        >>> print(metricas["registros_nuevos"])  # 45 (por ejemplo)
    """
    
    # ─── INICIALIZAR ───────────────────────────────────────────────────────
    clear_pause()  # Limpiar bandera de pausa
    ensure_output_dir()  # Crear directorio output/
    init_db()  # Crear tablas si no existen
    
    # ─── GENERAR QUERIES ────────────────────────────────────────────────────
    # ✅ Validar ciudades
    if not ciudades or not isinstance(ciudades, list):
        raise ValueError("❌ CIUDADES REQUERIDAS EN PARÁMETRO")
    
    run_id  = str(uuid.uuid4())
    queries = build_queries(ciudades=ciudades, limit_keywords=limit_keywords)  # ✅ Pasar ciudades
    
    # ─── MOSTRAR INICIO EN LOGS ─────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  🚀 SERPER SCRAPING - INICIADO")
    print(f"{'='*80}")
    print(f"  run_id:          {run_id}")
    print(f"  Inicio:          {datetime.now(timezone.utc).isoformat()}")
    print(f"  Total queries:   {len(queries)}")
    print(f"  Página:          {page}")
    print(f"  JSON Backup:     {'✅ SÍ' if SAVE_JSON_BACKUP else '❌ NO'}")
    print(f"  Progreso File:   {'✅ SÍ' if SAVE_PROGRESS_FILE else '❌ NO'}")
    print(f"{'='*80}\n")
    
    # ─── VARIABLES DE CONTROL ───────────────────────────────────────────────
    raw_responses  = []
    flat_results   = []
    total_ins      = 0
    total_dup      = 0
    total_aprobados = 0
    saltadas       = 0
    errores_totales = 0
    queries_hechas = 0
    ultima_query   = None
    consecutive_rate_limits = 0
    
    inicio_dt = datetime.now(timezone.utc)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # LOOP PRINCIPAL: Procesar cada query
    # ═══════════════════════════════════════════════════════════════════════════
    
    for idx, meta_query in enumerate(queries, start=1):
        
        # ─── VERIFICAR PAUSA MANUAL ────────────────────────────────────────
        if CONTROL["pause_requested"]:
            # Usuario llamó POST /pause, guardar estado y terminar
            save_progress({
                "run_id": run_id,
                "inicio": inicio_dt.isoformat(),
                "indice_actual": idx,
                "queries_total": len(queries),
                "queries_hechas": queries_hechas,
                "queries_saltadas": saltadas,
                "registros_nuevos": total_ins,
                "duplicados": total_dup,
                "aprobados_argos": total_aprobados,
                "errores_totales": errores_totales,
                "ultima_query": ultima_query,
                "status": "pausado_manual",
                "page": page,
                "consecutive_rate_limits": consecutive_rate_limits,
            })
            raise PauseRequested("Pausa manual solicitada por usuario")
        
        # ─── EXTRAER INFO DE LA QUERY ───────────────────────────────────────
        query_text = meta_query["query"]
        ultima_query = query_text
        
        # ─── VERIFICAR SI ALREADY PROCESADA (REANUDACIÓN) ────────────────────
        if consulta_ya_procesada(query_text, page):
            saltadas += 1
            continue
        
        # ─── IMPRIMIR PROGRESO ──────────────────────────────────────────────
        print(f"[{idx:4d}/{len(queries):4d}] {query_text}")
        
        # ═══════════════════════════════════════════════════════════════════════
        # BLOQUE PRINCIPAL: Llamar a Serper + Procesar
        # ═══════════════════════════════════════════════════════════════════════
        
        try:
            # ─── LLAMAR A SERPER ────────────────────────────────────────────
            response_json = call_serper(query_text, page=page)
            
            # ✅ ÉXITO: Serper respondió sin 429
            consecutive_rate_limits = 0
            
            # ─── INSERTAR CONSULTA EN BD ────────────────────────────────────
            consulta_id = insertar_consulta({
                "run_id":          run_id,
                "query":           query_text,
                "keyword_busqueda": meta_query["keyword"],
                "ciudad":          normalize_city(meta_query["ciudad"]),
                "departamento":    meta_query["departamento"],
                "page":            page,
                "tipo_consulta":   "search",
                "raw_response":    response_json,
            })
            
            # ─── GUARDAR EN JSON LOCAL (Si habilitado) ─────────────────────
            if SAVE_JSON_BACKUP:
                raw_responses.append({
                    "run_id":     run_id,
                    "query_meta": meta_query,
                    "response":   response_json,
                })
            
            # ─── APLANA RESPUESTA ───────────────────────────────────────────
            registros = flatten_response(run_id, consulta_id, meta_query, response_json)
            
            # ─── ENRIQUECE (Visita URLs) ───────────────────────────────────
            registros = enrich_records(registros)
            
            # ─── INSERTAR RESULTADOS EN BD ──────────────────────────────────
            ins = 0  # Insertados nuevos
            dup = 0  # Duplicados (ignorados)
            apr = 0  # Aprobados por Argos
            
            for registro in registros:
                if insertar_resultado(registro):
                    ins += 1
                    if registro.get("aprobado_argos"):
                        apr += 1
                else:
                    dup += 1
            
            # ─── ACTUALIZAR CONTADORES ────────────────────────────────────
            total_ins       += ins
            total_dup       += dup
            total_aprobados += apr
            queries_hechas  += 1
            
            # ─── GUARDAR EN JSON LOCAL (Si habilitado) ─────────────────────
            if SAVE_JSON_BACKUP:
                flat_results.extend(registros)
            
            # ─── MOSTRAR MÉTRICAS DE ESTA QUERY ────────────────────────────
            organicos = sum(1 for r in registros if r.get("result_type") == "organic")
            print(f"  ✅ {organicos} orgánicos | Nuevos: {ins} | Aprobados: {apr}")
            
            # ─── GUARDAR PROGRESO ───────────────────────────────────────────
            save_progress({
                "run_id": run_id,
                "inicio": inicio_dt.isoformat(),
                "indice_actual": idx,
                "queries_total": len(queries),
                "queries_hechas": queries_hechas,
                "queries_saltadas": saltadas,
                "registros_nuevos": total_ins,
                "duplicados": total_dup,
                "aprobados_argos": total_aprobados,
                "errores_totales": errores_totales,
                "ultima_query_ok": query_text,
                "status": "corriendo",
                "page": page,
                "consecutive_rate_limits": consecutive_rate_limits,
            })
            
            # ─── RESPETAR RATE LIMIT DE SERPER ────────────────────────────
            # Esperar antes de la siguiente query (Serper: 100 req/min máx)
            time.sleep(SERPER_SLEEP_SECONDS)
        
        # ═══════════════════════════════════════════════════════════════════════
        # MANEJO DE RATE LIMIT (429) — AUTOMÁTICO
        # ═══════════════════════════════════════════════════════════════════════
        
        except SerperRateLimitError as e:
            # ⚠️ Serper devolvió 429: Rate limit alcanzado
            consecutive_rate_limits += 1
            
            print(f"  ⚠️  RATE LIMIT #{consecutive_rate_limits} (429): {str(e)[:100]}")
            
            # ─── GUARDAR ESTADO DE PAUSA ────────────────────────────────────
            save_progress({
                "run_id": run_id,
                "inicio": inicio_dt.isoformat(),
                "indice_actual": idx,
                "queries_total": len(queries),
                "queries_hechas": queries_hechas,
                "queries_saltadas": saltadas,
                "registros_nuevos": total_ins,
                "duplicados": total_dup,
                "aprobados_argos": total_aprobados,
                "errores_totales": errores_totales,
                "ultima_query_error": query_text,
                "status": "pausado_sin_tokens",
                "page": page,
                "ultimo_error": str(e),
                "consecutive_rate_limits": consecutive_rate_limits,
            })
            
            # ─── DECIDIR SI CONTINUAR O PARAR ───────────────────────────────
            
            if not AUTO_RESUME_ON_RATE_LIMIT:
                # Usuario deshabilitó auto-resume, lanzar excepción
                raise TokensDepletedPause(f"Rate limit sin auto-resume: {str(e)}")
            
            if consecutive_rate_limits >= MAX_CONSECUTIVE_RATE_LIMITS:
                # Demasiados reintentos, parar
                raise TokensDepletedPause(
                    f"Demasiados rate limits consecutivos: {consecutive_rate_limits}/{MAX_CONSECUTIVE_RATE_LIMITS}"
                )
            
            # ─── ESPERAR Y REINTENTAR ───────────────────────────────────────
            print(f"  ⏳ Esperando {RATE_LIMIT_SLEEP_SECONDS}s antes de reintentar...")
            time.sleep(RATE_LIMIT_SLEEP_SECONDS)
            
            # NO hacer idx += 1, reintentar la misma query en la siguiente iteración
            # (el loop sigue, pero sin avanzar en queries)
            continue  # Ir a la siguiente iteración del for
        
        # ═══════════════════════════════════════════════════════════════════════
        # ERROR DE AUTENTICACIÓN (401/403) — NO REINTENTABLE
        # ═══════════════════════════════════════════════════════════════════════
        
        except SerperAuthError as e:
            # ❌ API key inválida o sin créditos
            # Esta es una falla crítica, no se puede recuperar
            print(f"  ❌ ERROR DE AUTENTICACIÓN: {e}")
            raise  # Re-lanzar para que se reporte al endpoint
        
        # ═══════════════════════════════════════════════════════════════════════
        # OTROS ERRORES DE API (4xx/5xx sin 429)
        # ═══════════════════════════════════════════════════════════════════════
        
        except SerperApiError as e:
            # ⚠️ Error API (timeout, error 5xx, etc)
            # No es reintentable ahora, pero queremos continuar con siguientes
            errores_totales += 1
            print(f"  ❌ ERROR API: {str(e)[:80]}")
            
            # ─── GUARDAR ESTADO ────────────────────────────────────────────
            save_progress({
                "run_id": run_id,
                "inicio": inicio_dt.isoformat(),
                "indice_actual": idx,
                "queries_total": len(queries),
                "queries_hechas": queries_hechas,
                "queries_saltadas": saltadas,
                "registros_nuevos": total_ins,
                "duplicados": total_dup,
                "aprobados_argos": total_aprobados,
                "errores_totales": errores_totales,
                "ultima_query_error": query_text,
                "status": "corriendo_con_error",
                "page": page,
                "ultimo_error": str(e),
            })
            
            # Continuar con siguiente query (no parar todo)
            continue
        
        # ═══════════════════════════════════════════════════════════════════════
        # OTROS ERRORES NO ESPERADOS
        # ═══════════════════════════════════════════════════════════════════════
        
        except Exception as e:
            # ⚠️ Error inesperado
            errores_totales += 1
            print(f"  ❌ ERROR INESPERADO: {str(e)[:80]}")
            
            save_progress({
                "run_id": run_id,
                "inicio": inicio_dt.isoformat(),
                "indice_actual": idx,
                "queries_total": len(queries),
                "queries_hechas": queries_hechas,
                "queries_saltadas": saltadas,
                "registros_nuevos": total_ins,
                "duplicados": total_dup,
                "aprobados_argos": total_aprobados,
                "errores_totales": errores_totales,
                "ultima_query_error": query_text,
                "status": "corriendo_con_error",
                "page": page,
                "ultimo_error": str(e),
            })
            
            continue
    
    # ═══════════════════════════════════════════════════════════════════════════
    # FINALIZACIÓN: Procesar resultados y retornar métricas
    # ═══════════════════════════════════════════════════════════════════════════
    
    fin_dt = datetime.now(timezone.utc)
    duracion_s = max(0, round((fin_dt - inicio_dt).total_seconds()))
    
    # Formatear duración amigable
    minutos = duracion_s // 60
    segundos = duracion_s % 60
    duracion = f"{minutos}m {segundos}s"
    
    # ─── GUARDAR JSON LOCAL (Si habilitado) ─────────────────────────────────
    if SAVE_JSON_BACKUP:
        save_json(RAW_JSON_FILE, raw_responses)
        save_json(FLAT_JSON_FILE, flat_results)
        print(f"✅ JSON guardados: {RAW_JSON_FILE}, {FLAT_JSON_FILE}\n")
    
    # ─── CONSTRUIR MÉTRICAS FINALES ─────────────────────────────────────────
    metricas = {
        "run_id": run_id,
        "inicio": inicio_dt.isoformat(),
        "fin": fin_dt.isoformat(),
        "duracion": duracion,
        "queries_total": len(queries),
        "queries_hechas": queries_hechas,
        "queries_saltadas": saltadas,
        "registros_nuevos": total_ins,
        "duplicados": total_dup,
        "aprobados_argos": total_aprobados,
        "errores_totales": errores_totales,
        "ultima_query": ultima_query,
        "page": page,
        "json_backup_habilitado": SAVE_JSON_BACKUP,
        "raw_json_file": RAW_JSON_FILE if SAVE_JSON_BACKUP else None,
        "flat_json_file": FLAT_JSON_FILE if SAVE_JSON_BACKUP else None,
        "progress_file": PROGRESS_FILE if SAVE_PROGRESS_FILE else None,
    }
    
    # ─── GUARDAR PROGRESO FINAL ────────────────────────────────────────────
    save_progress({
        **metricas,
        "status": "ok"
    })
    
    # ─── MOSTRAR RESUMEN ────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  ✅ SERPER SCRAPING - COMPLETADO")
    print(f"{'='*80}")
    print(f"  run_id:              {run_id}")
    print(f"  Duración:            {duracion}")
    print(f"  Queries total:       {len(queries)}")
    print(f"  Queries hechas:      {queries_hechas}")
    print(f"  Queries saltadas:    {saltadas}")
    print(f"  Registros nuevos:    {total_ins}")
    print(f"  Duplicados:          {total_dup}")
    print(f"  Aprobados Argos:     {total_aprobados}")
    print(f"  Errores:             {errores_totales}")
    print(f"{'='*80}\n")
    
    return metricas


# ═══════════════════════════════════════════════════════════════════════════════
# MODO STANDALONE (Para ejecutar manualmente con python main.py)
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import asyncio
    
    # Descomentar UNO de estos modos:
    
    # ❌ MODO PRUEBA (2 keywords × 2 ciudades para testear rápido)
    # asyncio.run(do_scrape(limit_keywords=2, limit_cities=2))
    
    # ✅ MODO PRODUCCIÓN COMPLETO (Todas las keywords y ciudades)
    asyncio.run(do_scrape())
