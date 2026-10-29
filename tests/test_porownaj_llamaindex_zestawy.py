"""Demo 7, zadanie 1: zestawy Z i C oraz miary porownania - BEZ LlamaIndex (biegnie w `.venv`).

Zestaw C = `dane/czat/pytania.json` z Demo 1 (zamrozony 28.10.2026, nie zmieniac). Zapytanie
nawiazujace = pytanie + poprzednie pytanie uzytkownika (rownowaznik
`czat.instrukcje.zapytanie_wyszukiwania` z gałęzi demo1, odtworzony w 2 liniach)."""

from __future__ import annotations

import json

import pytest

from ewaluacja.porownaj_llamaindex import (
    PLIK_PYTAN_C,
    agreguj,
    trafienia,
    zestaw_c,
    zestaw_z,
)
from ewaluacja.porownaj_wyszukiwarki import ocen_wyszukiwarke, zloty_zbior
from rag.fragmenty import podziel_owu
from rag.wyszukiwarka import TOP_K, WyszukiwarkaLokalna

KLUCZE_WIERSZA = {"id", "zestaw", "zapytanie", "oczekiwane"}


# --- zestaw Z ---------------------------------------------------------------------------

def test_zestaw_z_ma_9_wierszy_i_ten_sam_zbior_co_zloty_zbior():
    z = zestaw_z()
    zloty = zloty_zbior()
    assert len(z) == 9
    assert [w["id"] for w in z] == [w["id"] for w in zloty]
    for wiersz, zrodlo in zip(z, zloty):
        assert set(wiersz) == KLUCZE_WIERSZA
        assert wiersz["zestaw"] == "Z"
        assert wiersz["zapytanie"] == zrodlo["zapytanie"]
        assert wiersz["oczekiwane"] == zrodlo["oczekiwane"]


# --- zestaw C ---------------------------------------------------------------------------

def test_plik_pytan_c_jest_zamrozony_28_10():
    dane = json.loads(PLIK_PYTAN_C.read_text(encoding="utf-8"))
    assert dane["zamrozono"] == "2026-10-28"
    assert len(dane["pytania"]) == 12


def test_zestaw_c_ma_10_wierszy_bez_pytan_poza_owu():
    c = zestaw_c()
    ids = [w["id"] for w in c]
    assert len(c) == 10
    assert "P01" not in ids and "P02" not in ids
    assert ids == ["M01", "N01", "M02", "N02", "M03", "M04", "M05", "M06", "M07", "M08"]
    for wiersz in c:
        assert set(wiersz) == KLUCZE_WIERSZA
        assert wiersz["zestaw"] == "C"
        assert wiersz["oczekiwane"]


def test_zapytanie_nawiazujace_n01_to_pytanie_plus_poprzednie_pytanie():
    # rownowaznosc z demo1: czat/instrukcje.py::zapytanie_wyszukiwania (f"{pytanie} {poprzednie}")
    po_id = {w["id"]: w for w in zestaw_c()}
    assert po_id["N01"]["zapytanie"] == (
        "A kogo muszę o tym zawiadomić? Czy kradzież z włamaniem jest objęta ubezpieczeniem?"
    )
    assert po_id["N02"]["zapytanie"] == (
        "A co się stanie, jeśli go nie dotrzymam? W jakim terminie muszę zgłosić szkodę ubezpieczycielowi?"
    )


def test_zapytanie_merytoryczne_to_samo_pytanie_bez_historii():
    po_id = {w["id"]: w for w in zestaw_c()}
    assert po_id["M01"]["zapytanie"] == "Czy kradzież z włamaniem jest objęta ubezpieczeniem?"


def test_m04_ma_dwa_oczekiwane_ustepy():
    po_id = {w["id"]: w for w in zestaw_c()}
    assert po_id["M04"]["oczekiwane"] == {(9, 3), (9, 4)}
    assert po_id["M01"]["oczekiwane"] == {(4, 6)}


def test_kazdy_oczekiwany_ustep_istnieje_w_owu():
    istnieja = {(f.paragraf, f.ustep) for f in podziel_owu()}
    for wiersz in zestaw_c() + zestaw_z():
        assert wiersz["oczekiwane"] <= istnieja, wiersz["id"]


def test_zestaw_c_z_nieistniejacym_po_wywala_sie(tmp_path):
    plik = tmp_path / "pytania.json"
    plik.write_text(json.dumps({"pytania": [
        {"id": "N99", "typ": "nawiazujace", "po": "M99", "pytanie": "A co dalej?",
         "oczekiwane": [{"paragraf": 1, "ustep": 1}]},
    ]}), encoding="utf-8")
    with pytest.raises(KeyError):
        zestaw_c(plik)


# --- trafienia / agreguj ----------------------------------------------------------------

class _Stala:
    """Wyszukiwarka zwracajaca z gory zadane fragmenty (po id), niezaleznie od zapytania."""

    nazwa = "stala"

    def __init__(self, ids_po_zapytaniu: dict[str, list[str]]):
        self._ids = ids_po_zapytaniu
        self._po_id = {f.id: f for f in podziel_owu()}

    def szukaj(self, zapytanie, k=TOP_K):
        return [self._po_id[i] for i in self._ids[zapytanie]][:k]


def test_trafienia_ranga_i_ids_na_atrapie():
    zestaw = [
        {"id": "A", "zestaw": "Z", "zapytanie": "qa", "oczekiwane": {(4, 6)}},
        {"id": "B", "zestaw": "Z", "zapytanie": "qb", "oczekiwane": {(9, 3), (9, 4)}},
        {"id": "C", "zestaw": "Z", "zapytanie": "qc", "oczekiwane": {(9, 1)}},
    ]
    w = _Stala({"qa": ["p4u6", "p9u1"], "qb": ["p9u1", "p9u2", "p9u4"], "qc": ["p9u2", "p9u3"]})
    wynik = trafienia(w, zestaw)
    assert wynik["A"] == {"ranga": 1, "ids": ["p4u6", "p9u1"]}
    assert wynik["B"] == {"ranga": 3, "ids": ["p9u1", "p9u2", "p9u4"]}
    assert wynik["C"] == {"ranga": None, "ids": ["p9u2", "p9u3"]}


def test_trafienia_respektuje_k():
    zestaw = [{"id": "A", "zestaw": "Z", "zapytanie": "qa", "oczekiwane": {(9, 4)}}]
    w = _Stala({"qa": ["p9u1", "p9u2", "p9u4"]})
    assert trafienia(w, zestaw, k=2)["A"] == {"ranga": None, "ids": ["p9u1", "p9u2"]}
    assert trafienia(w, zestaw, k=3)["A"]["ranga"] == 3


def test_agreguj_liczy_recall_i_mrr_na_atrapie():
    wyniki = {
        "A": {"ranga": 1, "ids": []},
        "B": {"ranga": 3, "ids": []},
        "C": {"ranga": None, "ids": []},
        "D": {"ranga": 5, "ids": []},
    }
    a = agreguj(wyniki)
    assert a["n"] == 4
    assert (a["trafione_at_1"], a["trafione_at_3"], a["trafione_at_5"]) == (1, 2, 3)
    assert a["recall_at_1"] == 0.25
    assert a["recall_at_3"] == 0.5
    assert a["recall_at_5"] == 0.75
    assert a["mrr_at_5"] == round((1 + 1 / 3 + 0 + 1 / 5) / 4, 3)


def test_agreguj_puste_wejscie_daje_none():
    a = agreguj({})
    assert a["n"] == 0
    assert a["recall_at_5"] is None and a["mrr_at_5"] is None


def test_agregaty_lokalnej_na_z_rowne_ocen_wyszukiwarke():
    lokalna = WyszukiwarkaLokalna()
    stary = ocen_wyszukiwarke(lokalna, zloty_zbior())
    nowy = agreguj(trafienia(lokalna, zestaw_z()))
    assert nowy["n"] == stary["n_ocenionych"] == 9
    for klucz in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr_at_5"):
        assert nowy[klucz] == stary[klucz], klucz


def test_znane_liczby_lokalnej_na_z_9_z_9_at_5():
    # SPEC_ETAP12.md:79-86 - recall@5 100%, recall@1 67%, MRR 0,806
    a = agreguj(trafienia(WyszukiwarkaLokalna(), zestaw_z()))
    assert a["trafione_at_5"] == 9 and a["n"] == 9
    assert a["recall_at_1"] == 0.667
    assert a["mrr_at_5"] == 0.806


def test_znane_liczby_lokalnej_na_c_9_z_10_chybione_m06():
    # SPEC_DEMO1_CZAT_OWU.md:297 - recall@5 = 9/10, chybione M06 (luka leksykalna)
    wyniki = trafienia(WyszukiwarkaLokalna(), zestaw_c())
    a = agreguj(wyniki)
    assert a["n"] == 10
    assert a["trafione_at_5"] == 9
    assert [i for i, w in wyniki.items() if w["ranga"] is None] == ["M06"]
