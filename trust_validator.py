"""
Trust Validator: Detecta scams, ghost jobs, y ofertas dudosas.

Usa patrones comunes de estafas, validación de empresa, y heurísticas
para marcar ofertas potencialmente ilegítimas.
"""

import re
from typing import Dict, List, Tuple
from datetime import datetime, timedelta


# Palabras clave de scam común
SCAM_KEYWORDS = [
    "work from home guaranteed",
    "easy money",
    "no experience needed",
    "guaranteed income",
    "earn $",
    "bitcoin",
    "cryptocurrency",
    "western union",
    "money transfer",
    "wire transfer",
    "upfront payment",
    "processing fee",
    "validate your account",
    "confirm your identity",
]

# Red flags en descripción
RED_FLAGS = {
    "vague_location": r"\b(remote|work from home)\b.*\b(worldwide|any country)\b",
    "urgency": r"\b(urgent|asap|immediate|today|now)\b",
    "contact_outside_ats": r"(whatsapp|telegram|email directly|contact me at|dm me)",
    "multiple_typos": None,  # Se evalúa por conteo
    "all_caps": None,  # Se evalúa por porcentaje
}

# Compañías conocidas fake
KNOWN_SCAM_COMPANIES = [
    "amazon remote",
    "google work from home",
    "facebook remote jobs",
    "microsoft home based",
    "generic tech company",
]


def check_scam_keywords(description: str) -> Tuple[int, List[str]]:
    """
    Detecta keywords comunes de scam.
    Retorna (score, keywords_encontradas)
    """
    if not description:
        return 0, []
    
    text_lower = description.lower()
    found = []
    
    for keyword in SCAM_KEYWORDS:
        if keyword in text_lower:
            found.append(keyword)
    
    # Score: cada keyword = 1 punto (max 5)
    score = min(len(found) * 2, 5)
    return score, found


def check_red_flags(job: Dict) -> Tuple[int, List[str]]:
    """
    Evalúa heurísticas de red flag.
    Retorna (score, flags_encontradas)
    """
    flags = []
    description = job.get('descripcion', '') or job.get('description', '')
    title = job.get('titulo', '') or job.get('title', '')
    company = job.get('empresa', '') or job.get('company', '')
    
    # Flag 1: Ubicación vaga
    if re.search(RED_FLAGS["vague_location"], description, re.IGNORECASE):
        flags.append("vague_location")
    
    # Flag 2: Urgencia excesiva
    if re.search(RED_FLAGS["urgency"], description, re.IGNORECASE):
        flags.append("urgency_pressure")
    
    # Flag 3: Contacto fuera del ATS
    if re.search(RED_FLAGS["contact_outside_ats"], description, re.IGNORECASE):
        flags.append("contact_outside_ats")
    
    # Flag 4: Typos excesivos (>5 de común)
    typos = len(re.findall(r"\b\w{1,3}\b\s+\w", description))
    if typos > 10:
        flags.append("many_typos")
    
    # Flag 5: Demasiado CAPS
    if description:
        cap_ratio = len([c for c in description if c.isupper()]) / len(description)
        if cap_ratio > 0.3:
            flags.append("excessive_caps")
    
    # Flag 6: Compañía conocida fake
    for fake in KNOWN_SCAM_COMPANIES:
        if fake.lower() in company.lower():
            flags.append("known_fake_company")
            break
    
    # Flag 7: Descripción muy corta (<100 chars)
    if len(description) < 100:
        flags.append("suspiciously_short")
    
    # Score: cada flag = 1 punto
    score = len(flags)
    return score, flags


def validate_company_format(company: str) -> Tuple[bool, str]:
    """
    Valida que el nombre de empresa sea realista.
    Retorna (is_valid, reason)
    """
    if not company:
        return False, "empty_company_name"
    
    if len(company) < 2:
        return False, "too_short"
    
    if len(company) > 100:
        return False, "too_long"
    
    if re.search(r"^\d+$", company):
        return False, "only_numbers"
    
    if company.lower() in KNOWN_SCAM_COMPANIES:
        return False, "known_scam"
    
    return True, "valid"


def validate_url_format(url: str) -> Tuple[bool, str]:
    """
    Valida que la URL sea realista.
    Retorna (is_valid, reason)
    """
    if not url:
        return False, "empty_url"
    
    if not url.startswith(("http://", "https://")):
        return False, "invalid_protocol"
    
    # Detecta URLs sospechosas
    suspicious_patterns = [
        r"bit\.ly",
        r"tinyurl",
        r"short\.link",
        r"\.ml$",
        r"\.tk$",
        r"\.ga$",
    ]
    
    for pattern in suspicious_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return False, "suspicious_shortener"
    
    return True, "valid"


def check_posting_date(job: Dict) -> Tuple[int, str]:
    """
    Evalúa antigüedad del posting.
    Retorna (score, status)
    - score 0: reciente (<7 días)
    - score 1: moderado (7-30 días)
    - score 2: viejo (>30 días, potencial ghost job)
    """
    posting_date_str = job.get('fecha_publicada') or job.get('posted_date')
    
    if not posting_date_str:
        return 0, "date_unknown"
    
    try:
        posting_date = datetime.fromisoformat(posting_date_str)
        days_old = (datetime.now() - posting_date).days
        
        if days_old < 7:
            return 0, "recently_posted"
        elif days_old < 30:
            return 1, "moderately_old"
        else:
            return 2, "likely_ghost_job"
    except (ValueError, TypeError):
        return 0, "date_parse_error"


def generate_trust_score(job: Dict) -> Dict:
    """
    Genera un score de confianza completo (0-100).
    
    Retorna dict con:
    - trust_score: 0-100 (100 = muy confiable)
    - risk_level: "safe" / "warning" / "danger"
    - issues: Lista de problemas encontrados
    - recommendation: Texto con recomendación
    """
    issues = []
    score = 100
    
    # 1. Scam keywords (-20 por cada, max -50)
    scam_score, scam_keywords = check_scam_keywords(
        job.get('descripcion') or job.get('description', '')
    )
    if scam_score > 0:
        score -= min(scam_score * 10, 50)
        issues.append(f"Scam keywords detected: {', '.join(scam_keywords[:3])}")
    
    # 2. Red flags (-10 cada)
    flag_score, flags = check_red_flags(job)
    score -= flag_score * 10
    for flag in flags:
        issues.append(f"Red flag: {flag}")
    
    # 3. Company validation (-15)
    valid_company, company_reason = validate_company_format(
        job.get('empresa') or job.get('company', '')
    )
    if not valid_company:
        score -= 15
        issues.append(f"Company validation failed: {company_reason}")
    
    # 4. URL validation (-15)
    valid_url, url_reason = validate_url_format(
        job.get('url', '')
    )
    if not valid_url:
        score -= 15
        issues.append(f"URL validation failed: {url_reason}")
    
    # 5. Posting date (-10 si viejo, -5 si moderado)
    date_score, date_status = check_posting_date(job)
    if date_score == 2:
        score -= 10
        issues.append("Posting is very old (potential ghost job)")
    elif date_score == 1:
        score -= 5
        issues.append("Posting is moderately old")
    
    # Garantizar score válido
    score = max(0, min(100, score))
    
    # Determinar nivel de riesgo
    if score >= 70:
        risk_level = "safe"
        recommendation = "✅ This posting looks legitimate. Safe to apply."
    elif score >= 40:
        risk_level = "warning"
        recommendation = "⚠️ Some concerns found. Review before applying. Common issues: vague location, urgency pressure, or outdated posting."
    else:
        risk_level = "danger"
        recommendation = "🚨 High risk. Likely scam or ghost job. Do NOT apply without thorough verification."
    
    return {
        "trust_score": score,
        "risk_level": risk_level,
        "issues": issues,
        "recommendation": recommendation,
        "scam_keywords": scam_keywords,
        "red_flags": flags,
        "posting_age_days": (datetime.now() - datetime.fromisoformat(
            job.get('fecha_publicada') or job.get('posted_date') or datetime.now().isoformat()
        )).days if (job.get('fecha_publicada') or job.get('posted_date')) else None,
    }


def batch_validate_jobs(jobs: List[Dict]) -> List[Dict]:
    """
    Valida un lote de ofertas.
    Retorna lista con trust_score agregado a cada una.
    """
    validated = []
    for job in jobs:
        job_copy = job.copy()
        job_copy["trust_validation"] = generate_trust_score(job)
        validated.append(job_copy)
    return validated


def filter_safe_jobs(jobs: List[Dict], min_score: int = 50) -> Tuple[List[Dict], List[Dict]]:
    """
    Separa ofertas seguras de dudosas.
    Retorna (safe_jobs, suspicious_jobs)
    """
    validated = batch_validate_jobs(jobs)
    safe = [j for j in validated if j["trust_validation"]["trust_score"] >= min_score]
    suspicious = [j for j in validated if j["trust_validation"]["trust_score"] < min_score]
    return safe, suspicious
