"""Ewaluacja vision (Etap 23): zdjecia szkod Z01..Z12 + 6 par niezgodnych N1..N6.

Uruchomienie (z katalogu repo):
    python -m ewaluacja.zdjecia --atrapa                       # bez sieci: 12/12, 5/5, 0 falszywych alarmow
    python -m ewaluacja.zdjecia --dostawca azure --biegi 5 --mlflow   # NA ZYWO - platne (zadanie 6)

Wola WYLACZNIE `model.analizuj_zdjecie` + `agent.zdjecia.porownaj` (bez grafu) - tanio i izoluje vision
od reszty toru. Jeden bieg = 18 wywolan (jedno na pozycje, bez ponowien: blad = wiersz z polem `blad`).

Metryki (SPEC_ETAP23, zadanie 4), liczone z wierszy:
- `trafnosc_rodzaju`, `trafnosc_z_pokrewnymi`, `dlugotrwalosc_ok` - liczba trafien na 12 zdjeciach
  pod wlasne zgloszenie (pozycje Z01..Z12; pokrewne wg `agent.zdjecia.POKREWNE`),
- `wykrycie_niezgodnosci` - liczba wykryc na N1..N5; `n6_wynik` - 1.0, gdy N6 wykryta (raportowana osobno),
- `falszywe_alarmy` - pozycje zgodne (Z01..Z12), na ktorych wykryto "niezgodnosc",
- `nieustalone` - pozycje (z 18) ze zgodnoscia NIEUSTALONA, `bledy` - pozycje, w ktorych model rzucil wyjatek,
- tokeny i koszt na zdjecie, czas p50/p95 (nearest-rank).
Wiersz: `wykryto` = podniesiono alarm (NIEZGODNE albo sygnal dlugotrwalosci) - dla N1..N6 to wykrycie,
dla Z01..Z12 to falszywy alarm (`falszywy_alarm` = to samo, ale tylko dla pozycji zgodnych).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.model import BrakKluczaAPI, ModelGemini  # noqa: E402
from agent.model_azure import DOZWOLONE_DETAIL_OBRAZU, BrakKonfiguracjiAzure, ModelAzure  # noqa: E402
from agent.zdjecia import POKREWNE, PROG_PEWNOSCI, kategoria_przyczyny, porownaj, wczytaj_obraz  # noqa: E402
from ewaluacja.atrapa import ModelAtrapa  # noqa: E402
from ewaluacja.mlflow_log import zaloguj_przebieg  # noqa: E402
from ewaluacja.szkody import ZDJECIA_DIR, wczytaj_oczekiwany_szkody, wszystkie_id_szkod  # noqa: E402
from ewaluacja.uruchom import (  # noqa: E402
    CENA_GPT5_MINI_WE_USD_NA_MILION,
    CENA_GPT5_MINI_WY_USD_NA_MILION,
    LIMIT_TOKENOW_DOMYSLNY,
    OCZEKIWANE_DIR,
)
from ewaluacja.zdjecia_przypadki import (  # noqa: E402
    ID_PAR_DO_METRYKI,
    ID_PARY_RAPORTOWANEJ,
    Pozycja,
    pozycje_ewaluacji,
)

WYNIKI_DIR = Path(__file__).resolve().parent / "wyniki"
SCIEZKA_PROMPTU_ZDJECIA = ROOT / "agent" / "instrukcje_zdjecia.py"

NAGLOWKI_TABELI = ["ID", "Zdjecie", "Zgloszenie", "Rodzaj(ocz->otrz)", "Zgodnosc", "Dlugotrw.", "Wykryto", "Pewn.", "Czas[ms]"]


def percentyl(wartosci: list[float], p: int) -> float:
    """Percentyl metoda nearest-rank (bez interpolacji - przy 18 pozycjach interpolacja udawalaby dokladnosc)."""
    if not wartosci:
        return 0.0
    posortowane = sorted(wartosci)
    rank = max(1, math.ceil(p * len(posortowane) / 100))
    return float(posortowane[rank - 1])


def _zbuduj_model(uzyj_atrapy: bool, dostawca: str, detail: str | None):
    if uzyj_atrapy:
        return ModelAtrapa(OCZEKIWANE_DIR)
    if dostawca == "azure":
        return ModelAzure(detail_obrazu=detail)
    return ModelGemini()


def _wiersz(poz: Pozycja, oczekiwane_zdjecie: dict, kategoria_zgloszona, ocena, meta, czas_ms: float, blad: str | None) -> dict:
    zgodna = poz.id.startswith("Z")
    if ocena is None:
        return {
            "id": poz.id, "zdjecie": poz.zdjecie, "zgloszenie": poz.zgloszenie,
            "rodzaj_oczekiwany": oczekiwane_zdjecie["rodzaj_zdarzenia"], "rodzaj_otrzymany": None,
            "rodzaj_ok": False, "rodzaj_ok_pokrewne": False, "dlugotrwalosc_ok": False,
            "zgodnosc_rodzaju": None, "sygnal_dlugotrwalosci": False, "wykryto": False, "falszywy_alarm": False,
            "pewnosc": None, "tokeny_we": 0, "tokeny_wy": 0, "czas_ms": czas_ms, "blad": blad, "powody": [],
        }
    wynik = porownaj(ocena, kategoria_zgloszona)
    wykryto = wynik["zgodnosc_rodzaju"] == "NIEZGODNE" or wynik["sygnal_dlugotrwalosci"]
    oczekiwany_rodzaj = oczekiwane_zdjecie["rodzaj_zdarzenia"]
    return {
        "id": poz.id, "zdjecie": poz.zdjecie, "zgloszenie": poz.zgloszenie,
        "rodzaj_oczekiwany": oczekiwany_rodzaj, "rodzaj_otrzymany": ocena.rodzaj_zdarzenia,
        "rodzaj_ok": ocena.rodzaj_zdarzenia == oczekiwany_rodzaj,
        "rodzaj_ok_pokrewne": ocena.rodzaj_zdarzenia == oczekiwany_rodzaj
        or frozenset({ocena.rodzaj_zdarzenia, oczekiwany_rodzaj}) in POKREWNE,
        "dlugotrwalosc_ok": ocena.dlugotrwalosc == oczekiwane_zdjecie["dlugotrwalosc"],
        "zgodnosc_rodzaju": wynik["zgodnosc_rodzaju"], "sygnal_dlugotrwalosci": wynik["sygnal_dlugotrwalosci"],
        "wykryto": wykryto, "falszywy_alarm": bool(wykryto and zgodna),
        "pewnosc": ocena.pewnosc, "tokeny_we": (meta.tokeny_we or 0), "tokeny_wy": (meta.tokeny_wy or 0),
        "czas_ms": czas_ms, "blad": None, "powody": wynik["powody"],
    }


def ocen_pozycje(model, poz: Pozycja) -> dict:
    """Jedno zdjecie przez model + porownanie z przyczyna zgloszenia. Wyjatek modelu -> wiersz z `blad`
    (tylko nazwa typu - tresc wyjatku moze zawierac fragment odpowiedzi/zdjecia)."""
    oczekiwane_zdjecie = wczytaj_oczekiwany_szkody(poz.zdjecie)["zdjecie"]
    przyczyna = wczytaj_oczekiwany_szkody(poz.zgloszenie)["pola"].get("przyczyna")
    kategoria = kategoria_przyczyny(przyczyna)
    obraz, mime = wczytaj_obraz(ZDJECIA_DIR / f"{poz.zdjecie}.jpg")
    start = time.monotonic()
    try:
        ocena, meta = model.analizuj_zdjecie(obraz, mime)
    except Exception as e:  # noqa: BLE001 - blad dostawcy ma byc wierszem wyniku, nie przerwaniem biegu
        return _wiersz(poz, oczekiwane_zdjecie, kategoria, None, None, (time.monotonic() - start) * 1000, type(e).__name__)
    return _wiersz(poz, oczekiwane_zdjecie, kategoria, ocena, meta, (time.monotonic() - start) * 1000, None)


def uruchom_bieg(model, pozycje: list[Pozycja], limit_tokenow: int) -> tuple[list[dict], str | None]:
    """Jeden bieg po liscie pozycji. Zwraca (wiersze, przerwano): przerwano = None | "limit_tokenow"
    (wyniki czesciowe) | "rate_limit" (dalsze wywolania mierzylyby limit, nie model)."""
    wiersze: list[dict] = []
    for poz in pozycje:
        wiersz = ocen_pozycje(model, poz)
        wiersze.append(wiersz)
        if wiersz["blad"] and "RateLimit" in wiersz["blad"]:
            return wiersze, "rate_limit"
        if sum(w["tokeny_we"] + w["tokeny_wy"] for w in wiersze) > limit_tokenow:
            return wiersze, "limit_tokenow"
    return wiersze, None


def _zgodne(wiersze: list[dict]) -> list[dict]:
    return [w for w in wiersze if w["id"].startswith("Z")]


def metryki_zdjec(
    wiersze: list[dict], cena_we_usd_na_milion: float | None = None, cena_wy_usd_na_milion: float | None = None
) -> dict[str, float]:
    zgodne = _zgodne(wiersze)
    pary = {w["id"]: w for w in wiersze if w["id"].startswith("N")}
    n = len(wiersze)
    metryki = {
        "przypadki_lacznie": float(n),
        "trafnosc_rodzaju": float(sum(w["rodzaj_ok"] for w in zgodne)),
        "trafnosc_z_pokrewnymi": float(sum(w["rodzaj_ok_pokrewne"] for w in zgodne)),
        "dlugotrwalosc_ok": float(sum(w["dlugotrwalosc_ok"] for w in zgodne)),
        "wykrycie_niezgodnosci": float(sum(pary[i]["wykryto"] for i in ID_PAR_DO_METRYKI if i in pary)),
        "n6_wynik": float(bool(pary.get(ID_PARY_RAPORTOWANEJ, {}).get("wykryto", False))),
        "falszywe_alarmy": float(sum(w["falszywy_alarm"] for w in zgodne)),
        "nieustalone": float(sum(w["zgodnosc_rodzaju"] == "NIEUSTALONA" for w in wiersze)),
        "bledy": float(sum(1 for w in wiersze if w.get("blad"))),
        "tokeny_we_na_zdjecie": sum(w["tokeny_we"] for w in wiersze) / n if n else 0.0,
        "tokeny_wy_na_zdjecie": sum(w["tokeny_wy"] for w in wiersze) / n if n else 0.0,
        "czas_p50_ms": percentyl([w["czas_ms"] for w in wiersze], 50),
        "czas_p95_ms": percentyl([w["czas_ms"] for w in wiersze], 95),
    }
    if cena_we_usd_na_milion is not None and cena_wy_usd_na_milion is not None:
        metryki["koszt_usd_na_zdjecie"] = (
            metryki["tokeny_we_na_zdjecie"] * cena_we_usd_na_milion
            + metryki["tokeny_wy_na_zdjecie"] * cena_wy_usd_na_milion
        ) / 1_000_000
    return metryki


def tabela_ascii_zdjec(wiersze: list[dict]) -> str:
    linie = [" | ".join(NAGLOWKI_TABELI)]
    for w in wiersze:
        rodzaj = f"{w['rodzaj_oczekiwany']}->{w['rodzaj_otrzymany']}" + ("" if w["rodzaj_ok"] else " (!)")
        linie.append(" | ".join([
            w["id"], w["zdjecie"], w["zgloszenie"], rodzaj,
            w["zgodnosc_rodzaju"] or f"BLAD({w['blad']})", "TAK" if w["sygnal_dlugotrwalosci"] else "-",
            "TAK" if w["wykryto"] else "-", "-" if w["pewnosc"] is None else f"{w['pewnosc']:.2f}",
            f"{w['czas_ms']:.0f}",
        ]))
    return "\n".join(linie)


def _podsumowanie(metryki: dict[str, float]) -> str:
    return (f"Rodzaje: {metryki['trafnosc_rodzaju']:.0f}/12 (z pokrewnymi {metryki['trafnosc_z_pokrewnymi']:.0f}/12), "
            f"wykrycia N1-N5: {metryki['wykrycie_niezgodnosci']:.0f}/5, N6: "
            f"{'wykryta' if metryki['n6_wynik'] else 'niewykryta'}, "
            f"falszywe alarmy: {metryki['falszywe_alarmy']:.0f}/12, bledy: {metryki['bledy']:.0f}.")


def raport_md_zdjec(nazwa_modelu: str, wiersze: list[dict], metadane: dict, metryki: dict[str, float]) -> str:
    linie = [
        f"# Ewaluacja vision (zdjecia szkod) - model: {nazwa_modelu}",
        "",
        f"detail: {metadane.get('detail')}, prog pewnosci: {metadane['prog_pewnosci']} (ustalony z gory, nie strojony), "
        f"wywolania vision: {metadane['wywolania_llm_laczne']}"
        + (" - BIEG CZESCIOWY (przerwany bezpiecznikiem)" if metadane.get("czesciowy") else ""),
        _podsumowanie(metryki),
        "",
        "## Metryki",
        *[f"- {k}: {v:.4g}" for k, v in metryki.items()],
        "",
        "```",
        tabela_ascii_zdjec(wiersze),
        "```",
        "",
        "## Pomylki",
    ]
    pomylki = [w for w in wiersze if w.get("blad") or (w["id"].startswith("Z") and (not w["rodzaj_ok"] or w["falszywy_alarm"]))
               or (w["id"] in ID_PAR_DO_METRYKI and not w["wykryto"])]
    if not pomylki:
        linie.append("Brak - rodzaje trafione, wszystkie pary N1-N5 wykryte, zero falszywych alarmow.")
    for w in pomylki:
        linie.append(
            f"- {w['id']} (zdjecie {w['zdjecie']} pod zgloszenie {w['zgloszenie']}): rodzaj oczekiwany={w['rodzaj_oczekiwany']}, "
            f"otrzymany={w['rodzaj_otrzymany']}, zgodnosc={w['zgodnosc_rodzaju']}, wykryto={w['wykryto']}"
            + (f"; BLAD: {w['blad']}" if w.get("blad") else "")
        )
    return "\n".join(linie)


def raport_zbiorczy_md(nazwa_modelu: str, metryki_biegow: list[dict[str, float]]) -> str:
    """Metryki per bieg + zakres min-max z N biegow (zmiennosc LLM, nie jeden szczesliwy bieg)."""
    klucze = list(metryki_biegow[0])
    linie = [
        f"# Ewaluacja vision - {len(metryki_biegow)} biegow, model: {nazwa_modelu}",
        "",
        "| metryka | " + " | ".join(f"bieg {i}" for i in range(1, len(metryki_biegow) + 1)) + " | min | max |",
        "|---|" + "---|" * (len(metryki_biegow) + 2),
    ]
    for k in klucze:
        wartosci = [m[k] for m in metryki_biegow]
        linie.append(f"| {k} | " + " | ".join(f"{v:.4g}" for v in wartosci) + f" | {min(wartosci):.4g} | {max(wartosci):.4g} |")
    return "\n".join(linie)


def tabela_mlflow(wiersze: list[dict]) -> dict[str, list]:
    kolumny = ["id", "zdjecie", "zgloszenie", "rodzaj_oczekiwany", "rodzaj_otrzymany", "rodzaj_ok", "zgodnosc_rodzaju",
               "sygnal_dlugotrwalosci", "wykryto", "falszywy_alarm", "pewnosc", "tokeny_we", "tokeny_wy", "czas_ms"]
    return {k: [w.get(k) for w in wiersze] for k in kolumny}


def _bezpieczna_nazwa(tekst: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", tekst)


def _wersja_promptu_zdjecia() -> str:
    if not SCIEZKA_PROMPTU_ZDJECIA.exists():
        return "nieznana"
    return hashlib.sha256(SCIEZKA_PROMPTU_ZDJECIA.read_bytes()).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ewaluacja vision: 12 zdjec szkod + 6 par niezgodnych (Etap 23).")
    parser.add_argument("--atrapa", action="store_true", help="Atrapa modelu (hash zdjecia -> oczekiwana ocena) - bez sieci.")
    parser.add_argument("--dostawca", default="azure", choices=["azure", "gemini"],
                        help="Dostawca vision bez --atrapa (domyslnie azure; vLLM nie obsluguje obrazow).")
    parser.add_argument("--biegi", type=int, default=1, help="Liczba biegow po 18 wywolan (domyslnie 1).")
    parser.add_argument("--detail", default=None, choices=list(DOZWOLONE_DETAIL_OBRAZU),
                        help="detail obrazu dla Azure (domyslnie zmienna AZURE_OPENAI_VISION_DETAIL albo low).")
    parser.add_argument("--mlflow", action="store_true", help="Po kazdym biegu zaloguj run do MLflow (tag modul=zdjecia).")
    parser.add_argument("--limit-tokenow", type=int, default=LIMIT_TOKENOW_DOMYSLNY,
                        help=f"Przerwij, gdy laczne tokeny BIEGU przekrocza limit (domyslnie {LIMIT_TOKENOW_DOMYSLNY}).")
    args = parser.parse_args(argv)
    if args.biegi < 1:
        print("BLAD: --biegi musi byc >= 1.", file=sys.stderr)
        return 2

    try:
        model = _zbuduj_model(args.atrapa, args.dostawca, args.detail)
    except (BrakKluczaAPI, BrakKonfiguracjiAzure) as e:
        print(f"BLAD: {e}", file=sys.stderr)
        return 2

    nazwa_modelu = getattr(model, "nazwa_modelu", "nieznany")
    ma_cennik = isinstance(model, ModelAzure)
    cena_we = CENA_GPT5_MINI_WE_USD_NA_MILION if ma_cennik else None
    cena_wy = CENA_GPT5_MINI_WY_USD_NA_MILION if ma_cennik else None
    pozycje = pozycje_ewaluacji(wszystkie_id_szkod())
    WYNIKI_DIR.mkdir(parents=True, exist_ok=True)
    znacznik = time.strftime("%Y%m%d-%H%M")
    podstawa_wspolna = f"{znacznik}_zdjecia_{_bezpieczna_nazwa(nazwa_modelu)}"

    metryki_biegow: list[dict[str, float]] = []
    for numer in range(1, args.biegi + 1):
        start = time.monotonic()
        wiersze, przerwano = uruchom_bieg(model, pozycje, args.limit_tokenow)
        czas_ms = (time.monotonic() - start) * 1000
        if przerwano == "rate_limit":
            print(f"BLAD: limit zapytan API w biegu {numer} (pozycja {wiersze[-1]['id']}). Przerywam bez zapisu tego biegu.",
                  file=sys.stderr)
            return 4
        metryki = metryki_zdjec(wiersze, cena_we, cena_wy)
        metadane = {
            "czas_calkowity_ms": czas_ms,
            "wywolania_llm_laczne": len(wiersze),
            "liczba_przypadkow": len(wiersze),
            "tokeny_we_laczne": sum(w["tokeny_we"] for w in wiersze),
            "tokeny_wy_laczne": sum(w["tokeny_wy"] for w in wiersze),
            "prog_pewnosci": PROG_PEWNOSCI,
            "detail": getattr(model, "detail_obrazu", None),
            "dostawca": "atrapa" if args.atrapa else args.dostawca,
            "bieg": numer,
            "biegi": args.biegi,
            "czesciowy": przerwano is not None,
        }
        if "koszt_usd_na_zdjecie" in metryki:
            metadane["koszt_llm_usd_szacunkowy"] = metryki["koszt_usd_na_zdjecie"] * len(wiersze)

        podstawa = podstawa_wspolna + (f"_bieg{numer}" if args.biegi > 1 else "")
        sciezka_json = WYNIKI_DIR / f"{podstawa}.json"
        sciezka_md = WYNIKI_DIR / f"{podstawa}.md"
        sciezka_json.write_text(json.dumps(
            {"model": nazwa_modelu, "modul": "zdjecia", "metadane": metadane, "przypadki": wiersze, "metryki": metryki},
            ensure_ascii=False, indent=2), encoding="utf-8")
        sciezka_md.write_text(raport_md_zdjec(nazwa_modelu, wiersze, metadane, metryki), encoding="utf-8")

        print(f"--- bieg {numer}/{args.biegi} ---")
        print(tabela_ascii_zdjec(wiersze))
        print(f"\nWynik: {_podsumowanie(metryki)}")
        print(f"Zapisano wyniki: {sciezka_json}")
        metryki_biegow.append(metryki)

        if przerwano == "limit_tokenow":
            print(f"BLAD: bezpiecznik kosztowy - tokeny > {args.limit_tokenow} po pozycji {wiersze[-1]['id']}. "
                  "Przerywam, zapisano wyniki czesciowe.", file=sys.stderr)
            return 3

        if args.mlflow:
            parametry = {
                "dostawca": metadane["dostawca"], "model": nazwa_modelu, "detail": metadane["detail"],
                "prog_pewnosci": PROG_PEWNOSCI, "przypadki": [p.id for p in pozycje], "limit_tokenow": args.limit_tokenow,
                "atrapa": args.atrapa, "bieg": numer, "wersja_promptu": _wersja_promptu_zdjecia(),
            }
            try:
                run_id = zaloguj_przebieg(
                    parametry=parametry, metadane=metadane, wiersze=wiersze, artefakty=[sciezka_json, sciezka_md],
                    czesciowy=False, zrodlo="zdjecia", tagi_dodatkowe={"modul": "zdjecia", "klucz_przebiegu": podstawa},
                    metryki=metryki, tabela=tabela_mlflow(wiersze),
                )
            except Exception as e:  # noqa: BLE001 - pliki zostaja na dysku, kod 5 jak w uruchom.py
                print(f"BLAD: MLflow: {e}", file=sys.stderr)
                return 5
            print(f"MLflow: zapisano run {run_id}")

    if args.biegi > 1:
        sciezka_zbiorcza = WYNIKI_DIR / f"{podstawa_wspolna}_zbiorczo.md"
        sciezka_zbiorcza.write_text(raport_zbiorczy_md(nazwa_modelu, metryki_biegow), encoding="utf-8")
        print(f"Zapisano raport zbiorczy: {sciezka_zbiorcza}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
