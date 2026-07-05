# Verificación Post-Instalación

## ✅ Checklist

Ejecuta esto para verificar que todo está correctamente instalado:

```bash
# 1. Verifica archivos nuevos existen
ls -la providers.py scan_core.py scan_portals.py portals.yml

# 2. Verifica dependencias
pip show httpx pyyaml

# 3. Verifica sintaxis Python
python3 -m py_compile providers.py scan_core.py scan_portals.py

# 4. Prueba Scanner (opcional - requiere portals.yml configurado)
python3 test_scanner.py
```

## 📋 Checklist de Archivos

```
joborchestrator/
├── ✅ app.py                    (modificado: +Tab 5)
├── ✅ jobscrapping.py           (sin cambios)
├── ✅ lotes_core.py             (arreglado: merge str/int64)
├── ✅ persistence.py            (sin cambios)
├── ✅ requirements.txt           (actualizado: +httpx, +pyyaml)
├── ✅ README.md                  (actualizado: +Tab 5 info)
│
├── 🆕 portals.yml               (nuevo - config)
├── 🆕 providers.py              (nuevo - APIs)
├── 🆕 scan_core.py              (nuevo - core logic)
├── 🆕 scan_portals.py           (nuevo - orquestador)
├── 🆕 test_scanner.py           (nuevo - test)
│
├── 🆕 PORTAL_SCANNER.md         (nuevo - docs)
├── 🆕 INTEGRATION_GUIDE.md      (nuevo - docs)
│
└── data/
    └── 🆕 .gitkeep              (nuevo - marker)
```

## 🧪 Pruebas Manuales

### Test 1: Imports
```python
python3 -c "import providers; import scan_core; import scan_portals; print('✅ Imports OK')"
```

### Test 2: Carga config
```python
python3 -c "import scan_portals; config = scan_portals.load_portals_config(); print(f'✅ Config loaded: {len(config.get(\"tracked_companies\", []))} companies')"
```

### Test 3: Streamlit
```bash
streamlit run app.py
# Abre http://localhost:8501
# Navega a Tab 5
# Verifica que el botón de "Iniciar escaneo" aparezca
```

## 📊 Estadísticas

```
Líneas de código nuevas: ~800
Archivos nuevos: 6
Dependencias nuevas: 2
Tabs nuevas: 1
APIs soportadas: 6 (Greenhouse, Ashby, Lever, Workday, BambooHR, Teamtailor)
```

## 🚀 Próximo Paso

### Configurar `portals.yml`

1. **Edita `portals.yml`** con tus empresas target:

```yaml
tracked_companies:
  - name: "Tu Empresa"
    careers_url: "https://tuempresa.com/careers"
    api_provider: "greenhouse"  # o ashby, lever, etc
    api: "https://boards-api.greenhouse.io/v1/boards/tuempresa/jobs"
    enabled: true
```

2. **Identifica el API provider**:
   - Si la URL contiene `jobs.ashbyhq.com` → `api_provider: ashby`
   - Si contiene `jobs.lever.co` → `api_provider: lever`
   - Si es Greenhouse → `api_provider: greenhouse`
   - Si es Workday → `api_provider: workday`

3. **Prueba**:
```bash
python3 test_scanner.py
```

### Usar Tab 5

1. Abre: `streamlit run app.py`
2. Navega a Tab 5: "🔍 Portal Scanner"
3. Haz click: "▶ Iniciar escaneo de portales"
4. Espera 1-2 minutos
5. Verás las nuevas ofertas encontradas
6. Click: "📥 Importar a 'Preparar lotes'"
7. Ahora usas Tab 2 normalmente

## 🐛 Si Algo Falla

### Error: "ModuleNotFoundError"
```bash
pip install -r requirements.txt
```

### Error: "No companies configured"
- Edita portals.yml y agrega empresas

### Error: "HTTP 403/401"
- Verifica que el API endpoint sea correcto
- Algunos ATS requieren API keys (implementar en v1.1)

### Error en Tab 5 (Streamlit)
- Recarga la página (F5)
- O reinicia: `streamlit run app.py`

## 📖 Documentación

- [PORTAL_SCANNER.md](./PORTAL_SCANNER.md) — Guía completa del scanner
- [INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md) — Arquitectura y flujos
- [README.md](./README.md) — Overview general

## ✅ Estás Listo

La integración está completa. Ya puedes:

1. ✅ Hacer scraping manual de LinkedIn (Tab 1)
2. ✅ Hacer scanning automático de múltiples plataformas (Tab 5)
3. ✅ Combinar ambas fuentes
4. ✅ Generar lotes automáticamente (Tab 2)
5. ✅ Evaluar con IA (Claude/ChatGPT)
6. ✅ Consolidar rankings (Tab 3)
7. ✅ Trackear aplicaciones (Tab 4)

🎉 **¡Bienvenido a Career-Ops inspired Job Orchestrator!**
