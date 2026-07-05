# 🚀 Job Orchestrator — Tier 1 Advanced Features

**Release Date**: 2026-07-03  
**Features Added**: Trust Validator, Archetype Detector, Repost Detector, Salary Filtering

---

## Overview

Job Orchestrator ahora incluye 4 nuevas funcionalidades rescatadas de **career-ops**, focalizadas en mejorar la calidad de las ofertas descubiertas por Tab 5 (Portal Scanner).

Todas las validaciones se aplican **después del Level 2 scanning** para maximizar precisión sin perder oportunidades reales.

---

## 🛡️ Trust Validator (`trust_validator.py`)

**Objetivo**: Detectar scams, ghost jobs, y ofertas potencialmente ilegítimas.

### ¿Qué detecta?

1. **Scam Keywords** (Palabra clave lista)
   - "work from home guaranteed", "easy money", "bitcoin", "western union", etc.

2. **Red Flags** (Heurísticas)
   - ✅ Ubicación vaga + "worldwide"
   - ✅ Urgencia excesiva ("ASAP", "today")
   - ✅ Contacto fuera del ATS (WhatsApp, Telegram)
   - ✅ Excesivos typos o CAPS
   - ✅ Descripción suspiciosamente corta (<100 chars)
   - ✅ Compañía conocida fake (e.g., "amazon remote")

3. **Posting Age**
   - Ofertas muy antiguas (>30 días) = potencial ghost job

### Score & Risk Level

```
Trust Score: 0-100
- 70-100 ✅ SAFE: Legit posting, safe to apply
- 40-70  ⚠️  WARNING: Some concerns, review before applying
- 0-40   🚨 DANGER: High risk, likely scam/ghost job
```

### Uso en Tab 5

```
✅ Ofertas safe: Se procesan normalmente
⚠️ Ofertas warning: Se muestran pero con flag
🚨 Ofertas danger: Filtradas automáticamente (pero visibles en expander)
```

**Reducción esperada**: 10-15% de ofertas fake eliminadas.

---

## 🏷️ Archetype Detector (`archetype_detector.py`)

**Objetivo**: Clasificar automáticamente el tipo de rol para saber qué skills enfatizar.

### Archetypes Soportados

1. **LLMOps** - Infrastructure, token optimization, inference
2. **Agentic** - Multi-agent systems, orchestration, tool use
3. **PM** - Product management, strategy, roadmap
4. **Sales** - Account executive, revenue, pipeline
5. **Developer** - Backend/Frontend/Full-stack, systems
6. **Transformation** - Enterprise modernization, change mgmt
7. **Research** - ML research, publications, deep learning
8. **Solutions Architect** - Consulting, customer success

### Detection Logic

```
Score = (Title Match × 2) + (Keyword Match × 1)
Confidence = min(100, 50 + (primary_score - second_score) / 2)
```

### Output por Rol

Para cada archetype, sugiere:
- **Technical skills** a enfatizar (ej: "LLM infrastructure" para LLMOps)
- **Soft skills** clave
- **CV keywords** óptimos

### Ejemplo

```
JD: "Senior LLMOps Engineer at Anthropic"
→ Detected: "llmops" (confidence: 95%)
→ CV Angle: "Focus on infrastructure, optimization, and systems thinking"
→ Keywords: "LLM ops", "Model optimization", "Inference", "RAG systems"
```

**Reducción de trabajo**: Evita re-escritura de CV; usa ángulo sugerido.

---

## 🔁 Repost Detector (`repost_detector.py`)

**Objetivo**: Identificar ofertas que fueron republicadas (potencial ghost job o spam).

### Detection Method

1. **Exact Hash Match** (mismo title + company + descripción)
2. **Fuzzy Matching** (similaridad >70% en title + description)

### Status Classification

```
🆕 UNIQUE: Primera vez publicada
👑 MASTER: Republicada múltiples veces (show dates)
🔁 DUPLICATE: Copia de master (mostrar link a original)
```

### Use Cases

- **MASTER apareció 5 veces en 6 meses** → Potencial ghost job (no contratan)
- **DUPLICATE = misma oferta en LinkedIn + Ashby** → Aplica a master, ahorra trabajo
- **UNIQUE** → Fresh opportunity, likely active hiring

### Recomendaciones Automáticas

```json
{
  "status": "master",
  "repost_count": 5,
  "recommendation": "⚠️ This posting has been republished 5 times. Check dates for activity."
}
```

**Ahorro de tiempo**: Evita aplicar a lo mismo múltiples veces.

---

## 💰 Salary Filtering (`portals.yml`)

**Objetivo**: Descartar ofertas fuera de tu rango salarial.

### Configuration (en `portals.yml`)

```yaml
salary_filter:
  min_salary: 50000        # Rechaza ofertas por debajo
  max_salary: 300000       # Rechaza ofertas por encima
  currency: "USD"
```

### How It Works

1. Extrae `salary_min` / `salary_max` del JD
2. Parsea strings como "$50k-$100k"
3. Calcula midpoint y compara contra rango
4. Si fuera de rango → FILTERED OUT (pero visible)

### Edge Cases

- Sin salary info en JD → PASS (no rechaza)
- Salary en diferente currency → Ajusta si es posible
- Rango extremo en el JD → Usa lógica conservadora

**Ahorro de tiempo**: Evita revisar ofertas económicamente no-viables.

---

## 📊 Integration in Tab 5

### Before Running Scan

```
□ ✅ Trust Validator    [Enable/disable]
□ 🏷️ Archetype Detection [Enable/disable]
□ 🔁 Repost Detection    [Enable/disable]
[▶ Iniciar escaneo de portales]
```

### During Scan

1. **Level 2 APIs** scan empresas → raw jobs
2. **Salary Filter** (automatic) → rechaza fuera de rango
3. **Trust Validator** → separa safe/warning/danger
4. **Archetype Detection** → clasifica roles
5. **Repost Detection** → identifica duplicados

### Output Display

```
🛡️ Trust Validation
   ✅ Safe: 42
   ⚠️ Warning: 8
   🚨 Danger: 5 (filtered)

🏷️ Role Classification
   llmops: 15
   agentic: 12
   developer: 10
   pm: 8

🔁 Repost Detection
   🆕 Unique: 35
   👑 Master: 3
   🔁 Duplicates (filtered): 2

📋 45 ofertas después de validaciones
[Preview table with Trust, Archetype columns]
```

---

## 🔧 Configuration Examples

### Conservative (High Quality Only)

```yaml
# portals.yml
salary_filter:
  min_salary: 60000
  max_salary: 250000

# Tab 5
✅ Trust Validator: enabled (filters danger jobs)
✅ Archetype: enabled (prioritize LLMOps/Agentic)
✅ Repost: enabled (avoid ghost jobs)

Result: ~20-30% of raw jobs pass (pero high quality)
```

### Aggressive (Maximize Opportunities)

```yaml
# portals.yml
salary_filter:
  min_salary: 40000
  max_salary: 400000

# Tab 5
⚠️ Trust Validator: enabled (warning ok, danger filtered)
⚠️ Archetype: enabled (info only, no filter)
⚠️ Repost: enabled (visibility, no filter)

Result: ~60-70% of raw jobs pass (more opportunities)
```

---

## 📈 Expected Impact

### Before (Tab 5 v1)
```
1000 raw jobs from APIs
→ 150 after dedup/filters
→ 150 for evaluation
```

### After (v1 + Tier 1 Features)
```
1000 raw jobs from APIs
→ 150 after dedup/filters
→ 85 after trust/archetype/repost
   (50-60 safe, 20-25 warning, 5-10 danger filtered)
→ 80-85 for evaluation (higher quality)
+ Archetype info for CV angles
+ Repost info to avoid duplicates
```

**Quality improvement**: 40-50% fewer wasted evaluations.

---

## 🚀 File Structure

```
joborchestrator/
├── trust_validator.py         [NEW] Score/risk assessment
├── archetype_detector.py      [NEW] Role classification
├── repost_detector.py         [NEW] Duplicate detection
├── scan_core.py               [UPDATED] + filter_by_salary()
├── scan_portals.py            [UPDATED] + apply_trust/archetype/repost functions
├── app.py                     [UPDATED] Tab 5 UI improvements
├── portals.yml                [UPDATED] + salary_filter section
└── requirements.txt           [unchanged - no new deps]
```

---

## 🧪 Testing

### Test Trust Validator

```python
python3 -c "
from trust_validator import generate_trust_score
job = {
    'titulo': 'Work from home - EASY MONEY!!!',
    'empresa': 'Amazon Remote',
    'descripcion': 'Guaranteed income, no experience needed. Western Union payments.'
}
score = generate_trust_score(job)
print(f\"Trust Score: {score['trust_score']}, Risk: {score['risk_level']}\")
# Expected: Score ~20, Risk: danger
"
```

### Test Archetype Detection

```python
python3 -c "
from archetype_detector import detect_archetype
job = {
    'titulo': 'Senior LLMOps Engineer',
    'descripcion': 'Optimize LLM inference, manage token costs, RAG systems',
    'empresa': 'Anthropic'
}
result = detect_archetype(job)
print(f\"Archetype: {result['primary_archetype']}, Confidence: {result['confidence']}%\")
# Expected: llmops, ~95%
"
```

### Test Repost Detection

```python
python3 -c "
from repost_detector import detect_reposts
jobs = [
    {'titulo': 'Backend Engineer', 'empresa': 'Anthropic', 'descripcion': 'Python...'},
    {'titulo': 'Backend Engineer', 'empresa': 'Anthropic', 'descripcion': 'Python...'},
]
result = detect_reposts(jobs)
print(f\"Repost groups: {len(result['repost_groups'])}, Singles: {len(result['single_postings'])}\")
# Expected: 1 repost group with 2 jobs
"
```

---

## 🎯 Next Steps (Tier 2)

- [ ] Interview Story Bank (acumular STAR stories)
- [ ] Cover Letter Generator (investigación + generación)
- [ ] Negotiation Scripts (frameworks de negociación)
- [ ] Application Auto-fill (relleno automático de ATS)
- [ ] Deep Company Research (contexto de la empresa)

---

## 📝 Changelog

### v1.1.0 - 2026-07-03

**Added**
- `trust_validator.py` - Scam detection with 0-100 score
- `archetype_detector.py` - 8 role archetypes with skill suggestions
- `repost_detector.py` - Duplicate detection via fuzzy matching
- `scan_core.filter_by_salary()` - Salary range filtering
- `portals.yml` - `salary_filter` configuration section
- Tab 5 UI improvements with validation toggles + results display

**Changed**
- `scan_portals.py` - Added 4 new apply_*() validation functions
- `app.py` - Tab 5 now shows trust/archetype/repost metrics

**Fixed**
- None (new features, no bug fixes)

---

## 📞 Support

Issues or questions? Check:
- [PORTAL_SCANNER.md](PORTAL_SCANNER.md) - Scanner internals
- [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) - Overall architecture
- [VERIFICATION.md](VERIFICATION.md) - Setup checklist
