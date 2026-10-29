"""19c zad. 4: skrypt zasiewu `obserwowalnosc/zasiej_wnioski.py` na atrapie (zero kosztow, zero sieci).

Prawdziwy bieg (gpt-5-mini + eksport do App Insights) wykonuje właściciel - tu sprawdzamy
mechanike: kody wyjscia, liczby wnioskow/odejsc, atrybuty spanow na prawdziwej sciezce API."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from obserwowalnosc import zasiej_wnioski as zw

ROOT = Path(__file__).resolve().parent.parent
KQL = (ROOT / "obserwowalnosc" / "metryki_efektu.kql").read_text(encoding="utf-8")


_EKSPORTER = InMemorySpanExporter()
_PODPIETO = False


@pytest.fixture
def spany():
    """Wlasny eksporter podpiety do globalnego providera (ustawianego raz na proces).

    Nie importuje fikstury z tests/test_telemetria.py: ten modul wczytany drugi raz pod
    inna nazwa (tests.test_telemetria vs test_telemetria) nie ustawi providera, a jego
    eksporter nie dostalby spanow. Provider bierzemy z trace - jesli to nie SDK
    (nikt jeszcze nie ustawil), ustawiamy wlasny."""
    global _PODPIETO
    if not _PODPIETO:
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        provider.add_span_processor(SimpleSpanProcessor(_EKSPORTER))
        _PODPIETO = True
    _EKSPORTER.clear()
    yield _EKSPORTER
    _EKSPORTER.clear()


@pytest.fixture(autouse=True)
def _srodowisko(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "test")  # main() ustawia go na uw-zasiew; monkeypatch przywraca
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    for nazwa in ("AZURE_OPENAI_ENDPOINT", "AZURE_DOCINT_ENDPOINT"):
        monkeypatch.delenv(nazwa, raising=False)


def test_brak_connection_stringa_zwraca_kod_2():
    assert zw.main(["--stan", "zdrowy", "--llm", "atrapa"]) == 2


def test_azure_bez_konfiguracji_modelu_zwraca_kod_2(monkeypatch):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=00000000-0000-0000-0000-000000000000")
    assert zw.main(["--stan", "zdrowy", "--llm", "azure"]) == 2


def test_listy_zasiewu_maja_liczby_ze_specyfikacji_i_istniejace_pliki():
    for stan, (wnioski, odejscia) in {"zdrowy": (10, 2), "chory": (8, 6)}.items():
        lista = zw.PRZYPADKI_ZASIEWU[stan]
        assert len(lista) == wnioski
        assert sum(1 for _, odbiega, _ in lista if odbiega) == odejscia == zw.OCZEKIWANE_ODEJSCIA[stan]
        assert all((zw.KATALOG_WNIOSKOW / plik).exists() for plik, _, _ in lista)
        assert len({plik for plik, _, _ in lista}) == wnioski  # bez powtorzen


def test_progi_alertu_w_skrypcie_rowne_zapytaniu_6_w_kql():
    min_decyzji = int(re.search(r"let\s+min_decyzji\s*=\s*(\d+)\s*;", KQL).group(1))
    prog = float(re.search(r"let\s+prog_odejsc_pct\s*=\s*([0-9.]+)\s*;", KQL).group(1))
    assert (zw.MIN_DECYZJI, zw.PROG_ODEJSC_PCT) == (min_decyzji, prog)


@pytest.mark.parametrize(
    "rek, silnik, odbiega, pref, oczekiwane",
    [
        ("AKCEPTACJA", "AKCEPTACJA", False, None, ("AKCEPTACJA", False)),
        ("AKCEPTACJA", "AKCEPTACJA", True, "ODMOWA", ("ODMOWA", True)),
        # preferowana = rekomendacja -> musi byc inna, inaczej to nie bylo by odejscie
        ("ODMOWA", "ODMOWA", True, "ODMOWA", ("AKCEPTACJA", True)),
        # rekomendacja LLM != silnik: zgodnosc niemozliwa, odejscie wymuszone
        ("AKCEPTACJA", "SKIEROWANIE", False, None, ("SKIEROWANIE", True)),
    ],
)
def test_wybierz_decyzje(rek, silnik, odbiega, pref, oczekiwane):
    decyzja, odejscie, _ = zw.wybierz_decyzje(rek, silnik, odbiega, pref)
    assert (decyzja, odejscie) == oczekiwane
    if odbiega:
        assert decyzja not in (rek, silnik)


def _uruchom_na_atrapie(stan, capsys):
    kod = zw.main(["--stan", stan, "--llm", "atrapa", "--bez-eksportu"])
    return kod, capsys.readouterr().out


def test_zdrowy_na_atrapie_10_wnioskow_2_odejscia_alert_milczy(spany, capsys):
    kod, wyjscie = _uruchom_na_atrapie("zdrowy", capsys)
    assert kod == 0, wyjscie
    assert "wnioskow=10 decyzji=10 odejscia=2 odsetek=20.0%" in wyjscie
    assert "alert odejsc milczy" in wyjscie

    gotowe = spany.get_finished_spans()
    wznow = [s for s in gotowe if s.name == "wniosek.wznow"]
    assert len(wznow) == 10
    assert sum(1 for s in wznow if s.attributes["uw.odejscie_od_rekomendacji"] is True) == 2
    uruchom = [s for s in gotowe if s.name == "wniosek.uruchom"]
    assert len(uruchom) == 10
    assert all(s.attributes["uw.decyzja"] for s in uruchom)  # metryka SKIEROWANIE widzi kazdy wniosek
    # komentarz decyzji nie wycieka do telemetrii (RODO)
    wartosci = [str(v) for s in gotowe for v in (s.attributes or {}).values()]
    assert not any(zw.KOMENTARZ_ODEJSCIA in w or zw.UZYTKOWNIK in w for w in wartosci)


def test_chory_na_atrapie_8_wnioskow_6_odejsc_alert_odpali(spany, capsys):
    kod, wyjscie = _uruchom_na_atrapie("chory", capsys)
    assert kod == 0, wyjscie
    assert "wnioskow=8 decyzji=8 odejscia=6 odsetek=75.0%" in wyjscie
    assert "alert odejsc ODPALI" in wyjscie
    wznow = [s for s in spany.get_finished_spans() if s.name == "wniosek.wznow"]
    assert len(wznow) == 8
    assert sum(1 for s in wznow if s.attributes["uw.odejscie_od_rekomendacji"] is True) == 6


def test_podsumuj_niezgodny_stan_zwraca_zgodny_false():
    wyniki = [zw.WynikWniosku("W01.pdf", str(i), "ZAKONCZONY", odejscie=False) for i in range(6)]
    decyzje, odejscia, odsetek, alert, zgodny = zw.podsumuj(wyniki, "chory")
    assert (decyzje, odejscia, alert, zgodny) == (6, 0, False, False)
    assert zw.podsumuj(wyniki, "zdrowy")[4] is True
    # za malo decyzji: nawet 100% odejsc nie odpala alertu, wiec stan chory nie jest zgodny
    maly = [zw.WynikWniosku("W01.pdf", str(i), "ZAKONCZONY", odejscie=True) for i in range(4)]
    assert zw.podsumuj(maly, "chory")[3:] == (False, False)
