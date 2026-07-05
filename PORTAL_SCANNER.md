# 🔍 Portal Scanner — Funcionalidad Nueva

Sistema de descubrimiento automatizado de ofertas laborales en múltiples plataformas ATS.

## Conceptos: 4 Niveles

El scanner implementa una estrategia de 4 niveles de búsqueda, inspirada en Career-Ops:

### **Level 0: Local Parser** (Gratis en tokens)
- Scripts personalizados por empresa para HTML estable
- Ideal para páginas sin JavaScript
- Output: JSON de ofertas

### **Level 1: Playwright** (Primary)
- Navegación directa a `careers_url` con navegador
- Detecta SPAs, JavaScript dinámico
- 100% confiable para nuevas ofertas
- Requiere Playwright + browser

### **Level 2: APIs Públicas** (Fast)
- Conexión directa a APIs de ATS
- Soportados:
  - **Greenhouse**: `/v1/boards/{company}/jobs`
  - **Ashby**: GraphQL `ApiJobBoardWithTeams`
  - **Lever**: `/v0/postings/{company}`
  - **Workday**: `/wday/cxs/{company}/{site}/jobs`
  - **BambooHR**: Career list + detail endpoints
  - **Teamtailor**: RSS feeds
  - Y más...

### **Level 3: WebSearch** (Discovery)
- Búsquedas con site filters
- Descubrir nuevas empresas
- Verifica liveness (URLs expiradas)

## Archivos Nuevos

```
├── portals.yml                # Configuración de empresas y queries
├── providers.py               # Módulos de APIs (Greenhouse, Ashby, Lever, etc)
├── scan_core.py              # Lógica central: filtrado, dedup, history
├── scan_portals.py           # Orquestador de 4 niveles
└── data/
    └── scan_history.tsv      # Historial de todas las búsquedas (auto-creado)
```

## Configuración: `portals.yml`

### Estructura

```yaml
tracked_companies:
  - name: "Anthropic"
    careers_url: "https://www.anthropic.com/careers"
    api: "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"
    api_provider: "greenhouse"
    enabled: true

  - name: "OpenAI"
    careers_url: "https://openai.com/careers"
    api_provider: "ashby"
    enabled: true

search_queries:
  - query: "site:jobs.ashbyhq.com (AI Engineer OR Backend) Spain"
    enabled: true

title_filter:
  positive: ["AI", "Backend", "Python", "Engineer"]
  negative: ["Sales", "Marketing"]
  seniority_boost: ["Senior", "Staff"]

location_filter:
  allow: ["Spain", "Remote", "EU"]
  block: ["China", "Russia"]
```

### Agregar Nuevas Empresas

1. Identifica su ATS o careers URL
2. Encuentra el API endpoint (si existe)
3. Agrega a `tracked_companies`:

```yaml
- name: "Mi Empresa"
  careers_url: "https://miempresa.com/jobs"
  api_provider: "ashby"  # o "greenhouse", "lever", etc
  enabled: true
```

## Uso

### Tab 5: Portal Scanner en Streamlit

1. Abre el app: `streamlit run app.py`
2. Ve a Tab 5 "🔍 Portal Scanner"
3. Haz click en "▶ Iniciar escaneo de portales"
4. Espera 1-2 minutos
5. Verás las nuevas ofertas encontradas
6. Click en "📥 Importar a 'Preparar lotes'" para procesarlas con IA

### CLI (Programático)

```python
import asyncio
import scan_portals

result = asyncio.run(scan_portals.run_full_scan())
print(f"Nuevas ofertas: {len(result['new_jobs'])}")
```

## Deduplicación

El scanner automáticamente deduplica contra:
- `data/scan_history.tsv` — URLs ya escaneadas
- `job_tracker.db` — Ofertas ya evaluadas
- `applications.md` — Ofertas ya aplicadas

## Historial: `data/scan_history.tsv`

```tsv
url                          | first_seen        | portal    | title           | company   | status
https://...                  | 2026-07-03T...    | Ashby     | Senior Engineer | Anthropic | added
https://...                  | 2026-07-02T...    | API       | AI PM           | OpenAI    | skipped_dup
```

Columnas:
- `url` — URL de la oferta
- `first_seen` — Timestamp del primer escaneo
- `portal` — Fuente (API, Playwright, WebSearch, Parser)
- `title` — Título del puesto
- `company` — Empresa
- `status` — `added`, `skipped_dup`, `skipped_expired`, `skipped_title`
- `location` — Ubicación

## Filtrado

### Title Filter

```yaml
title_filter:
  positive: ["Backend", "Python"]     # Al menos 1 debe aparecer
  negative: ["Sales"]                 # Ninguno debe aparecer
  seniority_boost: ["Senior"]         # Bonus (opcional)
```

### Location Filter

```yaml
location_filter:
  allow: ["Spain", "Remote"]          # Al menos 1 debe coincidir
  block: ["China"]                    # Nada de esto
```

## Extensibilidad

### Agregar un Nuevo ATS Provider

1. Crea una clase en `providers.py`:

```python
class MiATSProvider(ATSProvider):
    async def fetch_jobs(self) -> List[Dict]:
        # Implementa lógica
        return [
            {
                "title": "...",
                "url": "...",
                "location": "...",
                "job_id": "..."
            }
        ]
```

2. Agrega a la factory en `get_provider()`:

```python
elif api_provider == "mi_ats":
    return MiATSProvider(company, api_url)
```

3. Usa en `portals.yml`:

```yaml
- name: "Empresa"
  api_provider: "mi_ats"
  api: "https://..."
```

## Limitaciones Actuales

- **Level 0 (Local Parser)**: No implementado (requiere scripts custom)
- **Level 1 (Playwright)**: No implementado en scanner automático (usa Level 2 APIs como fallback)
- **Level 3 (WebSearch)**: No implementado (requiere WebSearch API)
- **Full JD fetching**: Solo obtiene metadata (título, URL, ubicación)

## Próximos Pasos

1. ✅ Level 2 APIs (implementado)
2. ⏳ Level 1 Playwright en Tab 5
3. ⏳ Level 3 WebSearch Discovery
4. ⏳ Full JD fetching (HTML scraping)
5. ⏳ Local parser templates por empresa

## Performance

- **Greenhouse API**: ~50ms por empresa
- **Ashby GraphQL**: ~100ms por empresa
- **Lever API**: ~50ms por empresa
- **Total**: Todas las empresas en paralelo: ~1-2 minutos

## Troubleshooting

### "ModuleNotFoundError: No module named 'yaml'"
```bash
pip install pyyaml
```

### "No companies with API endpoints configured"
Verifica que en `portals.yml` tengas empresas con `api_provider` definido.

### "Error fetching jobs for X: [error details]"
- Verifica la URL de la API
- Comprueba que el provider sea el correcto
- Consulta la API manualmente: `curl https://...`

## Referencias

- [Career-Ops Scan Mode](https://github.com/santifer/career-ops/blob/main/modes/scan.md)
- [Supported Job Boards](https://github.com/santifer/career-ops/blob/main/docs/SUPPORTED_JOB_BOARDS.md)
- [Career-Ops GitHub](https://github.com/santifer/career-ops)
