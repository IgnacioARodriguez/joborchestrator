# Job Orchestrator — Portal Scanner Integration

## Flujo Completo Ejemplo

```
┌─────────────────────────────────────────────────────────────┐
│                  JOB ORCHESTRATOR FLOW                       │
└─────────────────────────────────────────────────────────────┘

OPCIÓN A: Manual (LinkedIn scraping)
──────────────────────────────────
  1. Tab 1: Scraping
     └─ python -m joborchestrator.scanning.linkedin (navegador manual)
     └─ Genera Excel: salidas_todas_posiciones_raw/*.xlsx

  2. Tab 2: Preparar lotes
     └─ Carga Excel
     └─ Filtra + genera lotes
     └─ Copia prompts a Claude

  3. Tab 3: Consolidar
     └─ Pega respuestas IA
     └─ Consolida ranking final

OPCIÓN B: Automatizado (Portal Scanner)
────────────────────────────────────────
  1. Tab 5: Portal Scanner
     └─ Click "Iniciar escaneo"
     └─ Level 2 APIs: Greenhouse, Ashby, Lever, etc
     └─ Filtra + deduplica automáticamente
     └─ Click "Importar a Preparar lotes"

  2. Tab 2: Preparar lotes
     └─ Selecciona Excel importado
     └─ Filtra + genera lotes
     └─ Copia prompts a Claude

  3. Tab 3: Consolidar
     └─ Pega respuestas IA
     └─ Consolida ranking final

OPCIÓN C: Combinada (Recomendada)
──────────────────────────────────
  • Usa Tab 5 Scanner para descubrir nuevas empresas
  • Usa Tab 1 Scraping para LinkedIn (ofertas específicas)
  • Combina ambas en Tab 2
  • Evalúa todo en Tab 3
```

## Arquitectura de Datos

```
ENTRADA:
├─ LinkedIn Manual (Tab 1)     → Excel en salidas_todas_posiciones_raw/
├─ Portal Scanner (Tab 5)      → In-memory dataframe
└─ Upload Manual (Tab 2)       → User subido

PROCESAMIENTO:
├─ filtrar_ofertas()
│   ├─ Deduplica por ID
│   ├─ Filtra extraccion_ok
│   ├─ Filtra descripción mínima
│   └─ Agrega categoría
│
├─ generar_lotes()
│   ├─ Agrupa por categoría
│   ├─ Divide en lotes de N filas
│   └─ Genera prompts para IA
│
└─ registrar_ofertas_vistas()
    └─ Guarda en job_tracker.db

EVALUACIÓN (Externa - IA):
├─ Claude.ai / ChatGPT
└─ Devuelve tabla con scores

CONSOLIDACIÓN (Tab 3):
├─ parsear_tabla_respuesta()
├─ Merge con datos originales
├─ Ordena por SCORE_TOTAL
└─ guardar_scores() en DB

OUTPUT:
├─ Excel descargable
├─ DB con histórico
└─ scan_history.tsv (Scanner)
```

## Deduplicación Inteligente

```
Job Orchestrator gestiona 3 fuentes de dedup:

1. SCAN_HISTORY.TSV (Tab 5 Scanner)
   └─ Todas las URLs escaneadas + status

2. JOB_TRACKER.DB (Tabs 1-4)
   └─ Ofertas registradas + scores

3. SESSION_STATE (In-memory)
   └─ Duplicados dentro de la sesión actual
```

## Casos de Uso

### UC1: Descubrimiento Pasivo
```
Ejecutar scanner periódicamente (ej. 1x semana)
├─ Scanner automático Level 2 APIs
├─ Guardar nuevas ofertas en scan_history.tsv
└─ Al llegar, revisar + filtrar manualmente
```

### UC2: Búsqueda Activa + Evaluación
```
1. Scanner: Descubre 50 nuevas ofertas de Anthropic
2. Tab 2: Genera 2-3 lotes
3. Claude: Evalúa en 2-3 evaluaciones paralelas
4. Tab 3: Consolida ranking de 50 ofertas
5. Aplica a top 5
```

### UC3: Monitoreo de Competencia
```
Agregar en portals.yml todas las empresas competidoras
├─ Scanner corre cada lunes 9am
├─ Genera reporte semanal
└─ Notifica nuevas ofertas
```

## Performance

### Scanner
```
15 empresas × 4 niveles (solo Level 2)
├─ Greenhouse (5 emprs): ~50ms c/u = 250ms
├─ Ashby (4 emprs): ~100ms c/u = 400ms
├─ Lever (3 emprs): ~50ms c/u = 150ms
├─ Workday (2 emprs): ~80ms c/u = 160ms
└─ Total paralelo: ~1min
```

### Full Pipeline
```
100 ofertas → 3 lotes → IA evals → ranking
├─ Escaneo: 1 min
├─ Filtrado: <1 sec
├─ Generación lotes: 1 sec
├─ IA evals (Claude): 3-5 min (paralelo)
├─ Consolidación: 1 sec
└─ Total: ~5-10 min
```

## Configuración Recomendada

### `portals.yml` para España

```yaml
tracked_companies:
  # Nivel de Entrada / Mid (Target)
  - name: "Retool"
    api_provider: "lever"
    enabled: true
  
  - name: "n8n"
    api_provider: "lever"
    enabled: true
  
  # AI Labs (Stretch)
  - name: "Anthropic"
    api_provider: "greenhouse"
    enabled: true
  
  - name: "Mistral AI"
    api_provider: "ashby"
    enabled: true
  
  # European Tech
  - name: "Tinybird"
    api_provider: "ashby"
    enabled: true

title_filter:
  positive:
    - "Backend"
    - "Python"
    - "Engineer"
    - "Solutions"
  negative:
    - "Sales"
    - "Support"
    - "Legal"
  seniority_boost:
    - "Senior"
    - "Staff"

location_filter:
  allow:
    - "Spain"
    - "Madrid"
    - "Barcelona"
    - "Remote"
    - "EU"
  block:
    - "China"
    - "Russia"
```

## Troubleshooting

### "No companies with API endpoints configured"
```
→ Verifica portals.yml tiene:
  - Empresas con api_provider definido
  - enabled: true
```

### "Error fetching from Greenhouse: 403"
```
→ Verifica que el slug sea correcto:
  - https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
  - El slug es la parte en la URL: boards-api.greenhouse.io/openai
  - slug = "openai", NO "openai-openai" o con espacios
```

### "HTTP 429 Too Many Requests"
```
→ Las APIs tienen rate limits
→ Reduce parallelismo o aumenta delays
→ Implementar retry + exponential backoff (v2)
```

## Roadmap

### v1.0 (Actual)
- ✅ Level 2 APIs (Greenhouse, Ashby, Lever, Workday, BambooHR)
- ✅ Filtrado title + location
- ✅ Deduplicación
- ✅ UI en Streamlit

### v1.1 (Próximo)
- ⏳ Level 1 Playwright scanning
- ⏳ Full JD fetching + HTML parsing
- ⏳ Liveness check (URLs expiradas)

### v1.2
- ⏳ Level 3 WebSearch discovery
- ⏳ Level 0 Local parsers
- ⏳ Scheduler (ejecutar periódicamente)

### v2.0
- ⏳ Notification system (Slack, email)
- ⏳ Advanced filtering (salary ranges, req keywords)
- ⏳ PDF generation por oferta
- ⏳ Cover letter generation
