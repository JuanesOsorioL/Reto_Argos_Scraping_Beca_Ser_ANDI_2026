"""
normalizer.py — Limpieza de campos antes de guardar en BD
Centraliza toda la normalización para que sea fácil ajustar después.
"""
import re
import hashlib


def normalizar_telefono(telefono_raw: str) -> tuple:
    """
    Recibe un string con uno o más teléfonos separados por ' / '
    Retorna (telefono_principal, telefonos_adicionales)

    Ejemplo entrada:  "(+57) 300 8730567 / (+57) 604 3222637"
    Ejemplo salida:   ("+573008730567", "+576043222637")
    """
    if not telefono_raw:
        return "", ""

    partes = [p.strip() for p in telefono_raw.split("/")]
    limpios = []
    for parte in partes:
        # Quitar todo menos dígitos y +
        numero = re.sub(r'[^\d]', '', parte)
        if not numero:
            continue
        # Si empieza con 57 y tiene 12 dígitos → agregar +
        if numero.startswith("57") and len(numero) == 12:
            numero = f"+{numero}"
        # Si es número móvil colombiano de 10 dígitos → agregar +57
        elif numero.startswith("3") and len(numero) == 10:
            numero = f"+57{numero}"
        # Si es fijo colombiano de 10 dígitos (área + número)
        elif len(numero) == 10:
            numero = f"+57{numero}"
        # Si es fijo de 7 dígitos (sin área) → dejar como está
        limpios.append(numero)

    if not limpios:
        return "", ""

    principal   = limpios[0]
    adicionales = " / ".join(limpios[1:]) if len(limpios) > 1 else ""
    return principal, adicionales


def normalizar_whatsapp(wa_raw: str) -> str:
    """
    Convierte URL de WhatsApp a número limpio.
    Entrada:  "https://wa.me/573008730567"
    Salida:   "+573008730567"
    """
    if not wa_raw:
        return ""
    if wa_raw.startswith("https://wa.me/"):
        numero = wa_raw.replace("https://wa.me/", "").strip()
        return f"+{numero}" if not numero.startswith("+") else numero
    # Si ya es número directo
    if wa_raw.startswith("+") or wa_raw.isdigit():
        return wa_raw
    return wa_raw


def normalizar_coordenadas(lat_raw, lon_raw) -> tuple:
    """Convierte latitud y longitud a float. Retorna (0.0, 0.0) si falla."""
    try:
        lat = float(lat_raw) if lat_raw else 0.0
        lon = float(lon_raw) if lon_raw else 0.0
        return lat, lon
    except (ValueError, TypeError):
        return 0.0, 0.0


def normalizar_categoria(categoria_raw: str) -> str:
    """
    Convierte keyword con guiones a texto legible.
    Entrada:  "materiales-para-construccion"
    Salida:   "materiales para construccion"
    """
    if not categoria_raw:
        return ""
    return categoria_raw.replace("-", " ").strip()


def generar_hash(url: str, sucursal_tipo: str = "") -> str:
    """
    Genera hash único por URL + tipo de sucursal.
    Así dos sucursales de la misma empresa tienen hash diferente.
    """
    clave = f"{url}||{sucursal_tipo}".lower().strip()
    return hashlib.md5(clave.encode("utf-8")).hexdigest()