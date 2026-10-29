"""Testy `agent/model_azure.py` - atrapa LLM i atrapa klienta OCR, zero sieci,
zero Entra ID, zero wywolan Gemini. Patrz SPEC_ETAP5.md, sekcja Testy.
"""

from __future__ import annotations

import httpx as httpx2
import openai
import pytest

from agent.model import MetadaneWywolania
from agent.model_azure import ModelAzure
from agent.schematy import Adres, Ekstrakcja, Klasyfikacja, Ocena, Pola
from agent.wczytywanie import CzesciDokumentu, Medium
from agent.wezly import StanGrafu, wezel_klasyfikuj


class FakeLLM:
    """Atrapa AzureChatOpenAI/langchain: `with_structured_output(...).invoke(...)`.
    Kolejne wywolania `invoke` zwracaja kolejne elementy `odpowiedzi` (parsed albo wyjatek).
    Zapamietuje kazda liste wiadomosci przekazana do invoke (do asercji tresci)."""

    def __init__(self, odpowiedzi):
        self._odpowiedzi = list(odpowiedzi)
        self.wiadomosci_otrzymane: list = []

    def with_structured_output(self, schemat, include_raw=True):
        assert include_raw is True
        return self

    def invoke(self, wiadomosci):
        self.wiadomosci_otrzymane.append(wiadomosci)
        element = self._odpowiedzi.pop(0)
        if isinstance(element, Exception):
            raise element
        return {"parsed": element, "raw": None, "parsing_error": None}


class FakeKlientOCR:
    def __init__(self, teksty: dict[bytes, str]):
        self._teksty = teksty
        self.wywolania = 0

    def begin_analyze_document(self, nazwa_modelu, body, content_type, **kwargs):
        self.wywolania += 1
        tekst = self._teksty[body]

        class _Wynik:
            def __init__(self, tekst, strony=1):
                self.content = tekst
                self.pages = [object()] * strony

        class _Poller:
            def __init__(self, wynik):
                self._wynik = wynik

            def result(self):
                return self._wynik

        return _Poller(_Wynik(tekst))


def _blad_rate_limit() -> openai.RateLimitError:
    req = httpx2.Request("POST", "https://example-azure-openai.test/")
    resp = httpx2.Response(429, request=req)
    return openai.RateLimitError("limit zapytan Azure OpenAI", response=resp, body=None)


def test_tekst_pelny_dolacza_ocr_ze_znacznikiem_i_tekst_dokumentu(tmp_path):
    bajty_medium = b"%PDF-fragment-skanu"
    klient_ocr = FakeKlientOCR({bajty_medium: "ODCZYTANY TEKST ZE SKANU"})
    model = ModelAzure(llm=FakeLLM([]), klient_ocr=klient_ocr, katalog_cache_ocr=tmp_path)

    czesci = CzesciDokumentu(
        tekst="Tresc maila: w zalaczeniu skan wniosku.",
        media=[Medium(mime_type="application/pdf", dane=bajty_medium)],
    )
    tekst_pelny = model._tekst_pelny(czesci)

    assert "Tresc maila: w zalaczeniu skan wniosku." in tekst_pelny
    assert "--- OCR:" in tekst_pelny
    assert "ODCZYTANY TEKST ZE SKANU" in tekst_pelny
    assert "KONIEC OCR" in tekst_pelny


def test_tekst_pelny_bez_mediow_i_bez_tekstu_nie_woła_ocr(tmp_path):
    klient_ocr = FakeKlientOCR({})
    model = ModelAzure(llm=FakeLLM([]), klient_ocr=klient_ocr, katalog_cache_ocr=tmp_path)

    tekst_pelny = model._tekst_pelny(CzesciDokumentu(tekst="", media=[]))

    assert klient_ocr.wywolania == 0
    assert "Dokument nie ma warstwy tekstowej" in tekst_pelny


def test_klasyfikuj_deleguje_do_llm_i_zwraca_metadane(tmp_path):
    llm = FakeLLM([Klasyfikacja(typ_dokumentu="WNIOSEK", uzasadnienie="widoczne pola wniosku")])
    model = ModelAzure(llm=llm, klient_ocr=FakeKlientOCR({}), katalog_cache_ocr=tmp_path)

    wynik, metadane = model.klasyfikuj(CzesciDokumentu(tekst="tresc wniosku", media=[]))

    assert wynik.typ_dokumentu == "WNIOSEK"
    assert isinstance(metadane, MetadaneWywolania)
    # HumanMessage dla Azure to zwykly string (tekst + OCR), nie lista czesci jak u Gemini.
    wiadomosc_uzytkownika = llm.wiadomosci_otrzymane[0][1]
    assert isinstance(wiadomosc_uzytkownika.content, str)
    assert "tresc wniosku" in wiadomosc_uzytkownika.content


def test_ekstrahuj_i_ocen_deleguja_do_llm(tmp_path):
    pola = Pola(nazwa_firmy="Testowa", nip="1234563201", adres=Adres(miasto="Warszawa"))
    llm = FakeLLM(
        [
            Ekstrakcja(pola=pola, podejrzane_instrukcje=False),
            Ocena(decyzja="AKCEPTACJA", reguly=[], uzasadnienia=[]),
        ]
    )
    model = ModelAzure(llm=llm, klient_ocr=FakeKlientOCR({}), katalog_cache_ocr=tmp_path)

    ekstrakcja, _ = model.ekstrahuj(CzesciDokumentu(tekst="tresc", media=[]))
    assert ekstrakcja.pola.nazwa_firmy == "Testowa"

    ocena, _ = model.ocen("wytyczne", "{}", [])
    assert ocena.decyzja == "AKCEPTACJA"


def test_rate_limit_azure_mapuje_sie_na_blad_wezla_tak_jak_gemini(tmp_path):
    """Nie zmienia sie agent/wezly.py: `_wywolaj_model` lapie kazdy wyjatek generycznie,
    wiec openai.RateLimitError konczy sie identycznie jak blad Gemini - 2 proby, potem
    `blad` z nazwa typu wyjatku (zawierajaca 'RateLimit', zgodnie z testem w
    ewaluacja/uruchom.py: `"RateLimit" in stan["blad"]`)."""
    llm = FakeLLM([_blad_rate_limit(), _blad_rate_limit()])
    model = ModelAzure(llm=llm, klient_ocr=FakeKlientOCR({}), katalog_cache_ocr=tmp_path)

    stan: StanGrafu = {
        "czesci": CzesciDokumentu(tekst="tresc", media=[]),
        "wywolania_llm": 0,
        "log": [],
    }
    aktualizacja = wezel_klasyfikuj(stan, model)

    assert "blad" in aktualizacja
    assert "RateLimit" in aktualizacja["blad"]
    assert aktualizacja["wywolania_llm"] == 2
