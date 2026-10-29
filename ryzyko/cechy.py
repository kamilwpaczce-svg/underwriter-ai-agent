"""Cechy modelu ryzyka szkody - JEDNO zrodlo prawdy dla treningu i serwowania (Etap 15).

`cechy_ze_stanu` liczy cechy ze stanu grafu po wezle `sprawdz_polise`. Generator
(`ryzyko.generator`) produkuje wiersze z tymi samymi nazwami kolumn (`CECHY`), dzieki
czemu nie ma rozjazdu trening/serwowanie (training-serving skew).

Zasada: brakujaca wartosc -> cala funkcja zwraca None. Nigdy 0 w zastepstwie - zero
bylaby wartoscia, ktorej model nie widzial w zgloszeniu (np. brak kwoty != kwota 0).
"""

from __future__ import annotations

from datetime import date
from typing import Any

CECHY: list[str] = [
    "suma_ubezpieczenia",
    "udzial_kwoty",
    "dni_do_zgloszenia",
    "dni_od_poczatku_polisy",
    "rodzaj_mienia",
    "liczba_zalacznikow",
    "szkody_3_lata",
]
CECHY_KATEGORIALNE: list[str] = ["rodzaj_mienia"]
CECHY_LICZBOWE: list[str] = [c for c in CECHY if c not in CECHY_KATEGORIALNE]
RODZAJE_MIENIA: list[str] = ["budynek", "maszyny", "zapasy"]


def _liczba_calkowita(wartosc: Any) -> int | None:
    if isinstance(wartosc, bool) or not isinstance(wartosc, int):
        return None
    return wartosc


def _data(tekst: Any) -> date | None:
    if not isinstance(tekst, str):
        return None
    try:
        return date.fromisoformat(tekst.strip())
    except ValueError:
        return None


def cechy_ze_stanu(stan: dict[str, Any]) -> dict[str, Any] | None:
    """Etap 15: 7 cech ze stanu grafu (`pola` + `wynik_polisy`) albo None.

    None, gdy brakuje polisy lub ktorejkolwiek wartosci (kwota, daty, rodzaj mienia,
    lista zalacznikow, szkody_3_lata) albo suma ubezpieczenia <= 0. Stanu nie zmienia.
    """
    pola = stan.get("pola") or {}
    wynik = stan.get("wynik_polisy") or {}
    polisa = wynik.get("polisa")
    if not polisa:
        return None

    su = wynik.get("suma_ubezpieczenia")
    if isinstance(su, bool) or not isinstance(su, (int, float)) or su <= 0:
        return None

    kwota = _liczba_calkowita(pola.get("szacowana_kwota"))
    if kwota is None or kwota < 0:
        return None

    dni_do_zgloszenia = _liczba_calkowita(wynik.get("dni_do_zgloszenia"))
    if dni_do_zgloszenia is None:
        return None

    data_zdarzenia = _data(pola.get("data_zdarzenia"))
    okres_od = _data(polisa.get("okres_od"))
    if data_zdarzenia is None or okres_od is None:
        return None

    rodzaj = pola.get("rodzaj_mienia")
    rodzaj = getattr(rodzaj, "value", rodzaj)
    if rodzaj not in RODZAJE_MIENIA:
        return None

    zalaczniki = pola.get("zalaczniki")
    if not isinstance(zalaczniki, list):
        return None

    szkody = _liczba_calkowita(polisa.get("szkody_3_lata"))
    if szkody is None or szkody < 0:
        return None

    return {
        "suma_ubezpieczenia": float(su),
        "udzial_kwoty": kwota / su,
        "dni_do_zgloszenia": dni_do_zgloszenia,
        "dni_od_poczatku_polisy": (data_zdarzenia - okres_od).days,
        "rodzaj_mienia": rodzaj,
        "liczba_zalacznikow": len(zalaczniki),
        "szkody_3_lata": szkody,
    }
