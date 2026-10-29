"""Testy logiki porownania wynikow agenta z danymi oczekiwanymi (ewaluacja/porownanie.py)."""

from __future__ import annotations

from ewaluacja.porownanie import (
    porownaj_pole,
    porownaj_pola,
    porownaj_przypadek,
    porownaj_reguly,
    przypadek_w_pelni_zgodny,
    wynik_pol,
)


def test_porownanie_napisow_ignoruje_wielkosc_liter_i_biale_znaki():
    assert porownaj_pole("nazwa_firmy", "Firma   Testowa", "firma testowa")
    assert porownaj_pole("nazwa_firmy", "  Firma Testowa  ", "Firma Testowa")
    assert not porownaj_pole("nazwa_firmy", "Firma A", "Firma B")


def test_porownanie_napisow_rozne_biale_znaki_srodkowe():
    assert porownaj_pole("branza", "Handel\tdetaliczny", "Handel detaliczny")
    assert porownaj_pole("pkd", "47.11.Z\n", "47.11.z")


def test_porownanie_liczb_i_wartosci_none():
    assert porownaj_pole("rok_budowy", 2010, 2010)
    assert not porownaj_pole("rok_budowy", 2010, 2011)
    assert porownaj_pole("uwagi", None, None)
    assert not porownaj_pole("uwagi", "cos", None)


def test_porownanie_adresu_po_polach_skladowych():
    oczekiwany = {"ulica": "ul. Testowa 1", "kod": "00-001", "miasto": "Warszawa"}
    otrzymany = {"ulica": "UL. TESTOWA 1", "kod": "00-001", "miasto": "warszawa"}
    assert porownaj_pole("adres", oczekiwany, otrzymany)


def test_porownanie_adresu_roznica_w_jednym_podpolu_daje_niezgodnosc():
    oczekiwany = {"ulica": "ul. Testowa 1", "kod": "00-001", "miasto": "Warszawa"}
    otrzymany = {"ulica": "ul. Testowa 1", "kod": "00-002", "miasto": "Warszawa"}
    assert not porownaj_pole("adres", oczekiwany, otrzymany)


def test_porownanie_adresu_brakujace_traktowane_jako_puste():
    assert porownaj_pole("adres", None, None)
    assert not porownaj_pole("adres", {"ulica": "x", "kod": "00-001", "miasto": "Warszawa"}, None)


def test_porownanie_adresu_ignoruje_prefiks_ul():
    oczekiwany = {"ulica": "ul. Warsztatowa 6", "kod": "44-100", "miasto": "Gliwice"}
    assert porownaj_pole("adres", oczekiwany, {**oczekiwany, "ulica": "Warsztatowa 6"})
    assert porownaj_pole("adres", oczekiwany, {**oczekiwany, "ulica": "UL Warsztatowa 6"})


def test_porownanie_adresu_prefiks_ul_nie_maskuje_innej_ulicy():
    oczekiwany = {"ulica": "ul. Warsztatowa 6", "kod": "44-100", "miasto": "Gliwice"}
    assert not porownaj_pole("adres", oczekiwany, {**oczekiwany, "ulica": "Warsztatowa 8"})
    # "Ulanska" zaczyna sie od "ul", ale bez kropki/spacji to nie prefiks
    assert not porownaj_pole("adres", {**oczekiwany, "ulica": "Ulanska 3"}, {**oczekiwany, "ulica": "anska 3"})


def test_porownanie_szkod_ta_sama_liczba_i_wielozbior_kwot():
    oczekiwane = [{"rok": 2024, "przyczyna": "powodz", "kwota": 5000}, {"rok": 2023, "przyczyna": "pozar", "kwota": 3000}]
    otrzymane = [{"rok": 2023, "przyczyna": "pozar", "kwota": 3000}, {"rok": 2024, "przyczyna": "powodz", "kwota": 5000}]
    assert porownaj_pole("szkody_3_lata", oczekiwane, otrzymane)


def test_porownanie_szkod_rozna_liczba_szkod_niezgodna():
    oczekiwane = [{"rok": 2024, "kwota": 5000}]
    otrzymane = [{"rok": 2024, "kwota": 5000}, {"rok": 2023, "kwota": 3000}]
    assert not porownaj_pole("szkody_3_lata", oczekiwane, otrzymane)


def test_porownanie_szkod_ta_sama_liczba_inna_kwota_niezgodna():
    oczekiwane = [{"rok": 2024, "kwota": 5000}]
    otrzymane = [{"rok": 2024, "kwota": 4000}]
    assert not porownaj_pole("szkody_3_lata", oczekiwane, otrzymane)


def test_porownanie_szkod_puste_listy_zgodne():
    assert porownaj_pole("szkody_3_lata", [], [])
    assert porownaj_pole("szkody_3_lata", None, [])


def test_porownaj_pola_zwraca_slownik_trafien_dla_kazdego_pola_oczekiwanego():
    oczekiwane = {"nazwa_firmy": "Firma A", "rok_budowy": 2010}
    otrzymane = {"nazwa_firmy": "firma a", "rok_budowy": 2099}
    wynik = porownaj_pola(oczekiwane, otrzymane)
    assert wynik == {"nazwa_firmy": True, "rok_budowy": False}


def test_wynik_pol_zlicza_trafienia_i_wszystkie():
    oczekiwane = {"a": "x", "b": "y", "c": "z"}
    otrzymane = {"a": "x", "b": "inne", "c": "z"}
    assert wynik_pol(oczekiwane, otrzymane) == (2, 3)


def test_porownaj_reguly_ignoruje_kolejnosc():
    assert porownaj_reguly(["R01", "R04"], ["R04", "R01"])
    assert not porownaj_reguly(["R01"], ["R01", "R04"])
    assert porownaj_reguly([], None)


def test_porownaj_przypadek_inny_pomija_decyzje_llm():
    oczekiwany = {"id": "W14", "typ_dokumentu": "INNY"}
    wynik_grafu = {"typ_dokumentu": "INNY", "pola": None}
    wynik = porownaj_przypadek(oczekiwany, wynik_grafu)
    assert wynik["typ_dokumentu_ok"] is True
    assert wynik["decyzja_llm_ok"] is True
    assert wynik["reguly_llm_ok"] is True
    assert przypadek_w_pelni_zgodny(wynik)


def test_porownaj_przypadek_wniosek_pelna_zgodnosc():
    oczekiwany = {
        "id": "W01",
        "typ_dokumentu": "WNIOSEK",
        "pola": {"nazwa_firmy": "Firma A", "nip": "1234563218"},
        "decyzja": "AKCEPTACJA",
        "reguly": [],
    }
    wynik_grafu = {
        "typ_dokumentu": "WNIOSEK",
        "pola": {"nazwa_firmy": "firma a", "nip": "1234563218"},
        "rekomendacja": {"decyzja": "AKCEPTACJA", "reguly": []},
        "decyzja_silnika": {"decyzja": "AKCEPTACJA", "reguly": []},
        "podejrzane_instrukcje": False,
    }
    wynik = porownaj_przypadek(oczekiwany, wynik_grafu)
    assert przypadek_w_pelni_zgodny(wynik)


def test_porownaj_przypadek_rozbieznosc_decyzji_llm_nie_jest_w_pelni_zgodny():
    oczekiwany = {
        "id": "W04",
        "typ_dokumentu": "WNIOSEK",
        "pola": {"nazwa_firmy": "Firma A"},
        "decyzja": "SKIEROWANIE",
        "reguly": ["R04"],
    }
    wynik_grafu = {
        "typ_dokumentu": "WNIOSEK",
        "pola": {"nazwa_firmy": "Firma A"},
        "rekomendacja": {"decyzja": "AKCEPTACJA", "reguly": []},
        "decyzja_silnika": {"decyzja": "SKIEROWANIE", "reguly": ["R04"]},
        "podejrzane_instrukcje": False,
    }
    wynik = porownaj_przypadek(oczekiwany, wynik_grafu)
    assert wynik["decyzja_llm_ok"] is False
    assert wynik["decyzja_silnika_na_polach_llm_ok"] is True
    assert not przypadek_w_pelni_zgodny(wynik)


def test_porownaj_przypadek_podejrzane_instrukcje_tylko_dla_w13():
    oczekiwany_w13 = {"id": "W13", "typ_dokumentu": "WNIOSEK", "pola": {}, "decyzja": "SKIEROWANIE", "reguly": []}
    wynik_grafu = {
        "typ_dokumentu": "WNIOSEK",
        "pola": {},
        "rekomendacja": {"decyzja": "SKIEROWANIE", "reguly": []},
        "decyzja_silnika": {"decyzja": "SKIEROWANIE", "reguly": []},
        "podejrzane_instrukcje": True,
    }
    wynik = porownaj_przypadek(oczekiwany_w13, wynik_grafu)
    assert wynik["podejrzane_instrukcje_oczekiwane"] is True
    assert wynik["podejrzane_instrukcje_ok"] is True

    oczekiwany_inny_id = {**oczekiwany_w13, "id": "W01"}
    wynik2 = porownaj_przypadek(oczekiwany_inny_id, wynik_grafu)
    assert wynik2["podejrzane_instrukcje_oczekiwane"] is False
    assert wynik2["podejrzane_instrukcje_ok"] is False
