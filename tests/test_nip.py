import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))

from nip import normalizuj_nip, nip_poprawny, oblicz_cyfre_kontrolna, wygeneruj_poprawny_nip


def test_normalizacja_myslniki():
    assert normalizuj_nip("123-456-32-18") == "1234563218"


def test_normalizacja_prefiks_pl():
    assert normalizuj_nip("PL1234563218") == "1234563218"


def test_normalizacja_spacje():
    assert normalizuj_nip("123 456 32 18") == "1234563218"


def test_nip_poprawny_dla_prawidlowej_sumy_kontrolnej():
    nip = wygeneruj_poprawny_nip("123456320")
    assert nip_poprawny(nip) is True


def test_nip_niepoprawny_dla_zlej_sumy_kontrolnej():
    nip = wygeneruj_poprawny_nip("123456320")
    zly_nip = nip[:9] + str((int(nip[9]) + 1) % 10)
    assert nip_poprawny(zly_nip) is False


def test_nip_niepoprawny_dla_zlej_dlugosci():
    assert nip_poprawny("12345") is False
    assert nip_poprawny("123456789012") is False


def test_nip_niepoprawny_dla_nie_cyfr():
    assert nip_poprawny("12345abcde") is False


def test_oblicz_cyfre_kontrolna_wymaga_9_cyfr():
    try:
        oblicz_cyfre_kontrolna("12345")
        assert False, "powinien rzucic ValueError"
    except ValueError:
        pass
