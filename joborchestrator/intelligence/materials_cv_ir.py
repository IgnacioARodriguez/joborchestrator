from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from joborchestrator.intelligence.materials_cv_policy import (
    dedupe_technologies,
    required_bullets_for_role,
)
from joborchestrator.intelligence.materials_keywords import derive_keywords_used

BULLET_PREFIXES = ("-", "*", "\u2022", "\u25aa", "\u25e6", "\u2023", "\u00b7")


@dataclass(frozen=True)
class CandidateIdentity:
    name: str
    contact: str = ""


@dataclass(frozen=True)
class EvidenceFact:
    id: str
    source_text: str


@dataclass(frozen=True)
class SkillEvidence:
    id: str
    name: str
    source_text: str


@dataclass(frozen=True)
class EvidenceBullet:
    id: str
    source_text: str
    technologies: list[str] = field(default_factory=list)
    mandatory: bool = False


@dataclass(frozen=True)
class ExperienceRole:
    id: str
    title: str
    company: str
    location: str | None
    dates: str
    bullets: list[EvidenceBullet]
    canonical_technologies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EducationEntry:
    id: str
    source_text: str


@dataclass(frozen=True)
class CandidateCvIR:
    candidate: CandidateIdentity
    summary_facts: list[EvidenceFact]
    skills: list[SkillEvidence]
    roles: list[ExperienceRole]
    education: list[EducationEntry]
    base_cv_text: str
    human_review_required: bool = False
    parse_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SummaryLinePlan:
    text: str
    evidence_ids: list[str]


@dataclass(frozen=True)
class RolePlan:
    role_id: str
    selected_bullet_ids: list[str]


@dataclass(frozen=True)
class AtsCvPlan:
    summary_lines: list[SummaryLinePlan] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)
    role_plans: list[RolePlan] = field(default_factory=list)


_EXPERIENCE_HEADINGS = (
    "experience",
    "professional experience",
    "work experience",
    "employment history",
    "employment experience",
    "work history",
    "career history",
    "career journey",
    "professional background",
    "relevant experience",
    "experiencia",
    "experiencia profesional",
    "historial laboral",
    "trayectoria profesional",
)
_SUMMARY_HEADINGS = (
    "summary",
    "professional summary",
    "profile",
    "professional profile",
    "perfil",
    "perfil profesional",
    "resumen",
)
_SKILL_HEADINGS = (
    "skills",
    "technical skills",
    "core skills",
    "competencies",
    "competencias",
    "habilidades",
    "tecnologías",
    "tecnologias",
)
_EDUCATION_HEADINGS = (
    "education",
    "academic background",
    "formacion",
    "formación",
    "educacion",
    "educación",
)
_OTHER_SECTION_HEADINGS = (
    "projects",
    "project experience",
    "certifications",
    "languages",
    "idiomas",
    "awards",
    "publications",
    "volunteer experience",
    "additional information",
)
_CV_SECTION_HEADINGS = {
    *_EXPERIENCE_HEADINGS,
    *_SUMMARY_HEADINGS,
    *_SKILL_HEADINGS,
    *_EDUCATION_HEADINGS,
    *_OTHER_SECTION_HEADINGS,
}

_MONTH_NAME_PATTERN = (
    r"(?:"
    r"jan(?:uary)?|ene(?:ro)?|"
    r"feb(?:ruary|rero)?|"
    r"mar(?:ch|zo)?|"
    r"apr(?:il)?|abr(?:il)?|"
    r"may(?:o)?|"
    r"jun(?:e|io)?|"
    r"jul(?:y|io)?|"
    r"aug(?:ust)?|ago(?:sto)?|"
    r"sep(?:t(?:ember|iembre)?)?|"
    r"oct(?:ober|ubre)?|"
    r"nov(?:ember|iembre)?|"
    r"dec(?:ember)?|dic(?:iembre)?"
    r")"
)
_MONTH_NAME_YEAR_PATTERN = rf"{_MONTH_NAME_PATTERN}\.?\s+\d{{4}}"
_NUMERIC_MONTH_YEAR_PATTERN = r"(?:0?[1-9]|1[0-2])[/.-]\d{4}"
_NUMERIC_YEAR_MONTH_PATTERN = r"\d{4}[/.-](?:0?[1-9]|1[0-2])"
_NUMERIC_DAY_MONTH_YEAR_PATTERN = (
    r"(?:0?[1-9]|[12]\d|3[01])[/.-]"
    r"(?:0?[1-9]|1[0-2])[/.-]\d{4}"
)
_NUMERIC_YEAR_MONTH_DAY_PATTERN = (
    r"\d{4}[/.-](?:0?[1-9]|1[0-2])[/.-]"
    r"(?:0?[1-9]|[12]\d|3[01])"
)
_DATE_COMPONENT_PATTERN = (
    rf"(?:"
    rf"{_NUMERIC_DAY_MONTH_YEAR_PATTERN}|"
    rf"{_NUMERIC_YEAR_MONTH_DAY_PATTERN}|"
    rf"{_MONTH_NAME_YEAR_PATTERN}|"
    rf"{_NUMERIC_MONTH_YEAR_PATTERN}|"
    rf"{_NUMERIC_YEAR_MONTH_PATTERN}|"
    rf"\d{{4}}"
    rf")"
)
_OPEN_ENDED_DATE_PATTERN = r"(?:present|current|actualidad|actual|presente|ongoing)"
_DATE_RANGE_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9/.])"
    rf"{_DATE_COMPONENT_PATTERN}"
    rf"\s*[-\u2013\u2014]\s*"
    rf"(?:{_DATE_COMPONENT_PATTERN}|{_OPEN_ENDED_DATE_PATTERN})"
    rf"(?![A-Za-z0-9]|[/.]\d)",
    flags=re.IGNORECASE,
)


def parse_candidate_cv_ir(
    base_cv_text: str,
    supported_terms: list[str] | None = None,
    *,
    canonical_skills: list[str] | None = None,
) -> CandidateCvIR:
    text = str(base_cv_text or "").strip()
    supported = _dedupe_strings(supported_terms or [])
    canonical = _dedupe_strings(canonical_skills or [])
    roles = _parse_roles(text, _dedupe_strings([*supported, *canonical]))
    candidate = _parse_candidate_identity(text)
    skills = _parse_skills(
        text,
        roles,
        supported_terms=supported,
        canonical_skills=canonical,
    )
    education = _parse_education(text)
    summary_facts = _parse_summary_facts(text, roles)

    warnings: list[str] = []
    if text and not roles:
        warnings.append("experience_roles_not_parsed")
    return CandidateCvIR(
        candidate=candidate,
        summary_facts=summary_facts,
        skills=skills,
        roles=roles,
        education=education,
        base_cv_text=text,
        human_review_required=bool(text and not roles),
        parse_warnings=warnings,
    )


def validate_ats_cv_plan(cv_ir: CandidateCvIR, plan: AtsCvPlan) -> list[str]:
    evidence_ids = {fact.id for fact in cv_ir.summary_facts}
    evidence_ids.update(skill.id for skill in cv_ir.skills)
    evidence_ids.update(bullet.id for role in cv_ir.roles for bullet in role.bullets)
    role_ids = {role.id for role in cv_ir.roles}
    skill_ids = {skill.id for skill in cv_ir.skills}
    errors: list[str] = []

    unknown_skills = [skill_id for skill_id in plan.skill_ids if skill_id not in skill_ids]
    if unknown_skills:
        errors.append(f"plan references unknown skill ids: {', '.join(unknown_skills)}")

    for line in plan.summary_lines:
        if str(line.text or "").strip() and not line.evidence_ids:
            errors.append("summary line must include at least one evidence id")
            continue
        unknown = [evidence_id for evidence_id in line.evidence_ids if evidence_id not in evidence_ids]
        if unknown:
            errors.append(f"summary line references unknown evidence ids: {', '.join(unknown)}")

    seen_roles: set[str] = set()
    for role_plan in plan.role_plans:
        if role_plan.role_id in seen_roles:
            errors.append(f"duplicate role plan: {role_plan.role_id}")
            continue
        seen_roles.add(role_plan.role_id)
        if role_plan.role_id not in role_ids:
            errors.append(f"role plan references unknown role id: {role_plan.role_id}")
            continue
        role = next(role for role in cv_ir.roles if role.id == role_plan.role_id)
        bullet_ids = {bullet.id for bullet in role.bullets}
        unknown = [bullet_id for bullet_id in role_plan.selected_bullet_ids if bullet_id not in bullet_ids]
        if unknown:
            errors.append(f"role {role.id} references unknown bullet ids: {', '.join(unknown)}")
    return errors


def render_ats_cv(
    cv_ir: CandidateCvIR,
    plan: AtsCvPlan | None = None,
    *,
    supported_keywords: list[str] | None = None,
    min_bullets_per_role: int | None = None,
    max_bullets_per_role: int | None = None,
    rewritten_bullets: dict[str, str] | None = None,
) -> str:
    plan = plan or AtsCvPlan()
    plan_errors = validate_ats_cv_plan(cv_ir, plan)
    if plan_errors:
        raise ValueError("; ".join(plan_errors))

    # The planner prioritizes skills, while the source-backed ATS keyword map
    # recovers relevant skills that model variability may omit.
    selected_skill_ids = set(plan.skill_ids)
    keyword_tokens = {
        token
        for value in (supported_keywords or [])
        for token in re.findall(r"[a-z0-9+#.]+", str(value or "").casefold())
        if len(token) > 1
    }
    ranked_candidates: list[tuple[int, int, str]] = []
    for index, skill in enumerate(cv_ir.skills):
        skill_tokens = set(re.findall(r"[a-z0-9+#.]+", skill.name.casefold()))
        relevance = len(skill_tokens & keyword_tokens)
        if relevance:
            ranked_candidates.append((relevance, -index, skill.id))
    # LLM-selected skills lead; deterministic keyword relevance fills the
    # remaining slots, keeping the main block focused and stable.
    ordered_ids = [skill.id for skill in cv_ir.skills if skill.id in selected_skill_ids]
    for _, _, skill_id in sorted(ranked_candidates, reverse=True):
        if skill_id not in ordered_ids:
            ordered_ids.append(skill_id)
        if len(ordered_ids) >= 12:
            break
    selected_skill_ids = {
        skill_id for skill_id in ordered_ids[:12]
        if not _is_nontechnical_skill(
            next((skill.name for skill in cv_ir.skills if skill.id == skill_id), "")
        )
    }
    selected_skills = [
        skill.name
        for skill in cv_ir.skills
        if not selected_skill_ids or skill.id in selected_skill_ids
    ]
    if not selected_skills:
        selected_skills = [skill.name for skill in cv_ir.skills]

    summary_lines = [line.text.strip() for line in plan.summary_lines if line.text.strip()]
    if not summary_lines:
        summary_lines = [fact.source_text for fact in cv_ir.summary_facts[:3]]

    output = [cv_ir.candidate.name or "Candidate"]
    if cv_ir.candidate.contact:
        output.append(cv_ir.candidate.contact)
    output.extend(["", "Professional Summary"])
    output.extend(summary_lines or ["Source-backed professional experience detailed below."])

    output.extend(["", "Technical Skills"])
    if selected_skills:
        output.append(", ".join(selected_skills))
    else:
        output.append("Source-backed technologies are listed under Professional Experience.")

    output.extend(["", "Professional Experience"])
    role_plans = {role_plan.role_id: role_plan for role_plan in plan.role_plans}
    explicit_minimum = max(0, int(min_bullets_per_role or 0))
    for role_index, role in enumerate(cv_ir.roles):
        header_parts = [role.title, role.company]
        if role.location:
            header_parts.append(role.location)
        if role.dates:
            header_parts.append(role.dates)
        output.append(" | ".join(part for part in header_parts if part))

        selected_ids = (
            role_plans[role.id].selected_bullet_ids
            if role.id in role_plans
            else []
        )
        selected_id_set = set(selected_ids)
        bullets = [
            bullet
            for bullet in role.bullets
            if bullet.mandatory or not selected_id_set or bullet.id in selected_id_set
        ]
        required = required_bullets_for_role(
            role_index,
            len(role.bullets),
            explicit_minimum=explicit_minimum,
        )
        for bullet in role.bullets:
            if len(bullets) >= required:
                break
            if bullet not in bullets:
                bullets.append(bullet)
        bullets.sort(key=lambda bullet: _bullet_order(role, bullet))
        if max_bullets_per_role is not None:
            bullets = bullets[:max(int(max_bullets_per_role), required)]

        for bullet in bullets:
            rewritten = str((rewritten_bullets or {}).get(bullet.id) or "").strip()
            output.append(f"- {_strip_bullet_prefix(rewritten or bullet.source_text)}")
        if role.canonical_technologies:
            output.append(f"Technologies: {', '.join(role.canonical_technologies)}")

    output.extend(["", "Education"])
    if cv_ir.education:
        output.extend(entry.source_text for entry in cv_ir.education)
    else:
        output.append("Not provided in source CV.")

    return "\n".join(line for line in output if line is not None).strip()


def _parse_candidate_identity(text: str) -> CandidateIdentity:
    header_lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _normalized_heading(line) in _CV_SECTION_HEADINGS:
            break
        header_lines.append(line)

    if not header_lines:
        return CandidateIdentity(name="Candidate")

    name = next((line for line in header_lines if not _looks_like_contact_line(line)), "Candidate")
    contact_lines = [
        line
        for line in header_lines
        if line != name and _looks_like_contact_line(line)
    ]
    return CandidateIdentity(name=name, contact=" | ".join(_dedupe_strings(contact_lines)))


def _parse_summary_facts(text: str, roles: list[ExperienceRole]) -> list[EvidenceFact]:
    section = _section(
        text,
        _SUMMARY_HEADINGS,
        (*_EXPERIENCE_HEADINGS, *_SKILL_HEADINGS, *_EDUCATION_HEADINGS, *_OTHER_SECTION_HEADINGS),
    )
    fact_texts = [
        _strip_bullet_prefix(line)
        for line in section.splitlines()
        if _strip_bullet_prefix(line)
    ]
    if not fact_texts:
        fact_texts = [bullet.source_text for role in roles for bullet in role.bullets][:3]
    return [
        EvidenceFact(id=f"fact_{index + 1:02d}", source_text=fact_text)
        for index, fact_text in enumerate(fact_texts[:5])
    ]


def _parse_skills(
    text: str,
    roles: list[ExperienceRole],
    *,
    supported_terms: list[str],
    canonical_skills: list[str],
) -> list[SkillEvidence]:
    section = _section(
        text,
        _SKILL_HEADINGS,
        (*_EXPERIENCE_HEADINGS, *_EDUCATION_HEADINGS, *_SUMMARY_HEADINGS, *_OTHER_SECTION_HEADINGS),
    )
    values: list[str] = []
    for raw_line in section.splitlines():
        line = _strip_bullet_prefix(raw_line)
        if not line:
            continue
        if ":" in line:
            _, line = line.split(":", 1)
        values.extend(
            item.strip()
            for item in re.split(r"[,;|]", line)
            if item.strip()
        )

    values.extend(canonical_skills)
    values.extend(
        technology
        for role in roles
        for technology in role.canonical_technologies
    )
    values.extend(derive_keywords_used(text, supported_terms))
    deduped = _dedupe_strings(values)
    return [
        SkillEvidence(
            id=f"skill_{_slug(value)}",
            name=value,
            source_text=value,
        )
        for value in deduped
    ]


def _parse_roles(text: str, supported_terms: list[str]) -> list[ExperienceRole]:
    section = _section(
        text,
        _EXPERIENCE_HEADINGS,
        (*_EDUCATION_HEADINGS, *_SKILL_HEADINGS, *_SUMMARY_HEADINGS, *_OTHER_SECTION_HEADINGS),
    )
    if not section:
        return []

    lines = _normalize_experience_lines(section)
    header_indices = [
        index
        for index, line in enumerate(lines)
        if _looks_like_role_header_line(line)
    ]
    roles: list[ExperienceRole] = []
    for role_index, header_index in enumerate(header_indices):
        next_index = (
            header_indices[role_index + 1]
            if role_index + 1 < len(header_indices)
            else len(lines)
        )
        header = lines[header_index]
        block = lines[header_index + 1 : next_index]
        title, company, location, dates = _parse_role_header(header, block)

        bullet_lines = [
            line
            for line in block
            if line.startswith(BULLET_PREFIXES)
            and not _parse_canonical_technology_line(line)
        ]
        bullets = [
            EvidenceBullet(
                id=f"role_{role_index + 1:02d}_b{bullet_index + 1:02d}",
                source_text=_strip_bullet_prefix(line),
                technologies=derive_keywords_used(line, supported_terms),
                mandatory=bullet_index == 0,
            )
            for bullet_index, line in enumerate(bullet_lines)
        ]
        canonical = dedupe_technologies(
            technology
            for line in block
            for technology in _parse_canonical_technology_line(line)
        )
        if not canonical:
            canonical = dedupe_technologies(
                technology
                for bullet in bullets
                for technology in bullet.technologies
            )

        stable_company = company or "Unknown company"
        roles.append(
            ExperienceRole(
                id=f"role_{role_index + 1:02d}_{_slug(stable_company)}",
                title=title or "Experience",
                company=stable_company,
                location=location,
                dates=dates,
                bullets=bullets,
                canonical_technologies=canonical,
            )
        )
    return roles


def _parse_role_header(
    header: str,
    block: list[str],
) -> tuple[str, str, str | None, str]:
    match = _date_range_match(header)
    if not match:
        return header.strip(), "", None, ""

    dates = match.group(0).strip()
    prefix = header[: match.start()].strip(" -|")
    parts = [part.strip() for part in prefix.split("|") if part.strip()]
    if len(parts) >= 2:
        title = parts[0]
        company, embedded_location = _split_company_location(parts[1])
        explicit_location = " | ".join(parts[2:]) or None
        return title, company, explicit_location or embedded_location, dates

    title = prefix
    company_index = _first_company_line_index(block)
    raw_company = block[company_index].strip() if company_index is not None else ""
    company, location = _split_company_location(raw_company)
    if company_index is not None and location is None:
        for line in block[company_index + 1 : company_index + 3]:
            if line.startswith(BULLET_PREFIXES) or _parse_canonical_technology_line(line):
                break
            if _looks_like_location_line(line):
                location = line.strip()
                break
    return title, company, location, dates


def _normalize_experience_lines(section: str) -> list[str]:
    raw_lines = [line.strip() for line in str(section or "").splitlines() if line.strip()]
    normalized: list[str] = []
    for index, line in enumerate(raw_lines):
        if (
            normalized
            and normalized[-1].startswith(BULLET_PREFIXES)
            and not line.startswith(BULLET_PREFIXES)
            and not _looks_like_role_header_line(line)
            and not _parse_canonical_technology_line(line)
            and _normalized_heading(line) not in _CV_SECTION_HEADINGS
            and not _looks_like_multiline_role_prefix(raw_lines, index)
        ):
            normalized[-1] = f"{normalized[-1].rstrip()} {line.lstrip()}".strip()
            continue
        normalized.append(line)
    return normalized


def _looks_like_multiline_role_prefix(lines: list[str], index: int) -> bool:
    line = str(lines[index] or "").strip()
    if not line or line.endswith((".", ";", ":")):
        return False
    words = re.findall(r"[A-Za-zÃ€-Ã¿][A-Za-zÃ€-Ã¿'â€™-]*", line)
    named_words = sum(1 for word in words if word[:1].isupper())
    looks_named = bool(words) and named_words >= max(1, len(words) - 1)
    looks_like_role = bool(
        re.search(
            r"(?i)\b(developer|engineer|consultant|architect|manager|analyst|specialist|lead|designer)\b",
            line,
        )
    )
    if not looks_named and not looks_like_role:
        return False
    following = lines[index + 1 : index + 3]
    return len(line) <= 100 and any(_date_range_match(candidate) for candidate in following)


def _split_company_location(value: str) -> tuple[str, str | None]:
    text = str(value or "").strip()
    if not text:
        return "", None

    for separator in (" Â· ", " â€¢ "):
        if separator in text:
            company, location = text.rsplit(separator, 1)
            if company.strip() and _looks_like_location_line(location):
                return company.strip(), location.strip()

    countries = (
        "Spain|Argentina|Uruguay|Mexico|Portugal|Italy|France|Germany|"
        "United Kingdom|UK|United States|USA|Canada|Brazil|Chile|Colombia|Peru"
    )
    multiword_cities = (
        "M.laga|Malaga|Buenos Aires|Mexico City|New York|San Francisco|Los Angeles|"
        "Rio de Janeiro|Sao Paulo"
    )
    multiword = re.match(
        rf"^(?P<company>.+?)\s+(?P<location>(?:{multiword_cities}),\s*(?:{countries}))$",
        text,
        flags=re.IGNORECASE,
    )
    if multiword:
        return multiword.group("company").strip(), multiword.group("location").strip()

    single_city = re.match(
        rf"^(?P<company>.+)\s+(?P<location>[A-Z][^,]+,\s*(?:{countries}))$",
        text,
    )
    if single_city:
        return single_city.group("company").strip(), single_city.group("location").strip()
    return text, None

def _role_metadata_lines(
    block: list[str],
    company: str,
    location: str | None,
) -> set[str]:
    values = {company.strip()} if company else set()
    if location:
        values.add(location.strip())
    return values


def _parse_canonical_technology_line(line: str) -> list[str]:
    value = _strip_bullet_prefix(line)
    match = re.search(
        r"(?i)\b(?:technologies|technology|tech stack|tecnologias|tecnologías)\s*:\s*(.+)$",
        value,
    )
    if not match:
        return []
    return dedupe_technologies(
        item.strip(" .\t")
        for item in re.split(r"[,;|]", match.group(1))
        if item.strip(" .\t")
    )


def _parse_education(text: str) -> list[EducationEntry]:
    section = _section(
        text,
        _EDUCATION_HEADINGS,
        (*_SKILL_HEADINGS, *_EXPERIENCE_HEADINGS, *_SUMMARY_HEADINGS, *_OTHER_SECTION_HEADINGS),
    )
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    return [
        EducationEntry(id=f"education_{index + 1:02d}", source_text=line)
        for index, line in enumerate(lines)
    ]


def _section(
    text: str,
    headings: tuple[str, ...],
    stop_headings: tuple[str, ...],
) -> str:
    heading_pattern = "|".join(re.escape(heading) for heading in headings)
    stop_pattern = "|".join(re.escape(heading) for heading in stop_headings)
    match = re.search(
        rf"(?ims)^\s*(?:{heading_pattern})\s*:?\s*$"
        rf"([\s\S]*?)"
        rf"(?=^\s*(?:{stop_pattern})\s*:?\s*$|\Z)",
        str(text or ""),
    )
    return match.group(1) if match else ""


def _date_range_match(line: str) -> re.Match[str] | None:
    return _DATE_RANGE_PATTERN.search(str(line or ""))


def _looks_like_role_header_line(line: str) -> bool:
    value = str(line or "").strip()
    return bool(
        value
        and not value.startswith(BULLET_PREFIXES)
        and _date_range_match(value)
    )


def _first_company_line_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines[:4]):
        if line.startswith(BULLET_PREFIXES):
            continue
        if _date_range_match(line):
            continue
        if _parse_canonical_technology_line(line):
            continue
        return index
    return None


def _looks_like_location_line(line: str) -> bool:
    value = str(line or "").strip()
    normalized = value.casefold()
    if not value or value.startswith(BULLET_PREFIXES):
        return False
    if any(token in normalized for token in ("remote", "remoto", "hybrid", "onsite")):
        return True
    return "," in value and len(value) <= 80 and not value.endswith(".")


def _looks_like_contact_line(line: str) -> bool:
    value = str(line or "").strip()
    normalized = value.casefold()
    if not value:
        return False
    if "@" in value:
        return True
    if any(token in normalized for token in ("linkedin", "github", "http://", "https://", "contact")):
        return True
    if "|" in value:
        return True
    if sum(character.isdigit() for character in value) >= 7:
        return True
    if "," in value and len(value) <= 60 and not value.endswith("."):
        return True
    return False


def _normalized_heading(line: str) -> str:
    return str(line or "").strip().strip(":").casefold()


def _strip_bullet_prefix(line: str) -> str:
    value = str(line or "").strip()
    while value.startswith(BULLET_PREFIXES):
        value = value[1:].lstrip()
    return value


def _bullet_order(role: ExperienceRole, bullet: EvidenceBullet) -> int:
    try:
        return role.bullets.index(bullet)
    except ValueError:
        return len(role.bullets)


def _is_nontechnical_skill(name: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(name or "").casefold()).strip()
    return bool(
        re.search(r"\b(english|spanish|native|professional working proficiency|b2|c1|c2)\b", normalized)
        or normalized in {"cloud", "internal platforms", "stakeholder", "business", "technical skills"}
    )
def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")
    return slug or "item"
