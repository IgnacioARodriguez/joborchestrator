from __future__ import annotations

DEFAULT_SKILL_CATALOG: dict[str, list[str]] = {
    "Programming": ["Python", "JavaScript", "TypeScript", "SQL", "Node.js", "Java", "C#", "Go"],
    "Backend": ["FastAPI", "Django", "Django REST Framework", "Flask", "REST APIs", "GraphQL", "Microservices", "API Integrations"],
    "Frontend": ["React", "Next.js", "HTML", "CSS", "Tailwind CSS", "Design Systems", "Accessibility"],
    "Database": ["PostgreSQL", "MongoDB", "MySQL", "Redis", "SQLite", "Aurora", "RDS", "DocumentDB"],
    "Cloud": ["AWS", "AWS Lambda", "S3", "EC2", "Azure", "GCP", "Serverless"],
    "DevOps": ["Docker", "Kubernetes", "Terraform", "CI/CD", "GitHub Actions", "Monitoring", "Linux"],
    "Data": ["ETL", "Airflow", "Pandas", "Data Pipelines", "Analytics", "Machine Learning", "LLM"],
    "Messaging": ["Celery", "RabbitMQ", "Kafka", "Async Processing", "Task Queues"],
    "Product": ["Product Discovery", "Stakeholder Management", "Requirements Analysis", "Roadmapping"],
    "Leadership": ["Mentoring", "Technical Leadership", "Code Review", "Agile", "Cross-functional Collaboration"],
    "Languages": ["English", "Spanish", "French", "German"],
}
