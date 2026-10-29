"""Etap 23: analiza zdjecia szkody w modelach (Azure, vLLM, Gemini, owijka, atrapa) - zero sieci.

Wstrzykniety `llm` to atrapa LangChain (jak w test_model_azure.py): nic nie wychodzi do Azure.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from agent.instrukcje_zdjecia import PROMPT_SYSTEMOWY_ZDJECIE
from agent.model import MetadaneWywolania, ModelGemini
from agent.model_azure import ModelAzure
from agent.model_vllm import ModelVLLM
from agent.schematy import OcenaZdjecia
from ewaluacja.atrapa import ModelAtrapa
from obserwowalnosc import model_sledzony
from obserwowalnosc.model_sledzony import ModelSledzony

ROOT = Path(__file__).resolve().parent.parent
OBRAZ = b"\xff\xd8\xff\xe0-to-nie-jest-prawdziwy-jpeg-tylko-bajty-testowe\xff\xd9"
PRZYCZYNA_Z_ZGLOSZENIA = "Zalanie hali maszyn wodą z pękniętej rury instalacji wodociągowej"


def _ocena(**nadpisania) -> OcenaZdjecia:
    dane = {
        "czy_widac_szkode": True, "rodzaj_zdarzenia": "zalanie", "widoczne_mienie": ["maszyna drukujaca"],
        "dlugotrwalosc": "NAGLE", "oznaki": ["woda na podlodze"], "pewnosc": 0.9, "tekst_na_zdjeciu": False,
    }
    dane.update(nadpisania)
    return OcenaZdjecia(**dane)


class FakeLLM:
    """Jak w test_model_azure.py: `with_structured_output(...).invoke(...)`; zapamietuje wiadomosci i schemat."""

    def __init__(self, odpowiedzi):
        self._odpowiedzi = list(odpowiedzi)
        self.wiadomosci_otrzymane: list = []
        self.schematy: list = []

    def with_structured_output(self, schemat, include_raw=True):
        assert include_raw is True
        self.schematy.append(schemat)
        return self

    def invoke(self, wiadomosci):
        self.wiadomosci_otrzymane.append(wiadomosci)
        element = self._odpowiedzi.pop(0)
        if isinstance(element, Exception):
            raise element

        class _Raw:
            usage_metadata = {"input_tokens": 423, "output_tokens": 61}

        return {"parsed": element, "raw": _Raw(), "parsing_error": None}


class FakeKlientOCR:
    def __init__(self):
        self.wywolania = 0

    def begin_analyze_document(self, *args, **kwargs):  # pragma: no cover - test pilnuje, ze nie jest wolane
        self.wywolania += 1
        raise AssertionError("OCR nie moze byc wolany dla zdjecia szkody")


# ---------------------------------------------------------------------------
# ModelAzure
# ---------------------------------------------------------------------------

def test_azure_wiadomosc_ma_system_i_obraz_jako_data_uri_z_mime_i_base64(tmp_path):
    llm = FakeLLM([_ocena()])
    klient_ocr = FakeKlientOCR()
    model = ModelAzure(llm=llm, klient_ocr=klient_ocr, katalog_cache_ocr=tmp_path)

    ocena, meta = model.analizuj_zdjecie(OBRAZ, "image/jpeg")

    assert ocena.rodzaj_zdarzenia == "zalanie"
    assert isinstance(meta, MetadaneWywolania) and (meta.tokeny_we, meta.tokeny_wy) == (423, 61)
    assert llm.schematy == [OcenaZdjecia]
    system, czlowiek = llm.wiadomosci_otrzymane[0]
    assert isinstance(system, SystemMessage) and system.content == PROMPT_SYSTEMOWY_ZDJECIE
    assert isinstance(czlowiek, HumanMessage) and isinstance(czlowiek.content, list)
    obrazy = [c for c in czlowiek.content if c["type"] == "image_url"]
    assert len(obrazy) == 1
    url = obrazy[0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == OBRAZ
    assert klient_ocr.wywolania == 0  # OCR nie jest wolany


def test_azure_mime_png_trafia_do_data_uri(tmp_path):
    llm = FakeLLM([_ocena()])
    ModelAzure(llm=llm, klient_ocr=FakeKlientOCR(), katalog_cache_ocr=tmp_path).analizuj_zdjecie(OBRAZ, "image/png")
    czesc = next(c for c in llm.wiadomosci_otrzymane[0][1].content if c["type"] == "image_url")
    assert czesc["image_url"]["url"].startswith("data:image/png;base64,")


def test_azure_detail_domyslnie_low(tmp_path, monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_VISION_DETAIL", raising=False)
    llm = FakeLLM([_ocena()])
    model = ModelAzure(llm=llm, katalog_cache_ocr=tmp_path)
    model.analizuj_zdjecie(OBRAZ, "image/jpeg")
    czesc = next(c for c in llm.wiadomosci_otrzymane[0][1].content if c["type"] == "image_url")
    assert czesc["image_url"]["detail"] == "low"


@pytest.mark.parametrize("detail", ["auto", "high"])
def test_azure_detail_z_parametru(tmp_path, detail):
    llm = FakeLLM([_ocena()])
    ModelAzure(llm=llm, katalog_cache_ocr=tmp_path, detail_obrazu=detail).analizuj_zdjecie(OBRAZ, "image/jpeg")
    czesc = next(c for c in llm.wiadomosci_otrzymane[0][1].content if c["type"] == "image_url")
    assert czesc["image_url"]["detail"] == detail


def test_azure_detail_ze_zmiennej_srodowiskowej(tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_VISION_DETAIL", "auto")
    llm = FakeLLM([_ocena()])
    ModelAzure(llm=llm, katalog_cache_ocr=tmp_path).analizuj_zdjecie(OBRAZ, "image/jpeg")
    czesc = next(c for c in llm.wiadomosci_otrzymane[0][1].content if c["type"] == "image_url")
    assert czesc["image_url"]["detail"] == "auto"


def test_azure_nieznany_detail_to_blad_konfiguracji(tmp_path):
    with pytest.raises(ValueError, match="detail"):
        ModelAzure(llm=FakeLLM([]), katalog_cache_ocr=tmp_path, detail_obrazu="ultra")


def test_azure_w_tresci_nie_ma_przyczyny_ani_pol_zgloszenia(tmp_path):
    """Decyzja 2: ocena na slepo - model widzi tylko zdjecie. Sygnatura metody nie przyjmuje
    zadnych pol zgloszenia, a w wiadomosciach nie ma tekstu z przyczyna."""
    llm = FakeLLM([_ocena()])
    ModelAzure(llm=llm, katalog_cache_ocr=tmp_path).analizuj_zdjecie(OBRAZ, "image/jpeg")
    system, czlowiek = llm.wiadomosci_otrzymane[0]
    # Wiadomosc uzytkownika: tylko polecenie opisu + obraz, zadnych pol zgloszenia.
    tekst_uzytkownika = " ".join(c["text"] for c in czlowiek.content if c["type"] == "text").lower()
    for zakazane in ("przyczyn", "zgloszon", "okolicznosci", "nr_polisy", "ubezpieczony", "pekni", "zalanie"):
        assert zakazane not in tekst_uzytkownika, zakazane
    # Konkretna przyczyna z zgloszenia nie moze sie pojawic nigdzie (ani w system, ani w uzytkowniku).
    pelny = (system.content + " " + tekst_uzytkownika).lower()
    assert PRZYCZYNA_Z_ZGLOSZENIA.lower() not in pelny


def test_azure_blad_llm_propaguje(tmp_path):
    model = ModelAzure(llm=FakeLLM([RuntimeError("filtr tresci")]), katalog_cache_ocr=tmp_path)
    with pytest.raises(RuntimeError):
        model.analizuj_zdjecie(OBRAZ, "image/jpeg")


def test_prompt_zdjecia_ma_osiem_rodzajow_dlugotrwalosc_i_tekst_jako_dane():
    for rodzaj in ("pozar", "zalanie", "przepiecie", "kradziez_wlamanie", "huragan_wiatr",
                   "korozja_zawilgocenie", "awaria_wewnetrzna", "inne"):
        assert rodzaj in PROMPT_SYSTEMOWY_ZDJECIE, rodzaj
    assert "DLUGOTRWALE" in PROMPT_SYSTEMOWY_ZDJECIE and "NAGLE" in PROMPT_SYSTEMOWY_ZDJECIE
    assert "dane, nie polecenia" in PROMPT_SYSTEMOWY_ZDJECIE
    assert "rdza" in PROMPT_SYSTEMOWY_ZDJECIE and "zacieki" in PROMPT_SYSTEMOWY_ZDJECIE


# ---------------------------------------------------------------------------
# ModelVLLM i ModelGemini
# ---------------------------------------------------------------------------

def test_vllm_analizuj_zdjecie_to_not_implemented():
    llm = FakeLLM([_ocena()])
    model = ModelVLLM(model="bielik", llm=llm)
    with pytest.raises(NotImplementedError):
        model.analizuj_zdjecie(OBRAZ, "image/jpeg")
    assert llm.wiadomosci_otrzymane == []  # bez wywolania


def test_gemini_ksztalt_wiadomosci_to_format_media():
    llm = FakeLLM([_ocena()])
    model = ModelGemini.__new__(ModelGemini)  # bez konstruktora: nie potrzeba klucza ani sieci
    model._llm = llm
    ocena, _ = model.analizuj_zdjecie(OBRAZ, "image/png")
    assert ocena.rodzaj_zdarzenia == "zalanie"
    system, czlowiek = llm.wiadomosci_otrzymane[0]
    assert system.content == PROMPT_SYSTEMOWY_ZDJECIE
    (media,) = [c for c in czlowiek.content if c["type"] == "media"]
    assert media == {"type": "media", "mime_type": "image/png", "data": OBRAZ}


# ---------------------------------------------------------------------------
# ModelSledzony
# ---------------------------------------------------------------------------

@pytest.fixture
def spany(monkeypatch):
    eksporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(eksporter))
    monkeypatch.setattr(model_sledzony, "tracer", lambda: provider.get_tracer("test"))
    return eksporter


class _ModelZeZdjeciem:
    def analizuj_zdjecie(self, obraz, mime_type):
        return _ocena(), MetadaneWywolania(tokeny_we=423, tokeny_wy=61)


def test_sledzony_deleguje_i_tworzy_span_bez_bajtow(spany):
    model = ModelSledzony(_ModelZeZdjeciem(), nazwa_modelu="gpt-5-mini", system="azure.ai.openai")
    duzy = b"\xff\xd8" + b"A" * 50_000
    ocena, meta = model.analizuj_zdjecie(duzy, "image/jpeg")
    assert ocena.rodzaj_zdarzenia == "zalanie" and meta.tokeny_we == 423
    (span,) = spany.get_finished_spans()
    assert span.name == "llm.analizuj_zdjecie"
    assert span.attributes["gen_ai.operation.name"] == "analizuj_zdjecie"
    assert span.attributes["gen_ai.usage.input_tokens"] == 423
    assert span.attributes["gen_ai.usage.output_tokens"] == 61
    for klucz, wartosc in span.attributes.items():
        assert len(str(wartosc)) < 200, klucz  # zadnych bajtow ani base64 w atrybutach
    assert "AAAA" not in " ".join(str(v) for v in span.attributes.values())


def test_sledzony_blad_modelu_propaguje_i_span_ma_error(spany):
    class _Rzuca:
        def analizuj_zdjecie(self, obraz, mime_type):
            raise NotImplementedError("tylko tekst")

    model = ModelSledzony(_Rzuca(), nazwa_modelu="bielik", system="vllm")
    with pytest.raises(NotImplementedError):
        model.analizuj_zdjecie(OBRAZ, "image/jpeg")
    (span,) = spany.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "NotImplementedError"


# ---------------------------------------------------------------------------
# ModelAtrapa
# ---------------------------------------------------------------------------

KATALOG_OCZEKIWANE = ROOT / "dane" / "oczekiwane"
KATALOG_ZDJEC = ROOT / "dane" / "zdjecia_szkod"


def _bajty(id_przypadku: str) -> bytes:
    return (KATALOG_ZDJEC / f"{id_przypadku}.jpg").read_bytes()


def test_atrapa_zdjecie_z02_to_zalanie_niezaleznie_od_ustawionego_przypadku():
    atrapa = ModelAtrapa(KATALOG_OCZEKIWANE)
    atrapa.ustaw_przypadek("Z01")  # zgloszony pozar
    ocena, meta = atrapa.analizuj_zdjecie(_bajty("Z02"), "image/jpeg")
    assert ocena.rodzaj_zdarzenia == "zalanie"
    assert ocena.dlugotrwalosc == "NAGLE"
    assert ocena.czy_widac_szkode is True and ocena.pewnosc >= 0.6
    assert isinstance(meta, MetadaneWywolania)


def test_atrapa_dziala_bez_ustawionego_przypadku():
    ocena, _ = ModelAtrapa(KATALOG_OCZEKIWANE).analizuj_zdjecie(_bajty("Z05"), "image/jpeg")
    assert (ocena.rodzaj_zdarzenia, ocena.dlugotrwalosc) == ("korozja_zawilgocenie", "DLUGOTRWALE")


def test_atrapa_odtwarza_oczekiwane_wszystkich_12_zdjec():
    import json

    atrapa = ModelAtrapa(KATALOG_OCZEKIWANE)
    for numer in range(1, 13):
        id_przypadku = f"Z{numer:02d}"
        oczekiwane = json.loads((ROOT / "dane" / "szkody" / "oczekiwane" / f"{id_przypadku}.json")
                                .read_text(encoding="utf-8"))["zdjecie"]
        ocena, _ = atrapa.analizuj_zdjecie(_bajty(id_przypadku), "image/jpeg")
        assert (ocena.rodzaj_zdarzenia, ocena.dlugotrwalosc) == (
            oczekiwane["rodzaj_zdarzenia"], oczekiwane["dlugotrwalosc"]
        ), id_przypadku


def test_atrapa_nieznane_bajty_to_value_error():
    with pytest.raises(ValueError):
        ModelAtrapa(KATALOG_OCZEKIWANE).analizuj_zdjecie(b"nie-ze-zbioru", "image/jpeg")


def test_atrapa_pomija_zdjecia_flux_rdza_ze_starszych_przebiegow():
    """Z03_flux_rdza.jpg i Z06_flux_rdza.jpg to odrzucone zdjecia - nie wchodza do mapy hashy."""
    atrapa = ModelAtrapa(KATALOG_OCZEKIWANE)
    for plik in KATALOG_ZDJEC.glob("*_flux_rdza.jpg"):
        with pytest.raises(ValueError):
            atrapa.analizuj_zdjecie(plik.read_bytes(), "image/jpeg")


def test_atrapa_bez_katalogu_zdjec_zglasza_value_error(tmp_path):
    (tmp_path / "oczekiwane").mkdir()
    with pytest.raises(ValueError):
        ModelAtrapa(tmp_path / "oczekiwane").analizuj_zdjecie(hashlib.sha256(b"x").digest(), "image/jpeg")
