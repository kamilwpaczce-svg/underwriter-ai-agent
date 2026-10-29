"""Etap 15: bramka champion/challenger na PR AUC (tolerancja 0,01)."""

from __future__ import annotations

from ryzyko.bramka import decyzja


def test_brak_championa_promuj():
    promuj, powod = decyzja(None, {"pr_auc": 0.5})
    assert promuj is True
    assert "champion" in powod.lower()


def test_rowny_promuj():
    assert decyzja({"pr_auc": 0.60}, {"pr_auc": 0.60})[0] is True


def test_lepszy_promuj():
    assert decyzja({"pr_auc": 0.60}, {"pr_auc": 0.70})[0] is True


def test_slabszy_w_tolerancji_promuj():
    assert decyzja({"pr_auc": 0.60}, {"pr_auc": 0.595})[0] is True


def test_dokladnie_na_granicy_tolerancji_promuj():
    assert decyzja({"pr_auc": 0.80}, {"pr_auc": 0.79})[0] is True


def test_slabszy_o_0_02_odrzuc_z_powodem():
    promuj, powod = decyzja({"pr_auc": 0.60}, {"pr_auc": 0.58})
    assert promuj is False
    assert "0.5800" in powod and "0.6000" in powod
    assert "pr_auc" in powod.lower()


def test_wlasna_tolerancja():
    assert decyzja({"pr_auc": 0.60}, {"pr_auc": 0.58}, tol=0.05)[0] is True
    assert decyzja({"pr_auc": 0.60}, {"pr_auc": 0.60}, tol=0.0)[0] is True
    assert decyzja({"pr_auc": 0.60}, {"pr_auc": 0.599}, tol=0.0)[0] is False
