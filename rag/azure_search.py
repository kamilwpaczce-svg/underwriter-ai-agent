"""Azure AI Search dla RAG po OWU (Etap 10): wyszukiwarka hybrydowa, embedder, fabryka.

Hybryda = `search_text` (BM25 z analizatorem pl.microsoft) + `VectorizedQuery` (HNSW po
polu `wektor`, embedding zapytania z Azure OpenAI text-embedding-3-small, 1536 wymiarow).
Semantic ranker opcjonalny: `AZURE_SEARCH_SEMANTIC=1` (konfiguracja `owu-semantyczna`),
domyslnie wylaczony, bo plan Free ma miesieczny limit zapytan semantycznych.

Uwierzytelnienie: wylacznie Entra ID przez `agent.ocr_azure.zbuduj_poswiadczenie_azure`
(Managed Identity `uw-demo-id` w Container Apps, `az login` lokalnie). Usluga Search ma
`authOptions: aadOrApiKey`, wiec RBAC dziala bez kluczy. SDK importowane leniwie - modul
laduje sie bez `azure-search-documents` (testy grafu, atrapa).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from rag.fragmenty import Fragment
from rag.wyszukiwarka import TOP_K, Wyszukiwarka, WyszukiwarkaLokalna

INDEKS_DOMYSLNY = "owu-mienie-v1"
EMBEDDING_DOMYSLNY = "text-embedding-3-small"
WYMIARY_WEKTORA = 1536
KONFIGURACJA_SEMANTYCZNA = "owu-semantyczna"
POLA_ZWRACANE = ["id", "paragraf", "ustep", "tytul", "tresc"]

Embedder = Callable[[list[str]], list[list[float]]]


class BrakKonfiguracjiWyszukiwarki(RuntimeError):
    """Brak zmiennej srodowiskowej albo niepoprawna wartosc WYSZUKIWARKA."""


def _wymagana(srodowisko: Mapping[str, str], nazwa: str) -> str:
    wartosc = srodowisko.get(nazwa)
    if not wartosc:
        raise BrakKonfiguracjiWyszukiwarki(f"Brak zmiennej srodowiskowej {nazwa}.")
    return wartosc


def zbuduj_embedder(srodowisko: Mapping[str, str] | None = None) -> Embedder:
    """Funkcja `teksty -> wektory` na Azure OpenAI (to samo konto co gpt-5-mini)."""
    from azure.identity import get_bearer_token_provider
    from openai import AzureOpenAI

    from agent.model_azure import DOMYSLNA_API_VERSION
    from agent.ocr_azure import ZAKRES_TOKENU_COGNITIVE, zbuduj_poswiadczenie_azure

    srodowisko = os.environ if srodowisko is None else srodowisko
    klient = AzureOpenAI(
        azure_endpoint=_wymagana(srodowisko, "AZURE_OPENAI_ENDPOINT"),
        api_version=srodowisko.get("AZURE_OPENAI_API_VERSION") or DOMYSLNA_API_VERSION,
        azure_ad_token_provider=get_bearer_token_provider(zbuduj_poswiadczenie_azure(), ZAKRES_TOKENU_COGNITIVE),
        max_retries=1,
        timeout=60,
    )
    deployment = srodowisko.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or EMBEDDING_DOMYSLNY

    def embeduj(teksty: list[str]) -> list[list[float]]:
        odpowiedz = klient.embeddings.create(model=deployment, input=teksty)
        return [element.embedding for element in sorted(odpowiedz.data, key=lambda e: e.index)]

    return embeduj


class WyszukiwarkaAzure:
    """`klient` - `azure.search.documents.SearchClient` (albo atrapa z metoda `search(**kwargs)`)."""

    nazwa = "azure"

    def __init__(self, klient: Any, embeduj: Embedder, semantyczna: bool = False):
        self._klient = klient
        self._embeduj = embeduj
        self.semantyczna = semantyczna

    def parametry_zapytania(self, zapytanie: str, k: int) -> dict[str, Any]:
        from azure.search.documents.models import VectorizedQuery

        wektor = self._embeduj([zapytanie])[0]
        parametry: dict[str, Any] = {
            "search_text": zapytanie,
            "vector_queries": [VectorizedQuery(vector=wektor, k_nearest_neighbors=k, fields="wektor")],
            "select": POLA_ZWRACANE,
            "top": k,
        }
        if self.semantyczna:
            parametry["query_type"] = "semantic"
            parametry["semantic_configuration_name"] = KONFIGURACJA_SEMANTYCZNA
        return parametry

    def szukaj(self, zapytanie: str, k: int = TOP_K) -> list[Fragment]:
        wyniki = self._klient.search(**self.parametry_zapytania(zapytanie, k))
        return [
            Fragment(
                id=d["id"], paragraf=int(d["paragraf"]), ustep=int(d["ustep"]), tytul=d["tytul"], tresc=d["tresc"]
            )
            for d in wyniki
        ][:k]


def zbuduj_klienta_wyszukiwania(srodowisko: Mapping[str, str]):
    from azure.search.documents import SearchClient

    from agent.ocr_azure import zbuduj_poswiadczenie_azure

    return SearchClient(
        endpoint=_wymagana(srodowisko, "AZURE_SEARCH_ENDPOINT"),
        index_name=srodowisko.get("AZURE_SEARCH_INDEX") or INDEKS_DOMYSLNY,
        credential=zbuduj_poswiadczenie_azure(),
    )


def zbuduj_wyszukiwarke(srodowisko: Mapping[str, str] | None = None) -> Wyszukiwarka:
    """`WYSZUKIWARKA=azure|lokalna|qdrant`; bez tej zmiennej: `azure`, gdy jest
    `AZURE_SEARCH_ENDPOINT`, inaczej `lokalna`. Zla wartosc albo brak wymaganej konfiguracji
    (np. `azure` bez endpointu) -> wyjatek przy starcie (nie cichy powrot do BM25)."""
    srodowisko = os.environ if srodowisko is None else srodowisko
    rodzaj = (srodowisko.get("WYSZUKIWARKA") or "").strip().lower()
    if not rodzaj:
        rodzaj = "azure" if srodowisko.get("AZURE_SEARCH_ENDPOINT") else "lokalna"
    if rodzaj == "lokalna":
        return WyszukiwarkaLokalna()
    if rodzaj == "qdrant":
        from rag.qdrant_search import zbuduj_wyszukiwarke_qdrant

        return zbuduj_wyszukiwarke_qdrant(srodowisko)
    if rodzaj != "azure":
        raise BrakKonfiguracjiWyszukiwarki(f"WYSZUKIWARKA={rodzaj!r} - dozwolone: azure, lokalna, qdrant.")
    return WyszukiwarkaAzure(
        zbuduj_klienta_wyszukiwania(srodowisko),
        zbuduj_embedder(srodowisko),
        semantyczna=srodowisko.get("AZURE_SEARCH_SEMANTIC") == "1",
    )
