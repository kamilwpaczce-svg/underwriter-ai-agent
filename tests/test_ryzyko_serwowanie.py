"""Etap 15: serwowanie modelu ryzyka - zapis/odczyt skops, z_bloba, glowne cechy."""

from __future__ import annotations

import logging

import pytest
from skops.io import dumps

from api.magazyn import MagazynBlob, MagazynPamieciowy
from ryzyko.cechy import CECHY
from ryzyko.generator import generuj_zbior
from ryzyko.model import zbuduj_pipeline
from ryzyko.psi import referencja
from ryzyko.serwowanie import (
    PLIK_METADANYCH,
    PLIK_MODELU,
    PLIK_REFERENCJI,
    PREFIKS_DOMYSLNY,
    ModelRyzyka,
    zapisz_do_katalogu,
)

RYZYKOWNE = {
    "suma_ubezpieczenia": 1_000_000.0,
    "udzial_kwoty": 1.2,
    "dni_do_zgloszenia": 40,
    "dni_od_poczatku_polisy": 5,
    "rodzaj_mienia": "zapasy",
    "liczba_zalacznikow": 0,
    "szkody_3_lata": 4,
}


@pytest.fixture(scope="module")
def zbior():
    return generuj_zbior(3000, seed=7)


@pytest.fixture(scope="module")
def model(zbior):
    m = zbuduj_pipeline("hgb")
    m.fit(zbior[CECHY], zbior["do_weryfikacji"])
    return m


@pytest.fixture(scope="module")
def ref(zbior):
    return referencja(zbior)


@pytest.fixture
def katalog(tmp_path, model, ref):
    zapisz_do_katalogu(model, "v3", ref, tmp_path, metryki={"pr_auc": 0.5})
    return tmp_path


def _wgraj(magazyn: MagazynPamieciowy, katalog, kontener="modele", prefiks=PREFIKS_DOMYSLNY):
    for nazwa in (PLIK_MODELU, PLIK_REFERENCJI, PLIK_METADANYCH):
        magazyn.zapisz_w_kontenerze(kontener, prefiks + nazwa, (katalog / nazwa).read_bytes())


def test_zapis_tworzy_trzy_pliki_i_metadane(katalog):
    import json

    assert sorted(p.name for p in katalog.iterdir()) == sorted([PLIK_MODELU, PLIK_REFERENCJI, PLIK_METADANYCH])
    meta = json.loads((katalog / PLIK_METADANYCH).read_text(encoding="utf-8"))
    assert meta["wersja"] == "v3" and meta["metryki"] == {"pr_auc": 0.5} and meta["data"]


def test_zapis_odczyt_daje_identyczne_predykcje(katalog, model, zbior):
    odczytany = ModelRyzyka.z_katalogu(katalog)
    assert odczytany.wersja == "v3"
    X = zbior[CECHY].iloc[:200]
    assert (odczytany.model.predict_proba(X) == model.predict_proba(X)).all()


def test_z_bloba_wynik_rowny_wynikowi_modelu_przed_eksportem(katalog, model, ref):
    magazyn = MagazynPamieciowy()
    _wgraj(magazyn, katalog)
    z_bloba = ModelRyzyka.z_bloba(magazyn)
    przed = ModelRyzyka(model, "v3", ModelRyzyka.z_katalogu(katalog).mediany)
    assert z_bloba is not None and z_bloba.wersja == "v3"
    assert z_bloba.ocen(RYZYKOWNE) == przed.ocen(RYZYKOWNE)


def test_z_bloba_kontener_z_env(katalog, monkeypatch):
    magazyn = MagazynPamieciowy()
    _wgraj(magazyn, katalog, kontener="inny")
    assert ModelRyzyka.z_bloba(magazyn) is None
    monkeypatch.setenv("KONTENER_MODELI", "inny")
    assert ModelRyzyka.z_bloba(magazyn) is not None


def test_z_bloba_brak_plikow_zwraca_none_i_loguje(caplog):
    with caplog.at_level(logging.WARNING):
        assert ModelRyzyka.z_bloba(MagazynPamieciowy()) is None
    assert any("Model ryzyka niedostepny" in r.message and "FileNotFoundError" in r.message for r in caplog.records)


def test_z_bloba_uszkodzony_plik_zwraca_none_bez_tresci_w_logu(katalog, caplog):
    magazyn = MagazynPamieciowy()
    _wgraj(magazyn, katalog)
    magazyn.zapisz_w_kontenerze("modele", PREFIKS_DOMYSLNY + PLIK_MODELU, b"to nie jest skops TAJNA_TRESC")
    with caplog.at_level(logging.WARNING):
        assert ModelRyzyka.z_bloba(magazyn) is None
    assert caplog.records and not any("TAJNA_TRESC" in r.getMessage() for r in caplog.records)


class _ObcyTyp:
    """Typ spoza ZAUFANE_TYPY - skops ma odmowic zaladowania."""

    def predict_proba(self, X):  # nawet z predict_proba nie moze przejsc
        raise AssertionError("nie powinno sie wykonac")


def test_z_bloba_nieznany_typ_zwraca_none(katalog, caplog):
    magazyn = MagazynPamieciowy()
    _wgraj(magazyn, katalog)
    magazyn.zapisz_w_kontenerze("modele", PREFIKS_DOMYSLNY + PLIK_MODELU, dumps(_ObcyTyp()))
    with caplog.at_level(logging.WARNING):
        assert ModelRyzyka.z_bloba(magazyn) is None
    assert any("UntrustedTypesFoundException" in r.message for r in caplog.records)


def test_z_bloba_metadane_bez_wersji_zwraca_none(katalog):
    magazyn = MagazynPamieciowy()
    _wgraj(magazyn, katalog)
    magazyn.zapisz_w_kontenerze("modele", PREFIKS_DOMYSLNY + PLIK_METADANYCH, b"{}")
    assert ModelRyzyka.z_bloba(magazyn) is None


def test_z_bloba_magazyn_bez_metody_zwraca_none():
    class Stary:
        pass

    assert ModelRyzyka.z_bloba(Stary()) is None


def test_ocen_ksztalt_wyniku_i_zaokraglenie(katalog):
    wynik = ModelRyzyka.z_katalogu(katalog).ocen(RYZYKOWNE)
    assert set(wynik) == {"wynik", "glowne_cechy"}
    assert wynik["wynik"] == round(wynik["wynik"], 3) and 0.0 <= wynik["wynik"] <= 1.0
    assert 2 <= len(wynik["glowne_cechy"]) <= 3
    assert set(wynik["glowne_cechy"]) <= set(CECHY) - {"rodzaj_mienia"}


def test_ocen_deterministyczne_i_ryzykowne_wyzej_niz_spokojne(katalog):
    m = ModelRyzyka.z_katalogu(katalog)
    spokojne = {**RYZYKOWNE, "udzial_kwoty": 0.05, "dni_do_zgloszenia": 1, "dni_od_poczatku_polisy": 300,
                "liczba_zalacznikow": 5, "szkody_3_lata": 0}
    assert m.ocen(RYZYKOWNE) == m.ocen(RYZYKOWNE)
    assert m.ocen(RYZYKOWNE)["wynik"] > m.ocen(spokojne)["wynik"]
    assert m.ocen(RYZYKOWNE)["glowne_cechy"]


def test_ocen_brak_cechy_rzuca_keyerror(katalog):
    zle = dict(RYZYKOWNE)
    del zle["szkody_3_lata"]
    with pytest.raises(KeyError):
        ModelRyzyka.z_katalogu(katalog).ocen(zle)


def test_glowne_cechy_wskazuja_cechy_ktore_podbijaja_wynik(katalog):
    m = ModelRyzyka.z_katalogu(katalog)
    # tylko udzial_kwoty ponad mediana -> to ona musi byc wskazana
    tylko_kwota = {**RYZYKOWNE, "udzial_kwoty": 1.4, "dni_do_zgloszenia": 0, "dni_od_poczatku_polisy": 300,
                   "liczba_zalacznikow": 5, "szkody_3_lata": 0}
    assert m.ocen(tylko_kwota)["glowne_cechy"][0] == "udzial_kwoty"


def test_referencja_ma_mediane_liczbowych(ref):
    assert all("mediana" in ref[c] for c in CECHY if c != "rodzaj_mienia")
    assert "mediana" not in ref["rodzaj_mienia"]


def test_magazyn_blob_pobierz_z_kontenera_uzywa_wskazanego_kontenera():
    zapytania = []

    class Pobranie:
        def readall(self):
            return b"dane"

    class Klient:
        def download_blob(self):
            return Pobranie()

    class Serwis:
        def get_blob_client(self, kontener, nazwa):
            zapytania.append((kontener, nazwa))
            return Klient()

    magazyn = MagazynBlob("wnioski", connection_string="UseDevelopmentStorage=true")
    magazyn._serwis = Serwis()
    assert magazyn.pobierz_z_kontenera("modele", "ryzyko_szkody/champion.skops") == b"dane"
    assert zapytania == [("modele", "ryzyko_szkody/champion.skops")]


def test_magazyn_pamieciowy_pobierz_z_kontenera_brak_rzuca():
    with pytest.raises(FileNotFoundError):
        MagazynPamieciowy().pobierz_z_kontenera("modele", "x")
