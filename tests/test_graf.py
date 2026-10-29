"""Testy grafu LangGraph (agent/graf.py) na atrapie ModelAgenta.

Atrapa zwraca zadane obiekty Pydantic (nie mock LangChaina) - zgodnie z
SPEC_ETAP2.md, sekcja "Testy". Zero wywolan sieciowych.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.graf import zbuduj_graf
from agent.model import MetadaneWywolania
from agent.schematy import Adres, Ekstrakcja, Klasyfikacja, Ocena, Pola, UzasadnienieReguly

ROOT = Path(__file__).resolve().parent.parent
WYTYCZNE_SCIEZKA = ROOT / "wytyczne" / "wytyczne_mienie_v1.yaml"
PLIK_WNIOSEK = ROOT / "dane" / "wnioski" / "W01.pdf"
PLIK_INNY = ROOT / "dane" / "wnioski" / "W14.pdf"

sys.path.insert(0, str(ROOT / "generator"))
from nip import wygeneruj_poprawny_nip  # noqa: E402

_METADANE = MetadaneWywolania(tokeny_we=10, tokeny_wy=5)


class AtrapaModel:
    """Test double ModelAgenta: zwraca z gory zadane obiekty albo rzuca wyjatki,
    w kolejnosci wywolan. Liczy wywolania, zapamietuje argumenty ocen()."""

    def __init__(self, klasyfikacje=None, ekstrakcje=None, oceny=None):
        self._klasyfikacje = list(klasyfikacje or [])
        self._ekstrakcje = list(ekstrakcje or [])
        self._oceny = list(oceny or [])
        self.liczba_klasyfikuj = 0
        self.liczba_ekstrahuj = 0
        self.liczba_ocen = 0
        self.wywolania_ocen: list[tuple] = []

    @staticmethod
    def _pop(lista):
        element = lista.pop(0)
        if isinstance(element, Exception):
            raise element
        return element, _METADANE

    def klasyfikuj(self, czesci):
        self.liczba_klasyfikuj += 1
        return self._pop(self._klasyfikacje)

    def ekstrahuj(self, czesci):
        self.liczba_ekstrahuj += 1
        return self._pop(self._ekstrakcje)

    def ocen(self, instrukcje, pola_json, problemy_walidacji):
        self.liczba_ocen += 1
        self.wywolania_ocen.append((instrukcje, pola_json, problemy_walidacji))
        return self._pop(self._oceny)


def _pola_czyste() -> Pola:
    return Pola(
        nazwa_firmy="Testowa Sp. z o.o.",
        nip=wygeneruj_poprawny_nip("123456320"),
        adres=Adres(ulica="ul. Testowa 1", kod="00-001", miasto="Warszawa"),
        pkd="47.11.Z",
        branza="Handel detaliczny",
        rodzaj_konstrukcji="niepalna",
        rok_budowy=2010,
        su_budynki=1_000_000,
        su_maszyny=200_000,
        su_zapasy=100_000,
        tryskacze=False,
        ssp=False,
        strefa_powodziowa=False,
        szkody_3_lata=[],
        okres_od="2026-11-01",
        okres_do="2027-10-31",
        data_wniosku="2026-09-01",
        broker="Broker Testowy",
        uwagi=None,
    )


def _pola_duza_su() -> Pola:
    """Suma ubezpieczenia > 10 mln -> silnik powinien wykryc R04/SKIEROWANIE."""
    pola = _pola_czyste()
    pola.su_budynki = 9_000_000
    pola.su_maszyny = 3_000_000
    pola.su_zapasy = 0
    return pola


def _zbuduj_graf(model):
    return zbuduj_graf(model, InMemorySaver(), WYTYCZNE_SCIEZKA)


def _nowy_config() -> dict:
    return {"configurable": {"thread_id": f"test-{uuid.uuid4().hex[:8]}"}}


def test_inny_konczy_bez_interrupt_z_nie_dotyczy():
    model = AtrapaModel(klasyfikacje=[Klasyfikacja(typ_dokumentu="INNY", uzasadnienie="to newsletter")])
    graf = _zbuduj_graf(model)
    wynik = graf.invoke({"plik": str(PLIK_INNY), "wywolania_llm": 0, "log": []}, _nowy_config())

    assert "__interrupt__" not in wynik
    assert wynik["decyzja_koncowa"] == "NIE_DOTYCZY"
    assert model.liczba_ekstrahuj == 0
    assert model.liczba_ocen == 0


def test_wniosek_zatrzymuje_sie_na_interrupt():
    model = AtrapaModel(
        klasyfikacje=[Klasyfikacja(typ_dokumentu="WNIOSEK", uzasadnienie="formularz wniosku")],
        ekstrakcje=[Ekstrakcja(pola=_pola_czyste(), podejrzane_instrukcje=False)],
        oceny=[Ocena(decyzja="AKCEPTACJA", reguly=[], uzasadnienia=[])],
    )
    graf = _zbuduj_graf(model)
    wynik = graf.invoke({"plik": str(PLIK_WNIOSEK), "wywolania_llm": 0, "log": []}, _nowy_config())

    assert "__interrupt__" in wynik
    podsumowanie = wynik["__interrupt__"][0].value
    assert podsumowanie["rekomendacja"]["decyzja"] == "AKCEPTACJA"
    assert podsumowanie["decyzja_silnika"]["decyzja"] == "AKCEPTACJA"
    assert podsumowanie["zgodnosc"] is True


def test_wznowienie_ustawia_decyzje_koncowa_i_zatwierdzajacego():
    model = AtrapaModel(
        klasyfikacje=[Klasyfikacja(typ_dokumentu="WNIOSEK", uzasadnienie="x")],
        ekstrakcje=[Ekstrakcja(pola=_pola_czyste(), podejrzane_instrukcje=False)],
        oceny=[Ocena(decyzja="AKCEPTACJA", reguly=[], uzasadnienia=[])],
    )
    graf = _zbuduj_graf(model)
    config = _nowy_config()
    graf.invoke({"plik": str(PLIK_WNIOSEK), "wywolania_llm": 0, "log": []}, config)

    wynik = graf.invoke(Command(resume={"decyzja": "AKCEPTACJA", "kto": "jan.kowalski"}), config)

    assert "__interrupt__" not in wynik
    assert wynik["decyzja_koncowa"] == "AKCEPTACJA"
    assert wynik["zatwierdzil"] == "jan.kowalski"


def test_rozbieznosc_llm_i_silnika_daje_zgodnosc_false():
    model = AtrapaModel(
        klasyfikacje=[Klasyfikacja(typ_dokumentu="WNIOSEK", uzasadnienie="x")],
        ekstrakcje=[Ekstrakcja(pola=_pola_duza_su(), podejrzane_instrukcje=False)],
        # LLM myli sie: su laczna 12 mln > 10 mln progu (R04/SKIEROWANIE), a LLM mowi AKCEPTACJA.
        oceny=[Ocena(decyzja="AKCEPTACJA", reguly=[], uzasadnienia=[])],
    )
    graf = _zbuduj_graf(model)
    wynik = graf.invoke({"plik": str(PLIK_WNIOSEK), "wywolania_llm": 0, "log": []}, _nowy_config())

    assert wynik["decyzja_silnika"]["decyzja"] == "SKIEROWANIE"
    assert wynik["decyzja_silnika"]["reguly"] == ["R04"]
    assert wynik["zgodnosc"] is False


def test_blad_structured_output_dwukrotny_ustawia_blad_i_interrupt():
    model = AtrapaModel(
        klasyfikacje=[ValueError("blad parsowania 1"), ValueError("blad parsowania 2")],
    )
    graf = _zbuduj_graf(model)
    wynik = graf.invoke({"plik": str(PLIK_WNIOSEK), "wywolania_llm": 0, "log": []}, _nowy_config())

    assert model.liczba_klasyfikuj == 2
    assert "__interrupt__" in wynik
    podsumowanie = wynik["__interrupt__"][0].value
    assert podsumowanie["blad"] is not None


def test_limit_wywolan_llm_blokuje_dalsze_wywolania():
    model = AtrapaModel(klasyfikacje=[Klasyfikacja(typ_dokumentu="WNIOSEK", uzasadnienie="x")])
    graf = _zbuduj_graf(model)
    wynik = graf.invoke(
        {"plik": str(PLIK_WNIOSEK), "wywolania_llm": 6, "log": []}, _nowy_config()
    )

    assert model.liczba_klasyfikuj == 0, "limit osiagniety - model nie powinien zostac wywolany"
    assert "__interrupt__" in wynik
    podsumowanie = wynik["__interrupt__"][0].value
    assert "limit" in podsumowanie["blad"].lower()


def test_ocen_nie_dostaje_surowej_tresci_dokumentu():
    model = AtrapaModel(
        klasyfikacje=[Klasyfikacja(typ_dokumentu="WNIOSEK", uzasadnienie="x")],
        ekstrakcje=[Ekstrakcja(pola=_pola_czyste(), podejrzane_instrukcje=False)],
        oceny=[Ocena(decyzja="AKCEPTACJA", reguly=[], uzasadnienia=[])],
    )
    graf = _zbuduj_graf(model)
    graf.invoke({"plik": str(PLIK_WNIOSEK), "wywolania_llm": 0, "log": []}, _nowy_config())

    assert model.liczba_ocen == 1
    instrukcje, pola_json, problemy = model.wywolania_ocen[0]
    assert isinstance(instrukcje, str) and isinstance(pola_json, str) and isinstance(problemy, list)
    # znaczniki uzywane tylko w surowej tresci dokumentu (agent/wczytywanie.py) nie
    # moga wyciekac do wezla ocen - dostaje on tylko wytyczne + JSON pol.
    for marker in ("TRESC WIADOMOSCI E-MAIL", "ZALACZNIK:"):
        assert marker not in instrukcje
        assert marker not in pola_json
