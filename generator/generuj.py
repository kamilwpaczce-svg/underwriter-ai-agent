"""CLI: czysci dane/ i generuje od zera wszystkie dokumenty wejsciowe oraz
oczekiwane JSON-y na podstawie generator/przypadki.py i generator/reguly.py.

Uzycie:
    python generator/generuj.py
"""

from __future__ import annotations

import copy
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import przypadki  # noqa: E402
import render  # noqa: E402
from reguly import oblicz_decyzje, wczytaj_wytyczne  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DANE_DIR = ROOT / "dane"
WNIOSKI_DIR = DANE_DIR / "wnioski"
OCZEKIWANE_DIR = DANE_DIR / "oczekiwane"
WYTYCZNE_SCIEZKA = ROOT / "wytyczne" / "wytyczne_mienie_v1.yaml"

EKSTENSJA_WG_FORMATU = {
    "pdf_formularz": ".pdf",
    "skan_pdf": ".pdf",
    "zdjecie_jpg": ".jpg",
    "eml": ".eml",
    "eml_zalacznik": ".eml",
    "pdf_inny": ".pdf",
}

ETYKIETY_KONSTRUKCJI = {
    "niepalna": "Niepalna (murowana / żelbetowa)",
    "drewniana": "Drewniana",
    "plyta_warstwowa_eps": "Płyta warstwowa z rdzeniem EPS",
    "mieszana": "Mieszana",
}


def _log(komunikat: str) -> None:
    # Konsola Windows bywa cp1250 - zero polskich znakow/emoji w logu, zeby
    # uniknac problemow z kodowaniem przy wypisywaniu na stdout.
    print(komunikat)


def wyczysc_dane() -> None:
    """Czysci zawartosc dane/ bez usuwania samych katalogow wnioski/ i
    oczekiwane/. Na tej maszynie Desktop jest pod nadzorem synchronizacji
    OneDrive, ktory potrafi przez chwile trzymac uchwyt na *usuwanych i
    tworzonych na nowo* katalogach (PermissionError z shutil.rmtree). Usuwanie
    tylko plikow (bez rmdir/mkdir katalogow nadrzednych) tego problemu nie ma.

    Etap 10: `dane/polisy.json` (pisany recznie) i `dane/szkody/` (generuje
    `generator/generuj_szkody.py`) nie naleza do tego generatora - zostaja.
    """
    polisy = DANE_DIR / "polisy.json"
    szkody = DANE_DIR / "szkody"

    def _chroniony(sciezka: Path) -> bool:
        return sciezka == polisy or sciezka == szkody or szkody in sciezka.parents

    if DANE_DIR.exists():
        for sciezka in DANE_DIR.rglob("*"):
            if sciezka.is_file() and not _chroniony(sciezka):
                sciezka.unlink()
        # Dodatkowe/przypadkowe podkatalogi (poza wnioski/oczekiwane) sprzatamy,
        # od najglebszych do najplytszych.
        podkatalogi = sorted(
            (
                p
                for p in DANE_DIR.rglob("*")
                if p.is_dir() and p not in (WNIOSKI_DIR, OCZEKIWANE_DIR) and not _chroniony(p)
            ),
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for podkatalog in podkatalogi:
            try:
                podkatalog.rmdir()
            except OSError:
                pass
    WNIOSKI_DIR.mkdir(parents=True, exist_ok=True)
    OCZEKIWANE_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Budowa kontekstu i HTML dla formularza wniosku
# --------------------------------------------------------------------------

def szkody_do_html(szkody, styl_kwota: str) -> str:
    if szkody is None:
        return "<p><em>Brak deklaracji szkodowości w dokumencie.</em></p>"
    if len(szkody) == 0:
        return "<p>Brak szkód zgłoszonych w okresie ostatnich 3 lat.</p>"
    wiersze = []
    for szkoda in szkody:
        kwota_tekst = render.formatuj_kwote(szkoda["kwota"], styl_kwota)
        wiersze.append(
            f"<tr><td>{szkoda['rok']}</td><td>{szkoda['przyczyna']}</td><td>{kwota_tekst}</td></tr>"
        )
    return (
        "<table class=\"szkody\"><tr><th>Rok</th><th>Przyczyna</th><th>Kwota wypłaty</th></tr>"
        + "".join(wiersze)
        + "</table>"
    )


def kontekst_formularza(case: dict, pola: dict) -> dict:
    render_opts = case.get("render", {})
    styl_kwota = render_opts.get("styl_kwota", "zwykly")
    styl_nip = render_opts.get("styl_nip")

    nip = pola.get("nip")
    nip_tekst = render.formatuj_nip(nip, styl_nip) if nip and styl_nip else (nip or "— brak danych —")

    adres = pola["adres"]
    uwagi_tekst = render_opts.get("uwagi_tekst") or (pola.get("uwagi") or "Brak uwag.")

    return {
        "numer_wniosku": render_opts.get("numer_wniosku", "—"),
        "data_wniosku_tekst": render.formatuj_date_pl(pola["data_wniosku"]),
        "nazwa_firmy": pola["nazwa_firmy"],
        "nip_tekst": nip_tekst,
        "ulica": adres["ulica"],
        "kod": adres["kod"],
        "miasto": adres["miasto"],
        "pkd": pola["pkd"],
        "branza": pola["branza"],
        "konstrukcja_tekst": ETYKIETY_KONSTRUKCJI.get(pola["rodzaj_konstrukcji"], pola["rodzaj_konstrukcji"]),
        "rok_budowy": pola["rok_budowy"],
        "tryskacze_tekst": render.tak_nie(pola["tryskacze"]),
        "ssp_tekst": render.tak_nie(pola["ssp"]),
        "strefa_powodziowa_tekst": render.tak_nie(pola["strefa_powodziowa"]),
        "su_budynki_tekst": render.formatuj_kwote(pola["su_budynki"], styl_kwota),
        "su_maszyny_tekst": render.formatuj_kwote(pola["su_maszyny"], styl_kwota),
        "su_zapasy_tekst": render.formatuj_kwote(pola["su_zapasy"], styl_kwota),
        "szkody_html": szkody_do_html(pola["szkody_3_lata"], styl_kwota),
        "okres_od_tekst": render.formatuj_date_pl(pola["okres_od"]),
        "okres_do_tekst": render.formatuj_date_pl(pola["okres_do"]),
        "uwagi": uwagi_tekst,
        "broker": pola["broker"],
    }


def nazwa_szablonu(numer_szablonu: int) -> str:
    return f"formularz_szablon{numer_szablonu}.html"


def html_formularza(case: dict, pola: dict) -> str:
    kontekst = kontekst_formularza(case, pola)
    return render.wypelnij_szablon(nazwa_szablonu(case["szablon"]), kontekst)


# --------------------------------------------------------------------------
# Generowanie poszczegolnych formatow dokumentow
# --------------------------------------------------------------------------

def generuj_pdf_formularz(strona, case: dict, sciezka: Path) -> None:
    html = html_formularza(case, case["pola"])
    render.html_do_pdf(strona, html, sciezka)


def generuj_skan_pdf(strona, case: dict, sciezka: Path, sciezka_png_tymczasowa: Path) -> None:
    html = html_formularza(case, case["pola"])
    render.html_do_png(strona, html, sciezka_png_tymczasowa)
    degr = case.get("degradacja", {})
    render.degraduj_do_skanu_pdf(
        sciezka_png_tymczasowa, sciezka,
        kat_obrotu=degr.get("kat_obrotu", 1.0),
        sigma_szumu=degr.get("sigma_szumu", 18),
        alpha_szumu=degr.get("alpha_szumu", 0.06),
        promien_rozmycia=degr.get("promien_rozmycia", 0.5),
        ziarno=degr.get("ziarno"),
    )


def generuj_zdjecie_jpg(strona, case: dict, sciezka: Path, sciezka_png_tymczasowa: Path) -> None:
    html = html_formularza(case, case["pola"])
    render.html_do_png(strona, html, sciezka_png_tymczasowa)
    degr = case.get("degradacja", {})
    render.degraduj_do_zdjecia_jpg(
        sciezka_png_tymczasowa, sciezka,
        kat_obrotu=degr.get("kat_obrotu", 1.2),
        sigma_szumu=degr.get("sigma_szumu", 14),
        alpha_szumu=degr.get("alpha_szumu", 0.05),
        promien_rozmycia=degr.get("promien_rozmycia", 0.4),
        przesuniecie_perspektywy=degr.get("przesuniecie_perspektywy", 0.03),
        ziarno=degr.get("ziarno"),
    )


def kontekst_email(pola: dict, styl_kwota: str, styl_nip: str) -> dict:
    nip = pola.get("nip")
    nip_tekst = render.formatuj_nip(nip, styl_nip) if nip and styl_nip else (nip or "brak")
    return {
        "nip_tekst": nip_tekst,
        "su_budynki_tekst": render.formatuj_kwote(pola["su_budynki"], styl_kwota),
        "su_maszyny_tekst": render.formatuj_kwote(pola["su_maszyny"], styl_kwota),
        "su_zapasy_tekst": render.formatuj_kwote(pola["su_zapasy"], styl_kwota),
    }


def data_wysylki(data_iso: str) -> datetime.datetime:
    rok, miesiac, dzien = (int(x) for x in data_iso.split("-"))
    strefa = datetime.timezone(datetime.timedelta(hours=1))
    return datetime.datetime(rok, miesiac, dzien, 9, 15, tzinfo=strefa)


def generuj_eml(case: dict, sciezka: Path) -> None:
    pola = case["pola"]
    email = case["email"]
    render_opts = case.get("render", {})
    kontekst = kontekst_email(pola, render_opts.get("styl_kwota", "zwykly"), render_opts.get("styl_nip"))
    tresc = string_template_podstaw(email["tresc_szablon"], kontekst)
    wiadomosc = render.zbuduj_eml(
        nadawca=email["nadawca"],
        odbiorca=email["odbiorca"],
        temat=email["temat"],
        tresc=tresc,
        data_wysylki=data_wysylki(pola["data_wniosku"]),
        zalacznik_bajty=None,
    )
    render.zapisz_eml(wiadomosc, sciezka)


def generuj_eml_z_zalacznikiem(strona, case: dict, sciezka: Path) -> None:
    pola = case["pola"]
    email = case["email"]
    render_opts = case.get("render", {})
    styl_kwota = render_opts.get("styl_kwota", "zwykly")
    styl_nip = render_opts.get("styl_nip")

    # Zalacznik PDF pokazuje DANE PIERWOTNE formularza (przed korekta mailowa).
    pola_zalacznika = copy.deepcopy(pola)
    pola_zalacznika.update(case.get("pola_zalacznika_nadpisania", {}))
    html_zalacznika = html_formularza(case, pola_zalacznika)
    bajty_pdf = render.html_do_pdf_bajty(strona, html_zalacznika)

    kontekst = kontekst_email(pola, styl_kwota, styl_nip)
    kontekst["su_maszyny_poprawiona_tekst"] = render.formatuj_kwote(pola["su_maszyny"], "mln_tys")
    kontekst["su_maszyny_bledna_tekst"] = render.formatuj_kwote(
        case["pola_zalacznika_nadpisania"]["su_maszyny"], "mln_tys"
    )
    tresc = string_template_podstaw(email["tresc_szablon"], kontekst)

    wiadomosc = render.zbuduj_eml(
        nadawca=email["nadawca"],
        odbiorca=email["odbiorca"],
        temat=email["temat"],
        tresc=tresc,
        data_wysylki=data_wysylki(pola["data_wniosku"]),
        zalacznik_bajty=bajty_pdf,
        nazwa_zalacznika=email["zalacznik_nazwa"],
    )
    render.zapisz_eml(wiadomosc, sciezka)


def generuj_newsletter_pdf(strona, case: dict, sciezka: Path) -> None:
    newsletter = case["newsletter"]
    html = render.wypelnij_szablon("newsletter.html", newsletter)
    render.html_do_pdf(strona, html, sciezka)


def string_template_podstaw(tekst: str, kontekst: dict) -> str:
    import string

    return string.Template(tekst).safe_substitute(kontekst)


# --------------------------------------------------------------------------
# Oczekiwane JSON (wg schematu ze specyfikacji)
# --------------------------------------------------------------------------

def zbuduj_oczekiwane_json(case: dict, wytyczne: dict) -> dict:
    if case["typ_dokumentu"] == "INNY":
        return {
            "id": case["id"],
            "typ_dokumentu": "INNY",
            "pola": None,
            "decyzja": "NIE_DOTYCZY",
            "reguly": [],
            "uwagi_dla_ewaluacji": case["uwagi_dla_ewaluacji"],
        }

    pola = case["pola"]
    wynik = oblicz_decyzje(pola, wytyczne)

    if wynik["decyzja"] != case["zamierzona_decyzja"] or wynik["reguly"] != case["zamierzone_reguly"]:
        raise RuntimeError(
            f"Rozjazd silnika z zamierzona decyzja dla {case['id']}: "
            f"silnik={wynik}, zamierzone=decyzja:{case['zamierzona_decyzja']} reguly:{case['zamierzone_reguly']}"
        )

    return {
        "id": case["id"],
        "typ_dokumentu": "WNIOSEK",
        "pola": pola,
        "decyzja": wynik["decyzja"],
        "reguly": wynik["reguly"],
        "uwagi_dla_ewaluacji": case["uwagi_dla_ewaluacji"],
    }


# --------------------------------------------------------------------------
# Glowna petla generowania
# --------------------------------------------------------------------------

def generuj_dokument(strona, case: dict, sciezka: Path, tmp_dir: Path) -> None:
    format_ = case["format"]
    if format_ == "pdf_formularz":
        generuj_pdf_formularz(strona, case, sciezka)
    elif format_ == "skan_pdf":
        generuj_skan_pdf(strona, case, sciezka, tmp_dir / f"{case['id']}_render.png")
    elif format_ == "zdjecie_jpg":
        generuj_zdjecie_jpg(strona, case, sciezka, tmp_dir / f"{case['id']}_render.png")
    elif format_ == "eml":
        generuj_eml(case, sciezka)
    elif format_ == "eml_zalacznik":
        generuj_eml_z_zalacznikiem(strona, case, sciezka)
    elif format_ == "pdf_inny":
        generuj_newsletter_pdf(strona, case, sciezka)
    else:
        raise ValueError(f"Nieznany format dokumentu: {format_}")


def main() -> None:
    _log("Czyszczenie katalogu dane/ ...")
    wyczysc_dane()

    wytyczne = wczytaj_wytyczne(WYTYCZNE_SCIEZKA)

    import tempfile

    manifest = []

    with tempfile.TemporaryDirectory(prefix="underwriter_demo_tmp_") as tmp_dir_nazwa:
        tmp_dir = Path(tmp_dir_nazwa)
        with render.otworz_przegladarke() as strona:
            for case in przypadki.PRZYPADKI:
                case_id = case["id"]
                rozszerzenie = EKSTENSJA_WG_FORMATU[case["format"]]
                sciezka_wzgledna = f"wnioski/{case_id}{rozszerzenie}"
                sciezka_pelna = WNIOSKI_DIR / f"{case_id}{rozszerzenie}"

                _log(f"[{case_id}] generowanie dokumentu ({case['format']}) ...")
                generuj_dokument(strona, case, sciezka_pelna, tmp_dir)

                oczekiwane = zbuduj_oczekiwane_json(case, wytyczne)
                oczekiwane_sciezka = OCZEKIWANE_DIR / f"{case_id}.json"
                with open(oczekiwane_sciezka, "w", encoding="utf-8") as plik:
                    json.dump(oczekiwane, plik, ensure_ascii=False, indent=2)
                    plik.write("\n")

                manifest.append({
                    "id": case_id,
                    "plik": sciezka_wzgledna,
                    "format": case["format"],
                    "pulapka": case["uwagi_dla_ewaluacji"],
                    "decyzja": oczekiwane["decyzja"],
                })

    manifest_sciezka = DANE_DIR / "manifest.json"
    with open(manifest_sciezka, "w", encoding="utf-8") as plik:
        json.dump(manifest, plik, ensure_ascii=False, indent=2)
        plik.write("\n")

    _log(f"Gotowe: {len(manifest)} przypadkow wygenerowanych do {DANE_DIR}")


if __name__ == "__main__":
    main()
