import asyncio
import json
from playwright.async_api import async_playwright
from scraper import obtener_urls_de_listado, extraer_detalle_negocio
from filter_engine import evaluar_cliente_argos

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        urls = await obtener_urls_de_listado(page, "medellin", "materiales-para-construccion", 1)
        
        validos = [u for u in urls if "/empresas/" in u]
        print(f"[!] Se encontraron {len(validos)} URLs válidas en la página 1")
        
        for u in validos[:2]:
            det = await extraer_detalle_negocio(page, u)
            if det:
                aprobado, score = evaluar_cliente_argos(det["nombre"], det["descripcion"])
                det["score"] = score
                det["aprobado"] = aprobado
                print("\n====================")
                print(json.dumps(det, indent=2, ensure_ascii=False))
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
