"""Demo 7: porownanie retrievalu LlamaIndex z obecna wyszukiwarka na zamrozonych zestawach.

Zestawy i miary (zadanie 1) oraz skladanie wynikow, tabela MD i `main()` (zadanie 3) NIE importuja
LlamaIndex na poziomie modulu - dzialaja w `.venv`. Warianty LlamaIndex laduje leniwie
`zaladuj_warianty_li` (import `rag.llamaindex_owu`); bez LlamaIndex `main()` liczy tylko `lokalna`,
pisze komunikat na stderr i konczy sie kodem != 0.

Uruchomienie (w `.venv-llamaindex`):  python -m ewaluacja.porownaj_llamaindex
Bez LLM i bez sieci (SPEC D4); wektory tylko z kopii cache `.cache_embeddingow_demo7/`.

Zestawy (kazdy wiersz: `{"id", "zestaw", "zapytanie", "oczekiwane": set[(paragraf, ustep)]}`):
- Z - zloty zbior szkod Etapu 12 (`ewaluacja.porownaj_wyszukiwarki.zloty_zbior`), 9 zapytan;
- C - `dane/czat/pytania.json` z Demo 1 (zamrozony 28.10.2026), 10 pytan z oczekiwanym ustepem
  (pytania poza OWU sa pomijane).

Trafienie = dowolny oczekiwany ustep w top-k (definicja jak w `porownaj_wyszukiwarki.py`).
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ewaluacja.porownaj_wyszukiwarki import PROGI_RECALL, zloty_zbior  # noqa: E402
from ewaluacja.statystyka import porownaj, przedzial_wilsona  # noqa: E402
from rag.wyszukiwarka import TOP_K, WyszukiwarkaLokalna  # noqa: E402

PLIK_PYTAN_C = ROOT / "dane" / "czat" / "pytania.json"
PLIK_CACHE_DOMYSLNY = ROOT / ".cache_embeddingow_demo7" / "text-embedding-3-small.json"
WYNIKI_DIR = ROOT / "ewaluacja" / "wyniki"
NAZWA_BASELINE = "lokalna"
NAZWY_ZESTAWOW = ("Z", "C", "Z+C")
# Warianty mierzone tylko na czesci zestawow: cache Etapu 12 nie ma wektorow zapytan C (SPEC D3, właściciel 28.10).
ZESTAWY_WARIANTU = {"li-wektor": ("Z",)}


def zestaw_z() -> list[dict[str, Any]]:
    """Zestaw Z: opakowanie `zloty_zbior()` z dopisanym polem `zestaw`."""
    return [{"id": w["id"], "zestaw": "Z", "zapytanie": w["zapytanie"], "oczekiwane": set(w["oczekiwane"])}
            for w in zloty_zbior()]


def zestaw_c(sciezka: str | Path = PLIK_PYTAN_C) -> list[dict[str, Any]]:
    """Zestaw C z Demo 1. Pytania bez `oczekiwane` (poza OWU) sa pomijane. Zapytanie
    nawiazujace = `f"{pytanie} {poprzednie_pytanie}"`, gdzie poprzednie = pytanie wskazane w `po`
    (rownowaznik `czat.instrukcje.zapytanie_wyszukiwania` z Demo 1). Nieznane `po` -> KeyError."""
    pytania = json.loads(Path(sciezka).read_text(encoding="utf-8"))["pytania"]
    po_id = {p["id"]: p for p in pytania}
    wiersze = []
    for p in pytania:
        if not p["oczekiwane"]:
            continue
        zapytanie = p["pytanie"]
        if p.get("po"):
            zapytanie = f"{zapytanie} {po_id[p['po']]['pytanie']}"
        wiersze.append({
            "id": p["id"],
            "zestaw": "C",
            "zapytanie": zapytanie,
            "oczekiwane": {(o["paragraf"], o["ustep"]) for o in p["oczekiwane"]},
        })
    return wiersze


def trafienia(wyszukiwarka, zestaw: list[dict[str, Any]], k: int = TOP_K) -> dict[str, dict[str, Any]]:
    """`id -> {"ranga": int | None, "ids": [id fragmentu, ...]}` dla top-k wyszukiwarki.
    `ranga` = pozycja (od 1) pierwszego oczekiwanego ustepu albo None. Wyjatek z `szukaj` liczy sie
    jako nietrafienie (`ranga` None, `ids` puste) i dodaje klucz `blad` (wzor `ocen_wyszukiwarke`)."""
    wynik: dict[str, dict[str, Any]] = {}
    for wiersz in zestaw:
        try:
            fragmenty = wyszukiwarka.szukaj(wiersz["zapytanie"], k)
        except Exception as e:  # noqa: BLE001 - awaria wariantu = nietrafienie, nie przerwanie porownania
            wynik[wiersz["id"]] = {"ranga": None, "ids": [], "blad": f"{type(e).__name__}: {e}"}
            continue
        pozycje = [(f.paragraf, f.ustep) for f in fragmenty]
        ranga = next((i + 1 for i, p in enumerate(pozycje) if p in wiersz["oczekiwane"]), None)
        wynik[wiersz["id"]] = {"ranga": ranga, "ids": [f.id for f in fragmenty]}
    return wynik


def agreguj(wyniki: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Recall@1/3/5 i MRR@5 z wyniku `trafienia(...)`. Zaokraglenie do 3 miejsc jak w
    `ocen_wyszukiwarke`; dodatkowo liczby trafien (wejscie dla Wilsona i McNemara)."""
    rangi = [w["ranga"] for w in wyniki.values()]
    n = len(rangi)
    wynik: dict[str, Any] = {"n": n}
    for k in PROGI_RECALL:
        trafione = sum(1 for r in rangi if r is not None and r <= k)
        wynik[f"trafione_at_{k}"] = trafione
        wynik[f"recall_at_{k}"] = round(trafione / n, 3) if n else None
    wynik["mrr_at_5"] = round(sum(1.0 / r for r in rangi if r is not None and r <= 5) / n, 3) if n else None
    return wynik


# --- zadanie 3: skladanie wynikow, tabela, main ------------------------------------------

def _trafione_bool(wyniki: dict[str, dict[str, Any]], k: int = TOP_K) -> dict[str, bool]:
    return {i: w["ranga"] is not None and w["ranga"] <= k for i, w in wyniki.items()}


def _blok(wyniki: dict[str, dict[str, Any]], baseline: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Agregaty + Wilson (recall@5) + McNemar vs baseline (None dla samego baseline) + top5/rangi/bledy."""
    blok = agreguj(wyniki)
    n = blok["n"]
    blok["wilson_at_5"] = list(przedzial_wilsona(blok["trafione_at_5"], n)) if n else None
    blok["mcnemar"] = None
    if baseline is not None and n:
        wspolne = set(wyniki)
        m = porownaj({i: v for i, v in _trafione_bool(baseline).items() if i in wspolne}, _trafione_bool(wyniki))
        blok["mcnemar"] = {
            "n": m["n"], "b": m["b"], "c": m["c"], "p": m["p"],
            "tylko_lokalna_ok": m["tylko_a_ok"], "tylko_wariant_ok": m["tylko_b_ok"],
        }
    blok["top5"] = {i: w["ids"] for i, w in wyniki.items()}
    blok["rangi"] = {i: w["ranga"] for i, w in wyniki.items()}
    blok["bledy"] = [{"id": i, "blad": w["blad"]} for i, w in wyniki.items() if "blad" in w]
    return blok


def zbuduj_wyniki(
    warianty: dict[str, Any],
    zestaw_z_: list[dict[str, Any]],
    zestaw_c_: list[dict[str, Any]],
    k: int = TOP_K,
    tylko_zestawy: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """`{"k", "zestawy": {Z, C, Z+C: n}, "warianty": {nazwa: {Z, C, Z+C: blok | None}}}`.
    Wariant z wpisem w `tylko_zestawy` jest mierzony tylko na wymienionych zestawach (reszta None =
    "nie mierzone"; Z+C tylko gdy zmierzono i Z, i C). McNemar liczony vs `NAZWA_BASELINE` na id wspolnych."""
    if NAZWA_BASELINE not in warianty:
        raise ValueError(f"Brak wariantu bazowego {NAZWA_BASELINE!r} w warianty.")
    tylko_zestawy = tylko_zestawy or {}
    zestawy = {"Z": zestaw_z_, "C": zestaw_c_}
    surowe: dict[str, dict[str, dict[str, Any]]] = {}
    for nazwa, wyszukiwarka in warianty.items():
        dozwolone = tylko_zestawy.get(nazwa, ("Z", "C"))
        surowe[nazwa] = {z: trafienia(wyszukiwarka, zestawy[z], k) for z in ("Z", "C") if z in dozwolone}
        if "Z" in surowe[nazwa] and "C" in surowe[nazwa]:
            surowe[nazwa]["Z+C"] = {**surowe[nazwa]["Z"], **surowe[nazwa]["C"]}
    baseline = surowe[NAZWA_BASELINE]
    wynik_warianty: dict[str, dict[str, Any]] = {}
    for nazwa, po_zestawach in surowe.items():
        wynik_warianty[nazwa] = {
            z: (_blok(po_zestawach[z], None if nazwa == NAZWA_BASELINE else baseline[z]) if z in po_zestawach else None)
            for z in NAZWY_ZESTAWOW
        }
    return {
        "k": k,
        "zestawy": {"Z": len(zestaw_z_), "C": len(zestaw_c_), "Z+C": len(zestaw_z_) + len(zestaw_c_)},
        "warianty": wynik_warianty,
    }


def _ulamek(blok: dict[str, Any], k: int) -> str:
    return f"{blok[f'trafione_at_{k}']}/{blok['n']} ({blok[f'recall_at_{k}']:.3f})"


def tabela_md(wyniki: dict[str, Any]) -> str:
    """Trzy tabele (Z, C, Z+C): warianty x miary, Wilson 95% dla recall@5, McNemar vs `lokalna`, rozjazdy.
    Same znaki ASCII (konsola Windows), na koncu sekcja bledow wariantow."""
    naglowki = ["Wariant", "n", "Recall@1", "Recall@3", "Recall@5", "MRR@5", "Wilson 95% (@5)",
                "McNemar b/c", "p", "Rozjazdy vs lokalna"]
    linie: list[str] = []
    for zestaw in NAZWY_ZESTAWOW:
        linie += [f"## Zestaw {zestaw} (n = {wyniki['zestawy'][zestaw]})", "",
                  "| " + " | ".join(naglowki) + " |", "|" + "---|" * len(naglowki)]
        for nazwa, bloki in wyniki["warianty"].items():
            b = bloki[zestaw]
            if b is None:
                linie.append(f"| {nazwa} | " + " | ".join(["nie mierzone"] + ["-"] * (len(naglowki) - 3)) + " |")
                continue
            d, g = b["wilson_at_5"]
            m = b["mcnemar"]
            if m is None:
                mcn, p, rozjazdy = "-", "-", "(baseline)"
            else:
                mcn, p = f"{m['b']}/{m['c']}", f"{m['p']:.4f}"
                rozjazdy = (f"tylko lokalna: {', '.join(m['tylko_lokalna_ok']) or '-'}; "
                            f"tylko wariant: {', '.join(m['tylko_wariant_ok']) or '-'}")
            linie.append("| " + " | ".join([
                nazwa, str(b["n"]), _ulamek(b, 1), _ulamek(b, 3), _ulamek(b, 5),
                f"{b['mrr_at_5']:.3f}", f"{d:.3f}-{g:.3f}", mcn, p, rozjazdy,
            ]) + " |")
        linie.append("")
    linie.append("## Bledy wariantow (wyjatek w szukaj = nietrafienie)")
    bledy = [f"- {nazwa} / {z} / {x['id']}: {x['blad']}"
             for nazwa, bloki in wyniki["warianty"].items() for z in ("Z", "C")
             if bloki[z] is not None for x in bloki[z]["bledy"]]
    linie += bledy or ["Brak."]
    return "\n".join(linie)


def zaladuj_warianty_li(plik_cache: str | Path) -> tuple[dict[str, Any], list[str], bool]:
    """Warianty LlamaIndex z D3: `li-bm25-domyslny`, `li-bm25-bez-stemmera`, `li-wektor` (tylko z cache).
    Zwraca `(warianty, komunikaty, llamaindex_dostepny)`. Brak LlamaIndex -> `({}, [komunikat], False)`.
    Brak pliku cache -> pomija tylko `li-wektor` (komunikat, `main` konczy kodem 3); nigdy nie dociaga wektorow z Azure."""
    try:
        li = importlib.import_module("rag.llamaindex_owu")
    except ImportError as e:
        return {}, [f"Brak LlamaIndex w tym srodowisku ({type(e).__name__}: {e}); liczona tylko wyszukiwarka "
                    f"{NAZWA_BASELINE!r}. Uruchom w .venv-llamaindex."], False
    warianty: dict[str, Any] = {}
    komunikaty: list[str] = []
    for wariant in li.WARIANTY_BM25:
        nazwa = f"li-bm25-{wariant}"
        warianty[nazwa] = li.WyszukiwarkaLlamaIndex(li.zbuduj_bm25(wariant), nazwa)
    try:
        warianty["li-wektor"] = li.WyszukiwarkaLlamaIndex(li.zbuduj_wektorowa(plik_cache), "li-wektor")
    except FileNotFoundError as e:
        komunikaty.append(f"Pomijam li-wektor: {e}")
    return warianty, komunikaty, True


def _wersja(pakiet: str) -> str | None:
    try:
        return importlib.metadata.version(pakiet)
    except importlib.metadata.PackageNotFoundError:
        return None


def _raport_md(wyniki: dict[str, Any], metadane: dict[str, Any]) -> str:
    return "\n".join([
        "# Demo 7: LlamaIndex vs wyszukiwanie lokalne (retrieval po OWU, bez LLM)",
        "",
        f"Data: {metadane['znacznik']}. k = {wyniki['k']}, korpus: {metadane['liczba_fragmentow']} fragmentow OWU "
        "(te same dla wszystkich wariantow). Trafienie = dowolny oczekiwany ustep w top-k.",
        "",
        "UWAGA: n = 9 / 10 / 19. Przy n = 19 nawet roznica 4:0 daje p = 0,125 - wynik to KIERUNEK, nie dowod. "
        "Mierzymy retrieval; nie mierzymy generacji ani czasu end-to-end. li-wektor tylko na zestawie Z "
        "(cache Etapu 12 nie ma wektorow zapytan C), na C i Z+C: nie mierzone.",
        "",
        tabela_md(wyniki),
        "",
        *(["## Komunikaty", *[f"- {m}" for m in metadane["komunikaty"]]] if metadane["komunikaty"] else []),
    ])


def zapisz_wyniki(wyniki: dict[str, Any], metadane: dict[str, Any], katalog: Path) -> tuple[Path, Path]:
    katalog.mkdir(parents=True, exist_ok=True)
    podstawa = f"{metadane['znacznik']}_llamaindex"
    sciezka_json, sciezka_md = katalog / f"{podstawa}.json", katalog / f"{podstawa}.md"
    sciezka_json.write_text(json.dumps({"metadane": metadane, "wyniki": wyniki}, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    sciezka_md.write_text(_raport_md(wyniki, metadane), encoding="utf-8")
    return sciezka_json, sciezka_md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demo 7: porownanie retrievalu LlamaIndex z lokalna (bez LLM, bez sieci).")
    parser.add_argument("--cache", default=str(PLIK_CACHE_DOMYSLNY), help="Kopia cache embeddingow Etapu 12 (li-wektor).")
    parser.add_argument("--wyniki-dir", default=str(WYNIKI_DIR), help="Katalog na <ts>_llamaindex.{json,md}.")
    argumenty = parser.parse_args(argv)

    z_, c_ = zestaw_z(), zestaw_c()
    warianty: dict[str, Any] = {NAZWA_BASELINE: WyszukiwarkaLokalna()}
    li_warianty, komunikaty, li_ok = zaladuj_warianty_li(argumenty.cache)
    warianty.update(li_warianty)
    for komunikat in komunikaty:
        print(komunikat, file=sys.stderr)

    wyniki = zbuduj_wyniki(warianty, z_, c_, tylko_zestawy=ZESTAWY_WARIANTU)
    print(tabela_md(wyniki))

    from rag.fragmenty import podziel_owu

    metadane = {
        "znacznik": time.strftime("%Y%m%d-%H%M"),
        "liczba_fragmentow": len(podziel_owu()),
        "warianty": list(warianty),
        "komunikaty": komunikaty,
        "llama_index_core": _wersja("llama-index-core"),
        "zapytania": {w["id"]: w["zapytanie"] for w in z_ + c_},
    }
    sciezka_json, sciezka_md = zapisz_wyniki(wyniki, metadane, Path(argumenty.wyniki_dir))
    print(f"\nZapisano: {sciezka_json}\nZapisano: {sciezka_md}")
    if not li_ok:
        return 2
    return 0 if "li-wektor" in warianty else 3  # brak cache: reszta zapisana, ale nie sukces (Właściciel 28.10)


if __name__ == "__main__":
    sys.exit(main())
