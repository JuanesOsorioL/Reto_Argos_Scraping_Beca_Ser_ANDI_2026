# OpenStreetMaps API — Argos Scraper

Servicio de scraping sobre **OpenStreetMap / Overpass API** para encontrar ferreterías, distribuidoras de materiales de construcción y negocios afines en Colombia. Normaliza, filtra y persiste los resultados en PostgreSQL.

---

## Qué hace

1. **Recibe** una lista de municipios y/o palabras clave desde n8n (u otro cliente HTTP).
2. **Consulta Overpass API** con 5 estrategias de búsqueda (familias OSM) por cada municipio.
3. **Filtra** resultados irrelevantes con 3 capas: tag excluido → palabras negativas → score mínimo.
4. **Persiste** únicamente los registros aprobados en la tabla `raw.overpass_ferreterias` de PostgreSQL.
5. **Notifica** a n8n al finalizar con métricas completas vía webhook.

---

## Requisitos previos

| Requisito | Detalle |
|-----------|---------|
| Python 3.11+ | o Docker (recomendado) |
| PostgreSQL | con un usuario y base de datos disponibles |
| Variable `N8N_WEBHOOK_URL` | URL del webhook de n8n para recibir el callback al finalizar |

---

## Instalación local

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Crear archivo .env en la raíz del proyecto
```

### Archivo `.env`

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=tu_password

N8N_WEBHOOK_URL=https://tu-instancia-n8n/webhook/overpass

PORT=8007

SAVE_LOG_FILES=false
SAVE_OUTPUT_FILES=false
```

> `SAVE_LOG_FILES=true` → guarda logs en `logs/overpass-FECHA.log`  
> `SAVE_OUTPUT_FILES=true` → guarda JSONL y JSON de métricas en `output/`

---

## Cómo iniciarlo

### Opción 1 — Local (API HTTP)

```bash
python api_runner.py
```

El servicio queda disponible en `http://localhost:8007`.

### Opción 2 — Docker

```bash
# Construir imagen
docker build -t argos-overpass .

# Ejecutar contenedor
docker run -p 8007:8007 --env-file .env argos-overpass
```

Desde n8n (dentro de Docker), la URL del servicio es:
```
http://host.docker.internal:8007
```

### Opción 3 — CLI directa (sin API)

```bash
python main.py                    # Todos los municipios
python main.py --test             # Solo 5 ciudades principales
python main.py --dept Antioquia   # Un departamento completo
python main.py --limit 50         # Primeros 50 municipios
```

---

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET`  | `/health` | Verificación de vida del servicio |
| `GET`  | `/status` | Estado actual de la corrida en curso |
| `GET`  | `/resultado` | Resumen y métricas de la última corrida |
| `GET`  | `/endpoints` | Lista todas las rutas disponibles |
| `POST` | `/scrape/overpass` | **Endpoint principal** — inicia scraping |
| `POST` | `/scrape/overpass/prueba` | Scraping de prueba (solo Medellín) |
| `POST` | `/scrape/overpass/depto` | Scraping de un departamento completo |
| `POST` | `/test/callback` | Simula un callback hacia n8n |

---

## Body del endpoint principal

```
POST /scrape/overpass
```

**Ambos campos son opcionales.** Si no llega ninguno, se usan los valores por defecto.

```json
{
  "selected_locations": [
    { "municipio": "Medellín", "departamento": "Antioquia" },
    { "municipio": "Bogotá",   "departamento": "Cundinamarca" }
  ],
  "keywords": ["ferreterias", "cemento", "depositos de materiales"]
}
```

| Campo | Tipo | Comportamiento si no llega |
|-------|------|---------------------------|
| `selected_locations` | `list` de `{municipio, departamento}` | Usa todos los municipios de Colombia (~1122) |
| `keywords` | `list` de strings | Usa las palabras clave por defecto definidas en `main.py` |

### Body desde n8n

```
{{ {
  selected_locations: $json['municipios '],
  keywords: $json.keywords
} }}
```

---

## Cómo funciona la búsqueda — Las 5 familias OSM

Por cada municipio se ejecutan **5 queries independientes** a Overpass:

| # | Familia | Qué busca | Score base |
|---|---------|-----------|-----------|
| 1 | `hardware` | `shop=hardware` (ferreterías estándar) | +5 |
| 2 | `building_materials` | `shop=building_materials` | +5 |
| 3 | `trade_supplies` | `shop=trade` (distribuidoras) | +1 |
| 4 | `doityourself` | `shop=doityourself` (mejoramiento hogar) | +1 |
| 5 | `text_search` | Busca por nombre con regex (tus keywords) | +0 base |

> Las keywords que envías **solo afectan la familia 5**. Las demás 4 son fijas porque buscan por tipo de negocio según la clasificación de OSM, no por nombre.

**Total de queries = `N municipios × 5`**

---

## Sistema de filtrado — 3 capas

Solo se guarda en BD lo que supera las 3 capas:

### Capa 1 — Tag OSM excluido (descarte inmediato)
Si el lugar tiene un tag `shop` irrelevante, se descarta sin calcular score:

```
pharmacy, chemist, fuel, car_repair, auto_parts, veterinary,
pet, supermarket, convenience, bakery, butcher, clothes, beauty,
electronics, mobile_phone, coffee, cafe, florist, optician,
laundry, dry_cleaning, car_wash, alcohol, tobacco, books, jewelry, shoes
```

### Capa 2 — Palabras negativas en el nombre (score -10)
Si el nombre contiene alguna de estas palabras, el score baja a negativo y no se guarda:

```
droguer, farmac, veterinar, lubricant, aceite motor,
cafeter, cafetero, panaderi, carnicer, ropa, calzado,
optic, joyeri, florist, lavanderi, tintoreri,
televis, celular, computad, licor, licorer, cigarr, tabac,
barberi, salon de bell, estetica, taller autom, llantera
```

### Capa 3 — Score mínimo (umbral = 2)
El score se calcula así:

```
hardware / building_materials  → +5 puntos
trade_supplies / doityourself  → +1 punto  (necesitan también palabra positiva en nombre)
text_search                    → +0 base

Palabras positivas en nombre (ferreter, cemento, concreto, mortero,
prefabric, bloquera, ladriller, deposito, material construccion) → +2 c/u
```

Solo se inserta en BD si `score >= 2`.

---

## Respuesta al iniciar un scraping

```json
{
  "status": "iniciado",
  "run_id": "uuid-generado",
  "inicio": "2026-05-05T10:00:00",
  "mensaje": "Consulta GET /status para ver el progreso.",
  "webhook_n8n": "https://tu-n8n/webhook/...",
  "tipo_ejecucion": "produccion"
}
```

El scraping corre en **background**. Consulta `GET /status` para monitorear y espera el webhook al finalizar.

---

## Callback que llega a n8n al finalizar

```json
{
  "evento": "overpass.finalizado",
  "status": "ok",
  "run_id": "uuid",
  "inicio": "...",
  "fin": "...",
  "duracion": "12m 35s",
  "metricas": {
    "municipios": 2,
    "queries_ok": 10,
    "queries_err": 0,
    "elementos_total": 150,
    "insertados": 42,
    "duplicados": 8,
    "aprobados": 42,
    "fallidos": 0
  },
  "tipo_ejecucion": "produccion"
}
```

---

## Base de datos

**Tabla:** `raw.overpass_ferreterias`  
**Esquema:** se crea automáticamente al iniciar el servicio si no existe.

Campos destacados:

| Campo | Descripción |
|-------|-------------|
| `hash_id` | Clave única (`overpass\|osm_type\|osm_id`) — evita duplicados |
| `run_id` | UUID de la corrida que generó el registro |
| `nombre`, `municipio`, `departamento` | Datos base del lugar |
| `latitud`, `longitud` | Georreferenciación |
| `telefono`, `correo_electronico`, `website` | Contacto |
| `score` | Puntaje calculado (solo se guardan score >= 2) |
| `aprobado_argos` | Siempre `true` para registros guardados |
| `familia_osm` | Familia que encontró el lugar |
| `raw_response` | Payload completo de OSM en JSONB |

---

## Puntos importantes a tener en cuenta

- **Solo corre una corrida a la vez.** Si se llama `/scrape/overpass` mientras hay una activa, devuelve `HTTP 409`. Espera a que termine o consulta `/status`.

- **La deduplicación es global**, no por corrida. Si un lugar ya existe en BD de una corrida anterior, no se vuelve a insertar. Esto es por diseño para evitar duplicados acumulados.

- **Overpass API es pública y puede saturarse.** El cliente aplica backoff exponencial (5s → 10s → 20s → 30s) y rota entre 3 endpoints distintos. Si todos fallan, espera 60s y hace un último intento.

- **El scraping puede tardar horas** si se lanzan muchos municipios. Para Colombia completa (~1122 municipios × 5 familias = 5610 queries, con pausa de 2s entre cada una) el tiempo estimado es de varias horas.

- **Los logs se ven en consola** en tiempo real. Para guardarlos en archivo activar `SAVE_LOG_FILES=true` en `.env`.

- **`N8N_WEBHOOK_URL` es obligatoria** para recibir el callback al finalizar. Si no está configurada, el scraping corre igual pero falla silenciosamente al intentar notificar.

- **El Dockerfile expone el puerto 8007** y arranca `api_runner.py` directamente. Las variables de entorno deben pasarse con `--env-file .env`.

---

## Estructura de archivos

```
OpenStreetMapsAPI/
├── api_runner.py          # Servidor FastAPI — endpoints HTTP y orquestación
├── main.py                # Motor de scraping, filtros, scoring y persistencia
├── municipios_colombia.py # Catálogo estático de ~1122 municipios de Colombia
├── requirements.txt       # Dependencias Python
├── dockerfile             # Imagen Docker del servicio
├── .env                   # Variables de entorno (no subir al repo)
├── logs/                  # Logs por fecha (si SAVE_LOG_FILES=true)
└── output/                # JSONL y JSON de métricas (si SAVE_OUTPUT_FILES=true)
```
