# Como levantar las APIs

Son DOS servicios separados que trabajan juntos.

## Arquitectura

```
Puerto 8003  →  api_runner.py       (City Matcher - elige municipios)
                    |
                    | envia municipios seleccionados
                    v
Puerto 8000  →  main.py             (api-ferreterias - limpia y consolida)
```

---

## Estructura de carpetas recomendada

```
Reto Beca Ser ANDI Argos/
    api-ferreterias/        <- este ZIP (puerto 8000)
        venv/
        main.py
        ...
    api-runner/             <- tu archivo api_runner.py (puerto 8003)
        venv/
        api_runner.py
        .env
```

---

## Paso 1 — Levantar api_runner (City Matcher)

```powershell
# Ir a la carpeta donde esta api_runner.py
cd "C:\Users\osori\...\api-runner"

# Crear entorno virtual (solo la primera vez)
python -m venv venv
venv\Scripts\activate

# Instalar dependencias (solo la primera vez)
pip install fastapi uvicorn httpx rapidfuzz openai python-dotenv requests

# Crear .env
echo OPENROUTER_API_KEY=sk-or-v1-... > .env

# Levantar en puerto 8003
uvicorn api_runner:app --reload --port 8003
```

Verificar: http://localhost:8003/docs

---

## Paso 2 — Levantar api-ferreterias (limpieza)

```powershell
# Ir a la carpeta del ZIP descomprimido
cd "C:\Users\osori\...\api-ferreterias"

# Crear entorno virtual (solo la primera vez)
python -m venv venv
venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt --only-binary psycopg2-binary

# Copiar y editar .env
copy .env.example .env
notepad .env

# Crear tablas en PostgreSQL (solo la primera vez)
psql -U postgres -d ferreterias_db -f sql/01_extensions.sql
psql -U postgres -d ferreterias_db -f sql/02_staging_clean_tables.sql

# Crear carpeta de respaldos
mkdir respaldos

# Levantar en puerto 8000
uvicorn main:app --reload --port 8000
```

Verificar: http://localhost:8000/docs

---

## Paso 3 — Flujo completo desde n8n

### 3a. El usuario elige municipios (via api_runner)

```
POST http://localhost:8003/match
{
  "mode": "multiple",
  "input": "medellin, cali, bogota",
  "search_level": "municipio"
}

Respuesta:
{
  "selected_locations": [
    {"municipio": "Medellín", "departamento": "Antioquia"},
    {"municipio": "Cali", "departamento": "Valle del Cauca"},
    {"municipio": "Bogotá", "departamento": "Cundinamarca"}
  ]
}
```

### 3b. n8n pasa el resultado a api-ferreterias

```
POST http://localhost:8000/ejecuciones/iniciar
{
  "municipios": [
    {"municipio": "Medellín", "departamento": "Antioquia"},
    {"municipio": "Cali", "departamento": "Valle del Cauca"}
  ],
  "validar_sin_rues": true,
  "preferir_openrouter": true
}

Respuesta:
{
  "execution_id": "exec-20240115-103000-abc12345"
}
```

### 3c. n8n consulta el estado (poll cada 30s)

```
GET http://localhost:8000/ejecuciones/exec-20240115-103000-abc12345

Respuesta:
{
  "estado": "completado",
  "empresas_consolidadas": 2400,
  "progreso_pct": 100
}
```

### 3d. Consultar empresas limpias

```
GET http://localhost:8000/empresas?aprobado_argos=true&municipio=Medellín
```

---

## Variables .env minimas que necesitas

### api_runner (.env)
```
OPENROUTER_API_KEY=sk-or-v1-...
```

### api-ferreterias (.env)
```
DATABASE_URL=postgresql://postgres:tupassword@localhost:5432/ferreterias_db
OPENROUTER_API_KEY=sk-or-v1-...
SERPER_API_KEY=tu-serper-key
```

---

## Abrir dos terminales en Windows

Terminal 1 (api_runner - puerto 8003):
```powershell
cd "C:\...\api-runner"
venv\Scripts\activate
uvicorn api_runner:app --reload --port 8003
```

Terminal 2 (api-ferreterias - puerto 8000):
```powershell
cd "C:\...\api-ferreterias"
venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

---

## Verificar que todo funciona

- api_runner docs:    http://localhost:8003/docs
- api-ferreterias:   http://localhost:8000/docs
- health check:      http://localhost:8000/health
- OpenRouter status: http://localhost:8000/openrouter/key-status
