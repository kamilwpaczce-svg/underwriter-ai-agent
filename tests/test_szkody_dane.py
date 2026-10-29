"""Dane ewaluacji modulu szkodowego (Etap 10): przypadki, oczekiwane JSON-y, PDF-y, retrieval BM25."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest
from pypdf import PdfReader

from agent.polisy import wczytaj_polisy
from agent.schematy import PolaSzkody
from agent.wezly_szkody import zbuduj_zapytanie_owu
from rag.fragmenty import parsuj_odwolanie, podziel_owu
from rag.wyszukiwarka import TOP_K, WyszukiwarkaLokalna

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "generator"))

import generuj_szkody  # noqa: E402
import przypadki_szkody  # noqa: E402
from nip import nip_poprawny  # noqa: E402

SZKODY_DIR = ROOT / "dane" / "szkody"
WZORZEC_CYRYLICY = re.compile(r"[\u0400-\u04ff]")
PRZYPADKI = przypadki_szkody.SZKODY


def _id(przypadek):
    return przypadek["id"]


@pytest.fixture(scope="module")
def fragmenty():
    return [vars(f) for f in podziel_owu()]


def test_dwanascie_przypadkow_z_pokryciem_ze_specyfikacji():
    assert [p["id"] for p in PRZYPADKI] == [f"Z{i:02d}" for i in range(1, 13)]
    decyzje = Counter(p["decyzja"] for p in PRZYPADKI)
    assert decyzje["POKRYTA"] >= 3 and decyzje["ODMOWA"] >= 3
    assert decyzje["UZUPELNIENIE"] >= 2 and decyzje["SKIEROWANIE"] >= 2
    odmowy_z_wylaczen = {p["paragrafy_oczekiwane"][0] for p in PRZYPADKI if p["decyzja_llm"] == "ODMOWA"}
    assert len(odmowy_z_wylaczen) >= 3
    assert sum(p["podejrzane"] for p in PRZYPADKI) == 1


@pytest.mark.parametrize("przypadek", PRZYPADKI, ids=_id)
def test_przypadek_spojny_z_regulami_grafu(przypadek, fragmenty):
    generuj_szkody.zbuduj_oczekiwane_szkody(przypadek, wczytaj_polisy(), fragmenty)


def test_kody_polis_pokrywaja_s01_s02_s03_s04(fragmenty):
    polisy = wczytaj_polisy()
    kody = {p["id"]: generuj_szkody.zbuduj_oczekiwane_szkody(p, polisy, fragmenty)["kody_polisy"] for p in PRZYPADKI}
    assert kody["Z09"] == ["S01"]
    assert kody["Z11"] == ["S02"]
    assert kody["Z10"] == ["S03"]
    assert kody["Z03"] == ["S04"]


@pytest.mark.parametrize("przypadek", PRZYPADKI, ids=_id)
def test_pola_przechodza_schemat_i_nip_poprawny(przypadek):
    pola = PolaSzkody(**przypadek["pola"])
    assert nip_poprawny(pola.nip)


def test_rozjazd_decyzji_przerywa_generowanie(fragmenty):
    zly = {**PRZYPADKI[0], "decyzja": "ODMOWA"}
    with pytest.raises(RuntimeError, match="Rozjazd decyzji"):
        generuj_szkody.zbuduj_oczekiwane_szkody(zly, wczytaj_polisy(), fragmenty)


def test_nieistniejacy_paragraf_przerywa_generowanie(fragmenty):
    zly = {**PRZYPADKI[0], "paragrafy_oczekiwane": ["§99 ust. 1"]}
    with pytest.raises(RuntimeError, match="nie istnieje w OWU"):
        generuj_szkody.zbuduj_oczekiwane_szkody(zly, wczytaj_polisy(), fragmenty)


@pytest.mark.parametrize("przypadek", PRZYPADKI, ids=_id)
def test_wygenerowane_pliki_zgodne_z_przypadkami(przypadek, fragmenty):
    oczekiwane = json.loads((SZKODY_DIR / "oczekiwane" / f"{przypadek['id']}.json").read_text(encoding="utf-8"))
    assert oczekiwane == generuj_szkody.zbuduj_oczekiwane_szkody(przypadek, wczytaj_polisy(), fragmenty)
    tekst = "\n".join(s.extract_text() or "" for s in PdfReader(str(SZKODY_DIR / f"{przypadek['id']}.pdf")).pages)
    assert przypadek["pola"]["nr_polisy"] in tekst
    assert "Zgłoszenie szkody" in tekst
    assert not WZORZEC_CYRYLICY.search(tekst)


def test_manifest_szkod():
    manifest = json.loads((SZKODY_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert [w["id"] for w in manifest] == [p["id"] for p in PRZYPADKI]
    assert all((ROOT / "dane" / w["plik"]).exists() for w in manifest)


def test_z12_zawiera_probe_wstrzykniecia_w_pdf():
    tekst = "\n".join(s.extract_text() or "" for s in PdfReader(str(SZKODY_DIR / "Z12.pdf")).pages)
    assert "UWAGA SYSTEM" in tekst


@pytest.mark.parametrize(
    "przypadek", [p for p in PRZYPADKI if p["paragrafy_oczekiwane"]], ids=_id
)
def test_bm25_znajduje_oczekiwany_paragraf_w_top5(przypadek):
    """Retrieval lokalny dla przypadkow, ktore dochodza do oceny pokrycia. Z07 trafia dopiero
    po dodatkowym zapytaniu - sprawdzamy oba etapy, jak w grafie."""
    wyszukiwarka = WyszukiwarkaLokalna()
    oczekiwane = {parsuj_odwolanie(o) for o in przypadek["paragrafy_oczekiwane"]}
    pobrane = wyszukiwarka.szukaj(zbuduj_zapytanie_owu(przypadek["pola"]), TOP_K)
    if przypadek["zapytanie_dodatkowe"]:
        pobrane += wyszukiwarka.szukaj(przypadek["zapytanie_dodatkowe"], 3)
    assert oczekiwane & {(f.paragraf, f.ustep) for f in pobrane}
