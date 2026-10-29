"""Etap 24, zadanie 3: supervisor i graf wieloagentowy (`agent/supervisor.py`,
`agent/graf_wieloagentowy.py`, `agent/graf.py::wybierz_graf`). Offline: ModelAtrapa, InMemorySaver,
lokalny BM25. Zero sieci."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent.graf import SCIEZKA_WYTYCZNYCH_DOMYSLNA, budowniczy_grafu, wybierz_graf, zbuduj_graf
from agent.graf_wieloagentowy import zbuduj_graf_wieloagentowy
from agent.supervisor import (
    MAKS_KROKOW_SUPERVISORA,
    dozwolone_ruchy,
    router_deterministyczny,
    wezel_supervisor,
)
from ewaluacja.atrapa import ModelAtrapa
from obserwowalnosc import model_sledzony as modul_model_sledzony
from obserwowalnosc import wezly as modul_wezly
from obserwowalnosc.model_sledzony import ModelSledzony
from rag.wyszukiwarka import WyszukiwarkaLokalna

ROOT = Path(__file__).resolve().parent.parent
WNIOSKI_DIR = ROOT / "dane" / "wnioski"
SZKODY_DIR = ROOT / "dane" / "szkody"
ZDJECIA_DIR = ROOT / "dane" / "zdjecia_szkod"

WNIOSKI = [f"W{i:02d}" for i in range(1, 15)]
SZKODY = [f"Z{i:02d}" for i in range(1, 13)]
DECYZJA_CZLOWIEKA = {"decyzja": "AKCEPTACJA", "kto": "tester"}


# --------------------------------------------------------------------------
# Pomocnicze
# --------------------------------------------------------------------------

def _atrapa(id_przypadku: str) -> ModelAtrapa:
    model = ModelAtrapa(ROOT / "dane" / "oczekiwane")
    model.ustaw_przypadek(id_przypadku)
    return model


def _wejscie(id_przypadku: str, zdjecie: bool = False) -> dict:
    katalog = WNIOSKI_DIR if id_przypadku.startswith("W") else SZKODY_DIR
    (plik,) = katalog.glob(f"{id_przypadku}.*")
    wejscie = {"plik": str(plik), "wywolania_llm": 0, "log": []}
    if zdjecie:
        wejscie["zdjecia"] = [str(ZDJECIA_DIR / f"{id_przypadku}.jpg")]
    return wejscie


class _Licznik:
    """Proxy modelu: liczy wywolania operacji LLM (po nazwie), reszte przepuszcza."""

    def __init__(self, model):
        self._model = model
        self.wywolania: list[str] = []

    def __getattr__(self, nazwa):
        atrybut = getattr(self._model, nazwa)
        if nazwa.startswith("_") or nazwa == "ustaw_przypadek" or not callable(atrybut):
            return atrybut

        def owiniete(*args, **kwargs):
            self.wywolania.append(nazwa)
            return atrybut(*args, **kwargs)

        return owiniete

    def ile(self, nazwa: str) -> int:
        return self.wywolania.count(nazwa)

    def ile_agentow(self) -> int:
        return len([n for n in self.wywolania if n != "decyduj_supervisor"])


class _Sterowany(ModelAtrapa):
    """Atrapa, w ktorej krok 1 / krok 2 supervisora mozna nadpisac (`atrapa-zlosnik`) albo zepsuc."""

    def __init__(self, id_przypadku: str, krok1: dict | None = None, krok2: dict | None = None,
                 blad_krok1: int = 0, blad_krok2: int = 0):
        super().__init__(ROOT / "dane" / "oczekiwane")
        self.ustaw_przypadek(id_przypadku)
        self._nadpisanie = {1: krok1, 2: krok2}
        self._bledy = {1: blad_krok1, 2: blad_krok2}

    def decyduj_supervisor(self, czesci, podsumowanie):
        krok = 1 if czesci is not None else 2
        if self._bledy[krok] > 0:
            self._bledy[krok] -= 1
            raise TimeoutError("limit czasu supervisora")
        wynik, meta = super().decyduj_supervisor(czesci, podsumowanie)
        if self._nadpisanie[krok]:
            wynik = wynik.model_copy(update=self._nadpisanie[krok])
        return wynik, meta


class _AgentZepsuty(ModelAtrapa):
    """Atrapa z zepsutym `ekstrahuj_szkode` (blad agenta szkod)."""

    def __init__(self, id_przypadku: str):
        super().__init__(ROOT / "dane" / "oczekiwane")
        self.ustaw_przypadek(id_przypadku)

    def ekstrahuj_szkode(self, czesci):
        raise TimeoutError("limit czasu")


def _graf(fabryka, model):
    return fabryka(model, InMemorySaver(), wyszukiwarka=WyszukiwarkaLokalna())


def _uruchom(fabryka, model, id_przypadku: str, zdjecie: bool = False):
    """(graf, config, wynik pierwszego invoke)."""
    graf = _graf(fabryka, model)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return graf, config, graf.invoke(_wejscie(id_przypadku, zdjecie), config)


def _panel(wynik) -> dict:
    assert "__interrupt__" in wynik
    return wynik["__interrupt__"][0].value


def _stan(graf, config) -> dict:
    return dict(graf.get_state(config).values)


def _nazwy_log(stan: dict) -> list[str]:
    return [wpis["wezel"] for wpis in stan.get("log", [])]


def _bez_orkiestracji(panel: dict) -> dict:
    return {k: v for k, v in panel.items() if k != "orkiestracja"}


def _typ(id_przypadku: str) -> str:
    return _atrapa(id_przypadku).klasyfikuj(None)[0].typ_dokumentu


# --------------------------------------------------------------------------
# Atrapa: decyzja w panelu identyczna jak w wariancie `jeden` (W01-W14, Z01-Z12)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("id_przypadku", WNIOSKI + SZKODY)
def test_panel_wieloagentowy_taki_jak_jeden(id_przypadku):
    graf_j, config_j, wynik_j = _uruchom(zbuduj_graf, _atrapa(id_przypadku), id_przypadku)
    graf_w, config_w, wynik_w = _uruchom(zbuduj_graf_wieloagentowy, _atrapa(id_przypadku), id_przypadku)
    if _typ(id_przypadku) == "INNY":
        assert "__interrupt__" not in wynik_j and "__interrupt__" not in wynik_w
        assert _stan(graf_j, config_j)["decyzja_koncowa"] == _stan(graf_w, config_w)["decyzja_koncowa"] == "NIE_DOTYCZY"
        return
    panel_j, panel_w = _panel(wynik_j), _panel(wynik_w)
    assert "orkiestracja" not in panel_j  # wariant `jeden`: panel bez zmian
    assert _bez_orkiestracji(panel_w) == panel_j
    assert panel_w["orkiestracja"]["wariant"] == "wieloagentowy"
    assert panel_w["orkiestracja"]["korekty"] == 0
    # po wznowieniu ta sama decyzja koncowa
    koniec_j = graf_j.invoke(Command(resume=DECYZJA_CZLOWIEKA), config_j)
    koniec_w = graf_w.invoke(Command(resume=DECYZJA_CZLOWIEKA), config_w)
    assert "__interrupt__" not in koniec_j and "__interrupt__" not in koniec_w
    assert koniec_w["decyzja_koncowa"] == koniec_j["decyzja_koncowa"]


def test_panel_ze_zdjeciem_taki_jak_jeden():
    _, _, wynik_j = _uruchom(zbuduj_graf, _atrapa("Z01"), "Z01", zdjecie=True)
    _, _, wynik_w = _uruchom(zbuduj_graf_wieloagentowy, _atrapa("Z01"), "Z01", zdjecie=True)
    assert _panel(wynik_j)["zdjecie"]["status"] == "OK"
    assert _bez_orkiestracji(_panel(wynik_w)) == _panel(wynik_j)


def test_trasy_agentow_i_orkiestracja_w_panelu():
    _, _, wynik = _uruchom(zbuduj_graf_wieloagentowy, _atrapa("W01"), "W01")
    assert _panel(wynik)["orkiestracja"] == {
        "wariant": "wieloagentowy",
        "trasa_agentow": ["agent_underwritingu"],
        "korekty": 0,
        "uzasadnienia": ["atrapa: z dane/oczekiwane"],
    }
    _, _, wynik = _uruchom(zbuduj_graf_wieloagentowy, _atrapa("Z01"), "Z01")
    orkiestracja = _panel(wynik)["orkiestracja"]
    assert orkiestracja["trasa_agentow"] == ["agent_szkod", "agent_owu"]
    assert orkiestracja["uzasadnienia"] == ["atrapa: z dane/oczekiwane", "atrapa: lustro po_sprawdzeniu_polisy"]


def test_wywolania_llm_agentow_bez_klasyfikacji_supervisora():
    """Krok 1 supervisora zastepuje `klasyfikuj`, ale nie zuzywa limitu agentow (osobny licznik)."""
    graf_j, config_j, _ = _uruchom(zbuduj_graf, _atrapa("W01"), "W01")
    graf_w, config_w, _ = _uruchom(zbuduj_graf_wieloagentowy, _atrapa("W01"), "W01")
    assert _stan(graf_j, config_j)["wywolania_llm"] == 3  # klasyfikuj + ekstrahuj + ocen
    assert _stan(graf_w, config_w)["wywolania_llm"] == 2
    assert _stan(graf_w, config_w)["wywolania_supervisora"] == 1


# --------------------------------------------------------------------------
# INNY -> zakoncz_inny, bez agentow
# --------------------------------------------------------------------------

def test_inny_konczy_przez_zakoncz_inny_bez_agentow():
    model = _Licznik(_atrapa("W14"))
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "W14")
    stan = _stan(graf, config)
    assert "__interrupt__" not in wynik
    assert stan["decyzja_koncowa"] == "NIE_DOTYCZY"
    assert stan["trasa_agentow"] == [] and stan["korekty_supervisora"] == 0
    assert model.wywolania == ["decyduj_supervisor"]
    assert _nazwy_log(stan) == ["wczytaj", "supervisor"]
    assert stan.get("wywolania_llm", 0) == 0


# --------------------------------------------------------------------------
# Bramki deterministyczne: dozwolone_ruchy / router_deterministyczny
# --------------------------------------------------------------------------

def test_dozwolone_ruchy_krok_1_wedlug_typu():
    assert dozwolone_ruchy({"typ_dokumentu": "WNIOSEK", "trasa_agentow": []}) == {"agent_underwritingu"}
    assert dozwolone_ruchy({"typ_dokumentu": "SZKODA", "trasa_agentow": []}) == {"agent_szkod"}
    assert dozwolone_ruchy({"typ_dokumentu": "INNY", "trasa_agentow": []}) == {"zakoncz"}
    assert dozwolone_ruchy({"typ_dokumentu": None, "trasa_agentow": []}) == set()


def test_dozwolone_ruchy_owu_tylko_dla_szkody_po_agencie_szkod_i_raz():
    po_szkodzie = {"typ_dokumentu": "SZKODA", "trasa_agentow": ["agent_szkod"]}
    assert dozwolone_ruchy(po_szkodzie) == {"agent_owu", "zakoncz"}
    assert dozwolone_ruchy({**po_szkodzie, "trasa_agentow": ["agent_szkod", "agent_owu"]}) == {"zakoncz"}
    assert dozwolone_ruchy({"typ_dokumentu": "WNIOSEK", "trasa_agentow": ["agent_underwritingu"]}) == {"zakoncz"}


def test_router_deterministyczny_lustro_obecnego_grafu():
    assert router_deterministyczny({"typ_dokumentu": "WNIOSEK", "trasa_agentow": []}) == "agent_underwritingu"
    assert router_deterministyczny({"typ_dokumentu": "SZKODA", "trasa_agentow": []}) == "agent_szkod"
    assert router_deterministyczny({"typ_dokumentu": "INNY", "trasa_agentow": []}) == "zakoncz"
    po_szkodzie = {"typ_dokumentu": "SZKODA", "trasa_agentow": ["agent_szkod"]}
    s01 = {**po_szkodzie, "wynik_polisy": {"kody": ["S01"], "braki": []}}
    s02 = {**po_szkodzie, "wynik_polisy": {"kody": ["S02"], "braki": []}}
    s03 = {**po_szkodzie, "wynik_polisy": {"kody": ["S03"], "braki": []}}
    assert router_deterministyczny(s01) == router_deterministyczny(s02) == "zakoncz"
    assert router_deterministyczny(s03) == router_deterministyczny(po_szkodzie) == "agent_owu"
    assert router_deterministyczny({**po_szkodzie, "trasa_agentow": ["agent_szkod", "agent_owu"]}) == "zakoncz"


# --------------------------------------------------------------------------
# Bramki w grafie (atrapa-zlosnik)
# --------------------------------------------------------------------------

def test_zlosnik_agent_owu_dla_wniosku_korekta_do_underwritingu():
    model = _Sterowany("W01", krok1={"nastepny": "agent_owu"})
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "W01")
    stan = _stan(graf, config)
    assert stan["korekty_supervisora"] == 1
    assert stan["trasa_agentow"] == ["agent_underwritingu"]
    assert "supervisor_korekta" in _nazwy_log(stan)
    _, _, wynik_j = _uruchom(zbuduj_graf, _atrapa("W01"), "W01")
    assert _bez_orkiestracji(_panel(wynik)) == _panel(wynik_j)
    assert _panel(wynik)["orkiestracja"]["korekty"] == 1


def test_zlosnik_ten_sam_agent_drugi_raz_korekta():
    """Krok 2: supervisor chce znowu `agent_szkod` -> zabronione, korekta do routera obecnego grafu (agent_owu)."""
    model = _Sterowany("Z01", krok2={"nastepny": "agent_szkod"})
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "Z01")
    stan = _stan(graf, config)
    assert stan["korekty_supervisora"] == 1
    assert stan["trasa_agentow"] == ["agent_szkod", "agent_owu"]
    _, _, wynik_j = _uruchom(zbuduj_graf, _atrapa("Z01"), "Z01")
    assert _bez_orkiestracji(_panel(wynik)) == _panel(wynik_j)


def test_zlosnik_agent_underwritingu_dla_szkody_w_kroku_2_korekta():
    model = _Sterowany("Z01", krok2={"nastepny": "agent_underwritingu"})
    graf, config, _ = _uruchom(zbuduj_graf_wieloagentowy, model, "Z01")
    stan = _stan(graf, config)
    assert stan["korekty_supervisora"] == 1 and stan["trasa_agentow"] == ["agent_szkod", "agent_owu"]


def test_zlosnik_korekta_do_zakoncz_gdy_router_mowi_zakoncz():
    """Z09 (S01): router obecnego grafu = zakoncz; zabroniony ruch (agent_szkod) -> korekta do zakoncz."""
    model = _Sterowany("Z09", krok2={"nastepny": "agent_szkod"})
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "Z09")
    stan = _stan(graf, config)
    assert stan["korekty_supervisora"] == 1 and stan["trasa_agentow"] == ["agent_szkod"]
    assert _panel(wynik)["decyzja"] == "SKIEROWANIE" and _panel(wynik)["powody_decyzji"] == ["S01"]


def test_typ_wygrywa_nad_nastepnym():
    # typ WNIOSEK, nastepny agent_szkod -> agent_underwritingu
    graf, config, wynik = _uruchom(
        zbuduj_graf_wieloagentowy, _Sterowany("W01", krok1={"nastepny": "agent_szkod"}), "W01"
    )
    stan = _stan(graf, config)
    assert stan["trasa_agentow"] == ["agent_underwritingu"] and stan["korekty_supervisora"] == 1
    assert stan["typ_dokumentu"] == "WNIOSEK"
    # typ SZKODA, nastepny zakoncz -> agent_szkod
    graf, config, wynik = _uruchom(
        zbuduj_graf_wieloagentowy, _Sterowany("Z01", krok1={"nastepny": "zakoncz"}), "Z01"
    )
    stan = _stan(graf, config)
    assert stan["trasa_agentow"][0] == "agent_szkod" and stan["korekty_supervisora"] == 1
    # typ INNY, nastepny agent_underwritingu -> zakoncz_inny
    graf, config, wynik = _uruchom(
        zbuduj_graf_wieloagentowy, _Sterowany("W01", krok1={"typ_dokumentu": "INNY", "nastepny": "agent_underwritingu"}),
        "W01",
    )
    stan = _stan(graf, config)
    assert "__interrupt__" not in wynik and stan["decyzja_koncowa"] == "NIE_DOTYCZY"
    assert stan["trasa_agentow"] == [] and stan["korekty_supervisora"] == 1


def test_dozwolony_ale_zly_wybor_nie_jest_korygowany_zakoncz_dla_z01():
    """Dokumentuje zachowanie: `zakoncz` po zwyklej szkodzie jest dozwolone (inne niz obecny graf, ale mierzone) ->
    brak oceny pokrycia -> SKIEROWANIE `brak_oceny`, BEZ korekty."""
    model = _Sterowany("Z01", krok2={"nastepny": "zakoncz"})
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "Z01")
    stan = _stan(graf, config)
    panel = _panel(wynik)
    assert panel["decyzja"] == "SKIEROWANIE" and panel["powody_decyzji"] == ["brak_oceny"]
    assert stan["korekty_supervisora"] == 0 and "supervisor_korekta" not in _nazwy_log(stan)
    assert stan["trasa_agentow"] == ["agent_szkod"]
    assert "szukaj_owu" not in _nazwy_log(stan)


def test_dozwolony_ale_inny_wybor_agent_owu_przy_s01_nie_jest_korygowany():
    model = _Sterowany("Z09", krok2={"nastepny": "agent_owu"})
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "Z09")
    stan = _stan(graf, config)
    assert stan["korekty_supervisora"] == 0 and stan["trasa_agentow"] == ["agent_szkod", "agent_owu"]
    # decyzja koncowa nadal z ustal_decyzje_szkody: S01 -> SKIEROWANIE
    assert _panel(wynik)["decyzja"] == "SKIEROWANIE" and _panel(wynik)["powody_decyzji"] == ["S01"]


# --------------------------------------------------------------------------
# Blad LLM supervisora
# --------------------------------------------------------------------------

def test_blad_llm_supervisora_krok_2_dwa_razy_skierowanie():
    model = _Licznik(_Sterowany("Z01", blad_krok2=2))
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "Z01")
    stan = _stan(graf, config)
    panel = _panel(wynik)
    assert panel["decyzja"] == "SKIEROWANIE" and panel["powody_decyzji"] == ["blad_agenta"]
    assert panel["blad"] and "supervisor" in panel["blad"] and "TimeoutError" in panel["blad"]
    assert stan["trasa_agentow"] == ["agent_szkod"]
    assert model.ile("decyduj_supervisor") == 3  # krok 1 + 2 proby kroku 2
    # wywolania_llm: tylko wywolania agentow (osobny licznik supervisora)
    assert stan["wywolania_llm"] == model.ile_agentow()
    assert stan["wywolania_supervisora"] == 2
    assert [n for n in _nazwy_log(stan) if n.startswith("supervisor")] == [
        "supervisor", "supervisor_proba1_blad", "supervisor_proba2_blad",
    ]


def test_blad_llm_supervisora_krok_1_dwa_razy_zatwierdzenie_z_bledem_bez_agentow():
    model = _Licznik(_Sterowany("W01", blad_krok1=2))
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "W01")
    panel = _panel(wynik)
    assert panel["blad"] and panel["typ_dokumentu"] is None
    assert panel["orkiestracja"]["trasa_agentow"] == []
    assert model.ile_agentow() == 0
    assert not {"ekstrahuj", "ocen"} & set(_nazwy_log(_stan(graf, config)))


def test_jeden_blad_supervisora_ponowienie_i_dalej_normalnie():
    model = _Sterowany("W01", blad_krok1=1)
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "W01")
    stan = _stan(graf, config)
    assert not stan.get("blad") and stan["trasa_agentow"] == ["agent_underwritingu"]
    assert "supervisor_proba1_blad" in _nazwy_log(stan)
    assert stan["wywolania_supervisora"] == 1


def test_brak_typu_w_kroku_1_liczy_sie_jak_blad_proby():
    model = _Sterowany("W01", krok1={"typ_dokumentu": None})
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "W01")
    stan = _stan(graf, config)
    assert stan["blad"] and stan["trasa_agentow"] == []


def test_limit_krokow_supervisora():
    stan = {"typ_dokumentu": None, "trasa_agentow": [], "wywolania_supervisora": MAKS_KROKOW_SUPERVISORA, "log": [],
            "czesci": object()}
    model = _Licznik(_atrapa("W01"))
    komenda = wezel_supervisor(stan, model)
    assert isinstance(komenda, Command) and komenda.goto == "zatwierdzenie"
    assert "limit" in komenda.update["blad"] and model.wywolania == []


# --------------------------------------------------------------------------
# Przejscia deterministyczne: bez LLM
# --------------------------------------------------------------------------

def test_po_agencie_underwritingu_brak_wywolania_llm_supervisora():
    model = _Licznik(_atrapa("W01"))
    graf, config, _ = _uruchom(zbuduj_graf_wieloagentowy, model, "W01")
    assert model.ile("decyduj_supervisor") == 1  # tylko krok 1
    stan = _stan(graf, config)
    assert stan["wywolania_supervisora"] == 1
    assert _nazwy_log(stan)[-1] == "supervisor_deterministyczny"


def test_po_agencie_owu_brak_wywolania_llm_supervisora():
    model = _Licznik(_atrapa("Z01"))
    graf, config, _ = _uruchom(zbuduj_graf_wieloagentowy, model, "Z01")
    assert model.ile("decyduj_supervisor") == 2  # krok 1 i krok 2 (po agent_szkod), NIE po agent_owu
    stan = _stan(graf, config)
    assert stan["wywolania_supervisora"] == 2 and stan["trasa_agentow"] == ["agent_szkod", "agent_owu"]
    assert _nazwy_log(stan)[-1] == "supervisor_deterministyczny"


def test_podejrzane_instrukcje_jak_blad_bez_llm_z12():
    model = _Licznik(_atrapa("Z12"))
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "Z12")
    assert model.ile("decyduj_supervisor") == 1
    stan = _stan(graf, config)
    assert stan["podejrzane_instrukcje"] is True and stan["trasa_agentow"] == ["agent_szkod"]
    assert _nazwy_log(stan)[-1] == "supervisor_deterministyczny"
    assert _panel(wynik)["decyzja"] == "SKIEROWANIE" and _panel(wynik)["powody_decyzji"] == ["podejrzane_instrukcje"]


def test_blad_agenta_jak_blad_bez_llm():
    model = _Licznik(_AgentZepsuty("Z01"))
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, "Z01")
    assert model.ile("decyduj_supervisor") == 1
    assert _panel(wynik)["decyzja"] == "SKIEROWANIE" and _panel(wynik)["powody_decyzji"] == ["blad_agenta"]
    assert "szukaj_owu" not in _nazwy_log(_stan(graf, config))


# --------------------------------------------------------------------------
# interrupt + resume
# --------------------------------------------------------------------------

@pytest.mark.parametrize("id_przypadku", ["W01", "Z01"])
def test_wznowienie_konczy_graf_i_nie_woluje_agentow_ponownie(id_przypadku):
    model = _Licznik(_atrapa(id_przypadku))
    graf, config, wynik = _uruchom(zbuduj_graf_wieloagentowy, model, id_przypadku)
    assert "__interrupt__" in wynik and graf.get_state(config).next == ("zatwierdzenie",)
    przed = list(model.wywolania)
    assert przed  # cos sie wywolalo
    koniec = graf.invoke(Command(resume=DECYZJA_CZLOWIEKA), config)
    assert model.wywolania == przed  # zero nowych wywolan modelu (agenci i supervisor)
    assert "__interrupt__" not in koniec
    assert koniec["decyzja_koncowa"] == "AKCEPTACJA" and koniec["zatwierdzil"] == "tester"
    assert graf.get_state(config).next == ()


def test_jedyny_interrupt_w_rodzicu_i_wezly_rodzica():
    graf = _graf(zbuduj_graf_wieloagentowy, _atrapa("W01"))
    wezly = set(graf.get_graph().nodes) - {"__start__", "__end__"}
    assert wezly == {
        "wczytaj", "supervisor", "agent_underwritingu", "agent_szkod", "agent_owu", "zakoncz_inny", "zatwierdzenie",
    }
    wszystkie = set(graf.get_graph(xray=True).nodes)
    assert [n for n in wszystkie if n.split(":")[-1] == "zatwierdzenie"] == ["zatwierdzenie"]


# --------------------------------------------------------------------------
# Telemetria
# --------------------------------------------------------------------------

@pytest.fixture
def spany(monkeypatch):
    eksporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(eksporter))
    monkeypatch.setattr(modul_wezly, "tracer", lambda: provider.get_tracer("test-wieloagentowy"))
    monkeypatch.setattr(modul_model_sledzony, "tracer", lambda: provider.get_tracer("test-wieloagentowy"))
    return eksporter


def _spany_supervisora(eksporter) -> list[dict]:
    spany_ = sorted(
        (s for s in eksporter.get_finished_spans() if s.name == "wezel.supervisor"), key=lambda s: s.start_time
    )
    return [dict(s.attributes) for s in spany_]


def test_span_supervisora_ma_atrybuty_z_decyzji_8(spany):
    _uruchom(zbuduj_graf_wieloagentowy, _atrapa("Z01"), "Z01")
    assert _spany_supervisora(spany) == [
        {"uw.supervisor.krok": 1, "uw.supervisor.wybor": "agent_szkod", "uw.supervisor.korekta": False,
         "uw.supervisor.llm": True},
        {"uw.supervisor.krok": 2, "uw.supervisor.wybor": "agent_owu", "uw.supervisor.korekta": False,
         "uw.supervisor.llm": True},
        {"uw.supervisor.krok": 3, "uw.supervisor.wybor": "zatwierdzenie", "uw.supervisor.korekta": False,
         "uw.supervisor.llm": False},
    ]


def test_span_supervisora_korekta_i_inny(spany):
    _uruchom(zbuduj_graf_wieloagentowy, _Sterowany("W01", krok1={"nastepny": "agent_owu"}), "W01")
    pierwszy = _spany_supervisora(spany)[0]
    assert pierwszy["uw.supervisor.korekta"] is True and pierwszy["uw.supervisor.wybor"] == "agent_underwritingu"
    spany.clear()
    _uruchom(zbuduj_graf_wieloagentowy, _atrapa("W14"), "W14")
    assert _spany_supervisora(spany) == [
        {"uw.supervisor.krok": 1, "uw.supervisor.wybor": "zakoncz_inny", "uw.supervisor.korekta": False,
         "uw.supervisor.llm": True}
    ]


def test_spany_wezlow_w_podgrafach_maja_uw_agent_w_grafie_wieloagentowym(spany):
    _uruchom(zbuduj_graf_wieloagentowy, _atrapa("Z01"), "Z01")
    po_nazwie = {s.name: s for s in spany.get_finished_spans()}
    for wezel in ("ekstrahuj_szkode", "sprawdz_polise", "ocen_ryzyko_szkody"):
        assert po_nazwie[f"wezel.{wezel}"].attributes["uw.agent"] == "agent_szkod"
    for wezel in ("szukaj_owu", "ocen_pokrycie", "kontrola_cytatow"):
        assert po_nazwie[f"wezel.{wezel}"].attributes["uw.agent"] == "agent_owu"
    assert "uw.agent" not in po_nazwie["wezel.wczytaj"].attributes
    assert "uw.agent" not in po_nazwie["wezel.zatwierdzenie"].attributes
    assert not [n for n in po_nazwie if n.startswith("agent.")]  # wariant (c)


def test_atrybuty_supervisora_bez_uzasadnienia_i_danych_osobowych(spany):
    class _Gadatliwy(ModelAtrapa):
        def decyduj_supervisor(self, czesci, podsumowanie):
            wynik, meta = super().decyduj_supervisor(czesci, podsumowanie)
            return wynik.model_copy(update={"uzasadnienie": "NIP 5260001246 TAJNA_FIRMA_XYZ"}), meta

    model = _Gadatliwy(ROOT / "dane" / "oczekiwane")
    model.ustaw_przypadek("Z01")
    _uruchom(zbuduj_graf_wieloagentowy, ModelSledzony.z_modelu(model), "Z01")
    wartosci = [str(v) for s in spany.get_finished_spans() for v in (s.attributes or {}).values()]
    assert wartosci
    for wrazliwe in ("TAJNA_FIRMA_XYZ", "5260001246"):
        assert not any(wrazliwe in w for w in wartosci), wrazliwe
    assert "llm.decyduj_supervisor" in {s.name for s in spany.get_finished_spans()}


# --------------------------------------------------------------------------
# Przelacznik wariantu
# --------------------------------------------------------------------------

def test_budowniczy_grafu_jeden_to_dotychczasowy_zbuduj_graf():
    assert budowniczy_grafu("jeden") is zbuduj_graf
    assert budowniczy_grafu("wieloagentowy") is zbuduj_graf_wieloagentowy


def test_wybierz_graf_jeden_ma_te_same_wezly_co_zbuduj_graf():
    model = _atrapa("W01")
    wybrany = wybierz_graf("jeden", model=model, checkpointer=InMemorySaver())
    bezposredni = zbuduj_graf(model, InMemorySaver())
    assert set(wybrany.get_graph().nodes) == set(bezposredni.get_graph().nodes)
    assert "supervisor" not in wybrany.get_graph().nodes


def test_wybierz_graf_wieloagentowy_buduje_graf_z_supervisorem():
    graf = wybierz_graf(
        "wieloagentowy", model=_atrapa("W01"), checkpointer=InMemorySaver(),
        sciezka_wytycznych=SCIEZKA_WYTYCZNYCH_DOMYSLNA,
    )
    assert "supervisor" in graf.get_graph().nodes


@pytest.mark.parametrize("zly", ["", "Jeden", "multi", "wieloagentowy ", None])
def test_nieznany_wariant_value_error(zly):
    with pytest.raises(ValueError):
        budowniczy_grafu(zly)
    with pytest.raises(ValueError):
        wybierz_graf(zly, model=_atrapa("W01"), checkpointer=InMemorySaver())
