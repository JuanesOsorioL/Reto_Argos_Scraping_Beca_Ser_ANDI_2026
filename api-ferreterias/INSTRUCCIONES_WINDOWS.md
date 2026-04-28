# Instrucciones de instalación en Windows

## Error: psycopg2 "pg_config executable not found"

Tienes 3 opciones, elige la más fácil:

---

### Opción A — La más simple (sin instalar PostgreSQL localmente)

```powershell
pip install psycopg2-binary --only-binary :all:
```

Si eso también falla:

```powershell
pip install "psycopg[binary]"
```

Y en `db/connection.py` cambia esta línea:
```python
# ANTES
import psycopg2  # (implícito en SQLAlchemy)

# DESPUÉS — cambiar en DATABASE_URL
# postgresql://...  →  postgresql+psycopg://...
```

---

### Opción B — Instalar PostgreSQL (recomendado para producción)

1. Descarga de: https://www.postgresql.org/download/windows/
2. Durante la instalación, asegúrate de marcar **"Command Line Tools"**
3. Agrega al PATH: `C:\Program Files\PostgreSQL\16\bin`
4. Luego:
```powershell
pip install -r requirements.txt
```

---

### Opción C — requirements_windows.txt simplificado

Crea un archivo `requirements_windows.txt`:
```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
psycopg2-binary
pydantic==2.9.2
python-multipart==0.0.9
python-dotenv==1.0.1
anthropic>=0.34.0
openai>=1.30.0
requests>=2.31.0
httpx>=0.27.0
openpyxl==3.1.5
rapidfuzz>=3.9.0
```

E instala con:
```powershell
pip install -r requirements_windows.txt --only-binary psycopg2-binary
```

---

## Setup completo en Windows (primera vez)

```powershell
# 1. Crear entorno virtual
python -m venv venv
venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements_windows.txt --only-binary psycopg2-binary

# 3. Copiar y editar .env
copy .env.example .env
notepad .env

# 4. Crear base de datos (PostgreSQL ya instalado)
createdb ferreterias_db
psql ferreterias_db -f sql/01_extensions.sql
psql ferreterias_db -f sql/02_staging_clean_tables.sql

# 5. Crear directorio de respaldos
mkdir respaldos

# 6. Iniciar API
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Variables de entorno mínimas (.env)

```env
DATABASE_URL=postgresql://postgres:tupassword@localhost:5432/ferreterias_db
ANTHROPIC_API_KEY=sk-ant-...        # Opcional, para Claude
OPENROUTER_API_KEY=sk-or-...        # Para modelos gratis
```
