"""Krok 1 pipeline'u: generuje syntetyczny zbior, dzieli na train/test, liczy referencje PSI.

Wyjscie (katalog): `train.csv`, `test.csv`, `referencja.json` (granice koszy i proporcje
z ZBIORU TRENINGOWEGO - do monitoringu dryfu).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from ryzyko.cechy import CECHY
from ryzyko.generator import ETYKIETA, generuj_zbior
from ryzyko.psi import referencja

UDZIAL_TESTU = 0.3


def przygotuj_dane(n: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Etap 15: (train, test, referencja). Podzial stratyfikowany po etykiecie, deterministyczny."""
    df = generuj_zbior(n, seed)
    train, test = train_test_split(df, test_size=UDZIAL_TESTU, stratify=df[ETYKIETA], random_state=seed)
    train = train.reset_index(drop=True)
    test = test.reset_index(drop=True)
    return train, test, referencja(train[CECHY])


def zapisz(katalog: Path, train: pd.DataFrame, test: pd.DataFrame, ref: dict) -> None:
    katalog.mkdir(parents=True, exist_ok=True)
    train.to_csv(katalog / "train.csv", index=False)
    test.to_csv(katalog / "test.csv", index=False)
    (katalog / "referencja.json").write_text(json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dane", required=True, help="katalog wyjsciowy")
    args = parser.parse_args(argv)
    train, test, ref = przygotuj_dane(args.n, args.seed)
    zapisz(Path(args.dane), train, test, ref)
    print(f"przygotuj: train={len(train)} test={len(test)} pozytywne_train={train[ETYKIETA].mean():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
