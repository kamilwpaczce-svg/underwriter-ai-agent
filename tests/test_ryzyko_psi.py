"""Etap 15: referencja i PSI do monitoringu dryfu."""

from __future__ import annotations

import json

import pytest

from ryzyko.cechy import CECHY
from ryzyko.generator import generuj_zbior
from ryzyko.psi import psi, referencja


@pytest.fixture(scope="module")
def ref():
    return referencja(generuj_zbior(5000, seed=1)[CECHY])


def test_referencja_serializuje_sie_do_json(ref):
    odczyt = json.loads(json.dumps(ref))
    assert odczyt == ref
    assert set(ref) == set(CECHY)
    assert ref["rodzaj_mienia"]["typ"] == "kategoria"
    assert ref["udzial_kwoty"]["typ"] == "liczbowa"


def test_referencja_10_koszy_dla_cechy_ciaglej(ref):
    cecha = ref["udzial_kwoty"]
    assert len(cecha["proporcje"]) == len(cecha["granice"]) + 1 == 10
    assert sum(cecha["proporcje"]) == pytest.approx(1.0)


def test_referencja_cechy_dyskretnej_ma_mniej_koszy(ref):
    cecha = ref["szkody_3_lata"]
    assert len(cecha["proporcje"]) == len(cecha["granice"]) + 1 < 10
    assert sum(cecha["proporcje"]) == pytest.approx(1.0)


def test_te_same_rozklady_psi_ponizej_0_1(ref):
    wyniki = psi(ref, generuj_zbior(2000, seed=2)[CECHY])
    assert set(wyniki) == set(CECHY)
    assert max(wyniki.values()) < 0.1


def test_psi_dziala_na_referencji_po_json(ref):
    biezace = generuj_zbior(2000, seed=2)[CECHY]
    assert psi(json.loads(json.dumps(ref)), biezace) == psi(ref, biezace)


def test_wstrzykniety_dryf_psi_powyzej_0_2(ref):
    wyniki = psi(ref, generuj_zbior(2000, seed=3, przesuniecie={"udzial_kwoty": 0.4})[CECHY])
    assert wyniki["udzial_kwoty"] > 0.2
    assert wyniki["dni_do_zgloszenia"] < 0.1


def test_dryf_kategorii_wykryty(ref):
    wyniki = psi(ref, generuj_zbior(2000, seed=3, przesuniecie={"rodzaj_mienia": 0.4})[CECHY])
    assert wyniki["rodzaj_mienia"] > 0.2


def test_nieznana_kategoria_to_osobny_kosz_a_nie_wyjatek(ref):
    biezace = generuj_zbior(2000, seed=2)[CECHY].copy()
    biezace.loc[biezace.index[:600], "rodzaj_mienia"] = "nowy_rodzaj"
    wyniki = psi(ref, biezace)
    assert wyniki["rodzaj_mienia"] > 0.2


def test_wartosci_poza_zakresem_referencji_wpadaja_do_skrajnych_koszy(ref):
    biezace = generuj_zbior(2000, seed=2)[CECHY].copy()
    biezace["suma_ubezpieczenia"] = 1e12
    assert psi(ref, biezace)["suma_ubezpieczenia"] > 0.2


def test_brak_kolumny_to_blad_a_nie_zero(ref):
    biezace = generuj_zbior(500, seed=2)[CECHY].drop(columns=["udzial_kwoty"])
    with pytest.raises(KeyError):
        psi(ref, biezace)


def test_pusty_zbior_to_blad_a_nie_zero(ref):
    with pytest.raises(ValueError):
        psi(ref, generuj_zbior(10, seed=2)[CECHY].iloc[0:0])
    with pytest.raises(ValueError):
        referencja(generuj_zbior(10, seed=2)[CECHY].iloc[0:0])
