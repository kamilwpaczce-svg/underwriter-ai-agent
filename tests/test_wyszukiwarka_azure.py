"""WyszukiwarkaAzure, fabryka i indeksacja na atrapach klientow SDK - zero sieci (Etap 10)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("azure.search.documents")

from rag.azure_search import (  # noqa: E402
    KONFIGURACJA_SEMANTYCZNA,
    BrakKonfiguracjiWyszukiwarki,
    WyszukiwarkaAzure,
    zbuduj_wyszukiwarke,
)
from rag.fragmenty import podziel_owu  # noqa: E402
from rag.indeksuj_owu import definicja_indeksu, dokumenty_do_indeksu, indeksuj  # noqa: E402
from rag.wyszukiwarka import WyszukiwarkaLokalna  # noqa: E402

DOKUMENT = {"id": "p4u1", "paragraf": 4, "ustep": 1, "tytul": "Zakres", "tresc": "§ 4. Zakres\nust. 1. Pożar.", "@search.score": 1.0}


class AtrapaKlientaWyszukiwania:
    def __init__(self, wyniki=(), istniejace_id=()):
        self._wyniki = list(wyniki)
        self._istniejace = list(istniejace_id)
        self.wywolania: list[dict] = []
        self.wgrane: list[dict] = []
        self.usuniete: list[dict] = []

    def search(self, **kwargs):
        self.wywolania.append(kwargs)
        if kwargs.get("search_text") == "*":
            return [{"id": i} for i in self._istniejace]
        return iter(self._wyniki)

    def merge_or_upload_documents(self, documents):
        self.wgrane.extend(documents)
        return [SimpleNamespace(key=d["id"], succeeded=True) for d in documents]

    def delete_documents(self, documents):
        self.usuniete.extend(documents)


class AtrapaKlientaIndeksow:
    def __init__(self):
        self.indeksy = []

    def create_or_update_index(self, indeks):
        self.indeksy.append(indeks)
        return indeks


def _embedder(rejestr=None):
    def embeduj(teksty):
        if rejestr is not None:
            rejestr.append(list(teksty))
        return [[0.1] * 1536 for _ in teksty]

    return embeduj


def test_zapytanie_hybrydowe_ma_tekst_i_wektor():
    klient = AtrapaKlientaWyszukiwania([DOKUMENT])
    wywolania_embeddera: list = []
    wynik = WyszukiwarkaAzure(klient, _embedder(wywolania_embeddera)).szukaj("pożar hali", k=5)
    parametry = klient.wywolania[0]
    assert parametry["search_text"] == "pożar hali"
    assert parametry["top"] == 5
    assert parametry["select"] == ["id", "paragraf", "ustep", "tytul", "tresc"]
    zapytanie_wektorowe = parametry["vector_queries"][0]
    assert zapytanie_wektorowe.fields == "wektor"
    assert zapytanie_wektorowe.k_nearest_neighbors == 5
    assert len(zapytanie_wektorowe.vector) == 1536
    assert "query_type" not in parametry
    assert wywolania_embeddera == [["pożar hali"]]
    assert [f.id for f in wynik] == ["p4u1"]
    assert wynik[0].tresc.startswith("§ 4. Zakres")


def test_semantic_ranker_tylko_po_wlaczeniu():
    klient = AtrapaKlientaWyszukiwania([DOKUMENT])
    WyszukiwarkaAzure(klient, _embedder(), semantyczna=True).szukaj("pożar", k=3)
    assert klient.wywolania[0]["query_type"] == "semantic"
    assert klient.wywolania[0]["semantic_configuration_name"] == KONFIGURACJA_SEMANTYCZNA
    assert klient.wywolania[0]["vector_queries"][0].k_nearest_neighbors == 3


def test_obcina_do_k_nawet_gdy_klient_zwroci_wiecej():
    dokumenty = [{**DOKUMENT, "id": f"p4u{i}", "ustep": i} for i in range(1, 8)]
    wynik = WyszukiwarkaAzure(AtrapaKlientaWyszukiwania(dokumenty), _embedder()).szukaj("x", k=3)
    assert [f.id for f in wynik] == ["p4u1", "p4u2", "p4u3"]


@pytest.mark.parametrize(
    ("srodowisko", "typ"),
    [
        ({}, WyszukiwarkaLokalna),
        ({"WYSZUKIWARKA": "lokalna", "AZURE_SEARCH_ENDPOINT": "https://x.search.windows.net"}, WyszukiwarkaLokalna),
        ({"WYSZUKIWARKA": " Lokalna "}, WyszukiwarkaLokalna),
    ],
)
def test_fabryka_lokalna(srodowisko, typ):
    assert isinstance(zbuduj_wyszukiwarke(srodowisko), typ)


def test_fabryka_azure_bez_sieci_i_z_flaga_semantyczna():
    srodowisko = {
        "AZURE_SEARCH_ENDPOINT": "https://uw-demo-search-xx1.search.windows.net",
        "AZURE_OPENAI_ENDPOINT": "https://uw-demo-aoai-xx1.openai.azure.com/",
        "AZURE_SEARCH_SEMANTIC": "1",
    }
    wyszukiwarka = zbuduj_wyszukiwarke(srodowisko)
    assert isinstance(wyszukiwarka, WyszukiwarkaAzure)
    assert wyszukiwarka.semantyczna is True
    assert zbuduj_wyszukiwarke({**srodowisko, "AZURE_SEARCH_SEMANTIC": "0"}).semantyczna is False


@pytest.mark.parametrize(
    ("srodowisko", "fragment"),
    [
        ({"WYSZUKIWARKA": "azure"}, "AZURE_SEARCH_ENDPOINT"),
        ({"WYSZUKIWARKA": "azure", "AZURE_SEARCH_ENDPOINT": "https://x.search.windows.net"}, "AZURE_OPENAI_ENDPOINT"),
        ({"WYSZUKIWARKA": "elastic"}, "dozwolone"),
    ],
)
def test_fabryka_glosno_odrzuca_zla_konfiguracje(srodowisko, fragment):
    with pytest.raises(BrakKonfiguracjiWyszukiwarki, match=fragment):
        zbuduj_wyszukiwarke(srodowisko)


def test_definicja_indeksu_zgodna_ze_specyfikacja():
    indeks = definicja_indeksu("owu-mienie-v1")
    pola = {p.name: p for p in indeks.fields}
    assert list(pola) == ["id", "tresc", "paragraf", "ustep", "tytul", "wektor"]
    assert pola["id"].key is True
    assert pola["tresc"].searchable is True and pola["tresc"].analyzer_name == "pl.microsoft"
    assert pola["paragraf"].filterable and pola["ustep"].filterable and pola["tytul"].filterable
    assert pola["wektor"].vector_search_dimensions == 1536
    konfiguracja = indeks.semantic_search.configurations[0]
    assert konfiguracja.name == KONFIGURACJA_SEMANTYCZNA
    assert konfiguracja.prioritized_fields.title_field.field_name == "tytul"
    assert [p.field_name for p in konfiguracja.prioritized_fields.content_fields] == ["tresc"]


def test_dokumenty_do_indeksu_w_paczkach_po_16():
    fragmenty = podziel_owu()
    paczki: list = []
    dokumenty = dokumenty_do_indeksu(fragmenty, _embedder(paczki))
    assert len(dokumenty) == len(fragmenty) == 66
    assert [len(p) for p in paczki] == [16, 16, 16, 16, 2]
    assert set(dokumenty[0]) == {"id", "paragraf", "ustep", "tytul", "tresc", "wektor"}


def test_dokumenty_do_indeksu_wykrywa_zgubione_wektory():
    with pytest.raises(RuntimeError, match="wektorow"):
        dokumenty_do_indeksu(podziel_owu(), lambda teksty: [[0.0] * 1536])


def test_indeksuj_jest_idempotentny_i_usuwa_nadmiarowe():
    klient_indeksow = AtrapaKlientaIndeksow()
    klient = AtrapaKlientaWyszukiwania(istniejace_id=["p4u1", "p99u1"])
    wynik = indeksuj(klient_indeksow, klient, _embedder(), "owu-mienie-v1")
    assert wynik["fragmenty"] == 66
    assert len(wynik["wersja_owu"]) == 12
    assert wynik["usuniete"] == ["p99u1"]
    assert klient.usuniete == [{"id": "p99u1"}]
    assert len({d["id"] for d in klient.wgrane}) == 66
    assert klient_indeksow.indeksy[0].name == "owu-mienie-v1"


def test_indeksacja_czeka_az_indeks_policzy_wszystkie_dokumenty(monkeypatch):
    from rag import indeksuj_owu

    class Klient:
        liczby = iter([0, 40, 66])

        def get_document_count(self):
            return next(self.liczby)

    monkeypatch.setattr(indeksuj_owu.time, "sleep", lambda s: None)
    klient = Klient()
    indeksuj_owu._czekaj_na_indeksacje(klient, 66)
    assert next(klient.liczby, "wyczerpane") == "wyczerpane"
