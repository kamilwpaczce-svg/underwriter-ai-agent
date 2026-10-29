"""Etap 19a: przedzial Wilsona, dokladny McNemar, stabilnosc biegow, porownanie konfiguracji."""
import json

import pytest

from ewaluacja.statystyka import (
    main,
    mcnemar_dokladny,
    porownaj,
    przedzial_wilsona,
    stabilnosc,
    wczytaj_wyniki,
)


# Newcombe (1998), Statistics in Medicine 17:857-872, tab. I, metoda 3 (score bez korekty)
@pytest.mark.parametrize("trafienia,n,dol,gora", [
    (81, 263, 0.2553, 0.3662),
    (15, 148, 0.0624, 0.1605),
    (0, 20, 0.0, 0.1611),
    (1, 29, 0.0061, 0.1718),
])
def test_wilson_wartosci_z_literatury(trafienia, n, dol, gora):
    d, g = przedzial_wilsona(trafienia, n)
    assert d == pytest.approx(dol, abs=1e-4)
    assert g == pytest.approx(gora, abs=1e-4)


def test_wilson_w_granicach_0_1_przy_pelnym_trafieniu():
    d, g = przedzial_wilsona(14, 14)
    assert 0.0 <= d < 1.0
    assert g == pytest.approx(1.0)


@pytest.mark.parametrize("trafienia,n", [(0, 0), (5, 4), (-1, 3)])
def test_wilson_bledne_wejscie(trafienia, n):
    with pytest.raises(ValueError):
        przedzial_wilsona(trafienia, n)


@pytest.mark.parametrize("b,c,p", [
    (0, 5, 0.0625),
    (0, 6, 0.03125),
    (6, 0, 0.03125),
    (1, 1, 1.0),
    (3, 0, 0.25),
    (0, 0, 1.0),
])
def test_mcnemar_dokladny(b, c, p):
    assert mcnemar_dokladny(b, c) == pytest.approx(p)


def test_mcnemar_ujemne_liczby():
    with pytest.raises(ValueError):
        mcnemar_dokladny(-1, 2)


def _zapisz(sciezka, wiersze, klucz="przypadki"):
    sciezka.write_text(json.dumps({klucz: wiersze}), encoding="utf-8")
    return sciezka


def test_wczytaj_wyniki_none_to_porazka_z_ostrzezeniem(tmp_path, capsys):
    plik = _zapisz(tmp_path / "a.json", [
        {"id": "W01", "decyzja_llm_ok": True},
        {"id": "W02", "decyzja_llm_ok": None},
    ])
    wyniki = wczytaj_wyniki(plik, "decyzja_llm_ok")
    assert wyniki == {"W01": True, "W02": False}
    assert "W02" in capsys.readouterr().err


def test_wczytaj_wyniki_brak_pola_to_blad(tmp_path):
    plik = _zapisz(tmp_path / "a.json", [{"id": "W01"}])
    with pytest.raises(KeyError):
        wczytaj_wyniki(plik, "decyzja_llm_ok")


def test_stabilnosc_wiekszosc_i_niestabilne():
    biegi = [
        {"A": True, "B": True, "C": False},
        {"A": True, "B": False, "C": False},
        {"A": True, "B": True, "C": False},
    ]
    s = stabilnosc(biegi)
    assert s["n"] == 3
    assert s["trafienia_biegow"] == [2, 1, 2]
    assert s["niestabilne"] == {"B": 2}
    assert s["wiekszosc"] == {"A": True, "B": True, "C": False}


def test_stabilnosc_rozne_zbiory_id_to_blad():
    with pytest.raises(ValueError):
        stabilnosc([{"A": True}, {"B": True}])


def test_porownaj_liczy_tylko_wspolne_i_ostrzega(capsys):
    a = {"A": True, "B": True, "C": False, "X": True}
    b = {"A": True, "B": False, "C": True, "Y": False}
    w = porownaj(a, b)
    assert w["n"] == 3
    assert (w["b"], w["c"]) == (1, 1)
    assert w["p"] == pytest.approx(1.0)
    err = capsys.readouterr().err
    assert "X" in err and "Y" in err


def test_cli_porownaj_format_a25(tmp_path, capsys):
    a = _zapisz(tmp_path / "a.json", [{"id": f"P{i}", "trafione": True} for i in range(6)], "pytania")
    b = _zapisz(tmp_path / "b.json", [{"id": f"P{i}", "trafione": False} for i in range(6)], "pytania")
    kod = main(["porownaj", str(a), str(b), "--pole", "trafione", "--klucz-listy", "pytania"])
    assert kod == 0
    out = capsys.readouterr().out
    assert "0.0312" in out  # 6 par niezgodnych w jedna strone


def test_cli_stabilnosc(tmp_path, capsys):
    pliki = [
        _zapisz(tmp_path / f"b{i}.json", [{"id": "W01", "ok": True}, {"id": "W02", "ok": i % 2 == 0}])
        for i in range(3)
    ]
    kod = main(["stabilnosc", *map(str, pliki), "--pole", "ok"])
    assert kod == 0
    out = capsys.readouterr().out
    assert "W02" in out
