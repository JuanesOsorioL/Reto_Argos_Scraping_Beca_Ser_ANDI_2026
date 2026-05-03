import os
import pandas as pd
import psycopg2
from rapidfuzz import fuzz, process

from utils.ciudades import CIUDADES, CIUDAD_DEPARTAMENTO
from utils.normalizar import normalizar_nombre, normalizar_direccion, normalizar_municipio

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:1234@localhost:1111/postgres')

# Columnas de la BD de Argos (Google Sheets export)
_COL_CODIGO = 'Código de cliente'
_COL_NOMBRE = 'Nombre de la cuenta'
_COL_DIR    = 'Dirección'
_COL_CIUDAD = 'Población: Población'
_COL_CIUDAD_ALT = 'Población'
_COL_DEPTO  = 'Departamento (Texto)'
_COL_DEPTO_ALT = 'Departamento'
_COL_MOVIL  = 'Móvil'

UMBRAL_CONFIRMADO = 85
UMBRAL_PROBABLE   = 70
UMBRAL_DIR        = 60


def cargar_municipios_default() -> list[str]:
    return sorted(CIUDADES)


def _get_connection():
    return psycopg2.connect(DATABASE_URL)


def cargar_prospectos(municipios: list[str] | None = None) -> pd.DataFrame:
    """Lee clean.empresas desde PostgreSQL, opcionalmente filtrado por municipios."""
    conn = _get_connection()
    try:
        query = """
            SELECT
                empresa_id::text,
                COALESCE(nombre_comercial, razon_social, nombre_normalizado) AS nombre_comercial,
                nombre_normalizado,
                municipio,
                departamento,
                direccion_principal,
                direccion_normalizada,
                latitud,
                longitud,
                telefono_principal  AS telefono,
                correo_principal    AS correo,
                sitio_web,
                score_calidad,
                aprobado_argos,
                fuente_principal
            FROM clean.empresas
            WHERE latitud IS NOT NULL AND longitud IS NOT NULL
        """
        params: list = []

        if municipios:
            muns_norm = [normalizar_municipio(m) for m in municipios]
            placeholders = ','.join(['%s'] * len(muns_norm))
            query += f"""
                AND unaccent(upper(trim(municipio))) = ANY(ARRAY[{placeholders}]::text[])
            """
            params = muns_norm

        df = pd.read_sql(query, conn, params=params if params else None)
    finally:
        conn.close()

    return df


def cargar_todos_municipios_bd() -> list[str]:
    """Devuelve todos los municipios distintos que existen en clean.empresas."""
    conn = _get_connection()
    try:
        df = pd.read_sql(
            "SELECT DISTINCT municipio FROM clean.empresas WHERE municipio IS NOT NULL ORDER BY municipio",
            conn,
        )
    finally:
        conn.close()
    return df['municipio'].dropna().tolist()


def cargar_clientes_argos(path_excel: str, municipios: list[str] | None = None) -> pd.DataFrame:
    """
    Lee el Excel de clientes Argos, deduplica por código de cliente
    y filtra por municipios si se indica.
    """
    df = pd.read_excel(path_excel, dtype=str)
    df.columns = df.columns.str.strip()

    # Detectar columna de ciudad
    ciudad_col = _COL_CIUDAD if _COL_CIUDAD in df.columns else _COL_CIUDAD_ALT
    depto_col  = _COL_DEPTO  if _COL_DEPTO  in df.columns else _COL_DEPTO_ALT

    # Deduplicar por código (un registro por empresa)
    if _COL_CODIGO in df.columns:
        df = df.drop_duplicates(subset=[_COL_CODIGO], keep='first')

    # Columnas normalizadas para matching
    df['municipio_norm'] = df[ciudad_col].apply(normalizar_municipio) if ciudad_col in df.columns else ''
    df['nombre_norm']    = df[_COL_NOMBRE].apply(normalizar_nombre)   if _COL_NOMBRE in df.columns else ''
    dir_col = _COL_DIR if _COL_DIR in df.columns else None
    df['dir_norm']       = df[dir_col].apply(normalizar_direccion)    if dir_col else ''

    # Alias limpios
    df['nombre_cuenta']  = df[_COL_NOMBRE] if _COL_NOMBRE in df.columns else ''
    df['ciudad_argos']   = df[ciudad_col]  if ciudad_col  in df.columns else ''
    df['depto_argos']    = df[depto_col]   if depto_col   in df.columns else ''
    df['dir_argos']      = df[dir_col]     if dir_col     else ''
    df['movil_argos']    = df[_COL_MOVIL]  if _COL_MOVIL  in df.columns else ''

    if municipios:
        muns_norm = [normalizar_municipio(m) for m in municipios]
        df = df[df['municipio_norm'].isin(muns_norm)]

    return df.reset_index(drop=True)


def contrastar(
    df_prospectos: pd.DataFrame,
    df_clientes: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Clasifica cada prospecto y detecta clientes de Argos sin datos en el scraping.

    Retorna:
      - df_pros: df_prospectos enriquecido con columnas categoria / score_match / nombre_argos_match
      - df_sin_datos: clientes de Argos sin par en clean.empresas
    """
    df_pros = df_prospectos.copy()
    df_pros['nombre_norm']  = df_pros['nombre_comercial'].apply(normalizar_nombre)
    df_pros['dir_norm']     = df_pros['direccion_principal'].apply(normalizar_direccion)
    df_pros['municipio_norm'] = df_pros['municipio'].apply(normalizar_municipio)
    df_pros['categoria']          = 'prospecto_nuevo'
    df_pros['score_match']        = 0.0
    df_pros['nombre_argos_match'] = ''

    if df_clientes.empty:
        return df_pros, pd.DataFrame()

    # Índice: municipio_norm → lista de (nombre_norm, dir_norm, nombre_cuenta, idx_cliente)
    idx_por_municipio: dict[str, list] = {}
    for i, row in df_clientes.iterrows():
        mun = row.get('municipio_norm', '')
        if mun not in idx_por_municipio:
            idx_por_municipio[mun] = []
        idx_por_municipio[mun].append((
            row.get('nombre_norm', ''),
            row.get('dir_norm', ''),
            row.get('nombre_cuenta', ''),
        ))

    clientes_con_match: set[str] = set()

    for idx, row in df_pros.iterrows():
        mun = row['municipio_norm']
        candidatos = idx_por_municipio.get(mun, [])
        if not candidatos:
            continue

        nombre_p = row['nombre_norm']
        if not nombre_p:
            continue

        nombres_candidatos = [c[0] for c in candidatos]
        resultado = process.extractOne(
            nombre_p,
            nombres_candidatos,
            scorer=fuzz.token_sort_ratio,
        )
        if resultado is None:
            continue

        score_nombre, pos_match = resultado[1], resultado[2]
        cand_nombre, cand_dir, cand_nombre_original = candidatos[pos_match]

        if score_nombre >= UMBRAL_CONFIRMADO:
            df_pros.at[idx, 'categoria']          = 'cliente_confirmado'
            df_pros.at[idx, 'score_match']        = score_nombre
            df_pros.at[idx, 'nombre_argos_match'] = cand_nombre_original
            clientes_con_match.add(cand_nombre_original.upper())

        elif score_nombre >= UMBRAL_PROBABLE:
            dir_p = row['dir_norm']
            score_dir = fuzz.partial_ratio(dir_p, cand_dir) if dir_p and cand_dir else 0
            if score_dir >= UMBRAL_DIR:
                df_pros.at[idx, 'categoria']          = 'cliente_probable'
                df_pros.at[idx, 'score_match']        = score_nombre
                df_pros.at[idx, 'nombre_argos_match'] = cand_nombre_original
                clientes_con_match.add(cand_nombre_original.upper())

    # Clientes de Argos que no tienen par en clean.empresas
    sin_datos_rows = []
    for _, row in df_clientes.iterrows():
        nombre_c = str(row.get('nombre_cuenta', '')).upper()
        if nombre_c not in clientes_con_match:
            sin_datos_rows.append({
                'nombre_comercial':  row.get('nombre_cuenta', ''),
                'municipio':         row.get('ciudad_argos', ''),
                'departamento':      row.get('depto_argos', ''),
                'direccion_principal': row.get('dir_argos', ''),
                'telefono':          row.get('movil_argos', ''),
                'latitud':           None,
                'longitud':          None,
                'score_calidad':     None,
                'aprobado_argos':    None,
                'categoria':         'cliente_argos_sin_datos',
                'score_match':       0,
                'nombre_argos_match': row.get('nombre_cuenta', ''),
            })

    df_sin_datos = pd.DataFrame(sin_datos_rows)
    return df_pros, df_sin_datos
