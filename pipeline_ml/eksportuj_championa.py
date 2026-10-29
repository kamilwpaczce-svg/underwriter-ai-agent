"""Eksport championa z rejestru Azure ML do Blob (Etap 15, zadanie 4a, SPEC decyzja 5).

Uruchamiac z `.venv-ewaluacja` (mlflow + azureml-mlflow; `-I` nie dodaje katalogu skryptu do
sys.path, dlatego korzen repo jest dodawany nizej jawnie):

    .venv-ewaluacja\\Scripts\\python -I -X utf8 pipeline_ml\\eksportuj_championa.py --sprawdz

Krok po kroku: tag modelu `champion` w rejestrze -> pobranie artefaktow wersji
(`models:/ryzyko_szkody/<wersja>`: model MLflow + `referencja.json` + `metryki.json`) -> zapis do
kontenera `modele`, prefiks `ryzyko_szkody/`: `champion.skops`, `referencja.json`,
`metadane.json`. Format i nazwy plikow dyktuje `ryzyko/serwowanie.py` (`pliki_modelu`),
z ktorego API ladowaniem `ModelRyzyka.z_bloba` czyta ten sam prefiks.
`metadane.json` zapisywane OSTATNIE: API wymaga w nim `wersja`, wiec polowiczny eksport
(przerwany po modelu) nie wyglada na kompletny.

`--sprawdz`: po zapisie laduje model z Blob przez `ModelRyzyka.z_bloba` i ocenia jedna
syntetyczna probke (nie wypisuje cech osobowych - ich tu nie ma).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

KORZEN = Path(__file__).resolve().parent.parent
if str(KORZEN) not in sys.path:
    sys.path.insert(0, str(KORZEN))

from ryzyko.serwowanie import (  # noqa: E402
    KONTENER_DOMYSLNY,
    PLIK_METADANYCH,
    PLIK_MODELU,
    PLIK_REFERENCJI,
    PREFIKS_DOMYSLNY,
    ModelRyzyka,
    pliki_modelu,
)

NAZWA_MODELU = "ryzyko_szkody"
KONTO_DOMYSLNE = "uwdemostxx1"
SUBSKRYPCJA = "00000000-0000-0000-0000-000000000000"
GRUPA = "rg-underwriter-demo"
WORKSPACE = "uw-demo-mlw"
REGION = "swedencentral"
# Kolejnosc zapisu: metadane na koncu (patrz docstring modulu).
KOLEJNOSC_ZAPISU = (PLIK_MODELU, PLIK_REFERENCJI, PLIK_METADANYCH)
TYPY_MIME = {PLIK_MODELU: "application/octet-stream", PLIK_REFERENCJI: "application/json", PLIK_METADANYCH: "application/json"}


def tracking_uri_workspace() -> str:
    return (
        f"azureml://{REGION}.api.azureml.ms/mlflow/v1.0/subscriptions/{SUBSKRYPCJA}/resourceGroups/{GRUPA}"
        f"/providers/Microsoft.MachineLearningServices/workspaces/{WORKSPACE}"
    )


def eksportuj(
    klient: Any,
    magazyn: Any,
    pobierz_wersje: Callable[[str, str], Path],
    zaladuj_model: Callable[[Path], Any],
    nazwa: str = NAZWA_MODELU,
    kontener: str = KONTENER_DOMYSLNY,
    prefiks: str = PREFIKS_DOMYSLNY,
) -> dict[str, Any]:
    """Etap 15: champion (tag modelu) -> 3 pliki serwowania w `kontener/prefiks`.

    `klient` = MlflowClient; `magazyn` ma `zapisz_w_kontenerze(kontener, nazwa_bloba, dane)`;
    `pobierz_wersje(nazwa, wersja)` zwraca katalog z artefaktami wersji; `zaladuj_model(katalog)`
    zwraca Pipeline. Brak championa albo brak `referencja.json` -> wyjatek (nic nie jest zapisane).
    """
    champion = (klient.get_registered_model(nazwa).tags or {}).get("champion")
    if not champion:
        raise RuntimeError(f"Model {nazwa!r} nie ma tagu 'champion' - nie ma czego eksportowac.")
    katalog = pobierz_wersje(nazwa, champion)
    referencja = json.loads((katalog / PLIK_REFERENCJI).read_text(encoding="utf-8"))
    metryki = json.loads((katalog / "metryki.json").read_text(encoding="utf-8"))
    pliki = pliki_modelu(zaladuj_model(katalog), wersja=str(champion), referencja=referencja, metryki=metryki)
    for plik in KOLEJNOSC_ZAPISU:
        magazyn.zapisz_w_kontenerze(kontener, prefiks + plik, pliki[plik])
    return {"wersja": str(champion), "metryki": metryki, "kontener": kontener, "prefiks": prefiks}


class MagazynModeli:
    """Blob konta `uwdemostxx1` przez tozsamosc z `az login` (rola Storage Blob Data Contributor)."""

    def __init__(self, konto: str):
        from azure.identity import AzureCliCredential
        from azure.storage.blob import BlobServiceClient

        self._serwis = BlobServiceClient(f"https://{konto}.blob.core.windows.net", credential=AzureCliCredential())

    def zapisz_w_kontenerze(self, kontener: str, nazwa_bloba: str, dane: bytes) -> None:
        from azure.storage.blob import ContentSettings

        typ = TYPY_MIME.get(nazwa_bloba.rsplit("/", 1)[-1], "application/octet-stream")
        self._serwis.get_blob_client(kontener, nazwa_bloba).upload_blob(
            dane, overwrite=True, content_settings=ContentSettings(content_type=typ)
        )

    def pobierz_z_kontenera(self, kontener: str, nazwa_bloba: str) -> bytes:
        return self._serwis.get_blob_client(kontener, nazwa_bloba).download_blob().readall()


def _pobierz_z_rejestru(nazwa: str, wersja: str) -> Path:
    import mlflow.artifacts

    return Path(mlflow.artifacts.download_artifacts(artifact_uri=f"models:/{nazwa}/{wersja}"))


def _zaladuj_z_katalogu(katalog: Path) -> Any:
    import mlflow.sklearn

    return mlflow.sklearn.load_model(str(katalog))


def sprawdz_z_bloba(magazyn: Any, kontener: str, prefiks: str) -> dict[str, Any]:
    """Laduje model z Blob dokladnie tak jak API i ocenia jedna probke ze zbioru syntetycznego."""
    from ryzyko.cechy import CECHY
    from ryzyko.generator import generuj_zbior

    model = ModelRyzyka.z_bloba(magazyn, kontener=kontener, prefiks=prefiks)
    if model is None:
        raise RuntimeError("ModelRyzyka.z_bloba zwrocil None - model niedostepny w Blob (powod w logu powyzej).")
    wiersz = generuj_zbior(1, seed=123).iloc[0]
    cechy = {c: (wiersz[c].item() if hasattr(wiersz[c], "item") else wiersz[c]) for c in CECHY}
    return {"wersja": model.wersja, "ocena": model.ocen(cechy), "cechy_probki": cechy}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--konto", default=KONTO_DOMYSLNE)
    parser.add_argument("--kontener", default=KONTENER_DOMYSLNY)
    parser.add_argument("--prefiks", default=PREFIKS_DOMYSLNY)
    parser.add_argument("--nazwa", default=NAZWA_MODELU)
    parser.add_argument("--sprawdz", action="store_true", help="po zapisie zaladuj z Blob i ocen jedna probke")
    args = parser.parse_args(argv)

    import mlflow
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI") or tracking_uri_workspace())
    magazyn = MagazynModeli(args.konto)
    wynik = eksportuj(
        MlflowClient(), magazyn, _pobierz_z_rejestru, _zaladuj_z_katalogu, args.nazwa, args.kontener, args.prefiks
    )
    print("eksport: " + json.dumps(wynik, ensure_ascii=False))
    if args.sprawdz:
        print("sprawdzenie z Blob: " + json.dumps(sprawdz_z_bloba(magazyn, args.kontener, args.prefiks)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
