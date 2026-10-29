"""Etap 13: span `wezel.<nazwa>` wokol kazdego wezla grafu LangGraph."""

from __future__ import annotations

from typing import Callable

from langgraph.errors import GraphBubbleUp
from opentelemetry.trace import Status, StatusCode

from obserwowalnosc.telemetria import tracer


def sledz_wezel(
    nazwa: str, fn: Callable[[dict], dict], agent: str | None = None
) -> Callable[[dict], dict]:
    """`agent` (Etap 24, wariant (c)): nazwa agenta-podgrafu, do ktorego wezel nalezy; trafia do
    atrybutu `uw.agent` spanu `wezel.<nazwa>`. None = bez atrybutu (obecny graf bez zmian)."""

    def owiniety(stan: dict) -> dict:
        # set_status_on_exception=False: inaczej OTel sam oznaczylby ERROR takze
        # interrupt() (GraphInterrupt), ktory jest zwyklym punktem zatrzymania grafu.
        with tracer().start_as_current_span(
            f"wezel.{nazwa}", record_exception=False, set_status_on_exception=False
        ) as span:
            if agent is not None:
                span.set_attribute("uw.agent", agent)
            try:
                return fn(stan)
            except GraphBubbleUp:
                raise
            except Exception as e:
                span.set_attribute("error.type", type(e).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise

    owiniety.__name__ = f"wezel_{nazwa}"
    return owiniety
