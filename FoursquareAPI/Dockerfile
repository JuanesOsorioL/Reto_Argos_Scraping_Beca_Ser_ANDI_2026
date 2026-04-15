# ──────────────────────────────────────────────────────────────────────────────
# Dockerfile — Imagen Docker para Foursquare Scraper API
# ──────────────────────────────────────────────────────────────────────────────

# Base image: Python 3.12 slim (ligero)
FROM python:3.12-slim

# ─── METADATA ─────────────────────────────────────────────────────────────────
LABEL maintainer="Argos Data Team"
LABEL description="Foursquare Places API Scraper con pausa automática por rate limits"

# ─── VARIABLES DE ENTORNO ─────────────────────────────────────────────────────

# Evitar que Python escriba archivos .pyc
ENV PYTHONDONTWRITEBYTECODE=1

# Enviar output de Python directamente a stdout/stderr
ENV PYTHONUNBUFFERED=1

# ─── DIRECTORIOS ──────────────────────────────────────────────────────────────

# Crear directorio de trabajo en el contenedor
WORKDIR /app

# ─── DEPENDENCIAS SISTEMA ─────────────────────────────────────────────────────

# Instalar utilidades requeridas
RUN apt-get update && apt-get install -y \
    # Herramientas útiles para debugging
    curl \
    wget \
    # Limpieza
    && rm -rf /var/lib/apt/lists/*

# ─── DEPENDENCIAS PYTHON ───────────────────────────────────────────────────────

# Copiar requirements.txt
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# ─── CÓDIGO FUENTE ────────────────────────────────────────────────────────────

# Copiar todo el código fuente
COPY . .

# Crear directorio de salida (para output files)
RUN mkdir -p /app/output

# ─── HEALTH CHECK ─────────────────────────────────────────────────────────────

# Verificar que la API está respondiendo
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8006/health || exit 1

# ─── PUERTO ───────────────────────────────────────────────────────────────────

# Puerto por defecto (configurable en docker-compose.yml)
EXPOSE 8006

# ─── COMANDO DE INICIO ─────────────────────────────────────────────────────────

# Ejecutar la API FastAPI
CMD ["python", "api_runner.py"]
