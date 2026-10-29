"""Etap 17 (pkt 6): maskowanie PII w spanach - wzorce i procesor na prawdziwym SDK OTel."""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from obserwowalnosc import telemetria
from obserwowalnosc.pii import ATRYBUT_LICZNIKA, MaskowaniePII, maskuj, maskuj_z_liczba, nip_poprawny, pesel_poprawny

PESEL = "44051401359"
NIP = "5213011102"  # z dane/polisy.json
IBAN = "PL61 1090 1014 0000 0712 1981 2874"


def test_sumy_kontrolne():
    assert pesel_poprawny(PESEL) and not pesel_poprawny("44051401358")
    assert nip_poprawny(NIP) and not nip_poprawny("5213011103")


@pytest.mark.parametrize(
    ("wejscie", "oczekiwane"),
    [
        (f"pesel {PESEL}", "pesel [PESEL]"),
        (f"NIP {NIP}", "NIP [NIP]"),
        ("NIP 521-301-11-02", "NIP [NIP]"),
        (f"konto {IBAN}", "konto [IBAN]"),
        ("konto 61109010140000071219812874", "konto [IBAN]"),
        ("pisz na jan.kowalski@firma.pl", "pisz na [EMAIL]"),
        ("tel. +48 600 700 800", "tel. [TELEFON]"),
        ("tel. 600-700-800", "tel. [TELEFON]"),
        ("polisa PL/MSP/2026/0001", "polisa [POLISA]"),
    ],
)
def test_maskuje_dane_osobowe(wejscie, oczekiwane):
    assert maskuj(wejscie) == oczekiwane


@pytest.mark.parametrize(
    "czysty",
    [
        "POST /wnioski/3f2c9a1e-7b4d-4c1a-9e2f-0a1b2c3d4e5f/decyzja",
        "znacznik 1761540000",  # 10 cyfr bez poprawnej sumy NIP
        "12345678901",  # 11 cyfr bez poprawnej sumy PESEL
        "AKCEPTACJA",
        "gpt-5-mini 2025-04-01-preview",
    ],
)
def test_nie_rusza_danych_bez_pii(czysty):
    assert maskuj(czysty) == czysty


def _provider(z_maskowaniem: bool):
    eksporter = InMemorySpanExporter()
    provider = TracerProvider()
    if z_maskowaniem:
        provider.add_span_processor(MaskowaniePII())
    provider.add_span_processor(SimpleSpanProcessor(eksporter))
    return provider.get_tracer("test"), eksporter


def _span_z_pii(tracer):
    with tracer.start_as_current_span(f"GET /klient/{PESEL}") as span:
        span.set_attribute("url.full", f"https://uw/api?email=jan@firma.pl&nip={NIP}")
        span.set_attribute("uw.decyzja", "ODMOWA")
        span.set_attribute("uw.lista", ("bez pii", "tel 600 700 800"))
        span.add_event("exception", {"exception.message": f"blad walidacji NIP {NIP}"})


def _cale_teksty(span) -> str:
    czesci = [span.name, *map(str, span.attributes.values())]
    for e in span.events:
        czesci += map(str, e.attributes.values())
    return " ".join(czesci)


def test_bez_procesora_pii_wycieka_do_eksportera():
    """Stan chory: dowod, ze test ponizej mierzy procesor, a nie atrape."""
    tracer, eksporter = _provider(z_maskowaniem=False)
    _span_z_pii(tracer)
    tekst = _cale_teksty(eksporter.get_finished_spans()[0])
    assert PESEL in tekst and NIP in tekst


def test_procesor_maskuje_nazwe_atrybuty_i_zdarzenia_przed_eksportem():
    tracer, eksporter = _provider(z_maskowaniem=True)
    _span_z_pii(tracer)
    span = eksporter.get_finished_spans()[0]
    tekst = _cale_teksty(span)
    for wrazliwe in (PESEL, NIP, "jan@firma.pl", "600 700 800"):
        assert wrazliwe not in tekst, wrazliwe
    assert span.name == "GET /klient/[PESEL]"
    assert span.attributes["uw.decyzja"] == "ODMOWA"
    assert span.attributes["uw.lista"] == ("bez pii", "tel [TELEFON]")
    assert span.events[0].attributes["exception.message"] == "blad walidacji NIP [NIP]"
    # nazwa (PESEL) + url (e-mail, NIP) + lista (telefon) + zdarzenie (NIP)
    assert span.attributes[ATRYBUT_LICZNIKA] == 5


def test_licznik_podmian():
    assert maskuj_z_liczba(f"{PESEL} {NIP} a@b.pl 12345678901") == ("[PESEL] [NIP] [EMAIL] 12345678901", 3)
    assert maskuj_z_liczba("AKCEPTACJA") == ("AKCEPTACJA", 0)


def test_span_bez_pii_nie_dostaje_licznika():
    tracer, eksporter = _provider(z_maskowaniem=True)
    with tracer.start_as_current_span("wezel.ocen") as span:
        span.set_attribute("uw.decyzja", "AKCEPTACJA")
    assert ATRYBUT_LICZNIKA not in eksporter.get_finished_spans()[0].attributes


def test_konfiguracja_podpina_maskowanie(monkeypatch):
    wywolania = []
    monkeypatch.setattr(telemetria, "_configure_azure_monitor", lambda **kw: wywolania.append(kw))
    monkeypatch.setattr(telemetria, "_skonfigurowano", False)
    telemetria.skonfiguruj_telemetrie("InstrumentationKey=x")
    assert any(isinstance(p, MaskowaniePII) for p in wywolania[0]["span_processors"])
