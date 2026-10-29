"""Etap 15, zadanie 6: job dryfu - testy offline (SQLite w pamieci + atrapa magazynu + lokalny TracerProvider)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from api.baza import Baza, WejscieModelu, utworz_fabryke_sesji, utworz_silnik
from api.magazyn import MagazynPamieciowy
from ryzyko import job_dryfu
from ryzyko.cechy import CECHY
from ryzyko.generator import generuj_zbior
from ryzyko.psi import referencja
from ryzyko.serwowanie import PLIK_REFERENCJI, PREFIKS_DOMYSLNY

KONTENER = "modele"


@pytest.fixture(scope="module")
def ref_json() -> bytes:
    return json.dumps(referencja(generuj_zbior(5000, seed=1)[CECHY])).encode("utf-8")


@pytest.fixture
def spany(monkeypatch):
    eksporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(eksporter))
    monkeypatch.setattr(job_dryfu, "tracer", lambda: provider.get_tracer("test-dryf"))
    return eksporter


@pytest.fixture
def magazyn(ref_json) -> MagazynPamieciowy:
    m = MagazynPamieciowy()
    m.zapisz_w_kontenerze(KONTENER, PREFIKS_DOMYSLNY + PLIK_REFERENCJI, ref_json)
    return m


@pytest.fixture
def fabryka() -> sessionmaker:
    silnik = utworz_silnik("sqlite://")
    Baza.metadata.create_all(silnik)
    return utworz_fabryke_sesji(silnik)


def _wstaw(fabryka, n: int, seed: int, przesuniecie=None, wiek_dni: float = 1.0, zrodlo="symulacja") -> None:
    df = generuj_zbior(n, seed=seed, przesuniecie=przesuniecie)[CECHY]
    czas = datetime.now(timezone.utc) - timedelta(days=wiek_dni)
    with fabryka() as sesja:
        for rekord in df.to_dict("records"):
            rekord = {k: (v if isinstance(v, str) else float(v)) for k, v in rekord.items()}
            sesja.add(WejscieModelu(wersja_modelu="v1", cechy=rekord, wynik=0.1, zrodlo=zrodlo, utworzono=czas))
        sesja.commit()


def _uruchom(fabryka, magazyn) -> int:
    return job_dryfu.przebieg(lambda: fabryka, lambda: magazyn, kontener=KONTENER)


def _span(spany):
    gotowe = spany.get_finished_spans()
    assert len(gotowe) == 1
    assert gotowe[0].name == "dryf.przebieg"
    return gotowe[0]


def test_zdrowo_bez_dryfu_status_ok(fabryka, magazyn, spany):
    _wstaw(fabryka, 400, seed=2)
    assert _uruchom(fabryka, magazyn) == 0
    span = _span(spany)
    a = span.attributes
    assert span.status.status_code != StatusCode.ERROR
    assert a["uw.dryf.status"] == "OK"
    assert a["uw.dryf.n"] == 400
    assert a["uw.dryf.psi_max"] < 0.1
    assert {k for k in a if k.startswith("uw.dryf.psi.")} == {f"uw.dryf.psi.{c}" for c in CECHY}
    assert a["uw.dryf.psi_max"] == max(a[f"uw.dryf.psi.{c}"] for c in CECHY)
    assert a[f"uw.dryf.psi.{a['uw.dryf.cecha_max']}"] == a["uw.dryf.psi_max"]


def test_dryf_status_dryf_i_cecha_max(fabryka, magazyn, spany):
    _wstaw(fabryka, 400, seed=3, przesuniecie={"udzial_kwoty": 0.5})
    assert _uruchom(fabryka, magazyn) == 0  # dryf to wynik, nie awaria joba
    a = _span(spany).attributes
    assert a["uw.dryf.status"] == "DRYF"
    assert a["uw.dryf.psi_max"] > 0.2
    assert a["uw.dryf.cecha_max"] == "udzial_kwoty"


def test_za_malo_danych_exit_0_bez_psi(fabryka, magazyn, spany):
    _wstaw(fabryka, 199, seed=2, przesuniecie={"udzial_kwoty": 0.5})  # nawet z dryfem: n < 200
    assert _uruchom(fabryka, magazyn) == 0
    span = _span(spany)
    assert span.status.status_code != StatusCode.ERROR
    assert dict(span.attributes) == {"uw.dryf.status": "ZA_MALO_DANYCH", "uw.dryf.n": 199}


def test_dokladnie_200_wierszy_liczy_psi(fabryka, magazyn, spany):
    _wstaw(fabryka, 200, seed=2)
    assert _uruchom(fabryka, magazyn) == 0
    a = _span(spany).attributes
    assert a["uw.dryf.status"] in ("OK", "DRYF")
    assert "uw.dryf.psi_max" in a


def test_puste_wejscia_to_za_malo_danych_nie_psi_zero(fabryka, magazyn, spany):
    assert _uruchom(fabryka, magazyn) == 0
    a = _span(spany).attributes
    assert a["uw.dryf.status"] == "ZA_MALO_DANYCH"
    assert a["uw.dryf.n"] == 0
    assert "uw.dryf.psi_max" not in a


def test_okno_30_dni_odcina_stare_wiersze(fabryka, magazyn, spany):
    _wstaw(fabryka, 150, seed=2, wiek_dni=1)
    _wstaw(fabryka, 100, seed=4, wiek_dni=45)  # poza oknem
    assert _uruchom(fabryka, magazyn) == 0
    a = _span(spany).attributes
    assert a["uw.dryf.n"] == 150
    assert a["uw.dryf.status"] == "ZA_MALO_DANYCH"


def test_okno_liczy_wiersze_api_i_symulacji(fabryka, magazyn, spany):
    _wstaw(fabryka, 120, seed=2, zrodlo="symulacja")
    _wstaw(fabryka, 120, seed=5, zrodlo="api")
    assert _uruchom(fabryka, magazyn) == 0
    assert _span(spany).attributes["uw.dryf.n"] == 240


def test_brak_referencji_span_error_i_exit_1(fabryka, spany):
    _wstaw(fabryka, 400, seed=2)
    assert _uruchom(fabryka, MagazynPamieciowy()) == 1
    span = _span(spany)
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["uw.dryf.etap_bledu"] == "referencja"
    assert span.attributes["error.type"] == "FileNotFoundError"
    assert "uw.dryf.psi_max" not in span.attributes
    assert "uw.dryf.status" not in span.attributes  # nigdy "OK" ani PSI = 0 przy bledzie


def test_referencja_bez_cechy_to_blad(fabryka, ref_json, spany):
    ref = json.loads(ref_json)
    del ref["udzial_kwoty"]
    m = MagazynPamieciowy()
    m.zapisz_w_kontenerze(KONTENER, PREFIKS_DOMYSLNY + PLIK_REFERENCJI, json.dumps(ref).encode())
    _wstaw(fabryka, 400, seed=2)
    assert _uruchom(fabryka, m) == 1
    span = _span(spany)
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["uw.dryf.etap_bledu"] == "referencja"


def test_uszkodzona_referencja_to_blad(fabryka, spany):
    m = MagazynPamieciowy()
    m.zapisz_w_kontenerze(KONTENER, PREFIKS_DOMYSLNY + PLIK_REFERENCJI, b"{nie json")
    assert _uruchom(fabryka, m) == 1
    assert _span(spany).status.status_code == StatusCode.ERROR


def test_brak_bazy_span_error_i_exit_1(magazyn, spany):
    # silnik bez utworzonych tabel = baza nieosiagalna / zly schemat
    pusta = utworz_fabryke_sesji(utworz_silnik("sqlite://"))
    assert _uruchom(pusta, magazyn) == 1
    span = _span(spany)
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["uw.dryf.etap_bledu"] == "baza"
    assert span.attributes["error.type"] == "OperationalError"
    assert "uw.dryf.status" not in span.attributes


def test_brak_konfiguracji_bazy_to_span_error(magazyn, spany):
    def _brak():
        raise RuntimeError("Brak zmiennej srodowiskowej DATABASE_URL.")

    assert job_dryfu.przebieg(_brak, lambda: magazyn, kontener=KONTENER) == 1
    span = _span(spany)
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["uw.dryf.etap_bledu"] == "baza"


def test_blad_budowy_magazynu_to_span_error(fabryka, spany):
    def _brak():
        raise RuntimeError("MagazynBlob wymaga connection_string")

    assert job_dryfu.przebieg(lambda: fabryka, _brak, kontener=KONTENER) == 1
    assert _span(spany).attributes["uw.dryf.etap_bledu"] == "referencja"


def test_zduplikowany_bieg_dwa_spany_i_baza_bez_zmian(fabryka, magazyn, spany):
    _wstaw(fabryka, 300, seed=2)
    with fabryka() as s:
        przed = s.scalar(select(func.count()).select_from(WejscieModelu))
    assert _uruchom(fabryka, magazyn) == 0
    assert _uruchom(fabryka, magazyn) == 0
    spany_gotowe = spany.get_finished_spans()
    assert [s.name for s in spany_gotowe] == ["dryf.przebieg", "dryf.przebieg"]
    assert spany_gotowe[0].attributes["uw.dryf.psi_max"] == spany_gotowe[1].attributes["uw.dryf.psi_max"]
    with fabryka() as s:
        assert s.scalar(select(func.count()).select_from(WejscieModelu)) == przed == 300


def test_span_niesie_tylko_liczby_i_nazwy_cech(fabryka, magazyn, spany):
    _wstaw(fabryka, 300, seed=2)
    _uruchom(fabryka, magazyn)
    a = _span(spany).attributes
    for klucz, wartosc in a.items():
        assert klucz.startswith("uw.dryf.")
        if isinstance(wartosc, str):
            assert wartosc in {"OK", "DRYF", "ZA_MALO_DANYCH", *CECHY}


class _AtrapaProvidera:
    def __init__(self):
        self.wywolania: list[str] = []

    def force_flush(self, timeout_millis=None):
        self.wywolania.append(f"force_flush({timeout_millis})")
        return True

    def shutdown(self):
        self.wywolania.append("shutdown")


def test_main_splukuje_telemetrie_takze_po_wyjatku(monkeypatch):
    provider = _AtrapaProvidera()
    monkeypatch.setattr(job_dryfu.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(job_dryfu.telemetria, "skonfiguruj_telemetrie", lambda cs: True)

    def _wybuch(*a, **k):
        raise RuntimeError("cos poszlo nie tak")

    monkeypatch.setattr(job_dryfu, "przebieg", _wybuch)
    with pytest.raises(RuntimeError):
        job_dryfu.main()
    assert provider.wywolania == [f"force_flush({job_dryfu.TIMEOUT_FLUSH_MS})", "shutdown"]


def test_main_zwraca_kod_przebiegu_i_splukuje(monkeypatch):
    provider = _AtrapaProvidera()
    monkeypatch.setattr(job_dryfu.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(job_dryfu.telemetria, "skonfiguruj_telemetrie", lambda cs: True)
    monkeypatch.setattr(job_dryfu, "przebieg", lambda *a, **k: 1)
    assert job_dryfu.main() == 1
    assert provider.wywolania[-1] == "shutdown"


def test_main_bez_env_konczy_sie_kodem_1(monkeypatch, spany):
    """Pelna sciezka main() bez DATABASE_URL i bez Storage: span ERROR, exit 1, flush."""
    provider = _AtrapaProvidera()
    monkeypatch.setattr(job_dryfu.trace, "get_tracer_provider", lambda: provider)
    for nazwa in ("DATABASE_URL", "AZURE_STORAGE_CONNECTION_STRING", "AZURE_STORAGE_ACCOUNT_URL",
                  "APPLICATIONINSIGHTS_CONNECTION_STRING"):
        monkeypatch.delenv(nazwa, raising=False)
    assert job_dryfu.main() == 1
    assert _span(spany).status.status_code == StatusCode.ERROR
    assert provider.wywolania[-1] == "shutdown"
