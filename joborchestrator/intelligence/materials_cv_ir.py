from __future__ import annotations

import re
from dataclasses import dataclass, field

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


def parse_candidate_cv_ir(
    base_cv_text: str,
    supported_terms: list[str] | None = None,
) -> CandidateCvIR:
    text = str(base_cv_text or "").strip()
    roles = _parse_roles(text, supported_terms or [])
    candidate = _parse_candidate_identity(text)
    skills = [
        SkillEvidence(
            id=f"skill_{_slug(term)}",
            name=term,
            source_text=term,
        )
        for term in derive_keywords_used(text, supported_terms or [])
    ]
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


_EXPERIENCE_HEADINGS = (
    "experience", "professional experience", "work experience",
    "employment history", "work history", "career history", "career journey",
    "experiencia", "experiencia profesional", "historial laboral", "trayectoria profesional",
)

_CV_SECTION_HEADINGS = {
    "summary",
    "professional summary",
    "profile",
    "professional profile",
    "perfil",
    "perfil profesional",
    "resumen",
    *_EXPERIENCE_HEADINGS,
    "skills",
    "technical skills",
    "habilidades",
    "competencias",
    "education",
    "formacion",
    "formación",
    "educacion",
    "educación",
}


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

    name = header_lines[0]
    contact_lines = [
        line
        for line in header_lines[1:]
        if _looks_like_contact_line(line)
    ]

    return CandidateIdentity(
        name=name,
        contact=" | ".join(contact_lines),
    )


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

    digits = sum(character.isdigit() for character in value)
    if digits >= 7:
        return True

    if "," in value and len(value) <= 60 and not value.endswith("."):
        return True

    return False


def _parse_summary_facts(
    text: str,
    roles: list[ExperienceRole],
) -> list[EvidenceFact]:
    section = _section(
        text,
        (
            "summary",
            "professional summary",
            "profile",
            "professional profile",
            "perfil",
            "perfil profesional",
            "resumen",
        ),
        (
            *_EXPERIENCE_HEADINGS,
            "skills",
            "technical skills",
            "habilidades",
            "competencias",
            "education",
            "formacion",
            "formación",
            "educacion",
            "educación",
        ),
    )

    fact_texts = [
        _strip_bullet_prefix(line)
        for line in section.splitlines()
        if _strip_bullet_prefix(line)
    ]

    if not fact_texts:
        fact_texts = [
            bullet.source_text
            for role in roles
            for bullet in role.bullets
        ][:3]

    return [
        EvidenceFact(
            id=f"fact_{index + 1:02d}",
            source_text=fact_text,
        )
        for index, fact_text in enumerate(fact_texts[:5])
    ]


def _normalized_heading(line: str) -> str:
    return str(line or "").strip().strip(":").casefold()


def _strip_bullet_prefix(line: str) -> str:
    value = str(line or "").strip()
    while value.startswith(BULLET_PREFIXES):
        value = value[1:].lstrip()
    return value


def validate_ats_cv_plan(cv_ir: CandidateCvIR, plan: AtsCvPlan) -> list[str]:
    evidence_ids = {fact.id for fact in cv_ir.summary_facts}
    evidence_ids.update(skill.id for skill in cv_ir.skills)
    evidence_ids.update(bullet.id for role in cv_ir.roles for bullet in role.bullets)
    role_ids = {role.id for role in cv_ir.roles}
    errors: list[str] = []
    for line in plan.summary_lines:
        if str(line.text or "").strip() and not line.evidence_ids:
            errors.append("summary line must include at least one evidence id")
            continue
        unknown = [evidence_id for evidence_id in line.evidence_ids if evidence_id not in evidence_ids]
        if unknown:
            errors.append(f"summary line references unknown evidence ids: {', '.join(unknown)}")
    for role_plan in plan.role_plans:
        if role_plan.role_id not in role_ids:
            errors.append(f"role plan references unknown role id: {role_plan.role_id}")
            continue
        role = next(role for role in cv_ir.roles if role.id == role_plan.role_id)
        bullet_ids = {bullet.id for bullet in role.bullets}
        unknown = [bullet_id for bullet_id in role_plan.selected_bullet_ids if bullet_id not in bullet_ids]
        if unknown:
            errors.append(f"role {role.id} references unknown bullet ids: {', '.join(unknown)}")
    return errors


def render_ats_cv(cv_ir: CandidateCvIR, plan: AtsCvPlan | None = None, *, min_bullets_per_role: int = 2) -> str:
    plan = plan or AtsCvPlan()
    plan_errors = validate_ats_cv_plan(cv_ir, plan)
    if plan_errors:
        raise ValueError("; ".join(plan_errors))
    selected_skill_ids = set(plan.skill_ids)
    selected_skills = [skill.name for skill in cv_ir.skills if not selected_skill_ids or skill.id in selected_skill_ids]
    summary_lines = [line.text for line in plan.summary_lines if line.text.strip()]
    if not summary_lines:
        summary_lines = [fact.source_text for fact in cv_ir.summary_facts[:3]]
    output = [cv_ir.candidate.name]
    if cv_ir.candidate.contact:
        output.append(cv_ir.candidate.contact)
    output.extend(["", "Professional Summary"])
    output.extend(summary_lines or ["Source-backed software engineering profile."])
    if selected_skills:
        output.extend(["", "Technical Skills", ", ".join(selected_skills)])
    output.extend(["", "Professional Experience"])
    role_plans = {role_plan.role_id: role_plan for role_plan in plan.role_plans}
    for role in cv_ir.roles:
        output.append(f"{role.title} | {role.company}{f' | {role.location}' if role.location else ''} | {role.dates}")
        selected_ids = role_plans.get(role.id).selected_bullet_ids if role.id in role_plans else []
        bullets = [bullet for bullet in role.bullets if bullet.mandatory or not selected_ids or bullet.id in selected_ids]
        if len(bullets) < min_bullets_per_role:
            for bullet in role.bullets:
                if bullet not in bullets:
                    bullets.append(bullet)
                if len(bullets) >= min_bullets_per_role:
                    break
        for bullet in bullets:
            output.append(f"- {bullet.source_text.strip().lstrip('-* ').strip()}")
        if role.canonical_technologies:
            output.append(f"Technologies: {', '.join(role.canonical_technologies)}")
    if cv_ir.education:
        output.extend(["", "Education"])
        output.extend(entry.source_text for entry in cv_ir.education)
    return "\n".join(line for line in output if line is not None).strip()


def _parse_roles(text: str, supported_terms: list[str]) -> list[ExperienceRole]:
    section = _section(text, _EXPERIENCE_HEADINGS, ("education", "skills", "technical skills", "formacion", "formación"))
    section = _section(text, ("experience", "professional experience", "experiencia", "experiencia profesional"), ("education", "skills", "technical skills", "formacion", "formación"))
    if not section:
        return []
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    header_indices = [idx for idx, line in enumerate(lines) if _date_range_match(line)]
    roles: list[ExperienceRole] = []
    for role_index, header_idx in enumerate(header_indices):
        header = lines[header_idx]
        next_idx = header_indices[role_index + 1] if role_index + 1 < len(header_indices) else len(lines)
        block = lines[header_idx + 1:next_idx]
        title, dates = _split_title_dates(header)
        company = _first_non_bullet(block) or "Unknown company"
        bullets = [
            EvidenceBullet(
                id=f"role_{role_index + 1:02d}_b{bullet_index + 1:02d}",
                source_text=line.lstrip("-*\u2022\u25aa\u25e6\u2023\u00b7 ").strip(),
                technologies=derive_keywords_used(line, supported_terms),
                mandatory=bullet_index == 0,
            )
            for bullet_index, line in enumerate(block)
            if line.startswith(BULLET_PREFIXES)
        ]
        canonical: list[str] = []
        for line in block:
            parsed_technologies = _parse_canonical_technology_line(line)
            if parsed_technologies:
                canonical = parsed_technologies
        roles.append(
            ExperienceRole(
                id=f"role_{role_index + 1:02d}_{_slug(company)}",
                title=title or "Experience",
                company=company,
                location=None,
                dates=dates,
                bullets=bullets,
                canonical_technologies=canonical,
            )
        )
    return roles


def _parse_canonical_technology_line(line: str) -> list[str]:
    value = _strip_bullet_prefix(line)

    match = re.search(
        r"(?i)\b(?:technologies|technology|tecnologias|tecnologías)\s*:\s*(.+)$",
        value,
    )
    if not match:
        return []

    technologies: list[str] = []
    seen: set[str] = set()

    for item in re.split(r"[,;]", match.group(1)):
        technology = item.strip(" .\t")
        key = technology.casefold()

        if not technology or key in seen:
            continue

        seen.add(key)
        technologies.append(technology)

    return technologies


def _parse_education(text: str) -> list[EducationEntry]:
    section = _section(text, ("education", "formacion", "formación"), ("skills", "experience", "professional experience"))
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    return [EducationEntry(id=f"education_{idx + 1:02d}", source_text=line) for idx, line in enumerate(lines)]


def _section(text: str, headings: tuple[str, ...], stop_headings: tuple[str, ...]) -> str:
    heading_pattern = "|".join(re.escape(heading) for heading in headings)
    stop_pattern = "|".join(re.escape(heading) for heading in stop_headings)
    match = re.search(rf"(?ims)^\s*({heading_pattern})\s*$([\s\S]*?)(?=^\s*({stop_pattern})\s*$|\Z)", text)
    return match.group(2) if match else ""


def _date_range_match(line: str) -> re.Match[str] | None:
    return re.search(r"(?i)\b(?:\w+\s+)?\d{4}\s*[-–—]\s*(?:\w+\s+)?(?:\d{4}|present|current|actualidad|presente)\b", line)


def _split_title_dates(header: str) -> tuple[str, str]:
    match = _date_range_match(header)
    if not match:
        return header.strip(), ""
    return header[: match.start()].strip(" -|"), match.group(0)


def _first_non_bullet(lines: list[str]) -> str:
    for line in lines[:3]:
        if not line.startswith(BULLET_PREFIXES) and not _date_range_match(line) and "technolog" not in line.lower():
            return line.strip()
    return ""


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "item"


# Extended section aliases and optional-colon headings.
def _section(text: str, headings: tuple[str, ...], stop_headings: tuple[str, ...]) -> str:
    heading_pattern = "|".join(re.escape(heading) for heading in headings)
    stop_pattern = "|".join(re.escape(heading) for heading in stop_headings)
    match = re.search(rf"(?ims)^\s*({heading_pattern})\s*:?\s*$([\s\S]*?)(?=^\s*({stop_pattern})\s*:?\s*$|\Z)", text)
    return match.group(2) if match else ""


def _parse_roles(text: str, supported_terms: list[str]) -> list[ExperienceRole]:
    section = _section(text, _EXPERIENCE_HEADINGS, ("education", "skills", "technical skills", "formacion", "formación"))
    if not section:
        return []
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    header_indices = [idx for idx, line in enumerate(lines) if _date_range_match(line)]
    roles: list[ExperienceRole] = []
    for role_index, header_idx in enumerate(header_indices):
        header = lines[header_idx]
        next_idx = header_indices[role_index + 1] if role_index + 1 < len(header_indices) else len(lines)
        block = lines[header_idx + 1:next_idx]
        title, dates = _split_title_dates(header)
        company = _first_non_bullet(block) or "Unknown company"
        bullets = [EvidenceBullet(id=f"role_{role_index + 1:02d}_b{bullet_index + 1:02d}", source_text=_strip_bullet_prefix(line), technologies=derive_keywords_used(line, supported_terms), mandatory=bullet_index == 0) for bullet_index, line in enumerate(block) if line.startswith(BULLET_PREFIXES)]
        canonical = []
        for line in block:
            parsed = _parse_canonical_technology_line(line)
            if parsed:
                canonical = parsed
        roles.append(ExperienceRole(id=f"role_{role_index + 1:02d}_{_slug(company)}", title=title or "Experience", company=company, location=None, dates=dates, bullets=bullets, canonical_technologies=canonical))
    return roles


def _parse_summary_facts(text: str, roles: list[ExperienceRole]) -> list[EvidenceFact]:
    section = _section(text, ("summary", "professional summary", "profile", "professional profile", "perfil", "perfil profesional", "resumen"), (*_EXPERIENCE_HEADINGS, "skills", "technical skills", "habilidades", "competencias", "education", "formacion", "formación", "educacion", "educación"))
    fact_texts = [_strip_bullet_prefix(line) for line in section.splitlines() if _strip_bullet_prefix(line)]
    if not fact_texts:
        fact_texts = [bullet.source_text for role in roles for bullet in role.bullets][:3]
    return [EvidenceFact(id=f"fact_{index + 1:02d}", source_text=fact_text) for index, fact_text in enumerate(fact_texts[:5])]


def _parse_education(text: str) -> list[EducationEntry]:
    section = _section(text, ("education", "formacion", "formación"), ("skills", *_EXPERIENCE_HEADINGS))
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    return [EducationEntry(id=f"education_{idx + 1:02d}", source_text=line) for idx, line in enumerate(lines)]
