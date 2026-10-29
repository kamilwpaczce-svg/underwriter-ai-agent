"""Deterministyczne sprawdzenie polisy dla zgloszenia szkody (Etap 10, wezel `sprawdz_polise`).

Kody (SPEC_ETAP10.md):
- S01 - brak polisy o tym numerze -> SKIEROWANIE, dalej bez LLM,
- S02 - data zdarzenia poza okresem ubezpieczenia (granice wlacznie) -> ODMOWA, dalej bez LLM,
- S03 - szacowana kwota > SU dla rodzaju mienia (rowna SU jest OK) -> POKRYTA zamienia sie na SKIEROWANIE,
- S04 - zgloszenie pozniej niz `TERMIN_ZGLOSZENIA_DNI` po zdarzeniu -> tylko flaga dla LLM.

`braki` to pola, bez ktorych nie da sie sprawdzic warunku (np. OCR zgubil date). Brak nie
jest kodem: kod oznacza stwierdzone naruszenie, brak - ze nie wiadomo. Decyzje z brakami
rozstrzyga `agent.decyzje_szkody.ustal_decyzje_szkody` (POKRYTA z brakami -> SKIEROWANIE).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCIEZKA_POLIS = ROOT / "dane" / "polisy.json"
TERMIN_ZGLOSZENIA_DNI = 7
POLE_SU = {"budynek": "su_budynki", "maszyny": "su_maszyny", "zapasy": "su_zapasy"}

_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalizuj_nr_polisy(nr: str | None) -> str | None:
    if not nr:
        return None
    return re.sub(r"\s+", "", nr).upper() or None


def wczytaj_polisy(sciezka: str | Path = SCIEZKA_POLIS) -> dict[str, dict[str, Any]]:
    """Slownik `znormalizowany nr_polisy -> polisa`. Brak pliku -> FileNotFoundError
    (glosno: bez polis kazda szkoda dostalaby S01)."""
    lista = json.loads(Path(sciezka).read_text(encoding="utf-8"))
    return {normalizuj_nr_polisy(p["nr_polisy"]): p for p in lista}


def _data(tekst: Any) -> date | None:
    if not isinstance(tekst, str) or not _DATA_ISO.match(tekst.strip()):
        return None
    try:
        return date.fromisoformat(tekst.strip())
    except ValueError:
        return None


def _kwota_poprawna(kwota: Any) -> bool:
    return isinstance(kwota, int) and not isinstance(kwota, bool) and kwota >= 0


def sprawdz_polise(
    pola: dict[str, Any],
    polisy: dict[str, dict[str, Any]],
    termin_zgloszenia_dni: int = TERMIN_ZGLOSZENIA_DNI,
) -> dict[str, Any]:
    wynik: dict[str, Any] = {
        "kody": [],
        "polisa": None,
        "suma_ubezpieczenia": None,
        "dni_do_zgloszenia": None,
        "braki": [],
        "opis": [],
    }
    nr = normalizuj_nr_polisy(pola.get("nr_polisy"))
    polisa = polisy.get(nr) if nr else None
    if polisa is None:
        wynik["kody"].append("S01")
        wynik["opis"].append(f"S01: brak polisy o numerze {pola.get('nr_polisy')!r}.")
        return wynik
    wynik["polisa"] = polisa

    data_zdarzenia = _data(pola.get("data_zdarzenia"))
    if data_zdarzenia is None:
        wynik["braki"].append("data_zdarzenia")
        wynik["opis"].append("Brak poprawnej daty zdarzenia - okresu ubezpieczenia nie sprawdzono.")
    elif not (_data(polisa["okres_od"]) <= data_zdarzenia <= _data(polisa["okres_do"])):
        wynik["kody"].append("S02")
        wynik["opis"].append(
            f"S02: zdarzenie {data_zdarzenia.isoformat()} poza okresem "
            f"{polisa['okres_od']} - {polisa['okres_do']}."
        )

    pole_su = POLE_SU.get(pola.get("rodzaj_mienia") or "")
    if pole_su is None:
        wynik["braki"].append("rodzaj_mienia")
        wynik["opis"].append("Brak rodzaju mienia - sumy ubezpieczenia nie sprawdzono.")
    else:
        wynik["suma_ubezpieczenia"] = polisa[pole_su]

    kwota = pola.get("szacowana_kwota")
    if not _kwota_poprawna(kwota):
        wynik["braki"].append("szacowana_kwota")
        wynik["opis"].append("Brak szacowanej kwoty szkody - sumy ubezpieczenia nie sprawdzono.")
    elif wynik["suma_ubezpieczenia"] is not None and kwota > wynik["suma_ubezpieczenia"]:
        wynik["kody"].append("S03")
        wynik["opis"].append(f"S03: kwota {kwota} przekracza sume ubezpieczenia {wynik['suma_ubezpieczenia']}.")

    data_zgloszenia = _data(pola.get("data_zgloszenia"))
    if data_zgloszenia is None:
        wynik["opis"].append("Brak daty zgloszenia - terminu zgloszenia nie sprawdzono.")
    elif data_zdarzenia is not None:
        dni = (data_zgloszenia - data_zdarzenia).days
        wynik["dni_do_zgloszenia"] = dni
        if dni > termin_zgloszenia_dni:
            wynik["kody"].append("S04")
            wynik["opis"].append(f"S04: zgloszenie {dni} dni po zdarzeniu (termin {termin_zgloszenia_dni} dni).")
    return wynik
