"""WyszukiwarkaQdrant - Qdrant w trybie `:memory:` + atrapa embeddera, zero sieci (Etap 12).

Tryb `rzadki` uzywa prawdziwego tokenizera (`rag.wyszukiwarka.tokenizuj`), wiec te same 3
zapytania co w `test_wyszukiwarka_lokalna.py` musza trafic w te same ustepy OWU - to sprawdza,
ze wlasny BM25-w-Qdrancie jest spojny z wersja lokalna, nie tylko ze "cos sie zwraca"."""

from __future__ import annotations

import pytest

pytest.importorskip("qdrant_client")

from qdrant_client import QdrantClient  # noqa: E402

from rag.azure_search import BrakKonfiguracjiWyszukiwarki, WYMIARY_WEKTORA, zbuduj_wyszukiwarke  # noqa: E402
from rag.fragmenty import podziel_owu, wersja_owu  # noqa: E402
from rag.qdrant_search import (  # noqa: E402
    KOLEKCJA_DOMYSLNA,
    NAZWA_WEKTORA_GESTEGO,
    NAZWA_WEKTORA_RZADKIEGO,
    WyszukiwarkaQdrant,
    definicja_kolekcji,
    hash_tokena,
    id_punktu,
    punkt_z_fragmentu,
    wektor_rzadki,
    zbuduj_klienta_qdrant,
)


def _embedder_stala(wektor=None):
    wektor = wektor or [0.1] * WYMIARY_WEKTORA

    def embeduj(teksty):
        return [list(wektor) for _ in teksty]

    return embeduj


@pytest.fixture(scope="module")
def kolekcja_w_pamieci():
    """Prawdziwy klient Qdrant `:memory:` z pelnym OWU - bez sieci i bez plikow na dysku."""
    klient = QdrantClient(":memory:")
    klient.create_collection(KOLEKCJA_DOMYSLNA, **definicja_kolekcji())
    wersja = wersja_owu()
    embeduj = _embedder_stala()
    punkty = [punkt_z_fragmentu(f, embeduj([f.tresc])[0], wersja) for f in podziel_owu()]
    klient.upsert(collection_name=KOLEKCJA_DOMYSLNA, points=punkty)
    return klient


def test_hash_tokena_jest_stabilny_i_w_zakresie():
    assert hash_tokena("pozar") == hash_tokena("pozar")
    assert hash_tokena("pozar") != hash_tokena("zalanie")
    assert 0 <= hash_tokena("pozar") < 2**31


def test_id_punktu_deterministyczny_i_rozny_dla_roznych_fragmentow():
    assert id_punktu("p4u1") == id_punktu("p4u1")
    assert id_punktu("p4u1") != id_punktu("p4u2")


def test_wektor_rzadki_pustego_tekstu_jest_pusty():
    pusty = wektor_rzadki("")
    assert pusty.indices == [] and pusty.values == []


def test_wektor_rzadki_tf_dla_powtorzonego_tokenu():
    wektor = wektor_rzadki("pożar pożar zalanie")
    mapowanie = dict(zip(wektor.indices, wektor.values))
    assert mapowanie[hash_tokena("pozar")] == 2.0
    assert mapowanie[hash_tokena("zalan")] == 1.0


def test_definicja_kolekcji_ma_wektor_gesty_i_rzadki():
    from qdrant_client import models

    definicja = definicja_kolekcji()
    gesty = definicja["vectors_config"][NAZWA_WEKTORA_GESTEGO]
    assert gesty.size == WYMIARY_WEKTORA
    assert gesty.distance == models.Distance.COSINE
    rzadki = definicja["sparse_vectors_config"][NAZWA_WEKTORA_RZADKIEGO]
    assert rzadki.modifier == models.Modifier.IDF


def test_nazwa_i_tryb_niepoprawny(kolekcja_w_pamieci):
    wyszukiwarka = WyszukiwarkaQdrant(kolekcja_w_pamieci, _embedder_stala(), kolekcja=KOLEKCJA_DOMYSLNA)
    assert wyszukiwarka.nazwa == "qdrant"
    with pytest.raises(ValueError, match="dozwolone"):
        WyszukiwarkaQdrant(kolekcja_w_pamieci, _embedder_stala(), tryb="niewlasciwy")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("zapytanie", "oczekiwany_id"),
    [
        ("pożar hali", "p4u1"),
        ("kradzież bez śladów włamania", "p6u6"),
        ("termin zgłoszenia szkody 7 dni", "p9u1"),
    ],
)
def test_tryb_rzadki_zgodny_z_wyszukiwarka_lokalna(kolekcja_w_pamieci, zapytanie, oczekiwany_id):
    wyszukiwarka = WyszukiwarkaQdrant(kolekcja_w_pamieci, _embedder_stala(), tryb="rzadki")
    wyniki = [f.id for f in wyszukiwarka.szukaj(zapytanie, 5)]
    assert oczekiwany_id in wyniki


def test_tryb_gesty_zwraca_najwyzej_k_fragmentow(kolekcja_w_pamieci):
    wyszukiwarka = WyszukiwarkaQdrant(kolekcja_w_pamieci, _embedder_stala(), tryb="gesty")
    assert len(wyszukiwarka.szukaj("dowolne zapytanie", 3)) == 3


def test_tryb_hybryda_laczy_prefetch_gesty_i_rzadki(kolekcja_w_pamieci):
    wyszukiwarka = WyszukiwarkaQdrant(kolekcja_w_pamieci, _embedder_stala(), tryb="hybryda")
    wyniki = wyszukiwarka.szukaj("pożar hali", 5)
    assert len(wyniki) == 5
    assert all(hasattr(f, "tresc") for f in wyniki)


def test_zbuduj_klienta_qdrant_wybiera_url_gdy_podany(monkeypatch):
    wywolania = []

    class AtrapaQdrantClient:
        def __init__(self, **kwargs):
            wywolania.append(kwargs)

    import qdrant_client

    monkeypatch.setattr(qdrant_client, "QdrantClient", AtrapaQdrantClient)
    zbuduj_klienta_qdrant({"QDRANT_URL": "http://localhost:6333", "QDRANT_PATH": "/powinno/byc/zignorowane"})
    assert wywolania[-1] == {"url": "http://localhost:6333"}


def test_zbuduj_klienta_qdrant_sciezka_lokalna_domyslna_gdy_brak_zmiennych(monkeypatch, tmp_path):
    wywolania = []

    class AtrapaQdrantClient:
        def __init__(self, **kwargs):
            wywolania.append(kwargs)

    import qdrant_client

    monkeypatch.setattr(qdrant_client, "QdrantClient", AtrapaQdrantClient)
    zbuduj_klienta_qdrant({})
    assert "path" in wywolania[-1] and wywolania[-1]["path"].endswith(".qdrant_lokalny")

    zbuduj_klienta_qdrant({"QDRANT_PATH": str(tmp_path / "moja_kolekcja")})
    assert wywolania[-1] == {"path": str(tmp_path / "moja_kolekcja")}


def test_fabryka_qdrant_wymaga_konfiguracji_embeddera():
    with pytest.raises(BrakKonfiguracjiWyszukiwarki, match="AZURE_OPENAI_ENDPOINT"):
        zbuduj_wyszukiwarke({"WYSZUKIWARKA": "qdrant"})


def test_fabryka_qdrant_odrzuca_zly_tryb():
    srodowisko = {
        "WYSZUKIWARKA": "qdrant",
        "AZURE_OPENAI_ENDPOINT": "https://uw-demo-aoai-xx1.openai.azure.com/",
        "QDRANT_TRYB": "niewlasciwy",
    }
    with pytest.raises(BrakKonfiguracjiWyszukiwarki, match="dozwolone"):
        zbuduj_wyszukiwarke(srodowisko)


def test_fabryka_qdrant_buduje_wyszukiwarke_bez_sieci(tmp_path):
    srodowisko = {
        "WYSZUKIWARKA": "qdrant",
        "AZURE_OPENAI_ENDPOINT": "https://uw-demo-aoai-xx1.openai.azure.com/",
        "QDRANT_PATH": str(tmp_path / "kolekcja"),
        "QDRANT_COLLECTION": "owu-test-v1",
    }
    wyszukiwarka = zbuduj_wyszukiwarke(srodowisko)
    assert isinstance(wyszukiwarka, WyszukiwarkaQdrant)
    assert wyszukiwarka.tryb == "hybryda"
    assert wyszukiwarka._kolekcja == "owu-test-v1"
