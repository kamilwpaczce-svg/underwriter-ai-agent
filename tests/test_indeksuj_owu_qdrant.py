"""Indeksowanie OWU w Qdrant (Etap 12) - QdrantClient(':memory:'), atrapa embeddera, zero sieci."""

from __future__ import annotations

import pytest

pytest.importorskip("qdrant_client")

from qdrant_client import QdrantClient, models  # noqa: E402

from rag.fragmenty import podziel_owu  # noqa: E402
from rag.indeksuj_owu_qdrant import indeksuj  # noqa: E402
from rag.qdrant_search import NAZWA_WEKTORA_GESTEGO, NAZWA_WEKTORA_RZADKIEGO, id_punktu  # noqa: E402


def _embedder_stala():
    return lambda teksty: [[0.05] * 1536 for _ in teksty]


def test_indeksuj_jest_idempotentny():
    klient = QdrantClient(":memory:")
    wynik = indeksuj(klient, _embedder_stala(), "owu-test-v1")
    assert wynik["fragmenty"] == len(podziel_owu()) == 66
    assert wynik["usuniete"] == []
    assert len(wynik["wersja_owu"]) == 12
    assert klient.get_collection("owu-test-v1").points_count == 66

    wynik2 = indeksuj(klient, _embedder_stala(), "owu-test-v1")
    assert wynik2 == wynik
    assert klient.get_collection("owu-test-v1").points_count == 66


def test_indeksuj_usuwa_punkty_spoza_aktualnego_owu():
    klient = QdrantClient(":memory:")
    indeksuj(klient, _embedder_stala(), "owu-test-v1")
    klient.upsert(
        "owu-test-v1",
        points=[
            models.PointStruct(
                id=id_punktu("p999u1"),
                vector={
                    NAZWA_WEKTORA_GESTEGO: [0.05] * 1536,
                    NAZWA_WEKTORA_RZADKIEGO: models.SparseVector(indices=[], values=[]),
                },
                payload={"id": "p999u1", "paragraf": 999, "ustep": 1, "tytul": "widmo", "tresc": "x", "wersja_owu": "stara"},
            )
        ],
    )
    assert klient.get_collection("owu-test-v1").points_count == 67

    wynik = indeksuj(klient, _embedder_stala(), "owu-test-v1")
    assert wynik["usuniete"] == [id_punktu("p999u1")]
    assert klient.get_collection("owu-test-v1").points_count == 66


def test_indeksuj_tworzy_kolekcje_gdy_nie_istnieje():
    klient = QdrantClient(":memory:")
    assert not klient.collection_exists("brakowalo-jeszcze")
    indeksuj(klient, _embedder_stala(), "brakowalo-jeszcze")
    assert klient.collection_exists("brakowalo-jeszcze")
