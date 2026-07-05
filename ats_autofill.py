from __future__ import annotations

from typing import Dict, Any


def build_ats_form_responses(job: Dict[str, Any], ats_type: str = "greenhouse") -> Dict[str, Any]:
    """Generate structured answers for common ATS application questions."""
    title = job.get("title") or "the role"
    company = job.get("company") or "the company"
    description = job.get("description") or ""

    return {
        "ats_type": ats_type.lower(),
        "responses": [
            {
                "field": "why_work_here",
                "question": f"Why do you want to work at {company}?",
                "answer": f"I am excited by the chance to contribute to {company} in a role that combines product impact, technical depth, and continuous learning.",
            },
            {
                "field": "tell_us_about_yourself",
                "question": "Tell us about yourself",
                "answer": f"I am a software engineer with experience building reliable backend systems and delivering products in {title.lower()} contexts.",
            },
            {
                "field": "relevant_experience",
                "question": "What experience is most relevant to this role?",
                "answer": description[:220] if description else "I bring hands-on experience building scalable systems, collaborating across teams, and owning delivery end to end.",
            },
            {
                "field": "motivation",
                "question": "What motivates you in this role?",
                "answer": "I am motivated by solving meaningful problems, improving product reliability, and helping teams ship with confidence.",
            },
        ],
    }


def build_autofill_plan(job: Dict[str, Any], ats_type: str = "greenhouse") -> Dict[str, Any]:
    """Build a lightweight autofill plan for supported ATS providers."""
    title = job.get("title") or "Role"
    company = job.get("company") or "the company"
    description = job.get("description") or ""

    questions = [
        {
            "field": "why_join",
            "question": f"Why are you interested in {title} at {company}?",
            "answer": f"I want to help {company} build reliable products and improve technical delivery.",
        },
        {
            "field": "experience",
            "question": "What experience is most relevant to this position?",
            "answer": "I have hands-on experience building backend services, APIs, and leading delivery with a pragmatic approach.",
        },
    ]

    if "lead" in description.lower() or "mentor" in description.lower():
        questions.append({
            "field": "leadership",
            "question": "How have you led others or influenced delivery?",
            "answer": "I have mentored engineers and improved engineering quality through clear standards and collaboration.",
        })

    responses = build_ats_form_responses(job, ats_type=ats_type)

    return {
        "ats_type": ats_type.lower(),
        "company": company,
        "title": title,
        "questions": questions,
        "field_mappings": {
            "resume": "Upload latest resume",
            "cover_letter": "Paste tailored cover letter",
            "linkedin": "Paste LinkedIn profile URL",
        },
        "form_responses": responses["responses"],
        "copy_paste_block": "\n".join(f"{q['field']}: {q['answer']}" for q in questions),
    }
