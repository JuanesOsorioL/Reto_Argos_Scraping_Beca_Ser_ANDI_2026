"""
config.py — Configuración centralizada del proyecto Foursquare Places API
Lee desde .env y valida todas las variables necesarias.
Incluye funciones helper para manejo de rate limits.
"""
import os
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()


# ──────────────────────────────────────────────────────────────────────────────
# FOURSQUARE API CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

FSQ_API_KEY = os.getenv("FSQ_API_KEY", "")
if not FSQ_API_KEY:
    raise ValueError("❌ FSQ_API_KEY no está definida en .env")

FSQ_BASE_URL = "https://places-api.foursquare.com/places/search"
FSQ_DETAIL_URL = "https://api.foursquare.com/v3/places/{fsq_id}"

FSQ_HEADERS = {
    "Authorization": f"Bearer {FSQ_API_KEY}",
    "Accept": "application/json",
    "X-Places-Api-Version": "2025-06-17",
}

# Campos a solicitar en cada búsqueda
FSQ_FIELDS = ",".join([
    "fsq_place_id", "name", "categories", "location",
    "latitude", "longitude", "distance", "tel", "email",
    "website", "social_media", "date_closed", "link",
    "placemaker_url", "chains", "store_id", "related_places",
    "extended_location", "unresolved_flags",
])


# ──────────────────────────────────────────────────────────────────────────────
# KEYWORDS Y CIUDADES
# ──────────────────────────────────────────────────────────────────────────────

"""
KEYWORDS_BUSQUEDA = [
    "ferretería", "materiales de construcción", "cemento",
    "depósito de materiales", "ferreteria deposito",
    "concreto premezclado", "mortero cemento", "bloquera",
    "ladrillera", "distribuidora cemento",
]
"""



KEYWORDS_BUSQUEDA = [
    "ferreterias",
    "depositos de materiales",
    "materiales de construccion",
    "concreto",
    "agregados para construccion",
    "bloqueras"
]




CIUDAD_DEPARTAMENTO = {
    "Bogotá": "Cundinamarca", "Medellín": "Antioquia", "Cali": "Valle del Cauca",
    "Barranquilla": "Atlántico", "Cartagena": "Bolívar", "Bucaramanga": "Santander",
    "Cúcuta": "Norte de Santander", "Pereira": "Risaralda", "Santa Marta": "Magdalena",
    "Ibagué": "Tolima", "Pasto": "Nariño", "Manizales": "Caldas",
    "Neiva": "Huila", "Villavicencio": "Meta", "Armenia": "Quindío",
    "Valledupar": "Cesar", "Montería": "Córdoba", "Sincelejo": "Sucre",
    "Popayán": "Cauca", "Tunja": "Boyacá", "Bello": "Antioquia",
    "Itagüí": "Antioquia", "Envigado": "Antioquia", "Rionegro": "Antioquia",
    "Apartadó": "Antioquia", "Soacha": "Cundinamarca", "Palmira": "Valle del Cauca",
    "Buenaventura": "Valle del Cauca", "Barrancabermeja": "Santander",
    "Duitama": "Boyacá", "Sogamoso": "Boyacá", "Dosquebradas": "Risaralda",
    "Floridablanca": "Santander", "Girón": "Santander",
    "Pitalito": "Huila", "Ipiales": "Nariño",
}

# ──────────────────────────────────────────────────────────────────────────────
# REQUEST CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

REQUEST_DELAY = float(os.getenv("REQUEST_DELAY_SECONDS", "0.3"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
LIMIT_POR_PAG = 50  # Máximo por página en Foursquare
MAX_POR_QUERY = 200  # Límite de seguridad por query


# ──────────────────────────────────────────────────────────────────────────────
# ARGOS SCORE CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

ARGOS_SCORE_THRESHOLD = 2


# ──────────────────────────────────────────────────────────────────────────────
# POSTGRESQL DATABASE CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "1234"),
}


# ──────────────────────────────────────────────────────────────────────────────
# RATE LIMIT CONFIGURATION (Pausa automática)
# ──────────────────────────────────────────────────────────────────────────────

AUTO_PAUSE_ON_RATE_LIMIT = os.getenv("AUTO_PAUSE_ON_RATE_LIMIT", "true").lower() == "true"
RATE_LIMIT_SLEEP_SECONDS = int(os.getenv("RATE_LIMIT_SLEEP_SECONDS", "3600"))
MAX_CONSECUTIVE_RATE_LIMITS = int(os.getenv("MAX_CONSECUTIVE_RATE_LIMITS", "5"))
AUTO_RESUME_AFTER_PAUSE = os.getenv("AUTO_RESUME_AFTER_PAUSE", "true").lower() == "true"


# ──────────────────────────────────────────────────────────────────────────────
# JSON BACKUP CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

SAVE_JSON_BACKUP = os.getenv("SAVE_JSON_BACKUP", "false").lower() == "true"
SAVE_PROGRESS_FILE = os.getenv("SAVE_PROGRESS_FILE", "false").lower() == "true"


# ──────────────────────────────────────────────────────────────────────────────
# WEBHOOK CONFIGURATION (Para n8n)
# ──────────────────────────────────────────────────────────────────────────────

WEBHOOK_ON_PAUSE = os.getenv("WEBHOOK_ON_PAUSE", "")
WEBHOOK_ON_COMPLETE = os.getenv("WEBHOOK_ON_COMPLETE", "")
WEBHOOK_ON_ERROR = os.getenv("WEBHOOK_ON_ERROR", "")


# ──────────────────────────────────────────────────────────────────────────────
# API SERVER CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

API_PORT = int(os.getenv("API_PORT", "8006"))
API_HOST = os.getenv("API_HOST", "0.0.0.0")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"


# ──────────────────────────────────────────────────────────────────────────────
# FILE PATHS
# ──────────────────────────────────────────────────────────────────────────────

OUTPUT_FILE = "foursquare_ferreterias.jsonl"
OUTPUT_DIR = "output"
JSON_RAW_FILE = "output/foursquare_raw_responses.json"
JSON_FLAT_FILE = "output/foursquare_flat_results.json"
PROGRESS_FILE = "foursquare_progress.json"
EXCEL_OUTPUT_FILE = "foursquare_ferreterias.xlsx"


# ──────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

def parse_rate_limit_header(response_headers: dict) -> tuple:
    """
    Extrae información de rate limit de los headers de respuesta.
    
    Foursquare devuelve:
    - X-RateLimit-Limit: límite máximo
    - X-RateLimit-Remaining: requests restantes
    - X-RateLimit-Reset: UNIX timestamp cuando se resetea
    
    Retorna: (remaining, reset_timestamp)
    """
    try:
        remaining = int(response_headers.get("X-RateLimit-Remaining", "-1"))
        reset = int(response_headers.get("X-RateLimit-Reset", "-1"))
        return remaining, reset
    except Exception:
        return -1, -1


def get_seconds_until_reset(reset_timestamp: int) -> int:
    """
    Calcula cuántos segundos faltan hasta que se resetee el rate limit.
    
    Args:
        reset_timestamp: UNIX timestamp del reset
    
    Returns:
        Segundos a esperar (positivo si falta, 0 si ya pasó)
    """
    import time
    now = int(time.time())
    delta = reset_timestamp - now
    return max(0, delta)


# ──────────────────────────────────────────────────────────────────────────────
# VALIDACIÓN AL INICIAR
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("✅ Config cargada correctamente")
    print(f"   FSQ_API_KEY: {FSQ_API_KEY[:10]}...")
    print(f"   DB: {DB_CONFIG['dbname']}@{DB_CONFIG['host']}")
    print(f"   AUTO_PAUSE: {AUTO_PAUSE_ON_RATE_LIMIT}")
    print(f"   SAVE_JSON: {SAVE_JSON_BACKUP}")
    print(f"   WEBHOOKS: {bool(WEBHOOK_ON_PAUSE)}")
