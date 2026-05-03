import sys
import os
import json

# Asegura que el proyecto raíz y la carpeta utils estén en el path
_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_DIR, '..'))
for _p in [_DIR, _ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st
import pandas as pd
from streamlit_folium import st_folium

from utils.data_loader import (
    cargar_municipios_default,
    cargar_prospectos,
    cargar_clientes_argos,
    contrastar,
    cargar_todos_municipios_bd,
)
from utils.map_builder import construir_mapa

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Dashboard Argos — Oportunidades de mercado",
    page_icon="🏗️",
    layout="wide",
)

# ─────────────────────────────────────────────
# LECTURA DE STATE FILE (webhook n8n)
# ─────────────────────────────────────────────
_STATE_FILE = os.getenv("STATE_FILE", os.path.join(_DIR, "state", "refresh.json"))

def _leer_state() -> dict:
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_state = _leer_state()
_muns_desde_state = _state.get("municipios", [])
_state_ts = _state.get("timestamp", "")
_state_exec = _state.get("execution_id", "")
_state_empresas = _state.get("empresas_consolidadas", 0)

# Detectar si llegó un webhook NUEVO de n8n comparando timestamps
if "ultimo_state_ts" not in st.session_state:
    st.session_state.ultimo_state_ts = _state_ts

_hay_actualizacion = (
    bool(_state_ts)
    and _state_ts != st.session_state.ultimo_state_ts
)

# ─────────────────────────────────────────────
# MUNICIPIOS DESDE URL (?municipios=medellin,bogota)
# ─────────────────────────────────────────────
params = st.query_params
muns_url = params.get("municipios", "")
muns_desde_url = [m.strip() for m in muns_url.split(",") if m.strip()] if muns_url else []

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/Argos_Colombia_logo.svg/200px-Argos_Colombia_logo.svg.png",
        width=140,
    )
    st.title("Filtros")

    # ── Carga del Excel de Argos
    st.subheader("BD Clientes Argos")
    excel_path_default = os.path.join(_DIR, "data", "clientes_argos.xlsx")
    uploaded = st.file_uploader("Subir Excel de clientes (.xlsx)", type=["xlsx"])
    if uploaded:
        tmp_path = os.path.join(_DIR, "data", "clientes_argos_tmp.xlsx")
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(uploaded.read())
        excel_path = tmp_path
        st.success("Excel cargado correctamente")
    elif os.path.exists(excel_path_default):
        excel_path = excel_path_default
        st.info("Usando archivo: clientes_argos.xlsx")
    else:
        excel_path = None
        st.warning("Sube el Excel de clientes de Argos para activar el contraste")

    st.divider()

    # ── Municipios
    st.subheader("Municipios a analizar")
    # Opciones = municipios reales en clean.empresas + cualquiera que llegue por URL/webhook
    try:
        muns_en_bd = cargar_todos_municipios_bd()
    except Exception:
        muns_en_bd = cargar_municipios_default()

    # Banner de actualización pendiente de n8n
    if _hay_actualizacion:
        st.warning(
            f"🔔 **n8n envió nuevos datos**\n\n"
            f"Pipeline: `{_state_exec}`  \n"
            f"Empresas: {_state_empresas:,}  \n"
            f"Municipios: {len(_muns_desde_state)}",
            icon="🔔",
        )
        if st.button("✅ Aplicar actualización", use_container_width=True, type="primary"):
            st.session_state.ultimo_state_ts = _state_ts
            st.cache_data.clear()
            st.rerun()
    elif _state_ts:
        st.caption(f"Última actualización n8n: {_state_ts[:19]}")

    if _muns_desde_state and not _hay_actualizacion:
        seleccion_inicial = _muns_desde_state
    elif muns_desde_url:
        seleccion_inicial = muns_desde_url
        st.caption(f"Municipios recibidos por URL: {len(muns_desde_url)}")
    else:
        seleccion_inicial = muns_en_bd

    # Opciones = BD + cualquier municipio externo que no esté en la BD
    opciones = sorted(set(muns_en_bd) | set(seleccion_inicial))
    # Default = solo los que realmente existen en opciones (evita el error de Streamlit)
    default_valido = sorted(set(seleccion_inicial) & set(opciones)) or opciones[:5]

    municipios_sel = st.multiselect(
        "Selecciona municipios",
        options=opciones,
        default=default_valido,
        help="Municipios con datos en la BD. Puedes también pasar ?municipios= en la URL.",
    )

    st.divider()

    # ── Filtros adicionales
    st.subheader("Filtros adicionales")

    score_min, score_max = st.slider(
        "Score de calidad",
        min_value=0, max_value=140,
        value=(0, 140),
        step=5,
    )

    solo_aprobados = st.checkbox("Solo aprobados por Argos", value=False)

    categorias_disponibles = [
        'prospecto_nuevo',
        'cliente_confirmado',
        'cliente_probable',
        'cliente_argos_sin_datos',
    ]
    categorias_labels = {
        'prospecto_nuevo':         '🔵 Prospecto nuevo',
        'cliente_confirmado':      '🟢 Cliente confirmado',
        'cliente_probable':        '🟡 Cliente probable',
        'cliente_argos_sin_datos': '🟠 Cliente Argos sin datos',
    }
    categorias_sel = st.multiselect(
        "Categorías a mostrar",
        options=categorias_disponibles,
        default=categorias_disponibles,
        format_func=lambda x: categorias_labels[x],
    )

    mostrar_heatmap = st.checkbox("Mostrar heatmap de densidad", value=True)

# ─────────────────────────────────────────────
# CARGA Y CONTRASTE DE DATOS (cacheado)
# ─────────────────────────────────────────────
@st.cache_data(show_spinner="Cargando datos de prospectos...")
def _cargar_prospectos(muns):
    return cargar_prospectos(list(muns) if muns else None)


@st.cache_data(show_spinner="Cargando clientes de Argos...")
def _cargar_clientes(path, muns):
    return cargar_clientes_argos(path, list(muns) if muns else None)


# Cargar prospectos
try:
    df_pros_raw = _cargar_prospectos(tuple(municipios_sel) if municipios_sel else None)
except Exception as e:
    st.error(f"Error conectando a PostgreSQL: {e}")
    st.stop()

# Aplicar filtro de score y aprobados
mask = (
    (df_pros_raw['score_calidad'].fillna(0) >= score_min) &
    (df_pros_raw['score_calidad'].fillna(0) <= score_max)
)
if solo_aprobados:
    mask &= df_pros_raw['aprobado_argos'].fillna(False).astype(bool)
df_pros_filtrado = df_pros_raw[mask].copy()

# Cargar Excel de Argos
df_sin_datos = pd.DataFrame()
df_clientes = pd.DataFrame()
if excel_path:
    try:
        df_clientes = _cargar_clientes(excel_path, tuple(municipios_sel) if municipios_sel else None)
    except Exception as e:
        st.warning(f"No se pudo leer el Excel de Argos: {e}")

# Contrastar ambas BDs (sin cache — rápido con ~1000 filas)
if not df_clientes.empty:
    try:
        df_pros_filtrado, df_sin_datos = contrastar(df_pros_filtrado, df_clientes)
    except Exception as e:
        st.warning(f"Error al contrastar las bases de datos: {e}")

# Filtrar por categorías seleccionadas
if 'categoria' not in df_pros_filtrado.columns:
    df_pros_filtrado['categoria'] = 'prospecto_nuevo'
if 'score_match' not in df_pros_filtrado.columns:
    df_pros_filtrado['score_match'] = 0.0
if 'nombre_argos_match' not in df_pros_filtrado.columns:
    df_pros_filtrado['nombre_argos_match'] = ''

df_mapa = df_pros_filtrado[df_pros_filtrado['categoria'].isin(categorias_sel)].copy()
df_sin_datos_mapa = df_sin_datos[
    df_sin_datos['categoria'].isin(categorias_sel)
] if not df_sin_datos.empty and 'categoria' in df_sin_datos.columns else pd.DataFrame()

# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
st.title("🏗️ Dashboard Argos — Oportunidades de mercado")
st.caption(
    f"Municipios analizados: **{len(municipios_sel)}** | "
    f"Empresas scrapeadas: **{len(df_pros_raw):,}** | "
    f"Filtradas: **{len(df_mapa):,}**"
)

# ─────────────────────────────────────────────
# KPIs
# ─────────────────────────────────────────────
total_scrapeados   = len(df_pros_filtrado)
n_confirmados      = (df_pros_filtrado['categoria'] == 'cliente_confirmado').sum()  if 'categoria' in df_pros_filtrado else 0
n_probables        = (df_pros_filtrado['categoria'] == 'cliente_probable').sum()    if 'categoria' in df_pros_filtrado else 0
n_prospectos       = (df_pros_filtrado['categoria'] == 'prospecto_nuevo').sum()     if 'categoria' in df_pros_filtrado else total_scrapeados
n_sin_datos        = len(df_sin_datos) if not df_sin_datos.empty else 0
pct_cobertura      = round((n_confirmados + n_probables) / total_scrapeados * 100, 1) if total_scrapeados > 0 else 0

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Empresas scrapeadas",    f"{total_scrapeados:,}")
col2.metric("Prospectos nuevos 🔵",   f"{n_prospectos:,}")
col3.metric("Clientes confirmados 🟢", f"{n_confirmados:,}")
col4.metric("Clientes probables 🟡",  f"{n_probables:,}")
col5.metric("Clientes sin datos 🟠",  f"{n_sin_datos:,}",
            help="Clientes de Argos que no aparecen en el scraping")

if excel_path and total_scrapeados > 0:
    st.progress(pct_cobertura / 100, text=f"Cobertura Argos en scraping: {pct_cobertura}%")

st.divider()

# ─────────────────────────────────────────────
# MAPA
# ─────────────────────────────────────────────
st.subheader("📍 Mapa interactivo")
st.caption(
    "🔵 Prospecto nuevo  |  🟢 Cliente confirmado  |  "
    "🟡 Cliente probable  |  🟠 Cliente Argos sin datos scraping"
)

if df_mapa.empty and df_sin_datos_mapa.empty:
    st.info("No hay datos para mostrar en el mapa con los filtros actuales.")
else:
    with st.spinner("Generando mapa..."):
        mapa = construir_mapa(
            df_mapa,
            df_sin_datos_mapa,
            mostrar_heatmap=mostrar_heatmap,
        )
    st_folium(mapa, use_container_width=True, height=580, returned_objects=[])

st.divider()

# ─────────────────────────────────────────────
# GRÁFICAS
# ─────────────────────────────────────────────
import plotly.express as px

col_g1, col_g2 = st.columns(2)

with col_g1:
    st.subheader("Top municipios por prospectos")
    if 'municipio' in df_mapa.columns and not df_mapa.empty:
        top_mun = (
            df_mapa[df_mapa['categoria'] == 'prospecto_nuevo']['municipio']
            .value_counts()
            .head(12)
            .reset_index()
        )
        top_mun.columns = ['municipio', 'cantidad']
        fig = px.bar(top_mun, x='municipio', y='cantidad', color_discrete_sequence=['#2196F3'])
        fig.update_layout(xaxis_tickangle=-35, margin=dict(b=90))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos suficientes.")

with col_g2:
    st.subheader("Distribución por categoría")
    if 'categoria' in df_pros_filtrado.columns:
        cat_count = df_pros_filtrado['categoria'].value_counts().reset_index()
        cat_count.columns = ['categoria', 'cantidad']
        if not df_sin_datos.empty:
            extra = pd.DataFrame([{'categoria': 'cliente_argos_sin_datos', 'cantidad': len(df_sin_datos)}])
            cat_count = pd.concat([cat_count, extra], ignore_index=True)
        colores_cat = {
            'prospecto_nuevo':         '#2196F3',
            'cliente_confirmado':      '#4CAF50',
            'cliente_probable':        '#FF9800',
            'cliente_argos_sin_datos': '#F44336',
        }
        fig2 = px.pie(
            cat_count,
            names='categoria',
            values='cantidad',
            color='categoria',
            color_discrete_map=colores_cat,
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Sube el Excel de Argos para ver la distribución de categorías.")

st.divider()

# ─────────────────────────────────────────────
# TABLAS EXPORTABLES
# ─────────────────────────────────────────────
st.subheader("📋 Tablas detalladas")

cols_pros = ['nombre_comercial', 'municipio', 'departamento', 'direccion_principal',
             'telefono', 'score_calidad', 'aprobado_argos', 'fuente_principal']
cols_match = cols_pros + ['nombre_argos_match', 'score_match']
cols_sin = ['nombre_comercial', 'municipio', 'departamento', 'direccion_principal', 'telefono']

tab1, tab2, tab3 = st.tabs([
    f"🔵 Prospectos nuevos ({n_prospectos:,})",
    f"🟠 Clientes sin datos ({n_sin_datos:,})",
    f"🟡 Clientes probables ({n_probables:,})",
])

def _cols_existentes(df, cols):
    return [c for c in cols if c in df.columns]

def _boton_csv(df, label, filename):
    if not df.empty:
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(f"⬇️ Descargar {label}", csv, filename, "text/csv")

with tab1:
    df_tab1 = df_pros_filtrado[df_pros_filtrado['categoria'] == 'prospecto_nuevo'] if 'categoria' in df_pros_filtrado.columns else df_pros_filtrado
    st.dataframe(df_tab1[_cols_existentes(df_tab1, cols_pros)], use_container_width=True)
    _boton_csv(df_tab1[_cols_existentes(df_tab1, cols_pros)], "Prospectos", "prospectos_nuevos.csv")

with tab2:
    if df_sin_datos.empty:
        st.info("Sube el Excel de Argos para ver esta tabla.")
    else:
        st.dataframe(df_sin_datos[_cols_existentes(df_sin_datos, cols_sin)], use_container_width=True)
        _boton_csv(df_sin_datos[_cols_existentes(df_sin_datos, cols_sin)], "Clientes sin datos", "clientes_sin_datos.csv")

with tab3:
    df_tab3 = df_pros_filtrado[df_pros_filtrado['categoria'] == 'cliente_probable'] if 'categoria' in df_pros_filtrado.columns else pd.DataFrame()
    if df_tab3.empty:
        st.info("No hay clientes probables con los filtros actuales.")
    else:
        st.dataframe(df_tab3[_cols_existentes(df_tab3, cols_match)], use_container_width=True)
        _boton_csv(df_tab3[_cols_existentes(df_tab3, cols_match)], "Clientes probables", "clientes_probables.csv")

st.caption("Dashboard generado con datos de clean.empresas (PostgreSQL) y BD Argos (.xlsx)")
