"""config.py - Configuracion global"""
import os

class Config:
    ENV:             str  = os.getenv("ENVIRONMENT", "dev")
    DEBUG:           bool = ENV == "dev"
    LOG_LEVEL:       str  = os.getenv("LOG_LEVEL", "INFO")

    DATABASE_URL:    str  = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost:5432/ferreterias_db")

    # OpenRouter (IA gratuita - principal)
    OPENROUTER_API_KEY:  str  = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MAX_MODELS: int = int(os.getenv("OPENROUTER_MAX_MODELS", "3"))
    PREFERIR_OPENROUTER: bool = os.getenv("PREFERIR_OPENROUTER", "true").lower() == "true"

    # Anthropic Claude (fallback de pago)
    ANTHROPIC_API_KEY:   str  = os.getenv("ANTHROPIC_API_KEY", "")

    # IA deduplicacion
    USAR_IA_DUPLICADOS:  bool = os.getenv("USAR_IA_DUPLICADOS", "true").lower() == "true"
    IA_MIN_SCORE:        int  = int(os.getenv("IA_MIN_SCORE", "68"))
    IA_MAX_SCORE:        int  = int(os.getenv("IA_MAX_SCORE", "74"))
    IA_BATCH_SIZE:       int  = int(os.getenv("IA_BATCH_SIZE", "100"))
    IA_MODEL:            str  = os.getenv("IA_MODEL", "claude-opus-4-5")
    IA_MAX_TOKENS:       int  = int(os.getenv("IA_MAX_TOKENS", "500"))

    # Serper - Google (validacion sin RUES)
    SERPER_API_KEY:      str  = os.getenv("SERPER_API_KEY", "")
    VALIDAR_SIN_RUES:    bool = os.getenv("VALIDAR_SIN_RUES", "true").lower() == "true"
    VALIDAR_LIMITE:      int  = int(os.getenv("VALIDAR_LIMITE", "500"))

    # RUES inactivos
    INCLUIR_RUES_INACTIVOS: bool = os.getenv("INCLUIR_RUES_INACTIVOS", "true").lower() == "true"
    # Empresas en liquidación (aplica a todas las fuentes)
    INCLUIR_EN_LIQUIDACION: bool = os.getenv("INCLUIR_EN_LIQUIDACION", "false").lower() == "true"

    # n8n webhook
    N8N_WEBHOOK_URL:     str  = os.getenv("N8N_WEBHOOK_URL", "")
    API_BASE_URL:        str  = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Normalización
    SIMILARITY_THRESHOLD_NOMBRE: float = float(os.getenv("SIMILARITY_THRESHOLD_NOMBRE", "0.75"))
    DISTANCIA_MAX_METROS:        int   = int(os.getenv("DISTANCIA_MAX_METROS", "50"))

    # Archivos de respaldo
    CREAR_JSON_CAMPOS_DUDOSOS:   bool = os.getenv("CREAR_JSON_CAMPOS_DUDOSOS", "true").lower() == "true"
    RUTA_CAMPOS_DUDOSOS:         str  = os.getenv("RUTA_CAMPOS_DUDOSOS", "respaldos/campos_dudosos")
    CREAR_JSON_POSIBLES_MATCHES: bool = os.getenv("CREAR_JSON_POSIBLES_MATCHES", "true").lower() == "true"
    RUTA_POSIBLES_MATCHES:       str  = os.getenv("RUTA_POSIBLES_MATCHES", "respaldos/posibles_matches")
    CREAR_JSON_REPORTE_EJECUCION: bool = True
    RUTA_REPORTE_EJECUCION:      str  = os.getenv("RUTA_REPORTE_EJECUCION", "respaldos/reporte_ejecucion")
    CREAR_CSV_CLEAN_EMPRESAS:    bool = os.getenv("CREAR_CSV_CLEAN_EMPRESAS", "false").lower() == "true"
    RUTA_CSV_CLEAN_EMPRESAS:     str  = os.getenv("RUTA_CSV_CLEAN_EMPRESAS", "respaldos/clean_empresas.csv")
    CREAR_EXCEL_CLEAN_EMPRESAS:  bool = os.getenv("CREAR_EXCEL_CLEAN_EMPRESAS", "false").lower() == "true"
    RUTA_EXCEL_CLEAN_EMPRESAS:   str  = os.getenv("RUTA_EXCEL_CLEAN_EMPRESAS", "respaldos/clean_empresas.xlsx")

config = Config()
