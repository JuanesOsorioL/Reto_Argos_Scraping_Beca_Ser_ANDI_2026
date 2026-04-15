# Documentación Técnica — Proyecto Argos Overpass Scraper

---

## Índice

1. [Resumen ejecutivo](#resumen-ejecutivo)
2. [Objetivo del proyecto](#objetivo-del-proyecto)
3. [Arquitectura general](#arquitectura-general)
4. [Flujo operativo end-to-end](#flujo-operativo-end-to-end)
5. [Mapa de dependencias](#mapa-de-dependencias)
6. [Punto de entrada y roles por archivo](#punto-de-entrada-y-roles-por-archivo)
7. [Variables de entorno](#variables-de-entorno)
8. [Modelo de datos persistido](#modelo-de-datos-persistido)
9. [Lógica crítica del sistema](#lógica-crítica-del-sistema)
10. [Endpoints expuestos](#endpoints-expuestos)
11. [Guía de ejecución](#guía-de-ejecución)
12. [Riesgos técnicos y observaciones](#riesgos-técnicos-y-observaciones)
13. [Recomendaciones de clean code y evolución](#recomendaciones-de-clean-code-y-evolución)
14. [Documentación del código](#documentación-del-código)
15. [Anexo: versión comentada por archivo](#anexo-versión-comentada-por-archivo)

---

## Resumen ejecutivo

Este proyecto implementa un **scraper de Overpass API** orientado a encontrar establecimientos relacionados con ferretería, materiales de construcción y suministros afines en Colombia, para luego **normalizar la información**, **calcular un score de relevancia para Argos**, y **persistirla en PostgreSQL**.

El sistema tiene dos modos principales de operación:

- **Modo script/CLI**, ejecutado desde `main.py`.
- **Modo servicio HTTP**, expuesto mediante `api_runner.py` para ser disparado por `n8n` o cualquier cliente externo.

El núcleo funcional se apoya en cinco piezas:

1. **Descubrimiento geográfico** de municipios de Colombia.
2. **Construcción de queries Overpass** por familia OSM.
3. **Extracción tolerante a fallos** con rotación de endpoints y backoff.
4. **Normalización y scoring** de registros.
5. **Persistencia en PostgreSQL** con deduplicación por `hash_id`.

---

## Objetivo del proyecto

El objetivo de negocio del proyecto es construir una base de datos operativa de posibles ferreterías, distribuidores y puntos de venta relacionados con construcción, usando OpenStreetMap vía Overpass API como fuente primaria.

El objetivo técnico es:

- recorrer municipios de Colombia,
- consultar varias familias de etiquetas OSM,
- tolerar errores de disponibilidad de la API pública,
- convertir respuestas heterogéneas a una estructura homogénea,
- almacenar trazabilidad mínima del proceso,
- dejar métricas utilizables por automatizaciones externas.

---

## Arquitectura general

```text
┌──────────────────────┐
│ Cliente / n8n / CLI  │
└──────────┬───────────┘
           │
           ├────────────── CLI: python main.py
           │
           └────────────── HTTP: api_runner.py (FastAPI)
                               │
                               ▼
                     ┌───────────────────┐
                     │   do_scrape()     │
                     │    en main.py     │
                     └─────────┬─────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
      municipios_colombia   Overpass API   PostgreSQL
      get_municipios()      múltiples EP   raw.overpass_ferreterias
                │              │              │
                └─────► normalización ◄──────┘
                               │
                               ▼
                       métricas / estado
                               │
                               ▼
                         callback a n8n
```

---

## Flujo operativo end-to-end

### Flujo HTTP

1. Un cliente llama a `/scrape/overpass`, `/scrape/overpass/prueba` o `/scrape/overpass/depto`.
2. `api_runner.py` valida si ya existe una corrida activa.
3. Se genera un `run_id` y se actualiza el estado global en memoria.
4. Se lanza una tarea asíncrona en background que importa y ejecuta `do_scrape()` desde `main.py`.
5. `main.py` obtiene los municipios, crea queries Overpass, consulta endpoints, normaliza, deduplica y persiste.
6. Al finalizar, `api_runner.py` actualiza el estado y envía un callback a `n8n`.

### Flujo CLI

1. Se ejecuta `python main.py` con o sin flags.
2. `main.py` resuelve el subconjunto de municipios.
3. Ejecuta `do_scrape()`.
4. Guarda resultados en base de datos y opcionalmente en JSON/JSONL/log.

---

## Mapa de dependencias

| Archivo | Tipo | Depende de | Es consumido por | Rol principal |
|---|---|---|---|---|
| `.env` | Configuración | Ninguno | `main.py`, `api_runner.py` | Parametrización del entorno |
| `requirements.txt` | Dependencias | Ninguno | Entorno de Python | Instalación de librerías |
| `municipios_colombia.py` | Datos + helper | Ninguno | `main.py`, `api_runner.py` | Catálogo de municipios |
| `main.py` | Núcleo de negocio | `.env`, `municipios_colombia.py`, PostgreSQL, Overpass | `api_runner.py`, CLI | Scraping, normalización y persistencia |
| `api_runner.py` | Capa de integración | `.env`, `main.py`, `municipios_colombia.py` | Clientes HTTP / n8n | Orquestación vía API |
| `dockerfile` | Infraestructura | Repositorio y Python | Runtime Docker | Empaquetado del servicio |

### Dependencias lógicas internas

```text
api_runner.py
 ├── importa do_scrape desde main.py
 ├── importa get_municipios desde municipios_colombia.py
 └── usa N8N_WEBHOOK_URL y PORT del entorno

main.py
 ├── carga .env con load_dotenv()
 ├── importa get_municipios desde municipios_colombia.py
 ├── usa requests para Overpass
 ├── usa psycopg2 para PostgreSQL
 └── usa Json de psycopg2.extras para almacenar raw_response
```

---

## Punto de entrada y roles por archivo

### Punto de entrada principal

- **HTTP**: `api_runner.py`
- **CLI**: `main.py`

### Clasificación por responsabilidad

| Archivo | Clasificación |
|---|---|
| `api_runner.py` | Adaptador de entrada / capa de integración / orquestación externa |
| `main.py` | Lógica de negocio principal |
| `municipios_colombia.py` | Catálogo estático / utilitario de datos |
| `.env` | Configuración externa |
| `requirements.txt` | Gestión de dependencias |
| `dockerfile` | Infraestructura / despliegue |

---

## Variables de entorno

| Variable | Valor observado | Uso |
|---|---:|---|
| `DB_HOST` | `localhost` | Host PostgreSQL |
| `DB_PORT` | `5432` | Puerto PostgreSQL |
| `DB_NAME` | `postgres` | Base de datos |
| `DB_USER` | `postgres` | Usuario |
| `DB_PASSWORD` | `1234` | Contraseña |
| `SAVE_LOG_FILES` | `false` | Activa/desactiva logs a archivo |
| `SAVE_OUTPUT_FILES` | `false` | Activa/desactiva JSON/JSONL de salida |
| `PORT` | fallback `8007` | Puerto FastAPI |
| `N8N_WEBHOOK_URL` | no observado en `.env` | URL de callback hacia n8n |

### Observación importante

`N8N_WEBHOOK_URL` es requerida para callbacks desde `api_runner.py`. Si no está definida, `enviar_callback()` lanza excepción.

---

## Modelo de datos persistido

La tabla persistida es `raw.overpass_ferreterias`.

### Propósito del esquema

- guardar una copia **normalizada** de cada lugar,
- conservar un **payload crudo** en `raw_response`,
- permitir análisis posterior por `run_id`, municipio, departamento, familia OSM y score Argos.

### Campos clave

| Campo | Propósito |
|---|---|
| `hash_id` | Clave única funcional para deduplicación |
| `run_id` | Identificador de la corrida |
| `nombre`, `departamento`, `municipio` | Datos base del establecimiento |
| `latitud`, `longitud` | Georreferenciación |
| `telefono`, `correo_electronico`, `website` | Contactabilidad |
| `score`, `aprobado_argos` | Clasificación de relevancia |
| `osm_type`, `osm_id`, `familia_osm` | Trazabilidad de origen en OSM |
| `raw_response` | Payload crudo completo |

---

## Lógica crítica del sistema

### 1. Estrategia de búsqueda OSM

Se consultan cinco familias:

- `hardware`
- `building_materials`
- `trade_supplies`
- `doityourself`
- `text_search`

Las primeras cuatro usan etiquetas estructuradas de OSM. La última usa una búsqueda por nombre mediante regex para capturar establecimientos que no estén correctamente tipificados.

### 2. Tolerancia a fallos

`OverpassClient` rota entre múltiples endpoints públicos y aplica backoff exponencial.

### 3. Deduplicación

Cada registro genera un hash determinístico basado en:

```text
overpass|osm_type|osm_id
```

### 4. Scoring Argos

El score mezcla:

- familia OSM encontrada,
- coincidencia del nombre con palabras de alto valor.

### 5. Persistencia robusta

Se usa `ON CONFLICT (hash_id) DO NOTHING`, lo que protege de inserciones repetidas incluso si el conjunto ya procesado no estuviera perfectamente sincronizado.

---

## Endpoints expuestos

| Método | Ruta | Propósito |
|---|---|---|
| GET | `/health` | Verificación simple de vida |
| GET | `/status` | Estado global de la corrida |
| POST | `/scrape/overpass` | Ejecuta scraping completo |
| POST | `/scrape/overpass/prueba` | Ejecuta scraping de prueba |
| POST | `/scrape/overpass/depto` | Ejecuta scraping filtrado por departamento |
| GET | `/resultado` | Devuelve resumen del último estado |
| POST | `/test/callback` | Dispara un callback sintético a n8n |
| GET | `/endpoints` | Lista rutas registradas |

---

## Guía de ejecución

### Instalación

```bash
pip install -r requirements.txt
```

### Configuración

Crear o ajustar `.env` con credenciales de base de datos y flags.

### Ejecución CLI

```bash
python main.py
python main.py --test
python main.py --dept Antioquia
python main.py --limit 50
```

### Ejecución API

```bash
python api_runner.py
```

Luego consumir:

```bash
GET  /health
POST /scrape/overpass
GET  /status
```

---

## Riesgos técnicos y observaciones

### Riesgos detectados

1. **Estado global en memoria**: `estado` vive solo dentro del proceso FastAPI.
2. **Conexión global `_conn`**: puede ser frágil en escenarios multiworker.
3. **Lista de municipios parcialmente placeholder**: existe al menos una entrada abreviada (`"Aquí va el resto..."`) que luego es filtrada.
4. **Dependencia de Overpass pública**: la disponibilidad puede fluctuar.
5. **Credenciales hardcodeadas por defecto**: los defaults del `.env` son inseguros para producción.
6. **Dockerfile no recuperado**: no fue posible inspeccionar su contenido desde los archivos accesibles de esta sesión, por lo que solo puede documentarse su rol esperado, no su implementación exacta.

---

## Recomendaciones de clean code y evolución

### Recomendaciones prioritarias

1. Separar `main.py` en módulos:
   - `db.py`
   - `overpass_client.py`
   - `normalizers.py`
   - `config.py`
   - `scraper_service.py`
2. Reemplazar estado global por persistencia transaccional de corridas.
3. Extraer el esquema SQL a migraciones formales.
4. Reemplazar `print()` por logging consistente en `api_runner.py`.
5. Añadir tests para:
   - `calcular_score`
   - `normalizar_elemento`
   - `build_query`
   - filtros por departamento
6. Añadir validación Pydantic en request bodies de FastAPI.
7. Proteger secretos vía variables de entorno seguras.

---

## Documentación del código

En esta sección se explica el código por archivo, siguiendo la estructura real del repositorio.

---

# Anexo: versión comentada por archivo

> **Nota metodológica interna del documento:** donde el archivo contiene cientos de líneas repetitivas de catálogo de municipios, la explicación línea por línea se hace por patrón estructural, sin alterar el valor de cada entrada. En los archivos ejecutables, la explicación sí se detalla bloque por bloque y línea por línea funcional.

---

## 1) `.env` — documentación línea por línea

```env
DB_HOST=localhost              # Define el host del servidor PostgreSQL al que se conectará main.py.
DB_PORT=5432                   # Define el puerto de PostgreSQL; luego se convierte a entero en DB_CONFIG.
DB_NAME=postgres               # Define el nombre de la base de datos objetivo.
DB_USER=postgres               # Define el usuario de autenticación contra PostgreSQL.
DB_PASSWORD=1234               # Define la contraseña del usuario configurado.
                               # Línea en blanco usada solo para separar grupos visuales.
SAVE_LOG_FILES=false           # Flag booleana para decidir si setup_logging() también escribe archivos .log.
SAVE_OUTPUT_FILES=false        # Flag booleana para decidir si do_scrape() genera JSON/JSONL en output/.
```

### Lectura técnica

Este archivo externaliza parámetros de entorno para que el comportamiento del proyecto cambie sin modificar código fuente.

---

## 2) `requirements.txt` — documentación línea por línea

```txt
requests            # Cliente HTTP síncrono usado por main.py para consultar Overpass.
httpx               # Cliente HTTP asíncrono usado por api_runner.py para callbacks a n8n.
psycopg2-binary     # Driver PostgreSQL usado para conexión, DDL e inserciones.
python-dotenv       # Permite cargar el archivo .env dentro del proceso Python.
fastapi             # Framework web con el que se exponen endpoints HTTP.
uvicorn             # Servidor ASGI usado para levantar la API FastAPI.
pandas              # Dependencia instalada pero no observada en el código actual recuperado.
openpyxl            # Dependencia instalada pero no observada en el código actual recuperado.
```

### Lectura técnica

`pandas` y `openpyxl` aparecen instaladas pero no son usadas en los fragmentos ejecutables observados; podrían ser remanentes o preparación para futuras exportaciones.

---

## 3) `municipios_colombia.py` — explicación estructural y línea por línea por patrón

### Propósito del archivo

Este archivo funciona como un **catálogo estático de municipios**. Su diseño es deliberadamente simple: una lista de diccionarios con pares `departamento` / `municipio`, más una función de utilidad para filtrar placeholders.

### Estructura real del archivo

```python
""" ... docstring ... """          # Encabezado descriptivo del módulo.
MUNICIPIOS_COLOMBIA = [              # Inicio de la lista maestra.
    # AMAZONAS                       # Comentario separador de bloque departamental.
    {"departamento": ..., ...},     # Entrada de municipio.
    {"departamento": ..., ...},     # Entrada de municipio.
    ...                              # Repetición homogénea del mismo patrón.
]

def get_municipios():                # Helper para devolver solo entradas válidas.
    ...

if __name__ == "__main__":          # Bloque de ejecución directa para inspección manual.
    ...
```

### Línea por línea funcional

```python
"""                                   # Abre el docstring del módulo.
municipios_colombia.py — Lista completa de los 1122 municipios de Colombia  # Describe la intención del archivo.
con departamento, para usarse en el scraper de Overpass.                    # Explica el uso operativo del catálogo.
                                                                             # Línea visual de separación dentro del docstring.
Fuente: División Político-Administrativa de Colombia (DIVIPOLA) - DANE      # Documenta la fuente conceptual del dataset.
"""                                   # Cierra el docstring del módulo.

MUNICIPIOS_COLOMBIA = [                # Declara la estructura principal con todas las entradas.
    # AMAZONAS                         # Inicia el grupo visual del departamento Amazonas.
    {"departamento": "Amazonas", "municipio": "Leticia"},          # Registra un municipio con su departamento.
    {"departamento": "Amazonas", "municipio": "Puerto Nariño"},   # Registra otro municipio bajo el mismo patrón.
    # ANTIOQUIA                        # Marca el siguiente bloque departamental.
    {"departamento": "Antioquia", "municipio": "Medellín"},       # Entrada estándar del catálogo.
    {"departamento": "Antioquia", "municipio": "Abejorral"},      # Entrada estándar del catálogo.
    ...                                # Cada línea análoga agrega exactamente un municipio al dataset estático.
    {"departamento": "Boyacá", "municipio": "Aquí va el resto..."}, # Placeholder detectado y posteriormente filtrado.
    ...                                # Continúa el mismo patrón de datos homogéneos.
]                                      # Cierra la lista completa del catálogo.


def get_municipios():                  # Declara la función pública de acceso seguro al catálogo.
    """Retorna la lista completa de municipios filtrada de entradas placeholder."""  # Documenta el comportamiento esperado.
    return [m for m in MUNICIPIOS_COLOMBIA if "va el resto" not in m["municipio"]]   # Filtra entradas no definitivas.


if __name__ == "__main__":            # Permite ejecutar el archivo como script autónomo.
    municipios = get_municipios()      # Obtiene la lista ya depurada.
    print(f"Total municipios: {len(municipios)}")  # Imprime la cantidad de municipios válidos.
    depts = set(m["departamento"] for m in municipios)  # Calcula departamentos únicos.
    print(f"Departamentos: {len(depts)}")  # Imprime la cantidad de departamentos encontrados.
```

### Interpretación del bloque masivo de municipios

Cada línea de la lista cumple siempre la misma función técnica:

```python
{"departamento": "X", "municipio": "Y"},   # Inserta un registro estático que será iterado por main.py.
```

Por tanto, aunque el archivo sea extenso, la semántica línea por línea es constante: **cada línea añade una unidad geográfica al universo de búsqueda**.

---

## 4) `main.py` — documentación técnica exhaustiva

### Propósito del archivo

`main.py` es el corazón del proyecto. Aquí viven:

- configuración,
- logging,
- conexión a base de datos,
- esquema SQL,
- cliente Overpass,
- construcción de queries,
- normalización,
- scoring,
- orquestación completa del scraping,
- entrada CLI.

### Lectura estructural del archivo

```python
Docstring inicial                        # Describe fixes y ejemplos de uso.
Imports                                  # Carga de dependencias del núcleo.
load_dotenv()                            # Inyección de variables de entorno.
Constantes                               # Endpoints, timeouts, regex, familias, score.
Helpers de entorno y logging             # Lectura booleana y configuración de logs.
Capa DB                                  # Conexión, esquema, lectura de hashes, inserción.
Cliente Overpass                         # Reintentos y rotación de endpoints.
Construcción de query                    # build_query y area_candidates.
Normalización y scoring                  # calcular_score y normalizar_elemento.
Persistencia JSONL opcional              # append_jsonl.
Orquestador principal                    # do_scrape().
Entrada CLI                              # parseo de argumentos y ejecución.
```

### Versión comentada

```python
"""                                                     # Abre el docstring de cabecera.
main.py — Scraper Overpass API para el proyecto Argos   # Identifica el módulo principal.
======================================================  # Subrayado visual descriptivo.
                                                         # Línea de separación visual.
Fixes aplicados:                                        # Introduce el historial resumido de mejoras.
  1. text_search separado en query propia más liviana (sin regex complejo)  # Mejora de performance de consultas por nombre.
  2. Backoff exponencial con cap en 30s                 # Define estrategia de reintentos.
  3. Si todos los endpoints fallan con 504/429, espera 60s y reintenta 1 vez # Mejora resiliencia ante saturación.
  4. JSON de fallidos (overpass-fallidos-RUNID.json) para trazabilidad        # Agrega persistencia de errores.
  5. Pausa entre queries aumentada a 2s para no saturar la API pública        # Reduce agresividad contra Overpass.
                                                         # Línea visual.
Uso:                                                    # Introduce ejemplos de ejecución.
  python main.py                                        # Ejecuta sobre todos los municipios disponibles.
  python main.py --test                                 # Ejecuta sobre un subconjunto de prueba.
  python main.py --dept Antioquia                       # Filtra por departamento.
  python main.py --limit 50                             # Limita cantidad de municipios.
"""                                                     # Cierra el docstring inicial.

from __future__ import annotations                      # Activa evaluación diferida de anotaciones de tipos.

import argparse                                         # Permite parsear argumentos de línea de comandos.
import hashlib                                          # Permite generar hash_id determinístico.
import json                                             # Permite serializar estructuras a JSON/JSONL.
import logging                                          # Maneja logs del sistema.
import os                                               # Lee variables de entorno y rutas del sistema.
import sys                                              # Proporciona stdout para logging.
import time                                             # Maneja pausas y backoff.
import uuid                                             # Genera identificadores únicos de corridas.
from datetime import datetime, timezone                 # Maneja tiempos locales y UTC.
from pathlib import Path                                # Abstrae rutas de archivos.
from typing import Any, Dict, List, Optional, Set, Tuple # Tipado estático del módulo.

import psycopg2                                         # Driver de PostgreSQL.
import requests                                         # Cliente HTTP síncrono para Overpass.
from psycopg2.extras import Json                        # Wrapper para insertar JSONB correctamente.
from dotenv import load_dotenv                          # Carga variables desde .env.

load_dotenv()                                           # Inyecta variables de entorno al proceso actual.

# ─── Configuración ────────────────────────────────────────────────────────────

OVERPASS_ENDPOINTS = [                                  # Lista de endpoints públicos alternativos para rotación.
    "https://overpass-api.de/api/interpreter",         # Endpoint principal.
    "https://lz4.overpass-api.de/api/interpreter",     # Espejo alternativo.
    "https://z.overpass-api.de/api/interpreter",       # Segundo espejo alternativo.
]                                                       # Cierra la lista de endpoints.

TIMEOUT_QUERY       = 90                                # Tiempo máximo por consulta Overpass.
PAUSE_ENTRE_QUERIES = 2.0                               # Pausa fija entre consultas exitosas.
MAX_INTENTOS        = 4                                 # Cantidad base de intentos antes del reintento largo final.
ESPERA_SOBRECARGA   = 60                                # Espera extraordinaria cuando todos los endpoints fallan.

TEXT_REGEX = r"(ferreter|cement|concret|morter|bloquera|ladriller|prefabric|deposito|material)"  # Expresión regular liviana para búsqueda por nombre.

FAMILIAS_OSM = {                                        # Define las familias de búsqueda OSM.
    "hardware": {                                     # Familia 1: ferreterías tipificadas.
        "descripcion": "Ferreterías (shop=hardware)", # Etiqueta humana descriptiva.
        "tags":        'nwr["shop"="hardware"](area.a);', # Cuerpo Overpass QL.
        "es_regex":    False,                         # Indica que no es búsqueda regex costosa.
    },
    "building_materials": {                           # Familia 2: materiales de construcción.
        "descripcion": "Materiales de construcción (shop=building_materials)",
        "tags":        'nwr["shop"="building_materials"](area.a);',
        "es_regex":    False,
    },
    "trade_supplies": {                               # Familia 3: trade / building supplies.
        "descripcion": "Trade / distribuidoras (shop=trade)",
        "tags":        'nwr["shop"="trade"](area.a); nwr["shop"="trade"]["trade"="building_supplies"](area.a);',
        "es_regex":    False,
    },
    "doityourself": {                                 # Familia 4: mejoramiento del hogar.
        "descripcion": "Mejoramiento del hogar (shop=doityourself)",
        "tags":        'nwr["shop"="doityourself"](area.a);',
        "es_regex":    False,
    },
    "text_search": {                                  # Familia 5: búsqueda por nombre con regex.
        "descripcion": "Búsqueda por nombre (regex)",
        "tags":        f'nwr["name"~"{TEXT_REGEX}", i](area.a);',
        "es_regex":    True,                          # Esta familia sí requiere tratamiento más conservador.
    },
}                                                       # Cierra la configuración de familias.

CIIU_RELEVANTES = {"4752", "4753", "4659", "4690", "2394", "2395"}  # Catálogo preparado de códigos CIIU relevantes.
PALABRAS_ALTA   = ["ferreter", "cemento", "concreto", "mortero", "prefabric",
                   "bloquera", "ladriller", "deposito", "material construccion"]  # Palabras que elevan score por nombre.
ARGOS_THRESHOLD = 2                                     # Umbral mínimo para marcar aprobado_argos.

DB_CONFIG = {                                           # Configuración consolidada de PostgreSQL.
    "host":     os.getenv("DB_HOST",     "localhost"), # Lee host del entorno.
    "port":     int(os.getenv("DB_PORT", "5432")),     # Lee puerto y lo convierte a entero.
    "dbname":   os.getenv("DB_NAME",     "postgres"),  # Lee nombre de la base.
    "user":     os.getenv("DB_USER",     "postgres"),  # Lee usuario.
    "password": os.getenv("DB_PASSWORD", "1234"),      # Lee contraseña.
}                                                       # Cierra configuración de base de datos.

OUTPUT_DIR = Path("output")                            # Ruta lógica para archivos de salida.
LOG_DIR    = Path("logs")                              # Ruta lógica para archivos de log.

def env_bool(name: str, default: bool = False) -> bool: # Helper que interpreta strings de entorno como booleanos.
    value = os.getenv(name)                             # Lee el valor bruto.
    if value is None:                                   # Si no existe la variable,
        return default                                  # devuelve el valor por defecto.
    return value.strip().lower() in ("1", "true", "yes", "si", "sí", "on")  # Convierte varias formas textuales a True.


SAVE_LOG_FILES = env_bool("SAVE_LOG_FILES", False)     # Resuelve si se guardan logs en disco.
SAVE_OUTPUT_FILES = env_bool("SAVE_OUTPUT_FILES", False) # Resuelve si se guardan JSON y JSONL.

# ─── Logging ─────────────────────────────────────────────────────────────────
def setup_logging():                                    # Configura el subsistema de logging.
    handlers = [logging.StreamHandler(sys.stdout)]      # Siempre loguea a stdout.

    if SAVE_LOG_FILES:                                  # Solo si el flag está activo,
        LOG_DIR.mkdir(parents=True, exist_ok=True)      # asegura la carpeta de logs.
        fecha = datetime.now().strftime("%Y-%m-%d")    # Construye nombre del log por fecha.
        handlers.append(                                # Añade un archivo de log a los handlers.
            logging.FileHandler(LOG_DIR / f"overpass-{fecha}.log", encoding="utf-8")
        )

    logging.basicConfig(                                # Inicializa configuración global de logging.
        level=logging.INFO,                             # Nivel mínimo INFO.
        format="%(asctime)s | %(levelname)-7s | %(message)s", # Formato de cada línea.
        datefmt="%Y-%m-%d %H:%M:%S",                  # Formato de fecha/hora.
        handlers=handlers,                              # Usa los handlers construidos.
        force=True,                                     # Reemplaza configuraciones previas.
    )

log = logging.getLogger(__name__)                       # Obtiene logger del módulo.

# ─── PostgreSQL ───────────────────────────────────────────────────────────────

_conn = None                                            # Mantiene una referencia global reutilizable de conexión.

def get_conn():                                          # Devuelve una conexión viva a PostgreSQL.
    global _conn                                         # Indica uso de variable global.
    if _conn is None or _conn.closed:                    # Si no existe o está cerrada,
        _conn = psycopg2.connect(**DB_CONFIG)            # crea una nueva conexión.
    return _conn                                         # Retorna la conexión activa.

def init_db():                                           # Garantiza existencia de esquema y tabla.
    with get_conn() as conn:                             # Abre contexto de conexión.
        with conn.cursor() as cur:                       # Abre cursor SQL.
            cur.execute("CREATE SCHEMA IF NOT EXISTS raw;") # Crea esquema raw si no existe.
            cur.execute("""                              # Ejecuta DDL principal de la tabla.
                CREATE TABLE IF NOT EXISTS raw.overpass_ferreterias (
                    id               SERIAL PRIMARY KEY, # Clave primaria surrogate.
                    hash_id          TEXT UNIQUE,        # Clave funcional única de deduplicación.
                    run_id           UUID        NOT NULL, # Identifica la corrida.
                    fecha_extraccion TIMESTAMP   NOT NULL DEFAULT NOW(), # Momento de inserción.
                    nit              TEXT,               # Campo reservado para NIT.
                    nombre           TEXT,               # Nombre del lugar.
                    departamento     TEXT,               # Departamento del lugar.
                    municipio        TEXT,               # Municipio del lugar.
                    direccion        TEXT,               # Dirección normalizada.
                    latitud          DOUBLE PRECISION,   # Latitud geográfica.
                    longitud         DOUBLE PRECISION,   # Longitud geográfica.
                    telefono         TEXT,               # Teléfono principal.
                    whatsapp         TEXT,               # Contacto de WhatsApp.
                    correo_electronico TEXT,             # Correo principal.
                    fecha_actualizacion TIMESTAMP,       # Campo reservado para futuras actualizaciones.
                    fuente           TEXT DEFAULT 'openstreetmap', # Fuente del dato.
                    score            INTEGER,            # Score Argos.
                    aprobado_argos   BOOLEAN,            # Indicador booleano de aprobación.
                    osm_type         TEXT,               # Tipo OSM: node/way/relation.
                    osm_id           BIGINT,             # Identificador OSM.
                    familia_osm      TEXT,               # Familia que disparó el hallazgo.
                    shop_tag         TEXT,               # Valor de tag shop.
                    trade_tag        TEXT,               # Valor de tag trade.
                    brand            TEXT,               # Marca OSM.
                    operator_osm     TEXT,               # Operador OSM.
                    opening_hours    TEXT,               # Horarios.
                    website          TEXT,               # Sitio web.
                    email_osm        TEXT,               # Email original OSM.
                    instagram        TEXT,               # Red social Instagram.
                    facebook         TEXT,               # Red social Facebook.
                    twitter          TEXT,               # Red social Twitter.
                    addr_street      TEXT,               # Calle OSM.
                    addr_number      TEXT,               # Número OSM.
                    addr_city        TEXT,               # Ciudad OSM.
                    addr_state       TEXT,               # Estado OSM.
                    addr_postcode    TEXT,               # Código postal OSM.
                    description_osm  TEXT,               # Descripción libre OSM.
                    raw_response     JSONB               # Payload completo normalizado/crudo.
                );
                CREATE INDEX IF NOT EXISTS idx_ov_municipio  ON raw.overpass_ferreterias (municipio);    # Índice por municipio.
                CREATE INDEX IF NOT EXISTS idx_ov_dept       ON raw.overpass_ferreterias (departamento); # Índice por departamento.
                CREATE INDEX IF NOT EXISTS idx_ov_aprobado   ON raw.overpass_ferreterias (aprobado_argos); # Índice por aprobación.
                CREATE INDEX IF NOT EXISTS idx_ov_run        ON raw.overpass_ferreterias (run_id);       # Índice por corrida.
                CREATE INDEX IF NOT EXISTS idx_ov_osm        ON raw.overpass_ferreterias (osm_type, osm_id); # Índice por identidad OSM.
                CREATE INDEX IF NOT EXISTS idx_ov_familia    ON raw.overpass_ferreterias (familia_osm); # Índice por familia de búsqueda.
            """)
        conn.commit()                                     # Confirma el DDL.
    log.info("[DB] Tabla raw.overpass_ferreterias verificada.") # Registra éxito.

def cargar_hashes_procesados() -> Set[str]:               # Carga hash_id existentes para deduplicación previa en memoria.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT hash_id FROM raw.overpass_ferreterias WHERE hash_id IS NOT NULL") # Consulta hashes ya guardados.
                return {row[0] for row in cur.fetchall()}  # Convierte resultados a set para búsqueda O(1).
    except Exception as e:
        log.warning(f"[DB] No se pudo cargar hashes: {e}") # Avisa si falló la carga.
        return set()                                      # Devuelve set vacío como fallback.

def insertar_lugar(run_id: str, registro: dict) -> bool:  # Inserta un lugar normalizado en la tabla destino.
    sql = """                                             # SQL parametrizado de inserción.
        INSERT INTO raw.overpass_ferreterias (
            hash_id, run_id,
            nit, nombre, departamento, municipio, direccion,
            latitud, longitud, telefono, whatsapp, correo_electronico, fuente,
            score, aprobado_argos,
            osm_type, osm_id, familia_osm, shop_tag, trade_tag,
            brand, operator_osm, opening_hours, website, email_osm,
            instagram, facebook, twitter,
            addr_street, addr_number, addr_city, addr_state, addr_postcode,
            description_osm, raw_response
        ) VALUES (
            %(hash_id)s, %(run_id)s,
            %(nit)s, %(nombre)s, %(departamento)s, %(municipio)s, %(direccion)s,
            %(latitud)s, %(longitud)s, %(telefono)s, %(whatsapp)s,
            %(correo_electronico)s, %(fuente)s,
            %(score)s, %(aprobado_argos)s,
            %(osm_type)s, %(osm_id)s, %(familia_osm)s, %(shop_tag)s, %(trade_tag)s,
            %(brand)s, %(operator_osm)s, %(opening_hours)s, %(website)s, %(email_osm)s,
            %(instagram)s, %(facebook)s, %(twitter)s,
            %(addr_street)s, %(addr_number)s, %(addr_city)s, %(addr_state)s,
            %(addr_postcode)s, %(description_osm)s, %(raw_response)s
        ) ON CONFLICT (hash_id) DO NOTHING                # Evita duplicados por hash_id.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                payload = {**registro, "raw_response": Json(registro.get("raw_response"))} # Envuelve JSONB correctamente.
                cur.execute(sql, payload)                 # Ejecuta inserción parametrizada.
                inserted = cur.rowcount                   # rowcount=1 si insertó; 0 si hizo DO NOTHING.
            conn.commit()                                 # Confirma la transacción.
        return inserted == 1                              # Retorna si realmente se insertó.
    except Exception as e:
        log.error(f"[DB] insertarLugar {registro.get('nombre')}: {e}") # Registra error de inserción.
        return False                                      # Fallback negativo.

# ─── Overpass Client ──────────────────────────────────────────────────────────

class OverpassClient:                                     # Encapsula la lógica de acceso resiliente a Overpass.
    """Cliente con rotación de endpoints y backoff exponencial.""" # Documentación resumida.
    def __init__(self):                                   # Constructor del cliente.
        self.session = requests.Session()                 # Reutiliza conexión HTTP para eficiencia.
        self.session.headers["User-Agent"] = "argos-overpass-scraper/2.0" # Define User-Agent identificable.
        self._ep_idx = 0                                  # Índice interno de rotación de endpoints.

    def _next_endpoint(self) -> str:                      # Devuelve el próximo endpoint disponible en round-robin.
        ep = OVERPASS_ENDPOINTS[self._ep_idx % len(OVERPASS_ENDPOINTS)] # Selecciona endpoint según índice circular.
        self._ep_idx += 1                                 # Avanza el índice interno.
        return ep                                         # Retorna el endpoint elegido.

    def query(self, ql: str, es_regex: bool = False) -> Tuple[dict, str]: # Ejecuta una consulta con reintentos.
        if es_regex:                                      # Si la query usa regex,
            time.sleep(1.0)                               # aplica una pausa extra preventiva.

        last_err = None                                   # Inicializa variable de último error observado.

        for intento in range(MAX_INTENTOS):               # Recorre los intentos base.
            endpoint = self._next_endpoint()              # Selecciona endpoint rotado.
            wait     = min(5 * (2 ** intento), 30)        # Calcula backoff exponencial con tope de 30 segundos.

            try:
                resp = self.session.post(                 # Ejecuta POST hacia Overpass.
                    endpoint,
                    data={"data": ql},                   # Envía Overpass QL como body.
                    timeout=TIMEOUT_QUERY,                # Usa timeout configurable.
                )

                if resp.status_code == 429:              # Si hay rate limit,
                    log.warning(f"  [429] Rate limit en {endpoint}, esperando {wait}s...") # registra la condición.
                    time.sleep(wait)                      # espera el backoff.
                    continue                              # prueba con el siguiente intento.

                if resp.status_code in (502, 503, 504):  # Si el endpoint está degradado o saturado,
                    log.warning(f"  [{resp.status_code}] {endpoint}, esperando {wait}s...")
                    time.sleep(wait)                      # espera antes de reintentar.
                    continue                              # sigue el ciclo.

                resp.raise_for_status()                   # Eleva error si la respuesta no es 2xx.
                time.sleep(PAUSE_ENTRE_QUERIES)           # Pausa de cortesía tras éxito.
                return resp.json(), endpoint              # Retorna payload JSON y endpoint que respondió.

            except requests.Timeout:                      # Maneja timeout explícito.
                log.warning(f"  [TIMEOUT] {endpoint}, esperando {wait}s...")
                last_err = "timeout"                     # Guarda la causa conocida.
                time.sleep(wait)                          # Espera antes del siguiente intento.
            except Exception as e:                        # Maneja cualquier otro error HTTP/parsing/red.
                log.warning(f"  [ERROR] {endpoint}: {e}, esperando {wait}s...")
                last_err = str(e)                         # Guarda texto del último error.
                time.sleep(wait)                          # Espera antes de reintentar.

        log.warning(f"  [SOBRECARGA] Todos los endpoints fallaron. Esperando {ESPERA_SOBRECARGA}s antes de último reintento...") # Marca la fase de espera larga.
        time.sleep(ESPERA_SOBRECARGA)                     # Espera extraordinaria.

        endpoint = self._next_endpoint()                  # Toma otro endpoint para el intento final.
        try:
            resp = self.session.post(endpoint, data={"data": ql}, timeout=TIMEOUT_QUERY) # Intenta una última vez.
            resp.raise_for_status()                       # Verifica éxito HTTP.
            time.sleep(PAUSE_ENTRE_QUERIES)               # Aplica pausa estándar tras éxito.
            log.info(f"  [RECUPERADO] {endpoint} respondió tras espera.") # Registra recuperación.
            return resp.json(), endpoint                  # Devuelve resultado recuperado.
        except Exception as e:
            raise RuntimeError(f"Overpass no respondió después de {MAX_INTENTOS} intentos + 60s espera. Último: {e}") # Falla definitiva.

# ─── Queries ─────────────────────────────────────────────────────────────────

def build_query(area_name: str, tags_body: str) -> str:   # Construye el texto Overpass QL para un área administrativa.
    safe = area_name.replace('"', '\\"')               # Escapa comillas dobles del nombre del área.
    return f"""[out:json][timeout:{TIMEOUT_QUERY}];      # Define salida JSON y timeout de Overpass.
area["name"="{safe}"]["boundary"="administrative"]->.a; # Resuelve el área administrativa a un alias .a.
({tags_body});                                           # Ejecuta el bloque de tags sobre el área.
out center tags qt;""".strip()                          # Pide centro y tags en formato compacto.

def area_candidates(municipio: str, departamento: str) -> List[str]: # Genera variantes de nombre del área para mejorar matching.
    return list(dict.fromkeys([                           # Elimina duplicados preservando orden.
        municipio,                                        # Variante simple.
        f"{municipio}, {departamento}",                  # Variante municipio + departamento.
        f"Municipio de {municipio}",                     # Variante textual administrativa.
    ]))

# ─── Normalización ────────────────────────────────────────────────────────────

def calcular_score(nombre: str, familia: str) -> Tuple[int, bool]: # Calcula score Argos y aprobación.
    score = 0                                             # Inicializa score base.
    if familia in ("hardware", "building_materials"):    # Si la familia es muy relevante,
        score += 5                                        # suma 5 puntos.
    elif familia in ("trade_supplies", "doityourself"): # Si la familia es medianamente relevante,
        score += 2                                        # suma 2 puntos.

    texto = (nombre or "").lower()                       # Normaliza el nombre a minúsculas.
    for p in PALABRAS_ALTA:                               # Recorre palabras de alto valor.
        if p in texto:                                    # Si la palabra aparece en el nombre,
            score += 2                                    # incrementa el score.

    return score, score >= ARGOS_THRESHOLD                # Devuelve score y aprobación booleana.

def normalizar_elemento(element: dict, municipio: str, departamento: str, familia: str, run_id: str) -> Optional[dict]: # Convierte un elemento OSM a estructura persistible.
    tags     = element.get("tags") or {}                  # Extrae tags del elemento.
    osm_type = element.get("type")                        # Extrae tipo OSM.
    osm_id   = element.get("id")                          # Extrae id OSM.
    if not osm_type or osm_id is None:                    # Si faltan identidad mínima,
        return None                                       # descarta el elemento.

    lat = element.get("lat") or (element.get("center") or {}).get("lat") # Obtiene latitud directa o del centro.
    lon = element.get("lon") or (element.get("center") or {}).get("lon") # Obtiene longitud directa o del centro.

    nombre   = tags.get("name") or tags.get("brand") or tags.get("operator") or "" # Determina el mejor nombre disponible.
    telefono = tags.get("phone") or tags.get("contact:phone") or tags.get("phone_1") or "" # Resuelve teléfono desde varios tags posibles.
    whatsapp = tags.get("contact:whatsapp") or ""       # Resuelve WhatsApp.
    email    = tags.get("email") or tags.get("contact:email") or "" # Resuelve email.
    website  = tags.get("website") or tags.get("contact:website") or tags.get("url") or "" # Resuelve web.
    calle    = tags.get("addr:street") or ""            # Obtiene calle.
    numero   = tags.get("addr:housenumber") or ""       # Obtiene número.
    direccion= f"{calle} {numero}".strip() or tags.get("addr:full") or "" # Compone dirección legible.

    score, aprobado = calcular_score(nombre, familia)     # Calcula score Argos.
    hash_id = hashlib.md5(f"overpass|{osm_type}|{osm_id}".encode()).hexdigest() # Genera hash único determinístico.

    return {                                              # Devuelve el payload normalizado completo.
        "hash_id":           hash_id,
        "run_id":            run_id,
        "nit":               None,
        "nombre":            nombre or None,
        "departamento":      departamento,
        "municipio":         municipio,
        "direccion":         direccion or None,
        "latitud":           float(lat) if lat is not None else None,
        "longitud":          float(lon) if lon is not None else None,
        "telefono":          telefono or None,
        "whatsapp":          whatsapp or None,
        "correo_electronico": email or None,
        "fecha_actualizacion": None,
        "fuente":            "openstreetmap",
        "score":             score,
        "aprobado_argos":    aprobado,
        "osm_type":          osm_type,
        "osm_id":            int(osm_id),
        "familia_osm":       familia,
        "shop_tag":          tags.get("shop") or None,
        "trade_tag":         tags.get("trade") or None,
        "brand":             tags.get("brand") or None,
        "operator_osm":      tags.get("operator") or None,
        "opening_hours":     tags.get("opening_hours") or None,
        "website":           website or None,
        "email_osm":         email or None,
        "instagram":         tags.get("contact:instagram") or tags.get("instagram") or None,
        "facebook":          tags.get("contact:facebook") or tags.get("facebook") or None,
        "twitter":           tags.get("contact:twitter") or tags.get("twitter") or None,
        "addr_street":       tags.get("addr:street") or None,
        "addr_number":       tags.get("addr:housenumber") or None,
        "addr_city":         tags.get("addr:city") or None,
        "addr_state":        tags.get("addr:state") or None,
        "addr_postcode":     tags.get("addr:postcode") or None,
        "description_osm":   tags.get("description") or None,
        "raw_response":      {                          # Conserva trazabilidad cruda del elemento.
            "osm_type": osm_type, "osm_id": osm_id,
            "lat": lat, "lon": lon,
            "familia": familia, "municipio": municipio, "departamento": departamento,
            "tags": tags,
        },
    }

# ─── JSONL helper ─────────────────────────────────────────────────────────────

def append_jsonl(filepath: Path, obj: dict):              # Agrega un objeto JSON serializado a un archivo JSONL.
    if not SAVE_OUTPUT_FILES:                             # Si el guardado está desactivado,
        return                                            # sale inmediatamente.
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True) # Asegura el directorio padre.
        with open(filepath, "a", encoding="utf-8") as f:  # Abre el archivo en modo append.
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n") # Escribe una línea JSON.
    except Exception as e:
        log.warning(f"[JSONL] Error: {e}")               # Registra el error sin detener la corrida.

# ─── Orquestador ─────────────────────────────────────────────────────────────

async def do_scrape(opciones: dict = None):              # Orquesta una corrida completa de scraping.
    if opciones is None:                                  # Si no se pasó configuración,
        opciones = {}                                     # usa un diccionario vacío.

    from municipios_colombia import get_municipios        # Importa el catálogo al momento de ejecución.
    municipios = opciones.get("municipios", get_municipios()) # Usa municipios custom o todos por defecto.

    run_id    = str(uuid.uuid4())                         # Genera identificador único de corrida.
    inicio_at = datetime.now(timezone.utc)                # Marca inicio en UTC.

    setup_logging()                                       # Inicializa logging.

    if SAVE_OUTPUT_FILES:                                 # Si el guardado está activo,
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)     # asegura la carpeta output.

    log.info("=" * 60)                                    # Imprime separador visual.
    log.info(f"OVERPASS SCRAPER — run_id: {run_id}")     # Loguea el identificador de la corrida.
    log.info(f"Inicio:            {inicio_at.isoformat()}") # Loguea hora de inicio.
    log.info(f"Municipios:        {len(municipios)}")    # Loguea cantidad de municipios.
    log.info(f"Familias OSM:      {len(FAMILIAS_OSM)}")  # Loguea cantidad de familias.
    log.info(f"Queries estimadas: {len(municipios) * len(FAMILIAS_OSM)}") # Loguea volumen estimado.
    log.info(f"Pausa entre queries: {PAUSE_ENTRE_QUERIES}s") # Loguea ritmo de ejecución.
    log.info("=" * 60)                                    # Cierra encabezado visual.

    init_db()                                             # Garantiza estructura de base de datos.
    procesados = cargar_hashes_procesados()               # Carga deduplicación histórica.
    log.info(f"[BD] {len(procesados)} registros ya procesados") # Reporta tamaño del set.

    client     = OverpassClient()                         # Instancia cliente Overpass.
    jsonl_path = OUTPUT_DIR / f"overpass-{run_id}.jsonl" if SAVE_OUTPUT_FILES else None # Ruta condicional de JSONL.

    fallidos  = []                                        # Acumula queries fallidas.
    raw_acum  = []                                        # Acumula respuestas crudas agrupadas.

    metricas = {                                          # Inicializa estructura de métricas.
        "run_id":          run_id,
        "inicio":          inicio_at.isoformat(),
        "municipios":      len(municipios),
        "queries_ok":      0,
        "queries_err":     0,
        "elementos_total": 0,
        "insertados":      0,
        "duplicados":      0,
        "aprobados":       0,
    }

    total_jobs = len(municipios) * len(FAMILIAS_OSM)      # Calcula total de combinaciones municipio x familia.
    job_num    = 0                                         # Inicializa contador de progreso.

    for muni_info in municipios:                           # Itera por cada municipio.
        muni = muni_info["municipio"]                     # Extrae nombre del municipio.
        dept = muni_info["departamento"]                  # Extrae departamento.

        for familia_id, familia_meta in FAMILIAS_OSM.items(): # Itera por cada familia OSM.
            job_num += 1                                   # Incrementa contador de trabajo.
            es_regex = familia_meta.get("es_regex", False) # Detecta si la familia usa regex.
            log.info(f"[{job_num}/{total_jobs}] {muni} ({dept}) | {familia_id}") # Loguea progreso.

            resultado_ok  = False                          # Marca si alguna variante de área funcionó.
            area_usada    = None                           # Guardará el nombre del área exitosa.
            error_final   = None                           # Guardará el último error si todo falla.

            for area_name in area_candidates(muni, dept):  # Prueba las variantes de nombre del área.
                try:
                    ql = build_query(area_name, familia_meta["tags"]) # Construye Overpass QL.
                    data, endpoint_used = client.query(ql, es_regex=es_regex) # Ejecuta la consulta.
                    elementos = data.get("elements") or [] # Extrae elementos de la respuesta.

                    raw_acum.append({                       # Guarda respuesta cruda resumida.
                        "municipio":       muni,
                        "departamento":    dept,
                        "familia":         familia_id,
                        "area_usada":      area_name,
                        "cant_elementos":  len(elementos),
                        "endpoint":        endpoint_used,
                        "raw_response":    data,
                    })

                    metricas["queries_ok"]      += 1      # Suma query exitosa.
                    metricas["elementos_total"] += len(elementos) # Suma cantidad de elementos devueltos.
                    area_usada   = area_name                # Guarda área efectiva.
                    resultado_ok = True                    # Marca éxito.

                    for element in elementos:              # Recorre cada elemento OSM.
                        registro = normalizar_elemento(element, muni, dept, familia_id, run_id) # Lo normaliza.
                        if not registro:                   # Si no pudo normalizar,
                            continue                       # lo salta.
                        if registro["hash_id"] in procesados: # Si ya fue procesado antes,
                            metricas["duplicados"] += 1   # suma duplicado.
                            continue                       # y no inserta.
                        ok = insertar_lugar(run_id, registro) # Intenta persistirlo.
                        if ok:                             # Si insertó exitosamente,
                            procesados.add(registro["hash_id"]) # actualiza set en memoria.
                            metricas["insertados"] += 1   # incrementa insertados.
                            if registro["aprobado_argos"]: # Si supera el umbral Argos,
                                metricas["aprobados"] += 1 # incrementa aprobados.
                            append_jsonl(jsonl_path, {     # Guarda línea JSONL en tiempo real.
                                "tipo":          "lugar",
                                "run_id":        run_id,
                                "municipio":     muni,
                                "departamento":  dept,
                                "familia":       familia_id,
                                "nombre":        registro["nombre"],
                                "latitud":       registro["latitud"],
                                "longitud":      registro["longitud"],
                                "telefono":      registro["telefono"],
                                "score":         registro["score"],
                                "aprobado_argos":registro["aprobado_argos"],
                                "osm_type":      registro["osm_type"],
                                "osm_id":        registro["osm_id"],
                            })
                        else:                               # Si no insertó,
                            metricas["duplicados"] += 1    # lo cuenta como duplicado/no insertado.

                    break                                   # Sale del loop de áreas porque ya hubo éxito.

                except Exception as e:                      # Si la variante de área falla,
                    error_final = str(e)                    # guarda el error.
                    log.warning(f"  [WARN] area='{area_name}' falló: {e}") # registra el warning.
                    continue                                # prueba la siguiente variante.

            if not resultado_ok:                            # Si ninguna variante de área funcionó,
                log.error(f"  [FALLIDO] {muni}/{dept}/{familia_id}") # registra fallo final.
                metricas["queries_err"] += 1              # incrementa errores.
                fallido = {                                 # construye payload de fallo.
                    "municipio":      muni,
                    "departamento":   dept,
                    "familia":        familia_id,
                    "descripcion":    familia_meta["descripcion"],
                    "error":          error_final,
                    "areas_probadas": area_candidates(muni, dept),
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                }
                fallidos.append(fallido)                   # lo agrega al acumulador de fallos.
                append_jsonl(jsonl_path, {"tipo": "fallido", "run_id": run_id, **fallido}) # lo serializa si aplica.

    fin_at     = datetime.now(timezone.utc)                # Marca fin de ejecución.
    duracion_s = int((fin_at - inicio_at).total_seconds()) # Calcula duración total en segundos.
    metricas["fin"]      = fin_at.isoformat()             # Guarda timestamp final.
    metricas["duracion"] = f"{duracion_s // 60}m {duracion_s % 60}s" # Guarda duración humana.
    metricas["fallidos"] = len(fallidos)                 # Guarda total de fallidos.

    if SAVE_OUTPUT_FILES:                                  # Si el guardado está habilitado,
        (OUTPUT_DIR / f"overpass-fallidos-{run_id}.json").write_text( # escribe JSON de fallidos.
            json.dumps({
                "run_id": run_id,
                "total_fallidos": len(fallidos),
                "generado": fin_at.isoformat(),
                "nota": "Estas queries no obtuvieron respuesta de Overpass. Pueden reintentarse en otra corrida.",
                "fallidos": fallidos,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        log.info(f"[JSON] Guardado: output/overpass-fallidos-{run_id}.json ({len(fallidos)} queries fallidas)") # Loguea archivo de fallidos.

        (OUTPUT_DIR / f"overpass-resumen-{run_id}.json").write_text( # escribe resumen de métricas.
            json.dumps(metricas, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        log.info(f"[JSON] Guardado: output/overpass-resumen-{run_id}.json") # Loguea resumen.
    else:
        log.info("[JSON] SAVE_OUTPUT_FILES=false → no se guardaron archivos output/") # Informa desactivación de salida a disco.

    log.info("=" * 60)                                     # Separador de cierre.
    log.info("COMPLETADO")                                 # Marca finalización.
    for k, v in metricas.items():                           # Recorre todas las métricas.
        log.info(f"  {k:<28} {v}")                         # Las imprime ordenadamente.
    if SAVE_OUTPUT_FILES:                                   # Si hay JSONL,
        log.info(f"  JSONL (tiempo real):         output/overpass-{run_id}.jsonl") # informa la ruta.
    else:
        log.info("  JSONL (tiempo real):         deshabilitado por SAVE_OUTPUT_FILES=false") # informa que está apagado.

    log.info("=" * 60)                                     # Cierra el bloque final de log.

    return metricas                                         # Devuelve resumen completo para API o CLI.

# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":                                 # Punto de entrada cuando se ejecuta como script.
    import asyncio                                          # Import local para ejecutar la coroutine principal.

    parser = argparse.ArgumentParser(description="Overpass scraper para proyecto Argos") # Crea parser CLI.
    parser.add_argument("--test",  action="store_true", help="Solo 5 municipios de prueba") # Flag para prueba rápida.
    parser.add_argument("--dept",  type=str,            help="Solo un departamento específico") # Filtro por departamento.
    parser.add_argument("--limit", type=int,            help="Límite de municipios") # Límite numérico.
    args = parser.parse_args()                              # Parsea argumentos.

    from municipios_colombia import get_municipios         # Importa el catálogo.
    municipios = get_municipios()                          # Carga lista por defecto.

    if args.test:                                          # Si se solicitó modo prueba,
        municipios = [                                     # reemplaza la lista por un subconjunto fijo.
            {"departamento": "Antioquia",       "municipio": "Medellín"},
            {"departamento": "Cundinamarca",     "municipio": "Bogotá"},
            {"departamento": "Valle del Cauca",  "municipio": "Cali"},
            {"departamento": "Atlántico",        "municipio": "Barranquilla"},
            {"departamento": "Santander",        "municipio": "Bucaramanga"},
        ]
    elif args.dept:                                        # Si se pidió un departamento,
        municipios = [m for m in municipios if m["departamento"].lower() == args.dept.lower()] # filtra por coincidencia case-insensitive.
    elif args.limit:                                       # Si se pidió límite,
        municipios = municipios[:args.limit]               # recorta la lista.

    asyncio.run(do_scrape({"municipios": municipios}))    # Ejecuta la corrida asíncrona principal.
```

---

## 5) `api_runner.py` — documentación técnica exhaustiva

### Propósito del archivo

`api_runner.py` convierte el scraper en un servicio HTTP integrable con `n8n`, exponiendo endpoints de disparo, consulta de estado y callback de prueba.

### Versión comentada

```python
"""                                                         # Abre docstring del módulo.
api_runner.py — Endpoint HTTP para que n8n dispare el scraper Overpass  # Describe el propósito del servicio.
Puerto: 8007                                                # Documenta el puerto por defecto.
                                                             # Línea de separación visual.
Endpoints:                                                  # Enumera rutas públicas.
  GET  /health                                              # Healthcheck.
  POST /scrape/overpass                                     # Corrida completa.
  POST /scrape/overpass/prueba                              # Corrida de prueba.
  POST /scrape/overpass/depto                               # Corrida filtrada por departamento.
  GET  /status                                              # Estado actual.
  GET  /resultado                                           # Resultado acumulado.
  POST /test/callback                                       # Prueba de callback.
  GET  /endpoints                                           # Descubrimiento de rutas.
"""                                                         # Cierra docstring.

from fastapi import FastAPI, Request                         # Importa FastAPI y Request.
from fastapi.responses import JSONResponse                   # Importa respuesta JSON personalizada.
import asyncio                                               # Permite crear tareas en background.
import uvicorn                                               # Permite levantar el servidor ASGI.
import uuid                                                  # Genera run_id para corridas API.
import os                                                    # Lee variables de entorno.
from datetime import datetime, timedelta                     # Maneja tiempos y defaults sintéticos.
import httpx                                                 # Cliente HTTP asíncrono para callbacks.

app = FastAPI(title="Argos Scraper — Overpass API")         # Crea la aplicación FastAPI.

PORT = int(os.getenv("PORT", "8007"))                      # Lee puerto desde entorno con fallback 8007.
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")              # Lee URL de callback hacia n8n.

estado = {                                                   # Estado global en memoria del proceso.
    "scraping_en_curso": False,                            # Indica si hay una corrida activa.
    "run_id": None,                                        # Guarda el identificador de la corrida.
    "inicio": None,                                        # Guarda hora de inicio.
    "fin": None,                                           # Guarda hora de fin.
    "duracion": None,                                      # Guarda duración humana.
    "ultimo_status": "sin_correr",                       # Estado semántico del último proceso.
    "ultimo_error": None,                                  # Último error capturado.
    "metricas": None,                                      # Métricas devueltas por main.py.
    "tipo_ejecucion": None,                                # Tipo de corrida: producción, prueba, departamento.
    "opciones": None,                                      # Payload de opciones usado para la corrida.
}

MUNICIPIOS_PRUEBA = [                                        # Subconjunto fijo de prueba para endpoint de smoke test.
    {"departamento": "Antioquia", "municipio": "Medellín"},
]


def calcular_duracion(inicio_iso: str | None, fin_iso: str | None): # Calcula duración legible desde dos ISO strings.
    if not inicio_iso or not fin_iso:                         # Si falta alguno de los extremos,
        return None                                           # no puede calcular duración.
    try:
        inicio = datetime.fromisoformat(inicio_iso)           # Convierte inicio a datetime.
        fin = datetime.fromisoformat(fin_iso)                 # Convierte fin a datetime.
        duracion_s = max(0, round((fin - inicio).total_seconds())) # Calcula diferencia en segundos.
        return f"{duracion_s // 60}m {duracion_s % 60}s"      # La retorna en formato humano.
    except Exception:
        return None                                           # Fallback silencioso si el parseo falla.


async def enviar_callback(payload: dict, headers: dict | None = None): # Envía un POST a n8n con el payload final.
    if not N8N_WEBHOOK_URL:                                   # Si la URL no está definida,
        raise ValueError("N8N_WEBHOOK_URL no está configurado") # falla explícitamente.

    async with httpx.AsyncClient(timeout=15.0) as client:     # Crea cliente HTTP asíncrono con timeout.
        response = await client.post(                         # Ejecuta el POST.
            N8N_WEBHOOK_URL,
            json=payload,                                     # Envía payload como JSON.
            headers={                                         # Construye headers.
                "Content-Type": "application/json",         # Fuerza content-type JSON.
                **(headers or {})                             # Mezcla headers extra si existen.
            }
        )
        response.raise_for_status()                           # Eleva error si n8n responde con fallo.


async def notificar_fin_run(payload: dict, headers: dict | None = None): # Wrapper tolerante a errores para callback.
    try:
        await enviar_callback(payload, headers)               # Intenta enviar callback real.
        print(f"[CALLBACK] Notificación enviada a n8n. evento={payload.get('evento')} run_id={payload.get('run_id')}") # Log simple.
    except Exception as e:
        print(f"[CALLBACK] Falló envío a n8n: {e}")          # No rompe el flujo si falla la notificación.


async def ejecutar_background(opciones: dict, tipo_ejecucion: str): # Ejecuta do_scrape en segundo plano y actualiza estado.
    global estado                                             # Declara uso de estado global.
    try:
        from main import do_scrape                            # Importa la lógica principal justo antes de usarla.

        metricas = await do_scrape(opciones)                 # Ejecuta la corrida.

        fin = datetime.now().isoformat()                     # Marca fin local ISO.
        duracion = None                                      # Inicializa duración.

        if isinstance(metricas, dict):                       # Si main devolvió dict válido,
            duracion = metricas.get("duracion")             # reutiliza la duración calculada por main.

        if not duracion:                                     # Si no vino duración,
            duracion = calcular_duracion(estado["inicio"], fin) # la recalcula localmente.

        estado.update({                                      # Actualiza estado global a éxito.
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": duracion,
            "ultimo_status": "ok",
            "ultimo_error": None,
            "metricas": metricas if isinstance(metricas, dict) else None,
        })

        run_id_callback = (                                  # Determina qué run_id usar en el callback final.
            metricas.get("run_id")
            if isinstance(metricas, dict) and metricas.get("run_id")
            else estado["run_id"]
        )

        print(f"\n[✓] Overpass completado. run_id: {run_id_callback}") # Log de finalización exitosa.

        await notificar_fin_run({                            # Envía callback de éxito.
            "evento": "overpass.finalizado",
            "status": "ok",
            "run_id": run_id_callback,
            "inicio": estado["inicio"],
            "fin": estado["fin"],
            "duracion": estado["duracion"],
            "metricas": estado["metricas"],
            "origen": "api_runner",
            "tipo_ejecucion": tipo_ejecucion
        })

    except Exception as e:                                   # Maneja errores de la corrida de background.
        fin = datetime.now().isoformat()                     # Marca fin aun en error.
        duracion = calcular_duracion(estado["inicio"], fin) # Calcula duración transcurrida.

        estado.update({                                      # Actualiza estado global a error.
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": duracion,
            "ultimo_status": "error",
            "ultimo_error": str(e),
        })

        print(f"\n[✗] Error Overpass: {e}")                 # Log de error.

        await notificar_fin_run({                            # Envía callback de error.
            "evento": "overpass.finalizado",
            "status": "error",
            "run_id": estado["run_id"],
            "inicio": estado["inicio"],
            "fin": estado["fin"],
            "duracion": estado["duracion"],
            "error": str(e),
            "origen": "api_runner",
            "tipo_ejecucion": tipo_ejecucion
        })


def iniciar(opciones: dict, tipo_ejecucion: str) -> dict:    # Inicializa una nueva corrida API.
    run_id = str(uuid.uuid4())                               # Genera identificador único.
    inicio = datetime.now().isoformat()                      # Marca hora de inicio.

    estado.update({                                          # Guarda estado inicial de ejecución.
        "scraping_en_curso": True,
        "run_id": run_id,
        "inicio": inicio,
        "fin": None,
        "duracion": None,
        "ultimo_status": "corriendo",
        "ultimo_error": None,
        "metricas": None,
        "tipo_ejecucion": tipo_ejecucion,
        "opciones": opciones,
    })

    asyncio.create_task(ejecutar_background(opciones, tipo_ejecucion)) # Lanza la corrida sin bloquear la respuesta HTTP.

    return {                                                  # Devuelve acuse de inicio inmediato.
        "status": "iniciado",
        "run_id": run_id,
        "inicio": inicio,
        "mensaje": "Consulta GET /status para ver el progreso.",
        "webhook_n8n": N8N_WEBHOOK_URL,
        "tipo_ejecucion": tipo_ejecucion,
    }


@app.get("/health")                                         # Declara endpoint GET /health.
def health():                                                # Función del healthcheck.
    return {"status": "ok", "code": "200"}              # Devuelve respuesta mínima de vida.


@app.get("/status")                                         # Declara endpoint de estado.
def status():                                                # Devuelve foto resumida del estado global.
    return {
        "status": estado["ultimo_status"],
        "en_curso": estado["scraping_en_curso"],
        "run_id": estado["run_id"],
        "inicio": estado["inicio"],
        "fin": estado["fin"],
        "duracion": estado["duracion"],
        "error": estado["ultimo_error"],
        "metricas": estado["metricas"],
        "tipo_ejecucion": estado["tipo_ejecucion"],
    }


@app.post("/scrape/overpass")                               # Declara endpoint de corrida completa.
async def run_completo():                                    # Lanza scraping de producción.
    if estado["scraping_en_curso"]:                          # Si ya hay una corrida activa,
        return JSONResponse(                                 # devuelve conflicto 409.
            status_code=409,
            content={"status": "ocupado", "run_id": estado["run_id"]}
        )

    from municipios_colombia import get_municipios           # Importa catálogo.
    return iniciar({"municipios": get_municipios()}, "produccion") # Arranca corrida completa.


@app.post("/scrape/overpass/prueba")                        # Declara endpoint de corrida de prueba.
async def run_prueba():                                      # Lanza scraping pequeño.
    if estado["scraping_en_curso"]:
        return JSONResponse(
            status_code=409,
            content={"status": "ocupado", "run_id": estado["run_id"]}
        )

    return iniciar({"municipios": MUNICIPIOS_PRUEBA}, "prueba") # Arranca corrida sobre subconjunto fijo.


@app.post("/scrape/overpass/depto")                         # Declara endpoint de corrida por departamento.
async def run_departamento(body: dict):                      # Recibe body JSON con el nombre del departamento.
    if estado["scraping_en_curso"]:
        return JSONResponse(
            status_code=409,
            content={"status": "ocupado", "run_id": estado["run_id"]}
        )

    dept = body.get("departamento")                         # Lee campo departamento del request.
    if not dept:                                             # Si falta,
        return JSONResponse(                                 # responde error 400.
            status_code=400,
            content={"error": "Falta el campo 'departamento'"}
        )

    from municipios_colombia import get_municipios           # Importa catálogo completo.
    municipios = [m for m in get_municipios() if m["departamento"].lower() == dept.lower()] # Filtra por departamento.

    if not municipios:                                       # Si no hubo coincidencias,
        return JSONResponse(                                 # responde 404.
            status_code=404,
            content={"error": f"No se encontraron municipios para '{dept}'"}
        )

    return iniciar({"municipios": municipios}, "departamento") # Arranca corrida filtrada.


@app.get("/resultado")                                      # Declara endpoint de resultado.
def resultado():                                             # Devuelve resumen del último proceso conocido.
    return {
        "status": estado["ultimo_status"],
        "run_id": estado["run_id"],
        "inicio": estado["inicio"],
        "fin": estado["fin"],
        "duracion": estado["duracion"],
        "error": estado["ultimo_error"],
        "en_curso": estado["scraping_en_curso"],
        "metricas": estado["metricas"],
        "tipo_ejecucion": estado["tipo_ejecucion"],
    }


@app.post("/test/callback")                                 # Declara endpoint de prueba del webhook a n8n.
async def test_callback(request: Request):                   # Recibe opcionalmente un body JSON personalizable.
    try:
        body = await request.json()                          # Intenta parsear el JSON recibido.
    except Exception:
        body = {}                                            # Si falla, usa body vacío.

    try:
        now = datetime.now()                                 # Toma la hora actual.
        inicio_default = (now - timedelta(seconds=65)).isoformat() # Genera un inicio sintético 65s antes.
        fin_default = now.isoformat()                        # Genera fin sintético actual.

        payload = {                                          # Construye payload de prueba.
            "evento": "overpass.finalizado",
            "status": body.get("status", "ok"),
            "run_id": body.get("run_id", "test-run-001"),
            "inicio": body.get("inicio", inicio_default),
            "fin": body.get("fin", fin_default),
            "duracion": body.get("duracion", "1m 5s"),
            "metricas": body.get("metricas", {
                "run_id": body.get("run_id", "test-run-001"),
                "inicio": body.get("inicio", inicio_default),
                "fin": body.get("fin", fin_default),
                "duracion": body.get("duracion", "1m 5s"),
                "municipios": 5,
                "queries_ok": 10,
                "queries_err": 2,
                "elementos_total": 40,
                "insertados": 20,
                "duplicados": 5,
                "aprobados": 12,
                "fallidos": 2
            }),
            "origen": "api_runner",
            "tipo_ejecucion": body.get("tipo_ejecucion", "prueba_callback")
        }

        if payload["status"] == "error":                  # Si la prueba se quiere simular como error,
            payload.pop("metricas", None)                  # elimina métricas,
            payload["error"] = body.get("error", "Error de prueba enviado manualmente") # y agrega mensaje de error.

        await enviar_callback(payload)                      # Envía el callback sintético.

        return {                                            # Devuelve confirmación de prueba exitosa.
            "status": "ok",
            "mensaje": "Callback de prueba enviado a n8n correctamente",
            "webhook_n8n": N8N_WEBHOOK_URL,
            "payload_enviado": payload
        }

    except Exception as e:
        print(f"[TEST_CALLBACK] Falló envío de prueba a n8n: {e}") # Registra error de prueba.
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "mensaje": "No se pudo enviar el callback de prueba a n8n",
                "error": str(e)
            }
        )


@app.get("/endpoints")                                      # Declara endpoint que lista las rutas registradas.
def endpoints():                                             # Recorre el router y expone sus rutas.
    rutas = []                                               # Inicializa lista acumuladora.
    for route in app.routes:                                 # Itera sobre todas las rutas conocidas.
        methods = getattr(route, "methods", None)           # Lee métodos si existen.
        path = getattr(route, "path", None)                 # Lee path si existe.

        if path and methods:                                 # Si el objeto de ruta tiene path y métodos,
            rutas.append({                                   # agrega una representación serializable.
                "path": path,
                "methods": sorted([m for m in methods if m not in {"HEAD", "OPTIONS"}]) # Limpia métodos automáticos.
            })

    return rutas                                             # Devuelve la lista de endpoints.


if __name__ == "__main__":                                  # Punto de entrada local del servicio.
    print(f"🚀 Overpass API en http://localhost:{PORT}")     # Informa URL local.
    print(f"   n8n: http://host.docker.internal:{PORT}")     # Informa referencia típica desde Docker.
    print(f"   webhook n8n: {N8N_WEBHOOK_URL}")              # Informa webhook configurado.
    print("   POST /scrape/overpass")                       # Lista endpoints útiles.
    print("   POST /scrape/overpass/prueba")
    print("   POST /scrape/overpass/depto")
    print("   GET  /status")
    print("   GET  /resultado")
    print("   GET  /health")
    print("   POST /test/callback")
    print("   GET  /endpoints\n")

    uvicorn.run(app, host="0.0.0.0", port=PORT)             # Levanta el servidor en todas las interfaces.
```

---

## 6) `dockerfile` — documentación disponible

### Estado de inspección

El archivo fue reportado como cargado en la sesión, pero su contenido no estuvo recuperable mediante las herramientas accesibles del entorno de análisis. Por fidelidad técnica, no se inventa su contenido.

### Rol esperado del archivo

Un `dockerfile` en este proyecto previsiblemente cumple estas funciones:

1. seleccionar imagen base de Python,
2. copiar el código fuente,
3. instalar dependencias desde `requirements.txt`,
4. exponer el puerto del servicio,
5. ejecutar `api_runner.py` o equivalente.

### Plantilla conceptual esperable

```dockerfile
# Imagen base de Python                 # Selecciona el runtime.
# WORKDIR                               # Define directorio de trabajo.
# COPY requirements.txt                 # Copia dependencias.
# RUN pip install -r requirements.txt   # Instala librerías.
# COPY . .                              # Copia el proyecto.
# EXPOSE 8007                           # Expone puerto del servicio.
# CMD [...]                             # Arranca la API.
```

> En una siguiente iteración conviene recuperar el contenido exacto del archivo para documentarlo sin aproximaciones.

---

## Cierre técnico

Este repositorio implementa una solución de scraping georreferenciado con una separación razonable entre:

- catálogo geográfico (`municipios_colombia.py`),
- núcleo de negocio (`main.py`),
- orquestación HTTP (`api_runner.py`),
- configuración (`.env`),
- dependencias (`requirements.txt`).

La lógica central está bien enfocada en tres prioridades: **resiliencia frente a Overpass**, **normalización de datos**, y **persistencia deduplicada en PostgreSQL**. La principal oportunidad de mejora está en modularización, pruebas, manejo de estado y endurecimiento para producción.

