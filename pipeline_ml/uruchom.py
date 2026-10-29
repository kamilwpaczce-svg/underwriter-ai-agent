"""Wysylka pipeline'u Azure ML: przygotuj -> trenuj -> ewaluuj -> zarejestruj (Etap 15, zadanie 3).

Uruchamiac z `.venv-mlops` (azure-ai-ml; `.venv-ewaluacja` ma inny azure-storage-blob):

    .venv-mlops\\Scripts\\python -I -X utf8 pipeline_ml\\uruchom.py --rodzaj hgb
    .venv-mlops\\Scripts\\python -I -X utf8 pipeline_ml\\uruchom.py --rodzaj zepsuty

`--rodzaj`: `hgb` (model docelowy), `logreg` (baseline), `zepsuty` (HGB na przetasowanych
etykietach - test bramki). Compute: SERVERLESS `Standard_DS2_v2` (zadnych klastrow). Nie
puszczac dwoch pipeline'ow naraz: odczyt championa i zapis tagu w rejestrze to nie transakcja.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

KORZEN = Path(__file__).resolve().parent.parent
KATALOG_KOMPONENTOW = Path(__file__).resolve().parent / "komponenty"
PLIK_SRODOWISKA = Path(__file__).resolve().parent / "srodowisko.yml"

SUBSKRYPCJA = "00000000-0000-0000-0000-000000000000"
GRUPA = "rg-underwriter-demo"
WORKSPACE = "uw-demo-mlw"
TYP_INSTANCJI = "Standard_DS2_v2"
OBRAZ_BAZOWY = "mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest"
NAZWA_SRODOWISKA = "uw-ryzyko-sklearn"
RODZAJE = ("hgb", "logreg", "zepsuty")
KROKI = ("przygotuj", "trenuj", "ewaluuj", "zarejestruj")
STANY_KONCOWE = ("Completed", "Failed", "Canceled", "NotResponding")
# display_name kroku zarejestruj w pipeline = nazwa zmiennej w funkcji `potok`. Wyjscie na poziomie
# pipeline'u NIE dziala: `jobs.download(pipeline, output_name=...)` zwraca pusty katalog bez bledu (26.10).
WEZEL_REJESTRACJI = "z"


def przygotuj_kod(cel: Path) -> Path:
    """Katalog `code=` komponentow: skrypty krokow (plasko) + pakiet `ryzyko/` (bez cache)."""
    for krok in KROKI:
        shutil.copy(KATALOG_KOMPONENTOW / f"{krok}.py", cel / f"{krok}.py")
    shutil.copytree(KORZEN / "ryzyko", cel / "ryzyko", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return cel


def wersja_srodowiska() -> str:
    """Wersja srodowiska = skrot tresci pliku conda: ta sama tresc -> ta sama wersja (idempotentnie)."""
    return hashlib.sha256(PLIK_SRODOWISKA.read_bytes()).hexdigest()[:8]


def zbuduj_klienta():
    from azure.ai.ml import MLClient
    from azure.identity import AzureCliCredential

    return MLClient(AzureCliCredential(), SUBSKRYPCJA, GRUPA, WORKSPACE)


def zbuduj_pipeline(klient, kod: Path, rodzaj: str, n: int, seed: int):
    from azure.ai.ml import Input, Output, command
    from azure.ai.ml.dsl import pipeline
    from azure.ai.ml.entities import Environment, JobResourceConfiguration

    srodowisko = klient.environments.create_or_update(
        Environment(
            name=NAZWA_SRODOWISKA,
            version=wersja_srodowiska(),
            image=OBRAZ_BAZOWY,
            conda_file=str(PLIK_SRODOWISKA),
            description="Etap 15: scikit-learn 1.9.1 + skops 0.16.0 + mlflow 3.15.0 (wersje jak w API i .venv-ewaluacja)",
        )
    )

    def krok(nazwa: str, polecenie: str, wejscia: dict, wyjscia: dict):
        return command(
            name=f"uw_{nazwa}",
            display_name=nazwa,
            code=str(kod),
            command=polecenie,
            inputs=wejscia,
            outputs=wyjscie_folder(wyjscia),
            environment=srodowisko,
        )

    def wyjscie_folder(nazwy: dict) -> dict:
        return {k: Output(type="uri_folder") for k in nazwy}

    przygotuj = krok(
        "przygotuj",
        "python przygotuj.py --n ${{inputs.n}} --seed ${{inputs.seed}} --dane ${{outputs.dane}}",
        {"n": Input(type="integer"), "seed": Input(type="integer")},
        {"dane": 1},
    )
    trenuj = krok(
        "trenuj",
        "python trenuj.py --dane ${{inputs.dane}} --rodzaj ${{inputs.rodzaj}} --seed ${{inputs.seed}}"
        " --model ${{outputs.model}}",
        {"dane": Input(type="uri_folder"), "rodzaj": Input(type="string"), "seed": Input(type="integer")},
        {"model": 1},
    )
    ewaluuj = krok(
        "ewaluuj",
        "python ewaluuj.py --dane ${{inputs.dane}} --model ${{inputs.model}} --metryki ${{outputs.metryki}}",
        {"dane": Input(type="uri_folder"), "model": Input(type="uri_folder")},
        {"metryki": 1},
    )
    zarejestruj = krok(
        "zarejestruj",
        "python zarejestruj.py --model ${{inputs.model}} --metryki ${{inputs.metryki}} --dane ${{inputs.dane}}"
        " --rodzaj ${{inputs.rodzaj}} --wynik ${{outputs.wynik}}",
        {
            "model": Input(type="uri_folder"),
            "metryki": Input(type="uri_folder"),
            "dane": Input(type="uri_folder"),
            "rodzaj": Input(type="string"),
        },
        {"wynik": 1},
    )

    @pipeline(name="uw_ryzyko_szkody", display_name=f"ryzyko_szkody-{rodzaj}", experiment_name="etap15-ryzyko-szkody")
    def potok(n=5000, seed=0, rodzaj="hgb"):  # bez adnotacji: SDK nie czyta ich przy `from __future__ import annotations`
        p = przygotuj(n=n, seed=seed)
        t = trenuj(dane=p.outputs.dane, rodzaj=rodzaj, seed=seed)
        e = ewaluuj(dane=p.outputs.dane, model=t.outputs.model)
        z = zarejestruj(model=t.outputs.model, metryki=e.outputs.metryki, dane=p.outputs.dane, rodzaj=rodzaj)  # noqa: F841 - nazwa wezla "z" (WEZEL_REJESTRACJI)

    job = potok(n=n, seed=seed, rodzaj=rodzaj)
    job.settings.default_compute = "serverless"
    for wezel in job.jobs.values():
        wezel.resources = JobResourceConfiguration(instance_type=TYP_INSTANCJI, instance_count=1)
    return job


def czekaj(klient, nazwa: str, odstep: int = 30) -> str:
    t0 = time.time()
    ostatni = None
    while True:
        status = klient.jobs.get(nazwa).status
        stan = str(getattr(status, "value", status))  # enum SDK -> "Completed", nie "JobStatus.COMPLETED"
        if stan != ostatni:
            print(f"{int(time.time() - t0):5d}s {stan}", flush=True)
            ostatni = stan
        if stan in STANY_KONCOWE:
            return stan
        time.sleep(odstep)


def pobierz_rejestracje(klient, nazwa: str) -> dict | None:
    """`rejestracja.json` z wyjscia `wynik` pipeline'u; brak pliku -> None (nie zgadujemy wyniku bramki)."""
    dzieci = [c for c in klient.jobs.list(parent_job_name=nazwa) if c.display_name == WEZEL_REJESTRACJI]
    if not dzieci:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        klient.jobs.download(dzieci[0].name, download_path=tmp, output_name="wynik")
        pliki = list(Path(tmp).rglob("rejestracja.json"))
        if not pliki:
            return None
        return json.loads(pliki[0].read_text(encoding="utf-8"))


def podsumowanie_md(nazwa: str, rodzaj: str, stan: str, rejestracja: dict | None) -> str:
    """Podsumowanie biegu dla `$GITHUB_STEP_SUMMARY`. Odrzucenie challengera to poprawny wynik, nie blad."""
    wiersze = [f"## Pipeline modelu ryzyka: `{rodzaj}`", "", f"- job Azure ML: `{nazwa}`", f"- stan: **{stan}**"]
    if rejestracja is None:
        wiersze.append("- bramka: **brak wyniku** (krok `zarejestruj` nie zapisal `rejestracja.json`)")
    else:
        werdykt = "PROMOWANY na championa" if rejestracja["promowany"] else "ODRZUCONY (champion bez zmian)"
        wiersze += [
            f"- bramka: **{werdykt}**",
            f"- wersja challengera: `{rejestracja['wersja']}`",
            f"- champion przed / po: `{rejestracja['champion_przed']}` -> `{rejestracja['champion_po']}`",
            f"- powod: {rejestracja['powod']}",
        ]
    return "\n".join(wiersze) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rodzaj", choices=RODZAJE, default="hgb")
    parser.add_argument("--n", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bez-czekania", action="store_true", help="wyslij i wyjdz (domyslnie czeka na wynik)")
    args = parser.parse_args(argv)

    klient = zbuduj_klienta()
    with tempfile.TemporaryDirectory() as tmp:
        kod = przygotuj_kod(Path(tmp))
        job = zbuduj_pipeline(klient, kod, args.rodzaj, args.n, args.seed)
        wyslany = klient.jobs.create_or_update(job)
    print(f"job: {wyslany.name} rodzaj={args.rodzaj}", flush=True)
    if args.bez_czekania:
        return 0
    stan = czekaj(klient, wyslany.name)
    print(f"koniec: {wyslany.name} {stan}")
    rejestracja = pobierz_rejestracje(klient, wyslany.name) if stan == "Completed" else None
    tekst = podsumowanie_md(wyslany.name, args.rodzaj, stan, rejestracja)
    print(tekst)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(tekst)
    # Kod != 0 tylko przy awarii kroku albo braku wyniku bramki; odrzucenie challengera = 0.
    return 0 if stan == "Completed" and rejestracja is not None else 1


if __name__ == "__main__":
    sys.exit(main())
