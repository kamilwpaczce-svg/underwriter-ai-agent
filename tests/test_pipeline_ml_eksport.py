"""Etap 15, zadanie 4a: eksport championa do Blob na atrapie magazynu (offline)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.magazyn import MagazynPamieciowy
from pipeline_ml.eksportuj_championa import eksportuj, sprawdz_z_bloba
from pipeline_ml.komponenty.przygotuj import przygotuj_dane
from pipeline_ml.komponenty.trenuj import trenuj_model
from ryzyko.cechy import CECHY
from ryzyko.serwowanie import KONTENER_DOMYSLNY, PREFIKS_DOMYSLNY, ModelRyzyka


class AtrapaKlienta:
    def __init__(self, tagi):
        self._tagi = tagi

    def get_registered_model(self, nazwa):
        return SimpleNamespace(tags=self._tagi)


@pytest.fixture(scope="module")
def zbior():
    train, test, ref = przygotuj_dane(2000, 0)
    return trenuj_model(train, "hgb", 0), test, ref


@pytest.fixture
def katalog_wersji(tmp_path, zbior):
    _, _, ref = zbior
    (tmp_path / "referencja.json").write_text(json.dumps(ref), encoding="utf-8")
    (tmp_path / "metryki.json").write_text(
        json.dumps({"pr_auc": 0.44, "roc_auc": 0.78, "brier": 0.10, "n_test": 600}), encoding="utf-8"
    )
    return tmp_path


def test_eksport_zapisuje_trzy_pliki_i_z_bloba_daje_ten_sam_wynik(zbior, katalog_wersji):
    model, test, _ = zbior
    magazyn = MagazynPamieciowy()
    pobrane = []

    def pobierz(nazwa, wersja):
        pobrane.append((nazwa, wersja))
        return katalog_wersji

    wynik = eksportuj(AtrapaKlienta({"champion": "3"}), magazyn, pobierz, lambda _: model)
    assert pobrane == [("ryzyko_szkody", "3")]  # wersja z tagu modelu, nie "ostatnia"
    assert wynik["wersja"] == "3"
    for plik in ("champion.skops", "referencja.json", "metadane.json"):
        assert magazyn.pobierz_z_kontenera(KONTENER_DOMYSLNY, PREFIKS_DOMYSLNY + plik)
    metadane = json.loads(magazyn.pobierz_z_kontenera(KONTENER_DOMYSLNY, PREFIKS_DOMYSLNY + "metadane.json"))
    assert metadane["wersja"] == "3" and metadane["metryki"]["pr_auc"] == 0.44 and metadane["data"]

    zaladowany = ModelRyzyka.z_bloba(magazyn)
    assert zaladowany is not None and zaladowany.wersja == "3"
    for i in range(5):
        wiersz = test.iloc[i]
        cechy = {c: (wiersz[c].item() if hasattr(wiersz[c], "item") else wiersz[c]) for c in CECHY}
        przed = round(float(model.predict_proba(test[CECHY].iloc[[i]])[0, 1]), 3)
        assert zaladowany.ocen(cechy)["wynik"] == przed


def test_sprawdz_z_bloba_ocenia_probke(zbior, katalog_wersji):
    model, _, _ = zbior
    magazyn = MagazynPamieciowy()
    eksportuj(AtrapaKlienta({"champion": "1"}), magazyn, lambda n, w: katalog_wersji, lambda _: model)
    wynik = sprawdz_z_bloba(magazyn, KONTENER_DOMYSLNY, PREFIKS_DOMYSLNY)
    assert wynik["wersja"] == "1" and 0.0 <= wynik["ocena"]["wynik"] <= 1.0


def test_brak_championa_nic_nie_zapisuje(zbior, katalog_wersji):
    model, _, _ = zbior
    magazyn = MagazynPamieciowy()
    with pytest.raises(RuntimeError, match="champion"):
        eksportuj(AtrapaKlienta({}), magazyn, lambda n, w: katalog_wersji, lambda _: model)
    assert magazyn._inne_kontenery == {}


def test_brak_referencji_w_wersji_nic_nie_zapisuje(zbior, tmp_path):
    model, _, _ = zbior
    magazyn = MagazynPamieciowy()
    with pytest.raises(FileNotFoundError):
        eksportuj(AtrapaKlienta({"champion": "1"}), magazyn, lambda n, w: tmp_path, lambda _: model)
    assert magazyn._inne_kontenery == {}


def test_metadane_zapisywane_jako_ostatnie(zbior, katalog_wersji):
    model, _, _ = zbior

    class Sledzacy(MagazynPamieciowy):
        def __init__(self):
            super().__init__()
            self.kolejnosc = []

        def zapisz_w_kontenerze(self, kontener, nazwa_bloba, dane):
            self.kolejnosc.append(nazwa_bloba.rsplit("/", 1)[-1])
            super().zapisz_w_kontenerze(kontener, nazwa_bloba, dane)

    magazyn = Sledzacy()
    eksportuj(AtrapaKlienta({"champion": "1"}), magazyn, lambda n, w: katalog_wersji, lambda _: model)
    assert magazyn.kolejnosc[-1] == "metadane.json"
