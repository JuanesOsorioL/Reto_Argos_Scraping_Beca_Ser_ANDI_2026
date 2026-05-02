import os
from dotenv import load_dotenv

load_dotenv()

# Base de datos
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "argos")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "1234")

# API
PORT = int(os.getenv("ANALISIS_PORT", "8008"))

# Umbral: municipios con menos de este número de registros en total se consideran "baja cobertura"
UMBRAL_BAJO_COBERTURA = int(os.getenv("UMBRAL_BAJO_COBERTURA", "5"))

# Keywords recomendadas para enviar a Serper (las más efectivas para municipios con poca data)
KEYWORDS_SERPER = [
    "ferreterias",
    "depositos de materiales",
    "distribuidora de construccion",
    "cemento al por mayor",
    "bloqueras",
    "ladrilleras",
]

# Ciudades con buena cobertura en Foursquare (normalizadas: sin tildes, minúsculas)
GRANDES_CIUDADES = [
    "bogota", "medellin", "cali", "barranquilla", "cartagena",
    "bucaramanga", "pereira", "manizales", "ibague", "cucuta",
    "santa marta", "villavicencio", "armenia", "pasto", "monteria",
    "neiva", "popayan", "valledupar", "sincelejo", "riohacha",
]

# Tablas a consultar (fuente → schema.tabla)
TABLAS_FUENTES = {
    "rues":               "raw.rues_detalle",
    "google_maps":        "raw.google_maps_ferreterias",
    "paginas_amarillas":  "raw.paginas_amarillas_ferreterias",
    "openstreetmap":      "raw.overpass_ferreterias",
}
