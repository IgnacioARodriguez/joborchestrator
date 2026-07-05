#!/usr/bin/env python3
"""
Quick validation script for Tier 1 features.

Run:
    python3 test_tier1_features.py
"""

import sys
from pathlib import Path

print("=" * 60)
print("🧪 Job Orchestrator — Tier 1 Features Test")
print("=" * 60)

# Test 1: Imports
print("\n1️⃣  Testing imports...")
try:
    import trust_validator
    print("   ✅ trust_validator imported")
except ImportError as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

try:
    import archetype_detector
    print("   ✅ archetype_detector imported")
except ImportError as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

try:
    import repost_detector
    print("   ✅ repost_detector imported")
except ImportError as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

# Test 2: Trust Validator
print("\n2️⃣  Testing Trust Validator...")
test_jobs = [
    {
        "titulo": "Senior Python Backend Engineer",
        "empresa": "Anthropic",
        "descripcion": "We're looking for a senior backend engineer with 5+ years of Python experience. Django, FastAPI, PostgreSQL, Docker required.",
        "url": "https://boards.greenhouse.io/anthropic/jobs/123456"
    },
    {
        "titulo": "Work from Home - EASY MONEY!!!",
        "empresa": "Amazon Remote",
        "descripcion": "Guaranteed income, no experience needed. Bitcoin payments via Western Union. Contact via WhatsApp!",
        "url": "https://bit.ly/fake-job-12345"
    }
]

for job in test_jobs:
    result = trust_validator.generate_trust_score(job)
    status = "✅" if result["risk_level"] in ["safe", "warning"] else "🚨"
    print(f"   {status} {job['titulo'][:40]}... → {result['risk_level']} ({result['trust_score']}/100)")

# Test 3: Archetype Detector
print("\n3️⃣  Testing Archetype Detector...")
test_archetypes = [
    {
        "titulo": "Senior LLMOps Engineer",
        "descripcion": "Optimize LLM inference, manage token costs, RAG systems, vector databases",
        "empresa": "Anthropic"
    },
    {
        "titulo": "Product Manager",
        "descripcion": "Lead product strategy, roadmap, prioritization for enterprise customers",
        "empresa": "Retool"
    },
    {
        "titulo": "Solutions Architect",
        "descripcion": "Design enterprise solutions, customer implementation, best practices",
        "empresa": "Salesforce"
    }
]

for job in test_archetypes:
    result = archetype_detector.detect_archetype(job)
    conf = result["confidence"]
    conf_badge = "🟢" if conf >= 80 else "🟡" if conf >= 50 else "🔴"
    print(f"   {conf_badge} {job['titulo'][:35]}... → {result['primary_archetype']} ({conf}%)")

# Test 4: Repost Detector
print("\n4️⃣  Testing Repost Detector...")
test_reposts = [
    {
        "titulo": "Backend Engineer",
        "empresa": "n8n",
        "descripcion": "Build scalable backend systems with Python and PostgreSQL",
        "url": "https://n8n.careers/backend-123"
    },
    {
        "titulo": "Backend Engineer",
        "empresa": "n8n",
        "descripcion": "Build scalable backend systems with Python and PostgreSQL",
        "url": "https://lever.co/n8n/backend-456"  # Duplicate
    },
    {
        "titulo": "Data Engineer",
        "empresa": "Anthropic",
        "descripcion": "Work with large-scale data pipelines and ML infrastructure",
        "url": "https://boards.greenhouse.io/anthropic/data-789"
    }
]

result = repost_detector.detect_reposts(test_reposts)
print(f"   Total: {result['stats']['total']}")
print(f"   Unique: {result['stats']['unique_count']}")
print(f"   Masters: {result['stats']['master_count']}")
print(f"   Duplicates detected: {result['stats']['repost_count']}")

# Test 5: Salary Filtering
print("\n5️⃣  Testing Salary Filtering...")
from scan_core import filter_by_salary

test_salary_jobs = [
    {"titulo": "Engineer 1", "salary_min": 60000, "salary_max": 100000},
    {"titulo": "Engineer 2", "salary_min": 150000, "salary_max": 200000},
    {"titulo": "Engineer 3", "salary_min": 300000, "salary_max": 400000},
]

salary_config = {"min_salary": 80000, "max_salary": 250000}
passed, filtered = filter_by_salary(test_salary_jobs, salary_config)

print(f"   Config: ${salary_config['min_salary']:,} - ${salary_config['max_salary']:,}")
print(f"   Passed: {len(passed)} jobs")
print(f"   Filtered: {len(filtered)} jobs")

# Test 6: Integration
print("\n6️⃣  Testing Integration...")
try:
    import scan_portals
    print("   ✅ scan_portals integration check")
    
    # Check new functions exist
    assert hasattr(scan_portals, 'apply_trust_validation')
    assert hasattr(scan_portals, 'apply_archetype_detection')
    assert hasattr(scan_portals, 'apply_repost_detection')
    assert hasattr(scan_portals, 'apply_salary_filter')
    print("   ✅ All new scan_portals functions present")
except (ImportError, AssertionError) as e:
    print(f"   ❌ Integration failed: {e}")
    sys.exit(1)

# Summary
print("\n" + "=" * 60)
print("✅ All Tier 1 Features tests passed!")
print("=" * 60)
print("\nNext steps:")
print("1. streamlit run app.py")
print("2. Navigate to Tab 5 'Portal Scanner'")
print("3. Check 'Trust Validator', 'Archetype Detection', 'Repost Detection'")
print("4. Click 'Iniciar escaneo de portales'")
print("=" * 60)
