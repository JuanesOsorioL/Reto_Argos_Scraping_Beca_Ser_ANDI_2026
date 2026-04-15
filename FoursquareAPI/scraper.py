"""
scraper.py — Scraper de Foursquare Places API
Detección de:
  - 403: Rate limit alcanzado
  - 401: API key inválida
  - 400: Parámetros inválidos
  - Otros: Reintentos exponenciales
"""
import requests
import time
from config import (
    FSQ_BASE_URL, FSQ_HEADERS, FSQ_FIELDS,
    REQUEST_DELAY, MAX_RETRIES, LIMIT_POR_PAG, MAX_POR_QUERY,
    parse_rate_limit_header, get_seconds_until_reset, DEBUG
)


class RateLimitException(Exception):
    """Se lanza cuando se detecta 403 (rate limit)."""
    def __init__(self, message: str, reset_timestamp: int = None):
        self.message = message
        self.reset_timestamp = reset_timestamp
        super().__init__(self.message)


class AuthException(Exception):
    """Se lanza cuando hay error de autenticación (401)."""
    pass


def safe_request(url: str, params: dict) -> dict | None:
    """
    Realiza request a Foursquare con reintentos y manejo de rate limit.
    
    Args:
        url: URL del endpoint
        params: Parámetros de la búsqueda
    
    Returns:
        dict: Respuesta JSON, o None si error definitivo
    
    Raises:
        RateLimitException: Si se alcanza 403 (rate limit)
        AuthException: Si API key es inválida (401)
    """
    wait = 1  # Espera inicial en segundos
    
    for attempt in range(MAX_RETRIES):
        try:
            if DEBUG:
                print(f"    [DEBUG] Request intento {attempt + 1}/{MAX_RETRIES}")
            
            response = requests.get(
                url,
                headers=FSQ_HEADERS,
                params=params,
                timeout=30
            )
            
            # DEBUG: Imprimir información de rate limit
            if DEBUG:
                remaining, reset = parse_rate_limit_header(response.headers)
                print(f"    [DEBUG] Status: {response.status_code}")
                print(f"    [DEBUG] Rate limit remaining: {remaining}")
            
            # ──────────────────────────────────────────────────────────────
            # 200: Éxito ✅
            # ──────────────────────────────────────────────────────────────
            if response.status_code == 200:
                return response.json()
            
            # ──────────────────────────────────────────────────────────────
            # 403: Rate Limit alcanzado 🛑
            # ──────────────────────────────────────────────────────────────
            elif response.status_code == 403:
                remaining, reset = parse_rate_limit_header(response.headers)
                
                # Verificar si es por rate limit o por créditos insuficientes
                body = response.text.lower()
                if "no api credits" in body or "billing" in body or "plan" in body:
                    print("    [FSQ] ❌ 403: Sin créditos/plan insuficiente (no se puede recuperar)")
                    return None
                
                # Es rate limit real
                print(f"    [FSQ] ⚠️  403: Rate limit alcanzado")
                print(f"    [FSQ] Requests restantes: {remaining}")
                if reset > 0:
                    seconds_wait = get_seconds_until_reset(reset)
                    print(f"    [FSQ] Reset en {seconds_wait} segundos (~{seconds_wait//60} minutos)")
                    raise RateLimitException(
                        f"Rate limit alcanzado. Reset en {seconds_wait}s",
                        reset_timestamp=reset
                    )
                else:
                    raise RateLimitException("Rate limit alcanzado (reset timestamp unknown)")
            
            # ──────────────────────────────────────────────────────────────
            # 401: Autenticación fallida 🔐
            # ──────────────────────────────────────────────────────────────
            elif response.status_code == 401:
                print(f"    [FSQ] ❌ 401: API key inválida")
                print(f"    [FSQ] Respuesta: {response.text[:200]}")
                raise AuthException("API key inválida. Revisa FSQ_API_KEY en .env")
            
            # ──────────────────────────────────────────────────────────────
            # 400: Parámetros inválidos
            # ──────────────────────────────────────────────────────────────
            elif response.status_code == 400:
                print(f"    [FSQ] ❌ 400: Parámetros inválidos")
                print(f"    [FSQ] {response.text[:300]}")
                return None
            
            # ──────────────────────────────────────────────────────────────
            # 404: No encontrado
            # ──────────────────────────────────────────────────────────────
            elif response.status_code == 404:
                print(f"    [FSQ] 404: Endpoint no encontrado")
                return None
            
            # ──────────────────────────────────────────────────────────────
            # 429: Too Many Requests (diferente de 403)
            # ──────────────────────────────────────────────────────────────
            elif response.status_code == 429:
                print(f"    [FSQ] ⚠️  429: Too many requests. Esperando {wait}s...")
                time.sleep(wait)
                wait = min(wait * 2, 60)
                continue
            
            # ──────────────────────────────────────────────────────────────
            # Otros errores: Reintentos exponenciales
            # ──────────────────────────────────────────────────────────────
            else:
                print(f"    [FSQ] ⚠️  {response.status_code}: Error temporal")
                if DEBUG:
                    print(f"    [DEBUG] {response.text[:200]}")
                time.sleep(wait)
                wait = min(wait * 2, 60)
                continue
        
        except RateLimitException:
            # Re-lanzar para que el caller lo maneje
            raise
        except AuthException:
            # Re-lanzar para que el caller lo maneje
            raise
        except requests.Timeout:
            print(f"    [FSQ] ⏱️  Timeout. Reintentando en {wait}s...")
            time.sleep(wait)
            wait *= 2
        except requests.ConnectionError:
            print(f"    [FSQ] 🔌 Error conexión. Reintentando en {wait}s...")
            time.sleep(wait)
            wait *= 2
        except Exception as e:
            print(f"    [FSQ] ❌ Error inesperado: {e}")
            time.sleep(wait)
            wait *= 2
    
    print(f"    [FSQ] ❌ Agotados {MAX_RETRIES} intentos. Abortando.")
    return None


def buscar_lugares(keyword: str, near: str, max_resultados: int = MAX_POR_QUERY) -> list:
    """
    Busca lugares en Foursquare con paginación.
    
    Args:
        keyword: Qué buscar (ej: "ferretería")
        near: Dónde buscar (ej: "Bogotá, Colombia")
        max_resultados: Máximo número de resultados a retornar
    
    Returns:
        list: Resultados de la búsqueda
    
    Raises:
        RateLimitException: Si se alcanza 403
        AuthException: Si API key es inválida
    """
    todos = []
    offset = 0
    
    print(f"  [FSQ] Buscando '{keyword}' en {near}...")
    
    while len(todos) < max_resultados:
        # Parámetros para esta página
        params = {
            "query": keyword,
            "near": near,
            "limit": LIMIT_POR_PAG,  # 50
            "offset": offset,
            "fields": FSQ_FIELDS,
        }
        
        # Realizar request (puede lanzar RateLimitException)
        data = safe_request(FSQ_BASE_URL, params)
        if not data:
            print(f"    [FSQ] ❌ Búsqueda falló")
            break
        
        # Extraer resultados
        resultados = data.get("results", [])
        if not resultados:
            print(f"    [FSQ] ✓ Sin más resultados (total: {len(todos)})")
            break
        
        todos.extend(resultados)
        print(f"    [FSQ] +{len(resultados)} resultados (total: {len(todos)}/{max_resultados})")
        
        # Si obtuvimos menos que el límite, no hay más páginas
        if len(resultados) < LIMIT_POR_PAG:
            print(f"    [FSQ] ✓ Última página alcanzada")
            break
        
        # Siguiente página
        offset += LIMIT_POR_PAG
        time.sleep(REQUEST_DELAY)  # Retraso entre requests
    
    return todos[:max_resultados]
