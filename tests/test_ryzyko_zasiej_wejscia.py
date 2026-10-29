"""Etap 15, zadanie 6: zasiew i sprzatanie wierszy symulacji (offline, SQLite w pamieci)."""

from __future__ import annotations

import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import func, select

from api.baza import Baza, WejscieModelu, utworz_fabryke_sesji, utworz_silnik
from api.magazyn import MagazynPamieciowy
from ryzyko import job_dryfu, zasiej_wejscia
from ryzyko.cechy import CECHY
from ryzyko.generator import generuj_zbior
from ryzyko.psi import referencja
from ryzyko.serwowanie import PLIK_REFERENCJI, PREFIKS_DOMYSLNY


@pytest.fixture
def fabryka():
    silnik = utworz_silnik("sqlite://")
    Baza.metadata.create_all(silnik)
    return utworz_fabryke_sesji(silnik)


def _ile(fabryka, zrodlo=None) -> int:
    with fabryka() as s:
        q = select(func.count()).select_from(WejscieModelu)
        if zrodlo:
            q = q.where(WejscieModelu.zrodlo == zrodlo)
        return s.scalar(q)


def test_zasiew_wstawia_n_wierszy_symulacji_z_cechami(fabryka):
    assert zasiej_wejscia.zasiej(fabryka, 50, seed=3) == 50
    with fabryka() as s:
        wiersze = s.scalars(select(WejscieModelu)).all()
    assert len(wiersze) == 50
    for w in wiersze:
        assert w.zrodlo == "symulacja"
        assert w.wniosek_id is None
        assert set(w.cechy) == set(CECHY)
        assert isinstance(w.cechy["dni_do_zgloszenia"], int)
        assert isinstance(w.cechy["udzial_kwoty"], float)
        assert isinstance(w.cechy["rodzaj_mienia"], str)


def test_zasiew_odrzuca_zle_n_i_nieznana_cechy(fabryka):
    with pytest.raises(ValueError):
        zasiej_wejscia.zasiej(fabryka, 0, seed=1)
    with pytest.raises(ValueError):
        zasiej_wejscia.zasiej(fabryka, zasiej_wejscia.MAX_WIERSZY + 1, seed=1)
    with pytest.raises(ValueError):
        zasiej_wejscia.zasiej(fabryka, 10, seed=1, przesuniecie={"nie_ma_takiej": 1.0})
    assert _ile(fabryka) == 0


def test_parsuj_przesuniecie():
    assert zasiej_wejscia.parsuj_przesuniecie(None) is None
    assert zasiej_wejscia.parsuj_przesuniecie(["udzial_kwoty=0.5", "szkody_3_lata=1"]) == {
        "udzial_kwoty": 0.5,
        "szkody_3_lata": 1.0,
    }
    with pytest.raises(ValueError):
        zasiej_wejscia.parsuj_przesuniecie(["udzial_kwoty"])


def test_sprzatanie_usuwa_tylko_symulacje(fabryka):
    zasiej_wejscia.zasiej(fabryka, 30, seed=1)
    with fabryka() as s:
        s.add(WejscieModelu(wersja_modelu="v1", cechy={"x": 1}, wynik=0.5, zrodlo="api"))
        s.commit()
    assert _ile(fabryka) == 31
    assert zasiej_wejscia.sprzatnij(fabryka) == 30
    assert _ile(fabryka) == 1
    assert _ile(fabryka, "api") == 1
    assert zasiej_wejscia.sprzatnij(fabryka) == 0  # powtorka bezpieczna


def test_main_wymaga_dokladnie_jednego_trybu(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    with pytest.raises(SystemExit):
        zasiej_wejscia.main([])
    with pytest.raises(SystemExit):
        zasiej_wejscia.main(["--n", "5", "--sprzatnij"])


def test_main_bez_database_url_exit_1(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert zasiej_wejscia.main(["--n", "5"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_przebieg_na_zasianych_czterech_krokach_testu_na_zywo(fabryka, monkeypatch):
    """Probka 4 przebiegow z SPEC (zadanie 6) na SQLite: cisza, cisza, DRYF, czysto po sprzataniu."""
    eksporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(eksporter))
    monkeypatch.setattr(job_dryfu, "tracer", lambda: provider.get_tracer("test"))
    magazyn = MagazynPamieciowy()
    magazyn.zapisz_w_kontenerze(
        "modele",
        PREFIKS_DOMYSLNY + PLIK_REFERENCJI,
        json.dumps(referencja(generuj_zbior(5000, seed=1)[CECHY])).encode(),
    )

    def bieg() -> dict:
        eksporter.clear()
        assert job_dryfu.przebieg(lambda: fabryka, lambda: magazyn, kontener="modele") == 0
        return dict(eksporter.get_finished_spans()[0].attributes)

    zasiej_wejscia.zasiej(fabryka, 300, seed=11)
    assert bieg()["uw.dryf.status"] == "OK"  # przebieg 1: bez dryfu
    assert bieg()["uw.dryf.status"] == "OK"  # przebieg 2: ponownie, to samo
    zasiej_wejscia.sprzatnij(fabryka)
    zasiej_wejscia.zasiej(fabryka, 300, seed=12, przesuniecie={"udzial_kwoty": 0.5})
    a3 = bieg()
    assert a3["uw.dryf.status"] == "DRYF" and a3["uw.dryf.cecha_max"] == "udzial_kwoty"  # przebieg 3: dryf
    zasiej_wejscia.sprzatnij(fabryka)
    zasiej_wejscia.zasiej(fabryka, 300, seed=13)
    assert bieg()["uw.dryf.status"] == "OK"  # przebieg 4: czysto
    zasiej_wejscia.sprzatnij(fabryka)
    assert _ile(fabryka) == 0
