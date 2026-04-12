"""
data_exporter.py — Exporta desde PostgreSQL a Excel
Uso:
    python data_exporter.py              → todos los registros
    python data_exporter.py --aprobados  → solo aprobados por Argos
"""
import sys
import pandas as pd
from config import EXCEL_OUTPUT_FILE
from db import get_connection


def export_to_excel(solo_aprobados: bool = False):
    filtro = "WHERE aprobado_argos = TRUE" if solo_aprobados else ""
    query = f"""
        SELECT
            -- Columnas requeridas por Argos (orden exacto)
            nit,
            nombre,
            departamento,
            municipio,
            direccion,
            latitud,
            longitud,
            telefono,
            whatsapp,
            correo_electronico,
            fecha_actualizacion,
            fuente,

            -- Columnas adicionales de calidad
            sucursal_tipo,
            categorias_maps,
            score,
            aprobado_argos,
            keyword_busqueda,
            descripcion,
            url,
            fecha_extraccion,
            run_id
        FROM raw.google_maps_ferreterias
        {filtro}
        ORDER BY departamento, municipio, nombre;
    """
    try:
        with get_connection() as conn:
            df = pd.read_sql(query, conn)

        if df.empty:
            print("No hay datos en la BD para exportar.")
            return

        # categorias_maps es array en PG — convertir a string
        if "categorias_maps" in df.columns:
            df["categorias_maps"] = df["categorias_maps"].apply(
                lambda x: ", ".join(x) if isinstance(x, list) else (x or "")
            )

        df = df.sort_values(by=["departamento", "municipio", "score"], ascending=[True, True, False])
        df.to_excel(EXCEL_OUTPUT_FILE, index=False, engine="openpyxl")
        print(f"✅ {len(df)} registros exportados → '{EXCEL_OUTPUT_FILE}'")
        print(f"   Columnas: {list(df.columns)}")

    except Exception as e:
        print(f"❌ Error al exportar: {e}")


if __name__ == "__main__":
    solo_aprobados = "--aprobados" in sys.argv
    export_to_excel(solo_aprobados=solo_aprobados)
    # Uso:
    #   python data_exporter.py              → todos
    #   python data_exporter.py --aprobados  → solo aprobados