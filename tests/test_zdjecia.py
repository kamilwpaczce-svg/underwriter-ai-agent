"""Etap 23: schemat OcenaZdjecia i zgodnosc zdjecia ze zgloszeniem liczona kodem - zero sieci, zero LLM."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schematy import OcenaZdjecia
from agent.zdjecia import POKREWNE, PROG_PEWNOSCI, kategoria_przyczyny, porownaj

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "generator"))

import przypadki_szkody  # noqa: E402

PRZYPADKI = przypadki_szkody.SZKODY


def _ocena(rodzaj="pozar", dlugotrwalosc="NAGLE", pewnosc=0.9, widac=True, **reszta) -> OcenaZdjecia:
    dane = {
        "czy_widac_szkode": widac,
        "rodzaj_zdarzenia": rodzaj,
        "widoczne_mienie": ["hala"],
        "dlugotrwalosc": dlugotrwalosc,
        "oznaki": [],
        "pewnosc": pewnosc,
        "tekst_na_zdjeciu": False,
    }
    dane.update(reszta)
    return OcenaZdjecia(**dane)


# ---------------------------------------------------------------------------
# Schemat OcenaZdjecia
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wejscie,oczekiwane", [(1.7, 1.0), (-0.3, 0.0), (0.0, 0.0), (1.0, 1.0), (0.42, 0.42)])
def test_pewnosc_przycieta_do_zakresu(wejscie, oczekiwane):
    assert _ocena(pewnosc=wejscie).pewnosc == oczekiwane


def test_pewnosc_nan_to_zero():
    assert _ocena(pewnosc=float("nan")).pewnosc == 0.0


def test_nieznany_rodzaj_to_blad_walidacji():
    with pytest.raises(ValidationError):
        _ocena(rodzaj="trzesienie_ziemi")


def test_nieznana_dlugotrwalosc_to_blad_walidacji():
    with pytest.raises(ValidationError):
        _ocena(dlugotrwalosc="NIGDY")


def test_listy_przyciete_do_pieciu():
    ocena = _ocena(widoczne_mienie=[f"m{i}" for i in range(9)], oznaki=[f"o{i}" for i in range(7)])
    assert ocena.widoczne_mienie == [f"m{i}" for i in range(5)]
    assert ocena.oznaki == [f"o{i}" for i in range(5)]


def test_tekst_modelu_oczyszczony_jak_w_innych_schematach():
    ocena = _ocena(oznaki=["rdza\x00a7 na prowadnicach", "sad\x01za"])
    assert ocena.oznaki == ["rdza§ na prowadnicach", "sadza"]


# ---------------------------------------------------------------------------
# kategoria_przyczyny
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("przypadek", PRZYPADKI, ids=lambda p: p["id"])
def test_kategoria_przyczyny_dla_kazdej_z_12_przyczyn(przypadek):
    assert kategoria_przyczyny(przypadek["pola"]["przyczyna"]) == przypadek["zdjecie"]["rodzaj_zdarzenia"]


@pytest.mark.parametrize("przyczyna", [None, "", "   ", "Szkoda w mieniu firmy", "coś zupełnie innego"])
def test_kategoria_przyczyny_brak_dopasowania_to_none(przyczyna):
    assert kategoria_przyczyny(przyczyna) is None


@pytest.mark.parametrize("przyczyna,oczekiwana", [
    ("pozar hali", "pozar"),
    ("POŻAR HALI", "pozar"),
    ("Korozja po zalaniu wodą", "korozja_zawilgocenie"),          # korozja przed zalanie/woda
    ("Zawilgocenie ścian od wody gruntowej", "korozja_zawilgocenie"),
    ("Nieszczelny dach, woda na maszynach", "korozja_zawilgocenie"),
    ("Woda z tryskaczy po awarii zaworu", "zalanie"),            # tryskacz przed awaria
    ("Uderzenie pioruna w budynek", "przepiecie"),
    ("Przepiecie w instalacji", "przepiecie"),
    ("Awaria silnika, spalone uzwojenie", "awaria_wewnetrzna"),
    ("Silny wiatr uszkodził ogrodzenie", "huragan_wiatr"),
    ("Burza zerwała dach magazynu", "huragan_wiatr"),
    ("Włamanie do biura", "kradziez_wlamanie"),
])
def test_kategoria_przyczyny_kolejnosc_regul(przyczyna, oczekiwana):
    assert kategoria_przyczyny(przyczyna) == oczekiwana


# ---------------------------------------------------------------------------
# porownaj - kazda regula osobno
# ---------------------------------------------------------------------------

def test_prog_pewnosci_ustalony_z_gory():
    assert PROG_PEWNOSCI == 0.6


def test_pokrewne_to_dwie_pary():
    assert POKREWNE == {frozenset({"przepiecie", "awaria_wewnetrzna"}), frozenset({"zalanie", "korozja_zawilgocenie"})}


def test_brak_kategorii_zgloszonej_to_nieustalona():
    wynik = porownaj(_ocena(), None)
    assert wynik["zgodnosc_rodzaju"] == "NIEUSTALONA"
    assert wynik["powody"] == ["przyczyna_nierozpoznana"]


def test_brak_widocznej_szkody_to_nieustalona():
    wynik = porownaj(_ocena(widac=False), "pozar")
    assert wynik["zgodnosc_rodzaju"] == "NIEUSTALONA"
    assert wynik["powody"] == ["brak_widocznej_szkody"]


def test_niska_pewnosc_to_nieustalona():
    wynik = porownaj(_ocena(pewnosc=0.59), "pozar")
    assert wynik["zgodnosc_rodzaju"] == "NIEUSTALONA"
    assert wynik["powody"] == ["niska_pewnosc"]


def test_pewnosc_na_progu_sie_liczy():
    assert porownaj(_ocena(pewnosc=0.6), "pozar")["zgodnosc_rodzaju"] == "ZGODNE"
    assert porownaj(_ocena(pewnosc=0.6), "zalanie")["zgodnosc_rodzaju"] == "NIEZGODNE"


def test_rodzaj_inne_to_nieustalona():
    wynik = porownaj(_ocena(rodzaj="inne"), "pozar")
    assert wynik["zgodnosc_rodzaju"] == "NIEUSTALONA"
    assert wynik["powody"] == ["rodzaj_inne"]


def test_rowne_rodzaje_to_zgodne():
    wynik = porownaj(_ocena(rodzaj="zalanie"), "zalanie")
    assert wynik == {"zgodnosc_rodzaju": "ZGODNE", "sygnal_dlugotrwalosci": False, "powody": []}


def test_rozne_rodzaje_to_niezgodne():
    wynik = porownaj(_ocena(rodzaj="zalanie"), "pozar")
    assert wynik["zgodnosc_rodzaju"] == "NIEZGODNE"
    assert wynik["powody"] == []


@pytest.mark.parametrize("zdjecie,zgloszenie", [
    ("przepiecie", "awaria_wewnetrzna"), ("awaria_wewnetrzna", "przepiecie"),
    ("zalanie", "korozja_zawilgocenie"), ("korozja_zawilgocenie", "zalanie"),
])
def test_kategorie_pokrewne_w_obie_strony_to_nieustalona(zdjecie, zgloszenie):
    wynik = porownaj(_ocena(rodzaj=zdjecie), zgloszenie)
    assert wynik["zgodnosc_rodzaju"] == "NIEUSTALONA"
    assert wynik["powody"] == ["kategorie_pokrewne"]


def test_pierwsza_pasujaca_regula_wygrywa():
    # brak kategorii wygrywa z brakiem szkody i niska pewnoscia
    assert porownaj(_ocena(widac=False, pewnosc=0.1), None)["powody"] == ["przyczyna_nierozpoznana"]
    # brak szkody wygrywa z niska pewnoscia
    assert porownaj(_ocena(widac=False, pewnosc=0.1), "pozar")["powody"] == ["brak_widocznej_szkody"]
    # niska pewnosc wygrywa z `inne`
    assert porownaj(_ocena(rodzaj="inne", pewnosc=0.1), "pozar")["powody"] == ["niska_pewnosc"]


def test_sygnal_dlugotrwalosci_wlacza_sie_przy_nagim_zgloszeniu():
    wynik = porownaj(_ocena(rodzaj="korozja_zawilgocenie", dlugotrwalosc="DLUGOTRWALE"), "zalanie")
    assert wynik["sygnal_dlugotrwalosci"] is True
    assert wynik["zgodnosc_rodzaju"] == "NIEUSTALONA"  # N5: wykrycie idzie przez sygnal, nie przez NIEZGODNE


def test_sygnal_dlugotrwalosci_nie_wlacza_sie_gdy_zgloszono_korozje():
    wynik = porownaj(_ocena(rodzaj="korozja_zawilgocenie", dlugotrwalosc="DLUGOTRWALE"), "korozja_zawilgocenie")
    assert wynik["sygnal_dlugotrwalosci"] is False
    assert wynik["zgodnosc_rodzaju"] == "ZGODNE"


@pytest.mark.parametrize("dlugotrwalosc", ["NAGLE", "NIEOKRESLONE"])
def test_sygnal_dlugotrwalosci_tylko_dla_dlugotrwale(dlugotrwalosc):
    assert porownaj(_ocena(dlugotrwalosc=dlugotrwalosc), "zalanie")["sygnal_dlugotrwalosci"] is False


def test_sygnal_dlugotrwalosci_wymaga_pewnosci_na_progu():
    zdjecie = {"rodzaj": "korozja_zawilgocenie", "dlugotrwalosc": "DLUGOTRWALE"}
    assert porownaj(_ocena(pewnosc=0.59, **zdjecie), "zalanie")["sygnal_dlugotrwalosci"] is False
    assert porownaj(_ocena(pewnosc=0.6, **zdjecie), "zalanie")["sygnal_dlugotrwalosci"] is True


# ---------------------------------------------------------------------------
# Oczekiwane `zdjecie` w przypadkach i JSON-ach
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("przypadek", PRZYPADKI, ids=lambda p: p["id"])
def test_oczekiwane_zdjecie_spojne_z_przyczyna(przypadek):
    zdjecie = przypadek["zdjecie"]
    assert kategoria_przyczyny(przypadek["pola"]["przyczyna"]) == zdjecie["rodzaj_zdarzenia"]
    assert zdjecie["dlugotrwalosc"] == ("DLUGOTRWALE" if przypadek["id"] == "Z05" else "NAGLE")
    # zadna z 12 par zgodnych nie moze dawac NIEZGODNE ani sygnalu przy "idealnym" zdjeciu
    wynik = porownaj(_ocena(rodzaj=zdjecie["rodzaj_zdarzenia"], dlugotrwalosc=zdjecie["dlugotrwalosc"]),
                     kategoria_przyczyny(przypadek["pola"]["przyczyna"]))
    assert wynik["zgodnosc_rodzaju"] == "ZGODNE"
    assert wynik["sygnal_dlugotrwalosci"] is False


@pytest.mark.parametrize("przypadek", PRZYPADKI, ids=lambda p: p["id"])
def test_json_oczekiwany_ma_zdjecie_z_przypadku(przypadek):
    sciezka = ROOT / "dane" / "szkody" / "oczekiwane" / f"{przypadek['id']}.json"
    oczekiwane = json.loads(sciezka.read_text(encoding="utf-8"))
    assert oczekiwane["zdjecie"] == przypadek["zdjecie"]


def test_zmiana_nie_dotyka_pdfow_zgloszen():
    """Etap 23 nie regeneruje PDF-ow (SPEC decyzja 8) - w kopii roboczej brak zmian w dane/szkody/*.pdf."""
    wynik = subprocess.run(
        ["git", "status", "--porcelain", "--", "dane/szkody/*.pdf"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert wynik.returncode == 0
    assert wynik.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Zadanie 3: wczytywanie pliku zdjecia (status zamiast wyjatku w wezle)
# ---------------------------------------------------------------------------

from agent.zdjecia import (  # noqa: E402
    MAKS_ROZMIAR_BAJTOW,
    MAKS_ZDJEC,
    BladOdczytuZdjecia,
    wczytaj_obraz,
)


NAGLOWEK_JPEG = b"\xff\xd8\xff"
NAGLOWEK_PNG = b"\x89PNG\r\n\x1a\n"


def test_stale_wczytywania_wg_spec():
    assert MAKS_ZDJEC == 1
    assert MAKS_ROZMIAR_BAJTOW == 5 * 1024 * 1024


@pytest.mark.parametrize(
    "nazwa, mime",
    [("a.jpg", "image/jpeg"), ("a.jpeg", "image/jpeg"), ("a.png", "image/png"), ("A.JPG", "image/jpeg")],
)
def test_wczytaj_obraz_zwraca_bajty_i_mime(tmp_path, nazwa, mime):
    plik = tmp_path / nazwa
    tresc = (NAGLOWEK_PNG if mime == "image/png" else NAGLOWEK_JPEG) + b"abc"
    plik.write_bytes(tresc)
    assert wczytaj_obraz(str(plik)) == (tresc, mime)


def _powod_bledu(sciezka) -> str:
    with pytest.raises(BladOdczytuZdjecia) as blad:
        wczytaj_obraz(str(sciezka))
    return blad.value.powod


def test_wczytaj_obraz_nieobslugiwany_typ(tmp_path):
    plik = tmp_path / "a.gif"
    plik.write_bytes(b"GIF89a")
    assert _powod_bledu(plik) == "nieobslugiwany_typ"
    assert _powod_bledu(tmp_path / "bez_rozszerzenia") == "nieobslugiwany_typ"


def test_wczytaj_obraz_brak_pliku_i_katalog(tmp_path):
    assert _powod_bledu(tmp_path / "nie_ma.jpg") == "plik_nie_istnieje"
    (tmp_path / "katalog.jpg").mkdir()
    assert _powod_bledu(tmp_path / "katalog.jpg") == "plik_nie_istnieje"


def test_wczytaj_obraz_limit_rozmiaru_jest_wlacznie(tmp_path):
    na_limicie = tmp_path / "limit.jpg"
    na_limicie.write_bytes(NAGLOWEK_JPEG + b"x" * (MAKS_ROZMIAR_BAJTOW - len(NAGLOWEK_JPEG)))
    assert len(wczytaj_obraz(str(na_limicie))[0]) == MAKS_ROZMIAR_BAJTOW
    za_duzy = tmp_path / "duzy.jpg"
    za_duzy.write_bytes(b"x" * (MAKS_ROZMIAR_BAJTOW + 1))
    assert _powod_bledu(za_duzy) == "plik_za_duzy"


def test_wczytaj_obraz_pusty_plik(tmp_path):
    plik = tmp_path / "pusty.png"
    plik.write_bytes(b"")
    assert _powod_bledu(plik) == "plik_pusty"


# --- magic bytes: naglowek pliku musi zgadzac sie z rozszerzeniem (Zadanie 5) ---


@pytest.mark.parametrize(
    "nazwa, tresc",
    [
        ("a.jpg", NAGLOWEK_PNG + b"-dane"),  # PNG pod nazwa .jpg
        ("a.jpeg", b"%PDF-1.4 dane"),  # PDF pod nazwa .jpeg
        ("a.png", NAGLOWEK_JPEG + b"\xe0-dane"),  # JPEG pod nazwa .png
        ("a.jpg", b"GIF89a-dane"),  # GIF pod nazwa .jpg
        ("a.png", b"\x89PNG-bez-reszty-naglowka"),  # niepelny naglowek PNG
        ("a.jpg", b"\xff\xd8"),  # za krotki na JPEG (2 z 3 bajtow)
    ],
)
def test_wczytaj_obraz_niezgodny_naglowek(tmp_path, nazwa, tresc):
    plik = tmp_path / nazwa
    plik.write_bytes(tresc)
    assert _powod_bledu(plik) == "niezgodny_naglowek"


def test_wczytaj_obraz_niezgodny_naglowek_nie_ujawnia_tresci_pliku(tmp_path):
    plik = tmp_path / "tajne.jpg"
    plik.write_bytes(b"TAJNA_TRESC_PLIKU")
    with pytest.raises(BladOdczytuZdjecia) as blad:
        wczytaj_obraz(str(plik))
    assert "TAJNA" not in str(blad.value)
    assert blad.value.powod == "niezgodny_naglowek"


def test_wczytaj_obraz_prawdziwe_zdjecia_z_repo_przechodza_sprawdzenie_naglowka():
    """Stan zdrowy: 12 prawdziwych zdjec JPEG z dane/zdjecia_szkod/ nie sa odrzucane."""
    from pathlib import Path

    katalog = Path(__file__).resolve().parent.parent / "dane" / "zdjecia_szkod"
    zdjecia = sorted(katalog.glob("Z??.jpg"))
    assert len(zdjecia) == 12
    for plik in zdjecia:
        assert wczytaj_obraz(str(plik))[1] == "image/jpeg"


def test_wczytaj_obraz_pusty_i_za_duzy_sa_przed_sprawdzeniem_naglowka(tmp_path):
    pusty = tmp_path / "pusty.jpg"
    pusty.write_bytes(b"")
    assert _powod_bledu(pusty) == "plik_pusty"
    duzy = tmp_path / "duzy.png"
    duzy.write_bytes(b"x" * (MAKS_ROZMIAR_BAJTOW + 1))
    assert _powod_bledu(duzy) == "plik_za_duzy"
