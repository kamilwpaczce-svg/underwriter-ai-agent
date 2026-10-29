"""Logowanie przebiegow ewaluacji do MLflow (Etap 8).

Jedna funkcja publiczna: `zaloguj_przebieg`. Import `mlflow` jest celowo lokalny
(wewnatrz funkcji), zeby `ewaluacja/uruchom.py` dalo sie zaimportowac i uruchomic
bez flagi `--mlflow` nawet gdy `mlflow` nie jest zainstalowany (obraz API w Dockerze
ma zostac lekki - patrz `requirements.txt` vs `requirements-ewaluacja.txt`).

Backend lokalny: SQLite pod `<ROOT>/mlruns.db` (domyslnie). Docelowo workspace Azure ML
jako serwer sledzenia - ustawiany przez `MLFLOW_TRACKING_URI` (patrz docs/ROZWOJ.md, Etap 8).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from ewaluacja.porownanie import przypadek_w_pelni_zgodny

ROOT = Path(__file__).resolve().parent.parent

NAZWA_EKSPERYMENTU_DOMYSLNA = "underwriter-agent-ewaluacja"
SCIEZKA_INSTRUKCJI = ROOT / "agent" / "instrukcje.py"
SCIEZKA_WYTYCZNYCH = ROOT / "wytyczne" / "wytyczne_mienie_v1.yaml"
SCIEZKA_OCZEKIWANE = ROOT / "dane" / "oczekiwane"
SCIEZKA_POROWNANIA = ROOT / "ewaluacja" / "porownanie.py"

# Limit dlugosci wartosci parametru MLflow - backendy wbudowane wspieraja do 6000 znakow,
# ale trzymamy sie nizej i przycinamy jawnie (zamiast polegac na cichym obcieciu MLflow),
# zeby zachowanie bylo przewidywalne niezaleznie od MLFLOW_TRUNCATE_LONG_VALUES.
_LIMIT_PARAMETRU = 480


def _sha256_12(tresc: bytes) -> str:
    return hashlib.sha256(tresc).hexdigest()[:12]


def _wersja_promptu() -> str:
    if not SCIEZKA_INSTRUKCJI.exists():
        return "nieznana"
    return _sha256_12(SCIEZKA_INSTRUKCJI.read_bytes())


def _wersja_wytycznych() -> str:
    if not SCIEZKA_WYTYCZNYCH.exists():
        return "nieznana"
    return _sha256_12(SCIEZKA_WYTYCZNYCH.read_bytes())


def _wersja_porownania() -> str:
    # Zmiana sposobu liczenia (np. normalizacja "ul." 12.10) zmienia wynik bez zmiany modelu.
    if not SCIEZKA_POROWNANIA.exists():
        return "nieznana"
    return _sha256_12(SCIEZKA_POROWNANIA.read_bytes())


def _wersja_wzorca() -> str:
    pliki = sorted(SCIEZKA_OCZEKIWANE.glob("*.json"))
    if not pliki:
        return "nieznana"
    tresc = b"".join(p.read_bytes() for p in pliki)
    return _sha256_12(tresc)


def _git_commit() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "brak"
    if not sha:
        return "brak"
    try:
        brudne = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        brudne = ""
    return f"{sha}-dirty" if brudne else sha


def _przytnij(tekst: str, limit: int = _LIMIT_PARAMETRU) -> str:
    if len(tekst) <= limit:
        return tekst
    return tekst[: limit - 3] + "..."


def _przygotuj_parametry(parametry: dict[str, Any]) -> dict[str, Any]:
    """Dopisuje wersje promptu/wytycznych/wzorca/git_commit, gdy wywolujacy ich nie podal
    (np. import historii podaje jawnie "nieznana" zamiast liczyc je z BIEZACEGO stanu repo,
    ktory nie musi odpowiadac stanowi w chwili historycznego przebiegu)."""
    parametry = dict(parametry)
    parametry.setdefault("wersja_promptu", _wersja_promptu())
    parametry.setdefault("wersja_wytycznych", _wersja_wytycznych())
    parametry.setdefault("wersja_wzorca", _wersja_wzorca())
    parametry.setdefault("wersja_porownania", _wersja_porownania())
    parametry.setdefault("git_commit", _git_commit())

    przypadki = parametry.get("przypadki")
    if isinstance(przypadki, (list, tuple)):
        przypadki = ",".join(str(x) for x in przypadki)
    if isinstance(przypadki, str):
        parametry["przypadki"] = _przytnij(przypadki)

    return {k: v for k, v in parametry.items() if v is not None}


def _oblicz_metryki(metadane: dict[str, Any], wiersze: list[dict[str, Any]]) -> dict[str, float]:
    """Metryki agregatowe licza sie z wierszy per-przypadek (nazwy kluczy z
    ewaluacja/porownanie.py), nie zgadywane - dziala identycznie dla swiezego przebiegu
    (ewaluacja/uruchom.py) i dla historycznych plikow JSON (ewaluacja/import_historii.py),
    bo oba maja ten sam ksztalt {"metadane": ..., "przypadki": [...]}."""
    przypadki_lacznie = len(wiersze)
    przypadki_ok = sum(1 for w in wiersze if przypadek_w_pelni_zgodny(w))
    pola_trafione = sum(w.get("pola_trafione", 0) or 0 for w in wiersze)
    pola_wszystkie = sum(w.get("pola_wszystkie", 0) or 0 for w in wiersze)
    decyzje_llm_ok = sum(1 for w in wiersze if w.get("decyzja_llm_ok"))
    reguly_llm_ok = sum(1 for w in wiersze if w.get("reguly_llm_ok"))
    silnik_na_polach_llm_ok = sum(1 for w in wiersze if w.get("decyzja_silnika_na_polach_llm_ok"))
    podejrzane_ok = sum(1 for w in wiersze if w.get("podejrzane_instrukcje_ok"))

    czas_calkowity_ms = metadane.get("czas_calkowity_ms")
    if czas_calkowity_ms is None:
        czas_calkowity_ms = sum(w.get("_czas_ms", 0.0) or 0.0 for w in wiersze)

    wywolania_llm = metadane.get("wywolania_llm_laczne")
    if wywolania_llm is None:
        wywolania_llm = sum(w.get("_wywolania_llm", 0) or 0 for w in wiersze)

    tokeny_we = metadane.get("tokeny_we_laczne")
    if tokeny_we is None:
        tokeny_we = sum(w.get("_tokeny_we", 0) or 0 for w in wiersze)

    tokeny_wy = metadane.get("tokeny_wy_laczne")
    if tokeny_wy is None:
        tokeny_wy = sum(w.get("_tokeny_wy", 0) or 0 for w in wiersze)

    metryki = {
        "przypadki_ok": float(przypadki_ok),
        "przypadki_lacznie": float(przypadki_lacznie),
        "odsetek_ok": (przypadki_ok / przypadki_lacznie) if przypadki_lacznie else 0.0,
        "pola_trafione": float(pola_trafione),
        "pola_wszystkie": float(pola_wszystkie),
        "odsetek_pol": (pola_trafione / pola_wszystkie) if pola_wszystkie else 0.0,
        "decyzje_llm_ok": float(decyzje_llm_ok),
        "reguly_llm_ok": float(reguly_llm_ok),
        "silnik_na_polach_llm_ok": float(silnik_na_polach_llm_ok),
        "podejrzane_ok": float(podejrzane_ok),
        "czas_calkowity_s": float(czas_calkowity_ms) / 1000.0,
        "wywolania_llm": float(wywolania_llm),
        "tokeny_we": float(tokeny_we),
        "tokeny_wy": float(tokeny_wy),
    }
    # Opcjonalne (tylko dostawca azure) - nazwy metryk wg SPEC_ETAP8, nazwy pol w metadane
    # z ewaluacja/uruchom.py::_zapisz_wyniki/main sa inne (np. ocr_stron_lacznie).
    if "koszt_llm_usd_szacunkowy" in metadane:
        metryki["koszt_llm_usd_szacunkowy"] = float(metadane["koszt_llm_usd_szacunkowy"])
    if "ocr_stron_lacznie" in metadane:
        metryki["ocr_stron"] = float(metadane["ocr_stron_lacznie"])
    if "ocr_wywolania_sieciowe" in metadane:
        metryki["ocr_wywolania_sieciowe"] = float(metadane["ocr_wywolania_sieciowe"])
    if "ocr_trafienia_cache" in metadane:
        metryki["ocr_trafienia_cache"] = float(metadane["ocr_trafienia_cache"])
    return metryki


def _tabela_przypadkow(wiersze: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """Tabela per przypadek dla mlflow.log_table - kolumny wg SPEC_ETAP8 (id, typ_ok, pola,
    decyzja oczekiwana/otrzymana, reguly ok, czas, tokeny), zeby w UI bylo widac KTORY
    przypadek sie zmienil miedzy przebiegami."""
    return {
        "id": [w.get("id") for w in wiersze],
        "typ_dokumentu_ok": [w.get("typ_dokumentu_ok") for w in wiersze],
        "pola_trafione": [w.get("pola_trafione") for w in wiersze],
        "pola_wszystkie": [w.get("pola_wszystkie") for w in wiersze],
        "decyzja_oczekiwana": [w.get("decyzja_llm_oczekiwana") for w in wiersze],
        "decyzja_otrzymana": [w.get("decyzja_llm_otrzymana") for w in wiersze],
        "reguly_llm_ok": [w.get("reguly_llm_ok") for w in wiersze],
        "czas_ms": [w.get("_czas_ms") for w in wiersze],
        "tokeny_we": [w.get("_tokeny_we") for w in wiersze],
        "tokeny_wy": [w.get("_tokeny_wy") for w in wiersze],
    }


def ustaw_sledzenie() -> tuple[str, str]:
    """Ustawia tracking URI (MLFLOW_TRACKING_URI albo SQLite lokalny) i eksperyment
    (MLFLOW_EXPERIMENT_NAME albo domyslny). Wspolne dla zaloguj_przebieg i dla
    ewaluacja/uruchom.py::main przy wlaczaniu sladow (--mlflow-trace), gdzie przebieg
    (a wiec i run) musi zaczac sie PRZED budowa grafu, nie dopiero przy logowaniu."""
    import mlflow

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI") or f"sqlite:///{(ROOT / 'mlruns.db').as_posix()}"
    mlflow.set_tracking_uri(tracking_uri)
    nazwa_eksperymentu = os.environ.get("MLFLOW_EXPERIMENT_NAME", NAZWA_EKSPERYMENTU_DOMYSLNA)
    mlflow.set_experiment(nazwa_eksperymentu)
    return tracking_uri, nazwa_eksperymentu


def _tagi_przebiegu(
    czesciowy: bool, zrodlo: str, tagi_dodatkowe: dict[str, str] | None, wariant: str | None
) -> dict[str, str]:
    """Tagi runu. Etap 24: `wariant` (jeden / wieloagentowy) jako osobny argument - brak = bez tagu."""
    tagi = {"czesciowy": "true" if czesciowy else "false", "zrodlo": zrodlo}
    if tagi_dodatkowe:
        tagi.update(tagi_dodatkowe)
    if wariant:
        tagi["wariant"] = wariant
    return tagi


def zaloguj_przebieg(
    parametry: dict[str, Any],
    metadane: dict[str, Any],
    wiersze: list[dict[str, Any]],
    artefakty: list[Path],
    czesciowy: bool,
    zrodlo: str = "uruchom",
    czas_startu: float | None = None,
    tagi_dodatkowe: dict[str, str] | None = None,
    metryki: dict[str, float] | None = None,
    tabela: dict[str, list[Any]] | None = None,
    wariant: str | None = None,
) -> str:
    """Loguje jeden przebieg ewaluacji jako run MLflow. Zwraca run_id.

    `czas_startu`: znacznik czasu UNIX (sekundy) startu runu - gdy podany (import historii),
    tworzy run z tym czasem startu zamiast "teraz". Gdy jest juz aktywny run MLflow (np.
    `--mlflow-trace` otworzyl go przed budowa grafu, zeby powiazac slady autologowania), loguje
    sie do NIEGO i nie zamyka go - zamkniecie nalezy wtedy do wywolujacego.

    `metryki`/`tabela` (Etap 10, modul szkody): gotowe metryki i tabela per przypadek zamiast
    liczonych z wierszy wnioskow; brak = dotychczasowe zachowanie.
    """
    import mlflow
    from mlflow import MlflowClient

    ustaw_sledzenie()

    parametry_gotowe = _przygotuj_parametry(parametry)
    if metryki is None:
        metryki = _oblicz_metryki(metadane, wiersze)
    if tabela is None:
        tabela = _tabela_przypadkow(wiersze)
    tagi = _tagi_przebiegu(czesciowy, zrodlo, tagi_dodatkowe, wariant)

    aktywny = mlflow.active_run()
    if aktywny is not None:
        kontekst = nullcontext(aktywny)
    else:
        nazwa_eksperymentu = os.environ.get("MLFLOW_EXPERIMENT_NAME", NAZWA_EKSPERYMENTU_DOMYSLNA)
        eksperyment = mlflow.get_experiment_by_name(nazwa_eksperymentu)
        start_time_ms = int((czas_startu if czas_startu is not None else time.time()) * 1000)
        utworzony = MlflowClient().create_run(eksperyment.experiment_id, start_time=start_time_ms)
        kontekst = mlflow.start_run(run_id=utworzony.info.run_id)

    with kontekst as run:
        mlflow.log_params(parametry_gotowe)
        mlflow.log_metrics(metryki)
        mlflow.log_table(data=tabela, artifact_file="przypadki.json")
        for artefakt in artefakty:
            mlflow.log_artifact(str(artefakt))
        mlflow.set_tags(tagi)
        run_id = run.info.run_id

    return run_id
