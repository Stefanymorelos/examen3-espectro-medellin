"""
Examen 3 - Internet de las Cosas - Notebook 2/3: indicadores, recomendacion e informe
Version script de 02_indicadores_informe.ipynb, adaptada para correr sin Colab/Drive.
"""
import os, json, base64, re
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import least_squares

try:
    from google.colab import drive
    drive.mount('/content/drive')
    BASE = '/content/drive/MyDrive/IoT_Examen3'
except ImportError:
    BASE = os.path.abspath('..')
OUT, FIGS = f'{BASE}/data/salida', f'{BASE}/data/salida/figs'

UMBRAL_DBM    = -60.0
MODO_POTENCIA = 'media'
USAR_PISO     = True
INCLUIR_CHISTE = True
OCUP_RECOMENDADO, OCUP_NO_RECOMENDADO = 25.0, 50.0

M = pd.read_csv(f'{OUT}/medidas_limpias.csv', parse_dates=['hora'])
D = np.load(f'{OUT}/espectros.npz')
S = D['S_final'] if USAR_PISO else D['S_clean']
S_CLEAN, FREQ = D['S_clean'], D['freq']
calidad = json.load(open(f'{OUT}/calidad.json'))
CANALES = {'A': (840, 845), 'B': (845, 850), 'C': (850, 855), 'D': (855, 860)}
SL = {c: slice(int(np.searchsorted(FREQ, lo - 1e-9)), int(np.searchsorted(FREQ, hi - 1e-9))) for c, (lo, hi) in CANALES.items()}
print({c: (s.stop - s.start) for c, s in SL.items()}, 'bins por canal |', S.shape[0], 'mediciones')

def potencia_canal(Sx, sl, modo=MODO_POTENCIA):
    lineal = 10 ** (Sx[:, sl] / 10)
    p = lineal.mean(axis=1) if modo == 'media' else lineal.sum(axis=1)
    return 10 * np.log10(p)

P = pd.DataFrame({f'P_{c}': potencia_canal(S, SL[c]) for c in CANALES})
Pc = pd.DataFrame({f'P_{c}': potencia_canal(S_CLEAN, SL[c]) for c in CANALES})
ocupado = P > UMBRAL_DBM
ind = pd.concat([M[['orden', 'hora', 'lat', 'lon', 'temp']], P, ocupado.add_prefix('ocup_')], axis=1)

def resumen_canales(Sx, modo=MODO_POTENCIA):
    filas = []
    for c in CANALES:
        p = potencia_canal(Sx, SL[c], modo)
        filas.append({'Canal': c, 'Banda (MHz)': f'{CANALES[c][0]}-{CANALES[c][1]}',
                      'Ocupacion (% de mediciones > umbral)': 100 * (p > UMBRAL_DBM).mean(),
                      'Potencia media (dBm)': 10 * np.log10((10 ** (p / 10)).mean()),
                      'Mediana (dBm)': np.median(p), 'P90 (dBm)': np.percentile(p, 90), 'Max (dBm)': p.max(),
                      '% bins > umbral': 100 * (Sx[:, SL[c]] > UMBRAL_DBM).mean()})
    return pd.DataFrame(filas).set_index('Canal')

R = resumen_canales(S)
OC = 'Ocupacion (% de mediciones > umbral)'
orden_cont = R.sort_values([OC, 'Potencia media (dBm)'], ascending=False).index.tolist()
R['Ranking (1 = mas contaminado)'] = [orden_cont.index(c) + 1 for c in R.index]

def wilson(k, n, z=1.96):
    p = k / n; den = 1 + z**2 / n
    c = (p + z**2 / (2*n)) / den; h = z * np.sqrt(p*(1-p)/n + z**2/(4*n**2)) / den
    return 100*(c - h), 100*(c + h)
n_med = len(P)
ci = {c: wilson(int(ocupado[f'P_{c}'].sum()), n_med) for c in CANALES}
R['IC95 ocupacion (%)'] = [f'{ci[c][0]:.0f}-{ci[c][1]:.0f}' for c in R.index]
print(R.round(1).to_string())
canal_max, canal_min = orden_cont[0], orden_cont[-1]
print(f'Mas contaminado: Canal {canal_max} | menos contaminado: Canal {canal_min}')

sens = pd.DataFrame({
  'Ocup. % (indicadores)': R['Ocupacion (% de mediciones > umbral)'],
  'Ocup. % sin piso':      resumen_canales(S_CLEAN)['Ocupacion (% de mediciones > umbral)'],
  'Ocup. % potencia suma': resumen_canales(S, 'suma')['Ocupacion (% de mediciones > umbral)']}).round(1)
print(sens.to_string())

# ── 3. Frecuencia mas y menos contaminada ────────────────
lin = 10 ** (S / 10)
FQ = pd.DataFrame({'f_MHz': FREQ, 'pot_media_dBm': 10 * np.log10(lin.mean(axis=0)),
                   'ocupacion_pct': 100 * (S > UMBRAL_DBM).mean(axis=0), 'max_dBm': S.max(axis=0)})
FQ['canal'] = [next(c for c, sl in SL.items() if sl.start <= i < sl.stop) for i in range(len(FQ))]
rank = FQ.sort_values(['ocupacion_pct', 'pot_media_dBm'], ascending=False)
i_max, i_min = rank.index[0], rank.index[-1]
f_max, f_min = FQ.loc[i_max], FQ.loc[i_min]
print(f'Mas contaminada: {f_max.f_MHz:.3f} MHz (canal {f_max.canal}) - ocupacion {f_max.ocupacion_pct:.0f} %, potencia media {f_max.pot_media_dBm:.1f} dBm')
print(f'Menos contaminada: {f_min.f_MHz:.3f} MHz (canal {f_min.canal}) - ocupacion {f_min.ocupacion_pct:.0f} %, potencia media {f_min.pot_media_dBm:.1f} dBm')

ind['P_fmax'], ind['P_fmin'] = S[:, i_max], S[:, i_min]
ind.to_csv(f'{OUT}/indicadores_medidas.csv', index=False)
json.dump({'f_max_MHz': float(f_max.f_MHz), 'f_min_MHz': float(f_min.f_MHz), 'canal_max_freq': f_max.canal, 'canal_min_freq': f_min.canal,
           'canal_mas_contaminado': canal_max, 'canal_menos_contaminado': canal_min, 'umbral_dBm': UMBRAL_DBM},
          open(f'{OUT}/frecuencias.json', 'w'))

fig, ax = plt.subplots(1, 2, figsize=(15, 4.6))
ax[0].plot(FQ.f_MHz, FQ.pot_media_dBm, lw=1, label='potencia media')
ax[0].plot(FQ.f_MHz, FQ.max_dBm, lw=.6, color='0.7', label='maximo')
ax[0].axhline(UMBRAL_DBM, color='r', ls='--', label=f'umbral {UMBRAL_DBM:.0f} dBm')
for (lo, hi), c, col in zip(CANALES.values(), CANALES, ['#e8f0fe', '#fef3e0', '#e6f4ea', '#fce8e6']):
    ax[0].axvspan(lo, hi, color=col, zorder=0); ax[0].text((lo + hi) / 2, ax[0].get_ylim()[0] + 2, f'Canal {c}', ha='center')
ax[0].scatter([f_max.f_MHz], [f_max.pot_media_dBm], c='r', zorder=5, label=f'mas contaminada {f_max.f_MHz:.2f} MHz')
ax[0].scatter([f_min.f_MHz], [f_min.pot_media_dBm], c='g', zorder=5, label=f'menos contaminada {f_min.f_MHz:.2f} MHz')
ax[0].set_xlabel('MHz'); ax[0].set_ylabel('dBm'); ax[0].set_title('Espectro medio del sistema'); ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)
ax[1].plot(M.orden, S[:, i_max], 'r.-', label=f'{f_max.f_MHz:.2f} MHz (mas contaminada)')
ax[1].plot(M.orden, S[:, i_min], 'g.-', label=f'{f_min.f_MHz:.2f} MHz (menos contaminada)')
ax[1].axhline(UMBRAL_DBM, color='k', ls='--', lw=1); ax[1].set_xlabel('n.o de medicion (a lo largo de la ruta)'); ax[1].set_ylabel('dBm')
ax[1].set_title('Potencia por medicion'); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)
plt.savefig(f'{FIGS}/frecuencias.png', dpi=140, bbox_inches='tight'); plt.close()

fig, ax = plt.subplots(1, 2, figsize=(12, 4))
cols = ['#4c78a8', '#f58518', '#54a24b', '#e45756']
ax[0].bar(R.index, R['Ocupacion (% de mediciones > umbral)'], color=cols)
for i, v in enumerate(R['Ocupacion (% de mediciones > umbral)']): ax[0].text(i, v + 1, f'{v:.0f} %', ha='center')
ax[0].set_ylabel('% de mediciones con P > -60 dBm'); ax[0].set_title('Ocupacion por canal'); ax[0].set_ylim(0, 105)
ax[1].boxplot([P[f'P_{c}'] for c in CANALES]); ax[1].set_xticklabels(list(CANALES)); ax[1].axhline(UMBRAL_DBM, color='r', ls='--')
ax[1].set_ylabel('dBm'); ax[1].set_title('Potencia media del canal por medicion')
for a in ax: a.grid(alpha=.3)
plt.savefig(f'{FIGS}/canales.png', dpi=140, bbox_inches='tight'); plt.close()

# ── 4. Dictamen tecnico ───────────────────────────────────────────
def dictamen(oc):
    if oc < OCUP_RECOMENDADO:     return 'Recomendado'
    if oc < OCUP_NO_RECOMENDADO:  return 'Condicionado'
    return 'No recomendado'
R['Dictamen'] = R[OC].map(dictamen)
print(R[['Banda (MHz)', OC, 'IC95 ocupacion (%)', 'Potencia media (dBm)', 'Dictamen']].round(1).to_string())
R.round(1).to_csv(f'{OUT}/resumen_canales.csv')

similares = [c for c in R.index if c != canal_min and ci[c][0] <= ci[canal_min][1]]
corr_canales = P.corr().values[np.triu_indices(4, 1)]
print('Canales indistinguibles del menos contaminado:', similares)
print(f'Correlacion entre potencias de canal: {corr_canales.min():.2f} - {corr_canales.max():.2f}')

# ── 5. BONIFICACION: fuente por canal ────────────
R2_MIN, D_MIN, MARGEN = 0.5, 30.0, 5000.0
R_T = 6371000.0
lat0, lon0 = M.lat.mean(), M.lon.mean()
to_xy   = lambda lat, lon: (np.radians(lon - lon0) * R_T * np.cos(np.radians(lat0)), np.radians(lat - lat0) * R_T)
from_xy = lambda x, y: (lat0 + np.degrees(y / R_T), lon0 + np.degrees(x / (R_T * np.cos(np.radians(lat0)))))
X, Y = to_xy(M.lat.values, M.lon.values)

def modelo(p, x, y, ruido):
    d = np.maximum(np.hypot(x - p[0], y - p[1]), D_MIN)
    return 10 * np.log10(10 ** ((p[2] - 10 * p[3] * np.log10(d)) / 10) + 10 ** (ruido / 10))

def ajustar(pot, ruido):
    lim = ([X.min() - MARGEN, Y.min() - MARGEN, -100, 2.0], [X.max() + MARGEN, Y.max() + MARGEN, 250, 4.5])
    mejor = None
    for gx in np.linspace(X.min() - 1500, X.max() + 1500, 6):
        for gy in np.linspace(Y.min() - 1500, Y.max() + 1500, 6):
            r = least_squares(lambda p: modelo(p, X, Y, ruido) - pot, [gx, gy, pot.mean() + 90, 3.0], bounds=lim, loss='soft_l1', f_scale=3.0)
            if mejor is None or r.cost < mejor.cost: mejor = r
    return mejor

def centroide(pot, idx):
    top = idx[pot[idx] >= np.percentile(pot[idx], 90)]
    w = 10 ** (pot[top] / 10)
    return (X[top] * w).sum() / w.sum(), (Y[top] * w).sum() / w.sum()

rng = np.random.default_rng(42)
fuentes = []
for c in CANALES:
    pot = Pc[f'P_{c}'].values
    ruido = np.percentile(pot, 5)
    sol = ajustar(pot, ruido); pred = modelo(sol.x, X, Y, ruido)
    r2 = 1 - np.sum((pot - pred) ** 2) / np.sum((pot - pot.mean()) ** 2)
    cx, cy = centroide(pot, np.arange(len(pot)))
    boot = np.array([centroide(pot, rng.integers(0, len(pot), len(pot))) for _ in range(300)])
    rad95 = np.percentile(np.hypot(boot[:, 0] - np.median(boot[:, 0]), boot[:, 1] - np.median(boot[:, 1])), 95)
    usar_modelo = r2 >= R2_MIN
    fx, fy = (sol.x[0], sol.x[1]) if usar_modelo else (cx, cy)
    lat_f, lon_f = from_xy(fx, fy); lat_m, lon_m = from_xy(sol.x[0], sol.x[1])
    fuentes.append({'canal': c, 'lat': lat_f, 'lon': lon_f, 'metodo': 'log-distancia' if usar_modelo else 'centroide ponderado',
                    'radio95_m': rad95, 'R2_modelo': r2, 'n_perdidas': sol.x[3], 'lat_modelo': lat_m, 'lon_modelo': lon_m,
                    'dist_a_ruta_m': float(np.min(np.hypot(X - fx, Y - fy)))})
F = pd.DataFrame(fuentes).set_index('canal')
F.to_csv(f'{OUT}/fuentes.csv')
print(F.round(4).to_string())

fig, ax = plt.subplots(1, 4, figsize=(18, 4.6), sharey=True)
for a, c in zip(ax, CANALES):
    sc = a.scatter(M.lon, M.lat, c=Pc[f'P_{c}'], cmap='inferno', s=35, vmin=-90, vmax=-10)
    a.scatter(F.lon[c], F.lat[c], marker='*', s=300, c='cyan', edgecolors='k', zorder=5, label='fuente estimada')
    a.set_title(f'Canal {c}'); a.set_aspect(1 / np.cos(np.radians(lat0))); a.grid(alpha=.3); a.set_xlabel('Longitud')
ax[0].set_ylabel('Latitud'); ax[0].legend(loc='lower left'); plt.colorbar(sc, ax=ax, label='dBm', shrink=.8)
plt.savefig(f'{FIGS}/fuentes.png', dpi=140, bbox_inches='tight'); plt.close()

# ── 6. Informe tecnico ──────────────────────
def tabla_md(df, dec=1):
    df = df.copy(); cab = '| ' + ' | '.join(map(str, df.columns)) + ' |\n|' + '---|' * len(df.columns) + '\n'
    filas = ''.join('| ' + ' | '.join(f'{v:.{dec}f}' if isinstance(v, (float, np.floating)) else str(v) for v in r) + ' |\n' for r in df.values)
    return cab + filas

Ft = F.reset_index()[['canal', 'lat', 'lon', 'metodo', 'radio95_m', 'R2_modelo', 'n_perdidas']].copy()
Ft['lat'], Ft['lon'] = Ft.lat.map('{:.5f}'.format), Ft.lon.map('{:.5f}'.format)
Ft['radio95_m'], Ft['R2_modelo'], Ft['n_perdidas'] = Ft.radio95_m.map('{:.0f}'.format), Ft.R2_modelo.map('{:.2f}'.format), Ft.n_perdidas.map('{:.1f}'.format)
q, T = calidad, calidad['temperatura']
chk = pd.DataFrame(q['checks']).rename(columns={'verificacion': 'Verificacion', 'casos': 'Casos', 'detalle': 'Detalle'})
imp = pd.DataFrame(q['imputaciones'])
imp.columns = ['Problema', 'Tecnica', 'Valores modificados', 'Motivo', '% del total']
ant = q['correccion_antena']
ruta = q['ruta']
tr = pd.DataFrame(T['tabla'])[['indicador', 'Pearson r', 'p', 'r parcial (ctrl. tiempo)', 'p (parcial)']]
concl_temp = ('**No se encuentra una incidencia significativa** de la temperatura sobre la calidad de las medidas: las correlaciones brutas son debiles y '
              'la variable esta fuertemente confundida con el tiempo (r = %.2f; el sensor se calienta a lo largo del recorrido); al controlar el tiempo desaparecen.' % T['r_tiempo']
              if not T['incidencia_significativa'] else
              '**Existe una incidencia estadisticamente significativa** de la temperatura (persiste al controlar el tiempo) que debe considerarse al comparar mediciones.')

tabla_can = R[['Banda (MHz)', OC, 'IC95 ocupacion (%)', 'Potencia media (dBm)', 'Mediana (dBm)', 'P90 (dBm)', 'Dictamen']].reset_index().round(1)
nota_sim = (f'El intervalo de confianza del canal {canal_min} se traslapa con el de {", ".join(similares)}: con {n_med} mediciones esos canales no son estadisticamente distinguibles entre si; la diferencia significativa es la del canal {canal_max}.' if similares else '')
rec_ok  = [c for c in R.index if R.Dictamen[c] == 'Recomendado']
rec_no  = [c for c in R.index if R.Dictamen[c] == 'No recomendado']
rec_cnd = [c for c in R.index if R.Dictamen[c] == 'Condicionado']
lista = lambda cs: ', '.join(f'Canal {c} ({CANALES[c][0]}-{CANALES[c][1]} MHz)' for c in cs) or 'ninguno'
uso_piso = 'Se aplico la regla de normalizacion del enunciado (valores < -65 dB -> -95 dB)' if q['aplicar_piso'] else 'No se aplico la regla de piso de ruido'

md_txt = f'''# Informe tecnico - Ocupacion del espectro 840-860 MHz, occidente de Medellin
*Examen 3, Internet de las Cosas - Analisis para la Agencia Nacional del Espectro (ANE)*
**Analista:** Stefany Morelos

## Resumen ejecutivo
Trabaje con **{q['mediciones_validas']} mediciones** tomadas por una estacion movil (banda 840-860 MHz, 1024 bins, resolucion de aprox. 19.5 kHz por bin) a lo largo de una ruta de {ruta['longitud_km']:.1f} km en el occidente de Medellin.
Con esos datos, el canal **mas contaminado resulto ser el {canal_max}** ({CANALES[canal_max][0]}-{CANALES[canal_max][1]} MHz, ocupado en el {R[OC][canal_max]:.0f} % de las mediciones) y el **menos contaminado el {canal_min}**
({R[OC][canal_min]:.0f} %). Viendo frecuencia por frecuencia, la mas contaminada de todo el sistema es {f_max.f_MHz:.2f} MHz y la menos contaminada {f_min.f_MHz:.2f} MHz.

## 1. Datos de los sensores
### 1.1 Calidad de los datos
Antes de calcular cualquier indicador revise que tan confiables eran los datos crudos. La completitud de los espectros quedo en {q['completitud_pct']:.1f} % y las posiciones GPS validas en {q['gps_valido_pct']:.1f} % (es decir, casi todo estaba en buen estado, pero no todo).

{tabla_md(chk)}
### 1.2 Imputaciones y correcciones
Sin contar la regla de piso que pide el enunciado, modifique **{q['valores_modificados_sin_piso']}** valores; contando esa regla, el total sube a **{q['valores_modificados_sin_piso'] + (q['valores_modificados_piso'] if q['aplicar_piso'] else 0)}** (de {q['valores_totales_espectro']} valores de espectro en total). {uso_piso}.

{tabla_md(imp, 3)}
Por que hice cada correccion: cuando el GPS no tiene fix (lat = lon = 0) o el HDOP es mayor a 5, la posicion no es confiable, asi que la reconstruyo interpolando entre las mediciones vecinas en el tiempo. La espiga que aparece siempre en 850.000 MHz no es una senal real, es un artefacto conocido de los receptores de conversion directa (fuga del oscilador local), por eso la reemplazo con el promedio de sus vecinos. Las espigas angostas (1-2 bins) tampoco pueden ser senales celulares reales -esas ocupan decenas de bins-, asi que las trato como ruido puntual y las corrijo con la mediana local. Las mediciones con posible saturacion ({', '.join(q['saturadas']) or 'ninguna'}) las dejo en el dataset pero marcadas, para no perder informacion.

Ademas de esas correcciones, el dataset trae `{ant['archivo']}`: un barrido S11 de la antena tomado con un analizador de redes. Ese archivo no es una medicion (mi filtro por regex lo descarta correctamente de la lista de mediciones), pero si es un dato de calibracion real del receptor, asi que lo uso para corregir la perdida de senal por desajuste de impedancia de la antena en la banda: interpolo el S11 a mis 1024 bins y le sumo a cada uno la perdida de desajuste correspondiente (perdida = -10*log10(1 - |Gamma|^2), con |Gamma|^2 = 10^(S11_dB/10)). En 840-860 MHz esa perdida va de {ant['min_dB']:.2f} a {ant['max_dB']:.2f} dB (media {ant['media_dB']:.2f} dB) -no es enorme, pero si suficiente para mover el dictamen de algunos canales que estaban cerca del umbral (ver seccion 2.2).

### 1.3 Ruta de la estacion movil
La ruta arranca en ({ruta['inicio'][0]:.5f}, {ruta['inicio'][1]:.5f}) y termina en ({ruta['fin'][0]:.5f}, {ruta['fin'][1]:.5f}): {ruta['longitud_km']:.1f} km recorridos en {ruta['duracion_min']:.0f} min
(unos {ruta['vel_media_kmh']:.0f} km/h en promedio), con altitud entre {ruta['alt_min']:.0f} y {ruta['alt_max']:.0f} m. El punto de inicio y el de fin quedan a solo {ruta['cierre_m']:.0f} m de distancia, o sea que el circuito casi se cierra.

![Ruta](figs/ruta.png)

### 1.4 Incidencia de la temperatura del sensor
La temperatura del sensor se movio entre {T['rango'][0]:.1f} y {T['rango'][1]:.1f} C durante la campana.

{tabla_md(tr, 3)}
{concl_temp}

![Temperatura](figs/temperatura.png)

## 2. Indicadores por canal
Para cada canal de 5 MHz calculo la potencia media con la identidad de Parseval discreta: P = (1/N) * Sum |X_k|^2 sobre los N = 256 bins que le corresponden (modo `{MODO_POTENCIA}`). Considero un canal ocupado/contaminado en una medicion si esa potencia supera {UMBRAL_DBM:.0f} dBm, tal como lo pide el enunciado.

{tabla_md(tabla_can)}
{nota_sim}

Tambien revise que tan sensible es este ranking a las decisiones que tome en la limpieza (por ejemplo, que pasa si no aplico la regla del piso, o si en vez de potencia promedio uso potencia total):

{tabla_md(sens.reset_index().rename(columns={'canal': 'Canal', 'index': 'Canal'}))}
![Canales](figs/canales.png)

### 2.1 Banda mas y menos contaminada
El **Canal {canal_max}** queda como el mas contaminado, con {R['Potencia media (dBm)'][canal_max]:.1f} dBm de potencia media, y el **Canal {canal_min}** como el menos contaminado, con {R['Potencia media (dBm)'][canal_min]:.1f} dBm.
Si miro frecuencia por frecuencia (no por canal completo), la mas contaminada es **{f_max.f_MHz:.3f} MHz** (ocupada en el {f_max.ocupacion_pct:.0f} % de las mediciones, {f_max.pot_media_dBm:.1f} dBm en promedio) y la menos contaminada **{f_min.f_MHz:.3f} MHz** ({f_min.ocupacion_pct:.0f} %, {f_min.pot_media_dBm:.1f} dBm).

![Frecuencias](figs/frecuencias.png)

### 2.2 Recomendacion tecnica para la Agencia
Use el siguiente criterio: ocupacion menor a {OCUP_RECOMENDADO:.0f} % -> *recomendado*; entre {OCUP_RECOMENDADO:.0f} % y {OCUP_NO_RECOMENDADO:.0f} % -> *condicionado*; {OCUP_NO_RECOMENDADO:.0f} % o mas -> *no recomendado*. Con base en eso, mi recomendacion para la ANE es:
- **Recomendados:** {lista(rec_ok)}.
- **Condicionados (necesitan coordinacion o alguna medida de mitigacion antes de asignarse):** {lista(rec_cnd)}.
- **No recomendados:** {lista(rec_no)}.

## 3. Bonificacion - ubicacion estimada de las fuentes
Para estimar de donde viene la contaminacion de cada canal, probe dos metodos: un modelo de propagacion log-distancia (que extrapola hacia atras de donde tuvo que salir la senal) y, como respaldo, el centroide ponderado del 10 % de los puntos con mas potencia. Solo me quedo con el modelo si de verdad explica los datos (R^2 >= {R2_MIN}); si no, uso el centroide y lo dejo claro en la tabla para no inflar la confianza del resultado. La incertidumbre la calculo con bootstrap (radio del 95 %).

{tabla_md(Ft)}
![Fuentes](figs/fuentes.png)

## 4. Limitaciones
Para ser honesta con lo que si puedo afirmar y lo que no:
- Los niveles vienen de una captura *max-hold* de 100 espectros, sin una calibracion absoluta documentada del receptor (dBFS); por eso mis conclusiones son comparativas entre canales, no valores absolutos certificados.
- Fue una sola campana de ~{ruta['duracion_min']:.0f} minutos, asi que no alcanza a capturar como varia la ocupacion en otras horas del dia.
- Las potencias de los canales A, B y D estan bastante correlacionadas entre si (r entre {corr_canales.min():.2f} y {corr_canales.max():.2f}) y sus picos coinciden con los del canal C. Esto me hace sospechar que parte de la "contaminacion" que veo puede deberse a que el receptor se satura o intermodula cuando llega una senal fuerte (la medicion {', '.join(q['saturadas']) or 'ninguna'} quedó marcada por eso). Si se repite la campana, recomendaria usar un atenuador o un filtro pasabanda.
- La estimacion de fuentes es la parte menos solida del analisis: el modelo log-distancia explica poca varianza (R^2 maximo de {F.R2_modelo.max():.2f}) porque hay multitrayecto, probablemente varias fuentes simultaneas y la captura es max-hold; tomo las coordenadas resultantes como una localizacion aproximada, no como una direccion exacta.
'''
if INCLUIR_CHISTE:
    md_txt += '\n---\n*Para cerrar:* Por que el gato no confia en el WiFi de la casa? Porque cada vez que salta a la mesa, la senal se cae.\n'

open(f'{OUT}/informe_tecnico.md', 'w').write(md_txt)
import markdown
html = markdown.markdown(md_txt, extensions=['tables'])
html = re.sub(r'src="(figs/[^"]+)"', lambda m: 'src="data:image/png;base64,' + base64.b64encode(open(f'{OUT}/{m.group(1)}', 'rb').read()).decode() + '"', html)
css = '<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2em auto;line-height:1.5}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:3px 8px;font-size:.9em}img{max-width:100%}</style>'
open(f'{OUT}/informe_tecnico.html', 'w').write(f'<meta charset="utf-8">{css}{html}')
print('Informe guardado en', f'{OUT}/informe_tecnico.html')
print('OK - NOTEBOOK 2 COMPLETADO')
