"""Job dryfu cech modelu ryzyka szkody (Etap 15, SPEC decyzje 9 i 10, zadanie 6).

Uruchamianie: `python -m ryzyko.job_dryfu` (Azure Container Apps Job, cron 06:00 UTC, ten
sam obraz co uw-api). Job TYLKO CZYTA: okno ostatnich 30 dni z tabeli `wejscia_modelu`
i `referencja.json` z Blob (`modele/ryzyko_szkody/`), liczy PSI per cecha i zapisuje wynik
w SPANIE `dryf.przebieg` (App Insights). Nic nie zapisuje do bazy - zdublowany bieg tego
samego dnia daje tylko drugi span.

Atrybuty spanu (tylko liczby i nazwy cech - zadnych tresci dokumentow, NIP, nazwisk):
- `uw.dryf.status`: `OK` | `DRYF` (psi_max > 0,2) | `ZA_MALO_DANYCH` (n < 200),
- `uw.dryf.n`: liczba wierszy w oknie,
- `uw.dryf.psi_max`, `uw.dryf.cecha_max`, `uw.dryf.psi.<cecha>` (tylko gdy PSI policzono),
- przy bledzie: status spanu ERROR, `error.type` (nazwa klasy wyjatku, nigdy tresc) i
  `uw.dryf.etap_bledu` (`referencja` | `baza` | `psi` | `nieznany`).

Kody wyjscia: 0 = przebieg wykonany (takze ZA_MALO_DANYCH i DRYF - dryf to wynik, nie awaria
joba; sygnalizuje go alert A), 1 = brak referencji / blad bazy / PSI nie do policzenia.
NIGDY PSI = 0 z braku danych: brak danych to ZA_MALO_DANYCH albo blad, nie "brak dryfu".

Job jest krotki, wiec przed wyjsciem WYMUSZA flush telemetrii - bez tego BatchSpanProcessor
nie zdazylby wyeksportowac spanu i alert B ("brak spanu") krzyczalby mimo udanego biegu.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import select

from obserwowalnosc import telemetria
from obserwowalnosc.telemetria import tracer
from ryzyko.cechy import CECHY
from ryzyko.serwowanie import KONTENER_DOMYSLNY, PLIK_REFERENCJI, PREFIKS_DOMYSLNY

logger = logging.getLogger(__name__)

NAZWA_SPANU = "dryf.przebieg"
OKNO_DNI = 30
MIN_WIERSZY = 200
PROG_DRYFU = 0.2  # PSI > 0,2 = dryf (regula kciuka, ryzyko/psi.py)
TIMEOUT_FLUSH_MS = 30_000

STATUS_OK = "OK"
STATUS_DRYF = "DRYF"
STATUS_ZA_MALO = "ZA_MALO_DANYCH"


class _BladEtapu(Exception):
    """Wewnetrzny: opakowuje blad z nazwa etapu (do `uw.dryf.etap_bledu`)."""

    def __init__(self, etap: str, przyczyna: Exception):
        super().__init__(etap)
        self.etap = etap
        self.przyczyna = przyczyna


def _wczytaj_referencje(magazyn: Any, kontener: str, prefiks: str) -> dict[str, Any]:
    try:
        ref = json.loads(magazyn.pobierz_z_kontenera(kontener, prefiks + PLIK_REFERENCJI).decode("utf-8"))
        if not isinstance(ref, dict):
            raise ValueError("referencja nie jest slownikiem")
        brakujace = [c for c in CECHY if c not in ref]
        if brakujace:
            raise ValueError(f"referencja bez cech: {brakujace}")
        return ref
    except Exception as e:  # noqa: BLE001 - kazdy blad = ERROR + exit 1, nigdy PSI = 0
        raise _BladEtapu("referencja", e) from e


def _wczytaj_wiersze(fabryka_sesji: Any, od: datetime) -> list[dict[str, Any]]:
    from api.baza import WejscieModelu

    try:
        with fabryka_sesji() as sesja:
            return list(
                sesja.execute(select(WejscieModelu.cechy).where(WejscieModelu.utworzono >= od)).scalars().all()
            )
    except Exception as e:  # noqa: BLE001
        raise _BladEtapu("baza", e) from e


def _policz_psi(ref: dict[str, Any], wiersze: list[dict[str, Any]]) -> dict[str, float]:
    import pandas as pd

    from ryzyko.psi import psi

    try:
        return psi(ref, pd.DataFrame(wiersze))
    except Exception as e:  # noqa: BLE001
        raise _BladEtapu("psi", e) from e


def _atrybuty_wyniku(n: int, wyniki: dict[str, float] | None) -> dict[str, Any]:
    if wyniki is None:
        return {"uw.dryf.status": STATUS_ZA_MALO, "uw.dryf.n": n}
    cecha_max = max(wyniki, key=lambda c: wyniki[c])
    psi_max = wyniki[cecha_max]
    atrybuty: dict[str, Any] = {
        "uw.dryf.status": STATUS_DRYF if psi_max > PROG_DRYFU else STATUS_OK,
        "uw.dryf.n": n,
        "uw.dryf.psi_max": round(psi_max, 4),
        "uw.dryf.cecha_max": cecha_max,
    }
    for cecha, wartosc in wyniki.items():
        atrybuty[f"uw.dryf.psi.{cecha}"] = round(wartosc, 4)
    return atrybuty


def przebieg(
    fabryka_sesji: Callable[[], Any],
    magazyn: Callable[[], Any],
    *,
    teraz: datetime | None = None,
    kontener: str | None = None,
    prefiks: str = PREFIKS_DOMYSLNY,
) -> int:
    """Jeden przebieg: span `dryf.przebieg`, zwraca kod wyjscia (0 albo 1).

    `fabryka_sesji` i `magazyn` to FABRYKI (wolane wewnatrz spanu): brak DATABASE_URL albo
    konta Storage tez konczy sie spanem ERROR, a nie wyjatkiem bez sladu w telemetrii.
    """
    teraz = teraz or datetime.now(timezone.utc)
    kontener = kontener or os.environ.get("KONTENER_MODELI") or KONTENER_DOMYSLNY
    with tracer().start_as_current_span(NAZWA_SPANU, record_exception=False, set_status_on_exception=False) as span:
        try:
            try:
                ref = _wczytaj_referencje(magazyn(), kontener, prefiks)
            except _BladEtapu:
                raise
            except Exception as e:  # noqa: BLE001 - blad budowy magazynu (brak konfiguracji)
                raise _BladEtapu("referencja", e) from e
            try:
                sesje = fabryka_sesji()
            except Exception as e:  # noqa: BLE001 - blad budowy silnika (brak DATABASE_URL)
                raise _BladEtapu("baza", e) from e
            wiersze = _wczytaj_wiersze(sesje, teraz - timedelta(days=OKNO_DNI))
            n = len(wiersze)
            wyniki = None if n < MIN_WIERSZY else _policz_psi(ref, wiersze)
        except Exception as e:  # noqa: BLE001 - kazdy blad = span ERROR + exit 1 (set_status_on_exception=False)
            etap, przyczyna = (e.etap, e.przyczyna) if isinstance(e, _BladEtapu) else ("nieznany", e)
            span.set_attribute("error.type", type(przyczyna).__name__)  # nazwa klasy, nigdy tresc
            span.set_attribute("uw.dryf.etap_bledu", etap)
            span.set_status(Status(StatusCode.ERROR))
            logger.error("Przebieg dryfu nieudany: etap=%s, blad=%s", etap, type(przyczyna).__name__)
            return 1
        atrybuty = _atrybuty_wyniku(n, wyniki)
        for klucz, wartosc in atrybuty.items():
            span.set_attribute(klucz, wartosc)
        logger.info("Dryf: status=%s n=%d psi_max=%s", atrybuty["uw.dryf.status"], n, atrybuty.get("uw.dryf.psi_max"))
        return 0


def _splucz_telemetrie() -> None:
    """Job zyje kilka sekund - BatchSpanProcessor musi wyeksportowac span przed wyjsciem."""
    provider = trace.get_tracer_provider()
    for nazwa in ("force_flush", "shutdown"):
        funkcja = getattr(provider, nazwa, None)
        if funkcja is None:
            continue
        try:
            wynik = funkcja(TIMEOUT_FLUSH_MS) if nazwa == "force_flush" else funkcja()
            if wynik is False:
                logger.warning("Flush telemetrii: %s zwrocil False (span mogl nie dojsc).", nazwa)
        except Exception as e:  # noqa: BLE001 - flush nie zmienia wyniku przebiegu
            logger.warning("Flush telemetrii: %s nieudany (%s).", nazwa, type(e).__name__)


def _fabryka_sesji_z_env() -> Callable[[], Any]:
    from api.baza import utworz_fabryke_sesji, utworz_silnik

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Brak zmiennej srodowiskowej DATABASE_URL.")
    fabryka = utworz_fabryke_sesji(utworz_silnik(database_url))
    return fabryka


def _magazyn_z_env() -> Any:
    from api.magazyn import MagazynBlob

    return MagazynBlob(
        os.environ.get("KONTENER_MODELI") or KONTENER_DOMYSLNY,
        connection_string=os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or None,
        account_url=os.environ.get("AZURE_STORAGE_ACCOUNT_URL") or None,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not telemetria.skonfiguruj_telemetrie(os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")):
        logger.warning("Brak APPLICATIONINSIGHTS_CONNECTION_STRING - span nie zostanie wyeksportowany.")
    try:
        return przebieg(_fabryka_sesji_z_env, _magazyn_z_env)
    finally:
        _splucz_telemetrie()


if __name__ == "__main__":
    sys.exit(main())
