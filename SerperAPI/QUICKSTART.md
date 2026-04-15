# ⚡ Inicio Rápido (5 minutos)

## 1. Descarga todos los archivos

Necesitas estos 8 archivos en la misma carpeta:

```
serper-api/
├── .env
├── config.py
├── scraper.py
├── db.py
├── main.py
├── api_runner.py
├── utils.py
├── requirements.txt
└── README.md
```

## 2. Obtén tu API key de Serper

1. Ve a https://serper.dev/
2. Regístrate (gratuito)
3. Copia tu API key (ej: `abc123def456...`)
4. Pega en `.env`:

```env
SERPER_API_KEY=abc123def456...
```

## 3. Instala dependencias

```bash
# Crear entorno virtual
python -m venv venv

# Activar
source venv/bin/activate  # macOS/Linux
# o
venv\Scripts\activate     # Windows

# Instalar
pip install -r requirements.txt
```

## 4. Configura PostgreSQL

```bash
# Crear BD (si no existe)
createdb postgres

# Verificar conexión
psql -U postgres -d postgres -c "SELECT 1;"
```

## 5. Inicia el servidor

```bash
python api_runner.py
```

Debe mostrar:
```
🚀 SERPER API — INICIANDO
════════════════════════════════════════════════════════════════════════════════
  Puerto:           http://localhost:8004
  Swagger:          http://localhost:8004/docs
  ...
```

## 6. Prueba rápido (2 keywords × 2 ciudades = 4 queries)

En otra terminal:

```bash
curl -X POST http://localhost:8004/scrape/serper/prueba

# Respuesta:
# {
#   "status": "iniciado",
#   "run_id": "a1b2c3d4-...",
#   "inicio": "2024-01-20T10:30:00..."
# }
```

## 7. Ve el progreso

```bash
curl http://localhost:8004/progress

# Verás algo como:
# {
#   "run_id": "a1b2c3d4-...",
#   "status": "corriendo",
#   "queries_hechas": 2,
#   "queries_total": 4,
#   "registros_nuevos": 23,
#   "aprobados_argos": 8
# }
```

## 8. ¡Listo!

El scraper está funcionando. Ahora puedes:

### Opción A: Ir a Producción Completo

```bash
curl -X POST http://localhost:8004/scrape/serper
```

Procesará 18 keywords × 70 ciudades = 1,260 queries
Tiempo: 30-45 minutos (con posibles pauses por rate limit)

### Opción B: Pausar y Reanudar

```bash
# Pausar
curl -X POST http://localhost:8004/pause

# Esperar un poco...

# Reanudar (continúa donde paró)
curl -X POST http://localhost:8004/resume
```

### Opción C: Ver Documentación Swagger

Abre en navegador:
```
http://localhost:8004/docs
```

Verás todos los endpoints documentados e interactivos.

---

## 🔥 Lo Más Importante

**Si Serper devuelve 429 (rate limit):**

✅ La app pausa automáticamente  
✅ Espera 15 minutos  
✅ Reintenta automáticamente  
✅ Guarda progreso → no pierde nada

**Si la app se cae:**

✅ Los datos ya están en PostgreSQL  
✅ Puedes llamar `POST /resume`  
✅ Continúa exactamente donde quedó

---

## 📝 Notas

- **Tokens gratis**: ~2,500 queries (límite)
- **Límite de velocidad**: 100 req/min
- **JSON backup**: Deshabilitado por defecto (solo Postgres)
- **Progreso**: Se guarda en `serper_progress.json` automáticamente

---

## ❓ ¿Algo no funciona?

1. ¿SERPER_API_KEY está en `.env`? ✓
2. ¿PostgreSQL está corriendo? ✓
3. ¿El puerto 8004 está libre? ✓

Si algo falla, revisa **README.md** sección "Troubleshooting".

---

**¡Ahora sí, a scraping! 🚀**
