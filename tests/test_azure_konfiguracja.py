"""Testy wyboru dostawcy 'azure' w konfiguracji API i CLI ewaluacji - zero sieci,
zero Entra ID (ModelAzure konstruowany tu tylko po to, zeby sprawdzic KLASE wyniku
zbuduj_model/_zbuduj_model; same wywolania LLM/OCR sa testowane osobno w
test_model_azure.py / test_ocr_azure.py na wstrzyknietych atrapach).
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.model import ModelGemini
from agent.model_azure import ModelAzure
from api.agent_serwis import zbuduj_model
from api.ustawienia import MODELE_AGENTA_DOZWOLONE, Ustawienia
from ewaluacja.atrapa import ModelAtrapa
from ewaluacja.uruchom import _zbuduj_model


def _bazowe_ustawienia(**nadpisania) -> Ustawienia:
    podstawa = dict(
        database_url="postgresql://x/y",
        azure_storage_connection_string="DefaultEndpointsProtocol=http;",
    )
    podstawa.update(nadpisania)
    return Ustawienia(**podstawa)


def test_azure_dozwolony_model_agenta():
    assert "azure" in MODELE_AGENTA_DOZWOLONE


def test_ustawienia_z_env_akceptuje_model_azure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=http;")
    monkeypatch.setenv("MODEL_AGENTA", "azure")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://przyklad.openai.azure.com/")
    monkeypatch.setenv("AZURE_DOCINT_ENDPOINT", "https://przyklad.cognitiveservices.azure.com/")

    ustawienia = Ustawienia.z_env()

    assert ustawienia.model_agenta == "azure"
    assert ustawienia.azure_openai_endpoint == "https://przyklad.openai.azure.com/"
    assert ustawienia.azure_docint_endpoint == "https://przyklad.cognitiveservices.azure.com/"


def test_brak_pola_klucza_api_azure_w_konfiguracji():
    """Uwierzytelnienie Azure to wylacznie Entra ID - w Ustawienia nie moze istniec
    zadne pole z 'key'/'secret'/'token' w nazwie dla Azure OpenAI/Document Intelligence."""
    nazwy_pol = {pole.name for pole in dataclasses.fields(Ustawienia)}
    podejrzane = {
        nazwa for nazwa in nazwy_pol
        if "azure" in nazwa and any(slowo in nazwa for slowo in ("key", "secret", "token"))
    }
    assert podejrzane == set(), f"Znaleziono pole przypominajace klucz/sekret Azure: {podejrzane}"


def test_zbuduj_model_api_zwraca_model_azure_dla_ustawienia_azure(monkeypatch):
    # ModelAzure.__init__ z endpoint=None podniosloby BrakKonfiguracjiAzure zanim dojdzie
    # do sieci - testujemy wiec z poprawnym endpointem, ale bez realnego polaczenia:
    # konstruktor AzureChatOpenAI nie laczy sie z siecia przy tworzeniu obiektu, tylko
    # przy pierwszym .invoke(). `zbuduj_poswiadczenie_azure()` tez nie laczy sie z siecia -
    # buduje tylko lancuch poswiadczen, token jest pobierany leniwie.
    ustawienia = _bazowe_ustawienia(
        model_agenta="azure",
        azure_openai_endpoint="https://przyklad.openai.azure.com/",
        azure_docint_endpoint="https://przyklad.cognitiveservices.azure.com/",
    )
    model = zbuduj_model(ustawienia)
    assert isinstance(model, ModelAzure)


def test_zbuduj_model_api_domyslnie_atrapa():
    ustawienia = _bazowe_ustawienia()
    assert isinstance(zbuduj_model(ustawienia), ModelAtrapa)


def test_zbuduj_model_api_gemini_niezmieniony(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "atrapa-nie-prawdziwy-klucz")
    ustawienia = _bazowe_ustawienia(model_agenta="gemini")
    assert isinstance(zbuduj_model(ustawienia), ModelGemini)


def test_ewaluacja_zbuduj_model_azure(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://przyklad.openai.azure.com/")
    monkeypatch.setenv("AZURE_DOCINT_ENDPOINT", "https://przyklad.cognitiveservices.azure.com/")
    model = _zbuduj_model(uzyj_atrapy=False, nazwa_modelu=None, dostawca="azure")
    assert isinstance(model, ModelAzure)


def test_ewaluacja_zbuduj_model_gemini_domyslny_niezmieniony(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "atrapa-nie-prawdziwy-klucz")
    model = _zbuduj_model(uzyj_atrapy=False, nazwa_modelu=None)
    assert isinstance(model, ModelGemini)


def test_ewaluacja_atrapa_ma_pierwszenstwo_przed_dostawca():
    model = _zbuduj_model(uzyj_atrapy=True, nazwa_modelu=None, dostawca="azure")
    assert isinstance(model, ModelAtrapa)
