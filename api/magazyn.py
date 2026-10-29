"""Protocol MagazynDokumentow + implementacja Azure Blob (prod/Azurite) + implementacja
pamieciowa (testy, bez sieci).

Etap 6: `MagazynBlob` przyjmuje dokladnie jedno z dwoch zrodel polaczenia -
`connection_string` (lokalnie, Azurite) albo `account_url` (Azure, Managed Identity przez
`agent.ocr_azure.zbuduj_poswiadczenie_azure`). Ktore z nich jest poprawne, waliduje juz
`api.ustawienia.Ustawienia.__post_init__` - tu jest tylko budowa klienta.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class MagazynDokumentow(Protocol):
    def zapisz(self, nazwa_bloba: str, dane: bytes, typ_mime: str) -> None: ...

    def pobierz(self, nazwa_bloba: str) -> bytes: ...

    def sprawdz_dostepnosc(self) -> None:
        """Rzuca wyjatek, gdy magazyn jest niedostepny. Uzywane przez /zdrowie."""
        ...


class MagazynBlob:
    """Implementacja na `azure-storage-blob`. Lokalnie wskazuje na Azurite
    (`connection_string`), w Azure na prawdziwe konto przez Managed Identity
    (`account_url`) - dokladnie jedno z dwoch, patrz docstring modulu."""

    def __init__(self, kontener: str, *, connection_string: str | None = None, account_url: str | None = None):
        from azure.storage.blob import BlobServiceClient

        if connection_string:
            self._serwis = BlobServiceClient.from_connection_string(connection_string)
        elif account_url:
            from agent.ocr_azure import zbuduj_poswiadczenie_azure

            self._serwis = BlobServiceClient(account_url, credential=zbuduj_poswiadczenie_azure())
        else:
            raise RuntimeError(
                "MagazynBlob wymaga connection_string (lokalnie, Azurite) albo account_url "
                "(Azure, Managed Identity)."
            )
        self._kontener_nazwa = kontener

    def utworz_kontener_jesli_brak(self) -> None:
        from azure.core.exceptions import HttpResponseError, ResourceExistsError

        try:
            self._serwis.create_container(self._kontener_nazwa)
        except ResourceExistsError:
            pass
        except HttpResponseError as e:
            if getattr(e, "status_code", None) == 403:
                # Rola Storage Blob Data Contributor nie musi obejmowac uprawnienia do
                # tworzenia kontenera (zalezy od przypisania) - kontener i tak tworzy Bicep
                # przy wdrozeniu. Brak uprawnien tutaj nie moze wywrocic startu API.
                logger.warning(
                    "Brak uprawnien (403) do utworzenia kontenera '%s' - zakladam, ze juz "
                    "istnieje (utworzony przez infrastrukture). Start API kontynuowany.",
                    self._kontener_nazwa,
                )
            else:
                raise

    def zapisz(self, nazwa_bloba: str, dane: bytes, typ_mime: str) -> None:
        from azure.storage.blob import ContentSettings

        klient = self._serwis.get_blob_client(self._kontener_nazwa, nazwa_bloba)
        klient.upload_blob(dane, overwrite=True, content_settings=ContentSettings(content_type=typ_mime))

    def pobierz(self, nazwa_bloba: str) -> bytes:
        klient = self._serwis.get_blob_client(self._kontener_nazwa, nazwa_bloba)
        return klient.download_blob().readall()

    def pobierz_z_kontenera(self, kontener: str, nazwa_bloba: str) -> bytes:
        """Etap 15: blob z INNEGO kontenera tego samego konta (np. `modele`).

        `pobierz` jest przypiete do kontenera magazynu (`wnioski`); modele ryzyka leza w
        osobnym kontenerze, a konto i tozsamosc sa te same.
        """
        klient = self._serwis.get_blob_client(kontener, nazwa_bloba)
        return klient.download_blob().readall()

    def sprawdz_dostepnosc(self) -> None:
        klient = self._serwis.get_container_client(self._kontener_nazwa)
        klient.get_container_properties()


class MagazynPamieciowy:
    """Implementacja do testow `tests/test_api.py` - bez sieci, bez Dockera.

    `wyjatek_dostepnosci` pozwala testom wymusic 503 na /zdrowie bez symulowania
    prawdziwej awarii sieci.
    """

    def __init__(self):
        self._dane: dict[str, bytes] = {}
        self._inne_kontenery: dict[tuple[str, str], bytes] = {}
        self.wyjatek_dostepnosci: Exception | None = None

    def zapisz(self, nazwa_bloba: str, dane: bytes, typ_mime: str) -> None:
        self._dane[nazwa_bloba] = dane

    def pobierz(self, nazwa_bloba: str) -> bytes:
        if nazwa_bloba not in self._dane:
            raise FileNotFoundError(f"Brak bloba '{nazwa_bloba}' w magazynie pamieciowym.")
        return self._dane[nazwa_bloba]

    def zapisz_w_kontenerze(self, kontener: str, nazwa_bloba: str, dane: bytes) -> None:
        self._inne_kontenery[(kontener, nazwa_bloba)] = dane

    def pobierz_z_kontenera(self, kontener: str, nazwa_bloba: str) -> bytes:
        if (kontener, nazwa_bloba) not in self._inne_kontenery:
            raise FileNotFoundError(f"Brak bloba '{kontener}/{nazwa_bloba}' w magazynie pamieciowym.")
        return self._inne_kontenery[(kontener, nazwa_bloba)]

    def sprawdz_dostepnosc(self) -> None:
        if self.wyjatek_dostepnosci is not None:
            raise self.wyjatek_dostepnosci
