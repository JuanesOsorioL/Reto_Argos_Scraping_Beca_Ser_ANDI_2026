import asyncio
import json
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        # Url from user's screenshot
        url = "https://www.paginasamarillas.com.co/empresas/ferreteria-la-87-sas/medellin-34016075?ad=80641545"
        await page.goto(url, wait_until="domcontentloaded")
        
        # Obtenemos el script con id __NEXT_DATA__
        next_data_content = await page.evaluate('''() => {
            const el = document.getElementById('__NEXT_DATA__');
            return el ? el.textContent : null;
        }''')
        
        if next_data_content:
            data = json.loads(next_data_content)
            with open("dump_next_data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("[+] Se encontró __NEXT_DATA__ y se guardó en dump_next_data.json")
        else:
            print("[-] No se encontró __NEXT_DATA__")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
