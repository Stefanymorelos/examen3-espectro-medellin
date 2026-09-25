"""
Examen 3 - Internet de las Cosas - Notebook 1/3: ETL y calidad de datos
Banda 840-860 MHz - estacion movil de monitoreo - occidente de Medellin

Version script (identica en logica a 01_ETL_calidad.ipynb), adaptada para
correr fuera de Google Colab (sin montar Drive).
"""
import os, glob, re, json, zipfile, warnings, datetime as dt
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats, ndimage
from scipy.ndimage import median_filter
warnings.filterwarnings('ignore')

# ── 1. Entorno y parametros ────────────────────────────────────────────────
try:
    from google.colab import drive
    drive.mount('/content/drive')
    BASE, EN_COLAB = '/content/drive/MyDrive/IoT_Examen3', True
except ImportError:
    BASE, EN_COLAB = os.path.abspath('..'), False
RAW, OUT = f'{BASE}/data/raw/extracted', f'{BASE}/data/salida'
FIGS = f'{OUT}/figs'
for d in (RAW, OUT, FIGS): os.makedirs(d, exist_ok=True)

FC_MHZ, FS_MHZ, NFFT = 850.0, 20.0, 1024
FREQ = FC_MHZ - FS_MHZ/2 + np.arange(NFFT) * FS_MHZ / NFFT
BIN_DC = NFFT // 2

HDOP_MAX         = 5.0
TEMP_RANGO       = (0, 85)
SATURACION_DBFS  = -5.0
HAMPEL_VENTANA, HAMPEL_K, HAMPEL_ANCHO_MAX = 11, 6, 2

APLICAR_PISO = True
PISO_UMBRAL, PISO_VALOR = -65.0, -95.0

# ── 2. EXTRACT: descomprimir y leer los 1029 valores de cada archivo ───────
ZIP = f'{BASE}/data/raw/Examen_03_2026_20_medidas.zip'
if not os.path.exists(ZIP):
    if EN_COLAB:
        from google.colab import files
        subido = files.upload()
        os.replace(next(iter(subido)), ZIP)
    else:
        raise FileNotFoundError(ZIP)

with zipfile.ZipFile(ZIP) as z:
    miembros = [m for m in z.namelist() if not m.startswith('__MACOSX')]
    z.extractall(RAW, members=miembros)
    horas = {os.path.basename(i.filename): pd.Timestamp(dt.datetime(*i.date_time)) for i in z.infolist()}

DATA_DIR = os.path.dirname(glob.glob(f'{RAW}/**/001.txt', recursive=True)[0])
COLS_META = ['temp', 'lon', 'lat', 'alt', 'hdop']

filas, espectros, rechazados = [], [], []
for f in sorted(glob.glob(f'{DATA_DIR}/*.txt')):
    nombre = os.path.basename(f)
    try:
        v = np.array(open(f).read().replace('\n', ',').strip().strip(',').split(','), dtype=float)
    except ValueError:
        rechazados.append((nombre, 'contenido no numerico')); continue
    if v.size != NFFT + 5:
        rechazados.append((nombre, f'{v.size} columnas (esperadas {NFFT+5})')); continue
    es_med = re.fullmatch(r'\d{3}\.txt', nombre) is not None
    filas.append({'archivo': nombre, 'tipo': 'medicion' if es_med else 'prueba',
                  'orden': int(nombre[:3]) if es_med else np.nan, 'hora': horas.get(nombre),
                  **dict(zip(COLS_META, v[NFFT:]))})
    espectros.append(v[:NFFT])

meta_all = pd.DataFrame(filas)
S_all = np.vstack(espectros)
print(f'Archivos leidos: {len(meta_all)} | rechazados por estructura: {len(rechazados)}')
print(meta_all.tipo.value_counts().to_string())

# ── 3. TRANSFORM (a): descarte de archivos de prueba ────────────────────────
mask_med = (meta_all.tipo == 'medicion').values
M = meta_all[mask_med].sort_values('orden').reset_index(drop=True)
S_raw = S_all[mask_med][np.argsort(meta_all.orden[mask_med].values)]
n_desc = int((~mask_med).sum())
print(f'Mediciones validas de campana: {len(M)} | pruebas descartadas: {n_desc} -> {meta_all.archivo[~mask_med].tolist()}')

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2-p1)/2)**2 + np.cos(p1)*np.cos(p2)*np.sin(np.radians(lon2-lon1)/2)**2
    return 2*R*np.arcsin(np.sqrt(a))

gps_cero   = ((M.lat == 0) & (M.lon == 0)).values
hdop_alto  = (M.hdop > HDOP_MAX).values
gps_malo   = gps_cero | hdop_alto | (M.alt == 0).values
temp_fuera = ~M.temp.between(*TEMP_RANGO).values
saturada   = (S_raw.max(axis=1) > SATURACION_DBFS)
spec_invalido = ~np.isfinite(S_raw).all(axis=1) | (S_raw.max(axis=1) > 0) | (S_raw.min(axis=1) < -120)

checks = [
 ('Archivos con estructura valida (1024 + 5 columnas)', len(filas), f'{len(rechazados)} rechazados'),
 ('Valores NaN / infinitos en espectros', int((~np.isfinite(S_all)).sum()), ''),
 ('Espectros fuera de rango fisico (>0 dB o <-120 dB)', int(spec_invalido.sum()), ''),
 ('GPS sin fijar (lat=lon=0, alt=0)', int(gps_cero.sum()), ', '.join(M.archivo[gps_cero])),
 (f'GPS con HDOP > {HDOP_MAX}', int(hdop_alto.sum()), ', '.join(f'{a} (HDOP {h})' for a, h in zip(M.archivo[hdop_alto], M.hdop[hdop_alto]))),
 ('Temperatura fuera de rango operativo', int(temp_fuera.sum()), ''),
 ('Espectros con posible saturacion (pico > %.0f dB)' % SATURACION_DBFS, int(saturada.sum()), ', '.join(M.archivo[saturada])),
 ('Archivos de prueba descartados', n_desc, ', '.join(meta_all.archivo[~mask_med])),
]
print(pd.DataFrame(checks, columns=['verificacion', 'casos', 'detalle']).to_string(index=False))

# ── 4. TRANSFORM (c): imputacion de GPS ─────────────────────────────────────
M['gps_imputado'] = gps_malo
for c in ['lat', 'lon', 'alt']:
    M[c + '_orig'] = M[c]
    serie = pd.Series(np.where(gps_malo, np.nan, M[c]), index=M.orden)
    M[c] = serie.interpolate('index', limit_direction='both').values

con_coord = gps_malo & ~gps_cero
desplaz = haversine(M.lat_orig, M.lon_orig, M.lat, M.lon)[con_coord]
print('Puntos GPS imputados:', M.archivo[gps_malo].tolist())
print('Desplazamiento aplicado a puntos con coordenadas originales (m):', np.round(desplaz.values, 1).tolist())

M['dist_prev_m'] = np.r_[np.nan, haversine(M.lat.values[:-1], M.lon.values[:-1], M.lat.values[1:], M.lon.values[1:])]
print(f'Distancia entre mediciones consecutivas: mediana {M.dist_prev_m.median():.0f} m, max {M.dist_prev_m.max():.0f} m')

# ── 5. TRANSFORM (d): limpieza de espectros ─────────────────────────────────
S_clean = S_raw.copy()

dc_antes = S_clean[:, BIN_DC] - 0.5*(S_clean[:, BIN_DC-1] + S_clean[:, BIN_DC+1])
S_clean[:, BIN_DC] = 0.5*(S_clean[:, BIN_DC-1] + S_clean[:, BIN_DC+1])
n_dc = S_clean.shape[0]

# ── 5b. Correccion por desajuste de antena (S11, calibracion del receptor) ──
# El dataset trae ANTENNA1.csv: barrido S11 de la antena (analizador de redes,
# 700-950 MHz). Se usa para corregir la perdida de senal por desajuste de
# impedancia en la banda medida -es una correccion de calibracion del receptor,
# no una imputacion de datos faltantes.
ANTENNA_CSV = f'{DATA_DIR}/ANTENNA1.csv'

def cargar_s11(path):
    freqs, s11v, leyendo = [], [], False
    for linea in open(path):
        linea = linea.strip()
        if linea == 'BEGIN': leyendo = True; continue
        if linea == 'END': break
        if leyendo and linea:
            fr, s = linea.split(',')
            freqs.append(float(fr) / 1e6); s11v.append(float(s))
    return np.array(freqs), np.array(s11v)

freq_s11, s11 = cargar_s11(ANTENNA_CSV)
s11_bins = np.interp(FREQ, freq_s11, s11)             # S11 (dB) interpolado a los 1024 bins
gamma2 = 10 ** (s11_bins / 10)                          # |Gamma|^2 = 10^(S11_dB/10)
perdida_desajuste_dB = -10 * np.log10(1 - gamma2)       # perdida de desajuste (dB), siempre > 0
S_clean += perdida_desajuste_dB[None, :]
print(f'Correccion por desajuste de antena (S11): {perdida_desajuste_dB.min():.2f} a '
      f'{perdida_desajuste_dB.max():.2f} dB en la banda (media {perdida_desajuste_dB.mean():.2f} dB)')

def espigas_aisladas(S, w, k, ancho_max):
    med = median_filter(S, size=(1, w), mode='nearest')
    mad = np.maximum(median_filter(np.abs(S - med), size=(1, w), mode='nearest') * 1.4826, 1.0)
    cand = (S - med) > k * mad
    cand[:, BIN_DC-1:BIN_DC+2] = False
    mask = np.zeros_like(cand)
    for i in range(S.shape[0]):
        etiquetas, n = ndimage.label(cand[i])
        for j in range(1, n + 1):
            idx = np.where(etiquetas == j)[0]
            if idx.size <= ancho_max: mask[i, idx] = True
    return mask, med

mask_pico, mediana_local = espigas_aisladas(S_clean, HAMPEL_VENTANA, HAMPEL_K, HAMPEL_ANCHO_MAX)
S_clean[mask_pico] = mediana_local[mask_pico]
n_picos = int(mask_pico.sum())

S_final = S_clean.copy()
mask_piso = (S_final < PISO_UMBRAL) if APLICAR_PISO else np.zeros_like(S_final, bool)
S_final[mask_piso] = PISO_VALOR
n_piso = int(mask_piso.sum())

M['saturacion'] = saturada
M['picos_corregidos'] = mask_pico.sum(axis=1)
print(f'Espiga DC corregida en {n_dc} espectros (media +{dc_antes.mean():.1f} dB sobre los vecinos)')
print(f'Espigas aisladas imputadas: {n_picos} bins en {int((mask_pico.any(axis=1)).sum())} espectros')
print(f'Regla piso (<{PISO_UMBRAL} -> {PISO_VALOR}): {n_piso} bins ({100*n_piso/S_raw.size:.1f} % de los datos) | APLICAR_PISO={APLICAR_PISO}')

# ── 6. Reporte de calidad e imputaciones ────────────────────────────────────
total_esp = S_raw.size
imput = pd.DataFrame([
 ('GPS sin fijar (lat, lon, alt)',              'Interpolacion lineal entre vecinos', int(gps_cero.sum())*3,  'Sin fix: coordenadas = 0'),
 (f'GPS con HDOP > {HDOP_MAX} (lat, lon, alt)', 'Interpolacion lineal entre vecinos', int((hdop_alto & ~gps_cero).sum())*3, 'Precision horizontal no confiable'),
 ('Espiga DC (bin 850.000 MHz)',                'Promedio de bins vecinos',           n_dc,     'Artefacto de conversion directa'),
 ('Espigas aisladas <=2 bins',                   'Mediana local (11 bins)',            n_picos,  'Ruido/interferencia espuria'),
 (f'Piso de ruido (<{PISO_UMBRAL} -> {PISO_VALOR} dB)', 'Sustitucion (regla del enunciado)', n_piso if APLICAR_PISO else 0, 'Normaliza el piso de ruido'),
], columns=['problema', 'tecnica', 'valores modificados', 'motivo'])
imput['% del total'] = (100 * imput['valores modificados'] / (total_esp + M.shape[0]*3)).round(3)
print(imput.to_string(index=False))

n_modif_sin_piso = int(imput['valores modificados'][:4].sum())
calidad = {
  'mediciones_validas': int(len(M)), 'pruebas_descartadas': n_desc, 'rechazados_estructura': len(rechazados),
  'completitud_pct': 100.0 * np.isfinite(S_all).mean(),
  'gps_valido_pct': 100.0 * (~gps_malo).mean(),
  'checks': [dict(verificacion=a, casos=b, detalle=c) for a, b, c in checks],
  'imputaciones': imput.to_dict('records'),
  'valores_modificados_sin_piso': n_modif_sin_piso, 'valores_modificados_piso': int(n_piso),
  'valores_totales_espectro': int(total_esp), 'aplicar_piso': bool(APLICAR_PISO),
  'saturadas': M.archivo[saturada].tolist(),
  'correccion_antena': {'archivo': os.path.basename(ANTENNA_CSV), 'min_dB': float(perdida_desajuste_dB.min()),
                         'max_dB': float(perdida_desajuste_dB.max()), 'media_dB': float(perdida_desajuste_dB.mean())},
}
print(f"Completitud: {calidad['completitud_pct']:.1f} % | GPS valido: {calidad['gps_valido_pct']:.1f} % | Modificados (sin piso): {n_modif_sin_piso} | con piso: {n_modif_sin_piso + n_piso}")

# ── 7. Ruta de la estacion movil ────────────────────────────────────────────
ruta_km   = M.dist_prev_m.sum() / 1000
cierre_m  = haversine(M.lat.iloc[0], M.lon.iloc[0], M.lat.iloc[-1], M.lon.iloc[-1])
dur_min   = (M.hora.iloc[-1] - M.hora.iloc[0]).total_seconds() / 60
ruta = {'inicio': [M.lat.iloc[0], M.lon.iloc[0]], 'fin': [M.lat.iloc[-1], M.lon.iloc[-1]],
        'longitud_km': ruta_km, 'cierre_m': cierre_m, 'duracion_min': dur_min,
        'vel_media_kmh': ruta_km / (dur_min/60) if dur_min > 0 else None,
        'hora_inicio': str(M.hora.iloc[0]), 'hora_fin': str(M.hora.iloc[-1]),
        'alt_min': M.alt.min(), 'alt_max': M.alt.max(),
        'bbox': [M.lat.min(), M.lon.min(), M.lat.max(), M.lon.max()]}
calidad['ruta'] = ruta
print(f"Ruta: {len(M)} puntos, {ruta_km:.1f} km, {dur_min:.0f} min ({ruta['vel_media_kmh']:.0f} km/h medios). "
      f"Inicio->fin separados {cierre_m:.0f} m (circuito {'casi cerrado' if cierre_m < 1000 else 'abierto'}).")

fig, ax = plt.subplots(figsize=(6.5, 6.5))
ax.plot(M.lon, M.lat, '-', color='0.6', lw=1, zorder=1)
sc = ax.scatter(M.lon, M.lat, c=M.orden, cmap='viridis', s=28, zorder=2)
ax.scatter(*M.loc[gps_malo, ['lon', 'lat']].values.T, marker='x', c='r', s=60, label='posicion imputada', zorder=3)
ax.annotate('Inicio (001)', (M.lon.iloc[0], M.lat.iloc[0]), xytext=(8, 8), textcoords='offset points', weight='bold')
ax.annotate('Fin (061)',    (M.lon.iloc[-1], M.lat.iloc[-1]), xytext=(8, -14), textcoords='offset points', weight='bold')
plt.colorbar(sc, label='n.o de medicion'); ax.set_aspect(1/np.cos(np.radians(M.lat.mean())))
ax.set_xlabel('Longitud'); ax.set_ylabel('Latitud'); ax.set_title('Ruta de la estacion movil'); ax.legend(); ax.grid(alpha=.3)
plt.savefig(f'{FIGS}/ruta.png', dpi=140, bbox_inches='tight'); plt.close()

# ── 8. Temperatura vs calidad ────────────────────────────────────────────
Q = pd.DataFrame({
  'piso_ruido_dB': np.percentile(S_clean, 10, axis=1),
  'potencia_media_dB': 10*np.log10((10**(S_clean/10)).mean(axis=1)),
  'desv_espectro_dB': S_clean.std(axis=1),
})
filas_t = []
for c in Q:
    r_p, p_p = stats.pearsonr(M.temp, Q[c]); r_s, p_s = stats.spearmanr(M.temp, Q[c])
    res = lambda y: y - np.polyval(np.polyfit(M.orden, y, 1), M.orden)
    r_par, p_par = stats.pearsonr(res(M.temp), res(Q[c]))
    filas_t.append((c, r_p, p_p, r_s, p_s, r_par, p_par))
corr_t = pd.DataFrame(filas_t, columns=['indicador', 'Pearson r', 'p', 'Spearman rho', 'p (S)', 'r parcial (ctrl. tiempo)', 'p (parcial)']).round(3)
print(corr_t.to_string(index=False))
r_t_orden = stats.pearsonr(M.temp, M.orden)[0]
print(f'Temperatura: {M.temp.min():.1f}-{M.temp.max():.1f} C (media {M.temp.mean():.1f}); correlacion temperatura-tiempo r = {r_t_orden:.2f}')

sig = corr_t[corr_t['p (parcial)'] < 0.05]
calidad['temperatura'] = {'rango': [M.temp.min(), M.temp.max()], 'r_tiempo': r_t_orden,
                          'tabla': corr_t.to_dict('records'), 'incidencia_significativa': bool(len(sig))}

fig, ax = plt.subplots(1, 3, figsize=(15, 4))
ax[0].plot(M.orden, M.temp, 'o-', ms=3); ax[0].set_title('Temperatura del sensor vs. medicion'); ax[0].set_xlabel('n.o medicion'); ax[0].set_ylabel('C')
ax[1].scatter(M.temp, Q.piso_ruido_dB, c=M.orden, s=20); ax[1].set_title('Piso de ruido vs. temperatura'); ax[1].set_xlabel('C'); ax[1].set_ylabel('P10 (dB)')
ax[2].scatter(M.temp, Q.potencia_media_dB, c=M.orden, s=20); ax[2].set_title('Potencia media vs. temperatura'); ax[2].set_xlabel('C'); ax[2].set_ylabel('dB')
for a in ax: a.grid(alpha=.3)
plt.savefig(f'{FIGS}/temperatura.png', dpi=140, bbox_inches='tight'); plt.close()

# ── 9. Cascada crudo vs final ───────────────────────────────────────────
fig, ax = plt.subplots(1, 2, figsize=(14, 4.5), sharey=True)
for a, S, t in zip(ax, [S_raw, S_final], ['Crudo', 'Limpio' + (' + piso' if APLICAR_PISO else '')]):
    im = a.imshow(S, aspect='auto', extent=[FREQ[0], FREQ[-1], len(S), 1], cmap='magma', vmin=-100, vmax=-20)
    a.set_title(f'Espectros - {t}'); a.set_xlabel('MHz')
    for x in (845, 850, 855): a.axvline(x, color='w', lw=.6, ls='--')
ax[0].set_ylabel('n.o medicion'); plt.colorbar(im, ax=ax, label='dBm')
plt.savefig(f'{FIGS}/cascada.png', dpi=140, bbox_inches='tight'); plt.close()

# ── 10. LOAD ─────────────────────────────────────────────────────────────
cols = ['orden', 'archivo', 'hora', 'temp', 'lon', 'lat', 'alt', 'hdop', 'gps_imputado', 'saturacion', 'picos_corregidos', 'dist_prev_m']
M[cols].to_csv(f'{OUT}/medidas_limpias.csv', index=False)
np.savez_compressed(f'{OUT}/espectros.npz', S_raw=S_raw, S_clean=S_clean, S_final=S_final, freq=FREQ)
with open(f'{OUT}/calidad.json', 'w') as f:
    json.dump(calidad, f, indent=2, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
print('Guardado en', OUT, '->', os.listdir(OUT))
print('OK - ETL COMPLETADO')
