# API Consolidacion Ferreterias v2

## Descripcion del proceso

Esta API recibe datos de 6 fuentes externas (ya scrapeadas y guardadas en tablas `raw.*`)
y produce una tabla limpia `clean.empresas` donde cada fila es un negocio real unico.

```
n8n elige municipios
       |
       v
POST /ejecuciones/iniciar
       |
       v
FASE 1 — Carga
  raw.google_maps_ferreterias
  raw.paginas_amarillas_ferreterias     → staging.empresas_unificadas
  raw.foursquare_ferreterias                (todo en un formato comun)
  raw.overpass_ferreterias
  raw.rues_detalle
  raw.serper_resultados_construccion
       |
       v
FASE 2 — Normalizacion
  Nombres: quitar tildes, palabras juridicas (S.A.S., Ltda.)
  Telefonos: formato estandar colombiano
  Emails: validar formato
  Municipios: normalizar contra ref.municipios_colombia
  Direcciones: expandir abreviaturas (Cra→Carrera, Cl→Calle)
       |
       v
FASE 3 — Validacion sin RUES (opcional)
  Registros sin NIT → busca en Google via Serper
  Extrae NIT/telefono si aparece en resultados
  IA gratuita (OpenRouter) confirma si existe el negocio
       |
       v
FASE 4 — Deduplicacion (7 reglas)
  Score 100 → MISMO NIT              → auto_match
  Score 100 → MISMO ID_RM (RUES)     → auto_match
  Score 85  → MISMO EMAIL + municipio → auto_match
  Score 85  → MISMO TELEFONO + mun.  → auto_match
  Score 70-85 → NOMBRE similar + mun. → pendiente / IA
  Score 70  → DIRECCION similar + mun → pendiente / IA
  Score 80  → COORDENADAS <50m + nom. → pendiente / IA
       |
       v
FASE 5 — Campos dudosos
  Detecta inconsistencias entre fuentes (mismo NIT, nombres distintos)
  Exporta JSON para revision
       |
       v
FASE 6 — IA para duplicados ambiguos (score 60-74)
  OpenRouter modelos gratis (rotacion automatica)
  Fallback a Claude si OpenRouter no disponible
  Prompt ultra-compacto para ahorrar tokens
       |
       v
FASE 7 — Consolidacion
  Union-Find agrupa staging_ids → empresa_id
  Inserta en clean.empresas (mejor dato por fuente)
  Tablas auxiliares: telefonos, emails, direcciones, fuentes
       |
       v
FASE 8 — Scoring y aprobacion
  score_calidad 0-140:
    +25 tiene NIT           +15 tiene telefono
    +15 tiene nombre        +10 tiene email
    +10 tiene municipio     +10 tiene coordenadas
    +10 tiene direccion     +20 fuente RUES incluida
    +15 tiene 2+ fuentes
  aprobado_argos = true  si score >= 80
       |
       v
WEBHOOK a n8n
  POST N8N_WEBHOOK_URL con resumen completo + URLs de descarga
```

## Estructura de tablas que se crean automaticamente

```
raw.*          — Fuentes originales (nunca se modifican)
staging.*      — Datos de trabajo durante el pipeline
ref.*          — Tablas de referencia (municipios Colombia)
clean.*        — Resultado final de produccion
```

## Instalacion y uso

### Local (Windows/Mac/Linux)

```bash
# 1. Instalar dependencias
pip install -r requirements.txt --only-binary psycopg2-binary

# 2. Configurar variables
copy .env.example .env   # Windows
cp .env.example .env     # Mac/Linux
# Editar .env con tus credenciales

# 3. Levantar (crea las tablas automaticamente)
python start.py
```

### Docker

```bash
copy .env.example .env
# Editar .env
docker-compose up -d
```

## Endpoints principales

| Metodo | URL | Descripcion |
|--------|-----|-------------|
| POST | `/ejecuciones/iniciar` | Inicia el pipeline (recibe municipios de n8n) |
| GET  | `/ejecuciones/{id}` | Estado de la ejecucion |
| GET  | `/ejecuciones/{id}/reporte` | Reporte JSON completo |
| GET  | `/empresas` | Listar empresas limpias (con filtros) |
| GET  | `/empresas/{id}` | Detalle + telefonos + emails + fuentes |
| GET  | `/campos-dudosos` | Inconsistencias detectadas |
| GET  | `/posibles-matches` | Duplicados encontrados |
| POST | `/validar-manualmente` | Confirmar o rechazar un match |
| GET  | `/openrouter/models` | Modelos gratis disponibles |
| GET  | `/health` | Estado de la API |
| GET  | `/docs` | Documentacion interactiva |

## Llamada desde n8n

```json
POST http://localhost:8000/ejecuciones/iniciar

{
  "municipios": [
    {"municipio": "Medellin", "departamento": "Antioquia"},
    {"municipio": "Cali",     "departamento": "Valle del Cauca"}
  ],
  "usar_ia_duplicados": true,
  "preferir_openrouter": true
}
```

`municipios: null` o `municipios: []` → procesa todos los municipios sin filtro.

Cuando termina, la API hace automaticamente:
```json
POST {N8N_WEBHOOK_URL}
{
  "evento": "ferreterias.pipeline_finalizado",
  "status": "completado",
  "empresas_consolidadas": 2400,
  "aprobadas_argos": 1950,
  "urls": {
    "empresas_aprobadas": "http://localhost:8000/empresas?aprobado_argos=true"
  }
}
```
