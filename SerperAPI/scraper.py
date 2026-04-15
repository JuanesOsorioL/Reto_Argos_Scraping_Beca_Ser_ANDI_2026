"""
═══════════════════════════════════════════════════════════════════════════════
scraper.py — Llamadas a Serper con manejo robusto de errores
═══════════════════════════════════════════════════════════════════════════════

Responsabilidades:
  ✓ Llamar a Serper API con reintento automático en 429
  ✓ Detectar y diferenciar errores:
      - 429: Rate limit o créditos agotados (reintentable)
      - 401/403: API key inválida (no reintentable)
      - 4xx/5xx: Otros errores
  ✓ Aplana respuesta de Serper en registros individuales
  ✓ Enriquece URLs visitando sitios web
  ✓ Calcula score Argos para filtrado de calidad
"""

import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

from config import (
    SERPER_API_KEY, SERPER_URL, REQUEST_TIMEOUT,
    USER_AGENT, MAX_WORKERS, ARGOS_SCORE_THRESHOLD,
)
from utils import (
    normalize_city, make_smart_hash,
    extract_emails, extract_phones, extract_whatsapp_links,
    extract_meta_description, find_contact_page,
    score_result, first_or_none,
)


# ═══════════════════════════════════════════════════════════════════════════════
# EXCEPCIONES PERSONALIZADAS
# ═══════════════════════════════════════════════════════════════════════════════

class SerperRateLimitError(Exception):
    """
    ❌ Serper devolvió 429: Rate limit alcanzado o créditos agotados
    
    Acciones recomendadas:
      - Esperar RATE_LIMIT_SLEEP_SECONDS
      - Reintentar la query
      - Si persiste, contactar a Serper o esperar próxima renovación
    """
    pass


class SerperAuthError(Exception):
    """
    ❌ Serper devolvió 401 o 403: API key inválida o acceso denegado
    
    Acciones recomendadas:
      - Verificar SERPER_API_KEY en .env
      - Verificar que la key tiene créditos
      - Obtener nueva key de https://serper.dev/
    """
    pass


class SerperApiError(Exception):
    """
    ❌ Serper devolvió otro error 4xx/5xx
    
    Acciones recomendadas:
      - Revisar logs
      - Reintentar después de un tiempo
      - Contactar a Serper si persiste
    """
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# SESIÓN HTTP REUTILIZABLE
# ═══════════════════════════════════════════════════════════════════════════════

# Crear sesión persistent para mejorar performance
session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
})


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL: LLAMAR A SERPER
# ═══════════════════════════════════════════════════════════════════════════════

def call_serper(query: str, page: int = 1) -> dict:
    """
    Llama a Serper API y maneja diferentes tipos de errores.
    
    Args:
        query (str): Búsqueda a realizar. Ejemplo: "ferreterías en Bogotá, Colombia"
        page (int): Página de resultados. Defecto: 1
    
    Returns:
        dict: Respuesta completa de Serper con structure:
            {
                "searchParameters": {...},
                "organic": [{...}, {...}],          # Resultados orgánicos
                "knowledgeGraph": {...},            # Panel de conocimiento
                "peopleAlsoAsk": [...],             # Preguntas relacionadas
                "relatedSearches": [...]            # Búsquedas relacionadas
            }
    
    Raises:
        SerperRateLimitError: Si Serper devuelve 429 (reintentable)
        SerperAuthError: Si Serper devuelve 401/403 (verificar API key)
        SerperApiError: Si Serper devuelve otro error
    
    Ejemplo:
        >>> response = call_serper("ferreterías en Bogotá, Colombia", page=1)
        >>> len(response["organic"])  # Cantidad de resultados orgánicos
        10
    """
    
    # Encabezados HTTP para la llamada
    headers = {
        "X-API-KEY": SERPER_API_KEY,  # Tu API key
        "Content-Type": "application/json"
    }
    
    # Payload (cuerpo de la solicitud)
    payload = {
        "q": query,           # La búsqueda
        "gl": "co",          # País: Colombia
        "hl": "es",          # Idioma: Español
        "page": page         # Página de resultados
    }
    
    try:
        # ─── LLAMADA HTTP A SERPER ───────────────────────────────────────────
        resp = requests.post(
            SERPER_URL,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT  # Timeout de 20s
        )
        # ──────────────────────────────────────────────────────────────────────
        
        # ─── MANEJO DE CÓDIGOS DE ESTADO ──────────────────────────────────────
        
        if resp.status_code == 429:
            # ⚠️ RATE LIMIT: Serper alcanzó el límite de requests
            # Típicamente significa:
            #   - Ya hiciste 100 requests en el último minuto (tier gratuito)
            #   - O se acabaron los créditos del plan
            raise SerperRateLimitError(
                "Serper devolvió 429: Rate limit o créditos agotados. "
                f"Respuesta: {resp.text[:200]}"
            )
        
        if resp.status_code in (401, 403):
            # ❌ AUTENTICACIÓN FALLIDA
            # Típicamente significa:
            #   - SERPER_API_KEY es inválida o expiró
            #   - La key no tiene créditos disponibles
            raise SerperAuthError(
                f"Serper devolvió {resp.status_code}: API key inválida o acceso denegado. "
                f"Verifica SERPER_API_KEY en .env"
            )
        
        if resp.status_code >= 400:
            # ⚠️ OTRO ERROR 4xx O 5xx
            # No sabemos exactamente qué pasó, reportar el error
            raise SerperApiError(
                f"Serper devolvió {resp.status_code}: {resp.text[:500]}"
            )
        
        # ──────────────────────────────────────────────────────────────────────
        
        # ✅ ÉXITO: Status 200, parsear JSON
        try:
            return resp.json()
        except Exception as e:
            raise SerperApiError(f"No se pudo parsear JSON de Serper: {e}")
    
    except requests.RequestException as e:
        # Error de red (timeout, conexión rechazada, etc)
        raise SerperApiError(f"Error de red llamando a Serper: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN AUXILIAR: SAFE GET (Visitar URLs con manejo de errores)
# ═══════════════════════════════════════════════════════════════════════════════

def safe_get(url: str) -> tuple:
    """
    Visita una URL de forma segura, sin romper el scraper si falla.
    
    Args:
        url (str): URL a visitar
    
    Returns:
        tuple: (html_content, final_url)
            - html_content (str): Contenido HTML si éxito, None si falla
            - final_url (str): URL final después de redirects
    
    Ejemplo:
        >>> html, final_url = safe_get("https://example.com/contact")
        >>> if html:
        ...     emails = extract_emails(html)
    """
    try:
        resp = session.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True  # Seguir redirects (301, 302, etc)
        )
        resp.raise_for_status()  # Levanta excepción si status >= 400
        
        # Verificar que es HTML (no PDF, imagen, etc)
        if "text/html" not in resp.headers.get("Content-Type", "").lower():
            return None, str(resp.url)
        
        return resp.text, str(resp.url)
    
    except Exception:
        # Silenciar errores: algunos sitios bloquean scrapers
        # Es mejor perder una URL que romper todo el scraper
        return None, None


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL: ENRIQUECER URL
# ═══════════════════════════════════════════════════════════════════════════════

def enrich_url(url: str) -> dict:
    """
    Visita una URL y extrae información de contacto.
    
    Extrae:
      - Emails (usando regex)
      - Teléfonos (usando regex)
      - Links de WhatsApp
      - Meta descripción
      - Si no encuentra nada, intenta página /contacto o /contact
    
    Args:
        url (str): URL a visitar
    
    Returns:
        dict: Diccionario con:
            {
                "scraped_email": "info@example.com" o None,
                "scraped_phone": "123456789" o None,
                "scraped_whatsapp": "https://wa.me/..." o None,
                "telefonos_adicionales": "111|222|333" o None,
                "meta_description": "Descripción del sitio",
                "is_enriched": True si encontró algo,
                "contact_page_url": URL de página de contacto
            }
    
    Ejemplo:
        >>> enrich = enrich_url("https://ferreteria.com")
        >>> enrich["scraped_phone"]  # "3001234567"
        >>> enrich["is_enriched"]    # True
    """
    
    # Template inicial: todos los campos en None
    result = {
        "scraped_email": None,
        "scraped_phone": None,
        "scraped_whatsapp": None,
        "telefonos_adicionales": None,
        "meta_description": None,
        "is_enriched": False,
        "contact_page_url": None,
    }
    
    if not url:
        return result
    
    # ─── OBTENER HTML ───────────────────────────────────────────────────────
    html, final_url = safe_get(url)
    if not html:
        return result
    
    # ─── EXTRAER DATOS DEL HTML ─────────────────────────────────────────────
    emails    = extract_emails(html)      # Lista de emails
    phones    = extract_phones(html)      # Lista de teléfonos
    whatsapps = extract_whatsapp_links(html)  # Lista de links WhatsApp
    meta_desc = extract_meta_description(html)  # Meta descripción
    
    # ─── SI NO ENCONTRÓ DATOS, INTENTAR PÁGINA DE CONTACTO ──────────────────
    if not emails and not phones and not whatsapps:
        # Buscar enlace a página de contacto (ej: /contacto, /contact)
        contact_url = find_contact_page(final_url or url, html)
        
        if contact_url:
            # Visitar la página de contacto
            contact_html, _ = safe_get(contact_url)
            
            if contact_html:
                result["contact_page_url"] = contact_url
                
                # Extraer datos de la página de contacto
                emails    = extract_emails(contact_html) or emails
                phones    = extract_phones(contact_html) or phones
                whatsapps = extract_whatsapp_links(contact_html) or whatsapps
                meta_desc = meta_desc or extract_meta_description(contact_html)
    
    # ─── GUARDAR RESULTADOS ─────────────────────────────────────────────────
    
    # El primer email encontrado
    result["scraped_email"] = first_or_none(emails)
    
    # El primer teléfono encontrado
    result["scraped_phone"] = first_or_none(phones)
    
    # El primer link de WhatsApp encontrado
    result["scraped_whatsapp"] = first_or_none(whatsapps)
    
    # Teléfonos adicionales (del segundo en adelante, separados por |)
    result["telefonos_adicionales"] = " | ".join(phones[1:]) if len(phones) > 1 else None
    
    # Meta descripción
    result["meta_description"] = meta_desc
    
    # Marcar como "enriquecido" si encontró al menos algo
    result["is_enriched"] = any([
        result["scraped_email"],
        result["scraped_phone"],
        result["scraped_whatsapp"],
        result["meta_description"]
    ])
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN: EXTRAER TELÉFONO DEL KNOWLEDGE GRAPH
# ═══════════════════════════════════════════════════════════════════════════════

def extraer_telefono_kg(kg: dict) -> str:
    """
    Extrae teléfono del panel de Knowledge Graph de Google.
    
    El Knowledge Graph es ese panel a la derecha en Google que muestra
    info empresarial (teléfono, dirección, horarios, etc).
    
    Args:
        kg (dict): Diccionario del Knowledge Graph
    
    Returns:
        str: Teléfono si lo encontró, None en otro caso
    
    Ejemplo:
        >>> kg = response["knowledgeGraph"]
        >>> phone = extraer_telefono_kg(kg)  # "3001234567"
    """
    if not kg:
        return None
    
    # El KG tiene estructura: {"attributes": {"Teléfono": "3001234567", ...}}
    attrs = kg.get("attributes", {})
    
    # Probar diferentes nombres de atributo (inglés, español, etc)
    for key in ["Teléfono", "Telefono", "Phone", "Sales", "Llámanos"]:
        if key in attrs:
            return attrs[key]
    
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN: CONSTRUIR REGISTRO BASE (Template)
# ═══════════════════════════════════════════════════════════════════════════════

def _base_registro(run_id, consulta_id, now, fecha_act, meta_query,
                   search_parameters, knowledge_graph, people_also_ask,
                   related_searches) -> dict:
    """
    Crea un diccionario "template" con todos los campos de un resultado.
    
    Todos los campos inicialmente en None, se llenan después según el tipo
    de resultado (organic, knowledgeGraph, etc).
    
    Args:
        run_id (str): UUID de la ejecución actual
        consulta_id (int): ID de la consulta en PostgreSQL
        now (datetime): Timestamp actual
        fecha_act (datetime): Fecha de actualización
        meta_query (dict): Metadata de la query {"keyword", "ciudad", "query"}
        search_parameters (dict): Parámetros de búsqueda de Serper
        knowledge_graph (dict): Panel Knowledge Graph de Google
        people_also_ask (list): Preguntas relacionadas
        related_searches (list): Búsquedas relacionadas
    
    Returns:
        dict: Registro con todos los campos (None por defecto)
    """
    municipio    = normalize_city(meta_query["ciudad"])
    departamento = meta_query["departamento"]
    query_text   = meta_query["query"]
    keyword      = meta_query["keyword"]
    
    return {
        # ─── IDENTIFICADORES ───────────────────────────────────────────────
        "run_id":             run_id,              # UUID de la ejecución
        "consulta_id":        consulta_id,         # ID de la consulta en DB
        "hash_id":            None,                # Se llena después (deduplicación)
        "fecha_extraccion":   now,                 # Timestamp de ahora
        
        # ─── DATOS PRINCIPALES (Argos) ─────────────────────────────────────
        "nit":                None,                # Número de identificación
        "nombre":             None,                # Nombre del negocio
        "departamento":       departamento,        # Departamento (pre-llenado)
        "municipio":          municipio,           # Ciudad (pre-llenada)
        "direccion":          None,                # Dirección física
        "latitud":            None,                # Coordenada geográfica
        "longitud":           None,                # Coordenada geográfica
        "telefono":           None,                # Teléfono principal
        "whatsapp":           None,                # Link de WhatsApp
        "correo_electronico": None,                # Email principal
        "fecha_actualizacion": fecha_act,          # Cuándo se actualizó
        "fuente":             "serper",            # Siempre "serper"
        
        # ─── DATOS ADICIONALES DE CALIDAD ──────────────────────────────────
        "telefonos_adicionales": None,             # Teléfonos extra (1|2|3)
        "descripcion":        None,                # Descripción del negocio
        "categoria_busqueda": None,                # organic / knowledgeGraph
        "keyword_busqueda":   keyword,             # Keyword original
        "url":                None,                # URL del sitio
        "score":              None,                # Score Argos (0-10+)
        "aprobado_argos":     None,                # True si score >= threshold
        
        # ─── METADATOS DE SERPER ───────────────────────────────────────────
        "result_type":        None,                # organic / knowledgeGraph
        "position":           None,                # Posición en results
        "title":              None,                # Título de la búsqueda
        "snippet":            None,                # Snippet/resumen
        "link":               None,                # Link del resultado
        "display_query":      query_text,          # Query original
        "ciudad_busqueda":    municipio,           # Ciudad (repetido)
        "pais_busqueda":      "Colombia",          # País fijo
        
        # ─── DATOS DE ENRIQUECIMIENTO (Visita a URL) ────────────────────────
        "scraped_email":      None,                # Email extraído del sitio
        "scraped_phone":      None,                # Teléfono del sitio
        "scraped_whatsapp":   None,                # WhatsApp del sitio
        "meta_description":   None,                # Meta description del sitio
        "is_enriched":        False,               # ¿Se enriqueció?
        "contact_page_url":   None,                # URL de página de contacto
        
        # ─── RAW JSON (Se guardan intactos para futuro análisis) ────────────
        "raw_item":           None,                # Item crudo individual
        "raw_search_parameters": search_parameters,  # Parámetros de búsqueda
        "raw_knowledge_graph":   knowledge_graph if knowledge_graph else None,
        "raw_people_also_ask":   people_also_ask,   # Preguntas relacionadas
        "raw_related_searches":  related_searches,  # Búsquedas relacionadas
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL: APLANA RESPUESTA DE SERPER
# ═══════════════════════════════════════════════════════════════════════════════

def flatten_response(run_id: str, consulta_id: int,
                     meta_query: dict, response_json: dict) -> list:
    """
    Convierte la respuesta de Serper en una lista de registros individuales.
    
    Serper devuelve:
      {
        "organic": [{result1}, {result2}, ...],    # Resultados web
        "knowledgeGraph": {empresa_info},          # Panel de datos
        "peopleAlsoAsk": [...],                    # Preguntas (NO se guardan como filas)
        "relatedSearches": [...]                   # Búsquedas (NO se guardan como filas)
      }
    
    Esta función genera UNA FILA por:
      - Knowledge Graph (si existe)
      - Cada resultado orgánico
    
    peopleAlsoAsk y relatedSearches se guardan solo en raw JSON.
    
    Args:
        run_id (str): UUID de ejecución
        consulta_id (int): ID de query en DB
        meta_query (dict): {"keyword", "ciudad", "departamento", "query"}
        response_json (dict): Respuesta completa de Serper
    
    Returns:
        list: Lista de registros (dicts) listos para insertar en DB
    
    Ejemplo:
        >>> registros = flatten_response(run_id, consulta_id, meta_query, response)
        >>> len(registros)  # Típicamente 10 (1 KG + 9 orgánicos)
    """
    registros = []
    now       = datetime.now(timezone.utc)
    fecha_act = now
    
    # Extraer componentes de la respuesta
    search_parameters = response_json.get("searchParameters", {})
    knowledge_graph   = response_json.get("knowledgeGraph", {})
    people_also_ask   = response_json.get("peopleAlsoAsk", [])
    related_searches  = response_json.get("relatedSearches", [])
    municipio         = normalize_city(meta_query["ciudad"])
    
    # ─── PROCESAR KNOWLEDGE GRAPH (Si existe) ────────────────────────────────
    if knowledge_graph:
        nombre   = knowledge_graph.get("title")           # Nombre del lugar
        url      = knowledge_graph.get("website") or \
                   knowledge_graph.get("descriptionLink")  # URL del sitio
        descripcion = knowledge_graph.get("description")  # Descripción
        telefono = extraer_telefono_kg(knowledge_graph)   # Teléfono
        
        # Crear registro base
        reg = _base_registro(run_id, consulta_id, now, fecha_act,
                              meta_query, search_parameters, knowledge_graph,
                              people_also_ask, related_searches)
        
        # Llenar campos específicos del Knowledge Graph
        reg.update({
            "hash_id":          make_smart_hash("knowledgeGraph", nombre, url, municipio),
            "nombre":           nombre,
            "telefono":         telefono,
            "descripcion":      descripcion,
            "categoria_busqueda": "knowledge_graph",
            "url":              url,
            "result_type":      "knowledgeGraph",
            "position":         0,                # KG es siempre posición 0
            "title":            nombre,
            "snippet":          descripcion,
            "link":             url,
            "raw_item":         knowledge_graph,
        })
        registros.append(reg)
    
    # ─── PROCESAR RESULTADOS ORGÁNICOS ─────────────────────────────────────
    # Cada resultado en la búsqueda web genera un registro
    for item in response_json.get("organic", []):
        title    = item.get("title")        # Título del resultado
        link     = item.get("link")         # URL
        snippet  = item.get("snippet")      # Resumen
        position = item.get("position")     # Posición (1, 2, 3, ...)
        
        # Crear registro base
        reg = _base_registro(run_id, consulta_id, now, fecha_act,
                              meta_query, search_parameters, knowledge_graph,
                              people_also_ask, related_searches)
        
        # Llenar campos específicos del resultado orgánico
        reg.update({
            "hash_id":          make_smart_hash("organic", title, link, municipio),
            "nombre":           title,          # Nombre = título
            "descripcion":      snippet,        # Descripción = snippet
            "categoria_busqueda": "organic",
            "url":              link,
            "result_type":      "organic",
            "position":         position,
            "title":            title,
            "snippet":          snippet,
            "link":             link,
            "raw_item":         item,
        })
        registros.append(reg)
    
    # Nota: peopleAlsoAsk y relatedSearches NO se guardan como filas
    # porque no son negocios — solo son sugerencias de Google
    # Pero SÍ se guardan en raw_people_also_ask y raw_related_searches
    # de cada registro para futuro análisis
    
    return registros


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL: ENRIQUECE REGISTROS EN PARALELO
# ═══════════════════════════════════════════════════════════════════════════════

def enrich_records(records: list) -> list:
    """
    Visita las URLs de los registros en paralelo para extraer contacto.
    
    Para cada registro de tipo "organic" o "knowledgeGraph":
      1. Visita la URL
      2. Extrae emails, teléfonos, WhatsApp, meta description
      3. Si no encontró nada, busca página de contacto
      4. Calcula score Argos para filtrado
    
    Usa ThreadPoolExecutor para procesar múltiples URLs simultáneamente.
    
    Args:
        records (list): Lista de registros sin enriquecer
    
    Returns:
        list: Los mismos registros con campos enriquecidos
              (scraped_email, scraped_phone, score, aprobado_argos, etc)
    
    Nota: La función modifica los registros in-place.
    """
    
    # ─── FILTRAR CANDIDATOS PARA ENRIQUECIMIENTO ───────────────────────────
    # Solo intentar enriquecer registros que tengan URL
    candidates = [r for r in records
                  if r.get("result_type") in ("organic", "knowledgeGraph")
                  and r.get("url")]
    
    # ─── PROCESAR URLS EN PARALELO ─────────────────────────────────────────
    # Crear un pool de workers (MAX_WORKERS = 8 por defecto)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Enviar todos los trabajos
        future_map = {
            executor.submit(enrich_url, r["url"]): r
            for r in candidates
        }
        
        # Recolectar resultados conforme se completan
        for future in as_completed(future_map):
            record   = future_map[future]
            
            try:
                # Obtener resultado del enriquecimiento
                enriched = future.result()
            except Exception:
                # Si algo falló, usar diccionario vacío (silenciar error)
                enriched = {}
            
            # ─── ACTUALIZAR CAMPOS DE ENRIQUECIMIENTO ──────────────────────
            record["scraped_email"]         = enriched.get("scraped_email")
            record["scraped_phone"]         = enriched.get("scraped_phone")
            record["scraped_whatsapp"]      = enriched.get("scraped_whatsapp")
            record["meta_description"]      = enriched.get("meta_description")
            record["is_enriched"]           = enriched.get("is_enriched", False)
            record["contact_page_url"]      = enriched.get("contact_page_url")
            record["telefonos_adicionales"] = enriched.get("telefonos_adicionales")
            
            # ─── PROPAGAR A COLUMNAS ARGOS ─────────────────────────────────
            # Si el scraper encontró datos pero no estaban en el campo Argos,
            # copiar los datos extraídos (prioridad: mejor algo que nada)
            if enriched.get("scraped_phone") and not record.get("telefono"):
                record["telefono"]           = enriched["scraped_phone"]
            
            if enriched.get("scraped_whatsapp") and not record.get("whatsapp"):
                record["whatsapp"]           = enriched["scraped_whatsapp"]
            
            if enriched.get("scraped_email") and not record.get("correo_electronico"):
                record["correo_electronico"] = enriched["scraped_email"]
    
    # ─── CALCULAR SCORE ARGOS PARA TODOS ───────────────────────────────────
    # Ahora que todos los datos están, calcular score y aprobación
    for record in records:
        # score_result analiza título, snippet, descripción, URL
        # y suma puntos según relevancia
        s = score_result(
            title=record.get("title"),
            snippet=record.get("snippet"),
            meta_description=record.get("meta_description"),
            query=record.get("display_query"),
            url=record.get("url"),
        )
        
        # Guardar score
        record["score"]         = s
        
        # Marcar como aprobado si supera el threshold
        record["aprobado_argos"] = s >= ARGOS_SCORE_THRESHOLD
    
    return records
