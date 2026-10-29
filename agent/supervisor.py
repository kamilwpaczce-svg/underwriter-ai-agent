"""Etap 24, zadanie 3: supervisor wariantu wieloagentowego (wezel LangGraph zwracajacy `Command(goto=...)`).

LLM jest wolany tylko tam, gdzie jest wybor:
- krok 1 (po `wczytaj`): dokument -> `typ_dokumentu` + pierwszy agent (zastepuje wezel `klasyfikuj`);
- krok 2 (po `agent_szkod`, bez bledu i bez podejrzanych instrukcji): `agent_owu` albo `zakoncz`.
Reszta przejsc jest deterministyczna i zapisana w `log` jako `supervisor_deterministyczny`:
po `agent_underwritingu` i `agent_owu`, a takze po kazdym agencie, gdy w stanie jest `blad` albo
`podejrzane_instrukcje` (decyzje właściciela z 27.10 i 28.10) - zawsze do `zatwierdzenie`.

Bramki (`dozwolone_ruchy`): ruch zabroniony jest zamieniany na wybor `router_deterministyczny`
(lustro routerow obecnego grafu) i liczony w `korekty_supervisora`. Wybor DOZWOLONY, ale inny niz
w obecnym grafie, nie jest korygowany - to wlasnie mierzy ewaluacja (zgodnosc trasy); decyzje
merytoryczne i tak ustala `ustal_decyzje_szkody` / silnik regul.

Supervisor ma wlasny licznik `wywolania_supervisora` (liczba KROKOW z LLM, kazdy z 1 ponowieniem) -
nie zuzywa `LIMIT_WYWOLAN_LLM` agentow.
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.types import Command
from opentelemetry import trace

from agent.agenci import AGENT_OWU, AGENT_SZKOD, AGENT_UNDERWRITINGU
from agent.instrukcje_supervisor import podsumowanie_dla_supervisora
from agent.model import ModelAgenta
from agent.wezly import StanGrafu, _wpis_logu
from agent.wezly_szkody import po_sprawdzeniu_polisy

MAKS_KROKOW_SUPERVISORA = 3
LICZBA_PROB = 2  # wywolanie + 1 ponowienie

_ZAKONCZ = "zakoncz"
_AGENT_WG_TYPU = {"WNIOSEK": AGENT_UNDERWRITINGU, "SZKODA": AGENT_SZKOD, "INNY": _ZAKONCZ}
_AGENCI = (AGENT_UNDERWRITINGU, AGENT_SZKOD, AGENT_OWU)

CELE_SUPERVISORA = (*_AGENCI, "zatwierdzenie", "zakoncz_inny")  # do `destinations=` przy rysowaniu grafu


def _ostatni_agent(stan: StanGrafu) -> str | None:
    trasa = stan.get("trasa_agentow") or []
    return trasa[-1] if trasa else None


def dozwolone_ruchy(stan: StanGrafu) -> set[str]:
    """Ruchy dozwolone dla wyboru LLM (slownik `AgentDocelowy`), na podstawie stanu.
    Krok 1: typ dokumentu wygrywa nad `nastepny`. Po `agent_szkod`: `agent_owu` (tylko raz) albo `zakoncz`.
    Po pozostalych agentach: tylko `zakoncz` (przejscie deterministyczne)."""
    ostatni = _ostatni_agent(stan)
    if ostatni is None:
        cel = _AGENT_WG_TYPU.get(stan.get("typ_dokumentu") or "")
        return {cel} if cel else set()
    trasa = stan.get("trasa_agentow") or []
    if ostatni == AGENT_SZKOD and stan.get("typ_dokumentu") == "SZKODA" and AGENT_OWU not in trasa:
        return {AGENT_OWU, _ZAKONCZ}
    return {_ZAKONCZ}


def router_deterministyczny(stan: StanGrafu) -> str:
    """Wybor, ktory zrobilby obecny graf (lustro `po_klasyfikacji` i `po_sprawdzeniu_polisy`)."""
    ostatni = _ostatni_agent(stan)
    if ostatni is None:
        return _AGENT_WG_TYPU.get(stan.get("typ_dokumentu") or "", _ZAKONCZ)
    if ostatni == AGENT_SZKOD and AGENT_OWU not in (stan.get("trasa_agentow") or []):
        return AGENT_OWU if po_sprawdzeniu_polisy(stan) == "szukaj_owu" else _ZAKONCZ
    return _ZAKONCZ


def _na_wezel(cel: str, stan: StanGrafu) -> str:
    """`zakoncz` przy INNY -> `zakoncz_inny`, w kazdym innym przypadku -> `zatwierdzenie`."""
    if cel != _ZAKONCZ:
        return cel
    return "zakoncz_inny" if stan.get("typ_dokumentu") == "INNY" else "zatwierdzenie"


def _opisz_span(krok: int, wybor: str, korekta: bool, llm: bool) -> None:
    """Atrybuty spanu `wezel.supervisor` (decyzja 8). Bez uzasadnienia i tresci dokumentu (RODO)."""
    span = trace.get_current_span()
    span.set_attribute("uw.supervisor.krok", krok)
    span.set_attribute("uw.supervisor.wybor", wybor)
    span.set_attribute("uw.supervisor.korekta", korekta)
    span.set_attribute("uw.supervisor.llm", llm)


def _wywolaj_z_ponowieniem(model: ModelAgenta, czesci, podsumowanie, krok: int, log: list[dict]):
    """(decyzja, None) albo (None, komunikat_bledu). Krok 1 bez `typ_dokumentu` liczy sie jak nieudana proba."""
    ostatni_blad: str | None = None
    for proba in range(LICZBA_PROB):
        start = time.monotonic()
        try:
            decyzja, metadane = model.decyduj_supervisor(czesci, podsumowanie)
            if krok == 1 and decyzja.typ_dokumentu is None:
                raise ValueError("krok 1 supervisora wymaga typ_dokumentu")
        except Exception as e:  # noqa: BLE001 - kazdy blad modelu liczy sie jako proba (jak `_wywolaj_model`)
            log.append(_wpis_logu(f"supervisor_proba{proba + 1}_blad", (time.monotonic() - start) * 1000))
            ostatni_blad = type(e).__name__
            continue
        log.append(
            _wpis_logu("supervisor", (time.monotonic() - start) * 1000, metadane.tokeny_we, metadane.tokeny_wy)
        )
        return decyzja, None
    return None, f"Blad wezla 'supervisor' po {LICZBA_PROB} probach (typ bledu: {ostatni_blad})."


def _blad_supervisora(stan: StanGrafu, krok: int, log: list[dict], komunikat: str, wywolania: int) -> Command:
    _opisz_span(krok, "zatwierdzenie", False, True)
    return Command(
        goto="zatwierdzenie",
        update={
            "blad": komunikat,
            "log": log,
            "wywolania_supervisora": wywolania,
            "trasa_agentow": list(stan.get("trasa_agentow") or []),
            "korekty_supervisora": stan.get("korekty_supervisora", 0),
            "uzasadnienia_supervisora": list(stan.get("uzasadnienia_supervisora") or []),
        },
    )


def wezel_supervisor(stan: StanGrafu, model: ModelAgenta) -> Command:
    trasa = list(stan.get("trasa_agentow") or [])
    krok = len(trasa) + 1
    log = list(stan.get("log", []))
    ostatni = _ostatni_agent(stan)

    # Przejscie deterministyczne (bez LLM): po agencie z bledem/podejrzanymi instrukcjami, po agencie
    # underwritingu i po agencie OWU.
    if ostatni is not None and (
        stan.get("blad") or stan.get("podejrzane_instrukcje") or ostatni in (AGENT_UNDERWRITINGU, AGENT_OWU)
    ):
        start = time.monotonic()
        log.append(_wpis_logu("supervisor_deterministyczny", (time.monotonic() - start) * 1000))
        _opisz_span(krok, "zatwierdzenie", False, False)
        return Command(goto="zatwierdzenie", update={"log": log})

    wywolania = stan.get("wywolania_supervisora", 0)
    if wywolania >= MAKS_KROKOW_SUPERVISORA:
        komunikat = f"Przekroczono limit {MAKS_KROKOW_SUPERVISORA} krokow supervisora."
        return _blad_supervisora(stan, krok, log, komunikat, wywolania)
    wywolania += 1

    if ostatni is None:  # krok 1: dokument -> typ + pierwszy agent
        decyzja, komunikat = _wywolaj_z_ponowieniem(model, stan.get("czesci"), None, 1, log)
    else:  # krok 2: po agent_szkod, tylko zwiezle podsumowanie (bez tresci dokumentu i danych osobowych)
        decyzja, komunikat = _wywolaj_z_ponowieniem(model, None, podsumowanie_dla_supervisora(stan), krok, log)
    if decyzja is None:
        return _blad_supervisora(stan, krok, log, komunikat, wywolania)

    stan_po = dict(stan)
    if ostatni is None:
        stan_po["typ_dokumentu"] = decyzja.typ_dokumentu  # typ wygrywa nad `nastepny`
    cel = decyzja.nastepny
    korekta = cel not in dozwolone_ruchy(stan_po)
    if korekta:
        cel = router_deterministyczny(stan_po)
        log.append(_wpis_logu("supervisor_korekta", 0.0))
    wezel_docelowy = _na_wezel(cel, stan_po)

    uzasadnienia = list(stan.get("uzasadnienia_supervisora") or [])
    uzasadnienia.append(decyzja.uzasadnienie)
    update: dict[str, Any] = {
        "log": log,
        "wywolania_supervisora": wywolania,
        "korekty_supervisora": stan.get("korekty_supervisora", 0) + (1 if korekta else 0),
        "trasa_agentow": trasa + ([cel] if cel in _AGENCI else []),
        "uzasadnienia_supervisora": uzasadnienia,
    }
    if ostatni is None:
        update["typ_dokumentu"] = decyzja.typ_dokumentu
    _opisz_span(krok, wezel_docelowy, korekta, True)
    return Command(goto=wezel_docelowy, update=update)
