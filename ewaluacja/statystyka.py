"""Etap 19a: ocena statystyczna wynikow ewaluacji (bez scipy, sam stdlib).

    python -m ewaluacja.statystyka stabilnosc PLIK... --pole decyzja_llm_ok
    python -m ewaluacja.statystyka porownaj PLIK_A PLIK_B --pole trafione --klucz-listy pytania

Przedzial Wilsona zamiast Walda: przy n = 12-14 i trafnosci blisko 1 Wald wychodzi
poza [0, 1]. McNemar DOKLADNY (dwumianowy), nie chi^2: par niezgodnych jest kilka,
a przyblizenie chi^2 wymaga ich rzedu 25+.

Biegi tego samego przypadku sa skorelowane - 5 biegow na 14 przypadkach to efektywne
n = 14, nie 70. Dlatego `stabilnosc` raportuje kazdy bieg osobno z przedzialem na
n przypadkow, a do porownania konfiguracji bierze wynik wiekszosciowy przypadku.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

Z_95 = 1.959964


def przedzial_wilsona(trafienia: int, n: int, z: float = Z_95) -> tuple[float, float]:
    if n <= 0 or trafienia < 0 or trafienia > n:
        raise ValueError(f"Niepoprawne trafienia={trafienia}, n={n}")
    p = trafienia / n
    z2 = z * z
    mianownik = 1 + z2 / n
    srodek = (p + z2 / (2 * n)) / mianownik
    polowa = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / mianownik
    return max(0.0, srodek - polowa), min(1.0, srodek + polowa)


def mcnemar_dokladny(b: int, c: int) -> float:
    """Dwustronne p dokladnego testu McNemara; b, c = liczby par niezgodnych w obie strony."""
    if b < 0 or c < 0:
        raise ValueError(f"Niepoprawne b={b}, c={c}")
    n = b + c
    if n == 0:
        return 1.0
    ogon = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * ogon)


def wczytaj_wyniki(plik: Path, pole: str, klucz_listy: str = "przypadki",
                   pole_id: str = "id") -> dict[str, bool]:
    """id -> trafione. Wartosc nie-bool (np. None przy bledzie agenta) liczy sie jako
    porazka - blad agenta to nietrafienie, nie brak danych - i jest zglaszana na stderr."""
    wiersze = json.loads(Path(plik).read_text(encoding="utf-8"))[klucz_listy]
    wyniki: dict[str, bool] = {}
    nie_bool: list[str] = []
    for w in wiersze:
        wartosc = w[pole]
        if not isinstance(wartosc, bool):
            nie_bool.append(str(w[pole_id]))
        wyniki[str(w[pole_id])] = wartosc is True
    if nie_bool:
        print(f"UWAGA {Path(plik).name}: pole '{pole}' nie-bool dla {nie_bool} - liczone jako nietrafione",
              file=sys.stderr)
    return wyniki


def stabilnosc(biegi: list[dict[str, bool]]) -> dict:
    ids = sorted(biegi[0])
    if any(sorted(b) != ids for b in biegi):
        raise ValueError("Biegi maja rozne zbiory przypadkow - porownanie stabilnosci bez sensu")
    trafienia_przypadku = {i: sum(b[i] for b in biegi) for i in ids}
    liczba = len(biegi)
    return {
        "n": len(ids),
        "biegi": liczba,
        "trafienia_biegow": [sum(b.values()) for b in biegi],
        "niestabilne": {i: t for i, t in trafienia_przypadku.items() if 0 < t < liczba},
        "wiekszosc": {i: t * 2 > liczba for i, t in trafienia_przypadku.items()},
    }


def porownaj(a: dict[str, bool], b: dict[str, bool]) -> dict:
    tylko_a, tylko_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    if tylko_a or tylko_b:
        print(f"UWAGA: rozne zbiory przypadkow - tylko w A: {tylko_a}, tylko w B: {tylko_b}; "
              "porownanie na czesci wspolnej", file=sys.stderr)
    wspolne = sorted(set(a) & set(b))
    b_ = sum(a[i] and not b[i] for i in wspolne)
    c_ = sum(b[i] and not a[i] for i in wspolne)
    return {
        "n": len(wspolne),
        "trafione_a": sum(a[i] for i in wspolne),
        "trafione_b": sum(b[i] for i in wspolne),
        "b": b_,
        "c": c_,
        "p": mcnemar_dokladny(b_, c_),
        "tylko_a_ok": [i for i in wspolne if a[i] and not b[i]],
        "tylko_b_ok": [i for i in wspolne if b[i] and not a[i]],
    }


def _procent(x: float) -> str:
    return f"{100 * x:.0f}%"


def _raport_stabilnosci(nazwy: list[str], s: dict) -> str:
    n = s["n"]
    linie = [f"## Stabilnosc: {s['biegi']} biegow x {n} przypadkow (efektywne n = {n})", "",
             "| bieg | trafione | trafnosc | Wilson 95% |", "|---|---|---|---|"]
    for nazwa, t in zip(nazwy, s["trafienia_biegow"]):
        d, g = przedzial_wilsona(t, n)
        linie.append(f"| {nazwa} | {t}/{n} | {_procent(t / n)} | {_procent(d)}-{_procent(g)} |")
    t = s["trafienia_biegow"]
    linie += ["", f"Rozrzut: min {min(t)}, max {max(t)}, srednia {sum(t) / len(t):.1f} / {n}.",
              f"Przypadki niestabilne (trafione w czesci biegow): "
              + (", ".join(f"{i} ({k}/{s['biegi']})" for i, k in s["niestabilne"].items()) or "brak")]
    w = sum(s["wiekszosc"].values())
    d, g = przedzial_wilsona(w, n)
    linie.append(f"Wynik wiekszosciowy: {w}/{n}, Wilson 95% {_procent(d)}-{_procent(g)}.")
    return "\n".join(linie)


def _raport_porownania(a: str, b: str, w: dict) -> str:
    n = w["n"]
    da, ga = przedzial_wilsona(w["trafione_a"], n)
    db, gb = przedzial_wilsona(w["trafione_b"], n)
    wniosek = ("roznica istotna na poziomie 0,05" if w["p"] < 0.05
               else "roznica NIEISTOTNA - przy tej liczbie przypadkow to szum")
    return "\n".join([
        f"## Porownanie (dokladny McNemar, n = {n})", "",
        "| konfiguracja | trafione | Wilson 95% |", "|---|---|---|",
        f"| A: {a} | {w['trafione_a']}/{n} | {_procent(da)}-{_procent(ga)} |",
        f"| B: {b} | {w['trafione_b']}/{n} | {_procent(db)}-{_procent(gb)} |", "",
        f"Pary niezgodne: tylko A trafia {w['b']} {w['tylko_a_ok']}, tylko B trafia {w['c']} {w['tylko_b_ok']}.",
        f"p = {w['p']:.4f} -> {wniosek}.",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ocena statystyczna wynikow ewaluacji (Etap 19a).")
    sub = parser.add_subparsers(dest="komenda", required=True)
    for nazwa, pomoc in (("stabilnosc", "N biegow tej samej konfiguracji"),
                         ("porownaj", "dwie konfiguracje, dokladny McNemar")):
        p = sub.add_parser(nazwa, help=pomoc)
        p.add_argument("pliki", nargs="+", type=Path)
        p.add_argument("--pole", required=True, help="pole bool w wierszu, np. decyzja_llm_ok, decyzja_ok, trafione")
        p.add_argument("--klucz-listy", default="przypadki", help="'przypadki' (underwriter) albo 'pytania' (A25)")
        p.add_argument("--pole-id", default="id")
        p.add_argument("--zapisz", type=Path, help="zapisz raport markdown do pliku")
    args = parser.parse_args(argv)

    wyniki = [wczytaj_wyniki(p, args.pole, args.klucz_listy, args.pole_id) for p in args.pliki]
    nazwy = [p.stem for p in args.pliki]
    if args.komenda == "stabilnosc":
        if len(wyniki) < 2:
            parser.error("stabilnosc wymaga co najmniej 2 plikow")
        raport = _raport_stabilnosci(nazwy, stabilnosc(wyniki))
    else:
        if len(wyniki) != 2:
            parser.error("porownaj wymaga dokladnie 2 plikow")
        raport = _raport_porownania(nazwy[0], nazwy[1], porownaj(*wyniki))

    print(raport)
    if args.zapisz:
        args.zapisz.write_text(raport + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
