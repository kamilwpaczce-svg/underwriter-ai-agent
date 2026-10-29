"""Konfiguracja API wylacznie ze zmiennych srodowiskowych (bez dodatkowych bibliotek)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DOMYSLNY_KONTENER_BLOB = "wnioski"
DOMYSLNY_MODEL_AGENTA = "atrapa"
DOMYSLNE_CORS_ORIGINS = "http://localhost:3000"
MODELE_AGENTA_DOZWOLONE = ("atrapa", "gemini", "azure")
# Etap 24: wariant orkiestracji grafu agenta. Lustro `agent.graf.WARIANTY_GRAFU` (test pilnuje zgodnosci) -
# tu osobna stala, zeby konfiguracja nie importowala LangGraph.
DOMYSLNY_GRAF_WARIANT = "jeden"
GRAF_WARIANTY_DOZWOLONE = ("jeden", "wieloagentowy")


@dataclass
class Ustawienia:
    """Jeden punkt prawdy o konfiguracji; budowana raz w `api.main.utworz_aplikacje`.

    Magazyn blob (Etap 6): dokladnie jedno z dwoch zrodel polaczenia -
    `azure_storage_connection_string` (lokalnie, Azurite) albo `azure_storage_account_url`
    (Azure, Managed Identity - patrz `agent.ocr_azure.zbuduj_poswiadczenie_azure`).
    Walidacja w `__post_init__`, zeby obowiazywala niezaleznie od drogi budowy obiektu
    (`z_env()` albo bezposrednia konstrukcja w testach)."""

    database_url: str
    azure_storage_connection_string: str | None = None
    azure_storage_account_url: str | None = None
    kontener_blob: str = DOMYSLNY_KONTENER_BLOB
    model_agenta: str = DOMYSLNY_MODEL_AGENTA
    gemini_model: str | None = None
    gemini_thinking: str | None = None
    # Etap 5 - Azure. Uwierzytelnienie wylacznie przez Entra ID (az login / Managed Identity),
    # dlatego celowo brak tu jakiegokolwiek pola na klucz/sekret Azure.
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str | None = None
    azure_openai_reasoning: str | None = None
    azure_docint_endpoint: str | None = None
    cors_origins: list[str] = field(default_factory=lambda: [DOMYSLNE_CORS_ORIGINS])
    # Etap 13 - OpenTelemetry -> Application Insights. Brak -> telemetria jest no-op
    # (patrz obserwowalnosc/telemetria.py).
    appinsights_connection_string: str | None = None
    # Etap 24: `GRAF_WARIANT=jeden|wieloagentowy` (domyslnie `jeden` = dotychczasowy graf).
    graf_wariant: str = DOMYSLNY_GRAF_WARIANT

    def __post_init__(self) -> None:
        if bool(self.azure_storage_connection_string) == bool(self.azure_storage_account_url):
            raise RuntimeError(
                "Ustaw dokladnie jedna z AZURE_STORAGE_CONNECTION_STRING (lokalnie, Azurite) "
                "lub AZURE_STORAGE_ACCOUNT_URL (Azure, Managed Identity) - nigdy obie, nigdy zadna."
            )
        if self.graf_wariant not in GRAF_WARIANTY_DOZWOLONE:
            raise RuntimeError(
                f"Niepoprawna wartosc GRAF_WARIANT: '{self.graf_wariant}' "
                f"(dozwolone: {', '.join(GRAF_WARIANTY_DOZWOLONE)})."
            )

    @classmethod
    def z_env(cls) -> "Ustawienia":
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("Brak zmiennej srodowiskowej DATABASE_URL.")

        azure_cs = os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or None
        azure_account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL") or None

        model_agenta = os.environ.get("MODEL_AGENTA", DOMYSLNY_MODEL_AGENTA)
        if model_agenta not in MODELE_AGENTA_DOZWOLONE:
            raise RuntimeError(
                f"Niepoprawna wartosc MODEL_AGENTA: '{model_agenta}' "
                f"(dozwolone: {', '.join(MODELE_AGENTA_DOZWOLONE)})."
            )

        cors_surowe = os.environ.get("CORS_ORIGINS", DOMYSLNE_CORS_ORIGINS)
        cors_origins = [o.strip() for o in cors_surowe.split(",") if o.strip()]

        return cls(
            database_url=database_url,
            azure_storage_connection_string=azure_cs,
            azure_storage_account_url=azure_account_url,
            kontener_blob=os.environ.get("KONTENER_BLOB", DOMYSLNY_KONTENER_BLOB),
            model_agenta=model_agenta,
            gemini_model=os.environ.get("GEMINI_MODEL") or None,
            gemini_thinking=os.environ.get("GEMINI_THINKING") or None,
            azure_openai_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT") or None,
            azure_openai_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT") or None,
            azure_openai_api_version=os.environ.get("AZURE_OPENAI_API_VERSION") or None,
            azure_openai_reasoning=os.environ.get("AZURE_OPENAI_REASONING") or None,
            azure_docint_endpoint=os.environ.get("AZURE_DOCINT_ENDPOINT") or None,
            cors_origins=cors_origins or [DOMYSLNE_CORS_ORIGINS],
            appinsights_connection_string=os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING") or None,
            graf_wariant=os.environ.get("GRAF_WARIANT") or DOMYSLNY_GRAF_WARIANT,
        )
