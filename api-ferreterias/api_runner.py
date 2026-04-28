"""
start.py - Inicia la API de Ferreterias con un solo comando.

Uso:
    python start.py
"""
import os
import sys
import time
import shutil
import subprocess
import webbrowser
import threading
from pathlib import Path

G="\033[92m"; Y="\033[93m"; R="\033[91m"; B="\033[94m"; W="\033[1m"; X="\033[0m"

def ok(m):   print(f"{G}  [OK]{X} {m}")
def warn(m): print(f"{Y}  [!]{X}  {m}")
def err(m):  print(f"{R}  [ERR]{X} {m}"); 
def info(m): print(f"{B}  ---{X}  {m}")

def banner():
    print(f"""{W}{B}
 ============================================
  API Ferreterias v2
  Reto Beca Ser ANDI Argos
 ============================================{X}""")

def verificar_env():
    print(f"\n{W}[1] Verificando configuracion...{X}")
    if not Path(".env").exists():
        if Path(".env.example").exists():
            shutil.copy(".env.example", ".env")
            warn(".env creado desde .env.example")
            warn(f"Edita el archivo: {Path('.env').resolve()}")
            input(f"\n  Presiona {W}Enter{X} cuando hayas puesto tus credenciales...")
        else:
            err("No se encontro .env ni .env.example"); sys.exit(1)
    ok(".env encontrado")

    from dotenv import load_dotenv
    load_dotenv(override=True)

    checks = [
        ("DATABASE_URL",       "PostgreSQL",       True),
        ("OPENROUTER_API_KEY", "OpenRouter (IA gratuita)", False),
        ("N8N_WEBHOOK_URL",    "Webhook n8n",      False),
        ("SERPER_API_KEY",     "Serper (Google)",  False),
        ("ANTHROPIC_API_KEY",  "Claude (opcional)", False),
    ]
    for var, label, requerido in checks:
        val = os.getenv(var, "")
        if val and "password" not in val and "pon-tu" not in val:
            ok(f"{label}")
        elif requerido:
            err(f"{label} — REQUERIDO. Agrega {var} al .env"); sys.exit(1)
        else:
            warn(f"{label} — no configurado (opcional)")

def verificar_deps():
    print(f"\n{W}[2] Verificando dependencias Python...{X}")
    faltantes = []
    for mod in ["fastapi","uvicorn","sqlalchemy","psycopg2","pydantic","dotenv","requests","httpx","openpyxl"]:
        try:
            __import__(mod)
        except ImportError:
            faltantes.append(mod)
    if faltantes:
        err(f"Faltan paquetes: {', '.join(faltantes)}")
        print(f"\n  Instala con:")
        print(f"  {W}pip install -r requirements.txt --only-binary psycopg2-binary{X}\n")
        sys.exit(1)
    ok("Todas las dependencias instaladas")

def crear_carpetas():
    print(f"\n{W}[3] Preparando carpetas...{X}")
    for d in ["respaldos/campos_dudosos","respaldos/posibles_matches","respaldos/reporte_ejecucion"]:
        Path(d).mkdir(parents=True, exist_ok=True)
    ok("Carpetas de respaldo listas")

def abrir_browser(url, delay=5):
    def _f():
        time.sleep(delay)
        try: webbrowser.open(url)
        except: pass
    threading.Thread(target=_f, daemon=True).start()

def main():
    banner()
    verificar_env()
    verificar_deps()
    crear_carpetas()

    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("ENVIRONMENT", "dev") == "dev"

    print(f"""
{W}[4] Iniciando servidor...{X}

  URL:   {G}http://localhost:{port}{X}
  Docs:  {G}http://localhost:{port}/docs{X}
  
  {B}Las tablas de PostgreSQL se crean automaticamente al conectar.
  No necesitas correr ningun SQL manualmente.{X}

{Y}  Presiona Ctrl+C para detener{X}
""")

    abrir_browser(f"http://localhost:{port}/docs")

    cmd = [sys.executable, "-m", "uvicorn", "main:app",
           "--host", "0.0.0.0", "--port", str(port),
           "--log-level", os.getenv("LOG_LEVEL","info").lower()]
    if reload:
        cmd.append("--reload")

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print(f"\n{Y}  API detenida.{X}")
    except subprocess.CalledProcessError as e:
        err(f"Error al iniciar: {e}"); sys.exit(1)

if __name__ == "__main__":
    main()
