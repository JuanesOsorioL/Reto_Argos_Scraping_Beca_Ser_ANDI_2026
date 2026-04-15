"""
normalizer.py — Convierte respuestas de Foursquare al esquema Argos
Incluye:
  - Extracción de todos los campos disponibles
  - Scoring automático (calidad del resultado)
  - Normalización de teléfono colombiano
"""
import hashlib
from datetime import datetime, timezone
from config import ARGOS_SCORE_THRESHOLD, CIUDAD_DEPARTAMENTO


# ──────────────────────────────────────────────────────────────────────────────
# SCORING: Palabras clave para calificar relevancia
# ──────────────────────────────────────────────────────────────────────────────

PALABRAS_ALTA = [
    "ferreteri", "cemento", "concreto", "mortero", "prefabricado",
    "bloquera", "ladrillera", "deposito materiales", "distribuidor cemento",
    "obra gris", "hierro cemento", "agregados", "ferredeposito",
    "centro ferretero", "materiales construccion",
]

PALABRAS_MEDIA = [
    "construccion", "deposito", "materiales", "hierro", "hardware",
    "building", "corralon",
]

PALABRAS_NEGATIVAS = [
    "restaurante", "salon belleza", "spa", "medico", "farmacia",
    "ropa", "hotel", "veterinaria", "supermercado",
]

# Categorías Foursquare que son directamente relevantes
CATEGORIAS_RELEVANTES = {
    "4bf58dd8d48988d112951735": 5,   # Hardware Store → +5
    "52f2ab2ebcbc57f1066b8b43": 3,   # Construction & Landscaping → +3
    "4d954b0ea243a5684a65b473": 1,   # Home → +1
}


def calcular_score(nombre: str, categorias: list, descripcion: str = "") -> tuple:
    """
    Calcula score de relevancia del lugar.
    Score = suma de puntos según nombre, categoría, descripción.
    
    Args:
        nombre: Nombre del lugar
        categorias: Lista de categorías de Foursquare
        descripcion: Descripción del lugar
    
    Returns:
        (score: int, aprobado_argos: bool)
    """
    # Combinar texto para búsqueda
    texto = f"{nombre} {descripcion} {' '.join([c.get('name','') for c in categorias])}".lower()
    score = 0
    
    # 1. Bonus por categoría FSQ exacta
    for cat in categorias:
        cat_id = str(cat.get("id", ""))
        if cat_id in CATEGORIAS_RELEVANTES:
            score += CATEGORIAS_RELEVANTES[cat_id]
    
    # 2. Bonus por palabras clave de alta relevancia
    for p in PALABRAS_ALTA:
        if p in texto:
            score += 3
    
    # 3. Bonus por palabras clave de media relevancia
    for p in PALABRAS_MEDIA:
        if p in texto:
            score += 2
    
    # 4. Penalización por palabras negativas
    for p in PALABRAS_NEGATIVAS:
        if p in texto:
            score -= 5
    
    # Validar si cumple umbral Argos
    aprobado = score >= ARGOS_SCORE_THRESHOLD
    
    return score, aprobado


def generar_hash(fsq_place_id: str) -> str:
    """
    Genera hash único basado en fsq_place_id.
    Evita duplicados en BD.
    
    Args:
        fsq_place_id: ID único de Foursquare
    
    Returns:
        Hash MD5 de 32 caracteres
    """
    return hashlib.md5(f"fsq||{fsq_place_id}".encode("utf-8")).hexdigest()


def limpiar_telefono(tel: str) -> str:
    """
    Normaliza teléfono colombiano a formato +57XXXXXXXXXX.
    
    Args:
        tel: Teléfono crudo
    
    Returns:
        Teléfono normalizado o string vacío
    """
    if not tel:
        return ""
    
    import re
    # Quitar caracteres especiales, mantener solo dígitos y +
    digits = re.sub(r"[^\d+]", "", tel)
    
    # Si es +57 + 10 dígitos, está correcto
    if digits.startswith("57") and len(digits) == 12:
        return f"+{digits}"
    
    # Si es 3 + 9 dígitos (móvil colombiano), agregar +57
    if digits.startswith("3") and len(digits) == 10:
        return f"+57{digits}"
    
    # Si no encaja, retornar como está (sin normalizar)
    return tel.strip()


def normalizar_lugar(
    place: dict,
    ciudad_nombre: str,
    keyword: str,
    run_id: str,
    fecha_extraccion: datetime,
) -> dict | None:
    """
    Mapea respuesta de Foursquare al esquema Argos.
    
    Args:
        place: Respuesta de Foursquare
        ciudad_nombre: Ciudad de búsqueda
        keyword: Palabra clave usada
        run_id: UUID de la corrida
        fecha_extraccion: Datetime del scraping
    
    Returns:
        dict normalizado, o None si falta información crítica
    """
    
    # ──────────────────────────────────────────────────────────────────────
    # EXTRACCIÓN DE CAMPOS
    # ──────────────────────────────────────────────────────────────────────
    
    fsq_id = place.get("fsq_place_id")
    nombre = place.get("name", "")
    
    # Validación básica
    if not fsq_id or not nombre:
        return None
    
    # ── UBICACIÓN ────────────────────────────────────────────────────────
    location = place.get("location", {})
    latitud = place.get("latitude")
    longitud = place.get("longitude")
    direccion = location.get("formatted_address", "") or location.get("address", "")
    postal_code = location.get("postcode", "")
    locality = location.get("locality", "")
    region_fsq = location.get("region", "")
    country = location.get("country", "CO")
    
    # Municipio: usar locality si viene, si no usar ciudad de búsqueda
    municipio = locality if locality else ciudad_nombre
    departamento = CIUDAD_DEPARTAMENTO.get(ciudad_nombre, region_fsq)
    
    # ── CONTACTO ─────────────────────────────────────────────────────────
    telefono = limpiar_telefono(place.get("tel", ""))
    email = place.get("email", "")
    website = place.get("website", "")
    
    # Redes sociales
    social_media = place.get("social_media", {}) or {}
    twitter = social_media.get("twitter", "")
    instagram = social_media.get("instagram", "")
    facebook = social_media.get("facebook_id", "")
    
    # ── CATEGORÍAS ───────────────────────────────────────────────────────
    categorias = place.get("categories", [])
    cats_nombres = ", ".join([c.get("name", "") for c in categorias])
    cats_ids = ", ".join([str(c.get("id", "")) for c in categorias])
    
    # ── METADATA FOURSQUARE ──────────────────────────────────────────────
    fsq_link = place.get("link", "")
    fsq_distance = place.get("distance")
    fsq_date_created = place.get("date_created", "")
    fsq_date_refresh = place.get("date_refreshed", "")
    descripcion = place.get("description", "")
    rating = place.get("rating")
    price = place.get("price")
    verified = place.get("verified", False)
    
    # Horarios (complejo, guardamos como JSON string)
    hours_raw = place.get("hours", {})
    hours_str = ""
    if hours_raw:
        import json
        try:
            hours_str = json.dumps(hours_raw, ensure_ascii=False)
        except Exception:
            hours_str = str(hours_raw)
    
    # ── SCORING ARGOS ────────────────────────────────────────────────────
    score, aprobado = calcular_score(nombre, categorias, descripcion)
    
    # ── FECHA DE ACTUALIZACIÓN ───────────────────────────────────────────
    fecha_act = fecha_extraccion
    if fsq_date_refresh:
        try:
            from datetime import date
            d = date.fromisoformat(fsq_date_refresh)
            fecha_act = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except Exception:
            pass
    
    # ──────────────────────────────────────────────────────────────────────
    # CONSTRUCCIÓN DEL REGISTRO NORMALIZADO
    # ──────────────────────────────────────────────────────────────────────
    
    return {
        # Identidad y trazabilidad
        "hash_id": generar_hash(fsq_id),
        "run_id": run_id,
        "fecha_extraccion": fecha_extraccion,
        
        # Columnas Argos (requeridas)
        "nit": "",  # Foursquare no proporciona NIT
        "nombre": nombre,
        "departamento": departamento,
        "municipio": municipio,
        "direccion": direccion,
        "latitud": latitud,
        "longitud": longitud,
        "telefono": telefono,
        "whatsapp": "",  # FSQ no siempre proporciona
        "correo_electronico": email,
        "fecha_actualizacion": fecha_act,
        "fuente": "foursquare",
        
        # Adicionales de calidad
        "keyword_busqueda": keyword,
        "score": score,
        "aprobado_argos": aprobado,
        
        # Exclusivos de Foursquare
        "fsq_place_id": fsq_id,
        "fsq_link": fsq_link,
        "fsq_categories": cats_nombres,
        "fsq_category_ids": cats_ids,
        "fsq_distance": fsq_distance,
        "fsq_date_created": fsq_date_created,
        "fsq_date_refreshed": fsq_date_refresh,
        "fsq_website": website,
        "fsq_twitter": twitter,
        "fsq_instagram": instagram,
        "fsq_facebook": facebook,
        "fsq_description": descripcion,
        "fsq_rating": rating,
        "fsq_price": price,
        "fsq_hours": hours_str,
        "fsq_verified": verified,
        "fsq_postal_code": postal_code,
        "fsq_locality": locality,
        "fsq_region": region_fsq,
        "fsq_country": country,
        
        # RAW JSON completo para análisis futuro
        "raw_place": place,
    }
