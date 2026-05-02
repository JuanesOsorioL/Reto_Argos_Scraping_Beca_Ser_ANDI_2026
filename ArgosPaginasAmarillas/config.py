
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

"""

antes
KEYWORDS_BUSQUEDA = [
    "ferreterias",
    "depositos-de-materiales",
    "depositos-y-ferreteria",
    "bodegas-de-construccion",
    "centro-ferretero",
    "materiales-para-construccion",
    "cemento",
    "concreto",
    "concreto-premezclado",
    "morteros",
    "mortero-seco",
    "agregados-para-construccion",
    "arena-y-balasto",
    "obra-gris",
    "hierro-y-cemento",
    "bloqueras",
    "ladrilleras",
    "prefabricados-de-concreto",
    "distribuidoras-de-cemento"
]

segunda vez unificadas
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

las de la primera fase
KEYWORDS_MVP = [
    "ferreterias",
    "depositos de materiales",
    "materiales de construccion",
    "cemento",
    "venta de cemento",
    "distribuidoras de cemento",
    "hierro y cemento",
    "concreto",
    "agregados para construccion",
    "bloqueras"
]


segunda fase
KEYWORDS_FASE_2 = [
    "depositos y ferreteria",
    "bodegas de construccion",
    "centro ferretero",
    "materiales para construccion",
    "concreto premezclado",
    "prefabricados de concreto",
    "morteros",
    "mortero seco",
    "arena y balasto",
    "arena grava y triturado",
    "obra gris",
    "ladrilleras"
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


# ─── PostgreSQL ───────────────────────────────────────────────────────────────
import os
from dotenv import load_dotenv
load_dotenv()

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "si", "sí", "on")

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME",     "postgres"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "password": os.getenv("DB_PASSWORD", "1234"),
}
# ─── Configuración Anti-Bloqueos ─────────────────────────────────────────────
CONCURRENCIA_PESTANAS = int(os.getenv("CONCURRENCIA_PESTANAS", "2"))
TIEMPO_ESPERA_MIN = float(os.getenv("TIEMPO_ESPERA_MIN", "1.0"))
TIEMPO_ESPERA_MAX = float(os.getenv("TIEMPO_ESPERA_MAX", "3.0"))

# ─── Rutas de Salida (respaldo local) ────────────────────────────────────────
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "base_de_datos_argos.jsonl")
OUTPUT_EXCEL = os.getenv("OUTPUT_EXCEL", "Data_Filtrada_Argos.xlsx")

SAVE_JSON_BACKUP = env_bool("SAVE_JSON_BACKUP", True)
HEADLESS = env_bool("HEADLESS", True)