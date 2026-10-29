"""Krok 3 pipeline'u: ocenia model na PRAWDZIWYCH etykietach z `test.csv`.

Wyjscie (katalog): `metryki.json` - `roc_auc`, `pr_auc` (glowna metryka bramki), `brier`, `n_test`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ryzyko.cechy import CECHY
from ryzyko.generator import ETYKIETA
from ryzyko.model import ocen


def ewaluuj_model(model, test: pd.DataFrame) -> dict[str, float]:
    """Etap 15: metryki `ryzyko.model.ocen` + `n_test`."""
    metryki = ocen(model, test[CECHY], test[ETYKIETA])
    metryki["n_test"] = int(len(test))
    return metryki


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dane", required=True, help="katalog z test.csv")
    parser.add_argument("--model", required=True, help="katalog wyjsciowy kroku trenuj (podkatalog model/)")
    parser.add_argument("--metryki", required=True, help="katalog wyjsciowy")
    args = parser.parse_args(argv)

    import mlflow
    import mlflow.sklearn

    model = mlflow.sklearn.load_model(str(Path(args.model) / "model"))
    test = pd.read_csv(Path(args.dane) / "test.csv")
    metryki = ewaluuj_model(model, test)
    wyjscie = Path(args.metryki)
    wyjscie.mkdir(parents=True, exist_ok=True)
    (wyjscie / "metryki.json").write_text(json.dumps(metryki, indent=2), encoding="utf-8")
    with mlflow.start_run():  # w jobie Azure ML wznawia run kroku, lokalnie zamyka sie po zapisie
        mlflow.log_metrics({k: v for k, v in metryki.items() if k != "n_test"})
    print("ewaluuj: " + json.dumps(metryki))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
