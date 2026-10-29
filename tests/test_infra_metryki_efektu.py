"""19c zad. 3: Terraform dla metryk efektu (workbook + alert odejsc). Wzorzec jak
tests/test_infra_monitoring.py - tekst plikow, bez parsera HCL. Prawdziwa weryfikacja to
`terraform validate` i `terraform plan` (patrz SPEC_ETAP19.md, zad. 3)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TF_DIR = ROOT / "infra" / "terraform"
TF = (TF_DIR / "metryki_efektu.tf").read_text(encoding="utf-8")
SZABLON = (TF_DIR / "metryki_efektu_workbook.json.tftpl").read_text(encoding="utf-8")
KQL = (ROOT / "obserwowalnosc" / "metryki_efektu.kql").read_text(encoding="utf-8")
WSZYSTKIE_TF = "\n".join(p.read_text(encoding="utf-8") for p in TF_DIR.glob("*.tf"))


def test_nie_tworzy_nowej_action_group_i_uzywa_istniejacej():
    assert 'resource "azurerm_monitor_action_group"' not in TF
    assert WSZYSTKIE_TF.count('resource "azurerm_monitor_action_group"') == 1  # tylko main.tf
    assert "azurerm_monitor_action_group.uw.id" in TF


def test_alert_odejsc_liczy_wiersze_a_zapytanie_filtruje_po_summarize():
    """Lekcja Etapu 13: Count po summarize zawsze >= 1, wiec warunek musi siedziec w `where`
    PO summarize, a regula ma byc Count > 0."""
    assert re.search(r'time_aggregation_method\s*=\s*"Count"', TF)
    assert re.search(r'operator\s*=\s*"GreaterThan"', TF)
    assert re.search(r"threshold\s*=\s*0\b", TF)
    assert "metric_measure_column" not in TF  # niedozwolone przy Count
    sekcja6 = KQL[KQL.index("// === 6.") :]
    kod = [l for l in sekcja6.splitlines() if l.strip() and not l.strip().startswith("//")]
    ostatnia = kod[-1]
    assert ostatnia.startswith("| where") and "decyzje >= min_decyzji" in ostatnia
    assert any(l.startswith("| summarize") for l in kod)
    assert kod.index(ostatnia) > max(i for i, l in enumerate(kod) if l.startswith("| summarize"))


def test_alert_i_workbook_czytaja_zapytania_z_pliku_kql():
    assert "metryki_efektu.kql" in TF
    assert 'split("// === ", local.kql_metryk)' in TF
    # literal podmieniany na parametr workbooka musi istniec w .kql (inaczej replace() nic nie zrobi)
    assert 'dynamic(["uw-api", "uw-zasiew"])' in KQL
    assert "dynamic([{Rola}])" in TF


def test_workbook_ma_guid_parametr_roli_i_jsonencode_zapytan():
    assert "uuidv5(" in TF
    assert "azurerm_application_insights_workbook" in TF
    assert "templatefile(" in TF
    assert '"name": "Rola"' in SZABLON
    assert "jsonencode(zapytanie)" in SZABLON
    assert "{Rola}" not in SZABLON  # parametr jest wstawiany w zapytaniach, nie w szablonie


def test_workbook_i_alert_nie_dotykaja_istniejacych_zasobow():
    zasoby = re.findall(r'^resource "(\w+)" "(\w+)"', TF, flags=re.MULTILINE)
    assert zasoby == [
        ("azurerm_application_insights_workbook", "metryki_efektu"),
        ("azurerm_monitor_scheduled_query_rules_alert_v2", "odejscia"),
    ]
