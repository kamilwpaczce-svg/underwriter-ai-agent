"""Etap 24, zadanie 3: graf wieloagentowy (supervisor + 3 agenci-podgrafy + `zatwierdzenie`).

Sygnatura jak `agent.graf.zbuduj_graf`. Wspolne z obecnym grafem: wezly, prompty, kontrole
deterministyczne, `zatwierdzenie` z `interrupt` (jedyny punkt nadzoru - w rodzicu), checkpointer.

    START -> wczytaj -> supervisor --Command(goto)--> agent_underwritingu | agent_szkod | agent_owu
                                                      | zakoncz_inny | zatwierdzenie
    agent_* -> supervisor (krawedz statyczna), zakoncz_inny -> END, zatwierdzenie -> END
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from agent.agenci import (
    AGENT_OWU,
    AGENT_SZKOD,
    AGENT_UNDERWRITINGU,
    zbuduj_agenta_owu,
    zbuduj_agenta_szkod,
    zbuduj_agenta_underwritingu,
)
from agent.graf import SCIEZKA_WYTYCZNYCH_DOMYSLNA, wczytaj_wytyczne
from agent.instrukcje import wytyczne_na_instrukcje
from agent.model import ModelAgenta
from agent.polisy import SCIEZKA_POLIS, wczytaj_polisy
from agent.supervisor import CELE_SUPERVISORA, wezel_supervisor
from agent.wezly import StanGrafu, wezel_wczytaj, wezel_zakoncz_inny, wezel_zatwierdzenie
from obserwowalnosc.wezly import sledz_wezel
from rag.wyszukiwarka import Wyszukiwarka, WyszukiwarkaLokalna

if TYPE_CHECKING:
    from ryzyko.serwowanie import ModelRyzyka


def zbuduj_graf_wieloagentowy(
    model: ModelAgenta,
    checkpointer: BaseCheckpointSaver,
    sciezka_wytycznych: str | Path = SCIEZKA_WYTYCZNYCH_DOMYSLNA,
    wyszukiwarka: Wyszukiwarka | None = None,
    sciezka_polis: str | Path = SCIEZKA_POLIS,
    model_ryzyka: "ModelRyzyka | None" = None,
):
    """Zwraca skompilowany graf wieloagentowy; argumenty jak w `zbuduj_graf`."""
    wytyczne = wczytaj_wytyczne(sciezka_wytycznych)
    instrukcje = wytyczne_na_instrukcje(sciezka_wytycznych)
    polisy = wczytaj_polisy(sciezka_polis)
    wyszukiwarka = wyszukiwarka if wyszukiwarka is not None else WyszukiwarkaLokalna()

    builder = StateGraph(StanGrafu)
    builder.add_node("wczytaj", sledz_wezel("wczytaj", wezel_wczytaj))
    # `destinations`: owijka `sledz_wezel` gubi adnotacje Command[Literal[...]], a bez nich diagram nie pokaze krawedzi.
    builder.add_node(
        "supervisor",
        sledz_wezel("supervisor", lambda stan: wezel_supervisor(stan, model)),
        destinations=CELE_SUPERVISORA,
    )
    builder.add_node(AGENT_UNDERWRITINGU, zbuduj_agenta_underwritingu(model, wytyczne, instrukcje))
    builder.add_node(AGENT_SZKOD, zbuduj_agenta_szkod(model, polisy, model_ryzyka))
    builder.add_node(AGENT_OWU, zbuduj_agenta_owu(model, wyszukiwarka))
    builder.add_node("zakoncz_inny", sledz_wezel("zakoncz_inny", wezel_zakoncz_inny))
    builder.add_node("zatwierdzenie", sledz_wezel("zatwierdzenie", wezel_zatwierdzenie))

    builder.add_edge(START, "wczytaj")
    builder.add_edge("wczytaj", "supervisor")
    for agent in (AGENT_UNDERWRITINGU, AGENT_SZKOD, AGENT_OWU):
        builder.add_edge(agent, "supervisor")
    builder.add_edge("zakoncz_inny", END)
    builder.add_edge("zatwierdzenie", END)

    return builder.compile(checkpointer=checkpointer)
