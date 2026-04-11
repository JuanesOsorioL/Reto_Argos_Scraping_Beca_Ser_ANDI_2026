# README Maestro — RUES API Scraper

## Índice

* [1. Resumen ejecutivo](#1-resumen-ejecutivo)
* [2. Objetivo del sistema](#2-objetivo-del-sistema)
* [3. Arquitectura general](#3-arquitectura-general)
* [4. Flujo operativo completo](#4-flujo-operativo-completo)
* [5. Punto de entrada y superficies de ejecución](#5-punto-de-entrada-y-superficies-de-ejecución)
* [6. Mapa de dependencias](#6-mapa-de-dependencias)
* [7. Análisis detallado por archivo](#7-análisis-detallado-por-archivo)
* [8. Contratos de datos](#8-contratos-de-datos)
* [9. Persistencia en PostgreSQL](#9-persistencia-en-postgresql)
* [10. Salidas JSON y trazabilidad](#10-salidas-json-y-trazabilidad)
* [11. Logging y observabilidad](#11-logging-y-observabilidad)
* [12. Lógica crítica del negocio](#12-lógica-crítica-del-negocio)
* [13. Riesgos técnicos detectados](#13-riesgos-técnicos-detectados)
* [14. Recomendaciones de clean code y evolución](#14-recomendaciones-de-clean-code-y-evolución)
* [15. Guía de uso](#15-guía-de-uso)
* [16. Checklist operativa](#16-checklist-operativa)
* [17. Conclusión técnica](#17-conclusion-tecnica)

---

## 1. Resumen ejecutivo

Este proyecto implementa un **scraper/orquestador técnico para RUES** que:

1. Inicializa una sesión HTTP compatible con el frontend real.
2. Cifra los payloads exactamente como lo espera el backend.
3. Ejecuta búsquedas por **razón social** o **NIT**.
4. Normaliza los registros de búsqueda.
5. Solicita el **detalle mercantil** por `id_rm`.
6. Opcionalmente consulta endpoints extendidos de **facultades** y **propietarios** usando `cod_camara + matricula`.
7. Persiste todo en **PostgreSQL** dentro del schema `raw`.
8. Genera artefactos de salida en **JSON y JSONL**.
9. Expone tres superficies de uso:

   * ejecución directa con `main.js`
   * ejecución manual por CLI con `cli.js`
   * disparo remoto vía HTTP con `api_runner.js`

El diseño está orientado a **trazabilidad**, **reintentos controlados**, **deduplicación parcial**, **persistencia de respuestas crudas** y **observabilidad detallada**.

---

## 2. Objetivo del sistema

El sistema busca automatizar la extracción estructurada de información mercantil desde RUES para alimentar un pipeline de datos que permita:

* localizar empresas por keywords del universo Argos;
* enriquecer cada resultado con detalle mercantil;
* guardar respuestas crudas para auditoría y reprocesamiento;
* calcular un **score Argos** para priorización de registros;
* producir salidas consultables tanto por base de datos como por archivos.

---

## 3. Arquitectura general

```text
                         ┌───────────────────────────┐
                         │       Usuario / n8n       │
                         └─────────────┬─────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
           ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
           │    main.js     │  │    cli.js      │  │ api_runner.js  │
           │ ejecución run  │  │ ejecución manual│ │ endpoint HTTP  │
           └───────┬────────┘  └───────┬────────┘  └───────┬────────┘
                   │                   │                   │
                   └──────────────┬────┴──────────────┬────┘
                                  ▼                   
                        ┌──────────────────────┐
                        │   runSearchPipeline  │
                        │     pipeline.js      │
                        └─────────┬────────────┘
                                  │
          ┌───────────────────────┼──────────────────────────┐
          │                       │                          │
          ▼                       ▼                          ▼
┌──────────────────┐   ┌─────────────────────┐    ┌─────────────────────┐
│    client.js     │   │      utils.js       │    │       db.js         │
│ HTTP + cookies   │   │ normalización,      │    │ PostgreSQL + schema │
│ + retries        │   │ limpieza, scoring   │    │ raw + inserts       │
└────────┬─────────┘   └─────────────────────┘    └─────────────────────┘
         │
         ▼
┌──────────────────────┐
│     crypto.js        │
│ AES compatible RUES  │
└────────┬─────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                      API RUES                               │
│ BusquedaAvanzadaRM / DetalleRM / Facultades / Propietarios  │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Flujo operativo completo

### 4.1 Flujo macro

```text
Inicio
  ↓
Carga de configuración
  ↓
Inicialización de logs y output
  ↓
Bootstrap de sesión web con RUES
  ↓
Por cada keyword:
  ↓
BusquedaAvanzadaRM
  ↓
Normalización de resultados
  ↓
Persistencia inmediata en raw.rues_busqueda + JSONL
  ↓
Selección de registros con id_rm
  ↓
Para cada id_rm no procesado:
  ↓
DetalleRM con retries
  ↓
Normalización de detalle
  ↓
Cálculo de score Argos
  ↓
Persistencia en raw.rues_detalle + JSONL
  ↓
[Si extended]
  ├─ ConsultFacultadesXCamYMatricula
  │    ↓
  │  Limpieza HTML → texto
  │    ↓
  │  Persistencia + JSONL
  │
  └─ PropietarioEstXCamaraYMatricula
       ↓
     Normalización de respuesta
       ↓
     Persistencia + JSONL
  ↓
Acumulación de métricas
  ↓
Guardado de JSON finales
  ↓
Cierre de pool y log stream
  ↓
Fin
```

### 4.2 Flujo real de datos

| Etapa                 | Entrada                   | Transformación               | Salida                                        |
| --------------------- | ------------------------- | ---------------------------- | --------------------------------------------- |
| Bootstrap             | Frontend base RUES        | Inicializa cookies/sesión    | Cliente listo                                 |
| Search                | keyword o NIT             | Payload + cifrado AES + POST | `searchResult`                                |
| Normalización search  | `response.registros[]`    | `normalizeBusquedaRecord`    | arreglo consistente                           |
| Persistencia búsqueda | registro normalizado      | insert DB + append JSONL     | `raw.rues_busqueda` + `rues-busqueda-*.jsonl` |
| Detalle               | `id_rm`                   | payload por id + retries     | respuesta de DetalleRM                        |
| Normalización detalle | `response.registros`      | `normalizeDetalleRecord`     | objeto de detalle                             |
| Scoring               | razón social + CIIU       | `calcularScoreArgos`         | `score`, `aprobado_argos`                     |
| Facultades            | `cod_camara`, `matricula` | HTML → texto                 | facultades limpias                            |
| Propietarios          | `cod_camara`, `matricula` | normalización array          | propietarios estructurados                    |
| Resumen final         | métricas acumuladas       | serialización JSON           | `rues-resumen-*.json`                         |

---

## 5. Punto de entrada y superficies de ejecución

### 5.1 `main.js`

Es el **orquestador principal**. Genera un `run_id`, inicializa la base de datos, abre sesión con RUES, recorre el conjunto de keywords, ejecuta el pipeline por cada keyword, consolida métricas, guarda JSON finales y cierra recursos.

### 5.2 `cli.js`

Es la **interfaz de línea de comandos** para consultas puntuales por razón social o NIT. Está pensada para ejecuciones manuales y exporta resultados a disco.

### 5.3 `api_runner.js`

Es la **fachada HTTP** para integraciones externas, especialmente n8n. Dispara el scraper en background, expone estado de ejecución y evita corridas concurrentes.

### 5.4 `index.js`

Es la **superficie pública del paquete**, reexportando cliente, cifrado, builders y pipeline.

---

## 6. Mapa de dependencias

```text
config.js
 ├─ usado por client.js
 ├─ usado por crypto.js
 ├─ usado por main.js
 ├─ usado por pipeline.js
 └─ usado por db.js

logger.js
 ├─ usado por api_runner.js
 ├─ usado por main.js
 ├─ usado por db.js
 └─ usado por pipeline.js

crypto.js
 └─ usado por client.js

payloads.js
 ├─ usado por client.js
 └─ usado por index.js

utils.js
 ├─ usado por client.js
 ├─ usado por cli.js
 └─ usado por pipeline.js

client.js
 ├─ usado por main.js
 ├─ usado por cli.js
 └─ usado por index.js

pipeline.js
 ├─ usado por main.js
 ├─ usado por cli.js
 ├─ usado por index.js
 └─ usa db.js + utils.js + logger.js

db.js
 └─ usado por main.js y pipeline.js

main.js
 └─ usado por api_runner.js
```

### 6.1 Dependencia crítica transversal

La relación más importante del sistema es:

`main.js` → `pipeline.js` → (`client.js` + `utils.js` + `db.js`) → `crypto.js` / `config.js`

Esto define el flujo real del negocio.

---

## 7. Análisis detallado por archivo

| Archivo         | Rol                     | Tipo                   | Responsabilidad principal                                     | Dependencias directas                                                                                   | Observaciones clave                               |
| --------------- | ----------------------- | ---------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `config.js`     | configuración central   | core                   | concentra URLs, headers, defaults, keywords y credenciales DB | `dotenv`                                                                                                | actúa como fuente única de parámetros del sistema |
| `logger.js`     | observabilidad          | utilitario transversal | logging en consola + archivo con niveles                      | `fs`, `path`                                                                                            | soporta secciones y resumen final                 |
| `crypto.js`     | infraestructura         | utilitario crítico     | cifra payloads con AES para compatibilidad con frontend       | `crypto-js`, `config.js`                                                                                | pieza indispensable para hablar con la API        |
| `payloads.js`   | contrato de request     | lógica de integración  | construye payloads para búsqueda, detalle y extendidos        | `config.js`                                                                                             | encapsula el shape esperado por el backend        |
| `client.js`     | acceso remoto           | integración            | axios + cookie jar + bootstrap de sesión + retries            | `axios`, `axios-cookiejar-support`, `tough-cookie`, `config.js`, `crypto.js`, `payloads.js`, `utils.js` | concentra la mecánica HTTP real                   |
| `utils.js`      | normalización y reglas  | lógica de negocio      | helpers, limpieza HTML, normalización teléfonos, score Argos  | ninguno externo del proyecto                                                                            | contiene heurísticas de negocio                   |
| `db.js`         | persistencia            | infraestructura        | schema raw, tablas, inserts y pool PostgreSQL                 | `pg`, `config.js`, `logger.js`                                                                          | conserva `raw_response` en todas las tablas       |
| `pipeline.js`   | orquestación operativa  | negocio                | secuencia search → detail → facultades → propietarios         | `config.js`, `logger.js`, `utils.js`, `db.js`                                                           | corazón del flujo unitario por keyword            |
| `main.js`       | orquestador de corrida  | negocio                | ejecuta múltiples keywords, resume métricas, cierra recursos  | `config.js`, `logger.js`, `client.js`, `pipeline.js`, `db.js`                                           | punto de entrada principal del scraper            |
| `cli.js`        | interfaz manual         | entrega                | permite ejecutar consultas específicas desde consola          | `client.js`, `pipeline.js`, `utils.js`                                                                  | útil para pruebas puntuales                       |
| `api_runner.js` | integración externa     | entrega                | servidor Express para ejecutar corridas por HTTP              | `express`, `uuid`, `logger.js`, `main.js`                                                               | diseñado para n8n y control de estado             |
| `index.js`      | API pública del paquete | fachada                | reexporta piezas reutilizables                                | `client.js`, `crypto.js`, `payloads.js`, `pipeline.js`                                                  | simplifica consumo desde terceros                 |

### 7.1 `config.js`

**Qué hace:** centraliza configuración de URLs de RUES, endpoints, llave AES, defaults operativos, headers de navegador, keywords objetivo, conexión PostgreSQL y rutas de salida.

**Por qué es crítico:** evita hardcodear configuración en múltiples archivos y mantiene coherencia entre cliente, pipeline, base de datos y ejecución.

**Impacto sistémico:** casi todos los módulos dependen de este archivo.

### 7.2 `logger.js`

**Qué hace:** provee un logger con niveles (`INFO`, `OK`, `WARN`, `ERROR`, `FATAL`, `DEBUG`), salida coloreada en consola y persistencia en `logs/rues-YYYY-MM-DD.log`.

**Por qué es crítico:** el proyecto está muy orientado a operaciones; sin este archivo se pierde trazabilidad de corridas, errores y métricas.

### 7.3 `crypto.js`

**Qué hace:** cifra el payload usando `CryptoJS.AES.encrypt(JSON.stringify(obj), AES_KEY).toString()`.

**Por qué es crítico:** el backend espera el cuerpo cifrado en `dataBody`. Si el cifrado falla o cambia, el sistema completo deja de comunicarse con RUES.

### 7.4 `payloads.js`

**Qué hace:** encapsula la construcción de payloads para:

* búsqueda por razón;
* búsqueda por NIT;
* detalle por `id`;
* endpoints extendidos por `codigo_camara + matricula`.

**Por qué es importante:** separa la forma del request de la lógica HTTP, reduciendo acoplamiento en `client.js`.

### 7.5 `client.js`

**Qué hace:** crea un cliente axios con cookie jar, prepara headers, inicializa sesión contra el frontend, cifra payloads y ejecuta requests POST. También implementa `withRetries` con backoff exponencial y jitter.

**Función técnica real:** es la capa de adaptación entre el scraper y la API de RUES.

### 7.6 `utils.js`

**Qué hace:** reúne utilidades técnicas y reglas de negocio:

* espera asíncrona;
* jitter aleatorio;
* sanitización de nombres de archivo;
* parseo robusto de fechas;
* limpieza de HTML;
* normalización de teléfonos;
* score Argos;
* normalizadores de búsqueda, detalle y propietarios.

**Importancia:** aquí vive gran parte de la “inteligencia semántica” del proyecto.

### 7.7 `db.js`

**Qué hace:** crea el schema `raw`, inicializa 4 tablas, define índices, inserta búsquedas, detalle, facultades y propietarios, carga `id_rm` ya procesados y cierra el pool.

**Decisión de diseño notable:** todas las tablas guardan `raw_response`, lo cual mejora auditoría, reprocesamiento y debugging.

### 7.8 `pipeline.js`

**Qué hace:** ejecuta el flujo unitario por keyword.

**Responsabilidad exacta:**

1. ejecutar búsqueda;
2. normalizar búsqueda;
3. persistir búsqueda en tiempo real;
4. seleccionar registros con `id_rm`;
5. solicitar detalle con retries;
6. calcular score Argos;
7. persistir detalle;
8. si aplica, consultar facultades y propietarios;
9. escribir JSONL de cada etapa;
10. devolver un objeto `pipeline` consumible por `main.js` y `cli.js`.

### 7.9 `main.js`

**Qué hace:** administra la corrida completa de muchas keywords.

**Responsabilidad exacta:**

* genera `run_id`;
* abre sesión;
* inicializa BD;
* precarga `id_rm` procesados;
* construye rutas JSONL;
* itera keywords;
* invoca `runSearchPipeline` por cada una;
* consolida métricas;
* guarda resumen y raw final;
* cierra BD y logger.

### 7.10 `cli.js`

**Qué hace:** permite correr búsquedas ad hoc desde terminal y guardar artefactos por consulta.

**Valor práctico:** facilita validación de payloads, depuración funcional y pruebas manuales sin correr el lote completo.

### 7.11 `api_runner.js`

**Qué hace:** expone endpoints HTTP para lanzar corridas completas o de prueba, con un estado global en memoria para monitorear progreso.

**Riesgo asociado:** el estado es volátil y solo vive en memoria del proceso.

### 7.12 `index.js`

**Qué hace:** exporta una API limpia del proyecto para consumo programático.

---

## 8. Contratos de datos

### 8.1 Contrato de búsqueda (`BusquedaAvanzadaRM`)

**Entrada funcional:**

* razón social/palabra clave o NIT;
* filtros opcionales: departamento, cámara, offset, limit.

**Salida relevante normalizada:**

* `id_rm`
* `nit`
* `razon_social`
* `cod_camara`
* `nom_camara`
* `matricula`
* `estado_matricula`
* `organizacion_juridica`
* `ultimo_ano_renovado`
* `categoria`
* `raw`

### 8.2 Contrato de detalle (`DetalleRM`)

**Clave de entrada:** `id_rm`

**Salida importante:**

* identificación mercantil;
* direcciones y contactos comerciales/fiscales;
* CIIU principal y secundarios;
* fechas de matrícula, renovación, vigencia y cancelación;
* indicadores normativos;
* URL de certificados;
* `raw` completo.

### 8.3 Contrato de facultades

**Entrada:** `codigo_camara`, `matricula`

**Salida:** normalmente HTML o texto HTMLizado, luego transformado a `facultades_text`.

### 8.4 Contrato de propietarios

**Entrada:** `codigo_camara`, `matricula`

**Salida normalizada:** metadata de respuesta y arreglo `registros[]` con identificación y estado del propietario.

---

## 9. Persistencia en PostgreSQL

### 9.1 Schema

El sistema usa el schema:

```sql
raw
```

### 9.2 Tablas

| Tabla                   | Propósito                         | Clave/Unicidad                    | Notas                                                    |
| ----------------------- | --------------------------------- | --------------------------------- | -------------------------------------------------------- |
| `raw.rues_busqueda`     | guardar cada hit de búsqueda      | `UNIQUE(id_rm, keyword_busqueda)` | soporta mismo `id_rm` en distintas keywords              |
| `raw.rues_detalle`      | guardar expediente detallado      | `id_rm UNIQUE`                    | hace upsert para refrescar `raw_response`, score y fecha |
| `raw.rues_facultades`   | guardar facultades/representación | `id_rm UNIQUE`                    | conserva html, texto y error                             |
| `raw.rues_propietarios` | guardar propietarios              | sin `UNIQUE(id_rm)` visible       | permite más de un insert si se repite corrida            |

### 9.3 Diseño de persistencia

```text
Búsqueda      -> tabla de granularidad alta por keyword
Detalle       -> tabla maestra por id_rm
Facultades    -> extensión documental por id_rm
Propietarios  -> extensión relacional por id_rm
```

### 9.4 Observaciones importantes

* El detalle se actualiza por `id_rm`, no por `run_id`.
* La búsqueda sí retiene variación por `keyword`.
* La tabla de propietarios no muestra `ON CONFLICT`, por lo que puede crecer con repetidos si el mismo `id_rm` se procesa varias veces.
* Todas las tablas conservan `raw_response`, lo que mejora trazabilidad.

---

## 10. Salidas JSON y trazabilidad

### 10.1 JSONL operacionales

| Archivo                            | Contenido                  | Momento de escritura   |
| ---------------------------------- | -------------------------- | ---------------------- |
| `rues-busqueda-{run_id}.jsonl`     | cada resultado de búsqueda | inmediato por registro |
| `rues-detalle-{run_id}.jsonl`      | cada detalle exitoso       | inmediato por detalle  |
| `rues-facultades-{run_id}.jsonl`   | facultades limpias         | inmediato por consulta |
| `rues-propietarios-{run_id}.jsonl` | propietarios normalizados  | inmediato por consulta |
| `rues-errores-{run_id}.jsonl`      | errores operativos         | inmediato por error    |

### 10.2 JSON finales

| Archivo                      | Propósito                            |
| ---------------------------- | ------------------------------------ |
| `rues-raw-{run_id}.json`     | agrupa respuestas crudas por keyword |
| `rues-resumen-{run_id}.json` | consolida métricas finales del run   |

### 10.3 Valor operacional

Este diseño permite:

* inspección en tiempo real;
* reanudación lógica parcial;
* auditoría posterior;
* análisis por etapa;
* debugging sin depender solo de la base de datos.

---

## 11. Logging y observabilidad

### 11.1 Niveles soportados

| Nivel   | Uso                          |
| ------- | ---------------------------- |
| `INFO`  | progreso normal              |
| `OK`    | operaciones exitosas         |
| `WARN`  | anomalías no fatales         |
| `ERROR` | errores recuperables         |
| `FATAL` | falla no recuperable         |
| `DEBUG` | detalle técnico bajo bandera |

### 11.2 Diseño del logger

* escribe en consola con color;
* escribe en archivo plano diario;
* soporta separadores de sección;
* imprime resumen final de métricas.

### 11.3 Beneficio

Aporta observabilidad clara en corridas largas con muchas keywords.

---

## 12. Lógica crítica del negocio

### 12.1 Bootstrap de sesión

El sistema primero hace un `GET` al frontend base para obtener cookies y emular navegación real. Sin esta sesión, el backend puede rechazar o degradar la interacción.

### 12.2 Cifrado AES del payload

Toda petición de negocio se envía como:

```json
{ "dataBody": "<payload cifrado>" }
```

Esto replica el frontend y es el contrato más delicado del sistema.

### 12.3 Deduplicación por `id_rm`

Antes de detallar, `main.js` carga desde BD los `id_rm` ya procesados. `pipeline.js` omite esos registros para no recalcular detalle innecesariamente.

### 12.4 Score Argos

El proyecto aplica una heurística de puntaje usando:

* palabras clave de alta afinidad;
* palabras de afinidad media;
* palabras negativas;
* CIIU relevantes.

Threshold operativo:

```text
score >= 2  => aprobado_argos = true
```

### 12.5 Reintentos con backoff

`client.withRetries()` reintenta frente a estados 429, 408, 503, 502 o ausencia de status. La espera crece exponencialmente y se le suma jitter aleatorio.

### 12.6 Endpoints extendidos

Las consultas de facultades y propietarios dependen de que el detalle haya devuelto `cod_camara` y `matricula`.

### 12.7 Normalización robusta

El proyecto corrige y estandariza:

* fechas RUES tipo `YYYYMMDD`;
* teléfonos colombianos;
* HTML a texto plano;
* arrays de propietarios.

---

## 13. Riesgos técnicos detectados

| Riesgo                                                                                           | Impacto    | Detalle                                                                                              | Recomendación                                                               |
| ------------------------------------------------------------------------------------------------ | ---------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Llave AES hardcodeada                                                                            | alto       | la llave vive en `config.js`                                                                         | mover a variable de entorno segura                                          |
| Estado en memoria en `api_runner.js`                                                             | medio      | se pierde al reiniciar el proceso                                                                    | persistir estado en DB o Redis                                              |
| `duracion` no se calcula en API runner                                                           | medio      | el campo se expone pero no se llena                                                                  | calcular diferencia inicio/fin en `.then/.catch`                            |
| `timeoutMs` pasado desde pipeline no se aplica realmente en `withRetries`                        | alto       | `client.withRetries()` no inyecta timeout al request interno                                         | permitir override del cliente o parámetros por request                      |
| `raw_response` de búsquedas guarda registro normalizado, no necesariamente payload HTTP completo | bajo/medio | en búsqueda se persiste `r.raw ?? r`                                                                 | documentar claramente la semántica del raw                                  |
| Propietarios sin upsert explícito                                                                | medio      | pueden duplicarse filas entre corridas                                                               | definir `UNIQUE(id_rm, cod_camara, matricula, run_id?)` según regla deseada |
| `logger.close()` al final de `main.js`                                                           | medio      | si `api_runner` dispara múltiples corridas, el stream se reabre, pero conviene revisar ciclo de vida | aislar recursos por corrida o dejar logger singleton vivo                   |
| `main.js` y `api_runner.js` dependen de proceso único                                            | medio      | no hay lock distribuido                                                                              | agregar lock persistente si habrá horizontal scaling                        |
| CIIU/score heurístico está embebido                                                              | bajo/medio | cambiar criterios requiere tocar código                                                              | externalizar reglas a config o tabla                                        |

---

## 14. Recomendaciones de clean code y evolución

### 14.1 Separar responsabilidades operativas

* Mover métricas a un módulo propio.
* Extraer un servicio de escritura JSONL.
* Extraer una capa de repositorio para BD.

### 14.2 Tipar contratos

Aunque el proyecto está en JavaScript, ganaría mucho con:

* JSDoc más estricto o
* migración gradual a TypeScript.

### 14.3 Formalizar errores

Crear una jerarquía de errores:

* `BootstrapError`
* `SearchError`
* `DetailError`
* `PersistenceError`
* `ExtendedEndpointError`

### 14.4 Hacer explícita la estrategia de idempotencia

Definir si:

* detalle debe refrescarse siempre;
* propietarios deben versionarse por corrida;
* facultades deben sobrescribirse o historizarse.

### 14.5 Introducir pruebas

Pruebas mínimas recomendadas:

* builders de payload;
* cifrado `encryptPayload`;
* normalizadores;
* score Argos;
* parseo de fechas;
* deduplicación de `id_rm`;
* `withRetries`.

### 14.6 Mejorar configuración

Mover a `.env` adicionalmente:

* `AES_KEY`
* `API_BASE_URL`
* `FRONTEND_BASE_URL`
* límites y delays

### 14.7 Aislar reglas Argos

El score debe salir de `utils.js` a un módulo de negocio, por ejemplo:

```text
argos_rules.js
argos_scoring.js
```

---

## 15. Guía de uso

### 15.1 Ejecución directa

```bash
node main.js
```

### 15.2 Ejecución de prueba

```bash
node main.js --test
```

### 15.3 CLI por razón social

```bash
node cli.js razon "ferreteria" --details --extended --limit=10 --search-limit=500 --concurrency=1 --delay=1200
```

### 15.4 CLI por NIT

```bash
node cli.js nit 901362593 --details --extended
```

### 15.5 API HTTP

```http
POST /scrape/rues
POST /scrape/rues/prueba
GET  /status
GET  /resultado
```

### 15.6 Resultado esperado

* datos en PostgreSQL `raw.*`;
* archivos en `output/`;
* logs en `logs/`.

---

## 16. Checklist operativa

### Antes de correr

* variables de entorno de DB correctas;
* PostgreSQL disponible;
* dependencias instaladas;
* permisos de escritura en `output/` y `logs/`.

### Durante la corrida

* revisar `/status` si se usa API;
* revisar `logs/rues-YYYY-MM-DD.log`;
* revisar JSONL para ver avance real.

### Después de la corrida

* validar `rues-resumen-{run_id}.json`;
* comprobar número de insertados en `raw.rues_busqueda` y `raw.rues_detalle`;
* revisar `rues-errores-{run_id}.jsonl`.

---

## 17. Conclusión técnica

Este repositorio está bien orientado a scraping productivo porque combina:

* emulación de sesión real;
* cifrado compatible con frontend;
* reintentos y throttling;
* normalización de datos;
* persistencia cruda y estructurada;
* observabilidad detallada;
* múltiples formas de ejecución.

Su mayor fortaleza es la **trazabilidad extremo a extremo**: casi toda operación deja huella en logs, BD o JSONL.

Su principal deuda técnica está en la **gestión de configuración sensible**, la **idempotencia completa**, el **timeout efectivo por request** y la **persistencia del estado del runner HTTP**.

Aun así, la arquitectura actual ya constituye una base sólida para producción controlada y para evolución hacia un servicio más robusto y mantenible.
#   R e t o _ A r g o s _ S c r a p i n g _ B e c a _ S e r _ A N D I _ 2 0 2 6  
 