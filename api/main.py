"""Punkt wejscia FastAPI: sklejenie ustawien, bazy, magazynu i agenta w jedna aplikacje.

`utworz_aplikacje` przyjmuje opcjonalne nadpisania (`magazyn`, `checkpointer`, `model`) -
to na nich stoi `tests/test_api.py` (atrapa/pamieciowy/InMemorySaver, bez Dockera).
Bez nadpisan (wywolanie produkcyjne, `uvicorn api.main:app`) buduje prawdziwy
`MagazynBlob` (Azurite/Azure) i `PostgresSaver` na puli polaczen z `DATABASE_URL`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver

from agent.model import ModelAgenta
from api.agent_serwis import SerwisAgenta, zbuduj_checkpointer_postgres, zbuduj_model
from api.baza import Baza, napraw_wiszace_wnioski, utworz_fabryke_sesji, utworz_silnik
from api.magazyn import MagazynBlob, MagazynDokumentow
from api.trasy import router
from api.ustawienia import Ustawienia
from obserwowalnosc import telemetria
from rag.azure_search import zbuduj_wyszukiwarke
from rag.wyszukiwarka import Wyszukiwarka
from ryzyko.serwowanie import ModelRyzyka

logging.basicConfig(level=logging.INFO)
# Azure SDK na INFO loguje kazde zadanie HTTP z naglowkami (Blob przy kazdej sondzie
# /zdrowie co 15 s) - zaglusza logi aplikacji i nabija Log Analytics.
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _sonda_zdrowia(scope) -> bool:
    """Sonda ACA co 15 s: bez spanow, metryk i logow FastAPI (AppRequests/AppDependencies)."""
    return scope.get("path", "").rstrip("/") == "/zdrowie"


def utworz_aplikacje(
    ustawienia: Ustawienia | None = None,
    *,
    magazyn: MagazynDokumentow | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    model: ModelAgenta | None = None,
    wyszukiwarka: Wyszukiwarka | None = None,
) -> FastAPI:
    ustawienia = ustawienia or Ustawienia.z_env()

    # Etap 13: provider OTel (azure-monitor-opentelemetry) musi istniec przed pierwszym
    # zadaniem. Spany tras robi natywna telemetria FastAPI - patrz telemetry= nizej.
    telemetria_wlaczona = telemetria.skonfiguruj_telemetrie(ustawienia.appinsights_connection_string)

    silnik = utworz_silnik(ustawienia.database_url)
    fabryka_sesji = utworz_fabryke_sesji(silnik)
    # SQLite (testy/demo lokalne) - schemat tworzony tu od razu, bez Alembica.
    # Postgres (prod/integracja) - schemat tworzy wylacznie `alembic upgrade head`.
    if silnik.dialect.name == "sqlite":
        Baza.metadata.create_all(silnik)

    magazyn = magazyn or MagazynBlob(
        ustawienia.kontener_blob,
        connection_string=ustawienia.azure_storage_connection_string,
        account_url=ustawienia.azure_storage_account_url,
    )
    model = model or zbuduj_model(ustawienia)

    pula_polaczen = None
    if checkpointer is None:
        checkpointer, pula_polaczen = zbuduj_checkpointer_postgres(ustawienia.database_url)

    # Etap 10: WYSZUKIWARKA / AZURE_SEARCH_ENDPOINT z env; zla konfiguracja to
    # BrakKonfiguracjiWyszukiwarki (RuntimeError) - glosno, jak brak DATABASE_URL.
    wyszukiwarka = wyszukiwarka or zbuduj_wyszukiwarke()
    serwis = SerwisAgenta(model, checkpointer, magazyn, wyszukiwarka, graf_wariant=ustawienia.graf_wariant)

    @asynccontextmanager
    async def lifespan(aplikacja: FastAPI):
        if hasattr(checkpointer, "setup"):
            checkpointer.setup()
        if hasattr(magazyn, "utworz_kontener_jesli_brak"):
            magazyn.utworz_kontener_jesli_brak()

        # Etap 15: model ryzyka ladowany RAZ przy starcie; kazdy blad -> None (z_bloba loguje),
        # API dziala dalej, a wezel grafu zwraca MODEL_NIEDOSTEPNY.
        model_ryzyka = ModelRyzyka.z_bloba(magazyn)
        serwis.ustaw_model_ryzyka(model_ryzyka)
        aplikacja.state.model_ryzyka = model_ryzyka
        if model_ryzyka is not None:
            logger.info("Zaladowano model ryzyka szkody, wersja %s.", model_ryzyka.wersja)

        liczba_naprawionych = napraw_wiszace_wnioski(fabryka_sesji)
        if liczba_naprawionych:
            logger.warning(
                "Oznaczono %d wniosek(ow) jako BLAD po restarcie (byly w PRZETWARZANIE).",
                liczba_naprawionych,
            )
        yield
        if pula_polaczen is not None:
            pula_polaczen.close()

    aplikacja = FastAPI(
        title="Underwriter Agent Demo - API (Etap 3)",
        lifespan=lifespan,
        # Spany serwera robi NATYWNA telemetria FastAPI (>=0.143, scope "fastapi"), nie
        # opentelemetry-instrumentation-fastapi: `from fastapi import FastAPI` na gorze modulu
        # wiaze klase przed configure_azure_monitor, wiec podmiana na _InstrumentedFastAPI
        # nas nie dotyczy, a OTEL_PYTHON_FASTAPI_EXCLUDED_URLS jest ignorowany (22.10).
        telemetry={"exclude": _sonda_zdrowia},
    )
    aplikacja.add_middleware(
        CORSMiddleware,
        allow_origins=ustawienia.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    aplikacja.state.ustawienia = ustawienia
    aplikacja.state.fabryka_sesji = fabryka_sesji
    aplikacja.state.magazyn = magazyn
    aplikacja.state.serwis = serwis
    aplikacja.state.telemetria = telemetria_wlaczona
    aplikacja.state.model_ryzyka = None  # ustawiane w lifespan

    aplikacja.include_router(router)
    return aplikacja


def _zbuduj_domyslna_aplikacje() -> FastAPI | None:
    """Wywolywane raz przy imporcie modulu (`uvicorn api.main:app`). Import tego
    modulu nie moze wywalic sie brakiem zmiennych srodowiskowych - testy importuja
    stad tylko `utworz_aplikacje` i budowuja aplikacje same, z wlasnymi nadpisaniami."""
    try:
        return utworz_aplikacje()
    except RuntimeError as e:
        logger.warning("Nie zbudowano domyslnej aplikacji API przy imporcie: %s", e)
        return None


app = _zbuduj_domyslna_aplikacje()
