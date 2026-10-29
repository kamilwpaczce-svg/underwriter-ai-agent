"""Tworzy/aktualizuje indeks Azure AI Search z fragmentami OWU (Etap 10).

    python rag/indeksuj_owu.py                       # indeks z AZURE_SEARCH_INDEX (domyslnie owu-mienie-v1)
    python rag/indeksuj_owu.py --zapytanie "pozar hali"

Idempotentny: definicja indeksu przez create_or_update, dokumenty przez merge_or_upload po `id`,
fragmenty, ktorych nie ma juz w OWU, sa usuwane. Wymaga roli Search Service Contributor
(definicja indeksu) i Search Index Data Contributor (dokumenty) na koncie z `az login`.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.azure_search import (  # noqa: E402
    INDEKS_DOMYSLNY,
    KONFIGURACJA_SEMANTYCZNA,
    WYMIARY_WEKTORA,
    Embedder,
    WyszukiwarkaAzure,
    zbuduj_embedder,
    zbuduj_klienta_wyszukiwania,
)
from rag.fragmenty import SCIEZKA_OWU, Fragment, podziel_owu, wersja_owu  # noqa: E402

PACZKA_EMBEDDINGOW = 16


def definicja_indeksu(nazwa: str = INDEKS_DOMYSLNY):
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SearchableField,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    return SearchIndex(
        name=nazwa,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SearchableField(name="tresc", analyzer_name="pl.microsoft"),
            SimpleField(name="paragraf", type=SearchFieldDataType.Int32, filterable=True),
            SimpleField(name="ustep", type=SearchFieldDataType.Int32, filterable=True),
            SearchableField(name="tytul", filterable=True, analyzer_name="pl.microsoft"),
            SearchField(
                name="wektor",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=WYMIARY_WEKTORA,
                vector_search_profile_name="profil-wektor",
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw-domyslny")],
            profiles=[VectorSearchProfile(name="profil-wektor", algorithm_configuration_name="hnsw-domyslny")],
        ),
        semantic_search=SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name=KONFIGURACJA_SEMANTYCZNA,
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=SemanticField(field_name="tytul"),
                        content_fields=[SemanticField(field_name="tresc")],
                    ),
                )
            ]
        ),
    )


def dokumenty_do_indeksu(fragmenty: list[Fragment], embeduj: Embedder) -> list[dict]:
    wektory: list[list[float]] = []
    for start in range(0, len(fragmenty), PACZKA_EMBEDDINGOW):
        wektory.extend(embeduj([f.tresc for f in fragmenty[start : start + PACZKA_EMBEDDINGOW]]))
    if len(wektory) != len(fragmenty):
        raise RuntimeError(f"Embedder zwrocil {len(wektory)} wektorow dla {len(fragmenty)} fragmentow.")
    return [
        {"id": f.id, "paragraf": f.paragraf, "ustep": f.ustep, "tytul": f.tytul, "tresc": f.tresc, "wektor": w}
        for f, w in zip(fragmenty, wektory)
    ]


def indeksuj(klient_indeksow, klient_wyszukiwania, embeduj: Embedder, nazwa_indeksu: str = INDEKS_DOMYSLNY,
             sciezka_owu: str | Path = SCIEZKA_OWU) -> dict:
    fragmenty = podziel_owu(sciezka_owu)
    klient_indeksow.create_or_update_index(definicja_indeksu(nazwa_indeksu))
    dokumenty = dokumenty_do_indeksu(fragmenty, embeduj)
    wyniki = klient_wyszukiwania.merge_or_upload_documents(documents=dokumenty)
    nieudane = [w.key for w in wyniki if not w.succeeded]
    if nieudane:
        raise RuntimeError(f"Nie zaindeksowano fragmentow: {nieudane}")
    aktualne = {f.id for f in fragmenty}
    istniejace = {d["id"] for d in klient_wyszukiwania.search(search_text="*", select=["id"], top=1000)}
    nadmiarowe = sorted(istniejace - aktualne)
    if nadmiarowe:
        klient_wyszukiwania.delete_documents(documents=[{"id": i} for i in nadmiarowe])
    return {"fragmenty": len(fragmenty), "usuniete": nadmiarowe, "wersja_owu": wersja_owu(sciezka_owu)}


def _czekaj_na_indeksacje(klient_wyszukiwania, oczekiwane: int, limit_s: float = 60.0) -> None:
    """Azure AI Search indeksuje z opoznieniem - bez czekania zapytanie testowe tuz po
    pierwszym uploadzie potrafi zwrocic [] i skrypt konczy sie kodem 1 mimo poprawnej indeksacji."""
    koniec = time.monotonic() + limit_s
    while (liczba := klient_wyszukiwania.get_document_count()) < oczekiwane and time.monotonic() < koniec:
        time.sleep(2)
    print(f"Dokumentow w indeksie: {liczba}/{oczekiwane}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Indeksuje OWU w Azure AI Search.")
    parser.add_argument("--zapytanie", default="pożar hali produkcyjnej", help="Zapytanie testowe po indeksacji.")
    argumenty = parser.parse_args(argv)

    from azure.search.documents.indexes import SearchIndexClient

    from agent.ocr_azure import zbuduj_poswiadczenie_azure

    srodowisko = dict(os.environ)
    nazwa = srodowisko.get("AZURE_SEARCH_INDEX") or INDEKS_DOMYSLNY
    klient_wyszukiwania = zbuduj_klienta_wyszukiwania(srodowisko)
    klient_indeksow = SearchIndexClient(endpoint=srodowisko["AZURE_SEARCH_ENDPOINT"], credential=zbuduj_poswiadczenie_azure())
    embeduj = zbuduj_embedder(srodowisko)

    wynik = indeksuj(klient_indeksow, klient_wyszukiwania, embeduj, nazwa)
    print(f"Indeks {nazwa}: {wynik['fragmenty']} fragmentow, wersja OWU {wynik['wersja_owu']}, "
          f"usuniete: {wynik['usuniete'] or 'brak'}")
    _czekaj_na_indeksacje(klient_wyszukiwania, wynik["fragmenty"])
    wyszukiwarka = WyszukiwarkaAzure(klient_wyszukiwania, embeduj, semantyczna=srodowisko.get("AZURE_SEARCH_SEMANTIC") == "1")
    trafienia = wyszukiwarka.szukaj(argumenty.zapytanie)
    print(f"Zapytanie testowe {argumenty.zapytanie!r}: {[f.id for f in trafienia]}")
    return 0 if trafienia else 1


if __name__ == "__main__":
    sys.exit(main())
