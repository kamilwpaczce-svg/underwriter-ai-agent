"""Etap 13: proxy ModelAgenta, ktore owija kazda operacje LLM w span `llm.<operacja>`.

Niezalezne od dostawcy (Azure, Gemini, vLLM, atrapa) - nie zmienia agent/model*.py.
Atrybuty wg konwencji OpenTelemetry GenAI. Zadnej tresci promptu ani odpowiedzi
w atrybutach (RODO): tylko model, system i tokeny."""

from __future__ import annotations

from opentelemetry.trace import Status, StatusCode

from agent.model import ModelAgenta
from obserwowalnosc.telemetria import tracer

OPERACJE = ("klasyfikuj", "ekstrahuj", "ocen", "ekstrahuj_szkode", "ocen_pokrycie", "analizuj_zdjecie",
            "decyduj_supervisor")


class ModelSledzony:
    def __init__(self, model: ModelAgenta, nazwa_modelu: str, system: str):
        self._model = model
        self._nazwa_modelu = nazwa_modelu
        self._system = system

    def _wywolaj(self, operacja: str, *args, **kwargs):
        # set_status_on_exception=False: status ERROR ustawiamy recznie nizej (bez komunikatu
        # wyjatku, ktory potrafi zacytowac prompt).
        with tracer().start_as_current_span(
            f"llm.{operacja}", record_exception=False, set_status_on_exception=False
        ) as span:
            span.set_attribute("gen_ai.operation.name", operacja)
            span.set_attribute("gen_ai.system", self._system)
            span.set_attribute("gen_ai.request.model", self._nazwa_modelu)
            try:
                wynik, meta = getattr(self._model, operacja)(*args, **kwargs)
            except Exception as e:
                # Typ bledu tak, tresc nie - komunikat SDK potrafi zacytowac prompt.
                span.set_attribute("error.type", type(e).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise
            if meta.tokeny_we is not None:
                span.set_attribute("gen_ai.usage.input_tokens", meta.tokeny_we)
            if meta.tokeny_wy is not None:
                span.set_attribute("gen_ai.usage.output_tokens", meta.tokeny_wy)
            return wynik, meta

    def klasyfikuj(self, czesci):
        return self._wywolaj("klasyfikuj", czesci)

    def ekstrahuj(self, czesci):
        return self._wywolaj("ekstrahuj", czesci)

    def ocen(self, instrukcje, pola_json, problemy_walidacji):
        return self._wywolaj("ocen", instrukcje, pola_json, problemy_walidacji)

    def ekstrahuj_szkode(self, czesci):
        return self._wywolaj("ekstrahuj_szkode", czesci)

    def ocen_pokrycie(self, pola, wynik_polisy, fragmenty, dodatkowe=None):
        return self._wywolaj("ocen_pokrycie", pola, wynik_polisy, fragmenty, dodatkowe)

    def analizuj_zdjecie(self, obraz, mime_type):
        # Bajty obrazu ida tylko jako argument - _wywolaj nie wpisuje argumentow do atrybutow spanu.
        return self._wywolaj("analizuj_zdjecie", obraz, mime_type)

    def decyduj_supervisor(self, czesci, podsumowanie):
        # Etap 24. Czesci i podsumowanie ida tylko jako argumenty - nie trafiaja do atrybutow spanu.
        return self._wywolaj("decyduj_supervisor", czesci, podsumowanie)

    def __getattr__(self, nazwa):
        # Atrybuty spoza protokolu (np. ModelAzure._tekst_pelny w testach) - bez zmian.
        # Straznik: bez niego copy/pickle przed __init__ wpada w nieskonczona rekurencje.
        if nazwa == "_model":
            raise AttributeError(nazwa)
        return getattr(self._model, nazwa)

    @classmethod
    def z_modelu(cls, model: ModelAgenta) -> "ModelSledzony":
        # Import leniwy: agent.model_vllm ciagnie langchain_openai, niepotrzebny atrapie.
        from agent.model import ModelGemini
        from agent.model_azure import ModelAzure
        from agent.model_vllm import ModelVLLM

        if isinstance(model, ModelVLLM):  # przed ModelAzure - ModelVLLM po nim dziedziczy
            system = "vllm"
        elif isinstance(model, ModelAzure):
            system = "azure.ai.openai"
        elif isinstance(model, ModelGemini):
            system = "gcp.gemini"
        else:
            system = "atrapa"
        return cls(model, nazwa_modelu=getattr(model, "nazwa_modelu", "atrapa"), system=system)
