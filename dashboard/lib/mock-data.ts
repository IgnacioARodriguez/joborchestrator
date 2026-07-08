import type { JobPosting, ImportRecord } from "./types"

// Realistic mock data. Structured so it can later be swapped for a Supabase fetch.

function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString()
}

function buildPrompt(job: {
  title: string
  company: string
  description_text: string
}): string {
  return `You are a senior technical recruiter helping me decide whether to apply.

ROLE: ${job.title}
COMPANY: ${job.company}

JOB DESCRIPTION:
${job.description_text}

Return STRICT JSON only, matching this shape:
{
  "final_score": <0-100>,
  "decision": "APPLY_NOW" | "APPLY_WITH_TAILORED_CV" | "MAYBE" | "SKIP" | "AVOID",
  "confidence": <0-1>,
  "reasoning_summary": "<2-3 sentences>",
  "recommended_application_angle": "<1-2 sentences>",
  "evidence": {
    "strong_matches": ["..."],
    "partial_matches": ["..."],
    "missing_requirements": ["..."],
    "red_flags": ["..."],
    "central_requirements": ["..."]
  }
}`
}

export const MOCK_JOBS: JobPosting[] = [
  {
    id: "job_001",
    title: "Senior Python Developer",
    company: "Northwind Data",
    location: "Remote (EU)",
    remote: true,
    source: "LinkedIn",
    url: "https://example.com/jobs/python-dev",
    apply_url: "https://example.com/apply/python-dev",
    description_text:
      "We are looking for a Senior Python Developer to build data-intensive backend services. You will design APIs with FastAPI, work with PostgreSQL, and deploy on AWS. Experience with async Python, Celery, and CI/CD pipelines is expected. You will collaborate with data engineers to ship reliable pipelines.",
    first_seen_at: daysAgo(1),
    last_seen_at: daysAgo(0),
    status: "active",
    pipeline_status: "new",
    ranking: {
      final_score: 91,
      decision: "APPLY_NOW",
      confidence: 0.92,
      scores: {
        role_fit: 95,
        requirement_coverage: 90,
        seniority_match: 92,
        location_fit: 100,
        compensation: 80,
      },
      evidence: {
        strong_matches: ["FastAPI", "PostgreSQL", "Async Python", "AWS"],
        partial_matches: ["Celery", "CI/CD"],
        missing_requirements: [],
        red_flags: [],
        central_requirements: ["5+ years Python", "Backend API design"],
      },
      reasoning_summary:
        "Excellent alignment with your backend Python background. Remote EU and strong stack match make this a top priority application.",
      recommended_application_angle:
        "Lead with your FastAPI + PostgreSQL production experience and async pipeline work.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: false,
      review_reason: "",
      prompt: "",
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message:
        "Hi — I'm a backend Python engineer with 6 years building FastAPI services on AWS. Your Senior Python role looks like a strong match. Would love to connect.",
      cover_letter:
        "I have spent the last several years designing async Python backends with FastAPI and PostgreSQL, deployed on AWS with automated CI/CD. I'm excited about Northwind Data's focus on reliable data pipelines...",
      ats_cv_notes:
        "Emphasize FastAPI, async Python, PostgreSQL tuning, and AWS deployment. Add Celery keyword.",
      autofill_notes: "Years of experience: 6. Work authorization: EU. Notice: 1 month.",
    },
  },
  {
    id: "job_002",
    title: "Backend Engineer (Go/Python)",
    company: "Lumen Systems",
    location: "Berlin, Germany",
    remote: false,
    source: "Greenhouse",
    url: "https://example.com/jobs/backend-eng",
    apply_url: "https://example.com/apply/backend-eng",
    description_text:
      "Backend Engineer to work on high-throughput microservices. Primary stack is Go with some Python tooling. You should be comfortable with gRPC, Kafka, Kubernetes, and observability tooling. On-site in Berlin 3 days per week.",
    first_seen_at: daysAgo(2),
    last_seen_at: daysAgo(0),
    status: "active",
    pipeline_status: "shortlisted",
    ranking: {
      final_score: 74,
      decision: "APPLY_WITH_TAILORED_CV",
      confidence: 0.78,
      scores: {
        role_fit: 78,
        requirement_coverage: 68,
        seniority_match: 82,
        location_fit: 55,
        compensation: 85,
      },
      evidence: {
        strong_matches: ["Python tooling", "Microservices", "Kubernetes"],
        partial_matches: ["gRPC", "Kafka"],
        missing_requirements: ["Production Go experience"],
        red_flags: ["On-site 3 days in Berlin"],
        central_requirements: ["Go proficiency", "Distributed systems"],
      },
      reasoning_summary:
        "Solid systems match but the role is Go-first and requires Berlin on-site. Worth applying with a CV that highlights transferable distributed systems work.",
      recommended_application_angle:
        "Position your microservices and Kubernetes experience, and frame Go as a fast ramp given your Python depth.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: false,
      review_reason: "",
      prompt: "",
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message:
        "Hi — strong distributed systems background here (Kubernetes, microservices). Interested in your Backend Engineer role and happy to discuss the Go ramp-up.",
      cover_letter:
        "I've built and operated high-throughput microservices on Kubernetes and am eager to deepen my Go work at Lumen Systems...",
      ats_cv_notes: "Highlight Kubernetes, gRPC exposure, distributed systems. Mention Go interest.",
      autofill_notes: "Relocation: open to Berlin. Notice: 2 months.",
    },
  },
  {
    id: "job_003",
    title: "Technical Consultant",
    company: "Vantage Advisory",
    location: "Remote (Global)",
    remote: true,
    source: "Lever",
    url: "https://example.com/jobs/tech-consultant",
    apply_url: "https://example.com/apply/tech-consultant",
    description_text:
      "Client-facing Technical Consultant to implement integrations and advise enterprise customers. Requires strong communication, API integration experience, and ability to travel occasionally. SQL and scripting skills valued.",
    first_seen_at: daysAgo(3),
    last_seen_at: daysAgo(1),
    status: "active",
    pipeline_status: "new",
    ranking: {
      final_score: 58,
      decision: "MAYBE",
      confidence: 0.54,
      scores: {
        role_fit: 60,
        requirement_coverage: 55,
        seniority_match: 65,
        location_fit: 100,
        compensation: 60,
      },
      evidence: {
        strong_matches: ["API integration", "SQL"],
        partial_matches: ["Client-facing work"],
        missing_requirements: ["Enterprise consulting background"],
        red_flags: ["Occasional travel"],
        central_requirements: ["Customer-facing delivery", "Integration experience"],
      },
      reasoning_summary:
        "Mixed fit. Your integration skills transfer, but this is more consulting than engineering. Confidence is low — worth a manual review.",
      recommended_application_angle:
        "If applying, emphasize customer-facing integration projects and clear communication.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: true,
      review_reason: "Low confidence (0.54) and ambiguous role type (consulting vs engineering).",
      prompt: buildPrompt({
        title: "Technical Consultant",
        company: "Vantage Advisory",
        description_text:
          "Client-facing Technical Consultant to implement integrations and advise enterprise customers. Requires strong communication, API integration experience, and ability to travel occasionally. SQL and scripting skills valued.",
      }),
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message:
        "Hi — I have hands-on API integration and SQL experience and enjoy customer-facing delivery. Curious about your Technical Consultant role.",
      cover_letter:
        "I combine engineering depth with clear communication, having delivered integration projects directly with customers...",
      ats_cv_notes: "Reframe engineering work as delivery/consulting outcomes.",
      autofill_notes: "Travel: occasional OK. Remote: preferred.",
    },
  },
  {
    id: "job_004",
    title: "Embedded Firmware Engineer",
    company: "Cortex Robotics",
    location: "Munich, Germany",
    remote: false,
    source: "Ashby",
    url: "https://example.com/jobs/embedded-firmware",
    apply_url: "https://example.com/apply/embedded-firmware",
    description_text:
      "Embedded Firmware Engineer to develop C/C++ firmware for robotics controllers. Requires RTOS experience, hardware debugging, and low-level driver development. Strong C fundamentals required.",
    first_seen_at: daysAgo(4),
    last_seen_at: daysAgo(2),
    status: "active",
    pipeline_status: "new",
    ranking: {
      final_score: 28,
      decision: "SKIP",
      confidence: 0.88,
      scores: {
        role_fit: 20,
        requirement_coverage: 15,
        seniority_match: 60,
        location_fit: 40,
        compensation: 70,
      },
      evidence: {
        strong_matches: [],
        partial_matches: ["General engineering fundamentals"],
        missing_requirements: ["C/C++ firmware", "RTOS", "Hardware debugging"],
        red_flags: ["Requires embedded specialization you don't have"],
        central_requirements: ["Embedded C/C++", "RTOS"],
      },
      reasoning_summary:
        "Poor fit. This is a specialized embedded firmware role far from your backend/data profile.",
      recommended_application_angle: "Not recommended.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: false,
      review_reason: "",
      prompt: "",
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message: "",
      cover_letter: "",
      ats_cv_notes: "",
      autofill_notes: "",
    },
  },
  {
    id: "job_005",
    title: "Data Engineer",
    company: "Meridian Analytics",
    location: "Remote (EU)",
    remote: true,
    source: "API",
    url: "https://example.com/jobs/data-engineer",
    apply_url: "https://example.com/apply/data-engineer",
    description_text:
      "Data Engineer to build and maintain ELT pipelines. Stack includes Python, dbt, Airflow, Snowflake, and AWS. You will own data quality and collaborate with analysts. SQL mastery required.",
    first_seen_at: daysAgo(1),
    last_seen_at: daysAgo(0),
    status: "active",
    pipeline_status: "applied",
    ranking: {
      final_score: 86,
      decision: "APPLY_NOW",
      confidence: 0.89,
      scores: {
        role_fit: 88,
        requirement_coverage: 85,
        seniority_match: 84,
        location_fit: 100,
        compensation: 82,
      },
      evidence: {
        strong_matches: ["Python", "SQL", "AWS", "ELT pipelines"],
        partial_matches: ["dbt", "Airflow", "Snowflake"],
        missing_requirements: [],
        red_flags: [],
        central_requirements: ["Pipeline ownership", "SQL mastery"],
      },
      reasoning_summary:
        "Strong match for your data + Python background. Already applied — track progress in pipeline.",
      recommended_application_angle:
        "Highlight end-to-end pipeline ownership and data quality practices.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: false,
      review_reason: "",
      prompt: "",
      pasted_chatgpt_json: null,
      applied_at: daysAgo(1),
    },
    materials: {
      recruiter_message:
        "Hi — data engineer with strong Python/SQL and AWS pipeline experience. Excited about the ELT ownership in this role.",
      cover_letter:
        "I've built ELT pipelines end to end with a focus on data quality and reliability...",
      ats_cv_notes: "Add dbt, Airflow, Snowflake keywords.",
      autofill_notes: "Notice: 1 month. Remote EU.",
    },
  },
  {
    id: "job_006",
    title: "Frontend Engineer (React)",
    company: "Brightloop",
    location: "Remote (EU)",
    remote: true,
    source: "LinkedIn",
    url: "https://example.com/jobs/frontend-eng",
    apply_url: "https://example.com/apply/frontend-eng",
    description_text:
      "Frontend Engineer to build modern web apps with React, TypeScript, and Next.js. Design-system experience and attention to UX detail expected. Some backend collaboration required.",
    first_seen_at: daysAgo(5),
    last_seen_at: daysAgo(1),
    status: "active",
    pipeline_status: "new",
    ranking: {
      final_score: 63,
      decision: "MAYBE",
      confidence: 0.61,
      scores: {
        role_fit: 62,
        requirement_coverage: 60,
        seniority_match: 70,
        location_fit: 100,
        compensation: 72,
      },
      evidence: {
        strong_matches: ["TypeScript", "Next.js"],
        partial_matches: ["React", "Design systems"],
        missing_requirements: ["Deep frontend specialization"],
        red_flags: [],
        central_requirements: ["React proficiency", "UX detail"],
      },
      reasoning_summary:
        "Reasonable fit if you want to pivot toward frontend. Your TypeScript/Next.js exposure helps, but it's a role shift.",
      recommended_application_angle:
        "Frame full-stack work and any React/Next.js projects prominently.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: true,
      review_reason: "Role direction shift (backend to frontend) — needs judgment call.",
      prompt: buildPrompt({
        title: "Frontend Engineer (React)",
        company: "Brightloop",
        description_text:
          "Frontend Engineer to build modern web apps with React, TypeScript, and Next.js. Design-system experience and attention to UX detail expected. Some backend collaboration required.",
      }),
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message:
        "Hi — full-stack leaning engineer comfortable with TypeScript and Next.js. Interested in your Frontend Engineer role.",
      cover_letter:
        "I enjoy building polished web interfaces with React and Next.js and care about UX detail...",
      ats_cv_notes: "Lead with React/Next.js projects.",
      autofill_notes: "Remote EU. Notice: 1 month.",
    },
  },
  {
    id: "job_007",
    title: "Salesforce Administrator",
    company: "Cloudpeak CRM",
    location: "Remote (US)",
    remote: true,
    source: "Greenhouse",
    url: "https://example.com/jobs/salesforce-admin",
    apply_url: "https://example.com/apply/salesforce-admin",
    description_text:
      "Salesforce Administrator to manage configuration, flows, and user permissions. Requires Salesforce certification and CRM administration experience. US time zone required.",
    first_seen_at: daysAgo(6),
    last_seen_at: daysAgo(3),
    status: "active",
    pipeline_status: "discarded",
    ranking: {
      final_score: 14,
      decision: "AVOID",
      confidence: 0.94,
      scores: {
        role_fit: 10,
        requirement_coverage: 8,
        seniority_match: 40,
        location_fit: 20,
        compensation: 50,
      },
      evidence: {
        strong_matches: [],
        partial_matches: [],
        missing_requirements: ["Salesforce certification", "CRM admin experience"],
        red_flags: ["US time zone", "Non-engineering role"],
        central_requirements: ["Salesforce admin", "Certification"],
      },
      reasoning_summary:
        "Not aligned with your profile at all. Different discipline and time zone.",
      recommended_application_angle: "Avoid.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: false,
      review_reason: "",
      prompt: "",
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message: "",
      cover_letter: "",
      ats_cv_notes: "",
      autofill_notes: "",
    },
  },
  {
    id: "job_008",
    title: "Python Backend Engineer",
    company: "Fintech Nova",
    location: "Remote (EU)",
    remote: true,
    source: "Lever",
    url: "https://example.com/jobs/python-backend",
    apply_url: "https://example.com/apply/python-backend",
    description_text:
      "Python Backend Engineer for a fintech platform. Django and DRF, PostgreSQL, Redis, and event-driven architecture. Security-conscious mindset and testing discipline required.",
    first_seen_at: daysAgo(0),
    last_seen_at: daysAgo(0),
    status: "active",
    pipeline_status: "new",
    ranking: {
      final_score: 82,
      decision: "APPLY_WITH_TAILORED_CV",
      confidence: 0.8,
      scores: {
        role_fit: 85,
        requirement_coverage: 78,
        seniority_match: 80,
        location_fit: 100,
        compensation: 78,
      },
      evidence: {
        strong_matches: ["Python", "PostgreSQL", "Redis"],
        partial_matches: ["Django/DRF", "Event-driven architecture"],
        missing_requirements: ["Fintech domain experience"],
        red_flags: [],
        central_requirements: ["Django proficiency", "Testing discipline"],
      },
      reasoning_summary:
        "Strong technical fit; tailor CV to emphasize Django and testing to offset lack of fintech domain.",
      recommended_application_angle:
        "Emphasize Django/DRF, security practices, and strong test coverage.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: false,
      review_reason: "",
      prompt: "",
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message:
        "Hi — Python backend engineer with Django, PostgreSQL, and Redis experience and a testing-first mindset. Keen on your fintech role.",
      cover_letter:
        "I build secure, well-tested Python backends with Django and PostgreSQL...",
      ats_cv_notes: "Emphasize Django/DRF and testing. Add Redis, event-driven keywords.",
      autofill_notes: "Remote EU. Notice: 1 month.",
    },
  },
  {
    id: "job_009",
    title: "Senior Data Engineer",
    company: "Helix Cloud",
    location: "Amsterdam, Netherlands",
    remote: false,
    source: "Ashby",
    url: "https://example.com/jobs/senior-data-eng",
    apply_url: "https://example.com/apply/senior-data-eng",
    description_text:
      "Senior Data Engineer to lead pipeline architecture. Spark, Kafka, Python, and cloud data warehousing. Mentorship and design leadership expected. Hybrid in Amsterdam.",
    first_seen_at: daysAgo(2),
    last_seen_at: daysAgo(0),
    status: "active",
    pipeline_status: "shortlisted",
    ranking: {
      final_score: 79,
      decision: "APPLY_WITH_TAILORED_CV",
      confidence: 0.75,
      scores: {
        role_fit: 82,
        requirement_coverage: 74,
        seniority_match: 88,
        location_fit: 60,
        compensation: 84,
      },
      evidence: {
        strong_matches: ["Python", "Data warehousing", "Pipeline design"],
        partial_matches: ["Spark", "Kafka"],
        missing_requirements: ["Large-scale Spark leadership"],
        red_flags: ["Hybrid Amsterdam"],
        central_requirements: ["Design leadership", "Streaming pipelines"],
      },
      reasoning_summary:
        "Good senior-level data fit. Tailor CV to highlight design leadership and any Spark/Kafka exposure.",
      recommended_application_angle:
        "Lead with pipeline architecture ownership and mentorship examples.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: false,
      review_reason: "",
      prompt: "",
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message:
        "Hi — senior data engineer with pipeline architecture and mentorship experience. Interested in your Senior Data Engineer role.",
      cover_letter:
        "I've owned pipeline architecture decisions and mentored engineers while scaling data platforms...",
      ats_cv_notes: "Emphasize leadership, Spark/Kafka, warehousing.",
      autofill_notes: "Hybrid Amsterdam OK. Notice: 2 months.",
    },
  },
  {
    id: "job_010",
    title: "Backend Engineer (Node/Python)",
    company: "Stackforge",
    location: "Remote (EU)",
    remote: true,
    source: "LinkedIn",
    url: "https://example.com/jobs/backend-node-python",
    apply_url: "https://example.com/apply/backend-node-python",
    description_text:
      "Backend Engineer to build APIs in Node.js and Python. REST and GraphQL, PostgreSQL, and container-based deployment. Startup pace with broad ownership.",
    first_seen_at: daysAgo(3),
    last_seen_at: daysAgo(0),
    status: "active",
    pipeline_status: "opened",
    ranking: {
      final_score: 71,
      decision: "MAYBE",
      confidence: 0.66,
      scores: {
        role_fit: 72,
        requirement_coverage: 68,
        seniority_match: 74,
        location_fit: 100,
        compensation: 68,
      },
      evidence: {
        strong_matches: ["Python", "PostgreSQL", "REST APIs"],
        partial_matches: ["Node.js", "GraphQL"],
        missing_requirements: ["Strong Node.js production experience"],
        red_flags: ["Startup pace / broad scope"],
        central_requirements: ["API development", "Container deployment"],
      },
      reasoning_summary:
        "Decent fit with a Node.js gap. A maybe — depends on your appetite for startup pace.",
      recommended_application_angle:
        "Highlight API breadth and containerized deployment; note Node.js familiarity.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: false,
      review_reason: "",
      prompt: "",
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message:
        "Hi — backend engineer strong in Python and APIs, comfortable with containers. Curious about your Backend Engineer role.",
      cover_letter:
        "I build and ship APIs quickly with a focus on reliability, and I'm comfortable in fast-moving teams...",
      ats_cv_notes: "Add Node.js, GraphQL keywords.",
      autofill_notes: "Remote EU. Notice: 1 month.",
    },
  },
  {
    id: "job_011",
    title: "Platform Engineer (Python/AWS)",
    company: "Quanta Grid",
    location: "Remote (EU)",
    remote: true,
    source: "API",
    url: "https://example.com/jobs/platform-eng",
    apply_url: "https://example.com/apply/platform-eng",
    description_text:
      "Platform Engineer to build internal developer platforms. Python tooling, AWS, Terraform, and Kubernetes. Focus on developer experience and reliability.",
    first_seen_at: daysAgo(4),
    last_seen_at: daysAgo(1),
    status: "active",
    pipeline_status: "new",
    ranking: {
      final_score: 68,
      decision: "MAYBE",
      confidence: 0.58,
      scores: {
        role_fit: 70,
        requirement_coverage: 64,
        seniority_match: 76,
        location_fit: 100,
        compensation: 80,
      },
      evidence: {
        strong_matches: ["Python", "AWS"],
        partial_matches: ["Terraform", "Kubernetes"],
        missing_requirements: ["Platform engineering focus"],
        red_flags: [],
        central_requirements: ["IaC", "Developer experience"],
      },
      reasoning_summary:
        "Borderline. Infra-leaning role; your Python + AWS help but platform focus is new. Low confidence — review manually.",
      recommended_application_angle:
        "Highlight any IaC/automation work and internal tooling you've built.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: true,
      review_reason: "Low confidence (0.58) and adjacent-but-different specialization.",
      prompt: buildPrompt({
        title: "Platform Engineer (Python/AWS)",
        company: "Quanta Grid",
        description_text:
          "Platform Engineer to build internal developer platforms. Python tooling, AWS, Terraform, and Kubernetes. Focus on developer experience and reliability.",
      }),
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message:
        "Hi — Python + AWS engineer interested in developer platforms and internal tooling. Keen to learn more.",
      cover_letter:
        "I care about developer experience and have automated internal workflows with Python and AWS...",
      ats_cv_notes: "Add Terraform, Kubernetes, platform keywords.",
      autofill_notes: "Remote EU. Notice: 1 month.",
    },
  },
  {
    id: "job_012",
    title: "Applied Data Engineer",
    company: "Signal Labs",
    location: "Remote (EU)",
    remote: true,
    source: "Greenhouse",
    url: "https://example.com/jobs/applied-data-eng",
    apply_url: "https://example.com/apply/applied-data-eng",
    description_text:
      "Applied Data Engineer bridging ML and data infrastructure. Python, feature pipelines, and cloud warehousing. Collaborate with ML engineers to productionize models.",
    first_seen_at: daysAgo(1),
    last_seen_at: daysAgo(0),
    status: "active",
    pipeline_status: "new",
    ranking: {
      final_score: 84,
      decision: "APPLY_NOW",
      confidence: 0.86,
      scores: {
        role_fit: 86,
        requirement_coverage: 82,
        seniority_match: 82,
        location_fit: 100,
        compensation: 80,
      },
      evidence: {
        strong_matches: ["Python", "Feature pipelines", "Cloud warehousing"],
        partial_matches: ["ML productionization"],
        missing_requirements: [],
        red_flags: [],
        central_requirements: ["Data pipelines", "ML collaboration"],
      },
      reasoning_summary:
        "Strong data engineering fit with a nice ML-adjacent angle. High priority.",
      recommended_application_angle:
        "Emphasize pipeline reliability and any ML data prep or productionization work.",
      ranking_version: "v1.2",
    },
    review: {
      requires_llm_review: false,
      review_reason: "",
      prompt: "",
      pasted_chatgpt_json: null,
      applied_at: null,
    },
    materials: {
      recruiter_message:
        "Hi — data engineer comfortable working alongside ML teams to productionize pipelines. Excited about your Applied Data Engineer role.",
      cover_letter:
        "I build reliable feature pipelines and enjoy partnering with ML engineers to get models into production...",
      ats_cv_notes: "Highlight feature pipelines and ML collaboration.",
      autofill_notes: "Remote EU. Notice: 1 month.",
    },
  },
]

export const MOCK_IMPORTS: ImportRecord[] = [
  {
    id: "imp_001",
    file_name: "linkedin_export_2025_07_06.xlsx",
    imported_at: daysAgo(0),
    rows_detected: 48,
    inserted: 12,
    updated: 9,
    duplicates: 25,
    errors: 2,
  },
  {
    id: "imp_002",
    file_name: "linkedin_export_2025_07_04.xlsx",
    imported_at: daysAgo(2),
    rows_detected: 40,
    inserted: 18,
    updated: 6,
    duplicates: 16,
    errors: 0,
  },
  {
    id: "imp_003",
    file_name: "ats_greenhouse_2025_07_01.xlsx",
    imported_at: daysAgo(5),
    rows_detected: 22,
    inserted: 14,
    updated: 2,
    duplicates: 5,
    errors: 1,
  },
]
