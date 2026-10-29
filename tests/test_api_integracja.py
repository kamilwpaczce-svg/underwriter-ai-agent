"""Testy integracyjne Etapu 3 - wymagaja Postgresa i Azurite z `docker compose up -d`.

Glowny dowod tego etapu: PostgresSaver przezywa restart procesu API - wniosek
zatrzymany w CZEKA_NA_DECYZJE przez jedna instancje aplikacji (jedna pula polaczen,
jeden skompilowany graf) jest poprawnie wznawiany przez zupelnie nowa instancje
(nowa pula polaczen, nowy graf, zaden wspolny obiekt Pythona) po "restarcie".

Uruchomienie: docker compose up -d && pytest -m integracja
Pomijane automatycznie, gdy Postgres (localhost:5432) albo Azurite (localhost:10000)
nie odpowiadaja - patrz `_wymagana_infrastruktura` (czytelny powod w komunikacie skip).
"""

from __future__ import annotations

import socket
import uuid
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import utworz_aplikacje
from api.ustawienia import Ustawienia

ROOT = Path(__file__).resolve().parent.parent
PLIK_W01 = ROOT / "dane" / "wnioski" / "W01.pdf"

DATABASE_URL = "postgresql://underwriter:underwriter@localhost:5432/underwriter"
# Znany publiczny klucz deweloperski Azurite - nie jest sekretem (patrz .env.example).
AZURE_CS = (
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)
KONTENER_TESTOWY = "wnioski-integracja"

pytestmark = pytest.mark.integracja


def _port_otwarty(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module", autouse=True)
def _wymagana_infrastruktura():
    if not _port_otwarty("localhost", 5432):
        pytest.skip("Postgres (localhost:5432) nie odpowiada - uruchom `docker compose up -d`.")
    if not _port_otwarty("localhost", 10000):
        pytest.skip("Azurite (localhost:10000) nie odpowiada - uruchom `docker compose up -d`.")


@pytest.fixture(autouse=True)
def _bez_gemini(monkeypatch):
    monkeypatch.setenv("MODEL_AGENTA", "atrapa")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _ustawienia() -> Ustawienia:
    return Ustawienia(
        database_url=DATABASE_URL,
        azure_storage_connection_string=AZURE_CS,
        kontener_blob=KONTENER_TESTOWY,
        model_agenta="atrapa",
    )


def _czekaj_na_status(klient, wniosek_id: str, oczekiwane: set[str], timeout: float = 15.0) -> dict:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        odp = klient.get(f"/wnioski/{wniosek_id}")
        assert odp.status_code == 200
        if odp.json()["status"] in oczekiwane:
            return odp.json()
        time.sleep(0.1)
    raise AssertionError(f"Wniosek {wniosek_id} nie osiagnal statusu z {oczekiwane} w {timeout}s")


def test_upload_przez_prawdziwy_azurite_i_postgres():
    """Caly przeplyw na prawdziwej infrastrukturze - zero atrap magazynu/bazy/checkpointera."""
    aplikacja = utworz_aplikacje(_ustawienia())
    with TestClient(aplikacja) as klient:
        odp = klient.post("/wnioski", files={"plik": ("W01.pdf", PLIK_W01.read_bytes(), "application/pdf")})
        assert odp.status_code == 202
        wniosek_id = odp.json()["id"]

        stan = _czekaj_na_status(klient, wniosek_id, {"CZEKA_NA_DECYZJE", "BLAD"})
        assert stan["status"] == "CZEKA_NA_DECYZJE"
        assert stan["podsumowanie"]["rekomendacja"]["decyzja"] == "AKCEPTACJA"

        dokument = klient.get(f"/wnioski/{wniosek_id}/dokument")
        assert dokument.status_code == 200
        assert dokument.content == PLIK_W01.read_bytes()
        assert dokument.headers["content-type"] == "application/pdf"

        odp_decyzja = klient.post(
            f"/wnioski/{wniosek_id}/decyzja",
            json={"decyzja": "AKCEPTACJA"},
            headers={"X-Uzytkownik": "test.integracja"},
        )
        assert odp_decyzja.status_code == 200
        assert odp_decyzja.json()["status"] == "ZAKONCZONY"


def test_checkpointer_przezywa_restart_procesu_api():
    """Glowny dowod Etapu 3: nowa instancja aplikacji (nowa pula polaczen do Postgresa,
    nowy skompilowany graf) wznawia wniosek zatrzymany na interrupt() przez POPRZEDNIA,
    juz zamknieta instancje - bez dzielenia ani jednego obiektu Pythona miedzy nimi."""
    ustawienia = _ustawienia()

    aplikacja_1 = utworz_aplikacje(ustawienia)
    with TestClient(aplikacja_1) as klient_1:
        odp = klient_1.post("/wnioski", files={"plik": ("W01.pdf", PLIK_W01.read_bytes(), "application/pdf")})
        assert odp.status_code == 202
        wniosek_id = odp.json()["id"]
        stan = _czekaj_na_status(klient_1, wniosek_id, {"CZEKA_NA_DECYZJE", "BLAD"})
        assert stan["status"] == "CZEKA_NA_DECYZJE"
    # Wyjscie z `with` zamyka lifespan aplikacji_1: pula polaczen do Postgresa jest
    # zamknieta, obiekt grafu/checkpointera porzucony - symulacja restartu procesu API.

    aplikacja_2 = utworz_aplikacje(ustawienia)
    with TestClient(aplikacja_2) as klient_2:
        odp_decyzja = klient_2.post(
            f"/wnioski/{wniosek_id}/decyzja",
            json={"decyzja": "AKCEPTACJA"},
            headers={"X-Uzytkownik": "test.restart"},
        )
        assert odp_decyzja.status_code == 200
        assert odp_decyzja.json()["status"] == "ZAKONCZONY"
        assert odp_decyzja.json()["decyzja_koncowa"] == "AKCEPTACJA"
        assert odp_decyzja.json()["zatwierdzil"] == "test.restart"

        audyt = klient_2.get(f"/wnioski/{wniosek_id}/audyt").json()
        zdarzenia = [z["zdarzenie"] for z in audyt]
        assert zdarzenia == ["PRZYJETO", "REKOMENDACJA", "DECYZJA"]


def test_wejscie_modelu_ryzyka_zapisane_w_postgresie_po_zgloszeniu_szkody(tmp_path, monkeypatch):
    """Etap 15: model z prawdziwego Blob (Azurite) -> API -> wiersz w `wejscia_modelu` (Postgres,
    schemat z `alembic upgrade head`, migracja nr 2). Wymaga tej samej infrastruktury co reszta pliku."""
    from azure.storage.blob import BlobServiceClient
    from sqlalchemy import select

    from api.baza import WejscieModelu
    from ewaluacja.atrapa import ModelAtrapa
    from rag.wyszukiwarka import WyszukiwarkaLokalna
    from ryzyko.cechy import CECHY
    from ryzyko.generator import generuj_zbior
    from ryzyko.model import zbuduj_pipeline
    from ryzyko.psi import referencja
    from ryzyko.serwowanie import (
        PLIK_METADANYCH,
        PLIK_MODELU,
        PLIK_REFERENCJI,
        PREFIKS_DOMYSLNY,
        zapisz_do_katalogu,
    )

    kontener_modeli = "modele-integracja"
    monkeypatch.setenv("KONTENER_MODELI", kontener_modeli)
    zbior = generuj_zbior(1500, seed=11)
    model = zbuduj_pipeline("hgb")
    model.fit(zbior[CECHY], zbior["do_weryfikacji"])
    zapisz_do_katalogu(model, "v-integracja", referencja(zbior), tmp_path)
    serwis_blob = BlobServiceClient.from_connection_string(AZURE_CS)
    kontener = serwis_blob.get_container_client(kontener_modeli)
    if not kontener.exists():
        kontener.create_container()
    for nazwa in (PLIK_MODELU, PLIK_REFERENCJI, PLIK_METADANYCH):
        kontener.upload_blob(PREFIKS_DOMYSLNY + nazwa, (tmp_path / nazwa).read_bytes(), overwrite=True)

    szkoda = ROOT / "dane" / "szkody" / "Z01.pdf"
    aplikacja = utworz_aplikacje(
        _ustawienia(), model=ModelAtrapa(ROOT / "dane" / "oczekiwane"), wyszukiwarka=WyszukiwarkaLokalna()
    )
    with TestClient(aplikacja) as klient:
        assert klient.get("/zdrowie").json()["model_ryzyka"] == "v-integracja"
        odp = klient.post("/wnioski", files={"plik": ("Z01.pdf", szkoda.read_bytes(), "application/pdf")})
        assert odp.status_code == 202
        wniosek_id = odp.json()["id"]
        stan = _czekaj_na_status(klient, wniosek_id, {"CZEKA_NA_DECYZJE", "BLAD"})
        assert stan["status"] == "CZEKA_NA_DECYZJE"
        assert stan["podsumowanie"]["ryzyko"]["status"] == "OK"
        with aplikacja.state.fabryka_sesji() as sesja:
            wiersze = list(sesja.scalars(select(WejscieModelu).where(WejscieModelu.wniosek_id == uuid.UUID(wniosek_id))).all())
        assert len(wiersze) == 1
        assert (wiersze[0].wersja_modelu, wiersze[0].zrodlo) == ("v-integracja", "api")
        assert set(wiersze[0].cechy) == set(CECHY)
