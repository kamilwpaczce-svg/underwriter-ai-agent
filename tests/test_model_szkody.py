"""Galaz SZKODA w modelach: prompty, ModelAzure/ModelGemini na atrapie LLM, ModelAtrapa (Etap 10).
Zero sieci, zero Entra ID."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.instrukcje_szkody import (
    PROMPT_SYSTEMOWY_EKSTRAKCJA_SZKODY,
    PROMPT_SYSTEMOWY_OCENA_POKRYCIA,
    formatuj_fragmenty,
    tresc_oceny_pokrycia,
)
from agent.model import ModelGemini
from agent.model_azure import ModelAzure
from agent.schematy import Cytat, EkstrakcjaSzkody, OcenaPokrycia, PolaSzkody
from agent.wczytywanie import CzesciDokumentu
from ewaluacja.atrapa import ModelAtrapa
from rag.fragmenty import Fragment

ROOT = Path(__file__).resolve().parent.parent
FRAGMENT_P9U2 = Fragment("p9u2", 9, 2, "Obowiązki", "§ 9. Obowiązki\nust. 2. Kradzież zgłosić policji.")
FRAGMENT_P4U1 = Fragment("p4u1", 4, 1, "Zakres", "§ 4. Zakres\nust. 1. Pożar.")


class FakeLLM:
    def __init__(self, odpowiedzi):
        self._odpowiedzi = list(odpowiedzi)
        self.wiadomosci_otrzymane: list = []
        self.schematy: list = []

    def with_structured_output(self, schemat, include_raw=True):
        self.schematy.append(schemat)
        return self

    def invoke(self, wiadomosci):
        self.wiadomosci_otrzymane.append(wiadomosci)
        return {"parsed": self._odpowiedzi.pop(0), "raw": None, "parsing_error": None}


def _model_azure(odpowiedzi):
    llm = FakeLLM(odpowiedzi)
    return ModelAzure(llm=llm, klient_ocr=object(), katalog_cache_ocr="nieuzywany"), llm


def test_formatuj_fragmenty_z_identyfikatorami():
    tekst = formatuj_fragmenty([FRAGMENT_P4U1, FRAGMENT_P9U2])
    assert tekst.startswith("[p4u1] § 4. Zakres")
    assert "[p9u2] § 9. Obowiązki" in tekst
    assert formatuj_fragmenty([]) == "(brak fragmentow)"


def test_tresc_oceny_bez_danych_polisy_i_z_blokada_drugiej_rundy():
    wynik_polisy = {"kody": ["S04"], "polisa": {"ubezpieczony": "X"}, "braki": []}
    pierwsza = tresc_oceny_pokrycia({"przyczyna": "pożar"}, wynik_polisy, [FRAGMENT_P4U1])
    assert "pożar" in pierwsza and "S04" in pierwsza
    assert "ubezpieczony" not in pierwsza
    assert "MUSI byc null" not in pierwsza
    druga = tresc_oceny_pokrycia({"przyczyna": "pożar"}, wynik_polisy, [FRAGMENT_P4U1], [FRAGMENT_P9U2])
    assert "[p9u2]" in druga and "MUSI byc null" in druga


def test_prompty_wymagaja_cytatu_przy_odmowie_i_chronia_przed_instrukcjami():
    assert "ODMOWA BEZ cytatu" in PROMPT_SYSTEMOWY_OCENA_POKRYCIA
    assert "podejrzane_instrukcje=true" in PROMPT_SYSTEMOWY_EKSTRAKCJA_SZKODY


def test_model_azure_ekstrahuj_szkode_pusty_dokument():
    model, llm = _model_azure([EkstrakcjaSzkody(pola=PolaSzkody(), podejrzane_instrukcje=False)])
    wynik, metadane = model.ekstrahuj_szkode(CzesciDokumentu(tekst="", media=[]))
    assert all(v is None for v in wynik.pola.model_dump().values())
    assert llm.schematy == [EkstrakcjaSzkody]
    assert "nie ma warstwy tekstowej" in llm.wiadomosci_otrzymane[0][1].content
    assert metadane.tokeny_we is None


def test_model_azure_ocen_pokrycie_przekazuje_fragmenty():
    ocena = OcenaPokrycia(decyzja="POKRYTA", cytaty=[Cytat(paragraf="§ 4", ustep="1", uzasadnienie="pożar")])
    model, llm = _model_azure([ocena])
    wynik, _ = model.ocen_pokrycie({"przyczyna": "pożar"}, {"kody": []}, [FRAGMENT_P4U1])
    assert wynik.decyzja == "POKRYTA"
    assert llm.schematy == [OcenaPokrycia]
    assert llm.wiadomosci_otrzymane[0][0].content == PROMPT_SYSTEMOWY_OCENA_POKRYCIA
    assert "[p4u1]" in llm.wiadomosci_otrzymane[0][1].content


def test_model_gemini_ma_obie_metody_szkody():
    model = ModelGemini.__new__(ModelGemini)
    model._llm = FakeLLM(
        [EkstrakcjaSzkody(pola=PolaSzkody(nr_polisy="PL/MSP/2026/0001"), podejrzane_instrukcje=False),
         OcenaPokrycia(decyzja="SKIEROWANIE")]
    )
    ekstrakcja, _ = model.ekstrahuj_szkode(CzesciDokumentu(tekst="Zgloszenie", media=[]))
    ocena, _ = model.ocen_pokrycie(ekstrakcja.pola.model_dump(), {"kody": []}, [])
    assert ekstrakcja.pola.nr_polisy == "PL/MSP/2026/0001"
    assert ocena.decyzja == "SKIEROWANIE"


def _zapisz_przypadek(katalog: Path, dane: dict) -> None:
    katalog.mkdir(parents=True, exist_ok=True)
    (katalog / f"{dane['id']}.json").write_text(json.dumps(dane, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def atrapa(tmp_path):
    szkody = tmp_path / "szkody" / "oczekiwane"
    _zapisz_przypadek(szkody, {
        "id": "Z07", "typ_dokumentu": "SZKODA", "pola": {"nr_polisy": "PL/MSP/2026/0007"},
        "podejrzane": False, "decyzja_llm": "UZUPELNIENIE", "decyzja": "UZUPELNIENIE",
        "paragrafy_oczekiwane": ["§9 ust. 2", "§10 ust. 2"],
        "brakujace_dokumenty": ["potwierdzenie zgłoszenia na policji"],
        "zapytanie_dodatkowe": "dokumenty wymagane po kradzieży",
    })
    _zapisz_przypadek(szkody, {
        "id": "Z12", "typ_dokumentu": "SZKODA", "pola": {}, "podejrzane": True,
        "decyzja_llm": None, "decyzja": "SKIEROWANIE", "paragrafy_oczekiwane": [],
        "brakujace_dokumenty": [], "zapytanie_dodatkowe": None,
    })
    return ModelAtrapa(ROOT / "dane" / "oczekiwane", katalog_szkody=szkody)


def test_atrapa_prosi_o_dodatkowe_zapytanie_tylko_w_pierwszej_rundzie(atrapa):
    atrapa.ustaw_przypadek("Z07")
    pierwsza, _ = atrapa.ocen_pokrycie({}, {"kody": []}, [FRAGMENT_P4U1])
    assert pierwsza.dodatkowe_zapytanie == "dokumenty wymagane po kradzieży"
    assert pierwsza.cytaty == []
    druga, _ = atrapa.ocen_pokrycie({}, {"kody": []}, [FRAGMENT_P4U1], [FRAGMENT_P9U2])
    assert druga.dodatkowe_zapytanie is None
    assert druga.decyzja == "UZUPELNIENIE"
    assert [(c.paragraf, c.ustep) for c in druga.cytaty] == [("§ 9", "2")]
    assert druga.brakujace_dokumenty == ["potwierdzenie zgłoszenia na policji"]


def test_atrapa_cytuje_pierwszy_oczekiwany_gdy_nie_pobrano_zadnego(atrapa):
    atrapa.ustaw_przypadek("Z07")
    druga, _ = atrapa.ocen_pokrycie({}, {"kody": []}, [FRAGMENT_P4U1], [])
    assert [(c.paragraf, c.ustep) for c in druga.cytaty] == [("§ 9", "2")]


def test_atrapa_ekstrahuje_podejrzane_z_json_i_bez_decyzji_llm_zwraca_skierowanie(atrapa):
    atrapa.ustaw_przypadek("Z12")
    ekstrakcja, _ = atrapa.ekstrahuj_szkode(CzesciDokumentu(tekst="", media=[]))
    assert ekstrakcja.podejrzane_instrukcje is True
    ocena, _ = atrapa.ocen_pokrycie({}, {"kody": []}, [])
    assert ocena.decyzja == "SKIEROWANIE" and ocena.cytaty == []


def test_atrapa_nadal_czyta_wnioski_z_dane_oczekiwane(atrapa):
    atrapa.ustaw_przypadek("W01")
    klasyfikacja, _ = atrapa.klasyfikuj(CzesciDokumentu(tekst="", media=[]))
    assert klasyfikacja.typ_dokumentu == "WNIOSEK"


def test_atrapa_domyslny_katalog_szkod_obok_oczekiwanych():
    atrapa = ModelAtrapa(ROOT / "dane" / "oczekiwane")
    assert atrapa._katalog_szkody == ROOT / "dane" / "szkody" / "oczekiwane"
