"""Budowa skompilowanego grafu LangGraph agenta underwritera."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from agent.instrukcje import wytyczne_na_instrukcje
from agent.model import ModelAgenta
from agent.polisy import SCIEZKA_POLIS, wczytaj_polisy
from agent.wezly import (
    StanGrafu,
    po_ekstrakcji,
    po_klasyfikacji,
    po_ocenie,
    wezel_ekstrahuj,
    wezel_klasyfikuj,
    wezel_kontrola,
    wezel_ocen,
    wezel_waliduj,
    wezel_wczytaj,
    wezel_zakoncz_inny,
    wezel_zatwierdzenie,
)
from agent.wezly_szkody import (
    po_ekstrakcji_szkody,
    po_ocenie_pokrycia,
    po_sprawdzeniu_polisy,
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
from rag.wyszukiwarka import Wyszukiwarka, WyszukiwarkaLokalna

if TYPE_CHECKING:
    from ryzyko.serwowanie import ModelRyzyka

_GENERATOR_DIR = Path(__file__).resolve().parent.parent / "generator"
sys.path.insert(0, str(_GENERATOR_DIR))
from reguly import wczytaj_wytyczne  # noqa: E402

SCIEZKA_WYTYCZNYCH_DOMYSLNA = Path(__file__).resolve().parent.parent / "wytyczne" / "wytyczne_mienie_v1.yaml"


def zbuduj_graf(
    model: ModelAgenta,
    checkpointer: BaseCheckpointSaver,
    sciezka_wytycznych: str | Path = SCIEZKA_WYTYCZNYCH_DOMYSLNA,
    wyszukiwarka: Wyszukiwarka | None = None,
    sciezka_polis: str | Path = SCIEZKA_POLIS,
    model_ryzyka: "ModelRyzyka | None" = None,
):
    """Zwraca skompilowany graf. `checkpointer`: MemorySaver w Etapie 2/3 - Postgres.
    Etap 10: `wyszukiwarka` dla galezi SZKODA (domyslnie lokalny BM25 - bez sieci);
    polisy wczytywane raz, przy budowie grafu (brak pliku = blad od razu, nie przy szkodzie).
    Etap 15: `model_ryzyka` (opcjonalny) zasila wezel `ocen_ryzyko_szkody`; None = status
    MODEL_NIEDOSTEPNY w panelu, trasa i decyzja bez zmian."""
    wytyczne = wczytaj_wytyczne(sciezka_wytycznych)
    instrukcje = wytyczne_na_instrukcje(sciezka_wytycznych)
    polisy = wczytaj_polisy(sciezka_polis)
    wyszukiwarka = wyszukiwarka if wyszukiwarka is not None else WyszukiwarkaLokalna()

    builder = StateGraph(StanGrafu)
    builder.add_node("wczytaj", sledz_wezel("wczytaj", wezel_wczytaj))
    builder.add_node("klasyfikuj", sledz_wezel("klasyfikuj", lambda stan: wezel_klasyfikuj(stan, model)))
    builder.add_node("zakoncz_inny", sledz_wezel("zakoncz_inny", wezel_zakoncz_inny))
    builder.add_node("ekstrahuj", sledz_wezel("ekstrahuj", lambda stan: wezel_ekstrahuj(stan, model)))
    builder.add_node("waliduj", sledz_wezel("waliduj", wezel_waliduj))
    builder.add_node("ocen", sledz_wezel("ocen", lambda stan: wezel_ocen(stan, model, instrukcje)))
    builder.add_node("kontrola", sledz_wezel("kontrola", lambda stan: wezel_kontrola(stan, wytyczne)))
    builder.add_node("zatwierdzenie", sledz_wezel("zatwierdzenie", wezel_zatwierdzenie))
    builder.add_node(
        "ekstrahuj_szkode", sledz_wezel("ekstrahuj_szkode", lambda stan: wezel_ekstrahuj_szkode(stan, model))
    )
    builder.add_node(
        "analizuj_zdjecie", sledz_wezel("analizuj_zdjecie", lambda stan: wezel_analizuj_zdjecie(stan, model))
    )
    builder.add_node("sprawdz_polise", sledz_wezel("sprawdz_polise", lambda stan: wezel_sprawdz_polise(stan, polisy)))
    builder.add_node(
        "ocen_ryzyko_szkody",
        sledz_wezel("ocen_ryzyko_szkody", lambda stan: wezel_ocen_ryzyko_szkody(stan, model_ryzyka)),
    )
    builder.add_node("szukaj_owu", sledz_wezel("szukaj_owu", lambda stan: wezel_szukaj_owu(stan, wyszukiwarka)))
    builder.add_node(
        "ocen_pokrycie",
        sledz_wezel("ocen_pokrycie", lambda stan: wezel_ocen_pokrycie(stan, model, wyszukiwarka)),
    )
    builder.add_node("kontrola_cytatow", sledz_wezel("kontrola_cytatow", wezel_kontrola_cytatow))

    builder.add_edge(START, "wczytaj")
    builder.add_edge("wczytaj", "klasyfikuj")
    builder.add_conditional_edges(
        "klasyfikuj",
        po_klasyfikacji,
        {
            "zatwierdzenie": "zatwierdzenie",
            "zakoncz_inny": "zakoncz_inny",
            "ekstrahuj": "ekstrahuj",
            "ekstrahuj_szkode": "ekstrahuj_szkode",
        },
    )
    builder.add_edge("zakoncz_inny", END)
    builder.add_conditional_edges(
        "ekstrahuj", po_ekstrakcji, {"zatwierdzenie": "zatwierdzenie", "waliduj": "waliduj"}
    )
    builder.add_edge("waliduj", "ocen")
    builder.add_conditional_edges(
        "ocen", po_ocenie, {"zatwierdzenie": "zatwierdzenie", "kontrola": "kontrola"}
    )
    builder.add_edge("kontrola", "zatwierdzenie")
    builder.add_conditional_edges(
        "ekstrahuj_szkode",
        po_ekstrakcji_szkody,
        {"zatwierdzenie": "zatwierdzenie", "analizuj_zdjecie": "analizuj_zdjecie"},
    )
    builder.add_edge("analizuj_zdjecie", "sprawdz_polise")
    builder.add_edge("sprawdz_polise", "ocen_ryzyko_szkody")
    builder.add_conditional_edges(
        "ocen_ryzyko_szkody",
        po_sprawdzeniu_polisy,
        {"zatwierdzenie": "zatwierdzenie", "szukaj_owu": "szukaj_owu"},
    )
    builder.add_conditional_edges(
        "szukaj_owu", po_szukaniu_owu, {"zatwierdzenie": "zatwierdzenie", "ocen_pokrycie": "ocen_pokrycie"}
    )
    builder.add_conditional_edges(
        "ocen_pokrycie",
        po_ocenie_pokrycia,
        {"zatwierdzenie": "zatwierdzenie", "kontrola_cytatow": "kontrola_cytatow"},
    )
    builder.add_edge("kontrola_cytatow", "zatwierdzenie")
    builder.add_edge("zatwierdzenie", END)

    return builder.compile(checkpointer=checkpointer)


WARIANTY_GRAFU = ("jeden", "wieloagentowy")


def budowniczy_grafu(wariant: str):
    """Etap 24: funkcja budujaca graf dla wariantu - `zbuduj_graf` (`jeden`, domyslny) albo
    `zbuduj_graf_wieloagentowy`; ta sama sygnatura. Nieznany wariant -> ValueError (bez cichego fallbacku)."""
    if wariant == "jeden":
        return zbuduj_graf
    if wariant == "wieloagentowy":
        from agent.graf_wieloagentowy import zbuduj_graf_wieloagentowy  # import tutaj: modul importuje agent.graf

        return zbuduj_graf_wieloagentowy
    raise ValueError(f"Nieznany wariant grafu: {wariant!r} (dozwolone: {', '.join(WARIANTY_GRAFU)}).")


def wybierz_graf(wariant: str, **kw):
    """Etap 24: buduje skompilowany graf wybranego wariantu; `kw` jak w `zbuduj_graf`
    (`model`, `checkpointer`, `sciezka_wytycznych`, `wyszukiwarka`, `sciezka_polis`, `model_ryzyka`)."""
    return budowniczy_grafu(wariant)(**kw)
