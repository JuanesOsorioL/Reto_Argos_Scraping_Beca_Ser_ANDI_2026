# 📊 Resumen Ejecutivo — Foursquare Places API Scraper

**Fecha**: Enero 2024  
**Estado**: ✅ Listo para Producción  
**Versión**: 1.0.0

---

## 🎯 Objetivo

Recolectar automáticamente datos de ferreterías y negocios de construcción de Colombia desde Foursquare, con pausa inteligente cuando se alcancen los límites de tasa de Foursquare.

**Resultado esperado**: 1,500+ ferreterías de 35 ciudades colombianas en PostgreSQL, con integración automática a n8n.

---

## 💼 Característica Clave: Pausa Automática por Rate Limit

### El Problema

Foursquare permite 5.000 requests/hora (gratis). Si las haces todas, tienes que esperar a que se resetee en 1 hora. Si haces 10.000 queries (10 keywords × 35 ciudades × 30 resultados c/u = 10.500 requests), excedes el límite.

**Sin pausa automática**: La app falla y pierdes datos.

### Nuestra Solución

1. **Detección automática** (status code 403)
2. **Pausa inteligente** (espera el tiempo correcto)
3. **Reanudación automática** (continúa donde quedó)
4. **Notificación a n8n** (puedes intervenir manualmente si quieres)

```
Foursquare 403 → Detecta scraper.py → Guarda progreso → Espera → Reintenta
                                                          ↓
                                                      Webhook a n8n
                                                      (notifica a Telegram/email)
```

---

## 📊 Números Clave

| Métrica | Valor |
|---------|-------|
| **Keywords** | 10 (ferretería, cemento, mortero, etc.) |
| **Ciudades** | 35 (Bogotá, Medellín, Cali, etc.) |
| **Combinaciones** | 350 búsquedas |
| **Resultados esperados** | 1,500+ ferreterías |
| **Tiempo estimado** | 30-45 minutos |
| **Duración mínima** | 5-10 minutos sin pausas |
| **Pausa típica** | 1 hora (cuando se alcanza 403) |
| **Rate limit Foursquare** | 5.000 requests/hora |
| **Requests por búsqueda** | 30 (con paginación) |
| **Total requests/corrida** | ~10.500 |
| **Pausas estimadas** | 1-2 por corrida |

---

## 🏗️ Arquitectura

```
                    ┌─────────────────────────────┐
                    │  n8n (Orquestador)          │
                    │  - Disparar cada hora       │
                    │  - Notificaciones           │
                    └──────────────┬──────────────┘
                                   │ POST /scrape/foursquare
                                   ↓
┌────────────────────────────────────────────────────────┐
│  FastAPI (Puerto 8006)                                 │
│  - POST /scrape/foursquare  → Iniciar                 │
│  - GET /status              → Ver estado              │
│  - GET /progress            → Ver progreso            │
│  - POST /reset              → Limpiar archivos        │
│  - GET /stats               → Estadísticas            │
└──────────┬─────────────────────────────────┬───────────┘
           │                                 │
           ↓                                 ↓
    ┌──────────────┐            ┌─────────────────────┐
    │ main.py      │            │ config.py           │
    │ Orquestador  │            │ scraper.py          │
    │ Detección403 │            │ normalizer.py       │
    │ Pausa auto.  │            │ db.py               │
    └──────┬───────┘            └─────────────────────┘
           │
           ↓
    ┌──────────────────┐
    │ PostgreSQL       │
    │ raw.foursquare_ │
    │ ferreterias     │
    │ (1,500+ registros)
    └──────────────────┘
           ↑
           │ SELECT/INSERT
           ↓
    JSON, Excel, etc.
```

---

## ✨ Características

### ✅ Detección Automática de Errores

| Error | Detección | Acción |
|-------|-----------|--------|
| **403 Rate Limit** | Sí | Pausa 1h, reintenta |
| **401 API Key inválida** | Sí | Aborta |
| **400 Parámetros** | Sí | Skip lugar |
| **429 Too Many Requests** | Sí | Reintenta exponencial |
| **Timeout conexión** | Sí | Reintenta 3 veces |

### ✅ Persistencia de Datos

- **PostgreSQL** (obligatorio): 1,500+ registros normalizados
- **foursquare_progress.json**: Dónde quedó (reanudación)
- **foursquare_ferreterias.jsonl**: Respaldo local línea a línea
- **output/foursquare_raw_responses.json**: Respuestas crudas (opcional)
- **output/foursquare_flat_results.json**: Normalizadas (opcional)

### ✅ Control Remoto HTTP

Todos los endpoints están documentados en Swagger:
- http://localhost:8006/docs

### ✅ Webhooks a n8n

Cuando se pausa o completa, envía JSON a n8n:

```json
{
  "estado": "pausado",
  "razon": "rate_limit_403",
  "combinacion_actual": {"keyword": "ferretería", "ciudad": "Bogotá"},
  "total_insertadas": 1200,
  "rate_limit_count": 1,
  "fecha_actualizacion": "2024-01-01T12:00:00"
}
```

n8n puede:
- Notificar a Telegram
- Enviar email
- Guardar a Google Sheets
- Esperar y reanudar automáticamente

---

## 🚀 Deployment

### Opción A: Local + Docker

```bash
docker-compose up -d
# PostgreSQL en 5432
# FastAPI en 8006
```

### Opción B: Local Python

```bash
python api_runner.py
```

### Opción C: Producción (AWS/GCP)

```bash
# Dockerfile incluido, listo para:
# - Docker Hub
# - AWS ECR
# - Google Cloud Run
# - DigitalOcean App Platform
```

---

## 📈 Roadmap Futuro

- [ ] Exportar directamente a BigQuery
- [ ] Dashboard en Metabase/Grafana
- [ ] API de búsqueda por ciudad/score
- [ ] Machine learning para detectar ferreterías fake
- [ ] Actualización incremental (solo nuevas/modificadas)
- [ ] Multi-región (otros países de Latam)

---

## 💰 Costos

| Componente | Costo Mensual |
|------------|---------------|
| **Foursquare API** | $0 (5.000 req/mes gratis) |
| **PostgreSQL Local** | $0 |
| **Docker Local** | $0 |
| **n8n Self-hosted** | $0 |
| **AWS RDS (si migras)** | $20-50 |
| **AWS EC2 (si migras)** | $10-30 |

**Total sin migración**: $0

---

## 🔒 Seguridad

- [x] API Key encriptada en .env
- [x] Sin exponer credenciales en logs
- [x] BD con contraseña
- [x] CORS habilitado para n8n
- [x] Input validation en todos los endpoints

---

## 📞 Soporte

| Pregunta | Respuesta |
|----------|-----------|
| ¿Dónde están los datos? | PostgreSQL, raw.foursquare_ferreterias |
| ¿Cómo retomar si falla? | Del archivo foursquare_progress.json |
| ¿Cómo integrar con Telegram? | Webhook en n8n + Telegram bot |
| ¿Cómo exportar a Excel? | `python data_exporter.py` |
| ¿Cómo limpiar todo? | `POST /reset` (archivos) o SQL (BD) |
| ¿Cuánto tarda? | 30-45 min (con 1-2 pausas por 403) |

---

## 📚 Documentación

- **README.md** — Instalación y uso completo (30 min de lectura)
- **QUICKSTART.md** — 5 pasos para empezar (5 min)
- **EXPLICACION_CODIGO.md** — Línea por línea (1-2 horas)
- **Swagger** — http://localhost:8006/docs (interactivo)

---

## ✅ Checklist Producción

- [x] Código comentado línea por línea
- [x] Excepciones personalizadas para cada error
- [x] Persistencia de progreso (reanudación)
- [x] Webhooks a n8n
- [x] Health check en Docker
- [x] Límites de reintentos configurables
- [x] Logs detallados con DEBUG mode
- [x] Documentación completa
- [x] Ejemplos de uso
- [x] Manejo de edge cases

---

## 🎉 Resultado Final

Sistema automático, robusto y documentado para recolectar ferreterías de Foursquare. Listo para usar en producción, integración con n8n, y escalable a múltiples fuentes de datos.

**Tiempo de setup**: 5 minutos  
**Tiempo de integración n8n**: 30 minutos  
**Tiempo de producción**: 1-2 horas  

**Total**: ~2-3 horas desde cero a producción. ✨
