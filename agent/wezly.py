"""Wezly grafu LangGraph. Stan grafu + funkcje wezlow (kod i wywolania LLM)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, TypedDict

from langgraph.types import interrupt

from agent.decyzje_szkody import orkiestracja_do_panelu, podsumowanie_szkody
from agent.model import ModelAgenta
from agent.wczytywanie import CzesciDokumentu, wczytaj_plik

_GENERATOR_DIR = Path(__file__).resolve().parent.parent / "generator"
sys.path.insert(0, str(_GENERATOR_DIR))
from nip import normalizuj_nip, nip_poprawny  # noqa: E402
from reguly import oblicz_decyzje  # noqa: E402

LIMIT_WYWOLAN_LLM = 6
_WZORZEC_DATY_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class StanGrafu(TypedDict, total=False):
    plik: str
    czesci: CzesciDokumentu | None
    typ_dokumentu: str | None
    pola: dict | None
    podejrzane_instrukcje: bool | None
    problemy_walidacji: list[str]
    rekomendacja: dict | None
    decyzja_silnika: dict | None
    zgodnosc: bool | None
    decyzja_koncowa: str | None
    zatwierdzil: str | None
    wywolania_llm: int
    log: list[dict]
    blad: str | None
    # Etap 10: galaz SZKODA
    wynik_polisy: dict | None
    fragmenty_owu: list[dict] | None
    ocena_pokrycia: dict | None
    dodatkowe_zapytanie: str | None
    kontrola_cytatow: dict | None
    # Etap 15: sygnal ryzyka z modelu scikit-learn (tylko dla czlowieka, nie zmienia decyzji)
    ryzyko_szkody: dict
    # Etap 23: zdjecie szkody (vision) - sygnal pomocniczy dla likwidatora, nie zmienia decyzji ani trasy
    zdjecia: list[str]  # wejscie grafu: sciezki plikow (analizowane tylko pierwsze)
    sygnal_zdjecia: dict
    # Etap 24: wariant wieloagentowy (agent/supervisor.py); w wariancie `jeden` pola nieustawione
    wywolania_supervisora: int  # kroki supervisora z LLM (osobno od `wywolania_llm` agentow)
    korekty_supervisora: int
    trasa_agentow: list[str]
    uzasadnienia_supervisora: list[str]


def _wpis_logu(wezel: str, czas_ms: float, tokeny_we: int | None = None, tokeny_wy: int | None = None) -> dict:
    return {"wezel": wezel, "czas_ms": round(czas_ms, 1), "tokeny_we": tokeny_we, "tokeny_wy": tokeny_wy}


def _wywolaj_model(stan: StanGrafu, nazwa_wezla: str, funkcja) -> tuple[Any, dict]:
    """Wspolna obsluga wywolan LLM: limit, jedna ponowna proba, log.

    `funkcja` to callable bez argumentow zwracajace (wynik, MetadaneWywolania).
    Zwraca (wynik_lub_None, czesciowa_aktualizacja_stanu). Gdy wynik is None,
    aktualizacja zawiera klucz "blad" i wezel wywolujacy ma zwrocic ja wprost
    (routing grafu skieruje do zatwierdzenia).
    """
    log = list(stan.get("log", []))
    wywolania = stan.get("wywolania_llm", 0)
    ostatni_blad: str | None = None

    for proba in range(2):
        if wywolania >= LIMIT_WYWOLAN_LLM:
            return None, {
                "blad": f"Przekroczono limit {LIMIT_WYWOLAN_LLM} wywolan LLM na dokument (wezel: {nazwa_wezla}).",
                "log": log,
                "wywolania_llm": wywolania,
            }
        start = time.monotonic()
        try:
            wynik, metadane = funkcja()
        except Exception as e:  # noqa: BLE001 - celowo szerokie: kazdy blad modelu liczy sie jako proba
            wywolania += 1
            czas_ms = (time.monotonic() - start) * 1000
            log.append(_wpis_logu(f"{nazwa_wezla}_proba{proba + 1}_blad", czas_ms))
            ostatni_blad = type(e).__name__
            continue
        czas_ms = (time.monotonic() - start) * 1000
        wywolania += 1
        log.append(_wpis_logu(nazwa_wezla, czas_ms, metadane.tokeny_we, metadane.tokeny_wy))
        return wynik, {"log": log, "wywolania_llm": wywolania}

    return None, {
        "blad": f"Blad wezla '{nazwa_wezla}' po 2 probach (typ bledu: {ostatni_blad}).",
        "log": log,
        "wywolania_llm": wywolania,
    }


# ---------------------------------------------------------------------------
# Wezly
# ---------------------------------------------------------------------------

def wezel_wczytaj(stan: StanGrafu) -> dict:
    start = time.monotonic()
    czesci = wczytaj_plik(stan["plik"])
    log = list(stan.get("log", []))
    log.append(_wpis_logu("wczytaj", (time.monotonic() - start) * 1000))
    return {"czesci": czesci, "log": log}


def wezel_klasyfikuj(stan: StanGrafu, model: ModelAgenta) -> dict:
    wynik, aktualizacja = _wywolaj_model(stan, "klasyfikuj", lambda: model.klasyfikuj(stan["czesci"]))
    if wynik is None:
        return aktualizacja
    aktualizacja["typ_dokumentu"] = wynik.typ_dokumentu
    return aktualizacja


def wezel_zakoncz_inny(stan: StanGrafu) -> dict:
    return {"decyzja_koncowa": "NIE_DOTYCZY"}


def wezel_ekstrahuj(stan: StanGrafu, model: ModelAgenta) -> dict:
    wynik, aktualizacja = _wywolaj_model(stan, "ekstrahuj", lambda: model.ekstrahuj(stan["czesci"]))
    # Etap 3: 'ekstrahuj' to ostatni wezel potrzebujacy bajtow dokumentu. Czyscimy
    # 'czesci' w stanie, zeby checkpointer (Postgres) nie powielal dokumentu w kazdym
    # kolejnym checkpoincie (wczytaj/klasyfikuj/ekstrahuj/waliduj/ocen/kontrola/
    # zatwierdzenie zapisuja po jednym checkpoincie kazdy) - dokument i tak jest w Blob.
    # None, nie pusta CzesciDokumentu: ostatni checkpoint bez wlasnych klas = wznowienie
    # po restarcie nie zalezy od tego, czy serializer zaakceptuje niezarejestrowany typ.
    aktualizacja["czesci"] = None
    if wynik is None:
        return aktualizacja
    aktualizacja["pola"] = wynik.pola.model_dump()
    aktualizacja["podejrzane_instrukcje"] = wynik.podejrzane_instrukcje
    return aktualizacja


def wezel_waliduj(stan: StanGrafu) -> dict:
    start = time.monotonic()
    pola = stan.get("pola") or {}
    problemy: list[str] = []

    nip = pola.get("nip")
    if nip:
        nip_znormalizowany = normalizuj_nip(str(nip))
        if len(nip_znormalizowany) != 10 or not nip_poprawny(nip_znormalizowany):
            problemy.append(f"NIP '{nip}' ma niepoprawna sume kontrolna lub niepoprawna dlugosc.")

    for nazwa_pola in ("okres_od", "okres_do", "data_wniosku"):
        wartosc = pola.get(nazwa_pola)
        if wartosc and not _WZORZEC_DATY_ISO.match(str(wartosc)):
            problemy.append(f"Pole '{nazwa_pola}' nie jest w formacie ISO (RRRR-MM-DD): '{wartosc}'.")

    for nazwa_pola in ("su_budynki", "su_maszyny", "su_zapasy"):
        wartosc = pola.get(nazwa_pola)
        if isinstance(wartosc, (int, float)) and wartosc < 0:
            problemy.append(f"Pole '{nazwa_pola}' ma ujemna wartosc: {wartosc}.")

    log = list(stan.get("log", []))
    log.append(_wpis_logu("waliduj", (time.monotonic() - start) * 1000))
    return {"problemy_walidacji": problemy, "log": log}


def wezel_ocen(stan: StanGrafu, model: ModelAgenta, instrukcje: str) -> dict:
    pola_json = json.dumps(stan.get("pola"), ensure_ascii=False, sort_keys=True)
    problemy = stan.get("problemy_walidacji", [])
    wynik, aktualizacja = _wywolaj_model(
        stan, "ocen", lambda: model.ocen(instrukcje, pola_json, problemy)
    )
    if wynik is None:
        return aktualizacja
    aktualizacja["rekomendacja"] = {
        "decyzja": wynik.decyzja,
        "reguly": wynik.reguly,
        "uzasadnienie": [u.model_dump() for u in wynik.uzasadnienia],
    }
    return aktualizacja


def wezel_kontrola(stan: StanGrafu, wytyczne: dict) -> dict:
    start = time.monotonic()
    wynik_silnika = oblicz_decyzje(stan.get("pola") or {}, wytyczne)
    rekomendacja = stan.get("rekomendacja") or {}
    zgodnosc = rekomendacja.get("decyzja") == wynik_silnika["decyzja"] and sorted(
        rekomendacja.get("reguly", [])
    ) == sorted(wynik_silnika["reguly"])

    log = list(stan.get("log", []))
    log.append(_wpis_logu("kontrola", (time.monotonic() - start) * 1000))
    return {"decyzja_silnika": wynik_silnika, "zgodnosc": zgodnosc, "log": log}


def wezel_zatwierdzenie(stan: StanGrafu) -> dict:
    if stan.get("typ_dokumentu") == "SZKODA":
        odpowiedz = interrupt(podsumowanie_szkody(stan))
        return {
            "decyzja_koncowa": odpowiedz.get("decyzja"),
            "zatwierdzil": odpowiedz.get("kto"),
        }
    podsumowanie = {
        "plik": stan.get("plik"),
        "typ_dokumentu": stan.get("typ_dokumentu"),
        "pola": stan.get("pola"),
        "podejrzane_instrukcje": stan.get("podejrzane_instrukcje"),
        "problemy_walidacji": stan.get("problemy_walidacji"),
        "rekomendacja": stan.get("rekomendacja"),
        "decyzja_silnika": stan.get("decyzja_silnika"),
        "zgodnosc": stan.get("zgodnosc"),
        "blad": stan.get("blad"),
    }
    orkiestracja = orkiestracja_do_panelu(stan)
    if orkiestracja is not None:  # tylko wariant wieloagentowy; w `jeden` panel bez zmian
        podsumowanie["orkiestracja"] = orkiestracja
    odpowiedz = interrupt(podsumowanie)
    return {
        "decyzja_koncowa": odpowiedz.get("decyzja"),
        "zatwierdzil": odpowiedz.get("kto"),
    }


# ---------------------------------------------------------------------------
# Routing warunkowy
# ---------------------------------------------------------------------------

def po_klasyfikacji(stan: StanGrafu) -> str:
    if stan.get("blad"):
        return "zatwierdzenie"
    if stan.get("typ_dokumentu") == "INNY":
        return "zakoncz_inny"
    if stan.get("typ_dokumentu") == "SZKODA":
        return "ekstrahuj_szkode"
    return "ekstrahuj"


def po_ekstrakcji(stan: StanGrafu) -> str:
    return "zatwierdzenie" if stan.get("blad") else "waliduj"


def po_ocenie(stan: StanGrafu) -> str:
    return "zatwierdzenie" if stan.get("blad") else "kontrola"
