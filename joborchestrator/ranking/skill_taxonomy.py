from __future__ import annotations

from joborchestrator.scanning.normalization import normalize_text

SKILL_TAXONOMY: dict[str, list[str]] = {
    "FastAPI": ["Python", "Backend", "REST APIs", "API Framework"],
    "API": ["REST APIs", "Backend"],
    "APIs": ["REST APIs", "Backend"],
    "Integrations": ["REST APIs", "Backend", "Technical Consulting"],
    "Django": ["Python", "Backend", "Web Framework"],
    "Django REST Framework": ["Python", "Backend", "REST APIs"],
    "Flask": ["Python", "Backend", "API Framework"],
    "Aurora": ["SQL", "AWS", "Relational Database"],
    "MySQL": ["SQL", "Relational Database"],
    "PostgreSQL": ["SQL", "Relational Database"],
    "DocumentDB": ["NoSQL", "MongoDB-like", "AWS"],
    "MongoDB": ["NoSQL", "Document Database"],
    "Redis": ["Cache", "In-memory DB"],
    "Celery": ["Async Processing", "Task Queue"],
    "RabbitMQ": ["Message Broker", "Queue"],
    "Docker": ["Containers"],
    "Kubernetes": ["Orchestration"],
    "AWS Lambda": ["AWS", "Serverless"],
    "S3": ["AWS", "Object Storage"],
    "RDS": ["AWS", "Relational Database"],
}

COMMON_SKILLS = [
    "Python",
    "Django",
    "Django REST Framework",
    "FastAPI",
    "Flask",
    "REST APIs",
    "API",
    "APIs",
    "Integrations",
    "GraphQL",
    "SQL",
    "MySQL",
    "PostgreSQL",
    "Aurora",
    "MongoDB",
    "DocumentDB",
    "Redis",
    "Docker",
    "Kubernetes",
    "AWS",
    "AWS Lambda",
    "S3",
    "RDS",
    "GCP",
    "Azure",
    "Celery",
    "RabbitMQ",
    "Kafka",
    "React",
    "TypeScript",
    "JavaScript",
    "Node",
    "Terraform",
    "CI/CD",
    "ETL",
    "Airflow",
    "LLM",
    "AI",
    "Machine Learning",
]


def expand_skill(skill: str) -> set[str]:
    expanded = {skill}
    for alias in SKILL_TAXONOMY.get(skill, []):
        expanded.add(alias)
    return expanded


def expand_skills(skills: list[str]) -> set[str]:
    expanded: set[str] = set()
    for skill in skills:
        expanded.update(expand_skill(skill))
    return expanded


def find_skills(text: str) -> list[str]:
    normalized = normalize_text(text)
    found = []
    for skill in sorted(COMMON_SKILLS, key=len, reverse=True):
        skill_norm = normalize_text(skill)
        if _contains_term(normalized, skill_norm):
            found.append(skill)
    return _dedupe(found)


def skill_match(required: str, strong: set[str], medium: set[str], weak: set[str]) -> tuple[str, str | None]:
    req_norm = normalize_text(required)
    if not req_norm:
        return "missing", None

    for skill in strong:
        if req_norm == normalize_text(skill):
            return "strong", skill
    for skill in medium:
        if req_norm == normalize_text(skill):
            return "partial", skill
    for skill in weak:
        if req_norm == normalize_text(skill):
            return "weak", skill

    req_expanded = {normalize_text(x) for x in expand_skill(required)}
    strong_expanded = {normalize_text(x) for x in expand_skills(list(strong))}
    medium_expanded = {normalize_text(x) for x in expand_skills(list(medium))}

    if req_expanded & strong_expanded:
        return "partial", next(iter(req_expanded & strong_expanded))
    if req_expanded & medium_expanded:
        return "partial", next(iter(req_expanded & medium_expanded))
    return "missing", None


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _contains_term(text: str, term: str) -> bool:
    padded = f" {text} "
    if f" {term} " in padded:
        return True
    if term.endswith("s") and f" {term[:-1]} " in padded:
        return True
    if not term.endswith("s") and f" {term}s " in padded:
        return True
    return False
