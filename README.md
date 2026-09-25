# Ocupación del espectro 840-860 MHz · occidente de Medellín

Análisis técnico de ocupación del espectro celular (840-860 MHz) a partir de mediciones de una estación móvil de monitoreo, con dashboard interactivo para visualizar los resultados.

**Curso:** Internet de las Cosas — Examen/Trabajo 3
**Autora:** Stefany Morelos ([@Stefanymorelos](https://github.com/Stefanymorelos))

## Qué hace este proyecto

A partir de 61 mediciones de espectro (1024 bins entre 840-860 MHz, más temperatura y posición GPS del sensor), el pipeline:

1. **Limpia y valida los datos** — descarta mediciones de prueba, corrige GPS no confiable por interpolación, elimina artefactos del receptor (espiga en 850.000 MHz) y ruido puntual (filtro de Hampel), y aplica la regla de normalización del piso de ruido.
2. **Calcula indicadores por canal** — potencia media de los 4 canales (A, B, C, D) usando la identidad de Parseval, determina cuáles están contaminados (> -60 dBm) y emite un dictamen técnico (Recomendado / Condicionado / No recomendado).
3. **Estima la fuente de contaminación de cada canal** (bonificación) — modelo de propagación log-distancia con respaldo de centroide ponderado cuando el modelo no explica los datos.
4. **Visualiza todo en un dashboard interactivo** — mapas de calor por canal, ruta de medición, temperatura del sensor y fuentes estimadas, sobre un servidor web (Dash).

## Resultado principal

| Canal | Banda | Ocupación | Dictamen |
| --- | --- | --- | --- |
| A | 840-845 MHz | 24.6% | Recomendado |
| B | 845-850 MHz | 32.8% | Condicionado |
| C | 850-855 MHz | 83.6% | **No recomendado** |
| D | 855-860 MHz | 29.5% | Condicionado |

El informe técnico completo está en [`docs/informe_tecnico.html`](docs/informe_tecnico.html).

## Estructura del repo

```
.
├── src/
│   ├── 01_ETL_calidad.py           # extracción, limpieza, imputación, calidad de datos
│   ├── 02_indicadores_informe.py   # potencia por canal, dictamen, fuentes, informe técnico
│   └── 03_dashboard.py             # dashboard interactivo (Dash) y export estático
├── data/
│   ├── raw/                        # dataset original del examen (no versionado, ver abajo)
│   └── salida/                     # resultados generados: CSVs, JSON, figuras
├── docs/
│   └── informe_tecnico.{md,html}   # informe técnico entregable
└── requirements.txt
```

## Cómo correrlo

1. El dataset original del examen ya está incluido en `data/raw/Examen_03_2026_20_medidas.zip`.
2. Instala dependencias:
   ```
   pip install -r requirements.txt
   ```
3. Corre el pipeline en orden:
   ```
   cd src
   python3 01_ETL_calidad.py
   python3 02_indicadores_informe.py
   ```
4. Levanta el dashboard:
   ```
   python3 03_dashboard.py --modo server --port 8050
   ```
   Ábrelo en `http://localhost:8050` (o el puerto/IP donde lo despliegues).

   Para una versión sin servidor (un solo HTML exportado):
   ```
   python3 03_dashboard.py --modo estatico
   ```

## Metodología (resumen)

- **Calidad de datos:** completitud de espectros 100%, GPS válido 96.7%. Se imputaron 2 posiciones GPS por interpolación entre mediciones vecinas.
- **Limpieza de espectros:** corrección de artefacto de conversión directa (espiga en la frecuencia central) y de espigas angostas (ruido puntual) mediante filtro de Hampel, preservando señales reales (que ocupan muchos bins contiguos).
- **Potencia por canal:** identidad de Parseval — la potencia se promedia en escala lineal (mW), nunca directamente en dB.
- **Bonificación (fuentes):** modelo de propagación log-distancia, con respaldo de centroide ponderado cuando R² < 0.5 (entorno urbano con múltiples fuentes y multitrayecto reduce la calidad del ajuste físico).

Más detalle de cada decisión técnica está documentado en el informe.

## Licencia

MIT — ver [LICENSE](LICENSE).
