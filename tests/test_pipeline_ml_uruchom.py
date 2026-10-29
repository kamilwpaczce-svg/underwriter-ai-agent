"""Etap 15, zadanie 3: pomocnicze funkcje `pipeline_ml/uruchom.py` bez SDK Azure ML (offline)."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from pipeline_ml import uruchom


def test_kod_komponentow_zawiera_kroki_i_pakiet_ryzyko_bez_cache(tmp_path):
    kod = uruchom.przygotuj_kod(tmp_path)
    for krok in uruchom.KROKI:
        assert (kod / f"{krok}.py").is_file()
    assert (kod / "ryzyko" / "bramka.py").is_file()
    assert not list(kod.rglob("__pycache__"))
    # skrypty krokow sa w korzeniu `code=`, wiec `python przygotuj.py` widzi `ryzyko` z tego samego katalogu
    assert not (kod / "pipeline_ml").exists()


def test_wersja_srodowiska_to_stabilny_skrot_pliku_conda():
    wersja = uruchom.wersja_srodowiska()
    assert re.fullmatch(r"[0-9a-f]{8}", wersja)
    assert wersja == uruchom.wersja_srodowiska()


def test_srodowisko_przypina_wersje_jak_w_api():
    tresc = uruchom.PLIK_SRODOWISKA.read_text(encoding="utf-8")
    for pakiet in ("scikit-learn==1.9.1", "skops==0.16.0", "mlflow==3.15.0", "azureml-mlflow==1.62.0.post6"):
        assert pakiet in tresc


def test_rodzaje_w_uruchom_pokrywaja_sie_z_komponentem_trenuj():
    from pipeline_ml.komponenty.trenuj import RODZAJE

    assert uruchom.RODZAJE == RODZAJE


def test_skrypty_kroku_dzialaja_jako_skrypty_z_katalogu_code(tmp_path):
    """To, co robi Azure ML: `python przygotuj.py` w katalogu z `ryzyko/` obok (bez PYTHONPATH)."""
    (tmp_path / "kod").mkdir()
    kod = uruchom.przygotuj_kod(tmp_path / "kod")
    wynik = subprocess.run(
        [sys.executable, "-X", "utf8", "przygotuj.py", "--n", "500", "--dane", str(tmp_path / "dane")],
        cwd=kod,
        capture_output=True,
        text=True,
    )
    assert wynik.returncode == 0, wynik.stderr
    assert (tmp_path / "dane" / "train.csv").is_file() and (tmp_path / "dane" / "referencja.json").is_file()


@pytest.mark.azure
def test_azure_rejestr_ma_championa_z_rola_champion():
    """Na zywo (po biegu pipeline'u): tag modelu `champion` wskazuje wersje z `rola=champion`."""
    pytest.importorskip("mlflow")
    import os

    from mlflow import MlflowClient

    if not os.environ.get("MLFLOW_TRACKING_URI", "").startswith("azureml:"):
        pytest.skip("MLFLOW_TRACKING_URI nie wskazuje workspace'u Azure ML")
    k = MlflowClient()
    champion = k.get_registered_model("ryzyko_szkody").tags["champion"]
    assert k.get_model_version("ryzyko_szkody", champion).tags["rola"] == "champion"


def test_podsumowanie_odrzucenia_mowi_ze_champion_bez_zmian():
    tekst = uruchom.podsumowanie_md(
        "job1",
        "zepsuty",
        "Completed",
        {"wersja": "7", "promowany": False, "powod": "pr_auc za niskie", "champion_przed": "5", "champion_po": "5"},
    )
    assert "ODRZUCONY (champion bez zmian)" in tekst
    assert "`5` -> `5`" in tekst


def test_podsumowanie_promocji_i_braku_wyniku():
    tekst = uruchom.podsumowanie_md(
        "job2", "hgb", "Completed", {"wersja": "8", "promowany": True, "powod": "lepszy", "champion_przed": "5", "champion_po": "8"}
    )
    assert "PROMOWANY na championa" in tekst
    assert "brak wyniku" in uruchom.podsumowanie_md("job3", "hgb", "Failed", None)
