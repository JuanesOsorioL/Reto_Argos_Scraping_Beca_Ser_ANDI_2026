# Dashboard Argos — Oportunidades de Mercado

Dashboard interactivo que visualiza los datos consolidados de ferreterias en un mapa de Colombia, contrasta prospectos del scraping contra la base de clientes existentes de Argos, y permite exportar resultados clasificados.

---

## Tabla de Contenidos

1. [Arquitectura del Dashboard](#1-arquitectura-del-dashboard)
2. [Flujo de Datos Completo](#2-flujo-de-datos-completo)
3. [Estructura de Archivos](#3-estructura-de-archivos)
4. [Componentes Detallados](#4-componentes-detallados)
5. [Integracion con el Sistema](#5-integracion-con-el-sistema)
6. [Algoritmo de Matching](#6-algoritmo-de-matching-y-clasificacion)
7. [Mapa Interactivo](#7-mapa-interactivo)
8. [Geocodificacion](#8-geocodificacion)
9. [API de Control](#9-api-de-control-puerto-8010)
10. [Configuracion y Despliegue](#10-configuracion-y-despliegue)
11. [Uso del Dashboard](#11-uso-del-dashboard)

---

## 1. Arquitectura del Dashboard

El dashboard opera como un contenedor Docker que ejecuta **dos procesos** en paralelo:

```
┌─────────────────────────────────────────────────────────────────┐
│               Container: argos-dashboard                         │
│                                                                  │
│  ┌─────────────────────────┐   ┌─────────────────────────────┐  │
│  │   Streamlit (app.py)    │   │   FastAPI (api_control.py)   │  │
│  │      Puerto 8050        │   │       Puerto 8010            │  │
│  │                         │   │                              │  │
│  │  - UI interactiva       │   │  - Recibe webhooks n8n       │  │
│  │  - Mapa Folium          │   │  - Escribe state file        │  │
│  │  - Graficas Plotly      │   │  - Health check              │  │
│  │  - Export CSV           │   │  - URL publica               │  │
│  └───────────┬─────────────┘   └──────────────┬───────────────┘  │
│              │                                 │                  │
│              ▼                                 ▼                  │
│       state/refresh.json  ◄────────────────────┘                 │
│              │                                                    │
│              ▼                                                    │
│    [Detecta cambio timestamp → limpia cache → rerun]             │
└──────────────────────────────────────────────────────────────────┘
         │                    │                      │
         ▼                    ▼                      ▼
   PostgreSQL          Excel Argos           Cloudflare Tunnel
   clean.empresas      (.xlsx upload)        (URL publica)
```

### Dos Procesos, Un Estado

| Proceso | Puerto | Rol |
|---------|--------|-----|
| **Streamlit** (`app.py`) | 8050 | UI web. Lee `state/refresh.json` en cada rerun para detectar actualizaciones |
| **FastAPI** (`api_control.py`) | 8010 | API REST. Recibe webhook de n8n y escribe `state/refresh.json` |

La comunicacion entre ambos ocurre a traves del **archivo de estado** (`state/refresh.json`), un volumen Docker compartido.

---

## 2. Flujo de Datos Completo

### Diagrama de Secuencia

```
n8n (pipeline completado)
  │
  │ POST /webhook/refresh
  │ {municipios, selected_locations, execution_id, empresas_consolidadas}
  │
  ▼
FastAPI (api_control.py :8010)
  │
  │ Escribe state/refresh.json con timestamp actual
  │
  ▼
Streamlit (app.py :8050) — detecta timestamp nuevo
  │
  ├── st.cache_data.clear() → limpia cache
  ├── st.rerun() → recarga completa
  │
  ▼
cargar_prospectos() → PostgreSQL clean.empresas
  │                    SELECT ... WHERE latitud IS NOT NULL
  │
  ▼
cargar_clientes_argos() → Lee Excel .xlsx (subido o default)
  │                        Deduplica por codigo_cliente
  │                        Normaliza nombres, direcciones, municipios
  │
  ▼
contrastar(df_prospectos, df_clientes) → Fuzzy matching
  │
  ├── prospecto_nuevo (azul) → No matchea con ningun cliente Argos
  ├── cliente_confirmado (verde) → Match nombre >= 85%
  ├── cliente_probable (naranja) → Match nombre 70-85% + direccion >= 60%
  └── cliente_argos_sin_datos (rojo) → Cliente Argos sin par en scraping
  │
  ▼
construir_mapa() → Mapa Folium con 4 capas + heatmap
  │
  ▼
Renderizado: KPIs + Mapa + Graficas + Tablas exportables
```

### Fuentes de Datos

| Fuente | Que Aporta | Como se Conecta |
|--------|------------|-----------------|
| **PostgreSQL** (`clean.empresas`) | Prospectos scrapeados y consolidados | Conexion directa via `DATABASE_URL` |
| **Excel Argos** (`.xlsx`) | Clientes existentes de Argos | Upload en sidebar o archivo default en `data/` |
| **Nominatim API** | Coordenadas para clientes sin geoloc | API gratuita OSM con cache local |
| **state/refresh.json** | Trigger de actualizacion desde n8n | Archivo JSON en volumen compartido |
| **dashboard-url.txt** | URL publica del tunnel | Escrito por contenedor cloudflared |

---

## 3. Estructura de Archivos

```
streamlit/
├── app.py                      # Aplicacion principal Streamlit (410 lineas)
├── api_control.py              # API FastAPI de control (164 lineas)
├── start.sh                    # Script de inicio (FastAPI bg + Streamlit fg)
├── Dockerfile                  # Imagen Docker (python:3.11-slim)
├── requirements.txt            # Dependencias Python
├── state/                      # Directorio de estado (volumen Docker)
│   ├── .gitkeep
│   └── refresh.json            # Estado del webhook (runtime, no versionado)
├── data/                       # Datos y cache
│   ├── clientes_argos.xlsx     # Excel default de clientes Argos
│   ├── clientes_argos_tmp.xlsx # Excel subido por el usuario (runtime)
│   └── geocoding_cache.json    # Cache persistente de geocodificacion
└── utils/                      # Modulos de utilidad
    ├── __init__.py
    ├── data_loader.py          # Carga de BD y algoritmo de matching (246 lineas)
    ├── map_builder.py          # Construccion del mapa Folium (314 lineas)
    ├── geocoder.py             # Geocodificacion via Nominatim (149 lineas)
    ├── normalizar.py           # Normalizacion de texto (68 lineas)
    └── ciudades.py             # Datos de referencia: ciudades y departamentos (49 lineas)
```

---

## 4. Componentes Detallados

### 4.1 `app.py` — Aplicacion Principal

Archivo central que orquesta toda la logica del dashboard.

**Secuencia de ejecucion (cada rerun de Streamlit):**

1. **Lectura del state file** — Detecta si n8n envio webhook nuevo comparando timestamps
2. **Auto-refresh** — Si hay nuevo timestamp: `st.cache_data.clear()` + `st.rerun()`
3. **Resolucion de municipios** — Prioridad: state file > URL params > BD completa
4. **Sidebar** — Renderiza filtros: Excel upload, multiselect municipios, sliders, checkboxes
5. **Carga de prospectos** — Query a PostgreSQL (cacheado por `@st.cache_data`)
6. **Carga de clientes** — Lee Excel de Argos (cacheado)
7. **Geocodificacion** — Si hay clientes sin coordenadas, ofrece boton para geocodificar
8. **Contraste** — Ejecuta matching fuzzy entre prospectos y clientes
9. **Filtrado** — Aplica score de calidad, aprobacion, categorias seleccionadas
10. **Renderizado** — KPIs, mapa, graficas (bar + pie), tablas con export CSV

**Parametros de URL soportados:**

```
http://localhost:8050/?municipios=medellin,bogota,cali
```

Permite precargar municipios sin necesidad de webhook.

**Filtros del sidebar:**

| Filtro | Tipo | Rango/Opciones |
|--------|------|----------------|
| Score de calidad | Slider | 0–140 (step 5) |
| Solo aprobados Argos | Checkbox | true/false |
| Categorias a mostrar | Multiselect | 4 categorias |
| Heatmap de densidad | Checkbox | true/false |
| Municipios | Multiselect | Todos los de clean.empresas |

---

### 4.2 `utils/data_loader.py` — Motor de Datos y Matching

#### `cargar_prospectos(municipios, locations)`

```sql
SELECT empresa_id::text,
       COALESCE(nombre_comercial, razon_social, nombre_normalizado) AS nombre_comercial,
       nombre_normalizado, municipio, departamento,
       direccion_principal, direccion_normalizada,
       latitud, longitud,
       telefono_principal AS telefono,
       correo_principal AS correo, sitio_web,
       score_calidad, aprobado_argos, fuente_principal
FROM clean.empresas
WHERE latitud IS NOT NULL AND longitud IS NOT NULL
```

- Si se pasan `locations` (municipio+departamento): filtra por pares exactos
- Si se pasan `municipios` (lista): filtra por nombre normalizado
- Si no se pasa nada: retorna todos los registros con coordenadas

#### `cargar_clientes_argos(path_excel, municipios)`

Lee el Excel de clientes Argos con columnas esperadas:

| Columna Excel | Alias Interno | Uso |
|---------------|---------------|-----|
| `Codigo de cliente` | Deduplicacion | Clave unica, clave de cache geocoding |
| `Nombre de la cuenta` | `nombre_norm` | Matching fuzzy contra prospectos |
| `Direccion` | `dir_norm` | Matching secundario de direcciones |
| `Poblacion` o `Poblacion: Poblacion` | `municipio_norm` | Agrupacion por municipio |
| `Departamento (Texto)` o `Departamento` | `depto_argos` | Contexto geografico |
| `Movil` | `movil_argos` | Informacion de contacto |

#### `contrastar(df_prospectos, df_clientes)`

Retorna tupla `(df_prospectos_enriquecido, df_clientes_sin_datos)`.

Columnas agregadas al DataFrame de prospectos:
- `categoria`: clasificacion resultante
- `score_match`: porcentaje de similitud con el cliente Argos
- `nombre_argos_match`: nombre del cliente Argos con el que matcheo

---

### 4.3 `utils/map_builder.py` — Construccion del Mapa

#### Configuracion del mapa base

```python
folium.Map(
    location=[4.5709, -74.2973],  # Centro de Colombia
    zoom_start=6,
    tiles='CartoDB positron',
)
```

#### 4 Capas de marcadores (MarkerCluster)

| Categoria | Color | Icono | Fuente de Coordenadas |
|-----------|-------|-------|----------------------|
| `prospecto_nuevo` | Azul | info-sign | PostgreSQL (lat/lon) |
| `cliente_confirmado` | Verde | ok-sign | PostgreSQL (lat/lon) |
| `cliente_probable` | Naranja | question-sign | PostgreSQL (lat/lon) |
| `cliente_argos_sin_datos` | Rojo | warning-sign | Geocodificacion Nominatim o centroide |

#### Validacion de coordenadas

1. **Bounding box de Colombia:** lat [-4.2, 13.0], lon [-82.0, -67.0]
   - Coordenadas fuera de este rango se descartan
2. **Snap-to-centroid:** Si la coordenada esta a >100 km del centroide del municipio esperado, se reemplaza por el centroide
   - Evita que errores de geocodificacion distorsionen el mapa
3. **Centroides hardcodeados:** 100+ municipios colombianos con coordenadas de referencia

#### Heatmap

- Solo incluye prospectos nuevos (azules)
- Parametros: radius=18, blur=15, min_opacity=0.3
- Aplica la misma logica de snap-to-centroid

#### Contenido del Popup

```
┌──────────────────────────────┐
│ FERRETERIA EL CONSTRUCTOR    │
│ Medellín, Antioquia          │
│ Calle 45 #23-10              │
│ Tel: 3001234567              │
│ Score calidad: 95            │
│ Match Argos: CONSTRUCTOR     │
│ S.A.S (87%)                  │
└──────────────────────────────┘
```

---

### 4.4 `utils/geocoder.py` — Geocodificacion

Convierte direcciones de clientes Argos (que no tienen lat/lon en el scraping) a coordenadas.

#### API utilizada

- **Nominatim** (OpenStreetMap): gratuita, sin API key
- **Limite:** 1 request por segundo (delay 1.1s entre llamadas)
- **User-Agent:** `ArgosOpportunityDashboard/1.0 (reto-beca-andi-argos)`

#### Estrategia de geocodificacion

```
Intento 1: "{direccion}, {municipio}, {departamento}, Colombia"
    → Si encuentra: guardar en cache
    → Si no: pasar a intento 2

Intento 2: "{municipio}, {departamento}, Colombia"
    → Si encuentra: guardar en cache (precision a nivel ciudad)
    → Si no: cache[clave] = None (no reintentar)
```

#### Cache persistente

- **Archivo:** `data/geocoding_cache.json`
- **Clave:** Codigo de cliente (o hash `dir|ciudad|depto` si no hay codigo)
- **Valor:** `{"lat": float, "lon": float}` o `null`
- **Persistencia:** Sobrevive reinicios del contenedor (volumen Docker)

#### Flujo en la UI

1. Se carga el Excel de clientes Argos
2. Se cuenta cuantos no tienen entrada en el cache
3. Si hay pendientes: muestra boton "Geocodificar clientes" en sidebar
4. Al hacer click: barra de progreso + llamadas secuenciales a Nominatim
5. Al terminar: limpia cache de Streamlit + rerun para mostrar marcadores

---

### 4.5 `utils/normalizar.py` — Normalizacion de Texto

Tres funciones que estandarizan texto para matching:

#### `normalizar_nombre(texto)`
```
"Ferretería El Constructor S.A.S." → "FERRETERIA EL CONSTRUCTOR SAS"
```
- Elimina tildes, convierte a mayuscula, elimina puntuacion

#### `normalizar_direccion(texto)`
```
"Cra. 45 #23-10, Barrio Centro" → "CARRERA 45 23 10 BARRIO CENTRO"
```
- Expande 20+ abreviaturas colombianas: CRA→CARRERA, CL→CALLE, TV→TRANSVERSAL, AV→AVENIDA, DIAG→DIAGONAL, KM→KILOMETRO, AP→APARTAMENTO, BLQ→BLOQUE, OF→OFICINA, etc.

#### `normalizar_municipio(texto)`
```
"Medellín" → "MEDELLIN"
"Santa-Marta" → "SANTA MARTA"
```
- Elimina tildes, mayuscula, reemplaza guiones por espacios

---

### 4.6 `utils/ciudades.py` — Datos de Referencia

Lista hardcodeada de 69 municipios colombianos con su departamento. Sirve como fallback cuando PostgreSQL no esta disponible para el multiselect de municipios.

---

## 5. Integracion con el Sistema

### 5.1 Trigger desde n8n

Cuando el pipeline de consolidacion (`api-ferreterias`) termina, n8n ejecuta:

```http
POST http://argos-dashboard:8010/webhook/refresh
Content-Type: application/json

{
  "municipios": ["medellin", "envigado", "itagui"],
  "selected_locations": [
    {"municipio": "medellin", "departamento": "Antioquia"},
    {"municipio": "envigado", "departamento": "Antioquia"},
    {"municipio": "itagui", "departamento": "Antioquia"}
  ],
  "execution_id": "exec-20260505-abc123",
  "empresas_consolidadas": 1847,
  "triggered_by": "n8n"
}
```

### 5.2 State File (Mecanismo de Comunicacion)

El archivo `state/refresh.json` actua como bus de mensajes entre FastAPI y Streamlit:

```json
{
  "timestamp": "2026-05-05T14:30:00.123456+00:00",
  "municipios": ["medellin", "envigado", "itagui"],
  "selected_locations": [
    {"municipio": "medellin", "departamento": "Antioquia"}
  ],
  "execution_id": "exec-20260505-abc123",
  "empresas_consolidadas": 1847,
  "triggered_by": "n8n"
}
```

**Mecanismo de deteccion:**
- Streamlit almacena el ultimo `timestamp` leido en `st.session_state.ultimo_state_ts`
- En cada rerun, compara el timestamp actual del archivo con el almacenado
- Si difieren: `st.cache_data.clear()` + `st.rerun()` → recarga automatica

### 5.3 Cloudflare Tunnel (Acceso Publico)

El contenedor `cloudflared-dashboard` crea un Quick Tunnel hacia `argos-dashboard:8050`:

```
cloudflared tunnel --url http://argos-dashboard:8050
```

La URL publica generada (ej: `https://abc123.trycloudflare.com`) se guarda en el volumen compartido `/shared/dashboard-url.txt`. La API de control puede retornar esta URL via `GET /dashboard-url`.

### 5.4 Docker Compose (Extracto relevante)

```yaml
argos-dashboard:
  build: ./streamlit
  container_name: argos-dashboard
  ports:
    - "8050:8050"   # Streamlit UI
    - "8010:8010"   # FastAPI control
  environment:
    DATABASE_URL: postgresql://postgres:1234@postgressArgos:5432/postgres
    STATE_FILE: /app/state/refresh.json
  volumes:
    - ./streamlit/data:/app/data           # Excel de clientes + cache geocoding
    - dashboard_state:/app/state           # State file (webhook trigger)
    - cloudflare_data:/shared              # URL publica del tunnel
  depends_on:
    postgressArgos:
      condition: service_healthy
  networks:
    - automatizacion_net

cloudflared-dashboard:
  build: ./cloudflared
  volumes:
    - cloudflare_data:/shared              # Escribe dashboard-url.txt aqui
  depends_on:
    - argos-dashboard
```

---

## 6. Algoritmo de Matching y Clasificacion

### Objetivo

Clasificar cada prospecto scrapeado en relacion con la base de clientes existentes de Argos para identificar:
- Oportunidades nuevas (prospectos que no son clientes actuales)
- Confirmaciones (prospectos que ya son clientes)
- Posibles matches (alta probabilidad de ser el mismo cliente)
- Gaps (clientes de Argos que el scraping no encontro)

### Umbrales

| Umbral | Valor | Uso |
|--------|-------|-----|
| `UMBRAL_CONFIRMADO` | 85% | Score de nombre >= 85% → cliente confirmado |
| `UMBRAL_PROBABLE` | 70% | Score de nombre >= 70% (requiere ademas match de direccion) |
| `UMBRAL_DIR` | 60% | Score de direccion >= 60% (para confirmar probable) |

### Algoritmo Paso a Paso

```python
# 1. Indexar clientes Argos por municipio normalizado
idx_por_municipio = {municipio: [(nombre_norm, dir_norm, nombre_original), ...]}

# 2. Para cada prospecto scrapeado:
for prospecto in df_prospectos:
    municipio = normalizar(prospecto.municipio)
    candidatos = idx_por_municipio[municipio]  # Solo compara dentro del mismo municipio

    # 3. Buscar mejor match de nombre
    resultado = rapidfuzz.process.extractOne(
        prospecto.nombre_norm,
        [c.nombre_norm for c in candidatos],
        scorer=fuzz.token_sort_ratio,
    )
    score_nombre = resultado.score

    # 4. Clasificar
    if score_nombre >= 85:
        prospecto.categoria = "cliente_confirmado"

    elif score_nombre >= 70:
        score_dir = fuzz.partial_ratio(prospecto.dir_norm, candidato.dir_norm)
        if score_dir >= 60:
            prospecto.categoria = "cliente_probable"
        else:
            prospecto.categoria = "prospecto_nuevo"

    else:
        prospecto.categoria = "prospecto_nuevo"

# 5. Detectar clientes Argos sin match
clientes_sin_match = [c for c in clientes if c.nombre not in clientes_matched]
→ categoria = "cliente_argos_sin_datos"
```

### Funciones de Similitud Usadas

| Funcion | Libreria | Uso |
|---------|----------|-----|
| `fuzz.token_sort_ratio` | RapidFuzz | Comparacion de nombres (ordena tokens, ignora orden) |
| `fuzz.partial_ratio` | RapidFuzz | Comparacion de direcciones (permite substring match) |

### Ejemplo de Clasificacion

| Prospecto Scrapeado | Cliente Argos | Score Nombre | Score Dir | Clasificacion |
|--------------------|--------------:|:-------------|:---------:|:-----------|
| FERRETERIA EL CONSTRUCTOR | FERRETERIA CONSTRUCTOR SAS | 92% | — | cliente_confirmado |
| DEPOSITO LA CASA | DEPOSITOS LA CASA LTDA | 78% | 65% | cliente_probable |
| MATERIALES DON PEDRO | — | <70% | — | prospecto_nuevo |
| — | HIERROS DEL CARIBE SA | — | — | cliente_argos_sin_datos |

---

## 7. Mapa Interactivo

### Capas del Mapa

El mapa usa `folium.LayerControl` para permitir al usuario activar/desactivar capas:

| Capa | Tipo | Contenido |
|------|------|-----------|
| Prospectos nuevos | MarkerCluster (azul) | Negocios nuevos no conocidos por Argos |
| Clientes confirmados | MarkerCluster (verde) | Negocios que matchean >= 85% con clientes |
| Clientes probables | MarkerCluster (naranja) | Negocios con match 70-85% + dir match |
| Clientes sin datos | MarkerCluster (rojo) | Clientes Argos no encontrados en scraping |
| Densidad prospectos | HeatMap | Concentracion geografica de oportunidades |

### Centroides y Validacion

El archivo `map_builder.py` contiene 100+ centroides de municipios colombianos. Se usan para:

1. **Validar coordenadas scrapeadas:** Si una coordenada cae a >100 km del centroide esperado del municipio, se reemplaza por el centroide (evita errores de geocodificacion que colocan marcadores en paises erroneos)

2. **Fallback para clientes sin geocodificar:** Si Nominatim no encuentra la direccion exacta, se usa el centroide del municipio como posicion aproximada

3. **Bounding box de Colombia:** Coordenadas fuera de lat[-4.2, 13.0] lon[-82.0, -67.0] se descartan completamente

---

## 8. Geocodificacion

### Por que es necesaria

Los clientes de Argos (archivo Excel) no tienen coordenadas. Para mostrarlos en el mapa, se geocodifican sus direcciones usando la API gratuita de Nominatim (OpenStreetMap).

### Flujo de geocodificacion

```
Excel cargado
  │
  ▼
contar_sin_geocodificar() → N clientes sin cache
  │
  ├── N = 0 → cargar coords del cache directamente
  │
  └── N > 0 → Mostrar boton "Geocodificar clientes"
                │
                ▼ (click)
              geocodificar_dataframe()
                │
                ├── Para cada cliente:
                │   ├── Buscar en cache → si existe, usar
                │   └── Si no existe:
                │       ├── Intento 1: "dir, municipio, depto, Colombia"
                │       ├── delay 1.1s
                │       ├── Intento 2: "municipio, depto, Colombia"
                │       ├── delay 1.1s
                │       └── Guardar en cache (resultado o null)
                │
                ▼
              Cache actualizado → df con columnas geo_lat, geo_lon
```

### Limitaciones

- **Velocidad:** ~1 cliente/segundo (limitacion de Nominatim)
- **Primera vez:** Si hay 200 clientes, toma ~4 minutos
- **Precision:** Direcciones colombianas son a menudo imprecisas en OSM
- **Fallback:** Si no geocodifica, el marcador se coloca en el centroide del municipio

---

## 9. API de Control (Puerto 8010)

### Endpoints

#### `GET /health`

Health check basico para Docker y balanceadores.

```json
{"status": "ok"}
```

#### `GET /status`

Estado detallado incluyendo conectividad a BD y ultimo refresh.

```json
{
  "status": "running",
  "uptime_seconds": 3600,
  "database_connected": true,
  "last_refresh": {
    "timestamp": "2026-05-05T14:30:00+00:00",
    "municipios": ["medellin", "envigado"],
    "execution_id": "exec-20260505-abc",
    "empresas_consolidadas": 1847,
    "triggered_by": "n8n"
  }
}
```

#### `GET /dashboard-url`

Retorna la URL publica del dashboard (generada por Cloudflare Tunnel).

```json
{
  "url": "https://abc123.trycloudflare.com",
  "available": true
}
```

#### `POST /webhook/refresh`

Recibe notificacion de n8n y escribe el state file para que Streamlit se recargue.

**Request:**
```json
{
  "municipios": ["medellin", "bogota"],
  "selected_locations": [
    {"municipio": "medellin", "departamento": "Antioquia"}
  ],
  "execution_id": "exec-id-123",
  "empresas_consolidadas": 1500,
  "triggered_by": "n8n"
}
```

**Response:**
```json
{
  "ok": true,
  "message": "Dashboard refresh programado",
  "municipios_count": 2,
  "selected_locations_count": 1,
  "dashboard_url": "https://abc123.trycloudflare.com"
}
```

#### `POST /control/stop`

Detiene el servicio graciosamente (util para n8n cuando necesita reiniciar).

---

## 10. Configuracion y Despliegue

### Variables de Entorno

| Variable | Default | Descripcion |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://postgres:1234@localhost:1111/postgres` | Conexion a PostgreSQL |
| `STATE_FILE` | `./state/refresh.json` | Ruta al archivo de estado |
| `DASHBOARD_URL_FILE` | `/shared/dashboard-url.txt` | Ruta al archivo de URL publica |

### Dependencias (requirements.txt)

```
streamlit>=1.35.0           # Framework de dashboard
streamlit-folium>=0.20.0    # Integracion Streamlit + Folium
streamlit-autorefresh>=1.0.1 # Auto-refresh del dashboard
pandas>=2.0.0               # DataFrames
plotly>=5.18.0              # Graficas interactivas
folium>=0.16.0              # Mapas Leaflet
psycopg2-binary>=2.9.9     # Driver PostgreSQL
openpyxl>=3.1.2             # Lectura de Excel .xlsx
rapidfuzz>=3.6.0            # Fuzzy matching
python-dotenv>=1.0.0        # Variables de entorno
fastapi>=0.110.0            # API de control
uvicorn>=0.29.0             # Servidor ASGI
```

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev gcc curl
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p state data && chmod +x start.sh
EXPOSE 8050 8010
CMD ["/bin/sh", "start.sh"]
```

### Script de Inicio (`start.sh`)

```bash
#!/bin/sh
set -e
mkdir -p /app/state /app/data

# Proceso 1: FastAPI control (background)
uvicorn api_control:app --host 0.0.0.0 --port 8010 &

# Proceso 2: Streamlit UI (foreground)
exec streamlit run app.py \
  --server.port 8050 \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.fileWatcherType none
```

### Levantar Solo el Dashboard (Desarrollo Local)

```bash
cd streamlit/

# Instalar dependencias
pip install -r requirements.txt

# Variables de entorno
export DATABASE_URL="postgresql://postgres:1234@localhost:1111/postgres"

# Arrancar ambos procesos
uvicorn api_control:app --host 0.0.0.0 --port 8010 &
streamlit run app.py --server.port 8050
```

---

## 11. Uso del Dashboard

### Interfaz Principal

```
┌─────────────────────────────────────────────────────────────────────────┐
│  🏗️ Dashboard Argos — Oportunidades de mercado                          │
│  Municipios: 12 | Empresas scrapeadas: 2,847 | Filtradas: 1,923         │
├──────────┬──────────┬──────────┬──────────┬──────────────────────────────┤
│ Empresas │Prospectos│ Clientes │ Clientes │ Clientes sin                 │
│scrapeadas│ nuevos   │confirmado│ probables│ datos                        │
│  2,847   │  2,100   │   412    │   335    │    89                        │
├──────────┴──────────┴──────────┴──────────┴──────────────────────────────┤
│  ████████████████░░░░ Cobertura Argos en scraping: 26.2%                 │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│                    [MAPA INTERACTIVO FOLIUM]                              │
│         Marcadores agrupados por cluster + heatmap                       │
│                                                                          │
├────────────────────────────────┬─────────────────────────────────────────┤
│  Top municipios por prospectos │  Distribucion por categoria              │
│  [Grafica de barras Plotly]    │  [Grafica pie Plotly]                    │
├────────────────────────────────┴─────────────────────────────────────────┤
│  Tabs: [Prospectos nuevos] [Clientes sin datos] [Clientes probables]     │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  Tabla con datos + boton "Descargar CSV"                            │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

### Sidebar (Panel Izquierdo)

```
┌───────────────────────────┐
│  [Logo Argos]             │
│                           │
│  BD Clientes Argos        │
│  [📁 Subir Excel .xlsx]   │
│  ✓ Usando: clientes.xlsx  │
│                           │
│  ─────────────────────    │
│  Municipios a analizar    │
│  [multiselect ▼]          │
│  Ultima n8n: 14:30:00     │
│                           │
│  ─────────────────────    │
│  Filtros adicionales      │
│  Score: [===●====] 0-140  │
│  □ Solo aprobados Argos   │
│  Categorias: [todos ▼]    │
│  ☑ Mostrar heatmap        │
│                           │
│  📍 45 clientes sin geoloc│
│  [🌐 Geocodificar]        │
└───────────────────────────┘
```

### Exports Disponibles

| Tab | Contenido | Archivo |
|-----|-----------|---------|
| Prospectos nuevos | Negocios no matcheados con Argos | `prospectos_nuevos.csv` |
| Clientes sin datos | Clientes Argos sin par en scraping | `clientes_sin_datos.csv` |
| Clientes probables | Matches con 70-85% + dir match | `clientes_probables.csv` |

### Metricas KPI Explicadas

| KPI | Formula | Significado |
|-----|---------|-------------|
| Empresas scrapeadas | Total de `clean.empresas` con coords | Todos los prospectos cargados |
| Prospectos nuevos | No matchean con ningun cliente Argos | **Oportunidades de venta** |
| Clientes confirmados | Match nombre >= 85% | Ya son clientes (validacion) |
| Clientes probables | Match 70-85% + dir >= 60% | Posiblemente ya son clientes |
| Clientes sin datos | Clientes Argos sin par en scraping | **Clientes sin presencia digital** |
| Cobertura Argos | (confirmados + probables) / total | % del scraping que ya es cliente |
