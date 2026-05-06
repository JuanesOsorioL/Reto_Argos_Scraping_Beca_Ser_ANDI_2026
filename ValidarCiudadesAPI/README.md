# ValidarCiudades API

API REST construida con FastAPI que valida y normaliza nombres de municipios colombianos. Recibe texto libre (con errores tipográficos, mayúsculas inconsistentes o abreviaciones) y lo compara contra la base oficial de ~1122 municipios y 32 departamentos de Colombia, retornando el nombre canónico y el departamento correspondiente.

---

## Descripción

La API consume los datos de [api-colombia.com](https://api-colombia.com) al iniciar y los almacena en memoria con una caché de 24 horas. Para el matching utiliza una estrategia de 4 niveles:

| Nivel | Tipo | Score | Resultado |
|-------|------|-------|-----------|
| 1 | Exact match | 100 | Aceptado automáticamente |
| 2 | Fuzzy high (RapidFuzz WRatio) | >= 88 | Aceptado automáticamente |
| 3 | Fuzzy medium | 72 – 88 | Devuelto con `accepted: false` y sugerencia |
| 4 | AI correction (OpenRouter) | opcional | Requiere `use_ai: true` y variable de entorno |

Si ningún nivel produce un match con score suficiente, la entrada se marca como `rejected`.

---

## Requisitos

- Python 3.9+
- Conexión a internet (para cargar datos de api-colombia.com al iniciar)

---

## Instalación y ejecución

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

Dependencias incluidas:

```
fastapi>=0.115.0        # Framework web y manejo de rutas
uvicorn[standard]>=0.30.0  # Servidor ASGI para ejecutar FastAPI
rapidfuzz>=3.9.0        # Matching difuso de strings (algoritmo WRatio)
pydantic>=2.10.0        # Validación y tipado del body de las peticiones
httpx>=0.28.0           # Cliente HTTP async para consumir api-colombia.com y OpenRouter
python-multipart>=0.0.9 # Parseo de form-data
```

### 2. Ejecutar la API

```bash
python api_runner.py
```

La API estará disponible en:

- API: `http://localhost:8005`
- Documentación interactiva (Swagger): `http://localhost:8005/docs`
- Documentación alternativa (ReDoc): `http://localhost:8005/redoc`

> La primera vez que inicie, la API descargará los datos de api-colombia.com. Esto tarda entre 2 y 5 segundos. Las peticiones posteriores usan la caché en memoria.

---

## Variables de entorno (opcional)

La corrección por IA es completamente opcional. Si no se configuran estas variables, la API funciona normalmente sin ese nivel de matching.

```bash
OPENROUTER_API_KEY="sk-..."
OPENROUTER_MODEL="openrouter/free"   # o cualquier modelo disponible en OpenRouter
```

---

## Endpoints

### GET `/health`

**Qué hace:** Consulta el estado interno de la API. Verifica si la caché de municipios ya fue cargada y cuánto tiempo lleva activa.

**Librerías involucradas:** Solo Python nativo (`datetime`). No hace llamadas externas.

**Retorna:**
- `status`: `"ok"` si la caché está lista, `"loading"` si aún no se han descargado los datos.
- `municipios_cached`: booleano que indica si hay datos en memoria.
- `cache_age_minutes`: minutos transcurridos desde la última carga.

```bash
curl http://localhost:8005/health
```

```json
{
  "status": "ok",
  "municipios_cached": true,
  "cache_age_minutes": 5
}
```

---

### GET `/departments`

**Qué hace:** Lee la caché en memoria (o la recarga si venció) y retorna los nombres de los 32 departamentos de Colombia ordenados alfabéticamente.

**Librerías involucradas:** `httpx` para descargar datos de api-colombia.com si la caché está vacía o vencida (24 h). Los datos se mantienen en memoria entre peticiones.

**Retorna:**
- `count`: total de departamentos.
- `departments`: lista de nombres ordenados alfabéticamente.

```bash
curl http://localhost:8005/departments
```

```json
{
  "count": 32,
  "departments": ["Amazonas", "Antioquia", "Arauca", "Atlántico", "...", "Vichada"]
}
```

---

### GET `/departments/{department}/municipalities`

**Qué hace:** Busca el departamento indicado en la caché usando `normalize_text` (quita tildes, minúsculas) para hacer la comparación insensible a mayúsculas y acentos. Retorna la lista de municipios de ese departamento ordenada alfabéticamente.

**Librerías involucradas:** Python nativo (`unicodedata`, `re`) para la normalización. `httpx` solo si la caché está vacía.

**Retorna:**
- `department`: nombre canónico del departamento encontrado.
- `count`: número de municipios.
- `municipalities`: lista de nombres en orden alfabético.
- Error `404` si el departamento no existe.

```bash
curl http://localhost:8005/departments/Antioquia/municipalities
```

```json
{
  "department": "Antioquia",
  "count": 125,
  "municipalities": ["Abejorral", "Abriaquí", "Amagá", "...", "Medellín", "...", "Zipacón"]
}
```

---

### GET `/municipalities`

**Qué hace:** Lee la caché y aplana el diccionario `{departamento: [municipios]}` en una lista plana de objetos `{municipio, departamento}`. Retorna todos los municipios del país sin ningún filtro ni transformación.

**Librerías involucradas:** Solo lectura de la caché en memoria. `httpx` únicamente si la caché está vacía.

**Retorna:**
- `total`: cantidad total de municipios (~1122).
- `municipalities`: lista de objetos con `municipio` y `departamento` en su nombre oficial con tildes y mayúsculas.

```bash
curl http://localhost:8005/municipalities
```

```json
{
  "total": 1122,
  "municipalities": [
    {"municipio": "Leticia", "departamento": "Amazonas"},
    {"municipio": "Puerto Nariño", "departamento": "Amazonas"},
    "..."
  ]
}
```

---

### GET `/refresh-cache`

**Qué hace:** Borra la caché en memoria y fuerza una nueva descarga desde api-colombia.com usando `httpx`. Vuelve a construir el índice normalizado de municipios.

**Librerías involucradas:** `httpx` (descarga los endpoints de departamentos y ciudades). Python nativo para reconstruir el índice.

**Retorna:**
- `status`: confirmación de recarga.
- `departments`: número de departamentos cargados.
- `total_municipalities`: total de municipios descargados.

```bash
curl http://localhost:8005/refresh-cache
```

```json
{
  "status": "cache refreshed",
  "departments": 32,
  "total_municipalities": 1122
}
```

---

### POST `/match-cities` — Endpoint principal

**Qué hace:** Recibe texto libre con uno o varios municipios, los normaliza y los compara contra el índice interno usando matching exacto, difuso o IA (en ese orden). Es el núcleo de la API.

**Flujo interno por cada municipio:**
1. `normalize_text` (Python / `unicodedata`, `re`): quita tildes, pasa a minúsculas, convierte espacios a guiones.
2. Búsqueda exacta en el índice en memoria (O(1)).
3. Si falla: `rapidfuzz.process.extractOne` con algoritmo `WRatio` contra todos los candidatos del índice.
4. Si falla y `use_ai: true`: `httpx` llama a OpenRouter con el nombre original; la respuesta se valida contra el índice.

**Para `mode: "multiple"`**, antes de correr el matching corre `smart_parse_municipalities`:
- Divide el input por comas y punto y coma.
- Divide también por la conjunción " y ".
- Filtra stopwords en español (`de`, `la`, `el`, `y`, etc.).
- Intenta match exacto, luego fuzzy por token completo, luego palabra a palabra (para casos como `"nariño bello"` sin coma).

**Librerías involucradas:**
- `pydantic`: valida y tipea el body de la petición.
- `rapidfuzz` (`fuzz.WRatio`): matching difuso tolerante a errores tipográficos.
- `httpx`: llamada a OpenRouter si `use_ai: true` y el fuzzy falla.
- `unicodedata`, `re`: normalización de texto.

**Esquema del body:**

```json
{
  "mode": "single | multiple | all",
  "input": "texto con municipio(s)",
  "use_ai": true,
  "return_valid_options": false,
  "search_level": "municipio | departamento",
  "department_filter": "Antioquia"
}
```

**Campo `department_filter`:**

Restringe el índice de búsqueda a los municipios de un único departamento **antes** de correr el matching. Esto evita que municipios con nombres repetidos en Colombia (ej: `Rionegro` existe en Antioquia y Santander) matcheen contra el departamento equivocado.

- **Fase 1:** el valor por defecto es `"Antioquia"` — no es necesario enviarlo explícitamente.
- **Para buscar en toda Colombia:** enviar `"department_filter": null`.
- **`mode: "all"` con filtro activo:** retorna solo los municipios del departamento filtrado (~125 para Antioquia), no los 1122 del país.

```json
// Solo Antioquia (comportamiento por defecto en Fase 1)
{ "mode": "multiple", "input": "Bello, Rionegro, Envigado" }

// Todos los departamentos
{ "mode": "multiple", "input": "Bogotá, Cali, Medellín", "department_filter": null }

// Todos los municipios de Colombia
{ "mode": "all", "department_filter": null }

// Todos los municipios de Antioquia
{ "mode": "all" }
```

---

#### Modo `single` — un municipio

```bash
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "single",
    "input": "medellin",
    "search_level": "municipio"
  }'
```

```json
{
  "mode": "single",
  "search_level": "municipio",
  "total_received": 1,
  "accepted_count": 1,
  "rejected_count": 0,
  "used_ai": false,
  "selected_locations": [
    {"municipio": "Medellín", "departamento": "Antioquia"}
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

#### Modo `multiple` — varios municipios separados por coma

```bash
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "multiple",
    "input": "Medellín, envigado, rionegro",
    "search_level": "municipio"
  }'
```

```json
{
  "mode": "multiple",
  "search_level": "municipio",
  "total_received": 3,
  "accepted_count": 3,
  "rejected_count": 0,
  "used_ai": false,
  "selected_locations": [
    {"municipio": "Medellín", "departamento": "Antioquia"},
    {"municipio": "Envigado", "departamento": "Antioquia"},
    {"municipio": "Rionegro", "departamento": "Antioquia"}
  ],
  "matches": ["..."]
}
```

---

#### Modo `all` — todos los municipios del departamento activo (o del país)

```bash
# Solo Antioquia (Fase 1, department_filter por defecto)
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{"mode": "all"}'

# Todos los municipios de Colombia
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{"mode": "all", "department_filter": null}'
```

---

#### `search_level: "departamento"` — todos los municipios de un departamento

```bash
curl -X POST http://localhost:8005/match-cities \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "single",
    "input": "Antioquia",
    "search_level": "departamento"
  }'
```

Retorna los 125 municipios de Antioquia como `selected_locations`.

---

### POST `/validate-location`

**Qué hace:** Alias de `/match-cities` con `mode` forzado a `"single"`. Internamente redirige la petición al mismo handler. Útil para integraciones con bots de Telegram u otros clientes que solo necesitan validar una ubicación a la vez sin especificar el modo.

**Librerías involucradas:** Las mismas que `/match-cities`.

**Retorna:** La misma estructura que `/match-cities` en modo `single`.

```bash
curl -X POST http://localhost:8005/validate-location \
  -H "Content-Type: application/json" \
  -d '{
    "input": "medellin",
    "search_level": "municipio"
  }'
```

---

## Campos de respuesta (`matches`)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `original` | string | Texto tal como fue enviado |
| `normalized` | string | Texto normalizado internamente (sin tildes, minúsculas, guiones) |
| `final_municipio` | string \| null | Municipio canónico encontrado |
| `departamento` | string \| null | Departamento correspondiente |
| `score` | int (0-100) | Nivel de confianza del match |
| `accepted` | bool | `true` si el match supera el umbral de aceptación |
| `source` | string | `exact`, `fuzzy_high`, `fuzzy_medium`, `ai`, `rejected` |
| `suggestion` | string \| null | Sugerencia cuando `accepted: false` |
| `reason` | string \| null | Razón del rechazo o baja confianza |

---

## Performance

| Operación | Tiempo estimado |
|-----------|----------------|
| Health check | < 10 ms |
| Listar departamentos | < 50 ms (caché) |
| Buscar municipio | < 20 ms (caché) |
| Match single | < 100 ms |
| Match multiple (10 ciudades) | < 300 ms |
| Carga inicial desde api-colombia.com | 2 – 5 s |

---

## Checklist de integración

- [ ] API ejecutándose en el puerto 8005
- [ ] `GET /health` retorna `"status": "ok"`
- [ ] `GET /departments` retorna 32 departamentos
- [ ] `POST /match-cities` responde correctamente con un ejemplo
- [ ] Caché cargada en menos de 5 segundos al iniciar
- [ ] (Opcional) Variables de entorno de OpenRouter configuradas si se requiere corrección por IA

---

## Troubleshooting

**Error al conectar con api-colombia.com:**

```bash
# Verificar conectividad
ping api-colombia.com

# Probar el endpoint directamente
curl https://api-colombia.com/api/v1/Department
```

**`ModuleNotFoundError: No module named 'rapidfuzz'`:**

```bash
pip install -r requirements.txt
```

**Caché desactualizada o datos incorrectos:**

```bash
curl http://localhost:8005/refresh-cache
```

---

## Fuente de datos

- [api-colombia.com](https://api-colombia.com) — API pública, sin autenticación
  - `https://api-colombia.com/api/v1/Department` → 32 departamentos
  - `https://api-colombia.com/api/v1/City` → ~1122 municipios
