"""Jednorazowy import historycznych plikow ewaluacja/wyniki/*.json do MLflow (Etap 8).

Kazdy plik staje sie runem z tagiem zrodlo=import. Parametry, ktorych stare pliki nie
zawieraja (wersja_promptu, wersja_wytycznych, wersja_wzorca, wersja_porownania, git_commit) dostaja wartosc
"nieznana" - NIE sa liczone z biezacego stanu repo, bo ten nie musi odpowiadac stanowi
repo w chwili historycznego przebiegu.

Uzycie:
    python ewaluacja/import_historii.py                 # pomija pliki *_atrapa.json
    python ewaluacja/import_historii.py --z-atrapa       # importuje rowniez atrapy

Idempotentne: plik juz zaimportowany (tag plik_zrodlowy == nazwa pliku) nie jest importowany
ponownie.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ewaluacja.mlflow_log import (  # noqa: E402
    NAZWA_EKSPERYMENTU_DOMYSLNA,
    ustaw_sledzenie,
    zaloguj_przebieg,
)

WYNIKI_DIR = Path(__file__).resolve().parent / "wyniki"
KATALOG_WZORCA = "archiwum_wzorzec_v1"

WZORZEC_ZNACZNIKA = re.compile(r"^(\d{8})-(\d{4})_")

# Etap 14: kopie i wyniki sedziego w wyniki/ to nie przebiegi - nie wchodza do MLflow jako runy historyczne.
POMIJANE_SUFIKSY = ("_mlflow", "_sedzia", "_sedzia_mlflow")

PARAMETRY_NIEZNANE = {
    "wersja_promptu": "nieznana",
    "wersja_wytycznych": "nieznana",
    "wersja_wzorca": "nieznana",
    "wersja_porownania": "nieznana",
    "git_commit": "nieznana",
}


def _znacznik_z_nazwy(nazwa_pliku: str) -> float | None:
    """Parsuje czas startu (sekundy unix) ze znacznika YYYYMMDD-HHMM w nazwie pliku.
    Zwraca None, gdy nazwa nie pasuje - wtedy wywolujacy uzywa biezacego czasu."""
    dopasowanie = WZORZEC_ZNACZNIKA.match(nazwa_pliku)
    if not dopasowanie:
        return None
    data, godzina = dopasowanie.groups()
    try:
        struct = time.strptime(f"{data}{godzina}", "%Y%m%d%H%M")
        return time.mktime(struct)
    except ValueError:
        return None


def _juz_zaimportowany(nazwa_pliku: str) -> bool:
    import mlflow
    from mlflow import MlflowClient

    nazwa_eksperymentu = os.environ.get("MLFLOW_EXPERIMENT_NAME", NAZWA_EKSPERYMENTU_DOMYSLNA)
    eksperyment = mlflow.get_experiment_by_name(nazwa_eksperymentu)
    if eksperyment is None:
        return False
    runy = MlflowClient().search_runs(
        [eksperyment.experiment_id],
        filter_string=f"tags.plik_zrodlowy = '{nazwa_pliku}'",
        max_results=1,
    )
    return len(runy) > 0


def _pliki_do_importu(z_atrapa: bool) -> list[Path]:
    pliki = []
    for plik in sorted(WYNIKI_DIR.glob("*.json")):
        if KATALOG_WZORCA in plik.parts:
            continue
        if plik.stem.endswith(POMIJANE_SUFIKSY):
            continue
        if plik.stem.endswith("_atrapa") and not z_atrapa:
            continue
        pliki.append(plik)
    return pliki


def importuj(z_atrapa: bool = False) -> list[str]:
    """Importuje historyczne pliki wynikow jako runy MLflow. Zwraca liste run_id
    utworzonych w tym wywolaniu (pliki juz zaimportowane sa pomijane, wiec ich run_id
    nie trafiaja na te liste)."""
    ustaw_sledzenie()

    from ewaluacja.szkody import KLUCZE_RAG  # lazy: szkody ciagnie langgraph, import_historii nie musi

    run_idy: list[str] = []
    for plik in _pliki_do_importu(z_atrapa):
        if _juz_zaimportowany(plik.name):
            print(f"Pomijam (juz zaimportowany): {plik.name}")
            continue

        dane = json.loads(plik.read_text(encoding="utf-8"))
        wiersze = dane.get("przypadki") if isinstance(dane, dict) else None
        # Etap 14, fail-closed na tresc: wiersze z polami RAG (query/context/response/ground_truth)
        # albo plik bez listy `przypadki` (np. wynik sedziego) nigdy nie trafiaja do MLflow.
        if not isinstance(wiersze, list) or any(
                isinstance(w, dict) and set(KLUCZE_RAG) & w.keys() for w in wiersze):
            print(f"Pomijam (Etap 14+: pola RAG albo nie plik wynikow): {plik.name}")
            continue
        metadane = dane.get("metadane", {})
        nazwa_modelu = dane.get("model", "nieznany")

        czas_startu = _znacznik_z_nazwy(plik.name)

        parametry = dict(PARAMETRY_NIEZNANE)
        parametry["dostawca"] = "nieznana"
        parametry["model"] = nazwa_modelu
        parametry["myslenie"] = None
        parametry["przypadki"] = [w.get("id") for w in wiersze]
        parametry["limit_tokenow"] = None
        parametry["atrapa"] = plik.stem.endswith("_atrapa")

        run_id = zaloguj_przebieg(
            parametry=parametry,
            metadane=metadane,
            wiersze=wiersze,
            artefakty=[plik],
            czesciowy=False,
            zrodlo="import",
            czas_startu=czas_startu,
            tagi_dodatkowe={"plik_zrodlowy": plik.name},
        )
        print(f"Zaimportowano {plik.name} -> run {run_id}")
        run_idy.append(run_id)

    return run_idy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import historycznych wynikow ewaluacji do MLflow.")
    parser.add_argument(
        "--z-atrapa", action="store_true",
        help="Importuj rowniez pliki *_atrapa.json (domyslnie pomijane).",
    )
    args = parser.parse_args(argv)

    try:
        importuj(z_atrapa=args.z_atrapa)
    except Exception as e:
        print(f"BLAD: MLflow: {e}", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
