import inspect

from joborchestrator.scanning import linkedin
from joborchestrator.scanning.hiring_contacts import extract_hiring_contacts_from_html, normalize_linkedin_profile_url
from joborchestrator.scanning.linkedin import extraer_cantidad_solicitantes, extraer_salario_desde_texto


def test_extraer_cantidad_solicitantes_es_en_variants():
    assert extraer_cantidad_solicitantes("Sé de los primeros 25 solicitantes") == {
        "cantidad_solicitantes": 25,
        "cantidad_solicitantes_raw": None,
    }
    assert extraer_cantidad_solicitantes("More than 100 applicants")["cantidad_solicitantes"] == 100
    assert extraer_cantidad_solicitantes("Under 10 applicants")["cantidad_solicitantes"] == 10
    assert extraer_cantidad_solicitantes("1 applicant")["cantidad_solicitantes"] == 1
    raw = extraer_cantidad_solicitantes("100+ applicants")
    assert raw["cantidad_solicitantes"] is None
    assert raw["cantidad_solicitantes_raw"] == "100+ applicants"


def test_extraer_salario_desde_texto_formats():
    assert extraer_salario_desde_texto("€40,000/año - €55,000/año") == {
        "salary_min": 40000.0,
        "salary_max": 55000.0,
        "salary_currency": "EUR",
    }
    assert extraer_salario_desde_texto("$120K/yr - $150K/yr") == {
        "salary_min": 120000.0,
        "salary_max": 150000.0,
        "salary_currency": "USD",
    }
    assert extraer_salario_desde_texto("40.000 € - 55.000 € al año") == {
        "salary_min": 40000.0,
        "salary_max": 55000.0,
        "salary_currency": "EUR",
    }
    assert extraer_salario_desde_texto("Salary: £90,000") == {
        "salary_min": 90000.0,
        "salary_max": 90000.0,
        "salary_currency": "GBP",
    }
    assert extraer_salario_desde_texto("Competitive compensation") == {
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
    }


def test_resolve_external_apply_url_is_not_called_by_normal_scan_flow():
    for func in [linkedin.procesar_pagina_actual, linkedin.run_linkedin_scrape]:
        source = inspect.getsource(func)
        assert "resolve_external_apply_url" not in source


def test_normalize_linkedin_profile_url_strips_tracking_relative_and_fragments():
    assert normalize_linkedin_profile_url("/in/jane-smith/?miniProfileUrn=x#about") == "https://www.linkedin.com/in/jane-smith/"
    assert normalize_linkedin_profile_url("https://www.linkedin.com/in/jane-smith?trk=jobs") == "https://www.linkedin.com/in/jane-smith/"
    assert normalize_linkedin_profile_url("https://www.linkedin.com/company/acme/") is None


def test_extract_hiring_contacts_from_english_section_only():
    html = """
    <a href="/in/outside/">Outside Person</a>
    <section aria-label="Meet the hiring team">
      <h2>Meet the hiring team</h2>
      <div><a href="/in/jane-smith/?trk=jobs">Jane Smith</a><p>Senior Technical Recruiter</p></div>
      <div><a href="https://www.linkedin.com/in/john-doe/#x">John Doe</a><p>Engineering Manager</p></div>
      <div><a href="https://www.linkedin.com/in/jane-smith/">Jane Smith duplicate</a></div>
      <div><a href="https://www.linkedin.com/company/acme/">Acme</a></div>
    </section>
    """
    result = extract_hiring_contacts_from_html(html)
    assert result.status == "found"
    assert [contact.name for contact in result.contacts] == ["Jane Smith", "John Doe"]
    assert result.contacts[0].headline == "Senior Technical Recruiter"
    assert result.contacts[0].is_primary is True
    assert result.contacts[1].is_primary is False


def test_extract_hiring_contacts_from_spanish_section_without_headline_and_invalid_links():
    html = """
    <section>
      <h2>Conoce al equipo de contratación</h2>
      <div><a href="">Ver perfil</a></div>
      <div><a href="/in/ana-garcia/">Ana Garcia</a></div>
    </section>
    """
    result = extract_hiring_contacts_from_html(html)
    assert result.status == "found"
    assert len(result.contacts) == 1
    assert result.contacts[0].headline is None
    assert result.contacts[0].source == "linkedin_hiring_team"


def test_extract_hiring_contacts_not_present_returns_empty_result():
    result = extract_hiring_contacts_from_html('<section><a href="/in/jane/">Jane</a></section>')
    assert result.status == "not_present"
    assert result.contacts == []
