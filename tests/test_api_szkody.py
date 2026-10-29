"""API dla zgloszen szkod (Etap 10) - atrapa, InMemorySaver, SQLite, BM25 lokalny, zero sieci."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from api.magazyn import MagazynPamieciowy
from api.main import utworz_aplikacje
from api.ustawienia import Ustawienia
from ewaluacja.atrapa import ModelAtrapa
from rag.wyszukiwarka import WyszukiwarkaLokalna

ROOT = Path(__file__).resolve().parent.parent
SZKODY = ROOT / "dane" / "szkody"
PLIK_W01 = ROOT / "dane" / "wnioski" / "W01.pdf"


@pytest.fixture
def klient(monkeypatch):
    monkeypatch.setenv("MODEL_AGENTA", "atrapa")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ustawienia = Ustawienia(
        database_url="sqlite://",
        azure_storage_connection_string="UseDevelopmentStorage=true",
        model_agenta="atrapa",
    )
    aplikacja = utworz_aplikacje(
        ustawienia,
        magazyn=MagazynPamieciowy(),
        checkpointer=InMemorySaver(),
        model=ModelAtrapa(ROOT / "dane" / "oczekiwane"),
        wyszukiwarka=WyszukiwarkaLokalna(),
    )
    with TestClient(aplikacja) as klient_testowy:
        yield klient_testowy


def _wyslij_i_czekaj(klient, sciezka: Path, zdjecie: Path | None = None) -> dict:
    pliki = {"plik": (sciezka.name, sciezka.read_bytes(), "application/pdf")}
    if zdjecie is not None:
        pliki["zdjecie"] = (zdjecie.name, zdjecie.read_bytes(), "image/jpeg")
    odp = klient.post("/wnioski", files=pliki)
    assert odp.status_code == 202
    wniosek_id = odp.json()["id"]
    start = time.monotonic()
    while time.monotonic() - start < 5.0:
        stan = klient.get(f"/wnioski/{wniosek_id}").json()
        if stan["status"] in {"CZEKA_NA_DECYZJE", "BLAD"}:
            return stan
        time.sleep(0.05)
    raise AssertionError(f"{sciezka.name}: brak CZEKA_NA_DECYZJE w 5 s")


def _decyzja(klient, wniosek_id: str, decyzja: str, komentarz: str | None = None):
    return klient.post(
        f"/wnioski/{wniosek_id}/decyzja",
        json={"decyzja": decyzja, "komentarz": komentarz},
        headers={"X-Uzytkownik": "anna.underwriter@example.com"},
    )


def test_szkoda_z01_czeka_na_decyzje_z_cytatem_i_trescia(klient):
    stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf")
    assert stan["status"] == "CZEKA_NA_DECYZJE"
    podsumowanie = stan["podsumowanie"]
    assert podsumowanie["typ_dokumentu"] == "SZKODA"
    assert podsumowanie["decyzja"] == "POKRYTA"
    assert podsumowanie["cytaty"][0]["fragment_id"] == "p4u1"
    assert podsumowanie["cytaty"][0]["tresc"].startswith("§ 4.")
    assert podsumowanie["wynik_polisy"]["kody"] == []

    lista = {w["id"]: w for w in klient.get("/wnioski").json()}
    assert lista[stan["id"]]["typ_dokumentu"] == "SZKODA"


def test_zatwierdzenie_pokryta_zapisuje_audyt(klient):
    stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf")
    odp = _decyzja(klient, stan["id"], "POKRYTA")
    assert odp.status_code == 200
    assert odp.json()["status"] == "ZAKONCZONY"
    assert odp.json()["decyzja_koncowa"] == "POKRYTA"
    decyzje = [z for z in klient.get(f"/wnioski/{stan['id']}/audyt").json() if z["zdarzenie"] == "DECYZJA"]
    assert decyzje[0]["dane"]["decyzja_silnika"] == "POKRYTA"
    assert decyzje[0]["dane"]["odejscie_od_rekomendacji"] is False


def test_akceptacja_niedozwolona_dla_szkody(klient):
    stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf")
    odp = _decyzja(klient, stan["id"], "AKCEPTACJA", komentarz="test")
    assert odp.status_code == 422
    assert "niedozwolona" in odp.json()["detail"]
    assert klient.get(f"/wnioski/{stan['id']}").json()["status"] == "CZEKA_NA_DECYZJE"


def test_pokryta_niedozwolona_dla_wniosku(klient):
    stan = _wyslij_i_czekaj(klient, PLIK_W01)
    assert klient.get("/wnioski").json()[0]["typ_dokumentu"] == "WNIOSEK"
    odp = _decyzja(klient, stan["id"], "POKRYTA", komentarz="test")
    assert odp.status_code == 422
    assert "AKCEPTACJA" in odp.json()["detail"]


def test_szkoda_z10_rekomendacja_to_decyzja_po_regulach(klient):
    """Z10: LLM mowi POKRYTA, reguly S03 (kwota > SU) daja SKIEROWANIE. Zgoda z SKIEROWANIE
    nie wymaga komentarza; POKRYTA (odejscie od rekomendacji) - wymaga."""
    stan = _wyslij_i_czekaj(klient, SZKODY / "Z10.pdf")
    assert stan["podsumowanie"]["decyzja"] == "SKIEROWANIE"
    assert stan["podsumowanie"]["decyzja_llm"] == "POKRYTA"
    assert _decyzja(klient, stan["id"], "POKRYTA").status_code == 422
    odp = _decyzja(klient, stan["id"], "SKIEROWANIE")
    assert odp.status_code == 200
    decyzje = [z for z in klient.get(f"/wnioski/{stan['id']}/audyt").json() if z["zdarzenie"] == "DECYZJA"]
    assert decyzje[0]["dane"]["rekomendacja_llm"] == "POKRYTA"


def test_dockerfile_kopiuje_pliki_modulu_szkodowego():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for linia in (
        "COPY rag/ rag/",
        "COPY owu/ owu/",
        "COPY dane/polisy.json dane/polisy.json",
        "COPY dane/szkody/oczekiwane/ dane/szkody/oczekiwane/",
    ):
        assert linia in dockerfile


def test_dockerfile_kopiuje_kazdy_lokalny_pakiet_importowany_przez_obraz():
    # 2026-10-21: obraz Etapu 13 bez COPY obserwowalnosc/ - api.main padal na imporcie,
    # rewizja uw-api--0000019 ActivationFailed. Pilnuje calej klasy bledu, nie jednego katalogu.
    import re

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    lokalne = {p.name for p in ROOT.iterdir() if (p / "__init__.py").exists()}
    do_sprawdzenia = [ROOT / "api", ROOT / "agent", ROOT / "rag"]
    importowane = set()
    for katalog in do_sprawdzenia:
        for plik in katalog.rglob("*.py"):
            for m in re.finditer(r"^\s*(?:from|import)\s+(\w+)", plik.read_text(encoding="utf-8"), re.M):
                if m.group(1) in lokalne:
                    importowane.add(m.group(1))
    brakujace = sorted(p for p in importowane if f"COPY {p}/ {p}/" not in dockerfile)
    assert brakujace == []


# ---------------------------------------------------------------------------
# Etap 23, zadanie 5: opcjonalne zdjecie przy zgloszeniu szkody
# ---------------------------------------------------------------------------

ZDJECIA = ROOT / "dane" / "zdjecia_szkod"
NAGLOWEK_PNG = b"\x89PNG\r\n\x1a\n"


def _wyslij_surowo(klient, zdjecie: tuple | None, plik: Path = SZKODY / "Z01.pdf"):
    pliki = {"plik": (plik.name, plik.read_bytes(), "application/pdf")}
    if zdjecie is not None:
        pliki["zdjecie"] = zdjecie
    return klient.post("/wnioski", files=pliki)


def _czekaj_na_stan(klient, wniosek_id: str) -> dict:
    start = time.monotonic()
    while time.monotonic() - start < 5.0:
        stan = klient.get(f"/wnioski/{wniosek_id}").json()
        if stan["status"] in {"CZEKA_NA_DECYZJE", "BLAD"}:
            return stan
        time.sleep(0.05)
    raise AssertionError("brak CZEKA_NA_DECYZJE w 5 s")


def test_szkoda_bez_zdjecia_dziala_jak_dotad_i_panel_pokazuje_brak_zdjecia(klient):
    stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf")
    assert stan["status"] == "CZEKA_NA_DECYZJE"
    assert stan["podsumowanie"]["decyzja"] == "POKRYTA"
    assert stan["podsumowanie"]["zdjecie"]["status"] == "BRAK_ZDJECIA"


def test_szkoda_ze_zdjeciem_z01_panel_ma_status_ok_i_zgodne(klient):
    stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf", zdjecie=ZDJECIA / "Z01.jpg")
    assert stan["status"] == "CZEKA_NA_DECYZJE"
    zdjecie = stan["podsumowanie"]["zdjecie"]
    assert zdjecie["status"] == "OK"
    assert zdjecie["zgodnosc_rodzaju"] == "ZGODNE"
    assert stan["podsumowanie"]["decyzja"] == "POKRYTA"  # zdjecie jest sygnalem, nie zmienia decyzji


def test_szkoda_ze_zdjeciem_innego_zdarzenia_panel_pokazuje_niezgodne(klient):
    """Para N1: zdjecie zalania (Z02) pod zgloszenie pozaru (Z01)."""
    stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf", zdjecie=ZDJECIA / "Z02.jpg")
    zdjecie = stan["podsumowanie"]["zdjecie"]
    assert (zdjecie["status"], zdjecie["zgodnosc_rodzaju"]) == ("OK", "NIEZGODNE")
    assert stan["podsumowanie"]["decyzja"] == "POKRYTA"


def test_zdjecie_zly_typ_to_415_i_nic_nie_zostaje_w_systemie(klient):
    for nazwa, tresc in [("a.gif", b"GIF89a-dane"), ("a.pdf", b"%PDF-1.4"), ("bez_rozszerzenia", b"x")]:
        odp = _wyslij_surowo(klient, (nazwa, tresc, "image/jpeg"))
        assert odp.status_code == 415, nazwa
    assert klient.get("/wnioski").json() == []  # odrzucone zdjecie nie zostawia wniosku ani bloba dokumentu


def test_zdjecie_za_duze_to_413(klient):
    from agent.zdjecia import MAKS_ROZMIAR_BAJTOW

    za_duze = b"\xff\xd8\xff" + b"x" * MAKS_ROZMIAR_BAJTOW  # o 3 bajty ponad limit
    odp = _wyslij_surowo(klient, ("duze.jpg", za_duze, "image/jpeg"))
    assert odp.status_code == 413
    assert klient.get("/wnioski").json() == []


def test_zdjecie_dokladnie_na_limicie_jest_przyjete(klient):
    from agent.zdjecia import MAKS_ROZMIAR_BAJTOW

    na_limicie = b"\xff\xd8\xff" + b"x" * (MAKS_ROZMIAR_BAJTOW - 3)
    odp = _wyslij_surowo(klient, ("limit.jpg", na_limicie, "image/jpeg"))
    assert odp.status_code == 202
    assert _czekaj_na_stan(klient, odp.json()["id"])["status"] == "CZEKA_NA_DECYZJE"


@pytest.mark.parametrize("nazwa", ["a.jpg", "a.jpeg", "a.png", "A.JPG"])
def test_zdjecie_dozwolone_rozszerzenia_sa_przyjmowane(klient, nazwa):
    tresc = NAGLOWEK_PNG + b"-dane" if nazwa.lower().endswith(".png") else (ZDJECIA / "Z01.jpg").read_bytes()
    odp = _wyslij_surowo(klient, (nazwa, tresc, "image/jpeg"))
    assert odp.status_code == 202
    assert _czekaj_na_stan(klient, odp.json()["id"])["status"] in {"CZEKA_NA_DECYZJE", "BLAD"}


def test_zdjecie_z_niezgodnym_naglowkiem_to_blad_odczytu_w_panelu(klient):
    """PNG pod nazwa .jpg: API przyjmuje (202), a panel pokazuje BLAD_ODCZYTU z powodem - nie puste miejsce."""
    odp = _wyslij_surowo(klient, ("udaje.jpg", NAGLOWEK_PNG + b"-dane", "image/jpeg"))
    assert odp.status_code == 202
    stan = _czekaj_na_stan(klient, odp.json()["id"])
    assert stan["status"] == "CZEKA_NA_DECYZJE"
    zdjecie = stan["podsumowanie"]["zdjecie"]
    assert zdjecie["status"] == "BLAD_ODCZYTU"
    assert "niezgodny_naglowek" in zdjecie["powody"]


def test_zdjecie_trafia_do_magazynu_pod_nazwa_wniosek_id_zdjecie_rozszerzenie(klient):
    zdjecie = ZDJECIA / "Z01.jpg"
    odp = _wyslij_surowo(klient, (zdjecie.name, zdjecie.read_bytes(), "image/jpeg"))
    wniosek_id = odp.json()["id"]
    magazyn = klient.app.state.magazyn
    assert magazyn.pobierz(f"{wniosek_id}_zdjecie.jpg") == zdjecie.read_bytes()
    assert magazyn.pobierz(f"{wniosek_id}.pdf") == (SZKODY / "Z01.pdf").read_bytes()


def test_pliki_tymczasowe_sa_usuwane_po_przebiegu_ze_zdjeciem(klient, monkeypatch):
    import tempfile

    utworzone: list[Path] = []
    oryginal = tempfile.NamedTemporaryFile

    def nagrywaj(*args, **kwargs):
        plik = oryginal(*args, **kwargs)
        utworzone.append(Path(plik.name))
        return plik

    monkeypatch.setattr("api.agent_serwis.tempfile.NamedTemporaryFile", nagrywaj)
    stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf", zdjecie=ZDJECIA / "Z01.jpg")
    assert stan["status"] == "CZEKA_NA_DECYZJE"
    assert sorted(p.suffix for p in utworzone) == [".jpg", ".pdf"]  # dokument i zdjecie
    assert [p for p in utworzone if p.exists()] == []


def test_pliki_tymczasowe_sa_usuwane_tez_gdy_graf_rzuca_wyjatek(klient, monkeypatch):
    import tempfile

    utworzone: list[Path] = []
    oryginal = tempfile.NamedTemporaryFile

    def nagrywaj(*args, **kwargs):
        plik = oryginal(*args, **kwargs)
        utworzone.append(Path(plik.name))
        return plik

    class GrafKtoryPada:
        def invoke(self, *args, **kwargs):
            raise RuntimeError("awaria grafu w tescie")

    monkeypatch.setattr("api.agent_serwis.tempfile.NamedTemporaryFile", nagrywaj)
    monkeypatch.setattr(klient.app.state.serwis, "graf", GrafKtoryPada())
    zdjecie = ZDJECIA / "Z01.jpg"
    odp = _wyslij_surowo(klient, (zdjecie.name, zdjecie.read_bytes(), "image/jpeg"))
    assert odp.status_code == 202
    assert _czekaj_na_stan(klient, odp.json()["id"])["status"] == "BLAD"
    assert sorted(p.suffix for p in utworzone) == [".jpg", ".pdf"]
    assert [p for p in utworzone if p.exists()] == []
