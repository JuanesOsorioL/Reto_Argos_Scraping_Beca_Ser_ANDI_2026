# 📖 Explicación Línea por Línea del Código

Este documento explica qué hace cada archivo y cada función en detalle.

---

## 📂 Estructura de Archivos

```
foursquare/
├── .env                          ← Variables de entorno (configuración)
├── config.py                     ← Configuración centralizada
├── db.py                         ← Funciones de base de datos
├── scraper.py                    ← Llamadas a Foursquare API
├── normalizer.py                 ← Mapeo de datos a esquema Argos
├── main.py                       ← Orquestador principal (lógica del scraping)
├── api_runner.py                 ← Servidor HTTP FastAPI
├── data_exporter.py              ← Exportar a Excel
├── requirements.txt              ← Dependencias Python
├── Dockerfile                    ← Imagen Docker
├── docker-compose.yml            ← Orquestación Docker
├── README.md                     ← Documentación completa
├── QUICKSTART.md                 ← Guía rápida
└── output/                       ← Directorio de salida
    ├── foursquare_raw_responses.json
    ├── foursquare_flat_results.json
    └── foursquare_ferreterias.jsonl
```

---

## 🔵 config.py — Configuración Centralizada

**Función**: Leer variables de `.env` y centralizarlas en un lugar.

### Secciones principales:

```python
# ① CARGAR .ENV
load_dotenv()  # Lee el archivo .env

# ② FOURSQUARE API
FSQ_API_KEY = os.getenv("FSQ_API_KEY", "")
FSQ_BASE_URL = "https://places-api.foursquare.com/places/search"
FSQ_HEADERS = {...}  # Headers con autenticación

# ③ KEYWORDS Y CIUDADES
KEYWORDS_BUSQUEDA = ["ferretería", "cemento", ...]  # Qué buscar
CIUDADES = [{"nombre": "Bogotá", "near": "Bogotá, Colombia"}, ...]  # Dónde

# ④ POSTGRESQL
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    ...
}

# ⑤ RATE LIMIT AUTOMÁTICO
AUTO_PAUSE_ON_RATE_LIMIT = os.getenv("AUTO_PAUSE_ON_RATE_LIMIT", "true")
RATE_LIMIT_SLEEP_SECONDS = int(os.getenv("RATE_LIMIT_SLEEP_SECONDS", "3600"))
```

### Funciones helper:

```python
def parse_rate_limit_header(response_headers: dict) -> tuple:
    """
    Extrae X-RateLimit-Remaining y X-RateLimit-Reset de los headers.
    Foursquare incluye estos headers en cada respuesta.
    """
    remaining = int(response_headers.get("X-RateLimit-Remaining", "-1"))
    reset = int(response_headers.get("X-RateLimit-Reset", "-1"))
    return remaining, reset

def get_seconds_until_reset(reset_timestamp: int) -> int:
    """Calcula cuántos segundos faltan para que se resetee el rate limit."""
    import time
    now = int(time.time())
    delta = reset_timestamp - now
    return max(0, delta)  # Si es negativo, retornar 0
```

**¿Por qué?** Centralizar config evita repetir valores en múltiples archivos.

---

## 🔵 db.py — Base de Datos PostgreSQL

**Función**: Interactuar con la BD. Crear tablas, insertar, guardar progreso.

### Funciones principales:

#### 1. `init_db()`
```python
def init_db():
    """Crea esquema raw.foursquare_ferreterias y tabla de progreso."""
    # CREATE SCHEMA IF NOT EXISTS raw
    # CREATE TABLE raw.foursquare_ferreterias (...)
    # CREATE TABLE raw.foursquare_progress (...)
```

**¿Qué hace?**
- Crea esquema `raw` (si no existe)
- Crea tabla `foursquare_ferreterias` con 45+ columnas
- Crea tabla `foursquare_progress` para guardar pausas
- Crea índices para búsquedas rápidas

#### 2. `cargar_fsq_ids_procesados()`
```python
def cargar_fsq_ids_procesados() -> set:
    """Devuelve set de IDs de Foursquare ya en BD."""
    # SELECT fsq_place_id FROM raw.foursquare_ferreterias
    return {row[0] for row in cur.fetchall()}
```

**¿Por qué?** Para no insertar duplicados. Si el ID ya existe, lo salta.

#### 3. `insertar_lugar(datos: dict) -> bool`
```python
def insertar_lugar(datos: dict) -> bool:
    """
    Inserta un registro en la BD.
    Si ya existe (hash_id), lo ignora (ON CONFLICT ... DO NOTHING).
    Retorna True si se insertó, False si era duplicado.
    """
    # INSERT INTO raw.foursquare_ferreterias (...) 
    # ON CONFLICT (hash_id) DO NOTHING
    return inserted == 1
```

**¿Por qué?** BD es la fuente de verdad. SIEMPRE se guarda aquí.

#### 4. `guardar_progreso(run_id: str, progreso: dict)`
```python
def guardar_progreso(run_id: str, progreso: dict):
    """
    Guarda estado actual del scraping en tabla foursquare_progress.
    Se ejecuta cuando hay rate limit (pausa).
    """
    # INSERT INTO raw.foursquare_progress (run_id, estado, ...)
    # ON CONFLICT (run_id) DO UPDATE SET ...
```

**¿Por qué?** Así si se caiga la app, podemos reanudar desde donde quedó.

---

## 🔵 scraper.py — Llamadas a Foursquare

**Función**: Hacer requests a Foursquare API y manejar errores.

### Excepciones personalizadas:

```python
class RateLimitException(Exception):
    """Lanzada cuando se detecta 403."""
    def __init__(self, message: str, reset_timestamp: int = None):
        self.reset_timestamp = reset_timestamp

class AuthException(Exception):
    """Lanzada cuando hay 401 (API key inválida)."""
    pass
```

### Función principal: `safe_request(url, params)`

```python
def safe_request(url: str, params: dict) -> dict | None:
    """
    Realiza request con reintentos y detección de errores.
    
    Flujo:
    1. Hacer request
    2. Si 200 → devolver respuesta ✓
    3. Si 403 + "no api credits" → devolver None (créditos agotados)
    4. Si 403 sin mencionar créditos → lanzar RateLimitException (rate limit)
    5. Si 401 → lanzar AuthException (API key inválida)
    6. Si 429 → esperar y reintentar
    7. Si 400 → devolver None (parámetros inválidos)
    8. Si 5xx → esperar exponencial y reintentar
    """
    wait = 1
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=FSQ_HEADERS, ...)
            
            # Analizar status code
            if response.status_code == 200:
                return response.json()  # ✓ Éxito
            elif response.status_code == 403:
                # ¿Es por créditos o por rate limit?
                if "no api credits" in response.text.lower():
                    return None  # Créditos agotados (no hay recuperación)
                else:
                    raise RateLimitException(...)  # Rate limit (esperar y reintentar)
            elif response.status_code == 401:
                raise AuthException(...)  # API key inválida
            elif response.status_code == 429:
                time.sleep(wait)  # Esperar y reintentar
                wait = min(wait * 2, 60)
            # ... más casos ...
        except RateLimitException:
            raise  # Re-lanzar para que main.py lo maneje
        except Exception as e:
            time.sleep(wait)
            wait *= 2
    
    return None  # Falló después de MAX_RETRIES intentos
```

**¿Por qué?** Manejar todos los casos de error de forma inteligente.

### Función: `buscar_lugares(keyword, near)`

```python
def buscar_lugares(keyword: str, near: str) -> list:
    """
    Busca lugares con paginación.
    
    Foursquare limita a 50 resultados por request.
    Esta función pagina hasta obtener MAX_POR_QUERY resultados.
    
    Flujo:
    1. offset = 0
    2. Hacer request con limit=50, offset=0
    3. Si obtengo <50 resultados, fin (no hay más páginas)
    4. Si obtengo 50 resultados, continuar
    5. offset += 50
    6. Repetir hasta MAX_POR_QUERY
    """
    todos = []
    offset = 0
    
    while len(todos) < max_resultados:
        params = {
            "query": keyword,
            "near": near,
            "limit": 50,      # Máximo por página
            "offset": offset,  # Página actual
            "fields": FSQ_FIELDS,
        }
        
        data = safe_request(FSQ_BASE_URL, params)  # Puede lanzar RateLimitException
        if not data:
            break
        
        resultados = data.get("results", [])
        if not resultados:
            break
        
        todos.extend(resultados)
        
        if len(resultados) < 50:
            break  # No hay más páginas
        
        offset += 50
        time.sleep(REQUEST_DELAY)  # Retraso entre requests
    
    return todos[:max_resultados]
```

**¿Por qué?** Foursquare limita a 50 resultados/request. Hay que paginar.

---

## 🔵 normalizer.py — Mapeo a Esquema Argos

**Función**: Convertir respuesta de Foursquare al schema Argos.

### Función: `calcular_score(nombre, categorias, descripcion)`

```python
def calcular_score(nombre: str, categorias: list, descripcion: str = "") -> tuple:
    """
    Calcula relevancia del lugar.
    
    Scoring:
    - Categoría FSQ exacta (ferretería): +5
    - Palabra alta relevancia (ferretería, cemento): +3
    - Palabra media relevancia (construcción): +2
    - Palabra negativa (restaurante): -5
    
    Retorna: (score, aprobado_argos)
    aprobado_argos = score >= ARGOS_SCORE_THRESHOLD (2)
    """
    score = 0
    texto = f"{nombre} {descripcion}".lower()
    
    # Bonus por categoría FSQ
    for cat in categorias:
        if cat.get("id") in CATEGORIAS_RELEVANTES:
            score += CATEGORIAS_RELEVANTES[cat.get("id")]
    
    # Bonus/penalización por palabras
    for p in PALABRAS_ALTA:
        if p in texto:
            score += 3
    for p in PALABRAS_NEGATIVAS:
        if p in texto:
            score -= 5
    
    aprobado = score >= ARGOS_SCORE_THRESHOLD
    return score, aprobado
```

**¿Por qué?** Filtrar buenos resultados de malos. No todos los "materiales" son ferreterías.

### Función: `normalizar_lugar(...)`

```python
def normalizar_lugar(place, ciudad_nombre, keyword, run_id, fecha_extraccion):
    """
    Mapea respuesta Foursquare a schema Argos.
    
    Extrae:
    - Ubicación: latitud, longitud, dirección, municipio, departamento
    - Contacto: teléfono, email, website, redes sociales
    - Metadata Foursquare: fsq_place_id, rating, hours, etc.
    - Calidad: score, aprobado_argos
    
    Retorna dict con todos los campos del schema.
    """
    fsq_id = place.get("fsq_place_id")
    nombre = place.get("name")
    
    if not fsq_id or not nombre:
        return None  # Datos insuficientes
    
    # Extraer ubicación
    location = place.get("location", {})
    municipio = location.get("locality") or ciudad_nombre
    departamento = CIUDAD_DEPARTAMENTO.get(ciudad_nombre, "")
    
    # Extraer contacto
    telefono = limpiar_telefono(place.get("tel", ""))
    email = place.get("email", "")
    
    # Calcular score
    score, aprobado = calcular_score(nombre, place.get("categories", []))
    
    # Retornar dict normalizado
    return {
        "hash_id": generar_hash(fsq_id),
        "run_id": run_id,
        "nombre": nombre,
        "municipio": municipio,
        "telefono": telefono,
        "score": score,
        "aprobado_argos": aprobado,
        # ... más campos ...
    }
```

---

## 🔵 main.py — Orquestador Principal

**Función**: Loop principal que busca, normaliza e inserta datos.

### Función: `do_scrape()`

```python
async def do_scrape():
    """
    Flujo completo de scraping.
    
    1. Inicializar BD
    2. Para cada (keyword, ciudad):
       a. Buscar en Foursquare
       b. Si 403 → pausar/reanudar automáticamente
       c. Normalizar resultados
       d. Insertar en PostgreSQL
    3. Guardar JSON (si habilitado)
    4. Enviar webhooks a n8n
    """
    
    # ① INICIALIZACIÓN
    run_id = str(uuid.uuid4())  # ID único de esta corrida
    fecha_extraccion = datetime.now(timezone.utc)
    procesados = cargar_fsq_ids_procesados()  # Caché de IDs
    
    total_combinaciones = len(KEYWORDS_BUSQUEDA) * len(CIUDADES)
    # Ej: 10 keywords × 35 ciudades = 350 combinaciones
    
    raw_responses = []  # Respuestas crudas de FSQ
    flat_results = []   # Registros normalizados
    
    total_ins = 0       # Total insertados
    total_dup = 0       # Total duplicados
    total_apr = 0       # Total aprobados
    rate_limit_count = 0
    
    # ② LOOP PRINCIPAL
    for ciudad_info in CIUDADES:
        for keyword in KEYWORDS_BUSQUEDA:
            try:
                # Buscar (puede lanzar RateLimitException)
                lugares = buscar_lugares(keyword, near)
            
            except RateLimitException as e:
                # ③ DETECCIÓN DE 403 → PAUSA AUTOMÁTICA
                if not AUTO_PAUSE_ON_RATE_LIMIT:
                    break
                
                rate_limit_count += 1
                if rate_limit_count >= MAX_CONSECUTIVE_RATE_LIMITS:
                    break
                
                # Guardar estado de pausa
                guardar_progreso(run_id, {
                    "estado": "pausado",
                    "combinacion_actual": {"keyword": keyword, "ciudad": ciudad_nombre},
                    "rate_limit_count": rate_limit_count,
                })
                
                # Enviar webhook a n8n
                enviar_webhook(WEBHOOK_ON_PAUSE, {...})
                
                # Esperar
                time.sleep(RATE_LIMIT_SLEEP_SECONDS)
                
                # Reanudar
                if AUTO_RESUME_AFTER_PAUSE:
                    lugares = buscar_lugares(keyword, near)  # Reintentar
            
            # ④ PROCESAMIENTO DE RESULTADOS
            raw_responses.append({
                "keyword": keyword,
                "ciudad": ciudad_nombre,
                "results": lugares,
            })
            
            for place in lugares:
                fsq_id = place.get("fsq_place_id")
                
                # Skip si ya está en caché
                if fsq_id in procesados:
                    total_dup += 1
                    continue
                
                # Normalizar
                registro = normalizar_lugar(place, ciudad_nombre, keyword, run_id, fecha_extraccion)
                if not registro:
                    continue
                
                # ⑤ INSERTAR EN BD (SIEMPRE)
                if insertar_lugar(registro):
                    total_ins += 1
                    procesados.add(fsq_id)
                    
                    if registro.get("aprobado_argos"):
                        total_apr += 1
                    
                    # Respaldo local
                    guardar_jsonl_local(registro)
                    flat_results.append(registro)
                else:
                    total_dup += 1
    
    # ⑥ GUARDADO FINAL
    if SAVE_JSON_BACKUP:
        save_json(JSON_RAW_FILE, raw_responses)  # Respuestas crudas
        save_json(JSON_FLAT_FILE, flat_results)   # Normalizadas
    
    # Guardar estado final
    guardar_progreso(run_id, {"estado": "completado", ...})
    
    # ⑦ NOTIFICACIÓN FINAL
    if WEBHOOK_ON_COMPLETE:
        enviar_webhook(WEBHOOK_ON_COMPLETE, {"estado": "completado", ...})
```

**Flujo de errores:**

```
buscar_lugares() 
  ↓
requests.get() 
  ↓
Status 403 + "no api credits" → devuelve None → continuar
Status 403 + rate limit → lanza RateLimitException
Status 401 → lanza AuthException → rompe loop
Status 429 → reintenta exponencial
```

---

## 🔵 api_runner.py — API HTTP

**Función**: Servidor FastAPI para controlar el scraping remotamente.

### Estado global:

```python
estado_global = {
    "scraping_en_curso": False,      # ¿Hay un scraping en curso?
    "run_id": None,                  # ID de la corrida actual
    "inicio": None,                  # Cuándo empezó
    "fin": None,                     # Cuándo terminó
    "duracion": None,                # Cuánto tardó
    "ultimo_status": "sin_correr",   # ok|error|corriendo
    "ultimo_error": None,            # Mensaje de error (si hay)
    "en_pausa": False,               # ¿Está pausado manualmente?
}
```

### Endpoints:

#### 1. `POST /scrape/foursquare`

```python
@app.post("/scrape/foursquare")
async def run_scraper():
    # Validar que no haya otro scraping
    if estado_global["scraping_en_curso"]:
        raise HTTPException(409, "Ya hay un scraping en curso")
    
    # Generar nuevo run_id
    run_id = str(uuid.uuid4())
    
    # Actualizar estado global
    estado_global.update({
        "scraping_en_curso": True,
        "run_id": run_id,
        "inicio": datetime.now().isoformat(),
        "ultimo_status": "corriendo",
    })
    
    # Ejecutar en background (no bloquea)
    asyncio.create_task(ejecutar_background(run_id))
    
    return {"status": "iniciado", "run_id": run_id}
```

**¿Por qué?** `asyncio.create_task()` ejecuta sin esperar. La API responde inmediatamente.

#### 2. `GET /status`

```python
@app.get("/status")
def get_status():
    return {
        "status": estado_global["ultimo_status"],
        "en_curso": estado_global["scraping_en_curso"],
        # ... resto de campos ...
    }
```

Simple, devuelve el estado global.

#### 3. `POST /reset`

```python
@app.post("/reset")
def reset_all():
    # Validar que no hay scraping
    if estado_global["scraping_en_curso"]:
        raise HTTPException(409, "No se puede resetear mientras hay scraping")
    
    # Borrar archivos
    for archivo in [PROGRESS_FILE, OUTPUT_FILE, JSON_RAW_FILE, ...]:
        if os.path.exists(archivo):
            os.remove(archivo)
    
    # Reset estado global
    estado_global.update({
        "scraping_en_curso": False,
        "run_id": None,
        # ... limpiar todo ...
    })
    
    return {"status": "reset", "archivos_borrados": [...]}
```

**Nota importante**: **NO borra la BD**. Solo archivos de progreso.

---

## 📊 Flujo Completo de Pausa Automática

```
1. main.py llama a buscar_lugares("ferretería", "Bogotá")
                    ↓
2. scraper.py hace safe_request() a Foursquare
                    ↓
3. Foursquare responde 403 (rate limit alcanzado)
                    ↓
4. safe_request() detecta 403 y lanza RateLimitException
                    ↓
5. main.py captura RateLimitException
                    ↓
6. main.py guarda estado en foursquare_progress.json
                    ↓
7. main.py guarda estado en PostgreSQL (tabla foursquare_progress)
                    ↓
8. main.py envía webhook a n8n
                    ↓
9. n8n recibe notificación (puede notificar a Telegram, email, etc.)
                    ↓
10. main.py espera RATE_LIMIT_SLEEP_SECONDS (3600 segundos = 1 hora)
                    ↓
11. main.py reintenta buscar_lugares("ferretería", "Bogotá")
                    ↓
12. (Repite o continúa con siguiente combinación)
```

---

## 🎯 Resumen

| Archivo | Función |
|---------|---------|
| **config.py** | Centralizar configuración desde .env |
| **db.py** | Crear BD, insertar, guardar progreso |
| **scraper.py** | Llamadas a Foursquare, detección de 403 |
| **normalizer.py** | Mapear datos a schema Argos, scoring |
| **main.py** | Loop principal, pausa automática, reanudación |
| **api_runner.py** | Servidor HTTP, endpoints de control |
| **.env** | Variables de entorno (configuración) |
| **Dockerfile** | Imagen Docker |
| **docker-compose.yml** | Orquestación de servicios |

Cada archivo tiene una responsabilidad clara. Juntos forman un sistema automático y robusto. 🚀
