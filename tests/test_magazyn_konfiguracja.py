"""Etap 6 - testy konfiguracji magazynu blob (Managed Identity) - zero sieci.

Dwa obszary:
1. `Ustawienia.__post_init__` - dokladnie jedno z AZURE_STORAGE_CONNECTION_STRING /
   AZURE_STORAGE_ACCOUNT_URL (4 przypadki: zadne, obie, tylko connection string,
   tylko account url).
2. `MagazynBlob.utworz_kontener_jesli_brak` - 403 (brak uprawnien do create) nie wywraca
   startu API, tylko loguje ostrzezenie; inny blad HTTP nadal sie propaguje.
"""

from __future__ import annotations

import logging

import pytest
from azure.core.exceptions import HttpResponseError, ResourceExistsError

from api.magazyn import MagazynBlob
from api.ustawienia import Ustawienia


def _bazowe(**nadpisania) -> dict:
    podstawa = dict(database_url="postgresql://x/y")
    podstawa.update(nadpisania)
    return podstawa


def test_brak_obu_zrodel_magazynu_rzuca_runtime_error():
    with pytest.raises(RuntimeError, match="dokladnie jedna"):
        Ustawienia(**_bazowe())


def test_oba_zrodla_magazynu_naraz_rzucaja_runtime_error():
    with pytest.raises(RuntimeError, match="dokladnie jedna"):
        Ustawienia(
            **_bazowe(
                azure_storage_connection_string="UseDevelopmentStorage=true",
                azure_storage_account_url="https://przyklad.blob.core.windows.net",
            )
        )


def test_tylko_connection_string_jest_poprawny():
    ustawienia = Ustawienia(**_bazowe(azure_storage_connection_string="UseDevelopmentStorage=true"))
    assert ustawienia.azure_storage_connection_string == "UseDevelopmentStorage=true"
    assert ustawienia.azure_storage_account_url is None


def test_tylko_account_url_jest_poprawny():
    ustawienia = Ustawienia(**_bazowe(azure_storage_account_url="https://przyklad.blob.core.windows.net"))
    assert ustawienia.azure_storage_account_url == "https://przyklad.blob.core.windows.net"
    assert ustawienia.azure_storage_connection_string is None


def test_z_env_rzuca_gdy_zadna_zmienna_magazynu_nie_jest_ustawiona(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_URL", raising=False)
    with pytest.raises(RuntimeError, match="dokladnie jedna"):
        Ustawienia.z_env()


def test_z_env_rzuca_gdy_obie_zmienne_magazynu_sa_ustawione(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://przyklad.blob.core.windows.net")
    with pytest.raises(RuntimeError, match="dokladnie jedna"):
        Ustawienia.z_env()


def test_z_env_akceptuje_tylko_account_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://przyklad.blob.core.windows.net")
    ustawienia = Ustawienia.z_env()
    assert ustawienia.azure_storage_account_url == "https://przyklad.blob.core.windows.net"
    assert ustawienia.azure_storage_connection_string is None


class _FakeKontenerKlient:
    def __init__(self, wyjatek: Exception):
        self._wyjatek = wyjatek

    def create_container(self, nazwa):
        raise self._wyjatek


def _blad_http(status_code: int) -> HttpResponseError:
    e = HttpResponseError(message="blad")
    e.status_code = status_code
    return e


def _magazyn_z_atrapa_klienta(wyjatek: Exception) -> MagazynBlob:
    magazyn = MagazynBlob("wnioski", connection_string="UseDevelopmentStorage=true")
    magazyn._serwis = _FakeKontenerKlient(wyjatek)
    return magazyn


def test_utworz_kontener_ignoruje_resource_exists_error():
    magazyn = _magazyn_z_atrapa_klienta(ResourceExistsError("juz istnieje"))
    magazyn.utworz_kontener_jesli_brak()  # nie rzuca


def test_utworz_kontener_403_loguje_ostrzezenie_i_nie_rzuca(caplog):
    magazyn = _magazyn_z_atrapa_klienta(_blad_http(403))
    with caplog.at_level(logging.WARNING):
        magazyn.utworz_kontener_jesli_brak()  # nie rzuca
    assert any("403" in rekord.message for rekord in caplog.records)


def test_utworz_kontener_inny_blad_http_propaguje_sie():
    magazyn = _magazyn_z_atrapa_klienta(_blad_http(500))
    with pytest.raises(HttpResponseError):
        magazyn.utworz_kontener_jesli_brak()


def test_magazyn_blob_bez_zrodla_polaczenia_rzuca_runtime_error():
    with pytest.raises(RuntimeError, match="connection_string.*account_url|account_url.*connection_string"):
        MagazynBlob("wnioski")
