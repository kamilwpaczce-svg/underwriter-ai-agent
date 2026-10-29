"""Tworzy/aktualizuje kolekcje Qdrant z fragmentami OWU (Etap 12) - trzecia wyszukiwarka obok
Azure AI Search i lokalnego BM25. Osobny skrypt od `rag/indeksuj_owu.py` (nie rozszerza go) -
Qdrant ma inny klient i inny ksztalt dokumentu (wektor gesty + rzadki w jednym punkcie), wiec
dopisanie tego do skryptu Azure zmieszaloby dwa niezalezne backendy w jednej funkcji `main`.

    python rag/indeksuj_owu_qdrant.py                       # kolekcja z QDRANT_COLLECTION (domyslnie jak Azure)
    python rag/indeksuj_owu_qdrant.py --zapytanie "pożar hali"

Idempotentny: punkty maja deterministyczne id (`id_punktu`, UUID5 z `Fragment.id`), upsert
nadpisuje bez duplikatow; fragmenty, ktorych nie ma juz w OWU, sa usuwane. Embeddingi gestego
wektora licza sie przez to samo Azure OpenAI `text-embedding-3-small` co `rag/indeksuj_owu.py`
(uczciwe porownanie silnika wyszukiwania, nie modelu embeddingow) i sa cachowane na dysku
(`rag/cache_embeddingow.py`) - wielokrotne odpalenie tego skryptu (albo porownania obok
indeksu Azure) nie placi drugi raz za te same fragmenty OWU.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.azure_search import zbuduj_embedder  # noqa: E402
from rag.cache_embeddingow import embedder_z_cache  # noqa: E402
from rag.fragmenty import SCIEZKA_OWU, Fragment, podziel_owu, wersja_owu  # noqa: E402
from rag.qdrant_search import (  # noqa: E402
    KOLEKCJA_DOMYSLNA,
    WyszukiwarkaQdrant,
    definicja_kolekcji,
    id_punktu,
    punkt_z_fragmentu,
    zbuduj_klienta_qdrant,
)
PLIK_CACHE_DOMYSLNY = ROOT / ".cache_embeddingow" / "text-embedding-3-small.json"


def punkty_do_indeksu(fragmenty: list[Fragment], embeduj, wersja: str) -> list:
    return [punkt_z_fragmentu(f, embeduj([f.tresc])[0], wersja) for f in fragmenty]


def _wszystkie_id_punktow(klient, kolekcja: str) -> set[str]:
    id_punktow: set[str] = set()
    przesuniecie = None
    while True:
        punkty, przesuniecie = klient.scroll(
            collection_name=kolekcja, limit=256, offset=przesuniecie, with_payload=False, with_vectors=False
        )
        id_punktow.update(str(p.id) for p in punkty)
        if przesuniecie is None:
            break
    return id_punktow


def indeksuj(klient, embeduj, nazwa_kolekcji: str = KOLEKCJA_DOMYSLNA, sciezka_owu: str | Path = SCIEZKA_OWU) -> dict:
    fragmenty = podziel_owu(sciezka_owu)
    if not klient.collection_exists(nazwa_kolekcji):
        klient.create_collection(nazwa_kolekcji, **definicja_kolekcji())
    wersja = wersja_owu(sciezka_owu)
    punkty = punkty_do_indeksu(fragmenty, embeduj, wersja)
    klient.upsert(collection_name=nazwa_kolekcji, points=punkty)
    aktualne = {id_punktu(f.id) for f in fragmenty}
    istniejace = _wszystkie_id_punktow(klient, nazwa_kolekcji)
    nadmiarowe = sorted(istniejace - aktualne)
    if nadmiarowe:
        from qdrant_client import models

        klient.delete(collection_name=nazwa_kolekcji, points_selector=models.PointIdsList(points=nadmiarowe))
    return {"fragmenty": len(fragmenty), "usuniete": nadmiarowe, "wersja_owu": wersja}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Indeksuje OWU w Qdrant.")
    parser.add_argument("--zapytanie", default="pożar hali produkcyjnej", help="Zapytanie testowe po indeksacji.")
    parser.add_argument("--cache", default=str(PLIK_CACHE_DOMYSLNY), help="Plik cache embeddingow na dysku.")
    argumenty = parser.parse_args(argv)

    import os

    srodowisko = dict(os.environ)
    nazwa = srodowisko.get("QDRANT_COLLECTION") or KOLEKCJA_DOMYSLNA
    klient = zbuduj_klienta_qdrant(srodowisko)
    embeduj = embedder_z_cache(zbuduj_embedder(srodowisko), argumenty.cache)

    wynik = indeksuj(klient, embeduj, nazwa)
    print(f"Kolekcja {nazwa}: {wynik['fragmenty']} fragmentow, wersja OWU {wynik['wersja_owu']}, "
          f"usuniete: {wynik['usuniete'] or 'brak'}")
    wyszukiwarka = WyszukiwarkaQdrant(klient, embeduj, kolekcja=nazwa)
    trafienia = wyszukiwarka.szukaj(argumenty.zapytanie)
    print(f"Zapytanie testowe {argumenty.zapytanie!r}: {[f.id for f in trafienia]}")
    return 0 if trafienia else 1


if __name__ == "__main__":
    sys.exit(main())
