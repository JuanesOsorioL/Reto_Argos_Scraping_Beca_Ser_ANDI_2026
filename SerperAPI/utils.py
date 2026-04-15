"""
═══════════════════════════════════════════════════════════════════════════════
utils.py — Funciones auxiliares para extracción, normalización y scoring
═══════════════════════════════════════════════════════════════════════════════

Responsabilidades:
  ✓ Normalizar nombres de ciudades
  ✓ Crear hashes para deduplicación
  ✓ Extraer emails, teléfonos, WhatsApp de HTML
  ✓ Extraer meta descriptions
  ✓ Encontrar página de contacto
  ✓ Calcular score Argos para filtrado
"""

import re
import json
import hashlib
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup


# ═══════════════════════════════════════════════════════════════════════════════
# NORMALIZACIÓN DE CIUDADES
# ═══════════════════════════════════════════════════════════════════════════════

# Mapeo de ciudad (slug) → ciudad (nombre completo con acentos)
CITY_NORMALIZATION = {
    "bogota": "Bogotá",
    "medellin": "Medellín",
    "cucuta": "Cúcuta",
    "ibague": "Ibagué",
    "monteria": "Montería",
    "popayan": "Popayán",
    "quibdo": "Quibdó",
    "santa-marta": "Santa Marta",
    "riohacha": "Riohacha",
    "pasto": "Pasto",
    "manizales": "Manizales",
    "neiva": "Neiva",
    "villavicencio": "Villavicencio",
    "armenia": "Armenia",
    "valledupar": "Valledupar",
    "sincelejo": "Sincelejo",
    "barranquilla": "Barranquilla",
    "cartagena": "Cartagena",
    "bucaramanga": "Bucaramanga",
    "pereira": "Pereira",
    "tunja": "Tunja",
    "florencia": "Florencia",
    "yopal": "Yopal",
    "arauca": "Arauca",
    "zipaquira": "Zipaquirá",
    "fusagasuga": "Fusagasugá",
    "chiquinquira": "Chiquinquirá",
    "giron": "Girón",
    "ocana": "Ocaña",
    "calarca": "Calarcá",
    "bello": "Bello",
    "itagui": "Itagüí",
    "envigado": "Envigado",
    "sabaneta": "Sabaneta",
    "rionegro": "Rionegro",
    "soacha": "Soacha",
    "chia": "Chía",
    "cali": "Cali",
}


def normalize_city(city: str) -> str:
    """
    Normaliza el nombre de una ciudad (slug → nombre completo).
    
    Convierte:
      "bogota" → "Bogotá"
      "santa-marta" → "Santa Marta"
    
    Args:
        city (str): Nombre de ciudad (slug o nombre)
    
    Returns:
        str: Nombre normalizado con acentos y mayúsculas
    
    Ejemplo:
        >>> normalize_city("bogota")
        "Bogotá"
        >>> normalize_city("santa-marta")
        "Santa Marta"
    """
    if not city:
        return city
    
    city_key = city.strip().lower()
    
    # Si está en el mapeo, usar versión normalizada
    if city_key in CITY_NORMALIZATION:
        return CITY_NORMALIZATION[city_key]
    
    # Si no está, aplicar transformaciones básicas
    return city.replace("-", " ").strip().title()


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE HASH Y DEDUPLICACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

def get_domain(url: str) -> str:
    """
    Extrae el dominio de una URL.
    
    Args:
        url (str): URL completa
    
    Returns:
        str: Dominio sin "www." y en minúsculas
    
    Ejemplo:
        >>> get_domain("https://www.ferreteria.com/page")
        "ferreteria.com"
    """
    if not url:
        return ""
    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
        return domain
    except Exception:
        return ""


def make_hash(*parts) -> str:
    """
    Crea un hash SHA-256 a partir de múltiples partes.
    
    Sirve para deduplicación: dos registros con igual hash
    se consideran duplicados.
    
    Args:
        *parts: Strings a hashear (nombre, URL, ciudad, etc)
    
    Returns:
        str: Hash SHA-256 hexadecimal
    
    Ejemplo:
        >>> h1 = make_hash("Ferretería X", "ferreteria.com", "bogota")
        >>> h2 = make_hash("Ferretería X", "ferreteria.com", "bogota")
        >>> h1 == h2  # True (son duplicados)
    """
    # Convertir a minúsculas y juntar con separador
    base = "|".join([str(p or "").strip().lower() for p in parts])
    
    # Crear hash SHA-256
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def make_smart_hash(result_type: str, nombre: str, url: str, municipio: str) -> str:
    """
    Crea un hash inteligente para deduplicación de resultados Serper.
    
    Toma en cuenta:
      - result_type: organic o knowledgeGraph
      - nombre: del negocio
      - dominio: extraído de la URL
      - municipio: la ciudad
    
    Args:
        result_type (str): "organic" o "knowledgeGraph"
        nombre (str): Nombre del negocio
        url (str): URL del sitio
        municipio (str): Ciudad normalizada
    
    Returns:
        str: Hash SHA-256
    
    Ejemplo:
        >>> h = make_smart_hash("organic", "Ferretería X", 
        ...                     "https://ferreteria-x.com", "Bogotá")
    """
    domain = get_domain(url)
    return make_hash(result_type, nombre, domain, municipio)


# ═══════════════════════════════════════════════════════════════════════════════
# EXTRACCIÓN DE CONTACTO (Regex)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_emails(text: str) -> list:
    """
    Extrae todos los emails de un texto usando regex.
    
    Args:
        text (str): Texto HTML o plain text
    
    Returns:
        list: Lista de emails únicos (ordenados alfabéticamente)
    
    Ejemplo:
        >>> extract_emails("<a href='mailto:info@ferreteria.com'>")
        ["info@ferreteria.com"]
    """
    if not text:
        return []
    
    # Regex estándar para emails
    pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    
    # Encontrar todos los matches
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    
    # Eliminar duplicados y ordenar
    return sorted(set(matches))


def extract_whatsapp_links(html: str) -> list:
    """
    Extrae links de WhatsApp de un HTML.
    
    Busca patrones como:
      - https://wa.me/573001234567
      - https://api.whatsapp.com/send?phone=57...
      - https://web.whatsapp.com/...
    
    Args:
        html (str): Contenido HTML
    
    Returns:
        list: Lista de links WhatsApp únicos
    
    Ejemplo:
        >>> extract_whatsapp_links("<a href='https://wa.me/573001234567'>")
        ["https://wa.me/573001234567"]
    """
    if not html:
        return []
    
    # Regex para WhatsApp links
    pattern = r"https?://(?:wa\.me|api\.whatsapp\.com|web\.whatsapp\.com)[^\s\"'<>]+"
    
    matches = re.findall(pattern, html, flags=re.IGNORECASE)
    
    return sorted(set(matches))


def extract_phones(text: str) -> list:
    """
    Extrae teléfonos colombianos de un texto.
    
    Busca patrones como:
      - +57 300 1234567
      - (300) 1234567
      - 3001234567
      - 9876543
    
    Args:
        text (str): Texto HTML o plain
    
    Returns:
        list: Lista de teléfonos únicos (sin limpiar, como se encontraron)
    
    Ejemplo:
        >>> extract_phones("+57 300 1234567, (301) 9876543")
        ["+57 300 1234567", "(301) 9876543"]
    """
    if not text:
        return []
    
    # Regex flexible para teléfonos colombianos
    # +57, (xxx) xxx-xxxx, xxx-xxxx, etc
    pattern = r"(?:\+57\s?)?(?:\(?\d{3}\)?[\s\-]?)?\d{3}[\s\-]?\d{4,}"
    
    matches = re.findall(pattern, text)
    
    cleaned = []
    for item in matches:
        # Validar que tiene entre 7 y 13 dígitos
        digits = re.sub(r"\D", "", item)
        if 7 <= len(digits) <= 13:
            cleaned.append(item.strip())
    
    return sorted(set(cleaned))


def extract_meta_description(html: str) -> str:
    """
    Extrae la meta descripción de una página HTML.
    
    Busca:
      1. <meta name="description" content="...">
      2. <meta property="og:description" content="...">
    
    Args:
        html (str): Contenido HTML de la página
    
    Returns:
        str: Meta description si la encuentra, string vacío en otro caso
    
    Ejemplo:
        >>> html = '<meta name="description" content="Ferretería online">'
        >>> extract_meta_description(html)
        "Ferretería online"
    """
    if not html:
        return ""
    
    try:
        # Parsear HTML
        soup = BeautifulSoup(html, "lxml")
        
        # Buscar meta description
        tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        if tag and tag.get("content"):
            return tag["content"].strip()
        
        # Buscar og:description
        tag = soup.find("meta", attrs={"property": re.compile("og:description", re.I)})
        if tag and tag.get("content"):
            return tag["content"].strip()
    
    except Exception:
        pass
    
    return ""


def find_contact_page(base_url: str, html: str) -> str:
    """
    Busca un enlace a página de contacto dentro del HTML.
    
    Busca links que contengan palabras como:
      - contacto, contact
      - contactanos, contact-us
      - atencion, support
    
    Args:
        base_url (str): URL base para resolver URLs relativas
        html (str): Contenido HTML de la página
    
    Returns:
        str: URL absoluta de la página de contacto, o string vacío si no la encuentra
    
    Ejemplo:
        >>> url = find_contact_page("https://ferreteria.com", html)
        >>> url
        "https://ferreteria.com/contacto"
    """
    if not base_url or not html:
        return ""
    
    try:
        soup = BeautifulSoup(html, "lxml")
        contact_words = ["contacto", "contact", "contactanos", "atencion"]
        
        # Buscar todos los links
        for a in soup.find_all("a", href=True):
            href  = a.get("href", "").strip()
            text  = a.get_text(" ", strip=True).lower()
            href_lower = href.lower()
            
            # Verificar si el texto o href contiene palabras de contacto
            if any(w in text or w in href_lower for w in contact_words):
                # Resolver URL relativa a URL absoluta
                return urljoin(base_url, href)
    
    except Exception:
        pass
    
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# SCORING ARGOS — FILTRADO DE CALIDAD
# ═══════════════════════════════════════════════════════════════════════════════

# Palabras clave con alta relevancia (construc + ferretes)
POSITIVE_TERMS_ALTA = [
    "ferreter", "deposito de materiales", "deposito y ferreteria",
    "materiales de construccion", "materiales para construccion",
    "cemento", "concreto", "mortero", "prefabricado", "bloquera",
    "ladrillera", "distribuidor de cemento", "distribuidora de cemento",
    "obra gris", "hierro y cemento", "agregados", "ferredeposito",
    "centro ferretero", "bodegas de construccion",
]

# Palabras clave con relevancia media
POSITIVE_TERMS_MEDIA = [
    "construccion", "deposito", "corralon", "materiales", "hierro",
    "arena", "grava", "triturado", "ferretero",
]

# Palabras que descalifican (negocios no relacionados)
NEGATIVE_TERMS = [
    "restaurante", "comida", "estetica", "spa", "medico", "odontologia",
    "ropa", "moda", "peluqueria", "barberia", "hotel", "turismo",
    "veterinaria", "abogado", "universidad", "colegio", "farmacia",
    "salon de belleza", "taxis", "supermercado",
]


def score_result(title: str, snippet: str, meta_description: str,
                 query: str, url: str) -> int:
    """
    Calcula el score Argos de un resultado.
    
    Scoring:
      +3 por cada término de alta relevancia
      +2 por cada término de media relevancia
      -5 por cada término descalificador
      +2 si el dominio contiene palabras construcción
    
    Args:
        title (str): Título del resultado
        snippet (str): Snippet/resumen
        meta_description (str): Meta descripción del sitio
        query (str): Query que se buscó
        url (str): URL del resultado
    
    Returns:
        int: Score total (puede ser negativo)
    
    Ejemplo:
        >>> score_result("Ferretería XYZ", "Cemento y materiales...",
        ...              "Vendemos cemento", "ferreterías en Bogotá",
        ...              "https://ferreteria-xyz.com")
        8  # 3 + 3 + 2 = 8
    """
    
    # Concatenar todo el texto para buscar
    text = " ".join([
        title or "", snippet or "", meta_description or "",
        query or "", url or ""
    ]).lower()
    
    score = 0
    
    # ─── TÉRMINOS POSITIVOS DE ALTA RELEVANCIA ────────────────────────────
    for term in POSITIVE_TERMS_ALTA:
        if term in text:
            score += 3
    
    # ─── TÉRMINOS POSITIVOS DE MEDIA RELEVANCIA ───────────────────────────
    for term in POSITIVE_TERMS_MEDIA:
        if term in text:
            score += 2
    
    # ─── TÉRMINOS DESCALIFICADORES ────────────────────────────────────────
    for term in NEGATIVE_TERMS:
        if term in text:
            score -= 5
    
    # ─── BONUS POR DOMINIO RELEVANTE ──────────────────────────────────────
    domain = get_domain(url)
    if any(x in domain for x in ["ferreter", "constructor", "cement", "concreto", "materiales"]):
        score += 2
    
    return score


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES UTILITARIAS VARIAS
# ═══════════════════════════════════════════════════════════════════════════════

def first_or_none(items: list):
    """
    Retorna el primer elemento de una lista, o None si está vacía.
    
    Args:
        items (list): Lista
    
    Returns:
        Primer elemento o None
    
    Ejemplo:
        >>> first_or_none(["a", "b"])
        "a"
        >>> first_or_none([])
        None
    """
    return items[0] if items else None


def json_dumps(data) -> str:
    """
    Convierte un objeto a JSON string (UTF-8, no ASCII).
    
    Args:
        data: Objeto a serializar
    
    Returns:
        str: JSON string
    
    Ejemplo:
        >>> json_dumps({"nombre": "José"})
        '{"nombre": "José"}'
    """
    return json.dumps(data, ensure_ascii=False, default=str)
