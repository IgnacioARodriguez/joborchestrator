import inspect

from joborchestrator.scanning import linkedin
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
