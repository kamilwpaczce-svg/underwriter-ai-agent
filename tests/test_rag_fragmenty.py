"""Podzial OWU na fragmenty (1 ustep = 1 fragment) - SPEC_ETAP10.md, sekcja Testy."""

from __future__ import annotations

import re
from collections import Counter

from rag.fragmenty import (
    SCIEZKA_OWU,
    Fragment,
    parsuj_liczbe,
    parsuj_odwolanie,
    podziel_owu,
    wersja_owu,
)

USTEPY_NA_PARAGRAF = {1: 3, 2: 10, 3: 3, 4: 8, 5: 3, 6: 10, 7: 3, 8: 4, 9: 6, 10: 3, 11: 3, 12: 4, 13: 3, 14: 3}


def test_podzial_owu_liczba_fragmentow_i_unikalne_id():
    fragmenty = podziel_owu()
    assert len(fragmenty) == 66
    assert len({f.id for f in fragmenty}) == 66


def test_kazdy_fragment_ma_paragraf_ustep_i_tytul_w_tresci():
    for f in podziel_owu():
        assert isinstance(f, Fragment)
        assert f.paragraf >= 1 and f.ustep >= 1
        assert f.id == f"p{f.paragraf}u{f.ustep}"
        assert f.tresc.startswith(f"§ {f.paragraf}. {f.tytul}\nust. {f.ustep}. ")
        assert len(f.tresc) > len(f.tytul) + 20


def test_ustepy_na_paragraf_zgodne_ze_struktura_owu():
    licznik = Counter(f.paragraf for f in podziel_owu())
    assert dict(licznik) == USTEPY_NA_PARAGRAF


def test_wylaczen_jest_co_najmniej_osiem():
    wylaczenia = [f for f in podziel_owu() if f.tytul == "Wyłączenia odpowiedzialności"]
    assert len(wylaczenia) >= 8


def test_linia_kontynuacji_dokleja_sie_do_ustepu_i_tekst_przed_paragrafem_jest_pomijany(tmp_path):
    plik = tmp_path / "owu.md"
    plik.write_text(
        "# Tytul\n\n1. To nie jest ustep - przed pierwszym paragrafem.\n\n"
        "## § 1. Pierwszy\n\n1. Poczatek ustepu\nciag dalszy ustepu.\n2. Drugi ustep.\n\n"
        "## § 2. Drugi\n\n1. Jedyny.\n",
        encoding="utf-8",
    )
    fragmenty = podziel_owu(plik)
    assert [f.id for f in fragmenty] == ["p1u1", "p1u2", "p2u1"]
    assert fragmenty[0].tresc == "§ 1. Pierwszy\nust. 1. Poczatek ustepu ciag dalszy ustepu."
    assert fragmenty[2].tytul == "Drugi"


def test_wersja_owu_to_12_znakow_hex_i_zmienia_sie_z_trescia(tmp_path):
    assert re.fullmatch(r"[0-9a-f]{12}", wersja_owu())
    plik = tmp_path / "owu.md"
    plik.write_text("## § 1. A\n\n1. x\n", encoding="utf-8")
    pierwsza = wersja_owu(plik)
    plik.write_text("## § 1. A\n\n1. y\n", encoding="utf-8")
    assert wersja_owu(plik) != pierwsza


def test_parsuj_liczbe_i_odwolanie():
    assert parsuj_liczbe("§ 6") == 6
    assert parsuj_liczbe("ust. 4") == 4
    assert parsuj_liczbe("brak") is None
    assert parsuj_liczbe(None) is None
    assert parsuj_odwolanie("§4 ust. 1") == (4, 1)
    assert parsuj_odwolanie("§ 10 ust. 2") == (10, 2)
    assert parsuj_odwolanie("§ 6") is None
    assert parsuj_odwolanie(None) is None


def test_plik_owu_istnieje_w_repo():
    assert SCIEZKA_OWU.exists()
