"""Cache embeddingow na dysku (Etap 12).

Opakowuje dowolny `Embedder` (`rag.azure_search.Embedder`), zeby ten sam tekst nie placil za
embedding drugi raz. Uzywane w `ewaluacja/porownaj_wyszukiwarki.py` (kilka wariantow
wyszukiwarki pyta o te same zapytania ze zlotego zbioru szkod) i w `rag/indeksuj_owu_qdrant.py`
(te same fragmenty OWU co w indeksie Azure - nie placimy drugi raz za ich embeddingi).

Plik cache to JSON `{sha256("<model>:<tekst>"): [float, ...]}` - klucz zawiera nazwe modelu,
zeby zmiana deploymentu embeddingow nie czytala przeterminowanych wektorow z cache innego
modelu."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rag.azure_search import EMBEDDING_DOMYSLNY, Embedder


def _klucz(tekst: str, model: str) -> str:
    return hashlib.sha256(f"{model}:{tekst}".encode("utf-8")).hexdigest()


def embedder_z_cache(embeduj: Embedder, plik_cache: str | Path, model: str = EMBEDDING_DOMYSLNY) -> Embedder:
    plik_cache = Path(plik_cache)
    cache: dict[str, list[float]] = {}
    if plik_cache.exists():
        cache = json.loads(plik_cache.read_text(encoding="utf-8"))

    def embeduj_z_cache(teksty: list[str]) -> list[list[float]]:
        brakujace = [t for t in teksty if _klucz(t, model) not in cache]
        if brakujace:
            nowe = embeduj(brakujace)
            if len(nowe) != len(brakujace):
                raise RuntimeError(f"Embedder zwrocil {len(nowe)} wektorow dla {len(brakujace)} tekstow.")
            for tekst, wektor in zip(brakujace, nowe):
                cache[_klucz(tekst, model)] = wektor
            plik_cache.parent.mkdir(parents=True, exist_ok=True)
            plik_cache.write_text(json.dumps(cache), encoding="utf-8")
        return [cache[_klucz(t, model)] for t in teksty]

    return embeduj_z_cache
