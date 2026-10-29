"""WyszukiwarkaLokalna (BM25 w pamieci) - SPEC_ETAP10.md: dla 3 zapytan oczekiwany paragraf w top 5."""

from __future__ import annotations

import pytest

from rag.wyszukiwarka import TOP_K, WyszukiwarkaLokalna, tokenizuj


@pytest.fixture(scope="module")
def wyszukiwarka():
    return WyszukiwarkaLokalna()


def test_tokenizuj_zamienia_polskie_znaki_i_obcina_do_5():
    assert tokenizuj("Pożar HALI, w 7 dni") == ["pozar", "hali", "dni"]
    assert tokenizuj("zgłoszenia zgłoszenie") == ["zglos", "zglos"]


@pytest.mark.parametrize(
    ("zapytanie", "oczekiwany_id"),
    [
        ("pożar hali", "p4u1"),
        ("kradzież bez śladów włamania", "p6u6"),
        ("termin zgłoszenia szkody 7 dni", "p9u1"),
    ],
)
def test_oczekiwany_ustep_w_top_5(wyszukiwarka, zapytanie, oczekiwany_id):
    wyniki = wyszukiwarka.szukaj(zapytanie, TOP_K)
    assert oczekiwany_id in [f.id for f in wyniki]


def test_zwraca_najwyzej_k_fragmentow_i_nazwe(wyszukiwarka):
    assert wyszukiwarka.nazwa == "lokalna"
    assert len(wyszukiwarka.szukaj("szkoda mienie ubezpieczenie", 3)) == 3


def test_zapytanie_bez_trafien_daje_pusta_liste(wyszukiwarka):
    assert wyszukiwarka.szukaj("xyzzy qwerty", 5) == []
    assert wyszukiwarka.szukaj("", 5) == []


def test_wynik_jest_deterministyczny(wyszukiwarka):
    pierwszy = [f.id for f in wyszukiwarka.szukaj("zalanie wodą z instalacji", 5)]
    drugi = [f.id for f in WyszukiwarkaLokalna().szukaj("zalanie wodą z instalacji", 5)]
    assert pierwszy == drugi
