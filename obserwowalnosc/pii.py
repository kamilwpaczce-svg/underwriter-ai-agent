"""Etap 17 (pkt 6): maskowanie danych osobowych w spanach przed eksportem do App Insights.

Spany z kodu demo nie niosa tresci (test RODO w tests/test_telemetria.py), ale
auto-instrumentacja HTTP dopisuje url, a zdarzenia wyjatkow tresc bledu. Procesor ponizej
to druga linia obrony: niezaleznie od tego, kto ustawil atrybut, tekst przechodzi przez
maskuj() zanim trafi do eksportera. Wzorce bez nowej uslugi (regex + sumy kontrolne)."""

from __future__ import annotations

import re

from opentelemetry.attributes import BoundedAttributes
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

ATRYBUT_LICZNIKA = "uw.pii.zamaskowane"
_WAGI_PESEL = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
_WAGI_NIP = (6, 5, 7, 2, 3, 4, 5, 6, 7)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IBAN = re.compile(r"\b(?:PL\s?)?\d{2}(?:\s?\d{4}){6}\b", re.IGNORECASE)
_POLISA = re.compile(r"\bPL/[A-Z]{2,5}/\d{4}/\d{3,6}\b", re.IGNORECASE)
_TELEFON = re.compile(r"(?<![\w-])(?:\+48[\s-]?)?\d{3}[\s-]\d{3}[\s-]\d{3}(?![\w-])|\+48\d{9}\b")
# NIP z kreskami (123-456-78-90) i bez; PESEL zawsze 11 cyfr ciagiem.
_CYFRY_10_11 = re.compile(r"(?<![\w-])(?:\d{3}-\d{3}-\d{2}-\d{2}|\d{3}-\d{2}-\d{2}-\d{3}|\d{11}|\d{10})(?![\w-])")


def pesel_poprawny(cyfry: str) -> bool:
    if len(cyfry) != 11 or not cyfry.isdigit():
        return False
    suma = sum(int(c) * w for c, w in zip(cyfry, _WAGI_PESEL))
    return (10 - suma % 10) % 10 == int(cyfry[10])


def nip_poprawny(cyfry: str) -> bool:
    if len(cyfry) != 10 or not cyfry.isdigit():
        return False
    reszta = sum(int(c) * w for c, w in zip(cyfry, _WAGI_NIP)) % 11
    return reszta != 10 and reszta == int(cyfry[9])


def _zamien_numer(m: re.Match) -> str:
    cyfry = m.group(0).replace("-", "")
    if pesel_poprawny(cyfry):
        return "[PESEL]"
    if nip_poprawny(cyfry):
        return "[NIP]"
    return m.group(0)  # dowolne 10-11 cyfr (np. znacznik czasu) zostaje


def maskuj_z_liczba(tekst: str) -> tuple[str, int]:
    """Kolejnosc ma znaczenie: IBAN przed telefonem/NIP (zawiera ich podciagi)."""
    razem = 0
    for wzorzec, znacznik in ((_EMAIL, "[EMAIL]"), (_IBAN, "[IBAN]"), (_POLISA, "[POLISA]"), (_TELEFON, "[TELEFON]")):
        tekst, n = wzorzec.subn(znacznik, tekst)
        razem += n
    numery = []

    def zamien(m: re.Match) -> str:
        wynik = _zamien_numer(m)
        if wynik != m.group(0):
            numery.append(wynik)
        return wynik

    return _CYFRY_10_11.sub(zamien, tekst), razem + len(numery)


def maskuj(tekst: str) -> str:
    return maskuj_z_liczba(tekst)[0]


class _Licznik:
    def __init__(self) -> None:
        self.n = 0

    def tekst(self, t: str) -> str:
        wynik, n = maskuj_z_liczba(t)
        self.n += n
        return wynik

    def wartosc(self, v):
        if isinstance(v, str):
            return self.tekst(v)
        if isinstance(v, (tuple, list)):
            return type(v)(self.tekst(x) if isinstance(x, str) else x for x in v)
        return v

    def atrybuty(self, attrs):
        if not attrs:
            return attrs
        return BoundedAttributes(attributes={k: self.wartosc(v) for k, v in attrs.items()}, immutable=True)


class MaskowaniePII(SpanProcessor):
    """Musi stac PRZED procesorem eksportera: on_end dostaje ten sam obiekt ReadableSpan
    co kolejne procesory, wiec podmiana pol jest widoczna dla eksportu. Pola prywatne,
    bo ReadableSpan nie ma API do zmiany - zachowanie przypiete testem na prawdziwym SDK.

    Liczba podmian trafia do atrybutu `uw.pii.zamaskowane` (tylko gdy > 0): pomiar dzialania
    oslony na produkcji (KQL), a nie samo "PII nie widac"."""

    def on_end(self, span: ReadableSpan) -> None:
        licznik = _Licznik()
        span._name = licznik.tekst(span._name)  # pylint: disable=protected-access
        for zdarzenie in span._events:  # pylint: disable=protected-access
            zdarzenie._attributes = licznik.atrybuty(zdarzenie._attributes)  # pylint: disable=protected-access
        atrybuty = licznik.atrybuty(span._attributes)  # pylint: disable=protected-access
        if licznik.n:
            atrybuty = BoundedAttributes(attributes={**(atrybuty or {}), ATRYBUT_LICZNIKA: licznik.n}, immutable=True)
        span._attributes = atrybuty  # pylint: disable=protected-access
