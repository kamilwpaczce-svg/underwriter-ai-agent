"""Etap 24, zadanie 4: `uruchom.py --wariant`, trasy oczekiwane, pola wariantu w JSON ewaluacji,
zgodnosc z `statystyka stabilnosc/porownaj`. Wszystko offline: `--atrapa`, `tmp_path`."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent.model_azure import ModelAzure
from ewaluacja import statystyka, uruchom
from ewaluacja.atrapa import ModelAtrapa
from ewaluacja.porownanie import przypadek_w_pelni_zgodny
from ewaluacja.szkody import przypadek_szkody_zgodny, wszystkie_id_szkod
from ewaluacja import trasy_oczekiwane as trasy

WARIANTY = ("jeden", "wieloagentowy")
ID_WNIOSKOW = [f"W{i:02d}" for i in range(1, 15)]
ID_SZKOD = [f"Z{i:02d}" for i in range(1, 13)]


def _bieg(monkeypatch, tmp_path: Path, *argv: str) -> dict:
    """Jeden bieg `uruchom.main --atrapa ...` -> wczytany JSON wyniku (jedyny plik nowy w katalogu)."""
    katalog = tmp_path / f"bieg{len(list(tmp_path.glob('bieg*')))}"
    katalog.mkdir()
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", katalog)
    assert uruchom.main(["--atrapa", *argv]) == 0
    (plik,) = katalog.glob("*.json")
    wynik = json.loads(plik.read_text(encoding="utf-8"))
    wynik["_plik"] = plik
    return wynik


# ---------------------------------------------------------------------------
# trasy_oczekiwane: pomocnicze funkcje
# ---------------------------------------------------------------------------

def test_trasa_z_logu_zdejmuje_sufiksy_prob_i_zwija_powtorzenia():
    log = [
        {"wezel": "wczytaj"},
        {"wezel": "ekstrahuj_proba1_blad"},
        {"wezel": "ekstrahuj"},
        {"wezel": "waliduj"},
    ]
    assert trasy.trasa_z_logu(log) == ["wczytaj", "ekstrahuj", "waliduj"]


def test_trasa_agentow_z_logu_dla_wariantu_jeden_zwija_wezly_do_agentow():
    log = [{"wezel": w} for w in ("wczytaj", "klasyfikuj", "ekstrahuj_szkode", "sprawdz_polise",
                                  "ocen_ryzyko_szkody", "szukaj_owu", "ocen_pokrycie", "kontrola_cytatow",
                                  "zatwierdzenie")]
    assert trasy.trasa_agentow({"log": log}) == ["agent_szkod", "agent_owu"]


def test_trasa_agentow_wariantu_wieloagentowego_bierze_pole_stanu():
    stan = {"trasa_agentow": ["agent_szkod"], "log": [{"wezel": "supervisor"}]}
    assert trasy.trasa_agentow(stan) == ["agent_szkod"]


def test_trasy_oczekiwane_pokrywaja_wszystkie_26_przypadkow():
    assert sorted(trasy.TRASY_OCZEKIWANE) == sorted(ID_WNIOSKOW + ID_SZKOD)
    assert trasy.TRASY_OCZEKIWANE["W14"] == []
    assert trasy.TRASY_OCZEKIWANE["W01"] == ["agent_underwritingu"]
    assert trasy.TRASY_OCZEKIWANE["Z01"] == ["agent_szkod", "agent_owu"]
    assert trasy.TRASY_OCZEKIWANE["Z09"] == ["agent_szkod"]  # S01: bez OWU
    assert trasy.TRASY_OCZEKIWANE["Z12"] == ["agent_szkod"]  # podejrzane instrukcje: bez OWU


def test_trasy_oczekiwane_zgadzaja_sie_z_biegiem_atrapy_wariantu_jeden(monkeypatch, tmp_path):
    """Straznik rozjazdu: plik wzorcow = to, co dzis robi graf `jeden` na atrapie."""
    wnioski = _bieg(monkeypatch, tmp_path, "--wariant", "jeden")
    szkody = _bieg(monkeypatch, tmp_path, "--wariant", "jeden", "--modul", "szkody")
    for w in wnioski["przypadki"] + szkody["przypadki"]:
        assert w["trasa_agentow"] == trasy.TRASY_OCZEKIWANE[w["id"]], w["id"]


def test_trasa_zgodna_wykrywa_inna_trase():
    assert trasy.trasa_zgodna("Z01", ["agent_szkod", "agent_owu"]) is True
    assert trasy.trasa_zgodna("Z01", ["agent_szkod"]) is False
    assert trasy.trasa_zgodna("NIEZNANY", []) is False  # brak wzorca = nie "zgodna"


# ---------------------------------------------------------------------------
# uruchom.py --wariant: wnioski
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wariant", WARIANTY)
def test_wnioski_atrapa_14_na_14_i_trasa_zgodna_w_obu_wariantach(monkeypatch, tmp_path, wariant):
    wynik = _bieg(monkeypatch, tmp_path, "--wariant", wariant)
    assert wynik["metadane"]["wariant"] == wariant
    assert [w["id"] for w in wynik["przypadki"]] == ID_WNIOSKOW
    assert sum(przypadek_w_pelni_zgodny(w) for w in wynik["przypadki"]) == 14
    assert sum(w["decyzja_llm_ok"] for w in wynik["przypadki"]) == 14
    assert sum(w["trasa_zgodna"] for w in wynik["przypadki"]) == 14
    assert wynik["metadane"]["liczba_ok"] == 14


@pytest.mark.parametrize("wariant", WARIANTY)
def test_wiersz_ma_pola_z_decyzji_10(monkeypatch, tmp_path, wariant):
    wynik = _bieg(monkeypatch, tmp_path, "--wariant", wariant, "--przypadki", "W01,W14")
    for w in wynik["przypadki"]:
        for pole in ("trasa", "trasa_agentow", "trasa_zgodna", "wywolania_supervisora", "korekty_supervisora",
                     "wywolania_llm_razem", "_wywolania_llm", "_czas_ms", "_tokeny_we", "_tokeny_wy"):
            assert pole in w, (w["id"], pole)
        assert isinstance(w["trasa"], list) and all(isinstance(x, str) for x in w["trasa"])
        assert not any("_proba" in x for x in w["trasa"])


def test_domyslny_wariant_to_jeden_a_plik_bez_sufiksu(monkeypatch, tmp_path):
    wynik = _bieg(monkeypatch, tmp_path, "--przypadki", "W01")
    assert wynik["metadane"]["wariant"] == "jeden"
    assert wynik["_plik"].name.endswith("_atrapa.json")
    assert all(w["wywolania_supervisora"] == 0 and w["korekty_supervisora"] == 0 for w in wynik["przypadki"])


def test_wieloagentowy_ma_osobna_nazwe_pliku(monkeypatch, tmp_path):
    wynik = _bieg(monkeypatch, tmp_path, "--wariant", "wieloagentowy", "--przypadki", "W01")
    assert wynik["_plik"].name.endswith("_atrapa_wieloagentowy.json")
    assert wynik["model"] == "atrapa"  # pole `model` bez sufiksu wariantu


def test_nieznany_wariant_to_blad_parsera():
    with pytest.raises(SystemExit) as e:
        uruchom.main(["--atrapa", "--wariant", "trzy"])
    assert e.value.code == 2


def test_trasa_wieloagentowego_ma_supervisora_a_jeden_klasyfikuj(monkeypatch, tmp_path):
    jeden = _bieg(monkeypatch, tmp_path, "--wariant", "jeden", "--przypadki", "W01")["przypadki"][0]
    wielo = _bieg(monkeypatch, tmp_path, "--wariant", "wieloagentowy", "--przypadki", "W01")["przypadki"][0]
    assert "klasyfikuj" in jeden["trasa"] and "supervisor" not in jeden["trasa"]
    assert "supervisor" in wielo["trasa"] and "klasyfikuj" not in wielo["trasa"]
    assert wielo["trasa_agentow"] == ["agent_underwritingu"]


def test_licznik_llm_wnioski_suma_taka_sama_skladniki_rozne(monkeypatch, tmp_path):
    """Krok 1 supervisora zastepuje `klasyfikuj`: `wywolania_llm` agentow jest o 1 nizsze,
    ale suma (agenci + supervisor) jest porownywalna z wariantem `jeden`."""
    jeden = _bieg(monkeypatch, tmp_path, "--wariant", "jeden", "--przypadki", "W01")["przypadki"][0]
    wielo = _bieg(monkeypatch, tmp_path, "--wariant", "wieloagentowy", "--przypadki", "W01")["przypadki"][0]
    assert wielo["_wywolania_llm"] == jeden["_wywolania_llm"] - 1
    assert wielo["wywolania_supervisora"] == 1
    assert wielo["wywolania_llm_razem"] == wielo["_wywolania_llm"] + wielo["wywolania_supervisora"]
    assert wielo["wywolania_llm_razem"] == jeden["wywolania_llm_razem"] == jeden["_wywolania_llm"]


def test_metadane_licznikow_skladniki_i_suma(monkeypatch, tmp_path):
    wynik = _bieg(monkeypatch, tmp_path, "--wariant", "wieloagentowy", "--przypadki", "W01,W02")
    m = wynik["metadane"]
    assert m["wywolania_supervisora_laczne"] == 2
    assert m["wywolania_llm_agenci_laczne"] == sum(w["_wywolania_llm"] for w in wynik["przypadki"])
    assert m["wywolania_llm_laczne"] == m["wywolania_llm_agenci_laczne"] + m["wywolania_supervisora_laczne"]


def test_bezpiecznik_liczy_sume_z_supervisorem(monkeypatch, tmp_path):
    """W01 w wieloagentowym: agenci 2 + supervisor 1 = 3 > 2; same wywolania agentow (2) limitu by nie przekroczyly."""
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path)
    monkeypatch.setattr(uruchom, "LIMIT_LACZNY_WYWOLAN", 2)
    assert uruchom.main(["--atrapa", "--wariant", "wieloagentowy", "--przypadki", "W01"]) == 3


# ---------------------------------------------------------------------------
# uruchom.py --wariant: szkody
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wariant", WARIANTY)
def test_szkody_atrapa_12_na_12_i_trasa_zgodna_w_obu_wariantach(monkeypatch, tmp_path, wariant):
    wynik = _bieg(monkeypatch, tmp_path, "--wariant", wariant, "--modul", "szkody")
    assert wynik["metadane"]["wariant"] == wariant
    assert [w["id"] for w in wynik["przypadki"]] == ID_SZKOD == wszystkie_id_szkod()
    assert sum(przypadek_szkody_zgodny(w) for w in wynik["przypadki"]) == 12
    assert sum(w["decyzja_ok"] for w in wynik["przypadki"]) == 12
    assert sum(w["trasa_zgodna"] for w in wynik["przypadki"]) == 12
    assert wynik["_plik"].name.endswith("_szkody_atrapa_wieloagentowy.json") == (wariant == "wieloagentowy")


def test_szkody_licznik_llm_krok_2_supervisora_to_plus_jeden(monkeypatch, tmp_path):
    """Wieloagentowy = krok 1 supervisora (zastepuje klasyfikuj) + krok 2 (nowy; po agencie szkod LLM wybiera
    OWU albo koniec) -> suma o 1 wyzsza niz w `jeden`, takze dla Z09 (S01, bez OWU: krok 2 konczy trase).
    Po agencie OWU przejscie jest deterministyczne (bez LLM), wiec Z01 tez ma 2 kroki."""
    ids = "Z01,Z09"
    jeden = _bieg(monkeypatch, tmp_path, "--wariant", "jeden", "--modul", "szkody", "--przypadki", ids)
    wielo = _bieg(monkeypatch, tmp_path, "--wariant", "wieloagentowy", "--modul", "szkody", "--przypadki", ids)
    j = {w["id"]: w for w in jeden["przypadki"]}
    w = {x["id"]: x for x in wielo["przypadki"]}
    assert w["Z01"]["wywolania_supervisora"] == 2
    assert w["Z01"]["wywolania_llm_razem"] == j["Z01"]["wywolania_llm_razem"] + 1
    assert w["Z09"]["wywolania_supervisora"] == 2
    assert w["Z09"]["wywolania_llm_razem"] == j["Z09"]["wywolania_llm_razem"] + 1
    assert w["Z01"]["_wywolania_llm"] == j["Z01"]["_wywolania_llm"] - 1  # skladnik agentow: bez klasyfikuj


def test_szkody_wieloagentowy_zapisuje_uzasadnienia_supervisora(monkeypatch, tmp_path):
    wynik = _bieg(monkeypatch, tmp_path, "--wariant", "wieloagentowy", "--modul", "szkody", "--przypadki", "Z01")
    (z01,) = wynik["przypadki"]
    assert len(z01["uzasadnienia_supervisora"]) == 2 and all(isinstance(u, str) for u in z01["uzasadnienia_supervisora"])


# ---------------------------------------------------------------------------
# trasa_zgodna == False: supervisor wybiera dozwolone, ale inne niz graf `jeden`
# ---------------------------------------------------------------------------

def test_trasa_niezgodna_gdy_supervisor_konczy_za_wczesnie(monkeypatch, tmp_path):
    from agent.schematy import DecyzjaSupervisora

    class AtrapaKonczacaZaWczesnie(ModelAtrapa):
        def decyduj_supervisor(self, czesci, podsumowanie):
            decyzja, meta = super().decyduj_supervisor(czesci, podsumowanie)
            if czesci is None:  # krok 2
                decyzja = DecyzjaSupervisora(typ_dokumentu=None, nastepny="zakoncz", uzasadnienie="test")
            return decyzja, meta

    monkeypatch.setattr(uruchom, "_zbuduj_model", lambda *a, **k: AtrapaKonczacaZaWczesnie(uruchom.OCZEKIWANE_DIR))
    wynik = _bieg(monkeypatch, tmp_path, "--wariant", "wieloagentowy", "--modul", "szkody", "--przypadki", "Z01")
    (z01,) = wynik["przypadki"]
    assert z01["trasa_zgodna"] is False
    assert z01["trasa_agentow"] == ["agent_szkod"]
    assert z01["decyzja_ok"] is False  # SKIEROWANIE z powodem brak_oceny zamiast POKRYTA


# ---------------------------------------------------------------------------
# metadane: reasoning, MLflow
# ---------------------------------------------------------------------------

def test_metadane_zapisuja_reasoning_dla_azure():
    model = ModelAzure(llm=object(), reasoning_effort="low")
    assert uruchom._pola_metadanych_wariantu("wieloagentowy", model) == {"wariant": "wieloagentowy", "reasoning": "low"}


def test_metadane_bez_reasoning_dla_atrapy():
    assert uruchom._pola_metadanych_wariantu("jeden", ModelAtrapa(uruchom.OCZEKIWANE_DIR)) == {"wariant": "jeden"}


@pytest.mark.parametrize("modul_argv", [[], ["--modul", "szkody"]])
def test_mlflow_dostaje_tag_i_parametr_wariant(monkeypatch, tmp_path, modul_argv):
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path)
    przechwycone: dict = {}

    def falszywy_zaloguj(**kw):
        przechwycone.update(kw)
        return "run-1"

    monkeypatch.setattr(uruchom, "zaloguj_przebieg", falszywy_zaloguj)
    argv = ["--atrapa", "--wariant", "wieloagentowy", "--mlflow", "--przypadki", "Z01" if modul_argv else "W01", *modul_argv]
    assert uruchom.main(argv) == 0
    assert przechwycone["wariant"] == "wieloagentowy"  # osobny kwarg: `tagi_dodatkowe` zostaje bez zmian
    assert przechwycone["parametry"]["wariant"] == "wieloagentowy"
    assert przechwycone["metadane"]["wariant"] == "wieloagentowy"


# ---------------------------------------------------------------------------
# statystyka: JSON z atrapy czytany przez `stabilnosc` i `porownaj`
# ---------------------------------------------------------------------------

def _dwa_biegi(monkeypatch, tmp_path: Path, wariant: str, *argv: str) -> list[Path]:
    """Dwa biegi tego samego wariantu; pliki dostaja unikalne nazwy (znacznik czasu ma rozdzielczosc minuty)."""
    pliki = []
    for nr in (1, 2):
        wynik = _bieg(monkeypatch, tmp_path, "--wariant", wariant, *argv)
        cel = tmp_path / f"{wariant}_{'_'.join(a.strip('-') for a in argv) or 'wnioski'}_bieg{nr}.json"
        shutil.copy(wynik["_plik"], cel)
        pliki.append(cel)
    return pliki


@pytest.mark.parametrize("modul_argv,pole,n", [([], "decyzja_llm_ok", 14), (["--modul", "szkody"], "decyzja_ok", 12)])
def test_statystyka_czyta_wyniki_obu_wariantow(monkeypatch, tmp_path, capsys, modul_argv, pole, n):
    jeden = _dwa_biegi(monkeypatch, tmp_path, "jeden", *modul_argv)
    wielo = _dwa_biegi(monkeypatch, tmp_path, "wieloagentowy", *modul_argv)
    capsys.readouterr()

    for pliki in (jeden, wielo):
        assert statystyka.main(["stabilnosc", *map(str, pliki), "--pole", pole]) == 0
        out = capsys.readouterr().out
        assert f"2 biegow x {n} przypadkow" in out
        assert f"Wynik wiekszosciowy: {n}/{n}" in out

    raport = tmp_path / "porownanie.md"
    assert statystyka.main(["porownaj", str(jeden[0]), str(wielo[0]), "--pole", pole, "--zapisz", str(raport)]) == 0
    out = capsys.readouterr().out
    assert f"n = {n}" in out and "p = 1.0000" in out
    assert raport.read_text(encoding="utf-8").startswith("## Porownanie")


def test_statystyka_czyta_tez_pole_trasa_zgodna(monkeypatch, tmp_path, capsys):
    pliki = _dwa_biegi(monkeypatch, tmp_path, "wieloagentowy")
    capsys.readouterr()
    assert statystyka.main(["stabilnosc", *map(str, pliki), "--pole", "trasa_zgodna"]) == 0
    assert "Wynik wiekszosciowy: 14/14" in capsys.readouterr().out


def test_zaloguj_przebieg_ustawia_tag_wariant(monkeypatch, tmp_path):
    """Prawdziwy run MLflow (SQLite w tmp_path): kwarg `wariant` -> tag `wariant`; bez kwarga tagu nie ma."""
    pytest.importorskip("mlflow")
    from mlflow import MlflowClient

    from ewaluacja import mlflow_log

    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{(tmp_path / 'mlruns.db').as_posix()}")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "test-wariant")
    metadane = {"czas_calkowity_ms": 1.0, "wywolania_llm_laczne": 1, "tokeny_we_laczne": 0, "tokeny_wy_laczne": 0}
    # Pelny zestaw pol czytanych przez `przypadek_w_pelni_zgodny` (prawdziwy wiersz wniosku je ma).
    wiersze = [{
        "id": "W01", "typ_dokumentu_ok": True, "decyzja_llm_ok": True, "reguly_llm_ok": True,
        "decyzja_silnika_na_polach_llm_ok": True, "podejrzane_instrukcje_ok": True, "blad": None,
        "pola_trafione": 1, "pola_wszystkie": 1, "_wywolania_llm": 1, "_czas_ms": 1.0,
    }]
    r_wielo = mlflow_log.zaloguj_przebieg(
        parametry={"model": "atrapa"}, metadane=metadane, wiersze=wiersze, artefakty=[], czesciowy=False,
        wariant="wieloagentowy",
    )
    r_stary = mlflow_log.zaloguj_przebieg(
        parametry={"model": "atrapa"}, metadane=metadane, wiersze=wiersze, artefakty=[], czesciowy=False,
    )
    klient = MlflowClient()
    assert klient.get_run(r_wielo).data.tags["wariant"] == "wieloagentowy"
    assert "wariant" not in klient.get_run(r_stary).data.tags


def test_tagi_przebiegu_skladane_bez_mlflow():
    """Czysta funkcja skladajaca tagi (dziala bez zainstalowanego mlflow): wariant dochodzi jako tag,
    a bez wariantu tagi sa dokladnie dotychczasowe."""
    from ewaluacja import mlflow_log

    assert mlflow_log._tagi_przebiegu(False, "uruchom", None, None) == {"czesciowy": "false", "zrodlo": "uruchom"}
    assert mlflow_log._tagi_przebiegu(True, "uruchom", {"modul": "szkody"}, "wieloagentowy") == {
        "czesciowy": "true", "zrodlo": "uruchom", "modul": "szkody", "wariant": "wieloagentowy",
    }
