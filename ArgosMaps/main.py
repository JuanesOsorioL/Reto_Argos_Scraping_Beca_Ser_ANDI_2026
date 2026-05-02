"""
main.py — Scraper Google Maps para Argos
Cambios vs versión original:
  - Guarda en PostgreSQL (raw.google_maps_ferreterias) además del .jsonl local
  - Agrega ciudad, departamento, run_id, fecha_extraccion, keyword_busqueda, hash_id
  - Caché de URLs ya procesadas viene de la BD (no solo del .jsonl)
  - Deduplicación por hash_id (MD5 de la URL normalizada)
"""

import asyncio
import json
import random
import re
import uuid
import hashlib
from datetime import datetime, timezone

from playwright.async_api import async_playwright, Page, BrowserContext, Response

from config import (
    CIUDAD_DEPARTAMENTO, KEYWORDS_BUSQUEDA,  # ✅ Sin CIUDADES
    MAX_CONCURRENT_TABS, MIN_DELAY_SECONDS, MAX_DELAY_SECONDS,
    HEADLESS, OUTPUT_FILE, GUARDAR_JSONL_LOCAL, BROWSER_RESTART_EVERY
)
from filter_engine import calcular_score_argos
from db import init_db, cargar_urls_procesadas, insertar_negocio





# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def normalizar_url(url: str) -> str:
    if not url:
        return ""
    return url.split('?')[0]


def generar_hash(url: str) -> str:
    """MD5 de la URL normalizada — llave de deduplicación."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def deducir_whatsapp(telefono_str: str) -> tuple:
    if not telefono_str:
        return "", ""
    phone = re.sub(r'[^\d+]', '', telefono_str)
    whatsapp = ""
    local_phone = phone.replace("+57", "")
    if local_phone.startswith('3') and len(local_phone) == 10:
        whatsapp = phone if phone.startswith('+') else f"+57{local_phone}"
    return phone, whatsapp


def guardar_jsonl_local(datos: dict):
    """Respaldo local en .jsonl — útil para debugging y exportar a Excel."""
    datos_serializables = {
        k: v.isoformat() if hasattr(v, 'isoformat') else v
        for k, v in datos.items()
    }
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(datos_serializables, ensure_ascii=False) + '\n')


async def human_pause():
    delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
    await asyncio.sleep(delay)


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACCIÓN DE URLs — SCROLL ADAPTATIVO + INTERCEPCIÓN DE RED
# ─────────────────────────────────────────────────────────────────────────────

async def extraer_urls_busqueda(page: Page, ciudad: str, keyword: str) -> list:
    query       = f"{keyword} en {ciudad}"
    url_busqueda = f"https://www.google.com/maps/search/{query.replace(' ', '+')}/"
    urls_de_red = set()

    async def capturar_respuesta(response: Response):
        try:
            if "maps/search" in response.url and response.status == 200:
                body      = await response.text()
                encontrados = re.findall(r'https://www\.google\.com/maps/place/[^\\"\']+', body)
                for href in encontrados:
                    norm = normalizar_url(href)
                    if "/maps/place/" in norm:
                        urls_de_red.add(norm)
        except Exception:
            pass

    page.on("response", capturar_respuesta)
    await page.goto(url_busqueda, wait_until="domcontentloaded")

    try:
        await page.click('button:has-text("Aceptar todo")', timeout=2500)
        await asyncio.sleep(0.5)
    except Exception:
        pass

    try:
        await page.wait_for_selector('div[role="feed"]', state="attached", timeout=20000)
    except Exception:
        print(f"    [-] Timeout: panel lateral no cargó para '{query}'.")
        page.remove_listener("response", capturar_respuesta)
        return []

    urls_de_scroll       = set()
    intentos_sin_nuevos  = 0
    MAX_INTENTOS_SIN_NUEVOS = 3
    MAX_SCROLLS_TOTAL    = 40
    ESPERA_BASE          = 2.0
    EXTRA_ESPERA         = 1.5

    for num_scroll in range(MAX_SCROLLS_TOTAL):
        elements = await page.query_selector_all('a[href*="/maps/place/"]')
        nuevas   = 0
        for el in elements:
            href = await el.get_attribute('href')
            if href:
                norm = normalizar_url(href)
                if norm and norm not in urls_de_scroll:
                    urls_de_scroll.add(norm)
                    nuevas += 1

        try:
            fin = await page.query_selector('span.HlvSq')
            if fin:
                texto = await fin.inner_text()
                if "final" in texto.lower() or "end of" in texto.lower():
                    print(f"    [✓] Fin de lista en scroll #{num_scroll + 1}.")
                    break
        except Exception:
            pass

        if nuevas == 0:
            intentos_sin_nuevos += 1
            if intentos_sin_nuevos >= MAX_INTENTOS_SIN_NUEVOS:
                print(f"    [→] Sin nuevos en {MAX_INTENTOS_SIN_NUEVOS} scrolls. Finalizando.")
                break
            await asyncio.sleep(EXTRA_ESPERA)
        else:
            intentos_sin_nuevos = 0
            print(f"       Scroll #{num_scroll + 1}: +{nuevas} URLs nuevas (Total DOM: {len(urls_de_scroll)})")

        try:
            await page.hover('div[role="feed"]')
            await page.mouse.wheel(0, 2500)
        except Exception:
            pass

        await asyncio.sleep(ESPERA_BASE + EXTRA_ESPERA)

    page.remove_listener("response", capturar_respuesta)
    todas = urls_de_scroll.union(urls_de_red)
    print(f"    [→] DOM: {len(urls_de_scroll)} | Red: {len(urls_de_red)} | TOTAL: {len(todas)}")
    return list(todas)


# ─────────────────────────────────────────────────────────────────────────────
# PROCESAMIENTO DE CADA LUGAR INDIVIDUAL
# ─────────────────────────────────────────────────────────────────────────────

async def procesar_lugar(
    context: BrowserContext,
    url: str,
    keyword: str,
    ciudad: str,
    run_id: str,
    fecha_extraccion: datetime,
):
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector('h1.DUwDvf', timeout=12000)
        except Exception:
            pass

        nombre      = ""
        categorias  = []
        direccion   = ""
        latitud     = 0.0
        longitud    = 0.0
        telefono_raw = ""

        # Coordenadas desde URL final
        url_final = page.url
        match = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url_final)
        if match:
            latitud, longitud = float(match.group(1)), float(match.group(2))
        else:
            match2 = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url_final)
            if match2:
                latitud, longitud = float(match2.group(1)), float(match2.group(2))

        # Nombre
        try:
            el = await page.query_selector('h1.DUwDvf')
            if el:
                nombre = (await el.inner_text()).strip()
        except Exception:
            pass
        if not nombre:
            try:
                nombre = (await page.title()).replace(" - Google Maps", "").strip()
            except Exception:
                pass

        # Categoría — 4 estrategias en cascada
        try:
            cat_el = await page.query_selector('button[jsaction="pane.rating.category"]')
            if not cat_el:
                cat_el = await page.query_selector('span.mgr77e')
            if not cat_el:
                cat_el = await page.query_selector('div.skqShb')
            if not cat_el:
                cat_el = await page.query_selector('[aria-label*="Categoría"], [aria-label*="category"]')
            if cat_el:
                cat_text = (await cat_el.inner_text()).strip()
                if cat_text:
                    categorias.append(cat_text)
        except Exception:
            pass

        # Teléfono
        try:
            btn = await page.query_selector('button[data-tooltip*="teléfono"], button[data-item-id*="phone"]')
            if btn:
                telefono_raw = await btn.get_attribute('aria-label') or ""
                if ":" in telefono_raw:
                    telefono_raw = telefono_raw.split(":")[-1].strip()
        except Exception:
            pass

        # Dirección
        try:
            btn = await page.query_selector('button[data-tooltip*="dirección"], button[data-item-id*="address"]')
            if btn:
                direccion = await btn.get_attribute('aria-label') or ""
                if ":" in direccion:
                    direccion = direccion.split(":")[-1].strip()
        except Exception:
            pass

        telefono, whatsapp = deducir_whatsapp(telefono_raw)
        score, aprobado    = calcular_score_argos(nombre, categorias, keyword)
        departamento       = CIUDAD_DEPARTAMENTO.get(ciudad, "")
        hash_id            = generar_hash(url)

        datos = {
            # ── Trazabilidad ──────────────────────────────────────────────
            "hash_id":              hash_id,
            "run_id":               run_id,
            "fecha_extraccion":     fecha_extraccion,

            # ── Columnas requeridas por Argos ─────────────────────────────
            "nit":                  "",
            "nombre":               nombre,
            "departamento":         departamento,
            "municipio":            ciudad,
            "direccion":            direccion,
            "latitud":              latitud,
            "longitud":             longitud,
            "telefono":             telefono,
            "whatsapp":             whatsapp,
            "correo_electronico":   "",
            "fecha_actualizacion":  fecha_extraccion,
            "fuente":               "google_maps",

            # ── Columnas adicionales de calidad ───────────────────────────
            "sucursal_tipo":        "Principal",
            "categorias_maps":      categorias,
            "descripcion":          "",
            "keyword_busqueda":     keyword,
            "url":                  url,
            "score":                score,
            "aprobado_argos":       aprobado,
        }

        # Guardar en PostgreSQL (fuente de verdad)
        insertado = insertar_negocio(datos)


        

        # Guardar también en .jsonl local como respaldo, solo si está habilitado
        if GUARDAR_JSONL_LOCAL and insertado:
            print(GUARDAR_JSONL_LOCAL)
            print(insertado)
            guardar_jsonl_local(datos)

        estado = "NUEVO" if insertado else "DUPLICADO"
        print(
            f"    [{estado}] {nombre} | {ciudad} | "
            f"Score: {score} | WA: {'✔️' if whatsapp else '❌'} | "
            f"Cat: {', '.join(categorias) or 'N/A'}"
        )

    except Exception as e:
        print(f"    [-] Error procesando {url} → {e}")
    finally:
        await page.close()


# ─────────────────────────────────────────────────────────────────────────────
# ORQUESTADOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3] });
    Object.defineProperty(navigator, 'languages', { get: () => ['es-CO', 'es', 'en-US'] });
    window.chrome = { runtime: {} };
"""


async def crear_browser_context(p):
    """Lanza un browser limpio y devuelve (browser, context). Llamar también para reiniciar."""
    browser = await p.chromium.launch(
        headless=HEADLESS,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
        ]
    )
    context = await browser.new_context(
        locale="es-CO",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    await context.add_init_script(STEALTH_SCRIPT)
    return browser, context


async def do_scrape(ciudades: list, keywords: list = None):
    """
    Scraper Google Maps con ciudades OBLIGATORIAS.

    Args:
        ciudades: list[dict] — REQUERIDO
                  Ej: [{"municipio": "cali", "departamento": "Valle del Cauca"}, ...]
        keywords: list[str] — OPCIONAL. Si None, usa KEYWORDS_BUSQUEDA de config.py.
    """
    
    # ✅ VALIDACIÓN OBLIGATORIA
    if not ciudades:
        raise ValueError(
            "❌ CIUDADES REQUERIDAS EN PARÁMETRO. "
            "api_runner.py debe enviar lista de ciudades en do_scrape(ciudades=[...])"
        )
    
    if not isinstance(ciudades, list):
        raise TypeError(f"ciudades debe ser list, recibió {type(ciudades)}")
    
    # Validar estructura de cada ciudad
    for i, ciudad_obj in enumerate(ciudades):
        if not isinstance(ciudad_obj, dict):
            raise ValueError(f"Ciudad #{i} no es dict: {ciudad_obj}")
        if "municipio" not in ciudad_obj or "departamento" not in ciudad_obj:
            raise ValueError(
                f"Ciudad #{i} debe tener 'municipio' y 'departamento': {ciudad_obj}"
            )




    # Inicializar BD (crea tablas si no existen)
    init_db()

    # Caché desde la BD — no reprocesamos URLs ya guardadas
    procesados = cargar_urls_procesadas()
    print(f"[*] Caché BD: {len(procesados)} negocios ya guardados (serán saltados).")
    keywords_activas = keywords if keywords else KEYWORDS_BUSQUEDA
    print(f"[*] Keywords: {len(keywords_activas)} {'(recibidas en body)' if keywords else '(defaults config.py)'}")
    print(f"[*] Ciudades: {len(ciudades)} | Keywords: {len(keywords_activas)} | "
          f"Combinaciones: {len(ciudades) * len(keywords_activas)}\n")

    # run_id y timestamp únicos para esta ejecución completa
    run_id           = str(uuid.uuid4())
    fecha_extraccion = datetime.now(timezone.utc)
    print(f"[*] run_id: {run_id}")
    print(f"[*] Inicio: {fecha_extraccion.isoformat()}\n")

    # Construir lista plana de combos (keyword, ciudad_obj) para poder dividirla en lotes
    todos_los_combos = [
        (keyword, ciudad_obj)
        for keyword in keywords_activas
        for ciudad_obj in ciudades
    ]
    print(f"[*] Total combos: {len(todos_los_combos)} | Lote driver: {BROWSER_RESTART_EVERY}\n")

    for lote_inicio in range(0, len(todos_los_combos), BROWSER_RESTART_EVERY):
        lote_combos = todos_los_combos[lote_inicio:lote_inicio + BROWSER_RESTART_EVERY]
        lote_num    = lote_inicio // BROWSER_RESTART_EVERY + 1
        print(f"\n[♻] Iniciando driver Playwright — lote {lote_num} "
              f"(combos {lote_inicio + 1}–{lote_inicio + len(lote_combos)})...")

        # Cada iteración de este for lanza y mata un proceso Node.js nuevo,
        # liberando completamente el heap V8 acumulado.
        async with async_playwright() as p:
            browser, context = await crear_browser_context(p)
            try:
                for keyword, ciudad_obj in lote_combos:
                    ciudad = ciudad_obj["municipio"]
                    print(f"\n[*] Buscando: '{keyword}' en '{ciudad}'...")
                    page = await context.new_page()
                    try:
                        urls_encontradas = await extraer_urls_busqueda(page, ciudad, keyword)
                    except Exception as e:
                        print(f"    [-] Error en búsqueda: {e}")
                        urls_encontradas = []
                    finally:
                        await page.close()

                    urls_a_procesar = [u for u in urls_encontradas if u not in procesados]
                    print(f"    → {len(urls_encontradas)} totales | {len(urls_a_procesar)} nuevos.")

                    for i in range(0, len(urls_a_procesar), MAX_CONCURRENT_TABS):
                        lote  = urls_a_procesar[i:i + MAX_CONCURRENT_TABS]
                        tareas = [
                            procesar_lugar(context, url, keyword, ciudad, run_id, fecha_extraccion)
                            for url in lote
                        ]
                        await asyncio.gather(*tareas)
                        for url in lote:
                            procesados.add(url)
                        await human_pause()
            finally:
                await context.close()
                await browser.close()

        print(f"[♻] Driver liberado — lote {lote_num} completado.")

    print(f"\n[✓] Scraping completado. run_id: {run_id}")
    print(f"[✓] Datos guardados en PostgreSQL y en: {OUTPUT_FILE}")


if __name__ == "__main__":
    try:
        asyncio.run(do_scrape())
    except KeyboardInterrupt:
        print("\n[!] Detenido por el usuario. Todo el progreso ya fue guardado en la BD.")