"""Porownanie trafnosci TYLKO wyszukiwania (Etap 12) - bez LLM, zero kosztu modelu.

Zloty zbior: zapytania zbudowane z `pola` przypadkow Z01-Z12 (`dane/szkody/oczekiwane/`), ta
sama funkcja `agent.wezly_szkody.zbuduj_zapytanie_owu` co w grafie na produkcji, oczekiwane
ustepy = `paragrafy_oczekiwane` (parsowane `rag.fragmenty.parsuj_odwolanie`). Przypadki bez
oczekiwanego paragrafu (np. S01/S02 - decyzja formalna, LLM nie ocenia pokrycia) sa pomijane,
tak samo jak w `ewaluacja/szkody.py` (`recall_wyszukiwania_at_5`).

UWAGA UCZCIWOSCI: 12 przypadkow to bardzo maly zbior - roznica o 1 trafienie to ok. 8 punktow
procentowych recall. Traktuj te liczby jako kierunek, nie jako precyzyjny pomiar.

Wyszukiwarki:
- `lokalna`   - WyszukiwarkaLokalna (BM25 w pamieci, bez sieci)
- `azure`     - WyszukiwarkaAzure, hybryda BM25+wektor (az login, tylko odczyt indeksu)
- `azure+semantyczna` - jak wyzej + semantic ranker (pomijane, jesli plan Free/limit odrzuci)
- `qdrant`    - WyszukiwarkaQdrant, hybryda RRF (wektor gesty Azure + wlasny sparse BM25)
- `qdrant-gesty`, `qdrant-rzadki` - te same dane w Qdrant, pojedynczy tryb (rozbicie hybrydy)

Wektor gesty wszedzie to ten sam embedding Azure OpenAI text-embedding-3-small, wspoldzielony
przez `rag/cache_embeddingow.py` miedzy Azure i Qdrant - ten sam tekst (zapytanie albo fragment
OWU) placi za embedding tylko raz w calym przebiegu, niezaleznie od tego, ile wariantow
wyszukiwarki go uzywa.

    python ewaluacja/porownaj_wyszukiwarki.py
    python ewaluacja/porownaj_wyszukiwarki.py --pomin-azure   # tylko lokalna + qdrant, bez az login
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.wezly_szkody import zbuduj_zapytanie_owu  # noqa: E402
from ewaluacja.szkody import wczytaj_oczekiwany_szkody, wszystkie_id_szkod  # noqa: E402
from rag.fragmenty import parsuj_odwolanie  # noqa: E402
from rag.wyszukiwarka import TOP_K, WyszukiwarkaLokalna  # noqa: E402

WYNIKI_DIR = Path(__file__).resolve().parent / "wyniki"
PLIK_CACHE_DOMYSLNY = ROOT / ".cache_embeddingow" / "text-embedding-3-small.json"
K_MAX = 5
PROGI_RECALL = (1, 3, 5)


def zloty_zbior() -> list[dict[str, Any]]:
    """Zapytania ze zlotego zbioru szkod, ktore maja oczekiwany paragraf OWU."""
    wiersze = []
    for id_przypadku in wszystkie_id_szkod():
        oczekiwany = wczytaj_oczekiwany_szkody(id_przypadku)
        oczekiwane = {parsuj_odwolanie(o) for o in oczekiwany["paragrafy_oczekiwane"]}
        if not oczekiwane:
            continue
        wiersze.append({
            "id": oczekiwany["id"],
            "zapytanie": zbuduj_zapytanie_owu(oczekiwany["pola"]),
            "oczekiwane": oczekiwane,
        })
    return wiersze


def _percentyl(wartosci: list[float], p: float) -> float:
    if len(wartosci) == 1:
        return wartosci[0]
    # statistics.quantiles z n=100 wymaga >=2 punktow; metoda "inclusive" jest stabilna
    # przy malych probach (patrz uwaga o uczciwosci na gorze pliku).
    return statistics.quantiles(wartosci, n=100, method="inclusive")[int(p) - 1]


def ocen_wyszukiwarke(wyszukiwarka, zapytania: list[dict[str, Any]], k_max: int = K_MAX) -> dict[str, Any]:
    trafienia: dict[int, list[bool]] = {k: [] for k in PROGI_RECALL}
    odwrotne_rangi: list[float] = []
    czasy_ms: list[float] = []
    bledy: list[dict[str, str]] = []

    for wiersz in zapytania:
        start = time.perf_counter()
        try:
            fragmenty = wyszukiwarka.szukaj(wiersz["zapytanie"], k_max)
        except Exception as e:  # noqa: BLE001 - awaria jednej wyszukiwarki nie przerywa calego porownania
            bledy.append({"id": wiersz["id"], "blad": f"{type(e).__name__}: {e}"})
            continue
        czasy_ms.append((time.perf_counter() - start) * 1000)
        pozycje = [(f.paragraf, f.ustep) for f in fragmenty]
        for k in PROGI_RECALL:
            trafienia[k].append(any(p in wiersz["oczekiwane"] for p in pozycje[:k]))
        ranga = next((i + 1 for i, p in enumerate(pozycje) if p in wiersz["oczekiwane"]), None)
        odwrotne_rangi.append(1.0 / ranga if ranga else 0.0)

    n = len(czasy_ms)
    wynik = {
        "n_zapytan": len(zapytania),
        "n_ocenionych": n,
        "bledy": bledy,
        "mrr_at_5": round(sum(odwrotne_rangi) / len(odwrotne_rangi), 3) if odwrotne_rangi else None,
        "p50_ms": round(_percentyl(czasy_ms, 50), 1) if czasy_ms else None,
        "p95_ms": round(_percentyl(czasy_ms, 95), 1) if czasy_ms else None,
    }
    for k in PROGI_RECALL:
        wynik[f"recall_at_{k}"] = round(sum(trafienia[k]) / len(trafienia[k]), 3) if trafienia[k] else None
    return wynik


def zbuduj_warianty(pomin_azure: bool, plik_cache: Path) -> dict[str, Any]:
    """Zwraca `{nazwa_wariantu: wyszukiwarka}`. Warianty niedostepne (brak az login, blad
    konfiguracji) sa pomijane z komunikatem na stderr, nie wywalaja calego porownania."""
    from rag.cache_embeddingow import embedder_z_cache

    warianty: dict[str, Any] = {"lokalna": WyszukiwarkaLokalna()}

    if pomin_azure:
        print("Pomijam warianty Azure (--pomin-azure).", file=sys.stderr)
        embeduj_wspolny = None
    else:
        try:
            from rag.azure_search import WyszukiwarkaAzure, zbuduj_embedder, zbuduj_klienta_wyszukiwania

            srodowisko = __import__("os").environ
            klient_azure = zbuduj_klienta_wyszukiwania(srodowisko)
            embeduj_wspolny = embedder_z_cache(zbuduj_embedder(srodowisko), plik_cache)
            warianty["azure"] = WyszukiwarkaAzure(klient_azure, embeduj_wspolny, semantyczna=False)
            try:
                warianty["azure+semantyczna"] = WyszukiwarkaAzure(klient_azure, embeduj_wspolny, semantyczna=True)
            except Exception as e:  # noqa: BLE001
                print(f"Pomijam azure+semantyczna: {type(e).__name__}: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - brak konfiguracji, brak az login, blad sieci
            print(f"Pomijam warianty Azure (brak konfiguracji/az login): {type(e).__name__}: {e}", file=sys.stderr)
            embeduj_wspolny = None

    try:
        from qdrant_client import QdrantClient

        from rag.indeksuj_owu_qdrant import indeksuj
        from rag.qdrant_search import KOLEKCJA_DOMYSLNA, WyszukiwarkaQdrant

        if embeduj_wspolny is None:
            from rag.azure_search import zbuduj_embedder

            embeduj_wspolny = embedder_z_cache(zbuduj_embedder(__import__("os").environ), plik_cache)

        klient_qdrant = QdrantClient(":memory:")
        indeksuj(klient_qdrant, embeduj_wspolny, KOLEKCJA_DOMYSLNA)
        warianty["qdrant"] = WyszukiwarkaQdrant(klient_qdrant, embeduj_wspolny, tryb="hybryda")
        warianty["qdrant-gesty"] = WyszukiwarkaQdrant(klient_qdrant, embeduj_wspolny, tryb="gesty")
        warianty["qdrant-rzadki"] = WyszukiwarkaQdrant(klient_qdrant, embeduj_wspolny, tryb="rzadki")
    except Exception as e:  # noqa: BLE001
        print(f"Pomijam warianty Qdrant: {type(e).__name__}: {e}", file=sys.stderr)

    return warianty


def _tabela_md(wyniki: dict[str, dict]) -> str:
    naglowki = ["Wyszukiwarka", "N", "Recall@1", "Recall@3", "Recall@5", "MRR@5", "p50 [ms]", "p95 [ms]", "Bledy"]
    linie = ["| " + " | ".join(naglowki) + " |", "|" + "---|" * len(naglowki)]
    for nazwa, w in wyniki.items():
        linie.append("| " + " | ".join([
            nazwa, str(w["n_ocenionych"]),
            "-" if w["recall_at_1"] is None else f"{w['recall_at_1']:.0%}",
            "-" if w["recall_at_3"] is None else f"{w['recall_at_3']:.0%}",
            "-" if w["recall_at_5"] is None else f"{w['recall_at_5']:.0%}",
            "-" if w["mrr_at_5"] is None else f"{w['mrr_at_5']:.3f}",
            "-" if w["p50_ms"] is None else f"{w['p50_ms']:.1f}",
            "-" if w["p95_ms"] is None else f"{w['p95_ms']:.1f}",
            str(len(w["bledy"])),
        ]) + " |")
    return "\n".join(linie)


def _zapisz_wyniki(wyniki: dict[str, dict], zapytania: list[dict], metadane: dict) -> tuple[Path, Path]:
    WYNIKI_DIR.mkdir(parents=True, exist_ok=True)
    znacznik = time.strftime("%Y%m%d-%H%M")
    podstawa = f"{znacznik}_wyszukiwarki"
    sciezka_json = WYNIKI_DIR / f"{podstawa}.json"
    sciezka_md = WYNIKI_DIR / f"{podstawa}.md"

    sciezka_json.write_text(
        json.dumps({"metadane": metadane, "wyniki": wyniki}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    linie = [
        "# Porownanie wyszukiwarek RAG po OWU (Etap 12)",
        "",
        f"Data: {znacznik}",
        f"Zloty zbior: {metadane['liczba_zapytan']} zapytan z przypadkow szkod majacych "
        f"oczekiwany paragraf OWU ({', '.join(metadane['id_przypadkow'])}) - sposrod 12 "
        "przypadkow Z01-Z12 (S01/S02-podobne beza paragrafu sa pomijane, tak samo jak w "
        "ewaluacja/szkody.py).",
        "",
        f"UWAGA: bardzo maly zbior ({metadane['liczba_zapytan']} zapytan) - roznica o 1 "
        "trafienie to kilka-kilkanascie punktow procentowych recall. Liczby ponizej pokazuja "
        "kierunek, nie precyzyjny pomiar.",
        "",
        "UWAGA (czas): wszystkie warianty dziela jeden cache embeddingow na dysku - ten sam "
        "tekst zapytania placi za embedding Azure OpenAI tylko raz w calym przebiegu. "
        "Wariant uruchomiony jako PIERWSZY (tu: `lokalna` nie placi wcale, `azure` placi "
        "naprawde) ponosi prawdziwy koszt sieciowy embeddingu; kolejne warianty (tu: qdrant) "
        "czesto dostaja ten embedding z cache za darmo. p50/p95 ponizej NIE sa wiec uczciwym "
        "porownaniem end-to-end (zapytanie uzytkownika -> wynik) - Qdrant mierzy tu w duzej "
        "czesci sam czas wyszukiwania w lokalnej, embedded bazie (bez sieci), nie koszt "
        "embeddingu zapytania.",
        "",
        _tabela_md(wyniki),
        "",
        "## Bledy per wariant",
    ]
    bledy_wystapily = False
    for nazwa, w in wyniki.items():
        for blad in w["bledy"]:
            bledy_wystapily = True
            linie.append(f"- {nazwa} / {blad['id']}: {blad['blad']}")
    if not bledy_wystapily:
        linie.append("Brak.")
    sciezka_md.write_text("\n".join(linie), encoding="utf-8")
    return sciezka_json, sciezka_md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Porownanie trafnosci wyszukiwarek RAG po OWU (bez LLM).")
    parser.add_argument("--pomin-azure", action="store_true", help="Nie buduj wariantow Azure (bez az login).")
    parser.add_argument("--cache", default=str(PLIK_CACHE_DOMYSLNY), help="Plik cache embeddingow na dysku.")
    argumenty = parser.parse_args(argv)

    zapytania = zloty_zbior()
    if not zapytania:
        print("Zloty zbior jest pusty - brak przypadkow z paragrafy_oczekiwane.", file=sys.stderr)
        return 1

    warianty = zbuduj_warianty(argumenty.pomin_azure, Path(argumenty.cache))
    wyniki = {nazwa: ocen_wyszukiwarke(wyszukiwarka, zapytania) for nazwa, wyszukiwarka in warianty.items()}

    print(_tabela_md(wyniki))

    metadane = {"liczba_zapytan": len(zapytania), "id_przypadkow": [w["id"] for w in zapytania]}
    sciezka_json, sciezka_md = _zapisz_wyniki(wyniki, zapytania, metadane)
    print(f"\nZapisano: {sciezka_json}")
    print(f"Zapisano: {sciezka_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
