"""Krok 4 pipeline'u: rejestracja nowej wersji modelu + bramka champion/challenger.

Zweryfikowane na zywo 26.10.2026 (Azure ML jako serwer MLflow): NIE dzialaja aliasy,
`log_model(registered_model_name=)`, `mlflow.register_model` ani `search_registered_models()`.
Dzialaja: `save_model` + `log_artifacts`, `create_registered_model`, `create_model_version`
ze `source=<artifact_uri>/model`, tagi wersji i tagi modelu. Dlatego:

- wskaznik championa = tag MODELU `champion=<wersja>` (jedno nadpisanie = promocja/rollback),
- historia = tagi wersji `rola` (`champion`/`challenger`/`odrzucony`/`wycofany`) i `powod`,
- metryki wersji = tagi wersji `pr_auc`, `roc_auc`, `brier` (+ `metryki.json` w artefaktach).

Odczyt championa i zapis tagu to NIE transakcja - nie puszczac dwoch pipeline'ow naraz.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ryzyko.bramka import METRYKA, decyzja

NAZWA_MODELU = "ryzyko_szkody"
KLUCZ_CHAMPIONA = "champion"
_BRAK_ZASOBU = "RESOURCE_DOES_NOT_EXIST"


def _brak_zasobu(e: Exception) -> bool:
    """Azure ML na brakujacy model odpowiada MlflowException z kodem RESOURCE_DOES_NOT_EXIST."""
    return getattr(e, "error_code", None) == _BRAK_ZASOBU


def zarejestruj_wersje(
    klient: Any, nazwa: str, source: str, run_id: str, metryki: dict[str, float], rodzaj: str
) -> dict[str, Any]:
    """Etap 15: rejestruje nowa wersje, przepuszcza przez bramke, ustawia tagi.

    `klient` = `mlflow.MlflowClient` (w testach atrapa). Brak championa -> promocja.
    Odrzucony: tag wersji `rola=odrzucony` + `powod`, tag modelu `champion` BEZ zmian.
    Zwraca `{"wersja", "promowany", "powod", "champion_przed", "champion_po"}`.
    """
    try:
        model = klient.get_registered_model(nazwa)
    except Exception as e:
        if not _brak_zasobu(e):
            raise  # np. blad uwierzytelnienia - nie udajemy, ze modelu "po prostu nie ma"
        klient.create_registered_model(nazwa)
        champion_przed = None
    else:
        champion_przed = (model.tags or {}).get(KLUCZ_CHAMPIONA) or None

    metryki_championa = None
    if champion_przed is not None:
        wersja_championa = klient.get_model_version(nazwa, champion_przed)
        metryki_championa = {METRYKA: float(wersja_championa.tags[METRYKA])}

    promuj, powod = decyzja(metryki_championa, metryki)

    wersja = str(klient.create_model_version(nazwa, source=source, run_id=run_id).version)
    for klucz in ("pr_auc", "roc_auc", "brier"):
        klient.set_model_version_tag(nazwa, wersja, klucz, f"{metryki[klucz]:.6f}")
    klient.set_model_version_tag(nazwa, wersja, "rodzaj", rodzaj)

    if promuj:
        klient.set_model_version_tag(nazwa, wersja, "rola", "champion")
        klient.set_model_version_tag(nazwa, wersja, "powod", powod)
        if champion_przed is not None:
            klient.set_model_version_tag(nazwa, champion_przed, "rola", "wycofany")
            klient.set_model_version_tag(nazwa, champion_przed, "powod", f"zastapiony przez wersje {wersja}")
        # Ostatni krok: dopiero tu wskaznik przechodzi na nowa wersje.
        klient.set_registered_model_tag(nazwa, KLUCZ_CHAMPIONA, wersja)
        champion_po = wersja
    else:
        klient.set_model_version_tag(nazwa, wersja, "rola", "odrzucony")
        klient.set_model_version_tag(nazwa, wersja, "powod", powod)
        champion_po = champion_przed
    return {
        "wersja": wersja,
        "promowany": promuj,
        "powod": powod,
        "champion_przed": champion_przed,
        "champion_po": champion_po,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="katalog wyjsciowy kroku trenuj (podkatalog model/)")
    parser.add_argument("--metryki", required=True, help="katalog z metryki.json")
    parser.add_argument("--dane", required=True, help="katalog z referencja.json")
    parser.add_argument("--rodzaj", required=True)
    parser.add_argument("--nazwa", default=NAZWA_MODELU)
    parser.add_argument("--wynik", required=True, help="katalog wyjsciowy (rejestracja.json)")
    args = parser.parse_args(argv)

    import mlflow
    from mlflow import MlflowClient

    metryki = json.loads((Path(args.metryki) / "metryki.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        # Wersja modelu = katalog MLflow + referencja PSI + metryki (jeden artefakt, jedno `source`).
        pakiet = Path(tmp) / "model"
        shutil.copytree(Path(args.model) / "model", pakiet)
        shutil.copy(Path(args.dane) / "referencja.json", pakiet / "referencja.json")
        shutil.copy(Path(args.metryki) / "metryki.json", pakiet / "metryki.json")
        with mlflow.start_run() as run:
            mlflow.log_artifacts(str(pakiet), artifact_path="model")
            wynik = zarejestruj_wersje(
                MlflowClient(),
                args.nazwa,
                f"{run.info.artifact_uri}/model",
                run.info.run_id,
                metryki,
                args.rodzaj,
            )
    wyjscie = Path(args.wynik)
    wyjscie.mkdir(parents=True, exist_ok=True)
    (wyjscie / "rejestracja.json").write_text(json.dumps(wynik, indent=2, ensure_ascii=False), encoding="utf-8")
    print("zarejestruj: " + json.dumps(wynik, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
