"""Testy API (FastAPI) - bez Dockera i bez sieci.

`utworz_aplikacje` dostaje `MagazynPamieciowy`, `InMemorySaver`, `ModelAtrapa` i baze
SQLite w pamieci. Zero wywolan Gemini: fixture `_bez_gemini` wymusza MODEL_AGENTA=atrapa
i usuwa GEMINI_API_KEY ze srodowiska testow.
"""

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

ROOT = Path(__file__).resolve().parent.parent
SCIEZKA_OCZEKIWANE = ROOT / "dane" / "oczekiwane"
PLIK_W01 = ROOT / "dane" / "wnioski" / "W01.pdf"
PLIK_W14 = ROOT / "dane" / "wnioski" / "W14.pdf"


@pytest.fixture(autouse=True)
def _bez_gemini(monkeypatch):
    monkeypatch.setenv("MODEL_AGENTA", "atrapa")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def magazyn() -> MagazynPamieciowy:
    return MagazynPamieciowy()


@pytest.fixture
def klient(magazyn):
    ustawienia = Ustawienia(
        database_url="sqlite://",
        azure_storage_connection_string="UseDevelopmentStorage=true",
        model_agenta="atrapa",
    )
    model = ModelAtrapa(SCIEZKA_OCZEKIWANE)
    aplikacja = utworz_aplikacje(ustawienia, magazyn=magazyn, checkpointer=InMemorySaver(), model=model)
    with TestClient(aplikacja) as klient_testowy:
        yield klient_testowy


def _wyslij(klient, sciezka: Path, nazwa: str | None = None, typ: str = "application/pdf"):
    nazwa = nazwa or sciezka.name
    return klient.post("/wnioski", files={"plik": (nazwa, sciezka.read_bytes(), typ)})


def _czekaj_na_status(klient, wniosek_id: str, oczekiwane: set[str], timeout: float = 5.0) -> dict:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        odp = klient.get(f"/wnioski/{wniosek_id}")
        assert odp.status_code == 200
        if odp.json()["status"] in oczekiwane:
            return odp.json()
        time.sleep(0.05)
    raise AssertionError(f"Wniosek {wniosek_id} nie osiagnal statusu z {oczekiwane} w {timeout}s")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def test_upload_wniosku_konczy_sie_czeka_na_decyzje_z_podsumowaniem(klient):
    odp = _wyslij(klient, PLIK_W01)
    assert odp.status_code == 202
    wniosek_id = odp.json()["id"]
    assert odp.json()["status"] == "PRZETWARZANIE"

    stan = _czekaj_na_status(klient, wniosek_id, {"CZEKA_NA_DECYZJE", "BLAD"})
    assert stan["status"] == "CZEKA_NA_DECYZJE"
    assert stan["podsumowanie"]["rekomendacja"]["decyzja"] == "AKCEPTACJA"
    assert stan["podsumowanie"]["decyzja_silnika"]["decyzja"] == "AKCEPTACJA"
    assert stan["podsumowanie"]["zgodnosc"] is True


def test_upload_w14_inny_dokument(klient):
    odp = _wyslij(klient, PLIK_W14)
    wniosek_id = odp.json()["id"]

    stan = _czekaj_na_status(klient, wniosek_id, {"INNY_DOKUMENT", "BLAD"})
    assert stan["status"] == "INNY_DOKUMENT"
    assert stan["decyzja_koncowa"] == "NIE_DOTYCZY"


def test_upload_zle_rozszerzenie_415(klient):
    odp = klient.post("/wnioski", files={"plik": ("notatka.txt", b"tresc", "text/plain")})
    assert odp.status_code == 415


def test_upload_za_duzy_413(klient):
    dane = b"0" * (10 * 1024 * 1024 + 1)
    odp = klient.post("/wnioski", files={"plik": ("duzy.pdf", dane, "application/pdf")})
    assert odp.status_code == 413


def test_upload_nieznany_atrapie_konczy_sie_bledem(klient):
    """Plik spoza W01-W14 - atrapa nie ma czym odpowiedziec -> BLAD + audyt BLAD."""
    odp = _wyslij(klient, PLIK_W01, nazwa="NIEZNANY.pdf")
    wniosek_id = odp.json()["id"]

    stan = _czekaj_na_status(klient, wniosek_id, {"BLAD", "CZEKA_NA_DECYZJE"})
    assert stan["status"] == "BLAD"

    audyt = klient.get(f"/wnioski/{wniosek_id}/audyt").json()
    zdarzenia = [z["zdarzenie"] for z in audyt]
    assert zdarzenia == ["PRZYJETO", "BLAD"]


# ---------------------------------------------------------------------------
# Decyzja
# ---------------------------------------------------------------------------

def _upload_i_czekaj(klient, plik: Path) -> str:
    odp = _wyslij(klient, plik)
    wniosek_id = odp.json()["id"]
    _czekaj_na_status(klient, wniosek_id, {"CZEKA_NA_DECYZJE"})
    return wniosek_id


def test_decyzja_zgodna_bez_komentarza_konczy_wniosek(klient):
    wniosek_id = _upload_i_czekaj(klient, PLIK_W01)

    odp = klient.post(
        f"/wnioski/{wniosek_id}/decyzja",
        json={"decyzja": "AKCEPTACJA"},
        headers={"X-Uzytkownik": "jan.kowalski"},
    )
    assert odp.status_code == 200
    assert odp.json()["status"] == "ZAKONCZONY"
    assert odp.json()["decyzja_koncowa"] == "AKCEPTACJA"
    assert odp.json()["zatwierdzil"] == "jan.kowalski"


def test_decyzja_niezgodna_bez_komentarza_422(klient):
    wniosek_id = _upload_i_czekaj(klient, PLIK_W01)

    odp = klient.post(
        f"/wnioski/{wniosek_id}/decyzja",
        json={"decyzja": "ODMOWA"},
        headers={"X-Uzytkownik": "jan.kowalski"},
    )
    assert odp.status_code == 422


def test_decyzja_niezgodna_z_komentarzem_przechodzi(klient):
    wniosek_id = _upload_i_czekaj(klient, PLIK_W01)

    odp = klient.post(
        f"/wnioski/{wniosek_id}/decyzja",
        json={"decyzja": "ODMOWA", "komentarz": "Dodatkowe ryzyko nieujete w regulach."},
        headers={"X-Uzytkownik": "jan.kowalski"},
    )
    assert odp.status_code == 200
    assert odp.json()["decyzja_koncowa"] == "ODMOWA"


def test_decyzja_ponowna_409(klient):
    wniosek_id = _upload_i_czekaj(klient, PLIK_W01)
    pierwsza = klient.post(
        f"/wnioski/{wniosek_id}/decyzja",
        json={"decyzja": "AKCEPTACJA"},
        headers={"X-Uzytkownik": "jan.kowalski"},
    )
    assert pierwsza.status_code == 200

    druga = klient.post(
        f"/wnioski/{wniosek_id}/decyzja",
        json={"decyzja": "AKCEPTACJA"},
        headers={"X-Uzytkownik": "jan.kowalski"},
    )
    assert druga.status_code == 409


def test_decyzja_brak_naglowka_uzytkownika_422(klient):
    wniosek_id = _upload_i_czekaj(klient, PLIK_W01)

    odp = klient.post(f"/wnioski/{wniosek_id}/decyzja", json={"decyzja": "AKCEPTACJA"})
    assert odp.status_code == 422


def test_audyt_w_kolejnosci_przyjeto_rekomendacja_decyzja(klient):
    wniosek_id = _upload_i_czekaj(klient, PLIK_W01)
    klient.post(
        f"/wnioski/{wniosek_id}/decyzja",
        json={"decyzja": "AKCEPTACJA"},
        headers={"X-Uzytkownik": "jan.kowalski"},
    )

    audyt = klient.get(f"/wnioski/{wniosek_id}/audyt").json()
    zdarzenia = [z["zdarzenie"] for z in audyt]
    assert zdarzenia == ["PRZYJETO", "REKOMENDACJA", "DECYZJA"]


# ---------------------------------------------------------------------------
# Lista, szczegoly, dokument
# ---------------------------------------------------------------------------

def test_lista_i_szczegoly_wniosku(klient):
    odp = _wyslij(klient, PLIK_W01)
    wniosek_id = odp.json()["id"]
    _czekaj_na_status(klient, wniosek_id, {"CZEKA_NA_DECYZJE"})

    lista = klient.get("/wnioski").json()
    assert any(w["id"] == wniosek_id for w in lista)

    szczegoly = klient.get(f"/wnioski/{wniosek_id}").json()
    assert szczegoly["nazwa_pliku"] == "W01.pdf"

    brak = klient.get("/wnioski/00000000-0000-0000-0000-000000000000")
    assert brak.status_code == 404


def test_dokument_zwraca_identyczne_bajty(klient):
    odp = _wyslij(klient, PLIK_W01)
    wniosek_id = odp.json()["id"]

    dokument = klient.get(f"/wnioski/{wniosek_id}/dokument")
    assert dokument.status_code == 200
    assert dokument.content == PLIK_W01.read_bytes()
    assert dokument.headers["content-type"] == "application/pdf"


# ---------------------------------------------------------------------------
# Zdrowie
# ---------------------------------------------------------------------------

def test_zdrowie_ok(klient):
    odp = klient.get("/zdrowie")
    assert odp.status_code == 200
    assert odp.json()["status"] == "ok"


def test_zdrowie_503_gdy_magazyn_niedostepny(klient, magazyn):
    magazyn.wyjatek_dostepnosci = RuntimeError("Azurite niedostepne")
    odp = klient.get("/zdrowie")
    assert odp.status_code == 503
