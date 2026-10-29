"""Testy generowania instrukcji tekstowych z wytycznych YAML (agent/instrukcje.py)."""

from __future__ import annotations

from pathlib import Path

from agent.instrukcje import wytyczne_na_instrukcje

ROOT = Path(__file__).resolve().parent.parent
WYTYCZNE_SCIEZKA = ROOT / "wytyczne" / "wytyczne_mienie_v1.yaml"


def _wczytaj_wytyczne_surowe() -> dict:
    import sys

    sys.path.insert(0, str(ROOT / "generator"))
    from reguly import wczytaj_wytyczne

    return wczytaj_wytyczne(WYTYCZNE_SCIEZKA)


def test_kazda_regula_wystepuje_w_instrukcjach():
    tekst = wytyczne_na_instrukcje(WYTYCZNE_SCIEZKA)
    wytyczne = _wczytaj_wytyczne_surowe()
    for regula in wytyczne["reguly"]:
        assert regula["id"] in tekst
        assert regula["skutek"] in tekst


def test_kazdy_prog_liczbowy_wystepuje_w_instrukcjach():
    tekst = wytyczne_na_instrukcje(WYTYCZNE_SCIEZKA)
    wytyczne = _wczytaj_wytyczne_surowe()
    for regula in wytyczne["reguly"]:
        for wartosc in (regula.get("parametry") or {}).values():
            if isinstance(wartosc, (int, float)):
                assert str(wartosc) in tekst, f"Brak progu {wartosc} reguly {regula['id']} w instrukcjach"


def test_pola_wymagane_wystepuja_w_instrukcjach():
    tekst = wytyczne_na_instrukcje(WYTYCZNE_SCIEZKA)
    wytyczne = _wczytaj_wytyczne_surowe()
    for pole in wytyczne["pola_wymagane"]:
        assert pole in tekst


def test_priorytet_decyzji_wystepuje_w_instrukcjach():
    tekst = wytyczne_na_instrukcje(WYTYCZNE_SCIEZKA)
    assert "ODMOWA" in tekst
    assert "UZUPELNIENIE" in tekst
    assert "SKIEROWANIE" in tekst
    assert "AKCEPTACJA" in tekst
