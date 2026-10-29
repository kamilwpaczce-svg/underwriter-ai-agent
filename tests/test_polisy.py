"""sprawdz_polise: S01-S04 na granicach + braki danych (SPEC_ETAP10.md, sekcja Testy)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent.polisy import (
    SCIEZKA_POLIS,
    normalizuj_nr_polisy,
    sprawdz_polise,
    wczytaj_polisy,
)
from agent.schematy import EkstrakcjaSzkody, OcenaPokrycia, PolaSzkody

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))

import generuj  # noqa: E402
from nip import nip_poprawny  # noqa: E402


@pytest.fixture(scope="module")
def polisy():
    return wczytaj_polisy()


def _pola(**zmiany):
    """Bazowe zgloszenie do P1 (PL/MSP/2026/0001, okres 2026-01-01..2026-12-31, SU budynki 2 000 000)."""
    pola = {
        "nr_polisy": "PL/MSP/2026/0001",
        "data_zdarzenia": "2026-09-03",
        "data_zgloszenia": "2026-09-05",
        "rodzaj_mienia": "budynek",
        "szacowana_kwota": 380000,
    }
    pola.update(zmiany)
    return pola


def test_plik_polis_ma_10_poprawnych_polis():
    lista = json.loads(SCIEZKA_POLIS.read_text(encoding="utf-8"))
    assert len(lista) == 10
    assert len({p["nr_polisy"] for p in lista}) == 10
    for polisa in lista:
        assert nip_poprawny(polisa["nip"])
        assert polisa["okres_od"] < polisa["okres_do"]


def test_normalizuj_nr_polisy():
    assert normalizuj_nr_polisy(" pl/msp/2026/ 0001 ") == "PL/MSP/2026/0001"
    assert normalizuj_nr_polisy(None) is None
    assert normalizuj_nr_polisy("  ") is None


def test_poprawne_zgloszenie_bez_kodow(polisy):
    wynik = sprawdz_polise(_pola(), polisy)
    assert wynik["kody"] == []
    assert wynik["braki"] == []
    assert wynik["suma_ubezpieczenia"] == 2000000
    assert wynik["dni_do_zgloszenia"] == 2
    assert wynik["polisa"]["ubezpieczony"].startswith("Piekarnia")


@pytest.mark.parametrize("nr", ["PL/MSP/2026/0999", None, ""])
def test_brak_polisy_to_S01_i_koniec_sprawdzania(polisy, nr):
    wynik = sprawdz_polise(_pola(nr_polisy=nr), polisy)
    assert wynik["kody"] == ["S01"]
    assert wynik["polisa"] is None
    assert wynik["braki"] == []


def test_numer_polisy_z_malymi_literami_i_spacjami_jest_rozpoznany(polisy):
    assert sprawdz_polise(_pola(nr_polisy="pl/msp/2026/0001 "), polisy)["kody"] == []


@pytest.mark.parametrize(
    ("data", "kody"),
    [
        ("2026-01-01", []),
        ("2026-12-31", []),
        ("2025-12-31", ["S02"]),
        ("2027-01-01", ["S02"]),
    ],
)
def test_granice_okresu_ubezpieczenia_wlacznie(polisy, data, kody):
    wynik = sprawdz_polise(_pola(data_zdarzenia=data, data_zgloszenia=data), polisy)
    assert wynik["kody"] == kody


@pytest.mark.parametrize(("kwota", "kody"), [(2000000, []), (2000001, ["S03"])])
def test_kwota_rowna_SU_jest_ok_wieksza_to_S03(polisy, kwota, kody):
    assert sprawdz_polise(_pola(szacowana_kwota=kwota), polisy)["kody"] == kody


@pytest.mark.parametrize(("data_zgloszenia", "kody"), [("2026-09-10", []), ("2026-09-11", ["S04"])])
def test_termin_zgloszenia_7_dni_granica(polisy, data_zgloszenia, kody):
    wynik = sprawdz_polise(_pola(data_zgloszenia=data_zgloszenia), polisy)
    assert wynik["kody"] == kody


def test_kilka_kodow_naraz(polisy):
    wynik = sprawdz_polise(
        _pola(data_zdarzenia="2027-02-01", data_zgloszenia="2027-03-01", szacowana_kwota=5000000), polisy
    )
    assert wynik["kody"] == ["S02", "S03", "S04"]


def test_brak_daty_zdarzenia_to_brak_nie_S02(polisy):
    wynik = sprawdz_polise(_pola(data_zdarzenia=None), polisy)
    assert "S02" not in wynik["kody"]
    assert "S04" not in wynik["kody"]
    assert wynik["braki"] == ["data_zdarzenia"]
    wynik_zly_format = sprawdz_polise(_pola(data_zdarzenia="3 września 2026"), polisy)
    assert wynik_zly_format["braki"] == ["data_zdarzenia"]
    assert wynik_zly_format["kody"] == []


@pytest.mark.parametrize("rodzaj", [None, "pojazdy", ""])
def test_nieznany_rodzaj_mienia_to_brak(polisy, rodzaj):
    wynik = sprawdz_polise(_pola(rodzaj_mienia=rodzaj, szacowana_kwota=99999999), polisy)
    assert wynik["braki"] == ["rodzaj_mienia"]
    assert wynik["suma_ubezpieczenia"] is None
    assert "S03" not in wynik["kody"]


@pytest.mark.parametrize("kwota", [None, -5, "380 000", True])
def test_niepoprawna_kwota_to_brak(polisy, kwota):
    wynik = sprawdz_polise(_pola(szacowana_kwota=kwota), polisy)
    assert wynik["braki"] == ["szacowana_kwota"]
    assert wynik["kody"] == []


def test_brak_daty_zgloszenia_nie_daje_S04_ani_braku(polisy):
    wynik = sprawdz_polise(_pola(data_zgloszenia=None), polisy)
    assert wynik["kody"] == []
    assert wynik["braki"] == []
    assert wynik["dni_do_zgloszenia"] is None
    assert any("zgloszenia" in linia for linia in wynik["opis"])


def test_brak_pliku_polis_konczy_sie_glosno(tmp_path):
    with pytest.raises(FileNotFoundError):
        wczytaj_polisy(tmp_path / "brak.json")


def test_schematy_szkody_przyjmuja_puste_pola():
    ekstrakcja = EkstrakcjaSzkody(pola=PolaSzkody(), podejrzane_instrukcje=False)
    assert ekstrakcja.pola.model_dump()["rodzaj_mienia"] is None
    ocena = OcenaPokrycia(decyzja="POKRYTA")
    assert ocena.cytaty == [] and ocena.brakujace_dokumenty == [] and ocena.dodatkowe_zapytanie is None


def test_wyczysc_dane_nie_kasuje_polis_ani_szkod(tmp_path, monkeypatch):
    dane = tmp_path / "dane"
    monkeypatch.setattr(generuj, "DANE_DIR", dane)
    monkeypatch.setattr(generuj, "WNIOSKI_DIR", dane / "wnioski")
    monkeypatch.setattr(generuj, "OCZEKIWANE_DIR", dane / "oczekiwane")
    for sciezka in ["polisy.json", "manifest.json", "wnioski/W01.pdf", "szkody/Z01.pdf", "szkody/oczekiwane/Z01.json", "smieci/x.txt"]:
        (dane / sciezka).parent.mkdir(parents=True, exist_ok=True)
        (dane / sciezka).write_text("x", encoding="utf-8")

    generuj.wyczysc_dane()

    assert (dane / "polisy.json").exists()
    assert (dane / "szkody" / "Z01.pdf").exists()
    assert (dane / "szkody" / "oczekiwane" / "Z01.json").exists()
    assert not (dane / "manifest.json").exists()
    assert not (dane / "wnioski" / "W01.pdf").exists()
    assert (dane / "wnioski").is_dir()
    assert not (dane / "smieci").exists()
