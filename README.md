# Job Orchestrator — UI local

Une tu scraper (`jobscrapping.py`) y la generación/consolidación de lotes de
ranking en una sola pantalla local con Streamlit.

## Instalación (una sola vez)

```bash
pip install -r requirements.txt --break-system-packages
playwright install chromium   # si aún no lo tenías de antes
```

## Estructura de carpeta esperada

```
joborchestrator/
├── app.py
├── lotes_core.py
├── jobscrapping.py      <- tu scraper, cópialo aquí tal cual
└── requirements.txt
```

## Correrla

```bash
streamlit run app.py
```

Se abre en el navegador en `http://localhost:8501`.

## Qué hace cada pestaña

1. **Scraping** — lanza `jobscrapping.py` como subproceso y muestra el log en
   vivo. Se abre un navegador real donde harás login manual la primera vez,
   exactamente igual que corriéndolo por consola. Si preferís seguir
   corriéndolo por terminal aparte, podés saltarte esta pestaña y usar solo
   la 2 y la 3.

2. **Preparar lotes** — carga el Excel más reciente de
   `salidas_todas_posiciones_raw/` (o uno que subas a mano), filtra
   duplicados/descripciones vacías, y genera los prompts por lote agrupados
   por categoría. Cada lote se muestra en una caja de código con botón de
   copiar incorporado — pégalo en un chat nuevo de Claude.ai o ChatGPT.

3. **Consolidar ranking** — pega la tabla que te devuelve la IA para cada
   lote, la parsea a filas reales, y cuando tengas todos los lotes guardados
   arma un ranking final ordenado por `SCORE_TOTAL` descendente, con el link
   directo a cada oferta. Ahí mismo podés tildar "¿Aplicado?" y agregar notas
   antes de descargar el Excel.

4. **Historial / Aplicadas** — vista de todas las ofertas que pasaron alguna
   vez por "Preparar lotes", con scores, fechas de vista, estado de aplicado
   y notas. Podés marcar nuevas aplicaciones acá.

5. **🔍 Portal Scanner** — descubrimiento automatizado de ofertas en múltiples
   plataformas ATS (Greenhouse, Ashby, Lever, Workday, etc.). Escanea empresas
   configuradas en `portals.yml` usando 4 niveles inteligentes de búsqueda.
   Las nuevas ofertas se pueden importar directamente a "Preparar lotes".

4. **Historial / Aplicadas** — todo lo que alguna vez pasó por el sistema,
   venga de hoy o de semanas atrás. Buscá por título/empresa, marcá aplicadas,
   agregá notas.

## Persistencia y deduplicación

Todo se guarda en `job_tracker.db` (SQLite), un archivo que vive en esta misma
carpeta. Mientras no borres esa carpeta ni el archivo:

- Si volvés a scrapear en una semana y salen ofertas repetidas, la pestaña 2
  las excluye automáticamente al generar lotes (hay un checkbox por si en
  algún caso puntual querés forzar que se incluyan igual).
- Los scores de facilidad de entrada y el estado de "aplicado" quedan
  guardados para siempre, visibles en la pestaña 4.
- Si borrás `job_tracker.db`, perdés todo el histórico — hacé backup de ese
  archivo si te importa conservarlo (ej. copialo a Google Drive de vez en
  cuando).

## Qué NO hace (a propósito)

No aplica a ofertas ni envía mensajes por vos. Esa parte se mantiene manual
para no arriesgar tu cuenta de LinkedIn — ver la conversación donde se
definió esta arquitectura.
