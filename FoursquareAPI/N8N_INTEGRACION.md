# 🔗 Integración con n8n — Guía Completa

Este documento explica cómo integrar el Foursquare Scraper con n8n para automatización y notificaciones.

---

## 📋 Tabla de Contenidos

1. [Conceptos Básicos](#conceptos-básicos)
2. [Paso 1: Setup n8n](#paso-1-setup-n8n)
3. [Paso 2: Crear Webhooks](#paso-2-crear-webhooks)
4. [Paso 3: Workflows](#paso-3-workflows)
5. [Paso 4: Notificaciones Telegram](#paso-4-notificaciones-telegram)
6. [Ejemplos Avanzados](#ejemplos-avanzados)

---

## 🎯 Conceptos Básicos

### ¿Por qué n8n?

- **Sin código**: Integración visual por arrastrar y soltar
- **Webhooks**: Recibe notificaciones del scraper
- **Automatización**: Disparar acciones automáticamente
- **Notificaciones**: Telegram, Email, Slack, etc.
- **Gratuito**: Self-hosted

### Flujo General

```
Foursquare Scraper
        ↓
Detecta 403 (Rate Limit)
        ↓
Envía webhook a n8n
        ↓
n8n recibe JSON con:
├─ estado: "pausado"
├─ combinacion_actual: {...}
├─ total_insertadas: 1200
└─ rate_limit_count: 1
        ↓
n8n ejecuta acciones:
├─ Notificar a Telegram
├─ Guardar a Google Sheets
├─ Esperar 1 hora
└─ Reanudar automáticamente
```

---

## 📌 Paso 1: Setup n8n

### 1.1 Instalar n8n (Self-hosted)

```bash
# Opción A: npm
npm install -g n8n
n8n

# Opción B: Docker
docker run -it --rm --name n8n -p 5678:5678 n8nio/n8n

# Opción C: Docker Compose (recomendado)
# Ver archivo docker-compose.yml en el proyecto
docker-compose up -d
```

### 1.2 Acceder a n8n

- **URL**: http://localhost:5678
- **Crear cuenta**: Email + contraseña

---

## 🔌 Paso 2: Crear Webhooks

### 2.1 Crear Webhook para "ON PAUSE"

1. Abre n8n
2. **Crea nuevo workflow**: `Foursquare - On Pause`
3. Añade nodo **Webhook**:
   - Method: `POST`
   - Path: `/webhook/foursquare-pause`
   - Respuesta: `200` (OK)
4. **Copia la URL completa**:
   - Ejemplo: `http://localhost:5678/webhook/foursquare-pause`

### 2.2 Crear Webhook para "ON COMPLETE"

Repite el proceso pero con Path: `/webhook/foursquare-complete`

### 2.3 Crear Webhook para "ON ERROR"

Repite el proceso pero con Path: `/webhook/foursquare-error`

### 2.4 Guardar URLs en .env

```bash
# En tu archivo .env del scraper:
WEBHOOK_ON_PAUSE=http://localhost:5678/webhook/foursquare-pause
WEBHOOK_ON_COMPLETE=http://localhost:5678/webhook/foursquare-complete
WEBHOOK_ON_ERROR=http://localhost:5678/webhook/foursquare-error
```

---

## 🔄 Paso 3: Workflows

### Workflow 1: Notificar Cuando Se Pausa

**Objetivo**: Recibir notificación cuando se alcanza rate limit (403).

```
Webhook (ON PAUSE)
        ↓
Verificar estado
        ├─ Si estado = "pausado" → Notify
        └─ Si estado = "error" → Error Handler
        ↓
Telegram: "⏸️ Scraper pausado por rate limit"
"Esperando a reanudar..."
```

**Pasos en n8n:**

1. Workflow: `Foursquare - On Pause`
2. Nodo: **Webhook** (recibe POST)
   ```
   - Method: POST
   - Path: /webhook/foursquare-pause
   ```

3. Nodo: **IF** (condicional)
   ```
   Condición: $.estado == "pausado"
   ```

4. Rama TRUE: **Telegram**
   ```
   Chat ID: tu_chat_id
   Mensaje: "⏸️ Foursquare pausado por rate limit\n"
            + "Combinación: {{$node.Webhook.json.combinacion_actual.keyword}} - {{$node.Webhook.json.combinacion_actual.ciudad}}\n"
            + "Insertados: {{$node.Webhook.json.total_insertadas}}\n"
            + "Reanudará en 1 hora..."
   ```

---

### Workflow 2: Notificar Cuando Completa

**Objetivo**: Resumen cuando termina el scraping.

```
Webhook (ON COMPLETE)
        ↓
Telegram:
"✅ Scraping completado!
Registros: 1500
Aprobados: 1200
Ciudades: 35"
```

**Pasos en n8n:**

1. Workflow: `Foursquare - On Complete`
2. Nodo: **Webhook**
   ```
   Path: /webhook/foursquare-complete
   ```

3. Nodo: **Telegram**
   ```
   Mensaje: "✅ Scraping completado!\n" +
            "Registros insertados: {{$node.Webhook.json.total_insertadas}}\n" +
            "Aprobados Argos: {{$node.Webhook.json.total_aprobadas}}\n" +
            "Pausas por 403: {{$node.Webhook.json.rate_limit_count}}"
   ```

---

### Workflow 3: Disparar Scraping Cada Hora

**Objetivo**: Ejecutar automáticamente cada hora.

```
Cron: "0 * * * *" (cada hora)
        ↓
HTTP Request: POST /scrape/foursquare
        ↓
Log: "Scraping disparado"
```

**Pasos en n8n:**

1. Workflow: `Foursquare - Daily Scheduler`
2. Nodo: **Cron**
   ```
   Mode: Every hour
   Minute: 0
   (Se ejecuta a las 00:00, 01:00, 02:00, etc.)
   ```

3. Nodo: **HTTP Request**
   ```
   Method: POST
   URL: http://localhost:8006/scrape/foursquare
   (Si está en Docker: http://host.docker.internal:8006)
   ```

4. Nodo: **Telegram**
   ```
   Mensaje: "🚀 Scraping disparado automáticamente"
   ```

---

### Workflow 4: Reanudar Automáticamente Después de 1 Hora

**Objetivo**: Si se pausa por rate limit, esperar 1 hora y reanudar.

```
Webhook (ON PAUSE)
        ↓
Wait: 3600 segundos (1 hora)
        ↓
HTTP Request: POST /resume
        ↓
Telegram: "✅ Reanudando scraping"
```

**Pasos en n8n:**

1. Workflow: `Foursquare - Auto Resume`
2. Nodo: **Webhook**
   ```
   Path: /webhook/foursquare-pause
   ```

3. Nodo: **Wait**
   ```
   Wait: 3600 seconds (1 hour)
   ```

4. Nodo: **HTTP Request**
   ```
   Method: POST
   URL: http://localhost:8006/resume
   ```

5. Nodo: **Telegram**
   ```
   Mensaje: "✅ Reanudando scraping automáticamente"
   ```

---

## 💬 Paso 4: Notificaciones Telegram

### 4.1 Crear Bot Telegram

1. Abre Telegram
2. Busca **@BotFather**
3. Comando: `/newbot`
4. Sigue instrucciones:
   - Nombre: "Foursquare Notifier"
   - Username: "foursquare_notifier_bot"
5. **Copia TOKEN** (ejemplo: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 4.2 Obtener Chat ID

1. Abre tu bot en Telegram
2. Envía mensaje: `/start`
3. Abre: `https://api.telegram.org/botTOKEN/getUpdates`
   - Reemplaza TOKEN con tu token
4. Busca `"chat":{"id": CHAT_ID}`

### 4.3 Configurar en n8n

En cada nodo **Telegram**:

```
Credentials:
├─ Bot Token: tu_token_aqui (123456:ABC-DEF...)
├─ Chat ID: tu_chat_id_aqui (123456789)
└─ Disable Notification: false
```

### 4.4 Prueba

Envía un mensaje de prueba desde n8n:

```
Telegram Message: "Hola, este es un test ✅"
```

---

## 🚀 Ejemplos Avanzados

### Ejemplo 1: Guardar Datos en Google Sheets

```
Webhook (ON COMPLETE)
        ↓
Google Sheets: Append
├─ Spreadsheet: "Foursquare Scraping"
├─ Sheet: "Runs"
└─ Values:
    ├─ Fecha: {{new Date().toISOString()}}
    ├─ Registros: {{$node.Webhook.json.total_insertadas}}
    ├─ Aprobados: {{$node.Webhook.json.total_aprobadas}}
    └─ Pausas: {{$node.Webhook.json.rate_limit_count}}
```

### Ejemplo 2: Enviar Email si Hay Error

```
Webhook (ON ERROR)
        ↓
IF: $.tipo_error == "auth_401"
        ├─ Email: "Error de API Key"
        └─ Body: "API Key inválida. Revisa FSQ_API_KEY en .env"
```

### Ejemplo 3: Actualizar Dashboard Metabase

```
Webhook (ON COMPLETE)
        ↓
HTTP Request: POST /api/dashboard/refresh
├─ Dashboard ID: foursquare-stats
└─ Refresh data
```

### Ejemplo 4: Slack en lugar de Telegram

```
Reemplaza nodo Telegram por Slack
├─ Channel: #foursquare-logs
└─ Message: Mismo formato que Telegram
```

---

## 📊 Ejemplo Completo: Monitoreo Completo

Este workflow recibe eventos del scraper y notifica en tiempo real:

```
┌─ Webhook: ON PAUSE
│  ├─ Wait: 3600s
│  ├─ HTTP: POST /resume
│  ├─ Telegram: "Reanudando..."
│  └─ Google Sheets: Append
│
├─ Webhook: ON COMPLETE
│  ├─ Telegram: "Completado!"
│  ├─ Google Sheets: Append
│  └─ Email: Resumen
│
└─ Webhook: ON ERROR
   ├─ Telegram: "ERROR!"
   └─ Email: Alert crítico
```

---

## 🔒 Seguridad

### Proteger Webhooks

Los webhooks son públicos por defecto. Para protegerlos:

1. **En n8n**:
   - Webhook → Settings → Authentication
   - Método: Basic Auth o API Key

2. **En scraper**:
   - Agregar header Authorization
   - Cambiar: `enviar_webhook(WEBHOOK_ON_PAUSE, datos, auth_header)`

### Proteger API Foursquare

- ✅ API Key en .env (nunca en logs)
- ✅ No exponer FSQ_API_KEY en URLs
- ✅ Rotarla regularmente

---

## 🆘 Troubleshooting

| Problema | Causa | Solución |
|----------|-------|----------|
| **Webhook no recibe datos** | URL incorrecta en .env | Verificar URL exacta en n8n |
| **Error de conexión** | Firewall bloqueando | Permitir localhost:5678 |
| **Telegram no envía** | Token o Chat ID inválido | Obtener nuevamente de BotFather |
| **No se reanuda** | AUTO_RESUME_AFTER_PAUSE=false | Cambiar a true en .env |
| **Webhook timeout** | n8n no responde a tiempo | n8n demora, dar más tiempo |

---

## 📚 Recursos

- **n8n Docs**: https://docs.n8n.io
- **Telegram Bot API**: https://core.telegram.org/bots/api
- **n8n Community**: https://community.n8n.io

---

## ✅ Checklist Integración n8n

- [ ] n8n instalado y corriendo
- [ ] 3 webhooks creados (pause, complete, error)
- [ ] URLs copiadas a .env
- [ ] Bot Telegram creado
- [ ] Chat ID obtenido
- [ ] Workflow "On Pause" creado
- [ ] Workflow "On Complete" creado
- [ ] Workflow "Daily Scheduler" creado
- [ ] Prueba manual: Disparar scraping
- [ ] Prueba manual: Recibir notificación Telegram
- [ ] Validar que reanuda automáticamente después de pausarse

---

¡Con esto tendrás un sistema completamente automático y monitoreado! 🚀
