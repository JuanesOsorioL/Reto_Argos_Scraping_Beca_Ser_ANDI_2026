import psycopg2
from psycopg2.extras import execute_values
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, TABLAS_FUENTES


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10,
    )


def contar_registros_por_municipio(municipios: list[dict]) -> dict:
    """
    Consulta las 4 tablas de fuentes y cuenta registros por municipio.

    Args:
        municipios: lista de dicts con keys 'municipio' y 'departamento'

    Returns:
        dict con key (municipio_lower, departamento_lower) y value:
            {
                "municipio": str,
                "departamento": str,
                "total": int,
                "rues": int,
                "google_maps": int,
                "paginas_amarillas": int,
                "openstreetmap": int,
            }
    """
    if not municipios:
        return {}

    # Normalizar para comparación
    muni_lower = [m["municipio"].strip().lower() for m in municipios]

    # Inicializar conteos en 0 para todos los municipios del input
    conteos: dict[tuple, dict] = {}
    for m in municipios:
        key = (m["municipio"].strip().lower(), m["departamento"].strip().lower())
        conteos[key] = {
            "municipio":         m["municipio"],
            "departamento":      m["departamento"],
            "total":             0,
            "rues":              0,
            "google_maps":       0,
            "paginas_amarillas": 0,
            "openstreetmap":     0,
        }

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for fuente, tabla in TABLAS_FUENTES.items():
                sql = f"""
                    SELECT LOWER(TRIM(municipio)), COUNT(*)
                    FROM {tabla}
                    WHERE LOWER(TRIM(municipio)) = ANY(%s)
                    GROUP BY LOWER(TRIM(municipio))
                """
                cur.execute(sql, (muni_lower,))
                rows = cur.fetchall()

                for muni_norm, cnt in rows:
                    # Buscar la key que coincida con este municipio normalizado
                    for key in conteos:
                        if key[0] == muni_norm:
                            conteos[key][fuente] += cnt
                            conteos[key]["total"] += cnt
    finally:
        conn.close()

    return conteos


def test_connection() -> bool:
    try:
        conn = get_connection()
        conn.close()
        return True
    except Exception:
        return False
