"""Etap 24, zadanie 2: agenci jako podgrafy LangGraph zlozone z ISTNIEJACYCH wezlow i routerow.

Zasady wspolne dla trzech podgrafow:
- wspolny `StanGrafu` (podgraf zwraca pelny stan, bez mapowania kanalow);
- kompilacja BEZ checkpointera - po dodaniu jako wezel rodzica podgraf dziedziczy checkpointer
  rodzica (spike z zadania 0); samodzielnie uruchomiony (`invoke`) nie zapisuje nic;
- zadnego `zatwierdzenie` ani `interrupt` - czlowiek zatwierdza tylko w rodzicu;
- routery obecnego grafu zwracaja "zatwierdzenie" przy bledzie; w podgrafie to oznacza `END`
  (blad zostaje w stanie, a dalsza decyzje podejmuje supervisor) - logiki routerow nie kopiuje sie;
- wezly owiniete `sledz_wezel(nazwa, fn, agent=...)`: span `wezel.<nazwa>` z atrybutem `uw.agent`
  (wariant (c) z 28.10, bez osobnego spanu `agent.<nazwa>`).

Decyzje "czy szukac OWU / zakonczyc po S01-S02" nalezy do supervisora, nie do podgrafu:
`agent_szkod` konczy sie na `ocen_ryzyko_szkody`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from agent.model import ModelAgenta
from agent.wezly import (
    StanGrafu,
    po_ekstrakcji,
    po_ocenie,
    wezel_ekstrahuj,
    wezel_kontrola,
    wezel_ocen,
    wezel_waliduj,
)
from agent.wezly_szkody import (
    po_ekstrakcji_szkody,
    po_ocenie_pokrycia,
    po_szukaniu_owu,
    wezel_analizuj_zdjecie,
    wezel_ekstrahuj_szkode,
    wezel_kontrola_cytatow,
    wezel_ocen_pokrycie,
    wezel_ocen_ryzyko_szkody,
    wezel_sprawdz_polise,
    wezel_szukaj_owu,
)
from obserwowalnosc.wezly import sledz_wezel
from rag.wyszukiwarka import Wyszukiwarka

if TYPE_CHECKING:
    from ryzyko.serwowanie import ModelRyzyka

AGENT_UNDERWRITINGU = "agent_underwritingu"
AGENT_SZKOD = "agent_szkod"
AGENT_OWU = "agent_owu"


def _koniec_przy_bledzie(router, nastepny: str):
    """Opakowanie istniejacego routera: jego "zatwierdzenie" (blad) -> END; reszta bez zmian."""

    def po(stan: StanGrafu) -> str:
        wybor = router(stan)
        return END if wybor == "zatwierdzenie" else wybor

    po.__name__ = f"koniec_przy_bledzie_{router.__name__}"
    return po, {END: END, nastepny: nastepny}


def zbuduj_agenta_underwritingu(model: ModelAgenta, wytyczne: dict, instrukcje: str):
    """ekstrahuj -> waliduj -> ocen -> kontrola; blad w ekstrakcji/ocenie konczy podgraf (END)."""

    def w(nazwa, fn):
        return sledz_wezel(nazwa, fn, agent=AGENT_UNDERWRITINGU)

    builder = StateGraph(StanGrafu)
    builder.add_node("ekstrahuj", w("ekstrahuj", lambda stan: wezel_ekstrahuj(stan, model)))
    builder.add_node("waliduj", w("waliduj", wezel_waliduj))
    builder.add_node("ocen", w("ocen", lambda stan: wezel_ocen(stan, model, instrukcje)))
    builder.add_node("kontrola", w("kontrola", lambda stan: wezel_kontrola(stan, wytyczne)))

    po_ekstr, mapa_ekstr = _koniec_przy_bledzie(po_ekstrakcji, "waliduj")
    po_oc, mapa_oc = _koniec_przy_bledzie(po_ocenie, "kontrola")
    builder.add_edge(START, "ekstrahuj")
    builder.add_conditional_edges("ekstrahuj", po_ekstr, mapa_ekstr)
    builder.add_edge("waliduj", "ocen")
    builder.add_conditional_edges("ocen", po_oc, mapa_oc)
    builder.add_edge("kontrola", END)
    return builder.compile()


def zbuduj_agenta_szkod(
    model: ModelAgenta,
    polisy: dict[str, dict],
    model_ryzyka: "ModelRyzyka | None" = None,
):
    """ekstrahuj_szkode -> analizuj_zdjecie -> sprawdz_polise -> ocen_ryzyko_szkody.
    Blad albo podejrzane instrukcje po ekstrakcji konczy podgraf (jak `po_ekstrakcji_szkody`).
    Decyzja S01/S02 -> zakoncz vs szukaj OWU nie nalezy do podgrafu (robi ja supervisor)."""

    def w(nazwa, fn):
        return sledz_wezel(nazwa, fn, agent=AGENT_SZKOD)

    builder = StateGraph(StanGrafu)
    builder.add_node("ekstrahuj_szkode", w("ekstrahuj_szkode", lambda stan: wezel_ekstrahuj_szkode(stan, model)))
    builder.add_node("analizuj_zdjecie", w("analizuj_zdjecie", lambda stan: wezel_analizuj_zdjecie(stan, model)))
    builder.add_node("sprawdz_polise", w("sprawdz_polise", lambda stan: wezel_sprawdz_polise(stan, polisy)))
    builder.add_node(
        "ocen_ryzyko_szkody",
        w("ocen_ryzyko_szkody", lambda stan: wezel_ocen_ryzyko_szkody(stan, model_ryzyka)),
    )

    po_ekstr, mapa_ekstr = _koniec_przy_bledzie(po_ekstrakcji_szkody, "analizuj_zdjecie")
    builder.add_edge(START, "ekstrahuj_szkode")
    builder.add_conditional_edges("ekstrahuj_szkode", po_ekstr, mapa_ekstr)
    builder.add_edge("analizuj_zdjecie", "sprawdz_polise")
    builder.add_edge("sprawdz_polise", "ocen_ryzyko_szkody")
    builder.add_edge("ocen_ryzyko_szkody", END)
    return builder.compile()


def zbuduj_agenta_owu(model: ModelAgenta, wyszukiwarka: Wyszukiwarka):
    """szukaj_owu -> ocen_pokrycie -> kontrola_cytatow; blad (szukanie/ocena) konczy podgraf (END).
    Dodatkowe wyszukiwanie przy `zapytanie_dodatkowe` dzieje sie wewnatrz `ocen_pokrycie`."""

    def w(nazwa, fn):
        return sledz_wezel(nazwa, fn, agent=AGENT_OWU)

    builder = StateGraph(StanGrafu)
    builder.add_node("szukaj_owu", w("szukaj_owu", lambda stan: wezel_szukaj_owu(stan, wyszukiwarka)))
    builder.add_node(
        "ocen_pokrycie", w("ocen_pokrycie", lambda stan: wezel_ocen_pokrycie(stan, model, wyszukiwarka))
    )
    builder.add_node("kontrola_cytatow", w("kontrola_cytatow", wezel_kontrola_cytatow))

    po_szuk, mapa_szuk = _koniec_przy_bledzie(po_szukaniu_owu, "ocen_pokrycie")
    po_pokr, mapa_pokr = _koniec_przy_bledzie(po_ocenie_pokrycia, "kontrola_cytatow")
    builder.add_edge(START, "szukaj_owu")
    builder.add_conditional_edges("szukaj_owu", po_szuk, mapa_szuk)
    builder.add_conditional_edges("ocen_pokrycie", po_pokr, mapa_pokr)
    builder.add_edge("kontrola_cytatow", END)
    return builder.compile()
