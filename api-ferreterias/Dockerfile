FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar codigo
COPY . .

# Crear carpetas de respaldo
RUN mkdir -p respaldos/campos_dudosos respaldos/posibles_matches respaldos/reporte_ejecucion

EXPOSE 8009

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009", "--workers", "2"]
