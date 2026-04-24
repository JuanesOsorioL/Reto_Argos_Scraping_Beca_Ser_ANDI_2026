
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from rapidfuzz import process, fuzz
from typing import List, Optional, Dict
import unicodedata
import re
import os
import json
import httpx
from datetime import datetime, timedelta

app = FastAPI(title="City Matcher API")

# ============================================================================
# CONFIGURACIÓN API COLOMBIA
# ============================================================================

API_COLOMBIA_DEPARTMENTS = "https://api-colombia.com/api/v1/Department"
API_COLOMBIA_CITIES = "https://api-colombia.com/api/v1/City"

# Cache local en memoria
MUNICIPIOS_CACHE = None
DEPARTAMENTOS_CACHE = None
CACHE_TIMESTAMP = None
CACHE_DURATION = timedelta(hours=24)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# ============================================================================
# MODELOS PYDANTIC
# ============================================================================

class MatchRequest(BaseModel):
    mode: str = Field(default="single", description="all | single | multiple")
    input: Optional[str] = Field(default=None, description="Ciudad o lista separada por comas")
    use_ai: bool = Field(default=True, description="Usar OpenRouter si fuzzy no logra corregir")
    return_valid_options: bool = Field(default=False, description="Retornar lista completa")
    search_level: str = Field(default="municipio", description="municipio | departamento")


class MatchResult(BaseModel):
    original: str
    normalized: str
    final_municipio: Optional[str] = None
    departamento: Optional[str] = None
    score: int
    accepted: bool
    source: str
    suggestion: Optional[str] = None
    reason: Optional[str] = None


class MatchResponse(BaseModel):
    mode: str
    search_level: str
    total_received: int
    accepted_count: int
    rejected_count: int
    used_ai: bool
    selected_locations: List[Dict[str, str]]
    matches: List[MatchResult]
    valid_cities: Optional[List[str]] = None


# ============================================================================
# FUNCIONES DE CARGA API-COLOMBIA
# ============================================================================

async def fetch_api_colombia_data() -> tuple[Dict[str, Dict], Dict[str, tuple]]:
    r"""
    Descarga departamentos y ciudades desde api-colombia.com.
    
    Retorna:
        - municipios_dict: {"Antioquia": ["Medellín", "Bello", ...], ...}
        - municipio_index: {"medellin": ("Medellín", "Antioquia"), ...}
    """
    global MUNICIPIOS_CACHE, DEPARTAMENTOS_CACHE, CACHE_TIMESTAMP

    # Verificar cache vigente
    if MUNICIPIOS_CACHE and DEPARTAMENTOS_CACHE and CACHE_TIMESTAMP:
        if datetime.now() - CACHE_TIMESTAMP < CACHE_DURATION:
            municipio_index = build_municipio_index(MUNICIPIOS_CACHE)
            return MUNICIPIOS_CACHE, municipio_index

    try:
        print("📡 Descargando departamentos de api-colombia.com...")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response_depts = await client.get(API_COLOMBIA_DEPARTMENTS)
            response_depts.raise_for_status()
            departamentos = response_depts.json()

        print("📡 Descargando ciudades de api-colombia.com...")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response_cities = await client.get(API_COLOMBIA_CITIES)
            response_cities.raise_for_status()
            ciudades = response_cities.json()

        municipios_dict = {}
        departamento_id_map = {}

        # 1️⃣ Procesar departamentos
        for dept in departamentos:
            dept_name = dept.get("name", "").strip()
            dept_id = dept.get("id")
            
            if dept_name and dept_id:
                municipios_dict[dept_name] = []
                departamento_id_map[dept_id] = dept_name

        # 2️⃣ Procesar ciudades y asociarlas a departamentos
        for city in ciudades:
            city_name = city.get("name", "").strip()
            dept_id = city.get("departmentId")
            
            if city_name and dept_id and dept_id in departamento_id_map:
                dept_name = departamento_id_map[dept_id]
                municipios_dict[dept_name].append(city_name)

        # Ordenar municipios alfabéticamente
        for dept in municipios_dict:
            municipios_dict[dept].sort()

        MUNICIPIOS_CACHE = municipios_dict
        DEPARTAMENTOS_CACHE = departamento_id_map
        CACHE_TIMESTAMP = datetime.now()

        print(f"✅ api-colombia.com loaded: {len(municipios_dict)} departamentos, {sum(len(m) for m in municipios_dict.values())} municipios")
        
        municipio_index = build_municipio_index(municipios_dict)
        return municipios_dict, municipio_index

    except Exception as e:
        print(f"❌ Error fetching from api-colombia.com: {e}")
        raise HTTPException(status_code=503, detail="No se pudo conectar a api-colombia.com")


# ============================================================================
# FUNCIONES DE NORMALIZACIÓN
# ============================================================================

def normalize_text(text: str, preserve_spaces: bool = False) -> str:
    r"""
    Normaliza texto: minúsculas, acentos, espacios → guiones.
    """
    text = text.strip().lower()
    
    # Eliminar acentos
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    
    text = text.replace("_", "-")
    
    if not preserve_spaces:
        text = re.sub(r"\s+", "-", text)
    
    if preserve_spaces:
        text = re.sub(r"[^a-z0-9\-\s]", "", text)
    else:
        text = re.sub(r"[^a-z0-9\-]", "", text)
    
    text = re.sub(r"-+", "-", text)
    
    return text.strip("-").strip()


def build_municipio_index(municipios_dict: Dict[str, List[str]]) -> Dict[str, tuple]:
    r"""
    Crea índice: municipio_normalized → (municipio_original, departamento)
    """
    index = {}
    for depto, municipios in municipios_dict.items():
        for municipio in municipios:
            normalized = normalize_text(municipio, preserve_spaces=False)
            index[normalized] = (municipio, depto)
    return index


# ============================================================================
# PARSING INTELIGENTE DE MÚLTIPLES CIUDADES
# ============================================================================

def smart_parse_municipalities(text: str, municipio_index: Dict[str, tuple]) -> List[str]:
    r"""
    Parsea inteligentemente texto libre para extraer nombres de ciudades.
    
    MEJORAS:
    - Filtra palabras muy cortas (< 3 caracteres)
    - Filtra palabras de relleno (es, la, de, y, un, etc.)
    - Busca solo en municipios conocidos
    - Maneja tanto "comas" como "y" como separadores
    
    Ejemplo:
        "Cali es la mejor ciudad de medellín y Itagüí"
        → ["Cali", "Medellín", "Itagüí"]
    """
    
    # Lista de palabras de relleno (stopwords) en español
    stopwords = {
        "es", "la", "de", "y", "un", "una", "los", "las", "el", "en", "a",
        "o", "u", "por", "para", "con", "sin", "del", "al", "es", "son",
        "está", "están", "soy", "eres", "somos", "que", "si", "no", "más",
        "menos", "muy", "mejor", "peor", "bien", "mal", "bueno", "malo",
        "grande", "pequeño", "nuevo", "viejo", "joven", "mayor", "menor",
        "ciudad", "municipio", "departamento", "región", "zona", "área",
        "desde", "hasta", "entre", "dentro", "fuera", "sobre", "bajo",
        "la", "me", "te", "se", "los", "las", "les", "mis", "tus", "sus"
    }
    
    # Obtener todas las formas normalizadas de municipios
    municipios_normalizados = set(municipio_index.keys())
    
    # Dividir por comas primero, luego por "y"
    # Ejemplo: "Medellín, Bogotá y Cali" → ["Medellín", "Bogotá", "Cali"]
    parts = re.split(r'[,;]', text)  # Dividir por comas o punto y coma
    
    found_cities = []
    
    for part in parts:
        # Dentro de cada parte, buscar por "y" pero manteniendo contexto
        # "Medellín y Cali" → ["Medellín", "Cali"]
        subparts = re.split(r'\sy\s', part)  # "y" rodeado de espacios
        
        for subpart in subparts:
            # Limpiar espacios
            subpart = subpart.strip()
            
            if not subpart:
                continue
            
            # Normalizar para búsqueda
            normalized = normalize_text(subpart)
            
            # ✅ OPCIÓN 1: Búsqueda EXACTA (la mejor)
            if normalized in municipios_normalizados:
                found_cities.append(subpart)
                continue
            
            # ✅ OPCIÓN 2: Si es una palabra compuesta (espacios), intenta directamente
            # Ejemplo: "Santa Marta" → buscar como "santa-marta"
            if " " in subpart:
                normalized_compound = normalize_text(subpart)
                if normalized_compound in municipios_normalizados:
                    found_cities.append(subpart)
                    continue
            
            # ✅ OPCIÓN 3: Fuzzy matching si la palabra es lo suficientemente larga
            # Ignora palabras muy cortas (ruido)
            if len(normalized) >= 3 and normalized not in stopwords:
                best_match = process.extractOne(normalized, municipios_normalizados, scorer=fuzz.WRatio)
                
                if best_match and best_match[1] >= 88:  # Score alto
                    best_normalized, score, _ = best_match
                    original_city, _ = municipio_index[best_normalized]
                    found_cities.append(original_city)
                    continue
    
    # Eliminar duplicados preservando orden
    seen = set()
    unique_cities = []
    for city in found_cities:
        normalized_city = normalize_text(city)
        if normalized_city not in seen:
            unique_cities.append(city)
            seen.add(normalized_city)
    
    return unique_cities


# ============================================================================
# FUNCIONES PRINCIPALES DE MATCHING
# ============================================================================

async def match_municipio(
    original: str,
    municipio_index: Dict[str, tuple],
    use_ai: bool = True
) -> Optional[tuple]:
    r"""
    Intenta matchear un municipio en orden:
    1. Exact match
    2. Fuzzy match (score >= 88)
    3. Fuzzy match (score >= 72, con sugerencia)
    4. AI correction (OpenRouter)
    
    Retorna: (municipio_original, departamento, score, source) o None
    """
    normalized = normalize_text(original, preserve_spaces=False)

    # 1️⃣ EXACT MATCH
    if normalized in municipio_index:
        municipio_orig, depto = municipio_index[normalized]
        return (municipio_orig, depto, 100, "exact")

    # 2️⃣ FUZZY MATCH (HIGH CONFIDENCE)
    municipios_list = list(municipio_index.keys())
    best = process.extractOne(normalized, municipios_list, scorer=fuzz.WRatio)

    if best:
        best_match, score, _ = best
        municipio_orig, depto = municipio_index[best_match]

        if score >= 88:
            return (municipio_orig, depto, score, "fuzzy_high")

        if 72 <= score < 88:
            return (municipio_orig, depto, score, "fuzzy_medium")

    # 3️⃣ AI CORRECTION
    if use_ai:
        ai_result = await correct_municipio_with_ai(original, municipio_index)
        if ai_result:
            return ai_result

    return None


async def correct_municipio_with_ai(
    original: str,
    municipio_index: Dict[str, tuple]
) -> Optional[tuple]:
    r"""
    Usa OpenRouter para corregir municipios que fuzzy no pudo matchear.
    Valida que la respuesta esté realmente en el índice.
    """
    if not OPENROUTER_API_KEY:
        return None

    valid_options = list(municipio_index.keys())[:100]

    prompt = f"""
Eres un corrector de municipios colombianos.

REGLAS ESTRICTAS:
- Debes elegir SOLO UN municipio de la lista válida.
- Si no estás seguro, responde {{"municipio": null}}.
- Responde SOLO JSON válido.

LISTA VÁLIDA DE MUNICIPIOS:
{json.dumps(valid_options, ensure_ascii=False)}

ENTRADA DEL USUARIO:
"{original}"

RESPUESTA (SOLO JSON):
{{"municipio": "municipio-normalizado"}}
""".strip()

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "city-matcher-api"
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "Responde únicamente JSON válido."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"].strip()

        # Limpiar markdown
        content = re.sub(r"^```json\s*", "", content)
        content = re.sub(r"^```\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        parsed = json.loads(content)
        municipio_norm = parsed.get("municipio")

        if not municipio_norm or municipio_norm not in municipio_index:
            return None

        municipio_orig, depto = municipio_index[municipio_norm]
        
        best = process.extractOne(municipio_norm, list(municipio_index.keys()), scorer=fuzz.WRatio)
        if best and best[1] >= 88:
            return (municipio_orig, depto, best[1], "ai")

        return None

    except Exception as e:
        print(f"⚠️ AI correction error: {e}")
        return None


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.on_event("startup")
async def load_data_on_startup():
    """Cargar datos de api-colombia.com al iniciar la API"""
    try:
        await fetch_api_colombia_data()
        print("✅ City Matcher API initialized with api-colombia.com data")
    except Exception as e:
        print(f"⚠️ Warning: Failed to load data on startup: {e}")


@app.get("/health")
async def health():
    """Health check endpoint"""
    municipios_loaded = MUNICIPIOS_CACHE is not None
    status = "ok" if municipios_loaded else "loading"
    return {
        "status": status,
        "municipios_cached": municipios_loaded,
        "cache_age_minutes": (datetime.now() - CACHE_TIMESTAMP).total_seconds() / 60 if CACHE_TIMESTAMP else None
    }


@app.get("/departments")
async def get_departments():
    """Retorna lista de departamentos disponibles"""
    municipios_dict, _ = await fetch_api_colombia_data()
    return {
        "count": len(municipios_dict),
        "departments": sorted(municipios_dict.keys())
    }


@app.get("/departments/{department}/municipalities")
async def get_municipalities_by_department(department: str):
    """Retorna municipios de un departamento específico"""
    municipios_dict, _ = await fetch_api_colombia_data()
    
    matching_dept = None
    for dept in municipios_dict.keys():
        if normalize_text(dept) == normalize_text(department):
            matching_dept = dept
            break

    if not matching_dept:
        raise HTTPException(status_code=404, detail=f"Departamento '{department}' no encontrado")

    return {
        "department": matching_dept,
        "count": len(municipios_dict[matching_dept]),
        "municipalities": municipios_dict[matching_dept]
    }


@app.get("/municipalities")
async def get_all_municipalities():
    """Retorna TODOS los municipios de Colombia"""
    municipios_dict, _ = await fetch_api_colombia_data()
    all_municipios = []
    for dept, munis in municipios_dict.items():
        for muni in munis:
            all_municipios.append({
                "municipio": muni,
                "departamento": dept
            })
    return {
        "total": len(all_municipios),
        "municipalities": all_municipios
    }


@app.post("/match-cities")
async def match_cities(payload: MatchRequest) -> MatchResponse:
    r"""
    Endpoint principal de matching.
    
    Modes:
    - all: retorna todos los municipios
    - single: un municipio
    - multiple: lista separada por comas
    
    Search levels:
    - municipio: exactitud máxima (recomendado para scraping)
    - departamento: agrupación de municipios
    """
    
    mode = payload.mode.lower().strip()
    search_level = payload.search_level.lower().strip()

    if mode not in {"all", "single", "multiple"}:
        raise HTTPException(status_code=400, detail="mode debe ser: all | single | multiple")

    if search_level not in {"municipio", "departamento"}:
        raise HTTPException(status_code=400, detail="search_level debe ser: municipio | departamento")

    municipios_dict, municipio_index = await fetch_api_colombia_data()

    # ========== BÚSQUEDA POR MUNICIPIO ==========
    if search_level == "municipio":

        if mode == "all":
            entries = list(municipio_index.keys())
        elif mode == "multiple":
            if not payload.input:
                raise HTTPException(status_code=400, detail="Debe enviar 'input' cuando mode='multiple'")
            # ✅ USAR PARSING INTELIGENTE
            entries = smart_parse_municipalities(payload.input, municipio_index)
        else:
            if not payload.input:
                raise HTTPException(status_code=400, detail="Debe enviar 'input' cuando mode='single'")
            entries = [payload.input.strip()]

        results = []
        selected_locations = []
        rejected = []
        used_ai = False

        for original in entries:
            match = await match_municipio(original, municipio_index, use_ai=payload.use_ai)

            if match and match[3] in {"exact", "fuzzy_high", "ai"}:
                municipio_orig, depto, score, source = match
                results.append(MatchResult(
                    original=original,
                    normalized=normalize_text(original),
                    final_municipio=municipio_orig,
                    departamento=depto,
                    score=score,
                    accepted=True,
                    source=source
                ))
                selected_locations.append({"municipio": municipio_orig, "departamento": depto})
                if source == "ai":
                    used_ai = True

            elif match and match[3] == "fuzzy_medium":
                municipio_orig, depto, score, source = match
                results.append(MatchResult(
                    original=original,
                    normalized=normalize_text(original),
                    final_municipio=municipio_orig,
                    departamento=depto,
                    score=score,
                    accepted=False,
                    source=source,
                    suggestion=municipio_orig,
                    reason="score medio, requiere revisión"
                ))
                rejected.append(original)

            else:
                results.append(MatchResult(
                    original=original,
                    normalized=normalize_text(original),
                    final_municipio=None,
                    departamento=None,
                    score=0,
                    accepted=False,
                    source="rejected",
                    reason="sin coincidencia confiable"
                ))
                rejected.append(original)

        # Eliminar duplicados preservando orden
        unique_locations = []
        seen = set()
        for loc in selected_locations:
            key = (loc["municipio"], loc["departamento"])
            if key not in seen:
                unique_locations.append(loc)
                seen.add(key)

        return MatchResponse(
            mode=mode,
            search_level=search_level,
            total_received=len(entries),
            accepted_count=len(unique_locations),
            rejected_count=len(rejected),
            used_ai=used_ai,
            selected_locations=unique_locations,
            matches=results,
            valid_cities=list(municipio_index.keys()) if payload.return_valid_options else None
        )

    # ========== BÚSQUEDA POR DEPARTAMENTO ==========
    else:
        depto_names = list(municipios_dict.keys())

        if mode == "all":
            entries = depto_names
        elif mode == "multiple":
            if not payload.input:
                raise HTTPException(status_code=400, detail="Debe enviar 'input' cuando mode='multiple'")
            # ✅ PARSING INTELIGENTE PARA DEPARTAMENTOS
            entries = smart_parse_municipalities(payload.input, 
                build_municipio_index({d: [d] for d in depto_names}))
        else:
            if not payload.input:
                raise HTTPException(status_code=400, detail="Debe enviar 'input' cuando mode='single'")
            entries = [payload.input.strip()]

        results = []
        selected_locations = []
        rejected = []

        for original in entries:
            normalized = normalize_text(original)

            best = process.extractOne(normalized, [normalize_text(d) for d in depto_names], scorer=fuzz.WRatio)

            if best:
                best_match_norm, score, idx = best
                matched_depto = depto_names[idx]

                if score >= 88:
                    for municipio in municipios_dict[matched_depto]:
                        selected_locations.append({
                            "municipio": municipio,
                            "departamento": matched_depto
                        })

                    results.append(MatchResult(
                        original=original,
                        normalized=normalized,
                        final_municipio=None,
                        departamento=matched_depto,
                        score=score,
                        accepted=True,
                        source="fuzzy_depto"
                    ))
                    continue

            results.append(MatchResult(
                original=original,
                normalized=normalized,
                final_municipio=None,
                departamento=None,
                score=0,
                accepted=False,
                source="rejected",
                reason="departamento no encontrado"
            ))
            rejected.append(original)

        return MatchResponse(
            mode=mode,
            search_level=search_level,
            total_received=len(entries),
            accepted_count=len(selected_locations),
            rejected_count=len(rejected),
            used_ai=False,
            selected_locations=selected_locations,
            matches=results,
            valid_cities=depto_names if payload.return_valid_options else None
        )


@app.post("/validate-location")
async def validate_single_location(payload: MatchRequest):
    r"""
    Endpoint simplificado: valida UNA ubicación (municipio o departamento).
    Útil para Telegram bot.
    """
    payload.mode = "single"
    return await match_cities(payload)


@app.get("/refresh-cache")
async def refresh_cache():
    """
    Fuerza la recarga de datos desde api-colombia.com.
    """
    global MUNICIPIOS_CACHE, DEPARTAMENTOS_CACHE, CACHE_TIMESTAMP
    MUNICIPIOS_CACHE = None
    DEPARTAMENTOS_CACHE = None
    CACHE_TIMESTAMP = None
    
    municipios_dict, _ = await fetch_api_colombia_data()
    return {
        "status": "cache refreshed",
        "departments": len(municipios_dict),
        "total_municipalities": sum(len(m) for m in municipios_dict.values())
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)






















"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from rapidfuzz import process, fuzz
from typing import List, Optional, Dict
import unicodedata
import re
import os
import json
import httpx
from datetime import datetime, timedelta

app = FastAPI(title="City Matcher API")

# ============================================================================
# CONFIGURACIÓN API COLOMBIA
# ============================================================================

API_COLOMBIA_DEPARTMENTS = "https://api-colombia.com/api/v1/Department"
API_COLOMBIA_CITIES = "https://api-colombia.com/api/v1/City"

# Cache local en memoria
MUNICIPIOS_CACHE = None
DEPARTAMENTOS_CACHE = None
CACHE_TIMESTAMP = None
CACHE_DURATION = timedelta(hours=24)  # Refrescar cada 24h

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# ============================================================================
# MODELOS PYDANTIC
# ============================================================================

class MatchRequest(BaseModel):
    mode: str = Field(default="single", description="all | single | multiple")
    input: Optional[str] = Field(default=None, description="Ciudad o lista separada por comas")
    use_ai: bool = Field(default=True, description="Usar OpenRouter si fuzzy no logra corregir")
    return_valid_options: bool = Field(default=False, description="Retornar lista completa")
    search_level: str = Field(default="municipio", description="municipio | departamento")


class MatchResult(BaseModel):
    original: str
    normalized: str
    final_municipio: Optional[str] = None
    departamento: Optional[str] = None
    score: int
    accepted: bool
    source: str
    suggestion: Optional[str] = None
    reason: Optional[str] = None


class MatchResponse(BaseModel):
    mode: str
    search_level: str
    total_received: int
    accepted_count: int
    rejected_count: int
    used_ai: bool
    selected_locations: List[Dict[str, str]]
    matches: List[MatchResult]
    valid_cities: Optional[List[str]] = None


# ============================================================================
# FUNCIONES DE CARGA API-COLOMBIA
# ============================================================================

async def fetch_api_colombia_data() -> tuple[Dict[str, Dict], Dict[str, tuple]]:
    r""
    Descarga departamentos y ciudades desde api-colombia.com.
    
    Retorna:
        - municipios_dict: {"Antioquia": ["Medellín", "Bello", ...], ...}
        - municipio_index: {"medellin": ("Medellín", "Antioquia"), ...}
    ""
    global MUNICIPIOS_CACHE, DEPARTAMENTOS_CACHE, CACHE_TIMESTAMP

    # Verificar cache vigente
    if MUNICIPIOS_CACHE and DEPARTAMENTOS_CACHE and CACHE_TIMESTAMP:
        if datetime.now() - CACHE_TIMESTAMP < CACHE_DURATION:
            municipio_index = build_municipio_index(MUNICIPIOS_CACHE)
            return MUNICIPIOS_CACHE, municipio_index

    try:
        print("📡 Descargando departamentos de api-colombia.com...")
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Obtener todos los departamentos
            response_depts = await client.get(API_COLOMBIA_DEPARTMENTS)
            response_depts.raise_for_status()
            departamentos = response_depts.json()

        # Obtener todas las ciudades
        print("📡 Descargando ciudades de api-colombia.com...")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response_cities = await client.get(API_COLOMBIA_CITIES)
            response_cities.raise_for_status()
            ciudades = response_cities.json()

        # Construir diccionario: departamento → municipios
        municipios_dict = {}
        departamento_id_map = {}  # Para mapear IDs a nombres

        # 1️⃣ Procesar departamentos
        for dept in departamentos:
            dept_name = dept.get("name", "").strip()
            dept_id = dept.get("id")
            
            if dept_name and dept_id:
                municipios_dict[dept_name] = []
                departamento_id_map[dept_id] = dept_name

        # 2️⃣ Procesar ciudades y asociarlas a departamentos
        for city in ciudades:
            city_name = city.get("name", "").strip()
            dept_id = city.get("departmentId")
            
            if city_name and dept_id and dept_id in departamento_id_map:
                dept_name = departamento_id_map[dept_id]
                municipios_dict[dept_name].append(city_name)

        # Ordenar municipios alfabéticamente
        for dept in municipios_dict:
            municipios_dict[dept].sort()

        # Cachear
        MUNICIPIOS_CACHE = municipios_dict
        DEPARTAMENTOS_CACHE = departamento_id_map
        CACHE_TIMESTAMP = datetime.now()

        print(f"✅ api-colombia.com loaded: {len(municipios_dict)} departamentos, {sum(len(m) for m in municipios_dict.values())} municipios")
        
        municipio_index = build_municipio_index(municipios_dict)
        return municipios_dict, municipio_index

    except Exception as e:
        print(f"❌ Error fetching from api-colombia.com: {e}")
        raise HTTPException(status_code=503, detail="No se pudo conectar a api-colombia.com")


# ============================================================================
# FUNCIONES DE NORMALIZACIÓN
# ============================================================================

def normalize_text(text: str, preserve_spaces: bool = False) -> str:
    r""
    Normaliza texto: minúsculas, acentos, espacios → guiones.
    
    Args:
        preserve_spaces: Si True, mantiene espacios (para comparación).
                         Si False, convierte espacios a guiones.
    ""
    text = text.strip().lower()
    
    # Eliminar acentos
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    
    # Reemplazos
    text = text.replace("_", "-")
    
    if not preserve_spaces:
        text = re.sub(r"\s+", "-", text)
    
    # Remover caracteres no alfanuméricos
    if preserve_spaces:
        text = re.sub(r"[^a-z0-9\-\s]", "", text)
    else:
        text = re.sub(r"[^a-z0-9\-]", "", text)
    
    # Limpiar guiones múltiples
    text = re.sub(r"-+", "-", text)
    
    return text.strip("-").strip()


def build_municipio_index(municipios_dict: Dict[str, List[str]]) -> Dict[str, tuple]:
    r""
    Crea índice: municipio_normalized → (municipio_original, departamento)
    ""
    index = {}
    for depto, municipios in municipios_dict.items():
        for municipio in municipios:
            normalized = normalize_text(municipio, preserve_spaces=False)
            index[normalized] = (municipio, depto)
    return index


# ============================================================================
# FUNCIONES PRINCIPALES DE MATCHING
# ============================================================================

async def match_municipio(
    original: str,
    municipio_index: Dict[str, tuple],
    use_ai: bool = True
) -> Optional[tuple]:
    r""
    Intenta matchear un municipio en orden:
    1. Exact match
    2. Fuzzy match (score >= 88)
    3. Fuzzy match (score >= 72, con sugerencia)
    4. AI correction (OpenRouter)
    
    Retorna: (municipio_original, departamento, score, source) o None
    ""
    normalized = normalize_text(original, preserve_spaces=False)

    # 1️⃣ EXACT MATCH
    if normalized in municipio_index:
        municipio_orig, depto = municipio_index[normalized]
        return (municipio_orig, depto, 100, "exact")

    # 2️⃣ FUZZY MATCH (HIGH CONFIDENCE)
    municipios_list = list(municipio_index.keys())
    best = process.extractOne(normalized, municipios_list, scorer=fuzz.WRatio)

    if best:
        best_match, score, _ = best
        municipio_orig, depto = municipio_index[best_match]

        if score >= 88:
            return (municipio_orig, depto, score, "fuzzy_high")

        if 72 <= score < 88:
            return (municipio_orig, depto, score, "fuzzy_medium")

    # 3️⃣ AI CORRECTION
    if use_ai:
        ai_result = await correct_municipio_with_ai(original, municipio_index)
        if ai_result:
            return ai_result

    return None


async def correct_municipio_with_ai(
    original: str,
    municipio_index: Dict[str, tuple]
) -> Optional[tuple]:
    r""
    Usa OpenRouter para corregir municipios que fuzzy no pudo matchear.
    Valida que la respuesta esté realmente en el índice.
    ""
    if not OPENROUTER_API_KEY:
        return None

    valid_options = list(municipio_index.keys())[:100]  # Top 100 para ahorrar tokens

    prompt = f""
Eres un corrector de municipios colombianos.

REGLAS ESTRICTAS:
- Debes elegir SOLO UN municipio de la lista válida.
- Si no estás seguro, responde {{"municipio": null}}.
- Responde SOLO JSON válido.

LISTA VÁLIDA DE MUNICIPIOS:
{json.dumps(valid_options, ensure_ascii=False)}

ENTRADA DEL USUARIO:
"{original}"

RESPUESTA (SOLO JSON):
{{"municipio": "municipio-normalizado"}}
"".strip()

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "city-matcher-api"
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "Responde únicamente JSON válido."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"].strip()

        # Limpiar markdown
        content = re.sub(r"^```json\s*", "", content)
        content = re.sub(r"^```\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        parsed = json.loads(content)
        municipio_norm = parsed.get("municipio")

        if not municipio_norm or municipio_norm not in municipio_index:
            return None

        municipio_orig, depto = municipio_index[municipio_norm]
        
        best = process.extractOne(municipio_norm, list(municipio_index.keys()), scorer=fuzz.WRatio)
        if best and best[1] >= 88:
            return (municipio_orig, depto, best[1], "ai")

        return None

    except Exception as e:
        print(f"⚠️ AI correction error: {e}")
        return None


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.on_event("startup")
async def load_data_on_startup():
    ""Cargar datos de api-colombia.com al iniciar la API""
    try:
        await fetch_api_colombia_data()
        print("✅ City Matcher API initialized with api-colombia.com data")
    except Exception as e:
        print(f"⚠️ Warning: Failed to load data on startup: {e}")


@app.get("/health")
async def health():
    ""Health check endpoint""
    municipios_loaded = MUNICIPIOS_CACHE is not None
    status = "ok" if municipios_loaded else "loading"
    return {
        "status": status,
        "municipios_cached": municipios_loaded,
        "cache_age_minutes": (datetime.now() - CACHE_TIMESTAMP).total_seconds() / 60 if CACHE_TIMESTAMP else None
    }


@app.get("/departments")
async def get_departments():
    ""Retorna lista de departamentos disponibles""
    municipios_dict, _ = await fetch_api_colombia_data()
    return {
        "count": len(municipios_dict),
        "departments": sorted(municipios_dict.keys())
    }


@app.get("/departments/{department}/municipalities")
async def get_municipalities_by_department(department: str):
    ""Retorna municipios de un departamento específico""
    municipios_dict, _ = await fetch_api_colombia_data()
    
    # Buscar departamento (case-insensitive)
    matching_dept = None
    for dept in municipios_dict.keys():
        if normalize_text(dept) == normalize_text(department):
            matching_dept = dept
            break

    if not matching_dept:
        raise HTTPException(status_code=404, detail=f"Departamento '{department}' no encontrado")

    return {
        "department": matching_dept,
        "count": len(municipios_dict[matching_dept]),
        "municipalities": municipios_dict[matching_dept]
    }


@app.get("/municipalities")
async def get_all_municipalities():
    ""Retorna TODOS los municipios de Colombia""
    municipios_dict, _ = await fetch_api_colombia_data()
    all_municipios = []
    for dept, munis in municipios_dict.items():
        for muni in munis:
            all_municipios.append({
                "municipio": muni,
                "departamento": dept
            })
    return {
        "total": len(all_municipios),
        "municipalities": all_municipios
    }


@app.post("/match-cities")
async def match_cities(payload: MatchRequest) -> MatchResponse:
    r""
    Endpoint principal de matching.
    
    Modes:
    - all: retorna todos los municipios
    - single: un municipio
    - multiple: lista separada por comas
    
    Search levels:
    - municipio: exactitud máxima (recomendado para scraping)
    - departamento: agrupación de municipios
    
    Ejemplo:
    POST /match-cities
    {
        "mode": "multiple",
        "input": "Medellín, Bogotá, Cali",
        "search_level": "municipio",
        "use_ai": true
    }
    ""
    
    mode = payload.mode.lower().strip()
    search_level = payload.search_level.lower().strip()

    if mode not in {"all", "single", "multiple"}:
        raise HTTPException(status_code=400, detail="mode debe ser: all | single | multiple")

    if search_level not in {"municipio", "departamento"}:
        raise HTTPException(status_code=400, detail="search_level debe ser: municipio | departamento")

    municipios_dict, municipio_index = await fetch_api_colombia_data()

    # ========== BÚSQUEDA POR MUNICIPIO ==========
    if search_level == "municipio":

        if mode == "all":
            entries = list(municipio_index.keys())
        elif mode == "multiple":
            if not payload.input:
                raise HTTPException(status_code=400, detail="Debe enviar 'input' cuando mode='multiple'")
            #entries = [p.strip() for p in payload.input.split(",") if p.strip()]
            entries = re.split(r"[,\s]+", payload.input)
            entries = [e.strip() for e in entries if e.strip()]
            entries = list(dict.fromkeys(entries))  # eliminar duplicados
        else:
            if not payload.input:
                raise HTTPException(status_code=400, detail="Debe enviar 'input' cuando mode='single'")
            entries = [payload.input.strip()]

        results = []
        selected_locations = []
        rejected = []
        used_ai = False

        for original in entries:
            match = await match_municipio(original, municipio_index, use_ai=payload.use_ai)

            if match and match[3] in {"exact", "fuzzy_high", "ai"}:
                municipio_orig, depto, score, source = match
                results.append(MatchResult(
                    original=original,
                    normalized=normalize_text(original),
                    final_municipio=municipio_orig,
                    departamento=depto,
                    score=score,
                    accepted=True,
                    source=source
                ))
                selected_locations.append({"municipio": municipio_orig, "departamento": depto})
                if source == "ai":
                    used_ai = True

            elif match and match[3] == "fuzzy_medium":
                municipio_orig, depto, score, source = match
                results.append(MatchResult(
                    original=original,
                    normalized=normalize_text(original),
                    final_municipio=municipio_orig,
                    departamento=depto,
                    score=score,
                    accepted=False,
                    source=source,
                    suggestion=municipio_orig,
                    reason="score medio, requiere revisión"
                ))
                rejected.append(original)

            else:
                results.append(MatchResult(
                    original=original,
                    normalized=normalize_text(original),
                    final_municipio=None,
                    departamento=None,
                    score=0,
                    accepted=False,
                    source="rejected",
                    reason="sin coincidencia confiable"
                ))
                rejected.append(original)

        # Eliminar duplicados preservando orden
        unique_locations = []
        seen = set()
        for loc in selected_locations:
            key = (loc["municipio"], loc["departamento"])
            if key not in seen:
                unique_locations.append(loc)
                seen.add(key)

        return MatchResponse(
            mode=mode,
            search_level=search_level,
            total_received=len(entries),
            accepted_count=len(unique_locations),
            rejected_count=len(rejected),
            used_ai=used_ai,
            selected_locations=unique_locations,
            matches=results,
            valid_cities=list(municipio_index.keys()) if payload.return_valid_options else None
        )

    # ========== BÚSQUEDA POR DEPARTAMENTO ==========
    else:
        depto_names = list(municipios_dict.keys())

        if mode == "all":
            entries = depto_names
        elif mode == "multiple":
            if not payload.input:
                raise HTTPException(status_code=400, detail="Debe enviar 'input' cuando mode='multiple'")
            #entries = [p.strip() for p in payload.input.split(",") if p.strip()]
            entries = re.split(r"[,\s]+", payload.input)
            entries = [e.strip() for e in entries if e.strip()]
            entries = list(dict.fromkeys(entries))  # eliminar duplicados
        else:
            if not payload.input:
                raise HTTPException(status_code=400, detail="Debe enviar 'input' cuando mode='single'")
            entries = [payload.input.strip()]

        results = []
        selected_locations = []
        rejected = []

        for original in entries:
            normalized = normalize_text(original)

            best = process.extractOne(normalized, [normalize_text(d) for d in depto_names], scorer=fuzz.WRatio)

            if best:
                best_match_norm, score, idx = best
                matched_depto = depto_names[idx]

                if score >= 88:
                    # Retornar TODOS los municipios del departamento
                    for municipio in municipios_dict[matched_depto]:
                        selected_locations.append({
                            "municipio": municipio,
                            "departamento": matched_depto
                        })

                    results.append(MatchResult(
                        original=original,
                        normalized=normalized,
                        final_municipio=None,
                        departamento=matched_depto,
                        score=score,
                        accepted=True,
                        source="fuzzy_depto"
                    ))
                    continue

            results.append(MatchResult(
                original=original,
                normalized=normalized,
                final_municipio=None,
                departamento=None,
                score=0,
                accepted=False,
                source="rejected",
                reason="departamento no encontrado"
            ))
            rejected.append(original)

        return MatchResponse(
            mode=mode,
            search_level=search_level,
            total_received=len(entries),
            accepted_count=len(selected_locations),
            rejected_count=len(rejected),
            used_ai=False,
            selected_locations=selected_locations,
            matches=results,
            valid_cities=depto_names if payload.return_valid_options else None
        )


@app.post("/validate-location")
async def validate_single_location(payload: MatchRequest):
    r""
    Endpoint simplificado: valida UNA ubicación (municipio o departamento).
    Útil para Telegram bot.
    
    Ejemplo:
    POST /validate-location
    {
        "input": "medellin",
        "search_level": "municipio"
    }
    ""
    payload.mode = "single"
    return await match_cities(payload)


@app.get("/refresh-cache")
async def refresh_cache():
    ""
    Fuerza la recarga de datos desde api-colombia.com.
    Útil para actualizar manualmente si cambios en los datos.
    ""
    global MUNICIPIOS_CACHE, DEPARTAMENTOS_CACHE, CACHE_TIMESTAMP
    MUNICIPIOS_CACHE = None
    DEPARTAMENTOS_CACHE = None
    CACHE_TIMESTAMP = None
    
    municipios_dict, _ = await fetch_api_colombia_data()
    return {
        "status": "cache refreshed",
        "departments": len(municipios_dict),
        "total_municipalities": sum(len(m) for m in municipios_dict.values())
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)



"""