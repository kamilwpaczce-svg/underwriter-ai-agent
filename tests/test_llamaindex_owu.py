"""Demo 7, zadanie 2: LlamaIndex nad OWU - wezly, adapter `Wyszukiwarka`, warianty BM25, wektory z cache.

Testy biegna tylko w `.venv-llamaindex`; w glownym `.venv` calosc jest pomijana (importorskip),
zeby liczba zielonych testow w `.venv` nie zalezala od LlamaIndex (SPEC D5)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("llama_index.core")
pytest.importorskip("llama_index.retrievers.bm25")

from llama_index.core.schema import MetadataMode, NodeWithScore, TextNode  # noqa: E402

import json  # noqa: E402
import socket  # noqa: E402

from llama_index.core.llms import MockLLM  # noqa: E402

from ewaluacja.porownaj_llamaindex import main, zestaw_z  # noqa: E402
from rag.fragmenty import podziel_owu  # noqa: E402
from rag.llamaindex_owu import (  # noqa: E402
    EmbeddingZCache,
    WyszukiwarkaLlamaIndex,
    wezly_owu,
    zbuduj_bm25,
    zbuduj_silnik_cytatow,
    zbuduj_wektorowa,
    zrodla_cytatow,
)
from rag.wyszukiwarka import TOP_K  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PLIK_CACHE_DEMO7 = ROOT / ".cache_embeddingow_demo7" / "text-embedding-3-small.json"
WARIANTY_BM25 = ["domyslny", "bez-stemmera"]

wymaga_cache = pytest.mark.skipif(
    not PLIK_CACHE_DEMO7.exists(),
    reason="brak kopii cache embeddingow Etapu 12 w .cache_embeddingow_demo7/ (gitignored; kopia z worktree qdrant)",
)


# --- wezly -------------------------------------------------------------------------------

def test_wezly_owu_66_wezlow_typu_textnode():
    fragmenty = podziel_owu()
    wezly = wezly_owu(fragmenty)
    assert len(fragmenty) == 66
    assert len(wezly) == 66
    assert all(isinstance(w, TextNode) for w in wezly)


def test_wezly_owu_id_unikalne_i_rowne_id_fragmentu():
    fragmenty = podziel_owu()
    wezly = wezly_owu(fragmenty)
    assert len({w.id_ for w in wezly}) == len(wezly)
    assert [w.id_ for w in wezly] == [f.id for f in fragmenty]


def test_wezly_owu_tekst_to_tresc_fragmentu_i_metadata():
    for fragment, wezel in zip(podziel_owu(), wezly_owu(podziel_owu())):
        assert wezel.text == fragment.tresc
        assert wezel.metadata == {"paragraf": fragment.paragraf, "ustep": fragment.ustep, "tytul": fragment.tytul}


def test_wezly_owu_metadata_wylaczona_z_embeddingu_i_llm():
    for wezel in wezly_owu(podziel_owu()):
        assert set(wezel.excluded_embed_metadata_keys) == {"paragraf", "ustep", "tytul"}
        assert set(wezel.excluded_llm_metadata_keys) == {"paragraf", "ustep", "tytul"}
        # tekst widziany przez BM25/embedding i przez LLM = sama tresc, bez dopisanych metadanych
        assert wezel.get_content(metadata_mode=MetadataMode.EMBED) == wezel.text
        assert wezel.get_content(metadata_mode=MetadataMode.LLM) == wezel.text


# --- adapter ----------------------------------------------------------------------------

class AtrapaRetrievera:
    """Udaje retriever LlamaIndex: zwraca zadane id w zadanej kolejnosci, zapamietuje `similarity_top_k`."""

    def __init__(self, ids: list[str]):
        self._ids = ids
        self.similarity_top_k = None
        self.zapytania: list[str] = []
        self.k_przy_wywolaniu: list[int] = []

    def retrieve(self, zapytanie):
        self.zapytania.append(zapytanie)
        self.k_przy_wywolaniu.append(self.similarity_top_k)
        return [NodeWithScore(node=TextNode(id_=i, text="atrapa"), score=1.0 / (n + 1)) for n, i in enumerate(self._ids)]


def test_adapter_mapuje_id_wezlow_na_fragmenty_w_kolejnosci_retrievera():
    fragmenty = {f.id: f for f in podziel_owu()}
    atrapa = AtrapaRetrievera(["p4u1", "p2u1", "p4u2"])
    wyszukiwarka = WyszukiwarkaLlamaIndex(atrapa, "atrapa-li")
    wynik = wyszukiwarka.szukaj("cokolwiek", k=3)
    assert wynik == [fragmenty["p4u1"], fragmenty["p2u1"], fragmenty["p4u2"]]
    assert wyszukiwarka.nazwa == "atrapa-li"


def test_adapter_ustawia_similarity_top_k_na_k_przed_retrieve():
    atrapa = AtrapaRetrievera(["p4u1"])
    wyszukiwarka = WyszukiwarkaLlamaIndex(atrapa, "atrapa-li")
    wyszukiwarka.szukaj("pierwsze", k=2)
    wyszukiwarka.szukaj("drugie", k=7)
    wyszukiwarka.szukaj("domyslne")
    assert atrapa.zapytania == ["pierwsze", "drugie", "domyslne"]
    assert atrapa.k_przy_wywolaniu == [2, 7, TOP_K]


def test_adapter_nieznane_id_to_wyjatek_nie_ciche_pominiecie():
    atrapa = AtrapaRetrievera(["p4u1", "p999u9"])
    wyszukiwarka = WyszukiwarkaLlamaIndex(atrapa, "atrapa-li")
    with pytest.raises(KeyError, match="p999u9"):
        wyszukiwarka.szukaj("cokolwiek", k=2)


def test_adapter_pusta_odpowiedz_retrievera_to_pusta_lista():
    wyszukiwarka = WyszukiwarkaLlamaIndex(AtrapaRetrievera([]), "atrapa-li")
    assert wyszukiwarka.szukaj("cokolwiek") == []


def test_adapter_pomija_wezly_z_wynikiem_zero_jak_baseline():
    # BM25Retriever dopelnia do k wezlami z wynikiem 0.0; baseline `lokalna` ich nie zwraca (decyzja właściciela 28.10).
    fragmenty = {f.id: f for f in podziel_owu()}
    atrapa = AtrapaRetrievera(["p4u1", "p2u1", "p4u2"])
    wyniki = atrapa.retrieve
    atrapa.retrieve = lambda q: [w if n == 0 else NodeWithScore(node=w.node, score=0.0) for n, w in enumerate(wyniki(q))]
    assert WyszukiwarkaLlamaIndex(atrapa, "atrapa-li").szukaj("cokolwiek", k=3) == [fragmenty["p4u1"]]


def test_adapter_zostawia_wezly_bez_wyniku():
    # score=None (retriever bez punktacji) to nie "wynik 0" - nie filtrujemy.
    fragmenty = {f.id: f for f in podziel_owu()}
    atrapa = AtrapaRetrievera(["p4u1"])
    atrapa.retrieve = lambda q: [NodeWithScore(node=TextNode(id_="p4u1", text="atrapa"), score=None)]
    assert WyszukiwarkaLlamaIndex(atrapa, "atrapa-li").szukaj("cokolwiek", k=1) == [fragmenty["p4u1"]]


# --- warianty BM25 ----------------------------------------------------------------------

@pytest.mark.parametrize("wariant", WARIANTY_BM25)
def test_bm25_pozar_budynku_zwraca_najwyzej_5_fragmentow_z_owu(wariant):
    id_owu = {f.id for f in podziel_owu()}
    wyszukiwarka = WyszukiwarkaLlamaIndex(zbuduj_bm25(wariant), f"li-bm25-{wariant}")
    wynik = wyszukiwarka.szukaj("pożar budynku", k=TOP_K)
    assert 1 <= len(wynik) <= TOP_K
    assert all(f.id in id_owu for f in wynik)


def test_bm25_nieznany_wariant_to_valueerror():
    with pytest.raises(ValueError, match="stemmer-pl"):
        zbuduj_bm25("stemmer-pl")


def test_bm25_domyslny_ma_angielski_stemmer_i_angielskie_stopwords():
    # ustalenie ze SPEC (tabela wersji) sprawdzone w kodzie: stemmer "english", stopwords "en" w indeksie
    retriever = zbuduj_bm25("domyslny")
    assert retriever.skip_stemming is False
    assert retriever.stemmer.stemWord("running") == "run"
    slownik = retriever.bm25.vocab_dict
    assert "to" not in slownik  # "to" jest na angielskiej liscie stopwords, a po polsku to czeste slowo


def test_bm25_bez_stemmera_pomija_stemming_i_stopwords_w_indeksie():
    retriever = zbuduj_bm25("bez-stemmera")
    assert retriever.skip_stemming is True
    assert "to" in retriever.bm25.vocab_dict


def test_bm25_similarity_top_k_domyslnie_top_k():
    for wariant in WARIANTY_BM25:
        assert zbuduj_bm25(wariant).similarity_top_k == TOP_K


# --- EmbeddingZCache + li-wektor (tylko cache, zero sieci) ----------------------------------

@wymaga_cache
def test_cache_pokrywa_66_fragmentow_i_9_zapytan_z():
    embed = EmbeddingZCache(PLIK_CACHE_DEMO7)
    fragmenty = podziel_owu()
    zapytania = zestaw_z()
    assert len(fragmenty) == 66 and len(zapytania) == 9
    for f in fragmenty:
        assert len(embed.get_text_embedding(f.tresc)) == 1536
    for wiersz in zapytania:
        assert len(embed.get_query_embedding(wiersz["zapytanie"])) == 1536


@wymaga_cache
def test_embedding_z_cache_brak_wpisu_to_keyerror_z_tekstem():
    embed = EmbeddingZCache(PLIK_CACHE_DEMO7)
    with pytest.raises(KeyError, match="tekst spoza cache"):
        embed.get_query_embedding("tekst spoza cache - zapytania C nie ma w cache")
    with pytest.raises(KeyError, match="fragment spoza cache"):
        embed.get_text_embedding("fragment spoza cache")


def test_embedding_z_cache_brak_pliku_to_filenotfounderror_bez_tworzenia(tmp_path):
    plik = tmp_path / "nie_ma.json"
    with pytest.raises(FileNotFoundError):
        EmbeddingZCache(plik)
    assert not plik.exists()


@wymaga_cache
def test_embedding_z_cache_wektor_taki_jak_w_pliku_cache():
    import json

    from rag.cache_embeddingow import _klucz

    surowy = json.loads(PLIK_CACHE_DEMO7.read_text(encoding="utf-8"))
    fragment = podziel_owu()[0]
    embed = EmbeddingZCache(PLIK_CACHE_DEMO7)
    assert embed.get_text_embedding(fragment.tresc) == surowy[_klucz(fragment.tresc, "text-embedding-3-small")]


@wymaga_cache
def test_wektorowa_zwraca_fragmenty_owu_dla_kazdego_zapytania_z():
    id_owu = {f.id for f in podziel_owu()}
    wyszukiwarka = WyszukiwarkaLlamaIndex(zbuduj_wektorowa(PLIK_CACHE_DEMO7), "li-wektor")
    for wiersz in zestaw_z():
        wynik = wyszukiwarka.szukaj(wiersz["zapytanie"], k=TOP_K)
        assert len(wynik) == TOP_K, wiersz["id"]
        assert all(f.id in id_owu for f in wynik)


@wymaga_cache
def test_wektorowa_wezly_maja_wektory_z_cache_czyli_embeduje_sama_tresc():
    import json

    from rag.cache_embeddingow import _klucz

    surowy = json.loads(PLIK_CACHE_DEMO7.read_text(encoding="utf-8"))
    retriever = zbuduj_wektorowa(PLIK_CACHE_DEMO7)
    fragment = podziel_owu()[5]
    wektor = retriever._index.vector_store.get(fragment.id)
    assert wektor == surowy[_klucz(fragment.tresc, "text-embedding-3-small")]


@wymaga_cache
def test_sciezka_wektorowa_nie_importuje_openai_ani_azure():
    # osobny proces, zeby inne testy nie zanieczyscily sys.modules
    kod = (
        "import sys\n"
        "from pathlib import Path\n"
        "from rag.fragmenty import podziel_owu\n"
        "from rag.llamaindex_owu import WyszukiwarkaLlamaIndex, zbuduj_wektorowa\n"
        "from ewaluacja.porownaj_llamaindex import zestaw_z\n"
        "w = WyszukiwarkaLlamaIndex(zbuduj_wektorowa(Path(sys.argv[1])), 'li-wektor')\n"
        "w.szukaj(zestaw_z()[0]['zapytanie'])\n"
        "zle = sorted(m for m in sys.modules if m.split('.')[0] in ('openai', 'azure'))\n"
        "print('ZLE=' + ','.join(zle))\n"
    )
    wynik = subprocess.run([sys.executable, "-c", kod, str(PLIK_CACHE_DEMO7)], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert wynik.returncode == 0, wynik.stderr
    assert wynik.stdout.strip().splitlines()[-1] == "ZLE=", wynik.stdout


# --- zadanie 3: potok z cytatami offline (MockLLM) i main() --------------------------------

@pytest.fixture
def bez_sieci(monkeypatch):
    def zabronione(*args, **kwargs):
        raise AssertionError("proba polaczenia sieciowego w tescie offline")

    monkeypatch.setattr(socket.socket, "connect", zabronione)
    monkeypatch.setattr(socket, "getaddrinfo", zabronione)


@pytest.mark.parametrize("wariant", WARIANTY_BM25)
def test_silnik_cytatow_z_mockllm_zwraca_zrodla_z_retrievera_mapowalne_na_paragraf_ustep(wariant, bez_sieci):
    retriever = zbuduj_bm25(wariant)
    silnik = zbuduj_silnik_cytatow(retriever, MockLLM())
    pytanie = "pozar budynku zgloszenie szkody"
    odpowiedz = silnik.query(pytanie)

    z_retrievera = {(w.node.metadata["paragraf"], w.node.metadata["ustep"]) for w in retriever.retrieve(pytanie)}
    assert odpowiedz.source_nodes, "silnik nie zwrocil zadnych zrodel"
    zrodla = zrodla_cytatow(odpowiedz)
    assert len(zrodla) == len(odpowiedz.source_nodes)
    for opis, wezel in zip(zrodla, odpowiedz.source_nodes):
        pozycja = (wezel.node.metadata["paragraf"], wezel.node.metadata["ustep"])
        assert pozycja in z_retrievera
        assert opis == f"§ {pozycja[0]} ust. {pozycja[1]}"


def test_silnik_cytatow_nie_tnie_fragmentow_owu_i_numeruje_zrodla(bez_sieci):
    # citation_chunk_size domyslnie 512 tokenow: kazdy z 66 fragmentow powinien miescic sie w jednym chunku,
    # wtedy kazdy wezel zrodlowy = jeden fragment OWU (a nie jego kawalek)
    tresci = {(f.paragraf, f.ustep): f.tresc for f in podziel_owu()}
    silnik = zbuduj_silnik_cytatow(zbuduj_bm25("domyslny"), MockLLM())
    odpowiedz = silnik.query("pozar budynku zgloszenie szkody")
    for numer, wezel in enumerate(odpowiedz.source_nodes, start=1):
        tekst = wezel.node.get_content()
        assert tekst.startswith(f"Source {numer}:")
        assert tresci[(wezel.node.metadata["paragraf"], wezel.node.metadata["ustep"])] in tekst


def test_silnik_cytatow_wymaga_jawnego_llm():
    with pytest.raises(TypeError):
        zbuduj_silnik_cytatow(zbuduj_bm25("domyslny"))  # bez llm: brak cichego domyslnego OpenAI


def test_main_w_llamaindex_liczy_trzy_warianty_li_i_zapisuje_wyniki(tmp_path, capsys):
    kod = main(["--cache", str(PLIK_CACHE_DEMO7), "--wyniki-dir", str(tmp_path)])
    assert kod == 0
    plik = next(tmp_path.glob("*_llamaindex.json"))
    warianty = json.loads(plik.read_text(encoding="utf-8"))["wyniki"]["warianty"]
    oczekiwane = {"lokalna", "li-bm25-domyslny", "li-bm25-bez-stemmera"} | ({"li-wektor"} if PLIK_CACHE_DEMO7.exists() else set())
    assert set(warianty) == oczekiwane
    for nazwa, bloki in warianty.items():
        if nazwa == "li-wektor":
            assert bloki["Z"]["n"] == 9 and bloki["C"] is None and bloki["Z+C"] is None
        else:
            assert bloki["Z"]["n"] == 9 and bloki["C"]["n"] == 10 and bloki["Z+C"]["n"] == 19
    assert warianty["lokalna"]["C"]["mcnemar"] is None
    assert warianty["li-bm25-domyslny"]["Z+C"]["mcnemar"]["n"] == 19


def test_main_bez_pliku_cache_pomija_li_wektor_i_konczy_kodem_3(tmp_path, capsys):
    # Brak wariantu nie moze wygladac jak sukces (Właściciel 28.10): reszta liczona i zapisana, ale kod 3.
    kod = main(["--cache", str(tmp_path / "nie_ma.json"), "--wyniki-dir", str(tmp_path)])
    wyjscie = capsys.readouterr()
    assert kod == 3
    assert "li-wektor" in wyjscie.err
    plik = next(tmp_path.glob("*_llamaindex.json"))
    assert "li-wektor" not in json.loads(plik.read_text(encoding="utf-8"))["wyniki"]["warianty"]
