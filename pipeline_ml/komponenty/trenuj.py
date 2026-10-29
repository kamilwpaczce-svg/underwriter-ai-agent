"""Krok 2 pipeline'u: trenuje model na `train.csv` i zapisuje go jako model MLflow.

Rodzaje: `hgb` (model docelowy), `logreg` (baseline), `zepsuty` = ten sam HGB uczony na
PRZETASOWANYCH etykietach (celowo bezuzyteczny - do testu bramki champion/challenger).

Wyjscie (katalog): `model/` (format MLflow, `mlflow.sklearn.save_model`) i `trening.json`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ryzyko.cechy import CECHY
from ryzyko.generator import ETYKIETA
from ryzyko.model import zbuduj_pipeline
from ryzyko.serwowanie import ZAUFANE_TYPY

RODZAJE = ("hgb", "logreg", "zepsuty")


def trenuj_model(train: pd.DataFrame, rodzaj: str, seed: int):
    """Etap 15: wytrenowany Pipeline. `zepsuty` uczy HGB na losowo przetasowanych etykietach."""
    if rodzaj not in RODZAJE:
        raise ValueError(f"Nieznany rodzaj {rodzaj!r}; dozwolone: {RODZAJE}")
    y = train[ETYKIETA].to_numpy()
    if rodzaj == "zepsuty":
        y = np.random.default_rng(seed).permutation(y)
    model = zbuduj_pipeline("hgb" if rodzaj == "zepsuty" else rodzaj)
    model.fit(train[CECHY], y)
    return model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dane", required=True, help="katalog z train.csv")
    parser.add_argument("--rodzaj", default="hgb", choices=RODZAJE)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", required=True, help="katalog wyjsciowy")
    args = parser.parse_args(argv)

    import mlflow
    import mlflow.sklearn

    train = pd.read_csv(Path(args.dane) / "train.csv")
    model = trenuj_model(train, args.rodzaj, args.seed)
    wyjscie = Path(args.model)
    wyjscie.mkdir(parents=True, exist_ok=True)
    # mlflow 3.15 zapisuje sklearn w formacie skops: typy spoza listy domyslnej trzeba zaufac jawnie
    mlflow.sklearn.save_model(model, str(wyjscie / "model"), skops_trusted_types=ZAUFANE_TYPY)
    (wyjscie / "trening.json").write_text(
        json.dumps({"rodzaj": args.rodzaj, "seed": args.seed, "n_train": len(train)}), encoding="utf-8"
    )
    with mlflow.start_run():  # w jobie Azure ML wznawia run kroku, lokalnie zamyka sie po zapisie
        mlflow.log_params({"rodzaj": args.rodzaj, "seed": args.seed, "n_train": len(train)})
    print(f"trenuj: rodzaj={args.rodzaj} n_train={len(train)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
