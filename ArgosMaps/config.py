
CIUDADES = [
    # Capitales Principales
    "bogota", "medellin", "cali", "barranquilla", "cartagena", "bucaramanga", 
    "cucuta", "pereira", "santa-marta", "ibague", "pasto", "manizales", 
    "neiva", "villavicencio", "armenia", "valledupar", "monteria", "sincelejo", 
    "popayan", "tunja", "riohacha", "florencia", "quibdo", "yopal", "arauca",
    # Periferias de Construcción Pesada
    "bello", "itagui", "envigado", "sabaneta", "rionegro", "apartado", 
    "caucasia", "turbo", "dosquebradas", "santa-rosa-de-cabal", "calarca",
    "soacha", "chia", "zipaquira", "facatativa", "fusagasuga", "girardot", 
    "mosquera", "madrid", "funza", "duitama", "sogamoso", "chiquinquira",
    "palmira", "buenaventura", "tulua", "cartago", "buga", "jamundi", "yumbo", "tumaco",
    "soledad", "malambo", "cienaga", "magangue", "maicao", "aguachica", 
    "floridablanca", "giron", "piedecuesta", "barrancabermeja", "pamplona", "ocana", 
    "pitalito", "garzon", "espinal", "ipiales"
]

# Mapa ciudad → departamento para enriquecer los registros
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


KEYWORDS_BUSQUEDA = [
    "ferreterias", "depositos de materiales", "depositos y ferreteria", 
    "bodegas de construccion", "centro ferretero", "materiales para construccion",
    "cemento", "concreto", "concreto premezclado", "morteros", "mortero seco", 
    "agregados para construccion", "arena y balasto", "obra gris", 
    "hierro y cemento", "bloqueras", "ladrilleras", "prefabricados de concreto", 
    "distribuidoras de cemento"
]




# ─── PostgreSQL ───────────────────────────────────────────────────────────────
# Carga desde variables de entorno. Crea un archivo .env con estos valores
# y nunca lo subas a Git.
import os
from dotenv import load_dotenv
load_dotenv()
 
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME",     "postgres"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "password": os.getenv("DB_PASSWORD", "1234"),
}



# ─── Configuración del Scraping ───────────────────────────────────────────────
MAX_CONCURRENT_TABS = 3 #2
MIN_DELAY_SECONDS   = 1.5 #2.0
MAX_DELAY_SECONDS   = 3.0 #5.0
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() == "true"


# ─── Rutas de Salida (respaldo local) ────────────────────────────────────────
OUTPUT_FILE      = "base_de_datos_argos_maps.jsonl"
EXCEL_OUTPUT_FILE = "base_de_datos_argos_maps.xlsx"
GUARDAR_JSONL_LOCAL = os.getenv("GUARDAR_JSONL_LOCAL", "false").strip().lower() == "true"

# ─── Sesión de Chrome (Playwright) ───────────────────────────────────────────
USER_DATA_DIR = "chrome_session_argos"
 
