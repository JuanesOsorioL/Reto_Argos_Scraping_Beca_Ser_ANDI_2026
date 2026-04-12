"""
filter_engine.py — Motor de scoring Argos
Nota de arquitectura: este motor se ejecuta durante la extracción (capa RAW)
para un filtrado rápido, pero el score puede recalcularse en la capa STAGING
si se ajustan las reglas sin necesidad de volver a hacer scraping.
"""


def calcular_score_argos(nombre: str, categorias: list, keyword_busqueda: str = "") -> tuple:
    """
    Motor de puntuación basado en reglas Argos.
    Retorna (score: int, aprobado: bool).

    Reglas:
    - palabras_positivas_alta:  +3 pts  (alta relevancia para Argos)
    - palabras_positivas_media: +2 pts  (relevancia media, negocios válidos)
    - palabras_negativas:       -5 pts  (descalificadores duros)

    Umbral de aprobación: score >= 2
    """
    text_to_search = f"{nombre} {' '.join(categorias)} {keyword_busqueda}".lower()
    score = 0

    # ✅ Alta relevancia — productos que Argos vende directamente
    palabras_positivas_alta = [
        "cemento", "concreto", "premezclado", "mortero", "morteros",
        "agregados", "arena", "balasto", "obra gris", "bloquera",
        "ladrillera", "prefabricado", "distribuidor de cemento",
        "material de construccion", "materiales de construccion",
        "deposito de materiales", "deposito y ferreteria",
        "ferredeposito", "ferredepositos", "centro ferretero",
        "bodegas de construccion", "hierro y cemento", "cementos argos"
    ]

    # ✅ Relevancia media — negocios que compran materiales de construcción
    palabras_positivas_media = [
        "ferreteria", "ferreterias", "ferretero", "materiales",
        "construccion", "deposito", "bloques", "hierro",
        "ferreteria y deposito", "construcciones", "contratista",
        "obra", "ladrillo"
    ]

    # ❌ Descalificadores — negocios irrelevantes para Argos
    palabras_negativas = [
        "cerrajeria", "cerrajero", "pinturas", "pintura",
        "electricos", "electricista", "ornamentacion", "ornamentador",
        "alquiler de equipos", "ropa", "comida", "taxis",
        "salon de belleza", "restaurante", "supermercado",
        "vidrios", "vidrieria", "plomeria", "fontaneria",
        "refrigeracion", "aires acondicionados"
    ]

    for word in palabras_positivas_alta:
        if word in text_to_search:
            score += 3

    for word in palabras_positivas_media:
        if word in text_to_search:
            score += 2

    for word in palabras_negativas:
        if word in text_to_search:
            score -= 5

    aprobado = score >= 2
    return score, aprobado