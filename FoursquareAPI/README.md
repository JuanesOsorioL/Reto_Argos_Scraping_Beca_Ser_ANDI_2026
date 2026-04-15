# 🌐 Foursquare Places API Scraper — Guía Completa

## 📋 Tabla de Contenidos

1. [Descripción General](#descripción-general)
2. [Requisitos](#requisitos)
3. [Instalación Local](#instalación-local)
4. [Instalación con Docker](#instalación-con-docker)
5. [Configuración](#configuración)
6. [Endpoints HTTP](#endpoints-http)
7. [Pausa Automática por Rate Limits](#pausa-automática-por-rate-limits)
8. [Integración con n8n](#integración-con-n8n)
9. [Solución de Problemas](#solución-de-problemas)

---

## 📝 Descripción General

Sistema automático para buscar ferreterías y negocios de construcción en Foursquare, con:

✅ **Detección automática de 403 (Rate Limit)**
- Pausa inteligente cuando se alcanza el límite de 5.000 requests/hora
- Reanudación automática cuando se resetea el límite
- Máximo 5 pausas para evitar loops infinitos

✅ **Guardado de datos**
- PostgreSQL (SIEMPRE, obligatorio)
- JSON backup (configurable)
- JSONL local (respaldo línea a línea)
- Archivo de progreso (configurable)

✅ **Notificaciones a n8n**
- Webhook cuando se pausa por rate limit
- Webhook cuando se completa
- Webhook cuando hay error

✅ **Control remoto vía HTTP**
- Iniciar scraping: `POST /scrape/foursquare`
- Ver estado: `GET /status`
- Ver progreso: `GET /progress`
- Pausar: `POST /pause`
- Reanudar: `POST /resume`
- Reset: `POST /reset` (borra archivos, NO la BD)

---

## 🔧 Requisitos

### Opción A: Local
- Python 3.9+
- PostgreSQL 12+
- pip

### Opción B: Docker
- Docker
- Docker Compose

### Obligatorio
- **Foursquare API Key** (gratuita, 5.000 requests/hora)
  - Obtener en: https://developer.foursquare.com

---

## 🚀 Instalación Local

### 1. Clonar o descargar el proyecto
```bash
cd /ruta/al/proyecto/foursquare
```

### 2. Crear entorno virtual
```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar .env
```bash
cp .env.example .env  # o crear uno nuevo
# Editar .env con tus valores
```

### 5. Verificar PostgreSQL
```bash
# Asegurarse de que PostgreSQL está corriendo
psql -U postgres -d postgres -c "SELECT version();"
```

### 6. Inicializar BD (opcional, se hace automáticamente)
```bash
python -c "from db import init_db; init_db()"
```

### 7. Ejecutar API
```bash
python api_runner.py
# O con uvicorn directamente:
uvicorn api_runner:app --host 0.0.0.0 --port 8006 --reload
```

La API estará en: **http://localhost:8006**
Documentación: **http://localhost:8006/docs**

---

## 🐳 Instalación con Docker

### 1. Preparar archivos

Asegurarse de tener en el directorio raíz:
- `Dockerfile`
- `docker-compose.yml`
- `.env` (o copiar de `.env.example`)
- `requirements.txt`
- Todos los archivos `.py`

### 2. Construir imagen
```bash
docker-compose build
```

### 3. Iniciar servicios
```bash
docker-compose up -d
```

Esto inicia:
- **PostgreSQL** en puerto 5432
- **Foursquare API** en puerto 8006
- **PgAdmin** en puerto 5050 (opcional, para administración)

### 4. Verificar que está corriendo
```bash
docker-compose ps
# Debe mostrar 3 servicios con estado "healthy"
```

### 5. Ver logs
```bash
docker-compose logs -f foursquare
```

### 6. Parar servicios
```bash
docker-compose down
```

---

## ⚙️ Configuración

### Archivo `.env`

#### Base de Datos
```bash
DB_HOST=localhost           # o "postgres" en Docker
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=1234
```

#### Foursquare API
```bash
FSQ_API_KEY=tu_api_key_aqui
```

#### Pausa Automática por Rate Limit
```bash
# Detectar 403 y pausar automáticamente
AUTO_PAUSE_ON_RATE_LIMIT=true

# Segundos a esperar cuando se detecta 403
# Foursquare reseta cada hora (3600 segundos)
RATE_LIMIT_SLEEP_SECONDS=3600

# Máximo de veces a pausar antes de abortar
MAX_CONSECUTIVE_RATE_LIMITS=5

# Reanudar automáticamente después de esperar
AUTO_RESUME_AFTER_PAUSE=true
```

#### JSON Backup (configurable)
```bash
# Guardar foursquare_raw_responses.json y foursquare_flat_results.json
SAVE_JSON_BACKUP=true

# Guardar foursquare_progress.json
SAVE_PROGRESS_FILE=true
```

#### Webhooks a n8n
```bash
# URL donde n8n escucha cuando se pausa
WEBHOOK_ON_PAUSE=http://localhost:5678/webhook/foursquare-pause

# URL cuando se completa
WEBHOOK_ON_COMPLETE=http://localhost:5678/webhook/foursquare-complete

# URL cuando hay error
WEBHOOK_ON_ERROR=http://localhost:5678/webhook/foursquare-error
```

#### API Server
```bash
API_PORT=8006
API_HOST=0.0.0.0
DEBUG=true
```

---

## 📡 Endpoints HTTP

### 1. Health Check
```bash
GET /health
# Response:
# {"status": "ok", "timestamp": "2024-01-01T12:00:00"}
```

### 2. Iniciar Scraping
```bash
POST /scrape/foursquare
# Response:
# {
#   "status": "iniciado",
#   "run_id": "abc123...",
#   "inicio": "2024-01-01T12:00:00"
# }
```

### 3. Ver Estado
```bash
GET /status
# Response:
# {
#   "status": "ok|error|corriendo",
#   "en_curso": true,
#   "run_id": "abc123...",
#   "inicio": "2024-01-01T12:00:00",
#   "fin": null,
#   "duracion": "45s",
#   "en_pausa": false,
#   "error": null
# }
```

### 4. Ver Progreso Detallado
```bash
GET /progress
# Response:
# {
#   "estado": "completado|pausado|corriendo",
#   "total_procesadas": 70,
#   "total_insertadas": 1500,
#   "total_duplicadas": 200,
#   "total_aprobadas": 1200,
#   "rate_limit_count": 1
# }
```

### 5. Pausar Scraping (manual)
```bash
POST /pause
# Response:
# {
#   "status": "pausado",
#   "razon": "manual"
# }
```

### 6. Reanudar Scraping
```bash
POST /resume
# Response:
# {
#   "status": "reanudado",
#   "run_id": "abc123..."
# }
```

### 7. Reset (borrar archivos de progreso)
```bash
POST /reset
# Response:
# {
#   "status": "reset",
#   "archivos_borrados": [
#     "foursquare_progress.json",
#     "foursquare_ferreterias.jsonl",
#     "output/foursquare_raw_responses.json",
#     "output/foursquare_flat_results.json"
#   ],
#   "nota": "PostgreSQL no fue borrado"
# }
```

### 8. Estadísticas de BD
```bash
GET /stats
# Response:
# {
#   "status": "ok",
#   "datos": {
#     "total_registros": 1500,
#     "aprobados_argos": 1200,
#     "municipios_unicos": 35,
#     "con_telefono": 1400,
#     "con_website": 900
#   }
# }
```

---

## ⏸️ Pausa Automática por Rate Limits

### ¿Cómo funciona?

1. **Límites de Foursquare**
   - 5.000 requests/hora a endpoints `/places/*`
   - 500 requests/hora a otros endpoints
   - Respuesta: **403** cuando se alcanza el límite

2. **Detección**
   - scraper.py detecta status code 403
   - Lee header `X-RateLimit-Reset` (UNIX timestamp)
   - Lanza `RateLimitException`

3. **Pausa Automática** (si `AUTO_PAUSE_ON_RATE_LIMIT=true`)
   - Guarda progreso en `foursquare_progress.json`
   - Guarda estado en PostgreSQL
   - Envía webhook a n8n (si configurado)
   - Espera `RATE_LIMIT_SLEEP_SECONDS` segundos

4. **Reanudación Automática** (si `AUTO_RESUME_AFTER_PAUSE=true`)
   - Después de esperar, reintenta la búsqueda
   - Continúa donde quedó (desde `foursquare_progress.json`)

### Ejemplo de Progreso Guardado

```json
{
  "run_id": "abc123...",
  "estado": "pausado",
  "razon": "rate_limit_403",
  "combinacion_actual": {
    "keyword": "ferretería",
    "ciudad": "Bogotá"
  },
  "combo_numero": 15,
  "total_combinaciones": 350,
  "total_insertadas": 1500,
  "total_duplicadas": 200,
  "rate_limit_count": 1,
  "fecha_actualizacion": "2024-01-01T12:00:00"
}
```

---

## 🔗 Integración con n8n

### Paso 1: Crear Webhook en n8n

1. Abre n8n: http://localhost:5678
2. Crea nuevo workflow
3. Añade nodo **Webhook**
4. Copia las 3 URLs:
   - **ON_PAUSE**: http://localhost:5678/webhook/foursquare-pause
   - **ON_COMPLETE**: http://localhost:5678/webhook/foursquare-complete
   - **ON_ERROR**: http://localhost:5678/webhook/foursquare-error

### Paso 2: Configurar en `.env`

```bash
WEBHOOK_ON_PAUSE=http://host.docker.internal:5678/webhook/foursquare-pause
WEBHOOK_ON_COMPLETE=http://host.docker.internal:5678/webhook/foursquare-complete
WEBHOOK_ON_ERROR=http://host.docker.internal:5678/webhook/foursquare-error
```

### Paso 3: Crear Workflow en n8n

Ejemplo básico:

```
Webhook (Recibe notificaciones)
  ↓
If (estado == "pausado")
  ├→ Esperar 60 minutos
  ├→ Reanudar: POST /resume
  └→ Log: "Reanudando..."
  ↓
Telegram: Enviar notificación
```

### Paso 4: Disparar Scraping

Puedes disparar desde n8n con este nodo:

```
HTTP Request
  Method: POST
  URL: http://host.docker.internal:8006/scrape/foursquare
```

---

## 🐛 Solución de Problemas

### Error: "403: Rate Limit alcanzado"

```
✓ Normal si AUTO_PAUSE_ON_RATE_LIMIT=true
✓ El sistema debe pausar y reanudar automáticamente
✓ Revisa foursquare_progress.json para ver estado
```

### Error: "401: API key inválida"

```bash
# Solución:
# 1. Verificar FSQ_API_KEY en .env
# 2. Obtener nueva key en https://developer.foursquare.com
# 3. Reiniciar API: docker-compose restart foursquare
```

### Error: "Conexión rechazada a PostgreSQL"

```bash
# Solución:
# 1. Verificar que PostgreSQL está corriendo
# 2. Verificar DB_HOST, DB_USER, DB_PASSWORD en .env
# 3. Probar conexión: psql -U postgres -h localhost
```

### Error: "Puerto 8006 ya en uso"

```bash
# Solución:
# Cambiar puerto en docker-compose.yml:
# ports:
#   - "8007:8006"  # Cambiar 8006 a otro puerto
```

### Error: "Volume foursquare_postgres_data no existe"

```bash
# Solución:
# Docker lo crea automáticamente
# Si falla, eliminar todo y reiniciar:
docker-compose down -v
docker-compose up -d
```

### ¿Cómo sé si hay datos en la BD?

```bash
# Conectar a PostgreSQL:
psql -U postgres -h localhost -d postgres

# Dentro de psql:
SELECT COUNT(*) FROM raw.foursquare_ferreterias;
SELECT COUNT(DISTINCT municipio) FROM raw.foursquare_ferreterias;
SELECT aprobado_argos, COUNT(*) FROM raw.foursquare_ferreterias GROUP BY aprobado_argos;
```

---

## 📊 Exportar Datos

### A Excel

```bash
# Todos los registros:
python data_exporter.py

# Solo aprobados:
python data_exporter.py --aprobados
```

Genera: `foursquare_ferreterias.xlsx`

### A JSON

Ya se genera automáticamente (si `SAVE_JSON_BACKUP=true`):

- `output/foursquare_raw_responses.json` — Respuestas crudas de Foursquare
- `output/foursquare_flat_results.json` — Registros normalizados

### Desde n8n

Puedes crear un workflow que lee de PostgreSQL y exporta:

```
HTTP Request (GET /stats)
  ↓
Query Database (SELECT * FROM raw.foursquare_ferreterias)
  ↓
Generate Excel / CSV
  ↓
Send Email / Upload S3
```

---

## 📞 Soporte

- **Documentación de config**: Ver archivo `.env`
- **Códigos de error HTTP**: https://developer.foursquare.com/docs
- **Rate limits**: https://developer.foursquare.com/docs/places-api/rate-limits

---

## 📄 Licencia

Proyecto privado de Argos Data Team.
