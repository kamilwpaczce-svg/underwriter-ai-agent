"""Etap 15: model ryzyka w API - zapis wejsc modelu (SPEC decyzja 8), /zdrowie, panel.

Offline: SQLite, MagazynPamieciowy z prawdziwymi plikami skops w kontenerze `modele`,
atrapa LLM, BM25 lokalny, zero sieci.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select

from api.baza import Baza, WejscieModelu
from api.magazyn import MagazynPamieciowy
from api.main import utworz_aplikacje
from api.ustawienia import Ustawienia
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
    ModelRyzyka,
    zapisz_do_katalogu,
)

ROOT = Path(__file__).resolve().parent.parent
SZKODY = ROOT / "dane" / "szkody"
PLIK_W01 = ROOT / "dane" / "wnioski" / "W01.pdf"


@pytest.fixture(scope="module")
def katalog_modelu(tmp_path_factory):
    zbior = generuj_zbior(1500, seed=11)
    model = zbuduj_pipeline("hgb")
    model.fit(zbior[CECHY], zbior["do_weryfikacji"])
    katalog = tmp_path_factory.mktemp("model_ryzyka")
    zapisz_do_katalogu(model, "v3", referencja(zbior), katalog)
    return katalog


def _magazyn(katalog=None) -> MagazynPamieciowy:
    magazyn = MagazynPamieciowy()
    if katalog is not None:
        for nazwa in (PLIK_MODELU, PLIK_REFERENCJI, PLIK_METADANYCH):
            magazyn.zapisz_w_kontenerze("modele", PREFIKS_DOMYSLNY + nazwa, (katalog / nazwa).read_bytes())
    return magazyn


def _zbuduj_klienta(monkeypatch, magazyn):
    monkeypatch.setenv("MODEL_AGENTA", "atrapa")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("KONTENER_MODELI", raising=False)
    ustawienia = Ustawienia(
        database_url="sqlite://",
        azure_storage_connection_string="UseDevelopmentStorage=true",
        model_agenta="atrapa",
    )
    return utworz_aplikacje(
        ustawienia,
        magazyn=magazyn,
        checkpointer=InMemorySaver(),
        model=ModelAtrapa(ROOT / "dane" / "oczekiwane"),
        wyszukiwarka=WyszukiwarkaLokalna(),
    )


def _wyslij_i_czekaj(klient, sciezka: Path) -> dict:
    odp = klient.post("/wnioski", files={"plik": (sciezka.name, sciezka.read_bytes(), "application/pdf")})
    assert odp.status_code == 202
    wniosek_id = odp.json()["id"]
    start = time.monotonic()
    while time.monotonic() - start < 10.0:
        stan = klient.get(f"/wnioski/{wniosek_id}").json()
        if stan["status"] in {"CZEKA_NA_DECYZJE", "BLAD"}:
            return stan
        time.sleep(0.05)
    raise AssertionError(f"{sciezka.name}: brak CZEKA_NA_DECYZJE w 10 s")


def _wiersze(aplikacja) -> list[WejscieModelu]:
    with aplikacja.state.fabryka_sesji() as sesja:
        return list(sesja.scalars(select(WejscieModelu)).all())


@pytest.fixture
def aplikacja_z_modelem(monkeypatch, katalog_modelu):
    return _zbuduj_klienta(monkeypatch, _magazyn(katalog_modelu))


@pytest.fixture
def aplikacja_bez_modelu(monkeypatch):
    return _zbuduj_klienta(monkeypatch, _magazyn())


def test_z01_z_modelem_zapisuje_jedno_wejscie_modelu(aplikacja_z_modelem):
    with TestClient(aplikacja_z_modelem) as klient:
        stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf")
        assert stan["status"] == "CZEKA_NA_DECYZJE"
        wiersze = _wiersze(aplikacja_z_modelem)
        assert len(wiersze) == 1
        wiersz = wiersze[0]
        assert str(wiersz.wniosek_id) == stan["id"]
        assert (wiersz.wersja_modelu, wiersz.zrodlo) == ("v3", "api")
        assert set(wiersz.cechy) == set(CECHY)
        assert 0.0 <= wiersz.wynik <= 1.0
        assert wiersz.utworzono is not None

        # panel: sygnal ryzyka jest, ale bez surowych cech
        ryzyko = stan["podsumowanie"]["ryzyko"]
        assert ryzyko["status"] == "OK" and ryzyko["wersja"] == "v3"
        assert ryzyko["wynik"] == pytest.approx(wiersz.wynik)
        assert "cechy" not in ryzyko
        audyt = [z for z in klient.get(f"/wnioski/{stan['id']}/audyt").json() if z["zdarzenie"] == "REKOMENDACJA"]
        assert "cechy" not in audyt[0]["dane"]["ryzyko"]


def test_zdrowie_pokazuje_wersje_modelu_albo_null(aplikacja_z_modelem, aplikacja_bez_modelu):
    with TestClient(aplikacja_z_modelem) as klient:
        assert klient.get("/zdrowie").json()["model_ryzyka"] == "v3"
    with TestClient(aplikacja_bez_modelu) as klient:
        odp = klient.get("/zdrowie").json()
        assert odp["model_ryzyka"] is None and odp["status"] == "ok"


def test_bez_modelu_nie_zapisuje_wejsc_a_panel_mowi_model_niedostepny(aplikacja_bez_modelu):
    with TestClient(aplikacja_bez_modelu) as klient:
        stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf")
        assert stan["status"] == "CZEKA_NA_DECYZJE"
        assert stan["podsumowanie"]["decyzja"] == "POKRYTA"
        assert stan["podsumowanie"]["ryzyko"]["status"] == "MODEL_NIEDOSTEPNY"
        assert _wiersze(aplikacja_bez_modelu) == []


def test_status_brak_danych_nie_zapisuje_wejsc(aplikacja_z_modelem):
    """Z09 -> S01 (braki pol): wezel daje BRAK_DANYCH, wiec nic nie trafia do tabeli."""
    with TestClient(aplikacja_z_modelem) as klient:
        stan = _wyslij_i_czekaj(klient, SZKODY / "Z09.pdf")
        assert stan["podsumowanie"]["ryzyko"]["status"] == "BRAK_DANYCH"
        assert _wiersze(aplikacja_z_modelem) == []


def test_model_rzucajacy_nie_zapisuje_wejsc_a_wniosek_zyje(aplikacja_z_modelem, monkeypatch):
    def _rzuca(self, cechy):
        raise RuntimeError("zepsuty model")

    monkeypatch.setattr(ModelRyzyka, "ocen", _rzuca)
    with TestClient(aplikacja_z_modelem) as klient:
        stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf")
        assert stan["status"] == "CZEKA_NA_DECYZJE"
        assert stan["podsumowanie"]["ryzyko"]["status"] == "MODEL_NIEDOSTEPNY"
        assert _wiersze(aplikacja_z_modelem) == []


def test_blad_zapisu_wejsc_nie_psuje_wniosku(aplikacja_z_modelem, caplog):
    """Tabela znika (jak przed migracja na prod): wniosek dalej CZEKA_NA_DECYZJE z rekomendacja,
    a blad zapisu laduje w logu."""
    with TestClient(aplikacja_z_modelem) as klient:
        with aplikacja_z_modelem.state.fabryka_sesji() as sesja:
            Baza.metadata.tables["wejscia_modelu"].drop(sesja.get_bind())
        with caplog.at_level("ERROR"):
            stan = _wyslij_i_czekaj(klient, SZKODY / "Z01.pdf")
        assert stan["status"] == "CZEKA_NA_DECYZJE"
        assert stan["podsumowanie"]["decyzja"] == "POKRYTA"
        assert any("Nie zapisano wejscia modelu ryzyka" in r.getMessage() for r in caplog.records)
        zdarzenia = [z["zdarzenie"] for z in klient.get(f"/wnioski/{stan['id']}/audyt").json()]
        assert "REKOMENDACJA" in zdarzenia


def test_wniosek_nie_szkoda_nie_zapisuje_wejsc(aplikacja_z_modelem):
    with TestClient(aplikacja_z_modelem) as klient:
        stan = _wyslij_i_czekaj(klient, PLIK_W01)
        assert stan["status"] == "CZEKA_NA_DECYZJE"
        assert _wiersze(aplikacja_z_modelem) == []


def test_tabela_ma_ograniczenie_na_zrodlo(aplikacja_z_modelem):
    from sqlalchemy.exc import IntegrityError

    with TestClient(aplikacja_z_modelem):
        with aplikacja_z_modelem.state.fabryka_sesji() as sesja:
            sesja.add(WejscieModelu(wersja_modelu="v3", cechy={}, wynik=0.1, zrodlo="inne"))
            with pytest.raises(IntegrityError):
                sesja.commit()
            sesja.rollback()
            sesja.add(WejscieModelu(wersja_modelu="v3", cechy={}, wynik=0.1, zrodlo="symulacja"))  # bez wniosku
            sesja.commit()
            assert sesja.scalar(select(func.count()).select_from(WejscieModelu)) == 1
