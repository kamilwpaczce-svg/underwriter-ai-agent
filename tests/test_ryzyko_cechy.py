"""Etap 15: cechy modelu ryzyka szkody - jedno zrodlo prawdy `cechy_ze_stanu`."""

from __future__ import annotations

import copy
import json

import pytest

from agent.polisy import SCIEZKA_POLIS, sprawdz_polise, wczytaj_polisy
from ryzyko.cechy import CECHY, cechy_ze_stanu


@pytest.fixture(scope="module")
def polisy():
    return wczytaj_polisy()


def _stan(polisy, **zmiany_pol):
    pola = {
        "nr_polisy": "PL/MSP/2026/0001",
        "data_zdarzenia": "2026-03-11",
        "data_zgloszenia": "2026-03-14",
        "rodzaj_mienia": "maszyny",
        "szacowana_kwota": 100000,
        "zalaczniki": ["protokol.pdf", "zdjecia.zip"],
    }
    pola.update(zmiany_pol)
    return {"pola": pola, "wynik_polisy": sprawdz_polise(pola, polisy)}


def test_polisy_maja_szkody_3_lata_0_do_4():
    lista = json.loads(SCIEZKA_POLIS.read_text(encoding="utf-8"))
    assert len(lista) == 10
    for polisa in lista:
        assert isinstance(polisa["szkody_3_lata"], int)
        assert not isinstance(polisa["szkody_3_lata"], bool)
        assert 0 <= polisa["szkody_3_lata"] <= 4


def test_kolejnosc_cech_jest_stala():
    assert CECHY == [
        "suma_ubezpieczenia",
        "udzial_kwoty",
        "dni_do_zgloszenia",
        "dni_od_poczatku_polisy",
        "rodzaj_mienia",
        "liczba_zalacznikow",
        "szkody_3_lata",
    ]


def test_pelny_stan_daje_7_cech(polisy):
    cechy = cechy_ze_stanu(_stan(polisy))
    assert list(cechy) == CECHY
    assert cechy["suma_ubezpieczenia"] == 400000
    assert cechy["udzial_kwoty"] == pytest.approx(0.25)
    assert cechy["dni_do_zgloszenia"] == 3
    assert cechy["dni_od_poczatku_polisy"] == 69
    assert cechy["rodzaj_mienia"] == "maszyny"
    assert cechy["liczba_zalacznikow"] == 2
    assert cechy["szkody_3_lata"] == polisy["PL/MSP/2026/0001"]["szkody_3_lata"]


def test_brak_polisy_daje_none(polisy):
    assert cechy_ze_stanu(_stan(polisy, nr_polisy="PL/MSP/2026/9999")) is None


def test_pusty_stan_daje_none():
    assert cechy_ze_stanu({}) is None
    assert cechy_ze_stanu({"pola": None, "wynik_polisy": None}) is None


@pytest.mark.parametrize("pole", ["szacowana_kwota", "data_zgloszenia", "data_zdarzenia", "rodzaj_mienia", "zalaczniki"])
def test_brak_wartosci_daje_none_a_nie_zero(polisy, pole):
    assert cechy_ze_stanu(_stan(polisy, **{pole: None})) is None


def test_zero_zalacznikow_to_wartosc_a_nie_brak(polisy):
    assert cechy_ze_stanu(_stan(polisy, zalaczniki=[]))["liczba_zalacznikow"] == 0


def test_su_zero_daje_none(polisy):
    stan = _stan(polisy)
    stan["wynik_polisy"]["suma_ubezpieczenia"] = 0
    assert cechy_ze_stanu(stan) is None


def test_brak_szkody_3_lata_w_polisie_daje_none(polisy):
    stan = _stan(polisy)
    stan["wynik_polisy"]["polisa"] = {k: v for k, v in stan["wynik_polisy"]["polisa"].items() if k != "szkody_3_lata"}
    assert cechy_ze_stanu(stan) is None


def test_nie_modyfikuje_stanu(polisy):
    stan = _stan(polisy)
    kopia = copy.deepcopy(stan)
    cechy_ze_stanu(stan)
    assert stan == kopia
