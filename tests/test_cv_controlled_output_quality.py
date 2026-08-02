from joborchestrator.intelligence.materials_cv_ir import parse_candidate_cv_ir, render_ats_cv


BASE_CV = """Ignacio Rodriguez
MÃ¡laga, Spain | ignacio@example.com

Professional Experience
Backend Developer | Fiction Express MÃ¡laga, Spain | April 2025 - March 2026
- Developed backend workflows to transform user activity events into engagement, progress, and product usage
  metrics.
- Built reliable APIs.
- Technologies: Python, Django, REST APIs

Full Stack Developer | Talan Consulting Client: Cepsa Â· MÃ¡laga, Spain | October 2022 - April 2025
- Built and maintained dashboards for finance teams, enabling visualization of business, operational, and market
  metrics.
Technologies: Python, Flask, SQL

Backend Developer | Globant Client: Tigo LATAM Â· Buenos Aires, Argentina | August 2022 - October 2022
- Worked in AWS cloud environments.
Technologies: Python, AWS

Full Stack Developer | Balloon Group Buenos Aires, Argentina | November 2021 - August 2022
- Developed web applications.
Technologies: Python, PHP

Education
Programming Technician
"""


def test_wrapped_bullet_lines_are_joined() -> None:
    cv_ir = parse_candidate_cv_ir(BASE_CV, ["Python", "REST APIs", "AWS"])

    assert cv_ir.roles[0].bullets[0].source_text.endswith("product usage metrics.")
    assert cv_ir.roles[1].bullets[0].source_text.endswith("operational, and market metrics.")


def test_technology_line_is_not_a_bullet_and_renders_once() -> None:
    cv_ir = parse_candidate_cv_ir(BASE_CV, ["Python", "REST APIs", "AWS"])
    rendered = render_ats_cv(cv_ir)

    assert all(not bullet.source_text.casefold().startswith("technologies:") for role in cv_ir.roles for bullet in role.bullets)
    assert rendered.count("Technologies: Python, Django, REST APIs") == 1
    assert "- Technologies:" not in rendered


def test_company_and_location_are_separated() -> None:
    cv_ir = parse_candidate_cv_ir(BASE_CV, ["Python", "REST APIs", "AWS"])

    assert (cv_ir.roles[0].company, cv_ir.roles[0].location) == ("Fiction Express", "MÃ¡laga, Spain")
    assert (cv_ir.roles[1].company, cv_ir.roles[1].location) == ("Talan Consulting Client: Cepsa", "MÃ¡laga, Spain")
    assert (cv_ir.roles[2].company, cv_ir.roles[2].location) == ("Globant Client: Tigo LATAM", "Buenos Aires, Argentina")
    assert (cv_ir.roles[3].company, cv_ir.roles[3].location) == ("Balloon Group", "Buenos Aires, Argentina")


def test_rendered_headers_keep_company_location_and_dates_distinct() -> None:
    rendered = render_ats_cv(parse_candidate_cv_ir(BASE_CV, ["Python", "REST APIs", "AWS"]))

    assert "Backend Developer | Fiction Express | MÃ¡laga, Spain | April 2025 - March 2026" in rendered
    assert "Full Stack Developer | Balloon Group | Buenos Aires, Argentina | November 2021 - August 2022" in rendered
