"""Deterministyczna czesc galezi SZKODA (Etap 10): kontrola cytatow, ustalenie decyzji
i podsumowanie dla czlowieka. Czyste funkcje na slownikach ze stanu grafu - bez LLM.

Kolejnosc ustalania decyzji (pierwsza pasujaca wygrywa):
1. blad agenta -> SKIEROWANIE,
2. podejrzane instrukcje w dokumencie -> SKIEROWANIE,
3. S01 (brak polisy) -> SKIEROWANIE,
4. S02 (zdarzenie poza okresem) -> ODMOWA (przyczyna formalna, bez cytatu z OWU),
5. brak oceny pokrycia -> SKIEROWANIE,
6. kontrola cytatow nie przeszla -> SKIEROWANIE (cytat_spoza_kontekstu / brak_cytatu),
7. POKRYTA przy S03 (kwota > SU) -> SKIEROWANIE,
8. POKRYTA przy brakach danych polisy (np. brak daty zdarzenia) -> SKIEROWANIE,
9. w pozostalych przypadkach decyzja z oceny pokrycia.
"""

from __future__ import annotations

from typing import Any

from rag.fragmenty import parsuj_liczbe, parsuj_odwolanie

DECYZJE_WYMAGAJACE_CYTATU = ("POKRYTA", "ODMOWA")


def klucz_cytatu(cytat: dict[str, Any]) -> tuple[int, int] | None:
    """`(paragraf, ustep)` z cytatu modelu. Akceptuje `"§ 6"/"4"`, `"6"/"ust. 4"`
    i `"§ 6 ust. 4"/""`. Bez numeru paragrafu albo ustepu -> None."""
    paragraf = str(cytat.get("paragraf") or "")
    ustep = parsuj_liczbe(str(cytat.get("ustep") or ""))
    if ustep is None:
        return parsuj_odwolanie(paragraf)
    numer_paragrafu = parsuj_liczbe(paragraf)
    if numer_paragrafu is None:
        return None
    return numer_paragrafu, ustep


def kontroluj_cytaty(ocena: dict[str, Any] | None, fragmenty: list[dict[str, Any]]) -> dict[str, Any]:
    if not ocena:
        return {"ok": False, "powod": "brak_oceny", "odrzucone": []}
    dostepne = {(f["paragraf"], f["ustep"]) for f in fragmenty}
    cytaty = ocena.get("cytaty") or []
    odrzucone = [c for c in cytaty if klucz_cytatu(c) not in dostepne]
    if odrzucone:
        return {"ok": False, "powod": "cytat_spoza_kontekstu", "odrzucone": odrzucone}
    if ocena.get("decyzja") in DECYZJE_WYMAGAJACE_CYTATU and not cytaty:
        return {"ok": False, "powod": "brak_cytatu", "odrzucone": []}
    return {"ok": True, "powod": None, "odrzucone": []}


def ustal_decyzje_szkody(stan: dict[str, Any]) -> tuple[str, list[str]]:
    if stan.get("blad"):
        return "SKIEROWANIE", ["blad_agenta"]
    if stan.get("podejrzane_instrukcje"):
        return "SKIEROWANIE", ["podejrzane_instrukcje"]
    wynik_polisy = stan.get("wynik_polisy") or {}
    kody = wynik_polisy.get("kody") or []
    if "S01" in kody:
        return "SKIEROWANIE", ["S01"]
    if "S02" in kody:
        return "ODMOWA", ["S02"]
    ocena = stan.get("ocena_pokrycia")
    if not ocena:
        return "SKIEROWANIE", ["brak_oceny"]
    kontrola = stan.get("kontrola_cytatow") or kontroluj_cytaty(ocena, stan.get("fragmenty_owu") or [])
    if not kontrola["ok"]:
        return "SKIEROWANIE", [kontrola["powod"]]
    decyzja = ocena["decyzja"]
    if decyzja == "POKRYTA":
        if "S03" in kody:
            return "SKIEROWANIE", ["S03"]
        braki = wynik_polisy.get("braki") or []
        if braki:
            return "SKIEROWANIE", [f"brak_danych:{pole}" for pole in braki]
    return decyzja, ["ocena_llm"]


def _cytaty_z_trescia(ocena: dict[str, Any], fragmenty: list[dict[str, Any]]) -> list[dict[str, Any]]:
    po_kluczu = {(f["paragraf"], f["ustep"]): f for f in fragmenty}
    wynik = []
    for cytat in ocena.get("cytaty") or []:
        fragment = po_kluczu.get(klucz_cytatu(cytat))
        wynik.append(
            {
                **cytat,
                "fragment_id": fragment["id"] if fragment else None,
                "tresc": fragment["tresc"] if fragment else None,
            }
        )
    return wynik


def _ryzyko_do_panelu(ryzyko: dict[str, Any] | None) -> dict[str, Any]:
    """Etap 15: sygnal ryzyka bez pola `cechy` (cechy sluza tylko do zapisu wejsc modelu)."""
    if not ryzyko:
        return {"status": "BRAK_DANYCH"}
    return {k: v for k, v in ryzyko.items() if k != "cechy"}


def _zdjecie_do_panelu(sygnal: dict[str, Any] | None) -> dict[str, Any]:
    """Etap 23: sygnal zdjecia (nie zawiera bajtow ani sciezki pliku). Brak sygnalu = wezel pominiety
    (podejrzane instrukcje albo blad ekstrakcji) - panel pokazuje status, nie puste miejsce."""
    if not sygnal:
        return {"status": "BRAK_ZDJECIA", "powody": ["pominiete"]}
    return dict(sygnal)


def orkiestracja_do_panelu(stan: dict[str, Any]) -> dict[str, Any] | None:
    """Etap 24: klucz `orkiestracja` panelu. None w wariancie `jeden` (stan bez `trasa_agentow`) -
    wtedy panel nie ma tego klucza i stare testy panelu zostaja bez zmian."""
    trasa = stan.get("trasa_agentow")
    if trasa is None:
        return None
    return {
        "wariant": "wieloagentowy",
        "trasa_agentow": list(trasa),
        "korekty": stan.get("korekty_supervisora", 0),
        "uzasadnienia": list(stan.get("uzasadnienia_supervisora") or []),
    }


def podsumowanie_szkody(stan: dict[str, Any]) -> dict[str, Any]:
    """Wartosc `interrupt` dla szkody: to widzi czlowiek (UI) i to trafia do audytu."""
    ocena = stan.get("ocena_pokrycia") or {}
    fragmenty = stan.get("fragmenty_owu") or []
    decyzja, powody = ustal_decyzje_szkody(stan)
    panel = {
        "plik": stan.get("plik"),
        "typ_dokumentu": "SZKODA",
        "pola": stan.get("pola"),
        "podejrzane_instrukcje": stan.get("podejrzane_instrukcje"),
        "blad": stan.get("blad"),
        "wynik_polisy": stan.get("wynik_polisy"),
        "decyzja": decyzja,
        "powody_decyzji": powody,
        "decyzja_llm": ocena.get("decyzja"),
        "cytaty": _cytaty_z_trescia(ocena, fragmenty),
        "brakujace_dokumenty": list(ocena.get("brakujace_dokumenty") or []),
        "kontrola_cytatow": stan.get("kontrola_cytatow"),
        "ryzyko": _ryzyko_do_panelu(stan.get("ryzyko_szkody")),
        "zdjecie": _zdjecie_do_panelu(stan.get("sygnal_zdjecia")),
        "dodatkowe_zapytanie": stan.get("dodatkowe_zapytanie"),
        "fragmenty_owu_id": [f["id"] for f in fragmenty],
    }
    orkiestracja = orkiestracja_do_panelu(stan)
    if orkiestracja is not None:
        panel["orkiestracja"] = orkiestracja
    return panel
