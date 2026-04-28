"""
═══════════════════════════════════════════════════════════════════════════════
config.py — Configuración centralizada del proyecto Serper API
═══════════════════════════════════════════════════════════════════════════════

Responsabilidades:
  ✓ Cargar variables de .env
  ✓ Validar que existan las keys críticas (SERPER_API_KEY, DB_*)
  ✓ Convertir strings a tipos correctos (bool, int)
  ✓ Centralizar todas las constantes para fácil mantenimiento
  ✓ Logging de valores importantes (sin exponer keys sensibles)
"""

import os
from dotenv import load_dotenv

# ─── Cargar .env ─────────────────────────────────────────────────────────────
load_dotenv()


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def env_bool(name: str, default: bool = False) -> bool:
    """
    Convierte una variable de entorno a booleano.
    Acepta: "1", "true", "yes", "si", "sí", "on" (case-insensitive)
    
    Args:
        name: Nombre de la variable en .env
        default: Valor por defecto si no existe
    
    Returns:
        bool: True si el valor es uno de los aceptados, False en otro caso
    
    Ejemplo:
        SAVE_JSON_BACKUP=true  →  env_bool("SAVE_JSON_BACKUP") = True
        SAVE_JSON_BACKUP=false →  env_bool("SAVE_JSON_BACKUP") = False
        (no definido)           →  env_bool("SAVE_JSON_BACKUP", True) = True
    """
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "si", "sí", "on")


def env_int(name: str, default: int) -> int:
    """
    Convierte una variable de entorno a entero.
    
    Args:
        name: Nombre de la variable en .env
        default: Valor por defecto si no existe o no es válido
    
    Returns:
        int: El valor convertido a entero
    """
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_str(name: str, default: str = "") -> str:
    """
    Obtiene una variable de entorno como string.
    
    Args:
        name: Nombre de la variable en .env
        default: Valor por defecto si no existe
    
    Returns:
        str: El valor de la variable
    """
    return os.getenv(name, default).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# SERPER API
# ═══════════════════════════════════════════════════════════════════════════════

# La URL de Serper API es fija, nunca cambia
SERPER_URL = "https://google.serper.dev/search"

# Tu API key de Serper (debe estar en .env)
# Obtenido de: https://serper.dev/
# Plan: Gratuito (~2,500 queries)
SERPER_API_KEY = env_str("SERPER_API_KEY")

if not SERPER_API_KEY or SERPER_API_KEY == "PON_AQUI_TU_API_KEY":
    raise ValueError(
        "❌ SERPER_API_KEY no está configurada en .env\n"
        "   Obtén una key gratuita en https://serper.dev/\n"
        "   Luego actualiza .env: SERPER_API_KEY=tu_key_aqui"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# BASE DE DATOS (PostgreSQL)
# ═══════════════════════════════════════════════════════════════════════════════

# Diccionario de configuración para psycopg2.connect()
DB_CONFIG = {
    "host":     env_str("DB_HOST", "localhost"),
    "port":     env_int("DB_PORT", 5432),
    "dbname":   env_str("DB_NAME", "postgres"),
    "user":     env_str("DB_USER", "postgres"),
    "password": env_str("DB_PASSWORD", "1234"),
}

# Validación básica
if not DB_CONFIG["host"] or not DB_CONFIG["user"]:
    raise ValueError(
        "❌ Configuración de base de datos incompleta en .env\n"
        "   Asegúrate de tener: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# BÚSQUEDA: KEYWORDS Y CIUDADES
# ═══════════════════════════════════════════════════════════════════════════════

"""
KEYWORDS_BUSQUEDA = [
    "ferreterias", "depositos de materiales", "depositos y ferreteria",
    "bodegas de construccion", "centro ferretero", "materiales para construccion",
    "cemento", "concreto", "concreto premezclado", "morteros", "mortero seco",
    "agregados para construccion", "arena y balasto", "obra gris",
    "hierro y cemento", "bloqueras", "ladrilleras", "prefabricados de concreto",
    "distribuidoras de cemento"
]

"""

KEYWORDS_BUSQUEDA = [
"ferreterias",
    "depositos de materiales",
    "depositos y ferreteria",
    "bodegas de construccion",
    "centro ferretero",
    "materiales de construccion",
    "materiales para construccion",

    "cemento",
    "distribuidoras de cemento",
    "venta de cemento",
    "hierro y cemento",

    "concreto",
    "concreto premezclado",
    "prefabricados de concreto",

    "morteros",
    "mortero seco",

    "agregados para construccion",
    "arena y balasto",
    "arena grava y triturado",

    "obra gris",

    "bloqueras",
    "ladrilleras"
]


# Mapeo ciudad → departamento (para enriquecimiento de datos)
CIUDAD_DEPARTAMENTO = {
    "bogota": "Cundinamarca", "medellin": "Antioquia", "cali": "Valle del Cauca",
    "barranquilla": "Atlántico", "cartagena": "Bolívar", "bucaramanga": "Santander",
    "cucuta": "Norte de Santander", "pereira": "Risaralda", "santa-marta": "Magdalena",
    "ibague": "Tolima", "pasto": "Nariño", "manizales": "Caldas",
    "neiva": "Huila", "villavicencio": "Meta", "armenia": "Quindío",
    "valledupar": "Cesar", "monteria": "Córdoba", "sincelejo": "Sucre",
    "popayan": "Cauca", "tunja": "Boyacá", "riohacha": "La Guajira",
    "florencia": "Caquetá", "quibdo": "Chocó", "yopal": "Casanare",
    "arauca": "Arauca", "bello": "Antioquia", "itagui": "Antioquia",
    "envigado": "Antioquia", "sabaneta": "Antioquia", "rionegro": "Antioquia",
    "apartado": "Antioquia", "caucasia": "Antioquia", "turbo": "Antioquia",
    "dosquebradas": "Risaralda", "santa-rosa-de-cabal": "Risaralda",
    "calarca": "Quindío", "soacha": "Cundinamarca", "chia": "Cundinamarca",
    "zipaquira": "Cundinamarca", "facatativa": "Cundinamarca",
    "fusagasuga": "Cundinamarca", "girardot": "Cundinamarca",
    "mosquera": "Cundinamarca", "madrid": "Cundinamarca", "funza": "Cundinamarca",
    "duitama": "Boyacá", "sogamoso": "Boyacá", "chiquinquira": "Boyacá",
    "palmira": "Valle del Cauca", "buenaventura": "Valle del Cauca",
    "tulua": "Valle del Cauca", "cartago": "Valle del Cauca",
    "buga": "Valle del Cauca", "jamundi": "Valle del Cauca",
    "yumbo": "Valle del Cauca", "tumaco": "Nariño",
    "soledad": "Atlántico", "malambo": "Atlántico", "cienaga": "Magdalena",
    "magangue": "Bolívar", "maicao": "La Guajira", "aguachica": "Cesar",
    "floridablanca": "Santander", "giron": "Santander", "piedecuesta": "Santander",
    "barrancabermeja": "Santander", "pamplona": "Norte de Santander",
    "ocana": "Norte de Santander", "pitalito": "Huila", "garzon": "Huila",
    "espinal": "Tolima", "ipiales": "Nariño",
}



# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE SCRAPING
# ═══════════════════════════════════════════════════════════════════════════════

# Timeout para requests HTTP (segundos)
# Si Serper o un sitio web no responde en 20s, timeout
REQUEST_TIMEOUT = 20

# Número de workers para enriquecimiento paralelo de URLs
# Si se visitan muchas URLs simultáneamente, aumentar esto
# Pero cuidado: no saturar el servidor ni los sitios destino
MAX_WORKERS = 8

# Pausa entre llamadas a Serper (segundos)
# Serper recomienda ~1.2s para tier gratuito (100 req/min máx)
# 60 seg / 100 req = 0.6 seg mínimo, pero somos conservadores
SERPER_SLEEP_SECONDS = 1.2

# User-Agent para que parezca un navegador real al visitar sitios
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


# ═══════════════════════════════════════════════════════════════════════════════
# SCORING (Argos Score) — Filtrado de resultados por calidad
# ═══════════════════════════════════════════════════════════════════════════════

# Threshold mínimo de score para que un resultado sea "aprobado_argos=True"
# Score se calcula en scraper.py con positivos/negativos
# Umbral consistente con Google Maps y PA
ARGOS_SCORE_THRESHOLD = 3


# ═══════════════════════════════════════════════════════════════════════════════
# ARCHIVOS DE SALIDA (JSON Backup)
# ═══════════════════════════════════════════════════════════════════════════════

# Directorio donde se guardan archivos locales (JSON)
OUTPUT_DIR = "output"

# Archivo con respuestas crudas de Serper (JSON)
# Contiene: run_id, query_meta, response (completa con organic, knowledgeGraph, etc)
RAW_JSON_FILE = f"{OUTPUT_DIR}/serper_raw_responses.json"

# Archivo con resultados aplanaados (JSON)
# Una línea por registro (nombre, teléfono, dirección, email, score, etc)
FLAT_JSON_FILE = f"{OUTPUT_DIR}/serper_flat_results.json"

# ⚠️ BANDERA CRÍTICA: Controla si se guardan los archivos JSON locales
# Si SAVE_JSON_BACKUP=false en .env: NO se crean estos archivos
# Si SAVE_JSON_BACKUP=true en .env:  Sí se crean (útil para debugging)
# En cualquier caso, los datos SIEMPRE se guardan en PostgreSQL
SAVE_JSON_BACKUP = env_bool("SAVE_JSON_BACKUP", False)


# ═══════════════════════════════════════════════════════════════════════════════
# PROGRESO Y REANUDACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

# Archivo JSON donde se guarda el estado actual
# Después de cada query éxitosa, se actualiza con:
#   - índice actual de queries
#   - últimas métricas (insertados, duplicados, errores)
#   - status (corriendo, pausado_sin_tokens, ok, error)
#   - timestamp de inicio/fin
# Permite reanudar exactamente donde se pausó
PROGRESS_FILE = "serper_progress.json"

# Si true: guarda el archivo de progreso después de cada query
# Si false: NO guarda, pero igual se puede ver /progress endpoint
SAVE_PROGRESS_FILE = env_bool("SAVE_PROGRESS_FILE", True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAUSA AUTOMÁTICA POR RATE LIMITS (429)
# ═══════════════════════════════════════════════════════════════════════════════

# Si true: cuando Serper devuelve 429 (rate limit), el scraper:
#   1. Pausa automáticamente
#   2. Espera RATE_LIMIT_SLEEP_SECONDS
#   3. Reintenta la query que falló
#   4. Si sigue fallando, espera de nuevo y reintenta
# Si false: levanta excepción y termina el proceso
AUTO_RESUME_ON_RATE_LIMIT = env_bool("AUTO_RESUME_ON_RATE_LIMIT", True)

# Segundos de espera cuando recibe 429 (Serper rate limit)
# Serper tier gratuito típicamente permite 100 req/min
# Si se alcanza ese límite, es recomendable esperar 15 min (900s)
RATE_LIMIT_SLEEP_SECONDS = env_int("RATE_LIMIT_SLEEP_SECONDS", 900)

# Máximo número de 429s CONSECUTIVOS antes de rendirse
# Si alcanza este número, pausa permanentemente hasta resume manual
# Con 20 reintentos × 900s cada uno = 5 horas de espera máximo
MAX_CONSECUTIVE_RATE_LIMITS = env_int("MAX_CONSECUTIVE_RATE_LIMITS", 20)


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOKS (n8n)
# ═══════════════════════════════════════════════════════════════════════════════

# URL del webhook de n8n donde se envían notificaciones
# n8n recibe eventos de:
#   - serper.finalizado (éxito o error)
#   - serper.pausado_tokens (rate limit automático)
#   - serper.pausado_manual (usuario llamó POST /pause)
N8N_WEBHOOK_URL = env_str("N8N_WEBHOOK_URL", "")

# Puerto donde corre la API FastAPI
PORT = env_int("PORT", 8004)


# ═══════════════════════════════════════════════════════════════════════════════
# RESUMEN DE CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  CONFIGURACIÓN ACTUAL DE SERPER API")
    print("="*80 + "\n")
    
    print("🔌 SERPER")
    print(f"   API Key: {SERPER_API_KEY[:20]}...XXX")
    print(f"   URL: {SERPER_URL}")
    print(f"   Sleep entre queries: {SERPER_SLEEP_SECONDS}s\n")
    
    print("🗄️  POSTGRESQL")
    print(f"   Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"   Database: {DB_CONFIG['dbname']}")
    print(f"   User: {DB_CONFIG['user']}\n")
    
    print("📊 BÚSQUEDA")
    print(f"   Keywords: {len(KEYWORDS_BUSQUEDA)}")
    print(f"   Ciudades: {len(CIUDADES)}")
    print(f"   Total queries: {len(KEYWORDS_BUSQUEDA) * len(CIUDADES)}\n")
    
    print("⚙️  CONTROL")
    print(f"   JSON Backup: {'✅ SÍ' if SAVE_JSON_BACKUP else '❌ NO'}")
    print(f"   Progreso File: {'✅ SÍ' if SAVE_PROGRESS_FILE else '❌ NO'}")
    print(f"   Auto-Resume Rate Limit: {'✅ SÍ' if AUTO_RESUME_ON_RATE_LIMIT else '❌ NO'}")
    print(f"   Rate Limit Sleep: {RATE_LIMIT_SLEEP_SECONDS}s")
    print(f"   Max Reintentos: {MAX_CONSECUTIVE_RATE_LIMITS}\n")
    
    print("🌐 WEBHOOKS")
    print(f"   n8n URL: {N8N_WEBHOOK_URL if N8N_WEBHOOK_URL else '(no configurado)'}")
    print(f"   API Port: {PORT}\n")
    
    print("="*80 + "\n")
