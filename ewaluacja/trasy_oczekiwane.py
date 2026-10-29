"""Etap 24, zadanie 4: trasa przypadku przez graf i jej zgodnosc z grafem `jeden`.

`TRASY_OCZEKIWANE` = kolejnosc AGENTOW (nie wezlow), jaka na atrapie przechodzi obecny graf `jeden`
dla kazdego z 26 przypadkow (W01-W14, Z01-Z12). Wzorce pochodza z biegu atrapy wariantu `jeden`;
test `test_trasy_oczekiwane_zgadzaja_sie_z_biegiem_atrapy_wariantu_jeden` pilnuje, zeby plik nie
rozjechal sie z grafem. `trasa_zgodna` w wynikach ewaluacji = trasa agentow wariantu rowna wzorcowi.

Trasa agentow wariantu `wieloagentowy` = pole stanu `trasa_agentow` (ustawia supervisor); w wariancie
`jeden` stan go nie ma, wiec trasa jest wyprowadzana z `log` (wezel -> agent, ktory go zawiera w grafie
wieloagentowym). Dzieki temu oba warianty mierza te sama wielkosc.

Licznik wywolan LLM: w wariancie wieloagentowym `wywolania_llm` agentow jest o 1 nizsze niz w `jeden`
(krok 1 supervisora zastepuje `klasyfikuj` i liczy sie w `wywolania_supervisora`). Pole porownywalne
miedzy wariantami to `wywolania_llm_razem` = agenci + supervisor; skladniki zostaja osobno.
"""

from __future__ import annotations

import re
from typing import Any

from agent.agenci import AGENT_OWU, AGENT_SZKOD, AGENT_UNDERWRITINGU

# Wygenerowane z biegu `uruchom.py --atrapa --wariant jeden` (wnioski + szkody) 28.10.2026.
TRASY_OCZEKIWANE: dict[str, list[str]] = {
    "W01": ["agent_underwritingu"],
    "W02": ["agent_underwritingu"],
    "W03": ["agent_underwritingu"],
    "W04": ["agent_underwritingu"],
    "W05": ["agent_underwritingu"],
    "W06": ["agent_underwritingu"],
    "W07": ["agent_underwritingu"],
    "W08": ["agent_underwritingu"],
    "W09": ["agent_underwritingu"],
    "W10": ["agent_underwritingu"],
    "W11": ["agent_underwritingu"],
    "W12": ["agent_underwritingu"],
    "W13": ["agent_underwritingu"],
    "W14": [],
    "Z01": ["agent_szkod", "agent_owu"],
    "Z02": ["agent_szkod", "agent_owu"],
    "Z03": ["agent_szkod", "agent_owu"],
    "Z04": ["agent_szkod", "agent_owu"],
    "Z05": ["agent_szkod", "agent_owu"],
    "Z06": ["agent_szkod", "agent_owu"],
    "Z07": ["agent_szkod", "agent_owu"],
    "Z08": ["agent_szkod", "agent_owu"],
    "Z09": ["agent_szkod"],
    "Z10": ["agent_szkod", "agent_owu"],
    "Z11": ["agent_szkod"],
    "Z12": ["agent_szkod"],
}

_SUFIKS_PROBY = re.compile(r"_proba\d+_blad$")

# Wezel (z `log`) -> agent, ktory go zawiera. Wezly poza agentami (wczytaj, klasyfikuj, supervisor*,
# zakoncz_inny, zatwierdzenie) nie naleza do zadnego agenta.
_AGENT_WEZLA = {
    **dict.fromkeys(("ekstrahuj", "waliduj", "ocen", "kontrola"), AGENT_UNDERWRITINGU),
    **dict.fromkeys(("ekstrahuj_szkode", "analizuj_zdjecie", "sprawdz_polise", "ocen_ryzyko_szkody"), AGENT_SZKOD),
    **dict.fromkeys(("szukaj_owu", "ocen_pokrycie", "kontrola_cytatow"), AGENT_OWU),
}


def trasa_z_logu(log: list[dict[str, Any]]) -> list[str]:
    """Nazwy wezlow z `log` w kolejnosci wykonania, bez sufiksow prob (`ekstrahuj_proba1_blad` -> `ekstrahuj`);
    kolejne powtorzenia tego samego wezla (ponowienia) zwiniete do jednego."""
    trasa: list[str] = []
    for wpis in log or []:
        nazwa = _SUFIKS_PROBY.sub("", wpis["wezel"])
        if not trasa or trasa[-1] != nazwa:
            trasa.append(nazwa)
    return trasa


def trasa_agentow(stan: dict[str, Any]) -> list[str]:
    """Kolejnosc agentow: z pola `trasa_agentow` (wariant wieloagentowy) albo z `log` (wariant `jeden`)."""
    if stan.get("trasa_agentow") is not None:
        return list(stan["trasa_agentow"])
    agenci: list[str] = []
    for wezel in trasa_z_logu(stan.get("log") or []):
        agent = _AGENT_WEZLA.get(wezel)
        if agent is not None and (not agenci or agenci[-1] != agent):
            agenci.append(agent)
    return agenci


def trasa_zgodna(id_przypadku: str, agenci: list[str]) -> bool:
    """Trasa agentow rowna wzorcowi z grafu `jeden`. Brak wzorca dla przypadku = False (nie zgadujemy)."""
    wzorzec = TRASY_OCZEKIWANE.get(id_przypadku)
    return wzorzec is not None and list(agenci) == wzorzec


def pola_wariantu(id_przypadku: str, stan: dict[str, Any]) -> dict[str, Any]:
    """Pola z decyzji 10 dla wiersza wyniku (wspolne dla modulu wnioski i szkody)."""
    agenci = trasa_agentow(stan)
    wywolania_supervisora = stan.get("wywolania_supervisora", 0)
    return {
        "trasa": trasa_z_logu(stan.get("log") or []),
        "trasa_agentow": agenci,
        "trasa_zgodna": trasa_zgodna(id_przypadku, agenci),
        "wywolania_supervisora": wywolania_supervisora,
        "korekty_supervisora": stan.get("korekty_supervisora", 0),
        "uzasadnienia_supervisora": list(stan.get("uzasadnienia_supervisora") or []),
        "wywolania_llm_razem": stan.get("wywolania_llm", 0) + wywolania_supervisora,
    }
