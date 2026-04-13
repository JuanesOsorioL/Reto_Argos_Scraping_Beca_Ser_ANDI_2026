# Motor de puntuación (Scoring) para filtrar negocios relevantes para Argos

# +3 puntos — Directamente relacionados con el catálogo de Argos
PRIORIDAD_ALTA = [
    "cemento", "concreto", "mortero", "agregado", "agregados",
    "obra gris", "prefabricado", "prefabricados", "bloquera", "bloques",
    "ladrillos", "ladrillera", "deposito de materiales", "depósito de materiales"
]

# +2 puntos — Muy probablemente venden materiales de construcción
PRIORIDAD_MEDIA = [
    "ferreteria", "ferretería", "materiales", "construccion", "construcción",
    "deposito", "depósito", "hierro", "corralon", "corralón",
    "arena", "grava", "triturado", "distribuidor", "distribuidora"
]

# +1 punto — Pueden ser relevantes pero necesitan confirmación de otras palabras
PRIORIDAD_BAJA = [
    "constructora", "acabados", "proveedor", "suministros", "estructuras"
]

# -3 puntos — Negocios técnicos de servicio que NO compran materiales a granel
KEYWORDS_MALAS = [
    "cerrajeria", "cerrajería",
    "pintura decorativa", "pinturas decorativas",
    "plomería residencial", "plomeria residencial",
    "mecanico", "mecánico", "taller automotriz",
    "restaurante", "comidas", "supermercado", "tienda de ropa"
]

def evaluar_cliente_argos(nombre: str, descripcion: str, keyword_busqueda: str = ""):
    """
    Calcula el score del negocio basado en el nombre, descripción y
    el keyword de búsqueda con el que fue encontrado (contexto extra).
    Retorna una tupla (aprobado: bool, score: int).
    La regla de negocio dice que un score >= 2 es válido para Argos.
    """
    # Incluimos el keyword de búsqueda como contexto extra para el scoring.
    # Ejemplo: si lo encontramos buscando "cemento", eso ya es una señal positiva.
    keyword_limpio = keyword_busqueda.replace("-", " ").lower()
    texto = f"{nombre} {descripcion} {keyword_limpio}".lower()
    score = 0
    
    # +3 puntos — Alta relevancia Argos
    for k in PRIORIDAD_ALTA:
        if k in texto:
            score += 3
            
    # +2 puntos — Media relevancia (ferreteria ahora vale 2, no 1)
    for k in PRIORIDAD_MEDIA:
        if k in texto:
            score += 2
            
    # +1 punto — Baja relevancia (señal débil, necesita confirmación)
    for k in PRIORIDAD_BAJA:
        if k in texto:
            score += 1
            
    # -3 puntos — Descalificadores claros (servicios técnicos puros)
    for k in KEYWORDS_MALAS:
        if k in texto:
            score -= 3
            
    aprobado = score >= 2
    return aprobado, score
