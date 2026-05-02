# AnalisisCoberturaAPI

API que analiza qué municipios tienen baja cobertura de datos tras correr las 4 fuentes principales (RUES, Google Maps, Páginas Amarillas, OpenStreetMaps), y retorna la lista de municipios a procesar con Serper junto con las keywords optimizadas.

## ¿Qué hace?

1. Recibe los 1,123 municipios de Colombia en el body.
2. Consulta las 4 tablas de PostgreSQL y cuenta registros por municipio.
3. Identifica cuáles están por debajo del umbral configurado (default: 5 registros).
4. Retorna:
   - Lista de municipios con baja cobertura (ordenados de menor a mayor).
   - Keywords recomendadas para enviar a Serper (6 más efectivas).
   - Resumen estadístico del análisis.

## Flujo en n8n

```
OpenStreetMaps finaliza
        ↓
POST /analizar/cobertura  ← (este servicio)
        ↓
Respuesta: municipios con baja cobertura + keywords
        ↓
POST SerperAPI /scrape/serper
  body: { selected_locations: [...], keywords: [...] }
```

## Levantar el servicio

```bash
# Desde esta carpeta
docker-compose up -d --build

# Verificar que está corriendo
curl http://localhost:8008/health
```

## Endpoint principal

### `POST /analizar/cobertura`

**Body:**
```json
{
  "municipios": [
    {"municipio": "Medellín",  "departamento": "Antioquia"},
    {"municipio": "Támesis",   "departamento": "Antioquia"},
    {"municipio": "Bogotá",    "departamento": "Cundinamarca"}
  ],
  "umbral": 5
}
```

> `umbral` es opcional. Si no se envía, usa el valor de `UMBRAL_BAJO_COBERTURA` en el `.env` (default 5).

**Respuesta:**
```json
{
  "resumen": {
    "total_municipios_analizados": 3,
    "municipios_bajo_cobertura": 1,
    "municipios_cubiertos": 2,
    "umbral_usado": 5
  },
  "keywords": [
    "ferreterias",
    "depositos de materiales",
    "distribuidora de construccion",
    "cemento al por mayor",
    "bloqueras",
    "ladrilleras"
  ],
  "municipios_bajo_cobertura": [
    {
      "municipio": "Támesis",
      "departamento": "Antioquia",
      "total_registros": 1,
      "detalle": {
        "rues": 1,
        "google_maps": 0,
        "paginas_amarillas": 0,
        "openstreetmap": 0
      }
    }
  ]
}
```

Luego en n8n tomar `municipios_bajo_cobertura` y `keywords` y enviarlo directamente al endpoint de Serper:

```json
{
  "selected_locations": <municipios_bajo_cobertura>,
  "keywords": <keywords>
}
```

## Variables de entorno

| Variable                  | Default       | Descripción                                      |
|---------------------------|---------------|--------------------------------------------------|
| `DB_HOST`                 | `postgressArgos` | Host de PostgreSQL                            |
| `DB_PORT`                 | `5432`        | Puerto de PostgreSQL                             |
| `DB_NAME`                 | `argos`       | Nombre de la base de datos                       |
| `DB_USER`                 | `postgres`    | Usuario de PostgreSQL                            |
| `DB_PASSWORD`             | —             | Contraseña de PostgreSQL                         |
| `UMBRAL_BAJO_COBERTURA`   | `5`           | Mínimo de registros para considerar un municipio cubierto |
| `ANALISIS_PORT`           | `8008`        | Puerto en que corre la API                       |

## Otros endpoints

| Endpoint   | Método | Descripción                          |
|------------|--------|--------------------------------------|
| `/health`  | GET    | Estado del servicio y conexión a BD  |
| `/status`  | GET    | Config actual (umbral, keywords, fuentes) |
| `/docs`    | GET    | Swagger UI interactivo               |
