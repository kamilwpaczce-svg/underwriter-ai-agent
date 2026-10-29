"""Ewaluacja modulu szkodowego (Etap 10): `uruchom.py --modul szkody` na atrapie, metryki."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ewaluacja import uruchom
from ewaluacja.atrapa import ModelAtrapa
from ewaluacja.szkody import metryki_szkod, pola_rag, porownaj_szkode, przypadek_szkody_zgodny

OCZEKIWANY = {"id": "Z01", "decyzja": "POKRYTA", "paragrafy_oczekiwane": ["§4 ust. 1"]}


def _fragment(paragraf: int, ustep: int) -> dict:
    return {"id": f"p{paragraf}u{ustep}", "paragraf": paragraf, "ustep": ustep, "tytul": "T", "tresc": "x"}


def _stan(cytaty: list[dict], fragmenty: list[dict], kontrola: dict | None = None) -> dict:
    return {
        "typ_dokumentu": "SZKODA",
        "podejrzane_instrukcje": False,
        "wynik_polisy": {"kody": [], "braki": [], "polisa": {"nr_polisy": "X"}},
        "fragmenty_owu": fragmenty,
        "ocena_pokrycia": {"decyzja": "POKRYTA", "cytaty": cytaty, "brakujace_dokumenty": [], "dodatkowe_zapytanie": None},
        "kontrola_cytatow": kontrola,
        "log": [{"wezel": "ocen_pokrycie", "czas_ms": 1.0, "tokeny_we": 100, "tokeny_wy": 20}],
        "wywolania_llm": 3,
    }


def test_main_szkody_na_atrapie_12_na_12(monkeypatch, tmp_path):
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path)
    assert uruchom.main(["--atrapa", "--modul", "szkody"]) == 0
    (plik,) = tmp_path.glob("*_szkody_atrapa.json")
    wynik = json.loads(plik.read_text(encoding="utf-8"))
    assert wynik["modul"] == "szkody"
    assert [w["id"] for w in wynik["przypadki"]] == [f"Z{i:02d}" for i in range(1, 13)]
    assert all(przypadek_szkody_zgodny(w) for w in wynik["przypadki"])
    assert wynik["metadane"]["wyszukiwarka"] == "lokalna"
    assert len(wynik["metadane"]["wersja_owu"]) == 12
    assert sum(w["dodatkowe_zapytanie"] for w in wynik["przypadki"]) == 1


def test_domyslny_modul_to_wnioski(monkeypatch, tmp_path):
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path)
    assert uruchom.main(["--atrapa", "--przypadki", "W01"]) == 0
    assert not list(tmp_path.glob("*_szkody_*"))


def test_mlflow_trace_dla_szkod_odmawia(capsys):
    assert uruchom.main(["--atrapa", "--modul", "szkody", "--mlflow-trace"]) == 2
    assert "--mlflow-trace" in capsys.readouterr().err


def test_zla_konfiguracja_wyszukiwarki_bez_atrapy_konczy_kodem_2(monkeypatch, capsys):
    monkeypatch.setattr(uruchom, "_zbuduj_model", lambda *a, **k: ModelAtrapa(uruchom.OCZEKIWANE_DIR))
    monkeypatch.setenv("WYSZUKIWARKA", "elastic")
    assert uruchom.main(["--modul", "szkody", "--przypadki", "Z01"]) == 2
    assert "dozwolone" in capsys.readouterr().err


def test_cytat_odrzucony_przez_kontrole_nie_jest_trafiony():
    cytat = {"paragraf": "§ 4", "ustep": "1", "uzasadnienie": "x"}
    kontrola = {"ok": False, "powod": "cytat_spoza_kontekstu", "odrzucone": [cytat]}
    wiersz = porownaj_szkode(OCZEKIWANY, _stan([cytat], [_fragment(6, 1)], kontrola))
    assert wiersz["cytat_trafiony"] is False
    assert wiersz["kontrola_odrzucila"] is True
    assert wiersz["decyzja_ok"] is False
    assert wiersz["_tokeny_we"] == 100 and wiersz["_tokeny_wy"] == 20


def test_recall_liczy_tylko_piec_pierwszych_fragmentow():
    """Fragmenty 6..8 pochodza z dodatkowego zapytania - nie wchodza do recall@5."""
    fragmenty = [_fragment(1, u) for u in range(1, 6)] + [_fragment(4, 1)]
    cytat = {"paragraf": "§ 4", "ustep": "1", "uzasadnienie": "x"}
    wiersz = porownaj_szkode(OCZEKIWANY, _stan([cytat], fragmenty, {"ok": True, "powod": None, "odrzucone": []}))
    assert wiersz["recall_at_5"] is False
    assert wiersz["cytat_trafiony"] is True
    assert wiersz["decyzja_ok"] is True


def test_metryki_pomijaja_przypadki_bez_paragrafu():
    wiersze = [
        {"decyzja_ok": True, "cytat_trafiony": True, "recall_at_5": True, "kontrola_odrzucila": False, "dodatkowe_zapytanie": True},
        {"decyzja_ok": True, "cytat_trafiony": False, "recall_at_5": True, "kontrola_odrzucila": True, "dodatkowe_zapytanie": False},
        {"decyzja_ok": False, "cytat_trafiony": None, "recall_at_5": None, "kontrola_odrzucila": False, "dodatkowe_zapytanie": False},
    ]
    metadane = {"czas_calkowity_ms": 2000, "wywolania_llm_laczne": 7, "tokeny_we_laczne": 10, "tokeny_wy_laczne": 5}
    metryki = metryki_szkod(metadane, wiersze)
    assert metryki["decyzje_ok"] == 2.0
    assert metryki["przypadki_ok"] == 1.0
    assert metryki["cytat_trafiony"] == pytest.approx(0.5)
    assert metryki["recall_wyszukiwania_at_5"] == pytest.approx(1.0)
    assert metryki["kontrola_cytatow_odrzucila"] == 1.0
    assert metryki["dodatkowe_zapytania"] == 1.0
    assert metryki["czas_calkowity_s"] == pytest.approx(2.0)
    assert "koszt_llm_usd_szacunkowy" not in metryki


def test_mlflow_run_szkod_ma_tag_i_parametry(monkeypatch, tmp_path):
    mlflow = pytest.importorskip("mlflow")
    from mlflow import MlflowClient

    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{(tmp_path / 'mlruns.db').as_posix()}")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "test-szkody")
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path / "wyniki")
    assert uruchom.main(["--atrapa", "--modul", "szkody", "--mlflow", "--przypadki", "Z01,Z07"]) == 0

    eksperyment = mlflow.get_experiment_by_name("test-szkody")
    (run,) = MlflowClient().search_runs([eksperyment.experiment_id])
    assert run.data.tags["modul"] == "szkody"
    assert run.data.params["wyszukiwarka"] == "lokalna"
    assert run.data.params["top_k"] == "5"
    assert len(run.data.params["wersja_owu"]) == 12
    assert run.data.metrics["decyzje_ok"] == 2.0
    assert run.data.metrics["recall_wyszukiwania_at_5"] == 1.0
    assert run.data.metrics["dodatkowe_zapytania"] == 1.0


def test_skierowanie_z_bledu_nie_jest_trafiona_decyzja():
    # Z10/Z12 oczekuja SKIEROWANIE; awaria wyszukiwarki tez daje SKIEROWANIE - nie moze sie liczyc.
    oczekiwany = {"id": "Z10", "decyzja": "SKIEROWANIE", "paragrafy_oczekiwane": []}
    stan = {**_stan([], []), "ocena_pokrycia": None, "blad": "Blad wyszukiwania OWU (azure, wezel szukaj_owu): 403"}
    wiersz = porownaj_szkode(oczekiwany, stan)
    assert wiersz["decyzja_otrzymana"] == "SKIEROWANIE"
    assert wiersz["decyzja_ok"] is False


class _PadajacaWyszukiwarka:
    nazwa = "azure"

    def szukaj(self, zapytanie, k=5):
        raise RuntimeError("(Forbidden) brak roli Search Index Data Reader")


def test_awaria_wyszukiwarki_przerywa_ewaluacje_bez_zapisu(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path)
    monkeypatch.setattr(uruchom, "_zbuduj_model", lambda *a, **k: ModelAtrapa(uruchom.OCZEKIWANE_DIR))
    monkeypatch.setattr(uruchom, "zbuduj_wyszukiwarke", lambda *a, **k: _PadajacaWyszukiwarka())
    assert uruchom.main(["--modul", "szkody", "--przypadki", "Z01,Z10"]) == 5
    assert "Forbidden" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())



def test_brak_konfiguracji_azure_przerywa_kodem_2_bez_zapisu(monkeypatch, tmp_path, capsys):
    # Przebieg 2026-10-21: bez AZURE_DOCINT_ENDPOINT 12/12 = blad_agenta, a skrypt konczyl sie kodem 0.
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path)
    monkeypatch.setattr(uruchom, "uruchom_szkode", lambda *a, **k: {
        "blad": "Blad wezla 'klasyfikuj' po 2 probach (typ bledu: BrakKonfiguracjiAzure)."})
    assert uruchom.main(["--atrapa", "--modul", "szkody", "--mlflow", "--przypadki", "Z01,Z10"]) == 2
    assert "AZURE_DOCINT_ENDPOINT" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())

# --- Etap 14, zadanie 1: pola RAG dla sedziego LLM ---

NIP_TESTOWY = "9524044407"


def _stan_z_polami() -> dict:
    stan = _stan(
        cytaty=[{"paragraf": "4", "ustep": "3", "uzasadnienie": "Zalanie z instalacji tryskaczowej jest objete."}],
        fragmenty=[{"id": "p4u3", "paragraf": 4, "ustep": 3, "tytul": "T", "tresc": "§ 4. Zakres\nust. 3. Zalanie."}],
    )
    stan["pola"] = {
        "nip": NIP_TESTOWY, "ubezpieczony": "Hurtownia Papieru Mazur sp. z o.o.", "nr_polisy": "PL/MSP/2026/0004",
        "miejsce": {"ulica": "ul. Skladowa 8", "kod": "05-500", "miasto": "Piaseczno"},
        "przyczyna": "Zalanie magazynu woda z instalacji tryskaczowej", "okolicznosci": "Tryskacze w nocy.",
        "rodzaj_mienia": "zapasy", "szacowana_kwota": 720000,
    }
    return stan


def test_pola_rag_buduja_cztery_teksty():
    oczekiwany = {**OCZEKIWANY, "decyzja_llm": "POKRYTA", "uwagi_dla_ewaluacji": "Kwota > SU zapasow."}
    rag = pola_rag(oczekiwany, _stan_z_polami())
    assert "tryskaczowej" in rag["query"] and "720000" in rag["query"]
    assert "Zalanie." in rag["context"] and "p4u3" in rag["context"]
    assert rag["response"].startswith("Decyzja: POKRYTA")
    assert "§4 ust. 3" in rag["response"]
    assert "§4 ust. 1" in rag["ground_truth"] and "Kwota > SU" in rag["ground_truth"]
    assert rag["ocenia_llm"] is True


ZAKAZANE = (NIP_TESTOWY, "Hurtownia Papieru Mazur sp. z o.o.", "ul. Skladowa 8", "05-500", "Piaseczno", "PL/MSP/2026/0004")


def test_pola_rag_bez_danych_osobowych():
    """Ograniczenia globalne (RODO): NIP, nazwa ubezpieczonego, adres, nr polisy nie trafiaja do JSONL."""
    rag = pola_rag(OCZEKIWANY, _stan_z_polami())
    tekst = " ".join(str(v) for v in rag.values())
    for zakazane in ZAKAZANE:
        assert zakazane not in tekst


def test_pola_rag_maskuje_dane_w_tekstach_llm():
    """Model moze przepisac nazwe/adres do uzasadnienia, okolicznosci albo fragmentu - maskowanie we wszystkich 4 tekstach."""
    stan = _stan_z_polami()
    stan["pola"]["okolicznosci"] = "Hurtownia Papieru Mazur sp. z o.o. zglosila zalanie w Piaseczno."
    stan["ocena_pokrycia"]["cytaty"][0]["uzasadnienie"] = (
        "Hurtownia Papieru Mazur sp. z o.o. (NIP 9524044407) ma polise PL/MSP/2026/0004, ul. Skladowa 8.")
    stan["fragmenty_owu"][0]["tresc"] += " Piaseczno"
    rag = pola_rag({**OCZEKIWANY, "uwagi_dla_ewaluacji": "Ubezpieczony Hurtownia Papieru Mazur sp. z o.o."}, stan)
    for klucz in ("query", "context", "response", "ground_truth"):
        for zakazane in ZAKAZANE:
            assert zakazane not in rag[klucz], (klucz, zakazane)
    assert "[ZANONIMIZOWANO]" in rag["response"] and "[ZANONIMIZOWANO]" in rag["query"]


def test_pola_rag_pomija_cytaty_odrzucone_przez_kontrole():
    cytat_zly = {"paragraf": "6", "ustep": "1", "uzasadnienie": "spoza kontekstu"}
    stan = _stan_z_polami()
    stan["ocena_pokrycia"]["cytaty"].append(cytat_zly)
    stan["kontrola_cytatow"] = {"ok": False, "powod": "cytat_spoza_kontekstu", "odrzucone": [cytat_zly]}
    rag = pola_rag(OCZEKIWANY, stan)
    assert "§4 ust. 3" in rag["response"] and "§6 ust. 1" not in rag["response"]


def test_pola_rag_bez_oceny_llm():
    stan = _stan_z_polami()
    stan["ocena_pokrycia"] = None
    rag = pola_rag(OCZEKIWANY, stan)
    assert rag["ocenia_llm"] is False
    assert rag["response"]  # tekst zastepczy, nie pusty - evaluate odrzuca puste wejscie


def test_porownaj_szkode_niesie_pola_rag():
    wiersz = porownaj_szkode(OCZEKIWANY, _stan_z_polami())
    assert {"query", "context", "response", "ground_truth", "ocenia_llm"} <= wiersz.keys()


def test_artefakt_mlflow_bez_tekstow_rag(monkeypatch, tmp_path):
    """Przeglad p. 8: JSON idacy do MLflow (Azure ML) nie niesie tekstow RAG; lokalny JSON - tak (sedzia go czyta)."""
    from ewaluacja.szkody import KLUCZE_RAG
    przekazane = {}
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path)
    monkeypatch.setattr(uruchom, "zaloguj_przebieg", lambda **kw: przekazane.update(kw) or "run-x", raising=False)
    assert uruchom.main(["--atrapa", "--modul", "szkody", "--mlflow"]) == 0
    lokalny = next(p for p in tmp_path.glob("*_szkody_*.json") if "_mlflow" not in p.name)
    assert set(KLUCZE_RAG) <= json.loads(lokalny.read_text(encoding="utf-8"))["przypadki"][0].keys()
    artefakt = next(p for p in przekazane["artefakty"] if str(p).endswith(".json"))
    for w in json.loads(Path(artefakt).read_text(encoding="utf-8"))["przypadki"]:
        assert not set(KLUCZE_RAG) & w.keys()


def test_run_rag_szkod_ma_tag_klucz_przebiegu(monkeypatch, tmp_path):
    """Przeglad koncowy m2: run RAG i run sedziego wiaza sie tagiem klucz_przebiegu (= nazwa pliku wynikow bez .json)."""
    przekazane = {}
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path)
    monkeypatch.setattr(uruchom, "zaloguj_przebieg", lambda **kw: przekazane.update(kw) or "run-x", raising=False)
    assert uruchom.main(["--atrapa", "--modul", "szkody", "--mlflow"]) == 0
    lokalny = next(p for p in tmp_path.glob("*_szkody_*.json") if "_mlflow" not in p.name)
    assert przekazane["tagi_dodatkowe"] == {"modul": "szkody", "klucz_przebiegu": lokalny.stem}


@pytest.mark.parametrize("nip", ["1234563218", "123-456-32-18", "123-45-63-218"])
def test_pola_rag_maskuje_obcy_nip_w_tekscie_modelu(nip):
    """Przeglad koncowy m3: instance_results.jsonl leci do chmury - NIP, ktorego nie ma w polach zgloszenia
    (model go halucynuje albo bierze z dokumentu), tez jest maskowany wzorcem, nie tylko wartoscia."""
    stan = _stan_z_polami()
    stan["ocena_pokrycia"]["cytaty"][0]["uzasadnienie"] = f"Kontrahent o NIP {nip} nie jest ubezpieczonym."
    rag = pola_rag(OCZEKIWANY, stan)
    assert nip not in rag["response"]
    assert "[ZANONIMIZOWANO]" in rag["response"]
