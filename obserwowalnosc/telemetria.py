"""Etap 13: telemetria OpenTelemetry -> Azure Monitor (Application Insights).

Bez APPLICATIONINSIGHTS_CONNECTION_STRING wszystko jest no-op: API OpenTelemetry bez
skonfigurowanego providera zwraca tracer, ktory nic nie eksportuje. Testy i CI nie
potrzebuja wiec zadnej atrapy telemetrii."""

from __future__ import annotations

import logging
import os

from opentelemetry import trace

logger = logging.getLogger(__name__)
NAZWA_TRACERA = "underwriter"
_skonfigurowano = False


def _configure_azure_monitor(**kwargs) -> None:
    # Import leniwy: pakiet ciagnie auto-instrumentacje, niepotrzebna w testach.
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(**kwargs)


def skonfiguruj_telemetrie(connection_string: str | None) -> bool:
    """True = eksport do App Insights wlaczony. Wywolanie drugi raz nic nie robi
    (configure_azure_monitor dwa razy = zdublowane spany)."""
    global _skonfigurowano
    if not connection_string or not connection_string.strip():
        return False
    if not _skonfigurowano:
        # disable_logging=True (RODO): domyslnie dystrybucja wysylalaby tez logi Pythona
        # (WARNING+), a logger.exception z trescia bledu (np. walidacji pydantic z odpowiedzia
        # LLM) niesie NIP/nazwiska - to omijaloby record_exception=False na spanach.
        # Sam kwarg nie wystarcza: azure-monitor-opentelemetry 1.8.11 nadpisuje go wartoscia
        # z env (_default_disable_logging) - 21.10 logi szly do AppTraces. Rozstrzyga env.
        os.environ["OTEL_LOGS_EXPORTER"] = "none"
        # Domyslny RateLimitedSampler(5/s) tuz po starcie odrzucal cale serie spanow (24.10:
        # 0 z 21) - przy minReplicas 0 pierwszy nieudany wniosek po zimnym starcie omijalby
        # alert. Ruch demo jest maly, wiec 100%; setdefault zostawia nadpisanie z env.
        os.environ.setdefault("OTEL_TRACES_SAMPLER", "always_on")
        # Etap 17: maskowanie PII w spanach (takze z auto-instrumentacji) przed eksporterem.
        from obserwowalnosc.pii import MaskowaniePII

        _configure_azure_monitor(
            connection_string=connection_string.strip(),
            disable_logging=True,
            span_processors=[MaskowaniePII()],
        )
        _skonfigurowano = True
        logger.info("Telemetria: eksport do Application Insights wlaczony.")
    return True


def tracer() -> trace.Tracer:
    return trace.get_tracer(NAZWA_TRACERA)
