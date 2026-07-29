from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from joborchestrator.evals.llm_judge import JUDGE_ISSUE_CODES
from joborchestrator.ranking.schemas import VALID_DECISIONS


@dataclass(slots=True)
class SemanticEvalResult:
    passed: bool
    score: int
    issues: list[str]
    metrics: dict[str, Any]


def build_auto_eval_case(
    job: Any,
    profile_payload: dict[str, Any] | None = None,
    ranking: Any | None = None,
) -> dict[str, Any]:
    job_payload = _to_dict(job)
    profile_payload = profile_payload or {}
    ranking_payload = _to_dict(ranking) if ranking is not None else {}
    base_cv_text = str(profile_payload.get("base_cv_text") or "").strip()
    required_terms = _required_supported_terms(job_payload, profile_payload, ranking_payload)
    return {
        "id": f"auto-job-{job_payload.get('id') or job_payload.get('job_id') or 'unknown'}",
        "job": {
            "title": job_payload.get("title") or "",
            "company": job_payload.get("company") or "",
            "description_text": job_payload.get("description_text") or job_payload.get("description") or "",
        },
        "candidate": {
            "base_cv_text": base_cv_text,
            "required_experience_terms": _extract_likely_employers(base_cv_text),
            "forbidden_claims": _derive_profile_forbidden_claims(profile_payload, job_payload),
            "supported_claim_source_text": _profile_claim_source_text(profile_payload),
            "real_experience_years": profile_payload.get("real_experience_years"),
        },
        "materials_expectations": {
            "required_terms": required_terms,
            "specificity_terms": [
                term
                for term in [job_payload.get("company"), job_payload.get("title")]
                if str(term or "").strip()
            ],
            "max_recruiter_message_chars": 320,
            "ranking_decision": ranking_payload.get("decision") or "",
            "risk_terms": _ranking_risk_terms(ranking_payload),
        },
        "ats_cv_expectations": {
            "required_keywords": required_terms,
            "required_sections": ["summary", "skills", "experience", "education"],
        },
        "ranking_expectations": {"required_evidence_terms": required_terms[:3]},
    }


def evaluate_application_materials(case: dict[str, Any], materials: Any) -> SemanticEvalResult:
    payload = _to_dict(materials)
    expectations = case.get("materials_expectations") or {}
    candidate = case.get("candidate") or {}
    job = case.get("job") or {}
    issues: list[str] = []
    metrics: dict[str, Any] = {}

    required_fields = expectations.get("required_fields") or [
        "recruiter_message",
        "cover_letter",
        "ats_cv_text",
        "autofill_notes",
    ]
    missing_fields = [field for field in required_fields if not str(payload.get(field) or "").strip()]
    if missing_fields:
        issues.append(f"missing_required_fields:{','.join(missing_fields)}")

    cover_letter = str(payload.get("cover_letter") or "").strip()
    min_cover_letter_chars = int(expectations.get("min_cover_letter_chars") or 120)
    metrics["cover_letter_chars"] = len(cover_letter)
    if "cover_letter" in required_fields and cover_letter and len(cover_letter) < min_cover_letter_chars:
        issues.append(f"cover_letter_too_short:{len(cover_letter)}<{min_cover_letter_chars}")

    full_text = _joined_text(payload)
    normalized_full_text = _normalize(full_text)

    unsupported_claims = _unsupported_claims_in_text(full_text, candidate, expectations)
    if unsupported_claims:
        issues.append(f"unsupported_claims:{','.join(unsupported_claims)}")
    metrics["unsupported_claims"] = unsupported_claims

    required_terms = expectations.get("required_terms") or []
    missing_required_terms = [term for term in required_terms if not _contains_phrase(normalized_full_text, term)]
    if missing_required_terms:
        issues.append(f"missing_required_terms:{','.join(missing_required_terms)}")
    metrics["missing_required_terms"] = missing_required_terms

    base_experience_terms = candidate.get("required_experience_terms") or []
    ats_cv_text = str(payload.get("ats_cv_text") or "")
    normalized_ats_cv = _normalize(ats_cv_text)
    omitted_experiences = [term for term in base_experience_terms if not _contains_phrase(normalized_ats_cv, term)]
    if omitted_experiences:
        issues.append(f"omitted_base_experience:{','.join(omitted_experiences)}")
    metrics["omitted_base_experience"] = omitted_experiences

    internal_cv_markers = _internal_cv_markers(ats_cv_text)
    if internal_cv_markers:
        issues.append(f"ats_cv_contains_internal_notes:{','.join(internal_cv_markers)}")
    metrics["ats_cv_internal_markers"] = internal_cv_markers

    recruiter_message = str(payload.get("recruiter_message") or "").strip()
    max_recruiter_chars = int(expectations.get("max_recruiter_message_chars") or 320)
    metrics["recruiter_message_chars"] = len(recruiter_message)
    if len(recruiter_message) > max_recruiter_chars:
        issues.append(f"recruiter_message_too_long:{len(recruiter_message)}>{max_recruiter_chars}")

    cover_letter_markers = _cover_letter_markers(recruiter_message)
    if cover_letter_markers:
        issues.append(f"recruiter_message_cover_letter_style:{','.join(cover_letter_markers)}")
    metrics["recruiter_message_cover_letter_markers"] = cover_letter_markers

    specificity_terms = expectations.get("specificity_terms") or [job.get("company"), job.get("title")]
    matched_specificity = [term for term in specificity_terms if term and _contains_phrase(normalized_full_text, str(term))]
    if specificity_terms and not matched_specificity:
        issues.append("missing_job_specificity")
    metrics["matched_specificity_terms"] = matched_specificity

    internal_material_markers = _internal_material_markers(full_text)
    if internal_material_markers:
        issues.append(f"application_materials_contains_internal_notes:{','.join(internal_material_markers)}")
    metrics["application_material_internal_markers"] = internal_material_markers

    overconfident_markers = _overconfident_material_markers(full_text, expectations)
    if overconfident_markers:
        issues.append(f"application_materials_overconfident_for_risky_ranking:{','.join(overconfident_markers)}")
    metrics["application_material_overconfident_markers"] = overconfident_markers

    return _result(issues, metrics)


def evaluate_ranking_result(case: dict[str, Any], ranking: Any) -> SemanticEvalResult:
    payload = _to_dict(ranking)
    expectations = case.get("ranking_expectations") or {}
    issues: list[str] = []
    metrics: dict[str, Any] = {}

    decision = str(payload.get("decision") or "").strip()
    final_score = _int_or_none(payload.get("final_score"))
    metrics["decision"] = decision
    metrics["final_score"] = final_score

    if decision not in VALID_DECISIONS:
        issues.append(f"invalid_decision:{decision}")

    allowed_decisions = expectations.get("allowed_decisions") or []
    if allowed_decisions and decision not in allowed_decisions:
        issues.append(f"decision_outside_expected_band:{decision}")

    min_score = expectations.get("min_score")
    max_score = expectations.get("max_score")
    if min_score is not None and (final_score is None or final_score < int(min_score)):
        issues.append(f"score_below_expected:{final_score}<{min_score}")
    if max_score is not None and (final_score is None or final_score > int(max_score)):
        issues.append(f"score_above_expected:{final_score}>{max_score}")

    evidence_text = _ranking_evidence_text(payload)
    normalized_evidence = _normalize(evidence_text)
    required_evidence_terms = expectations.get("required_evidence_terms") or []
    keyword_synonyms = expectations.get("keyword_synonyms") or {}
    missing_evidence_terms = [
        term
        for term in required_evidence_terms
        if not _contains_keyword_or_synonym(normalized_evidence, term, keyword_synonyms)
    ]
    if missing_evidence_terms:
        issues.append(f"missing_evidence_terms:{','.join(missing_evidence_terms)}")
    metrics["missing_evidence_terms"] = missing_evidence_terms

    dealbreaker_terms = expectations.get("dealbreaker_terms") or []
    mentioned_dealbreakers = [
        term
        for term in dealbreaker_terms
        if _contains_keyword_or_synonym(normalized_evidence, term, keyword_synonyms)
    ]
    if dealbreaker_terms and decision == "APPLY_NOW":
        issues.append("apply_now_with_expected_dealbreaker")
    if dealbreaker_terms and not mentioned_dealbreakers:
        issues.append(f"missing_dealbreaker_evidence:{','.join(dealbreaker_terms)}")
    metrics["mentioned_dealbreakers"] = mentioned_dealbreakers

    avoid_overclaiming = payload.get("cv_keywords_to_avoid_overclaiming") or []
    candidate = case.get("candidate") or {}
    forbidden_claims = _unsupported_claims_in_text(
        " ".join(map(str, payload.get("cv_keywords_to_emphasize") or [])),
        candidate,
        expectations,
    )
    unsafe_emphasis = [
        term
        for term in forbidden_claims
        if _contains_phrase(_normalize(" ".join(map(str, payload.get("cv_keywords_to_emphasize") or []))), term)
        and not _contains_phrase(_normalize(" ".join(map(str, avoid_overclaiming))), term)
    ]
    if unsafe_emphasis:
        issues.append(f"unsafe_cv_keyword_emphasis:{','.join(unsafe_emphasis)}")
    metrics["unsafe_cv_keyword_emphasis"] = unsafe_emphasis

    return _result(issues, metrics)


def evaluate_ats_cv_result(case: dict[str, Any], ats_cv_output: Any) -> SemanticEvalResult:
    payload = {"ats_cv_text": ats_cv_output} if isinstance(ats_cv_output, str) else _to_dict(ats_cv_output)
    expectations = case.get("ats_cv_expectations") or case.get("materials_expectations") or {}
    candidate = case.get("candidate") or {}
    issues: list[str] = []
    metrics: dict[str, Any] = {}

    ats_cv_text = str(payload.get("ats_cv_text") or "")
    normalized_ats_cv = _normalize(ats_cv_text)
    if not ats_cv_text.strip():
        issues.append("missing_required_fields:ats_cv_text")

    unsupported_claims = _unsupported_claims_in_text(ats_cv_text, candidate, expectations)
    if unsupported_claims:
        issues.append(f"unsupported_claims:{','.join(unsupported_claims)}")
    metrics["unsupported_claims"] = unsupported_claims

    required_keywords = expectations.get("required_keywords") or expectations.get("required_terms") or []
    keyword_synonyms = expectations.get("keyword_synonyms") or {}
    missing_keywords = [
        term for term in required_keywords if not _contains_keyword_or_synonym(normalized_ats_cv, term, keyword_synonyms)
    ]
    if missing_keywords:
        issues.append(f"missing_required_keywords:{','.join(missing_keywords)}")
    metrics["missing_required_keywords"] = missing_keywords

    required_sections = expectations.get("required_sections") or ["summary", "skills", "experience", "education"]
    missing_sections = [section for section in required_sections if not _has_ats_section(ats_cv_text, section)]
    if missing_sections:
        issues.append(f"ats_cv_missing_parseable_sections:{','.join(missing_sections)}")
    metrics["missing_parseable_sections"] = missing_sections

    min_chars = int(expectations.get("min_chars") or 500)
    parseable_lines = [line for line in ats_cv_text.splitlines() if line.strip()]
    metrics["ats_cv_chars"] = len(ats_cv_text)
    metrics["ats_cv_parseable_lines"] = len(parseable_lines)
    if ats_cv_text.strip() and len(ats_cv_text) < min_chars:
        issues.append(f"ats_cv_too_short:{len(ats_cv_text)}<{min_chars}")

    base_experience_terms = candidate.get("required_experience_terms") or []
    omitted_experiences = [term for term in base_experience_terms if not _contains_phrase(normalized_ats_cv, term)]
    if omitted_experiences:
        issues.append(f"omitted_base_experience:{','.join(omitted_experiences)}")
    metrics["omitted_base_experience"] = omitted_experiences

    internal_cv_markers = _internal_cv_markers(ats_cv_text)
    if internal_cv_markers:
        issues.append(f"ats_cv_contains_internal_notes:{','.join(internal_cv_markers)}")
    metrics["ats_cv_internal_markers"] = internal_cv_markers

    return _result(issues, metrics)


def build_llm_judge_payload(case: dict[str, Any], candidate_output: Any, artifact_type: str) -> dict[str, Any]:
    if artifact_type not in {"application_materials", "ranking", "ats_cv"}:
        raise ValueError("artifact_type must be one of: application_materials, ranking, ats_cv")
    pass_fail_rules = [
        "Fail if the output invents employers, degrees, certifications, tools, years, or projects not supported by the candidate source.",
        "Fail if a ranking recommends APPLY_NOW despite an explicit central requirement mismatch or dealbreaker.",
        "Fail if evidence does not cite the strongest match and the most important gap for the candidate.",
        "Fail if application materials are generic and do not reference the target company, role, or truthful candidate strengths.",
    ]
    if artifact_type == "ats_cv":
        pass_fail_rules = [
            "Fail if the ATS CV invents experience, employers, degrees, certifications, tools, years, or projects not supported by the candidate source.",
            "Fail if the ATS CV omits required job keywords the candidate can truthfully support.",
            "Fail if the ATS CV contains internal notes, targeting commentary, or prompt artifacts instead of final CV text.",
            "Fail if the ATS CV is not parseable with standard sections such as summary, skills, experience, and education.",
            "Fail if the ATS CV drops real candidate experience entries from the source CV.",
        ]
    return {
        "artifact_type": artifact_type,
        "case_id": case.get("id"),
        "rubric_version": "semantic-eval-v1",
        "rubric": {
            "pass_fail_rules": pass_fail_rules,
            "issue_codes": JUDGE_ISSUE_CODES,
            "scores": {
                "faithfulness": "0-100 based on whether claims are supported by candidate data.",
                "job_specificity": "0-100 based on target role/company/requirement specificity.",
                "decision_quality": "0-100 based on ranking decision, score band, and evidence.",
                "actionability": "0-100 based on readiness to apply or clear next steps.",
            },
        },
        "source_case": {
            "job": case.get("job"),
            "candidate": case.get("candidate"),
            "expectations": {
                "materials": case.get("materials_expectations"),
                "ranking": case.get("ranking_expectations"),
                "ats_cv": case.get("ats_cv_expectations"),
            },
        },
        "candidate_output": _to_dict(candidate_output),
        "expected_response_schema": {
            "passed": "boolean",
            "score": "integer 0-100",
            "issue_codes": ["enum string from rubric.issue_codes"],
            "issues": ["string"],
            "rationale": "short evidence-backed explanation",
        },
    }


def _supported_profile_terms(profile_payload: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for skill in profile_payload.get("skills") or []:
        if isinstance(skill, dict) and str(skill.get("name") or "").strip():
            terms.append(str(skill["name"]).strip())
    for key in ["strong_skills", "medium_skills", "weak_skills"]:
        terms.extend(str(term).strip() for term in profile_payload.get(key) or [] if str(term or "").strip())
    base_cv = str(profile_payload.get("base_cv_text") or "")
    fallback_terms = [
        "Python",
        "FastAPI",
        "Django",
        "Flask",
        "PostgreSQL",
        "SQL",
        "MongoDB",
        "Redis",
        "Docker",
        "AWS",
        "React",
        "TypeScript",
        "JavaScript",
        "API",
        "automation",
        "stakeholder",
    ]
    for term in fallback_terms:
        if _contains_phrase(_normalize(base_cv), term):
            terms.append(term)
    return _unique_terms(terms)


def _required_supported_terms(
    job_payload: dict[str, Any],
    profile_payload: dict[str, Any],
    ranking_payload: dict[str, Any],
) -> list[str]:
    supported_terms = _supported_profile_terms(profile_payload)
    if not supported_terms:
        return []
    full_job_text = _normalize(
        " ".join(
            str(job_payload.get(key) or "")
            for key in ["title", "company", "description_text", "description", "location"]
        )
    )
    avoid_terms = _normalized_terms(ranking_payload.get("cv_keywords_to_avoid_overclaiming"))
    emphasize_terms = _normalized_terms(ranking_payload.get("cv_keywords_to_emphasize"))
    scored = [
        (term, _required_term_score(term, job_payload, profile_payload, emphasize_terms))
        for term in supported_terms
        if _contains_phrase(full_job_text, term) and not _term_overlaps(term, avoid_terms)
    ]
    scored = [(term, score) for term, score in scored if score >= 2]
    supported_order = {_normalize(term): index for index, term in enumerate(supported_terms)}
    scored.sort(key=lambda item: (-item[1], supported_order.get(_normalize(item[0]), len(supported_order)), item[0].lower()))
    return [term for term, _score in scored[: _required_terms_limit(ranking_payload)]]


def _required_term_score(
    term: str,
    job_payload: dict[str, Any],
    profile_payload: dict[str, Any],
    emphasize_terms: list[str],
) -> int:
    title = _normalize(job_payload.get("title") or "")
    description = _normalize(job_payload.get("description_text") or job_payload.get("description") or "")
    normalized_term = _normalize(term)
    score = 0
    if _contains_phrase(title, term):
        score += 5
    score += min(len(re.findall(rf"\b{re.escape(normalized_term)}\b", description)), 3)
    if _term_in_requirement_context(term, description):
        score += 3
    if _term_overlaps(term, emphasize_terms):
        score += 2
    if _contains_phrase(_normalize(_profile_claim_source_text(profile_payload)), term):
        score += 1
    level = _profile_skill_level(term, profile_payload)
    if level == "strong":
        score += 2
    elif level == "medium":
        score += 1
    if _is_secondary_process_term(term):
        score -= 2
    return score


def _term_in_requirement_context(term: str, normalized_description: str) -> bool:
    if not normalized_description:
        return False
    markers = [
        "required",
        "requirements",
        "required skills",
        "qualifications",
        "must have",
        "imprescindible",
        "requisitos",
        "necesitamos",
        "experiencia",
        "knowledge of",
        "hands-on experience",
        "solid experience",
        "strong understanding",
    ]
    for marker in markers:
        marker_index = normalized_description.find(marker)
        while marker_index >= 0:
            window = normalized_description[marker_index : marker_index + 800]
            if _contains_phrase(window, term):
                return True
            marker_index = normalized_description.find(marker, marker_index + len(marker))
    return False


def _profile_skill_level(term: str, profile_payload: dict[str, Any]) -> str:
    normalized_term = _normalize(term)
    for skill in profile_payload.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        if _normalize(skill.get("name") or "") == normalized_term:
            return str(skill.get("level") or "").strip().lower()
    for level, key in [("strong", "strong_skills"), ("medium", "medium_skills"), ("weak", "weak_skills")]:
        if any(_normalize(skill) == normalized_term for skill in profile_payload.get(key) or []):
            return level
    return ""


def _required_terms_limit(ranking_payload: dict[str, Any]) -> int:
    decision = str(ranking_payload.get("decision") or "").strip().upper()
    score = _int_or_none(ranking_payload.get("final_score"))
    if decision in {"SKIP", "AVOID"} or (score is not None and score < 55):
        return 3
    if decision in {"MAYBE", "APPLY_WITH_TAILORED_CV"} or (score is not None and score < 80):
        return 4
    return 5


def _normalized_terms(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_terms = [value]
    elif isinstance(value, list):
        raw_terms = [str(item) for item in value]
    else:
        raw_terms = []
    return [_normalize(term) for term in raw_terms if str(term or "").strip()]


def _term_overlaps(term: str, normalized_terms: list[str]) -> bool:
    normalized_term = _normalize(term)
    return any(normalized_term == item or normalized_term in item or item in normalized_term for item in normalized_terms)


def _is_secondary_process_term(term: str) -> bool:
    return _normalize(term) in {
        "code review",
        "monitoring",
        "documentation",
        "testing",
        "debugging",
        "troubleshooting",
        "agile",
        "scrum",
        "git",
        "ci/cd",
    }


def _derive_profile_forbidden_claims(profile_payload: dict[str, Any], job_payload: dict[str, Any]) -> list[str]:
    supported_text = _normalize(_profile_claim_source_text(profile_payload))
    source_terms = _unique_terms(
        [
            *_supported_profile_terms(profile_payload),
            *re.findall(
                r"(?i)\b[A-Z][A-Za-z0-9+#.-]{2,}(?:\s+[A-Z][A-Za-z0-9+#.-]{2,}){0,3}\b",
                " ".join(str(job_payload.get(key) or "") for key in ["title", "description_text", "description"]),
            ),
        ]
    )
    claims: list[str] = []
    for term in source_terms:
        if len(term) < 3:
            continue
        claims.extend([f"{term} Certified", f"Certified {term}", f"{term} certification"])
    if any(_contains_phrase(supported_text, term) for term in ["aws", "amazon web services"]):
        claims.append("AWS Certified Solutions Architect")
    if _contains_phrase(supported_text, "kubernetes"):
        claims.append("Kubernetes Certified")
    return [claim for claim in _unique_terms(claims) if not _contains_phrase(supported_text, claim)]


def _profile_claim_source_text(profile_payload: dict[str, Any]) -> str:
    parts = [
        profile_payload.get("headline"),
        profile_payload.get("summary"),
        profile_payload.get("base_cv_text"),
        profile_payload.get("certifications"),
        profile_payload.get("education"),
        profile_payload.get("experience"),
    ]
    for skill in profile_payload.get("skills") or []:
        if isinstance(skill, dict):
            parts.extend([skill.get("name"), skill.get("evidence")])
        else:
            parts.append(skill)
    parts.extend(profile_payload.get("strong_skills") or [])
    parts.extend(profile_payload.get("medium_skills") or [])
    parts.extend(profile_payload.get("weak_skills") or [])
    return "\n".join(_string_values(parts))


def _unsupported_claims_in_text(
    text: str,
    candidate: dict[str, Any],
    expectations: dict[str, Any],
) -> list[str]:
    explicit_forbidden = candidate.get("forbidden_claims") or expectations.get("forbidden_claims") or []
    normalized_text = _normalize(text)
    unsupported = [term for term in explicit_forbidden if _contains_phrase(normalized_text, term)]

    supported_text = _normalize(_candidate_claim_source_text(candidate))
    real_experience_years = _float_or_none(candidate.get("real_experience_years"))
    for claim in _extract_sensitive_claims(text):
        if _sensitive_claim_supported(claim, supported_text, real_experience_years):
            continue
        unsupported.append(claim)
    return _unique_terms(unsupported)


def _candidate_claim_source_text(candidate: dict[str, Any]) -> str:
    return "\n".join(
        _string_values(
            [
                candidate.get("supported_claim_source_text"),
                candidate.get("base_cv_text"),
                candidate.get("candidate_profile"),
                candidate.get("profile"),
            ]
        )
    )


def _extract_sensitive_claims(text: str) -> list[str]:
    claims: list[str] = []
    known_claims = [
        "AWS Certified Solutions Architect",
        "Certified Scrum Product Owner",
        "Certified Scrum Master",
        "Professional Scrum Master",
        "Kubernetes Certified",
        "Google Cloud Professional Cloud Architect",
        "managed product P&L",
    ]
    normalized_text = _normalize(text)
    claims.extend([claim for claim in known_claims if _contains_phrase(normalized_text, claim)])
    patterns = [
        r"\b(?:[A-Za-z0-9+#.-]+\s+){0,4}Certified(?:\s+[A-Za-z0-9+#.-]+){0,4}\b",
        r"\b(?:PhD|Ph\.D\.|MBA|Master'?s degree|Bachelor'?s degree)\b",
        r"\b\d{1,2}\+?\s*(?:years|years'|anos|años)\b",
        r"\b(?:managed|led|leading)\s+(?:a\s+)?team\s+of\s+\d+\b",
    ]
    for pattern in patterns:
        claims.extend(match.group(0).strip(" .,;:") for match in re.finditer(pattern, str(text or ""), flags=re.IGNORECASE))
    return _unique_terms(claims)


def _sensitive_claim_supported(claim: str, supported_text: str, real_experience_years: float | None) -> bool:
    if _contains_phrase(supported_text, claim):
        return True
    years = re.search(r"\b(\d{1,2})\+?\s*(?:years|years'|anos|años)\b", claim, flags=re.IGNORECASE)
    if years and real_experience_years is not None:
        return int(years.group(1)) <= real_experience_years
    return False


def _extract_likely_employers(base_cv_text: str) -> list[str]:
    section = re.search(
        r"(?ims)^\s*(experience|professional experience|experiencia)\s*$([\s\S]*?)(?=^\s*(projects|skills|education|formaci[oó]n)\s*$|\Z)",
        base_cv_text,
    )
    if not section:
        return []
    employers: list[str] = []
    tech_only_terms = {
        "api",
        "apis",
        "aws",
        "django",
        "docker",
        "fastapi",
        "flask",
        "javascript",
        "mongodb",
        "nosql",
        "php",
        "postgresql",
        "python",
        "react",
        "redis",
        "sql",
        "typescript",
    }
    for line in section.group(2).splitlines():
        if line.lstrip().startswith(("-", "*")):
            continue
        stripped = line.strip(" -\t")
        if not stripped or len(stripped) > 80:
            continue
        if re.search(r"(?i)\b(developer|engineer|consultant|manager|specialist)\b", stripped):
            continue
        tokens = _match_tokens(stripped)
        if tokens and all(token in tech_only_terms for token in tokens):
            continue
        if re.search(r"[A-Z][a-z]+", stripped):
            employers.append(stripped)
    return _unique_terms(employers)[:6]


def _unique_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        normalized = _normalize(term)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(term)
    return unique


def _internal_cv_markers(text: str) -> list[str]:
    normalized = _normalize(text)
    markers = [
        "target role:",
        "ats keywords",
        "positioning angle:",
        "optimized cv",
        "optimization notes",
        "keywords to emphasize",
        "internal note",
    ]
    return [marker for marker in markers if marker in normalized]


def _ranking_risk_terms(ranking_payload: dict[str, Any]) -> list[str]:
    evidence = ranking_payload.get("evidence") if isinstance(ranking_payload.get("evidence"), dict) else {}
    terms = []
    for key in ["dealbreakers", "red_flags", "missing_requirements"]:
        terms.extend(str(item).strip() for item in evidence.get(key) or [] if str(item).strip())
    return terms


def _internal_material_markers(text: str) -> list[str]:
    normalized = _normalize(text)
    markers = [
        "safety gate",
        "highlighted in your system",
        "ranking decision",
        "ranking says",
        "dealbreaker",
        "avoid-overclaiming",
        "validation error",
    ]
    return [marker for marker in markers if marker in normalized]


def _overconfident_material_markers(text: str, expectations: dict[str, Any]) -> list[str]:
    decision = str(expectations.get("ranking_decision") or "").upper()
    risk_terms = expectations.get("risk_terms") or []
    if decision not in {"SKIP", "AVOID"} and not risk_terms:
        return []
    normalized = _normalize(text)
    markers = [
        "confident my skills",
        "i am confident",
        "immediate impact",
        "strong fit",
        "ideal fit",
        "perfect fit",
        "excited about",
        "excited to",
        "eager to",
        "eager to enhance",
        "eager to contribute",
        "highly confident",
        "excellent fit",
    ]
    return [marker for marker in markers if marker in normalized]


def _contains_keyword_or_synonym(
    normalized_text: str,
    keyword: str,
    keyword_synonyms: dict[str, Any],
) -> bool:
    if _contains_phrase(normalized_text, keyword):
        return True
    synonyms = keyword_synonyms.get(keyword) or keyword_synonyms.get(_normalize(keyword)) or []
    return any(_contains_phrase(normalized_text, synonym) for synonym in synonyms)


def _has_ats_section(text: str, section: str) -> bool:
    aliases = {
        "summary": ["summary", "professional summary", "profile", "perfil", "resumen"],
        "skills": ["skills", "technical skills", "core skills", "competencias", "habilidades"],
        "experience": ["experience", "professional experience", "work experience", "experiencia"],
        "education": ["education", "academic", "formacion", "formación", "educacion", "educación"],
    }
    expected = aliases.get(str(section).lower(), [str(section).lower()])
    for line in str(text or "").splitlines():
        stripped = _normalize(line).strip(" :-\t")
        if any(stripped == alias or stripped.startswith(f"{alias}:") for alias in expected):
            return True
    return False


def _result(issues: list[str], metrics: dict[str, Any]) -> SemanticEvalResult:
    score = max(0, 100 - (15 * len(issues)))
    return SemanticEvalResult(passed=not issues, score=score, issues=issues, metrics=metrics)


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _string_values(values: list[Any]) -> list[str]:
    strings: list[str] = []
    for value in values:
        if isinstance(value, dict):
            strings.append(" ".join(_string_values(list(value.values()))))
        elif isinstance(value, list):
            strings.append(" ".join(_string_values(value)))
        elif str(value or "").strip():
            strings.append(str(value).strip())
    return strings


def _joined_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        str(value)
        for key, value in payload.items()
        if value is not None and not str(key).startswith("_")
    )


def _ranking_evidence_text(payload: dict[str, Any]) -> str:
    fields: list[str] = []
    for key in [
        "reasoning_summary",
        "recommended_application_angle",
        "cv_keywords_to_emphasize",
        "cv_keywords_to_avoid_overclaiming",
    ]:
        fields.append(str(payload.get(key) or ""))
    evidence = payload.get("evidence") or {}
    if is_dataclass(evidence):
        evidence = asdict(evidence)
    if isinstance(evidence, dict):
        fields.extend(str(value) for value in evidence.values())
    return "\n".join(fields)


def _cover_letter_markers(text: str) -> list[str]:
    normalized = _normalize(text)
    markers = [
        "dear hiring manager",
        "dear recruiter",
        "i am writing to express",
        "i'm writing to express",
        "sincerely",
        "best regards",
    ]
    return [marker for marker in markers if marker in normalized]


def _normalize(text: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_text = _normalize(normalized_text)
    normalized_phrase = _normalize(phrase)
    if not normalized_phrase:
        return True

    text_tokens = [_canonical_match_token(token) for token in _match_tokens(normalized_text)]
    phrase_tokens = [_canonical_match_token(token) for token in _match_tokens(normalized_phrase)]
    if not phrase_tokens:
        return True
    if len(phrase_tokens) > len(text_tokens):
        return False

    window_size = len(phrase_tokens)
    return any(
        text_tokens[index : index + window_size] == phrase_tokens
        for index in range(len(text_tokens) - window_size + 1)
    )


def _match_tokens(text: Any) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", _normalize(text))


def _canonical_match_token(token: str) -> str:
    value = token.strip("'")
    if len(value) > 4 and value.endswith("ies"):
        value = f"{value[:-3]}y"
    elif len(value) > 4 and value.endswith("es"):
        value = value[:-2]
    elif len(value) > 3 and value.endswith("s") and not value.endswith("ss"):
        value = value[:-1]

    if value.startswith("document"):
        return "document"
    if value.startswith("automat"):
        return "automat"
    if value.startswith("integrat"):
        return "integrat"
    if value.startswith("operat"):
        return "operat"
    return value


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
