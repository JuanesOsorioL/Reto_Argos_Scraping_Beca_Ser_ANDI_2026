# 🚀 Serper API v2.0 — Scraper Inteligente con Pausa Automática

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-12+-blue.svg)](https://www.postgresql.org/)

**Scraper de Google Search via Serper API con detección automática de rate limits, pausa inteligente y control desde n8n.**

---

## 📋 Tabla de Contenidos

1. [Características](#características)
2. [Requisitos](#requisitos)
3. [Instalación](#instalación)
4. [Configuración](#configuración)
5. [Uso](#uso)
6. [Endpoints API](#endpoints-api)
7. [Pausa Automática por Rate Limits](#pausa-automática-por-rate-limits)
8. [Integración con n8n](#integración-con-n8n)
9. [Estructura de Datos](#estructura-de-datos)
10. [Troubleshooting](#troubleshooting)

---

## ✨ Características

✅ **Detección Automática de Rate Limits (429)**
- Cuando Serper devuelve 429, pausa automáticamente
- Espera 15 minutos (configurable) y reintenta
- Guarda progreso para no perder datos

✅ **Reanudación Inteligente**
- Si la app se cae, retoma exactamente donde quedó
- Salta queries ya procesadas en PostgreSQL
- No pierde resultados

✅ **Control Manual desde API**
- POST `/pause` — Pausar scraping en curso
- POST `/resume` — Reanudar desde donde se pausó
- POST `/reset` — Borrar todo y empezar de cero

✅ **Webhooks a n8n**
- Notificaciones automáticas cuando se pause/termine
- Control total: n8n puede reanudar automáticamente
- Perfect para orquestación

✅ **Tokens Gratis Gestionados**
- ~2,500 queries disponibles en plan gratuito Serper
- Límite: 100 requests/minuto
- Sistema automático monitorea y pausa cuando sea necesario

✅ **Progreso en Tiempo Real**
- GET `/progress` — Ver estado actual (para polling)
- Archivo `serper_progress.json` actualizado constantemente
- Métricas: queries procesadas, registros insertados, etc

✅ **Guardado Configurable**
- `SAVE_JSON_BACKUP=true/false` — Guardar JSON locales
- `SAVE_PROGRESS_FILE=true/false` — Guardar archivo de progreso
- **Siempre** guarda en PostgreSQL (no se pierde nada)

---

## 🛠️ Requisitos

### Sistema
- **Python 3.10+**
- **PostgreSQL 12+**
- **pip** (gestor de paquetes Python)

### Cuentas Online
- **Serper API**: Plan gratuito en [serper.dev](https://serper.dev/)
- **n8n** (opcional): Para automatización

### Puertos
- **8004**: API FastAPI
- **5432**: PostgreSQL (si está local)
- **5678**: n8n (si está local)

---

## 📦 Instalación

### 1. Clonar o Descargar Proyecto

```bash
# Descargar los archivos en una carpeta
mkdir serper-api
cd serper-api
# Copiar los 8 archivos aquí
```

### 2. Crear Entorno Virtual

```bash
# macOS/Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar PostgreSQL

```bash
# Crear base de datos (si no existe)
createdb postgres

# O en psql:
CREATE DATABASE postgres;
```

**Nota**: Puedes usar una BD diferente cambiando `DB_NAME` en `.env`.

---

## ⚙️ Configuración

### 1. Crear/Editar `.env`

Copiar el `.env` incluido y actualizar:

```env
# ─── SERPER API ───────────────────────────────────────────────────────────
# Obtener de: https://serper.dev/
SERPER_API_KEY=tu_api_key_aqui

# ─── BASE DE DATOS ─────────────────────────────────────────────────────────
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=1234

# ─── CONTROL DE GUARDADO ──────────────────────────────────────────────────
SAVE_JSON_BACKUP=false          # true = guardar JSON, false = no guardar
SAVE_PROGRESS_FILE=true         # Archivo de progreso

# ─── PAUSA AUTOMÁTICA POR RATE LIMIT ───────────────────────────────────
AUTO_RESUME_ON_RATE_LIMIT=true  # Auto-reintentar cuando 429
RATE_LIMIT_SLEEP_SECONDS=900    # 15 minutos de espera
MAX_CONSECUTIVE_RATE_LIMITS=20  # Máximo de reintentos

# ─── WEBHOOKS n8n ─────────────────────────────────────────────────────
N8N_WEBHOOK_URL=http://n8n:5678/webhook/serper-callback

# ─── PUERTO API ────────────────────────────────────────────────────────
PORT=8004
```

**Campos críticos:**
- `SERPER_API_KEY`: ⭐ **OBLIGATORIO** — sin esto no funciona
- `DB_HOST`, `DB_USER`, `DB_PASSWORD`: Para conectar a PostgreSQL
- `RATE_LIMIT_SLEEP_SECONDS`: Cuánto esperar cuando hay 429

### 2. Verificar Configuración

```bash
python config.py
```

Debe mostrar un resumen de la configuración sin errores.

---

## 🚀 Uso

### Modo 1: Línea de Comandos (Testing)

```bash
# Prueba rápida (2 keywords × 2 ciudades)
python -c "import asyncio; from main import do_scrape; asyncio.run(do_scrape(limit_keywords=2, limit_cities=2))"

# Producción completo (18 keywords × 70 ciudades = 1,260 queries)
python -c "import asyncio; from main import do_scrape; asyncio.run(do_scrape())"
```

### Modo 2: API HTTP (Recomendado)

#### Iniciar el servidor

```bash
python api_runner.py
```

Verás:
```
🚀 SERPER API — INICIANDO
════════════════════════════════════════════════════════════════════════════════
  Puerto:           http://localhost:8004
  Swagger:          http://localhost:8004/docs
  Webhook n8n:      http://n8n:5678/webhook/serper-callback
  Progress file:    serper_progress.json
════════════════════════════════════════════════════════════════════════════════
```

Luego usa `curl` o Postman para controlar:

---

## 📡 Endpoints API

### Health Check

```bash
curl http://localhost:8004/health
# {"status":"ok","code":200}
```

### Iniciar Scraping

```bash
# Producción completo
curl -X POST http://localhost:8004/scrape/serper

# Prueba rápida (2x2)
curl -X POST http://localhost:8004/scrape/serper/prueba
```

Respuesta:
```json
{
  "status": "iniciado",
  "run_id": "a1b2c3d4-e5f6-7890",
  "inicio": "2024-01-20T10:30:00.123456",
  "tipo_ejecucion": "produccion",
  "mensaje": "Scraping iniciado. Usa GET /progress para monitorear."
}
```

### Ver Progreso (Para Polling)

```bash
curl http://localhost:8004/progress

# Respuesta (actualizada en tiempo real):
{
  "run_id": "a1b2c3d4-e5f6-7890",
  "status": "corriendo",
  "queries_hechas": 45,
  "queries_total": 1260,
  "registros_nuevos": 235,
  "aprobados_argos": 78,
  "ultima_query_ok": "ferreterías en Bogotá, Colombia",
  "consecutive_rate_limits": 0
}
```

### Pausar

```bash
curl -X POST http://localhost:8004/pause
# {"status":"ok","mensaje":"Pausa solicitada."}
```

La app terminará limpiamente, guardará progreso, y puedes reanudar.

### Reanudar

```bash
curl -X POST http://localhost:8004/resume
# {"status":"iniciado","run_id":"nuevo-uuid",...}
```

Continúa EXACTAMENTE donde se pausó.

### Reset (⚠️ PELIGROSO)

```bash
curl -X POST http://localhost:8004/reset
# {"status":"ok","mensaje":"Todo reseteado..."}
```

⚠️ **CUIDADO**: Borra:
- Todos los registros en PostgreSQL
- `serper_progress.json`
- Archivos JSON locales

### Listar Endpoints

```bash
curl http://localhost:8004/endpoints
```

---

## 🔄 Pausa Automática por Rate Limits

### Flujo Automático

```
1. Serper responde 429 (rate limit)
   ↓
2. Sistema detecta SerperRateLimitError
   ↓
3. Guarda estado en serper_progress.json
   ↓
4. Espera 900s (15 minutos, configurable)
   ↓
5. Reintenta la MISMA query
   ↓
6. Si éxito → continúa normal
   Si falla → espera de nuevo (máx 20 reintentos)
   Si agota → pausa permanente
```

### Cómo n8n Detecta y Reacciona

n8n hace polling cada 1-2 minutos:

```
GET /progress
```

Si ve:
```json
{
  "status": "pausado_sin_tokens",
  "ultima_query_error": "...429...",
  "consecutive_rate_limits": 3
}
```

n8n puede:
1. **Notificar** por Telegram/Email
2. **Esperar** otros 15 minutos
3. **Llamar** POST `/resume` automáticamente

---

## 🔗 Integración con n8n

### 1. Crear Webhook en n8n

1. Abrir n8n
2. Crear nuevo workflow
3. Agregar nodo **"Webhook"**
4. Copiar URL (ej: `http://localhost:5678/webhook/serper-callback`)
5. Pegar en `.env` como `N8N_WEBHOOK_URL`

### 2. Flujo en n8n

```
┌─────────────────┐
│ Manual Trigger  │ (botón para empezar manualmente)
└────────┬────────┘
         ↓
┌─────────────────────────────┐
│ HTTP: POST /scrape/serper   │ (iniciar scraping)
└────────┬────────────────────┘
         ↓
┌─────────────────────────────┐
│ Wait: 2 minutos             │ (esperar antes de polling)
└────────┬────────────────────┘
         ↓
┌─────────────────────────────┐
│ HTTP: GET /progress         │ (ver estado)
└────────┬────────────────────┘
         ↓
┌─────────────────────────────┐
│ IF: Revisar status          │
├─────────────────────────────┤
│ status == "corriendo" →     │ vuelve a Wait
│ status == "pausado_sin_tokens" → espera + POST /resume
│ status == "ok" →            │ siguiente paso
│ status == "error" →         │ notificar Error
└─────────────────────────────┘
```

### 3. Variables de Entorno en n8n

Dentro de n8n:

```javascript
// En expresiones:
$env.SERPER_API_URL = "http://host.docker.internal:8004"
$env.TELEGRAM_BOT_TOKEN = "tu_token"
```

---

## 🗄️ Estructura de Datos

### PostgreSQL

**Tabla: `raw.serper_consultas_construccion`**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | INT | Auto-increment |
| `run_id` | UUID | UUID del run |
| `query` | TEXT | Query exacta |
| `raw_response` | JSONB | Respuesta de Serper completa |

**Tabla: `raw.serper_resultados_construccion`**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `hash_id` | TEXT | Para deduplicación |
| `nombre` | TEXT | Nombre del negocio |
| `telefono` | TEXT | Teléfono principal |
| `whatsapp` | TEXT | Link WhatsApp |
| `correo_electronico` | TEXT | Email |
| `score` | INT | Score Argos |
| `aprobado_argos` | BOOL | ¿Pasó filtro? |
| `scraped_email` | TEXT | Email extraído de URL |
| `scraped_phone` | TEXT | Teléfono de URL |
| ... | ... | +40 campos más |

### Archivo de Progreso

**`serper_progress.json`** (Actualizado cada query)

```json
{
  "run_id": "uuid",
  "status": "corriendo",
  "inicio": "2024-01-20T10:30:00",
  "queries_hechas": 45,
  "queries_total": 1260,
  "registros_nuevos": 235,
  "registros_duplicados": 8,
  "aprobados_argos": 78,
  "errores_totales": 0,
  "consecutive_rate_limits": 0,
  "ultima_query_ok": "ferreterías en Bogotá, Colombia"
}
```

---

## 🐛 Troubleshooting

### Error: "SERPER_API_KEY no está configurada"

**Problema**: Falta la key en `.env`

**Solución**:
```bash
# Editar .env
SERPER_API_KEY=tu_key_aqui

# Obtener key en: https://serper.dev/ (registro gratuito)
```

### Error: "psycopg2.OperationalError: FATAL: database postgres does not exist"

**Problema**: PostgreSQL no está corriendo o la BD no existe

**Solución**:
```bash
# Crear BD
createdb postgres

# O cambiar en .env
DB_NAME=mi_bd_existente
```

### Scraping se queda en "pausado_sin_tokens"

**Problema**: Alcanzó MAX_CONSECUTIVE_RATE_LIMITS reintentos

**Solución**:
```bash
# Opción 1: Esperar hasta mañana (se renuevan tokens)
# Opción 2: Llamar POST /resume mañana
curl -X POST http://localhost:8004/resume

# Opción 3: Usar cuenta Serper de pago (más requests)
```

### JSON no se guarda aunque SAVE_JSON_BACKUP=true

**Problema**: Falta crear directorio `output/`

**Solución**:
```bash
mkdir output
# Vuelve a ejecutar
```

### n8n no recibe webhook

**Problema**: N8N_WEBHOOK_URL incorrea o n8n no está escuchando

**Verificar**:
```bash
# Probar webhook manualmente
curl -X POST http://localhost:8004/test/callback

# Debe retornar: {"status":"ok","webhook_n8n":"..."}
```

---

## 📊 Métricas y Monitoreo

### Ver métricas finales

```bash
curl http://localhost:8004/status

{
  "status": "ok",
  "metricas": {
    "run_id": "uuid",
    "duracion": "45m 30s",
    "queries_total": 1260,
    "queries_hechas": 1245,
    "queries_saltadas": 15,
    "registros_nuevos": 3450,
    "duplicados": 200,
    "aprobados_argos": 1200,
    "errores_totales": 5
  }
}
```

### Logs en tiempo real

```bash
# Terminal 1: Ver logs de la API
tail -f nohup.out

# Terminal 2: Monitorear progreso
watch -n 5 'curl http://localhost:8004/progress | jq'
```

---

## 🎯 Casos de Uso

### Uso 1: Ejecutar Manualmente

```bash
python api_runner.py &

# En otra terminal:
curl -X POST http://localhost:8004/scrape/serper/prueba
```

### Uso 2: Cron Job + Notificaciones

```bash
# En crontab (cada domingo a las 8 AM):
0 8 * * 0 curl -X POST http://localhost:8004/scrape/serper 2>/dev/null
```

### Uso 3: n8n Automático

Workflow que:
1. Cada domingo dispara scraping
2. Cada 2 min verifica progreso
3. Si "pausado_sin_tokens" → espera 15 min y resume
4. Al terminar → notifica por Telegram

---

## 📝 Cambios desde v1.0

- ✅ Detección de 429 (rate limit)
- ✅ Pausa automática con reintento
- ✅ Webhooks a n8n
- ✅ Endpoint `/reset`
- ✅ Archivo de progreso en tiempo real
- ✅ Documentación línea por línea
- ✅ Manejo robusto de errores

---

## 📄 Licencia

Uso libre. Basado en Serper API.

---

## 🤝 Contacto

¿Preguntas o problemas?

1. Revisar [Troubleshooting](#troubleshooting)
2. Verificar logs: `tail -f *.log`
3. Probar endpoints con `/test/callback`

---

**Última actualización**: Enero 2024  
**Versión**: 2.0.0
