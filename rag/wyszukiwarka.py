"""Wyszukiwanie fragmentow OWU (Etap 10): Protocol `Wyszukiwarka` i implementacja lokalna.

`WyszukiwarkaLokalna` to BM25 w pamieci po tym samym pliku OWU co indeks Azure - bez
sieci, do testow, CI i atrapy. Tokenizacja: male litery, polskie znaki -> ASCII, slowa
z co najmniej 3 znakow obciete do 5 pierwszych (prosty "stemming" dla fleksji: pozar,
pozaru, pozarem -> "pozar").
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Protocol

from rag.fragmenty import SCIEZKA_OWU, Fragment, podziel_owu

TOP_K = 5
K_DODATKOWE = 3

_ZAMIANA_ZNAKOW = str.maketrans("ąćęłńóśźż", "acelnoszz")
_SLOWO = re.compile(r"[a-z0-9]+")


class Wyszukiwarka(Protocol):
    nazwa: str

    def szukaj(self, zapytanie: str, k: int = TOP_K) -> list[Fragment]: ...


def tokenizuj(tekst: str) -> list[str]:
    tekst = tekst.lower().translate(_ZAMIANA_ZNAKOW)
    return [slowo[:5] for slowo in _SLOWO.findall(tekst) if len(slowo) >= 3]


class WyszukiwarkaLokalna:
    """BM25 (k1=1.5, b=0.75, idf = log(1 + (N - n + 0.5) / (n + 0.5))). Remis -> kolejnosc
    w OWU. Fragmenty z wynikiem 0 nie sa zwracane."""

    nazwa = "lokalna"

    def __init__(self, sciezka_owu: str | Path = SCIEZKA_OWU, k1: float = 1.5, b: float = 0.75):
        self._fragmenty = podziel_owu(sciezka_owu)
        self._k1 = k1
        self._b = b
        self._dokumenty = [Counter(tokenizuj(f.tresc)) for f in self._fragmenty]
        self._dlugosci = [sum(d.values()) for d in self._dokumenty]
        self._srednia_dlugosc = sum(self._dlugosci) / len(self._dlugosci)
        liczba = len(self._dokumenty)
        czestosc = Counter()
        for dokument in self._dokumenty:
            czestosc.update(dokument.keys())
        self._idf = {t: math.log(1 + (liczba - c + 0.5) / (c + 0.5)) for t, c in czestosc.items()}

    @property
    def fragmenty(self) -> list[Fragment]:
        return list(self._fragmenty)

    def _wynik(self, indeks: int, tokeny: list[str]) -> float:
        dokument = self._dokumenty[indeks]
        normalizacja = 1 - self._b + self._b * self._dlugosci[indeks] / self._srednia_dlugosc
        wynik = 0.0
        for token in tokeny:
            tf = dokument.get(token, 0)
            if tf:
                wynik += self._idf[token] * tf * (self._k1 + 1) / (tf + self._k1 * normalizacja)
        return wynik

    def szukaj(self, zapytanie: str, k: int = TOP_K) -> list[Fragment]:
        tokeny = tokenizuj(zapytanie)
        wyniki = [(self._wynik(i, tokeny), i) for i in range(len(self._fragmenty))]
        wyniki.sort(key=lambda para: (-para[0], para[1]))
        return [self._fragmenty[i] for wynik, i in wyniki[:k] if wynik > 0]
