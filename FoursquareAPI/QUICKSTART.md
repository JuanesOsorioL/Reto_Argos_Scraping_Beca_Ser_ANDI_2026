# ⚡ Quick Start — 5 Minutos para Empezar

## 🎯 Objetivo

Tener el scraper de Foursquare corriendo y recolectando ferreterías en 5 minutos.

---

## ✅ Paso 1: Preparar .env (1 minuto)

Crea o edita `.env`:

```bash
# Base de datos
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=1234

# Foursquare API — CAMBIAR ESTO CON TU KEY
FSQ_API_KEY=tu_api_key_aqui

# Pausa automática por rate limit
AUTO_PAUSE_ON_RATE_LIMIT=true
RATE_LIMIT_SLEEP_SECONDS=3600
MAX_CONSECUTIVE_RATE_LIMITS=5

# JSON Backup
SAVE_JSON_BACKUP=true
SAVE_PROGRESS_FILE=true

# API Server
API_PORT=8006
```

**⚠️ Paso crítico**: Obtén tu API Key en https://developer.foursquare.com

---

## ✅ Paso 2: Opción A - Docker (Recomendado)

### Si usas Docker:

```bash
# Iniciar PostgreSQL + API
docker-compose up -d

# Esperar 10 segundos a que levante
sleep 10

# Verificar que está corriendo
docker-compose ps
```

**✓ Listo**. API en: http://localhost:8006

---

## ✅ Paso 2: Opción B - Local

### Si usas Python local:

```bash
# 1. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Iniciar API
python api_runner.py
```

**✓ Listo**. API en: http://localhost:8006

---

## ✅ Paso 3: Disparar Scraping

En otra terminal:

```bash
curl -X POST http://localhost:8006/scrape/foursquare
```

Response:
```json
{
  "status": "iniciado",
  "run_id": "abc-123-def...",
  "inicio": "2024-01-01T12:00:00"
}
```

**✓ Scraping disparado**

---

## ✅ Paso 4: Monitorear Progreso

Ver estado en tiempo real:

```bash
# Estado actual
curl http://localhost:8006/status

# Progreso detallado
curl http://localhost:8006/progress

# Estadísticas de BD
curl http://localhost:8006/stats
```

O accede a la documentación interactiva:
- http://localhost:8006/docs

---

## ✅ Paso 5: Exportar Datos

Una vez completado el scraping:

```bash
# Exportar a Excel
python data_exporter.py

# O solo aprobados
python data_exporter.py --aprobados
```

Genera: `foursquare_ferreterias.xlsx`

---

## 🎉 ¡Completado!

Ahora tienes:

✅ 1,500+ ferreterías de Colombia en PostgreSQL
✅ JSON de respaldo (si habilitaste SAVE_JSON_BACKUP)
✅ Progreso guardado automáticamente
✅ Pausa automática por rate limit
✅ API HTTP para control remoto

---

## 📋 Próximos Pasos

### Si quieres integrar con n8n:

1. Abre http://localhost:5678
2. Crea webhook para recibir notificaciones
3. Configura URLs en .env (WEBHOOK_ON_*)
4. n8n recibirá notificaciones cuando se pausa/completa

### Si quieres monitorear con Telegram:

1. Crea workflow en n8n
2. Añade acción "Send Telegram Message"
3. n8n te notifica en Telegram cuando hay cambios

### Si quieres ejecutar cada hora:

1. Usa cron o task scheduler
2. O configura webhook en n8n para disparar cada hora:
   ```bash
   curl -X POST http://localhost:8006/scrape/foursquare
   ```

---

## 🆘 Solución Rápida de Problemas

| Problema | Solución |
|----------|----------|
| **Error 401 API Key** | Verificar FSQ_API_KEY en .env |
| **Error BD no conecta** | Verificar PostgreSQL está corriendo |
| **Error 403 Rate Limit** | Normal, espera a que se reaunude automáticamente |
| **Puerto 8006 en uso** | Cambiar API_PORT en .env |
| **Logs confusos** | Ver con `docker-compose logs -f foursquare` |

---

## 📚 Documentación Completa

Para más detalles, ver: **README.md**

¡Listo! Ahora tienes un scraper de Foursquare completamente automático. 🚀
