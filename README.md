# Job Orchestrator

Aplicacion local en Streamlit para organizar un pipeline de busqueda de empleo:
scraping, preparacion de lotes para IA, consolidacion de ranking, historial de
ofertas y escaneo de portales ATS.

## Instalacion

```bash
pip install -r requirements.txt
playwright install chromium
```

## Ejecutar la app

```bash
streamlit run app.py
```

La interfaz se abre normalmente en `http://localhost:8501`.

En Windows, si tienes la `.venv` del proyecto, usa el lanzador incluido para
evitar mezclar dependencias con otro Python:

```bat
run_app.bat
```

## Dashboard Next.js

El prototipo web generado con V0 vive en `dashboard/`. Es una app Next.js
mobile-first con datos mock para ranking, revision manual, pipeline e import.

```bash
cd dashboard
npm install
npm run dev
```

La interfaz se abre normalmente en `http://localhost:3000`.

Comandos utiles:

```bash
npm run build
npm run lint
npm run typecheck
```

## Estructura

```text
joborchestrator/
├── app.py
├── dashboard/
├── portals.yml
├── requirements.txt
├── pyproject.toml
├── joborchestrator/
│   ├── batching.py
│   ├── paths.py
│   ├── intelligence/
│   ├── scanning/
│   └── storage/
├── data/
└── tests/
```

## Modulos principales

- `app.py`: UI de Streamlit y orquestacion de pantallas.
- `joborchestrator/batching.py`: filtrado de ofertas, generacion de lotes y parseo de respuestas.
- `joborchestrator/storage/persistence.py`: persistencia SQLite local.
- `joborchestrator/scanning/`: scanner de portales, proveedores ATS y scraper de LinkedIn.
- `joborchestrator/intelligence/`: validacion de confianza, arquetipos, reposts, cartas y autofill ATS.
- `joborchestrator/paths.py`: rutas compartidas para evitar paths relativos dispersos.

## Scraper de LinkedIn

Desde la UI se lanza como subproceso. Tambien puede ejecutarse manualmente:

```bash
python -m joborchestrator.scanning.linkedin
```

El scraper sigue usando navegador local y sesion manual. No automatiza
credenciales, captchas, aplicaciones ni mensajes.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Datos locales

Estos archivos se mantienen fuera de Git por defecto:

- `.venv/`
- `__pycache__/` y caches de test
- `job_tracker.db`
- `data/scan_history.tsv`

`data/.gitkeep` se versiona solo para conservar la carpeta.
