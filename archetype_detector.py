"""
Archetype Detector: Clasifica ofertas por tipo de rol.

Detecta automáticamente si es: LLMOps, Agentic, PM, Sales, Developer, Transformation, etc.
Útil para saber qué skills enfatizar en evaluación + CV personalización.
"""

from typing import Dict, List, Tuple
import re


# Palabras clave por archetype
ARCHETYPES = {
    "llmops": {
        "keywords": [
            "langchain", "llamaindex", "ragas", "promptflow", "llm monitoring",
            "token optimization", "latency", "throughput", "prompt engineering",
            "fine-tuning", "model selection", "inference", "llm infrastructure",
            "vector database", "embeddings", "rag", "retrieval augmented"
        ],
        "titles": [
            "llmops", "ml ops", "mlops", "platform engineer.*ai", "inference engineer",
            "model operations", "ai ops"
        ],
    },
    
    "agentic": {
        "keywords": [
            "agent", "autonomous", "reasoning", "tool use", "function calling",
            "workflow", "orchestration", "agentic framework", "crewai", "autogen",
            "cognitive architecture", "planning", "task decomposition", "agent loop"
        ],
        "titles": [
            "agent.*engineer", "agentic", "autonomous", "orchestration engineer",
            "workflow engineer", "reasoning engineer"
        ],
    },
    
    "pm": {
        "keywords": [
            "product management", "product owner", "roadmap", "prioritization",
            "stakeholder", "user research", "analytics", "product strategy",
            "features", "product launch", "go-to-market"
        ],
        "titles": [
            "product manager", "product owner", "pm ", " pm$", "head of product",
            "vp product", "chief product"
        ],
    },
    
    "sales": {
        "keywords": [
            "sales", "quota", "pipeline", "prospecting", "closing", "deal",
            "enterprise", "account executive", "hunting", "business development",
            "revenue", "commission", "territory"
        ],
        "titles": [
            "sales", "account executive", "ae ", "business development",
            "sales engineer", "sales representative", "quota", "hunter"
        ],
    },
    
    "developer": {
        "keywords": [
            "software engineer", "backend", "frontend", "full stack", "api",
            "database", "microservices", "cloud", "devops", "infrastructure",
            "systems", "distributed", "scalability"
        ],
        "titles": [
            "software engineer", "developer", "engineer", "backend", "frontend",
            "full.?stack", "systems engineer", "infrastructure"
        ],
    },
    
    "transformation": {
        "keywords": [
            "transformation", "modernization", "legacy", "migration", "cloud adoption",
            "organizational change", "process improvement", "efficiency", "digital",
            "optimization", "enterprise architecture"
        ],
        "titles": [
            "transformation", "modernization", "change management", "architect",
            "consultant", "migration"
        ],
    },
    
    "research": {
        "keywords": [
            "research", "phd", "publication", "paper", "arxiv", "ml research",
            "deep learning", "neural", "algorithm", "experiment", "methodology",
            "science", "academic"
        ],
        "titles": [
            "researcher", "research scientist", "research engineer", "phd",
            "research lead", "principal scientist"
        ],
    },
    
    "solutions_architect": {
        "keywords": [
            "solutions", "consulting", "architect", "design", "enterprise",
            "customer success", "implementation", "deployment", "framework",
            "best practices", "client"
        ],
        "titles": [
            "solutions architect", "solutions engineer", "consultant",
            "technical architect", "solutions specialist"
        ],
    },
}


def detect_archetype(job: Dict) -> Dict:
    """
    Detecta el archetype de una oferta.
    
    Retorna dict con:
    - primary_archetype: El detectado con más confianza
    - confidence: 0-100
    - detected_archetypes: Dict con scores de cada uno
    - reasoning: Explicación de qué keywords/titles llevaron a la clasificación
    """
    title = (job.get('titulo') or job.get('title', '')).lower()
    description = (job.get('descripcion') or job.get('description', '')).lower()
    company = (job.get('empresa') or job.get('company', '')).lower()
    
    combined_text = f"{title} {description} {company}"
    
    scores = {}
    matched_keywords = {}
    
    for archetype, patterns in ARCHETYPES.items():
        score = 0
        keywords = []
        
        # Búsqueda en títulos (peso 2x)
        for title_pattern in patterns["titles"]:
            if re.search(title_pattern, title, re.IGNORECASE):
                score += 20
                keywords.append(f"title: {title_pattern}")
        
        # Búsqueda en keywords (peso 1x)
        for keyword in patterns["keywords"]:
            if keyword.lower() in combined_text:
                score += 5
                if keyword not in keywords:
                    keywords.append(keyword)
        
        scores[archetype] = score
        matched_keywords[archetype] = keywords[:5]  # Top 5
    
    # Encontrar el principal
    primary = max(scores, key=scores.get)
    primary_score = scores[primary]
    
    # Calcular confianza (0-100)
    # Si el top está muy lejos del segundo, confianza alta
    sorted_scores = sorted(scores.values(), reverse=True)
    if len(sorted_scores) > 1:
        confidence = min(
            100,
            int(50 + (primary_score - sorted_scores[1]) / 2)
        )
    else:
        confidence = min(100, int(primary_score / 2))
    
    # Si no hay match, confidence baja
    if primary_score == 0:
        confidence = 0
        primary = "unknown"
    
    return {
        "primary_archetype": primary if confidence > 20 else "general",
        "confidence": confidence,
        "all_archetypes": scores,
        "matched_keywords": matched_keywords.get(primary, []),
        "reasoning": f"Detected '{primary}' with {len(matched_keywords.get(primary, []))} matching keywords: {', '.join(matched_keywords.get(primary, [])[:3])}",
    }


def batch_detect_archetypes(jobs: List[Dict]) -> List[Dict]:
    """
    Detecta archetype para un lote de ofertas.
    Retorna lista con archetype_detection agregado.
    """
    result = []
    for job in jobs:
        job_copy = job.copy()
        job_copy["archetype_detection"] = detect_archetype(job)
        result.append(job_copy)
    return result


def get_emphasis_by_archetype(archetype: str) -> Dict[str, List[str]]:
    """
    Retorna skills a enfatizar según el archetype.
    """
    emphasis_map = {
        "llmops": {
            "technical": ["LLM infrastructure", "Token optimization", "Prompt engineering", "Fine-tuning", "Vector DBs"],
            "soft": ["Analytical thinking", "Problem-solving", "Documentation", "Attention to detail"],
            "cv_keywords": ["LLM ops", "Model optimization", "Inference", "RAG systems", "LLM monitoring"],
        },
        "agentic": {
            "technical": ["Multi-agent systems", "Tool orchestration", "Reasoning loops", "Function calling", "Workflow design"],
            "soft": ["Systems thinking", "Architecture design", "Problem decomposition"],
            "cv_keywords": ["Agent architectures", "Autonomous systems", "Orchestration", "Tool use", "Agentic frameworks"],
        },
        "pm": {
            "technical": ["Product analytics", "A/B testing", "SQL/Data", "API knowledge"],
            "soft": ["Communication", "Stakeholder management", "Prioritization", "Strategy", "Negotiation"],
            "cv_keywords": ["Product strategy", "Roadmap planning", "Stakeholder mgmt", "Analytics", "Go-to-market"],
        },
        "sales": {
            "technical": ["CRM", "Sales tools", "Data analysis"],
            "soft": ["Communication", "Negotiation", "Relationship building", "Persistence", "Adaptability"],
            "cv_keywords": ["Sales leadership", "Deal closing", "Pipeline mgmt", "Account growth", "Revenue"],
        },
        "developer": {
            "technical": ["System design", "API design", "Database design", "Cloud platforms", "DevOps", "Testing"],
            "soft": ["Code quality", "Documentation", "Collaboration", "Problem-solving"],
            "cv_keywords": ["Microservices", "Distributed systems", "Cloud infrastructure", "API design", "Testing"],
        },
        "transformation": {
            "technical": ["Enterprise systems", "Change mgmt tools", "Integration"],
            "soft": ["Leadership", "Change management", "Communication", "Stakeholder engagement"],
            "cv_keywords": ["Digital transformation", "Legacy modernization", "Process optimization", "Enterprise architecture"],
        },
        "research": {
            "technical": ["ML/DL frameworks", "Statistical analysis", "Experiment design", "Paper writing"],
            "soft": ["Curiosity", "Rigor", "Collaboration", "Communication"],
            "cv_keywords": ["Research methodology", "Novel algorithms", "Publications", "Deep learning", "Experimentation"],
        },
        "solutions_architect": {
            "technical": ["Architecture design", "Consulting tools", "Integration patterns"],
            "soft": ["Client communication", "Problem-solving", "Strategic thinking", "Presentation"],
            "cv_keywords": ["Architecture design", "Enterprise solutions", "Client engagement", "Best practices", "Implementation"],
        },
    }
    
    return emphasis_map.get(archetype, {
        "technical": [],
        "soft": [],
        "cv_keywords": [],
    })


def suggest_cv_angle(job: Dict, archetype_detection: Dict) -> str:
    """
    Sugiere cómo angularizar el CV basado en archetype.
    """
    archetype = archetype_detection.get("primary_archetype", "general")
    confidence = archetype_detection.get("confidence", 0)
    
    if confidence < 30:
        return "Generic approach - couldn't strongly detect role type."
    
    angles = {
        "llmops": "Focus on infrastructure, optimization, and systems thinking. Emphasize any experience with LLM frameworks, vector DBs, or model deployment.",
        "agentic": "Emphasize autonomous system design, orchestration thinking, and tool integration experience. Highlight any multi-agent or complex workflow projects.",
        "pm": "Highlight product thinking, metrics-driven decisions, and stakeholder management. Lead with strategy and vision.",
        "sales": "Emphasize revenue impact, relationship building, and deal closure experience. Quantify numbers.",
        "developer": "Focus on technical depth: architecture, design patterns, system scalability. Code quality matters most.",
        "transformation": "Highlight change leadership, enterprise thinking, and business impact. Show experience with modernization or large-scale projects.",
        "research": "Emphasize novel contributions, experimental rigor, and publications. Show curiosity and scientific thinking.",
        "solutions_architect": "Demonstrate consulting mindset, client success, and architecture thinking. Balance technical and business.",
    }
    
    return angles.get(archetype, "No specific guidance available.")
