"""Walidacja i normalizacja polskiego NIP (suma kontrolna)."""

from __future__ import annotations

WAGI_NIP = [6, 5, 7, 2, 3, 4, 5, 6, 7]


def normalizuj_nip(tekst: str) -> str:
    """Usuwa wszystko poza cyframi: myślniki, spacje, prefiks 'PL' itp.

    "123-456-32-18" -> "1234563218"
    "PL1234563218"  -> "1234563218"
    """
    if tekst is None:
        return ""
    return "".join(znak for znak in tekst if znak.isdigit())


def oblicz_cyfre_kontrolna(nip_9_cyfr: str) -> int:
    """Liczy cyfrę kontrolną z pierwszych 9 cyfr NIP wg wag WAGI_NIP."""
    if len(nip_9_cyfr) != 9 or not nip_9_cyfr.isdigit():
        raise ValueError("Oczekiwano dokładnie 9 cyfr")
    suma = sum(int(cyfra) * waga for cyfra, waga in zip(nip_9_cyfr, WAGI_NIP))
    return suma % 11


def nip_poprawny(nip: str) -> bool:
    """Sprawdza sumę kontrolną 10-cyfrowego NIP (oczekuje samych cyfr).

    Zwraca False dla niepoprawnej długości, nie-cyfr oraz dla sumy kontrolnej
    równej 10 (wtedy żadna cyfra 0-9 nie może jej spełnić).
    """
    if len(nip) != 10 or not nip.isdigit():
        return False
    cyfra_kontrolna = oblicz_cyfre_kontrolna(nip[:9])
    if cyfra_kontrolna == 10:
        return False
    return cyfra_kontrolna == int(nip[9])


def wygeneruj_poprawny_nip(nip_9_cyfr: str) -> str:
    """Dla 9-cyfrowego prefiksu dokleja poprawną cyfrę kontrolną.

    Pomocnicze przy tworzeniu danych testowych / przypadków.
    """
    cyfra_kontrolna = oblicz_cyfre_kontrolna(nip_9_cyfr)
    if cyfra_kontrolna == 10:
        raise ValueError("Dla tego prefiksu nie istnieje poprawny NIP (suma mod 11 == 10)")
    return nip_9_cyfr + str(cyfra_kontrolna)
