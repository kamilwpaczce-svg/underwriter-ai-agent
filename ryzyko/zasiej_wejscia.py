"""Zasiew wierszy `zrodlo='symulacja'` do `wejscia_modelu` - do testu na zywo alertow dryfu (Etap 15).

Uzycie (DATABASE_URL w env; w chmurze patrz docs/MLOPS.md - uruchamiane jako jednorazowe
wykonanie joba `uw-dryf` z nadpisana komenda, bo baza nie ma publicznego dostepu):

    python -m ryzyko.zasiej_wejscia --n 300 --seed 11
    python -m ryzyko.zasiej_wejscia --n 300 --seed 12 --przesuniecie udzial_kwoty=0.5
    python -m ryzyko.zasiej_wejscia --sprzatnij

Wiersze: cechy z `ryzyko.generator.generuj_zbior` (te same nazwy i typy, co z `cechy_ze_stanu`),
`wersja_modelu='symulacja'`, `wynik=0.0` (model nie jest tu uruchamiany - PSI liczy cechy, nie
wynik), `wniosek_id=NULL`. `--sprzatnij` kasuje WYLACZNIE wiersze `zrodlo='symulacja'`
(wiersze `api` sa nietykalne). Skrypt nie konfiguruje telemetrii, wiec nie tworzy spanow
(w szczegolnosci `dryf.przebieg`, ktory liczy alert B). Na stdout tylko liczby.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Callable

from sqlalchemy import delete, func, select

from api.baza import WejscieModelu
from ryzyko.cechy import CECHY
from ryzyko.generator import generuj_zbior

ZRODLO_SYMULACJI = "symulacja"
WERSJA_SYMULACJI = "symulacja"
MAX_WIERSZY = 5000


def parsuj_przesuniecie(pary: list[str] | None) -> dict[str, float] | None:
    """`["udzial_kwoty=0.5", ...]` -> `{"udzial_kwoty": 0.5}`; nieznane cechy odrzuca generator."""
    if not pary:
        return None
    wynik: dict[str, float] = {}
    for para in pary:
        nazwa, sep, wartosc = para.partition("=")
        if not sep or not nazwa.strip():
            raise ValueError(f"przesuniecie musi miec postac cecha=liczba, dostalem {para!r}")
        wynik[nazwa.strip()] = float(wartosc)
    return wynik


def zasiej(fabryka_sesji: Callable[[], Any], n: int, seed: int, przesuniecie: dict[str, float] | None = None) -> int:
    """Wstawia `n` wierszy symulacji; zwraca liczbe wstawionych."""
    if not 1 <= n <= MAX_WIERSZY:
        raise ValueError(f"n musi byc w zakresie 1..{MAX_WIERSZY}, dostalem {n}")
    df = generuj_zbior(n, seed=seed, przesuniecie=przesuniecie)[CECHY]
    with fabryka_sesji() as sesja:
        for rekord in df.to_dict("records"):
            sesja.add(
                WejscieModelu(
                    wniosek_id=None,
                    wersja_modelu=WERSJA_SYMULACJI,
                    cechy=rekord,
                    wynik=0.0,
                    zrodlo=ZRODLO_SYMULACJI,
                )
            )
        sesja.commit()
    return n


def sprzatnij(fabryka_sesji: Callable[[], Any]) -> int:
    """Kasuje WYLACZNIE wiersze `zrodlo='symulacja'`; zwraca liczbe usunietych."""
    with fabryka_sesji() as sesja:
        wynik = sesja.execute(delete(WejscieModelu).where(WejscieModelu.zrodlo == ZRODLO_SYMULACJI))
        sesja.commit()
        return int(wynik.rowcount)


def _liczniki(fabryka_sesji: Callable[[], Any]) -> dict[str, int]:
    with fabryka_sesji() as sesja:
        wiersze = sesja.execute(select(WejscieModelu.zrodlo, func.count()).group_by(WejscieModelu.zrodlo)).all()
    return {zrodlo: int(ile) for zrodlo, ile in wiersze}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zasiew / sprzatanie wierszy symulacji w wejscia_modelu.")
    parser.add_argument("--n", type=int, help="liczba wierszy do wstawienia")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--przesuniecie", action="append", metavar="CECHA=LICZBA", help="dryf, np. udzial_kwoty=0.5")
    parser.add_argument("--sprzatnij", action="store_true", help="usun wszystkie wiersze zrodlo='symulacja'")
    args = parser.parse_args(argv)
    if args.sprzatnij == (args.n is not None):
        parser.error("podaj dokladnie jedno z: --n (zasiew) albo --sprzatnij")

    from api.baza import utworz_fabryke_sesji, utworz_silnik

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("BLAD: brak DATABASE_URL", file=sys.stderr)
        return 1
    fabryka = utworz_fabryke_sesji(utworz_silnik(database_url))
    if args.sprzatnij:
        print(f"usunieto={sprzatnij(fabryka)}")
    else:
        przesuniecie = parsuj_przesuniecie(args.przesuniecie)
        print(f"wstawiono={zasiej(fabryka, args.n, args.seed, przesuniecie)} przesuniecie={przesuniecie or 'brak'}")
    print(f"w_tabeli={_liczniki(fabryka)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
