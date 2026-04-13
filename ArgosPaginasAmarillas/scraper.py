import asyncio
import json
from playwright.async_api import Page

async def obtener_urls_de_listado(page: Page, ciudad: str, keyword: str, pagina: int):
    """
    Navega al listado y extrae todas las URLs de los detalles.
    Retorna una lista de URLs. Retorna una lista vacía si no hay resultados o si es la última página.
    """
    url = f"https://www.paginasamarillas.com.co/{ciudad}/servicios/{keyword}"
    if pagina > 1:
        url += f"?page={pagina}"
        
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"Error navegando a listado: {e}")
        return []
    
    # Verificamos si hay elementos o si la página dice que no hay resultados.
    # Timeout de 20s para tolerar internet lento (Bug #1 fix).
    # Si falla una vez, esperamos 3s adicionales y reintentamos antes de rendirse.
    selector_ok = False
    for intento in range(2):
        try:
            await page.wait_for_selector("a[href*='/empresas/']", timeout=20000)
            selector_ok = True
            break
        except:
            if intento == 0:
                # Primer intento fallido: esperar y reintentar
                await page.wait_for_timeout(3000)
            else:
                # Segundo intento fallido: no hay resultados reales
                return []
    
    if not selector_ok:
        return []

    enlaces = []
    cards = await page.query_selector_all("a[href*='/empresas/']")
    for elemento_a in cards:
        href = await elemento_a.get_attribute("href")
        if href:
            if not href.startswith("http"):
                href = "https://www.paginasamarillas.com.co" + href
            if href not in enlaces: # Evitar hrefs duplicados en la misma card
                enlaces.append(href)
                
    return enlaces

async def extraer_detalle_negocio(page: Page, url: str):
    """
    Entra a la URL de detalle y extrae la información profunda desde el objeto __NEXT_DATA__.
    Devuelve siempre una lista de diccionarios (cada sucursal es un registro).
    """
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"  Error cargando detalle {url}: {e}")
        return []
    
    # Extraemos el JSON crudo inyectado en el DOM
    next_data_content = await page.evaluate('''() => {
        const el = document.getElementById('__NEXT_DATA__');
        return el ? el.textContent : null;
    }''')
    
    if not next_data_content:
        # Fallback de seguridad si no está construido en nextjs o falló la carga
        return []
        
    try:
        data_json = json.loads(next_data_content)
        data = data_json.get('props', {}).get('pageProps', {}).get('data', {})
        if not data:
            return []
    except:
        return []
        
    # Datos generales del negocio
    nombre_empresa = data.get('name', 'SIN NOMBRE')
    slogan = data.get('slogan', '')
    info_empresa = data.get('infoEmpresa', '')
    descripcion_completa = f"{slogan} {info_empresa}".strip()
    emails = " / ".join(data.get('emails', []))
    
    # WhatsApp oficial (contactMap)
    whatsapp = ""
    contact_map = data.get('contactMap') or {}
    wa_list = contact_map.get('WHATSAPP', [])
    if wa_list:
        whatsapp = wa_list[0]
        
    sucursales_encontradas = []
    
    # Localizamos todas las direcciones
    all_addresses = data.get('allAddresses', [])
    if not all_addresses and data.get('mainAddress'):
        all_addresses = [data.get('mainAddress')]
        
    for branch in all_addresses:
        sucursal_nombre = branch.get('mainAddressName') or branch.get('addressLocality') or "Principal"
        
        # Dirección
        direccion = branch.get('streetName', '')
        if branch.get('streetNumber'):
            direccion += f" {branch.get('streetNumber')}"
            
        latitud = branch.get('latitude', '')
        longitud = branch.get('longitude', '')
        
        # Teléfonos (intentar arrays posibles)
        tels = branch.get('allPhonesList', []) or branch.get('allPhones', []) or branch.get('phones', [])
        tels_str = " / ".join([t.get('phoneToShow', t.get('number', '')) for t in tels])
        
        # Si la sucursal no tiene teléfono asignado, heredamos el principal
        if not tels_str and data.get('mainPhone'):
            tels_str = data.get('mainPhone', {}).get('phoneToShow', '')
            
        # Generar URL única si quisieramos rastrear la sucursal
        # Pero usamos la misma base
        
        direccion_limpia = direccion.strip()

        # Filtrar sucursales virtuales de PA — son registros como
        # "Atiende en Medellín desde su sede principal en Bogotá"
        # No son ferreterías reales en esa ciudad, son ruido.
        if direccion_limpia.lower().startswith("atiende en"):
            continue

        sucursales_encontradas.append({
            "nombre": nombre_empresa,
            "sucursal_tipo": sucursal_nombre,
            "direccion": direccion_limpia,
            "latitud": latitud,
            "longitud": longitud,
            "telefono": tels_str,
            "whatsapp": whatsapp,
            "email": emails,
            "descripcion": descripcion_completa,
            "url": url,
            "fuente": "paginas_amarillas"
        })
        
    return sucursales_encontradas