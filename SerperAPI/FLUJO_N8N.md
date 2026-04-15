# 🔗 Integración con n8n — Guía Completa

Este documento explica cómo crear un workflow en n8n que:
1. **Inicia** scraping automático
2. **Monitorea** con polling
3. **Detecta** pausas por rate limit
4. **Reintenta** automáticamente
5. **Notifica** por Telegram cuando termina

---

## 🔧 Requisitos Previos

- ✅ Serper API corriendo en `http://localhost:8004` (o URL pública)
- ✅ n8n instalado y corriendo
- ✅ (Opcional) Bot de Telegram para notificaciones

---

## 📋 Paso 1: Crear Webhook en n8n

### 1.1 Nuevo Workflow

1. Abre n8n: `http://localhost:5678`
2. Click: **+ New** → **Workflow**
3. Nombre: `Serper Scraper Automático`

### 1.2 Agregar Webhook (Receptor)

El webhook recibe notificaciones cuando Serper termina.

1. Click: **+** (agregar nodo)
2. Buscar: **Webhook**
3. Seleccionar: **Webhook**
4. Config:
   - **HTTP Method**: POST
   - **Path**: `/webhook/serper-callback` (o lo que prefieras)
5. Click: **Test** → Verás la URL exacta, ej:
   ```
   http://localhost:5678/webhook/serper-callback/test
   ```
6. Copiar la URL (sin `/test`)
7. Pegar en `.env` del Serper:
   ```env
   N8N_WEBHOOK_URL=http://localhost:5678/webhook/serper-callback
   ```

---

## 🚀 Paso 2: Workflow Manual (Para Testear)

Este flujo inicia scraping manualmente con un botón.

### Estructura

```
Manual Trigger
    ↓
HTTP: POST /scrape/serper
    ↓
Set Variables (guardar run_id)
    ↓
Wait 2 min
    ↓
Loop: Check Progress (cada 30s)
    ↓
IF: Status?
  ├─ corriendo → vuelve a loop
  ├─ pausado_sin_tokens → espera + resume
  ├─ ok → Telegram "Completado ✅"
  └─ error → Telegram "Error ❌"
```

### Nodos

#### Nodo 1: Manual Trigger

1. Click: **+** → **Manual**
2. Sin config necesaria

#### Nodo 2: HTTP - Start Scraping

1. Click: **+** → **HTTP Request**
2. Nombre: `Start Scraping`
3. Config:
   - **Method**: POST
   - **URL**: `http://localhost:8004/scrape/serper`
   - **Authentication**: None
4. Click: **Test** → Debe retornar:
   ```json
   {
     "status": "iniciado",
     "run_id": "uuid...",
     "inicio": "2024-01-20T..."
   }
   ```

#### Nodo 3: Set Variables

Guardar `run_id` para usarlo luego.

1. Click: **+** → **Set**
2. Config:
   - **Name**: `run_id`
   - **Value**: `{{ $node['HTTP - Start Scraping'].json.run_id }}`

#### Nodo 4: Wait

Esperar 2 minutos antes de empezar a verificar.

1. Click: **+** → **Wait**
2. Config:
   - **Wait**: 2 minutes

#### Nodo 5: Loop - Check Progress

Verificar estado cada 30 segundos.

1. Click: **+** → **HTTP Request**
2. Nombre: `Check Progress`
3. Config:
   - **Method**: GET
   - **URL**: `http://localhost:8004/progress`
4. Click: **Test** → Debe retornar estado actual

#### Nodo 6: IF - Revisar Status

Decidir qué hacer según el status.

1. Click: **+** → **IF**
2. Config:
   - **Field 1**: `{{ $node['Check Progress'].json.status }}`
   - **Operation**: equals
   - **Field 2**: `corriendo`
3. **Output**: 
   - **Then**: Volver a Check Progress (esperar 30s)
   - **Else**: Continuar

#### Nodo 7: IF - Pausado por Tokens?

```
Field 1: {{ $node['Check Progress'].json.status }}
Operation: equals
Field 2: "pausado_sin_tokens"

If Yes:
  - Wait 15 min
  - HTTP: POST /resume
  - Volver a Check Progress
  
If No:
  - Continuar a Telegram
```

#### Nodo 8: Telegram (Éxito)

Solo si `status == "ok"`.

1. Click: **+** → **Telegram**
2. Config:
   - **Credentials**: Tu bot token (crear antes)
   - **Chat ID**: Tu chat ID
   - **Text**:
     ```
     ✅ Scraping Completado!
     
     Run ID: {{ $node.Variable.json.run_id }}
     Status: {{ $node['Check Progress'].json.status }}
     Duración: {{ $node['Check Progress'].json.duracion }}
     Registros: {{ $node['Check Progress'].json.registros_nuevos }}
     Aprobados: {{ $node['Check Progress'].json.aprobados_argos }}
     ```

#### Nodo 9: Telegram (Error)

Solo si `status == "error"`.

1. Click: **+** → **Telegram**
2. Text:
   ```
   ❌ Error en Scraping
   
   Run ID: {{ $node.Variable.json.run_id }}
   Error: {{ $node['Check Progress'].json.ultimo_error }}
   ```

### Flujo Visual (ASCII)

```
┌──────────────────────┐
│   Manual Trigger     │ ← Click para empezar
└──────────┬───────────┘
           ↓
┌──────────────────────────────┐
│  HTTP: POST /scrape/serper   │ Inicia scraping
└──────────┬───────────────────┘
           ↓
┌──────────────────────┐
│   Set: run_id        │ Guardar UUID
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│   Wait: 2 min        │ Esperar inicio
└──────────┬───────────┘
           ↓
┌──────────────────────────────┐
│  Check: GET /progress        │ ← LOOP
└──────────┬───────────────────┘
           ↓
        ¿Status?
        /  |  \  \
       /   |   \  \
      /    |    \  \
   "corriendo" "pausado" "ok" "error"
     |       |        |     |
     ↓       ↓        ↓     ↓
    LOOP   Resume  Telegram  Telegram
                    "✅"     "❌"
```

---

## ⏰ Paso 3: Workflow Automático (Cron)

Este flujo corre automáticamente cada día.

### Nodos

1. **Cron**: Trigger cada domingo a las 8 AM
   - Pattern: `0 8 * * 0` (cron format)
2. **HTTP**: POST /scrape/serper
3. **Check Progress Loop** (mismo que arriba)
4. **Telegram**: Notificar resultado

### Config Cron

```
Cron Expression: 0 8 * * 0
Day: Sunday
Time: 08:00 AM
```

---

## 🔔 Paso 4: Credenciales de Telegram

### 4.1 Crear Bot

1. Abre Telegram
2. Busca: `@BotFather`
3. Envía: `/start`
4. Envía: `/newbot`
5. Elige nombre: `SerperScraperBot`
6. Elige usuario: `serper_scraper_bot`
7. Copiar token: `123456:ABCdef...` (guardar)

### 4.2 Obtener Chat ID

1. Busca tu bot: `@serper_scraper_bot`
2. Envía: `/start`
3. Abre: `https://api.telegram.org/bot123456:ABCdef.../getUpdates`
4. Busca tu mensaje, copia `chat.id`

### 4.3 Agregar en n8n

1. En n8n, click: **Credentials** (parte superior)
2. **+ New** → **Telegram**
3. Token: `123456:ABCdef...`
4. **Create**

---

## 📊 Paso 5: Variables de Ambiente

Si quieres que n8n acceda a variables del sistema:

1. En n8n, edita el workflow
2. Agregar nodo **Function**:
   ```javascript
   return {
     serper_url: process.env.SERPER_API_URL || "http://localhost:8004",
     webhook_url: process.env.N8N_WEBHOOK_URL,
   };
   ```

---

## 🧪 Paso 6: Testing

### Test 1: Webhook Manual

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"evento":"test","status":"ok"}' \
  http://localhost:5678/webhook/serper-callback
```

n8n debe recibir el POST.

### Test 2: Prueba Workflow Manual

1. Abre el workflow en n8n
2. Click: **Manual Trigger**
3. Click: **Test Workflow** (botón azul)
4. Click el botón "play" en Manual Trigger

Debe:
1. Iniciar scraping
2. Mostrar run_id
3. Esperar 2 min
4. Hacer polling cada 30s
5. Cuando "ok" → enviar Telegram ✅

---

## 🔄 Paso 7: Autoescalado (Avanzado)

Si quieres que n8n reintente automáticamente cuando hay rate limit:

```
Check Progress
    ↓
IF: status == "pausado_sin_tokens"?
    ├─ Yes:
    │   Wait 15 min
    │   POST /resume
    │   Loop again
    └─ No:
        Continuar
```

Agregando después del nodo "Check Progress":

1. **IF**: 
   ```
   Field: {{ $node['Check Progress'].json.status }}
   Operator: equals
   Value: "pausado_sin_tokens"
   ```

2. **True path**: 
   - Wait 15 minutes
   - HTTP POST /resume
   - Wait 1 minute
   - HTTP GET /progress (volver a check)

3. **False path**: Continuar a Telegram

---

## 📈 Monitoreo

### Desde n8n

Abre **Execution History** para ver:
- Cada ejecución del workflow
- Timing de cada nodo
- Datos que pasaron por cada paso

### Desde CLI

```bash
# Ver logs de Serper API
tail -f api_runner.log

# Ver progreso actual
curl http://localhost:8004/progress | jq

# Ver status final
curl http://localhost:8004/status | jq .metricas
```

---

## 🎯 Caso de Uso Completo

**Lunes a Viernes, 8 AM:**
1. n8n dispara Cron
2. Llama POST /scrape/serper (completamente)
3. Cada 1 minuto: GET /progress
4. Si "pausado_sin_tokens": espera + resume automático
5. Cuando "ok": Telegram "✅ Completado: 3.450 registros"
6. Si "error": Telegram "❌ Error: API key inválida"

**Resultado:**
- Scraping automático, sin intervención
- Rate limits manejados automáticamente
- Notificaciones en tiempo real
- Historial en n8n

---

## ❌ Troubleshooting

### "Error: Webhook URL not found"

**Problema**: N8N_WEBHOOK_URL no es alcanzable desde Serper

**Solución**:
```env
# Si ambos están en localhost:
N8N_WEBHOOK_URL=http://host.docker.internal:5678/webhook/serper-callback

# Si n8n está en servidor remoto:
N8N_WEBHOOK_URL=https://tudominio.com/webhook/serper-callback
```

### "Workflow no se ejecuta"

**Problema**: Cron expression incorrecta

**Solución**:
- Verificar formato cron en https://crontab.guru/
- Ejemplo: `0 8 * * 0` = Domingo 8 AM

### Telegram no recibe mensajes

**Problema**: Token o Chat ID incorrectos

**Solución**:
1. Verificar token: `curl https://api.telegram.org/botTOKEN/getMe`
2. Verificar chat ID: `curl https://api.telegram.org/botTOKEN/getUpdates`

---

## 📝 Resumen

| Componente | Rol |
|-----------|-----|
| **Serper API** | Scraping + Webhooks |
| **n8n Workflow** | Orquestación + Control |
| **PostgreSQL** | Almacenamiento de datos |
| **Telegram** | Notificaciones |

---

**¡Tu workflow automático está listo! 🚀**
