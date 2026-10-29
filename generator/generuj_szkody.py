"""CLI: generuje 12 fikcyjnych zgloszen szkod (Etap 10) do dane/szkody/.

    python generator/generuj_szkody.py

Tworzy dane/szkody/Z01..Z12.pdf, dane/szkody/oczekiwane/Z01..Z12.json i dane/szkody/manifest.json.
Nie rusza dane/wnioski, dane/oczekiwane ani dane/polisy.json. Oczekiwana decyzja kazdego
przypadku jest sprawdzana tymi samymi funkcjami co w grafie (`sprawdz_polise`,
`ustal_decyzje_szkody`) - rozjazd przerywa generowanie, jak w generator/generuj.py.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _sciezka in (ROOT, Path(__file__).resolve().parent):
    if str(_sciezka) not in sys.path:
        sys.path.insert(0, str(_sciezka))

import przypadki_szkody  # noqa: E402
import render  # noqa: E402

from agent.decyzje_szkody import ustal_decyzje_szkody  # noqa: E402
from agent.polisy import sprawdz_polise, wczytaj_polisy  # noqa: E402
from rag.fragmenty import podziel_owu, parsuj_odwolanie  # noqa: E402

SZKODY_DIR = ROOT / "dane" / "szkody"
OCZEKIWANE_SZKODY_DIR = SZKODY_DIR / "oczekiwane"
NAZWA_SZABLONU = "zgloszenie_szkody.html"
RODZAJ_MIENIA_TEKST = {
    "budynek": "budynki i budowle",
    "maszyny": "maszyny i urządzenia",
    "zapasy": "zapasy (towary i surowce)",
}


def _cytat_wzorcowy(paragraf_oczekiwany: str) -> dict:
    paragraf, ustep = parsuj_odwolanie(paragraf_oczekiwany)
    return {"paragraf": f"§ {paragraf}", "ustep": str(ustep), "uzasadnienie": "wzorzec"}


def zbuduj_oczekiwane_szkody(case: dict, polisy: dict[str, dict], fragmenty: list[dict]) -> dict:
    """Oczekiwany JSON przypadku; RuntimeError, gdy decyzja z przypadki_szkody.py nie wynika
    z regul grafu albo oczekiwany paragraf nie istnieje w OWU."""
    dostepne = {(f["paragraf"], f["ustep"]) for f in fragmenty}
    for odwolanie in case["paragrafy_oczekiwane"]:
        if parsuj_odwolanie(odwolanie) not in dostepne:
            raise RuntimeError(f"{case['id']}: paragraf {odwolanie} nie istnieje w OWU.")

    wynik_polisy = sprawdz_polise(case["pola"], polisy)
    stan: dict = {"podejrzane_instrukcje": case["podejrzane"], "wynik_polisy": wynik_polisy, "fragmenty_owu": fragmenty}
    if case["decyzja_llm"]:
        cytaty = [_cytat_wzorcowy(case["paragrafy_oczekiwane"][0])] if case["paragrafy_oczekiwane"] else []
        stan["ocena_pokrycia"] = {
            "decyzja": case["decyzja_llm"],
            "cytaty": cytaty,
            "brakujace_dokumenty": case["brakujace_dokumenty"],
            "dodatkowe_zapytanie": None,
        }
    decyzja, powody = ustal_decyzje_szkody(stan)
    if decyzja != case["decyzja"]:
        raise RuntimeError(f"Rozjazd decyzji dla {case['id']}: reguly={decyzja} {powody}, zamierzona={case['decyzja']}")

    oczekiwany = {
        "id": case["id"],
        "typ_dokumentu": "SZKODA",
        "pola": case["pola"],
        "podejrzane": case["podejrzane"],
        "decyzja_llm": case["decyzja_llm"],
        "decyzja": case["decyzja"],
        "kody_polisy": wynik_polisy["kody"],
        "paragrafy_oczekiwane": case["paragrafy_oczekiwane"],
        "brakujace_dokumenty": case["brakujace_dokumenty"],
        "zapytanie_dodatkowe": case["zapytanie_dodatkowe"],
        "uwagi_dla_ewaluacji": case["uwagi_dla_ewaluacji"],
    }
    if case.get("ground_truth_sedziego"):  # Etap 14: opcjonalny, tylko tam, gdzie domyslny szablon nie wystarcza
        oczekiwany["ground_truth_sedziego"] = case["ground_truth_sedziego"]
    if case.get("zdjecie"):  # Etap 23: oczekiwany wynik analizy zdjecia (vision) dla tego przypadku
        oczekiwany["zdjecie"] = case["zdjecie"]
    return oczekiwany


def kontekst_zgloszenia(case: dict) -> dict:
    pola = case["pola"]
    miejsce = pola["miejsce"]
    kontekst = {
        "numer_zgloszenia": f"SZK/2026/{case['id']}",
        "data_zgloszenia_tekst": render.formatuj_date_pl(pola["data_zgloszenia"]),
        "ubezpieczony": pola["ubezpieczony"],
        "nip": render.formatuj_nip(pola["nip"], "dashes"),
        "nr_polisy": pola["nr_polisy"],
        "data_zdarzenia_tekst": render.formatuj_date_pl(pola["data_zdarzenia"]),
        "adres": f"{miejsce['ulica']}, {miejsce['kod']} {miejsce['miasto']}",
        "rodzaj_mienia_tekst": RODZAJ_MIENIA_TEKST[pola["rodzaj_mienia"]],
        "kwota_tekst": render.formatuj_kwote(pola["szacowana_kwota"], "spacje"),
        "przyczyna": pola["przyczyna"],
        "okolicznosci": pola["okolicznosci"],
        "zalaczniki": "\n".join(f"- {z}" for z in pola["zalaczniki"]),
        "zglaszajacy": pola["ubezpieczony"],
    }
    return {klucz: html.escape(wartosc) for klucz, wartosc in kontekst.items()}


def html_zgloszenia(case: dict) -> str:
    return render.wypelnij_szablon(NAZWA_SZABLONU, kontekst_zgloszenia(case))


def wyczysc_szkody() -> None:
    """Usuwa tylko pliki tego generatora (bez rmdir - patrz uwaga o OneDrive w generuj.py)."""
    for wzorzec, katalog in (("Z*.pdf", SZKODY_DIR), ("Z*.json", OCZEKIWANE_SZKODY_DIR)):
        if katalog.exists():
            for sciezka in katalog.glob(wzorzec):
                sciezka.unlink()
    (SZKODY_DIR / "manifest.json").unlink(missing_ok=True)
    OCZEKIWANE_SZKODY_DIR.mkdir(parents=True, exist_ok=True)


def _zapisz_json(sciezka: Path, dane) -> None:
    with open(sciezka, "w", encoding="utf-8") as plik:
        json.dump(dane, plik, ensure_ascii=False, indent=2)
        plik.write("\n")


def main() -> None:
    polisy = wczytaj_polisy()
    fragmenty = [vars(f) for f in podziel_owu()]
    oczekiwane = [zbuduj_oczekiwane_szkody(case, polisy, fragmenty) for case in przypadki_szkody.SZKODY]
    wyczysc_szkody()
    manifest = []
    with render.otworz_przegladarke() as strona:
        for case, dane in zip(przypadki_szkody.SZKODY, oczekiwane):
            print(f"[{case['id']}] generowanie zgloszenia szkody ...", flush=True)
            render.html_do_pdf(strona, html_zgloszenia(case), SZKODY_DIR / f"{case['id']}.pdf")
            _zapisz_json(OCZEKIWANE_SZKODY_DIR / f"{case['id']}.json", dane)
            manifest.append({"id": case["id"], "plik": f"szkody/{case['id']}.pdf", "format": "pdf_formularz",
                             "pulapka": case["uwagi_dla_ewaluacji"], "decyzja": dane["decyzja"]})
    _zapisz_json(SZKODY_DIR / "manifest.json", manifest)
    print(f"Gotowe: {len(manifest)} zgloszen szkod w {SZKODY_DIR}", flush=True)


if __name__ == "__main__":
    main()
