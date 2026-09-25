"""
Examen 3 - Internet de las Cosas - Notebook 3/3: dashboard interactivo
Version script de 03_dashboard.ipynb (misma logica), adaptada para correr
como servidor Dash local (sin Colab), y exportar tambien la version
estatica dashboard_estatico.html.
"""
import os, json, argparse, base64
import numpy as np, pandas as pd
import plotly.graph_objects as go
from scipy.spatial import cKDTree

BASE, EN_COLAB = os.path.abspath('./IoT_Examen3'), False
OUT = f'{BASE}/salida'
FIGS = f'{OUT}/figs'

IND = pd.read_csv(f'{OUT}/indicadores_medidas.csv', parse_dates=['hora'])
RES = pd.read_csv(f'{OUT}/resumen_canales.csv', index_col='Canal')
FUE = pd.read_csv(f'{OUT}/fuentes.csv', index_col='canal')
FQ  = json.load(open(f'{OUT}/frecuencias.json'))
CAL = json.load(open(f'{OUT}/calidad.json'))
CANALES = {'A': (840, 845), 'B': (845, 850), 'C': (850, 855), 'D': (855, 860)}

def img64(nombre):
    ruta = f'{FIGS}/{nombre}'
    if not os.path.exists(ruta): return None
    return 'data:image/png;base64,' + base64.b64encode(open(ruta, 'rb').read()).decode()

RANGO_P = (-95, -10)
CAPAS = {'ubicacion': ('Ubicacion de las mediciones', None, None, None, None),
         'ruta':      ('Ruta de las mediciones', None, None, None, None)}
for c, (lo, hi) in CANALES.items():
    CAPAS[f'canal_{c}'] = (f'Mapa de calor - Canal {c} ({lo}-{hi} MHz)', f'P_{c}', 'Turbo', 'dBm', RANGO_P)
CAPAS['temp'] = ('Mapa de calor - Temperatura del sensor', 'temp', 'YlOrRd', 'C', (IND.temp.min(), IND.temp.max()))
CAPAS['freq'] = (f"Mapa de calor - Frecuencia mas contaminada ({FQ['f_max_MHz']:.3f} MHz)", 'P_fmax', 'Turbo', 'dBm', RANGO_P)
print(len(IND), 'mediciones |', len(CAPAS), 'capas')

CELDA_M, BUFFER_M, K_VEC = 80.0, 400.0, 8
R_T = 6371000.0
lat0, lon0 = IND.lat.mean(), IND.lon.mean()
to_xy   = lambda lat, lon: (np.radians(lon - lon0) * R_T * np.cos(np.radians(lat0)), np.radians(lat - lat0) * R_T)
from_xy = lambda x, y: (lat0 + np.degrees(y / R_T), lon0 + np.degrees(x / (R_T * np.cos(np.radians(lat0)))))
X, Y = to_xy(IND.lat.values, IND.lon.values)

gx, gy = np.arange(X.min() - BUFFER_M, X.max() + BUFFER_M, CELDA_M), np.arange(Y.min() - BUFFER_M, Y.max() + BUFFER_M, CELDA_M)
GX, GY = np.meshgrid(gx, gy); celdas = np.c_[GX.ravel(), GY.ravel()]
arbol = cKDTree(np.c_[X, Y])
d1, _ = arbol.query(celdas, k=1)
celdas = celdas[d1 <= BUFFER_M]
d, idx = arbol.query(celdas, k=K_VEC)
pesos = 1.0 / np.maximum(d, 1.0) ** 2; pesos /= pesos.sum(axis=1, keepdims=True)
idw = lambda v: (pesos * np.asarray(v)[idx]).sum(axis=1)

h = CELDA_M / 2
def cuadrado(cx, cy):
    esq = [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h), (cx - h, cy - h)]
    return [[round(from_xy(x, y)[1], 5), round(from_xy(x, y)[0], 5)] for x, y in esq]
GEO = {'type': 'FeatureCollection', 'features': [
    {'type': 'Feature', 'id': str(i), 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [cuadrado(cx, cy)]}}
    for i, (cx, cy) in enumerate(celdas)]}
IDS = [str(i) for i in range(len(celdas))]
VALORES = {k: idw(IND[col].values) for k, (_, col, *_r) in CAPAS.items() if col}
print(f'{len(celdas)} celdas de {CELDA_M:.0f} m')

import dash
from dash import Dash, dcc, html, Input, Output

TEXTO_PUNTO = [f'<b>Medicion {int(o):03d}</b> - {h_:%H:%M}<br>Temp {t:.1f} C<br>' + '<br>'.join(f'Canal {c}: {p:.1f} dBm' for c, p in zip('ABCD', ps))
               for o, h_, t, *ps in zip(IND.orden, IND.hora, IND.temp, IND.P_A, IND.P_B, IND.P_C, IND.P_D)]

def crear_figura(capa, overlays=('ruta', 'fuentes')):
    titulo, col, escala, unidad, rango = CAPAS[capa]
    fig = go.Figure()
    if col:
        fig.add_trace(go.Choroplethmap(geojson=GEO, locations=IDS, z=VALORES[capa], zmin=rango[0], zmax=rango[1],
                      colorscale=escala, marker_opacity=0.68, marker_line_width=0, hoverinfo='skip', name=titulo,
                      colorbar=dict(title=unidad, thickness=12, len=0.55, x=0.99, xanchor='right', y=0.5)))
    if capa == 'ruta' or 'ruta' in overlays:
        fig.add_trace(go.Scattermap(lat=IND.lat, lon=IND.lon, mode='lines', line=dict(width=3, color='#1b3a4b'), hoverinfo='skip', name='Ruta'))
    if capa == 'ruta':
        fig.add_trace(go.Scattermap(lat=IND.lat, lon=IND.lon, mode='markers', name='Mediciones', text=TEXTO_PUNTO, hoverinfo='text',
                      marker=dict(size=9, color=IND.orden, colorscale='Viridis', colorbar=dict(title='n.', thickness=12, len=0.5, x=0.99, xanchor='right'))))
        fig.add_trace(go.Scattermap(lat=[IND.lat.iloc[0]], lon=[IND.lon.iloc[0]], mode='markers+text', text=['Inicio'], textposition='top right',
                      marker=dict(size=15, color='#1e8e3e'), name='Inicio', hoverinfo='skip'))
        fig.add_trace(go.Scattermap(lat=[IND.lat.iloc[-1]], lon=[IND.lon.iloc[-1]], mode='markers+text', text=['Fin'], textposition='bottom right',
                      marker=dict(size=15, color='#c5221f'), name='Fin', hoverinfo='skip'))
    elif capa == 'ubicacion' or 'puntos' in overlays:
        fig.add_trace(go.Scattermap(lat=IND.lat, lon=IND.lon, mode='markers', name='Mediciones', text=TEXTO_PUNTO, hoverinfo='text',
                      marker=dict(size=9, color='#0b6e8a')))
    if 'fuentes' in overlays:
        fig.add_trace(go.Scattermap(lat=FUE.lat, lon=FUE.lon, mode='markers+text', text=[f'Fuente {c}' for c in FUE.index], textposition='top center',
                      marker=dict(size=16, color='#ffffff'), name='Fuente estimada', hoverinfo='text',
                      hovertext=[f'Canal {c}: {r.lat:.5f}, {r.lon:.5f}<br>{r.metodo} - incertidumbre +-{r.radio95_m:.0f} m' for c, r in FUE.iterrows()]))
        fig.add_trace(go.Scattermap(lat=FUE.lat, lon=FUE.lon, mode='markers', marker=dict(size=9, color='#c5221f'), showlegend=False, hoverinfo='skip'))
    fig.update_layout(map=dict(style='carto-positron', center=dict(lat=lat0, lon=lon0), zoom=11.7), margin=dict(l=0, r=0, t=0, b=0),
                      legend=dict(orientation='h', y=0.01, x=0.01, bgcolor='rgba(255,255,255,.8)'), uirevision=capa, height=640)
    return fig

COLOR_DICT = {'Recomendado': '#1e8e3e', 'Condicionado': '#b06000', 'No recomendado': '#c5221f'}
def panel_indicadores():
    oc = 'Ocupacion (% de mediciones > umbral)'
    barras = go.Figure(go.Bar(x=list(RES.index), y=RES[oc], marker_color=[COLOR_DICT[d] for d in RES.Dictamen], text=[f'{v:.0f} %' for v in RES[oc]], textposition='outside'))
    barras.update_layout(height=230, margin=dict(l=30, r=10, t=30, b=25), yaxis=dict(range=[0, 105], title='% ocupacion'), title=dict(text=f"Ocupacion (P > {FQ['umbral_dBm']:.0f} dBm)", font=dict(size=13)), plot_bgcolor='white')
    filas = [html.Tr([html.Th(t) for t in ['Canal', 'MHz', 'Pot. media', 'Dictamen']])] + [
        html.Tr([html.Td(c), html.Td(r['Banda (MHz)']), html.Td(f"{r['Potencia media (dBm)']:.1f} dBm"),
                 html.Td(r.Dictamen, style={'color': COLOR_DICT[r.Dictamen], 'fontWeight': 600})]) for c, r in RES.iterrows()]
    return [dcc.Graph(figure=barras, config={'displayModeBar': False}), html.Table(filas, style={'width': '100%', 'fontSize': 13, 'borderCollapse': 'collapse'})]

# ── Paleta y layout general ───────────────────────────────────────────────
NAVY, NAVY_DK, TEAL, ICE, BG, TEXT, MUTED = '#1e2f52', '#132139', '#1c7293', '#cfe0ec', '#eef1f4', '#14202b', '#4a5a68'
PANEL = {'background': 'white', 'border': '1px solid #d5dbe1', 'borderRadius': 6, 'padding': 12}

VISTAS = [
    ('inicio',   'Inicio',   '⌂'),
    ('mapa',     'Mapa',     '◈'),
    ('espectro', 'Espectro', '≈'),
    ('calidad',  'Calidad',  '✓'),
    ('fuentes',  'Fuentes',  '◎'),
]

def sidebar(activa='inicio'):
    items = []
    for key, label, icono in VISTAS:
        es_activa = key == activa
        items.append(html.Button([
            html.Span(icono, style={'fontSize': 16, 'width': 22, 'display': 'inline-block', 'textAlign': 'center'}),
            html.Span(label, style={'marginLeft': 8})
        ], id={'type': 'nav', 'index': key}, n_clicks=0, style={
            'display': 'flex', 'alignItems': 'center', 'width': '100%', 'padding': '10px 14px', 'marginBottom': 4,
            'border': 'none', 'borderRadius': 6, 'cursor': 'pointer', 'fontSize': 14, 'textAlign': 'left',
            'background': TEAL if es_activa else 'transparent', 'color': '#ffffff' if es_activa else ICE,
            'fontWeight': 600 if es_activa else 400}))
    return html.Div([
        html.Div('IoT · Examen 3', style={'color': ICE, 'fontSize': 11, 'letterSpacing': 1, 'opacity': 0.7, 'padding': '4px 14px 2px'}),
        html.Div('840-860 MHz', style={'color': '#ffffff', 'fontSize': 16, 'fontWeight': 700, 'padding': '0 14px 16px'}),
        html.Div(items, style={'padding': '0 8px'}),
    ], style={'background': NAVY, 'width': 200, 'minHeight': '100vh', 'padding': '18px 0', 'boxSizing': 'border-box'})

def kpi(valor, etiqueta, color=NAVY):
    return html.Div([
        html.Div(valor, style={'fontSize': 26, 'fontWeight': 700, 'color': color}),
        html.Div(etiqueta, style={'fontSize': 12, 'color': MUTED, 'marginTop': 2}),
    ], style={**PANEL, 'flex': 1, 'textAlign': 'center'})

def imagen_card(nombre_archivo, titulo):
    src = img64(nombre_archivo)
    if not src:
        return html.Div([html.Div(titulo, style={'fontWeight': 600, 'marginBottom': 6}),
                          html.Div('Figura no disponible (corre 02_indicadores_informe.py).', style={'fontSize': 12, 'color': MUTED})], style=PANEL)
    return html.Div([html.Div(titulo, style={'fontWeight': 600, 'marginBottom': 8}),
                      html.Img(src=src, style={'width': '100%', 'borderRadius': 4})], style=PANEL)

# ── Vista: Inicio ──────────────────────────────────────────────────────────
def vista_inicio():
    ant = CAL.get('correccion_antena', {})
    return html.Div([
        html.H2('Ocupacion del espectro 840-860 MHz - occidente de Medellin', style={'margin': '0 0 4px', 'fontSize': 22, 'color': NAVY}),
        html.Div(f"{len(IND)} mediciones - canal mas contaminado: {FQ['canal_mas_contaminado']} - frecuencia mas critica: {FQ['f_max_MHz']:.3f} MHz",
                 style={'fontSize': 13, 'color': MUTED, 'marginBottom': 16}),
        html.Div([
            kpi(len(IND), 'mediciones validas'),
            kpi(f"{CAL['gps_valido_pct']:.1f}%", 'GPS valido'),
            kpi(f"{ant.get('media_dB', 0):.2f} dB", 'correccion de antena (media)', color=TEAL),
            kpi(FQ['canal_mas_contaminado'], 'canal mas contaminado', color='#c5221f'),
        ], style={'display': 'flex', 'gap': 12, 'marginBottom': 16}),
        html.Div(style=PANEL, children=[
            html.Div('Dictamen por canal', style={'fontWeight': 600, 'marginBottom': 8}),
            *panel_indicadores(),
        ]),
        html.Div('Usa el menu de la izquierda para ver el mapa interactivo, el analisis espectral, la calidad de datos y las fuentes estimadas.',
                 style={'fontSize': 12, 'color': MUTED, 'marginTop': 14}),
    ])

# ── Vista: Mapa ─────────────────────────────────────────────────────────────
def vista_mapa():
    return html.Div(style={'display': 'grid', 'gridTemplateColumns': '230px 1fr 290px', 'gap': 12, 'alignItems': 'start'}, children=[
        html.Div(style=PANEL, children=[
            html.Div('Capa', style={'fontWeight': 600, 'marginBottom': 6}),
            dcc.RadioItems(id='capa', value='canal_C', options=[{'label': v[0], 'value': k} for k, v in CAPAS.items()], labelStyle={'display': 'block', 'margin': '5px 0', 'fontSize': 13}),
            html.Hr(),
            html.Div('Superponer', style={'fontWeight': 600, 'marginBottom': 6}),
            dcc.Checklist(id='overlays', value=['ruta', 'fuentes'], labelStyle={'display': 'block', 'margin': '5px 0', 'fontSize': 13},
                          options=[{'label': 'Ruta', 'value': 'ruta'}, {'label': 'Puntos de medicion', 'value': 'puntos'}, {'label': 'Fuentes estimadas (bonificacion)', 'value': 'fuentes'}]),
            html.Div('Los mapas de calor son interpolaciones IDW a <= 400 m de la ruta.', style={'fontSize': 11, 'color': MUTED, 'marginTop': 10})]),
        html.Div(style=PANEL, children=[dcc.Graph(id='mapa', style={'height': 640}, config={'scrollZoom': True})]),
        html.Div(style=PANEL, children=panel_indicadores()),
    ])

# ── Vista: Espectro ──────────────────────────────────────────────────────────
def vista_espectro():
    return html.Div([
        html.Div(f"Frecuencia mas critica de toda la banda: {FQ['f_max_MHz']:.3f} MHz.", style={'fontSize': 13, 'color': MUTED, 'marginBottom': 12}),
        html.Div(style={'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': 12}, children=[
            imagen_card('cascada.png', 'Cascada temporal del espectro'),
            imagen_card('frecuencias.png', 'Potencia media por frecuencia'),
        ]),
    ])

# ── Vista: Calidad ───────────────────────────────────────────────────────────
def vista_calidad():
    ant = CAL.get('correccion_antena', {})
    filas = [html.Tr([html.Th(t) for t in ['Verificacion', 'Casos', 'Detalle']])] + [
        html.Tr([html.Td(c['verificacion']), html.Td(c['casos']), html.Td(c.get('detalle', ''))]) for c in CAL['checks']]
    return html.Div([
        html.Div([
            kpi(f"{CAL['completitud_pct']:.0f}%", 'completitud de espectros'),
            kpi(f"{CAL['gps_valido_pct']:.1f}%", 'GPS valido'),
            kpi(f"{ant.get('min_dB', 0):.2f}-{ant.get('max_dB', 0):.2f} dB", 'correccion antena (rango)', color=TEAL),
            kpi(CAL.get('valores_modificados_piso', 0), 'bins normalizados por piso de ruido'),
        ], style={'display': 'flex', 'gap': 12, 'marginBottom': 12}),
        html.Div(style={**PANEL, 'marginBottom': 12}, children=[
            html.Div('Correccion por desajuste de antena (barrido S11)', style={'fontWeight': 600, 'marginBottom': 6}),
            html.Div(f"Archivo: {ant.get('archivo', '-')} - perdida de {ant.get('min_dB', 0):.2f} a {ant.get('max_dB', 0):.2f} dB segun la frecuencia "
                     f"(media {ant.get('media_dB', 0):.2f} dB). Se aplico a todo el espectro antes del filtro de Hampel y la normalizacion del piso de ruido.",
                     style={'fontSize': 13, 'color': TEXT}),
        ]),
        html.Div(style={**PANEL, 'marginBottom': 12}, children=[
            html.Div('Verificaciones de calidad de datos', style={'fontWeight': 600, 'marginBottom': 8}),
            html.Table(filas, style={'width': '100%', 'fontSize': 12, 'borderCollapse': 'collapse'}),
        ]),
        html.Div(style={'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': 12}, children=[
            imagen_card('ruta.png', 'Ruta de medicion'),
            imagen_card('temperatura.png', 'Temperatura del sensor'),
        ]),
    ])

# ── Vista: Fuentes ───────────────────────────────────────────────────────────
def vista_fuentes():
    filas = [html.Tr([html.Th(t) for t in ['Canal', 'Metodo', 'Lat', 'Lon', 'Incertidumbre (m)']])] + [
        html.Tr([html.Td(c), html.Td(r.metodo), html.Td(f'{r.lat:.5f}'), html.Td(f'{r.lon:.5f}'), html.Td(f'{r.radio95_m:.0f}')])
        for c, r in FUE.iterrows()]
    return html.Div([
        html.Div('Fuente estimada de contaminacion por canal (bonificacion) - modelo de propagacion log-distancia, con respaldo de centroide ponderado cuando el ajuste es debil.',
                 style={'fontSize': 13, 'color': MUTED, 'marginBottom': 12}),
        html.Div(style={**PANEL, 'marginBottom': 12}, children=[html.Table(filas, style={'width': '100%', 'fontSize': 13, 'borderCollapse': 'collapse'})]),
        imagen_card('fuentes.png', 'Fuentes estimadas sobre el mapa'),
    ])

RENDER_VISTA = {'inicio': vista_inicio, 'mapa': vista_mapa, 'espectro': vista_espectro, 'calidad': vista_calidad, 'fuentes': vista_fuentes}

app = Dash(__name__, title='Ocupacion 840-860 MHz - Medellin')
app.config.suppress_callback_exceptions = True
app.layout = html.Div(style={'fontFamily': 'system-ui, -apple-system, Segoe UI, sans-serif', 'display': 'flex', 'minHeight': '100vh', 'background': BG, 'color': TEXT}, children=[
    html.Div(id='sidebar', children=sidebar('inicio')),
    dcc.Store(id='vista', data='inicio'),
    html.Div(id='contenido', style={'flex': 1, 'padding': 16}, children=vista_inicio()),
])

@app.callback(Output('vista', 'data'), Input({'type': 'nav', 'index': dash.ALL}, 'n_clicks'), prevent_initial_call=True)
def cambiar_vista(_clicks):
    trig = dash.ctx.triggered_id
    if trig and isinstance(trig, dict):
        return trig['index']
    return dash.no_update

@app.callback(Output('contenido', 'children'), Output('sidebar', 'children'), Input('vista', 'data'))
def render_vista(vista):
    vista = vista or 'inicio'
    return RENDER_VISTA.get(vista, vista_inicio)(), sidebar(vista)

@app.callback(Output('mapa', 'figure'), Input('capa', 'value'), Input('overlays', 'value'))
def actualizar(capa, overlays):
    return crear_figura(capa, tuple(overlays or ()))

# ── Plan B: HTML estatico (sin servidor) ─────────────────────────────────
def exportar_estatico():
    figs = {k: crear_figura(k) for k in CAPAS}
    todas = go.Figure(layout=figs['canal_C'].layout)
    rangos, n = {}, 0
    for k, f in figs.items():
        for tr in f.data: todas.add_trace(tr)
        rangos[k] = list(range(n, n + len(f.data))); n += len(f.data)
    for i, tr in enumerate(todas.data): tr.visible = i in rangos['canal_C']
    todas.update_layout(updatemenus=[dict(type='dropdown', x=0.01, y=0.99, xanchor='left', yanchor='top', active=list(CAPAS).index('canal_C'), buttons=[
        dict(label=CAPAS[k][0], method='update', args=[{'visible': [i in rangos[k] for i in range(n)]}]) for k in CAPAS])])
    todas.write_html(f'{OUT}/dashboard_estatico.html', include_plotlyjs='cdn')
    print('Guardado:', f'{OUT}/dashboard_estatico.html')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--modo', choices=['server', 'estatico'], default='estatico')
    p.add_argument('--port', type=int, default=8050)
    args = p.parse_args()
    if args.modo == 'estatico':
        exportar_estatico()
    else:
        app.run(debug=False, host='0.0.0.0', port=args.port)
