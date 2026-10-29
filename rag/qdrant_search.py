"""Qdrant jako trzecia wyszukiwarka RAG po OWU (Etap 12): hybryda wektor gesty + sparse BM25.

Wektor gesty: te same embeddingi Azure OpenAI `text-embedding-3-small` co `WyszukiwarkaAzure`
(`rag.azure_search.zbuduj_embedder`) - porownujemy silnik wyszukiwania, nie model embeddingow.

Wektor rzadki (BM25): WLASNY, nie fastembed `Qdrant/bm25`. Powod: wbudowany stemmer Snowball
tego modelu nie obsluguje polskiego (`fastembed.sparse.bm25.supported_languages` - jest
"russian", nie ma "polish"; uzycie z `language="english"` zle stemowaloby polskie koncowki).
Uzywamy wiec tego samego tokenizera co `WyszukiwarkaLokalna` (`rag.wyszukiwarka.tokenizuj`:
male litery, polskie znaki -> ASCII, 5-znakowy "stemming"), zeby trafienia BM25 w Qdrant i w
wersji lokalnej byly spojne jezykowo. Wymiar rzadkiego wektora dla danego tokenu to stabilny
hash (sha1 mod `MODULO_HASH`) - nie trzeba trzymac wspolnego slownika token->indeks miedzy
indeksowaniem a zapytaniem, obie strony licza ten sam hash niezaleznie (ryzyko kolizji przy
hashowaniu kilkuset unikalnych tokenow OWU w przestrzen 2^31 jest pomijalne).

Dokument niesie SUROWA czestosc termu (tf); globalne idf liczy Qdrant przy zapytaniu
(`SparseVectorParams(modifier=Modifier.IDF)`) - to standardowy wzorzec Qdrant dla BM25-podobnego
wyszukiwania rzadkiego. UWAGA: to przyblizenie BM25, nie identyczna formula co
`WyszukiwarkaLokalna` - brak normalizacji dlugosci dokumentu (parametr `b`); SPEC_ETAP12.md
odnotowuje to jako swiadomy kompromis.

Fuzja hybrydowa: Query API, `prefetch` (gesty i rzadki, kazdy top `k * MNOZNIK_PREFETCH`) +
`FusionQuery(fusion=Fusion.RRF)` dajace koncowe top `k`.

Klient: `QDRANT_URL` (serwer, np. `docker-compose.qdrant.yml`) ma pierwszenstwo; inaczej
`QDRANT_PATH` (tryb lokalny embedded, plik na dysku) - domyslnie `.qdrant_lokalny/` w katalogu
repo (w .gitignore). Oba tryby dzialaja bez zadnego serwera/kluczy.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from rag.azure_search import INDEKS_DOMYSLNY, WYMIARY_WEKTORA, BrakKonfiguracjiWyszukiwarki, Embedder
from rag.fragmenty import SCIEZKA_OWU, Fragment
from rag.wyszukiwarka import TOP_K, tokenizuj

ROOT = Path(__file__).resolve().parent.parent
SCIEZKA_LOKALNA_DOMYSLNA = ROOT / ".qdrant_lokalny"

KOLEKCJA_DOMYSLNA = INDEKS_DOMYSLNY  # ten sam domyslny identyfikator co indeks Azure
NAZWA_WEKTORA_GESTEGO = "wektor"
NAZWA_WEKTORA_RZADKIEGO = "bm25"
MODULO_HASH = 2**31 - 1
MNOZNIK_PREFETCH = 4

# Przestrzen nazw UUID5 dla punktow Qdrant - Qdrant wymaga int/UUID jako id punktu, nasze
# fragmenty maja id tekstowe (np. "p4u1"); uuid5 z ta sama przestrzenia nazw + tym samym
# tekstem zawsze daje ten sam punkt (idempotentny upsert po Fragment.id).
_PRZESTRZEN_ID = uuid.UUID("2f9f6a3e-7b8e-4e2a-9b0a-8e6a7c1d9f10")

TrybQdrant = Literal["hybryda", "gesty", "rzadki"]
TRYBY_QDRANT: tuple[TrybQdrant, ...] = ("hybryda", "gesty", "rzadki")


def id_punktu(fragment_id: str) -> str:
    return str(uuid.uuid5(_PRZESTRZEN_ID, fragment_id))


def hash_tokena(token: str) -> int:
    return int(hashlib.sha1(token.encode("utf-8")).hexdigest(), 16) % MODULO_HASH


def wektor_rzadki(tekst: str):
    from qdrant_client import models

    czestosc = Counter(tokenizuj(tekst))
    if not czestosc:
        return models.SparseVector(indices=[], values=[])
    return models.SparseVector(
        indices=[hash_tokena(t) for t in czestosc],
        values=[float(c) for c in czestosc.values()],
    )


def definicja_kolekcji() -> dict[str, Any]:
    """Konfiguracja wektorow do `create_collection` (gesty: cosinus, 1536 wymiarow jak Azure;
    rzadki: BM25-podobny, idf liczony przez Qdrant z calej kolekcji)."""
    from qdrant_client import models

    return {
        "vectors_config": {
            NAZWA_WEKTORA_GESTEGO: models.VectorParams(size=WYMIARY_WEKTORA, distance=models.Distance.COSINE),
        },
        "sparse_vectors_config": {
            NAZWA_WEKTORA_RZADKIEGO: models.SparseVectorParams(modifier=models.Modifier.IDF),
        },
    }


def punkt_z_fragmentu(fragment: Fragment, wektor_gesty: list[float], wersja_owu: str):
    from qdrant_client import models

    return models.PointStruct(
        id=id_punktu(fragment.id),
        vector={
            NAZWA_WEKTORA_GESTEGO: wektor_gesty,
            NAZWA_WEKTORA_RZADKIEGO: wektor_rzadki(fragment.tresc),
        },
        payload={
            "id": fragment.id,
            "paragraf": fragment.paragraf,
            "ustep": fragment.ustep,
            "tytul": fragment.tytul,
            "tresc": fragment.tresc,
            "wersja_owu": wersja_owu,
        },
    )


def _fragment_z_payloadu(payload: dict) -> Fragment:
    return Fragment(
        id=payload["id"], paragraf=int(payload["paragraf"]), ustep=int(payload["ustep"]),
        tytul=payload["tytul"], tresc=payload["tresc"],
    )


class WyszukiwarkaQdrant:
    """`klient` - `qdrant_client.QdrantClient` (serwer, embedded na dysku albo `:memory:`)."""

    nazwa = "qdrant"

    def __init__(self, klient: Any, embeduj: Embedder, kolekcja: str = KOLEKCJA_DOMYSLNA, tryb: TrybQdrant = "hybryda"):
        if tryb not in TRYBY_QDRANT:
            raise ValueError(f"Nieznany tryb Qdrant {tryb!r} - dozwolone: {', '.join(TRYBY_QDRANT)}.")
        self._klient = klient
        self._embeduj = embeduj
        self._kolekcja = kolekcja
        self.tryb = tryb

    def _wektor_gesty(self, zapytanie: str) -> list[float]:
        return self._embeduj([zapytanie])[0]

    def szukaj(self, zapytanie: str, k: int = TOP_K) -> list[Fragment]:
        from qdrant_client import models

        limit_prefetch = max(k * MNOZNIK_PREFETCH, TOP_K * MNOZNIK_PREFETCH)
        if self.tryb == "gesty":
            wynik = self._klient.query_points(
                self._kolekcja, query=self._wektor_gesty(zapytanie), using=NAZWA_WEKTORA_GESTEGO,
                limit=k, with_payload=True,
            )
        elif self.tryb == "rzadki":
            wynik = self._klient.query_points(
                self._kolekcja, query=wektor_rzadki(zapytanie), using=NAZWA_WEKTORA_RZADKIEGO,
                limit=k, with_payload=True,
            )
        else:  # hybryda
            wynik = self._klient.query_points(
                self._kolekcja,
                prefetch=[
                    models.Prefetch(query=self._wektor_gesty(zapytanie), using=NAZWA_WEKTORA_GESTEGO, limit=limit_prefetch),
                    models.Prefetch(query=wektor_rzadki(zapytanie), using=NAZWA_WEKTORA_RZADKIEGO, limit=limit_prefetch),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=k,
                with_payload=True,
            )
        return [_fragment_z_payloadu(p.payload) for p in wynik.points][:k]


def _wymagana(srodowisko: Mapping[str, str], nazwa: str) -> str:
    wartosc = srodowisko.get(nazwa)
    if not wartosc:
        raise BrakKonfiguracjiWyszukiwarki(f"Brak zmiennej srodowiskowej {nazwa}.")
    return wartosc


def zbuduj_klienta_qdrant(srodowisko: Mapping[str, str] | None = None):
    from qdrant_client import QdrantClient

    srodowisko = os.environ if srodowisko is None else srodowisko
    url = srodowisko.get("QDRANT_URL")
    if url:
        return QdrantClient(url=url)
    sciezka = srodowisko.get("QDRANT_PATH") or str(SCIEZKA_LOKALNA_DOMYSLNA)
    return QdrantClient(path=sciezka)


def zbuduj_wyszukiwarke_qdrant(srodowisko: Mapping[str, str] | None = None) -> WyszukiwarkaQdrant:
    """Uzywane przez `rag.azure_search.zbuduj_wyszukiwarke` dla `WYSZUKIWARKA=qdrant`.
    `QDRANT_TRYB=hybryda|gesty|rzadki` (domyslnie `hybryda`) - zla wartosc -> wyjatek przy
    starcie, tak samo jak zla wartosc `WYSZUKIWARKA`."""
    from rag.azure_search import zbuduj_embedder

    srodowisko = os.environ if srodowisko is None else srodowisko
    tryb = (srodowisko.get("QDRANT_TRYB") or "hybryda").strip().lower()
    if tryb not in TRYBY_QDRANT:
        raise BrakKonfiguracjiWyszukiwarki(f"QDRANT_TRYB={tryb!r} - dozwolone: {', '.join(TRYBY_QDRANT)}.")
    klient = zbuduj_klienta_qdrant(srodowisko)
    embeduj = zbuduj_embedder(srodowisko)
    kolekcja = srodowisko.get("QDRANT_COLLECTION") or KOLEKCJA_DOMYSLNA
    return WyszukiwarkaQdrant(klient, embeduj, kolekcja=kolekcja, tryb=tryb)  # type: ignore[arg-type]
