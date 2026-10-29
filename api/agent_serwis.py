"""Budowa grafu z checkpointerem, uruchomienie nowego przebiegu i wznowienie po
decyzji czlowieka. Model atrapa/gemini wedlug `Ustawienia.model_agenta`.

Zwiazek z tabela `wnioski`: ten modul tylko uruchamia graf i zwraca jego wynik
(`dict` zwrocony przez `graf.invoke`). Zapis do bazy robi wolajacy (`api.trasy` dla
wznowienia - synchronicznie w requescie; `zadanie_w_tle` ponizej dla nowego wniosku -
w BackgroundTasks, bo pierwszy przebieg moze wolac prawdziwy LLM i trwac dlugo).
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy.orm import sessionmaker

from agent.graf import wybierz_graf
from agent.model import ModelAgenta, ModelGemini
from agent.model_azure import ModelAzure
from api.baza import WejscieModelu, Wniosek, dopisz_audyt
from api.magazyn import MagazynDokumentow
from api.ustawienia import Ustawienia
from ewaluacja.atrapa import ModelAtrapa
from obserwowalnosc.model_sledzony import ModelSledzony
from obserwowalnosc.telemetria import tracer
from rag.wyszukiwarka import Wyszukiwarka
from ryzyko.serwowanie import ModelRyzyka

logger = logging.getLogger(__name__)

SCIEZKA_OCZEKIWANE_DOMYSLNA = Path(__file__).resolve().parent.parent / "dane" / "oczekiwane"
PRZYPADKI_ATRAPY = {f"W{n:02d}" for n in range(1, 15)} | {f"Z{n:02d}" for n in range(1, 13)}


def _teraz():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def zbuduj_model(ustawienia: Ustawienia) -> ModelAgenta:
    if ustawienia.model_agenta == "gemini":
        return ModelGemini(model=ustawienia.gemini_model, myslenie=ustawienia.gemini_thinking)
    if ustawienia.model_agenta == "azure":
        return ModelAzure(
            endpoint=ustawienia.azure_openai_endpoint,
            deployment=ustawienia.azure_openai_deployment,
            api_version=ustawienia.azure_openai_api_version,
            reasoning_effort=ustawienia.azure_openai_reasoning,
            docint_endpoint=ustawienia.azure_docint_endpoint,
        )
    return ModelAtrapa(SCIEZKA_OCZEKIWANE_DOMYSLNA)


def zbuduj_checkpointer_postgres(database_url: str):
    """Zwraca (PostgresSaver, ConnectionPool). Pula zyje tyle, co aplikacja - zamyka
    ja wolajacy (`api.main`, lifespan) przy wylaczeniu API."""
    from langgraph.checkpoint.postgres import PostgresSaver

    pula = ConnectionPool(
        database_url,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        # Odpowiednik pool_pre_ping z api/baza.py: sprawdz polaczenie przed wydaniem.
        # Bez tego po restarcie Postgresa pierwszy wniosek dostawal martwe polaczenie
        # z puli (AdminShutdown) i konczyl w BLAD (wykryte testem dymnym na kind 14.10).
        check=ConnectionPool.check_connection,
        open=True,
    )
    return PostgresSaver(pula), pula


def _sumuj_tokeny(log: list[dict]) -> tuple[int, int]:
    tokeny_we = sum(wpis.get("tokeny_we") or 0 for wpis in log)
    tokeny_wy = sum(wpis.get("tokeny_wy") or 0 for wpis in log)
    return tokeny_we, tokeny_wy


def _span_wniosku(nazwa: str, wniosek_id: uuid.UUID, nowy_korzen: bool = True):
    """`uruchom_nowy` (BackgroundTasks): nowy korzen z linkiem do biezacego spanu
    (zadania HTTP) - zadanie 202 konczy sie przed przetwarzaniem, dziecko dluzsze od
    rodzica psuje widok w App Insights.
    `wznow` jest synchroniczny w requescie (`api/trasy.py`) - tam `nowy_korzen=False`:
    zwykle dziecko biezacego spanu, bez linku."""
    attrs = {"uw.wniosek_id": str(wniosek_id)}
    if not nowy_korzen:
        return tracer().start_as_current_span(
            nazwa, attributes=attrs, record_exception=False, set_status_on_exception=False
        )
    biezacy = trace.get_current_span().get_span_context()
    return tracer().start_as_current_span(
        nazwa,
        context=otel_context.Context(),
        links=[trace.Link(biezacy)] if biezacy.is_valid else [],
        attributes=attrs,
        record_exception=False,
        set_status_on_exception=False,
    )


def _decyzja_szkody_z_interruptu(przerwania) -> str | None:
    """`wynik["__interrupt__"][0].value["decyzja"]` (patrz `agent.decyzje_szkody.podsumowanie_szkody`).
    Bez wyjatkow: telemetria nie moze zepsuc przebiegu."""
    try:
        wartosc = przerwania[0].value
    except (IndexError, AttributeError, TypeError):
        return None
    return wartosc.get("decyzja") if isinstance(wartosc, dict) else None


def _opisz_wynik(span, wynik: dict, pierwszy_przebieg: bool = False) -> None:
    """Tylko kody i flagi - zadnej tresci dokumentu (RODO).

    `pierwszy_przebieg=True` (wolane z `uruchom_nowy`): zwierciadlo logiki
    `zadanie_w_tle` ponizej - po pierwszym przebiegu jedyne poprawne zakonczenia bez
    ludzkiej decyzji to interrupt (czeka_na_decyzje) albo klasyfikacja INNY
    (decyzja_koncowa=NIE_DOTYCZY); kazdy inny brak interruptu to BLAD w bazie, wiec
    span ma to widziec tez jako ERROR (alert na `Success == false` inaczej by tego
    rozjazdu nie zlapal). `wznow` (domyslnie) konczy sie normalnie BEZ interruptu i z
    prawdziwa decyzja czlowieka - to nie jest blad."""
    rekomendacja = wynik.get("rekomendacja")
    decyzja = wynik.get("decyzja_koncowa") or (
        rekomendacja.get("decyzja") if isinstance(rekomendacja, dict) else getattr(rekomendacja, "decyzja", None)
    )
    ma_interrupt = "__interrupt__" in wynik
    if not decyzja and ma_interrupt and wynik.get("typ_dokumentu") == "SZKODA":
        # Szkoda nie ma `rekomendacja` ani `decyzja_koncowa` przed decyzja czlowieka - decyzja po
        # regulach (ta, ktora `api/trasy.py` traktuje jako rekomendacje) jest w payloadzie interruptu.
        decyzja = _decyzja_szkody_z_interruptu(wynik["__interrupt__"])
    span.set_attribute("uw.typ_dokumentu", wynik.get("typ_dokumentu") or "")
    span.set_attribute("uw.decyzja", decyzja or "")
    span.set_attribute("uw.status", "czeka_na_decyzje" if ma_interrupt else "zakonczony")

    blad_wezla = bool(wynik.get("blad"))
    brak_decyzji_koncowej = pierwszy_przebieg and not ma_interrupt and decyzja != "NIE_DOTYCZY"
    if blad_wezla or brak_decyzji_koncowej:
        span.set_attribute("uw.blad", True)
        span.set_attribute("error.type", "BladWezlaGrafu" if blad_wezla else "GrafBezDecyzjiKoncowej")
        span.set_status(Status(StatusCode.ERROR))


class SerwisAgenta:
    """Buduje skompilowany graf raz; kolejne wnioski dziela ten sam graf i checkpointer,
    rozroznione przez `thread_id` (= str(id wniosku))."""

    def __init__(
        self,
        model: ModelAgenta,
        checkpointer: BaseCheckpointSaver,
        magazyn: MagazynDokumentow,
        wyszukiwarka: Wyszukiwarka | None = None,
        model_ryzyka: ModelRyzyka | None = None,
        graf_wariant: str = "jeden",
    ):
        # self.model zostaje surowy (uruchom_nowy robi isinstance(self.model, ModelAtrapa)
        # i ustaw_przypadek; 6 testow w test_azure_konfiguracja.py/test_model_vllm.py
        # sprawdzaja typ zwrocony z zbuduj_model) - proxy dostaje tylko graf.
        self.model = model
        self.magazyn = magazyn
        self._checkpointer = checkpointer
        self._wyszukiwarka = wyszukiwarka
        self.model_ryzyka = model_ryzyka
        # Etap 24: wariant orkiestracji (`GRAF_WARIANT`); nieznany -> ValueError z `wybierz_graf` przy starcie.
        self.graf_wariant = graf_wariant
        self.graf = self._zbuduj_graf()

    def _zbuduj_graf(self):
        return wybierz_graf(
            self.graf_wariant,
            model=ModelSledzony.z_modelu(self.model),
            checkpointer=self._checkpointer,
            wyszukiwarka=self._wyszukiwarka,
            model_ryzyka=self.model_ryzyka,
        )

    def ustaw_model_ryzyka(self, model_ryzyka: ModelRyzyka | None) -> None:
        """Etap 15: model ladowany z Blob w lifespan API (po zbudowaniu serwisu) - graf kompiluje
        sie ponownie z nowa zaleznoscia. Wolac przed przyjmowaniem wnioskow."""
        self.model_ryzyka = model_ryzyka
        self.graf = self._zbuduj_graf()

    def uruchom_nowy(
        self, wniosek_id: uuid.UUID, nazwa_pliku: str, blob_nazwa: str, zdjecie_blob: str | None = None
    ) -> dict:
        """Pobiera plik z magazynu do katalogu tymczasowego, puszcza graf od poczatku.
        Etap 23: opcjonalne zdjecie (`zdjecie_blob`) trafia obok dokumentu do pliku tymczasowego
        o tym samym rozszerzeniu co blob i jest podawane grafowi w `zdjecia`.
        Pliki tymczasowe sa usuwane po przebiegu niezaleznie od wyniku."""
        with _span_wniosku("wniosek.uruchom", wniosek_id) as span:
            try:
                config = {"configurable": {"thread_id": str(wniosek_id)}}
                dane_pliku = self.magazyn.pobierz(blob_nazwa)
                sufiks = Path(nazwa_pliku).suffix
                with tempfile.NamedTemporaryFile(suffix=sufiks, delete=False) as tmp:
                    tmp.write(dane_pliku)
                    sciezka_tymczasowa = Path(tmp.name)

                sciezka_zdjecia: Path | None = None
                try:
                    if isinstance(self.model, ModelAtrapa):
                        stem = Path(nazwa_pliku).stem
                        if stem not in PRZYPADKI_ATRAPY:
                            raise ValueError(
                                f"Atrapa zna tylko W01-W14 i Z01-Z12, otrzymano plik '{nazwa_pliku}' (stem '{stem}')."
                            )
                        self.model.ustaw_przypadek(stem)

                    wejscie = {"plik": str(sciezka_tymczasowa), "wywolania_llm": 0, "log": []}
                    if zdjecie_blob is not None:
                        dane_zdjecia = self.magazyn.pobierz(zdjecie_blob)
                        with tempfile.NamedTemporaryFile(suffix=Path(zdjecie_blob).suffix, delete=False) as tmp_zdj:
                            tmp_zdj.write(dane_zdjecia)
                            sciezka_zdjecia = Path(tmp_zdj.name)
                        wejscie["zdjecia"] = [str(sciezka_zdjecia)]
                    wynik = self.graf.invoke(wejscie, config)
                finally:
                    sciezka_tymczasowa.unlink(missing_ok=True)
                    if sciezka_zdjecia is not None:
                        sciezka_zdjecia.unlink(missing_ok=True)
            except Exception as e:
                span.set_attribute("error.type", type(e).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise
            _opisz_wynik(span, wynik, pierwszy_przebieg=True)
            return wynik

    def wznow(self, wniosek_id: uuid.UUID, decyzja: str, kto: str, odejscie: bool | None = None) -> dict:
        """`odejscie`: czy decyzja czlowieka odbiega od rekomendacji (liczy to `api/trasy.py`).
        None = wolajacy nie podal - wtedy atrybutu nie ma (KQL nie liczy braku jako zgodnosci)."""
        with _span_wniosku("wniosek.wznow", wniosek_id, nowy_korzen=False) as span:
            try:
                config = {"configurable": {"thread_id": str(wniosek_id)}}
                wynik = self.graf.invoke(Command(resume={"decyzja": decyzja, "kto": kto}), config)
            except Exception as e:
                span.set_attribute("error.type", type(e).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise
            _opisz_wynik(span, wynik)
            # Metryki efektu (19c): tylko bool i kod decyzji - bez komentarza i bez `kto` (RODO).
            # Po udanym przebiegu, wiec nieudane wznowienie nie liczy sie jako decyzja.
            span.set_attribute("uw.decyzja_czlowieka", decyzja)
            if odejscie is not None:
                span.set_attribute("uw.odejscie_od_rekomendacji", odejscie)
            return wynik


def _zapisz_wejscie_modelu(sesja, wniosek_id: uuid.UUID, wynik: dict) -> None:
    """Etap 15 (SPEC decyzja 8): przy REKOMENDACJI ze statusem ryzyka OK zapisz wejscia modelu.

    Osobna transakcja PO zatwierdzeniu wniosku: blad zapisu (np. brak tabeli przed migracja)
    jest logowany i polykany - nie moze zmienic statusu wniosku ani zgubic rekomendacji.
    Zapisuje tylko liczby i kody (cechy), wersje modelu i wynik.
    """
    ryzyko = wynik.get("ryzyko_szkody")
    if not isinstance(ryzyko, dict) or ryzyko.get("status") != "OK":
        return
    try:
        sesja.add(
            WejscieModelu(
                wniosek_id=wniosek_id,
                wersja_modelu=ryzyko["wersja"],
                cechy=ryzyko["cechy"],
                wynik=ryzyko["wynik"],
                zrodlo="api",
            )
        )
        sesja.commit()
    except Exception:  # noqa: BLE001 - zapis wejsc nie moze popsuc wniosku
        sesja.rollback()
        logger.exception("Nie zapisano wejscia modelu ryzyka (wniosek %s)", wniosek_id)


def zadanie_w_tle(
    serwis: SerwisAgenta,
    fabryka_sesji: sessionmaker,
    wniosek_id: uuid.UUID,
    nazwa_pliku: str,
    blob_nazwa: str,
    zdjecie_blob: str | None = None,
) -> None:
    """Wolane z `BackgroundTasks` po odpowiedzi 202. Zaden wyjatek nie moze zniknac
    cicho - kazda sciezka konczy sie zapisem statusu do bazy (BLAD, CZEKA_NA_DECYZJE
    albo INNY_DOKUMENT)."""
    try:
        wynik = serwis.uruchom_nowy(wniosek_id, nazwa_pliku, blob_nazwa, zdjecie_blob)
    except Exception as e:  # noqa: BLE001 - celowo szerokie, patrz docstring
        logger.exception("Blad przetwarzania wniosku w tle (id=%s)", wniosek_id)
        with fabryka_sesji() as sesja:
            wpis = sesja.get(Wniosek, wniosek_id)
            if wpis is not None:
                wpis.status = "BLAD"
                wpis.zakonczono = _teraz()
                dopisz_audyt(sesja, wniosek_id, "BLAD", kto=None, dane={"blad": str(e)})
                sesja.commit()
        return

    with fabryka_sesji() as sesja:
        wpis = sesja.get(Wniosek, wniosek_id)
        if wpis is None:
            logger.error("Wniosek %s zniknal z bazy w trakcie przetwarzania w tle.", wniosek_id)
            return

        log = wynik.get("log", [])
        tokeny_we, tokeny_wy = _sumuj_tokeny(log)
        wejscia_ryzyka = None

        if "__interrupt__" in wynik:
            podsumowanie = wynik["__interrupt__"][0].value
            wpis.status = "CZEKA_NA_DECYZJE"
            wpis.podsumowanie = podsumowanie
            wpis.log_wezlow = log
            wpis.wywolania_llm = wynik.get("wywolania_llm")
            wpis.tokeny_we = tokeny_we
            wpis.tokeny_wy = tokeny_wy
            dopisz_audyt(sesja, wniosek_id, "REKOMENDACJA", kto=None, dane=podsumowanie)
            wejscia_ryzyka = wynik
        elif wynik.get("decyzja_koncowa") == "NIE_DOTYCZY":
            wpis.status = "INNY_DOKUMENT"
            wpis.decyzja_koncowa = "NIE_DOTYCZY"
            wpis.log_wezlow = log
            wpis.wywolania_llm = wynik.get("wywolania_llm")
            wpis.tokeny_we = tokeny_we
            wpis.tokeny_wy = tokeny_wy
            wpis.zakonczono = _teraz()
        else:
            wpis.status = "BLAD"
            wpis.zakonczono = _teraz()
            dopisz_audyt(
                sesja,
                wniosek_id,
                "BLAD",
                kto=None,
                dane={"blad": "Graf zakonczyl przebieg bez interrupt i bez klasyfikacji INNY."},
            )
        sesja.commit()
        if wejscia_ryzyka is not None:
            _zapisz_wejscie_modelu(sesja, wniosek_id, wejscia_ryzyka)
