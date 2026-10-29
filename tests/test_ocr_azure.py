"""Testy `agent/ocr_azure.py` - wylacznie atrapa klienta Document Intelligence,
zero sieci, zero Entra ID. Patrz SPEC_ETAP5.md, sekcja Testy.
"""

from __future__ import annotations

import pytest
from azure.core.exceptions import HttpResponseError

from agent.ocr_azure import BladOCR, liczniki_ocr, ocr_bajtow, resetuj_liczniki_ocr, zbuduj_poswiadczenie_azure


class _FakeOdpowiedz:
    def __init__(self, headers):
        self.headers = headers


def _blad_429() -> HttpResponseError:
    """Blad 429 z Retry-After=0, zeby test nie czekal realnie na ponowienie."""
    e = HttpResponseError(message="limit zapytan Document Intelligence")
    e.status_code = 429
    e.response = _FakeOdpowiedz({"Retry-After": "0"})
    return e


class _FakeWynikOCR:
    def __init__(self, tekst: str, liczba_stron: int):
        self.content = tekst
        self.pages = [object()] * liczba_stron


class _FakePoller:
    def __init__(self, wynik_lub_blad):
        self._wynik_lub_blad = wynik_lub_blad

    def result(self):
        if isinstance(self._wynik_lub_blad, Exception):
            raise self._wynik_lub_blad
        return self._wynik_lub_blad


class FakeKlientOCR:
    """Atrapa `DocumentIntelligenceClient`: kolejne wywolania `begin_analyze_document`
    zwracaja kolejne elementy `odpowiedzi` (wynik albo wyjatek)."""

    def __init__(self, odpowiedzi):
        self._odpowiedzi = list(odpowiedzi)
        self.wywolania = 0
        self.argumenty: list[dict] = []

    def begin_analyze_document(self, nazwa_modelu, body, content_type, **kwargs):
        self.wywolania += 1
        self.argumenty.append({"nazwa_modelu": nazwa_modelu, **kwargs})
        return _FakePoller(self._odpowiedzi.pop(0))


@pytest.fixture(autouse=True)
def _reset_liczniki():
    resetuj_liczniki_ocr()
    yield
    resetuj_liczniki_ocr()


def test_cache_trafienie_nie_woła_sieci(tmp_path):
    klient = FakeKlientOCR([_FakeWynikOCR("tresc strony 1", liczba_stron=1)])
    bajty = b"% PDF-atrapa"

    pierwszy = ocr_bajtow(bajty, "application/pdf", klient=klient, katalog_cache=tmp_path)
    drugi = ocr_bajtow(bajty, "application/pdf", klient=klient, katalog_cache=tmp_path)

    assert pierwszy.tekst == "tresc strony 1"
    assert pierwszy.z_cache is False
    assert drugi.tekst == "tresc strony 1"
    assert drugi.z_cache is True
    assert klient.wywolania == 1, "drugie wywolanie powinno trafic w cache, bez sieci"

    liczniki = liczniki_ocr()
    assert liczniki["wywolania_sieciowe"] == 1
    assert liczniki["trafienia_cache"] == 1
    assert liczniki["stron_ocr"] == 1


def test_rozne_bajty_nie_trafiaja_w_ten_sam_cache(tmp_path):
    klient = FakeKlientOCR(
        [_FakeWynikOCR("a", liczba_stron=1), _FakeWynikOCR("b", liczba_stron=1)]
    )
    ocr_bajtow(b"dokument-1", "application/pdf", klient=klient, katalog_cache=tmp_path)
    ocr_bajtow(b"dokument-2", "application/pdf", klient=klient, katalog_cache=tmp_path)
    assert klient.wywolania == 2


def test_ponowienie_429_dokladnie_raz_potem_sukces(tmp_path):
    klient = FakeKlientOCR([_blad_429(), _FakeWynikOCR("po ponowieniu", liczba_stron=2)])
    wynik = ocr_bajtow(b"dok-429-sukces", "application/pdf", klient=klient, katalog_cache=tmp_path)

    assert wynik.tekst == "po ponowieniu"
    assert wynik.z_cache is False
    assert klient.wywolania == 2, "dokladnie jedno ponowienie: proba pierwsza + jedna kolejna"
    assert liczniki_ocr()["stron_ocr"] == 2


def test_ponowienie_429_dokladnie_raz_potem_nadal_blad(tmp_path):
    klient = FakeKlientOCR([_blad_429(), _blad_429()])

    with pytest.raises(BladOCR):
        ocr_bajtow(b"dok-429-429", "application/pdf", klient=klient, katalog_cache=tmp_path)

    assert klient.wywolania == 2, "bez petli: po drugim 429 wyjatek, nie trzecia proba"
    assert liczniki_ocr() == {"wywolania_sieciowe": 0, "stron_ocr": 0, "trafienia_cache": 0}


def test_blad_inny_niz_429_nie_jest_ponawiany(tmp_path):
    klient = FakeKlientOCR([RuntimeError("inny blad, np. 500")])

    with pytest.raises(RuntimeError):
        ocr_bajtow(b"dok-500", "application/pdf", klient=klient, katalog_cache=tmp_path)

    assert klient.wywolania == 1, "blad inny niz 429 nie powinien wywolywac ponowienia"


def test_layout_prosi_o_markdown_read_nie(tmp_path):
    klient = FakeKlientOCR([_FakeWynikOCR("l", liczba_stron=1), _FakeWynikOCR("r", liczba_stron=1)])
    ocr_bajtow(b"dok", "application/pdf", klient=klient, katalog_cache=tmp_path)
    ocr_bajtow(b"dok", "application/pdf", klient=klient, katalog_cache=tmp_path,
               nazwa_modelu="prebuilt-read")
    assert klient.argumenty[0] == {"nazwa_modelu": "prebuilt-layout", "output_content_format": "markdown"}
    assert klient.argumenty[1] == {"nazwa_modelu": "prebuilt-read"}


class _FakeManagedIdentityCredential:
    """Atrapa `ManagedIdentityCredential` - przechwytuje `client_id` bez sieci (Etap 6)."""

    ostatnie_client_id: str | None = "NIEUSTAWIONE"

    def __init__(self, *, client_id=None):
        _FakeManagedIdentityCredential.ostatnie_client_id = client_id


def test_poswiadczenie_azure_przekazuje_client_id_z_env(monkeypatch):
    monkeypatch.setenv("AZURE_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr("azure.identity.ManagedIdentityCredential", _FakeManagedIdentityCredential)

    zbuduj_poswiadczenie_azure()

    assert _FakeManagedIdentityCredential.ostatnie_client_id == "11111111-2222-3333-4444-555555555555"


def test_poswiadczenie_azure_bez_env_uzywa_client_id_none(monkeypatch):
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.setattr("azure.identity.ManagedIdentityCredential", _FakeManagedIdentityCredential)

    zbuduj_poswiadczenie_azure()

    assert _FakeManagedIdentityCredential.ostatnie_client_id is None


def test_cache_rozroznia_model_ocr(tmp_path):
    """Te same bajty, inny model OCR = osobny wpis cache (stary wynik read nie wraca po
    przelaczeniu na layout)."""
    klient = FakeKlientOCR([_FakeWynikOCR("read", liczba_stron=1), _FakeWynikOCR("layout", liczba_stron=1)])
    ocr_bajtow(b"dok", "application/pdf", klient=klient, katalog_cache=tmp_path,
               nazwa_modelu="prebuilt-read")
    wynik = ocr_bajtow(b"dok", "application/pdf", klient=klient, katalog_cache=tmp_path)
    assert wynik.tekst == "layout"
    assert klient.wywolania == 2
