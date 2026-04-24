# 📚 City Matcher API - Guía de Uso

## 🚀 Inicio Rápido

### 1. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 2. Ejecutar API
```bash
python city_matcher_api_colombia.py
```

API disponible en: `http://localhost:8005`
Swagger docs: `http://localhost:8005/docs`

---

## 📡 Fuente de Datos

**api-colombia.com** - API pública y gratuita
- ✅ Sin autenticación
- ✅ Rápida y confiable
- ✅ Datos actualizados
- ✅ Estructura clara

Endpoints:
- `https://api-colombia.com/api/v1/Department` → Departamentos
- `https://api-colombia.com/api/v1/City` → Ciudades

---

## 📌 Endpoints Disponibles

### 1️⃣ `/health` - Health Check

```bash
GET http://localhost:8005/health
```

**Respuesta:**
```json
{
  "status": "ok",
  "municipios_cached": true,
  "cache_age_minutes": 5
}
```

---

### 2️⃣ `/departments` - Listar Departamentos

```bash
GET http://localhost:8005/departments
```

**Respuesta:**
```json
{
  "count": 32,
  "departments": [
    "Amazonas",
    "Antioquia",
    "Arauca",
    "Atlántico",
    "Bolívar",
    ...
    "Vichada"
  ]
}
```

---

### 3️⃣ `/departments/{department}/municipalities` - Municipios de un Departamento

```bash
GET http://localhost:8005/departments/Antioquia/municipalities
```

**Respuesta:**
```json
{
  "department": "Antioquia",
  "count": 125,
  "municipalities": [
    "Abejorral",
    "Abriaquí",
    "Amagá",
    "Amalfi",
    "Andes",
    ...
    "Envigado",
    ...
    "Medellín"
  ]
}
```

---

### 4️⃣ `/municipalities` - TODOS los Municipios

```bash
GET http://localhost:8005/municipalities
```

**Respuesta:**
```json
{
  "total": 1122,
  "municipalities": [
    {
      "municipio": "Leticia",
      "departamento": "Amazonas"
    },
    {
      "municipio": "Puerto Nariño",
      "departamento": "Amazonas"
    },
    ...
  ]
}
```

---

### 5️⃣ `/match-cities` - ENDPOINT PRINCIPAL ⭐

**Modo: SINGLE (un municipio)**

```bash
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "single",
    "input": "medellin",
    "search_level": "municipio"
  }'
```

**Respuesta:**
```json
{
  "mode": "single",
  "search_level": "municipio",
  "total_received": 1,
  "accepted_count": 1,
  "rejected_count": 0,
  "used_ai": false,
  "selected_locations": [
    {
      "municipio": "Medellín",
      "departamento": "Antioquia"
    }
  ],
  "matches": [
    {
      "original": "medellin",
      "normalized": "medellin",
      "final_municipio": "Medellín",
      "departamento": "Antioquia",
      "score": 100,
      "accepted": true,
      "source": "exact",
      "suggestion": null,
      "reason": null
    }
  ]
}
```

---

**Modo: MULTIPLE (varios municipios)**

```bash
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "multiple",
    "input": "Medellín, bogota, cali, santa-marta",
    "search_level": "municipio"
  }'
```

**Respuesta:**
```json
{
  "mode": "multiple",
  "search_level": "municipio",
  "total_received": 4,
  "accepted_count": 4,
  "rejected_count": 0,
  "used_ai": false,
  "selected_locations": [
    {"municipio": "Medellín", "departamento": "Antioquia"},
    {"municipio": "Bogotá", "departamento": "Bogotá D.C."},
    {"municipio": "Cali", "departamento": "Valle del Cauca"},
    {"municipio": "Santa Marta", "departamento": "Magdalena"}
  ],
  "matches": [
    {
      "original": "Medellín",
      "normalized": "medellin",
      "final_municipio": "Medellín",
      "departamento": "Antioquia",
      "score": 100,
      "accepted": true,
      "source": "exact"
    },
    {
      "original": "bogota",
      "normalized": "bogota",
      "final_municipio": "Bogotá",
      "departamento": "Bogotá D.C.",
      "score": 100,
      "accepted": true,
      "source": "exact"
    },
    ...
  ]
}
```

---

**Modo: ALL (todos los municipios)**

```bash
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "all",
    "search_level": "municipio"
  }'
```

**Retorna:** ~1100+ municipios validados

---

### 6️⃣ `/match-cities` - Búsqueda por DEPARTAMENTO

```bash
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "single",
    "input": "Antioquia",
    "search_level": "departamento"
  }'
```

**Respuesta:**
```json
{
  "mode": "single",
  "search_level": "departamento",
  "total_received": 1,
  "accepted_count": 125,  // Todos los municipios de Antioquia
  "rejected_count": 0,
  "used_ai": false,
  "selected_locations": [
    {"municipio": "Abejorral", "departamento": "Antioquia"},
    {"municipio": "Abriaquí", "departamento": "Antioquia"},
    ...
    {"municipio": "Medellín", "departamento": "Antioquia"},
    ...
    {"municipio": "Zipacón", "departamento": "Antioquia"}
  ],
  "matches": [...]
}
```

---

### 7️⃣ `/validate-location` - Validación Simple (para Telegram)

```bash
curl -X POST http://localhost:8005/validate-location \
  -H "Content-Type: application/json" \
  -d '{
    "input": "medellin",
    "search_level": "municipio"
  }'
```

Es lo mismo que `/match-cities` con `mode: "single"`

---

### 8️⃣ `/refresh-cache` - Forzar Recarga de Datos

```bash
GET http://localhost:8005/refresh-cache
```

**Respuesta:**
```json
{
  "status": "cache refreshed",
  "departments": 32,
  "total_municipalities": 1122
}
```

---

## 🔍 Estrategia de Matching (en orden)

1. **EXACT MATCH** - Match exacto (score 100)
   - Entrada: "medellin"
   - Match: "medellin"

2. **FUZZY HIGH** - Coincidencia difusa con score >= 88
   - Entrada: "medelin" (typo)
   - Match: "medellin" (score 95)

3. **FUZZY MEDIUM** - Score entre 72-88 (requiere revisión)
   - Entrada: "mede"
   - Match: "medellin" (score 75) → `accepted: false`

4. **AI CORRECTION** - Si `use_ai: true` y fuzzy falla
   - Entrada: "md" (abreviatura)
   - Match: OpenRouter intenta corregir

5. **REJECTED** - Score muy bajo
   - Entrada: "xxx"
   - Result: `accepted: false`, `source: "rejected"`

---

## 💡 Casos de Uso

### Caso 1: Telegram Bot
```python
# Usuario selecciona "Algunas ciudades"
# Escribe: "Medellín, Bogotá, Cali"

response = requests.post("http://localhost:8005/match-cities", json={
    "mode": "multiple",
    "input": "Medellín, Bogotá, Cali",
    "search_level": "municipio"
})

selected = response.json()["selected_locations"]
# Enviar a n8n webhook con estos municipios validados
```

### Caso 2: n8n Webhook
```javascript
// Recibir del Telegram Bot
const cities = $json.selected_locations;

// Iterar por cada municipio
for (const location of cities) {
    // POST a RetoArgos Serper service
    await scrapeByMunicipio(location.municipio, location.departamento);
}
```

### Caso 3: Búsqueda por Departamento
```bash
# Usuario: "Quiero ferreterías en TODA Antioquia"
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "single",
    "input": "Antioquia",
    "search_level": "departamento"
  }'

# Respuesta: 125 municipios de Antioquia para scraping
```

---

## 📊 Performance

| Operación | Tiempo |
|-----------|--------|
| Health check | < 10ms |
| Get all departments | < 50ms (cached) |
| Get municipality | < 20ms (cached) |
| Match single | < 100ms |
| Match multiple (10) | < 300ms |
| First load from api-colombia.com | 2-5s |

**Cache Duration:** 24 horas
**Auto-refresh:** POST a `/refresh-cache`

---

## 🛠️ Configuración

### Variables de Entorno

```bash
# Opcional: Para AI correction
OPENROUTER_API_KEY="sk-..."
OPENROUTER_MODEL="openrouter/free"  # o "meta-llama/llama-2-7b-chat"
```

Si no configuras OpenRouter, la API sigue funcionando sin AI correction.

---

## ✅ Checklist de Integración

- [ ] API ejecutándose en puerto 8005
- [ ] Swagger docs accesibles en `/docs`
- [ ] GET `/health` retorna `status: "ok"`
- [ ] GET `/departments` retorna 32 departamentos
- [ ] POST `/match-cities` funciona con ejemplo
- [ ] Cache se carga en < 5 segundos (primera vez)
- [ ] n8n webhook configurado para recibir `selected_locations`
- [ ] RetoArgos Serper service actualizado para aceptar municipios

---

## 🐛 Troubleshooting

### Error: "No se pudo conectar a api-colombia.com"
```bash
# Solución: Verifica tu conexión a internet
ping api-colombia.com

# O intenta manualmente:
curl https://api-colombia.com/api/v1/Department
```

### Error: "ModuleNotFoundError: No module named 'rapidfuzz'"
```bash
# Solución:
pip install -r requirements.txt
```

### Cache muy antiguo
```bash
# Fuerza recarga:
curl http://localhost:8005/refresh-cache
```

---

## 📞 Soporte

- **API Colombia Docs:** https://api-colombia.com
- **FastAPI Docs:** https://fastapi.tiangolo.com
- **RapidFuzz Docs:** https://maxbachmann.github.io/RapidFuzz/