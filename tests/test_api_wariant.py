"""Etap 24, zadanie 4: przelacznik `GRAF_WARIANT` w ustawieniach i w API (atrapa, InMemorySaver, SQLite, zero sieci)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent.graf import WARIANTY_GRAFU
from api.agent_serwis import SerwisAgenta
from api.magazyn import MagazynPamieciowy
from api.main import utworz_aplikacje
from api.ustawienia import GRAF_WARIANTY_DOZWOLONE, Ustawienia
from ewaluacja.atrapa import ModelAtrapa
from rag.wyszukiwarka import WyszukiwarkaLokalna

ROOT = Path(__file__).resolve().parent.parent
OCZEKIWANE = ROOT / "dane" / "oczekiwane"
PLIK_W01 = ROOT / "dane" / "wnioski" / "W01.pdf"
PLIK_W14 = ROOT / "dane" / "wnioski" / "W14.pdf"
PLIK_Z01 = ROOT / "dane" / "szkody" / "Z01.pdf"
PLIK_Z09 = ROOT / "dane" / "szkody" / "Z09.pdf"

AZURITE = "UseDevelopmentStorage=true"


def _ustawienia(**kw) -> Ustawienia:
    return Ustawienia(database_url="sqlite://", azure_storage_connection_string=AZURITE, model_agenta="atrapa", **kw)


def _klient(monkeypatch, **kw):
    monkeypatch.setenv("MODEL_AGENTA", "atrapa")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    aplikacja = utworz_aplikacje(
        _ustawienia(**kw),
        magazyn=MagazynPamieciowy(),
        checkpointer=InMemorySaver(),
        model=ModelAtrapa(OCZEKIWANE),
        wyszukiwarka=WyszukiwarkaLokalna(),
    )
    return TestClient(aplikacja)


def _wyslij_i_czekaj(klient, sciezka: Path) -> dict:
    odp = klient.post("/wnioski", files={"plik": (sciezka.name, sciezka.read_bytes(), "application/pdf")})
    assert odp.status_code == 202
    wniosek_id = odp.json()["id"]
    start = time.monotonic()
    while time.monotonic() - start < 5.0:
        stan = klient.get(f"/wnioski/{wniosek_id}").json()
        if stan["status"] in {"CZEKA_NA_DECYZJE", "BLAD"}:
            return stan
        time.sleep(0.05)
    raise AssertionError(f"{sciezka.name}: brak CZEKA_NA_DECYZJE w 5 s")


# ---------------------------------------------------------------------------
# Ustawienia
# ---------------------------------------------------------------------------

def test_dozwolone_warianty_w_ustawieniach_to_te_z_grafu():
    assert GRAF_WARIANTY_DOZWOLONE == WARIANTY_GRAFU


def test_domyslny_wariant_to_jeden():
    assert _ustawienia().graf_wariant == "jeden"


def test_z_env_bez_zmiennej_daje_jeden(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", AZURITE)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    monkeypatch.delenv("GRAF_WARIANT", raising=False)
    assert Ustawienia.z_env().graf_wariant == "jeden"


@pytest.mark.parametrize("wariant", WARIANTY_GRAFU)
def test_z_env_czyta_graf_wariant(monkeypatch, wariant):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", AZURITE)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    monkeypatch.setenv("GRAF_WARIANT", wariant)
    assert Ustawienia.z_env().graf_wariant == wariant


def test_z_env_zla_wartosc_to_blad_startu(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", AZURITE)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    monkeypatch.setenv("GRAF_WARIANT", "wieloagentowo")
    with pytest.raises(RuntimeError, match="GRAF_WARIANT"):
        Ustawienia.z_env()


def test_bezposrednia_konstrukcja_ze_zla_wartoscia_tez_rzuca():
    with pytest.raises(RuntimeError, match="GRAF_WARIANT"):
        _ustawienia(graf_wariant="trzy")


def test_serwis_ze_zlym_wariantem_nie_startuje():
    with pytest.raises(ValueError, match="Nieznany wariant"):
        SerwisAgenta(ModelAtrapa(OCZEKIWANE), InMemorySaver(), MagazynPamieciowy(), graf_wariant="trzy")


# ---------------------------------------------------------------------------
# Serwis: ktory graf jest zbudowany
# ---------------------------------------------------------------------------

def _wezly(serwis: SerwisAgenta) -> set[str]:
    return set(serwis.graf.get_graph().nodes)


def test_serwis_domyslnie_buduje_graf_jeden():
    wezly = _wezly(SerwisAgenta(ModelAtrapa(OCZEKIWANE), InMemorySaver(), MagazynPamieciowy()))
    assert "klasyfikuj" in wezly and "supervisor" not in wezly


def test_serwis_wieloagentowy_buduje_graf_z_supervisorem():
    serwis = SerwisAgenta(ModelAtrapa(OCZEKIWANE), InMemorySaver(), MagazynPamieciowy(), graf_wariant="wieloagentowy")
    wezly = _wezly(serwis)
    assert "supervisor" in wezly and "agent_szkod" in wezly and "klasyfikuj" not in wezly


def test_ustaw_model_ryzyka_zachowuje_wariant():
    serwis = SerwisAgenta(ModelAtrapa(OCZEKIWANE), InMemorySaver(), MagazynPamieciowy(), graf_wariant="wieloagentowy")
    serwis.ustaw_model_ryzyka(None)
    assert "supervisor" in _wezly(serwis)


# ---------------------------------------------------------------------------
# API end-to-end w obu wariantach
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wariant", WARIANTY_GRAFU)
def test_api_wniosek_w01_w_obu_wariantach(monkeypatch, wariant):
    with _klient(monkeypatch, graf_wariant=wariant) as klient:
        stan = _wyslij_i_czekaj(klient, PLIK_W01)
    assert stan["status"] == "CZEKA_NA_DECYZJE"
    assert stan["podsumowanie"]["rekomendacja"]["decyzja"] == "AKCEPTACJA"
    if wariant == "jeden":
        assert "orkiestracja" not in stan["podsumowanie"]
    else:
        assert stan["podsumowanie"]["orkiestracja"]["wariant"] == "wieloagentowy"
        assert stan["podsumowanie"]["orkiestracja"]["trasa_agentow"] == ["agent_underwritingu"]


@pytest.mark.parametrize("wariant", WARIANTY_GRAFU)
def test_api_szkoda_z01_w_obu_wariantach(monkeypatch, wariant):
    with _klient(monkeypatch, graf_wariant=wariant) as klient:
        stan = _wyslij_i_czekaj(klient, PLIK_Z01)
    assert stan["status"] == "CZEKA_NA_DECYZJE"
    assert stan["podsumowanie"]["typ_dokumentu"] == "SZKODA"
    assert stan["podsumowanie"]["decyzja"] == "POKRYTA"
    assert stan["podsumowanie"]["cytaty"][0]["fragment_id"] == "p4u1"
    if wariant == "wieloagentowy":
        assert stan["podsumowanie"]["orkiestracja"]["trasa_agentow"] == ["agent_szkod", "agent_owu"]
    else:
        assert "orkiestracja" not in stan["podsumowanie"]


def test_api_szkoda_z09_wieloagentowy_bez_owu(monkeypatch):
    with _klient(monkeypatch, graf_wariant="wieloagentowy") as klient:
        stan = _wyslij_i_czekaj(klient, PLIK_Z09)
    assert stan["podsumowanie"]["orkiestracja"]["trasa_agentow"] == ["agent_szkod"]


@pytest.mark.parametrize("wariant", WARIANTY_GRAFU)
def test_api_decyzja_czlowieka_konczy_wniosek_w_obu_wariantach(monkeypatch, wariant):
    """Wznowienie po `interrupt` (zatwierdzenie w rodzicu) dziala przez API w obu wariantach."""
    with _klient(monkeypatch, graf_wariant=wariant) as klient:
        stan = _wyslij_i_czekaj(klient, PLIK_W01)
        odp = klient.post(
            f"/wnioski/{stan['id']}/decyzja",
            json={"decyzja": "AKCEPTACJA", "komentarz": None},
            headers={"X-Uzytkownik": "jan.kowalski"},
        )
        assert odp.status_code == 200, odp.text
    assert odp.json()["status"] == "ZAKONCZONY"
    assert odp.json()["decyzja_koncowa"] == "AKCEPTACJA"


@pytest.mark.parametrize("wariant", WARIANTY_GRAFU)
def test_api_inny_dokument_w_obu_wariantach(monkeypatch, wariant):
    with _klient(monkeypatch, graf_wariant=wariant) as klient:
        odp = klient.post("/wnioski", files={"plik": ("W14.pdf", PLIK_W14.read_bytes(), "application/pdf")})
        wniosek_id = odp.json()["id"]
        start = time.monotonic()
        while time.monotonic() - start < 5.0:
            stan = klient.get(f"/wnioski/{wniosek_id}").json()
            if stan["status"] != "PRZETWARZANIE":
                break
            time.sleep(0.05)
    assert stan["status"] == "INNY_DOKUMENT"
    assert stan["decyzja_koncowa"] == "NIE_DOTYCZY"


def test_utworz_aplikacje_czyta_wariant_z_ustawien(monkeypatch):
    monkeypatch.setenv("MODEL_AGENTA", "atrapa")
    aplikacja = utworz_aplikacje(
        _ustawienia(graf_wariant="wieloagentowy"),
        magazyn=MagazynPamieciowy(),
        checkpointer=InMemorySaver(),
        model=ModelAtrapa(OCZEKIWANE),
        wyszukiwarka=WyszukiwarkaLokalna(),
    )
    assert "supervisor" in _wezly(aplikacja.state.serwis)
