"""Demo 7, zadanie 3 (czesc bez LlamaIndex, biegnie w `.venv`): skladanie wynikow porownania,
tabela MD, McNemar vs `lokalna`, wariant z wyjatkiem, `main()` w srodowisku bez LlamaIndex.

Wszystko na atrapach wyszukiwarek - zero sieci, zero LLM."""

from __future__ import annotations

import json
import sys

import pytest

from ewaluacja.porownaj_llamaindex import (
    main,
    tabela_md,
    trafienia,
    zbuduj_wyniki,
    zestaw_c,
    zestaw_z,
)
from ewaluacja.statystyka import mcnemar_dokladny, przedzial_wilsona
from rag.fragmenty import podziel_owu

FRAGMENTY = podziel_owu()


class Atrapa:
    """Wyszukiwarka z gory zadana funkcja `zapytanie -> list[Fragment]`."""

    def __init__(self, nazwa, funkcja):
        self.nazwa = nazwa
        self._funkcja = funkcja

    def szukaj(self, zapytanie, k=5):
        return self._funkcja(zapytanie)[:k]


def _fragment_dla(oczekiwane):
    return next(f for f in FRAGMENTY if (f.paragraf, f.ustep) in oczekiwane)


def _fragment_niepasujacy(oczekiwane_wszystkie):
    return next(f for f in FRAGMENTY if (f.paragraf, f.ustep) not in oczekiwane_wszystkie)


def _mapa_dobrych(zestawy):
    return {w["zapytanie"]: [_fragment_dla(w["oczekiwane"])] for z in zestawy for w in z}


def _atrapa_dobra(nazwa, zestawy):
    mapa = _mapa_dobrych(zestawy)
    return Atrapa(nazwa, lambda q: mapa[q])


def _atrapa_trafia_tylko(nazwa, zestawy_dobre, zestawy_zle):
    dobre = _mapa_dobrych(zestawy_dobre)
    wszystkie = {p for z in (zestawy_dobre + zestawy_zle) for w in z for p in w["oczekiwane"]}
    zly = _fragment_niepasujacy(wszystkie)
    return Atrapa(nazwa, lambda q: dobre.get(q, [zly]))


@pytest.fixture
def z():
    return zestaw_z()


@pytest.fixture
def c():
    return zestaw_c()


# --- trafienia: wyjatek w szukaj ---------------------------------------------------------

def test_trafienia_wyjatek_w_szukaj_to_nietrafienie_z_opisem_bledu(z):
    def funkcja(q):
        if q == z[2]["zapytanie"]:
            raise KeyError("brak wektora w cache")
        return [_fragment_dla(next(w for w in z if w["zapytanie"] == q)["oczekiwane"])]

    wynik = trafienia(Atrapa("chora", funkcja), z)
    id_bledu = z[2]["id"]
    assert wynik[id_bledu]["ranga"] is None
    assert wynik[id_bledu]["ids"] == []
    assert "KeyError" in wynik[id_bledu]["blad"] and "brak wektora" in wynik[id_bledu]["blad"]
    reszta = [w for i, w in wynik.items() if i != id_bledu]
    assert len(reszta) == 8 and all(w["ranga"] == 1 and "blad" not in w for w in reszta)


# --- zbuduj_wyniki -----------------------------------------------------------------------

def test_wyniki_maja_trzy_zestawy_i_wszystkie_warianty(z, c):
    warianty = {
        "lokalna": _atrapa_dobra("lokalna", [z, c]),
        "wariant-a": _atrapa_dobra("wariant-a", [z, c]),
    }
    wyniki = zbuduj_wyniki(warianty, z, c)
    assert set(wyniki["warianty"]) == {"lokalna", "wariant-a"}
    for nazwa in warianty:
        assert set(wyniki["warianty"][nazwa]) == {"Z", "C", "Z+C"}
    assert wyniki["zestawy"] == {"Z": 9, "C": 10, "Z+C": 19}
    assert wyniki["k"] == 5
    w = wyniki["warianty"]["wariant-a"]["Z+C"]
    assert w["n"] == 19 and w["trafione_at_5"] == 19 and w["recall_at_1"] == 1.0 and w["mrr_at_5"] == 1.0
    assert w["wilson_at_5"] == list(przedzial_wilsona(19, 19))


def test_baseline_nie_ma_mcnemara_a_wariant_ma(z, c):
    warianty = {"lokalna": _atrapa_dobra("lokalna", [z, c]), "w": _atrapa_dobra("w", [z, c])}
    wyniki = zbuduj_wyniki(warianty, z, c)
    assert wyniki["warianty"]["lokalna"]["Z"]["mcnemar"] is None
    m = wyniki["warianty"]["w"]["Z+C"]["mcnemar"]
    assert (m["b"], m["c"], m["p"], m["n"]) == (0, 0, 1.0, 19)


def test_mcnemar_vs_lokalna_liczy_pary_niezgodne_i_podaje_id(z, c):
    # baseline trafia wszystko; wariant tylko zestaw Z -> baseline wygrywa 10 par na C
    warianty = {
        "lokalna": _atrapa_dobra("lokalna", [z, c]),
        "slaby": _atrapa_trafia_tylko("slaby", [z], [c]),
    }
    wyniki = zbuduj_wyniki(warianty, z, c)
    zc = wyniki["warianty"]["slaby"]["Z+C"]
    assert zc["trafione_at_5"] == 9
    assert (zc["mcnemar"]["b"], zc["mcnemar"]["c"]) == (10, 0)
    assert zc["mcnemar"]["p"] == mcnemar_dokladny(10, 0)
    assert zc["mcnemar"]["tylko_lokalna_ok"] == sorted(w["id"] for w in c)
    assert zc["mcnemar"]["tylko_wariant_ok"] == []
    assert wyniki["warianty"]["slaby"]["Z"]["mcnemar"]["b"] == 0
    assert wyniki["warianty"]["slaby"]["C"]["mcnemar"]["b"] == 10


def test_top5_i_rangi_per_zapytanie_sa_w_wynikach(z, c):
    warianty = {"lokalna": _atrapa_dobra("lokalna", [z, c])}
    w = zbuduj_wyniki(warianty, z, c)["warianty"]["lokalna"]["Z"]
    assert set(w["top5"]) == {x["id"] for x in z}
    assert all(len(ids) == 1 for ids in w["top5"].values())
    assert set(w["rangi"].values()) == {1}


def test_wariant_z_wyjatkiem_liczy_sie_jako_nietrafienie_i_jest_wypisany(z, c):
    chory_id = z[0]["zapytanie"]

    def funkcja(q):
        if q == chory_id:
            raise RuntimeError("awaria wariantu")
        return _mapa_dobrych([z, c])[q]

    warianty = {"lokalna": _atrapa_dobra("lokalna", [z, c]), "chory": Atrapa("chory", funkcja)}
    wyniki = zbuduj_wyniki(warianty, z, c)
    w = wyniki["warianty"]["chory"]["Z"]
    assert w["n"] == 9 and w["trafione_at_5"] == 8
    assert [b["id"] for b in w["bledy"]] == [z[0]["id"]]
    assert "RuntimeError" in w["bledy"][0]["blad"]
    assert wyniki["warianty"]["chory"]["Z+C"]["mcnemar"]["b"] == 1  # lokalna trafia, chory nie
    md = tabela_md(wyniki)
    assert "Bledy" in md and z[0]["id"] in md and "RuntimeError" in md


def test_wariant_tylko_na_z_ma_none_dla_c_i_zc_a_mcnemar_na_wspolnych_id(z, c):
    warianty = {
        "lokalna": _atrapa_dobra("lokalna", [z, c]),
        "tylko-z": _atrapa_trafia_tylko("tylko-z", [z], []),
    }
    wyniki = zbuduj_wyniki(warianty, z, c, tylko_zestawy={"tylko-z": ("Z",)})
    w = wyniki["warianty"]["tylko-z"]
    assert w["C"] is None and w["Z+C"] is None
    assert w["Z"]["n"] == 9 and w["Z"]["mcnemar"]["n"] == 9
    md = tabela_md(wyniki)
    assert "nie mierzone" in md


def test_tabela_md_ma_wszystkie_warianty_w_kazdym_zestawie(z, c):
    warianty = {n: _atrapa_dobra(n, [z, c]) for n in ("lokalna", "li-a", "li-b")}
    md = tabela_md(zbuduj_wyniki(warianty, z, c))
    for naglowek in ("## Zestaw Z (n = 9)", "## Zestaw C (n = 10)", "## Zestaw Z+C (n = 19)"):
        assert naglowek in md
    for nazwa in warianty:
        assert md.count(f"| {nazwa} |") == 3
    assert "McNemar" in md and "Wilson" in md and "MRR@5" in md


def test_tabela_md_jest_ascii_i_podaje_rozjazdy(z, c):
    warianty = {"lokalna": _atrapa_dobra("lokalna", [z, c]), "slaby": _atrapa_trafia_tylko("slaby", [z], [c])}
    md = tabela_md(zbuduj_wyniki(warianty, z, c))
    md.encode("ascii")
    assert "M06" in md  # id rozjazdu widoczne w tabeli


# --- main() w srodowisku bez LlamaIndex --------------------------------------------------

def test_main_bez_llamaindex_daje_tylko_lokalna_komunikat_i_kod_niezerowy(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "rag.llamaindex_owu", None)  # import -> ImportError
    kod = main(["--wyniki-dir", str(tmp_path)])
    wyjscie = capsys.readouterr()
    assert kod != 0
    assert "llama" in wyjscie.err.lower()
    assert "| lokalna |" in wyjscie.out
    pliki = sorted(p.name for p in tmp_path.iterdir())
    assert len(pliki) == 2 and pliki[0].endswith("_llamaindex.json") and pliki[1].endswith("_llamaindex.md")
    dane = json.loads((tmp_path / pliki[0]).read_text(encoding="utf-8"))
    assert list(dane["wyniki"]["warianty"]) == ["lokalna"]


def test_main_lokalna_odtwarza_znane_liczby_z_etapu_12_i_demo_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "rag.llamaindex_owu", None)
    main(["--wyniki-dir", str(tmp_path)])
    json_plik = next(tmp_path.glob("*_llamaindex.json"))
    w = json.loads(json_plik.read_text(encoding="utf-8"))["wyniki"]["warianty"]["lokalna"]
    assert w["Z"]["trafione_at_5"] == 9 and w["Z"]["n"] == 9
    assert w["C"]["trafione_at_5"] == 9 and w["C"]["n"] == 10
    assert [b for b in w["C"]["rangi"] if w["C"]["rangi"][b] is None] == ["M06"]
    assert w["Z+C"]["trafione_at_5"] == 18
