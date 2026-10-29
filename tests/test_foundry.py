"""Etap 14: ewaluacja sedzia LLM (azure-ai-evaluation) - czesci offline, bez SDK i bez sieci."""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

from ewaluacja import foundry, foundry_uruchom


def _wiersz(id_: str, ocenia_llm: bool = True, **nadpisz) -> dict:
    w = {"id": id_, "query": "q", "context": "c", "response": "r", "ground_truth": "g",
         "ocenia_llm": ocenia_llm, "decyzja_ok": True, "cytat_trafiony": True, "_tokeny_we": 1}
    return {**w, **nadpisz}


def test_zapisz_jsonl_tylko_klucze_rag_i_wiersze_z_ocena_llm(tmp_path):
    sciezka = tmp_path / "x_sedzia.jsonl"
    wiersze = [_wiersz("Z01"), _wiersz("Z02"), _wiersz("Z09", ocenia_llm=False)]
    assert foundry.zapisz_jsonl(wiersze, sciezka) == 2  # Z09 (decyzja z regul) nie idzie do sedziego
    linie = [json.loads(l) for l in sciezka.read_text(encoding="utf-8").splitlines()]
    assert [l["id"] for l in linie] == ["Z01", "Z02"]
    assert [set(l) for l in linie] == [set(foundry.KLUCZE_JSONL)] * 2  # bez metryk i tokenow


def test_zapisz_jsonl_stary_plik_wynikow(tmp_path):
    with pytest.raises(foundry.BrakPolRag):
        foundry.zapisz_jsonl([{"id": "Z01", "decyzja_ok": True}], tmp_path / "x.jsonl")


def test_mapowanie_kolumn_zgodne_z_wymaganiami_ewaluatorow():
    m = foundry.mapowanie_kolumn()
    assert set(m) == {"groundedness", "relevance", "retrieval", "response_completeness"}
    assert m["groundedness"]["column_mapping"] == {
        "query": "${data.query}", "context": "${data.context}", "response": "${data.response}"}
    assert set(m["retrieval"]["column_mapping"]) == {"query", "context"}
    assert set(m["response_completeness"]["column_mapping"]) == {"response", "ground_truth"}


WYNIK = {  # ksztalt z [Z4]/[Z6]: rows z inputs.<kolumna> i outputs.<alias>.<metryka>
    "rows": [
        {"inputs.id": "Z01", **{f"outputs.{n}.{n}": 5.0 for n in foundry.WEJSCIA},
         **{f"outputs.{n}.{n}_result": "pass" for n in foundry.WEJSCIA}},
        {"inputs.id": "Z10", **{f"outputs.{n}.{n}": 4.0 for n in foundry.WEJSCIA},
         **{f"outputs.{n}.{n}_result": "pass" for n in foundry.WEJSCIA}},
        {"inputs.id": "Z11"},  # brak ocen - ewaluator padl albo n/d
    ],
    "metrics": {}, "studio_url": "https://ai.azure.com/x",
}


def test_oceny_z_wyniku():
    oceny = foundry.oceny_z_wyniku(WYNIK)
    assert oceny["Z01"]["groundedness"] == {"wynik": 5.0, "pass": True}
    assert oceny["Z11"] == {}


@pytest.mark.parametrize("det, sedzia, klasa", [
    (True, True, "zgoda_ok"), (False, False, "zgoda_blad"),
    (False, True, "sedzia_poblazliwy"), (True, False, "sedzia_surowy"), (True, None, "n/d"),
])
def test_klasyfikuj(det, sedzia, klasa):
    assert foundry.klasyfikuj(det, sedzia) == klasa


def test_tabela_rozjazdow_z10_poblazliwy():
    wiersze = [_wiersz("Z01"), _wiersz("Z10", decyzja_ok=False), _wiersz("Z11", ocenia_llm=False)]
    tabela = {t["id"]: t for t in foundry.tabela_rozjazdow(wiersze, foundry.oceny_z_wyniku(WYNIK))}
    assert tabela["Z01"]["klasa"] == "zgoda_ok"
    assert tabela["Z10"]["klasa"] == "sedzia_poblazliwy"
    assert tabela["Z11"]["klasa"] == "n/d"


def test_klasa_tylko_z_completeness():
    """Przeglad p. 5: G/Rel/Ret to osobne kolumny; klasa rozjazdu = completeness vs metryka deterministyczna."""
    wynik = {"rows": [{"inputs.id": "Z10",
                       **{f"outputs.{n}.{n}": 2.0 for n in foundry.WEJSCIA},
                       **{f"outputs.{n}.{n}_result": "fail" for n in foundry.WEJSCIA},
                       "outputs.response_completeness.response_completeness_result": "pass"}]}
    t = foundry.tabela_rozjazdow([_wiersz("Z10", decyzja_ok=False)], foundry.oceny_z_wyniku(wynik))[0]
    assert t["klasa"] == "sedzia_poblazliwy"
    assert t["groundedness"] == {"wynik": 2.0, "pass": False}  # kolumna zostaje w tabeli


def test_brak_oceny_przy_ocenie_llm_to_awaria():
    """Cicha awaria: ewaluator padl (fail_on_evaluator_errors=False daje pusty wiersz)."""
    wiersze = [_wiersz("Z11", ocenia_llm=True)]
    assert foundry.wiersze_bez_oceny(wiersze, foundry.oceny_z_wyniku(WYNIK)) == ["Z11"]


def test_metryki_sedziego_i_raport():
    wiersze = [_wiersz("Z01"), _wiersz("Z10", decyzja_ok=False)]
    tabela = foundry.tabela_rozjazdow(wiersze, foundry.oceny_z_wyniku(WYNIK))
    m = foundry.metryki_sedziego(tabela)
    assert m["sedzia_groundedness"] == pytest.approx(4.5)
    assert m["sedzia_rozjazdy"] == 1.0
    md = foundry.raport_rozjazdow_md(tabela, "20261022-1810_szkody_gpt-5-mini", WYNIK["studio_url"])
    assert "Z10" in md and "sedzia_poblazliwy" in md and "https://ai.azure.com/x" in md


def test_metryki_sedziego_pomija_nd():
    """Wiersze n/d (bez oceny LLM) nie wchodza do srednich ani do licznika ocenionych."""
    wiersze = [_wiersz("Z01"), _wiersz("Z11", ocenia_llm=False)]
    tabela = foundry.tabela_rozjazdow(wiersze, foundry.oceny_z_wyniku(WYNIK))
    m = foundry.metryki_sedziego(tabela)
    assert m["sedzia_ocenione"] == 1.0
    assert m["sedzia_groundedness"] == pytest.approx(5.0)
    assert m["sedzia_rozjazdy"] == 0.0


def test_tabela_mlflow_plaskie_kolumny():
    wiersze = [_wiersz("Z01"), _wiersz("Z10", decyzja_ok=False), _wiersz("Z11", ocenia_llm=False)]
    t = foundry.tabela_mlflow(foundry.tabela_rozjazdow(wiersze, foundry.oceny_z_wyniku(WYNIK)))
    assert set(t) >= {"id", "klasa", "groundedness", "groundedness_pass"}
    assert len({len(v) for v in t.values()}) == 1
    assert t["groundedness"] == [5.0, 4.0, None]
    assert t["groundedness_pass"] == [True, True, None]
    assert t["klasa"] == ["zgoda_ok", "sedzia_poblazliwy", "n/d"]


def test_raport_komorki_pass_fail_i_myslnik():
    tabela = [{"id": "Z01", "decyzja_ok": True, "cytat_trafiony": None, "klasa": "n/d",
               "groundedness": {"wynik": 2.0, "pass": False}, "relevance": {"wynik": 5.0, "pass": True},
               "retrieval": None, "response_completeness": None}]
    md = foundry.raport_rozjazdow_md(tabela, "k", None)
    assert "2.0 FAIL" in md and "5.0 pass" in md and "| - |" in md


def _wiersz_wyniku(id_: str, **nadpisz) -> dict:
    w = {"inputs.id": id_, **{f"outputs.{n}.{n}": 4.0 for n in foundry.WEJSCIA},
         **{f"outputs.{n}.{n}_result": "pass" for n in foundry.WEJSCIA}}
    return w | nadpisz


@pytest.mark.parametrize("zly_result", ["error", None, "", "PASS", True])
def test_result_spoza_pass_fail_to_brak_oceny(zly_result):
    """Etap 14 recenzja 2+3: nieznany _result nie moze byc cichym FAIL - ewaluator pomijany, wiersz idzie do kodu 6."""
    wynik = {"rows": [_wiersz_wyniku("Z01", **{"outputs.relevance.relevance_result": zly_result})]}
    oceny = foundry.oceny_z_wyniku(wynik)
    assert "relevance" not in oceny["Z01"] and len(oceny["Z01"]) == len(foundry.WEJSCIA) - 1
    assert foundry.wiersze_bez_oceny([_wiersz("Z01")], oceny) == ["Z01"]


def test_result_fail_zostaje_oceną_fail():
    wynik = {"rows": [_wiersz_wyniku("Z01", **{"outputs.relevance.relevance_result": "fail"})]}
    assert foundry.oceny_z_wyniku(wynik)["Z01"]["relevance"] == {"wynik": 4.0, "pass": False}


@pytest.mark.parametrize("zla_liczba", [True, False, float("nan"), None, "5"])
def test_wynik_bool_nan_tekst_to_brak_oceny(zla_liczba):
    wynik = {"rows": [_wiersz_wyniku("Z01", **{"outputs.groundedness.groundedness": zla_liczba})]}
    assert "groundedness" not in foundry.oceny_z_wyniku(wynik)["Z01"]


def test_zbuduj_ewaluatory_klucze_zgodne_z_wejsciami(monkeypatch):
    """Przeglad R6: aliasy ewaluatorow == klucze WEJSCIA (mapowanie kolumn), bez prawdziwego SDK."""
    wywolania = {}

    def klasa(nazwa):
        class Falszywy:
            def __init__(self, model_config, **opcje):
                wywolania[nazwa] = (model_config, opcje)
        return Falszywy

    nazwy = ("GroundednessEvaluator", "RelevanceEvaluator", "ResponseCompletenessEvaluator", "RetrievalEvaluator")
    ev = types.ModuleType("azure.ai.evaluation")
    for n in nazwy:
        setattr(ev, n, klasa(n))
    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.ai", types.ModuleType("azure.ai"))
    monkeypatch.setitem(sys.modules, "azure.ai.evaluation", ev)
    wynik = foundry.zbuduj_ewaluatory({"azure_endpoint": "https://x"}, "CRED", True)
    assert set(wynik) == set(foundry.WEJSCIA)
    assert set(foundry.mapowanie_kolumn()) == set(wynik)
    assert set(wywolania) == set(nazwy)
    assert all(o == {"credential": "CRED", "is_reasoning_model": True} for _, o in wywolania.values())


def test_oczysc_sedzia_json_bez_tresci_i_bez_mutacji():
    props = {"prompt_tokens": 10, "completion_tokens": 2, "model": "m", "sample_input": "TRESC", "sample_output": "TRESC",
             "thought_chain": "TRESC"}
    wynik = {"rows": [{"inputs.id": "Z01", "inputs.query": "TRESC", "inputs.context": "TRESC",
                       "inputs.response": "TRESC", "inputs.ground_truth": "TRESC",
                       "outputs.groundedness.groundedness": 5.0, "outputs.groundedness.groundedness_properties": props,
                       "outputs.retrieval.retrieval_properties": "tekst-nieznany"}],
             "metrics": {"groundedness.groundedness": 5.0}, "studio_url": "https://ai.azure.com/x"}
    kopia = json.loads(json.dumps(wynik))
    czysty = foundry.oczysc_sedzia_json(wynik)
    assert wynik == kopia  # wejscie nietkniete
    assert "TRESC" not in json.dumps(czysty)
    wiersz = czysty["rows"][0]
    assert wiersz["inputs.id"] == "Z01" and wiersz["outputs.groundedness.groundedness"] == 5.0
    assert wiersz["outputs.groundedness.groundedness_properties"] == {"prompt_tokens": 10, "completion_tokens": 2, "model": "m"}
    assert "outputs.retrieval.retrieval_properties" not in wiersz
    assert czysty["metrics"] == wynik["metrics"] and czysty["studio_url"] == wynik["studio_url"]


def test_oczysc_sedzia_json_bez_rows():
    assert foundry.oczysc_sedzia_json({"metrics": {}}) == {"metrics": {}}


# ---------------------------------------------------------------------------------------------
# CLI foundry_uruchom (zadanie 5) - bez sieci i bez SDK: evaluate, ewaluatory i MLflow podmieniane
# ---------------------------------------------------------------------------------------------

PROJEKT = ["--projekt", "https://p/api/projects/e"]
KLUCZ = "20261022-1810_szkody_gpt-5-mini"


def _plik_wynikow(tmp_path, wiersze) -> Path:
    p = tmp_path / f"{KLUCZ}.json"
    p.write_text(json.dumps({"model": "gpt-5-mini", "modul": "szkody", "metadane": {}, "przypadki": wiersze}),
                 encoding="utf-8")
    return p


def _oczekiwane(tmp_path, ids_llm, ids_reguly=()) -> list[str]:
    katalog = tmp_path / "oczekiwane"
    katalog.mkdir(exist_ok=True)
    for id_ in ids_llm:
        (katalog / f"{id_}.json").write_text(json.dumps({"id": id_, "decyzja_llm": "POKRYTA"}), encoding="utf-8")
    for id_ in ids_reguly:
        (katalog / f"{id_}.json").write_text(json.dumps({"id": id_, "decyzja_llm": None}), encoding="utf-8")
    return ["--oczekiwane", str(katalog)]


@pytest.fixture(autouse=True)
def _bez_sdk(monkeypatch):
    # CI/.venv nie ma azure-ai-evaluation - ewaluatory zastepcze, evaluate podmieniany w testach
    monkeypatch.setattr(foundry_uruchom, "_ewaluatory", lambda *a: {})
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x")
    monkeypatch.delenv("AZURE_EVAL_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)
    monkeypatch.setenv("PF_WORKER_COUNT", "pocz")  # rejestruje przywrocenie - main nie przecieka zmiennej do innych testow
    monkeypatch.delenv("PF_WORKER_COUNT")


def _evaluate_zwraca(monkeypatch, wynik, przekazane=None):
    def falszywy(**kw):
        (przekazane if przekazane is not None else {}).update(kw)
        return wynik
    monkeypatch.setattr(foundry_uruchom, "uruchom_evaluate", falszywy)


def _zaloguj_zapisuje(monkeypatch, zapis: dict, zwraca="run123"):
    def falszywy(**kw):
        zapis.update(kw)
        # czytamy tresc od razu - katalog tymczasowy znika po tescie
        zapis["tresc_artefaktow"] = {a.name: a.read_text(encoding="utf-8") for a in kw["artefakty"]}
        return zwraca
    monkeypatch.setattr(foundry_uruchom, "_zaloguj", falszywy)


def test_cli_stary_plik_kod_3(tmp_path):
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [{"id": "Z01"}])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 3


def test_cli_brak_endpointu_kod_2(tmp_path, monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT")
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 2


def test_cli_brak_projektu_kod_2_chyba_ze_bez_foundry(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK | {"studio_url": None})
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 2
    assert foundry_uruchom.main([*args, "--bez-foundry"]) == 0


def test_cli_projekt_bez_studio_url_kod_8(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK | {"studio_url": ""})
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 8


def test_cli_graf_padl_wszedzie_kod_7(tmp_path, monkeypatch):
    """Graf padl: wszystkie wiersze ocenia_llm=False i blad - bez kodu 7 bylby falszywy sukces (0 wierszy do sedziego)."""
    _evaluate_zwraca(monkeypatch, {"rows": [], "metrics": {}, "studio_url": "https://ai.azure.com/x"})
    wiersze = [_wiersz(i, ocenia_llm=False, blad="Timeout") for i in ("Z01", "Z09")]
    args = ["--wyniki", str(_plik_wynikow(tmp_path, wiersze)), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"], ["Z09"])]
    assert foundry_uruchom.main(args) == 7


def test_cli_mniej_ocen_llm_niz_oczekiwanych_kod_7(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01"), _wiersz("Z10", ocenia_llm=False)])),
            *PROJEKT, *_oczekiwane(tmp_path, ["Z01", "Z10"])]
    assert foundry_uruchom.main(args) == 7


def test_cli_inny_wiersz_z_ocena_llm_nie_maskuje_braku_kod_7(tmp_path, monkeypatch):
    """Ta sama liczba wierszy z ocena LLM co oczekiwanych, ale nie ten przypadek - porownanie zbiorow, nie licznikow."""
    _evaluate_zwraca(monkeypatch, WYNIK)
    wiersze = [_wiersz("Z01"), _wiersz("Z05"), _wiersz("Z10", ocenia_llm=False)]
    args = ["--wyniki", str(_plik_wynikow(tmp_path, wiersze)), *PROJEKT, *_oczekiwane(tmp_path, ["Z01", "Z10"])]
    assert foundry_uruchom.main(args) == 7


def test_cli_blad_w_jednym_wierszu_kod_7(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01", blad="RateLimit")])),
            *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 7


def test_cli_zly_katalog_oczekiwanych_kod_2(tmp_path, monkeypatch):
    """Zla sciezka --oczekiwane to nie '0 oczekiwanych = wszystko OK'."""
    _evaluate_zwraca(monkeypatch, WYNIK)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT,
            "--oczekiwane", str(tmp_path / "nie_ma")]
    assert foundry_uruchom.main(args) == 2


def test_cli_pusta_ocena_kod_6(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, {"rows": [{"inputs.id": "Z01"}], "metrics": {}, "studio_url": "https://ai.azure.com/x"})
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 6


def test_cli_nieznany_result_to_kod_6_nie_cichy_fail(tmp_path, monkeypatch):
    wynik = WYNIK | {"rows": [_wiersz_wyniku("Z01", **{"outputs.relevance.relevance_result": "error"})]}
    _evaluate_zwraca(monkeypatch, wynik)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 6


def test_cli_wyjatek_evaluate_kod_4_komunikat_przyciety(tmp_path, monkeypatch, capsys):
    def pada(**kw):
        raise RuntimeError("403 brak roli " + "x" * 1000)
    monkeypatch.setattr(foundry_uruchom, "uruchom_evaluate", pada)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 4
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "403 brak roli" in err and len(err) < 500


def test_cli_mlflow_z_wymaga_wynikow(tmp_path):
    assert foundry_uruchom.main(["--mlflow-z", str(tmp_path / "x_sedzia.json")]) == 2


def test_cli_zapisuje_jsonl_i_raport(tmp_path, monkeypatch):
    przekazane = {}
    _evaluate_zwraca(monkeypatch, WYNIK, przekazane)
    plik = _plik_wynikow(tmp_path, [_wiersz("Z01"), _wiersz("Z10", decyzja_ok=False), _wiersz("Z11", ocenia_llm=False)])
    assert foundry_uruchom.main(["--wyniki", str(plik), *PROJEKT, *_oczekiwane(tmp_path, ["Z01", "Z10"], ["Z11"])]) == 0
    assert przekazane["evaluation_name"] == "szkody-20261022-1810_szkody_gpt-5-mini"
    assert przekazane["tags"] == {"klucz_przebiegu": "20261022-1810_szkody_gpt-5-mini"}
    assert przekazane["azure_ai_project"] == "https://p/api/projects/e"
    jsonl = (tmp_path / "20261022-1810_szkody_gpt-5-mini_sedzia.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(jsonl) == 2  # Z11 (reguly) poza sedzia
    md = (tmp_path / "20261022-1810_szkody_gpt-5-mini_rozjazdy.md").read_text(encoding="utf-8")
    assert "sedzia_poblazliwy" in md and "Z11" in md  # tabela pelna, n/d dla regul


def test_cli_ustawia_pf_worker_count_przed_evaluate(tmp_path, monkeypatch):
    """R3: domyslnie 3 (limit TPM), ale jawna wartosc operatora wygrywa (setdefault)."""
    widziane = []

    def falszywy(**kw):
        widziane.append(os.environ.get("PF_WORKER_COUNT"))
        return WYNIK
    monkeypatch.setattr(foundry_uruchom, "uruchom_evaluate", falszywy)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 0
    monkeypatch.setenv("PF_WORKER_COUNT", "7")
    assert foundry_uruchom.main(args) == 0
    assert widziane == ["3", "7"]


def test_cli_rozumowanie_i_model_config_do_ewaluatorow(tmp_path, monkeypatch):
    zapis = []
    monkeypatch.setattr(foundry_uruchom, "_ewaluatory", lambda mc, r: zapis.append((mc, r)) or {})
    _evaluate_zwraca(monkeypatch, WYNIK)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 0
    assert foundry_uruchom.main([*args, "--bez-rozumowania", "--sedzia", "gpt-4o-mini"]) == 0
    assert zapis[0][1] is True and zapis[1][1] is False
    assert zapis[1][0]["azure_deployment"] == "gpt-4o-mini" and zapis[1][0]["azure_endpoint"] == "https://x"


# --- MLflow ----------------------------------------------------------------------------------

WYNIK_Z_TRESCIA = WYNIK | {"rows": [
    {"inputs.id": "Z01", "inputs.query": "TAJNE", "inputs.context": "TAJNE", "inputs.response": "TAJNE",
     "inputs.ground_truth": "TAJNE",
     **{f"outputs.{n}.{n}": 5.0 for n in foundry.WEJSCIA},
     **{f"outputs.{n}.{n}_result": "pass" for n in foundry.WEJSCIA},
     "outputs.groundedness.groundedness_properties": {"prompt_tokens": 9, "sample_input": "TAJNE",
                                                     "sample_output": "TAJNE", "thought_chain": "TAJNE"}}]}


def test_cli_mlflow_loguje_oczyszczone_artefakty(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK_Z_TRESCIA)
    zapis = {}
    _zaloguj_zapisuje(monkeypatch, zapis)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"]),
            "--mlflow"]
    assert foundry_uruchom.main(args) == 0
    assert sorted(zapis["tresc_artefaktow"]) == [f"{KLUCZ}_rozjazdy.md", f"{KLUCZ}_sedzia_mlflow.json"]  # bez .jsonl (R2)
    assert all("TAJNE" not in t for t in zapis["tresc_artefaktow"].values())  # R1
    assert "prompt_tokens" in zapis["tresc_artefaktow"][f"{KLUCZ}_sedzia_mlflow.json"]
    assert zapis["zrodlo"] == "foundry"
    assert zapis["tagi_dodatkowe"] == {"modul": "szkody-sedzia", "klucz_przebiegu": KLUCZ,
                                       "foundry_url": "https://ai.azure.com/x"}
    assert zapis["metryki"]["sedzia_groundedness"] == 5.0
    assert zapis["tabela"]["id"] == ["Z01"] and zapis["parametry"]["sedzia"] == "gpt-5-mini"
    assert zapis["wiersze"] == []  # zadnych wierszy z tekstami RAG do zaloguj_przebieg


def test_cli_mlflow_import_error_kod_5_z_poleceniem(tmp_path, monkeypatch, capsys):
    _evaluate_zwraca(monkeypatch, WYNIK)

    def brak_mlflow(**kw):
        raise ImportError("No module named 'mlflow'")
    monkeypatch.setattr(foundry_uruchom, "_zaloguj", brak_mlflow)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"]),
            "--mlflow"]
    assert foundry_uruchom.main(args) == 5
    # m1 (przeglad koncowy): pelne sciezki, bo polecenie jest kopiowane z innego katalogu roboczego
    assert (f'--mlflow-z "{tmp_path / f"{KLUCZ}_sedzia.json"}" '
            f'--wyniki "{tmp_path / f"{KLUCZ}.json"}"') in capsys.readouterr().err


def test_cli_mlflow_wyjatek_logowania_kod_5(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK)

    def pada(**kw):
        raise RuntimeError("serwer")
    monkeypatch.setattr(foundry_uruchom, "_zaloguj", pada)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"]),
            "--mlflow"]
    assert foundry_uruchom.main(args) == 5


def _gotowy_przebieg(tmp_path, wynik, wiersze, ids_llm=("Z01",), ids_reguly=()):
    wyniki = _plik_wynikow(tmp_path, wiersze)
    sedzia = tmp_path / f"{KLUCZ}_sedzia.json"
    sedzia.write_text(json.dumps(wynik), encoding="utf-8")
    return ["--mlflow-z", str(sedzia), "--wyniki", str(wyniki), *_oczekiwane(tmp_path, ids_llm, ids_reguly)]


def test_cli_mlflow_z_niepelne_oceny_kod_6_bez_logowania(tmp_path, monkeypatch):
    """R4: MLflow nie moze dostac srednich z niepelnych ocen - kod 6 i _zaloguj nie jest wolany."""
    def nie_wolac(**kw):
        raise AssertionError("zaloguj nie moze byc wolany przy niepelnych ocenach")
    monkeypatch.setattr(foundry_uruchom, "_zaloguj", nie_wolac)
    z10 = _wiersz_wyniku("Z10")  # Z01 w pelni, Z10 tylko 3 z 4 ewaluatorow
    del z10["outputs.relevance.relevance"]
    wynik = WYNIK | {"rows": [_wiersz_wyniku("Z01"), z10]}
    args = _gotowy_przebieg(tmp_path, wynik, [_wiersz("Z01"), _wiersz("Z10")], ids_llm=("Z01", "Z10"))
    assert foundry_uruchom.main(args) == 6


def test_cli_mlflow_z_pusty_wiersz_kod_6(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry_uruchom, "_zaloguj", lambda **kw: pytest.fail("nie wolno logowac"))
    args = _gotowy_przebieg(tmp_path, WYNIK, [_wiersz("Z11")], ids_llm=("Z11",))  # Z11 w WYNIK ma pusty wiersz
    assert foundry_uruchom.main(args) == 6


def test_cli_mlflow_z_stary_plik_kod_3(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry_uruchom, "_zaloguj", lambda **kw: pytest.fail("nie wolno logowac"))
    args = _gotowy_przebieg(tmp_path, WYNIK, [{"id": "Z01", "decyzja_ok": True}])
    assert foundry_uruchom.main(args) == 3


def test_cli_mlflow_z_pelne_oceny_loguje_oczyszczone(tmp_path, monkeypatch):
    zapis = {}
    _zaloguj_zapisuje(monkeypatch, zapis)
    args = _gotowy_przebieg(tmp_path, WYNIK_Z_TRESCIA, [_wiersz("Z01"), _wiersz("Z11", ocenia_llm=False)],
                            ids_reguly=("Z11",))
    assert foundry_uruchom.main(args) == 0
    assert all("TAJNE" not in t for t in zapis["tresc_artefaktow"].values())
    assert zapis["tabela"]["klasa"] == ["zgoda_ok", "n/d"]
    assert zapis["tagi_dodatkowe"]["foundry_url"] == "https://ai.azure.com/x"
    assert "sedzia" not in zapis["parametry"]  # z pliku nie wiadomo, jaki sedzia - nie zgadujemy


def test_cli_mlflow_z_pliki_z_roznych_przebiegow_kod_2(tmp_path, monkeypatch):
    """Recenzja I2: _sedzia.json innego przebiegu niz --wyniki nie moze trafic do MLflow."""
    monkeypatch.setattr(foundry_uruchom, "_zaloguj", lambda **kw: pytest.fail("nie wolno logowac"))
    args = _gotowy_przebieg(tmp_path, WYNIK, [_wiersz("Z01")])
    obcy = tmp_path / "20260101-0000_szkody_gpt-5-mini_sedzia.json"
    obcy.write_text(json.dumps(WYNIK), encoding="utf-8")
    args[1] = str(obcy)
    assert foundry_uruchom.main(args) == 2


@pytest.mark.parametrize("wiersze, ids_llm", [
    ([_wiersz("Z01"), _wiersz("Z10", ocenia_llm=False)], ("Z01", "Z10")),  # brak oceny LLM tam, gdzie oczekiwana
    ([_wiersz("Z01", blad="Timeout")], ("Z01",)),                          # blad w wierszu
])
def test_cli_mlflow_z_przebieg_niepelny_kod_7_bez_logowania(tmp_path, monkeypatch, wiersze, ids_llm):
    """Recenzja I2: ta sama bramka 7 co w pelnym przebiegu, przed logowaniem."""
    monkeypatch.setattr(foundry_uruchom, "_zaloguj", lambda **kw: pytest.fail("nie wolno logowac"))
    args = _gotowy_przebieg(tmp_path, WYNIK, wiersze, ids_llm=ids_llm)
    assert foundry_uruchom.main(args) == 7


def test_cli_mlflow_z_zly_katalog_oczekiwanych_kod_2(tmp_path):
    args = _gotowy_przebieg(tmp_path, WYNIK, [_wiersz("Z01")])
    args[-1] = str(tmp_path / "nie_ma")
    assert foundry_uruchom.main(args) == 2


# --- m5: uszkodzone wejscia = kod 2, nie traceback ---------------------------------------------

def test_cli_brak_pliku_wynikow_kod_2(tmp_path):
    assert foundry_uruchom.main(["--wyniki", str(tmp_path / "nie_ma.json"), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]) == 2


@pytest.mark.parametrize("tresc", ["to nie json", "[]", '{"model": "x"}', '{"przypadki": [1, 2]}', '{"przypadki": "x"}'])
def test_cli_uszkodzony_plik_wynikow_kod_2(tmp_path, tresc):
    p = tmp_path / f"{KLUCZ}.json"
    p.write_text(tresc, encoding="utf-8")
    assert foundry_uruchom.main(["--wyniki", str(p), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]) == 2


@pytest.mark.parametrize("tresc", ["to nie json", "[1]"])
def test_cli_uszkodzony_plik_oczekiwanych_kod_2(tmp_path, monkeypatch, tresc):
    _evaluate_zwraca(monkeypatch, WYNIK)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    (tmp_path / "oczekiwane" / "Z02.json").write_text(tresc, encoding="utf-8")
    assert foundry_uruchom.main(args) == 2


def test_cli_mlflow_z_uszkodzony_sedzia_json_kod_2(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry_uruchom, "_zaloguj", lambda **kw: pytest.fail("nie wolno logowac"))
    args = _gotowy_przebieg(tmp_path, WYNIK, [_wiersz("Z01")])
    Path(args[1]).write_text("{uszkodzony", encoding="utf-8")
    assert foundry_uruchom.main(args) == 2


# --- m3: zdublowane inputs.id ------------------------------------------------------------------

def test_zdublowane_id_w_wyniku_to_brak_oceny():
    wynik = {"rows": [_wiersz_wyniku("Z01"), _wiersz_wyniku("Z01", **{"outputs.relevance.relevance": 1.0})]}
    oceny = foundry.oceny_z_wyniku(wynik)
    assert oceny["Z01"] == {}  # nie wiadomo, ktory wiersz jest wlasciwy - zaden
    assert foundry.wiersze_bez_oceny([_wiersz("Z01")], oceny) == ["Z01"]


def test_cli_zdublowane_id_kod_6(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK | {"rows": [_wiersz_wyniku("Z01"), _wiersz_wyniku("Z01")]})
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 6


# --- I1: lista dozwolonych pol w oczysc_sedzia_json --------------------------------------------

def test_oczysc_lista_dozwolonych_odrzuca_nieznane():
    wiersz = {"inputs.id": "Z01", "inputs.ocenia_llm": True,
              "inputs.nowa_kolumna": "TAJNE", "inputs.query": "TAJNE",
              "outputs.groundedness.groundedness": 5.0, "outputs.groundedness.groundedness_score": 5.0,
              "outputs.groundedness.groundedness_result": "pass", "outputs.groundedness.groundedness_passed": True,
              "outputs.groundedness.groundedness_threshold": 3, "outputs.groundedness.groundedness_status": "completed",
              "outputs.groundedness.groundedness_reason": "TAJNE",
              "outputs.groundedness.groundedness_nowe_pole": "TAJNE",
              "outputs.nieznany_ewaluator.nieznany_ewaluator": 1.0,
              "outputs.groundedness.groundedness_properties": {
                  "prompt_tokens": 9, "completion_tokens": 2, "model": "m", "finish_reason": "stop",
                  "nowy_klucz": "TAJNE", "sample_input": "TAJNE"}}
    wynik = {"rows": [wiersz], "metrics": {"groundedness.groundedness": 5.0, "tekst": "TAJNE", "flaga": True,
                                           "slownik": {"a": 1}},
             "studio_url": "https://ai.azure.com/x", "nowy_klucz_gorny": "TAJNE", "evaluation_results_list": ["TAJNE"]}
    czysty = foundry.oczysc_sedzia_json(wynik)
    assert "TAJNE" not in json.dumps(czysty)
    assert set(czysty) == {"rows", "metrics", "studio_url"}
    assert czysty["metrics"] == {"groundedness.groundedness": 5.0}
    assert czysty["rows"][0] == {
        "inputs.id": "Z01", "inputs.ocenia_llm": True,
        "outputs.groundedness.groundedness": 5.0, "outputs.groundedness.groundedness_score": 5.0,
        "outputs.groundedness.groundedness_result": "pass", "outputs.groundedness.groundedness_passed": True,
        "outputs.groundedness.groundedness_threshold": 3, "outputs.groundedness.groundedness_status": "completed",
        "outputs.groundedness.groundedness_properties": {
            "prompt_tokens": 9, "completion_tokens": 2, "model": "m", "finish_reason": "stop"}}


def test_oczysc_dozwolone_pola_wszystkich_czterech_ewaluatorow():
    wiersz = _wiersz_wyniku("Z01")
    czysty = foundry.oczysc_sedzia_json({"rows": [wiersz]})["rows"][0]
    assert czysty == wiersz  # wszystkie dozwolone klucze przechodza


def test_klucze_jsonl_pochodza_z_szkody():
    """Przeglad koncowy m4: jedno zrodlo prawdy o polach RAG, bez duplikatu listy w foundry.py."""
    from ewaluacja.szkody import KLUCZE_RAG
    assert foundry.KLUCZE_JSONL == ("id", *KLUCZE_RAG)
