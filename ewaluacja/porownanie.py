"""Porownanie wyniku agenta (stan grafu) z `dane/oczekiwane/<ID>.json`.

Rozdziela blad ekstrakcji (zle pola) od bledu rozumowania (dobre pola, zla
decyzja): `decyzja_silnika_na_polach_llm` liczy silnik deterministyczny na
polach WYCIAGNIETYCH PRZEZ LLM, nie na polach oczekiwanych.
"""

from __future__ import annotations

import re
from typing import Any

_BIALE_ZNAKI = re.compile(r"\s+")
# "ul. Warsztatowa 6" == "Warsztatowa 6": gpt-5-mini raz pisze prefiks, raz nie (12.10: 4 z 5
# rozjazdow pol w 14 przypadkach) - to ten sam adres, nie blad ekstrakcji. Wymaga kropki albo
# spacji, zeby nie ciac nazw zaczynajacych sie od "ul" (np. "Ulanska").
_PREFIKS_ULICY = re.compile(r"^ul(?:\.\s*|\s+)")
_POLA_ADRESU = ("ulica", "kod", "miasto")
# "uwagi" poza punktacja: zadna regula z niego nie korzysta, a wzorzec z etapu 1
# ma tam null mimo tekstu w dokumencie (poza W13). Wstrzykniecie mierzy
# osobno podejrzane_instrukcje.
_POLA_POZA_PUNKTACJA = frozenset({"uwagi"})


def _znormalizuj_napis(wartosc: Any) -> Any:
    if not isinstance(wartosc, str):
        return wartosc
    return _BIALE_ZNAKI.sub(" ", wartosc).strip().casefold()


def _znormalizuj_ulice(wartosc: Any) -> Any:
    wartosc = _znormalizuj_napis(wartosc)
    if not isinstance(wartosc, str):
        return wartosc
    return _PREFIKS_ULICY.sub("", wartosc)


def _znormalizuj_szkody(szkody: list[dict] | None) -> tuple[int, tuple]:
    if not szkody:
        return (0, tuple())
    kwoty = tuple(sorted((s.get("kwota") or 0) for s in szkody))
    return (len(szkody), kwoty)


def porownaj_pole(nazwa: str, oczekiwane: Any, otrzymane: Any) -> bool:
    """Porownuje jedno pole po normalizacji wlasciwej dla jego typu."""
    if nazwa == "adres":
        oczekiwane = oczekiwane or {}
        otrzymane = otrzymane or {}
        if _znormalizuj_ulice(oczekiwane.get("ulica")) != _znormalizuj_ulice(otrzymane.get("ulica")):
            return False
        return all(
            _znormalizuj_napis(oczekiwane.get(p)) == _znormalizuj_napis(otrzymane.get(p))
            for p in _POLA_ADRESU
            if p != "ulica"
        )
    if nazwa == "szkody_3_lata":
        return _znormalizuj_szkody(oczekiwane) == _znormalizuj_szkody(otrzymane)
    return _znormalizuj_napis(oczekiwane) == _znormalizuj_napis(otrzymane)


def porownaj_pola(pola_oczekiwane: dict | None, pola_otrzymane: dict | None) -> dict[str, bool]:
    """{nazwa_pola: czy_trafione} dla kazdego pola z pola_oczekiwane."""
    pola_oczekiwane = pola_oczekiwane or {}
    pola_otrzymane = pola_otrzymane or {}
    return {
        nazwa: porownaj_pole(nazwa, wartosc, pola_otrzymane.get(nazwa))
        for nazwa, wartosc in pola_oczekiwane.items()
        if nazwa not in _POLA_POZA_PUNKTACJA
    }


def wynik_pol(pola_oczekiwane: dict | None, pola_otrzymane: dict | None) -> tuple[int, int]:
    """(trafione, wszystkie) pol."""
    wyniki = porownaj_pola(pola_oczekiwane, pola_otrzymane)
    return sum(wyniki.values()), len(wyniki)


def porownaj_reguly(oczekiwane: list[str] | None, otrzymane: list[str] | None) -> bool:
    return sorted(oczekiwane or []) == sorted(otrzymane or [])


def porownaj_przypadek(oczekiwany: dict, wynik_grafu: dict) -> dict[str, Any]:
    """Pelne porownanie jednego przypadku wedlug SPEC_ETAP2.md.

    `wynik_grafu`: stan grafu po zatrzymaniu na interrupt (co najmniej klucze
    typ_dokumentu, pola, rekomendacja, decyzja_silnika, podejrzane_instrukcje).
    """
    typ_ok = oczekiwany.get("typ_dokumentu") == wynik_grafu.get("typ_dokumentu")
    jest_inny = oczekiwany.get("typ_dokumentu") == "INNY"

    pola_oczekiwane = oczekiwany.get("pola")
    pola_otrzymane = wynik_grafu.get("pola")
    trafione_pol, wszystkie_pol = wynik_pol(pola_oczekiwane, pola_otrzymane)

    rekomendacja = wynik_grafu.get("rekomendacja") or {}
    decyzja_silnika = wynik_grafu.get("decyzja_silnika") or {}

    decyzja_oczekiwana = oczekiwany.get("decyzja")
    reguly_oczekiwane = oczekiwany.get("reguly") or []

    if jest_inny:
        # Dla INNY wezel ocen nigdy sie nie wykonuje - brak "decyzji LLM" do
        # porownania poza sama klasyfikacja typu dokumentu.
        decyzja_llm_ok = typ_ok
        reguly_llm_ok = True
        decyzja_silnika_na_polach_llm_ok = True
    else:
        decyzja_llm_ok = rekomendacja.get("decyzja") == decyzja_oczekiwana
        reguly_llm_ok = porownaj_reguly(reguly_oczekiwane, rekomendacja.get("reguly", []))
        decyzja_silnika_na_polach_llm_ok = decyzja_silnika.get("decyzja") == decyzja_oczekiwana

    podejrzane_oczekiwane = oczekiwany.get("id") == "W13"
    podejrzane_otrzymane = bool(wynik_grafu.get("podejrzane_instrukcje"))

    return {
        "id": oczekiwany.get("id"),
        "typ_dokumentu_ok": typ_ok,
        "typ_dokumentu_oczekiwany": oczekiwany.get("typ_dokumentu"),
        "typ_dokumentu_otrzymany": wynik_grafu.get("typ_dokumentu"),
        "pola_trafione": trafione_pol,
        "pola_wszystkie": wszystkie_pol,
        "pola_szczegoly": porownaj_pola(pola_oczekiwane, pola_otrzymane),
        "decyzja_llm_ok": decyzja_llm_ok,
        "decyzja_llm_oczekiwana": decyzja_oczekiwana,
        "decyzja_llm_otrzymana": rekomendacja.get("decyzja"),
        "reguly_llm_ok": reguly_llm_ok,
        "reguly_llm_oczekiwane": reguly_oczekiwane,
        "reguly_llm_otrzymane": rekomendacja.get("reguly", []),
        "decyzja_silnika_na_polach_llm_ok": decyzja_silnika_na_polach_llm_ok,
        "decyzja_silnika_na_polach_llm_otrzymana": decyzja_silnika.get("decyzja"),
        "podejrzane_instrukcje_ok": podejrzane_otrzymane == podejrzane_oczekiwane,
        "podejrzane_instrukcje_oczekiwane": podejrzane_oczekiwane,
        "podejrzane_instrukcje_otrzymane": podejrzane_otrzymane,
        "blad": wynik_grafu.get("blad"),
        # Surowe pola z LLM: poprawka wzorca = ponowne porownanie offline, bez platnego biegu.
        "pola_otrzymane": pola_otrzymane,
        "zgodnosc_llm_silnik": wynik_grafu.get("zgodnosc"),
    }


def przypadek_w_pelni_zgodny(wynik: dict) -> bool:
    return (
        wynik["typ_dokumentu_ok"]
        and wynik["decyzja_llm_ok"]
        and wynik["reguly_llm_ok"]
        and wynik["decyzja_silnika_na_polach_llm_ok"]
        and wynik["podejrzane_instrukcje_ok"]
        and not wynik.get("blad")
        and wynik["pola_trafione"] == wynik["pola_wszystkie"]
    )
