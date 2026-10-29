import time
import uuid

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphInterrupt
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from agent.graf import zbuduj_graf
from agent.model import MetadaneWywolania
from agent.schematy import Ekstrakcja, Klasyfikacja, Ocena
from api.agent_serwis import SCIEZKA_OCZEKIWANE_DOMYSLNA, SerwisAgenta, _opisz_wynik
from api.magazyn import MagazynPamieciowy
from api.main import utworz_aplikacje
from api.ustawienia import Ustawienia
from ewaluacja.atrapa import ModelAtrapa
from obserwowalnosc import telemetria
from obserwowalnosc import test_alarmu
from obserwowalnosc.model_sledzony import ModelSledzony
from obserwowalnosc.wezly import sledz_wezel
from tests.test_graf import (
    PLIK_WNIOSEK,
    WYTYCZNE_SCIEZKA,
    AtrapaModel,
    _nowy_config,
    _pola_czyste,
)
from tests.test_graf_szkody import POLA_Z01, AtrapaZeZdjeciem, _ekstrakcja, _ocena_zdjecia, _pokryta

_EKSPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EKSPORTER))
trace.set_tracer_provider(_PROVIDER)  # globalny provider da sie ustawic raz na proces


@pytest.fixture
def spany():
    _EKSPORTER.clear()
    yield _EKSPORTER
    _EKSPORTER.clear()


def test_bez_connection_stringa_telemetria_wylaczona(monkeypatch):
    wywolania = []
    monkeypatch.setattr(telemetria, "_configure_azure_monitor", lambda **kw: wywolania.append(kw))
    assert telemetria.skonfiguruj_telemetrie(None) is False
    assert telemetria.skonfiguruj_telemetrie("   ") is False
    assert wywolania == []


def test_z_connection_stringiem_konfiguruje_raz(monkeypatch):
    wywolania = []
    monkeypatch.setattr(telemetria, "_configure_azure_monitor", lambda **kw: wywolania.append(kw))
    monkeypatch.setattr(telemetria, "_skonfigurowano", False)
    assert telemetria.skonfiguruj_telemetrie("InstrumentationKey=x") is True
    assert telemetria.skonfiguruj_telemetrie("InstrumentationKey=x") is True
    assert len(wywolania) == 1
    assert wywolania[0]["connection_string"] == "InstrumentationKey=x"


def test_konfiguracja_wylacza_logi_pythona_z_powodu_pii(monkeypatch):
    """Logi Pythona (logger.exception z trescia bledu) nie moga isc do App Insights -
    przeglad koncowy Etapu 13, poprawka 2."""
    wywolania = []
    monkeypatch.setattr(telemetria, "_configure_azure_monitor", lambda **kw: wywolania.append(kw))
    monkeypatch.setattr(telemetria, "_skonfigurowano", False)
    telemetria.skonfiguruj_telemetrie("InstrumentationKey=x")
    assert wywolania[0]["disable_logging"] is True



def test_biblioteka_naprawde_wylacza_logi(monkeypatch):
    """azure-monitor-opentelemetry 1.8.11 nadpisuje kwarg disable_logging=True wartoscia
    z env (_default_disable_logging) - logi Pythona szly do AppTraces mimo kwargu
    (21.10, rewizja uw-api--0000020). Sprawdza rozstrzygniecie BIBLIOTEKI, nie tylko kwarg."""
    from azure.monitor.opentelemetry._constants import DISABLE_LOGGING_ARG
    from azure.monitor.opentelemetry._utils.configurations import _get_configurations

    rozstrzygniete = []
    monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
    monkeypatch.setattr(
        telemetria,
        "_configure_azure_monitor",
        lambda **kw: rozstrzygniete.append(_get_configurations(**kw)[DISABLE_LOGGING_ARG]),
    )
    monkeypatch.setattr(telemetria, "_skonfigurowano", False)
    telemetria.skonfiguruj_telemetrie("InstrumentationKey=x")
    assert rozstrzygniete == [True]


def test_sampler_nie_gubi_pierwszych_spanow(monkeypatch):
    """24.10: domyslny RateLimitedSampler(5/s) zaraz po starcie odrzucil 21 z 21 spanow -
    przy minReplicas 0 pierwszy (np. nieudany) wniosek po zimnym starcie nie trafilby do
    App Insights i alert by milczal. Sprawdza rozstrzygniecie BIBLIOTEKI: always_on."""
    from azure.monitor.opentelemetry._constants import SAMPLER_TYPE, SAMPLING_ARG
    from azure.monitor.opentelemetry._utils.configurations import _get_configurations

    rozstrzygniete = []
    monkeypatch.delenv("OTEL_TRACES_SAMPLER", raising=False)
    monkeypatch.delenv("OTEL_TRACES_SAMPLER_ARG", raising=False)
    monkeypatch.setattr(
        telemetria,
        "_configure_azure_monitor",
        lambda **kw: rozstrzygniete.append(
            (lambda k: (k.get(SAMPLER_TYPE), k.get(SAMPLING_ARG)))(_get_configurations(**kw))
        ),
    )
    monkeypatch.setattr(telemetria, "_skonfigurowano", False)
    telemetria.skonfiguruj_telemetrie("InstrumentationKey=x")
    assert rozstrzygniete == [("always_on", 1.0)]


def test_tracer_dziala_bez_konfiguracji():
    with telemetria.tracer().start_as_current_span("cokolwiek") as span:
        span.set_attribute("uw.test", 1)


class _Model:
    def klasyfikuj(self, czesci):
        return "KLASYFIKACJA", MetadaneWywolania(tokeny_we=120, tokeny_wy=7)

    def ekstrahuj(self, czesci):
        raise TimeoutError("limit czasu")


def test_span_llm_ma_tokeny_i_model(spany):
    model = ModelSledzony(_Model(), nazwa_modelu="gpt-5-mini", system="azure.ai.openai")
    wynik, meta = model.klasyfikuj(czesci=None)
    assert wynik == "KLASYFIKACJA" and meta.tokeny_we == 120
    (span,) = spany.get_finished_spans()
    assert span.name == "llm.klasyfikuj"
    assert span.attributes["gen_ai.request.model"] == "gpt-5-mini"
    assert span.attributes["gen_ai.system"] == "azure.ai.openai"
    assert span.attributes["gen_ai.usage.input_tokens"] == 120
    assert span.attributes["gen_ai.usage.output_tokens"] == 7


def test_blad_llm_propaguje_i_span_ma_status_error(spany):
    model = ModelSledzony(_Model(), nazwa_modelu="gpt-5-mini", system="azure.ai.openai")
    with pytest.raises(TimeoutError):
        model.ekstrahuj(czesci=None)
    (span,) = spany.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "TimeoutError"
    # set_status_on_exception=False: opis statusu nie niesie komunikatu wyjatku.
    assert span.status.description is None


def test_z_modelu_rozpoznaje_atrape():
    sledzony = ModelSledzony.z_modelu(_Model())
    assert sledzony._system == "atrapa" and sledzony._nazwa_modelu == "atrapa"


def _rzuc(wyjatek):
    def fn(stan):
        raise wyjatek
    return fn


def test_sledz_wezel_zachowuje_wynik_i_blad(spany):
    owiniety = sledz_wezel("waliduj", lambda stan: {"problemy_walidacji": []})
    assert owiniety({}) == {"problemy_walidacji": []}
    with pytest.raises(ValueError):
        sledz_wezel("ocen", _rzuc(ValueError("x")))({})
    nazwy = [s.name for s in spany.get_finished_spans()]
    assert nazwy == ["wezel.waliduj", "wezel.ocen"]
    assert spany.get_finished_spans()[0].status.status_code == StatusCode.UNSET
    assert spany.get_finished_spans()[1].status.status_code == StatusCode.ERROR


def test_interrupt_nie_jest_bledem(spany):
    with pytest.raises(GraphInterrupt):
        sledz_wezel("zatwierdzenie", _rzuc(GraphInterrupt()))({})
    (span,) = spany.get_finished_spans()
    assert span.status.status_code != StatusCode.ERROR
    assert "error.type" not in span.attributes


def test_przebieg_grafu_spany_zagniezdzone_i_bez_danych_osobowych(spany, tmp_path):
    pola = _pola_czyste()
    model = AtrapaModel(
        klasyfikacje=[Klasyfikacja(typ_dokumentu="WNIOSEK", uzasadnienie="formularz wniosku")],
        ekstrakcje=[Ekstrakcja(pola=pola, podejrzane_instrukcje=False)],
        oceny=[Ocena(decyzja="AKCEPTACJA", reguly=[], uzasadnienia=[])],
    )
    graf = zbuduj_graf(ModelSledzony.z_modelu(model), InMemorySaver(), WYTYCZNE_SCIEZKA)
    with telemetria.tracer().start_as_current_span("wniosek.test"):
        wynik = graf.invoke({"plik": str(PLIK_WNIOSEK), "wywolania_llm": 0, "log": []}, _nowy_config())
    assert "__interrupt__" in wynik

    gotowe = spany.get_finished_spans()
    po_nazwie = {s.name: s for s in gotowe}
    assert {"wezel.wczytaj", "wezel.klasyfikuj", "wezel.ekstrahuj", "wezel.ocen",
            "llm.klasyfikuj", "llm.ekstrahuj", "llm.ocen"} <= set(po_nazwie)
    # Kontekst OTel przechodzi przez wykonawce LangGraph (contextvars): wezel jest
    # dzieckiem spanu wniosku, llm dzieckiem swojego wezla.
    korzen = po_nazwie["wniosek.test"]
    assert po_nazwie["wezel.klasyfikuj"].parent.span_id == korzen.context.span_id
    assert po_nazwie["llm.klasyfikuj"].parent.span_id == po_nazwie["wezel.klasyfikuj"].context.span_id
    assert po_nazwie["wezel.zatwierdzenie"].status.status_code != StatusCode.ERROR

    wartosci = [str(v) for s in gotowe for v in (s.attributes or {}).values()]
    for wrazliwe in (pola.nip, pola.nazwa_firmy, pola.adres.ulica, pola.broker):
        assert not any(wrazliwe in w for w in wartosci), wrazliwe

    # Etap 23: galaz SZKODA ze zdjeciem - te same spany i ta sama asercja RODO, plus lista dozwolonych
    # atrybutow wezla zdjecia (bez bajtow, nazwy pliku, przyczyny, widocznego mienia i oznak).
    plik_zdjecia = tmp_path / "tajna_nazwa_zdjecia.jpg"
    plik_zdjecia.write_bytes(b"\xff\xd8\xffBAJTY_ZDJECIA_XYZ")
    ocena_zdjecia = _ocena_zdjecia(oznaki=["SZYLD_FIRMY_XYZ"], widoczne_mienie=["SZYLD_FIRMY_XYZ"])
    model_szkody = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()], [ocena_zdjecia])
    graf_szkody = zbuduj_graf(ModelSledzony.z_modelu(model_szkody), InMemorySaver(), WYTYCZNE_SCIEZKA)
    with telemetria.tracer().start_as_current_span("szkoda.test"):
        wynik_szkody = graf_szkody.invoke(
            {"plik": str(PLIK_WNIOSEK), "zdjecia": [str(plik_zdjecia)], "wywolania_llm": 0, "log": []},
            _nowy_config(),
        )
    assert "__interrupt__" in wynik_szkody

    gotowe = spany.get_finished_spans()
    po_nazwie = {s.name: s for s in gotowe}
    assert {"wezel.analizuj_zdjecie", "llm.analizuj_zdjecie"} <= set(po_nazwie)
    assert po_nazwie["llm.analizuj_zdjecie"].parent.span_id == po_nazwie["wezel.analizuj_zdjecie"].context.span_id
    assert dict(po_nazwie["wezel.analizuj_zdjecie"].attributes) == {
        "uw.zdjecie.status": "OK",
        "uw.zdjecie.rodzaj": "pozar",
        "uw.zdjecie.zgodnosc": "ZGODNE",
        "uw.zdjecie.dlugotrwalosc_sygnal": False,
        "uw.zdjecie.pewnosc": 0.9,
    }
    wartosci = [str(v) for s in gotowe for v in (s.attributes or {}).values()]
    for wrazliwe in (
        POLA_Z01["przyczyna"], POLA_Z01["okolicznosci"], "tajna_nazwa_zdjecia", "BAJTY_ZDJECIA_XYZ", "SZYLD_FIRMY_XYZ",
        str(tmp_path),
    ):
        assert not any(wrazliwe in w for w in wartosci), wrazliwe


class _MagazynStalyPlik(MagazynPamieciowy):
    """Atrapa magazynu z tests/test_api.py (MagazynPamieciowy): zwraca zawsze
    W01.pdf, bo blob_nazwa w tescie ponizej = wniosek_id wygenerowany dopiero
    w tescie, po zbudowaniu fikstury."""

    def pobierz(self, nazwa_bloba: str) -> bytes:
        return PLIK_WNIOSEK.read_bytes()


@pytest.fixture
def serwis_atrapy():
    model = ModelAtrapa(SCIEZKA_OCZEKIWANE_DOMYSLNA)
    return SerwisAgenta(model, InMemorySaver(), _MagazynStalyPlik())


def test_serwis_otwiera_span_wniosku_jako_nowy_korzen(spany, serwis_atrapy):
    wniosek_id = uuid.uuid4()
    with telemetria.tracer().start_as_current_span("http.post_wnioski") as zadanie:
        serwis_atrapy.uruchom_nowy(wniosek_id, "W01.pdf", f"{wniosek_id}.pdf")
    po_nazwie = {s.name: s for s in spany.get_finished_spans()}
    span = po_nazwie["wniosek.uruchom"]
    assert span.parent is None  # nowy korzen, nie dziecko zadania HTTP
    assert span.links[0].context.span_id == zadanie.get_span_context().span_id
    assert span.attributes["uw.wniosek_id"] == str(wniosek_id)
    assert span.attributes["uw.status"] == "czeka_na_decyzje"
    assert "llm.klasyfikuj" in po_nazwie  # graf dostal ModelSledzony mimo atrapy


# ---------------------------------------------------------------------------
# Runda poprawek 1/5 (review Zadania 3)
# ---------------------------------------------------------------------------


def test_uruchom_nowy_blad_rzuca_i_span_ma_error(spany, serwis_atrapy):
    """Plik spoza W01-W14/Z01-Z12 - atrapa nie ma czym odpowiedziec (jak w
    tests/test_api.py::...nieznany_plik). uruchom_nowy rzuca ValueError (po
    pobraniu pliku z magazynu, przed invoke grafu) - span wniosek.uruchom ma
    dostac status ERROR i error.type, wyjatek ma propagowac."""
    wniosek_id = uuid.uuid4()
    with pytest.raises(ValueError):
        serwis_atrapy.uruchom_nowy(wniosek_id, "nieznany.pdf", f"{wniosek_id}.pdf")
    po_nazwie = {s.name: s for s in spany.get_finished_spans()}
    span = po_nazwie["wniosek.uruchom"]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "ValueError"
    assert span.attributes["uw.wniosek_id"] == str(wniosek_id)


def test_opisz_wynik_pierwszy_przebieg_blad_wezla_jest_error(spany):
    """wynik['blad'] ustawiony przez wezel grafu (np. limit wywolan LLM, podwojny
    blad structured output) - span ma ERROR + error.type czytelnym kodem, bez
    tresci bledu wezla (RODO: komunikat bledu moze cos zacytowac)."""
    with telemetria.tracer().start_as_current_span("test_blad_wezla") as span:
        _opisz_wynik(
            span,
            {"typ_dokumentu": "WNIOSEK", "decyzja_koncowa": None, "blad": "Blad wezla 'ocen' po 2 probach."},
            pierwszy_przebieg=True,
        )
    (zakonczony,) = spany.get_finished_spans()
    assert zakonczony.status.status_code == StatusCode.ERROR
    assert zakonczony.attributes["error.type"] == "BladWezlaGrafu"
    assert zakonczony.attributes["uw.blad"] is True
    # Tresc komunikatu bledu wezla nie ma trafic do atrybutow spanu.
    wartosci = [str(v) for v in zakonczony.attributes.values()]
    assert not any("Blad wezla" in w for w in wartosci)


def test_opisz_wynik_pierwszy_przebieg_bez_interruptu_i_bez_nie_dotyczy_jest_error(spany):
    """Rozjazd span vs baza: zadanie_w_tle traktuje kazdy wynik uruchom_nowy bez
    __interrupt__ i bez decyzja_koncowa == NIE_DOTYCZY jako BLAD w bazie (gl. kod,
    ~linia 227 w api/agent_serwis.py) - span ma to widziec jako ERROR, inaczej
    alert na Success == false tego nie zlapie."""
    with telemetria.tracer().start_as_current_span("test_bez_decyzji") as span:
        _opisz_wynik(span, {"typ_dokumentu": "WNIOSEK", "decyzja_koncowa": None}, pierwszy_przebieg=True)
    (zakonczony,) = spany.get_finished_spans()
    assert zakonczony.status.status_code == StatusCode.ERROR
    assert zakonczony.attributes["error.type"] == "GrafBezDecyzjiKoncowej"
    assert zakonczony.attributes["uw.blad"] is True
    assert zakonczony.attributes["uw.status"] == "zakonczony"


def test_opisz_wynik_wznow_bez_interruptu_i_bez_nie_dotyczy_nie_jest_error(spany):
    """Dla wznow (pierwszy_przebieg=False, domyslne) brak interruptu i prawdziwa
    decyzja czlowieka (nie NIE_DOTYCZY) to normalne, poprawne zakonczenie - nie
    wolno go oznaczac jako ERROR (inaczej kazde zatwierdzenie wniosku zapalaloby
    alert)."""
    with telemetria.tracer().start_as_current_span("test_wznow_ok") as span:
        _opisz_wynik(span, {"typ_dokumentu": "WNIOSEK", "decyzja_koncowa": "AKCEPTACJA"})
    (zakonczony,) = spany.get_finished_spans()
    assert zakonczony.status.status_code != StatusCode.ERROR
    assert "error.type" not in zakonczony.attributes
    assert "uw.blad" not in zakonczony.attributes


def test_serwis_wznow_jest_dzieckiem_zadania_bez_linku(spany, serwis_atrapy):
    """wznow jest wywolywany synchronicznie w requescie (api/trasy.py), nie w
    BackgroundTasks - wniosek.wznow ma byc zwyklym dzieckiem biezacego spanu
    (zadania HTTP), NIE nowym korzeniem z linkiem jak wniosek.uruchom."""
    wniosek_id = uuid.uuid4()
    serwis_atrapy.uruchom_nowy(wniosek_id, "W01.pdf", f"{wniosek_id}.pdf")  # -> interrupt, czeka na decyzje
    spany.clear()

    with telemetria.tracer().start_as_current_span("http.post_decyzja") as zadanie:
        wynik = serwis_atrapy.wznow(wniosek_id, "AKCEPTACJA", "underwriter_testowy")
    assert "__interrupt__" not in wynik

    po_nazwie = {s.name: s for s in spany.get_finished_spans()}
    span = po_nazwie["wniosek.wznow"]
    assert span.parent is not None
    assert span.parent.span_id == zadanie.get_span_context().span_id  # dziecko, nie korzen
    assert span.links == ()  # brak linku - to nie jest BackgroundTasks jak uruchom_nowy
    assert span.attributes["uw.wniosek_id"] == str(wniosek_id)
    assert span.attributes["uw.status"] == "zakonczony"
    assert span.status.status_code != StatusCode.ERROR


# ---------------------------------------------------------------------------
# 19c zad. 1 - atrybuty metryk efektu na spanie wniosek.wznow
# ---------------------------------------------------------------------------


def test_serwis_wznow_bez_odejscia_nie_ustawia_atrybutu_odejscia(spany, serwis_atrapy):
    """Domyslnie odejscie=None (wolajacy nie wie / nie podaje) - atrybut NIE powstaje, zeby
    KQL nie liczyl 'brak danych' jako 'zgodna'. uw.decyzja_czlowieka jest zawsze."""
    wniosek_id = uuid.uuid4()
    serwis_atrapy.uruchom_nowy(wniosek_id, "W01.pdf", f"{wniosek_id}.pdf")
    spany.clear()

    serwis_atrapy.wznow(wniosek_id, "AKCEPTACJA", "underwriter_testowy")

    span = {s.name: s for s in spany.get_finished_spans()}["wniosek.wznow"]
    assert "uw.odejscie_od_rekomendacji" not in span.attributes
    assert span.attributes["uw.decyzja_czlowieka"] == "AKCEPTACJA"


@pytest.mark.parametrize("odejscie", [False, True])
def test_serwis_wznow_ustawia_odejscie_i_decyzje_czlowieka(spany, serwis_atrapy, odejscie):
    wniosek_id = uuid.uuid4()
    serwis_atrapy.uruchom_nowy(wniosek_id, "W01.pdf", f"{wniosek_id}.pdf")
    spany.clear()

    serwis_atrapy.wznow(wniosek_id, "AKCEPTACJA", "underwriter_testowy", odejscie=odejscie)

    span = {s.name: s for s in spany.get_finished_spans()}["wniosek.wznow"]
    assert span.attributes["uw.odejscie_od_rekomendacji"] is odejscie
    assert span.attributes["uw.decyzja_czlowieka"] == "AKCEPTACJA"
    assert span.attributes["uw.wniosek_id"] == str(wniosek_id)


@pytest.fixture
def klient_api(spany):
    ustawienia = _ustawienia_testowe()
    aplikacja = utworz_aplikacje(
        ustawienia,
        magazyn=MagazynPamieciowy(),
        checkpointer=InMemorySaver(),
        model=ModelAtrapa(SCIEZKA_OCZEKIWANE_DOMYSLNA),
    )
    with TestClient(aplikacja) as klient:
        yield klient


def _wniosek_do_decyzji(klient) -> str:
    odp = klient.post("/wnioski", files={"plik": ("W01.pdf", PLIK_WNIOSEK.read_bytes(), "application/pdf")})
    assert odp.status_code == 202
    wniosek_id = odp.json()["id"]
    start = time.monotonic()
    while time.monotonic() - start < 5.0:
        if klient.get(f"/wnioski/{wniosek_id}").json()["status"] == "CZEKA_NA_DECYZJE":
            return wniosek_id
        time.sleep(0.05)
    raise AssertionError("wniosek nie doszedl do CZEKA_NA_DECYZJE")


def _span_wznow(spany_) -> "ReadableSpan":
    (span,) = [s for s in spany_.get_finished_spans() if s.name == "wniosek.wznow"]
    return span


def test_trasa_decyzja_zgodna_ustawia_odejscie_false(klient_api, spany):
    wniosek_id = _wniosek_do_decyzji(klient_api)
    spany.clear()
    odp = klient_api.post(
        f"/wnioski/{wniosek_id}/decyzja", json={"decyzja": "AKCEPTACJA"}, headers={"X-Uzytkownik": "jan.kowalski"}
    )
    assert odp.status_code == 200
    span = _span_wznow(spany)
    assert span.attributes["uw.odejscie_od_rekomendacji"] is False
    assert span.attributes["uw.decyzja_czlowieka"] == "AKCEPTACJA"
    assert span.attributes["uw.wniosek_id"] == wniosek_id


def test_trasa_decyzja_odbiegajaca_z_komentarzem_ustawia_odejscie_true(klient_api, spany):
    wniosek_id = _wniosek_do_decyzji(klient_api)
    spany.clear()
    komentarz = "Dodatkowe ryzyko nieujete w regulach."
    odp = klient_api.post(
        f"/wnioski/{wniosek_id}/decyzja",
        json={"decyzja": "ODMOWA", "komentarz": komentarz},
        headers={"X-Uzytkownik": "jan.kowalski"},
    )
    assert odp.status_code == 200
    span = _span_wznow(spany)
    assert span.attributes["uw.odejscie_od_rekomendacji"] is True
    assert span.attributes["uw.decyzja_czlowieka"] == "ODMOWA"

    # RODO: ani komentarz, ani nazwa uzytkownika nie trafiaja do zadnego spanu.
    wartosci = [str(v) for s in spany.get_finished_spans() for v in (s.attributes or {}).values()]
    assert not any(komentarz in w or "jan.kowalski" in w for w in wartosci)
    # Nowe klucze maja tylko typy bezpieczne: bool albo kod decyzji (krotki, bez spacji).
    assert isinstance(span.attributes["uw.odejscie_od_rekomendacji"], bool)
    assert span.attributes["uw.decyzja_czlowieka"].isupper()


# ---------------------------------------------------------------------------
# Zadanie 4 - podlaczenie w API
# ---------------------------------------------------------------------------


def _ustawienia_testowe(**nadpisania) -> Ustawienia:
    podstawowe = dict(
        database_url="sqlite://",
        azure_storage_connection_string="UseDevelopmentStorage=true",
        model_agenta="atrapa",
    )
    podstawowe.update(nadpisania)
    return Ustawienia(**podstawowe)


def test_ustawienia_czyta_appinsights_connection_string(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setenv("MODEL_AGENTA", "atrapa")
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    assert Ustawienia.z_env().appinsights_connection_string is None

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    assert Ustawienia.z_env().appinsights_connection_string is None

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    assert Ustawienia.z_env().appinsights_connection_string == "InstrumentationKey=abc"


def test_utworz_aplikacje_bez_connection_stringa_nie_konfiguruje_azure_monitor(monkeypatch):
    wywolania = []
    monkeypatch.setattr(telemetria, "_configure_azure_monitor", lambda **kw: wywolania.append(kw))
    monkeypatch.setattr(telemetria, "_skonfigurowano", False)

    aplikacja = utworz_aplikacje(
        _ustawienia_testowe(),
        magazyn=MagazynPamieciowy(),
        checkpointer=InMemorySaver(),
        model=ModelAtrapa(SCIEZKA_OCZEKIWANE_DOMYSLNA),
    )

    assert wywolania == []
    assert aplikacja.state.telemetria is False


def test_zdrowie_telemetria_false_bez_connection_stringa(monkeypatch):
    monkeypatch.setattr(telemetria, "_skonfigurowano", False)
    aplikacja = utworz_aplikacje(
        _ustawienia_testowe(),
        magazyn=MagazynPamieciowy(),
        checkpointer=InMemorySaver(),
        model=ModelAtrapa(SCIEZKA_OCZEKIWANE_DOMYSLNA),
    )
    with TestClient(aplikacja) as klient:
        odp = klient.get("/zdrowie")
    assert odp.status_code == 200
    assert odp.json()["telemetria"] is False


def test_zdrowie_telemetria_true_gdy_skonfigurowana(monkeypatch):
    monkeypatch.setattr(telemetria, "skonfiguruj_telemetrie", lambda connection_string: True)
    aplikacja = utworz_aplikacje(
        _ustawienia_testowe(appinsights_connection_string="InstrumentationKey=abc"),
        magazyn=MagazynPamieciowy(),
        checkpointer=InMemorySaver(),
        model=ModelAtrapa(SCIEZKA_OCZEKIWANE_DOMYSLNA),
    )
    with TestClient(aplikacja) as klient:
        odp = klient.get("/zdrowie")
    assert odp.status_code == 200
    assert odp.json()["telemetria"] is True


# ---------------------------------------------------------------------------
# Zadanie 7 - obserwowalnosc/test_alarmu.py (CLI testu alertu w obu stanach)
# ---------------------------------------------------------------------------


def test_alarmu_brak_connection_stringa_zwraca_kod_2(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    assert test_alarmu.main(["--stan", "zdrowy"]) == 2

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "   ")
    assert test_alarmu.main(["--stan", "chory"]) == 2


def test_alarmu_stan_zdrowy_drzewo_spanow_bez_error(monkeypatch, spany, capsys):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test")
    monkeypatch.setattr(telemetria, "_configure_azure_monitor", lambda **kw: None)
    monkeypatch.setattr(telemetria, "_skonfigurowano", False)

    assert test_alarmu.main(["--stan", "zdrowy"]) == 0

    po_nazwie = {s.name: s for s in spany.get_finished_spans()}
    korzen = po_nazwie["wniosek.uruchom"]
    assert korzen.status.status_code != StatusCode.ERROR
    assert {
        "wezel.wczytaj", "wezel.klasyfikuj", "wezel.ekstrahuj", "wezel.ocen",
        "llm.klasyfikuj", "llm.ekstrahuj", "llm.ocen",
    } <= set(po_nazwie)
    assert all(s.status.status_code != StatusCode.ERROR for s in po_nazwie.values())

    wydrukowane = capsys.readouterr().out.strip()
    operation_id = wydrukowane.removeprefix("operation_Id=")
    assert len(operation_id) == 32
    assert operation_id == format(korzen.context.trace_id, "032x")


def test_alarmu_stan_chory_span_error_timeout(monkeypatch, spany, capsys):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test")
    monkeypatch.setattr(telemetria, "_configure_azure_monitor", lambda **kw: None)
    monkeypatch.setattr(telemetria, "_skonfigurowano", False)

    assert test_alarmu.main(["--stan", "chory"]) == 0

    po_nazwie = {s.name: s for s in spany.get_finished_spans()}
    korzen = po_nazwie["wniosek.uruchom"]
    assert korzen.status.status_code == StatusCode.ERROR
    assert korzen.attributes["error.type"] == "TimeoutError"
    assert po_nazwie["llm.klasyfikuj"].status.status_code == StatusCode.ERROR
    assert po_nazwie["llm.klasyfikuj"].attributes["error.type"] == "TimeoutError"

    wydrukowane = capsys.readouterr().out.strip()
    operation_id = wydrukowane.removeprefix("operation_Id=")
    assert operation_id == format(korzen.context.trace_id, "032x")


def test_sonda_zdrowie_nie_tworzy_spanow_a_inne_trasy_tak(monkeypatch, spany):
    """22.10: AppRequests mialo GET /zdrowie mimo OTEL_PYTHON_FASTAPI_EXCLUDED_URLS - spany
    serwera robi natywna telemetria FastAPI 0.143 (scope 'fastapi'), ktora tej zmiennej nie
    czyta. Sprawdza realne spany: /zdrowie zero, /wnioski jest (kontrola, ze tracing zyje)."""
    monkeypatch.setattr(telemetria, "skonfiguruj_telemetrie", lambda connection_string: True)
    aplikacja = utworz_aplikacje(
        _ustawienia_testowe(),
        magazyn=MagazynPamieciowy(),
        checkpointer=InMemorySaver(),
        model=ModelAtrapa(SCIEZKA_OCZEKIWANE_DOMYSLNA),
    )
    with TestClient(aplikacja) as klient:
        assert klient.get("/zdrowie").status_code == 200
        po_sondzie = [(s.kind, s.name) for s in spany.get_finished_spans()]
        assert klient.get("/wnioski").status_code == 200

    assert po_sondzie == [], f"sonda /zdrowie wygenerowala spany: {po_sondzie}"
    serwerowe = [s for s in spany.get_finished_spans() if s.kind == SpanKind.SERVER]
    assert [s.attributes.get("url.path") for s in serwerowe] == ["/wnioski"]


# ---------------------------------------------------------------------------
# 19c: decyzja szkody na spanie wniosek.uruchom (metryka SKIEROWANIE)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("przypadek, oczekiwana", [("Z01", "POKRYTA"), ("Z05", "ODMOWA")])
def test_uruchom_nowy_szkoda_ustawia_uw_decyzja_z_interruptu(spany, serwis_atrapy, przypadek, oczekiwana):
    """Szkoda nie ma `rekomendacja`/`decyzja_koncowa` w stanie po pierwszym przebiegu -
    decyzja po regulach siedzi tylko w payloadzie interruptu. Bez niej metryka
    SKIEROWANIE (zapytanie 2 w metryki_efektu.kql) nie widzi szkod."""
    wniosek_id = uuid.uuid4()
    wynik = serwis_atrapy.uruchom_nowy(wniosek_id, f"{przypadek}.pdf", f"{wniosek_id}.pdf")
    podsumowanie = wynik["__interrupt__"][0].value
    assert podsumowanie["decyzja"] == oczekiwana  # zalozenie testu: to ta sama decyzja co trasy.py
    span = {s.name: s for s in spany.get_finished_spans()}["wniosek.uruchom"]
    assert span.attributes["uw.typ_dokumentu"] == "SZKODA"
    assert span.attributes["uw.decyzja"] == oczekiwana
    assert span.attributes["uw.status"] == "czeka_na_decyzje"


def test_opisz_wynik_szkoda_skierowanie_z_interruptu(spany):
    class _Int:
        value = {"typ_dokumentu": "SZKODA", "decyzja": "SKIEROWANIE", "decyzja_llm": "POKRYTA"}

    with telemetria.tracer().start_as_current_span("t") as span:
        _opisz_wynik(span, {"typ_dokumentu": "SZKODA", "__interrupt__": [_Int()]}, pierwszy_przebieg=True)
    (zakonczony,) = spany.get_finished_spans()
    assert zakonczony.attributes["uw.decyzja"] == "SKIEROWANIE"  # nie decyzja_llm
    assert zakonczony.status.status_code != StatusCode.ERROR


def test_opisz_wynik_wniosek_z_interruptem_nie_bierze_decyzji_z_payloadu(spany):
    """WNIOSEK: payload nie ma klucza `decyzja` na gorze (jest rekomendacja.decyzja) -
    zachowanie bez zmian."""

    class _Int:
        value = {"typ_dokumentu": "WNIOSEK", "rekomendacja": {"decyzja": "UZUPELNIENIE"}}

    with telemetria.tracer().start_as_current_span("t") as span:
        _opisz_wynik(
            span,
            {"typ_dokumentu": "WNIOSEK", "rekomendacja": {"decyzja": "UZUPELNIENIE"}, "__interrupt__": [_Int()]},
            pierwszy_przebieg=True,
        )
    (zakonczony,) = spany.get_finished_spans()
    assert zakonczony.attributes["uw.decyzja"] == "UZUPELNIENIE"


# ---------------------------------------------------------------------------
# Etap 24, zadanie 3: wariant wieloagentowy - spany supervisora i uw.agent, ta sama asercja RODO
# ---------------------------------------------------------------------------


def test_graf_wieloagentowy_spany_i_brak_danych_osobowych_w_atrybutach(spany):
    import json
    from pathlib import Path

    from agent.graf_wieloagentowy import zbuduj_graf_wieloagentowy

    root = Path(__file__).resolve().parent.parent
    model = ModelAtrapa(root / "dane" / "oczekiwane")
    model.ustaw_przypadek("Z01")
    (plik,) = (root / "dane" / "szkody").glob("Z01.*")
    graf = zbuduj_graf_wieloagentowy(ModelSledzony.z_modelu(model), InMemorySaver(), WYTYCZNE_SCIEZKA)
    with telemetria.tracer().start_as_current_span("szkoda.wieloagentowa"):
        wynik = graf.invoke({"plik": str(plik), "wywolania_llm": 0, "log": []}, _nowy_config())
    assert "__interrupt__" in wynik

    gotowe = spany.get_finished_spans()
    po_nazwie = {}
    for s in gotowe:
        po_nazwie.setdefault(s.name, []).append(s)
    assert {"wezel.supervisor", "llm.decyduj_supervisor", "wezel.ekstrahuj_szkode", "wezel.ocen_pokrycie"} <= set(po_nazwie)
    assert not [n for n in po_nazwie if n.startswith("agent.")]  # wariant (c): bez spanu agent.<nazwa>
    assert po_nazwie["wezel.ekstrahuj_szkode"][0].attributes["uw.agent"] == "agent_szkod"
    assert po_nazwie["wezel.ocen_pokrycie"][0].attributes["uw.agent"] == "agent_owu"
    for s in po_nazwie["wezel.supervisor"]:
        assert {k for k in s.attributes} == {
            "uw.supervisor.krok", "uw.supervisor.wybor", "uw.supervisor.korekta", "uw.supervisor.llm"
        }

    pola = json.loads((root / "dane" / "szkody" / "oczekiwane" / "Z01.json").read_text(encoding="utf-8"))["pola"]
    wartosci = [str(v) for s in gotowe for v in (s.attributes or {}).values()]
    for wrazliwe in (pola["nip"], pola["ubezpieczony"], pola["miejsce"]["ulica"], pola["przyczyna"], pola["okolicznosci"],
                     pola["nr_polisy"], "atrapa: z dane/oczekiwane", "atrapa: lustro"):  # ostatnie dwa: uzasadnienia supervisora
        assert not any(wrazliwe in w for w in wartosci), wrazliwe
