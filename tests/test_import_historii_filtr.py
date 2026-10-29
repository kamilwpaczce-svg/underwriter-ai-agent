"""Etap 14, przeglad koncowy I1: import historii nie wciaga plikow Etapu 14 do MLflow.

Test bez mlflow (dziala w .venv i w CI): ustaw_sledzenie, _juz_zaimportowany i zaloguj_przebieg
sa podmienione, wiec sprawdzamy wylacznie wybor plikow i bramke na tresc."""

from __future__ import annotations

import json

from ewaluacja import import_historii

STARY = "20261010-1758_gemini-3.8-flash.json"
NOWY_KLUCZ = "20261020-1200_gpt-5-mini_szkody"


def _plik(katalog, nazwa: str, tresc) -> None:
    (katalog / nazwa).write_text(json.dumps(tresc, ensure_ascii=False), encoding="utf-8")


def _wynik_starego_typu() -> dict:
    return {"model": "gemini-3.8-flash", "metadane": {}, "przypadki": [{"id": "A01", "decyzja": "OK"}]}


def _wynik_szkod_z_rag() -> dict:
    wiersz = {"id": "Z01", "query": "q", "context": "c", "response": "r", "ground_truth": "g", "ocenia_llm": True}
    return {"model": "gpt-5-mini", "modul": "szkody", "metadane": {}, "przypadki": [wiersz]}


def _przygotuj(tmp_path) -> None:
    _plik(tmp_path, STARY, _wynik_starego_typu())
    _plik(tmp_path, f"{NOWY_KLUCZ}.json", _wynik_szkod_z_rag())
    _plik(tmp_path, f"{NOWY_KLUCZ}_mlflow.json", _wynik_starego_typu())
    _plik(tmp_path, f"{NOWY_KLUCZ}_sedzia.json", {"rows": [{"inputs.query": "q"}], "metrics": {}})
    _plik(tmp_path, f"{NOWY_KLUCZ}_sedzia_mlflow.json", {"metrics": {}})
    _plik(tmp_path, "20261020-1200_gpt-5-mini_szkody_atrapa_mlflow.json", _wynik_starego_typu())


def test_pliki_do_importu_pomija_kopie_i_wyniki_sedziego(monkeypatch, tmp_path):
    monkeypatch.setattr(import_historii, "WYNIKI_DIR", tmp_path)
    _przygotuj(tmp_path)
    nazwy = [p.name for p in import_historii._pliki_do_importu(z_atrapa=True)]
    assert nazwy == sorted([STARY, f"{NOWY_KLUCZ}.json"])


def test_importuj_loguje_tylko_stary_plik(monkeypatch, tmp_path):
    monkeypatch.setattr(import_historii, "WYNIKI_DIR", tmp_path)
    _przygotuj(tmp_path)
    zalogowane: list[str] = []
    monkeypatch.setattr(import_historii, "ustaw_sledzenie", lambda: None)
    monkeypatch.setattr(import_historii, "_juz_zaimportowany", lambda nazwa: False)

    def _fikcyjny_log(**kw):
        zalogowane.append(kw["tagi_dodatkowe"]["plik_zrodlowy"])
        return "run-" + str(len(zalogowane))

    monkeypatch.setattr(import_historii, "zaloguj_przebieg", _fikcyjny_log)
    run_idy = import_historii.importuj(z_atrapa=True)
    assert zalogowane == [STARY]
    assert run_idy == ["run-1"]


def test_importuj_pomija_plik_bez_listy_przypadkow(monkeypatch, tmp_path):
    """Fail-closed: plik o nieznanym ksztalcie (np. wynik sedziego pod zwykla nazwa) nie jest runem."""
    monkeypatch.setattr(import_historii, "WYNIKI_DIR", tmp_path)
    _plik(tmp_path, "20261020-1300_cos.json", {"rows": []})
    monkeypatch.setattr(import_historii, "ustaw_sledzenie", lambda: None)
    monkeypatch.setattr(import_historii, "_juz_zaimportowany", lambda nazwa: False)
    monkeypatch.setattr(import_historii, "zaloguj_przebieg", lambda **kw: pytest_fail())
    assert import_historii.importuj() == []


def pytest_fail():
    raise AssertionError("zaloguj_przebieg nie powinien byc wolany")
