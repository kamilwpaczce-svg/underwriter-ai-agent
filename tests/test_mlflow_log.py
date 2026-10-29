"""Testy sledzenia ewaluacji w MLflow (Etap 8). Zawsze na atrapie, bez sieci.
Tracking kierowany do tmp_path (SQLite) - zadnego wspoldzielonego stanu miedzy testami.

pytest.importorskip - CI instaluje tylko requirements.txt (bez mlflow), wiec te testy
maja byc pomijane, nie failowac.
"""

from __future__ import annotations

import json

import pytest

mlflow = pytest.importorskip("mlflow")

from mlflow import MlflowClient  # noqa: E402

from ewaluacja import import_historii, mlflow_log, uruchom  # noqa: E402


def _tracking_uri(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'mlruns.db').as_posix()}"


def _ustaw_tracking(monkeypatch, tmp_path, nazwa_eksperymentu: str) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", _tracking_uri(tmp_path))
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", nazwa_eksperymentu)


def _pobierz_jedyny_run(nazwa_eksperymentu: str):
    eksperyment = mlflow.get_experiment_by_name(nazwa_eksperymentu)
    runy = MlflowClient().search_runs([eksperyment.experiment_id])
    assert len(runy) == 1
    return runy[0]


def _wiersz_w_pelni_zgodny(id_przypadku: str) -> dict:
    """Minimalny wiersz spelniajacy przypadek_w_pelni_zgodny (ewaluacja/porownanie.py) -
    uzywany tam, gdzie test nie przechodzi przez caly tor porownaj_przypadek."""
    return {
        "id": id_przypadku,
        "typ_dokumentu_ok": True,
        "decyzja_llm_ok": True,
        "decyzja_llm_oczekiwana": "AKCEPTACJA",
        "decyzja_llm_otrzymana": "AKCEPTACJA",
        "reguly_llm_ok": True,
        "decyzja_silnika_na_polach_llm_ok": True,
        "podejrzane_instrukcje_ok": True,
        "blad": None,
        "pola_trafione": 1,
        "pola_wszystkie": 1,
    }


def test_main_mlflow_zapisuje_run(monkeypatch, tmp_path):
    _ustaw_tracking(monkeypatch, tmp_path, "test-main-mlflow")
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path / "wyniki")

    kod = uruchom.main(["--atrapa", "--mlflow", "--przypadki", "W01,W02"])
    assert kod == 0

    run = _pobierz_jedyny_run("test-main-mlflow")
    assert "wersja_promptu" in run.data.params
    assert "wersja_porownania" in run.data.params
    assert run.data.params["model"] == "atrapa"
    assert run.data.params["atrapa"] == "True"
    assert run.data.metrics["przypadki_lacznie"] == 2.0
    assert run.data.tags["czesciowy"] == "false"

    artefakty = {a.path for a in MlflowClient().list_artifacts(run.info.run_id)}
    assert any(p.endswith(".json") for p in artefakty)
    assert any(p.endswith(".md") for p in artefakty)

    pliki_wynikow = list((tmp_path / "wyniki").glob("*"))
    assert any(p.suffix == ".json" for p in pliki_wynikow)
    assert any(p.suffix == ".md" for p in pliki_wynikow)


def test_zmiana_promptu_zmienia_wersje_promptu(monkeypatch, tmp_path):
    _ustaw_tracking(monkeypatch, tmp_path, "test-wersja-promptu")

    plik_a = tmp_path / "instrukcje_a.py"
    plik_b = tmp_path / "instrukcje_b.py"
    plik_a.write_text("TRESC_A = 1\n", encoding="utf-8")
    plik_b.write_text("TRESC_B = 2\n", encoding="utf-8")

    wiersze = [_wiersz_w_pelni_zgodny("W01")]
    metadane = {"czas_calkowity_ms": 1.0, "wywolania_llm_laczne": 1, "tokeny_we_laczne": 0, "tokeny_wy_laczne": 0}

    monkeypatch.setattr(mlflow_log, "SCIEZKA_INSTRUKCJI", plik_a)
    run_id_a = mlflow_log.zaloguj_przebieg(
        parametry={"model": "atrapa"}, metadane=metadane, wiersze=wiersze, artefakty=[], czesciowy=False,
    )
    monkeypatch.setattr(mlflow_log, "SCIEZKA_INSTRUKCJI", plik_b)
    run_id_b = mlflow_log.zaloguj_przebieg(
        parametry={"model": "atrapa"}, metadane=metadane, wiersze=wiersze, artefakty=[], czesciowy=False,
    )

    client = MlflowClient()
    wersja_a = client.get_run(run_id_a).data.params["wersja_promptu"]
    wersja_b = client.get_run(run_id_b).data.params["wersja_promptu"]
    assert wersja_a != wersja_b


def test_bledny_tracking_uri_zwraca_5_i_zachowuje_pliki(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "nieobslugiwany-schemat://gdzies")
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path / "wyniki")

    kod = uruchom.main(["--atrapa", "--mlflow", "--przypadki", "W01"])
    assert kod == 5

    przechwycone = capsys.readouterr()
    assert "BLAD: MLflow" in przechwycone.err

    pliki_wynikow = list((tmp_path / "wyniki").glob("*"))
    assert any(p.suffix == ".json" for p in pliki_wynikow)
    assert any(p.suffix == ".md" for p in pliki_wynikow)


def test_mlflow_trace_na_azure_ml_odmawia_przed_przebiegiem(monkeypatch, tmp_path, capsys):
    # Azure ML nie ma API sladow - bez blokady slady gina w tle, a kod wyjscia to 0.
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "azureml://swedencentral.api.azureml.ms/mlflow/v1.0/x")
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path / "wyniki")

    kod = uruchom.main(["--atrapa", "--mlflow-trace", "--przypadki", "W01"])
    assert kod == 5
    assert "nie obsluguje sladow" in capsys.readouterr().err
    assert not (tmp_path / "wyniki").exists()


def test_czesciowy_przebieg_oznaczony_tagiem(monkeypatch, tmp_path):
    # Atrapa zawsze raportuje 0 tokenow (MetadaneWywolania(tokeny_we=0, tokeny_wy=0) w
    # ewaluacja/atrapa.py), wiec bezpiecznik --limit-tokenow nigdy nie zadziala przez CLI
    # na atrapie - test jednostkowy zaloguj_przebieg(..., czesciowy=True) wprost (zgodnie z SPEC_ETAP8).
    _ustaw_tracking(monkeypatch, tmp_path, "test-czesciowy")

    wiersze = [_wiersz_w_pelni_zgodny("W01")]
    metadane = {"czas_calkowity_ms": 1.0, "wywolania_llm_laczne": 1, "tokeny_we_laczne": 0, "tokeny_wy_laczne": 0}

    run_id = mlflow_log.zaloguj_przebieg(
        parametry={"model": "atrapa"}, metadane=metadane, wiersze=wiersze, artefakty=[], czesciowy=True,
    )
    tag = MlflowClient().get_run(run_id).data.tags["czesciowy"]
    assert tag == "true"


def _zapisz_syntetyczny_plik_wynikow(katalog, nazwa: str) -> None:
    dane = {
        "model": "gemini-test",
        "metadane": {
            "czas_calkowity_ms": 10.0,
            "wywolania_llm_laczne": 2,
            "liczba_przypadkow": 1,
            "liczba_ok": 1,
            "tokeny_we_laczne": 100,
            "tokeny_wy_laczne": 50,
        },
        "przypadki": [
            {
                "id": "W01",
                "typ_dokumentu_ok": True,
                "pola_trafione": 1,
                "pola_wszystkie": 1,
                "decyzja_llm_ok": True,
                "decyzja_llm_oczekiwana": "AKCEPTACJA",
                "decyzja_llm_otrzymana": "AKCEPTACJA",
                "reguly_llm_ok": True,
                "decyzja_silnika_na_polach_llm_ok": True,
                "podejrzane_instrukcje_ok": True,
                "blad": None,
            }
        ],
    }
    (katalog / nazwa).write_text(json.dumps(dane, ensure_ascii=False), encoding="utf-8")


def test_import_historii_idempotentny(monkeypatch, tmp_path):
    _ustaw_tracking(monkeypatch, tmp_path, "test-import-historii")
    monkeypatch.setattr(import_historii, "WYNIKI_DIR", tmp_path)

    _zapisz_syntetyczny_plik_wynikow(tmp_path, "20260101-0900_gemini-test.json")
    _zapisz_syntetyczny_plik_wynikow(tmp_path, "20260102-1000_gemini-test.json")

    run_idy_1 = import_historii.importuj()
    assert len(run_idy_1) == 2

    eksperyment = mlflow.get_experiment_by_name("test-import-historii")
    runy_po_pierwszym = MlflowClient().search_runs([eksperyment.experiment_id])
    assert len(runy_po_pierwszym) == 2

    run_idy_2 = import_historii.importuj()
    assert len(run_idy_2) == 0

    runy_po_drugim = MlflowClient().search_runs([eksperyment.experiment_id])
    assert len(runy_po_drugim) == 2


def test_import_historii_pomija_atrape_domyslnie(monkeypatch, tmp_path):
    _ustaw_tracking(monkeypatch, tmp_path, "test-import-atrapa")
    monkeypatch.setattr(import_historii, "WYNIKI_DIR", tmp_path)

    _zapisz_syntetyczny_plik_wynikow(tmp_path, "20260101-0900_atrapa.json")

    run_idy = import_historii.importuj(z_atrapa=False)
    assert len(run_idy) == 0

    run_idy_z_atrapa = import_historii.importuj(z_atrapa=True)
    assert len(run_idy_z_atrapa) == 1
