"""Etap 15: generator syntetycznego zbioru do treningu i symulacji dryfu."""

from __future__ import annotations

import pandas as pd
import pytest

from ryzyko.cechy import CECHY
from ryzyko.generator import generuj_zbior


def test_kolumny_to_cechy_plus_etykieta():
    df = generuj_zbior(300, seed=1)
    assert list(df.columns) == CECHY + ["do_weryfikacji"]
    assert len(df) == 300
    assert set(df["do_weryfikacji"].unique()) <= {0, 1}
    assert not df.isna().any().any()


def test_deterministyczny_dla_seeda():
    pd.testing.assert_frame_equal(generuj_zbior(500, seed=7), generuj_zbior(500, seed=7))
    assert not generuj_zbior(500, seed=7).equals(generuj_zbior(500, seed=8))


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_odsetek_pozytywnych_10_do_20_proc(seed):
    odsetek = generuj_zbior(5000, seed=seed)["do_weryfikacji"].mean()
    assert 0.10 <= odsetek <= 0.20


def test_zakresy_cech():
    df = generuj_zbior(5000, seed=3)
    assert df["suma_ubezpieczenia"].between(100_000, 20_000_000).all()
    assert df["udzial_kwoty"].between(0, 1.5).all()
    assert df["dni_do_zgloszenia"].between(0, 60).all()
    assert df["dni_od_poczatku_polisy"].between(0, 365).all()
    assert df["liczba_zalacznikow"].between(0, 6).all()
    assert df["szkody_3_lata"].between(0, 4).all()
    assert set(df["rodzaj_mienia"].unique()) == {"budynek", "maszyny", "zapasy"}


def test_przesuniecie_liczbowe_zmienia_rozklad():
    baza = generuj_zbior(3000, seed=5)
    dryf = generuj_zbior(3000, seed=5, przesuniecie={"udzial_kwoty": 0.4})
    assert dryf["udzial_kwoty"].mean() > baza["udzial_kwoty"].mean() + 0.2
    # inne cechy bez zmian (te same liczby losowe)
    assert dryf["dni_do_zgloszenia"].equals(baza["dni_do_zgloszenia"])


def test_przesuniecie_kategorii_zmienia_proporcje():
    baza = generuj_zbior(3000, seed=5)
    dryf = generuj_zbior(3000, seed=5, przesuniecie={"rodzaj_mienia": 0.3})
    udzial = lambda df: (df["rodzaj_mienia"] == "zapasy").mean()
    assert udzial(dryf) > udzial(baza) + 0.2


def test_nieznana_cecha_w_przesunieciu_to_blad():
    with pytest.raises(ValueError):
        generuj_zbior(10, seed=1, przesuniecie={"nie_ma_takiej": 1.0})


def test_etykieta_zalezy_od_ukrytej_reguly():
    df = generuj_zbior(5000, seed=11)
    wysoki = df[df["udzial_kwoty"] > 1.0]["do_weryfikacji"].mean()
    niski = df[df["udzial_kwoty"] < 0.3]["do_weryfikacji"].mean()
    assert wysoki > 2 * niski
