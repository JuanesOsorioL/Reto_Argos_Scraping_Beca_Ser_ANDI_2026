"""
main.py — Scraper Páginas Amarillas para Argos
Columnas requeridas: nit, nombre, departamento, municipio, direccion,
latitud, longitud, telefono, whatsapp, correo_electronico,
fecha_actualizacion, fuente
"""

import asyncio
import json
import os
import random
import uuid
from datetime import datetime, timezone

from playwright.async_api import async_playwright

import config
from scraper import obtener_urls_de_listado, extraer_detalle_negocio
from filter_engine import evaluar_cliente_argos
from normalizer import (
    normalizar_telefono, normalizar_whatsapp,
    normalizar_coordenadas, normalizar_categoria, generar_hash
)
from db import init_db, cargar_urls_procesadas, insertar_negocio


def guardar_jsonl_local(datos: dict):
    """Respaldo local — convierte datetime a string antes de serializar."""
    datos_serializables = {
        k: v.isoformat() if hasattr(v, 'isoformat') else v
        for k, v in datos.items()
    }
    with open(config.OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(datos_serializables, ensure_ascii=False) + "\n")


async def main(ciudades: list, keywords: list = None):
    """
    ciudades: list[dict] — REQUERIDO
    keywords: list[str] — opcional, usa config.KEYWORDS_BUSQUEDA si no se pasa
    """
    if not ciudades:
        raise ValueError("❌ CIUDADES REQUERIDAS EN PARÁMETRO")
    if not isinstance(ciudades, list):
        raise TypeError(f"ciudades debe ser list, recibió {type(ciudades)}")
    keywords = keywords or config.KEYWORDS_BUSQUEDA
    
    init_db()

    procesados       = cargar_urls_procesadas()
    run_id           = str(uuid.uuid4())
    fecha_extraccion = datetime.now(timezone.utc)

    print(f"[*] Caché BD: {len(procesados)} URLs ya procesadas.")
    print(f"[*] Ciudades: {len(ciudades)}")
    print(f"[*] Keywords: {len(keywords)}")
    print(f"[*] run_id:   {run_id}")
    print(f"[*] Inicio:   {fecha_extraccion.isoformat()}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.HEADLESS)

        for ciudad_obj in ciudades:  # ✅ Dinámico
            ciudad = ciudad_obj["municipio"]
            for keyword in keywords:
                print(f"\n{'='*50}")
                print(f"[*] {ciudad} → {keyword}")
                print(f"{'='*50}")

                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    )
                )

                page_listado    = await context.new_page()
                pagina          = 1
                urls_anteriores = []

                while True:
                    print(f"  [>] Página {pagina}...")
                    urls = await obtener_urls_de_listado(page_listado, ciudad, keyword, pagina)

                    if not urls:
                        print(f"  [!] Sin más páginas.")
                        break
                    if urls == urls_anteriores:
                        print(f"  [!] Páginas Amarillas repite resultados. Avanzando.")
                        break

                    urls_anteriores = urls
                    print(f"  [v] {len(urls)} URLs en página {pagina}.")

                    for i in range(0, len(urls), config.CONCURRENCIA_PESTANAS):
                        lote           = urls[i:i + config.CONCURRENCIA_PESTANAS]
                        tareas         = []
                        pares_page_url = []

                        for url_detalle in lote:
                            if url_detalle in procesados:
                                print(f"      [-] Saltando: {url_detalle}")
                                continue
                            nueva_pestana = await context.new_page()
                            pares_page_url.append((nueva_pestana, url_detalle))
                            tareas.append(extraer_detalle_negocio(nueva_pestana, url_detalle))

                        if not tareas:
                            continue

                        resultados_lote = await asyncio.gather(*tareas, return_exceptions=True)

                        for index, ((pestana, url_req), _) in enumerate(zip(pares_page_url, resultados_lote)):
                            await pestana.close()
                            res = resultados_lote[index]
                            if isinstance(res, Exception) or not res:
                                print(f"      [x] Error: {url_req}")
                                continue

                            if isinstance(res, list):
                                for obj in res:
                                    if "nombre" not in obj:
                                        continue

                                    # ── Scoring ───────────────────────────────
                                    aprobado, score = evaluar_cliente_argos(
                                        obj["nombre"], obj.get("descripcion", ""), keyword
                                    )

                                    # ── Normalización ─────────────────────────
                                    telefono, telefonos_adicionales = normalizar_telefono(obj.get("telefono", ""))
                                    whatsapp     = normalizar_whatsapp(obj.get("whatsapp", ""))
                                    lat, lon     = normalizar_coordenadas(obj.get("latitud"), obj.get("longitud"))
                                    categoria    = normalizar_categoria(keyword)
                                    departamento = config.CIUDAD_DEPARTAMENTO.get(ciudad, "")
                                    sucursal     = obj.get("sucursal_tipo", "Principal")
                                    hash_id      = generar_hash(url_req, sucursal)
                                    ahora        = datetime.now(timezone.utc)

                                    registro = {
                                        # ── Trazabilidad ──────────────────────
                                        "hash_id":               hash_id,
                                        "run_id":                run_id,
                                        "fecha_extraccion":      fecha_extraccion,

                                        # ── Columnas requeridas por Argos ─────
                                        "nit":                   "",           # PA no tiene NIT
                                        "nombre":                obj["nombre"],
                                        "departamento":          departamento,
                                        "municipio":             ciudad,
                                        "direccion":             obj.get("direccion", "").strip(),
                                        "latitud":               lat,
                                        "longitud":              lon,
                                        "telefono":              telefono,
                                        "whatsapp":              whatsapp,
                                        "correo_electronico":    obj.get("email", ""),
                                        "fecha_actualizacion":   ahora,
                                        "fuente":                "paginas_amarillas",

                                        # ── Columnas adicionales de calidad ───
                                        "sucursal_tipo":         sucursal,
                                        "telefonos_adicionales": telefonos_adicionales,
                                        "descripcion":           obj.get("descripcion", ""),
                                        "categoria_busqueda":    categoria,
                                        "keyword_busqueda":      keyword,
                                        "url":                   url_req,
                                        "score":                 score,
                                        "aprobado_argos":        aprobado,
                                    }

                                    insertado = insertar_negocio(registro)
                                    
                                    if insertado and config.SAVE_JSON_BACKUP:
                                        guardar_jsonl_local(registro)

                                    estado = "NUEVO" if insertado else "DUPLICADO"
                                    if aprobado:
                                        print(f"      [+] {estado} | Score {score} | {obj['nombre']} | {ciudad}")
                                    else:
                                        print(f"      [~] {estado} | Score {score} | Descartado: {obj['nombre']}")

                                procesados.add(url_req)

                        await asyncio.sleep(random.uniform(config.TIEMPO_ESPERA_MIN, config.TIEMPO_ESPERA_MAX))

                    pagina += 1

                await context.close()

        await browser.close()
        print(f"\n[✓] Terminado. run_id: {run_id}")


if __name__ == "__main__":
    # Ejemplo: ejecutar con ciudades específicas
    ciudades_ejemplo = [
        {"municipio": "bogota", "departamento": "Cundinamarca"}
    ]
    asyncio.run(main(ciudades=ciudades_ejemplo))