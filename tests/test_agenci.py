"""Etap 24, zadanie 2: agenci jako podgrafy LangGraph (`agent/agenci.py`) zlozone z istniejacych
wezlow. Offline: ModelAtrapa + lokalny BM25, zero sieci. Podgraf uruchomiony samodzielnie ma dac
te same pola stanu co odpowiadajacy odcinek obecnego grafu (`zbuduj_graf`)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent.agenci import zbuduj_agenta_owu, zbuduj_agenta_szkod, zbuduj_agenta_underwritingu
from agent.graf import SCIEZKA_WYTYCZNYCH_DOMYSLNA, zbuduj_graf
from agent.instrukcje import wytyczne_na_instrukcje
from agent.polisy import SCIEZKA_POLIS, wczytaj_polisy
from agent.wezly import StanGrafu, wezel_klasyfikuj, wezel_wczytaj
from agent.wezly_szkody import po_sprawdzeniu_polisy
from ewaluacja.atrapa import ModelAtrapa
from obserwowalnosc import wezly as modul_wezly
from obserwowalnosc.wezly import sledz_wezel
from rag.wyszukiwarka import WyszukiwarkaLokalna
from reguly import wczytaj_wytyczne

ROOT = Path(__file__).resolve().parent.parent
WNIOSKI_DIR = ROOT / "dane" / "wnioski"
SZKODY_DIR = ROOT / "dane" / "szkody"
ZDJECIA_DIR = ROOT / "dane" / "zdjecia_szkod"

WNIOSKI = [f"W{i:02d}" for i in range(1, 15)]
SZKODY = [f"Z{i:02d}" for i in range(1, 13)]


def _atrapa(id_przypadku: str) -> ModelAtrapa:
    model = ModelAtrapa(ROOT / "dane" / "oczekiwane")
    model.ustaw_przypadek(id_przypadku)
    return model


def _plik(id_przypadku: str) -> Path:
    katalog = WNIOSKI_DIR if id_przypadku.startswith("W") else SZKODY_DIR
    (plik,) = katalog.glob(f"{id_przypadku}.*")  # rozszerzenia: pdf, jpg (W09), eml (W10-W12)
    return plik


def _wejscie(id_przypadku: str, zdjecie: bool = False) -> dict:
    wejscie = {"plik": str(_plik(id_przypadku)), "wywolania_llm": 0, "log": []}
    if zdjecie:
        wejscie["zdjecia"] = [str(ZDJECIA_DIR / f"{id_przypadku}.jpg")]
    return wejscie


def _po_klasyfikacji(model, wejscie: dict) -> StanGrafu:
    """Stan, z jakim agent dostaje sterowanie od supervisora: po `wczytaj` i klasyfikacji."""
    stan: StanGrafu = dict(wejscie)
    stan.update(wezel_wczytaj(stan))
    stan.update(wezel_klasyfikuj(stan, model))
    return stan


def _stan_obecnego_grafu(id_przypadku: str, zdjecie: bool = False) -> dict:
    """Wartosci stanu obecnego grafu w chwili `interrupt` (wszystko przed `zatwierdzenie`)."""
    model = _atrapa(id_przypadku)
    graf = zbuduj_graf(model, InMemorySaver(), wyszukiwarka=WyszukiwarkaLokalna())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    wynik = graf.invoke(_wejscie(id_przypadku, zdjecie), config)
    assert "__interrupt__" in wynik
    return dict(graf.get_state(config).values)


def _agent_underwritingu(model):
    sciezka = SCIEZKA_WYTYCZNYCH_DOMYSLNA
    return zbuduj_agenta_underwritingu(model, wczytaj_wytyczne(sciezka), wytyczne_na_instrukcje(sciezka))


def _agent_szkod(model, model_ryzyka=None):
    return zbuduj_agenta_szkod(model, wczytaj_polisy(SCIEZKA_POLIS), model_ryzyka)


def _agent_owu(model, wyszukiwarka=None):
    return zbuduj_agenta_owu(model, wyszukiwarka or WyszukiwarkaLokalna())


def _nazwy_log(stan: dict) -> list[str]:
    return [wpis["wezel"] for wpis in stan.get("log", [])]


def _bez_logu(stan: dict) -> dict:
    return {k: v for k, v in stan.items() if k != "log"}


def _uruchom_agentow_szkody(model, wejscie: dict) -> dict:
    """agent_szkod, a potem agent_owu, jesli nie ma bledu/podejrzanych instrukcji/S01-S02 - jak supervisor."""
    stan = _po_klasyfikacji(model, wejscie)
    stan = dict(_agent_szkod(model).invoke(stan))
    if not stan.get("blad") and not stan.get("podejrzane_instrukcje") and po_sprawdzeniu_polisy(stan) == "szukaj_owu":
        stan = dict(_agent_owu(model).invoke(stan))
    return stan


# --------------------------------------------------------------------------
# Rownowaznosc z obecnym grafem
# --------------------------------------------------------------------------

@pytest.mark.parametrize("id_przypadku", WNIOSKI)
def test_agent_underwritingu_jak_odcinek_obecnego_grafu(id_przypadku):
    pytanie = _atrapa(id_przypadku)
    typ = pytanie.klasyfikuj(None)[0].typ_dokumentu
    if typ != "WNIOSEK":
        pytest.skip(f"{id_przypadku} to {typ} - agent underwritingu dostaje tylko wnioski")
    oczekiwany = _stan_obecnego_grafu(id_przypadku)
    model = _atrapa(id_przypadku)
    wynik = dict(_agent_underwritingu(model).invoke(_po_klasyfikacji(model, _wejscie(id_przypadku))))
    assert "__interrupt__" not in wynik
    assert _bez_logu(wynik) == _bez_logu(oczekiwany)
    assert _nazwy_log(wynik) == _nazwy_log(oczekiwany)


def test_agent_underwritingu_w01_ma_rekomendacje_i_kontrole():
    model = _atrapa("W01")
    wynik = _agent_underwritingu(model).invoke(_po_klasyfikacji(model, _wejscie("W01")))
    assert wynik["pola"] and wynik["rekomendacja"]["decyzja"]
    assert wynik["decyzja_silnika"] and wynik["zgodnosc"] in (True, False)
    assert _nazwy_log(wynik) == ["wczytaj", "klasyfikuj", "ekstrahuj", "waliduj", "ocen", "kontrola"]


@pytest.mark.parametrize("id_przypadku", SZKODY)
def test_agenci_szkod_i_owu_jak_odcinek_obecnego_grafu(id_przypadku):
    oczekiwany = _stan_obecnego_grafu(id_przypadku)
    model = _atrapa(id_przypadku)
    wynik = _uruchom_agentow_szkody(model, _wejscie(id_przypadku))
    assert _bez_logu(wynik) == _bez_logu(oczekiwany)
    assert _nazwy_log(wynik) == _nazwy_log(oczekiwany)


def test_agenci_z01_pola_wynik_polisy_ocena_i_kontrola():
    """Wskazane w SPEC: Z01 - `pola`, `wynik_polisy`, `ocena_pokrycia`, `kontrola_cytatow`."""
    oczekiwany = _stan_obecnego_grafu("Z01")
    model = _atrapa("Z01")
    wynik = _uruchom_agentow_szkody(model, _wejscie("Z01"))
    for klucz in ("pola", "wynik_polisy", "ocena_pokrycia", "kontrola_cytatow", "fragmenty_owu", "ryzyko_szkody"):
        assert wynik[klucz] and wynik[klucz] == oczekiwany[klucz], klucz
    assert _nazwy_log(wynik) == [
        "wczytaj", "klasyfikuj", "ekstrahuj_szkode", "analizuj_zdjecie", "sprawdz_polise",
        "ocen_ryzyko_szkody", "szukaj_owu", "ocen_pokrycie", "kontrola_cytatow",
    ]


def test_agenci_z05_odmowa_z_ocena_pokrycia():
    oczekiwany = _stan_obecnego_grafu("Z05")
    model = _atrapa("Z05")
    wynik = _uruchom_agentow_szkody(model, _wejscie("Z05"))
    assert wynik["ocena_pokrycia"]["decyzja"] == "ODMOWA"
    assert _bez_logu(wynik) == _bez_logu(oczekiwany)


def test_agenci_z07_dodatkowe_wyszukiwanie_i_druga_ocena():
    oczekiwany = _stan_obecnego_grafu("Z07")
    model = _atrapa("Z07")
    wynik = _uruchom_agentow_szkody(model, _wejscie("Z07"))
    assert wynik["dodatkowe_zapytanie"]
    assert "szukaj_owu_dodatkowe" in _nazwy_log(wynik) and "ocen_pokrycie_2" in _nazwy_log(wynik)
    assert _bez_logu(wynik) == _bez_logu(oczekiwany)


def test_agent_szkod_zdjecie_jak_w_obecnym_grafie():
    oczekiwany = _stan_obecnego_grafu("Z01", zdjecie=True)
    assert oczekiwany["sygnal_zdjecia"]["status"] == "OK"
    model = _atrapa("Z01")
    wynik = _uruchom_agentow_szkody(model, _wejscie("Z01", zdjecie=True))
    assert wynik["sygnal_zdjecia"] == oczekiwany["sygnal_zdjecia"]
    assert _bez_logu(wynik) == _bez_logu(oczekiwany)


def test_agent_szkod_s01_konczy_sie_przed_owu_bez_bledu():
    """Z09 (S01): agent_szkod konczy sie na `ocen_ryzyko_szkody`; decyzje o OWU podejmuje supervisor, nie podgraf."""
    model = _atrapa("Z09")
    stan = _po_klasyfikacji(model, _wejscie("Z09"))
    wynik = _agent_szkod(model).invoke(stan)
    assert "S01" in wynik["wynik_polisy"]["kody"]
    assert _nazwy_log(wynik)[-1] == "ocen_ryzyko_szkody"
    assert not wynik.get("blad") and not wynik.get("fragmenty_owu")


def test_agent_szkod_podejrzane_instrukcje_konczy_po_ekstrakcji():
    """Z12 ma `podejrzane: true`: jak `po_ekstrakcji_szkody` w obecnym grafie - bez zdjecia, polisy i ryzyka."""
    model = _atrapa("Z12")
    wynik = _agent_szkod(model).invoke(_po_klasyfikacji(model, _wejscie("Z12")))
    assert wynik["podejrzane_instrukcje"] is True
    assert _nazwy_log(wynik)[-1] == "ekstrahuj_szkode"
    assert "wynik_polisy" not in wynik and "sygnal_zdjecia" not in wynik


# --------------------------------------------------------------------------
# Blad LLM w podgrafie: `blad` w stanie, koniec podgrafu, bez wyjatku
# --------------------------------------------------------------------------

class _Zepsuta(ModelAtrapa):
    """ModelAtrapa, w ktorej wskazane operacje rzucaja wyjatek."""

    def __init__(self, id_przypadku: str, zepsute: set[str]):
        super().__init__(ROOT / "dane" / "oczekiwane")
        self.ustaw_przypadek(id_przypadku)
        self._zepsute = zepsute
        self.wywolania: list[str] = []

    def _maybe(self, nazwa: str):
        self.wywolania.append(nazwa)
        if nazwa in self._zepsute:
            raise TimeoutError("limit czasu")

    def ekstrahuj(self, czesci):
        self._maybe("ekstrahuj")
        return super().ekstrahuj(czesci)

    def ocen(self, instrukcje, pola_json, problemy_walidacji):
        self._maybe("ocen")
        return super().ocen(instrukcje, pola_json, problemy_walidacji)

    def ekstrahuj_szkode(self, czesci):
        self._maybe("ekstrahuj_szkode")
        return super().ekstrahuj_szkode(czesci)

    def ocen_pokrycie(self, pola, wynik_polisy, fragmenty, dodatkowe=None):
        self._maybe("ocen_pokrycie")
        return super().ocen_pokrycie(pola, wynik_polisy, fragmenty, dodatkowe)


def test_blad_ekstrakcji_wniosku_konczy_podgraf():
    model = _Zepsuta("W01", {"ekstrahuj"})
    wynik = _agent_underwritingu(model).invoke(_po_klasyfikacji(model, _wejscie("W01")))
    assert "ekstrahuj" in wynik["blad"] and "TimeoutError" in wynik["blad"]
    assert model.wywolania == ["ekstrahuj", "ekstrahuj"]  # 2 proby, dalej nie idzie
    assert not set(_nazwy_log(wynik)) & {"waliduj", "ocen", "kontrola"}
    assert wynik["wywolania_llm"] == 3  # 1 klasyfikacja + 2 proby ekstrakcji


def test_blad_oceny_wniosku_konczy_podgraf_przed_kontrola():
    model = _Zepsuta("W01", {"ocen"})
    wynik = _agent_underwritingu(model).invoke(_po_klasyfikacji(model, _wejscie("W01")))
    assert "ocen" in wynik["blad"]
    assert "waliduj" in _nazwy_log(wynik) and "kontrola" not in _nazwy_log(wynik)
    assert "rekomendacja" not in wynik and "decyzja_silnika" not in wynik


def test_blad_ekstrakcji_szkody_konczy_podgraf_przed_polisa():
    model = _Zepsuta("Z01", {"ekstrahuj_szkode"})
    wynik = _agent_szkod(model).invoke(_po_klasyfikacji(model, _wejscie("Z01")))
    assert "ekstrahuj_szkode" in wynik["blad"]
    assert not set(_nazwy_log(wynik)) & {"analizuj_zdjecie", "sprawdz_polise", "ocen_ryzyko_szkody"}


def test_blad_szukania_owu_konczy_podgraf():
    class WyszukiwarkaZepsuta:
        nazwa = "zepsuta"

        def szukaj(self, zapytanie, k=5):
            raise ConnectionError("brak polaczenia")

    model = _atrapa("Z01")
    stan = dict(_agent_szkod(model).invoke(_po_klasyfikacji(model, _wejscie("Z01"))))
    wynik = _agent_owu(model, WyszukiwarkaZepsuta()).invoke(stan)
    assert wynik["blad"] and "ocen_pokrycie" not in _nazwy_log(wynik)


def test_blad_oceny_pokrycia_konczy_podgraf_przed_kontrola_cytatow():
    model = _Zepsuta("Z01", {"ocen_pokrycie"})
    stan = dict(_agent_szkod(model).invoke(_po_klasyfikacji(model, _wejscie("Z01"))))
    wynik = _agent_owu(model).invoke(stan)
    assert "ocen_pokrycie" in wynik["blad"]
    assert "kontrola_cytatow" not in _nazwy_log(wynik) and "ocena_pokrycia" not in wynik


# --------------------------------------------------------------------------
# Struktura: tylko istniejace wezly, zero `zatwierdzenie` i `interrupt`, bez checkpointera
# --------------------------------------------------------------------------

def _wezly(agent) -> set[str]:
    return set(agent.get_graph().nodes) - {"__start__", "__end__"}


def test_wezly_podgrafow():
    model = _atrapa("W01")
    assert _wezly(_agent_underwritingu(model)) == {"ekstrahuj", "waliduj", "ocen", "kontrola"}
    assert _wezly(_agent_szkod(model)) == {
        "ekstrahuj_szkode", "analizuj_zdjecie", "sprawdz_polise", "ocen_ryzyko_szkody",
    }
    assert _wezly(_agent_owu(model)) == {"szukaj_owu", "ocen_pokrycie", "kontrola_cytatow"}


def test_podgrafy_bez_zatwierdzenia_i_bez_checkpointera():
    model = _atrapa("W01")
    for agent in (_agent_underwritingu(model), _agent_szkod(model), _agent_owu(model)):
        assert "zatwierdzenie" not in _wezly(agent)
        assert agent.checkpointer is None  # dziedziczy checkpointer rodzica po dodaniu jako wezel


def test_podgrafy_nie_przerywaja_interrupt_na_calej_sciezce():
    """Zaden z 26 przypadkow nie konczy sie GraphInterrupt (invoke bez checkpointera by go nie wznowil)."""
    for id_przypadku in WNIOSKI + SZKODY:
        model = _atrapa(id_przypadku)
        stan = _po_klasyfikacji(model, _wejscie(id_przypadku))
        if stan["typ_dokumentu"] == "WNIOSEK":
            wynik = _agent_underwritingu(model).invoke(stan)
        elif stan["typ_dokumentu"] == "SZKODA":
            wynik = _agent_szkod(model).invoke(stan)
        else:
            continue
        assert "__interrupt__" not in wynik, id_przypadku


def test_podgraf_jako_wezel_rodzica_dziedziczy_checkpointer():
    model = _atrapa("W01")
    rodzic = StateGraph(StanGrafu)
    rodzic.add_node("agent_underwritingu", _agent_underwritingu(model))
    rodzic.add_edge(START, "agent_underwritingu")
    rodzic.add_edge("agent_underwritingu", END)
    graf = rodzic.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graf.invoke(_po_klasyfikacji(model, _wejscie("W01")), config)
    zapisany = graf.get_state(config).values
    assert zapisany["rekomendacja"] and zapisany["decyzja_silnika"]


# --------------------------------------------------------------------------
# Telemetria: wariant (c) z 28.10 - atrybut `uw.agent` na spanach `wezel.*`, bez spanu `agent.<nazwa>`
# --------------------------------------------------------------------------

@pytest.fixture
def spany(monkeypatch):
    eksporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(eksporter))
    monkeypatch.setattr(modul_wezly, "tracer", lambda: provider.get_tracer("test-agenci"))
    return eksporter


def test_spany_wezlow_maja_atrybut_uw_agent(spany):
    model = _atrapa("Z01")
    stan = _po_klasyfikacji(model, _wejscie("Z01"))
    stan = dict(_agent_szkod(model).invoke(stan))
    _agent_owu(model).invoke(stan)
    po_nazwie = {s.name: s for s in spany.get_finished_spans()}
    for wezel in ("ekstrahuj_szkode", "analizuj_zdjecie", "sprawdz_polise", "ocen_ryzyko_szkody"):
        assert po_nazwie[f"wezel.{wezel}"].attributes["uw.agent"] == "agent_szkod", wezel
    for wezel in ("szukaj_owu", "ocen_pokrycie", "kontrola_cytatow"):
        assert po_nazwie[f"wezel.{wezel}"].attributes["uw.agent"] == "agent_owu", wezel
    assert not [n for n in po_nazwie if n.startswith("agent.")]  # wariant (c): brak spanu agent.<nazwa>


def test_spany_agenta_underwritingu_maja_uw_agent(spany):
    model = _atrapa("W01")
    _agent_underwritingu(model).invoke(_po_klasyfikacji(model, _wejscie("W01")))
    po_nazwie = {s.name: s for s in spany.get_finished_spans()}
    for wezel in ("ekstrahuj", "waliduj", "ocen", "kontrola"):
        assert po_nazwie[f"wezel.{wezel}"].attributes["uw.agent"] == "agent_underwritingu", wezel


def test_sledz_wezel_bez_agenta_nie_dodaje_atrybutu(spany):
    """Obecny graf: `sledz_wezel(nazwa, fn)` bez zmian - span bez `uw.agent`."""
    sledz_wezel("x", lambda stan: {})({})
    (span,) = spany.get_finished_spans()
    assert span.name == "wezel.x" and "uw.agent" not in span.attributes
