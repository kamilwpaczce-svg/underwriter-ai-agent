"""Deterministyczny podzial OWU na fragmenty: 1 ustep = 1 fragment (Etap 10).

Format pliku OWU: naglowki `## § N. Tytul`, ustepy `M. tresc` w jednej linii; linia
niepusta, ktora nie jest ani naglowkiem, ani nowym ustepem, dokleja sie do biezacego
ustepu. Tekst przed pierwszym paragrafem (tytul dokumentu, preambula) jest pomijany.
Tresc fragmentu zaczyna sie od tytulu paragrafu, zeby BM25 i embedding widzialy kontekst.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCIEZKA_OWU = ROOT / "owu" / "owu_mienie_msp_v1.md"

_NAGLOWEK_PARAGRAFU = re.compile(r"^## § (\d+)\. (.+?)\s*$")
_USTEP = re.compile(r"^(\d+)\. (.+)$")
_LICZBA = re.compile(r"\d+")


@dataclass(frozen=True)
class Fragment:
    id: str
    paragraf: int
    ustep: int
    tytul: str
    tresc: str


def podziel_owu(sciezka: str | Path = SCIEZKA_OWU) -> list[Fragment]:
    surowe: list[dict] = []
    paragraf: int | None = None
    tytul = ""
    biezacy: dict | None = None
    for linia in Path(sciezka).read_text(encoding="utf-8").splitlines():
        naglowek = _NAGLOWEK_PARAGRAFU.match(linia)
        if naglowek:
            paragraf, tytul, biezacy = int(naglowek.group(1)), naglowek.group(2), None
            continue
        if paragraf is None:
            continue
        ustep = _USTEP.match(linia)
        if ustep:
            biezacy = {"paragraf": paragraf, "ustep": int(ustep.group(1)), "tytul": tytul, "tekst": ustep.group(2).strip()}
            surowe.append(biezacy)
        elif linia.strip() and not linia.startswith("#") and biezacy is not None:
            biezacy["tekst"] += " " + linia.strip()
    return [
        Fragment(
            id=f"p{s['paragraf']}u{s['ustep']}",
            paragraf=s["paragraf"],
            ustep=s["ustep"],
            tytul=s["tytul"],
            tresc=f"§ {s['paragraf']}. {s['tytul']}\nust. {s['ustep']}. {s['tekst']}",
        )
        for s in surowe
    ]


def wersja_owu(sciezka: str | Path = SCIEZKA_OWU) -> str:
    return hashlib.sha256(Path(sciezka).read_bytes()).hexdigest()[:12]


def parsuj_liczbe(tekst: str | None) -> int | None:
    if not tekst:
        return None
    dopasowanie = _LICZBA.search(tekst)
    return int(dopasowanie.group()) if dopasowanie else None


def parsuj_odwolanie(tekst: str | None) -> tuple[int, int] | None:
    """`"§4 ust. 1"` -> `(4, 1)`. Brak dwoch liczb -> None."""
    if not tekst:
        return None
    liczby = _LICZBA.findall(tekst)
    if len(liczby) < 2:
        return None
    return int(liczby[0]), int(liczby[1])
