"""Cache embeddingow na dysku (Etap 12) - bez sieci, atrapa embeddera liczy wywolania."""

from __future__ import annotations

from rag.cache_embeddingow import embedder_z_cache


def _liczacy_embedder():
    wywolania = []

    def embeduj(teksty):
        wywolania.append(list(teksty))
        return [[float(len(t))] for t in teksty]

    return embeduj, wywolania


def test_drugie_wywolanie_tego_samego_tekstu_nie_dotyka_embeddera(tmp_path):
    embeduj, wywolania = _liczacy_embedder()
    plik = tmp_path / "cache.json"
    z_cache = embedder_z_cache(embeduj, plik)

    assert z_cache(["pożar hali"]) == [[10.0]]
    assert z_cache(["pożar hali"]) == [[10.0]]
    assert wywolania == [["pożar hali"]]
    assert plik.exists()


def test_tylko_brakujace_teksty_trafiaja_do_embeddera(tmp_path):
    embeduj, wywolania = _liczacy_embedder()
    plik = tmp_path / "cache.json"
    z_cache = embedder_z_cache(embeduj, plik)

    z_cache(["a", "bb"])
    z_cache(["bb", "ccc"])
    assert wywolania == [["a", "bb"], ["ccc"]]


def test_cache_przetrwa_nowa_instancje_wrappera(tmp_path):
    embeduj, wywolania = _liczacy_embedder()
    plik = tmp_path / "cache.json"
    embedder_z_cache(embeduj, plik)(["trwale"])
    assert len(wywolania) == 1

    embedder_z_cache(embeduj, plik)(["trwale"])
    assert len(wywolania) == 1  # druga "sesja" czyta z pliku, nie woluje embeddera ponownie


def test_rozne_modele_maja_osobne_klucze_cache(tmp_path):
    embeduj, wywolania = _liczacy_embedder()
    plik = tmp_path / "cache.json"
    embedder_z_cache(embeduj, plik, model="model-a")(["x"])
    embedder_z_cache(embeduj, plik, model="model-b")(["x"])
    assert len(wywolania) == 2
