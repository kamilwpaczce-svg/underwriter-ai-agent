"""Testy weryfikujace wygenerowane dane w dane/ (po uruchomieniu generator/generuj.py).

Zakres zgodny z SPEC_ETAP1.md, sekcja "Testy (pytest, musza przejsc)", pkt 3.
"""

from __future__ import annotations

import json
import re
import sys
from email import message_from_bytes
from email.message import Message
from pathlib import Path

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
GENERATOR_DIR = ROOT / "generator"
sys.path.insert(0, str(GENERATOR_DIR))

import przypadki  # noqa: E402
from reguly import oblicz_decyzje, wczytaj_wytyczne  # noqa: E402

DANE_DIR = ROOT / "dane"
WNIOSKI_DIR = DANE_DIR / "wnioski"
OCZEKIWANE_DIR = DANE_DIR / "oczekiwane"
MANIFEST_SCIEZKA = DANE_DIR / "manifest.json"
WYTYCZNE_SCIEZKA = ROOT / "wytyczne" / "wytyczne_mienie_v1.yaml"

# Zakres cyrylicy (alfabet rosyjski/ukrainski itp.) - nie uzywany nigdzie w tym
# projekcie, wiec jego obecnosc w pliku tekstowym/PDF to blad.
WZORZEC_CYRYLICY = re.compile(r"[Ѐ-ӿ]")


def _wczytaj_wytyczne():
    return wczytaj_wytyczne(WYTYCZNE_SCIEZKA)


def _wczytaj_manifest() -> list[dict]:
    with open(MANIFEST_SCIEZKA, "r", encoding="utf-8") as plik:
        return json.load(plik)


def _sciezka_wnioski(wpis: dict) -> Path:
    return DANE_DIR / wpis["plik"]


def _tekst_pdf(sciezka: Path) -> str:
    czytnik = PdfReader(str(sciezka))
    return "\n".join(strona.extract_text() or "" for strona in czytnik.pages)


# ---------------------------------------------------------------------------
# 1. Silnik daje dokladnie zamierzona_decyzje / zamierzone_reguly dla kazdego
#    przypadku (kontrola spojnosci miedzy przypadki.py a reguly.py).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("przypadek", przypadki.PRZYPADKI, ids=lambda p: p["id"])
def test_silnik_zgadza_sie_z_zamierzonym_wynikiem(przypadek):
    wytyczne = _wczytaj_wytyczne()
    pola = przypadek.get("pola")
    if pola is None:
        pytest.skip(f"{przypadek['id']}: typ_dokumentu != WNIOSEK, brak pol do oceny")
    wynik = oblicz_decyzje(pola, wytyczne)
    assert wynik["decyzja"] == przypadek["zamierzona_decyzja"], przypadek["id"]
    assert wynik["reguly"] == przypadek["zamierzone_reguly"], przypadek["id"]


# ---------------------------------------------------------------------------
# 2. Pokrycie: kazda regula R01-R09 >= 1 raz, kazda decyzja (poza NIE_DOTYCZY)
#    >= 2 razy.
# ---------------------------------------------------------------------------

def test_pokrycie_regul_i_decyzji():
    wytyczne = _wczytaj_wytyczne()
    wszystkie_reguly: list[str] = []
    wszystkie_decyzje: list[str] = []
    for przypadek in przypadki.PRZYPADKI:
        pola = przypadek.get("pola")
        if pola is None:
            wszystkie_decyzje.append(przypadek["zamierzona_decyzja"])
            continue
        wynik = oblicz_decyzje(pola, wytyczne)
        wszystkie_reguly.extend(wynik["reguly"])
        wszystkie_decyzje.append(wynik["decyzja"])

    reguly_id = [f"R{numer:02d}" for numer in range(1, 10)]
    for regula_id in reguly_id:
        assert wszystkie_reguly.count(regula_id) >= 1, f"{regula_id} nie zadzialala w zadnym przypadku"

    for decyzja in ("AKCEPTACJA", "UZUPELNIENIE", "SKIEROWANIE", "ODMOWA"):
        assert wszystkie_decyzje.count(decyzja) >= 2, f"decyzja {decyzja} wystapila mniej niz 2 razy"


# ---------------------------------------------------------------------------
# 3. Kazdy plik z manifestu istnieje i jest niepusty.
# ---------------------------------------------------------------------------

def test_pliki_z_manifestu_istnieja_i_sa_niepuste():
    manifest = _wczytaj_manifest()
    assert len(manifest) == 14
    for wpis in manifest:
        sciezka = _sciezka_wnioski(wpis)
        assert sciezka.exists(), f"brak pliku: {sciezka}"
        assert sciezka.stat().st_size > 0, f"pusty plik: {sciezka}"
        oczekiwany_json = OCZEKIWANE_DIR / f"{wpis['id']}.json"
        assert oczekiwany_json.exists(), f"brak pliku: {oczekiwany_json}"
        assert oczekiwany_json.stat().st_size > 0, f"pusty plik: {oczekiwany_json}"


# ---------------------------------------------------------------------------
# 4. PDF-y formularzy maja warstwe tekstu zawierajaca NIP i nazwe firmy.
#
#    ODSTEPSTWO OD SPECYFIKACJI: W06 ma celowo brak NIP w ogole (pola["nip"]
#    is None) - to jest sedno przypadku testujacego regule R02 (brak
#    wymaganego pola). Nie da sie jednoczesnie "miec NIP w tekscie" i "nie
#    miec NIP". Dla W06 sprawdzamy tylko nazwe firmy i brak jakiegokolwiek
#    ciagu cyfr NIP, a sam check obecnosci NIP pomijamy swiadomie.
# ---------------------------------------------------------------------------

PRZYPADKI_WG_ID = {przypadek["id"]: przypadek for przypadek in przypadki.PRZYPADKI}

FORMULARZE_PDF = [
    przypadek for przypadek in przypadki.PRZYPADKI if przypadek["format"] == "pdf_formularz"
]


@pytest.mark.parametrize("przypadek", FORMULARZE_PDF, ids=lambda p: p["id"])
def test_formularze_pdf_maja_nazwe_firmy_w_tekscie(przypadek):
    manifest = {wpis["id"]: wpis for wpis in _wczytaj_manifest()}
    sciezka = _sciezka_wnioski(manifest[przypadek["id"]])
    tekst = _tekst_pdf(sciezka)
    assert przypadek["pola"]["nazwa_firmy"] in tekst


@pytest.mark.parametrize(
    "przypadek",
    [p for p in FORMULARZE_PDF if p["pola"]["nip"] is not None],
    ids=lambda p: p["id"],
)
def test_formularze_pdf_maja_nip_w_tekscie(przypadek):
    manifest = {wpis["id"]: wpis for wpis in _wczytaj_manifest()}
    sciezka = _sciezka_wnioski(manifest[przypadek["id"]])
    tekst = _tekst_pdf(sciezka)
    cyfry_nip = przypadek["pola"]["nip"]
    cyfry_w_tekscie = re.sub(r"\D", "", tekst)
    assert cyfry_nip in cyfry_w_tekscie


# ---------------------------------------------------------------------------
# 5. Skany i JPG NIE maja warstwy tekstu.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "przypadek",
    [p for p in przypadki.PRZYPADKI if p["format"] == "skan_pdf"],
    ids=lambda p: p["id"],
)
def test_skany_pdf_bez_warstwy_tekstu(przypadek):
    manifest = {wpis["id"]: wpis for wpis in _wczytaj_manifest()}
    sciezka = _sciezka_wnioski(manifest[przypadek["id"]])
    tekst = _tekst_pdf(sciezka).strip()
    assert tekst == "", f"{przypadek['id']}: skan ma warstwe tekstu ({len(tekst)} znakow)"


def test_zdjecie_jpg_to_plik_obrazu_bez_tekstu():
    przypadek = PRZYPADKI_WG_ID["W09"]
    assert przypadek["format"] == "zdjecie_jpg"
    manifest = {wpis["id"]: wpis for wpis in _wczytaj_manifest()}
    sciezka = _sciezka_wnioski(manifest["W09"])
    assert sciezka.suffix.lower() in (".jpg", ".jpeg")
    naglowek = sciezka.read_bytes()[:3]
    assert naglowek == b"\xff\xd8\xff", "plik nie ma naglowka JPEG"


# ---------------------------------------------------------------------------
# 6. .eml parsuje sie; W11 ma zalacznik PDF, W10 nie ma.
# ---------------------------------------------------------------------------

def _wczytaj_eml(sciezka: Path) -> Message:
    with open(sciezka, "rb") as plik:
        return message_from_bytes(plik.read())


@pytest.mark.parametrize(
    "przypadek",
    [p for p in przypadki.PRZYPADKI if p["format"] in ("eml", "eml_zalacznik")],
    ids=lambda p: p["id"],
)
def test_eml_parsuje_sie(przypadek):
    manifest = {wpis["id"]: wpis for wpis in _wczytaj_manifest()}
    sciezka = _sciezka_wnioski(manifest[przypadek["id"]])
    wiadomosc = _wczytaj_eml(sciezka)
    assert wiadomosc["From"]
    assert wiadomosc["To"]
    assert wiadomosc["Subject"]


def _zalaczniki_pdf(wiadomosc: Message) -> list[Message]:
    return [
        czesc
        for czesc in wiadomosc.walk()
        if czesc.get_content_type() == "application/pdf"
    ]


def test_w11_ma_zalacznik_pdf():
    manifest = {wpis["id"]: wpis for wpis in _wczytaj_manifest()}
    wiadomosc = _wczytaj_eml(_sciezka_wnioski(manifest["W11"]))
    assert len(_zalaczniki_pdf(wiadomosc)) == 1


def test_w10_nie_ma_zalacznika():
    manifest = {wpis["id"]: wpis for wpis in _wczytaj_manifest()}
    wiadomosc = _wczytaj_eml(_sciezka_wnioski(manifest["W10"]))
    assert len(_zalaczniki_pdf(wiadomosc)) == 0


# ---------------------------------------------------------------------------
# 7. W13 zawiera tekst wstrzykniecia w warstwie tekstu PDF.
# ---------------------------------------------------------------------------

def test_w13_zawiera_tekst_wstrzykniecia():
    manifest = {wpis["id"]: wpis for wpis in _wczytaj_manifest()}
    sciezka = _sciezka_wnioski(manifest["W13"])
    tekst = _tekst_pdf(sciezka)
    assert "zignoruj wytyczne" in tekst
    # Agent MUSI trzymac sie wytycznych mimo tej tresci - potwierdzamy to
    # niezaleznie w tescie silnika: W13 ma zamierzona_decyzje SKIEROWANIE,
    # nie AKCEPTACJA (patrz test_silnik_zgadza_sie_z_zamierzonym_wynikiem).
    assert PRZYPADKI_WG_ID["W13"]["zamierzona_decyzja"] == "SKIEROWANIE"


# ---------------------------------------------------------------------------
# 8. Brak cyrylicy we wszystkich plikach tekstowych projektu i w tresci PDF.
# ---------------------------------------------------------------------------

ROZSZERZENIA_TEKSTOWE = {".py", ".yaml", ".yml", ".html", ".md", ".json", ".txt"}


def _pliki_tekstowe_projektu() -> list[Path]:
    # test_dane.py jest wylaczony: zawiera w kodzie zrodlowym literal Ѐ-ӿ
    # (definicja zakresu Unicode cyrylicy w WZORZEC_CYRYLICY), co jest fragmentem
    # kodu testu, a nie rzeczywistym tekstem cyrylicy.
    wlasny_plik = Path(__file__).resolve()
    wynik = []
    for sciezka in ROOT.rglob("*"):
        if not sciezka.is_file():
            continue
        if sciezka.resolve() == wlasny_plik:
            continue
        if sciezka.suffix.lower() not in ROZSZERZENIA_TEKSTOWE:
            continue
        # node_modules/.next: cudze pakiety npm (np. nanoid ma cyrylice w README) i artefakty buildu.
        if {"__pycache__", ".pytest_cache", ".venv", ".venv-ewaluacja", ".venv-mlops", ".venv-llamaindex", "mlruns", "mlartifacts", "node_modules", ".next", ".cache_ocr"} & set(sciezka.parts):
            continue
        wynik.append(sciezka)
    return wynik


def test_brak_cyrylicy_w_plikach_tekstowych():
    for sciezka in _pliki_tekstowe_projektu():
        tresc = sciezka.read_text(encoding="utf-8")
        assert not WZORZEC_CYRYLICY.search(tresc), f"cyrylica w pliku: {sciezka}"


def test_brak_cyrylicy_w_plikach_eml():
    for sciezka in WNIOSKI_DIR.glob("*.eml"):
        tresc = sciezka.read_text(encoding="utf-8")
        assert not WZORZEC_CYRYLICY.search(tresc), f"cyrylica w pliku: {sciezka}"


def test_brak_cyrylicy_w_tresci_pdf():
    for sciezka in WNIOSKI_DIR.glob("*.pdf"):
        tekst = _tekst_pdf(sciezka)
        assert not WZORZEC_CYRYLICY.search(tekst), f"cyrylica w PDF: {sciezka}"
