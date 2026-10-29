"""Etap 19c, zadanie 4: zasiew wnioskow do App Insights pod rola `uw-zasiew`.

Cel: dostarczyc >= 10 wnioskow z decyzjami czlowieka, zeby pieciu metrykom efektu
(`obserwowalnosc/metryki_efektu.kql`) i alertowi odejsc bylo co liczyc. Wzorzec jak
`obserwowalnosc/test_alarmu.py` (rola `uw-zasiew` zamiast `uw-test-alarmu`, ten sam
mechanizm eksportu), ale tu idzie PRAWDZIWA sciezka API: FastAPI `TestClient` z
prawdziwym grafem i trasami z `api/trasy.py` (POST /wnioski -> czekanie na
CZEKA_NA_DECYZJE -> POST /wnioski/{id}/decyzja), wiec spany `wniosek.uruchom` i
`wniosek.wznow` maja dokladnie te atrybuty co w produkcji (uw.decyzja,
uw.odejscie_od_rekomendacji, uw.decyzja_czlowieka).

Co potrzebuje `TestClient` (sprawdzone 26.10 w `tests/test_api.py` i `utworz_aplikacje`):
NIC z docker-compose. Skrypt buduje aplikacje z SQLite w pamieci (`sqlite://`),
`MagazynPamieciowy` i `InMemorySaver` - Postgres i Azurite NIE sa potrzebne. Z zewnatrz
potrzebny jest tylko model (`--llm azure`) oraz connection string App Insights.

Stany:
  --stan zdrowy  10 wnioskow, 2 odejscia z komentarzem (20%)  -> alert odejsc milczy
  --stan chory    8 wnioskow, 6 odejsc z komentarzem (75%)    -> alert odejsc odpala
Lista decyzji czlowieka jest w `PRZYPADKI_ZASIEWU` ponizej. "zgodna" = decyzja rowna
rekomendacji agenta I decyzji silnika regul (tak liczy `api/trasy.py`); "odbiega" = inna
decyzja + komentarz. Przy prawdziwym LLM rekomendacja moze sie rozjechac z lista (wtedy
decyzje sa wybierane w locie, ostrzezenie w wydruku), dlatego na koncu skrypt porownuje
FAKTYCZNY odsetek odejsc z warunkiem alertu i konczy kodem 1, gdy stan nie odpowiada.

--llm azure (domyslnie)  gpt-5-mini na Azure OpenAI: BIEG PLATNY (wnioski ida przez LLM
                         + OCR dla W09/W10-W12). Wymaga `az login` (Entra, bez kluczy).
--llm atrapa             ModelAtrapa: zero kosztow, zero sieci - tylko do sprawdzenia
                         skryptu. UWAGA: wyslana do App Insights zasieje metryki zerowym
                         kosztem LLM i zafalszuje metryke 1; do eksportu uzywaj azure.
--bez-eksportu           nie wysyla spanow (pomija kontrole connection stringa) - bieg
                         lokalny do ogladania tabeli wynikow.

Uzycie (PowerShell, z katalogu repo, po `terraform apply` z infra/terraform):
    az login
    $env:APPLICATIONINSIGHTS_CONNECTION_STRING = terraform -chdir=infra/terraform output -raw connection_string
    $env:AZURE_OPENAI_ENDPOINT = "https://uw-demo-aoai-xx1.openai.azure.com/"
    $env:AZURE_OPENAI_DEPLOYMENT = "gpt-5-mini"
    $env:AZURE_OPENAI_API_VERSION = "2025-04-01-preview"
    $env:AZURE_OPENAI_REASONING = "low"
    $env:AZURE_DOCINT_ENDPOINT = "https://uw-demo-docint-xx1.cognitiveservices.azure.com/"
    .venv\\Scripts\\python.exe obserwowalnosc\\zasiej_wnioski.py --stan zdrowy
    # sprawdz w portalu (Logs workspace uw-demo-logs) metryki z metryki_efektu.kql, potem:
    .venv\\Scripts\\python.exe obserwowalnosc\\zasiej_wnioski.py --stan chory

Kody wyjscia: 0 = bieg poprawny i stan zgodny z oczekiwanym; 1 = blad albo stan niezgodny;
2 = brak APPLICATIONINSIGHTS_CONNECTION_STRING (jak test_alarmu.py) albo brak konfiguracji
Azure OpenAI dla --llm azure.

RODO: skrypt nie wysyla nic poza tym, co wysyla API (kody i flagi); komentarze decyzji sa
ogolnikowe i zostaja w lokalnej bazie w pamieci. Dokumenty to syntetyczne W01-W13
(`dane/wnioski/`); W14 (inny dokument) nie ma decyzji czlowieka, wiec jest pominiety.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from opentelemetry import trace  # noqa: E402

from api.agent_serwis import SCIEZKA_OCZEKIWANE_DOMYSLNA, zbuduj_model  # noqa: E402
from api.magazyn import MagazynPamieciowy  # noqa: E402
from api.main import utworz_aplikacje  # noqa: E402
from api.schematy_api import DECYZJE_WNIOSKU  # noqa: E402
from api.ustawienia import Ustawienia  # noqa: E402
from ewaluacja.atrapa import ModelAtrapa  # noqa: E402

NAZWA_SERWISU_ZASIEWU = "uw-zasiew"
KATALOG_WNIOSKOW = ROOT / "dane" / "wnioski"
UZYTKOWNIK = "zasiew.19c"  # naglowek X-Uzytkownik; nie trafia do telemetrii (RODO)

# Parametry alertu odejsc - musza byc rowne zapytaniu 6 w metryki_efektu.kql (pilnuje test).
MIN_DECYZJI = 5
PROG_ODEJSC_PCT = 50.0

# (plik, odbiega?, decyzja czlowieka gdy odbiega, komentarz). Atrapa daje rekomendacje:
# W01,W02,W11=AKCEPTACJA; W03,W04,W07,W08,W10,W13=SKIEROWANIE; W05,W06=ODMOWA; W09,W12=UZUPELNIENIE.
KOMENTARZ_ODEJSCIA = "Zasiew 19c: decyzja swiadomie odbiega od rekomendacji agenta (test metryk efektu)."

PRZYPADKI_ZASIEWU: dict[str, list[tuple[str, bool, str | None]]] = {
    "zdrowy": [
        ("W01.pdf", False, None),
        ("W02.pdf", False, None),
        ("W03.pdf", True, "ODMOWA"),
        ("W04.pdf", False, None),
        ("W05.pdf", False, None),
        ("W06.pdf", False, None),
        ("W07.pdf", False, None),
        ("W09.jpg", False, None),
        ("W11.eml", True, "UZUPELNIENIE"),
        ("W12.eml", False, None),
    ],
    "chory": [
        ("W01.pdf", True, "ODMOWA"),
        ("W02.pdf", True, "UZUPELNIENIE"),
        ("W03.pdf", True, "AKCEPTACJA"),
        ("W05.pdf", True, "AKCEPTACJA"),
        ("W09.jpg", True, "ODMOWA"),
        ("W12.eml", True, "AKCEPTACJA"),
        ("W07.pdf", False, None),
        ("W13.pdf", False, None),
    ],
}
OCZEKIWANE_ODEJSCIA = {"zdrowy": 2, "chory": 6}


@dataclass
class WynikWniosku:
    plik: str
    wniosek_id: str
    status: str
    rekomendacja: str | None = None
    silnik: str | None = None
    decyzja: str | None = None
    odejscie: bool | None = None
    uwaga: str = ""


def _zmienne_azure_brakujace() -> list[str]:
    return [n for n in ("AZURE_OPENAI_ENDPOINT", "AZURE_DOCINT_ENDPOINT") if not os.environ.get(n)]


def _ustawienia(llm: str, connection_string: str | None) -> Ustawienia:
    """Baza i magazyn zawsze lokalne (SQLite w pamieci); z env tylko konfiguracja modelu."""
    return Ustawienia(
        database_url="sqlite://",
        azure_storage_connection_string="UseDevelopmentStorage=true",
        model_agenta=llm,
        azure_openai_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT") or None,
        azure_openai_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT") or None,
        azure_openai_api_version=os.environ.get("AZURE_OPENAI_API_VERSION") or None,
        azure_openai_reasoning=os.environ.get("AZURE_OPENAI_REASONING") or None,
        azure_docint_endpoint=os.environ.get("AZURE_DOCINT_ENDPOINT") or None,
        appinsights_connection_string=connection_string,
    )


def zbuduj_aplikacje(llm: str, connection_string: str | None):
    ustawienia = _ustawienia(llm, connection_string)
    model = ModelAtrapa(SCIEZKA_OCZEKIWANE_DOMYSLNA) if llm == "atrapa" else zbuduj_model(ustawienia)
    return utworz_aplikacje(
        ustawienia,
        magazyn=MagazynPamieciowy(),
        checkpointer=InMemorySaver(),
        model=model,
    )


def wybierz_decyzje(
    rekomendacja: str | None, silnik: str | None, odbiega: bool, preferowana: str | None
) -> tuple[str, bool, str]:
    """(decyzja, czy_bedzie_odejscie, uwaga). Odejscie wg `api/trasy.py`: decyzja != rekomendacja
    LUB != decyzja silnika. Zgodnosc jest mozliwa tylko gdy rekomendacja == silnik."""
    if not odbiega:
        if rekomendacja is not None and rekomendacja == silnik:
            return rekomendacja, False, ""
        # Rekomendacja LLM rozjechana z silnikiem: zadna decyzja nie bedzie zgodna z obiema.
        return (silnik or rekomendacja or "SKIEROWANIE"), True, "rozjazd rekomendacji i silnika - odejscie wymuszone"
    zajete = {rekomendacja, silnik}
    if preferowana and preferowana not in zajete:
        return preferowana, True, ""
    inna = next(d for d in sorted(DECYZJE_WNIOSKU) if d not in zajete)
    return inna, True, f"lista zakladala {preferowana}, rekomendacja inna - wybrano {inna}"


def _czekaj_na_status(klient: TestClient, wniosek_id: str, timeout: float) -> dict:
    start = time.monotonic()
    while True:
        szczegoly = klient.get(f"/wnioski/{wniosek_id}").json()
        if szczegoly["status"] != "PRZETWARZANIE":
            return szczegoly
        if time.monotonic() - start > timeout:
            return szczegoly
        time.sleep(0.1)


def przetworz_wniosek(
    klient: TestClient, plik: str, odbiega: bool, preferowana: str | None, timeout: float
) -> WynikWniosku:
    sciezka = KATALOG_WNIOSKOW / plik
    odp = klient.post("/wnioski", files={"plik": (plik, sciezka.read_bytes(), "application/octet-stream")})
    if odp.status_code != 202:
        return WynikWniosku(plik, "-", f"HTTP {odp.status_code}", uwaga=odp.text[:80])
    wniosek_id = odp.json()["id"]
    szczegoly = _czekaj_na_status(klient, wniosek_id, timeout)
    wynik = WynikWniosku(plik, wniosek_id, szczegoly["status"])
    if szczegoly["status"] != "CZEKA_NA_DECYZJE":
        wynik.uwaga = "brak decyzji czlowieka (status inny niz CZEKA_NA_DECYZJE)"
        return wynik

    podsumowanie = szczegoly.get("podsumowanie") or {}
    wynik.rekomendacja = (podsumowanie.get("rekomendacja") or {}).get("decyzja")
    wynik.silnik = (podsumowanie.get("decyzja_silnika") or {}).get("decyzja")
    decyzja, _, uwaga = wybierz_decyzje(wynik.rekomendacja, wynik.silnik, odbiega, preferowana)
    cialo = {"decyzja": decyzja}
    if decyzja != wynik.rekomendacja or decyzja != wynik.silnik:
        cialo["komentarz"] = KOMENTARZ_ODEJSCIA
    odp = klient.post(f"/wnioski/{wniosek_id}/decyzja", json=cialo, headers={"X-Uzytkownik": UZYTKOWNIK})
    wynik.decyzja = decyzja
    wynik.uwaga = uwaga
    if odp.status_code != 200:
        wynik.status = f"decyzja HTTP {odp.status_code}"
        wynik.uwaga = (uwaga + " " + odp.text[:80]).strip()
        return wynik
    wynik.status = odp.json()["status"]
    # Odejscie z audytu (to samo, co trafilo na span) - nie z naszego wyliczenia.
    audyt = klient.get(f"/wnioski/{wniosek_id}/audyt").json()
    zdarzenie = next((z for z in audyt if z["zdarzenie"] == "DECYZJA"), None)
    if zdarzenie is not None:
        wynik.odejscie = bool(zdarzenie["dane"].get("odejscie_od_rekomendacji"))
    return wynik


def zasiej(klient: TestClient, stan: str, timeout: float = 300.0) -> list[WynikWniosku]:
    wyniki = []
    for plik, odbiega, preferowana in PRZYPADKI_ZASIEWU[stan]:
        wynik = przetworz_wniosek(klient, plik, odbiega, preferowana, timeout)
        wyniki.append(wynik)
        print(
            f"{wynik.plik:9} rek={wynik.rekomendacja or '-':13} silnik={wynik.silnik or '-':13} "
            f"czlowiek={wynik.decyzja or '-':13} odejscie={wynik.odejscie!s:5} {wynik.status} "
            f"id={wynik.wniosek_id} {wynik.uwaga}".rstrip()
        )
    return wyniki


def podsumuj(wyniki: list[WynikWniosku], stan: str) -> tuple[int, int, float, bool, bool]:
    """(decyzje, odejscia, odsetek %, czy_alert_odpali, czy_stan_zgodny). Warunek alertu jak w
    zapytaniu 6: decyzje >= MIN_DECYZJI i odsetek > PROG_ODEJSC_PCT."""
    z_odejsciem = [w for w in wyniki if w.odejscie is not None]
    decyzje = len(z_odejsciem)
    odejscia = sum(1 for w in z_odejsciem if w.odejscie)
    odsetek = round(100.0 * odejscia / decyzje, 1) if decyzje else 0.0
    alert = decyzje >= MIN_DECYZJI and odsetek > PROG_ODEJSC_PCT
    zgodny = alert == (stan == "chory") and decyzje >= MIN_DECYZJI
    return decyzje, odejscia, odsetek, alert, zgodny


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Etap 19c: zasiew wnioskow (rola uw-zasiew) do metryk efektu.")
    parser.add_argument("--stan", choices=["zdrowy", "chory"], required=True)
    parser.add_argument("--llm", choices=["azure", "atrapa"], default="azure")
    parser.add_argument("--bez-eksportu", action="store_true", help="nie wysylaj spanow do App Insights")
    parser.add_argument("--timeout", type=float, default=300.0, help="limit czekania na jeden wniosek [s]")
    args = parser.parse_args(argv)

    connection_string = None
    if not args.bez_eksportu:
        connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if not connection_string or not connection_string.strip():
            print(
                "Brak APPLICATIONINSIGHTS_CONNECTION_STRING w srodowisku - nie mam gdzie wyslac spanow "
                "(albo uzyj --bez-eksportu).",
                file=sys.stderr,
            )
            return 2
    if args.llm == "azure":
        brakujace = _zmienne_azure_brakujace()
        if brakujace:
            print(f"Brak zmiennych srodowiskowych dla --llm azure: {', '.join(brakujace)}", file=sys.stderr)
            return 2
        print("UWAGA: bieg platny - wnioski ida przez gpt-5-mini (Azure OpenAI) i OCR.", file=sys.stderr)
    elif connection_string:
        print(
            "UWAGA: --llm atrapa z eksportem do App Insights zafalszuje metryke kosztu (tokeny = 0).",
            file=sys.stderr,
        )

    # Przed konfiguracja telemetrii (robi to utworz_aplikacje): rola chmurowa uw-zasiew.
    os.environ["OTEL_SERVICE_NAME"] = NAZWA_SERWISU_ZASIEWU

    try:
        aplikacja = zbuduj_aplikacje(args.llm, connection_string)
        with TestClient(aplikacja) as klient:
            wyniki = zasiej(klient, args.stan, args.timeout)
    except Exception as e:  # noqa: BLE001 - CLI: kazdy blad ma dac czytelny komunikat i kod 1
        print(f"Nieoczekiwany blad ({type(e).__name__}): {e}", file=sys.stderr)
        _splukaj()
        return 1

    _splukaj()
    decyzje, odejscia, odsetek, alert, zgodny = podsumuj(wyniki, args.stan)
    print(
        f"\nstan={args.stan} wnioskow={len(wyniki)} decyzji={decyzje} odejscia={odejscia} "
        f"odsetek={odsetek}% (min {MIN_DECYZJI} decyzji, prog >{PROG_ODEJSC_PCT}%) "
        f"-> alert odejsc {'ODPALI' if alert else 'milczy'}; cel: {OCZEKIWANE_ODEJSCIA[args.stan]} odejsc"
    )
    if not zgodny:
        print(f"Stan '{args.stan}' NIE odpowiada oczekiwanemu - sprawdz uwagi powyzej.", file=sys.stderr)
        return 1
    return 0


def _splukaj() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()


if __name__ == "__main__":
    sys.exit(main())
