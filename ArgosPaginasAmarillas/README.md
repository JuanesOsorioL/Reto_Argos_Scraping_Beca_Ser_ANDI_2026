# README Maestro — Scraper de Páginas Amarillas para Argos

## Índice
- [1. Resumen ejecutivo](#1-resumen-ejecutivo)
- [2. Objetivo del sistema](#2-objetivo-del-sistema)
- [3. Arquitectura general](#3-arquitectura-general)
- [4. Flujo operativo](#4-flujo-operativo)
- [5. Mapa de dependencias](#5-mapa-de-dependencias)
- [6. Análisis por archivo](#6-análisis-por-archivo)
- [7. Modelo de datos](#7-modelo-de-datos)
- [8. Lógica crítica](#8-lógica-crítica)
- [9. Documentación línea por línea de cada archivo](#9-documentación-línea-por-línea-de-cada-archivo)
- [10. Ejecución del proyecto](#10-ejecución-del-proyecto)
- [11. Riesgos técnicos detectados](#11-riesgos-técnicos-detectados)
- [12. Recomendaciones de clean code](#12-recomendaciones-de-clean-code)
- [13. Prioridad de correcciones](#13-prioridad-de-correcciones)

---

## 1. Resumen ejecutivo
Este proyecto implementa un scraper orientado a capturar negocios desde **Páginas Amarillas Colombia**, filtrarlos según criterios de relevancia comercial para **Argos**, normalizarlos, persistirlos en **PostgreSQL** y exponer la ejecución mediante una **API FastAPI** preparada para integrarse con **n8n**.

El sistema tiene una intención clara y bien segmentada:
- **Extracción** desde listados y páginas de detalle.
- **Clasificación** por score de relevancia.
- **Normalización** de teléfonos, WhatsApp, coordenadas y categorías.
- **Persistencia** en PostgreSQL con deduplicación por hash.
- **Orquestación externa** mediante endpoints HTTP.

---

## 2. Objetivo del sistema
Construir una base de datos de potenciales clientes o puntos de venta relacionados con:
- ferreterías,
- depósitos de materiales,
- concretos,
- morteros,
- agregados,
- prefabricados,
- ladrilleras,
- distribuidores de cemento.

El resultado final está diseñado para alimentar procesos internos de Argos y/o flujos automatizados por n8n.

---

## 3. Arquitectura general

```text
┌──────────────────────────────┐
│          FastAPI             │
│        api_runner.py         │
└──────────────┬───────────────┘
               │ dispara
               ▼
┌──────────────────────────────┐
│           main.py            │
│ Orquestador principal scrape │
└───────┬───────────┬──────────┘
        │           │
        │           ├───────────────────────────────┐
        │                                           │
        ▼                                           ▼
┌──────────────────────┐                  ┌──────────────────────┐
│      scraper.py      │                  │   filter_engine.py   │
│ extrae URLs y detalle│                  │ score de relevancia  │
└──────────┬───────────┘                  └──────────┬───────────┘
           │                                         │
           ▼                                         ▼
┌──────────────────────┐                  ┌──────────────────────┐
│    normalizer.py     │                  │        db.py         │
│ limpia y estandariza │                  │ persistencia PG      │
└──────────┬───────────┘                  └──────────┬───────────┘
           │                                         │
           └──────────────────────┬──────────────────┘
                                  ▼
                     ┌──────────────────────────┐
                     │ PostgreSQL / esquema raw │
                     └──────────────────────────┘
```

---

## 4. Flujo operativo

### 4.1 Inicio
`main.py` inicializa la base de datos y carga una caché de URLs ya procesadas.

### 4.2 Generación del contexto de scraping
Para cada ciudad y cada keyword configurada, se crea un contexto nuevo de Playwright con un user-agent fijo.

### 4.3 Extracción del listado
`scraper.py -> obtener_urls_de_listado()` navega a una URL de listados y extrae todos los enlaces de detalle con patrón `/empresas/`.

### 4.4 Extracción profunda del detalle
`scraper.py -> extraer_detalle_negocio()` abre cada URL detalle y lee el objeto `__NEXT_DATA__` generado por Next.js para evitar scraping visual frágil.

### 4.5 Filtrado por relevancia
`filter_engine.py -> evaluar_cliente_argos()` calcula un score por coincidencia de palabras clave positivas y negativas.

### 4.6 Normalización
`normalizer.py` estandariza:
- teléfono principal y secundarios,
- WhatsApp,
- coordenadas,
- categoría legible,
- hash único por URL + sucursal.

### 4.7 Persistencia
`db.py -> insertar_negocio()` inserta el registro en PostgreSQL con `ON CONFLICT (hash_id) DO NOTHING`.

### 4.8 Respaldo local opcional
Si `SAVE_JSON_BACKUP=true`, se escribe un JSONL local.

### 4.9 Orquestación remota
`api_runner.py` permite disparar el scraper por HTTP y notificar el cierre a n8n.

---

## 5. Mapa de dependencias

```text
main.py
 ├── import config
 ├── from scraper import obtener_urls_de_listado, extraer_detalle_negocio
 ├── from filter_engine import evaluar_cliente_argos
 ├── from normalizer import normalizar_telefono, normalizar_whatsapp,
 │                         normalizar_coordenadas, normalizar_categoria,
 │                         generar_hash
 └── from db import init_db, cargar_urls_procesadas, insertar_negocio

scraper.py
 └── depende de Playwright y del DOM/JSON __NEXT_DATA__ del sitio objetivo

db.py
 └── from config import DB_CONFIG

data_exporter.py
 ├── from config import EXCEL_OUTPUT_FILE
 └── from db import get_connection

api_runner.py
 ├── from main import main as do_scrape
 ├── usa FastAPI
 ├── usa httpx
 └── usa dotenv/os para webhook y puerto
```

---

## 6. Análisis por archivo

| Archivo | Rol técnico | Tipo | Observaciones |
|---|---|---|---|
| `main.py` | Orquestador principal del scraping | Núcleo | Recorre ciudades/keywords, abre páginas, clasifica, normaliza e inserta |
| `scraper.py` | Extracción de URLs y detalle | Núcleo | Usa `__NEXT_DATA__`, estrategia robusta frente a HTML cambiante |
| `filter_engine.py` | Motor de scoring | Negocio | Determina aprobación para Argos con score >= 2 |
| `normalizer.py` | Estandarización | Utilitario | Limpia teléfonos, WhatsApp, coordenadas, categorías, hash |
| `db.py` | Persistencia PostgreSQL | Infraestructura | Crea esquema/tabla, carga caché, inserta con deduplicación |
| `config.py` | Configuración | Infraestructura | Contiene ciudades, keywords, variables de entorno y toggles |
| `Api_runner.py` | Exposición HTTP del proceso | Integración | Endpoint para n8n, health, status, callback |
| `data_exporter.py` | Exportación a Excel | Utilitario | Conceptualmente útil pero desalineado con el esquema actual |
| `dump_script.py` | Diagnóstico | Soporte | Prueba puntual para volcar `__NEXT_DATA__` |
| `print_json.py` | Diagnóstico | Soporte | Reduce el JSON capturado a campos relevantes |
| `quick_test.py` | Test rápido del scraper | Soporte | Prueba extracción y scoring sobre pocas URLs |
| `test_pl.py` | Dump HTML | Soporte | Guarda HTML del listado para depuración visual |
| `requirements.txt` | Dependencias | Infraestructura | Lista dependencias del proyecto |
| `.env` | Variables runtime | Infraestructura | Controla salida, headless, concurrencia, webhook |

---

## 7. Modelo de datos

### Tabla objetivo
`raw.paginas_amarillas_ferreterias`

### Columnas funcionales
- **Identidad y trazabilidad**: `id`, `hash_id`, `run_id`, `fecha_extraccion`
- **Campos objetivo Argos**: `nit`, `nombre`, `departamento`, `municipio`, `direccion`, `latitud`, `longitud`, `telefono`, `whatsapp`, `correo_electronico`, `fecha_actualizacion`, `fuente`
- **Calidad y clasificación**: `sucursal_tipo`, `telefonos_adicionales`, `descripcion`, `categoria_busqueda`, `keyword_busqueda`, `url`, `score`, `aprobado_argos`

### Estrategia de deduplicación
El sistema no deduplica por nombre, teléfono o dirección. La unicidad se garantiza mediante:

```text
hash_id = md5(url + "||" + sucursal_tipo)
```

Esto permite que una misma empresa con múltiples sucursales se conserve como registros distintos.

---

## 8. Lógica crítica

### 8.1 Scoring de relevancia
- Coincidencias de alta prioridad: **+3**
- Coincidencias de prioridad media: **+2**
- Coincidencias de prioridad baja: **+1**
- Coincidencias descalificadoras: **-3**
- Aprobación final: `score >= 2`

### 8.2 Extracción desde `__NEXT_DATA__`
La decisión más sólida del proyecto es leer directamente el JSON hidratado por Next.js. Esto reduce dependencia del DOM renderizado y mejora la resiliencia ante cambios menores de markup.

### 8.3 Filtrado de sucursales virtuales
Se descartan direcciones que comienzan por `Atiende en`, ya que representan cobertura comercial y no una sede física útil.

### 8.4 Caché por URL ya procesada
Antes de abrir una ficha, `main.py` verifica si la URL ya fue persistida. Esto evita trabajo repetido entre corridas.

### 8.5 Arquitectura de disparo remoto
La API no bloquea al cliente al iniciar scraping. Devuelve inmediatamente y deja la ejecución en una task asíncrona.

---

---

## 9. Documentación línea por línea de cada archivo

---

# 9.1 `db.py`

## Función del archivo
Gestiona la conexión a PostgreSQL, la creación de esquema/tabla y la inserción de negocios.

```python
"""
db.py — PostgreSQL para scraper Páginas Amarillas
Tabla destino: raw.paginas_amarillas_ferreterias

Columnas requeridas por Argos:
  nit, nombre, departamento, municipio, direccion,
  latitud, longitud, telefono, whatsapp, correo_electronico,
  fecha_actualizacion, fuente

Columnas adicionales de trazabilidad y calidad:
  id, run_id, fecha_extraccion, sucursal_tipo,
  telefonos_adicionales, descripcion, categoria_busqueda,
  keyword_busqueda, url, score, aprobado_argos, hash_id
"""
# Importa el driver de PostgreSQL.
import psycopg2
# Importa la configuración de conexión desde config.py.
from config import DB_CONFIG

# Define una función simple para obtener una conexión a PostgreSQL.
def get_connection():
    # Abre y retorna la conexión usando el diccionario DB_CONFIG.
    return psycopg2.connect(**DB_CONFIG)

# Define la función que crea el esquema y la tabla objetivo si no existen.
def init_db():
    """Crea el esquema raw y la tabla si no existen."""
    # Declara el bloque DDL completo como string SQL multilínea.
    ddl = """
    CREATE SCHEMA IF NOT EXISTS raw;

    CREATE TABLE IF NOT EXISTS raw.paginas_amarillas_ferreterias (

        -- ── Identidad ────────────────────────────────────────────────────
        id                    SERIAL PRIMARY KEY,
        hash_id               TEXT UNIQUE,
        run_id                UUID NOT NULL,

        -- ── Columnas requeridas por Argos ────────────────────────────────
        nit                   TEXT,
        nombre                TEXT,
        departamento          TEXT,
        municipio             TEXT,
        direccion             TEXT,
        latitud               DOUBLE PRECISION,
        longitud              DOUBLE PRECISION,
        telefono              TEXT,
        whatsapp              TEXT,
        correo_electronico    TEXT,
        fecha_actualizacion   TIMESTAMP,
        fuente                TEXT DEFAULT 'paginas_amarillas',

        -- ── Columnas adicionales de calidad ──────────────────────────────
        sucursal_tipo         TEXT,
        telefonos_adicionales TEXT,
        descripcion           TEXT,
        categoria_busqueda    TEXT,
        keyword_busqueda      TEXT,
        url                   TEXT,
        score                 INTEGER,
        aprobado_argos        BOOLEAN,
        fecha_extraccion      TIMESTAMP NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_pa_municipio   ON raw.paginas_amarillas_ferreterias (municipio);
    CREATE INDEX IF NOT EXISTS idx_pa_departamento ON raw.paginas_amarillas_ferreterias (departamento);
    CREATE INDEX IF NOT EXISTS idx_pa_aprobado    ON raw.paginas_amarillas_ferreterias (aprobado_argos);
    CREATE INDEX IF NOT EXISTS idx_pa_run_id      ON raw.paginas_amarillas_ferreterias (run_id);
    CREATE INDEX IF NOT EXISTS idx_pa_nombre      ON raw.paginas_amarillas_ferreterias (nombre);
    CREATE INDEX IF NOT EXISTS idx_pa_nit         ON raw.paginas_amarillas_ferreterias (nit);
    """
    # Abre una conexión administrada automáticamente.
    with get_connection() as conn:
        # Abre un cursor SQL.
        with conn.cursor() as cur:
            # Ejecuta el DDL completo.
            cur.execute(ddl)
        # Confirma la transacción.
        conn.commit()
    # Imprime un mensaje operativo.
    print("[DB] Tabla raw.paginas_amarillas_ferreterias verificada.")

# Define una función que devuelve un set de URLs ya persistidas.
def cargar_urls_procesadas() -> set:
    """Carga URLs ya guardadas para usarlas como caché."""
    # Protege la lectura con manejo de excepciones.
    try:
        # Abre conexión a la base.
        with get_connection() as conn:
            # Abre cursor para consulta.
            with conn.cursor() as cur:
                # Pide todas las URLs no nulas.
                cur.execute("SELECT url FROM raw.paginas_amarillas_ferreterias WHERE url IS NOT NULL;")
                # Retorna un set para consultas rápidas por pertenencia.
                return {row[0] for row in cur.fetchall()}
    except Exception as e:
        # Informa el error sin detener el sistema.
        print(f"[DB] No se pudo cargar caché: {e}")
        # Fallback seguro.
        return set()

# Define la inserción del negocio normalizado.
def insertar_negocio(datos: dict) -> bool:
    """
    Inserta un registro. Si el hash_id ya existe lo ignora.
    Retorna True si insertó, False si era duplicado.
    """
    # SQL parametrizado para inserción con deduplicación por hash_id.
    sql = """
    INSERT INTO raw.paginas_amarillas_ferreterias (
        hash_id, run_id,
        nit, nombre, departamento, municipio, direccion,
        latitud, longitud,
        telefono, telefonos_adicionales, whatsapp, correo_electronico,
        fecha_actualizacion, fuente,
        sucursal_tipo, descripcion, categoria_busqueda, keyword_busqueda,
        url, score, aprobado_argos, fecha_extraccion
    ) VALUES (
        %(hash_id)s, %(run_id)s,
        %(nit)s, %(nombre)s, %(departamento)s, %(municipio)s, %(direccion)s,
        %(latitud)s, %(longitud)s,
        %(telefono)s, %(telefonos_adicionales)s, %(whatsapp)s, %(correo_electronico)s,
        %(fecha_actualizacion)s, %(fuente)s,
        %(sucursal_tipo)s, %(descripcion)s, %(categoria_busqueda)s, %(keyword_busqueda)s,
        %(url)s, %(score)s, %(aprobado_argos)s, %(fecha_extraccion)s
    )
    ON CONFLICT (hash_id) DO NOTHING;
    """
    # Intenta la inserción.
    try:
        # Abre conexión.
        with get_connection() as conn:
            # Abre cursor.
            with conn.cursor() as cur:
                # Ejecuta el insert con los parámetros del diccionario datos.
                cur.execute(sql, datos)
                # Guarda cuántas filas fueron afectadas.
                inserted = cur.rowcount
            # Confirma la operación.
            conn.commit()
        # Retorna True si insertó exactamente una fila.
        return inserted == 1
    except Exception as e:
        # Reporta el error asociado al negocio.
        print(f"[DB] Error insertando {datos.get('nombre','?')}: {e}")
        # Retorna False si falló.
        return False
```

---

# 9.2 `dump_script.py`

## Función del archivo
Script auxiliar para abrir una ficha puntual y extraer el `__NEXT_DATA__` a disco.

```python
# Importa asyncio para correr la función asíncrona principal.
import asyncio
# Importa json para serializar el JSON obtenido de la página.
import json
# Importa Playwright asíncrono.
from playwright.async_api import async_playwright

# Define la corrutina principal.
async def run():
    # Inicializa Playwright en un contexto seguro.
    async with async_playwright() as p:
        # Lanza el navegador Chromium.
        browser = await p.chromium.launch()
        # Abre una pestaña nueva.
        page = await browser.new_page()
        # Define una URL fija de ejemplo.
        url = "https://www.paginasamarillas.com.co/empresas/ferreteria-la-87-sas/medellin-34016075?ad=80641545"
        # Navega a la URL esperando el DOM inicial.
        await page.goto(url, wait_until="domcontentloaded")
        
        # Ejecuta JS para leer el script __NEXT_DATA__.
        next_data_content = await page.evaluate('''() => {
            const el = document.getElementById('__NEXT_DATA__');
            return el ? el.textContent : null;
        }''')
        
        # Si se encontró contenido JSON...
        if next_data_content:
            # Lo parsea.
            data = json.loads(next_data_content)
            # Abre un archivo de salida.
            with open("dump_next_data.json", "w", encoding="utf-8") as f:
                # Guarda el JSON formateado.
                json.dump(data, f, indent=2, ensure_ascii=False)
            # Informa éxito.
            print("[+] Se encontró __NEXT_DATA__ y se guardó en dump_next_data.json")
        else:
            # Informa ausencia del nodo esperado.
            print("[-] No se encontró __NEXT_DATA__")
            
        # Cierra el navegador.
        await browser.close()

# Punto de entrada estándar.
if __name__ == "__main__":
    # Ejecuta la corrutina.
    asyncio.run(run())
```

---

# 9.3 `filter_engine.py`

## Función del archivo
Define la lógica de scoring para aprobar o descartar negocios según afinidad con el catálogo de Argos.

```python
# Motor de puntuación para filtrar negocios relevantes para Argos.

# Lista de palabras de máxima relevancia comercial.
PRIORIDAD_ALTA = [
    "cemento", "concreto", "mortero", "agregado", "agregados",
    "obra gris", "prefabricado", "prefabricados", "bloquera", "bloques",
    "ladrillos", "ladrillera", "deposito de materiales", "depósito de materiales"
]

# Lista de palabras de relevancia media.
PRIORIDAD_MEDIA = [
    "ferreteria", "ferretería", "materiales", "construccion", "construcción",
    "deposito", "depósito", "hierro", "corralon", "corralón",
    "arena", "grava", "triturado", "distribuidor", "distribuidora"
]

# Lista de palabras de relevancia débil.
PRIORIDAD_BAJA = [
    "constructora", "acabados", "proveedor", "suministros", "estructuras"
]

# Lista de palabras descalificadoras.
KEYWORDS_MALAS = [
    "cerrajeria", "cerrajería",
    "pintura decorativa", "pinturas decorativas",
    "plomería residencial", "plomeria residencial",
    "mecanico", "mecánico", "taller automotriz",
    "restaurante", "comidas", "supermercado", "tienda de ropa"
]

# Define la función principal de evaluación.
def evaluar_cliente_argos(nombre: str, descripcion: str, keyword_busqueda: str = ""):
    """
    Calcula el score del negocio basado en el nombre, descripción y
    el keyword de búsqueda con el que fue encontrado.
    Retorna una tupla (aprobado: bool, score: int).
    """
    # Limpia la keyword y reemplaza guiones por espacios.
    keyword_limpio = keyword_busqueda.replace("-", " ").lower()
    # Concatena el texto a evaluar en una sola cadena homogénea.
    texto = f"{nombre} {descripcion} {keyword_limpio}".lower()
    # Inicializa el score acumulado.
    score = 0
    
    # Suma puntos por coincidencias de alta prioridad.
    for k in PRIORIDAD_ALTA:
        if k in texto:
            score += 3
            
    # Suma puntos por coincidencias de prioridad media.
    for k in PRIORIDAD_MEDIA:
        if k in texto:
            score += 2
            
    # Suma puntos por coincidencias de prioridad baja.
    for k in PRIORIDAD_BAJA:
        if k in texto:
            score += 1
            
    # Resta puntos por coincidencias negativas.
    for k in KEYWORDS_MALAS:
        if k in texto:
            score -= 3
            
    # Aprueba solo si supera el umbral mínimo.
    aprobado = score >= 2
    # Retorna el veredicto y el score.
    return aprobado, score
```

---

# 9.4 `main.py`

## Función del archivo
Es el punto de entrada principal del scraping batch. Coordina scraping, normalización, scoring y persistencia.

```python
"""
main.py — Scraper Páginas Amarillas para Argos
Columnas requeridas: nit, nombre, departamento, municipio, direccion,
latitud, longitud, telefono, whatsapp, correo_electronico,
fecha_actualizacion, fuente
"""

# Importa asyncio para concurrencia asíncrona.
import asyncio
# Importa json para respaldo local JSONL.
import json
# Importa os, aunque actualmente no se usa de forma efectiva en este archivo.
import os
# Importa random para pausas variables entre lotes.
import random
# Importa uuid para generar identificadores únicos por corrida.
import uuid
# Importa datetime y timezone para timestamps consistentes.
from datetime import datetime, timezone

# Importa Playwright asíncrono.
from playwright.async_api import async_playwright

# Importa la configuración central del proyecto.
import config
# Importa las funciones de scraping de listados y detalles.
from scraper import obtener_urls_de_listado, extraer_detalle_negocio
# Importa el motor de scoring.
from filter_engine import evaluar_cliente_argos
# Importa funciones de normalización.
from normalizer import (
    normalizar_telefono, normalizar_whatsapp,
    normalizar_coordenadas, normalizar_categoria, generar_hash
)
# Importa funciones de base de datos.
from db import init_db, cargar_urls_procesadas, insertar_negocio

# Define el respaldo local en formato JSONL.
def guardar_jsonl_local(datos: dict):
    """Respaldo local — convierte datetime a string antes de serializar."""
    # Convierte cualquier datetime a ISO 8601 para serializarlo sin error.
    datos_serializables = {
        k: v.isoformat() if hasattr(v, 'isoformat') else v
        for k, v in datos.items()
    }
    # Abre el archivo configurado en modo append.
    with open(config.OUTPUT_FILE, "a", encoding="utf-8") as f:
        # Escribe una línea JSON por registro.
        f.write(json.dumps(datos_serializables, ensure_ascii=False) + "\n")

# Define la corrutina principal del scraper.
async def main():
    # Verifica o crea la tabla de destino.
    init_db()

    # Carga URLs ya procesadas para caché.
    procesados = cargar_urls_procesadas()
    # Genera run_id único para la corrida actual.
    run_id = str(uuid.uuid4())
    # Marca la fecha de extracción global.
    fecha_extraccion = datetime.now(timezone.utc)

    # Imprime métricas básicas de arranque.
    print(f"[*] Caché BD: {len(procesados)} URLs ya procesadas.")
    print(f"[*] run_id:   {run_id}")
    print(f"[*] Inicio:   {fecha_extraccion.isoformat()}\n")

    # Abre Playwright.
    async with async_playwright() as p:
        # Lanza Chromium en modo headless configurable.
        browser = await p.chromium.launch(headless=config.HEADLESS)

        # Recorre ciudades configuradas.
        for ciudad in config.CIUDADES:
            # Recorre keywords configuradas.
            for keyword in config.KEYWORDS_BUSQUEDA:
                # Imprime cabecera operativa.
                print(f"\n{'='*50}")
                print(f"[*] {ciudad} → {keyword}")
                print(f"{'='*50}")

                # Crea un contexto independiente por combinación ciudad/keyword.
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    )
                )

                # Pestaña base de listado.
                page_listado = await context.new_page()
                # Inicializa paginación.
                pagina = 1
                # Guarda las URLs de la página previa para detectar repeticiones.
                urls_anteriores = []

                # Inicia el loop de paginación.
                while True:
                    # Informa la página actual.
                    print(f"  [>] Página {pagina}...")
                    # Extrae URLs del listado.
                    urls = await obtener_urls_de_listado(page_listado, ciudad, keyword, pagina)

                    # Si ya no hay URLs, corta la paginación.
                    if not urls:
                        print(f"  [!] Sin más páginas.")
                        break
                    # Si el sitio repite exactamente el mismo conjunto, evita loop infinito.
                    if urls == urls_anteriores:
                        print(f"  [!] Páginas Amarillas repite resultados. Avanzando.")
                        break

                    # Actualiza la referencia de URLs previas.
                    urls_anteriores = urls
                    # Imprime el total encontrado en la página.
                    print(f"  [v] {len(urls)} URLs en página {pagina}.")

                    # Procesa URLs por lotes según la concurrencia permitida.
                    for i in range(0, len(urls), config.CONCURRENCIA_PESTANAS):
                        # Recorta el sublote actual.
                        lote = urls[i:i + config.CONCURRENCIA_PESTANAS]
                        # Lista de tareas asíncronas.
                        tareas = []
                        # Lista para relacionar pestaña y URL.
                        pares_page_url = []

                        # Recorre cada URL del lote.
                        for url_detalle in lote:
                            # Si ya se había procesado antes, la salta.
                            if url_detalle in procesados:
                                print(f"      [-] Saltando: {url_detalle}")
                                continue
                            # Crea una pestaña nueva para el detalle.
                            nueva_pestana = await context.new_page()
                            # Guarda la correlación.
                            pares_page_url.append((nueva_pestana, url_detalle))
                            # Agrega la tarea de scraping del detalle.
                            tareas.append(extraer_detalle_negocio(nueva_pestana, url_detalle))

                        # Si no hay tareas, sigue al siguiente lote.
                        if not tareas:
                            continue

                        # Ejecuta todas las tareas en paralelo sin romper el lote por un fallo aislado.
                        resultados_lote = await asyncio.gather(*tareas, return_exceptions=True)

                        # Recorre resultados y sus pestañas asociadas.
                        for index, ((pestana, url_req), _) in enumerate(zip(pares_page_url, resultados_lote)):
                            # Cierra la pestaña usada.
                            await pestana.close()
                            # Toma el resultado real por índice.
                            res = resultados_lote[index]
                            # Si hubo error o no hubo datos, reporta y continúa.
                            if isinstance(res, Exception) or not res:
                                print(f"      [x] Error: {url_req}")
                                continue

                            # El scraper retorna una lista porque una empresa puede tener varias sucursales.
                            if isinstance(res, list):
                                # Recorre cada sucursal extraída.
                                for obj in res:
                                    # Descarta cualquier objeto sin nombre.
                                    if "nombre" not in obj:
                                        continue

                                    # Evalúa el score comercial del negocio.
                                    aprobado, score = evaluar_cliente_argos(
                                        obj["nombre"], obj.get("descripcion", ""), keyword
                                    )

                                    # Normaliza teléfonos principal y secundarios.
                                    telefono, telefonos_adicionales = normalizar_telefono(obj.get("telefono", ""))
                                    # Normaliza el WhatsApp.
                                    whatsapp = normalizar_whatsapp(obj.get("whatsapp", ""))
                                    # Normaliza latitud y longitud.
                                    lat, lon = normalizar_coordenadas(obj.get("latitud"), obj.get("longitud"))
                                    # Convierte la keyword a una categoría legible.
                                    categoria = normalizar_categoria(keyword)
                                    # Busca el departamento correspondiente a la ciudad.
                                    departamento = config.CIUDAD_DEPARTAMENTO.get(ciudad, "")
                                    # Obtiene el tipo de sucursal o usa Principal.
                                    sucursal = obj.get("sucursal_tipo", "Principal")
                                    # Genera el identificador hash lógico.
                                    hash_id = generar_hash(url_req, sucursal)
                                    # Marca la fecha de actualización puntual del registro.
                                    ahora = datetime.now(timezone.utc)

                                    # Construye el registro final listo para BD.
                                    registro = {
                                        "hash_id": hash_id,
                                        "run_id": run_id,
                                        "fecha_extraccion": fecha_extraccion,
                                        "nit": "",
                                        "nombre": obj["nombre"],
                                        "departamento": departamento,
                                        "municipio": ciudad,
                                        "direccion": obj.get("direccion", "").strip(),
                                        "latitud": lat,
                                        "longitud": lon,
                                        "telefono": telefono,
                                        "whatsapp": whatsapp,
                                        "correo_electronico": obj.get("email", ""),
                                        "fecha_actualizacion": ahora,
                                        "fuente": "paginas_amarillas",
                                        "sucursal_tipo": sucursal,
                                        "telefonos_adicionales": telefonos_adicionales,
                                        "descripcion": obj.get("descripcion", ""),
                                        "categoria_busqueda": categoria,
                                        "keyword_busqueda": keyword,
                                        "url": url_req,
                                        "score": score,
                                        "aprobado_argos": aprobado,
                                    }

                                    # Intenta insertar en base de datos.
                                    insertado = insertar_negocio(registro)
                                    
                                    # Si se insertó y está habilitado el backup local, se guarda también en JSONL.
                                    if insertado and config.SAVE_JSON_BACKUP:
                                        guardar_jsonl_local(registro)

                                    # Define el estado textual del registro.
                                    estado = "NUEVO" if insertado else "DUPLICADO"
                                    # Imprime resultado aprobado.
                                    if aprobado:
                                        print(f"      [+] {estado} | Score {score} | {obj['nombre']} | {ciudad}")
                                    else:
                                        # Imprime resultado descartado.
                                        print(f"      [~] {estado} | Score {score} | Descartado: {obj['nombre']}")

                                # Marca la URL como procesada al terminar sus sucursales.
                                procesados.add(url_req)

                        # Introduce espera aleatoria para no golpear el sitio en patrón fijo.
                        await asyncio.sleep(random.uniform(config.TIEMPO_ESPERA_MIN, config.TIEMPO_ESPERA_MAX))

                    # Avanza a la siguiente página.
                    pagina += 1

                # Cierra el contexto del navegador para esta combinación.
                await context.close()

        # Cierra el navegador completo al terminar.
        await browser.close()
        # Informa fin del proceso.
        print(f"\n[✓] Terminado. run_id: {run_id}")

# Punto de entrada del script.
if __name__ == "__main__":
    # Ejecuta la corrutina principal.
    asyncio.run(main())
```

---

# 9.5 `normalizer.py`

## Función del archivo
Centraliza la limpieza y estandarización de campos antes de persistirlos.

```python
"""
normalizer.py — Limpieza de campos antes de guardar en BD
Centraliza toda la normalización para que sea fácil ajustar después.
"""
# Importa expresiones regulares.
import re
# Importa hashlib para hashes determinísticos.
import hashlib

# Define la normalización de teléfonos.
def normalizar_telefono(telefono_raw: str) -> tuple:
    """
    Recibe un string con uno o más teléfonos separados por '/'.
    Retorna (telefono_principal, telefonos_adicionales).
    """
    # Si no hay dato de entrada, retorna vacíos.
    if not telefono_raw:
        return "", ""

    # Separa por slash y recorta espacios.
    partes = [p.strip() for p in telefono_raw.split("/")]
    # Lista de teléfonos limpios.
    limpios = []
    # Recorre cada fragmento.
    for parte in partes:
        # Conserva solo dígitos.
        numero = re.sub(r'[^\d]', '', parte)
        # Si no queda nada útil, lo salta.
        if not numero:
            continue
        # Si empieza por 57 y tiene longitud de internacional colombiana, agrega +.
        if numero.startswith("57") and len(numero) == 12:
            numero = f"+{numero}"
        # Si parece celular colombiano, agrega prefijo país.
        elif numero.startswith("3") and len(numero) == 10:
            numero = f"+57{numero}"
        # Si tiene 10 dígitos, asume formato nacional y agrega +57.
        elif len(numero) == 10:
            numero = f"+57{numero}"
        # Agrega el número normalizado a la lista.
        limpios.append(numero)

    # Si no se obtuvo ningún número válido, retorna vacíos.
    if not limpios:
        return "", ""

    # El primero se toma como principal.
    principal = limpios[0]
    # El resto se concatena como adicionales.
    adicionales = " / ".join(limpios[1:]) if len(limpios) > 1 else ""
    # Retorna ambos resultados.
    return principal, adicionales

# Define la normalización del WhatsApp.
def normalizar_whatsapp(wa_raw: str) -> str:
    """Convierte URL de WhatsApp a número limpio."""
    # Si no hay dato, retorna vacío.
    if not wa_raw:
        return ""
    # Si viene como wa.me, extrae el número.
    if wa_raw.startswith("https://wa.me/"):
        numero = wa_raw.replace("https://wa.me/", "").strip()
        return f"+{numero}" if not numero.startswith("+") else numero
    # Si ya es número o ya tiene +, lo devuelve igual.
    if wa_raw.startswith("+") or wa_raw.isdigit():
        return wa_raw
    # Si no coincide con reglas conocidas, conserva el valor original.
    return wa_raw

# Define la normalización de coordenadas.
def normalizar_coordenadas(lat_raw, lon_raw) -> tuple:
    """Convierte latitud y longitud a float."""
    # Intenta convertir a flotantes.
    try:
        # Convierte latitud o usa 0.0 si viene vacía.
        lat = float(lat_raw) if lat_raw else 0.0
        # Convierte longitud o usa 0.0 si viene vacía.
        lon = float(lon_raw) if lon_raw else 0.0
        # Retorna la tupla normalizada.
        return lat, lon
    except (ValueError, TypeError):
        # Fallback seguro si algo falla.
        return 0.0, 0.0

# Define la transformación de keyword a categoría legible.
def normalizar_categoria(categoria_raw: str) -> str:
    """Convierte keyword con guiones a texto legible."""
    # Si no existe valor, retorna vacío.
    if not categoria_raw:
        return ""
    # Reemplaza guiones por espacios.
    return categoria_raw.replace("-", " ").strip()

# Define la generación del hash lógico del registro.
def generar_hash(url: str, sucursal_tipo: str = "") -> str:
    """Genera hash único por URL + tipo de sucursal."""
    # Construye la clave base normalizada.
    clave = f"{url}||{sucursal_tipo}".lower().strip()
    # Retorna el md5 hexadecimal.
    return hashlib.md5(clave.encode("utf-8")).hexdigest()
```

---

# 9.6 `print_json.py`

## Función del archivo
Toma el dump JSON completo y produce una versión reducida con los campos más útiles para análisis.

```python
# Importa json para manipular archivos JSON.
import json

# Abre el dump completo del __NEXT_DATA__.
with open('dump_next_data.json', encoding='utf-8') as f:
    # Carga el contenido en memoria.
    d = json.load(f)
    
# Navega hasta el nodo de datos principal.
data = d['props']['pageProps']['data']

# Construye un subconjunto con campos relevantes.
result = {
    "allAddresses": data.get("allAddresses"),
    "allPhonesList": data.get("allPhonesList"),
    "contactMap": data.get("contactMap"),
    "emails": data.get("emails"),
    "infoEmpresa": data.get("infoEmpresa"),
    "services": data.get("services"),
    "slogan": data.get("slogan")
}

# Abre el archivo de salida resumido.
with open("printed.json", "w", encoding="utf-8") as out:
    # Guarda el resultado con indentación legible.
    json.dump(result, out, indent=2, ensure_ascii=False)
```

---

# 9.7 `quick_test.py`

## Función del archivo
Smoke test para validar rápidamente extracción de listado, detalle y scoring.

```python
# Importa asyncio.
import asyncio
# Importa json para imprimir objetos bonitos.
import json
# Importa Playwright asíncrono.
from playwright.async_api import async_playwright
# Importa funciones del scraper.
from scraper import obtener_urls_de_listado, extraer_detalle_negocio
# Importa el motor de scoring.
from filter_engine import evaluar_cliente_argos

# Define la corrutina de prueba.
async def run():
    # Inicializa Playwright.
    async with async_playwright() as p:
        # Lanza Chromium.
        browser = await p.chromium.launch()
        # Abre una pestaña.
        page = await browser.new_page()
        # Consulta la primera página de resultados para una ciudad y keyword específicas.
        urls = await obtener_urls_de_listado(page, "medellin", "materiales-para-construccion", 1)
        
        # Filtra solo URLs con patrón de detalle de empresa.
        validos = [u for u in urls if "/empresas/" in u]
        # Imprime cuántas URLs válidas se encontraron.
        print(f"[!] Se encontraron {len(validos)} URLs válidas en la página 1")
        
        # Toma únicamente las dos primeras para prueba rápida.
        for u in validos[:2]:
            # Extrae el detalle del negocio.
            det = await extraer_detalle_negocio(page, u)
            # Si hubo datos...
            if det:
                # Este bloque asume que det es diccionario, pero en realidad la función retorna lista.
                aprobado, score = evaluar_cliente_argos(det["nombre"], det["descripcion"])
                # Agrega score al objeto.
                det["score"] = score
                # Agrega bandera de aprobación.
                det["aprobado"] = aprobado
                # Imprime separador.
                print("\n====================")
                # Imprime el objeto en JSON legible.
                print(json.dumps(det, indent=2, ensure_ascii=False))
        # Cierra el navegador.
        await browser.close()

# Punto de entrada.
if __name__ == "__main__":
    # Ejecuta la prueba asíncrona.
    asyncio.run(run())
```

### Observación crítica
Este archivo tiene una inconsistencia real: `extraer_detalle_negocio()` retorna una **lista**, no un diccionario. Este test debe corregirse antes de usarse.

---

# 9.8 `requirements.txt`

## Función del archivo
Declara las dependencias Python del proyecto.

```txt
# Navegador automatizado para scraping dinámico.
playwright==1.58.0
# Librería de dataframes usada para exportación tabular.
pandas
# Motor Excel para lectura y escritura .xlsx.
openpyxl
# Driver PostgreSQL para Python.
psycopg2-binary
# Carga variables de entorno desde archivo .env.
python-dotenv
# Framework web para la API.
fastapi
# Servidor ASGI para ejecutar FastAPI.
uvicorn
# Cliente HTTP asíncrono para callbacks a n8n.
httpx
```

---

# 9.9 `scraper.py`

## Función del archivo
Contiene la lógica de scraping real del sitio: extracción de URLs desde el listado y extracción de detalle desde `__NEXT_DATA__`.

```python
# Importa asyncio aunque en este módulo no se usa directamente en las funciones actuales.
import asyncio
# Importa json para parsear el contenido de __NEXT_DATA__.
import json
# Importa la clase Page de Playwright para tipar las funciones.
from playwright.async_api import Page

# Define la extracción de URLs desde una página de listado.
async def obtener_urls_de_listado(page: Page, ciudad: str, keyword: str, pagina: int):
    """
    Navega al listado y extrae todas las URLs de los detalles.
    Retorna una lista de URLs.
    """
    # Construye la URL base del listado a partir de ciudad y keyword.
    url = f"https://www.paginasamarillas.com.co/{ciudad}/servicios/{keyword}"
    # Si la página es mayor a 1, agrega el query param page.
    if pagina > 1:
        url += f"?page={pagina}"
        
    # Protege la navegación con try/except.
    try:
        # Navega a la URL y espera el DOM inicial.
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        # Reporta fallo de navegación.
        print(f"Error navegando a listado: {e}")
        # Retorna vacío como fallback.
        return []
    
    # Inicializa bandera de éxito para el selector esperado.
    selector_ok = False
    # Reintenta hasta dos veces la espera del selector.
    for intento in range(2):
        try:
            # Espera que aparezca al menos un enlace de detalle.
            await page.wait_for_selector("a[href*='/empresas/']", timeout=20000)
            # Marca éxito.
            selector_ok = True
            # Sale del bucle de reintento.
            break
        except:
            # Si fue el primer fallo, espera 3 segundos y reintenta.
            if intento == 0:
                await page.wait_for_timeout(3000)
            else:
                # Si volvió a fallar, asume que no hay resultados reales.
                return []
    
    # Si por algún motivo la bandera sigue falsa, retorna vacío.
    if not selector_ok:
        return []

    # Inicializa lista de enlaces únicos.
    enlaces = []
    # Busca todos los anchors con patrón /empresas/.
    cards = await page.query_selector_all("a[href*='/empresas/']")
    # Recorre cada anchor.
    for elemento_a in cards:
        # Obtiene el href del enlace.
        href = await elemento_a.get_attribute("href")
        # Si el href existe...
        if href:
            # Si es relativo, lo convierte en absoluto.
            if not href.startswith("http"):
                href = "https://www.paginasamarillas.com.co" + href
            # Evita duplicados dentro de la misma página.
            if href not in enlaces:
                enlaces.append(href)
                
    # Retorna la lista final de URLs.
    return enlaces

# Define la extracción de detalle de negocio.
async def extraer_detalle_negocio(page: Page, url: str):
    """
    Entra a la URL de detalle y extrae la información profunda desde __NEXT_DATA__.
    Devuelve siempre una lista de diccionarios.
    """
    # Intenta navegar a la ficha de negocio.
    try:
        # Navega a la URL de detalle.
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        # Reporta error de carga.
        print(f"  Error cargando detalle {url}: {e}")
        # Fallback vacío.
        return []
    
    # Ejecuta JavaScript para leer el JSON hidratado de Next.js.
    next_data_content = await page.evaluate('''() => {
        const el = document.getElementById('__NEXT_DATA__');
        return el ? el.textContent : null;
    }''')
    
    # Si no existe el script esperado, retorna vacío.
    if not next_data_content:
        return []
        
    # Intenta parsear el JSON.
    try:
        data_json = json.loads(next_data_content)
        data = data_json.get('props', {}).get('pageProps', {}).get('data', {})
        if not data:
            return []
    except:
        # Si el parseo falla, retorna vacío.
        return []
        
    # Extrae nombre general del negocio.
    nombre_empresa = data.get('name', 'SIN NOMBRE')
    # Extrae slogan si existe.
    slogan = data.get('slogan', '')
    # Extrae descripción extensa o información de empresa.
    info_empresa = data.get('infoEmpresa', '')
    # Concatena slogan e info en una sola descripción.
    descripcion_completa = f"{slogan} {info_empresa}".strip()
    # Une todos los correos encontrados.
    emails = " / ".join(data.get('emails', []))
    
    # Inicializa el WhatsApp oficial.
    whatsapp = ""
    # Extrae el mapa de contactos o usa dict vacío.
    contact_map = data.get('contactMap') or {}
    # Busca la lista de WhatsApp dentro del mapa.
    wa_list = contact_map.get('WHATSAPP', [])
    # Si existe al menos un WhatsApp, usa el primero.
    if wa_list:
        whatsapp = wa_list[0]
        
    # Inicializa la lista de sucursales encontradas.
    sucursales_encontradas = []
    
    # Intenta obtener todas las direcciones.
    all_addresses = data.get('allAddresses', [])
    # Si no hay direcciones múltiples pero sí una principal, la envuelve en lista.
    if not all_addresses and data.get('mainAddress'):
        all_addresses = [data.get('mainAddress')]
        
    # Recorre cada dirección/sucursal.
    for branch in all_addresses:
        # Determina el nombre o tipo de sucursal.
        sucursal_nombre = branch.get('mainAddressName') or branch.get('addressLocality') or "Principal"
        
        # Toma la calle base.
        direccion = branch.get('streetName', '')
        # Si hay número, lo concatena a la dirección.
        if branch.get('streetNumber'):
            direccion += f" {branch.get('streetNumber')}"
            
        # Toma latitud y longitud crudas.
        latitud = branch.get('latitude', '')
        longitud = branch.get('longitude', '')
        
        # Intenta varias posibles fuentes de teléfonos de sucursal.
        tels = branch.get('allPhonesList', []) or branch.get('allPhones', []) or branch.get('phones', [])
        # Convierte la lista de teléfonos a texto unido por slash.
        tels_str = " / ".join([t.get('phoneToShow', t.get('number', '')) for t in tels])
        
        # Si la sucursal no tiene teléfonos propios, hereda el teléfono principal del negocio.
        if not tels_str and data.get('mainPhone'):
            tels_str = data.get('mainPhone', {}).get('phoneToShow', '')
            
        # Limpia espacios laterales de la dirección.
        direccion_limpia = direccion.strip()

        # Descarta direcciones virtuales tipo "Atiende en ...".
        if direccion_limpia.lower().startswith("atiende en"):
            continue

        # Agrega la sucursal encontrada como un diccionario homogéneo.
        sucursales_encontradas.append({
            "nombre": nombre_empresa,
            "sucursal_tipo": sucursal_nombre,
            "direccion": direccion_limpia,
            "latitud": latitud,
            "longitud": longitud,
            "telefono": tels_str,
            "whatsapp": whatsapp,
            "email": emails,
            "descripcion": descripcion_completa,
            "url": url,
            "fuente": "paginas_amarillas"
        })
        
    # Retorna todas las sucursales válidas encontradas.
    return sucursales_encontradas
```

---

# 9.10 `test_pl.py`

## Función del archivo
Script de depuración visual que guarda el HTML de un listado completo para inspección manual.

```python
# Importa Playwright síncrono para una prueba rápida no asíncrona.
from playwright.sync_api import sync_playwright
# Importa time para introducir una pausa fija.
import time

# Abre el contexto de Playwright síncrono.
with sync_playwright() as p:
    # Lanza el navegador Chromium.
    browser = p.chromium.launch()
    # Abre una nueva página.
    page = browser.new_page()
    # Navega a un listado fijo.
    page.goto('https://www.paginasamarillas.com.co/medellin/servicios/materiales-para-construccion')
    # Espera 3 segundos para dejar cargar el contenido.
    time.sleep(3)
    # Abre un archivo HTML local para guardar el contenido renderizado.
    with open('page_dump.html', 'w', encoding='utf-8') as f:
        # Escribe el HTML actual de la página.
        f.write(page.content())
    # Cierra el navegador.
    browser.close()
```

---

# 9.11 `.env`

## Función del archivo
Define parámetros de ejecución y configuración local del entorno.

```env
# Nombre del archivo JSONL de salida local.
OUTPUT_FILE=base_de_datos_argos.jsonl
# Nombre del archivo Excel esperado de salida.
OUTPUT_EXCEL=Data_Filtrada_Argos.xlsx

# Controla si se guarda también un backup local JSONL.
SAVE_JSON_BACKUP=false

# Ejecuta Playwright en modo headless.
HEADLESS=true

# Cantidad de pestañas concurrentes para scraping de detalle.
CONCURRENCIA_PESTANAS=2
# Tiempo mínimo de espera aleatoria entre lotes.
TIEMPO_ESPERA_MIN=1.0
# Tiempo máximo de espera aleatoria entre lotes.
TIEMPO_ESPERA_MAX=3.0

# Puerto donde corre la API FastAPI.
PORT=8002
# Webhook de n8n comentado como referencia local previa.
#N8N_WEBHOOK_URL=http://localhost:5678/webhook/tu-webhook

# Webhook activo actual para callback a n8n.
N8N_WEBHOOK_URL=http://localhost:2222/webhook-test/Scrapingpaginasamarillas
```

---

# 9.12 `Api_runner.py`

## Función del archivo
Expone una API FastAPI para disparar el scraper, consultar estado y notificar resultados a n8n.

```python
"""
api_runner.py — Endpoint HTTP para que n8n dispare el scraper
Arquitectura fire & forget: responde inmediatamente, corre en background.
"""

# Importa FastAPI y Request.
from fastapi import FastAPI, Request
# Importa respuesta JSON personalizada.
from fastapi.responses import JSONResponse
# Importa asyncio para lanzar tareas en background.
import asyncio
# Importa uvicorn para levantar el servidor.
import uvicorn
# Importa uuid para ids únicos de corrida.
import uuid
# Importa os para leer variables de entorno.
import os
# Importa utilidades de tiempo.
from datetime import datetime, timedelta
# Importa httpx para callbacks HTTP asíncronos.
import httpx
# Importa carga de .env.
from dotenv import load_dotenv
# Carga variables de entorno desde el archivo .env.
load_dotenv()

# Crea la aplicación FastAPI.
app = FastAPI(title="Argos Scraper — Páginas Amarillas")

# Lee la URL de webhook de n8n desde variables de entorno.
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")

# Estado global en memoria del proceso actual o último proceso ejecutado.
estado = {
    "scraping_en_curso": False,
    "run_id": None,
    "inicio": None,
    "fin": None,
    "duracion": None,
    "ultimo_status": "sin_correr",
    "ultimo_error": None,
    "metricas": None,
}

# Calcula duración legible entre dos timestamps ISO.
def calcular_duracion(inicio_iso: str | None, fin_iso: str | None):
    # Si falta alguno de los extremos, retorna None.
    if not inicio_iso or not fin_iso:
        return None
    try:
        # Convierte las fechas ISO a datetime.
        inicio = datetime.fromisoformat(inicio_iso)
        fin = datetime.fromisoformat(fin_iso)
        # Calcula duración total en segundos redondeada.
        duracion_s = max(0, round((fin - inicio).total_seconds()))
        # Retorna texto en minutos y segundos.
        return f"{duracion_s // 60}m {duracion_s % 60}s"
    except Exception:
        # Si algo falla, retorna None.
        return None

# Envía el callback HTTP a n8n.
async def enviar_callback(payload: dict, headers: dict | None = None):
    # Si no existe la URL del webhook, falla explícitamente.
    if not N8N_WEBHOOK_URL:
        raise ValueError("N8N_WEBHOOK_URL no está configurado")

    # Crea el cliente HTTP asíncrono.
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Realiza POST JSON al webhook.
        response = await client.post(
            N8N_WEBHOOK_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                **(headers or {})
            }
        )
        # Lanza excepción si el webhook respondió con error.
        response.raise_for_status()

# Envuelve el callback final para no romper el proceso principal si falla la notificación.
async def notificar_fin_run(payload: dict, headers: dict | None = None):
    try:
        # Intenta enviar el callback.
        await enviar_callback(payload, headers)
        # Log de éxito.
        print(f"[CALLBACK] Notificación enviada a n8n. evento={payload.get('evento')} run_id={payload.get('run_id')}")
    except Exception as e:
        # Log de error sin interrumpir la API.
        print(f"[CALLBACK] Falló envío a n8n: {e}")

# Ejecuta el scraper en segundo plano.
async def ejecutar_scraper_background(run_id: str):
    global estado
    try:
        # Importa el main real solo al ejecutar, evitando costos al arrancar la API.
        from main import main as do_scrape

        # Ejecuta el scraping.
        metricas = await do_scrape()

        # Marca fecha de fin.
        fin = datetime.now().isoformat()
        # Inicializa duración.
        duracion = None

        # Si el scraper retornó dict de métricas, intenta usar su duración.
        if isinstance(metricas, dict):
            duracion = metricas.get("duracion")

        # Si no vino duración, la calcula con los timestamps guardados.
        if not duracion:
            duracion = calcular_duracion(estado["inicio"], fin)

        # Actualiza el estado global finalizando en éxito.
        estado.update({
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": duracion,
            "ultimo_status": "ok",
            "ultimo_error": None,
            "metricas": metricas if isinstance(metricas, dict) else None,
        })

        # Log final.
        print(f"\n[✓] Scraping completado. run_id: {run_id}")

        # Notifica a n8n el cierre exitoso.
        await notificar_fin_run({
            "evento": "paginas_amarillas.finalizado",
            "status": "ok",
            "run_id": run_id,
            "inicio": estado["inicio"],
            "fin": estado["fin"],
            "duracion": estado["duracion"],
            "metricas": estado["metricas"],
            "origen": "api_runner",
            "tipo_ejecucion": "produccion"
        })

    except Exception as e:
        # Si falla, registra fin y duración igualmente.
        fin = datetime.now().isoformat()
        duracion = calcular_duracion(estado["inicio"], fin)

        # Actualiza estado global en error.
        estado.update({
            "scraping_en_curso": False,
            "fin": fin,
            "duracion": duracion,
            "ultimo_status": "error",
            "ultimo_error": str(e),
            "metricas": None,
        })

        # Log del error.
        print(f"\n[✗] Error en scraping: {e}")

        # Notifica a n8n el cierre fallido.
        await notificar_fin_run({
            "evento": "paginas_amarillas.finalizado",
            "status": "error",
            "run_id": run_id,
            "inicio": estado["inicio"],
            "fin": estado["fin"],
            "duracion": estado["duracion"],
            "error": str(e),
            "origen": "api_runner",
            "tipo_ejecucion": "produccion"
        })

# Healthcheck simple.
@app.get("/health")
def health():
    # Retorna estado básico del servicio.
    return {"status": "ok", "code": "200"}

# Endpoint para consultar estado actual.
@app.get("/status")
def status():
    # Retorna el snapshot del estado global.
    return {
        "statusGeneral": estado["ultimo_status"],
        "status": estado["ultimo_status"],
        "en_curso": estado["scraping_en_curso"],
        "run_id": estado["run_id"],
        "inicio": estado["inicio"],
        "fin": estado["fin"],
        "duracion": estado["duracion"],
        "error": estado["ultimo_error"],
        "metricas": estado["metricas"],
    }

# Endpoint que dispara el scraper.
@app.post("/scrape/paginas-amarillas")
async def run_scraper():
    global estado

    # Si ya hay un proceso corriendo, responde conflicto 409.
    if estado["scraping_en_curso"]:
        return JSONResponse(
            status_code=409,
            content={
                "status": "ocupado",
                "mensaje": "Ya hay un scraping en curso.",
                "run_id": estado["run_id"],
                "inicio": estado["inicio"],
            }
        )

    # Genera run_id para la ejecución disparada desde API.
    run_id = str(uuid.uuid4())
    # Marca tiempo de inicio.
    inicio = datetime.now().isoformat()

    # Actualiza estado global al arrancar la ejecución.
    estado.update({
        "scraping_en_curso": True,
        "run_id": run_id,
        "inicio": inicio,
        "fin": None,
        "duracion": None,
        "ultimo_status": "corriendo",
        "ultimo_error": None,
        "metricas": None,
    })

    # Dispara el scraper en background.
    asyncio.create_task(ejecutar_scraper_background(run_id))

    # Responde de inmediato sin bloquear al cliente HTTP.
    return {
        "status": "iniciado",
        "mensaje": "Scraper disparado. Consulta /status para ver el progreso.",
        "run_id": run_id,
        "inicio": inicio,
        "webhook_n8n": N8N_WEBHOOK_URL,
    }

# Endpoint para consultar el último resultado.
@app.get("/resultado")
def resultado():
    # Retorna resumen del último run conocido.
    return {
        "status": estado["ultimo_status"],
        "run_id": estado["run_id"],
        "inicio": estado["inicio"],
        "fin": estado["fin"],
        "duracion": estado["duracion"],
        "error": estado["ultimo_error"],
        "en_curso": estado["scraping_en_curso"],
        "metricas": estado["metricas"],
    }

# Endpoint para probar manualmente el callback a n8n.
@app.post("/test/callback")
async def test_callback(request: Request):
    try:
        # Intenta leer el body como JSON.
        body = await request.json()
    except Exception:
        # Si falla, usa body vacío.
        body = {}

    try:
        # Marca tiempo actual.
        now = datetime.now()
        # Genera inicio por defecto 65 segundos antes.
        inicio_default = (now - timedelta(seconds=65)).isoformat()
        # Genera fin por defecto ahora.
        fin_default = now.isoformat()

        # Construye el payload de prueba.
        payload = {
            "evento": "paginas_amarillas.finalizado",
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
                "keywords_total": 1,
                "keywords_procesadas": 1,
                "busqueda_total": 5,
                "detalle_ok": 4,
                "detalle_error": 1,
                "detalle_saltado": 0,
                "aprobados_argos": 2,
                "errores_totales": 1
            }),
            "origen": "api_runner",
            "tipo_ejecucion": body.get("tipo_ejecucion", "prueba_callback")
        }

        # Si se pide simular error, ajusta el payload.
        if payload["status"] == "error":
            payload.pop("metricas", None)
            payload["error"] = body.get("error", "Error de prueba enviado manualmente")

        # Envía el callback de prueba.
        await enviar_callback(payload)

        # Retorna éxito con el payload enviado.
        return {
            "status": "ok",
            "mensaje": "Callback de prueba enviado a n8n correctamente",
            "webhook_n8n": N8N_WEBHOOK_URL,
            "payload_enviado": payload
        }

    except Exception as e:
        # Reporta fallo del test callback.
        print(f"[TEST_CALLBACK] Falló envío de prueba a n8n: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "mensaje": "No se pudo enviar el callback de prueba a n8n",
                "error": str(e)
            }
        )

# Endpoint que lista rutas expuestas.
@app.get("/endpoints")
def endpoints():
    # Inicializa la lista de rutas.
    rutas = []
    # Recorre todas las rutas registradas en FastAPI.
    for route in app.routes:
        # Toma los métodos HTTP disponibles.
        methods = getattr(route, "methods", None)
        # Toma el path de la ruta.
        path = getattr(route, "path", None)

        # Si la ruta tiene path y métodos, la agrega al resultado.
        if path and methods:
            rutas.append({
                "path": path,
                "methods": sorted([m for m in methods if m not in {"HEAD", "OPTIONS"}])
            })

    # Retorna la lista de endpoints.
    return rutas

# Arranque directo del servidor si se ejecuta como script.
if __name__ == "__main__":
    # Lee el puerto desde entorno.
    port = int(os.getenv("PORT", "8002"))

    # Imprime ayuda operativa de arranque.
    print(f"🚀 Páginas Amarillas Scraper API en http://localhost:{port}")
    print(f"   n8n debe usar: http://host.docker.internal:{port}")
    print(f"   Webhook n8n:   {N8N_WEBHOOK_URL}")
    print(f"   GET  /health")
    print(f"   POST /scrape/paginas-amarillas")
    print(f"   GET  /status")
    print(f"   GET  /resultado")
    print(f"   POST /test/callback")
    print(f"   GET  /endpoints\n")

    # Lanza el servidor uvicorn.
    uvicorn.run(app, host="0.0.0.0", port=port)
```

---

# 9.13 `config.py`

## Función del archivo
Centraliza:
- ciudades a recorrer,
- mapa ciudad → departamento,
- keywords de búsqueda,
- conexión a DB,
- parámetros anti-bloqueo,
- rutas de salida,
- flags runtime.

## Observación crítica
Este archivo tiene señales de edición manual inconsistente. Lo documento tal como fue recibido, pero necesita saneamiento antes de considerarlo estable.

```python
"""
# Este bloque inicial abre un string multilínea; aparenta encapsular listas de configuración.

# Lista principal de ciudades objetivo.
CIUDADES = [
    "bogota", "medellin", "cali", "barranquilla", "cartagena", "bucaramanga",
    "cucuta", "pereira", "santa-marta", "ibague", "pasto", "manizales",
    "neiva", "villavicencio", "armenia", "valledupar", "monteria", "sincelejo",
    "popayan", "tunja", "riohacha", "florencia", "quibdo", "yopal", "arauca",
    "bello", "itagui", "envigado", "sabaneta", "rionegro", "apartado",
    "caucasia", "turbo", "dosquebradas", "santa-rosa-de-cabal", "calarca",
    "soacha", "chia", "zipaquira", "facatativa", "fusagasuga", "girardot",
    "mosquera", "madrid", "funza", "duitama", "sogamoso", "chiquinquira",
    "palmira", "buenaventura", "tulua", "cartago", "buga", "jamundi", "yumbo", "tumaco",
    "soledad", "malambo", "cienaga", "magangue", "maicao", "aguachica",
    "floridablanca", "giron", "piedecuesta", "barrancabermeja", "pamplona", "ocana",
    "pitalito", "garzon", "espinal", "ipiales"
]

# Diccionario que mapea ciudad a departamento.
CIUDAD_DEPARTAMENTO = {
    "bogota": "Cundinamarca", "medellin": "Antioquia", "cali": "Valle del Cauca",
    "barranquilla": "Atlántico", "cartagena": "Bolívar", "bucaramanga": "Santander",
    "cucuta": "Norte de Santander", "pereira": "Risaralda", "santa-marta": "Magdalena",
    "ibague": "Tolima", "pasto": "Nariño", "manizales": "Caldas",
    "neiva": "Huila", "villavicencio": "Meta", "armenia": "Quindío",
    "valledupar": "Cesar", "monteria": "Córdoba", "sincelejo": "Sucre",
    "popayan": "Cauca", "tunja": "Boyacá", "riohacha": "La Guajira",
    "florencia": "Caquetá", "quibdo": "Chocó", "yopal": "Casanare",
    "arauca": "Arauca", "bello": "Antioquia", "itagui": "Antioquia",
    "envigado": "Antioquia", "sabaneta": "Antioquia", "rionegro": "Antioquia",
    "apartado": "Antioquia", "caucasia": "Antioquia", "turbo": "Antioquia",
    "dosquebradas": "Risaralda", "santa-rosa-de-cabal": "Risaralda",
    "calarca": "Quindío", "soacha": "Cundinamarca", "chia": "Cundinamarca",
    "zipaquira": "Cundinamarca", "facatativa": "Cundinamarca",
    "fusagasuga": "Cundinamarca", "girardot": "Cundinamarca",
    "mosquera": "Cundinamarca", "madrid": "Cundinamarca", "funza": "Cundinamarca",
    "duitama": "Boyacá", "sogamoso": "Boyacá", "chiquinquira": "Boyacá",
    "palmira": "Valle del Cauca", "buenaventura": "Valle del Cauca",
    "tulua": "Valle del Cauca", "cartago": "Valle del Cauca",
    "buga": "Valle del Cauca", "jamundi": "Valle del Cauca",
    "yumbo": "Valle del Cauca", "tumaco": "Nariño",
    "soledad": "Atlántico", "malambo": "Atlántico", "cienaga": "Magdalena",
    "magangue": "Bolívar", "maicao": "La Guajira", "aguachica": "Cesar",
    "floridablanca": "Santander", "giron": "Santander", "piedecuesta": "Santander",
    "barrancabermeja": "Santander", "pamplona": "Norte de Santander",
    "ocana": "Norte de Santander", "pitalito": "Huila", "garzon": "Huila",
    "espinal": "Tolima", "ipiales": "Nariño",
}

# Lista de keywords a consultar en el sitio.
KEYWORDS_BUSQUEDA = [
    "ferreterias",
    "depositos-de-materiales",
    "depositos-y-ferreteria",
    "bodegas-de-construccion",
    "centro-ferretero",
    "materiales-para-construccion",
    "cemento",
    "concreto",
    "concreto-premezclado",
    "morteros",
    "mortero-seco",
    "agregados-para-construccion",
    "arena-y-balasto",
    "obra-gris",
    "hierro-y-cemento",
    "bloqueras",
    "ladrilleras",
    "prefabricados-de-concreto",
    "distribuidoras-de-cemento"
]

# Este segundo bloque también aparece dentro del archivo y parece un ejemplo reducido de prueba.
"""

CIUDADES = [
    "bogota"
]

CIUDAD_DEPARTAMENTO = {
    "bogota": "Cundinamarca"
}

KEYWORDS_BUSQUEDA = [
    "ferreterias"
]

# Importa os para leer variables de entorno.
import os
# Importa load_dotenv para cargar el archivo .env.
from dotenv import load_dotenv
# Carga variables de entorno al importar el módulo.
load_dotenv()

# Define helper para leer booleanos desde entorno.
def env_bool(name: str, default: bool = False) -> bool:
    # Lee el valor bruto desde entorno.
    value = os.getenv(name)
    # Si no existe, retorna el default.
    if value is None:
        return default
    # Convierte múltiples literales afirmativos en True.
    return value.strip().lower() in ("1", "true", "yes", "si", "sí", "on")

# Diccionario de configuración de PostgreSQL.
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME",     "postgres"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "password": os.getenv("DB_PASSWORD", "1234"),
}

# Configuración anti-bloqueos / throughput.
CONCURRENCIA_PESTANAS = int(os.getenv("CONCURRENCIA_PESTANAS", "2"))
TIEMPO_ESPERA_MIN = float(os.getenv("TIEMPO_ESPERA_MIN", "1.0"))
TIEMPO_ESPERA_MAX = float(os.getenv("TIEMPO_ESPERA_MAX", "3.0"))

# Rutas de salida locales.
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "base_de_datos_argos.jsonl")
OUTPUT_EXCEL = os.getenv("OUTPUT_EXCEL", "Data_Filtrada_Argos.xlsx")

# Flags de comportamiento runtime.
SAVE_JSON_BACKUP = env_bool("SAVE_JSON_BACKUP", True)
HEADLESS = env_bool("HEADLESS", True)
```

### Diagnóstico específico de `config.py`
- Hay una mezcla de bloque multilínea y configuración viva.
- Se ve un bloque grande y luego un bloque pequeño de prueba.
- Debe limpiarse para dejar una sola fuente de verdad.

---

# 9.14 `data_exporter.py`

## Función del archivo
Pretende exportar resultados desde PostgreSQL a Excel, pero hoy está desalineado con el resto del proyecto.

```python
"""
data_exporter.py — Exporta desde PostgreSQL a Excel
Uso:
    python data_exporter.py              → todos los registros
    python data_exporter.py --aprobados  → solo aprobados por Argos
"""
# Importa sys para leer flags CLI.
import sys
# Importa pandas para cargar SQL en dataframe y exportar Excel.
import pandas as pd
# Importa nombre de archivo Excel desde config.
from config import EXCEL_OUTPUT_FILE
# Importa la conexión PostgreSQL desde db.py.
from db import get_connection

# Define la exportación a Excel.
def export_to_excel(solo_aprobados: bool = False):
    # Si se pide solo aprobados, agrega un WHERE.
    filtro = "WHERE aprobado_argos = TRUE" if solo_aprobados else ""
    # Construye la consulta SQL.
    query = f"""
        SELECT
            nit,
            nombre,
            departamento,
            municipio,
            direccion,
            latitud,
            longitud,
            telefono,
            whatsapp,
            correo_electronico,
            fecha_actualizacion,
            fuente,
            sucursal_tipo,
            categorias_maps,
            score,
            aprobado_argos,
            keyword_busqueda,
            descripcion,
            url,
            fecha_extraccion,
            run_id
        FROM raw.google_maps_ferreterias
        {filtro}
        ORDER BY departamento, municipio, nombre;
    """
    try:
        # Abre conexión y carga la consulta en dataframe.
        with get_connection() as conn:
            df = pd.read_sql(query, conn)

        # Si no hay datos, informa y sale.
        if df.empty:
            print("No hay datos en la BD para exportar.")
            return

        # Si existe la columna categorias_maps, la convierte a string.
        if "categorias_maps" in df.columns:
            df["categorias_maps"] = df["categorias_maps"].apply(
                lambda x: ", ".join(x) if isinstance(x, list) else (x or "")
            )

        # Ordena el dataframe antes de exportar.
        df = df.sort_values(by=["departamento", "municipio", "score"], ascending=[True, True, False])
        # Exporta a Excel.
        df.to_excel(EXCEL_OUTPUT_FILE, index=False, engine="openpyxl")
        # Informa éxito.
        print(f"✅ {len(df)} registros exportados → '{EXCEL_OUTPUT_FILE}'")
        print(f"   Columnas: {list(df.columns)}")

    except Exception as e:
        # Informa cualquier error durante la exportación.
        print(f"❌ Error al exportar: {e}")

# Punto de entrada CLI.
if __name__ == "__main__":
    # Detecta flag --aprobados.
    solo_aprobados = "--aprobados" in sys.argv
    # Ejecuta la exportación.
    export_to_excel(solo_aprobados=solo_aprobados)
```











## 10. Ejecución del proyecto

### 10.1 Dependencias
```bash
pip install -r requirements.txt
playwright install
```

### 10.2 Ejecución directa
```bash
python main.py
```

### 10.3 API HTTP
```bash
python Api_runner.py
```

### 10.4 Endpoints esperados
- `GET /health`
- `POST /scrape/paginas-amarillas`
- `GET /status`
- `GET /resultado`
- `POST /test/callback`
- `GET /endpoints`

---

## 11. Riesgos técnicos detectados

### Riesgo 1 — `config.py` presenta señales de inconsistencia estructural
Hay bloques aparentes de configuración duplicados/comentados de forma irregular. Debe revisarse antes de producción.

### Riesgo 2 — `data_exporter.py` no está alineado con el esquema actual
Hace referencia a `raw.google_maps_ferreterias`, `categorias_maps` y `EXCEL_OUTPUT_FILE`, elementos que no coinciden con el resto del proyecto.

### Riesgo 3 — `api_runner.py` espera métricas que `main.py` no retorna
El comentario del runner asume que `main.main()` podría devolver métricas, pero el `main` actual no devuelve un `dict`.

### Riesgo 4 — doble `run_id`
La API genera un `run_id`, y `main.py` genera otro independiente. Esto rompe la trazabilidad punta a punta entre API, DB y callback.

### Riesgo 5 — sensibilidad a cambios del sitio fuente
Aunque usar `__NEXT_DATA__` es robusto, el sistema depende de que el sitio continúe exponiendo esa estructura.

### Riesgo 6 — ausencia de logging estructurado
La observabilidad depende de `print()`, lo cual dificulta monitoreo productivo y correlación de errores.

---

## 12. Recomendaciones de clean code

### Arquitectura
- Separar capa de **orquestación**, **extracción**, **transformación**, **persistencia** y **API** en paquetes.
- Convertir `main.py` en servicio reutilizable con retorno explícito de métricas.
- Mover constantes de negocio del scoring a una configuración externa versionable.

### Calidad de datos
- Agregar validación de coordenadas fuera de rango.
- Normalizar email a lista o campo principal/secundario.
- Registrar motivo de descarte además del score.

### Observabilidad
- Reemplazar `print()` por `logging` con niveles.
- Incluir conteos acumulados por ciudad, keyword, éxitos, duplicados y fallos.
- Persistir errores en tabla de auditoría.

### Mantenibilidad
- Unificar naming: `Api_runner.py` vs `api_runner.py`.
- Eliminar archivos de prueba del flujo productivo o moverlos a `/tests` y `/debug`.
- Agregar tipado más estricto y dataclasses o pydantic models para registros.

---

## 13. Prioridad de correcciones

### Críticas
1. Corregir `config.py`.
2. Alinear `data_exporter.py` con la tabla real.
3. Hacer que `main.py` reciba o retorne el mismo `run_id` que usa `api_runner.py`.

### Altas
4. Incorporar métricas explícitas en `main.py`.
5. Agregar logging estructurado.
6. Manejar mejor reintentos y timeouts por detalle.

### Medias
7. Separar pruebas de producción.
8. Añadir tests unitarios para `normalizer.py` y `filter_engine.py`.
9. Externalizar listas de keywords positivas/negativas.

---

## Conclusión
La base del proyecto es sólida: el pipeline principal está bien pensado, la extracción desde `__NEXT_DATA__` es una decisión técnica acertada y la deduplicación por `hash_id` resuelve adecuadamente la persistencia multi-sucursal.

Sin embargo, hay inconsistencias importantes de configuración, exportación y trazabilidad entre la API y el scraper principal que deben corregirse para considerar el sistema listo para producción.

