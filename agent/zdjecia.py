"""Etap 23: zgodnosc zdjecia szkody ze zgloszona przyczyna - czysty kod, bez LLM i bez sieci.

Model vision opisuje zdjecie "na slepo" (bez przyczyny ze zgloszenia, SPEC decyzja 2); porownanie
robi ten modul, wiec jest testowalny offline i jednakowy dla kazdego dostawcy modelu.
Wynik to sygnal dla likwidatora - nigdy nie zmienia decyzji ani trasy.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from agent.schematy import OcenaZdjecia, RodzajZdarzenia

# Analizujemy tylko pierwsze zdjecie (SPEC decyzja 5); kolejne -> powod `pominieto_kolejne_zdjecia`.
MAKS_ZDJEC = 1
MAKS_ROZMIAR_BAJTOW = 5 * 1024 * 1024
# MIME po rozszerzeniu pliku - dozwolone tylko JPEG i PNG. Naglowek (magic bytes) musi sie z nim zgadzac.
MIME_WG_ROZSZERZENIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
NAGLOWKI_WG_MIME = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n"}


class BladOdczytuZdjecia(Exception):
    """Zdjecia nie da sie wczytac; `powod` to krotki kod (bez sciezki i bez tresci pliku)."""

    def __init__(self, powod: str):
        super().__init__(powod)
        self.powod = powod

# Ustalony z gory, NIE strojony na zestawie ewaluacyjnym (18 pozycji to za malo na strojenie).
# Pewnosc z LLM nie jest skalibrowana - to nie jest prawdopodobienstwo.
PROG_PEWNOSCI = 0.6

POKREWNE = {
    frozenset({"przepiecie", "awaria_wewnetrzna"}),
    frozenset({"zalanie", "korozja_zawilgocenie"}),
}

# Kolejnosc ma znaczenie - pierwsza pasujaca wygrywa. Wzorce na tekscie bez ogonkow, malymi literami;
# `\b` tylko z przodu (rdzenie wyrazow). korozja/zawilgocenie/nieszczelny przed zalanie/woda
# (Z05: "korozja ... woda przeciekajaca przez nieszczelny dach"), tryskacz przed awaria
# (Z10: "... po awarii zaworu").
_REGULY_KATEGORII: list[tuple[RodzajZdarzenia, re.Pattern[str]]] = [
    ("korozja_zawilgocenie", re.compile(r"\b(korozj|zawilg|nieszczeln|rdz[aey]|plesn)")),
    ("zalanie", re.compile(r"\b(tryskacz|zalan|zalew|zatopi)")),
    ("przepiecie", re.compile(r"\b(piorun|przepiec)")),
    ("huragan_wiatr", re.compile(r"\b(huragan|wiatr|nawalnic|wichur|burz\w*\b.*\bdach|dach\w*\b.*\bburz)")),
    ("pozar", re.compile(r"\b(pozar|ogien|ognia|splon)")),
    ("kradziez_wlamanie", re.compile(r"\b(kradziez|wlam|skradzion)")),
    ("awaria_wewnetrzna", re.compile(r"\b(awari|uzwojeni)")),
    ("zalanie", re.compile(r"\b(wod[aeiuy]?\b|wodoc)")),
]


def _bez_ogonkow(tekst: str) -> str:
    tekst = tekst.lower().replace("ł", "l")  # ł nie rozkłada się w NFKD
    rozlozony = unicodedata.normalize("NFKD", tekst)
    return "".join(znak for znak in rozlozony if not unicodedata.combining(znak))


def kategoria_przyczyny(przyczyna: str | None) -> RodzajZdarzenia | None:
    """Rodzaj zdarzenia ze zgloszonej przyczyny (slownik slow-kluczy); brak dopasowania -> None."""
    if not przyczyna or not przyczyna.strip():
        return None
    tekst = _bez_ogonkow(przyczyna)
    for rodzaj, wzorzec in _REGULY_KATEGORII:
        if wzorzec.search(tekst):
            return rodzaj
    return None


def porownaj(ocena: OcenaZdjecia, kategoria_zgloszona: RodzajZdarzenia | None) -> dict:
    """Zgodnosc zdjecia ze zgloszeniem. Zwraca `zgodnosc_rodzaju` (ZGODNE / NIEZGODNE / NIEUSTALONA),
    `sygnal_dlugotrwalosci` i `powody` (przyczyny NIEUSTALONA). Pierwsza pasujaca regula wygrywa."""
    pewnosc_ok = ocena.pewnosc >= PROG_PEWNOSCI
    sygnal = bool(
        ocena.dlugotrwalosc == "DLUGOTRWALE" and pewnosc_ok and kategoria_zgloszona != "korozja_zawilgocenie"
    )
    if kategoria_zgloszona is None:
        zgodnosc, powody = "NIEUSTALONA", ["przyczyna_nierozpoznana"]
    elif not ocena.czy_widac_szkode:
        zgodnosc, powody = "NIEUSTALONA", ["brak_widocznej_szkody"]
    elif not pewnosc_ok:
        zgodnosc, powody = "NIEUSTALONA", ["niska_pewnosc"]
    elif ocena.rodzaj_zdarzenia == "inne":
        zgodnosc, powody = "NIEUSTALONA", ["rodzaj_inne"]
    elif ocena.rodzaj_zdarzenia == kategoria_zgloszona:
        zgodnosc, powody = "ZGODNE", []
    elif frozenset({ocena.rodzaj_zdarzenia, kategoria_zgloszona}) in POKREWNE:
        zgodnosc, powody = "NIEUSTALONA", ["kategorie_pokrewne"]
    else:
        zgodnosc, powody = "NIEZGODNE", []
    return {"zgodnosc_rodzaju": zgodnosc, "sygnal_dlugotrwalosci": sygnal, "powody": powody}


def wczytaj_obraz(sciezka: str | Path) -> tuple[bytes, str]:
    """(bajty, mime_type) zdjecia z dysku albo `BladOdczytuZdjecia` z kodem powodu:
    nieobslugiwany_typ / plik_nie_istnieje / plik_za_duzy / plik_pusty / niezgodny_naglowek / blad_odczytu.
    Rozmiar sprawdzany przed odczytem (stat) i po nim (plik mogl urosnac)."""
    plik = Path(sciezka)
    mime = MIME_WG_ROZSZERZENIA.get(plik.suffix.lower())
    if mime is None:
        raise BladOdczytuZdjecia("nieobslugiwany_typ")
    try:
        if not plik.is_file():
            raise BladOdczytuZdjecia("plik_nie_istnieje")
        if plik.stat().st_size > MAKS_ROZMIAR_BAJTOW:
            raise BladOdczytuZdjecia("plik_za_duzy")
        with open(plik, "rb") as uchwyt:
            bajty = uchwyt.read(MAKS_ROZMIAR_BAJTOW + 1)
    except BladOdczytuZdjecia:
        raise
    except OSError as e:
        raise BladOdczytuZdjecia("blad_odczytu") from e
    if len(bajty) > MAKS_ROZMIAR_BAJTOW:
        raise BladOdczytuZdjecia("plik_za_duzy")
    if not bajty:
        raise BladOdczytuZdjecia("plik_pusty")
    if not bajty.startswith(NAGLOWKI_WG_MIME[mime]):
        raise BladOdczytuZdjecia("niezgodny_naglowek")
    return bajty, mime
