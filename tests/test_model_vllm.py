"""Testy `agent/model_vllm.py` - zero sieci, zero prawdziwego serwera vLLM.
Wzorowane na tests/test_model_azure.py. Patrz SPEC_ETAP11.md.
"""

from __future__ import annotations

import pytest

from agent.model import MetadaneWywolania
from agent.model_vllm import (
    DOMYSLNA_METODA_STRUCTURED,
    BrakKonfiguracjiVLLM,
    ModelVLLM,
    _ChatOpenAIZMetodaStructured,
    _wczytaj_klucz_vllm,
)
from agent.schematy import Adres, Ekstrakcja, Klasyfikacja, Pola
from agent.wczytywanie import CzesciDokumentu, Medium

ZMIENNE_VLLM = [
    "VLLM_BASE_URL",
    "VLLM_MODEL",
    "VLLM_API_KEY",
    "VLLM_API_KEY_FILE",
    "VLLM_BEZ_KLUCZA",
    "VLLM_STRUCTURED_METHOD",
    "VLLM_MYSLENIE",
]


@pytest.fixture(autouse=True)
def _czysta_konfiguracja_vllm(monkeypatch):
    """Kazdy test startuje bez zadnej zmiennej VLLM_* - konfiguracja testowa nie
    przecieka miedzy testami ani z realnego srodowiska uruchamiajacego pytest."""
    for nazwa in ZMIENNE_VLLM:
        monkeypatch.delenv(nazwa, raising=False)


class FakeLLM:
    """Atrapa llm (jak w test_model_azure.py): `with_structured_output(...).invoke(...)`.
    Zapamietuje kazda liste wiadomosci i kwargs przekazane do with_structured_output."""

    def __init__(self, odpowiedzi):
        self._odpowiedzi = list(odpowiedzi)
        self.wiadomosci_otrzymane: list = []
        self.wywolania_with_structured_output: list = []

    def with_structured_output(self, schemat, **kwargs):
        self.wywolania_with_structured_output.append({"schemat": schemat, **kwargs})
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


# --- Konfiguracja: base_url/model/klucz -------------------------------------------------


def test_brak_model_podnosi_wyjatek(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "https://przyklad-pod-8000.proxy.runpod.net/v1")
    with pytest.raises(BrakKonfiguracjiVLLM, match="VLLM_MODEL"):
        ModelVLLM()


def test_brak_base_url_podnosi_wyjatek(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "Qwen/Qwen3-8B")
    with pytest.raises(BrakKonfiguracjiVLLM, match="VLLM_BASE_URL"):
        ModelVLLM()


def test_brak_konfiguracji_pomijana_gdy_llm_wstrzykniety(tmp_path):
    """Jak ModelAzure(llm=...): brak VLLM_BASE_URL/VLLM_MODEL nie przeszkadza, gdy llm
    jest wstrzykniety (testy jednostkowe bez sieci) - do sieci i tak nie dojdzie."""
    model = ModelVLLM(
        model="qwen-test", llm=FakeLLM([]), klient_ocr=FakeKlientOCR({}), katalog_cache_ocr=tmp_path
    )
    assert model.nazwa_modelu == "qwen-test"
    assert model.myslenie is None


# --- Klucz API: VLLM_API_KEY / VLLM_API_KEY_FILE / VLLM_BEZ_KLUCZA ----------------------


def test_klucz_z_env(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "  tajny-klucz  ")
    assert _wczytaj_klucz_vllm() == "tajny-klucz"


def test_klucz_z_pliku(tmp_path, monkeypatch):
    plik = tmp_path / "klucz_vllm.txt"
    plik.write_text("klucz-z-pliku\n", encoding="utf-8")
    monkeypatch.setenv("VLLM_API_KEY_FILE", str(plik))
    assert _wczytaj_klucz_vllm() == "klucz-z-pliku"


def test_klucz_env_ma_pierwszenstwo_przed_plikiem(tmp_path, monkeypatch):
    plik = tmp_path / "klucz_vllm.txt"
    plik.write_text("klucz-z-pliku", encoding="utf-8")
    monkeypatch.setenv("VLLM_API_KEY_FILE", str(plik))
    monkeypatch.setenv("VLLM_API_KEY", "klucz-z-env")
    assert _wczytaj_klucz_vllm() == "klucz-z-env"


def test_brak_klucza_bez_vllm_bez_klucza_podnosi_wyjatek():
    with pytest.raises(BrakKonfiguracjiVLLM, match="klucz"):
        _wczytaj_klucz_vllm()


def test_vllm_bez_klucza_zwraca_empty(monkeypatch):
    monkeypatch.setenv("VLLM_BEZ_KLUCZA", "1")
    assert _wczytaj_klucz_vllm() == "EMPTY"


def test_vllm_bez_klucza_niejawne_nie_wystarcza(monkeypatch):
    """VLLM_BEZ_KLUCZA musi byc dokladnie '1' - inna wartosc to wciaz brak konfiguracji,
    zeby literowka nie wylaczyla przypadkiem autoryzacji po cichu."""
    monkeypatch.setenv("VLLM_BEZ_KLUCZA", "true")
    with pytest.raises(BrakKonfiguracjiVLLM):
        _wczytaj_klucz_vllm()


# --- Metoda structured output: wrapper wokol ChatOpenAI ---------------------------------


def test_wrapper_wstrzykuje_domyslna_metode():
    llm = FakeLLM([])
    wrapper = _ChatOpenAIZMetodaStructured(llm, "json_schema")

    wrapper.with_structured_output(Klasyfikacja, include_raw=True)

    assert llm.wywolania_with_structured_output == [
        {"schemat": Klasyfikacja, "include_raw": True, "method": "json_schema"}
    ]


def test_wrapper_nie_nadpisuje_jawnie_podanej_metody():
    llm = FakeLLM([])
    wrapper = _ChatOpenAIZMetodaStructured(llm, "json_schema")

    wrapper.with_structured_output(Klasyfikacja, include_raw=True, method="function_calling")

    assert llm.wywolania_with_structured_output[0]["method"] == "function_calling"


def test_wrapper_deleguje_atrybuty_do_opakowanego_llm():
    llm = FakeLLM([])
    llm.model_name = "qwen-test"
    wrapper = _ChatOpenAIZMetodaStructured(llm, "json_schema")

    assert wrapper.model_name == "qwen-test"


def test_nieznana_metoda_structured_podnosi_wyjatek(tmp_path):
    with pytest.raises(BrakKonfiguracjiVLLM, match="Nieznana metoda"):
        ModelVLLM(
            model="qwen-test",
            metoda_structured="zgadnij",
            llm=FakeLLM([]),
            klient_ocr=FakeKlientOCR({}),
            katalog_cache_ocr=tmp_path,
        )


def test_metoda_structured_domyslna_to_json_schema(tmp_path):
    model = ModelVLLM(
        model="qwen-test", llm=FakeLLM([]), klient_ocr=FakeKlientOCR({}), katalog_cache_ocr=tmp_path
    )
    assert model.metoda_structured_output == DOMYSLNA_METODA_STRUCTURED


def test_metoda_structured_z_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VLLM_STRUCTURED_METHOD", "function_calling")
    model = ModelVLLM(
        model="qwen-test", llm=FakeLLM([]), klient_ocr=FakeKlientOCR({}), katalog_cache_ocr=tmp_path
    )
    assert model.metoda_structured_output == "function_calling"


# --- extra_body: wylaczanie trybu myslenia (Qwen3) --------------------------------------


def test_extra_body_domyslnie_wylacza_myslenie(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "Qwen/Qwen3-8B")
    monkeypatch.setenv("VLLM_BASE_URL", "https://przyklad-pod-8000.proxy.runpod.net/v1")
    monkeypatch.setenv("VLLM_BEZ_KLUCZA", "1")

    model = ModelVLLM()

    assert model._llm._llm.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_extra_body_puste_gdy_vllm_myslenie_1(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "Qwen/Qwen3-8B")
    monkeypatch.setenv("VLLM_BASE_URL", "https://przyklad-pod-8000.proxy.runpod.net/v1")
    monkeypatch.setenv("VLLM_BEZ_KLUCZA", "1")
    monkeypatch.setenv("VLLM_MYSLENIE", "1")

    model = ModelVLLM()

    assert model._llm._llm.extra_body is None


def test_bazowy_llm_dostaje_base_url_model_i_klucz(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "Qwen/Qwen3-8B")
    monkeypatch.setenv("VLLM_BASE_URL", "https://przyklad-pod-8000.proxy.runpod.net/v1")
    monkeypatch.setenv("VLLM_API_KEY", "tajny-klucz")

    model = ModelVLLM()

    llm_bazowy = model._llm._llm
    assert llm_bazowy.openai_api_base == "https://przyklad-pod-8000.proxy.runpod.net/v1"
    assert llm_bazowy.model_name == "Qwen/Qwen3-8B"
    assert llm_bazowy.temperature == 0
    assert llm_bazowy.max_retries == 1


def test_max_tokens_domyslny_i_z_env(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "bielik-11b-v3")
    monkeypatch.setenv("VLLM_BASE_URL", "https://przyklad-pod-8000.proxy.runpod.net/v1")
    monkeypatch.setenv("VLLM_BEZ_KLUCZA", "1")

    model = ModelVLLM()
    assert model.max_tokens == 2048
    assert model._llm._llm.max_tokens == 2048

    monkeypatch.setenv("VLLM_MAX_TOKENS", "512")
    model = ModelVLLM()
    assert model._llm._llm.max_tokens == 512


# --- OCR mediow przez wstrzykniety klient (tekst do llm, bajty nie) ---------------------


def test_klasyfikuj_z_ocr_wysyla_tekst_nie_bajty_do_llm(tmp_path):
    bajty_medium = b"%PDF-fragment-skanu-vllm"
    klient_ocr = FakeKlientOCR({bajty_medium: "ODCZYTANY TEKST ZE SKANU VLLM"})
    llm = FakeLLM([Klasyfikacja(typ_dokumentu="WNIOSEK", uzasadnienie="widoczne pola wniosku")])
    model = ModelVLLM(model="qwen-test", llm=llm, klient_ocr=klient_ocr, katalog_cache_ocr=tmp_path)

    czesci = CzesciDokumentu(
        tekst="Tresc maila: w zalaczeniu skan wniosku.",
        media=[Medium(mime_type="application/pdf", dane=bajty_medium)],
    )
    wynik, metadane = model.klasyfikuj(czesci)

    assert wynik.typ_dokumentu == "WNIOSEK"
    assert isinstance(metadane, MetadaneWywolania)
    assert klient_ocr.wywolania == 1

    wiadomosc_uzytkownika = llm.wiadomosci_otrzymane[0][1]
    assert isinstance(wiadomosc_uzytkownika.content, str)
    assert "ODCZYTANY TEKST ZE SKANU VLLM" in wiadomosc_uzytkownika.content
    assert "Tresc maila: w zalaczeniu skan wniosku." in wiadomosc_uzytkownika.content
    # Bajty medium nie trafiaja do LLM - tylko tekst OCR (to samo zalozenie co ModelAzure).
    assert bajty_medium not in wiadomosc_uzytkownika.content.encode("utf-8", errors="ignore")


def test_ekstrahuj_deleguje_do_llm(tmp_path):
    pola = Pola(nazwa_firmy="Testowa", nip="1234563201", adres=Adres(miasto="Warszawa"))
    llm = FakeLLM([Ekstrakcja(pola=pola, podejrzane_instrukcje=False)])
    model = ModelVLLM(
        model="qwen-test", llm=llm, klient_ocr=FakeKlientOCR({}), katalog_cache_ocr=tmp_path
    )

    ekstrakcja, _ = model.ekstrahuj(CzesciDokumentu(tekst="tresc", media=[]))

    assert ekstrakcja.pola.nazwa_firmy == "Testowa"


# --- ewaluacja/uruchom.py: _zbuduj_model("vllm") ----------------------------------------


def test_zbuduj_model_ewaluacja_vllm(monkeypatch):
    from ewaluacja.uruchom import _zbuduj_model

    monkeypatch.setenv("VLLM_MODEL", "Qwen/Qwen3-8B")
    monkeypatch.setenv("VLLM_BASE_URL", "https://przyklad-pod-8000.proxy.runpod.net/v1")
    monkeypatch.setenv("VLLM_BEZ_KLUCZA", "1")

    model = _zbuduj_model(uzyj_atrapy=False, nazwa_modelu=None, dostawca="vllm")

    assert isinstance(model, ModelVLLM)
    assert model.nazwa_modelu == "Qwen/Qwen3-8B"
    assert model.myslenie is None


def test_zbuduj_model_ewaluacja_atrapa_ma_pierwszenstwo_przed_vllm():
    from ewaluacja.atrapa import ModelAtrapa
    from ewaluacja.uruchom import _zbuduj_model

    model = _zbuduj_model(uzyj_atrapy=True, nazwa_modelu=None, dostawca="vllm")

    assert isinstance(model, ModelAtrapa)
