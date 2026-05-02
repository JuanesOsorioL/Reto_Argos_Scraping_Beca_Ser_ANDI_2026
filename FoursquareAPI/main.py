"""
main.py — Orquestador principal del scraping Foursquare
Función: do_scrape() ejecutada por api_runner.py

Características:
  1. Detección automática de 403 (rate limit)
  2. Pausa automática si AUTO_PAUSE_ON_RATE_LIMIT=true
  3. Reanudación automática si AUTO_RESUME_AFTER_PAUSE=true
  4. Guardado de progreso en foursquare_progress.json
  5. Guardado de datos en PostgreSQL (SIEMPRE)
  6. Guardado de JSONs (configurable: SAVE_JSON_BACKUP)
"""
import uuid
import json
import os
import time
import requests
from datetime import datetime, timezone

from config import (
    KEYWORDS_BUSQUEDA,
    OUTPUT_DIR, OUTPUT_FILE, JSON_RAW_FILE, JSON_FLAT_FILE, PROGRESS_FILE,
    SAVE_JSON_BACKUP, SAVE_PROGRESS_FILE,
    AUTO_PAUSE_ON_RATE_LIMIT, RATE_LIMIT_SLEEP_SECONDS,
    MAX_CONSECUTIVE_RATE_LIMITS, AUTO_RESUME_AFTER_PAUSE,
    WEBHOOK_ON_PAUSE, WEBHOOK_ON_COMPLETE, WEBHOOK_ON_ERROR,
    DEBUG,
)
from db import init_db, cargar_fsq_ids_procesados, insertar_lugar, guardar_progreso, cargar_progreso
from scraper import buscar_lugares, RateLimitException, AuthException
from normalizer import normalizar_lugar


def ensure_output_dir():
    if SAVE_JSON_BACKUP:
        """Crea directorio de salida si no existe."""
        os.makedirs(OUTPUT_DIR, exist_ok=True)


def save_json(path: str, data):
    """Guarda datos en JSON con formato legible."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"  [JSON] ✓ Guardado: {path}")


def guardar_jsonl_local(datos: dict):
    """Respaldo local línea a línea (JSONL)."""
    datos_serial = {
        k: v.isoformat() if hasattr(v, 'isoformat') else v
        for k, v in datos.items()
        if k != "raw_place"
    }
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(datos_serial, ensure_ascii=False) + '\n')


def guardar_progreso_json(run_id: str, estado: dict):
    """
    Guarda progreso en archivo JSON para referencia rápida.
    
    Args:
        run_id: UUID de la corrida
        estado: dict con progreso actual
    """
    if not SAVE_PROGRESS_FILE:
        return
    
    estado["run_id"] = run_id
    estado["fecha_actualizacion"] = datetime.now(timezone.utc).isoformat()
    
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
        if DEBUG:
            print(f"  [PROG] Guardado: {PROGRESS_FILE}")
    except Exception as e:
        print(f"  [PROG] ❌ Error guardando progreso: {e}")


def enviar_webhook(webhook_url: str, datos: dict):
    """
    Envía notificación a n8n vía webhook.
    
    Args:
        webhook_url: URL del webhook en n8n
        datos: dict con información a enviar
    """
    if not webhook_url:
        return
    
    try:
        response = requests.post(
            webhook_url,
            json=datos,
            timeout=10
        )
        if response.status_code in [200, 201, 202]:
            print(f"  [HOOK] ✓ Webhook enviado a n8n")
        else:
            print(f"  [HOOK] ⚠️  Webhook respondió con {response.status_code}")
    except Exception as e:
        print(f"  [HOOK] ❌ Error enviando webhook: {e}")


async def do_scrape(ciudades: list, run_idfinal: str, keywords: list = None):
    """
    Función principal compatible con api_runner.py.

    Args:
        ciudades: list[dict] — REQUERIDO
        Ej: [{"municipio": "bogota", "departamento": "Cundinamarca"}, ...]
        keywords: list[str] opcional — si no se envía, usa KEYWORDS_BUSQUEDA de config

    Ejecuta:
      1. Inicializa BD
      2. Loop sobre keywords × ciudades dinámicas
      3. Detecta 403 → pausa automática → reanudación
      4. Guarda datos en PostgreSQL + JSONs
      5. Envía webhooks a n8n
    """

    # ✅ VALIDACIÓN OBLIGATORIA
    if not ciudades:
        raise ValueError("❌ CIUDADES REQUERIDAS EN PARÁMETRO. "
                        "api_runner.py debe enviar lista de ciudades")
    
    if not isinstance(ciudades, list):
        raise TypeError(f"ciudades debe ser list, recibió {type(ciudades)}")
    
    for i, ciudad_obj in enumerate(ciudades):
        if not isinstance(ciudad_obj, dict) or "municipio" not in ciudad_obj:
            raise ValueError(f"Ciudad #{i} debe tener 'municipio': {ciudad_obj}")
    
    ensure_output_dir()
    init_db()

    keywords_activas = keywords if keywords else KEYWORDS_BUSQUEDA

    # ──────────────────────────────────────────────────────────────────────
    # INICIALIZACIÓN DE LA CORRIDA
    # ──────────────────────────────────────────────────────────────────────

    run_id = run_idfinal
    fecha_extraccion = datetime.now(timezone.utc)
    procesados = cargar_fsq_ids_procesados()

    total_combinaciones = len(keywords_activas) * len(ciudades)
    
    print(f"\n{'='*70}")
    print(f"[FOURSQUARE SCRAPER] run_id: {run_id}")
    print(f"  Inicio:        {fecha_extraccion.isoformat()}")
    print(f"  Combinaciones: {total_combinaciones} (keywords × ciudades)")
    print(f"  Ya en BD:      {len(procesados)} lugares")
    print(f"  AUTO_PAUSE:    {AUTO_PAUSE_ON_RATE_LIMIT}")
    print(f"  JSON_BACKUP:   {SAVE_JSON_BACKUP}")
    print(f"{'='*70}\n")
    
    # ──────────────────────────────────────────────────────────────────────
    # ACUMULADORES PARA ESTADÍSTICAS Y JSONS
    # ──────────────────────────────────────────────────────────────────────
    
    raw_responses = []   # Respuestas crudas de FSQ
    flat_results = []    # Registros normalizados
    
    total_ins = 0        # Total insertados
    total_dup = 0        # Total duplicados
    total_apr = 0        # Total aprobados Argos
    combo_num = 0        # Número de combinación actual
    
    rate_limit_count = 0 # Cuántas veces se pausó por 403
    
    # ──────────────────────────────────────────────────────────────────────
    # LOOP PRINCIPAL: Keywords × Ciudades
    # ──────────────────────────────────────────────────────────────────────
    
    for ciudad_obj in ciudades:  # ✅ Dinámico
        ciudad_nombre = ciudad_obj["municipio"]
        departamento = ciudad_obj["departamento"]
        near = f"{ciudad_nombre}, {departamento}, Colombia"  # Construir "near"
        
        for keyword in keywords_activas:
            combo_num += 1
            
            print(f"\n[{combo_num:3d}/{total_combinaciones}] '{keyword}' en {ciudad_nombre}")
            
            # ──────────────────────────────────────────────────────────────
            # BÚSQUEDA CON MANEJO DE RATE LIMIT
            # ──────────────────────────────────────────────────────────────
            
            try:
                lugares = buscar_lugares(keyword, near)
            
            except RateLimitException as e:
                # Se alcanzó el rate limit (403)
                print(f"  [RATE] 🛑 Rate limit detectado: {e.message}")
                rate_limit_count += 1
                
                # Guardar estado de pausa
                estado_pausa = {
                    "estado": "pausado",
                    "razon": "rate_limit_403",
                    "combinacion_actual": {"keyword": keyword, "ciudad": ciudad_nombre},
                    "combo_numero": combo_num,
                    "total_combinaciones": total_combinaciones,
                    "total_procesadas": combo_num - 1,
                    "total_insertadas": total_ins,
                    "total_duplicadas": total_dup,
                    "total_aprobadas": total_apr,
                    "rate_limit_count": rate_limit_count,
                }
                
                guardar_progreso(run_id, estado_pausa)
                guardar_progreso_json(run_id, estado_pausa)
                
                # Enviar webhook a n8n
                if WEBHOOK_ON_PAUSE:
                    enviar_webhook(WEBHOOK_ON_PAUSE, estado_pausa)
                
                if not AUTO_PAUSE_ON_RATE_LIMIT:
                    print(f"  [RATE] AUTO_PAUSE deshabilitado, abortando...")
                    break
                
                if rate_limit_count >= MAX_CONSECUTIVE_RATE_LIMITS:
                    print(f"  [RATE] Máximo de pausas ({MAX_CONSECUTIVE_RATE_LIMITS}) alcanzado, abortando...")
                    break
                
                # Esperar antes de reanudar
                print(f"  [RATE] Esperando {RATE_LIMIT_SLEEP_SECONDS}s antes de reanudar...")
                time.sleep(RATE_LIMIT_SLEEP_SECONDS)
                
                if AUTO_RESUME_AFTER_PAUSE:
                    print(f"  [RATE] Reanudando automáticamente...")
                    try:
                        lugares = buscar_lugares(keyword, near)
                    except RateLimitException:
                        print(f"  [RATE] Aún hay rate limit, saltando...")
                        continue
                else:
                    print(f"  [RATE] AUTO_RESUME deshabilitado, saltando...")
                    continue
            
            except AuthException as e:
                # API key inválida
                print(f"  [AUTH] ❌ {e}")
                estado_error = {
                    "estado": "error",
                    "tipo_error": "auth_401",
                    "mensaje": str(e),
                    "combo_numero": combo_num,
                }
                enviar_webhook(WEBHOOK_ON_ERROR, estado_error)
                break
            
            except Exception as e:
                # Error inesperado
                print(f"  [ERR] ❌ Error inesperado: {e}")
                if DEBUG:
                    import traceback
                    traceback.print_exc()
                continue
            
            # ──────────────────────────────────────────────────────────────
            # PROCESAMIENTO DE RESULTADOS
            # ──────────────────────────────────────────────────────────────
            
            if not lugares:
                print(f"  [->] Sin resultados.")
                continue
            
            # Guardar respuesta cruda
            raw_responses.append({
                "run_id": run_id,
                "keyword": keyword,
                "ciudad": ciudad_nombre,
                "near": near,
                "total": len(lugares),
                "results": lugares,
            })
            
            ins = 0
            dup = 0
            apr = 0
            
            for place in lugares:
                fsq_id = place.get("fsq_place_id")
                
                # Skip si ya está en caché
                if fsq_id and fsq_id in procesados:
                    dup += 1
                    continue
                
                # Normalizar según esquema Argos
                registro = normalizar_lugar(
                    place=place,
                    ciudad_nombre=ciudad_nombre,
                    keyword=keyword,
                    run_id=run_id,
                    fecha_extraccion=fecha_extraccion,
                )
                
                if not registro:
                    continue
                
                # Insertar en PostgreSQL (SIEMPRE, aunque no haya JSON backup)
                if insertar_lugar(registro):
                    ins += 1
                    if registro.get("aprobado_argos"):
                        apr += 1
                    if fsq_id:
                        procesados.add(fsq_id)
                    
                    # Respaldo local JSONL
                    #guardar_jsonl_local(registro)
                    
                    # Respaldo local JSONL solo si está habilitado
                    if SAVE_JSON_BACKUP:
                        guardar_jsonl_local(registro)



                    # Acumular para JSON flat (sin raw_place)
                    registro_flat = {k: v for k, v in registro.items() if k != "raw_place"}
                    flat_results.append(registro_flat)
                else:
                    dup += 1
            
            total_ins += ins
            total_dup += dup
            total_apr += apr
            print(f"  [OK] Insertados: {ins} | Duplicados: {dup} | Aprobados: {apr}")
            
            time.sleep(0.5)  # Retraso entre combinaciones
    
    # ──────────────────────────────────────────────────────────────────────
    # GUARDADO FINAL
    # ──────────────────────────────────────────────────────────────────────
    

    """
    O:     Started server process [14088]
    INFO:     Waiting for application startup.

    [API] 🚀 Foursquare Scraper API en http://0.0.0.0:8005
    [API] Documentación: http://0.0.0.0:8005/docs
    [API] Health: http://0.0.0.0:8005/health
    [DB] ✅ Tabla raw.foursquare_ferreterias verificada.
    [API] ✓ Base de datos inicializada
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://0.0.0.0:8005 (Press CTRL+C to quit)
    [DB] ✅ Tabla raw.foursquare_ferreterias verificada.
    INFO:     127.0.0.1:52556 - "POST /scrape/foursquare HTTP/1.1" 200 OK

    [API] 🚀 Iniciando scraping con run_id: 5980d241-d99d-4a81-b02d-9946965c4d4f
    [DB] ✅ Tabla raw.foursquare_ferreterias verificada.

    ======================================================================
    [FOURSQUARE SCRAPER] run_id: 28042c20-857f-4c3a-9b4d-aa5b2d7a4969
    Inicio:        2026-04-15T15:47:42.746719+00:00
    Combinaciones: 360 (keywords × ciudades)
    Ya en BD:      50 lugares
    AUTO_PAUSE:    True
    JSON_BACKUP:   False
    ======================================================================


    [  1/360] 'ferretería' en Bogotá
    [FSQ] Buscando 'ferretería' en Bogotá, Colombia...
        [DEBUG] Request intento 1/3
        [DEBUG] Status: 200
        [DEBUG] Rate limit remaining: 179975
        [FSQ] +50 resultados (total: 50/200)
        [DEBUG] Request intento 1/3
        [DEBUG] Status: 200
        [DEBUG] Rate limit remaining: 179974
        [FSQ] +50 resultados (total: 100/200)
        [DEBUG] Request intento 1/3
        [DEBUG] Status: 200
        [DEBUG] Rate limit remaining: 179973
        [FSQ] +50 resultados (total: 150/200)
        [DEBUG] Request intento 1/3
        [DEBUG] Status: 200
        [DEBUG] Rate limit remaining: 179972
        [FSQ] +50 resultados (total: 200/200)
    [OK] Insertados: 0 | Duplicados: 200 | Aprobados: 0

    [  2/360] 'materiales de construcción' en Bogotá
    [FSQ] Buscando 'materiales de construcción' en Bogotá, Colombia...
        [DEBUG] Request intento 1/3
        [DEBUG] Status: 200
        [DEBUG] Rate limit remaining: 179971
    """


    # Guardar JSONs (si está habilitado)
    print(SAVE_JSON_BACKUP)
    if SAVE_JSON_BACKUP:
        print("entro ",SAVE_JSON_BACKUP)
        save_json(JSON_RAW_FILE, raw_responses)
        save_json(JSON_FLAT_FILE, flat_results)
    
     # ─── CALCULAR DURACIÓN Y PREPARAR MÉTRICAS ─────────────────────────────
    fecha_fin = datetime.now(timezone.utc)
    duracion_seconds = (fecha_fin - fecha_extraccion).total_seconds()
    duracion_minutos = int(duracion_seconds // 60)
    duracion_segundos = int(duracion_seconds % 60)
    duracion_str = f"{duracion_minutos}m {duracion_segundos}s"
    
    # ─── ESTRUCTURA FINAL DE NOTIFICACIÓN (formato n8n estándar) ───────────
    payload_webhook = {
        "evento": "foursquare.finalizado",        # ← Tipo de evento
        "status": "ok",                            # ← Estado de ejecución
        "run_id": run_id,                          # ← UUID de la corrida
        "inicio": fecha_extraccion.isoformat(),    # ← Timestamp inicio
        "fin": fecha_fin.isoformat(),              # ← Timestamp fin
        "duracion": duracion_str,                  # ← Duración formateada
        
        # ─── MÉTRICAS DETALLADAS ───────────────────────────────────────────
        "metricas": {
            "run_id": run_id,
            "inicio": fecha_extraccion.isoformat(),
            "fin": fecha_fin.isoformat(),
            "duracion": duracion_str,
            
            # Combinaciones procesadas
            "combinaciones_total": total_combinaciones,
            "combinaciones_procesadas": combo_num,
            "ciudades": len(ciudades),
            "keywords": len(keywords_activas),
            
            # Datos guardados
            "registros_nuevos": total_ins,
            "duplicados": total_dup,
            "aprobados_argos": total_apr,
            
            # Control de rate limit
            "rate_limit_pausas": rate_limit_count,
            
            # Configuración
            "json_backup_habilitado": SAVE_JSON_BACKUP,
            "raw_json_file": JSON_RAW_FILE if SAVE_JSON_BACKUP else None,
            "flat_json_file": JSON_FLAT_FILE if SAVE_JSON_BACKUP else None,
            "progress_file": PROGRESS_FILE if SAVE_PROGRESS_FILE else None,
        },
        
        "origen": "api_runner",                    # ← Quién envía
        "tipo_ejecucion": "produccion"             # ← Contexto de ejecución
    }
    
    # ─── GUARDAR ESTADO FINAL EN BD Y JSON ──────────────────────────────────
    # Guardar en BD (para auditoría)
    estado_final_bd = {
        "estado": "completado",
        "run_id": run_id,
        "total_procesadas": combo_num,
        "total_insertadas": total_ins,
        "total_duplicadas": total_dup,
        "total_aprobadas": total_apr,
        "rate_limit_count": rate_limit_count,
        "duracion": duracion_str,
    }
    guardar_progreso(run_id, estado_final_bd)
    guardar_progreso_json(run_id, payload_webhook)  # ← Guardar payload completo
    
    # ─── ENVIAR WEBHOOK A N8N CON FORMATO ESTÁNDAR ─────────────────────────
    if WEBHOOK_ON_COMPLETE:
        enviar_webhook(WEBHOOK_ON_COMPLETE, payload_webhook)
    
    # ──────────────────────────────────────────────────────────────────────
    # RESUMEN FINAL
    # ──────────────────────────────────────────────────────────────────────
    
    print(f"\n{'='*70}")
    print(f"[✅ COMPLETADO]")
    print(f"  run_id:              {run_id}")
    print(f"  Combinaciones:       {combo_num}/{total_combinaciones}")
    print(f"  Registros nuevos:    {total_ins}")
    print(f"  Duplicados:          {total_dup}")
    print(f"  Aprobados Argos:     {total_apr}")
    print(f"  Pausas por 403:      {rate_limit_count}")
    if SAVE_JSON_BACKUP:
        print(f"  JSON raw:            {JSON_RAW_FILE}")
        print(f"  JSON flat:           {JSON_FLAT_FILE}")
    print(f"  JSONL local:         {OUTPUT_FILE}")
    print(f"  PostgreSQL:          raw.foursquare_ferreterias")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(do_scrape())
