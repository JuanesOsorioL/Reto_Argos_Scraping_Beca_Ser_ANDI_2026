# 📑 ÍNDICE GENERAL — Serper API v2.0

Bienvenido. Este es tu **índice de navegación** para acceder a todo lo que necesitas.

---

## 🎯 ¿Por Dónde Empiezo?

### Opción A: Quiero empezar AHORA (5 minutos)
→ Abre: **[QUICKSTART.md](QUICKSTART.md)**

### Opción B: Quiero entender TODO
→ Abre: **[README.md](README.md)** (secciones en orden)

### Opción C: Quiero ver el código explicado
→ Abre: **[EXPLICACION_CODIGO.md](EXPLICACION_CODIGO.md)**

### Opción D: Quiero integrar con n8n
→ Abre: **[FLUJO_N8N.md](FLUJO_N8N.md)**

---

## 📂 Estructura de Archivos

```
serper-api/
├── 📋 DOCUMENTACIÓN
│   ├── INDEX.md                    ← TÚ ESTÁS AQUÍ
│   ├── RESUMEN_FINAL.md           ← Lo que conseguiste
│   ├── README.md                  ← Guía completa (30 min)
│   ├── QUICKSTART.md              ← Inicio rápido (5 min)
│   ├── FLUJO_N8N.md               ← Integración n8n (15 min)
│   └── EXPLICACION_CODIGO.md      ← Código línea por línea (20 min)
│
├── ⚙️  CONFIGURACIÓN
│   └── .env                       ← Variables de entorno (EDITAR)
│
├── 🐍 CÓDIGO PYTHON
│   ├── config.py                  ← Configuración centralizada (280 líneas)
│   ├── scraper.py                 ← Llamadas a Serper (350 líneas)
│   ├── db.py                      ← PostgreSQL (220 líneas)
│   ├── main.py                    ← Loop principal (480 líneas)
│   ├── api_runner.py              ← API FastAPI (420 líneas)
│   └── utils.py                   ← Funciones auxiliares (330 líneas)
│
└── 📦 DEPENDENCIAS
    └── requirements.txt           ← pip install -r requirements.txt
```

---

## 📚 Documentación Detallada

### [RESUMEN_FINAL.md](RESUMEN_FINAL.md) (5 min)
**Qué es**: Resumen ejecutivo del proyecto  
**Incluye**: 
- Lo que creamos
- Cómo funciona
- Puntos clave
- Casos de uso
- Troubleshooting rápido
**Lee si**: Quieres una visión general

### [QUICKSTART.md](QUICKSTART.md) (5 min)
**Qué es**: Inicio rápido en 5 pasos  
**Incluye**:
1. Descargar archivos
2. Obtener API key
3. Instalar dependencias
4. Configurar PostgreSQL
5. Iniciar servidor
**Lee si**: Quieres empezar YA

### [README.md](README.md) (30 min)
**Qué es**: Guía COMPLETA del proyecto  
**Secciones**:
- ✨ Características
- 🛠️ Requisitos
- 📦 Instalación (paso a paso)
- ⚙️ Configuración (cada variable)
- 🚀 Uso (línea de comandos e HTTP)
- 📡 Endpoints API (todos con ejemplos)
- 🔄 Pausa automática (explicación)
- 🔗 Integración n8n
- 🗄️ Estructura de datos (tablas)
- 🐛 Troubleshooting
**Lee si**: Quieres todo documentado

### [FLUJO_N8N.md](FLUJO_N8N.md) (15 min)
**Qué es**: Cómo integrar con n8n paso a paso  
**Incluye**:
- Crear webhook en n8n
- Workflow manual (button)
- Workflow automático (Cron)
- Credenciales Telegram
- Testing del flujo
- Monitoreo
**Lee si**: Quieres automatizar con n8n

### [EXPLICACION_CODIGO.md](EXPLICACION_CODIGO.md) (20 min)
**Qué es**: Explicación línea por línea de todo el código  
**Secciones por archivo**:
- `.env` — Configuración
- `config.py` — Lectura de vars
- `scraper.py` — Llamadas a Serper
- `db.py` — PostgreSQL
- `main.py` — Loop principal
- `api_runner.py` — API HTTP
- `utils.py` — Funciones auxiliares
**Lee si**: Quieres entender el código

---

## 🐍 Archivos Python

### config.py (280 líneas)
**Responsabilidad**: Centralizar TODO la configuración  
**Qué hace**:
- Carga `.env`
- Valida que exista SERPER_API_KEY
- Convierte strings a tipos correctos
- Define constantes (KEYWORDS, CIUDADES, etc)
- Muestra resumen al ejecutar
**Ejecutar**: `python config.py` (para ver resumen)

### scraper.py (350 líneas)
**Responsabilidad**: Comunicación con Serper API  
**Qué hace**:
- `call_serper()` — Llama API
- Diferencia errores (429 vs 401 vs 403)
- `enrich_url()` — Visita URLs y extrae contacto
- `flatten_response()` — Aplana respuesta en registros
- `enrich_records()` — Enriquece en paralelo
**Importa**: `from scraper import call_serper, SerperRateLimitError`

### db.py (220 líneas)
**Responsabilidad**: Manejo de PostgreSQL  
**Qué hace**:
- `init_db()` — Crear tablas
- `consulta_ya_procesada()` — Verificar reanudación
- `insertar_consulta()` — Guardar query
- `insertar_resultado()` — Guardar resultado
- `reset_all()` — Borrar todo (⚠️)
**Importa**: `from db import init_db, insertar_resultado`

### main.py (480 líneas)
**Responsabilidad**: Orquestación principal  
**Qué hace**:
- `do_scrape()` — Loop principal
- Detecta pausa manual (`CONTROL["pause_requested"]`)
- Maneja 429 automáticamente (espera + reintenta)
- Guarda progreso
- Retorna métricas
**Ejecutar**: `python main.py` (prueba o producción)

### api_runner.py (420 líneas)
**Responsabilidad**: HTTP API con FastAPI  
**Qué hace**:
- Endpoints: `/scrape/serper`, `/pause`, `/resume`, `/progress`, `/reset`
- Ejecuta `do_scrape()` en background (no bloquea)
- Actualiza `estado` global
- Envía webhooks a n8n
**Ejecutar**: `python api_runner.py` (inicia servidor)

### utils.py (330 líneas)
**Responsabilidad**: Funciones auxiliares  
**Qué hace**:
- `normalize_city()` — Normalizar ciudades
- `make_smart_hash()` — Deduplicación
- `extract_emails()` — Buscar emails
- `extract_phones()` — Buscar teléfonos
- `score_result()` — Calcular relevancia
**Importa**: `from utils import normalize_city, extract_emails`

---

## ⚙️ Archivo .env

**Qué es**: Configuración sensible (no versionar)  
**Cómo editar**:
```bash
nano .env
# Luego Ctrl+X, Y, Enter
```

**Variables críticas**:
- `SERPER_API_KEY` ← ⭐ OBLIGATORIO
- `DB_PASSWORD` ← Cambia según tu PostgreSQL
- `AUTO_RESUME_ON_RATE_LIMIT` ← true/false

**Más info**: Ver [README.md](README.md) sección "Configuración"

---

## 📦 requirements.txt

**Qué es**: Lista de dependencias Python  
**Instalar**:
```bash
pip install -r requirements.txt
```

**Paquetes principales**:
- `requests` — HTTP calls a Serper
- `fastapi` + `uvicorn` — API web
- `psycopg2-binary` — PostgreSQL driver
- `beautifulsoup4` + `lxml` — HTML parsing
- `httpx` — Webhooks async
- `python-dotenv` — Leer `.env`

---

## 🚀 Cómo Usar Este Proyecto

### Flujo 1: Testing (Para verificar que funciona)
```bash
# Paso 1: Instalar
pip install -r requirements.txt

# Paso 2: Iniciar API
python api_runner.py

# Paso 3: En otra terminal, prueba rápido
curl -X POST http://localhost:8004/scrape/serper/prueba

# Paso 4: Ver progreso
curl http://localhost:8004/progress | jq

# Paso 5: Ver resultados en PostgreSQL
psql -U postgres -d postgres -c "SELECT COUNT(*) FROM raw.serper_resultados_construccion;"
```

### Flujo 2: Producción (Todos los datos)
```bash
# Iniciar servidor
python api_runner.py

# En otra terminal, lanzar
curl -X POST http://localhost:8004/scrape/serper

# Monitorear
watch -n 10 'curl http://localhost:8004/progress | jq'

# Si necesita pausa
curl -X POST http://localhost:8004/pause

# Reanudar
curl -X POST http://localhost:8004/resume
```

### Flujo 3: Automático (Con n8n)
1. Abre [FLUJO_N8N.md](FLUJO_N8N.md)
2. Sigue los 7 pasos
3. Crea workflow automático
4. Recibe notificaciones por Telegram

---

## 🆘 ¿Necesitas Ayuda?

| Pregunta | Dónde buscar |
|----------|-------------|
| "¿Por dónde empiezo?" | [QUICKSTART.md](QUICKSTART.md) |
| "¿Cómo configuro?" | [README.md](README.md) → Configuración |
| "¿Cuál es cada endpoint?" | [README.md](README.md) → Endpoints API |
| "¿Por qué falla?" | [README.md](README.md) → Troubleshooting |
| "¿Qué hace esta línea?" | [EXPLICACION_CODIGO.md](EXPLICACION_CODIGO.md) |
| "¿Cómo integro con n8n?" | [FLUJO_N8N.md](FLUJO_N8N.md) |
| "¿Qué conseguí?" | [RESUMEN_FINAL.md](RESUMEN_FINAL.md) |

---

## 📊 Estadísticas del Proyecto

| Métrica | Valor |
|---------|-------|
| **Total líneas código** | 2,100+ |
| **Total líneas docs** | 5,000+ |
| **Archivos Python** | 6 |
| **Documentos** | 6 |
| **Endpoints HTTP** | 9 |
| **Tablas PostgreSQL** | 2 |
| **Configurables** | 15+ |
| **Excepciones custom** | 5 |
| **Funciones auxiliares** | 20+ |

---

## 🎯 Checklist de Implementación

- [ ] Descargar 12 archivos
- [ ] Configurar API key en `.env`
- [ ] Instalar Python dependencias
- [ ] Verificar PostgreSQL
- [ ] Ejecutar prueba rápida
- [ ] Ver progreso en tiempo real
- [ ] Verificar datos en PostgreSQL
- [ ] (Opcional) Integrar con n8n
- [ ] (Opcional) Notificaciones Telegram

---

## 📞 Próximos Pasos

**Ahora**:
1. Lee [QUICKSTART.md](QUICKSTART.md) (5 min)
2. Sigue los 6 pasos
3. ¡Prueba! (30 seg)

**Después**:
1. Lee [README.md](README.md) completo
2. Experimenta con endpoints
3. Integra con n8n si quieres

**Si necesitas help**:
1. Busca en [EXPLICACION_CODIGO.md](EXPLICACION_CODIGO.md)
2. Revisa [Troubleshooting en README.md](README.md#-troubleshooting)
3. Ejecuta tests: `curl http://localhost:8004/health`

---

## 🎉 ¡Listo!

Tienes un **scraper enterprise-grade** completamente documentado y listo para producción.

**Próximo paso**: Abre [QUICKSTART.md](QUICKSTART.md) 🚀

---

**Versión**: 2.0.0  
**Creado**: Enero 2024  
**Para**: Scraping de Google Search + Rate Limits Automáticos
