# Decisiones de Diseño — API Ferreterías v2

Respuestas a las preguntas planteadas y cómo se implementaron.

---

## 1. Filtro de municipios desde n8n / api_runner

**Flujo completo:**

```
n8n bot pregunta al usuario
      ↓
api_runner.py responde:
{
  "selected_locations": [
    {"municipio": "Cali", "departamento": "Valle del Cauca"}
  ]
}
      ↓
POST /ejecuciones/iniciar
{
  "municipios": [
    {"municipio": "Cali", "departamento": "Valle del Cauca"}
  ]
}
      ↓
Pipeline filtra solo esos municipios
```

**Caso "todos los municipios":**
Enviar `"municipios": null` o `"municipios": []` → sin filtro.

**RUES y el filtro de municipios:**
RUES no tiene filtro por municipio en su API de búsqueda.
Lo que hacemos: filtramos los resultados de `raw.rues_detalle` por municipio
usando el campo `municipio` que ya fue almacenado cuando se hizo la extracción.

```sql
-- Si hay filtro: trae solo RUES de Cali
WHERE municipio ilike 'cali' AND ...

-- Si no hay filtro: trae todo RUES
(sin WHERE de municipio)
```

---

## 2. RUES inactivos — ¿Qué hacer?

**Decisión: INCLUIR con penalización, NO descartar.**

**¿Por qué?**
En Colombia, muchos negocios siguen operando sin renovar su matrícula mercantil.
Un registro "cancelado" en RUES no significa que el negocio cerró —
puede significar simplemente que no renovó el trámite.

**Cómo se implementa:**

| Estado RUES | Score | Incluir | aprobado_argos |
|-------------|-------|---------|----------------|
| Activo / Renovado | sin cambio | ✅ | según score |
| Sin renovar 2-3 años | -5 pts | ✅ | según score |
| Sin renovar 4+ años | -10 pts | ✅ | según score |
| Cancelado / Disuelto | -15 pts | ✅ | generalmente false |
| Liquidado | -15 pts | ✅ | generalmente false |

**Si NO quieres inactivos:**
```json
POST /ejecuciones/iniciar
{
  "incluir_rues_inactivos": false
}
```
→ Los registros solo de RUES inactivo se eliminan de `clean.empresas`.
→ Los que además tienen otras fuentes (Google Maps, PA, etc.) se mantienen.

---

## 3. Registros en otras APIs que NO están en RUES

**Decisión: Incluir + validar via Google.**

**¿Por qué incluir?**
Google Maps, Foursquare, OSM y Páginas Amarillas tienen info de negocios
que operan informalmente o que simplemente no están en RUES.
Son igual de relevantes para encontrar ferreterías reales.

**Proceso de validación:**

```
Registro sin NIT de Google Maps
       ↓
1. Reglas rápidas: ¿tiene teléfono? ¿email? ¿coords? → score base
       ↓
2. Búsqueda Google (Serper): "{nombre} {municipio} Colombia ferreteria"
   → ¿aparece en resultados? → +20 pts
   → ¿tiene NIT en Google? → +20 pts, extraído automáticamente
       ↓
3. IA gratuita (OpenRouter) analiza los snippets:
   → ¿confirma que existe? → +10 pts
   → ¿encuentra teléfono/NIT? → enriquece el staging
       ↓
4. Si score final >= 40 → se incluye en clean.empresas
   Si score final < 40 → se descarta
```

**Costo estimado:**
- Serper: ~$0.001 por búsqueda. 500 registros = $0.50
- OpenRouter: gratis (modelos :free)
- Total validación: ~$0.50 por ejecución

---

## 4. Sucursales (Páginas Amarillas y otras)

**Decisión: Siempre son empresas SEPARADAS si están en diferente municipio.**

```
"Ferretería El Diamante" en Cali  →  empresa_id = UUID-1
"Ferretería El Diamante" en Bogotá →  empresa_id = UUID-2
```

**¿Por qué?**
La regla `NOMBRE_SIMILAR_MUNICIPIO` requiere **mismo municipio** para unir.
Entonces dos sucursales de la misma cadena en diferente ciudad = dos empresas distintas.

**Excepción — si comparten NIT:**
```
"Ferretería El Diamante" en Cali   → NIT 900123456
"Ferretería El Diamante" en Bogotá → NIT 900123456
→ Se unen por MISMO_NIT (score 100)
→ Una empresa con múltiples direcciones en clean.empresa_direcciones
```

**¿Cómo saber cuáles son sucursales?**
- Mismo NIT → misma empresa con sucursales
- Sin NIT y mismo nombre → empresas independientes (puede ser franquicia o coincidencia)
- La IA puede clasificarlas con `/openrouter/chat` si se necesita confirmación

---

## 5. OpenRouter — Modelos gratis como IA principal

**Jerarquía de uso:**

```
1. OpenRouter modelos :free (gratis, limitado)
   ↓ si falla o no disponible
2. Claude Anthropic (pago, más preciso)
   ↓ si tampoco disponible
3. Sin IA — solo reglas determinísticas
```

**Para qué se usa OpenRouter en el pipeline:**

| Tarea | Tokens aprox. | Frecuencia |
|-------|---------------|------------|
| Resolver duplicado | ~80 tokens | Por cada match 60-74 |
| Validar empresa sin RUES | ~100 tokens | Por registro sin NIT |
| Clasificar sucursal | ~80 tokens | Solo si se necesita |

**Límites OpenRouter :free:**
- ~50 requests/día (free tier básico)
- ~1000 requests/día (si compraste créditos antes)
- Para procesar 500 matches: se hacen en varios días o se usa Claude para los urgentes

---

## 6. Estrategia general de costos

| Fase | Costo |
|------|-------|
| Normalización | Gratis (SQL) |
| Deduplicación 7 reglas | Gratis (SQL + pg_trgm) |
| Validación Google (Serper) | ~$0.001/búsqueda |
| IA duplicados (OpenRouter :free) | Gratis |
| IA duplicados (Claude fallback) | ~$0.001/request |
| **Total 14k registros** | **~$1-3 por ejecución** |

---

## 7. Flujo completo desde n8n

```
[n8n/Telegram bot]
Usuario elige: "Buscar en Medellín y Cali"
       ↓
[api_runner.py]
POST /match → returns selected_locations
       ↓
[n8n pasa el resultado a api-ferreterias]
POST http://api-ferreterias:8000/ejecuciones/iniciar
{
  "municipios": [
    {"municipio": "Medellín", "departamento": "Antioquia"},
    {"municipio": "Cali", "departamento": "Valle del Cauca"}
  ],
  "validar_sin_rues": true,
  "preferir_openrouter": true,
  "incluir_rues_inactivos": true
}
       ↓
[Pipeline ejecuta en background]
- Carga solo registros de Medellín y Cali de raw.*
- RUES carga todo lo de esas ciudades (filtrado en SQL)
- Normalización → matching → validación → consolidación
       ↓
[n8n consulta estado]
GET /ejecuciones/{id} → {"estado": "completado", "empresas_consolidadas": 2400}
       ↓
[Resultado disponible]
GET /empresas?municipio=Medellín&aprobado_argos=true
```
