"""Ewaluacja RAG szkodowego sedzia LLM w Azure AI Foundry (Etap 14).

Czyste funkcje (JSONL, mapowanie, parsowanie, tabela rozjazdow) nie importuja
azure-ai-evaluation - pakiet jest tylko w .venv-ewaluacja, nie w CI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from ewaluacja.szkody import KLUCZE_RAG

KLUCZE_JSONL = ("id", *KLUCZE_RAG)  # jedno zrodlo prawdy o polach RAG (przeglad koncowy m4)
WEJSCIA = {
    "groundedness": ("query", "context", "response"),
    "relevance": ("query", "response"),
    "retrieval": ("query", "context"),
    "response_completeness": ("response", "ground_truth"),
}


class BrakPolRag(ValueError):
    """Plik wynikow sprzed Etapu 14 - brak query/context/response/ground_truth."""


def zapisz_jsonl(wiersze: list[dict], sciezka: Path) -> int:
    """Tylko wiersze z ocena LLM (przeglad p. 6) - wiersze z regul nie maja czego sedziowac (n/d w tabeli)."""
    for w in wiersze:
        brak = [k for k in KLUCZE_JSONL if k not in w]
        if brak:
            raise BrakPolRag(f"{w.get('id')}: brak {brak} - uruchom ponownie --modul szkody (Etap 14).")
    do_sedziego = [w for w in wiersze if w["ocenia_llm"]]
    sciezka.write_text(
        "".join(json.dumps({k: w[k] for k in KLUCZE_JSONL}, ensure_ascii=False) + "\n" for w in do_sedziego),
        encoding="utf-8",
    )
    return len(do_sedziego)


def mapowanie_kolumn() -> dict[str, dict]:
    return {n: {"column_mapping": {k: f"${{data.{k}}}" for k in wejscia}} for n, wejscia in WEJSCIA.items()}


def zbuduj_ewaluatory(model_config: dict, credential, rozumujacy: bool) -> dict[str, Callable]:
    from azure.ai.evaluation import (GroundednessEvaluator, RelevanceEvaluator,
                                     ResponseCompletenessEvaluator, RetrievalEvaluator)
    opcje = {"credential": credential, "is_reasoning_model": rozumujacy}
    return {
        "groundedness": GroundednessEvaluator(model_config, **opcje),
        "relevance": RelevanceEvaluator(model_config, **opcje),
        "retrieval": RetrievalEvaluator(model_config, **opcje),
        # DSZ0 (pkt 1): is_reasoning_model przyjmowany takze przez ResponseCompletenessEvaluator (**kwargs)
        "response_completeness": ResponseCompletenessEvaluator(model_config, **opcje),
    }


def oceny_z_wyniku(wynik: dict) -> dict[str, dict]:
    oceny: dict[str, dict] = {}
    zdublowane: set[str] = set()
    for i, wiersz in enumerate(wynik.get("rows") or []):
        id_ = wiersz.get("inputs.id") or f"wiersz{i}"
        if id_ in oceny:  # dwa wiersze jednego przypadku: ktory jest wlasciwy? - zaden (wiersz bez oceny => kod 6)
            zdublowane.add(id_)
            continue
        oceny[id_] = {}
        for n in WEJSCIA:
            liczba = wiersz.get(f"outputs.{n}.{n}")
            wynik_tekst = wiersz.get(f"outputs.{n}.{n}_result")
            # bool to podklasa int; NaN != NaN; _result spoza pass/fail = brak oceny (nie cichy FAIL, Etap 14 recenzja 2+3)
            if (isinstance(liczba, (int, float)) and not isinstance(liczba, bool) and liczba == liczba
                    and wynik_tekst in ("pass", "fail")):
                oceny[id_][n] = {"wynik": float(liczba), "pass": wynik_tekst == "pass"}
    for id_ in zdublowane:
        oceny[id_] = {}
    return oceny


KOLUMNY_DOZWOLONE = ("inputs.id", "inputs.ocenia_llm")
SUFIKSY_DOZWOLONE = ("", "_score", "_result", "_passed", "_threshold", "_status")  # BEZ _reason (tresc sedziego)
PROPERTIES_DOZWOLONE = ("prompt_tokens", "completion_tokens", "model", "finish_reason")
SKALARY = (str, int, float, bool, type(None))


def _liczba(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def oczysc_sedzia_json(wynik: dict) -> dict:
    """Kopia wyniku `evaluate` do MLflow - LISTA DOZWOLONYCH pol (ustalenie sesji R1, runda 1 I1), nie zakazanych:
    nowe pole SDK nie wycieknie samo. Najwyzszy poziom: rows, metrics (tylko liczby), studio_url. Wiersz:
    inputs.id, inputs.ocenia_llm i outputs.<alias>.<metryka>{,_score,_result,_passed,_threshold,_status};
    z `*_properties` tylko liczniki tokenow, model i finish_reason. `*_reason` (uzasadnienie sedziego)
    nie przechodzi. Nie modyfikuje wejscia - pelny plik zostaje lokalnie."""
    dozwolone = set(KOLUMNY_DOZWOLONE)
    dozwolone |= {f"outputs.{n}.{n}{suf}" for n in WEJSCIA for suf in SUFIKSY_DOZWOLONE}
    wlasciwosci = {f"outputs.{n}.{n}_properties" for n in WEJSCIA}
    czysty: dict = {}
    if "rows" in wynik:
        czysty["rows"] = []
        for wiersz in wynik["rows"] or []:
            nowy: dict = {}
            for k, v in wiersz.items():
                if k in dozwolone and isinstance(v, SKALARY):
                    nowy[k] = v
                elif k in wlasciwosci and isinstance(v, dict):
                    nowy[k] = {kk: vv for kk, vv in v.items() if kk in PROPERTIES_DOZWOLONE and isinstance(vv, SKALARY)}
            czysty["rows"].append(nowy)
    if isinstance(wynik.get("metrics"), dict):
        czysty["metrics"] = {k: v for k, v in wynik["metrics"].items() if _liczba(v)}
    if "studio_url" in wynik and isinstance(wynik["studio_url"], (str, type(None))):
        czysty["studio_url"] = wynik["studio_url"]
    return czysty


def klasyfikuj(det_ok: bool, sedzia_ok: bool | None) -> str:
    if sedzia_ok is None:
        return "n/d"
    if det_ok == sedzia_ok:
        return "zgoda_ok" if det_ok else "zgoda_blad"
    return "sedzia_poblazliwy" if sedzia_ok else "sedzia_surowy"


def wiersze_bez_oceny(wiersze: list[dict], oceny: dict[str, dict]) -> list[str]:
    return [w["id"] for w in wiersze if w["ocenia_llm"] and len(oceny.get(w["id"]) or {}) < len(WEJSCIA)]


KLASA_Z = "response_completeness"  # jedyny ewaluator porownujacy z ground_truth (przeglad p. 5)


def tabela_rozjazdow(wiersze: list[dict], oceny: dict[str, dict]) -> list[dict]:
    """Wszystkie wiersze (12), takze n/d - JSONL ma tylko ocenia_llm, tabela pokazuje calosc."""
    tabela = []
    for w in wiersze:
        o = oceny.get(w["id"]) or {}
        sedzia_ok = o[KLASA_Z]["pass"] if (w["ocenia_llm"] and KLASA_Z in o) else None
        det_ok = bool(w["decyzja_ok"]) and w.get("cytat_trafiony") is not False
        tabela.append({"id": w["id"], "decyzja_ok": w["decyzja_ok"], "cytat_trafiony": w.get("cytat_trafiony"),
                       **{n: o.get(n) for n in WEJSCIA}, "klasa": klasyfikuj(det_ok, sedzia_ok)})
    return tabela


def metryki_sedziego(tabela: list[dict]) -> dict[str, float]:
    """Srednie `wynik` per ewaluator tylko po wierszach z klasa != n/d (wiersze bez oceny LLM
    nie zanizaja ani nie zawyzaja sredniej). Ewaluator bez zadnej oceny - brak klucza, nie 0."""
    ocenione = [t for t in tabela if t["klasa"] != "n/d"]
    metryki: dict[str, float] = {
        "sedzia_ocenione": float(len(ocenione)),
        "sedzia_rozjazdy": float(sum(t["klasa"].startswith("sedzia_") for t in ocenione)),
    }
    for n in WEJSCIA:
        liczby = [t[n]["wynik"] for t in ocenione if t.get(n)]
        if liczby:
            metryki[f"sedzia_{n}"] = sum(liczby) / len(liczby)
    return metryki


def tabela_mlflow(tabela: list[dict]) -> dict[str, list]:
    """Plaskie kolumny (skalary) dla `zaloguj_przebieg(tabela=...)`."""
    kolumny: dict[str, list] = {
        "id": [t["id"] for t in tabela],
        "klasa": [t["klasa"] for t in tabela],
        "decyzja_ok": [t["decyzja_ok"] for t in tabela],
        "cytat_trafiony": [t["cytat_trafiony"] for t in tabela],
    }
    for n in WEJSCIA:
        kolumny[n] = [t[n]["wynik"] if t.get(n) else None for t in tabela]
        kolumny[f"{n}_pass"] = [t[n]["pass"] if t.get(n) else None for t in tabela]
    return kolumny


def _komorka(ocena: dict | None) -> str:
    if not ocena:
        return "-"
    return f"{ocena['wynik']:.1f} {'pass' if ocena['pass'] else 'FAIL'}"


def _znak_cytatu(wartosc: bool | None) -> str:
    return "-" if wartosc is None else ("tak" if wartosc else "nie")


def raport_rozjazdow_md(tabela: list[dict], klucz: str, studio_url: str | None) -> str:
    linie = [
        f"# Sedzia LLM vs metryka deterministyczna - {klucz}",
        "",
        f"Portal Foundry: {studio_url or 'brak (przebieg bez Foundry)'}",
        "",
        "| ID | decyzja_ok | cytat | G | Rel | Ret | Compl | klasa |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for t in tabela:
        linie.append(
            f"| {t['id']} | {'tak' if t['decyzja_ok'] else 'nie'} | {_znak_cytatu(t['cytat_trafiony'])} | "
            f"{_komorka(t['groundedness'])} | {_komorka(t['relevance'])} | {_komorka(t['retrieval'])} | "
            f"{_komorka(t['response_completeness'])} | {t['klasa']} |")
    return "\n".join(linie) + "\n"
