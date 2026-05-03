import re
import unicodedata


_ABREVIACIONES_DIR = [
    (r'\bCRA?\.?\b', 'CARRERA'),
    (r'\bCLL?\b\.?', 'CALLE'),
    (r'\bCL\b\.?', 'CALLE'),
    (r'\bTV\b\.?', 'TRANSVERSAL'),
    (r'\bTRANSV\.?\b', 'TRANSVERSAL'),
    (r'\bAVDAS?\b\.?', 'AVENIDA'),
    (r'\bAV\b\.?', 'AVENIDA'),
    (r'\bDIAG\.?\b', 'DIAGONAL'),
    (r'\bDG\b\.?', 'DIAGONAL'),
    (r'\bMZ\b\.?', 'MANZANA'),
    (r'\bBRR?IO?\b\.?', 'BARRIO'),
    (r'\bKM\b\.?', 'KILOMETRO'),
    (r'\bVDA\b\.?', 'VEREDA'),
    (r'\bAP(TO|T)?\b\.?', 'APARTAMENTO'),
    (r'\bLT\b\.?', 'LOTE'),
    (r'\bBLQ?\b\.?', 'BLOQUE'),
    (r'\bCS(A)?\b\.?', 'CASA'),
    (r'\bED(F|IF)?\b\.?', 'EDIFICIO'),
    (r'\bPISO\b', 'PISO'),
    (r'\bOF\b\.?', 'OFICINA'),
]

_ABREVIACIONES_COMPILADAS = [
    (re.compile(patron, re.IGNORECASE), reemplazo)
    for patron, reemplazo in _ABREVIACIONES_DIR
]


def quitar_tildes(texto: str) -> str:
    nfkd = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_nombre(texto) -> str:
    if not isinstance(texto, str) or not texto.strip():
        return ''
    texto = quitar_tildes(texto.upper().strip())
    texto = re.sub(r'[^\w\s]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto


def normalizar_direccion(texto) -> str:
    if not isinstance(texto, str) or not texto.strip():
        return ''
    texto = quitar_tildes(texto.upper().strip())
    texto = re.sub(r'[#\-°]', ' ', texto)
    for patron, reemplazo in _ABREVIACIONES_COMPILADAS:
        texto = patron.sub(reemplazo, texto)
    texto = re.sub(r'[^\w\s]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto


def normalizar_municipio(texto) -> str:
    if not isinstance(texto, str) or not texto.strip():
        return ''
    texto = quitar_tildes(texto.upper().strip())
    texto = texto.replace('-', ' ')
    texto = re.sub(r'[^\w\s]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto
