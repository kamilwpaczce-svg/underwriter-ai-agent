"""Etap 15: pipeline scikit-learn i metryki (HGB vs baseline logreg)."""

from __future__ import annotations

import pytest

from ryzyko.cechy import CECHY
from ryzyko.generator import generuj_zbior
from ryzyko.model import ocen, zbuduj_pipeline


@pytest.fixture(scope="module")
def zbior():
    df = generuj_zbior(5000, seed=42)
    return df.iloc[:3500], df.iloc[3500:]


def _dopasuj(rodzaj, trening):
    model = zbuduj_pipeline(rodzaj)
    model.fit(trening[CECHY], trening["do_weryfikacji"])
    return model


def test_ocen_zwraca_trzy_metryki(zbior):
    trening, test = zbior
    metryki = ocen(_dopasuj("logreg", trening), test[CECHY], test["do_weryfikacji"])
    assert set(metryki) == {"roc_auc", "pr_auc", "brier"}
    assert all(isinstance(v, float) for v in metryki.values())
    assert 0.5 < metryki["roc_auc"] <= 1.0
    assert 0.0 < metryki["brier"] < 0.25


def test_hgb_lepszy_od_baseline(zbior):
    trening, test = zbior
    hgb = ocen(_dopasuj("hgb", trening), test[CECHY], test["do_weryfikacji"])
    baza = ocen(_dopasuj("logreg", trening), test[CECHY], test["do_weryfikacji"])
    assert hgb["pr_auc"] > baza["pr_auc"]
    assert hgb["roc_auc"] > baza["roc_auc"]


def test_model_zna_kategorie_spoza_treningu(zbior):
    trening, test = zbior
    model = _dopasuj("hgb", trening)
    nowy = test[CECHY].head(3).copy()
    nowy["rodzaj_mienia"] = "inny_rodzaj"
    assert model.predict_proba(nowy).shape == (3, 2)


def test_deterministyczny_trening(zbior):
    trening, test = zbior
    a = _dopasuj("hgb", trening).predict_proba(test[CECHY])
    b = _dopasuj("hgb", trening).predict_proba(test[CECHY])
    assert (a == b).all()


def test_nieznany_rodzaj_modelu():
    with pytest.raises(ValueError):
        zbuduj_pipeline("xgboost")
