"""Ewaluacja modulu szkodowego (Etap 10): przypadki Z01..Z12 z dane/szkody.

Wywolywane z `ewaluacja/uruchom.py --modul szkody`. Metryki (SPEC_ETAP10, sekcja Ewaluacja):
- `decyzje_ok` - decyzja grafu (regul + LLM) zgodna z oczekiwana,
- `cytat_trafiony` - oczekiwany ustep wsrod cytatow, ktore przeszly kontrole (tylko przypadki
  z `paragrafy_oczekiwane`),
- `recall_wyszukiwania_at_5` - oczekiwany ustep wsrod 5 fragmentow z PIERWSZEGO zapytania
  (sam retrieval, osobno od LLM; MLflow nie dopuszcza znaku "@" w nazwie metryki),
- `kontrola_cytatow_odrzucila`, `dodatkowe_zapytania` - liczniki przypadkow.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from langgraph.types import Command

from agent.decyzje_szkody import klucz_cytatu, podsumowanie_szkody
from rag.fragmenty import parsuj_odwolanie
from rag.wyszukiwarka import TOP_K

ROOT = Path(__file__).resolve().parent.parent
SZKODY_DIR = ROOT / "dane" / "szkody"
OCZEKIWANE_SZKODY_DIR = SZKODY_DIR / "oczekiwane"
ZDJECIA_DIR = ROOT / "dane" / "zdjecia_szkod"  # Etap 23: <ID>.jpg (flux/nano-banana, SPEC decyzja 8)

NAGLOWKI_TABELI_SZKOD = ["ID", "Decyzja", "Cytat", "Recall@5", "Kontrola", "DodZapytanie", "Czas[ms]"]


def wszystkie_id_szkod() -> list[str]:
    return sorted(p.stem for p in OCZEKIWANE_SZKODY_DIR.glob("Z*.json"))


def wczytaj_oczekiwany_szkody(id_przypadku: str) -> dict:
    return json.loads((OCZEKIWANE_SZKODY_DIR / f"{id_przypadku}.json").read_text(encoding="utf-8"))


def uruchom_szkode(graf, model, id_przypadku: str, zdjecia: bool = False) -> dict:
    """Jeden przypadek przez graf az do zatwierdzenia (automat zatwierdza rekomendacje).
    `zdjecia=True` (Etap 23) podaje do grafu `dane/zdjecia_szkod/<ID>.jpg` w polu `zdjecia`.
    Zwraca koncowy stan grafu z `_czas_ms`."""
    if hasattr(model, "ustaw_przypadek"):
        model.ustaw_przypadek(id_przypadku)
    plik = SZKODY_DIR / f"{id_przypadku}.pdf"
    if not plik.exists():
        raise FileNotFoundError(f"Brak pliku zgloszenia {plik} - uruchom generator/generuj_szkody.py")
    wejscie = {"plik": str(plik), "wywolania_llm": 0, "log": []}
    if zdjecia:
        plik_zdjecia = ZDJECIA_DIR / f"{id_przypadku}.jpg"
        if not plik_zdjecia.exists():
            raise FileNotFoundError(f"Brak zdjecia {plik_zdjecia}")
        wejscie["zdjecia"] = [str(plik_zdjecia)]
    config = {"configurable": {"thread_id": f"ewaluacja-{id_przypadku}-{uuid.uuid4().hex[:8]}"}}
    start = time.monotonic()
    stan = graf.invoke(wejscie, config)
    if "__interrupt__" in stan:
        decyzja = stan["__interrupt__"][0].value.get("decyzja") or "SKIEROWANIE"
        stan = graf.invoke(Command(resume={"decyzja": decyzja, "kto": "ewaluacja-automat"}), config)
    stan["_czas_ms"] = (time.monotonic() - start) * 1000
    return stan


BRAK_OCENY_LLM = "Brak oceny LLM - decyzja z regul (polisa/podejrzane instrukcje)."
BRAK_FRAGMENTOW = "(brak fragmentow OWU)"
MASKA = "[ZANONIMIZOWANO]"
KLUCZE_RAG = ("query", "context", "response", "ground_truth", "ocenia_llm")


def _query(pola: dict) -> str:
    """Etap 14: tylko opis zdarzenia i liczby - bez NIP, ubezpieczonego, adresu, nr polisy (RODO)."""
    czesci = [f"Zgloszenie szkody: {pola.get('przyczyna') or '-'}."]
    if pola.get("okolicznosci"):
        czesci.append(f"Okolicznosci: {pola['okolicznosci']}")
    czesci.append(f"Rodzaj mienia: {pola.get('rodzaj_mienia') or '-'}, kwota: {pola.get('szacowana_kwota') or '-'} PLN.")
    czesci.append("Czy szkoda jest objeta ochrona wedlug OWU i na jakiej podstawie?")
    return " ".join(czesci)


def _etykieta_cytatu(cytat: dict) -> str:
    """`§4 ust. 3` z cytatu modelu; model bywa wolny w formacie ("§ 4"/"4"), wiec normalizacja
    przez `klucz_cytatu`. Gdy klucza nie da sie ustalic - surowe wartosci."""
    klucz = klucz_cytatu(cytat)
    if klucz is not None:
        return f"§{klucz[0]} ust. {klucz[1]}"
    return f"§{cytat.get('paragraf')} ust. {cytat.get('ustep')}"


def _response(ocena: dict, odrzucone: set) -> str:
    """Przeglad p. 14: cytaty odrzucone przez kontrole cytatow NIE wchodza do response - sedzia ocenia
    to, co agent faktycznie przekazal dalej; odrzucenie liczy metryka deterministyczna (kontrola_odrzucila)."""
    linie = [f"Decyzja: {ocena.get('decyzja')}."]
    linie += [f"{_etykieta_cytatu(c)}: {c.get('uzasadnienie') or ''}"
              for c in ocena.get("cytaty") or [] if klucz_cytatu(c) not in odrzucone]
    if ocena.get("brakujace_dokumenty"):
        linie.append("Brakujace dokumenty: " + ", ".join(ocena["brakujace_dokumenty"]))
    return "\n".join(linie)


def _wartosci_osobowe(pola: dict) -> list[str]:
    """NIP, ubezpieczony, nr_polisy, miejsce.* - wartosci z tego zgloszenia (najdluzsze pierwsze)."""
    wartosci = [pola.get(k) for k in ("nip", "ubezpieczony", "nr_polisy")]
    wartosci += list((pola.get("miejsce") or {}).values())
    return sorted({str(w).strip() for w in wartosci if w and str(w).strip()}, key=len, reverse=True)


# NIP (10 cyfr, z myslnikami 3-3-2-2 / 3-2-2-3 albo bez) - wzorzec, nie tylko wartosc z pol zgloszenia:
# model moze przepisac do uzasadnienia NIP kontrahenta z dokumentu (Etap 14, przeglad koncowy m3).
WZORZEC_NIP = re.compile(r"\b\d{3}-?\d{3}-?\d{2}-?\d{2}\b|\b\d{3}-\d{2}-\d{2}-\d{3}\b")


def _maskuj(tekst: str, wartosci: list[str]) -> str:
    for w in wartosci:
        tekst = tekst.replace(w, MASKA)
    return WZORZEC_NIP.sub(MASKA, tekst)


def pola_rag(oczekiwany: dict, stan: dict) -> dict[str, Any]:
    """Etap 14: teksty do JSONL sedziego (query/context/response/ground_truth).
    Zostaja lokalnie w ewaluacja/wyniki/ (gitignore), nigdy w telemetrii. Wartosci osobowe
    z pol zgloszenia maskowane we WSZYSTKICH tekstach - LLM moze je przepisac do uzasadnienia."""
    pola = stan.get("pola") or {}
    ocena = stan.get("ocena_pokrycia") or {}
    odrzucone = {klucz_cytatu(c) for c in (stan.get("kontrola_cytatow") or {}).get("odrzucone") or []}
    fragmenty = stan.get("fragmenty_owu") or []
    kontekst = "\n\n".join(f"[{f['id']}] {f['tresc']}" for f in fragmenty) or BRAK_FRAGMENTOW
    paragrafy = ", ".join(oczekiwany.get("paragrafy_oczekiwane") or []) or "brak"
    prawda = oczekiwany.get("ground_truth_sedziego") or (
        f"Decyzja: {oczekiwany.get('decyzja_llm') or oczekiwany['decyzja']}. Podstawa: {paragrafy}.")
    if oczekiwany.get("uwagi_dla_ewaluacji"):
        prawda += f" {oczekiwany['uwagi_dla_ewaluacji']}"
    wartosci = _wartosci_osobowe(pola)
    teksty = {
        "query": _query(pola),
        "context": kontekst,
        "response": _response(ocena, odrzucone) if ocena else BRAK_OCENY_LLM,
        "ground_truth": prawda,
    }
    return {**{k: _maskuj(v, wartosci) for k, v in teksty.items()}, "ocenia_llm": bool(ocena)}


def porownaj_szkode(oczekiwany: dict, stan: dict) -> dict[str, Any]:
    """Wiersz wyniku dla jednego przypadku. `cytat_trafiony` i `recall_at_5` sa None,
    gdy przypadek nie ma oczekiwanego paragrafu (S01/S02/podejrzane - LLM nie ocenia)."""
    podsumowanie = podsumowanie_szkody(stan)
    oczekiwane = {parsuj_odwolanie(o) for o in oczekiwany["paragrafy_oczekiwane"]}
    kontrola = podsumowanie["kontrola_cytatow"] or {}
    odrzucone = {klucz_cytatu(c) for c in kontrola.get("odrzucone") or []}
    zacytowane = {klucz_cytatu(c) for c in podsumowanie["cytaty"]} - {None} - odrzucone
    fragmenty = stan.get("fragmenty_owu") or []
    pobrane_5 = {(f["paragraf"], f["ustep"]) for f in fragmenty[:TOP_K]}
    ma_paragraf = bool(oczekiwane)
    log = stan.get("log") or []
    rag = pola_rag(oczekiwany, stan)
    return {
        "id": oczekiwany["id"],
        "decyzja_oczekiwana": oczekiwany["decyzja"],
        "decyzja_otrzymana": podsumowanie["decyzja"],
        # SKIEROWANIE z bledu (403/404 wyszukiwarki, limit LLM) przypadkiem zgadza sie z
        # oczekiwanym SKIEROWANIE - to awaria, nie trafiona decyzja.
        "decyzja_ok": podsumowanie["decyzja"] == oczekiwany["decyzja"] and not stan.get("blad"),
        "powody_decyzji": podsumowanie["powody_decyzji"],
        "cytat_trafiony": bool(oczekiwane & zacytowane) if ma_paragraf else None,
        "recall_at_5": bool(oczekiwane & pobrane_5) if ma_paragraf else None,
        "kontrola_odrzucila": bool(kontrola) and not kontrola.get("ok", True),
        "dodatkowe_zapytanie": bool(stan.get("dodatkowe_zapytanie")),
        "blad": stan.get("blad"),
        "_czas_ms": stan.get("_czas_ms", 0.0),
        "_wywolania_llm": stan.get("wywolania_llm", 0),
        "_tokeny_we": sum(w.get("tokeny_we") or 0 for w in log),
        "_tokeny_wy": sum(w.get("tokeny_wy") or 0 for w in log),
        **rag,
    }


def przypadek_szkody_zgodny(wiersz: dict) -> bool:
    return wiersz["decyzja_ok"] and wiersz["cytat_trafiony"] is not False


def _odsetek(wiersze: list[dict], klucz: str) -> float:
    dotyczy = [w[klucz] for w in wiersze if w[klucz] is not None]
    return sum(dotyczy) / len(dotyczy) if dotyczy else 0.0


def metryki_szkod(metadane: dict, wiersze: list[dict]) -> dict[str, float]:
    metryki = {
        "przypadki_lacznie": float(len(wiersze)),
        "przypadki_ok": float(sum(przypadek_szkody_zgodny(w) for w in wiersze)),
        "decyzje_ok": float(sum(w["decyzja_ok"] for w in wiersze)),
        "cytat_trafiony": _odsetek(wiersze, "cytat_trafiony"),
        "recall_wyszukiwania_at_5": _odsetek(wiersze, "recall_at_5"),
        "kontrola_cytatow_odrzucila": float(sum(w["kontrola_odrzucila"] for w in wiersze)),
        "dodatkowe_zapytania": float(sum(w["dodatkowe_zapytanie"] for w in wiersze)),
        "czas_calkowity_s": float(metadane["czas_calkowity_ms"]) / 1000.0,
        "wywolania_llm": float(metadane["wywolania_llm_laczne"]),
        "tokeny_we": float(metadane["tokeny_we_laczne"]),
        "tokeny_wy": float(metadane["tokeny_wy_laczne"]),
    }
    if "koszt_llm_usd_szacunkowy" in metadane:
        metryki["koszt_llm_usd_szacunkowy"] = float(metadane["koszt_llm_usd_szacunkowy"])
    return metryki


def tabela_szkod_mlflow(wiersze: list[dict]) -> dict[str, list]:
    kolumny = ["id", "decyzja_oczekiwana", "decyzja_otrzymana", "decyzja_ok", "cytat_trafiony",
               "recall_at_5", "kontrola_odrzucila", "dodatkowe_zapytanie", "_czas_ms", "_tokeny_we", "_tokeny_wy"]
    return {k.lstrip("_"): [w.get(k) for w in wiersze] for k in kolumny}


def _znak(wartosc: bool | None) -> str:
    return "-" if wartosc is None else ("OK" if wartosc else "BLAD")


def tabela_ascii_szkod(wiersze: list[dict]) -> str:
    linie = [" | ".join(NAGLOWKI_TABELI_SZKOD)]
    for w in wiersze:
        decyzja = "OK" if w["decyzja_ok"] else f"BLAD({w['decyzja_otrzymana']}!={w['decyzja_oczekiwana']})"
        linie.append(" | ".join([
            w["id"], decyzja, _znak(w["cytat_trafiony"]), _znak(w["recall_at_5"]),
            "ODRZUCILA" if w["kontrola_odrzucila"] else "OK",
            "TAK" if w["dodatkowe_zapytanie"] else "-", f"{w['_czas_ms']:.0f}",
        ]))
    return "\n".join(linie)


def raport_md_szkod(nazwa_modelu: str, wiersze: list[dict], metadane: dict) -> str:
    metryki = metryki_szkod(metadane, wiersze)
    linie = [
        f"# Ewaluacja modulu szkodowego - model: {nazwa_modelu}",
        "",
        f"Wyszukiwarka: {metadane['wyszukiwarka']}, top_k: {TOP_K}, wersja OWU: {metadane['wersja_owu']}",
        f"Przypadki: {len(wiersze)}, decyzje zgodne: {metryki['decyzje_ok']:.0f}, "
        f"w pelni zgodne: {metryki['przypadki_ok']:.0f}",
        f"cytat_trafiony: {metryki['cytat_trafiony']:.2f}, "
        f"recall_wyszukiwania@5: {metryki['recall_wyszukiwania_at_5']:.2f}",
        f"Tokeny: wejscie {metadane['tokeny_we_laczne']}, wyjscie {metadane['tokeny_wy_laczne']}",
        "",
        "```",
        tabela_ascii_szkod(wiersze),
        "```",
        "",
        "## Pomylki",
    ]
    pomylki = [w for w in wiersze if not przypadek_szkody_zgodny(w)]
    if not pomylki:
        linie.append("Brak - wszystkie przypadki w pelni zgodne.")
    for w in pomylki:
        linie.append(
            f"- {w['id']}: decyzja oczekiwana={w['decyzja_oczekiwana']}, otrzymana={w['decyzja_otrzymana']} "
            f"{w['powody_decyzji']}; cytat_trafiony={w['cytat_trafiony']}"
            + (f"; BLAD: {w['blad']}" if w.get("blad") else "")
        )
    return "\n".join(linie)
