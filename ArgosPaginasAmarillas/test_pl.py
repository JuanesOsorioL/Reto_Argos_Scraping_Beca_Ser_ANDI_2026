from playwright.sync_api import sync_playwright
import time
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('https://www.paginasamarillas.com.co/medellin/servicios/materiales-para-construccion')
    time.sleep(3)
    with open('page_dump.html', 'w', encoding='utf-8') as f:
        f.write(page.content())
    browser.close()
