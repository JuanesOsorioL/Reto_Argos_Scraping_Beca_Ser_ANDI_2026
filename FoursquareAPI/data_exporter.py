"""
data_exporter.py — Exporta datos desde PostgreSQL a Excel
Uso:
    python data_exporter.py              → todos los registros
    python data_exporter.py --aprobados  → solo aprobados por Argos
"""
import sys
import pandas as pd
from config import EXCEL_OUTPUT_FILE
from db import get_connection


def exportar_a_excel(solo_aprobados: bool = False):
    """
    Exporta registros de PostgreSQL a archivo Excel.
    
    Args:
        solo_aprobados: Si True, solo exporta registros con aprobado_argos=TRUE
    """
    
    # Construir filtro SQL
    filtro = "WHERE aprobado_argos = TRUE" if solo_aprobados else ""
    
    query = f"""
        SELECT
            -- Columnas Argos
            nit, nombre, departamento, municipio, direccion,
            latitud, longitud, telefono, whatsapp, correo_electronico,
            fecha_actualizacion, fuente,
            -- Calidad
            keyword_busqueda, score, aprobado_argos,
            -- Exclusivas Foursquare
            fsq_place_id, fsq_categories, fsq_website,
            fsq_twitter, fsq_instagram, fsq_facebook,
            fsq_date_created, fsq_date_refreshed,
            fsq_rating, fsq_price, fsq_hours, fsq_verified,
            fsq_locality, fsq_region, fsq_postal_code,
            -- Trazabilidad
            fecha_extraccion, run_id
        FROM raw.foursquare_ferreterias
        {filtro}
        ORDER BY departamento, municipio, nombre;
    """
    
    try:
        # Conectar a BD y leer datos
        with get_connection() as conn:
            df = pd.read_sql(query, conn)
        
        if df.empty:
            print("⚠️  No hay datos para exportar.")
            return
        
        # Ordenar por relevancia
        df = df.sort_values(
            by=["departamento", "municipio", "score"],
            ascending=[True, True, False]
        )
        
        # Exportar a Excel
        df.to_excel(EXCEL_OUTPUT_FILE, index=False, engine="openpyxl")
        
        # Estadísticas
        print(f"\n✅ Exportación completada")
        print(f"   Archivo: '{EXCEL_OUTPUT_FILE}'")
        print(f"   Registros: {len(df)}")
        print(f"   Municipios únicos: {df['municipio'].nunique()}")
        print(f"   Departamentos únicos: {df['departamento'].nunique()}")
        print(f"   Aprobados Argos: {df['aprobado_argos'].sum()}")
        print(f"   Con teléfono: {(df['telefono'] != '').sum()}")
        print(f"   Con website: {(df['fsq_website'] != '').sum()}")
        print()
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    solo_aprobados = "--aprobados" in sys.argv
    if solo_aprobados:
        print("📊 Exportando solo registros aprobados...")
    else:
        print("📊 Exportando todos los registros...")
    
    exportar_a_excel(solo_aprobados=solo_aprobados)
