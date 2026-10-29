"""Etap 13, zadanie 7: CLI testu alertu awarii w obu stanach (zdrowy/chory).

Przepuszcza jeden wniosek przez graf z atrapa ModelAgenta (bez Postgresa i bez
Bloba - wzorzec fikstury `serwis_atrapy` w tests/test_telemetria.py) i eksportuje
spany do Application Insights pod osobna rola chmurowa (`cloud_RoleName =
uw-test-alarmu`), zeby ruch testowy dalo sie odroznic od prawdziwego API w
portalu.

Stan "zdrowy": atrapa W01 (AKCEPTACJA) - graf dochodzi do wezla `zatwierdzenie`
i interrumpuje (czeka na decyzje czlowieka), bez bledu. Drzewo spanow w App
Insights: `wniosek.uruchom -> wezel.* -> llm.*`, zaden bez statusu ERROR.

Stan "chory": atrapa, ktorej `klasyfikuj` zawsze rzuca `TimeoutError` (symulacja
awarii LLM). `agent/wezly.py::_wywolaj_model` probuje dwa razy i - gdy oba razy
dostanie wyjatek - NIE rzuca go dalej, tylko zwraca stan z kluczem "blad"
(tekst: "... (typ bledu: TimeoutError)."); graf routuje do `zatwierdzenie` i
tez interrumpuje. Efekt w telemetrii: dwa spany `llm.klasyfikuj` ze statusem
ERROR i `error.type=TimeoutError` (to one uruchamiaja alert KQL - zapytanie w
infra/terraform/main.tf lapie kazdy span `wniosek.*`/`llm.*` z Success==false,
niezaleznie od statusu spanu nadrzednego). Ten skrypt dodatkowo oznacza span
`wniosek.uruchom` jako ERROR z tym samym `error.type` (patrz `_zakoncz_span`) -
dla czytelnosci w Transaction search, nie dlatego, ze jest to wymagane przez
alert.

Gdyby mimo wszystko jakis wyjatek wyszedl poza `graf.invoke` (np. zmiana w
agent/wezly.py usuwajaca pochlanianie bledow) - skrypt lapie go w `_uruchom`
na spanie `wniosek.uruchom` tak samo, jak `api.agent_serwis.SerwisAgenta`: jesli
to spodziewany `TimeoutError` w stanie "chory", traktuje to jak zamierzony blad
testowy (exit 0); kazdy inny wyjatek propaguje do `main()` i konczy kodem 1.

Uzycie (PowerShell):
    $env:APPLICATIONINSIGHTS_CONNECTION_STRING = "<connection string z Key Vault/portalu>"
    .venv\\Scripts\\python.exe obserwowalnosc\\test_alarmu.py --stan zdrowy
    .venv\\Scripts\\python.exe obserwowalnosc\\test_alarmu.py --stan chory
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.trace import Status, StatusCode  # noqa: E402

from agent.graf import zbuduj_graf  # noqa: E402
from api.agent_serwis import SCIEZKA_OCZEKIWANE_DOMYSLNA  # noqa: E402
from ewaluacja.atrapa import ModelAtrapa  # noqa: E402
from obserwowalnosc.model_sledzony import ModelSledzony  # noqa: E402
from obserwowalnosc.telemetria import skonfiguruj_telemetrie, tracer  # noqa: E402

NAZWA_SERWISU_TESTOWEGO = "uw-test-alarmu"
PLIK_WNIOSEK_ZDROWY = ROOT / "dane" / "wnioski" / "W01.pdf"  # W01 = AKCEPTACJA, bez regul
PRZYPADEK_ZDROWY = "W01"

_WZORZEC_TYP_BLEDU = re.compile(r"typ bledu: (\w+)")


class _ModelAtrapaChora(ModelAtrapa):
    """Jak ModelAtrapa, ale `klasyfikuj` zawsze rzuca TimeoutError - symulacja
    awarii LLM do testu alertu w stanie "chory". Pozostale operacje nie sa
    wolane (graf routuje do `zatwierdzenie` zaraz po nieudanej klasyfikacji)."""

    def klasyfikuj(self, czesci):
        raise TimeoutError("test_alarmu: symulowany limit czasu wywolania klasyfikacji")


def _zbuduj_model(stan: str):
    if stan == "chory":
        return _ModelAtrapaChora(SCIEZKA_OCZEKIWANE_DOMYSLNA)
    model = ModelAtrapa(SCIEZKA_OCZEKIWANE_DOMYSLNA)
    model.ustaw_przypadek(PRZYPADEK_ZDROWY)
    return model


def _zakoncz_span(span, wynik: dict) -> None:
    """Jak `api.agent_serwis._opisz_wynik`, ale `error.type` (gdy jest blad)
    pochodzi z prawdziwego wyjatku modelu, nie ze stalej "BladWezlaGrafu" -
    test alarmu ma pokazac w App Insights prawdziwy typ awarii LLM.
    Zadnej tresci dokumentu/komunikatu bledu w atrybutach (RODO) - tylko kody."""
    span.set_attribute("uw.typ_dokumentu", wynik.get("typ_dokumentu") or "")
    span.set_attribute("uw.status", "czeka_na_decyzje" if "__interrupt__" in wynik else "zakonczony")
    blad = wynik.get("blad")
    if not blad:
        return
    dopasowanie = _WZORZEC_TYP_BLEDU.search(blad)
    span.set_attribute("uw.blad", True)
    span.set_attribute("error.type", dopasowanie.group(1) if dopasowanie else "BladWezlaGrafu")
    span.set_status(Status(StatusCode.ERROR))


def _uruchom(stan: str) -> tuple[str, bool]:
    """Buduje graf z atrapa odpowiednia dla `stan`, puszcza jeden wniosek w
    spanie `wniosek.uruchom`. Zwraca (operation_Id w hex, czy_wynik_byl_bledny)."""
    model = _zbuduj_model(stan)
    graf = zbuduj_graf(ModelSledzony.z_modelu(model), InMemorySaver())
    wniosek_id = uuid.uuid4()
    config = {"configurable": {"thread_id": str(wniosek_id)}}

    with tracer().start_as_current_span("wniosek.uruchom") as span:
        span.set_attribute("uw.wniosek_id", str(wniosek_id))
        operation_id = format(span.get_span_context().trace_id, "032x")
        try:
            wejscie = {"plik": str(PLIK_WNIOSEK_ZDROWY), "wywolania_llm": 0, "log": []}
            wynik = graf.invoke(wejscie, config)
        except Exception as e:
            span.set_attribute("error.type", type(e).__name__)
            span.set_status(Status(StatusCode.ERROR))
            if stan == "chory" and isinstance(e, TimeoutError):
                return operation_id, True
            raise
        _zakoncz_span(span, wynik)
        return operation_id, bool(wynik.get("blad"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Etap 13: test alertu awarii w App Insights - jeden wniosek zdrowy albo chory."
    )
    parser.add_argument("--stan", choices=["zdrowy", "chory"], required=True)
    args = parser.parse_args(argv)

    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string or not connection_string.strip():
        print(
            "Brak APPLICATIONINSIGHTS_CONNECTION_STRING w srodowisku - nie mam gdzie "
            "wyslac spanu testowego.",
            file=sys.stderr,
        )
        return 2

    # Przed konfiguracja: azure-monitor-opentelemetry czyta nazwe uslugi z env przy
    # starcie eksportu - inaczej spany testowe mieszalyby sie z prawdziwym uw-api.
    os.environ["OTEL_SERVICE_NAME"] = NAZWA_SERWISU_TESTOWEGO
    skonfiguruj_telemetrie(connection_string)

    try:
        operation_id, bledny = _uruchom(args.stan)
    except Exception as e:
        print(f"Nieoczekiwany blad ({type(e).__name__}): {e}", file=sys.stderr)
        trace.get_tracer_provider().force_flush()
        return 1

    trace.get_tracer_provider().force_flush()
    print(f"operation_Id={operation_id}")

    if args.stan == "chory" and not bledny:
        print("Stan chory nie wygenerowal bledu w grafie - sprawdz atrape.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
