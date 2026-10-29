"""Etap 15, zadanie 3: decyzja rejestracji (bramka + tagi) na atrapie klienta MLflow."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline_ml.komponenty.zarejestruj import zarejestruj_wersje

N = "ryzyko_szkody"


class BrakModelu(Exception):
    error_code = "RESOURCE_DOES_NOT_EXIST"


class AtrapaKlienta:
    """Tylko te wywolania, ktore dzialaja w Azure ML (zweryfikowane 26.10): zadnych aliasow."""

    def __init__(self):
        self.model: dict | None = None  # tagi modelu, None = nie istnieje
        self.wersje: dict[str, dict] = {}
        self.wywolania: list[str] = []

    def get_registered_model(self, nazwa):
        self.wywolania.append("get_registered_model")
        if self.model is None:
            raise BrakModelu("nie ma")
        return SimpleNamespace(tags=dict(self.model))

    def create_registered_model(self, nazwa):
        self.wywolania.append("create_registered_model")
        self.model = {}

    def get_model_version(self, nazwa, wersja):
        return SimpleNamespace(tags=dict(self.wersje[str(wersja)]))

    def create_model_version(self, nazwa, source, run_id):
        wersja = str(len(self.wersje) + 1)
        self.wersje[wersja] = {}
        return SimpleNamespace(version=wersja)

    def set_model_version_tag(self, nazwa, wersja, klucz, wartosc):
        self.wersje[str(wersja)][klucz] = wartosc

    def set_registered_model_tag(self, nazwa, klucz, wartosc):
        self.model[klucz] = wartosc


def metryki(pr_auc):
    return {"pr_auc": pr_auc, "roc_auc": 0.8, "brier": 0.1, "n_test": 100}


def rejestruj(k, pr_auc, rodzaj="hgb"):
    return zarejestruj_wersje(k, N, "src", "run", metryki(pr_auc), rodzaj)


def test_pierwsza_wersja_zostaje_championem():
    k = AtrapaKlienta()
    wynik = rejestruj(k, 0.5)
    assert wynik["wersja"] == "1" and wynik["promowany"] and wynik["champion_przed"] is None
    assert k.model == {"champion": "1"}
    assert k.wersje["1"]["rola"] == "champion" and k.wersje["1"]["pr_auc"] == "0.500000"
    assert "create_registered_model" in k.wywolania


def test_istniejacy_model_nie_jest_tworzony_drugi_raz():
    k = AtrapaKlienta()
    rejestruj(k, 0.5)
    k.wywolania.clear()
    rejestruj(k, 0.5)
    assert "create_registered_model" not in k.wywolania


def test_slabszy_challenger_odrzucony_champion_bez_zmian():
    k = AtrapaKlienta()
    rejestruj(k, 0.50)
    wynik = rejestruj(k, 0.15, rodzaj="zepsuty")
    assert not wynik["promowany"] and wynik["champion_po"] == "1"
    assert k.model["champion"] == "1"
    assert k.wersje["2"]["rola"] == "odrzucony"
    assert "odrzucony" in k.wersje["2"]["powod"]
    assert k.wersje["1"]["rola"] == "champion"


def test_rowny_i_lepszy_challenger_przejmuje_championa_stary_wycofany():
    k = AtrapaKlienta()
    rejestruj(k, 0.50)
    wynik = rejestruj(k, 0.495)  # w tolerancji 0,01
    assert wynik["promowany"] and k.model["champion"] == "2"
    assert k.wersje["1"]["rola"] == "wycofany" and "2" in k.wersje["1"]["powod"]
    assert k.wersje["2"]["rola"] == "champion"
    # dokladnie jeden champion wg tagow wersji
    assert [v for v, t in k.wersje.items() if t["rola"] == "champion"] == ["2"]


def test_granica_tolerancji_slabszy_o_002_odrzucony():
    k = AtrapaKlienta()
    rejestruj(k, 0.50)
    assert not rejestruj(k, 0.48)["promowany"]


def test_inny_blad_niz_brak_modelu_nie_jest_polykany():
    class Zepsuty(AtrapaKlienta):
        def get_registered_model(self, nazwa):
            raise RuntimeError("403 Forbidden")

    with pytest.raises(RuntimeError, match="403"):
        rejestruj(Zepsuty(), 0.5)
