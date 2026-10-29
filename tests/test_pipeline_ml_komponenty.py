"""Etap 15, zadanie 3: logika krokow pipeline'u Azure ML (offline, bez Azure).

Czyste funkcje (przygotuj/trenuj/ewaluuj) dzialaja w `.venv`; lancuch 4 skryptow z lokalnym
MLflow (SQLite) wymaga `mlflow` i jest pomijany tam, gdzie go nie ma (`.venv`, CI).
"""

from __future__ import annotations

import json

import pytest

from pipeline_ml.komponenty.ewaluuj import ewaluuj_model
from pipeline_ml.komponenty.przygotuj import przygotuj_dane
from pipeline_ml.komponenty.trenuj import trenuj_model
from ryzyko.cechy import CECHY
from ryzyko.generator import ETYKIETA


def test_przygotuj_deterministyczny_i_stratyfikowany():
    train, test, ref = przygotuj_dane(2000, 3)
    train2, _, ref2 = przygotuj_dane(2000, 3)
    assert train.equals(train2) and ref == ref2
    assert len(train) == 1400 and len(test) == 600
    assert abs(train[ETYKIETA].mean() - test[ETYKIETA].mean()) < 0.01
    assert set(ref) == set(CECHY)  # referencja PSI dla kazdej cechy, z danych treningowych


def test_trenuj_rodzaje_i_nieznany_rodzaj():
    train, test, _ = przygotuj_dane(2000, 0)
    for rodzaj in ("hgb", "logreg", "zepsuty"):
        model = trenuj_model(train, rodzaj, 0)
        assert model.predict_proba(test[CECHY]).shape == (len(test), 2)
    with pytest.raises(ValueError, match="Nieznany rodzaj"):
        trenuj_model(train, "xgboost", 0)


def test_zepsuty_jest_wyraznie_slabszy_od_hgb_na_prawdziwych_etykietach():
    train, test, _ = przygotuj_dane(5000, 0)
    dobry = ewaluuj_model(trenuj_model(train, "hgb", 0), test)
    zepsuty = ewaluuj_model(trenuj_model(train, "zepsuty", 0), test)
    assert set(dobry) == {"roc_auc", "pr_auc", "brier", "n_test"}
    # luka musi byc duzo wieksza niz tolerancja bramki (0,01), inaczej test bramki nic nie znaczy
    assert dobry["pr_auc"] - zepsuty["pr_auc"] > 0.1
    assert zepsuty["roc_auc"] < 0.6


def test_lancuch_czterech_skryptow_z_lokalnym_mlflow(tmp_path, monkeypatch):
    mlflow = pytest.importorskip("mlflow")
    import mlflow.sklearn  # noqa: F401
    from mlflow import MlflowClient

    from pipeline_ml.komponenty import ewaluuj, przygotuj, trenuj, zarejestruj

    monkeypatch.chdir(tmp_path)  # artefakty lokalnego MLflow ('mlruns/') laduja w tmp_path
    uri = f"sqlite:///{(tmp_path / 'ml.db').as_posix()}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    mlflow.set_tracking_uri(uri)
    d = tmp_path / "dane"

    def bieg(rodzaj: str) -> dict:
        m, met, w = tmp_path / f"m_{rodzaj}", tmp_path / f"met_{rodzaj}", tmp_path / f"w_{rodzaj}"
        assert przygotuj.main(["--n", "3000", "--seed", "0", "--dane", str(d)]) == 0
        assert trenuj.main(["--dane", str(d), "--rodzaj", rodzaj, "--model", str(m)]) == 0
        assert ewaluuj.main(["--dane", str(d), "--model", str(m), "--metryki", str(met)]) == 0
        assert (
            zarejestruj.main(
                ["--model", str(m), "--metryki", str(met), "--dane", str(d), "--rodzaj", rodzaj, "--wynik", str(w)]
            )
            == 0
        )
        return json.loads((w / "rejestracja.json").read_text(encoding="utf-8"))

    pierwszy = bieg("hgb")
    assert pierwszy["wersja"] == "1" and pierwszy["promowany"] is True and pierwszy["champion_po"] == "1"
    drugi = bieg("zepsuty")
    assert drugi["wersja"] == "2" and drugi["promowany"] is False and drugi["champion_po"] == "1"

    k = MlflowClient()
    assert k.get_registered_model("ryzyko_szkody").tags["champion"] == "1"
    assert k.get_model_version("ryzyko_szkody", "1").tags["rola"] == "champion"
    v2 = k.get_model_version("ryzyko_szkody", "2")
    assert v2.tags["rola"] == "odrzucony" and "odrzucony" in v2.tags["powod"]
    # wersja 1 laduje sie z rejestru i daje prawdopodobienstwa
    model = mlflow.sklearn.load_model("models:/ryzyko_szkody/1")
    _, test, _ = przygotuj.przygotuj_dane(300, 1)
    assert model.predict_proba(test[CECHY]).shape == (len(test), 2)
