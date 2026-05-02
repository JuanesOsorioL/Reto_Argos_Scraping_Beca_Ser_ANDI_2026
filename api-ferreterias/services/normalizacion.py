"""
services/normalizacion.py - Normalización de datos empresariales
"""

import re
import unicodedata
from typing import Optional
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


def quitar_tildes(texto: str) -> str:
    """Quita tildes y caracteres diacríticos"""
    nfkd = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


PALABRAS_JURIDICAS = {
    'sas', 'sas.', 's.a.s', 's a s', 'ltda', 'limitada', 'sa', 's.a',
    'cia', 'compania', 'compañia', 'sociedad', 'anonima', 'anonima',
    'eirl', 'spa', 'asociacion', 'asociacion', 'empresa',
    'eu', 'e.u', 'sociedad anonima', 'and cia', '& cia',
}

ABBREV_CALLE = {
    r'\bcra\b': 'carrera',
    r'\bcr\b': 'carrera',
    r'\bkr\b': 'carrera',
    r'\bcl\b': 'calle',
    r'\bclle\b': 'calle',
    r'\bcll\b': 'calle',
    r'\bav\b': 'avenida',
    r'\bavda\b': 'avenida',
    r'\bdg\b': 'diagonal',
    r'\btv\b': 'transversal',
    r'\bno\.\s*': '# ',
    r'\bnro\.\s*': '# ',
    r'\bnum\.\s*': '# ',
    r'\bnumero\b': '#',
}

# Prioridades de fuentes para selección de datos
PRIORIDAD_FUENTES = {
    'rues': 1,
    'serper': 2,
    'google_maps': 3,
    'paginas_amarillas': 4,
    'overpass': 5,
    'foursquare': 6,
}

PRIORIDAD_NOMBRE_COMERCIAL = {
    'google_maps': 1,
    'paginas_amarillas': 2,
    'foursquare': 3,
    'serper': 4,
    'rues': 5,
    'overpass': 6,
}


def normalizar_nombre(nombre: Optional[str]) -> Optional[str]:
    """
    Normaliza nombre de empresa:
    - Minúsculas
    - Quita tildes
    - Quita palabras jurídicas
    - Normaliza espacios
    """
    if not nombre or not nombre.strip():
        return None

    n = quitar_tildes(nombre.lower().strip())
    # Quitar formas jurídicas con puntos ANTES de eliminar puntuación
    n = re.sub(r'\bs\.a\.s\.?\b', ' ', n)
    n = re.sub(r'\bs\.a\.?\b', ' ', n)
    n = re.sub(r'\be\.u\.?\b', ' ', n)
    n = re.sub(r'[.,;:\-*()]+', ' ', n)

    palabras = n.split()
    palabras_filtradas = [p for p in palabras if p and p not in PALABRAS_JURIDICAS]
    n = ' '.join(palabras_filtradas)
    n = re.sub(r'\s+', ' ', n).strip()

    return n if n else None


def normalizar_telefono(telefono: Optional[str]) -> Optional[str]:
    """
    Normaliza teléfono colombiano:
    - Quita +57, 57 al inicio
    - Quita espacios, guiones, paréntesis
    - Solo dígitos
    - Valida longitud >= 7
    """
    if not telefono or not telefono.strip():
        return None

    t = re.sub(r'[\s\-()]+', '', telefono.strip())

    if t.startswith('+57'):
        t = t[3:]
    elif t.startswith('57') and len(t) > 10:
        t = t[2:]

    t = re.sub(r'\D', '', t)

    if len(t) < 7:
        return None

    # Truncar a 10 dígitos si viene largo
    if len(t) > 10:
        t = t[-10:]

    return t


def normalizar_correo(correo: Optional[str]) -> Optional[str]:
    """
    Normaliza email:
    - Minúsculas
    - Trim
    - Valida formato básico
    """
    if not correo or not correo.strip():
        return None

    c = correo.lower().strip()
    regex = r'^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$'
    if not re.match(regex, c):
        return None

    return c


def normalizar_direccion(direccion: Optional[str]) -> Optional[str]:
    """
    Normaliza dirección colombiana:
    - Minúsculas
    - Expande abreviaturas
    - Normaliza espacios
    """
    if not direccion or not direccion.strip():
        return None

    d = quitar_tildes(direccion.lower().strip())

    for patron, reemplazo in ABBREV_CALLE.items():
        d = re.sub(patron, reemplazo, d)

    d = re.sub(r'\s+', ' ', d).strip()
    return d if d else None


def normalizar_municipio(municipio: Optional[str]) -> Optional[str]:
    """Normaliza municipio para matching"""
    if not municipio or not municipio.strip():
        return None
    m = quitar_tildes(municipio.lower().strip())
    m = re.sub(r'[.,;:]', '', m)
    m = re.sub(r'\s+', ' ', m).strip()
    return m if m else None


def clasificar_telefono(telefono: str) -> str:
    """Clasifica teléfono como celular, fijo o desconocido"""
    if not telefono or len(telefono) < 7:
        return 'desconocido'
    if telefono.startswith('3') and len(telefono) == 10:
        return 'celular'
    if (telefono.startswith('60') or telefono.startswith('6')) and len(telefono) == 10:
        return 'fijo'
    return 'desconocido'


def crear_match_key_nombre_municipio(nombre: Optional[str], municipio: Optional[str]) -> Optional[str]:
    """Crea clave de matching combinada nombre+municipio"""
    n = nombre or ''
    m = municipio or ''
    if not n and not m:
        return None
    return f"{n}|{m}"


# ─── Funciones que ejecutan normalización en la DB ───────────────────────────

def normalizar_staging(db) -> dict:
    """
    Ejecuta normalización sobre staging.empresas_unificadas.
    Retorna conteo de registros normalizados.
    """
    logger.info("🔄 Iniciando normalización de staging...")
    conteos = {}

    # Normalizar nombres (quita tildes, siglas jurídicas, liquidación y puntuación)
    db.execute(text(r"""
        UPDATE staging.empresas_unificadas
        SET nombre_normalizado = trim(regexp_replace(
            regexp_replace(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            lower(unaccent(coalesce(nombre_original, razon_social_original, ''))),
                            -- 1. Quitar frases de liquidacion (unaccent ya convirtio la o acentuada)
                            'en liquidacion(\s+judicial)?', '', 'g'
                        ),
                        -- 2. Formas con puntos Y/O espacios: s.a.s, s a s, s a.s., s.a, s a, e.u, e u
                        '(^|[\s])s[\s.]*a[\s.]*s[\s.]*([\s]|$)|(^|[\s])s[\s.]*a[\s.]*([\s]|$)|(^|[\s])e[\s.]*u[\s.]*([\s]|$)', ' ', 'gi'
                    ),
                    -- 3. Siglas y palabras jurídicas completas
                    '\m(sas|sa|ltda|limitada|cia|compania|spa|eirl|eu|empresa|asociacion)\M', ' ', 'gi'
                ),
                -- 4. Puntuación incluyendo & y comillas ASCII
                '[.,;:\-*()/&"]+', ' ', 'g'
            ),
            '\s+', ' ', 'g'
        ))
        WHERE nombre_original IS NOT NULL OR razon_social_original IS NOT NULL
    """))
    conteos['nombres'] = db.execute(
        text("SELECT COUNT(*) FROM staging.empresas_unificadas WHERE nombre_normalizado IS NOT NULL")
    ).scalar()
    logger.info(f"  ✓ Nombres normalizados: {conteos['nombres']}")

    # Normalizar teléfonos
    db.execute(text("""
        UPDATE staging.empresas_unificadas
        SET telefono_normalizado = (
            SELECT regexp_replace(
                regexp_replace(telefono_original, '[+]?57', '', 'g'),
                '[^0-9]', '', 'g'
            )
        )
        WHERE telefono_original IS NOT NULL
          AND length(regexp_replace(regexp_replace(telefono_original, '[+]?57', ''), '[^0-9]', '', 'g')) >= 7
    """))
    conteos['telefonos'] = db.execute(
        text("SELECT COUNT(*) FROM staging.empresas_unificadas WHERE telefono_normalizado IS NOT NULL")
    ).scalar()
    logger.info(f"  ✓ Teléfonos normalizados: {conteos['telefonos']}")

    # Normalizar correos
    db.execute(text(r"""
        UPDATE staging.empresas_unificadas
        SET correo_normalizado = lower(trim(correo_original))
        WHERE correo_original IS NOT NULL
          AND lower(trim(correo_original)) ~* '^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$'
    """))
    conteos['correos'] = db.execute(
        text("SELECT COUNT(*) FROM staging.empresas_unificadas WHERE correo_normalizado IS NOT NULL")
    ).scalar()
    logger.info(f"  ✓ Correos normalizados: {conteos['correos']}")

    # Normalizar municipios usando ref si está disponible
    db.execute(text("""
        UPDATE staging.empresas_unificadas s
        SET municipio_norm = r.municipio_norm,
            departamento_norm = r.departamento_norm,
            codigo_dane_municipio = r.codigo_dane_municipio
        FROM ref.municipios_colombia r
        WHERE unaccent(lower(trim(s.municipio_original))) = r.municipio_norm
          AND s.municipio_original IS NOT NULL
    """))

    # Municipios que no matchearon → normalización básica
    db.execute(text("""
        UPDATE staging.empresas_unificadas
        SET municipio_norm = unaccent(lower(trim(municipio_original))),
            departamento_norm = unaccent(lower(trim(departamento_original)))
        WHERE municipio_norm IS NULL
          AND municipio_original IS NOT NULL
    """))
    conteos['municipios'] = db.execute(
        text("SELECT COUNT(*) FROM staging.empresas_unificadas WHERE municipio_norm IS NOT NULL")
    ).scalar()
    logger.info(f"  ✓ Municipios normalizados: {conteos['municipios']}")

    # Normalizar direcciones
    db.execute(text("""
        UPDATE staging.empresas_unificadas
        SET direccion_normalizada = unaccent(lower(trim(direccion_original)))
        WHERE direccion_original IS NOT NULL
    """))
    conteos['direcciones'] = db.execute(
        text("SELECT COUNT(*) FROM staging.empresas_unificadas WHERE direccion_normalizada IS NOT NULL")
    ).scalar()
    logger.info(f"  ✓ Direcciones normalizadas: {conteos['direcciones']}")

    # Crear match keys
    db.execute(text("""
        UPDATE staging.empresas_unificadas
        SET match_key_nit = regexp_replace(nit, '[^0-9]', '', 'g'),
            match_key_email = correo_normalizado,
            match_key_telefono = telefono_normalizado,
            match_key_nombre_municipio = concat(nombre_normalizado, '|', coalesce(municipio_norm, ''))
        WHERE TRUE
    """))
    logger.info("  ✓ Match keys creados")

    db.commit()
    logger.info("✅ Normalización completada")
    return conteos
