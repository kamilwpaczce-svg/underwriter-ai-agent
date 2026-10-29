"""Wezly i routery galezi SZKODA (Etap 10):
ekstrahuj_szkode -> sprawdz_polise -> szukaj_owu -> ocen_pokrycie -> kontrola_cytatow -> zatwierdzenie.

Fragmenty OWU trzymamy w stanie jako slowniki (`dataclasses.asdict`) - checkpointer
Postgres serializuje stan, a zwykly dict nie zalezy od rejestracji wlasnych klas.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from agent.decyzje_szkody import kontroluj_cytaty
from agent.model import ModelAgenta
from agent.polisy import sprawdz_polise
from agent.schematy import OcenaZdjecia
from agent.wezly import StanGrafu, _wpis_logu, _wywolaj_model
from agent.zdjecia import MAKS_ZDJEC, BladOdczytuZdjecia, kategoria_przyczyny, porownaj, wczytaj_obraz
from rag.fragmenty import Fragment
from rag.wyszukiwarka import K_DODATKOWE, TOP_K, Wyszukiwarka
from ryzyko.cechy import cechy_ze_stanu

if TYPE_CHECKING:  # Etap 15: sklearn/skops ladowane dopiero przy faktycznym uzyciu modelu
    from ryzyko.serwowanie import ModelRyzyka

logger = logging.getLogger(__name__)

ZAPYTANIE_DOMYSLNE = "zakres ubezpieczenia zdarzenie losowe szkoda w mieniu"


def zbuduj_zapytanie_owu(pola: dict[str, Any]) -> str:
    czesci = [pola.get(nazwa) for nazwa in ("przyczyna", "rodzaj_mienia", "okolicznosci")]
    zapytanie = " ".join(str(c) for c in czesci if c)
    return zapytanie or ZAPYTANIE_DOMYSLNE


def wezel_ekstrahuj_szkode(stan: StanGrafu, model: ModelAgenta) -> dict:
    wynik, aktualizacja = _wywolaj_model(stan, "ekstrahuj_szkode", lambda: model.ekstrahuj_szkode(stan["czesci"]))
    # Jak w wezel_ekstrahuj: ostatni wezel potrzebujacy bajtow dokumentu.
    aktualizacja["czesci"] = None
    if wynik is None:
        return aktualizacja
    aktualizacja["pola"] = wynik.pola.model_dump()
    aktualizacja["podejrzane_instrukcje"] = wynik.podejrzane_instrukcje
    return aktualizacja


def _sygnal_zdjecia(status: str, powody: list[str] | None = None, ocena: dict | None = None,
                    kategoria: str | None = None, zgodnosc: str | None = None,
                    dlugotrwalosc: bool = False) -> dict:
    return {
        "status": status,
        "ocena": ocena,
        "kategoria_zgloszona": kategoria,
        "zgodnosc_rodzaju": zgodnosc,
        "sygnal_dlugotrwalosci": dlugotrwalosc,
        "powody": list(powody or []),
    }


def _oznacz_span_zdjecia(sygnal: dict) -> None:
    """Etap 23 (SPEC decyzja 10): na biezacym spanie (`wezel.analizuj_zdjecie`) wylacznie status,
    rodzaj, zgodnosc, sygnal dlugotrwalosci i pewnosc - bez bajtow, nazwy pliku, przyczyny,
    widocznego mienia ani oznak (tekst z modelu moze zawierac nazwe firmy z szyldu)."""
    span = trace.get_current_span()
    span.set_attribute("uw.zdjecie.status", sygnal["status"])
    if sygnal["status"] != "OK":
        return
    ocena = sygnal["ocena"]
    span.set_attribute("uw.zdjecie.rodzaj", ocena["rodzaj_zdarzenia"])
    span.set_attribute("uw.zdjecie.zgodnosc", sygnal["zgodnosc_rodzaju"])
    span.set_attribute("uw.zdjecie.dlugotrwalosc_sygnal", sygnal["sygnal_dlugotrwalosci"])
    span.set_attribute("uw.zdjecie.pewnosc", ocena["pewnosc"])


def _wywolaj_vision(model: Any, obraz: bytes, mime_type: str, log: list[dict]):
    """(OcenaZdjecia, MetadaneWywolania) albo None. Osobny budzet niz `_wywolaj_model` (SPEC decyzja 6):
    nie zwieksza `wywolania_llm` i nie sprawdza limitu, zeby ponowienie vision nie wyczerpalo limitu
    potrzebnego `ocen_pokrycie`. Max 2 proby; `NotImplementedError` (np. vLLM) = 1 proba.
    Do logu trafia tylko nazwa klasy bledu, nie jego tresc."""
    metoda = getattr(model, "analizuj_zdjecie", None)
    if metoda is None:
        return None
    for proba in (1, 2):
        start = time.monotonic()
        try:
            ocena, metadane = metoda(obraz, mime_type)
            if not isinstance(ocena, OcenaZdjecia):
                raise TypeError("model zwrocil cos innego niz OcenaZdjecia")
            _ = (metadane.tokeny_we, metadane.tokeny_wy)  # brak pol = blad proby, nie wyjatek w grafie
        except NotImplementedError:
            log.append(_wpis_logu(f"analizuj_zdjecie_proba{proba}_blad", (time.monotonic() - start) * 1000))
            return None
        except Exception as e:  # noqa: BLE001 - blad vision = sygnal niedostepny, a nie awaria wniosku
            log.append(_wpis_logu(f"analizuj_zdjecie_proba{proba}_blad", (time.monotonic() - start) * 1000))
            logger.warning("Blad analizy zdjecia (proba %d): %s", proba, type(e).__name__)
            continue
        return ocena, metadane
    return None


def _policz_sygnal_zdjecia(stan: StanGrafu, model: Any, log: list[dict]) -> tuple[dict, int | None, int | None]:
    """(sygnal, tokeny_we, tokeny_wy); tokeny tylko przy statusie OK."""
    zdjecia = stan.get("zdjecia")
    if not zdjecia:
        return _sygnal_zdjecia("BRAK_ZDJECIA"), None, None
    if not isinstance(zdjecia, list):
        return _sygnal_zdjecia("BLAD_ODCZYTU", ["nieprawidlowe_pole_zdjecia"]), None, None
    powody = ["pominieto_kolejne_zdjecia"] if len(zdjecia) > MAKS_ZDJEC else []
    try:
        obraz, mime_type = wczytaj_obraz(str(zdjecia[0]))
    except BladOdczytuZdjecia as e:
        return _sygnal_zdjecia("BLAD_ODCZYTU", [e.powod, *powody]), None, None

    pola = stan.get("pola")
    przyczyna = pola.get("przyczyna") if isinstance(pola, dict) else None
    kategoria = kategoria_przyczyny(przyczyna if isinstance(przyczyna, str) else None)

    wynik = _wywolaj_vision(model, obraz, mime_type, log)
    if wynik is None:
        return _sygnal_zdjecia("MODEL_NIEDOSTEPNY", powody, kategoria=kategoria), None, None
    ocena, metadane = wynik
    zgodnosc = porownaj(ocena, kategoria)
    sygnal = _sygnal_zdjecia(
        "OK",
        [*zgodnosc["powody"], *powody],
        ocena=ocena.model_dump(),
        kategoria=kategoria,
        zgodnosc=zgodnosc["zgodnosc_rodzaju"],
        dlugotrwalosc=zgodnosc["sygnal_dlugotrwalosci"],
    )
    return sygnal, metadane.tokeny_we, metadane.tokeny_wy


def wezel_analizuj_zdjecie(stan: StanGrafu, model: Any) -> dict:
    """Etap 23 (SPEC decyzje 2, 5, 6): opis zdjecia szkody "na slepo" + zgodnosc ze zgloszona
    przyczyna liczona kodem - sygnal dla likwidatora.

    Zmienia WYLACZNIE `sygnal_zdjecia` i `log` (nie `wywolania_llm`); nie rzuca wyjatkow i nie wplywa
    na decyzje ani trase. Statusy: BRAK_ZDJECIA, BLAD_ODCZYTU (brak pliku, > 5 MB, zly typ),
    MODEL_NIEDOSTEPNY (2 nieudane proby, `NotImplementedError`, nieznane zdjecie), OK.
    Zawsze dopisuje wpis `analizuj_zdjecie` (tokeny tylko przy OK).
    """
    start = time.monotonic()
    log = list(stan.get("log", []))
    tokeny_we = tokeny_wy = None
    try:
        sygnal, tokeny_we, tokeny_wy = _policz_sygnal_zdjecia(stan, model, log)
    except Exception:  # noqa: BLE001 - nietypowy stan/model = sygnal niedostepny, nie wyjatek w grafie
        logger.exception("Blad wezla analizuj_zdjecie")
        sygnal = _sygnal_zdjecia("MODEL_NIEDOSTEPNY", ["blad_wezla"])
    try:
        _oznacz_span_zdjecia(sygnal)
    except Exception:  # noqa: BLE001 - telemetria nie moze zepsuc wezla
        logger.exception("Nie udalo sie oznaczyc spanu zdjecia")
    log.append(_wpis_logu("analizuj_zdjecie", (time.monotonic() - start) * 1000, tokeny_we, tokeny_wy))
    return {"sygnal_zdjecia": sygnal, "log": log}


def wezel_sprawdz_polise(stan: StanGrafu, polisy: dict[str, dict]) -> dict:
    start = time.monotonic()
    wynik = sprawdz_polise(stan.get("pola") or {}, polisy)
    log = list(stan.get("log", []))
    log.append(_wpis_logu("sprawdz_polise", (time.monotonic() - start) * 1000))
    return {"wynik_polisy": wynik, "log": log}


def _ryzyko(status: str, wersja: str | None = None, wynik: float | None = None,
            glowne_cechy: list[str] | None = None, cechy: dict | None = None) -> dict:
    ryzyko = {"status": status, "wynik": wynik, "wersja": wersja, "glowne_cechy": glowne_cechy or []}
    if cechy is not None:
        ryzyko["cechy"] = cechy
    return ryzyko


def _oznacz_span_ryzyka(ryzyko: dict) -> None:
    """Etap 15: na biezacym spanie (`wezel.ocen_ryzyko_szkody`) tylko status, wersja i wynik -
    zadnych wartosci cech ani innych danych ze zgloszenia."""
    span = trace.get_current_span()
    span.set_attribute("uw.ryzyko.status", ryzyko["status"])
    if ryzyko.get("wersja") is not None:
        span.set_attribute("uw.ryzyko.wersja", ryzyko["wersja"])
    if ryzyko.get("wynik") is not None:
        span.set_attribute("uw.ryzyko.wynik", ryzyko["wynik"])


def wezel_ocen_ryzyko_szkody(stan: StanGrafu, model_ryzyka: "ModelRyzyka | None" = None) -> dict:
    """Etap 15 (SPEC decyzja 6): sygnal ryzyka "szkoda do weryfikacji" dla likwidatora.

    Zmienia WYLACZNIE `ryzyko_szkody` i `log`; nie rzuca wyjatkow i nie wplywa na decyzje
    ani trase (router `po_sprawdzeniu_polisy` widzi te same `wynik_polisy`/`kody`).
    Statusy: BRAK_DANYCH (cechy_ze_stanu = None, np. S01), MODEL_NIEDOSTEPNY (brak modelu
    albo wyjatek w `ocen`), OK (+ `cechy` do zapisu wejsc modelu: tylko liczby i kody).
    """
    start = time.monotonic()
    ryzyko = _liczenie_ryzyka(stan, model_ryzyka)
    try:
        _oznacz_span_ryzyka(ryzyko)
    except Exception:  # noqa: BLE001 - telemetria nie moze zepsuc wezla
        logger.exception("Nie udalo sie oznaczyc spanu ryzyka")
    log = list(stan.get("log", []))
    log.append(_wpis_logu("ocen_ryzyko_szkody", (time.monotonic() - start) * 1000))
    return {"ryzyko_szkody": ryzyko, "log": log}


def _liczenie_ryzyka(stan: StanGrafu, model_ryzyka: "ModelRyzyka | None") -> dict:
    try:
        cechy = cechy_ze_stanu(stan)
    except Exception:  # noqa: BLE001 - nietypowy stan = brak danych, nie wyjatek w grafie
        logger.exception("Blad liczenia cech ryzyka")
        return _ryzyko("BRAK_DANYCH")
    if cechy is None:
        return _ryzyko("BRAK_DANYCH")
    if model_ryzyka is None:
        return _ryzyko("MODEL_NIEDOSTEPNY")
    wersja = getattr(model_ryzyka, "wersja", None)
    try:
        wynik = model_ryzyka.ocen(cechy)
        wartosc = float(wynik["wynik"])
        if not math.isfinite(wartosc):
            raise ValueError("wynik modelu nie jest liczba skonczona")
        glowne = [str(c) for c in wynik.get("glowne_cechy") or []]
    except Exception:  # noqa: BLE001 - blad modelu = sygnal niedostepny, a nie awaria wniosku
        logger.exception("Blad oceny ryzyka (model %s)", wersja)
        return _ryzyko("MODEL_NIEDOSTEPNY", wersja=wersja)
    return _ryzyko("OK", wersja=wersja, wynik=wartosc, glowne_cechy=glowne, cechy=cechy)


def _szukaj(wyszukiwarka: Wyszukiwarka, zapytanie: str, k: int, nazwa_wezla: str, log: list[dict]):
    """(fragmenty, None) albo (None, komunikat_bledu). Dopisuje wpis do `log`."""
    start = time.monotonic()
    try:
        fragmenty = wyszukiwarka.szukaj(zapytanie, k)
    except Exception as e:  # noqa: BLE001 - blad wyszukiwarki = SKIEROWANIE, nie wyjatek w grafie
        log.append(_wpis_logu(f"{nazwa_wezla}_blad", (time.monotonic() - start) * 1000))
        logger.exception("Blad wyszukiwania OWU (%s, wezel %s)", wyszukiwarka.nazwa, nazwa_wezla)
        # Sama nazwa klasy (HttpResponseError) nie odroznia 403 (brak roli) od 404 (brak indeksu).
        szczegoly = " ".join(str(e).split())[:200]
        return None, (f"Blad wyszukiwania OWU ({wyszukiwarka.nazwa}, wezel {nazwa_wezla}): "
                      f"{type(e).__name__}: {szczegoly}")
    log.append(_wpis_logu(nazwa_wezla, (time.monotonic() - start) * 1000))
    return fragmenty, None


def wezel_szukaj_owu(stan: StanGrafu, wyszukiwarka: Wyszukiwarka) -> dict:
    log = list(stan.get("log", []))
    zapytanie = zbuduj_zapytanie_owu(stan.get("pola") or {})
    fragmenty, blad = _szukaj(wyszukiwarka, zapytanie, TOP_K, "szukaj_owu", log)
    if blad:
        return {"blad": blad, "log": log}
    return {"fragmenty_owu": [asdict(f) for f in fragmenty], "log": log}


def wezel_ocen_pokrycie(stan: StanGrafu, model: ModelAgenta, wyszukiwarka: Wyszukiwarka) -> dict:
    """Najwyzej 2 wywolania modelu i najwyzej 1 dodatkowe wyszukiwanie (top `K_DODATKOWE`).
    `dodatkowe_zapytanie` z drugiej odpowiedzi jest ignorowane."""
    pola = stan.get("pola") or {}
    wynik_polisy = stan.get("wynik_polisy") or {}
    fragmenty = [Fragment(**f) for f in stan.get("fragmenty_owu") or []]

    wynik, aktualizacja = _wywolaj_model(
        stan, "ocen_pokrycie", lambda: model.ocen_pokrycie(pola, wynik_polisy, fragmenty)
    )
    if wynik is None:
        return aktualizacja

    zapytanie = wynik.dodatkowe_zapytanie
    if zapytanie:
        aktualizacja["dodatkowe_zapytanie"] = zapytanie
        znalezione, blad = _szukaj(wyszukiwarka, zapytanie, K_DODATKOWE, "szukaj_owu_dodatkowe", aktualizacja["log"])
        if blad:
            return {**aktualizacja, "blad": blad}
        znane_id = {f.id for f in fragmenty}
        dodatkowe = [f for f in znalezione if f.id not in znane_id]
        aktualizacja["fragmenty_owu"] = [asdict(f) for f in [*fragmenty, *dodatkowe]]
        wynik, aktualizacja_2 = _wywolaj_model(
            {**stan, **aktualizacja},
            "ocen_pokrycie_2",
            lambda: model.ocen_pokrycie(pola, wynik_polisy, fragmenty, dodatkowe),
        )
        aktualizacja.update(aktualizacja_2)
        if wynik is None:
            return aktualizacja

    aktualizacja["ocena_pokrycia"] = wynik.model_dump()
    return aktualizacja


def wezel_kontrola_cytatow(stan: StanGrafu) -> dict:
    start = time.monotonic()
    kontrola = kontroluj_cytaty(stan.get("ocena_pokrycia"), stan.get("fragmenty_owu") or [])
    log = list(stan.get("log", []))
    log.append(_wpis_logu("kontrola_cytatow", (time.monotonic() - start) * 1000))
    return {"kontrola_cytatow": kontrola, "log": log}


# ---------------------------------------------------------------------------
# Routing warunkowy
# ---------------------------------------------------------------------------

def po_ekstrakcji_szkody(stan: StanGrafu) -> str:
    if stan.get("blad") or stan.get("podejrzane_instrukcje"):
        return "zatwierdzenie"
    return "analizuj_zdjecie"


def po_sprawdzeniu_polisy(stan: StanGrafu) -> str:
    kody = (stan.get("wynik_polisy") or {}).get("kody") or []
    if "S01" in kody or "S02" in kody:
        return "zatwierdzenie"
    return "szukaj_owu"


def po_szukaniu_owu(stan: StanGrafu) -> str:
    return "zatwierdzenie" if stan.get("blad") else "ocen_pokrycie"


def po_ocenie_pokrycia(stan: StanGrafu) -> str:
    return "zatwierdzenie" if stan.get("blad") else "kontrola_cytatow"
