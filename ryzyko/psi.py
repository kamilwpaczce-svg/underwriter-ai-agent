"""Population Stability Index (PSI) - monitoring dryfu cech (Etap 15, SPEC decyzja 9).

`referencja(df)` zapisuje per cecha:
- liczbowa: `mediana` (dla `ryzyko.serwowanie`; PSI jej nie uzywa), `granice` (unikalne kwantyle 10%..90% ze zbioru treningowego, czyli do 9
  granic wewnetrznych = do 10 koszy; cecha dyskretna z duplikatami kwantyli ma mniej koszy)
  i `proporcje` kosztow; kosze skrajne sa otwarte, wiec wartosc poza zakresem
  treningowym wpada do skrajnego kosza, a nie jest gubiona,
- kategoria: `proporcje` per kategoria.
Wynik jest czystym slownikiem JSON (zapis do `referencja.json`).

`psi(ref, df)` porownuje biezace dane z referencja. Pusta kolumna / brak kolumny to
BLAD, nigdy PSI = 0 (brak danych nie jest dowodem braku dryfu).
Regula kciuka: < 0,1 stabilnie, 0,1-0,2 uwaga, > 0,2 dryf.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ryzyko.cechy import CECHY_KATEGORIALNE, CECHY_LICZBOWE

LICZBA_KOSZY = 10
EPSILON = 1e-4  # zamiast 0 w pustym koszu (log(0) i dzielenie przez 0)
KOSZ_NIEZNANY = "__nieznana_kategoria__"


def _wartosci(df: pd.DataFrame, cecha: str) -> pd.Series:
    if cecha not in df.columns:
        raise KeyError(f"brak kolumny {cecha!r} w danych")
    seria = df[cecha].dropna()
    if seria.empty:
        raise ValueError(f"kolumna {cecha!r} jest pusta - PSI nie do policzenia")
    return seria


def _proporcje_liczbowe(wartosci: np.ndarray, granice: list[float]) -> np.ndarray:
    kosze = np.searchsorted(np.asarray(granice, dtype=float), wartosci, side="left")
    zliczenia = np.bincount(kosze, minlength=len(granice) + 1)
    return zliczenia / zliczenia.sum()


def referencja(df: pd.DataFrame) -> dict[str, Any]:
    """Etap 15: granice koszy i proporcje treningowe per cecha (serializowalne do JSON)."""
    wynik: dict[str, Any] = {}
    for cecha in CECHY_LICZBOWE:
        wartosci = _wartosci(df, cecha).to_numpy(dtype=float)
        kwantyle = np.quantile(wartosci, np.linspace(0, 1, LICZBA_KOSZY + 1)[1:-1])
        granice = [float(g) for g in np.unique(kwantyle)]
        wynik[cecha] = {
            "typ": "liczbowa",
            "granice": granice,
            "proporcje": [float(p) for p in _proporcje_liczbowe(wartosci, granice)],
            "mediana": float(np.median(wartosci)),  # do przyblizenia "glownych cech" w serwowaniu
        }
    for cecha in CECHY_KATEGORIALNE:
        liczebnosci = _wartosci(df, cecha).astype(str).value_counts(normalize=True)
        wynik[cecha] = {"typ": "kategoria", "proporcje": {str(k): float(v) for k, v in liczebnosci.items()}}
    return wynik


def _psi_wektorow(oczekiwane: np.ndarray, biezace: np.ndarray) -> float:
    e = np.maximum(oczekiwane, EPSILON)
    a = np.maximum(biezace, EPSILON)
    return float(np.sum((a - e) * np.log(a / e)))


def psi(ref_cechy: dict[str, Any], df_biezace: pd.DataFrame) -> dict[str, float]:
    """Etap 15: PSI per cecha z `ref_cechy` (wynik `referencja`) dla `df_biezace`.

    Nieznana kategoria -> osobny kosz (referencja ma tam 0 -> EPSILON), nie wyjatek.
    Brak kolumny -> KeyError, pusta kolumna -> ValueError.
    """
    wynik: dict[str, float] = {}
    for cecha, opis in ref_cechy.items():
        wartosci = _wartosci(df_biezace, cecha)
        if opis["typ"] == "liczbowa":
            biezace = _proporcje_liczbowe(wartosci.to_numpy(dtype=float), opis["granice"])
            oczekiwane = np.asarray(opis["proporcje"], dtype=float)
        else:
            znane = list(opis["proporcje"])
            udzialy = wartosci.astype(str).value_counts(normalize=True)
            biezace = np.array([udzialy.get(k, 0.0) for k in znane] + [float(udzialy[~udzialy.index.isin(znane)].sum())])
            oczekiwane = np.array([opis["proporcje"][k] for k in znane] + [0.0])
        wynik[cecha] = _psi_wektorow(oczekiwane, biezace)
    return wynik
