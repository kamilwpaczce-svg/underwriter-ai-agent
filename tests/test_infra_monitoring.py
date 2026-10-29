"""Monitoring Etapu 13: Terraform (App Insights, action group, alert) + Bicep
(sekret i env App Insights w uw-api). Wzorzec jak w tests/test_infra_szkody.py -
czytanie plikow jako tekst, bez parsera Bicep/HCL."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERRAFORM_DIR = ROOT / "infra" / "terraform"
MAIN_TF = (TERRAFORM_DIR / "main.tf").read_text(encoding="utf-8")
VERSIONS_TF = (TERRAFORM_DIR / "versions.tf").read_text(encoding="utf-8")
GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")
BICEP = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
BICEPPARAM = (ROOT / "infra" / "main.bicepparam").read_text(encoding="utf-8")


def _env_kontenera(nazwa: str) -> str:
    """Tekst tablicy `env: [...]` (lub `env: concat([...])`) kontenera o podanej nazwie
    (ten sam wzorzec co tests/test_infra_szkody.py - bez parsera Bicep)."""
    poczatek = BICEP.index(f"name: '{nazwa}'")
    env = BICEP.index("env: ", poczatek)
    if BICEP.startswith("env: concat([", env):
        koniec = BICEP.index("\n          )", env)
    else:
        koniec = BICEP.index("\n          ]", env)
    return BICEP[env:koniec]


def _sekcja_param(nazwa: str) -> str:
    """Kilka linii bezposrednio przed deklaracja `param {nazwa}` w main.bicep -
    do sprawdzenia dekoratora @secure() tuz nad parametrem."""
    poczatek = BICEP.index(f"param {nazwa} ")
    return BICEP[max(0, poczatek - 200) : poczatek]


def test_main_tf_app_insights_na_istniejacym_log_analytics():
    assert "azurerm_application_insights" in MAIN_TF
    assert "workspace_id" in MAIN_TF
    assert "azurerm_log_analytics_workspace" in MAIN_TF  # data, nie tworzony od nowa


def test_main_tf_alert_filtruje_obie_rodziny_spanow_i_sukces_false():
    assert 'startswith "wniosek."' in MAIN_TF
    assert 'startswith "llm."' in MAIN_TF
    assert "Success == false" in MAIN_TF


def test_main_tf_alert_scope_to_workspace_log_analytics_nie_app_insights():
    """Zapytanie uzywa tabel workspace'u (AppRequests/AppDependencies); regula przypieta do
    zasobu App Insights obowiazywalaby w starym schemacie (requests/dependencies) i nie
    zadzialalaby (przeglad koncowy Etapu 13, poprawka 1)."""
    m = re.search(r"^\s*scopes\s*=\s*\[(.*?)\]", MAIN_TF, re.MULTILINE)
    assert m, "brak linii scopes w main.tf"
    assert m.group(1).strip() == "data.azurerm_log_analytics_workspace.uw.id"
    assert "azurerm_application_insights" not in m.group(1)


def test_main_tf_alert_criteria_i_czestotliwosc_z_briefu():
    # Regex zakotwiczony po polu, nie po literalnym wyrownaniu - odporny na to, jak
    # `terraform fmt` wyrownuje spacje przed `=` w bloku (zalezy od dlugosci innych
    # nazw pol w tym samym bloku, wiec sztywny string latwo siada przy drobnej zmianie).
    wzorce = {
        r'evaluation_frequency\s*=\s*"PT5M"': "evaluation_frequency",
        r'window_duration\s*=\s*"PT15M"': "window_duration",
        r"severity\s*=\s*2\b": "severity",
        # Patrz komentarz w main.tf: zapytanie bez "by" zawsze zwraca 1 wiersz
        # (kolumna `bledy`) - "Total" + metric_measure_column mierzy WARTOSC kolumny,
        # "Count" mierzylby liczbe wierszy (zawsze 1 -> alert stale aktywny).
        r'time_aggregation_method\s*=\s*"Total"': "time_aggregation_method",
        r'metric_measure_column\s*=\s*"bledy"': "metric_measure_column",
        r"threshold\s*=\s*1\b": "threshold",
    }
    for wzorzec, nazwa in wzorce.items():
        assert re.search(wzorzec, MAIN_TF), f"brak pola {nazwa} w main.tf (wzorzec: {wzorzec})"
    # "Count" nie moze zostac uzyty razem z metric_measure_column (provider by to odrzucil).
    assert 'time_aggregation_method = "Count"' not in MAIN_TF


def test_main_tf_alert_auto_mitigation_i_akcja():
    assert re.search(r"auto_mitigation_enabled\s*=\s*true", MAIN_TF)
    assert "azurerm_monitor_action_group" in MAIN_TF
    assert "email_receiver" in MAIN_TF


def test_versions_tf_backend_bez_sekretow_w_repo():
    assert "storage_account_name =" not in VERSIONS_TF
    assert "access_key" not in VERSIONS_TF
    assert "use_azuread_auth" in VERSIONS_TF


def test_gitignore_ignoruje_stan_terraform():
    assert ".terraform/" in GITIGNORE
    assert "*.tfstate" in GITIGNORE
    assert "*.tfvars" in GITIGNORE


def test_lock_file_nie_jest_ignorowany():
    # .terraform.lock.hcl (pin providera) MUSI byc commitowany - patrz task-5-brief.md.
    # Sprawdzamy wzorce (linie bez komentarzy), nie cala tresc pliku - nazwa pliku
    # moze legalnie pojawic sie w komentarzu wyjasniajacym wyjatek.
    wzorce = [linia.strip() for linia in GITIGNORE.splitlines() if linia.strip() and not linia.strip().startswith("#")]
    assert ".terraform.lock.hcl" not in wzorce


def test_email_alertow_bez_wartosci_domyslnej():
    variables_tf = (TERRAFORM_DIR / "variables.tf").read_text(encoding="utf-8")
    poczatek = variables_tf.index('variable "email_alertow"')
    koniec = variables_tf.index("\n}", poczatek)
    blok = variables_tf[poczatek:koniec]
    assert "default" not in blok
    assert "@" not in blok  # zaden adres e-mail wpisany na stale


# Zadanie 6 - Bicep: sekret i env App Insights w uw-api (bez tworzenia zasobow -
# te powstaja w Terraform, Zadanie 5; main.bicep tylko je podlacza do uw-api).


def test_bicep_appinsights_param_jest_secure_i_wymagany():
    # Runda poprawek 1/5: parametr jest WYMAGANY (bez wartosci domyslnej) - jak
    # hasloPostgres, brak wartosci ma wywrocic build glosno, nie cicho skasowac
    # sekret/env App Insights przy ponownym `deployment group create`.
    assert "param appInsightsConnectionString string\n" in BICEP
    assert "param appInsightsConnectionString string = ''" not in BICEP
    assert "@secure()" in _sekcja_param("appInsightsConnectionString")


def test_bicep_appinsights_secret_zawsze_obecny_bez_warunku():
    # Skoro appInsightsConnectionString jest wymagany, sekret/env istnieja zawsze -
    # bez `empty(...) ? [] : [...]` (ten warunek zostal usuniety w rundzie poprawek 1/5).
    assert "name: 'appinsights-cs'" in BICEP
    assert "empty(appInsightsConnectionString)" not in BICEP
    assert "env: concat(" not in BICEP
    assert "secrets: concat(" not in BICEP


def test_bicep_uw_api_env_ma_connection_string_i_otel_zmienne():
    env = _env_kontenera("uw-api")
    assert "{ name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-cs' }" in env
    assert "{ name: 'OTEL_SERVICE_NAME', value: 'uw-api' }" in env
    assert "{ name: 'OTEL_PYTHON_FASTAPI_EXCLUDED_URLS', value: 'zdrowie' }" in env


def test_bicep_uw_web_env_bez_telemetrii():
    # Tylko uw-api rozmawia z Application Insights - uw-web nie dostaje tych zmiennych.
    env = _env_kontenera("uw-web")
    assert "APPLICATIONINSIGHTS_CONNECTION_STRING" not in env
    assert "OTEL_SERVICE_NAME" not in env


def test_bicepparam_appinsights_bez_literalnej_wartosci_i_bez_pustego_defaultu():
    # Jak hasloPostgres - czytane ze zmiennej srodowiskowej, nigdy zapisane na stale,
    # i BEZ drugiego argumentu (pustego defaultu) - brak zmiennej ma wywrocic build.
    assert (
        "param appInsightsConnectionString = readEnvironmentVariable('APPINSIGHTS_CONNECTION_STRING_ETAP13')"
        in BICEPPARAM
    )
    assert "InstrumentationKey=" not in BICEPPARAM
