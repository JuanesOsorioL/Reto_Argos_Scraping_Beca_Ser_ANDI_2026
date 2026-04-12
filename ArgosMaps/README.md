# README Maestro — Proyecto Argos Scraper Google Maps

## Índice
- [1. Resumen ejecutivo](#1-resumen-ejecutivo)
- [2. Punto de entrada y mapa del sistema](#2-punto-de-entrada-y-mapa-del-sistema)
- [3. Diagrama de arquitectura](#3-diagrama-de-arquitectura)
- [4. Dependencias entre archivos](#4-dependencias-entre-archivos)
- [5. Flujo operativo](#5-flujo-operativo)
- [6. Lógica crítica](#6-lógica-crítica)
- [7. Riesgos técnicos](#7-riesgos-técnicos)
- [8. Recomendaciones de clean code](#8-recomendaciones-de-clean-code)
- [9. Análisis por archivo](#9-análisis-por-archivo)
- [10. Código completo documentado](#10-código-completo-documentado)
- [11. Dockerfile](#11-dockerfile)

---

## 1. Resumen ejecutivo
Este proyecto implementa un **scraper de Google Maps** enfocado en negocios ferreteros o relacionados con construcción para Argos. El sistema:

- busca combinaciones `keyword + ciudad`;
- extrae URLs de resultados desde Google Maps;
- abre cada ficha individual;
- obtiene nombre, categorías, dirección, teléfono y coordenadas;
- calcula un score de afinidad con reglas de negocio;
- persiste el resultado en PostgreSQL;
- opcionalmente deja respaldo local en `.jsonl`;
- exporta a Excel desde base de datos;
- expone una API FastAPI para lanzar el scraping en modo “dispara y olvida”.

En términos arquitectónicos, el sistema está dividido en **configuración**, **extracción**, **scoring**, **persistencia**, **exportación** y **orquestación HTTP**.

---

## 2. Punto de entrada y mapa del sistema
### Punto de entrada técnico
El sistema tiene **dos puntos de entrada operativos**:

| Entrada | Archivo | Propósito |
|---|---|---|
| CLI scraper | `main.py` | Ejecuta el scraping directamente desde consola. |
| API HTTP | `api_runner.py` | Expone endpoints para ejecutar el scraping en background y consultar estado. |

### Clasificación funcional
| Tipo | Archivo | Rol |
|---|---|---|
| Configuración | `config.py` | Variables estáticas, listas de ciudades/keywords, flags y conexión DB. |
| Lógica de negocio | `main.py` | Orquestación del scraping, parsing, deduplicación, persistencia. |
| Lógica de negocio | `filter_engine.py` | Reglas de scoring y aprobación Argos. |
| Persistencia | `db.py` | Inicialización, conexión, inserción y caché desde PostgreSQL. |
| Exposición HTTP | `api_runner.py` | API para disparar el proceso y reportar estado/callback. |
| Exportación | `data_exporter.py` | Exporta resultados desde PostgreSQL a Excel. |
| Dependencias | `requirements.txt` | Librerías Python requeridas. |
| Infraestructura | `dockerfile` | Contenerización del servicio. |

---

## 3. Diagrama de arquitectura
```text
                ┌──────────────────────────────┐
                │           n8n / cliente      │
                └──────────────┬───────────────┘
                               │ POST /scrape/google-maps
                               ▼
                    ┌──────────────────────┐
                    │     api_runner.py    │
                    │ FastAPI + estado run │
                    └──────────┬───────────┘
                               │ asyncio.create_task()
                               ▼
                    ┌──────────────────────┐
                    │       main.py        │
                    │  orquestador scrape  │
                    └──────────┬───────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
 ┌─────────────────┐  ┌──────────────────┐  ┌───────────────────┐
 │   config.py     │  │ filter_engine.py │  │       db.py       │
 │ ciudades/flags  │  │ scoring Argos    │  │ PG init/insert    │
 └─────────────────┘  └──────────────────┘  └───────────────────┘
                               │                    │
                               │                    ▼
                               │          ┌──────────────────────┐
                               │          │ PostgreSQL raw schema│
                               │          │ google_maps_...      │
                               │          └──────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ respaldo JSONL local │
                    └──────────────────────┘

Posteriormente:

┌──────────────────────┐      lee desde DB      ┌──────────────────────┐
│  data_exporter.py    │ ─────────────────────▶ │ Excel .xlsx          │
└──────────────────────┘                         └──────────────────────┘
```

---

## 4. Dependencias entre archivos
```text
api_runner.py
 └── importa main.do_scrape()

main.py
 ├── importa config.py
 ├── importa filter_engine.py
 └── importa db.py

data_exporter.py
 ├── importa config.py
 └── importa db.py

db.py
 └── importa config.py
```

### Relación clave de trazabilidad
- `main.py` genera `run_id` y `fecha_extraccion` para toda la corrida.
- `db.py` persiste ese `run_id` por registro.
- `api_runner.py` también crea un `run_id` externo para seguimiento del job HTTP.
- Aquí existe una **dualidad de run_id**: uno en API y otro en scraper. Eso puede generar trazabilidad ambigua entre ejecución HTTP y ejecución de scraping real.

---

## 5. Flujo operativo
### Flujo completo
1. `api_runner.py` recibe `POST /scrape/google-maps`.
2. Marca el estado global como `corriendo`.
3. Lanza `ejecutar_scraper_background()`.
4. Esa función importa y ejecuta `main.do_scrape()`.
5. `main.py` inicializa la DB con `init_db()`.
6. Carga URLs ya procesadas con `cargar_urls_procesadas()`.
7. Recorre `KEYWORDS_BUSQUEDA × CIUDADES`.
8. Para cada combinación, `extraer_urls_busqueda()` obtiene URLs de fichas de Google Maps.
9. Cada URL nueva pasa por `procesar_lugar()`.
10. `procesar_lugar()` obtiene datos del negocio, calcula score y persiste con `insertar_negocio()`.
11. Cuando termina, `api_runner.py` actualiza el estado final y opcionalmente llama webhook de n8n.
12. `data_exporter.py` permite luego exportar los datos guardados a Excel.

---

## 6. Lógica crítica
### 6.1 Deduplicación
- Se normaliza la URL eliminando query params.
- Se calcula `hash_id` con MD5.
- PostgreSQL impone `UNIQUE` sobre `hash_id`.
- Inserciones duplicadas se ignoran con `ON CONFLICT DO NOTHING`.

### 6.2 Caché operativa
- Antes de scrapear, el sistema carga todas las URLs existentes desde DB.
- Eso evita reprocesar lugares ya guardados, incluso entre corridas distintas.

### 6.3 Scoring Argos
- `filter_engine.py` concatena `nombre + categorias + keyword_busqueda`.
- Suma puntos positivos altos y medios.
- Resta puntos por términos descalificadores.
- Aprueba cuando `score >= 2`.

### 6.4 Persistencia
- La **fuente de verdad** es PostgreSQL.
- El `.jsonl` es solo respaldo opcional.
- `data_exporter.py` exporta exclusivamente desde DB, no desde el JSONL.

### 6.5 Concurrencia
- `main.py` procesa lugares por lotes de `MAX_CONCURRENT_TABS`.
- `api_runner.py` evita corridas simultáneas usando un estado global `scraping_en_curso`.

---

## 7. Riesgos técnicos
| Riesgo | Impacto | Detalle |
|---|---|---|
| Estado global en memoria | Alto | Si reinicia el contenedor, se pierde el estado de corrida de la API. |
| Dos `run_id` distintos | Alto | El `run_id` del job HTTP no coincide con el `run_id` persistido por `main.py`. |
| Selectores de Google Maps frágiles | Alto | Cambios en DOM/atributos pueden romper extracción. |
| Caché basada solo en URL | Medio | Si un negocio cambia datos pero conserva URL, no se refresca automáticamente. |
| Falta de retry estructurado | Medio | Fallos temporales de red o render no tienen política de reintento formal. |
| Credenciales por defecto | Alto | `config.py` usa defaults inseguros para DB. |
| `dockerfile` no inspeccionado | Medio | No se puede verificar build, puertos ni entrypoint en esta documentación. |

---

## 8. Recomendaciones de clean code
1. Unificar el `run_id` de `api_runner.py` con el `run_id` generado en `main.py`.
2. Extraer selectores de Google Maps a constantes versionadas.
3. Separar parsing, navegación y persistencia en módulos independientes.
4. Reemplazar `print()` por logging estructurado.
5. Mover reglas del scoring a configuración externa o tabla parametrizable.
6. Agregar pruebas unitarias para `filter_engine.py`, `deducir_whatsapp()`, `normalizar_url()` y `generar_hash()`.
7. Convertir el estado global de API a Redis o DB si habrá múltiples workers.
8. Añadir validación de variables de entorno obligatorias al arranque.

---

## 9. Análisis por archivo
| Archivo | Propósito | Entradas | Salidas | Dependencias |
|---|---|---|---|---|
| `api_runner.py` | Exponer scraper como API HTTP asíncrona | Requests HTTP, webhook URL | JSON de estado, callback n8n | `main.py`, `httpx`, `fastapi` |
| `config.py` | Centralizar parámetros del sistema | Variables de entorno | Constantes de runtime | `dotenv`, `os` |
| `data_exporter.py` | Exportar datos a Excel | Flags CLI, datos PostgreSQL | Archivo `.xlsx` | `db.py`, `config.py`, `pandas` |
| `db.py` | Acceso a PostgreSQL | Credenciales DB, diccionarios de negocio | Tabla, inserts, caché URLs | `psycopg2`, `config.py` |
| `filter_engine.py` | Calcular score y aprobación | nombre, categorías, keyword | `(score, aprobado)` | Ninguna interna |
| `main.py` | Scraping completo Google Maps | Config, keywords, ciudades | Inserciones DB, JSONL opcional | `config.py`, `db.py`, `filter_engine.py`, `playwright` |
| `requirements.txt` | Dependencias | Ninguna | Entorno instalable | pip |
| `dockerfile` | Contenerización | Base image, copy, run | Imagen Docker | no inspeccionado |

---

## 10. Código completo documentado

### 10.1 `api_runner.py`
```python
"""  # Docstring de módulo: describe el propósito general del archivo.
api_runner.py — Expone el scraper como endpoint HTTP  # Explica la responsabilidad principal del módulo.
Arquitectura "dispara y olvida":  # Describe el patrón de ejecución asíncrona del servicio.
  - n8n llama a /scrape/google-maps  # Paso 1 del flujo de integración.
  - El servidor responde INMEDIATAMENTE con run_id  # Paso 2: respuesta no bloqueante.
  - El scraper corre en segundo plano  # Paso 3: la tarea larga sale del request principal.
  - n8n consulta /status para saber si terminó  # Paso 4: polling de estado.
  - opcionalmente se notifica a n8n vía webhook al finalizar  # Paso 5: callback saliente opcional.

Endpoints:  # Enumera la API pública.
    GET  /health               → healthcheck simple  # Endpoint de salud.
    POST /scrape/google-maps   → dispara el scraper (responde al instante)  # Endpoint principal.
    GET  /status               → estado actual del scraper  # Endpoint de monitoreo.
    GET  /resultado            → resultado de la última corrida  # Endpoint de resumen final.
    POST /test/callback        → prueba manual del callback a n8n  # Endpoint de testing.
    GET  /endpoints            → lista endpoints expuestos  # Endpoint de introspección.
"""  # Cierre del docstring.

from fastapi import FastAPI, Request  # Importa la app FastAPI y el tipo Request.
from fastapi.responses import JSONResponse  # Permite devolver respuestas JSON con status code personalizado.
import asyncio  # Se usa para lanzar la tarea en background.
import uvicorn  # Servidor ASGI para ejecución local.
import uuid  # Genera run_id únicos.
import os  # Acceso a variables de entorno.
from datetime import datetime, timedelta  # Manejo de timestamps y ventanas de tiempo.
import httpx  # Cliente HTTP asíncrono para callback a n8n.
from dotenv import load_dotenv  # Carga variables desde archivo .env.
load_dotenv()  # Inicializa variables de entorno al arrancar el módulo.

app = FastAPI(title="Argos Scraper API")  # Instancia principal de la API.

# URL fija del webhook de n8n.  # Comentario de configuración externa.
# todo en docker  # Nota de implementación pendiente o contexto de despliegue.
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")  # Lee la URL del webhook desde entorno.

# Estado global del scraper  # Estructura en memoria para exponer progreso actual.
estado = {  # Diccionario compartido por todos los endpoints del proceso.
    "scraping_en_curso": False,  # Indica si ya existe una corrida activa.
    "run_id": None,  # Identificador de la corrida expuesta por la API.
    "inicio": None,  # Timestamp de inicio de la última ejecución.
    "fin": None,  # Timestamp de fin de la última ejecución.
    "duracion": None,  # Duración legible de la corrida.
    "ultimo_status": "sin_correr",  # Estado lógico: sin_correr | corriendo | ok | error.
    "ultimo_error": None,  # Último error registrado, si existe.
    "metricas": None,  # Métricas retornadas por el scraper, si las hay.
}  # Fin de la estructura global de estado.


def calcular_duracion(inicio_iso: str | None, fin_iso: str | None):  # Convierte dos ISO timestamps en una duración legible.
    if not inicio_iso or not fin_iso:  # Si falta uno de los extremos, no se puede calcular.
        return None  # Devuelve ausencia de duración.
    try:  # Intenta convertir y restar timestamps.
        inicio = datetime.fromisoformat(inicio_iso)  # Parsea la fecha de inicio.
        fin = datetime.fromisoformat(fin_iso)  # Parsea la fecha de fin.
        duracion_s = max(0, round((fin - inicio).total_seconds()))  # Obtiene segundos y evita negativos.
        return f"{duracion_s // 60}m {duracion_s % 60}s"  # Retorna formato minutos/segundos.
    except Exception:  # Captura cualquier fecha mal formada.
        return None  # Falla silenciosamente devolviendo vacío.


async def enviar_callback(payload: dict, headers: dict | None = None):  # Envía notificación HTTP a n8n.
    """  # Docstring de la función.
    Envía el callback al webhook de n8n si está configurado.  # Describe la responsabilidad directa.
    """  # Cierre del docstring.
    if not N8N_WEBHOOK_URL:  # Valida que exista configuración del webhook.
        raise ValueError("N8N_WEBHOOK_URL no está configurado")  # Corta el flujo si no hay destino.

    async with httpx.AsyncClient(timeout=15.0) as client:  # Crea cliente HTTP asíncrono con timeout.
        response = await client.post(  # Ejecuta POST al webhook.
            N8N_WEBHOOK_URL,  # URL de destino configurada.
            json=payload,  # Cuerpo JSON del callback.
            headers={  # Construye cabeceras salientes.
                "Content-Type": "application/json",  # Declara contenido JSON.
                **(headers or {})  # Mezcla headers opcionales adicionales.
            }  # Fin de headers.
        )  # Fin del POST.
        response.raise_for_status()  # Lanza excepción si la respuesta no fue 2xx.


async def notificar_fin_run(payload: dict, headers: dict | None = None):  # Wrapper tolerante a fallos para callback.
    """  # Docstring de la función.
    Intenta notificar a n8n, pero no rompe el flujo principal si falla.  # Define que el callback no debe abortar la corrida.
    """  # Cierre del docstring.
    try:  # Ejecuta el envío sin impactar el flujo principal.
        await enviar_callback(payload, headers)  # Reutiliza la función de envío real.
        print(f"[CALLBACK] Notificación enviada a n8n. evento={payload.get('evento')} run_id={payload.get('run_id')}")  # Log de éxito.
    except Exception as e:  # Captura cualquier error de red o configuración.
        print(f"[CALLBACK] Falló envío a n8n: {e}")  # Loguea el fallo sin re-lanzarlo.


async def ejecutar_scraper_background(run_id: str):  # Ejecuta el scraper fuera del request HTTP.
    """  # Docstring de la función.
    Corre el scraper en segundo plano sin bloquear la respuesta HTTP.  # Explica la razón de ser del background task.
    Al finalizar, actualiza estado y notifica a n8n.  # Explica sus efectos laterales.
    """  # Cierre del docstring.
    global estado  # Declara que se modificará el estado compartido del módulo.
    try:  # Inicia flujo exitoso.
        from main import do_scrape  # Importación diferida para evitar costo o ciclos al cargar el módulo.

        # Si do_scrape retorna métricas, las guardamos  # Aclara el contrato esperado del scraper.
        metricas = await do_scrape()  # Ejecuta el scraping completo.

        fin = datetime.now().isoformat()  # Marca el fin de la ejecución.
        duracion = None  # Inicializa duración antes de calcularla.

        # Si do_scrape ya trae duracion, la usamos  # Prioriza una duración generada por la capa inferior.
        if isinstance(metricas, dict):  # Verifica si el scraper devolvió un objeto estructurado.
            duracion = metricas.get("duracion")  # Intenta extraer duración reportada por el scraper.

        if not duracion:  # Si no vino duración explícita.
            duracion = calcular_duracion(estado["inicio"], fin)  # La calcula usando timestamps API.

        estado.update({  # Actualiza el estado global con el resultado exitoso.
            "scraping_en_curso": False,  # Marca que ya no hay proceso activo.
            "fin": fin,  # Guarda timestamp de cierre.
            "duracion": duracion,  # Guarda duración final.
            "ultimo_status": "ok",  # Marca finalización exitosa.
            "ultimo_error": None,  # Limpia error previo.
            "metricas": metricas if isinstance(metricas, dict) else None,  # Guarda métricas si son válidas.
        })  # Fin de update.

        print(f"\n[✓] Scraping completado. run_id: {run_id}")  # Log de finalización exitosa.

        await notificar_fin_run({  # Envía callback de cierre exitoso.
            "evento": "google_maps.finalizado",  # Tipo de evento emitido.
            "status": "ok",  # Estado final para el consumidor externo.
            "run_id": run_id,  # run_id visible por la API.
            "inicio": estado["inicio"],  # Timestamp inicial registrado por la API.
            "fin": estado["fin"],  # Timestamp final registrado por la API.
            "duracion": estado["duracion"],  # Duración calculada.
            "metricas": estado["metricas"],  # Métricas, si existen.
            "origen": "api_runner",  # Traza el emisor del evento.
            "tipo_ejecucion": "produccion"  # Etiqueta de contexto operativo.
        })  # Fin del payload exitoso.

    except Exception as e:  # Inicia flujo de error.
        fin = datetime.now().isoformat()  # Registra fin incluso en error.
        duracion = calcular_duracion(estado["inicio"], fin)  # Calcula duración transcurrida hasta fallar.

        estado.update({  # Actualiza el estado global con resultado fallido.
            "scraping_en_curso": False,  # Libera bloqueo de corrida.
            "fin": fin,  # Guarda momento del error/finalización.
            "duracion": duracion,  # Guarda duración parcial.
            "ultimo_status": "error",  # Marca estado fallido.
            "ultimo_error": str(e),  # Persiste el mensaje de error.
            "metricas": None,  # En error, se limpian métricas.
        })  # Fin de update.

        print(f"\n[✗] Error en scraping: {e}")  # Log de error.

        await notificar_fin_run({  # Envía callback de cierre con error.
            "evento": "google_maps.finalizado",  # Tipo de evento emitido.
            "status": "error",  # Estado final con fallo.
            "run_id": run_id,  # run_id visible por la API.
            "inicio": estado["inicio"],  # Momento en que inició la corrida.
            "fin": estado["fin"],  # Momento en que terminó con error.
            "duracion": estado["duracion"],  # Tiempo consumido antes de fallar.
            "error": str(e),  # Texto del error.
            "origen": "api_runner",  # Fuente del evento.
            "tipo_ejecucion": "produccion"  # Etiqueta del tipo de ejecución.
        })  # Fin del payload de error.


@app.get("/health")  # Registra endpoint GET /health.
def health():  # Endpoint mínimo de healthcheck.
    return {"status": "ok", "code": "200"}  # Respuesta simple para monitoreo.


@app.get("/status")  # Registra endpoint GET /status.
def status():  # Devuelve el estado actual del proceso.
    """  # Docstring del endpoint.
    Retorna estado actual.  # Describe la finalidad del endpoint.
    """  # Cierre del docstring.
    return {  # Arma payload de estado consumible externamente.
        "statusGeneral": estado["ultimo_status"],  # Alias de estado general.
        "status": estado["ultimo_status"],  # Estado principal actual.
        "en_curso": estado["scraping_en_curso"],  # Bandera booleana de ejecución.
        "run_id": estado["run_id"],  # Identificador de la corrida API.
        "inicio": estado["inicio"],  # Fecha/hora de inicio.
        "fin": estado["fin"],  # Fecha/hora de fin.
        "duracion": estado["duracion"],  # Duración legible.
        "error": estado["ultimo_error"],  # Mensaje de error, si hubo.
        "metricas": estado["metricas"],  # Métricas del scraper.
    }  # Fin de respuesta.


@app.post("/scrape/google-maps")  # Registra endpoint POST principal.
async def run_scraper():  # Dispara scraping asíncrono.
    """  # Docstring del endpoint.
    Dispara el scraper y responde inmediatamente.  # Explica el comportamiento no bloqueante.
    """  # Cierre del docstring.
    global estado  # Se modificará el estado global.

    if estado["scraping_en_curso"]:  # Evita corridas paralelas.
        return JSONResponse(  # Devuelve conflicto HTTP si ya hay proceso activo.
            status_code=409,  # Código HTTP Conflict.
            content={  # Cuerpo explicativo del conflicto.
                "status": "ocupado",  # Estado semántico.
                "mensaje": "Ya hay un scraping en curso.",  # Mensaje humano.
                "run_id": estado["run_id"],  # Informa la corrida activa.
                "inicio": estado["inicio"],  # Informa desde cuándo corre.
            }  # Fin del contenido.
        )  # Fin de la respuesta 409.

    run_id = str(uuid.uuid4())  # Genera un identificador único para esta corrida API.
    inicio = datetime.now().isoformat()  # Registra timestamp de inicio.

    estado.update({  # Inicializa el estado global para nueva corrida.
        "scraping_en_curso": True,  # Marca ejecución activa.
        "run_id": run_id,  # Guarda identificador actual.
        "inicio": inicio,  # Guarda hora de inicio.
        "fin": None,  # Limpia hora de fin previa.
        "duracion": None,  # Limpia duración previa.
        "ultimo_status": "corriendo",  # Marca estado intermedio.
        "ultimo_error": None,  # Limpia error previo.
        "metricas": None,  # Limpia métricas previas.
    })  # Fin de update.

    asyncio.create_task(ejecutar_scraper_background(run_id))  # Lanza la corrida sin bloquear la respuesta.

    return {  # Devuelve acuse inmediato al cliente.
        "status": "iniciado",  # Estado de aceptación.
        "mensaje": "Scraper disparado. Consulta /status para ver el progreso.",  # Instrucción de uso.
        "run_id": run_id,  # Id para correlación externa.
        "inicio": inicio,  # Momento de inicio.
        "webhook_n8n": N8N_WEBHOOK_URL,  # Echo de configuración para debugging.
    }  # Fin de respuesta inmediata.


@app.get("/resultado")  # Registra endpoint GET /resultado.
def resultado():  # Devuelve último resultado consolidado.
    return {  # Respuesta resumen de la última corrida conocida.
        "status": estado["ultimo_status"],  # Estado final o actual.
        "run_id": estado["run_id"],  # Id de corrida API.
        "inicio": estado["inicio"],  # Fecha de inicio.
        "fin": estado["fin"],  # Fecha de fin.
        "duracion": estado["duracion"],  # Duración.
        "error": estado["ultimo_error"],  # Error si existe.
        "en_curso": estado["scraping_en_curso"],  # Bandera de actividad.
        "metricas": estado["metricas"],  # Métricas si existen.
    }  # Fin de respuesta.


@app.post("/test/callback")  # Registra endpoint POST de prueba de callback.
async def test_callback(request: Request):  # Permite probar el webhook sin scrapear.
    """  # Docstring del endpoint.
    Prueba manual del callback hacia n8n sin ejecutar el scraper.  # Define el caso de uso de testing.
    """  # Cierre del docstring.
    try:  # Intenta leer JSON del body.
        body = await request.json()  # Parsea el cuerpo de la petición.
    except Exception:  # Si el body no es JSON válido.
        body = {}  # Usa un diccionario vacío por defecto.

    try:  # Inicia construcción del payload de prueba.
        now = datetime.now()  # Toma la hora actual.
        inicio_default = (now - timedelta(seconds=65)).isoformat()  # Fabrica un inicio de ejemplo 65 s antes.
        fin_default = now.isoformat()  # Usa ahora como fin de ejemplo.

        payload = {  # Arma payload similar al callback real.
            "evento": "google_maps.finalizado",  # Tipo de evento.
            "status": body.get("status", "ok"),  # Permite forzar status desde body.
            "run_id": body.get("run_id", "test-run-001"),  # Permite inyectar run_id de prueba.
            "inicio": body.get("inicio", inicio_default),  # Permite inyectar inicio o usa default.
            "fin": body.get("fin", fin_default),  # Permite inyectar fin o usa default.
            "duracion": body.get("duracion", "1m 5s"),  # Permite inyectar duración o usa default.
            "metricas": body.get("metricas", {  # Permite enviar métricas custom o usa demo.
                "run_id": body.get("run_id", "test-run-001"),  # run_id demo.
                "inicio": body.get("inicio", inicio_default),  # inicio demo.
                "fin": body.get("fin", fin_default),  # fin demo.
                "duracion": body.get("duracion", "1m 5s"),  # duración demo.
                "keywords_total": 1,  # métrica demo.
                "keywords_procesadas": 1,  # métrica demo.
                "busqueda_total": 5,  # métrica demo.
                "detalle_ok": 4,  # métrica demo.
                "detalle_error": 1,  # métrica demo.
                "detalle_saltado": 0,  # métrica demo.
                "aprobados_argos": 2,  # métrica demo.
                "errores_totales": 1  # métrica demo.
            }),  # Fin de métricas demo.
            "origen": "api_runner",  # Origen del evento.
            "tipo_ejecucion": body.get("tipo_ejecucion", "prueba_callback")  # Tipo de ejecución configurable.
        }  # Fin del payload base.

        if payload["status"] == "error":  # Ajusta payload si se quiere simular error.
            payload.pop("metricas", None)  # Quita métricas en caso de error.
            payload["error"] = body.get("error", "Error de prueba enviado manualmente")  # Inserta mensaje de error.

        await enviar_callback(payload)  # Envía el payload al webhook configurado.

        return {  # Devuelve confirmación de envío exitoso.
            "status": "ok",  # Estado de respuesta local.
            "mensaje": "Callback de prueba enviado a n8n correctamente",  # Mensaje humano.
            "webhook_n8n": N8N_WEBHOOK_URL,  # Echo del destino usado.
            "payload_enviado": payload  # Retorna el payload transmitido.
        }  # Fin de respuesta exitosa.

    except Exception as e:  # Captura cualquier fallo durante la prueba.
        print(f"[TEST_CALLBACK] Falló envío de prueba a n8n: {e}")  # Log del error.
        return JSONResponse(  # Devuelve error HTTP.
            status_code=500,  # Código Internal Server Error.
            content={  # Cuerpo del error.
                "status": "error",  # Estado semántico.
                "mensaje": "No se pudo enviar el callback de prueba a n8n",  # Mensaje explicativo.
                "error": str(e)  # Detalle del error capturado.
            }  # Fin del contenido.
        )  # Fin de respuesta 500.


@app.get("/endpoints")  # Registra endpoint GET /endpoints.
def endpoints():  # Lista las rutas expuestas por la app.
    rutas = []  # Acumulador de rutas encontradas.
    for route in app.routes:  # Recorre el registro interno de rutas FastAPI.
        methods = getattr(route, "methods", None)  # Extrae métodos HTTP si existen.
        path = getattr(route, "path", None)  # Extrae path si existe.

        if path and methods:  # Solo procesa rutas bien formadas.
            rutas.append({  # Agrega una representación simplificada de la ruta.
                "path": path,  # Path público de la ruta.
                "methods": sorted([m for m in methods if m not in {"HEAD", "OPTIONS"}])  # Filtra métodos implícitos.
            })  # Fin del registro de ruta.

    return rutas  # Devuelve la lista de endpoints detectados.


if __name__ == "__main__":  # Bloque de ejecución directa del módulo.
    port = int(os.getenv("PORT", "8001"))  # Lee el puerto desde entorno o usa 8001.

    print(f"🚀 Argos Scraper API corriendo en http://localhost:{port}")  # Informa URL local.
    print(f"   n8n debe usar: http://host.docker.internal:{port}")  # Sugiere URL de acceso desde Docker.
    print(f"   Prueba local:  http://localhost:{port}/status")  # Sugiere endpoint de prueba.
    print(f"   Webhook n8n:   {N8N_WEBHOOK_URL}")  # Muestra webhook configurado.
    print(f"   GET  /health")  # Lista endpoint health.
    print(f"   POST /scrape/google-maps")  # Lista endpoint principal.
    print(f"   GET  /status")  # Lista endpoint de estado.
    print(f"   GET  /resultado")  # Lista endpoint de resultado.
    print(f"   POST /test/callback")  # Lista endpoint de prueba callback.
    print(f"   GET  /endpoints\n")  # Lista endpoint de introspección.

    uvicorn.run(app, host="0.0.0.0", port=port)  # Levanta servidor ASGI escuchando en todas las interfaces.
```

### 10.2 `config.py`
```python

# Bloque de comentario deshabilitado que conserva configuración extensa original.
CIUDADES = [  # Lista activa de ciudades a procesar.
    # Capitales Principales  # Subgrupo de capitales.
    "bogota", "medellin", "cali", "barranquilla", "cartagena", "bucaramanga",   # Ejemplos de ciudades principales.
    "cucuta", "pereira", "santa-marta", "ibague", "pasto", "manizales",   # Más capitales.
    "neiva", "villavicencio", "armenia", "valledupar", "monteria", "sincelejo",   # Más ciudades.
    "popayan", "tunja", "riohacha", "florencia", "quibdo", "yopal", "arauca",  # Cierre del bloque de capitales.
    # Periferias de Construcción Pesada  # Subgrupo de periferias.
    "bello", "itagui", "envigado", "sabaneta", "rionegro", "apartado",   # Ciudades periféricas.
    "caucasia", "turbo", "dosquebradas", "santa-rosa-de-cabal", "calarca",  # Más periferias.
    "soacha", "chia", "zipaquira", "facatativa", "fusagasuga", "girardot",   # Más periferias.
    "mosquera", "madrid", "funza", "duitama", "sogamoso", "chiquinquira",  # Más periferias.
    "palmira", "buenaventura", "tulua", "cartago", "buga", "jamundi", "yumbo", "tumaco",  # Más periferias.
    "soledad", "malambo", "cienaga", "magangue", "maicao", "aguachica",   # Más periferias.
    "floridablanca", "giron", "piedecuesta", "barrancabermeja", "pamplona", "ocana",   # Más periferias.
    "pitalito", "garzon", "espinal", "ipiales"  # Cierre de la lista ampliada.
]  # Fin de la lista histórica.


# Inicio de bloque histórico deshabilitado para mapa ciudad→departamento.
# Mapa ciudad → departamento para enriquecer los registros  # Explica el propósito del diccionario.
CIUDAD_DEPARTAMENTO = {  # Diccionario histórico amplio.
    "bogota": "Cundinamarca", "medellin": "Antioquia", "cali": "Valle del Cauca",  # Entradas de ejemplo.
    "barranquilla": "Atlántico", "cartagena": "Bolívar", "bucaramanga": "Santander",  # Más entradas.
    "cucuta": "Norte de Santander", "pereira": "Risaralda", "santa-marta": "Magdalena",  # Más entradas.
    "ibague": "Tolima", "pasto": "Nariño", "manizales": "Caldas",  # Más entradas.
    "neiva": "Huila", "villavicencio": "Meta", "armenia": "Quindío",  # Más entradas.
    "valledupar": "Cesar", "monteria": "Córdoba", "sincelejo": "Sucre",  # Más entradas.
    "popayan": "Cauca", "tunja": "Boyacá", "riohacha": "La Guajira",  # Más entradas.
    "florencia": "Caquetá", "quibdo": "Chocó", "yopal": "Casanare",  # Más entradas.
    "arauca": "Arauca", "bello": "Antioquia", "itagui": "Antioquia",  # Más entradas.
    "envigado": "Antioquia", "sabaneta": "Antioquia", "rionegro": "Antioquia",  # Más entradas.
    "apartado": "Antioquia", "caucasia": "Antioquia", "turbo": "Antioquia",  # Más entradas.
    "dosquebradas": "Risaralda", "santa-rosa-de-cabal": "Risaralda",  # Más entradas.
    "calarca": "Quindío", "soacha": "Cundinamarca", "chia": "Cundinamarca",  # Más entradas.
    "zipaquira": "Cundinamarca", "facatativa": "Cundinamarca",  # Más entradas.
    "fusagasuga": "Cundinamarca", "girardot": "Cundinamarca",  # Más entradas.
    "mosquera": "Cundinamarca", "madrid": "Cundinamarca", "funza": "Cundinamarca",  # Más entradas.
    "duitama": "Boyacá", "sogamoso": "Boyacá", "chiquinquira": "Boyacá",  # Más entradas.
    "palmira": "Valle del Cauca", "buenaventura": "Valle del Cauca",  # Más entradas.
    "tulua": "Valle del Cauca", "cartago": "Valle del Cauca",  # Más entradas.
    "buga": "Valle del Cauca", "jamundi": "Valle del Cauca",  # Más entradas.
    "yumbo": "Valle del Cauca", "tumaco": "Nariño",  # Más entradas.
    "soledad": "Atlántico", "malambo": "Atlántico", "cienaga": "Magdalena",  # Más entradas.
    "magangue": "Bolívar", "maicao": "La Guajira", "aguachica": "Cesar",  # Más entradas.
    "floridablanca": "Santander", "giron": "Santander", "piedecuesta": "Santander",  # Más entradas.
    "barrancabermeja": "Santander", "pamplona": "Norte de Santander",  # Más entradas.
    "ocana": "Norte de Santander", "pitalito": "Huila", "garzon": "Huila",  # Más entradas.
    "espinal": "Tolima", "ipiales": "Nariño",  # Cierre del diccionario histórico.
}  # Fin del diccionario histórico.

 # Inicio de bloque histórico deshabilitado para keywords.
KEYWORDS_BUSQUEDA = [  # Lista histórica amplia de términos de búsqueda.
    "ferreterias", "depositos de materiales", "depositos y ferreteria",   # Keywords del dominio construcción.
    "bodegas de construccion", "centro ferretero", "materiales para construccion",  # Más keywords.
    "cemento", "concreto", "concreto premezclado", "morteros", "mortero seco",   # Más keywords.
    "agregados para construccion", "arena y balasto", "obra gris",   # Más keywords.
    "hierro y cemento", "bloqueras", "ladrilleras", "prefabricados de concreto",   # Más keywords.
    "distribuidoras de cemento"  # Cierre de lista histórica.
]  # Fin de la lista histórica.


# ─── PostgreSQL ───────────────────────────────────────────────────────────────  # Separador visual de configuración DB.
# Carga desde variables de entorno. Crea un archivo .env con estos valores  # Instrucción operativa para configuración externa.
# y nunca lo subas a Git.  # Advertencia de seguridad.
import os  # Módulo estándar para leer entorno.
from dotenv import load_dotenv  # Permite cargar variables desde .env.
load_dotenv()  # Inicializa variables de entorno.

DB_CONFIG = {  # Diccionario consolidado para conexión PostgreSQL.
    "host":     os.getenv("DB_HOST",     "localhost"),  # Host de la DB con default local.
    "port":     int(os.getenv("DB_PORT", "5432")),  # Puerto convertido a entero.
    "dbname":   os.getenv("DB_NAME",     "postgres"),  # Nombre de base de datos.
    "user":     os.getenv("DB_USER",     "postgres"),  # Usuario de conexión.
    "password": os.getenv("DB_PASSWORD", "1234"),  # Contraseña de conexión con default inseguro.
}  # Fin de configuración DB.

# ─── Configuración del Scraping ───────────────────────────────────────────────  # Separador visual de scraping.
MAX_CONCURRENT_TABS = 3 #2  # Máximo de pestañas concurrentes; quedó valor anterior como referencia.
MIN_DELAY_SECONDS   = 1.5 #2.0  # Mínimo delay aleatorio entre lotes; incluye valor histórico comentado.
MAX_DELAY_SECONDS   = 3.0 #5.0  # Máximo delay aleatorio entre lotes; incluye valor histórico comentado.
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() == "true"  # Convierte flag HEADLESS a booleano.

# ─── Rutas de Salida (respaldo local) ────────────────────────────────────────  # Separador visual de archivos de salida.
OUTPUT_FILE      = "base_de_datos_argos_maps.jsonl"  # Ruta del respaldo local en JSON Lines.
EXCEL_OUTPUT_FILE = "base_de_datos_argos_maps.xlsx"  # Ruta del archivo Excel exportado.
GUARDAR_JSONL_LOCAL = os.getenv("GUARDAR_JSONL_LOCAL", "false").strip().lower() == "true"  # Habilita o deshabilita respaldo local.

# ─── Sesión de Chrome (Playwright) ───────────────────────────────────────────  # Separador visual de sesión Playwright.
USER_DATA_DIR = "chrome_session_argos"  # Directorio planeado para perfil persistente de Chrome.
```

### 10.3 `data_exporter.py`
```python
"""  # Docstring de módulo.
data_exporter.py — Exporta desde PostgreSQL a Excel  # Explica la función principal del archivo.
Uso:  # Documenta uso CLI.
    python data_exporter.py              → todos los registros  # Exportación completa.
    python data_exporter.py --aprobados  → solo aprobados por Argos  # Exportación filtrada.
"""  # Cierre del docstring.
import sys  # Permite leer flags de línea de comandos.
import pandas as pd  # Librería para manejo tabular y exportación a Excel.
from config import EXCEL_OUTPUT_FILE  # Importa la ruta destino del Excel.
from db import get_connection  # Importa la función de conexión a PostgreSQL.


def export_to_excel(solo_aprobados: bool = False):  # Exporta datos de DB a archivo Excel.
    filtro = "WHERE aprobado_argos = TRUE" if solo_aprobados else ""  # Construye filtro opcional según el flag.
    query = f"""  # Arma SQL multilinea con filtro interpolado.
        SELECT  # Inicio de selección de columnas.
            -- Columnas requeridas por Argos (orden exacto)  # Comentario SQL de orden contractual.
            nit,  # Identificador tributario.
            nombre,  # Nombre del negocio.
            departamento,  # Departamento.
            municipio,  # Municipio.
            direccion,  # Dirección.
            latitud,  # Latitud.
            longitud,  # Longitud.
            telefono,  # Teléfono.
            whatsapp,  # WhatsApp derivado.
            correo_electronico,  # Correo.
            fecha_actualizacion,  # Fecha de actualización.
            fuente,  # Fuente del dato.

            -- Columnas adicionales de calidad  # Comentario SQL de columnas extra.
            sucursal_tipo,  # Tipo de sucursal.
            categorias_maps,  # Categorías de Google Maps.
            score,  # Score Argos.
            aprobado_argos,  # Aprobación booleana.
            keyword_busqueda,  # Keyword usada en la búsqueda.
            descripcion,  # Descripción adicional.
            url,  # URL de Maps.
            fecha_extraccion,  # Fecha de extracción.
            run_id  # Identificador de corrida.
        FROM raw.google_maps_ferreterias  # Tabla origen.
        {filtro}  # Inserta filtro si aplica.
        ORDER BY departamento, municipio, nombre;  # Orden estable para exportación.
    """  # Fin del SQL.
    try:  # Intenta conectarse y exportar.
        with get_connection() as conn:  # Abre conexión PostgreSQL con context manager.
            df = pd.read_sql(query, conn)  # Ejecuta query y carga resultado en DataFrame.

        if df.empty:  # Valida si no hay resultados.
            print("No hay datos en la BD para exportar.")  # Informa ausencia de datos.
            return  # Sale sin generar archivo.

        # categorias_maps es array en PG — convertir a string  # Explica normalización previa a Excel.
        if "categorias_maps" in df.columns:  # Verifica existencia de la columna.
            df["categorias_maps"] = df["categorias_maps"].apply(  # Transforma cada valor de la columna.
                lambda x: ", ".join(x) if isinstance(x, list) else (x or "")  # Convierte listas a texto separado por comas.
            )  # Fin de la transformación.

        df = df.sort_values(by=["departamento", "municipio", "score"], ascending=[True, True, False])  # Reordena priorizando score descendente dentro de cada municipio.
        df.to_excel(EXCEL_OUTPUT_FILE, index=False, engine="openpyxl")  # Escribe el DataFrame en archivo Excel.
        print(f"✅ {len(df)} registros exportados → '{EXCEL_OUTPUT_FILE}'")  # Informa cantidad exportada y ruta.
        print(f"   Columnas: {list(df.columns)}")  # Muestra columnas incluidas.

    except Exception as e:  # Captura fallos de conexión, SQL o escritura.
        print(f"❌ Error al exportar: {e}")  # Reporta el error en consola.


if __name__ == "__main__":  # Punto de entrada CLI del script.
    solo_aprobados = "--aprobados" in sys.argv  # Detecta flag de exportación filtrada.
    export_to_excel(solo_aprobados=solo_aprobados)  # Ejecuta exportación con el filtro correspondiente.
    # Uso:  # Recordatorio de uso CLI.
    #   python data_exporter.py              → todos  # Caso sin filtro.
    #   python data_exporter.py --aprobados  → solo aprobados  # Caso filtrado.
```

### 10.4 `db.py`
```python
"""  # Docstring de módulo.
db.py — PostgreSQL para scraper Google Maps  # Describe la responsabilidad del archivo.
Tabla destino: raw.google_maps_ferreterias  # Indica la tabla principal.

Columnas requeridas por Argos:  # Enumera columnas contractuales.
  nit, nombre, departamento, municipio, direccion,  # Primer grupo de columnas.
  latitud, longitud, telefono, whatsapp, correo_electronico,  # Segundo grupo de columnas.
  fecha_actualizacion, fuente  # Cierre del grupo.

Columnas adicionales de trazabilidad y calidad:  # Enumera columnas técnicas adicionales.
  id, hash_id, run_id, fecha_extraccion, sucursal_tipo,  # Primer grupo adicional.
  categorias_maps, descripcion, keyword_busqueda,  # Segundo grupo adicional.
  url, score, aprobado_argos  # Cierre del grupo adicional.
"""  # Cierre del docstring.
import psycopg2  # Driver PostgreSQL.
from config import DB_CONFIG  # Importa configuración de conexión.


def get_connection():  # Fabrica una conexión PostgreSQL.
    return psycopg2.connect(**DB_CONFIG)  # Desempaqueta configuración y abre conexión.


def init_db():  # Inicializa el esquema y tabla si no existen.
    """Crea el esquema raw y la tabla si no existen."""  # Docstring corto de la función.
    ddl = """  # SQL DDL multilinea.
    CREATE SCHEMA IF NOT EXISTS raw;  # Crea el esquema lógico si aún no existe.

    CREATE TABLE IF NOT EXISTS raw.google_maps_ferreterias (  # Crea tabla destino si no existe.

        -- ── Identidad y trazabilidad ─────────────────────────────────────  # Bloque de columnas técnicas.
        id                    SERIAL PRIMARY KEY,  # ID autoincremental interno.
        hash_id               TEXT UNIQUE,  # Hash único para deduplicación.
        run_id                UUID        NOT NULL,  # Identificador de corrida.
        fecha_extraccion      TIMESTAMP   NOT NULL DEFAULT NOW(),  # Momento de extracción.

        -- ── Columnas requeridas por Argos (mismo orden que PA) ───────────  # Bloque de columnas de negocio.
        nit                   TEXT,  # NIT del negocio.
        nombre                TEXT,  # Nombre del negocio.
        departamento          TEXT,  # Departamento.
        municipio             TEXT,  # Municipio.
        direccion             TEXT,  # Dirección.
        latitud               DOUBLE PRECISION,  # Latitud geográfica.
        longitud              DOUBLE PRECISION,  # Longitud geográfica.
        telefono              TEXT,  # Teléfono.
        whatsapp              TEXT,  # Número deducido como WhatsApp.
        correo_electronico    TEXT,  # Correo electrónico.
        fecha_actualizacion   TIMESTAMP,  # Fecha de actualización lógica del registro.
        fuente                TEXT DEFAULT 'google_maps',  # Fuente del dato.

        -- ── Columnas adicionales de calidad ──────────────────────────────  # Bloque de columnas complementarias.
        sucursal_tipo         TEXT DEFAULT 'Principal',  # Tipo de sucursal.
        categorias_maps       TEXT[],  # Arreglo de categorías capturadas desde Maps.
        descripcion           TEXT,  # Descripción opcional.
        keyword_busqueda      TEXT,  # Keyword que originó el hallazgo.
        url                   TEXT,  # URL del lugar en Maps.
        score                 INTEGER,  # Score Argos.
        aprobado_argos        BOOLEAN  # Indicador de aprobación.
    );  # Fin de la tabla.

    CREATE INDEX IF NOT EXISTS idx_gm_municipio    ON raw.google_maps_ferreterias (municipio);  # Índice para búsquedas por municipio.
    CREATE INDEX IF NOT EXISTS idx_gm_departamento ON raw.google_maps_ferreterias (departamento);  # Índice por departamento.
    CREATE INDEX IF NOT EXISTS idx_gm_aprobado     ON raw.google_maps_ferreterias (aprobado_argos);  # Índice por aprobación.
    CREATE INDEX IF NOT EXISTS idx_gm_run_id       ON raw.google_maps_ferreterias (run_id);  # Índice por corrida.
    CREATE INDEX IF NOT EXISTS idx_gm_nombre       ON raw.google_maps_ferreterias (nombre);  # Índice por nombre.
    CREATE INDEX IF NOT EXISTS idx_gm_nit          ON raw.google_maps_ferreterias (nit);  # Índice por NIT.
    """  # Fin del DDL.
    with get_connection() as conn:  # Abre conexión a DB.
        with conn.cursor() as cur:  # Abre cursor SQL.
            cur.execute(ddl)  # Ejecuta el script DDL completo.
        conn.commit()  # Confirma cambios de esquema.
    print("[DB] Tabla raw.google_maps_ferreterias verificada.")  # Log de inicialización exitosa.


def cargar_urls_procesadas() -> set:  # Carga URLs ya persistidas para evitar reprocesarlas.
    """Carga URLs ya guardadas para usarlas como caché."""  # Docstring de la función.
    try:  # Intenta consultar la DB.
        with get_connection() as conn:  # Abre conexión.
            with conn.cursor() as cur:  # Abre cursor.
                cur.execute("SELECT url FROM raw.google_maps_ferreterias WHERE url IS NOT NULL;")  # Consulta URLs previamente guardadas.
                return {row[0] for row in cur.fetchall()}  # Devuelve set para búsquedas O(1).
    except Exception as e:  # Captura fallos de conexión o inexistencia inicial de tabla.
        print(f"[DB] No se pudo cargar caché: {e}")  # Log de fallo.
        return set()  # Devuelve caché vacía para no bloquear el scraping.


def insertar_negocio(datos: dict) -> bool:  # Inserta un negocio en la tabla destino.
    """  # Docstring de la función.
    Inserta un registro. Si el hash_id ya existe lo ignora.  # Explica la lógica de deduplicación.
    Retorna True si insertó, False si era duplicado.  # Explica el contrato de salida.
    """  # Cierre del docstring.
    sql = """  # SQL parametrizado de inserción.
    INSERT INTO raw.google_maps_ferreterias (  # Tabla destino.
        hash_id, run_id, fecha_extraccion,  # Campos de trazabilidad.
        nit, nombre, departamento, municipio, direccion,  # Campos requeridos por Argos.
        latitud, longitud, telefono, whatsapp, correo_electronico,  # Campos de contacto y geolocalización.
        fecha_actualizacion, fuente,  # Metadatos de actualización y origen.
        sucursal_tipo, categorias_maps, descripcion,  # Campos complementarios.
        keyword_busqueda, url, score, aprobado_argos  # Más campos complementarios.
    ) VALUES (  # Inicio de valores parametrizados.
        %(hash_id)s, %(run_id)s, %(fecha_extraccion)s,  # Valores de trazabilidad.
        %(nit)s, %(nombre)s, %(departamento)s, %(municipio)s, %(direccion)s,  # Valores de negocio.
        %(latitud)s, %(longitud)s, %(telefono)s, %(whatsapp)s, %(correo_electronico)s,  # Valores de contacto y geolocalización.
        %(fecha_actualizacion)s, %(fuente)s,  # Valores de actualización y origen.
        %(sucursal_tipo)s, %(categorias_maps)s, %(descripcion)s,  # Valores complementarios.
        %(keyword_busqueda)s, %(url)s, %(score)s, %(aprobado_argos)s  # Último bloque de valores.
    )  # Cierre del VALUES.
    ON CONFLICT (hash_id) DO NOTHING;  # Ignora duplicados basados en el hash.
    """  # Fin del SQL.
    try:  # Intenta insertar el registro.
        with get_connection() as conn:  # Abre conexión.
            with conn.cursor() as cur:  # Abre cursor.
                cur.execute(sql, datos)  # Ejecuta inserción parametrizada usando el diccionario datos.
                inserted = cur.rowcount  # Guarda número de filas afectadas.
            conn.commit()  # Confirma la transacción.
        return inserted == 1  # True si insertó exactamente una fila.
    except Exception as e:  # Captura errores de DB o datos inválidos.
        print(f"[DB] Error insertando {datos.get('nombre','?')}: {e}")  # Log del error con nombre si existe.
        return False  # Devuelve False ante error o no inserción.
```

### 10.5 `filter_engine.py`
```python
"""  # Docstring de módulo.
filter_engine.py — Motor de scoring Argos  # Identifica la función del módulo.
Nota de arquitectura: este motor se ejecuta durante la extracción (capa RAW)  # Explica dónde ocurre el scoring.
para un filtrado rápido, pero el score puede recalcularse en la capa STAGING  # Indica posibilidad de recálculo posterior.
si se ajustan las reglas sin necesidad de volver a hacer scraping.  # Describe la ventaja arquitectónica.
"""  # Cierre del docstring.


def calcular_score_argos(nombre: str, categorias: list, keyword_busqueda: str = "") -> tuple:  # Calcula score y aprobación.
    """  # Docstring de la función.
    Motor de puntuación basado en reglas Argos.  # Describe el enfoque del algoritmo.
    Retorna (score: int, aprobado: bool).  # Define la salida.

    Reglas:  # Encabezado de reglas.
    - palabras_positivas_alta:  +3 pts  (alta relevancia para Argos)  # Regla de bonificación alta.
    - palabras_positivas_media: +2 pts  (relevancia media, negocios válidos)  # Regla de bonificación media.
    - palabras_negativas:       -5 pts  (descalificadores duros)  # Regla de penalización.

    Umbral de aprobación: score >= 2  # Condición de aprobado.
    """  # Cierre del docstring.
    text_to_search = f"{nombre} {' '.join(categorias)} {keyword_busqueda}".lower()  # Consolida todo el texto relevante en una sola cadena en minúsculas.
    score = 0  # Inicializa acumulador de puntaje.

    # ✅ Alta relevancia — productos que Argos vende directamente  # Define lista de términos de alta afinidad.
    palabras_positivas_alta = [  # Lista de términos que suman +3 cada uno cuando aparecen.
        "cemento", "concreto", "premezclado", "mortero", "morteros",  # Materiales core.
        "agregados", "arena", "balasto", "obra gris", "bloquera",  # Materiales/segmentos core.
        "ladrillera", "prefabricado", "distribuidor de cemento",  # Más términos de alta relevancia.
        "material de construccion", "materiales de construccion",  # Términos genéricos de construcción.
        "deposito de materiales", "deposito y ferreteria",  # Tipologías valiosas.
        "ferredeposito", "ferredepositos", "centro ferretero",  # Variantes de negocio.
        "bodegas de construccion", "hierro y cemento", "cementos argos"  # Más términos de afinidad alta.
    ]  # Fin de términos de alta relevancia.

    # ✅ Relevancia media — negocios que compran materiales de construcción  # Define lista de afinidad media.
    palabras_positivas_media = [  # Lista de términos que suman +2 cada uno.
        "ferreteria", "ferreterias", "ferretero", "materiales",  # Términos del canal ferretero.
        "construccion", "deposito", "bloques", "hierro",  # Términos del sector construcción.
        "ferreteria y deposito", "construcciones", "contratista",  # Variantes de negocio/comprador.
        "obra", "ladrillo"  # Más términos relevantes.
    ]  # Fin de términos de relevancia media.

    # ❌ Descalificadores — negocios irrelevantes para Argos  # Define términos que restan fuertemente.
    palabras_negativas = [  # Lista de términos que penalizan -5 cada uno.
        "cerrajeria", "cerrajero", "pinturas", "pintura",  # Oficios/rubros no objetivo.
        "electricos", "electricista", "ornamentacion", "ornamentador",  # Más rubros no objetivo.
        "alquiler de equipos", "ropa", "comida", "taxis",  # Términos claramente irrelevantes.
        "salon de belleza", "restaurante", "supermercado",  # Negocios fuera de segmento.
        "vidrios", "vidrieria", "plomeria", "fontaneria",  # Rubros no core.
        "refrigeracion", "aires acondicionados"  # Más rubros descartados.
    ]  # Fin de descalificadores.

    for word in palabras_positivas_alta:  # Recorre términos de alta relevancia.
        if word in text_to_search:  # Verifica presencia por substring.
            score += 3  # Suma 3 puntos por coincidencia.

    for word in palabras_positivas_media:  # Recorre términos de relevancia media.
        if word in text_to_search:  # Verifica presencia por substring.
            score += 2  # Suma 2 puntos por coincidencia.

    for word in palabras_negativas:  # Recorre términos descalificadores.
        if word in text_to_search:  # Verifica presencia por substring.
            score -= 5  # Resta 5 puntos por coincidencia.

    aprobado = score >= 2  # Evalúa la aprobación contra el umbral.
    return score, aprobado  # Devuelve el puntaje y la decisión booleana.
```

### 10.6 `main.py`
```python
"""  # Docstring de módulo.
main.py — Scraper Google Maps para Argos  # Describe la responsabilidad principal del archivo.
Cambios vs versión original:  # Enumera diferencias arquitectónicas frente a una base previa.
  - Guarda en PostgreSQL (raw.google_maps_ferreterias) además del .jsonl local  # Persistencia principal en DB.
  - Agrega ciudad, departamento, run_id, fecha_extraccion, keyword_busqueda, hash_id  # Más trazabilidad por registro.
  - Caché de URLs ya procesadas viene de la BD (no solo del .jsonl)  # Deduplicación mejorada entre corridas.
  - Deduplicación por hash_id (MD5 de la URL normalizada)  # Define la llave técnica de unicidad.
"""  # Cierre del docstring.

import asyncio  # Manejo de concurrencia asíncrona.
import json  # Serialización para respaldo JSONL.
import random  # Delays aleatorios para simular comportamiento humano.
import re  # Expresiones regulares para parsing de URLs y texto.
import uuid  # Generación de run_id único por corrida.
import hashlib  # Hashing MD5 para deduplicación.
from datetime import datetime, timezone  # Manejo de fechas y zona horaria UTC.

from playwright.async_api import async_playwright, Page, BrowserContext, Response  # API asíncrona de Playwright y tipos usados.

from config import (  # Importa configuración central.
    CIUDADES, CIUDAD_DEPARTAMENTO, KEYWORDS_BUSQUEDA,  # Insumos de búsqueda y enriquecimiento geográfico.
    MAX_CONCURRENT_TABS, MIN_DELAY_SECONDS, MAX_DELAY_SECONDS,  # Parámetros de concurrencia y pausas.
    HEADLESS, OUTPUT_FILE, GUARDAR_JSONL_LOCAL  # Flags de navegador y salidas locales.
)  # Fin del bloque de importación desde config.
from filter_engine import calcular_score_argos  # Importa el motor de scoring de negocio.
from db import init_db, cargar_urls_procesadas, insertar_negocio  # Importa funciones de persistencia.

# ─────────────────────────────────────────────────────────────────────────────  # Separador visual de utilidades.
# UTILIDADES  # Encabezado de sección.
# ─────────────────────────────────────────────────────────────────────────────  # Separador visual.

def normalizar_url(url: str) -> str:  # Elimina parámetros para obtener una URL canónica.
    if not url:  # Valida entrada vacía o nula.
        return ""  # Devuelve cadena vacía si no hay URL.
    return url.split('?')[0]  # Conserva solo la parte previa a los query params.


def generar_hash(url: str) -> str:  # Genera hash de una URL para deduplicar.
    """MD5 de la URL normalizada — llave de deduplicación."""  # Docstring breve de la función.
    return hashlib.md5(url.encode("utf-8")).hexdigest()  # Calcula huella MD5 en hexadecimal.


def deducir_whatsapp(telefono_str: str) -> tuple:  # Deriva teléfono limpio y posible número WhatsApp.
    if not telefono_str:  # Si no hay teléfono origen.
        return "", ""  # Devuelve ambos campos vacíos.
    phone = re.sub(r'[^\d+]', '', telefono_str)  # Limpia todos los caracteres excepto dígitos y +.
    whatsapp = ""  # Inicializa WhatsApp vacío.
    local_phone = phone.replace("+57", "")  # Remueve prefijo Colombia para validar longitud local.
    if local_phone.startswith('3') and len(local_phone) == 10:  # Regla: móviles colombianos inician en 3 y tienen 10 dígitos.
        whatsapp = phone if phone.startswith('+') else f"+57{local_phone}"  # Normaliza a formato internacional si aplica.
    return phone, whatsapp  # Devuelve teléfono limpio y número WhatsApp deducido.


def guardar_jsonl_local(datos: dict):  # Escribe un registro serializable en archivo JSON Lines.
    """Respaldo local en .jsonl — útil para debugging y exportar a Excel."""  # Docstring de la función.
    datos_serializables = {  # Convierte el diccionario original a valores serializables.
        k: v.isoformat() if hasattr(v, 'isoformat') else v  # Convierte fechas a ISO y deja intacto el resto.
        for k, v in datos.items()  # Recorre todos los pares del diccionario.
    }  # Fin de la comprensión de diccionario.
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:  # Abre el JSONL en append con UTF-8.
        f.write(json.dumps(datos_serializables, ensure_ascii=False) + '\n')  # Escribe una línea JSON por registro.


async def human_pause():  # Introduce una pausa aleatoria entre lotes.
    delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)  # Elige un delay uniforme entre min y max.
    await asyncio.sleep(delay)  # Suspende la coroutine durante el tiempo elegido.

# ─────────────────────────────────────────────────────────────────────────────  # Separador visual de extracción de URLs.
# EXTRACCIÓN DE URLs — SCROLL ADAPTATIVO + INTERCEPCIÓN DE RED  # Encabezado de sección.
# ─────────────────────────────────────────────────────────────────────────────  # Separador visual.

async def extraer_urls_busqueda(page: Page, ciudad: str, keyword: str) -> list:  # Extrae URLs de lugares para una búsqueda dada.
    query       = f"{keyword} en {ciudad}"  # Construye la consulta humana para Google Maps.
    url_busqueda = f"https://www.google.com/maps/search/{query.replace(' ', '+')}/"  # Construye URL de búsqueda navegable.
    urls_de_red = set()  # Acumula URLs detectadas desde respuestas de red.

    async def capturar_respuesta(response: Response):  # Listener de respuestas HTTP del navegador.
        try:  # Intenta parsear respuestas relevantes.
            if "maps/search" in response.url and response.status == 200:  # Filtra respuestas de búsqueda exitosas de Maps.
                body      = await response.text()  # Lee el cuerpo textual de la respuesta.
                encontrados = re.findall(r'https://www\.google\.com/maps/place/[^\\"\']+', body)  # Extrae URLs de lugares con regex.
                for href in encontrados:  # Recorre URLs encontradas en la respuesta.
                    norm = normalizar_url(href)  # Normaliza la URL candidata.
                    if "/maps/place/" in norm:  # Valida que realmente sea una ficha de lugar.
                        urls_de_red.add(norm)  # Guarda la URL en el set capturado por red.
        except Exception:  # Ignora silenciosamente fallos de parsing/red.
            pass  # Evita que un fallo del listener interrumpa el scraping.

    page.on("response", capturar_respuesta)  # Registra el listener de respuestas en la página.
    await page.goto(url_busqueda, wait_until="domcontentloaded")  # Navega a la búsqueda de Google Maps.

    try:  # Intenta aceptar el banner de cookies.
        await page.click('button:has-text("Aceptar todo")', timeout=2500)  # Hace click en el botón si aparece.
        await asyncio.sleep(0.5)  # Espera breve tras aceptar cookies.
    except Exception:  # Si no aparece el banner o falla el click.
        pass  # Continúa sin bloquear el flujo.

    try:  # Espera el panel lateral con resultados.
        await page.wait_for_selector('div[role="feed"]', state="attached", timeout=20000)  # Espera el contenedor principal de resultados.
    except Exception:  # Si no carga el panel a tiempo.
        print(f"    [-] Timeout: panel lateral no cargó para '{query}'.")  # Log del timeout.
        page.remove_listener("response", capturar_respuesta)  # Limpia el listener antes de salir.
        return []  # Devuelve lista vacía de URLs.

    urls_de_scroll       = set()  # Acumula URLs detectadas directamente en el DOM.
    intentos_sin_nuevos  = 0  # Cuenta scrolls consecutivos sin nuevas URLs.
    MAX_INTENTOS_SIN_NUEVOS = 3  # Umbral para detenerse si no aparecen resultados nuevos.
    MAX_SCROLLS_TOTAL    = 40  # Límite duro de scrolls por búsqueda.
    ESPERA_BASE          = 2.0  # Espera base entre scrolls.
    EXTRA_ESPERA         = 1.5  # Espera adicional para dar tiempo a render/carga.

    for num_scroll in range(MAX_SCROLLS_TOTAL):  # Itera hasta el máximo de scrolls permitidos.
        elements = await page.query_selector_all('a[href*="/maps/place/"]')  # Obtiene anchors a fichas de lugar visibles en el DOM.
        nuevas   = 0  # Cuenta nuevas URLs halladas en este ciclo.
        for el in elements:  # Recorre todos los anchors hallados.
            href = await el.get_attribute('href')  # Lee el atributo href.
            if href:  # Solo procesa links válidos.
                norm = normalizar_url(href)  # Normaliza la URL del anchor.
                if norm and norm not in urls_de_scroll:  # Verifica que no esté repetida.
                    urls_de_scroll.add(norm)  # Agrega la nueva URL al set DOM.
                    nuevas += 1  # Incrementa el contador de URLs nuevas.

        try:  # Intenta detectar el fin natural de la lista de resultados.
            fin = await page.query_selector('span.HlvSq')  # Busca un posible nodo indicador de fin.
            if fin:  # Si el nodo existe.
                texto = await fin.inner_text()  # Extrae su texto visible.
                if "final" in texto.lower() or "end of" in texto.lower():  # Detecta frases de fin en español o inglés.
                    print(f"    [✓] Fin de lista en scroll #{num_scroll + 1}.")  # Log de corte exitoso.
                    break  # Sale del loop de scroll.
        except Exception:  # Si falla la detección de fin.
            pass  # No interrumpe el scraping.

        if nuevas == 0:  # Si este scroll no produjo nuevas URLs.
            intentos_sin_nuevos += 1  # Incrementa contador de inactividad.
            if intentos_sin_nuevos >= MAX_INTENTOS_SIN_NUEVOS:  # Si superó el umbral permitido.
                print(f"    [→] Sin nuevos en {MAX_INTENTOS_SIN_NUEVOS} scrolls. Finalizando.")  # Log de corte por estancamiento.
                break  # Sale del loop.
            await asyncio.sleep(EXTRA_ESPERA)  # Espera extra antes del siguiente intento.
        else:  # Si sí aparecieron nuevas URLs.
            intentos_sin_nuevos = 0  # Reinicia contador de estancamiento.
            print(f"       Scroll #{num_scroll + 1}: +{nuevas} URLs nuevas (Total DOM: {len(urls_de_scroll)})")  # Log de progreso.

        try:  # Intenta ejecutar el scroll sobre el panel lateral.
            await page.hover('div[role="feed"]')  # Enfoca el panel para que el wheel afecte el listado correcto.
            await page.mouse.wheel(0, 2500)  # Hace scroll vertical.
        except Exception:  # Si el hover o el scroll fallan.
            pass  # Continúa de forma tolerante.

        await asyncio.sleep(ESPERA_BASE + EXTRA_ESPERA)  # Espera para permitir carga de más resultados.

    page.remove_listener("response", capturar_respuesta)  # Limpia el listener de red al terminar.
    todas = urls_de_scroll.union(urls_de_red)  # Une resultados capturados por DOM y por red.
    print(f"    [→] DOM: {len(urls_de_scroll)} | Red: {len(urls_de_red)} | TOTAL: {len(todas)}")  # Log comparativo de fuentes de URLs.
    return list(todas)  # Devuelve lista final de URLs únicas.

# ─────────────────────────────────────────────────────────────────────────────  # Separador visual de procesamiento individual.
# PROCESAMIENTO DE CADA LUGAR INDIVIDUAL  # Encabezado de sección.
# ─────────────────────────────────────────────────────────────────────────────  # Separador visual.

async def procesar_lugar(  # Procesa una ficha individual de Google Maps.
    context: BrowserContext,  # Contexto del navegador compartido.
    url: str,  # URL del lugar a procesar.
    keyword: str,  # Keyword que originó la búsqueda.
    ciudad: str,  # Ciudad de contexto.
    run_id: str,  # run_id de la corrida actual.
    fecha_extraccion: datetime,  # Timestamp único de extracción de la corrida.
):  # Fin de firma.
    page = await context.new_page()  # Abre una nueva pestaña dentro del contexto.
    try:  # Inicia el procesamiento protegido de la ficha.
        await page.goto(url, wait_until="domcontentloaded")  # Navega a la ficha del lugar.

        try:  # Intenta esperar el título principal de la ficha.
            await page.wait_for_selector('h1.DUwDvf', timeout=12000)  # Espera el h1 principal.
        except Exception:  # Si no aparece a tiempo.
            pass  # Continúa intentando extraer por otras vías.

        nombre      = ""  # Inicializa nombre vacío.
        categorias  = []  # Inicializa lista de categorías.
        direccion   = ""  # Inicializa dirección vacía.
        latitud     = 0.0  # Inicializa latitud por defecto.
        longitud    = 0.0  # Inicializa longitud por defecto.
        telefono_raw = ""  # Inicializa teléfono bruto vacío.

        # Coordenadas desde URL final  # Encabezado del bloque de parsing geográfico.
        url_final = page.url  # Lee la URL final tras posibles redirecciones.
        match = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url_final)  # Busca patrón de coordenadas tipo !3d..!4d.. en la URL.
        if match:  # Si encontró ese patrón.
            latitud, longitud = float(match.group(1)), float(match.group(2))  # Convierte ambos grupos a float.
        else:  # Si no encontró el patrón principal.
            match2 = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url_final)  # Busca patrón alternativo @lat,long.
            if match2:  # Si encontró el patrón alternativo.
                latitud, longitud = float(match2.group(1)), float(match2.group(2))  # Convierte ambos valores a float.

        # Nombre  # Encabezado del bloque de extracción de nombre.
        try:  # Intenta extraer nombre desde el selector principal.
            el = await page.query_selector('h1.DUwDvf')  # Busca el h1 del nombre.
            if el:  # Si el elemento existe.
                nombre = (await el.inner_text()).strip()  # Extrae texto y quita espacios.
        except Exception:  # Si falla el selector o la lectura.
            pass  # Continúa con fallback.
        if not nombre:  # Si aún no hay nombre.
            try:  # Intenta fallback con el title del documento.
                nombre = (await page.title()).replace(" - Google Maps", "").strip()  # Limpia el sufijo común del title.
            except Exception:  # Si también falla el fallback.
                pass  # Mantiene nombre vacío.

        # Categoría — 4 estrategias en cascada  # Encabezado del bloque de categorías.
        try:  # Intenta varias estrategias de extracción de categoría.
            cat_el = await page.query_selector('button[jsaction="pane.rating.category"]')  # Estrategia 1: botón de categoría asociado a rating.
            if not cat_el:  # Si no existe.
                cat_el = await page.query_selector('span.mgr77e')  # Estrategia 2: selector alternativo.
            if not cat_el:  # Si aún no existe.
                cat_el = await page.query_selector('div.skqShb')  # Estrategia 3: otro selector alternativo.
            if not cat_el:  # Si aún no existe.
                cat_el = await page.query_selector('[aria-label*="Categoría"], [aria-label*="category"]')  # Estrategia 4: búsqueda por aria-label.
            if cat_el:  # Si alguna estrategia encontró un elemento.
                cat_text = (await cat_el.inner_text()).strip()  # Extrae texto de la categoría.
                if cat_text:  # Si el texto no quedó vacío.
                    categorias.append(cat_text)  # Guarda la categoría en la lista.
        except Exception:  # Si falla cualquier estrategia.
            pass  # Continúa sin categorías.

        # Teléfono  # Encabezado del bloque de teléfono.
        try:  # Intenta extraer teléfono desde botones conocidos.
            btn = await page.query_selector('button[data-tooltip*="teléfono"], button[data-item-id*="phone"]')  # Busca botón de teléfono en español o por item-id.
            if btn:  # Si el botón existe.
                telefono_raw = await btn.get_attribute('aria-label') or ""  # Lee aria-label, que suele contener el número.
                if ":" in telefono_raw:  # Si el valor trae prefijo descriptivo.
                    telefono_raw = telefono_raw.split(":")[-1].strip()  # Conserva solo el número limpio al final.
        except Exception:  # Si falla el selector o lectura.
            pass  # Continúa sin teléfono.

        # Dirección  # Encabezado del bloque de dirección.
        try:  # Intenta extraer dirección desde botones conocidos.
            btn = await page.query_selector('button[data-tooltip*="dirección"], button[data-item-id*="address"]')  # Busca botón de dirección en español o por item-id.
            if btn:  # Si el botón existe.
                direccion = await btn.get_attribute('aria-label') or ""  # Lee aria-label con la dirección.
                if ":" in direccion:  # Si trae prefijo descriptivo.
                    direccion = direccion.split(":")[-1].strip()  # Conserva solo la dirección limpia.
        except Exception:  # Si falla el selector o lectura.
            pass  # Continúa sin dirección.

        telefono, whatsapp = deducir_whatsapp(telefono_raw)  # Normaliza teléfono y deriva posible WhatsApp.
        score, aprobado    = calcular_score_argos(nombre, categorias, keyword)  # Calcula score y aprobación del negocio.
        departamento       = CIUDAD_DEPARTAMENTO.get(ciudad, "")  # Enriquecimiento ciudad→departamento.
        hash_id            = generar_hash(url)  # Genera hash para deduplicación del registro.

        datos = {  # Construye payload completo listo para persistir.
            # ── Trazabilidad ──────────────────────────────────────────────  # Bloque de trazabilidad.
            "hash_id":              hash_id,  # Hash único del lugar.
            "run_id":               run_id,  # Corrida a la que pertenece.
            "fecha_extraccion":     fecha_extraccion,  # Timestamp de extracción.

            # ── Columnas requeridas por Argos ─────────────────────────────  # Bloque requerido por negocio.
            "nit":                  "",  # NIT no disponible en Google Maps.
            "nombre":               nombre,  # Nombre capturado del lugar.
            "departamento":         departamento,  # Departamento enriquecido desde config.
            "municipio":            ciudad,  # Ciudad de la búsqueda.
            "direccion":            direccion,  # Dirección capturada.
            "latitud":              latitud,  # Coordenada latitud.
            "longitud":             longitud,  # Coordenada longitud.
            "telefono":             telefono,  # Teléfono normalizado.
            "whatsapp":             whatsapp,  # WhatsApp deducido si aplica.
            "correo_electronico":   "",  # Correo no extraído en esta versión.
            "fecha_actualizacion":  fecha_extraccion,  # Usa fecha de extracción como actualización lógica.
            "fuente":               "google_maps",  # Fuente de origen fija.

            # ── Columnas adicionales de calidad ───────────────────────────  # Bloque adicional de calidad.
            "sucursal_tipo":        "Principal",  # Valor fijo por defecto.
            "categorias_maps":      categorias,  # Lista de categorías obtenidas.
            "descripcion":          "",  # Descripción no extraída en esta versión.
            "keyword_busqueda":     keyword,  # Keyword que originó el hallazgo.
            "url":                  url,  # URL del lugar.
            "score":                score,  # Score calculado.
            "aprobado_argos":       aprobado,  # Booleano de aprobación.
        }  # Fin del diccionario datos.

        # Guardar en PostgreSQL (fuente de verdad)  # Aclara que DB es el repositorio principal.
        insertado = insertar_negocio(datos)  # Inserta el negocio y detecta duplicados.

        # Guardar también en .jsonl local como respaldo, solo si está habilitado  # Aclara condición del respaldo local.
        if GUARDAR_JSONL_LOCAL and insertado:  # Solo guarda local si el flag está activo y el registro fue nuevo.
            print(GUARDAR_JSONL_LOCAL)  # Debug del valor del flag.
            print(insertado)  # Debug del resultado de inserción.
            guardar_jsonl_local(datos)  # Escribe el registro en el JSONL local.

        estado = "NUEVO" if insertado else "DUPLICADO"  # Etiqueta textual del resultado de persistencia.
        print(  # Log de salida por lugar procesado.
            f"    [{estado}] {nombre} | {ciudad} | "  # Informa si fue nuevo o duplicado, nombre y ciudad.
            f"Score: {score} | WA: {'✔️' if whatsapp else '❌'} | "  # Informa score y presencia de WhatsApp.
            f"Cat: {', '.join(categorias) or 'N/A'}"  # Informa categorías halladas.
        )  # Fin del print de estado.

    except Exception as e:  # Captura fallos al procesar la ficha individual.
        print(f"    [-] Error procesando {url} → {e}")  # Log del error asociado a la URL.
    finally:  # Bloque de limpieza obligatoria.
        await page.close()  # Cierra la pestaña aunque haya habido error.

# ─────────────────────────────────────────────────────────────────────────────  # Separador visual de orquestador principal.
# ORQUESTADOR PRINCIPAL  # Encabezado de sección.
# ─────────────────────────────────────────────────────────────────────────────  # Separador visual.

STEALTH_SCRIPT = """  # Script JS inyectado para reducir señales de automatización.
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });  # Oculta webdriver.
    Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3] });  # Simula plugins instalados.
    Object.defineProperty(navigator, 'languages', { get: () => ['es-CO', 'es', 'en-US'] });  # Simula idiomas del navegador.
    window.chrome = { runtime: {} };  # Simula objeto chrome mínimo.
"""  # Fin del script stealth.

async def do_scrape():  # Orquesta la ejecución completa del scraping.
    # Inicializar BD (crea tablas si no existen)  # Asegura infraestructura de persistencia.
    init_db()  # Crea esquema y tabla si aún no existen.

    # Caché desde la BD — no reprocesamos URLs ya guardadas  # Encabezado del bloque de caché.
    procesados = cargar_urls_procesadas()  # Obtiene set de URLs ya persistidas.
    print(f"[*] Caché BD: {len(procesados)} negocios ya guardados (serán saltados).")  # Informa tamaño de caché.
    print(f"[*] Ciudades: {len(CIUDADES)} | Keywords: {len(KEYWORDS_BUSQUEDA)} | "  # Informa dimensión de la corrida.
          f"Combinaciones: {len(CIUDADES) * len(KEYWORDS_BUSQUEDA)}\n")  # Completa el mensaje con combinaciones totales.

    # run_id y timestamp únicos para esta ejecución completa  # Encabezado del bloque de trazabilidad de corrida.
    run_id           = str(uuid.uuid4())  # Genera identificador único de corrida del scraper.
    fecha_extraccion = datetime.now(timezone.utc)  # Timestamp UTC común para los registros de esta corrida.
    print(f"[*] run_id: {run_id}")  # Log del run_id.
    print(f"[*] Inicio: {fecha_extraccion.isoformat()}\n")  # Log del inicio.

    async with async_playwright() as p:  # Inicializa Playwright de forma segura.
        browser = await p.chromium.launch(  # Lanza navegador Chromium.
            headless=HEADLESS,  # Decide si corre sin UI según configuración.
            args=[  # Argumentos de endurecimiento/compatibilidad.
                "--disable-blink-features=AutomationControlled",  # Reduce señal de automatización.
                "--no-sandbox",  # Necesario en algunos contenedores.
                "--disable-dev-shm-usage",  # Mitiga problemas de /dev/shm en Docker.
                "--disable-infobars",  # Reduce barras informativas del navegador.
            ]  # Fin de args.
        )  # Fin del launch.

        context = await browser.new_context(  # Crea un contexto aislado del navegador.
            locale="es-CO",  # Localiza el navegador a español Colombia.
            user_agent=(  # Fuerza un user agent tipo Chrome realista.
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "  # Plataforma Windows de escritorio.
                "AppleWebKit/537.36 (KHTML, like Gecko) "  # Motor compatible.
                "Chrome/124.0.0.0 Safari/537.36"  # Firma de Chrome/Safari.
            ),  # Fin del user agent.
            viewport={"width": 1280, "height": 900},  # Define tamaño de viewport.
        )  # Fin del new_context.
        await context.add_init_script(STEALTH_SCRIPT)  # Inyecta script stealth en todas las páginas del contexto.

        for keyword in KEYWORDS_BUSQUEDA:  # Recorre cada término de búsqueda.
            for ciudad in CIUDADES:  # Recorre cada ciudad configurada.
                print(f"\n[*] Buscando: '{keyword}' en '{ciudad}'...")  # Log del par keyword-ciudad actual.
                page = await context.new_page()  # Abre página temporal para la búsqueda.
                try:  # Intenta extraer URLs de resultados.
                    urls_encontradas = await extraer_urls_busqueda(page, ciudad, keyword)  # Ejecuta la búsqueda en Maps.
                except Exception as e:  # Captura fallos de la búsqueda.
                    print(f"    [-] Error en búsqueda: {e}")  # Log del error.
                    urls_encontradas = []  # Usa lista vacía para continuar.
                finally:  # Limpieza del recurso de búsqueda.
                    await page.close()  # Cierra la página usada para buscar.

                urls_a_procesar = [u for u in urls_encontradas if u not in procesados]  # Filtra URLs ya conocidas por caché.
                print(f"    → {len(urls_encontradas)} totales | {len(urls_a_procesar)} nuevos.")  # Log del resumen de deduplicación previa.

                for i in range(0, len(urls_a_procesar), MAX_CONCURRENT_TABS):  # Parte las URLs nuevas en lotes de concurrencia máxima.
                    lote  = urls_a_procesar[i:i + MAX_CONCURRENT_TABS]  # Toma el sublote actual.
                    tareas = [  # Construye la lista de coroutines del lote.
                        procesar_lugar(context, url, keyword, ciudad, run_id, fecha_extraccion)  # Define una tarea por URL.
                        for url in lote  # Recorre URLs del lote.
                    ]  # Fin de la lista de tareas.
                    await asyncio.gather(*tareas)  # Ejecuta el lote en paralelo.
                    for url in lote:  # Recorre las URLs recién procesadas.
                        procesados.add(url)  # Las agrega al set para evitar reprocesarlas en esta misma corrida.
                    await human_pause()  # Espera aleatoria entre lotes.

        await browser.close()  # Cierra el navegador al finalizar toda la corrida.
        print(f"\n[✓] Scraping completado. run_id: {run_id}")  # Log de finalización global.
        print(f"[✓] Datos guardados en PostgreSQL y en: {OUTPUT_FILE}")  # Log de destinos de salida.

if __name__ == "__main__":  # Punto de entrada CLI del scraper.
    try:  # Intenta ejecutar el event loop principal.
        asyncio.run(do_scrape())  # Ejecuta el scraping completo.
    except KeyboardInterrupt:  # Captura interrupción manual por consola.
        print("\n[!] Detenido por el usuario. Todo el progreso ya fue guardado en la BD.")  # Informa parada segura con persistencia ya realizada.
```

### 10.7 `requirements.txt`
```text
playwright==1.58.0  # Automatización del navegador para scraping de Google Maps.
pandas  # Manipulación tabular y exportación a Excel.
openpyxl  # Engine de escritura de archivos .xlsx.
psycopg2-binary  # Driver PostgreSQL para Python.
python-dotenv  # Carga variables de entorno desde archivo .env.
fastapi  # Framework web para exponer la API HTTP.
uvicorn  # Servidor ASGI para ejecutar FastAPI.
httpx  # Cliente HTTP asíncrono para callbacks y requests salientes.
```

---

## 11. Dockerfile

El archivo `dockerfile`

FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8001

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8001

CMD ["python", "api_runner.py"]

---

## Cierre técnico
Este repositorio implementa una pipeline coherente de **captura → filtrado → persistencia → exposición HTTP → exportación**, con PostgreSQL como fuente de verdad y FastAPI como capa de automatización operativa.

El núcleo real del negocio está en tres piezas:
- `main.py`: extrae y orquesta.
- `filter_engine.py`: decide relevancia.
- `db.py`: garantiza persistencia y deduplicación.

La mayor mejora estructural futura sería **unificar trazabilidad de corrida**, **hacer más robusto el parsing de Google Maps** y **externalizar las reglas de scoring**.

