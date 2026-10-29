"""Testy wczytywania dokumentow wejsciowych (agent/wczytywanie.py).

Uzywa plikow wygenerowanych w Etapie 1 (dane/wnioski) - test_dane.py dba o to,
ze te pliki istnieja i sa poprawne po `python generator/generuj.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.wczytywanie import wczytaj_plik

ROOT = Path(__file__).resolve().parent.parent
WNIOSKI_DIR = ROOT / "dane" / "wnioski"


def test_pdf_formularz_ma_tekst_i_medium_pdf():
    czesci = wczytaj_plik(WNIOSKI_DIR / "W01.pdf")
    assert "Wisła" in czesci.tekst or "Wisla" in czesci.tekst or len(czesci.tekst) > 0
    assert len(czesci.media) == 1
    assert czesci.media[0].mime_type == "application/pdf"
    assert len(czesci.media[0].dane) > 0


def test_pdf_formularz_zawiera_nip_w_tekscie():
    czesci = wczytaj_plik(WNIOSKI_DIR / "W01.pdf")
    cyfry_tekstu = "".join(ch for ch in czesci.tekst if ch.isdigit())
    assert "1234563201" in cyfry_tekstu or "1234563201"[:-1] in cyfry_tekstu


def test_skan_pdf_bez_warstwy_tekstowej():
    czesci = wczytaj_plik(WNIOSKI_DIR / "W07.pdf")
    assert czesci.tekst == ""
    assert len(czesci.media) == 1
    assert czesci.media[0].mime_type == "application/pdf"


def test_zdjecie_jpg():
    czesci = wczytaj_plik(WNIOSKI_DIR / "W09.jpg")
    assert czesci.tekst == ""
    assert len(czesci.media) == 1
    assert czesci.media[0].mime_type == "image/jpeg"
    assert len(czesci.media[0].dane) > 0


def test_eml_bez_zalacznika():
    czesci = wczytaj_plik(WNIOSKI_DIR / "W10.eml")
    assert czesci.media == []
    assert "TRESC WIADOMOSCI E-MAIL" in czesci.tekst
    assert "Sochaczew" in czesci.tekst
    assert "ZALACZNIK" not in czesci.tekst


def test_eml_z_zalacznikiem_ma_tresc_i_zalacznik():
    czesci = wczytaj_plik(WNIOSKI_DIR / "W11.eml")
    assert "TRESC WIADOMOSCI E-MAIL" in czesci.tekst
    assert "ZALACZNIK" in czesci.tekst
    assert len(czesci.media) == 1
    assert czesci.media[0].mime_type == "application/pdf"
    assert len(czesci.media[0].dane) > 0
    # korekta sumy maszyn musi byc widoczna w tresci (ma pierwszenstwo przed zalacznikiem)
    assert "korekta" in czesci.tekst.lower()


def test_nieobslugiwane_rozszerzenie_rzuca_wyjatek():
    with pytest.raises(ValueError):
        wczytaj_plik(ROOT / "wytyczne" / "wytyczne_mienie_v1.yaml")
