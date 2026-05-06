import folium
from folium.plugins import HeatMap, MarkerCluster
from math import radians, cos, sin, asin, sqrt
import pandas as pd

# Centroides aproximados de los municipios del scraping
CENTROIDES: dict[str, tuple[float, float]] = {
    "BOGOTA":               (4.7110, -74.0721),
    "MEDELLIN":             (6.2442, -75.5812),
    "CALI":                 (3.4516, -76.5320),
    "BARRANQUILLA":         (10.9639, -74.7964),
    "CARTAGENA":            (10.3910, -75.4794),
    "BUCARAMANGA":          (7.1193, -73.1227),
    "CUCUTA":               (7.8939, -72.5078),
    "PEREIRA":              (4.8133, -75.6961),
    "SANTA MARTA":          (11.2408, -74.1990),
    "IBAGUE":               (4.4389, -75.2322),
    "PASTO":                (1.2136, -77.2811),
    "MANIZALES":            (5.0703, -75.5138),
    "NEIVA":                (2.9273, -75.2819),
    "VILLAVICENCIO":        (4.1420, -73.6266),
    "ARMENIA":              (4.5339, -75.6811),
    "VALLEDUPAR":           (10.4778, -73.2604),
    "MONTERIA":             (8.7575, -75.8890),
    "SINCELEJO":            (9.3047, -75.3978),
    "POPAYAN":              (2.4419, -76.6064),
    "TUNJA":                (5.5353, -73.3678),
    "RIOHACHA":             (11.5444, -72.9072),
    "FLORENCIA":            (1.6144, -75.6062),
    "QUIBDO":               (5.6919, -76.6583),
    "YOPAL":                (5.3378, -72.3950),
    "ARAUCA":               (7.0864, -70.7589),
    "BELLO":                (6.3367, -75.5565),
    "ITAGUI":               (6.1844, -75.5991),
    "ENVIGADO":             (6.1754, -75.5867),
    "SABANETA":             (6.1511, -75.6155),
    "RIONEGRO":             (6.1547, -75.3731),
    "APARTADO":             (7.8800, -76.6319),
    "CAUCASIA":             (7.9839, -75.1978),
    "TURBO":                (8.0931, -76.7258),
    "DOSQUEBRADAS":         (4.8392, -75.6628),
    "SANTA ROSA DE CABAL":  (4.8686, -75.6186),
    "CALARCA":              (4.5253, -75.6428),
    "SOACHA":               (4.5792, -74.2172),
    "CHIA":                 (4.8611, -74.0594),
    "ZIPAQUIRA":            (5.0228, -74.0053),
    "FACATATIVA":           (4.8142, -74.3542),
    "FUSAGASUGA":           (4.3372, -74.3636),
    "GIRARDOT":             (4.3028, -74.8025),
    "MOSQUERA":             (4.7058, -74.2294),
    "MADRID":               (4.7339, -74.2656),
    "FUNZA":                (4.7175, -74.2108),
    "DUITAMA":              (5.8264, -73.0275),
    "SOGAMOSO":             (5.7178, -72.9319),
    "CHIQUINQUIRA":         (5.6186, -73.8197),
    "PALMIRA":              (3.5394, -76.3039),
    "BUENAVENTURA":         (3.8833, -77.0311),
    "TULUA":                (4.0839, -76.1961),
    "CARTAGO":              (4.7456, -75.9119),
    "BUGA":                 (3.9014, -76.2981),
    "JAMUNDI":              (3.2636, -76.5392),
    "YUMBO":                (3.5908, -76.4956),
    "TUMACO":               (1.8003, -78.7658),
    "SOLEDAD":              (10.9153, -74.7706),
    "MALAMBO":              (10.8575, -74.7733),
    "CIENAGA":              (11.0069, -74.2519),
    "MAGANGUE":             (9.2419, -74.7589),
    "MAICAO":               (11.3814, -72.2436),
    "AGUACHICA":            (8.3094, -73.6194),
    "FLORIDABLANCA":        (7.0644, -73.0881),
    "GIRON":                (7.0736, -73.1689),
    "PIEDECUESTA":          (6.9903, -73.0517),
    "BARRANCABERMEJA":      (7.0644, -73.8544),
    "PAMPLONA":             (7.3767, -72.6508),
    "OCANA":                (8.2361, -73.3572),
    "PITALITO":             (1.8544, -76.0519),
    "GARZON":               (2.1981, -75.6294),
    "ESPINAL":              (4.1536, -74.8892),
    "IPIALES":              (0.8283, -77.6442),
    "EL BAGRE":             (7.5928, -74.8086),
    # Municipios adicionales Antioquia
    "SAN RAFAEL":           (6.2942, -75.0128),
    "SAN CARLOS":           (6.1906, -74.9969),
    "GUARNE":               (6.2761, -75.4383),
    "LA CEJA":              (6.0297, -75.4311),
    "EL RETIRO":            (6.0569, -75.5067),
    "MARINILLA":            (6.1742, -75.3367),
    "SANTUARIO":            (5.9108, -75.9706),
    "ANDES":                (5.6575, -75.8794),
    "YARUMAL":              (7.0036, -75.4175),
    "SANTA FE DE ANTIOQUIA": (6.5561, -75.8261),
    "TITIRIBI":             (6.0722, -75.7894),
    "FREDONIA":             (5.9244, -75.6756),
    "CALDAS":               (6.0939, -75.6364),
    "LA ESTRELLA":          (6.1553, -75.6428),
    "COPACABANA":           (6.3492, -75.5094),
    "GIRARDOTA":            (6.3792, -75.4467),
    "BARBOSA":              (6.4378, -75.3317),
    "CHIGORODO":            (7.6731, -76.6856),
    "DON MATIAS":           (6.4961, -75.3994),
    "ENTRERRIOS":           (6.5614, -75.4233),
    "SAN PEDRO DE LOS MILAGROS": (6.4753, -75.5447),
    "BELMIRA":              (6.6089, -75.6672),
    "SANTA ROSA DE OSOS":   (6.6431, -75.4644),
    "ANGOSTURA":            (6.8789, -75.3392),
    "CAROLINA":             (6.7528, -75.3253),
    "GOMEZ PLATA":          (6.6825, -75.2306),
    "GUADALUPE":            (6.8642, -75.2683),
    # Municipios adicionales del payload n8n
    "SABANALARGA":          (8.7400, -75.7000),   # Sabanalarga, Antioquia
    "SONSON":               (5.7128, -75.3147),
    "SEGOVIA":              (7.0897, -74.7050),
    "PUERTO BERRIO":        (6.4897, -74.4019),
    "URRAO":                (6.3228, -76.1406),
    "LIBORINA":             (6.6908, -75.8778),
    "GUATAPE":              (6.2322, -75.1578),
    "FRONTINO":             (6.7800, -76.1311),
    "REMEDIOS":             (7.0217, -74.6953),
    "ZARAGOZA":             (7.4917, -74.8708),
    "URAMITA":              (6.8883, -76.1733),
    "PEÑOL":                (6.2042, -75.2392),
}

# Bounding box de Colombia — filtra coordenadas erróneas fuera del país
_LAT_MIN, _LAT_MAX = -4.2, 13.0
_LON_MIN, _LON_MAX = -82.0, -67.0

# Distancia máxima aceptable entre coordenada scrapeada y centroide del municipio
_MAX_DIST_KM = 100


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en km entre dos puntos geográficos."""
    R = 6371
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * R * asin(sqrt(a))

_COLORES = {
    'prospecto_nuevo':        ('blue',   '#2196F3', 'Prospecto nuevo'),
    'cliente_confirmado':     ('green',  '#4CAF50', 'Cliente confirmado'),
    'cliente_probable':       ('orange', '#FF9800', 'Cliente probable'),
    'cliente_argos_sin_datos':('red',    '#F44336', 'Cliente Argos sin datos scraping'),
}


def _centroide(municipio: str) -> tuple[float, float] | None:
    from utils.normalizar import normalizar_municipio
    key = normalizar_municipio(municipio)
    return CENTROIDES.get(key)


def _icono(categoria: str, color: str) -> folium.Icon:
    iconos = {
        'prospecto_nuevo':         'info-sign',
        'cliente_confirmado':      'ok-sign',
        'cliente_probable':        'question-sign',
        'cliente_argos_sin_datos': 'warning-sign',
    }
    return folium.Icon(color=color, icon=iconos.get(categoria, 'info-sign'), prefix='glyphicon')


def construir_mapa(
    df_prospectos: pd.DataFrame,
    df_sin_datos: pd.DataFrame,
    mostrar_heatmap: bool = True,
) -> folium.Map:
    """
    Construye el mapa Folium con 4 capas de marcadores + heatmap opcional.

    df_prospectos: resultado de contrastar(), incluye columna 'categoria'
    df_sin_datos:  clientes Argos sin par en clean.empresas
    """
    mapa = folium.Map(
        location=[4.5709, -74.2973],
        zoom_start=6,
        tiles='CartoDB positron',
    )

    grupos: dict[str, MarkerCluster] = {}
    for cat, (color, _, label) in _COLORES.items():
        grupos[cat] = MarkerCluster(name=label, show=True).add_to(mapa)

    # ── Prospectos, clientes confirmados y probables (tienen lat/lon de PostgreSQL)
    for _, row in df_prospectos.iterrows():
        cat = row.get('categoria', 'prospecto_nuevo')
        lat = row.get('latitud')
        lon = row.get('longitud')
        mun = row.get('municipio', '') or ''
        if lat is None or lon is None:
            continue
        lat, lon = float(lat), float(lon)
        if not (_LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX):
            continue  # coordenada fuera del bounding box de Colombia

        # Validar que la coordenada esté cerca del centroide del municipio
        centroide = _centroide(mun)
        if centroide:
            dist = _haversine(lat, lon, centroide[0], centroide[1])
            if dist > _MAX_DIST_KM:
                # Coordenada scrapeada muy lejos del municipio → usar centroide
                lat, lon = centroide[0], centroide[1]

        color_folium = _COLORES[cat][0]
        nombre  = row.get('nombre_comercial', '') or ''
        depto   = row.get('departamento', '') or ''
        dir_    = row.get('direccion_principal', '') or ''
        tel     = row.get('telefono', '') or ''
        score   = row.get('score_calidad', '')
        match   = row.get('nombre_argos_match', '') or ''
        sm      = row.get('score_match', 0)

        popup_lines = [
            f"<b>{nombre}</b>",
            f"<i>{mun}, {depto}</i>",
            f"<br>{dir_}" if dir_ else '',
            f"Tel: {tel}" if tel else '',
            f"Score calidad: {score}" if score != '' else '',
        ]
        if cat in ('cliente_confirmado', 'cliente_probable'):
            popup_lines.append(f"Match Argos: <b>{match}</b> ({sm}%)")

        popup_html = '<br>'.join(l for l in popup_lines if l)

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=nombre,
            icon=_icono(cat, color_folium),
        ).add_to(grupos[cat])

    # ── Clientes Argos sin datos scraping
    # Prioridad: 1) coords geocodificadas reales, 2) centroide del municipio
    for _, row in df_sin_datos.iterrows():
        mun  = row.get('municipio', '') or ''
        depto = row.get('departamento', '') or ''

        # Intentar coordenadas geocodificadas (dirección real)
        geo_lat = row.get('latitud')
        geo_lon = row.get('longitud')

        if geo_lat is not None and geo_lon is not None:
            try:
                lat, lon = float(geo_lat), float(geo_lon)
                # Validar que caigan dentro del bounding box de Colombia
                if not (_LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX):
                    lat, lon = None, None
            except (ValueError, TypeError):
                lat, lon = None, None
        else:
            lat, lon = None, None

        # Fallback: centroide del municipio
        if lat is None:
            centroide = _centroide(mun)
            if centroide is None:
                continue  # sin coordenadas de ningún tipo → no mostrar
            lat, lon = centroide

        nombre = row.get('nombre_comercial', '') or ''
        dir_   = row.get('direccion_principal', '') or ''
        tel    = row.get('telefono', '') or ''
        fuente = "📍 Geocodificado" if geo_lat is not None else "📌 Centroide aproximado"

        popup_html = (
            f"<b>{nombre}</b><br>"
            f"<i>{mun}, {depto}</i><br>"
            f"{dir_}<br>"
            f"Tel: {tel}<br>"
            f"<small>⚠️ Sin datos de scraping &nbsp;|&nbsp; {fuente}</small>"
        )

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=nombre,
            icon=_icono('cliente_argos_sin_datos', 'red'),
        ).add_to(grupos['cliente_argos_sin_datos'])

    # ── Heatmap (solo prospectos nuevos con coords)
    if mostrar_heatmap:
        df_heat = df_prospectos[
            (df_prospectos['categoria'] == 'prospecto_nuevo') &
            df_prospectos['latitud'].notna() &
            df_prospectos['longitud'].notna() &
            df_prospectos['latitud'].between(_LAT_MIN, _LAT_MAX) &
            df_prospectos['longitud'].between(_LON_MIN, _LON_MAX)
        ]
        if not df_heat.empty:
            # Aplicar el mismo snap de centroide que se usa para los marcadores
            heat_data = []
            for _, row in df_heat.iterrows():
                lat, lon = float(row['latitud']), float(row['longitud'])
                mun = row.get('municipio', '') or ''
                centroide = _centroide(mun)
                if centroide:
                    dist = _haversine(lat, lon, centroide[0], centroide[1])
                    if dist > _MAX_DIST_KM:
                        lat, lon = centroide[0], centroide[1]
                heat_data.append([lat, lon])
            HeatMap(
                heat_data,
                name='Densidad de prospectos',
                radius=18,
                blur=15,
                min_opacity=0.3,
                show=True,
            ).add_to(mapa)

    folium.LayerControl(collapsed=False).add_to(mapa)
    return mapa
