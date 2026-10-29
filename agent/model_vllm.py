"""ModelVLLM - implementacja `ModelAgenta` (Protocol w `agent/model.py`) dla modelu
open-source serwowanego przez vLLM (API zgodne z OpenAI) na wynajetym GPU (RunPod).
Patrz SPEC_ETAP11.md.

Decyzja projektowa: dziedziczenie po `ModelAzure` (agent/model_azure.py), nie
kompozycja. ModelAzure juz implementuje dokladnie to, czego potrzebuje trzeci dostawca:
OCR mediow przez Document Intelligence (`agent/ocr_azure.py`, ten sam zasob demo - ten
etap wymienia TYLKO dostawce LLM, nie dostawce OCR) + `_tekst_pelny` (zamiana mediow na
tekst, do modelu jezykowego idzie wylacznie tekst) + wszystkie metody `ModelAgenta`
(klasyfikuj/ekstrahuj/ocen/ekstrahuj_szkode/ocen_pokrycie), ktore wolaja wspolne funkcje
`_wywolaj_*` z agent/model.py na `self._llm`. Jedyna faktyczna roznica miedzy ModelAzure
i ModelVLLM to budowa `self._llm` (ChatOpenAI wskazujacy na serwer vLLM zamiast
AzureChatOpenAI z Entra ID) i zrodlo konfiguracji (zmienne VLLM_* zamiast AZURE_OPENAI_*).
Kompozycja wymagalaby przepisania _tekst_pelny/klasyfikuj/ekstrahuj/... linia w linie -
czysta duplikacja bez zadnej korzysci, bo ModelVLLM i tak w pelni spelnia kontrakt
ModelAgenta przez ModelAzure.

Bezpieczenstwo kluczy: klucz API vLLM nigdy nie jest logowany, wypisywany na stdout ani
zapisywany do wynikow - identycznie jak klucz Gemini w agent/model.py. W przeciwienstwie
do Azure (wylacznie Entra ID, zero kluczy) serwer vLLM na RunPod uzywa prostego klucza
API zgodnego z OpenAI (`--api-key` przy starcie vLLM) albo dziala bez klucza.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.model_azure import ModelAzure

DOMYSLNA_METODA_STRUCTURED = "json_schema"
METODY_STRUCTURED_DOZWOLONE = {"json_schema", "function_calling", "json_mode"}
# Limit dlugosci odpowiedzi. Pomiar 2026-10-17 (Bielik 11B, json_schema): bez limitu czesc
# zapytan nie konczyla sie - model generowal ~7 tys. tokenow (~2 min GPU) do timeoutu
# klienta, a wezel grafu ponawial. Poprawny JSON wyniku ma najwyzej kilkaset tokenow, wiec
# 2048 zamienia zapetlenie w szybki blad parsowania zamiast minut placonych za GPU.
DOMYSLNY_MAX_TOKENS = 2048


class BrakKonfiguracjiVLLM(RuntimeError):
    """Brak wymaganej konfiguracji vLLM (base_url/model/klucz) - komunikat nigdy nie
    zawiera wartosci klucza API."""


def _wczytaj_klucz_vllm() -> str:
    """VLLM_API_KEY > pierwsza linia pliku z VLLM_API_KEY_FILE > "EMPTY" gdy jawnie
    VLLM_BEZ_KLUCZA=1 (serwer vLLM uruchomiony bez --api-key). W kazdym innym przypadku -
    BrakKonfiguracjiVLLM, zeby nie wyslac przypadkiem pustego/domyslnego klucza do
    serwera, ktory faktycznie klucza wymaga."""
    klucz = os.environ.get("VLLM_API_KEY")
    if klucz and klucz.strip():
        return klucz.strip()

    sciezka_klucza = os.environ.get("VLLM_API_KEY_FILE")
    if sciezka_klucza:
        try:
            tresc = Path(sciezka_klucza).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise BrakKonfiguracjiVLLM(
                f"Nie udalo sie odczytac pliku klucza VLLM_API_KEY_FILE ({sciezka_klucza}): {e}"
            ) from e
        if tresc:
            return tresc

    if os.environ.get("VLLM_BEZ_KLUCZA") == "1":
        return "EMPTY"

    raise BrakKonfiguracjiVLLM(
        "Brak klucza API vLLM. Ustaw VLLM_API_KEY, VLLM_API_KEY_FILE (sciezka do pliku "
        "z kluczem) albo - gdy serwer vLLM naprawde dziala bez --api-key - VLLM_BEZ_KLUCZA=1."
    )


class _ChatOpenAIZMetodaStructured:
    """Cienki wrapper na `langchain_openai.ChatOpenAI`: wstrzykuje `method` do
    `with_structured_output`, nie dotykajac `agent/model.py::_wywolaj_structured_llm`
    (wspolne dla kazdego dostawcy, wola `llm.with_structured_output(schemat,
    include_raw=True)` BEZ `method` - zgodnie z poleceniem tej funkcji sie nie zmienia).

    Zweryfikowane w zrodle zainstalowanej wersji langchain-openai==1.7.0
    (.venv/Lib/site-packages/langchain_openai/chat_models/base.py,
    `BaseChatOpenAI.with_structured_output`): domyslna wartosc `method` w tej bibliotece
    to "function_calling", nie "json_schema" - dla vLLM metoda ma byc konfigurowalna
    (VLLM_STRUCTURED_METHOD, domyslnie "json_schema"), wiec trzeba ja jawnie przekazac.

    Kompozycja (nie dziedziczenie po ChatOpenAI): ChatOpenAI to model pydantic -
    podklasa z dodatkowym polem wymagalaby PrivateAttr i nadpisania __init__ tylko po
    to, zeby dolozyc jedno pole tekstowe. `__getattr__` deleguje tu wszystko inne
    (invoke, with_structured_output bez wstrzyknietej metody, atrybuty typu
    `model_name`) do opakowanego obiektu bez duplikowania API ChatOpenAI."""

    def __init__(self, llm: Any, metoda_structured_output: str):
        self._llm = llm
        self._metoda_structured_output = metoda_structured_output

    def with_structured_output(self, schema=None, **kwargs):
        kwargs.setdefault("method", self._metoda_structured_output)
        return self._llm.with_structured_output(schema, **kwargs)

    def __getattr__(self, nazwa):
        return getattr(self._llm, nazwa)


class ModelVLLM(ModelAzure):
    """Implementacja `ModelAgenta` dla modelu open-source (np. Bielik 11B, Qwen3-8B)
    serwowanego przez vLLM na wynajetym GPU (RunPod), za API zgodnym z OpenAI
    (`langchain_openai.ChatOpenAI` wskazujacy na `base_url` serwera vLLM zamiast
    `AzureChatOpenAI`). OCR mediow i reszta logiki - patrz docstring modulu.

    `llm` i `klient_ocr` mozna wstrzyknac (testy jednostkowe bez sieci), dokladnie jak
    w `ModelAzure` - wtedy walidacja `base_url`/klucza jest pomijana (nie ma czego
    walidowac, do sieci i tak nie dojdzie), identycznie jak pominiecie
    `AZURE_OPENAI_ENDPOINT` w ModelAzure przy wstrzyknietym `llm`."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        metoda_structured: str | None = None,
        wylacz_myslenie: bool | None = None,
        docint_endpoint: str | None = None,
        katalog_cache_ocr: str | Path | None = None,
        llm: Any = None,
        klient_ocr: Any = None,
    ):
        nazwa_modelu = model or os.environ.get("VLLM_MODEL")

        self.metoda_structured_output = metoda_structured or os.environ.get(
            "VLLM_STRUCTURED_METHOD", DOMYSLNA_METODA_STRUCTURED
        )
        if self.metoda_structured_output not in METODY_STRUCTURED_DOZWOLONE:
            raise BrakKonfiguracjiVLLM(
                f"Nieznana metoda structured output '{self.metoda_structured_output}'. "
                f"Dozwolone: {sorted(METODY_STRUCTURED_DOZWOLONE)}."
            )

        # Domyslnie wylaczamy tryb "myslenia" modeli typu Qwen3 (enable_thinking=False w
        # chat_template_kwargs) - ewaluacja structured-output nie potrzebuje lancucha
        # rozumowania w odpowiedzi. VLLM_MYSLENIE=1 wylacza TA wstawke (zostawia domyslne
        # zachowanie modelu/szablonu czatu).
        if wylacz_myslenie is None:
            wylacz_myslenie = os.environ.get("VLLM_MYSLENIE") != "1"

        self.max_tokens = int(os.environ.get("VLLM_MAX_TOKENS") or DOMYSLNY_MAX_TOKENS)

        if llm is None:
            if not nazwa_modelu:
                raise BrakKonfiguracjiVLLM(
                    "Brak zmiennej srodowiskowej VLLM_MODEL (albo parametru model)."
                )
            vllm_base_url = base_url or os.environ.get("VLLM_BASE_URL")
            if not vllm_base_url:
                raise BrakKonfiguracjiVLLM(
                    "Brak zmiennej srodowiskowej VLLM_BASE_URL (albo parametru base_url), "
                    "np. https://<pod>-8000.proxy.runpod.net/v1."
                )
            klucz = api_key or _wczytaj_klucz_vllm()

            from langchain_openai import ChatOpenAI

            extra_body = (
                {"chat_template_kwargs": {"enable_thinking": False}} if wylacz_myslenie else None
            )
            # max_retries=1, timeout=180, temperature=0: te same wartosci co ModelAzure -
            # jeden blad kosztuje najwyzej 2 platne/platne-czasowo zapytania (ponowienie
            # robi wezel grafu), nie wiecej.
            llm_bazowy = ChatOpenAI(
                base_url=vllm_base_url,
                api_key=klucz,
                model=nazwa_modelu,
                temperature=0,
                max_retries=1,
                timeout=180,
                max_tokens=self.max_tokens,
                extra_body=extra_body,
            )
            llm = _ChatOpenAIZMetodaStructured(llm_bazowy, self.metoda_structured_output)

        # llm zawsze niepuste w tym miejscu -> ModelAzure.__init__ nie dotyka sieci ani
        # AZURE_OPENAI_ENDPOINT (ten sam wczesny-return co przy wstrzyknietym llm w testach
        # test_model_azure.py).
        super().__init__(
            deployment=nazwa_modelu,
            docint_endpoint=docint_endpoint,
            katalog_cache_ocr=katalog_cache_ocr,
            llm=llm,
            klient_ocr=klient_ocr,
        )
        # Nadpisanie po ModelAzure.__init__: bez tego `nazwa_modelu=None` (llm wstrzykniety
        # w tescie bez podania modelu) dostalby domyslny DEPLOYMENT Azure ("gpt-5-mini") -
        # myloca nazwa dla modelu vLLM. `myslenie` dla ModelAzure to reasoning_effort
        # Azure ("low" domyslnie) - dla vLLM nie ma odpowiednika, ewaluacja/uruchom.py
        # dolacza je do nazwy modelu tylko gdy truthy, wiec None = nic nie dolacza.
        self.nazwa_modelu = nazwa_modelu
        self.myslenie = None

    def analizuj_zdjecie(self, obraz: bytes, mime_type: str):
        # Etap 23: modele tekstowe vLLM (Bielik, Qwen3-8B) nie przyjmuja obrazow - jawny blad, bez wywolania.
        raise NotImplementedError("ModelVLLM nie obsluguje zdjec (model tekstowy) - uzyj ModelAzure.")
