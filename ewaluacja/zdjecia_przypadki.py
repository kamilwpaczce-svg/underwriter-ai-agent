"""Etap 23: pozycje ewaluacji vision - 12 zdjec pod wlasne zgloszenie + 6 par niezgodnych (SPEC decyzja 9).

Stala lista, nie losowana. Para = zdjecie jednego przypadku przylozone do zgloszenia innego.
Wykrycie = `NIEZGODNE` albo `sygnal_dlugotrwalosci`; metryka wykrycia liczona na N1-N5,
N6 (bardzo trudna: awaria silnika vs przepiecie) tylko raportowana.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pozycja:
    id: str
    zdjecie: str      # id przypadku, z ktorego pochodzi dane/zdjecia_szkod/<id>.jpg
    zgloszenie: str   # id przypadku, ktorego przyczyna jest porownywana ze zdjeciem
    trudnosc: str     # "zgodna" dla 12 par wlasnych; dla N1-N6: latwa / srednia / trudna / bardzo trudna


PARY_NIEZGODNE: tuple[Pozycja, ...] = (
    Pozycja("N1", "Z02", "Z01", "latwa"),          # zalanie pod zgloszenie pozaru
    Pozycja("N2", "Z12", "Z09", "latwa"),          # pozar pod zgloszenie zalania
    Pozycja("N3", "Z07", "Z08", "latwa"),          # wlamanie pod zgloszenie pozaru
    Pozycja("N4", "Z11", "Z10", "srednia"),        # huragan (woda na regalach) pod zalanie tryskaczem
    Pozycja("N5", "Z05", "Z02", "trudna"),         # korozja pod zalanie z rury: wykryta przez sygnal dlugotrwalosci
    Pozycja("N6", "Z06", "Z03", "bardzo trudna"),  # awaria silnika pod przepiecie: NIEUSTALONA dopuszczalna
)

# Pary, na ktorych liczona jest metryka wykrycia (N6 tylko raportowana).
ID_PAR_DO_METRYKI = ("N1", "N2", "N3", "N4", "N5")
ID_PARY_RAPORTOWANEJ = "N6"


def pozycje_ewaluacji(ids_szkod: list[str]) -> list[Pozycja]:
    """12 pozycji zgodnych (zdjecie Zxx pod zgloszenie Zxx) + 6 par niezgodnych = 18 na bieg."""
    zgodne = [Pozycja(i, i, i, "zgodna") for i in sorted(ids_szkod)]
    return [*zgodne, *PARY_NIEZGODNE]
