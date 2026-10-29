"""Renderowanie dokumentow: HTML -> PDF / PNG (Playwright), degradacja do
"skanu" / "zdjecia" (Pillow), budowa wiadomosci .eml."""

from __future__ import annotations

import random
import string
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter

SZABLONY_DIR = Path(__file__).resolve().parent / "szablony"


# --------------------------------------------------------------------------
# Formatowanie wartosci do wyswietlenia w dokumentach (rozne zapisy)
# --------------------------------------------------------------------------

def formatuj_kwote(kwota: int, styl: str) -> str:
    """Formatuje kwote PLN w jednym z kilku zapisow uzywanych przez brokerow."""
    if styl == "spacje":
        # 1 800 000,00 zl
        calosc = f"{kwota:,}".replace(",", " ")
        return f"{calosc},00 zł"
    if styl == "kropki":
        # 1.800.000
        return f"{kwota:,}".replace(",", ".")
    if styl == "zwykly":
        return f"{kwota} PLN"
    if styl == "mln_tys":
        if kwota >= 1_000_000:
            wartosc = kwota / 1_000_000
            tekst = f"{wartosc:g}".replace(".", ",")
            return f"{tekst} mln PLN"
        if kwota >= 1_000:
            wartosc = kwota / 1_000
            tekst = f"{wartosc:g}".replace(".", ",")
            return f"{tekst} tys. PLN"
        return f"{kwota} PLN"
    raise ValueError(f"Nieznany styl kwoty: {styl}")


def formatuj_nip(nip: str, styl: str) -> str:
    """Formatuje 10-cyfrowy NIP w jednym z zapisow uzywanych w dokumentach."""
    if len(nip) != 10:
        raise ValueError("NIP do formatowania musi miec 10 cyfr")
    if styl == "dashes":
        return f"{nip[0:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:10]}"
    if styl == "pl":
        return f"PL{nip}"
    if styl == "zwykly":
        return nip
    raise ValueError(f"Nieznany styl NIP: {styl}")


def formatuj_date_pl(data_iso: str) -> str:
    """'2026-11-01' -> '01.11.2026'."""
    rok, miesiac, dzien = data_iso.split("-")
    return f"{dzien}.{miesiac}.{rok}"


def tak_nie(wartosc: bool) -> str:
    return "TAK" if wartosc else "NIE"


# --------------------------------------------------------------------------
# Wypelnianie szablonow HTML (string.Template, placeholdery $nazwa)
# --------------------------------------------------------------------------

def wczytaj_szablon(nazwa_pliku: str) -> str:
    sciezka = SZABLONY_DIR / nazwa_pliku
    return sciezka.read_text(encoding="utf-8")


def wypelnij_szablon(nazwa_pliku: str, kontekst: dict[str, Any]) -> str:
    tekst = wczytaj_szablon(nazwa_pliku)
    return string.Template(tekst).safe_substitute(kontekst)


# --------------------------------------------------------------------------
# Playwright: HTML -> PDF / PNG
# --------------------------------------------------------------------------

@contextmanager
def otworz_przegladarke():
    """Context manager: uruchamia Chromium (Playwright) i zwraca obiekt strony."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        przegladarka = pw.chromium.launch()
        strona = przegladarka.new_page()
        try:
            yield strona
        finally:
            przegladarka.close()


def html_do_pdf(strona, html: str, sciezka_pdf: Path) -> None:
    sciezka_pdf.parent.mkdir(parents=True, exist_ok=True)
    strona.set_content(html, wait_until="load")
    strona.pdf(path=str(sciezka_pdf), format="A4", print_background=True)


def html_do_pdf_bajty(strona, html: str) -> bytes:
    """Jak html_do_pdf, ale zwraca bajty PDF bez zapisu na dysk (np. zalacznik)."""
    strona.set_content(html, wait_until="load")
    return strona.pdf(format="A4", print_background=True)


def html_do_png(strona, html: str, sciezka_png: Path, szerokosc: int = 900) -> None:
    sciezka_png.parent.mkdir(parents=True, exist_ok=True)
    strona.set_viewport_size({"width": szerokosc, "height": 1200})
    strona.set_content(html, wait_until="load")
    strona.screenshot(path=str(sciezka_png), full_page=True)


# --------------------------------------------------------------------------
# Pillow: degradacja PNG -> "skan" (PDF bez warstwy tekstu) / "zdjecie" (JPG)
# --------------------------------------------------------------------------

def _obroc_i_wypelnij_bialym(obraz: Image.Image, kat: float) -> Image.Image:
    return obraz.rotate(kat, expand=True, fillcolor=255, resample=Image.BICUBIC)


def _dodaj_szum(obraz_l: Image.Image, sigma: float, alpha: float) -> Image.Image:
    szum = Image.effect_noise(obraz_l.size, sigma)
    return Image.blend(obraz_l, szum, alpha)


def degraduj_do_skanu_pdf(sciezka_png: Path, sciezka_pdf: Path, kat_obrotu: float = 1.0,
                           sigma_szumu: float = 18, alpha_szumu: float = 0.06,
                           promien_rozmycia: float = 0.5, ziarno: int | None = None) -> None:
    """PNG (render formularza) -> obraz 'ze skanera' zapisany jako PDF bez
    warstwy tekstu (sam obraz)."""
    if ziarno is not None:
        random.seed(ziarno)
    obraz = Image.open(sciezka_png).convert("L")
    obraz = _obroc_i_wypelnij_bialym(obraz, kat_obrotu)
    obraz = _dodaj_szum(obraz, sigma_szumu, alpha_szumu)
    obraz = obraz.filter(ImageFilter.GaussianBlur(radius=promien_rozmycia))
    sciezka_pdf.parent.mkdir(parents=True, exist_ok=True)
    obraz.convert("RGB").save(sciezka_pdf, "PDF", resolution=150.0)


def _gradient_cienia(rozmiar: tuple[int, int], strona: str = "lewa", sila: int = 70) -> Image.Image:
    szerokosc, wysokosc = rozmiar
    gradient = Image.new("L", (szerokosc, 1))
    for x in range(szerokosc):
        udzial = x / max(szerokosc - 1, 1)
        if strona == "prawa":
            udzial = 1 - udzial
        wartosc = 255 - int(sila * (1 - udzial))
        gradient.putpixel((x, 0), max(0, min(255, wartosc)))
    return gradient.resize((szerokosc, wysokosc))


def degraduj_do_zdjecia_jpg(sciezka_png: Path, sciezka_jpg: Path, kat_obrotu: float = 1.2,
                             sigma_szumu: float = 14, alpha_szumu: float = 0.05,
                             promien_rozmycia: float = 0.4, przesuniecie_perspektywy: float = 0.03,
                             ziarno: int | None = None) -> None:
    """PNG -> symulacja zdjecia telefonem: jak skan + perspektywa + cien, JPG."""
    if ziarno is not None:
        random.seed(ziarno)
    obraz = Image.open(sciezka_png).convert("L")
    obraz = _obroc_i_wypelnij_bialym(obraz, kat_obrotu)
    obraz = _dodaj_szum(obraz, sigma_szumu, alpha_szumu)
    obraz = obraz.filter(ImageFilter.GaussianBlur(radius=promien_rozmycia))

    szerokosc, wysokosc = obraz.size
    przes_x = int(szerokosc * przesuniecie_perspektywy)
    przes_y = int(wysokosc * przesuniecie_perspektywy)
    # Rogi docelowe (QUAD) lekko przesuniete, zeby symulowac fotografowanie
    # pod katem: gorna krawedz wezsza niz dolna.
    quad = (
        przes_x, przes_y,            # lewy-gorny
        0, wysokosc,                  # lewy-dolny
        szerokosc, wysokosc,          # prawy-dolny
        szerokosc - przes_x, przes_y,  # prawy-gorny
    )
    obraz = obraz.transform((szerokosc, wysokosc), Image.QUAD, quad, resample=Image.BICUBIC, fillcolor=255)

    cien = _gradient_cienia(obraz.size, strona="lewa", sila=60)
    obraz = ImageChops.multiply(obraz, cien)

    sciezka_jpg.parent.mkdir(parents=True, exist_ok=True)
    obraz.convert("RGB").save(sciezka_jpg, "JPEG", quality=85)


# --------------------------------------------------------------------------
# Budowa wiadomosci .eml
# --------------------------------------------------------------------------

def zbuduj_eml(nadawca: str, odbiorca: str, temat: str, tresc: str, data_wysylki,
               zalacznik_bajty: bytes | None = None, nazwa_zalacznika: str | None = None) -> EmailMessage:
    wiadomosc = EmailMessage()
    wiadomosc["From"] = nadawca
    wiadomosc["To"] = odbiorca
    wiadomosc["Subject"] = temat
    wiadomosc["Date"] = format_datetime(data_wysylki)
    wiadomosc.set_content(tresc, charset="utf-8")
    if zalacznik_bajty is not None:
        wiadomosc.add_attachment(
            zalacznik_bajty,
            maintype="application",
            subtype="pdf",
            filename=nazwa_zalacznika or "zalacznik.pdf",
        )
    return wiadomosc


def zapisz_eml(wiadomosc: EmailMessage, sciezka: Path) -> None:
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    with open(sciezka, "wb") as plik:
        plik.write(wiadomosc.as_bytes())
