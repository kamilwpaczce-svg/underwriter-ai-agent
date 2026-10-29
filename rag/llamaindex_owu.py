"""Demo 7: OWU w LlamaIndex - wezly, adapter `Wyszukiwarka`, warianty BM25, wektory z cache.

Ten modul importuje `llama_index` na poziomie modulu, wiec dziala tylko w `.venv-llamaindex`.
Zaden istniejacy modul go nie importuje; kod wolajacy (`ewaluacja/porownaj_llamaindex.py`,
testy z `importorskip`) importuje go leniwie (SPEC D5).

- `wezly_owu` - te same 66 fragmentow co `podziel_owu()` jako `TextNode` (SPEC D2: bez SentenceSplitter).
- `WyszukiwarkaLlamaIndex` - adapter retrievera LlamaIndex do Protocolu `rag.wyszukiwarka.Wyszukiwarka` (D6).
- `zbuduj_bm25` - dwa warianty BM25 (D3): `domyslny` ("jak z tutoriala") i `bez-stemmera`.
- `EmbeddingZCache`, `zbuduj_wektorowa` - wariant `li-wektor`: wektory WYLACZNIE z kopii cache
  Etapu 12, bez sieci; brak wpisu = `KeyError`, nigdy wywolanie Azure.

Znane wlasciwosci `BM25Retriever` 0.8.0 (sprawdzone w kodzie `llama_index/retrievers/bm25/base.py`):
- indeks buduje z `node.get_content(metadata_mode=MetadataMode.EMBED)` - dlatego metadane wezlow sa
  wylaczone z tekstu embeddingu (inaczej BM25 indeksowalby numery paragrafow);
- stopwords (`language`) dziala TYLKO przy budowie indeksu; zapytanie jest tokenizowane przez
  `bm25s.tokenize(...)` z domyslnymi stopwords "english" niezaleznie od `language`, a stemmer jest
  stosowany po obu stronach (z `skip_stemming=True` po zadnej). Tego nie obchodzimy wlasnym kodem.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llama_index.core import VectorStoreIndex
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.query_engine import CitationQueryEngine
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.retrievers.bm25 import BM25Retriever

from rag.cache_embeddingow import _klucz
from rag.fragmenty import Fragment, podziel_owu
from rag.wyszukiwarka import TOP_K

MODEL_EMBEDDINGOW = "text-embedding-3-small"
KLUCZE_METADANYCH = ["paragraf", "ustep", "tytul"]
WARIANTY_BM25 = ("domyslny", "bez-stemmera")


def wezly_owu(fragmenty: list[Fragment]) -> list[TextNode]:
    """1 fragment = 1 `TextNode` (`id_` = id fragmentu, `text` = tresc). Metadane (paragraf, ustep,
    tytul) sa wylaczone z tekstu dla embeddingu i dla LLM."""
    return [
        TextNode(
            id_=f.id,
            text=f.tresc,
            metadata={"paragraf": f.paragraf, "ustep": f.ustep, "tytul": f.tytul},
            excluded_embed_metadata_keys=list(KLUCZE_METADANYCH),
            excluded_llm_metadata_keys=list(KLUCZE_METADANYCH),
        )
        for f in fragmenty
    ]


class WyszukiwarkaLlamaIndex:
    """Adapter: retriever LlamaIndex -> `Wyszukiwarka`. `szukaj` ustawia `similarity_top_k = k`, woła
    `retrieve` i mapuje `node.id_` na `Fragment`. Nieznane id = `KeyError` (nie ciche pominiecie).
    Pomija wezly z wynikiem 0 (jak baseline `lokalna`; `score=None` zostaje)."""

    def __init__(self, retriever: Any, nazwa: str, fragmenty: list[Fragment] | None = None):
        self.nazwa = nazwa
        self._retriever = retriever
        self._fragmenty = {f.id: f for f in (fragmenty if fragmenty is not None else podziel_owu())}

    def szukaj(self, zapytanie: str, k: int = TOP_K) -> list[Fragment]:
        self._retriever.similarity_top_k = k
        wyniki: list[NodeWithScore] = self._retriever.retrieve(zapytanie)
        fragmenty: list[Fragment] = []
        for wynik in wyniki:
            if wynik.score == 0:  # BM25Retriever dopelnia do k zerami; baseline ich nie zwraca (Właściciel 28.10)
                continue
            id_wezla = wynik.node.node_id
            if id_wezla not in self._fragmenty:
                raise KeyError(f"Retriever zwrocil wezel o nieznanym id {id_wezla!r} - brak go w korpusie OWU adaptera.")
            fragmenty.append(self._fragmenty[id_wezla])
        return fragmenty


def zbuduj_bm25(wariant: str, fragmenty: list[Fragment] | None = None) -> BM25Retriever:
    """Dwa warianty z D3, jedna konfiguracja na wariant (nie stroic pod wynik):
    - `domyslny`: `BM25Retriever.from_defaults(nodes=..., similarity_top_k=5)` - stemmer angielski, stopwords "en";
    - `bez-stemmera`: `skip_stemming=True`, `language=None` (bm25s: `stopwords=None` -> pusta lista).
      Polskiego stemmera PyStemmer nie ma."""
    if wariant not in WARIANTY_BM25:
        raise ValueError(f"Nieznany wariant BM25 {wariant!r}; dozwolone: {', '.join(WARIANTY_BM25)}.")
    wezly = wezly_owu(fragmenty if fragmenty is not None else podziel_owu())
    if wariant == "domyslny":
        return BM25Retriever.from_defaults(nodes=wezly, similarity_top_k=TOP_K)
    return BM25Retriever.from_defaults(nodes=wezly, similarity_top_k=TOP_K, skip_stemming=True, language=None)


class EmbeddingZCache(BaseEmbedding):
    """`BaseEmbedding` czytajacy wektory z pliku cache Etapu 12 (`rag/cache_embeddingow.py`: JSON
    `{sha256("<model>:<tekst>"): [float, ...]}`). Zero sieci: brak pliku = `FileNotFoundError` (pliku
    nie tworzymy), brak wpisu = `KeyError` z tekstem. Nie importuje `openai` ani `azure`."""

    plik_cache: str = ""
    _cache: dict[str, list[float]] = PrivateAttr(default_factory=dict)

    def __init__(self, plik_cache: str | Path, model_name: str = MODEL_EMBEDDINGOW, **kwargs: Any):
        plik = Path(plik_cache)
        if not plik.exists():
            raise FileNotFoundError(f"Brak pliku cache embeddingow: {plik}. Wariant li-wektor czyta tylko istniejacy cache.")
        super().__init__(model_name=model_name, plik_cache=str(plik), **kwargs)
        self._cache = json.loads(plik.read_text(encoding="utf-8"))

    @classmethod
    def class_name(cls) -> str:
        return "EmbeddingZCache"

    def _z_cache(self, tekst: str) -> list[float]:
        klucz = _klucz(tekst, self.model_name)
        if klucz not in self._cache:
            raise KeyError(
                f"Brak wektora w cache {self.plik_cache} (model {self.model_name}) dla tekstu {tekst[:80]!r}; "
                "li-wektor czyta tylko cache i nie wola Azure."
            )
        return self._cache[klucz]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._z_cache(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._z_cache(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._z_cache(text)


def zbuduj_silnik_cytatow(retriever: Any, llm: Any) -> CitationQueryEngine:
    """`CitationQueryEngine` na retrieverze LlamaIndex. `llm` jest WYMAGANY (bez domyslnego z `Settings`,
    zeby nie siegnac po OpenAI); w demie 7 to `MockLLM` - dowod potoku offline, nie ocena odpowiedzi (SPEC D4).
    `CitationQueryEngine` dzieli wezly na chunki (domyslnie 512 tokenow) i nadaje im nowe id - mapowanie
    na zrodlo idzie po metadanych (`paragraf`, `ustep`), patrz `zrodla_cytatow`."""
    return CitationQueryEngine(retriever=retriever, llm=llm)


def zrodla_cytatow(odpowiedz: Any) -> list[str]:
    """`response.source_nodes` -> `["§ 4 ust. 1", ...]` (kolejnosc jak w `source_nodes`)."""
    return [f"§ {w.node.metadata['paragraf']} ust. {w.node.metadata['ustep']}" for w in odpowiedz.source_nodes]


def zbuduj_wektorowa(plik_cache: str | Path, fragmenty: list[Fragment] | None = None, k: int = TOP_K) -> Any:
    """`VectorStoreIndex` (in-memory) na tych samych 66 wezlach z `EmbeddingZCache`; zwraca retriever
    (`index.as_retriever(similarity_top_k=k)`). Pokrywa tylko zapytania zestawu Z (zapytan C nie ma w cache)."""
    wezly = wezly_owu(fragmenty if fragmenty is not None else podziel_owu())
    indeks = VectorStoreIndex(wezly, embed_model=EmbeddingZCache(plik_cache), show_progress=False)
    return indeks.as_retriever(similarity_top_k=k)
