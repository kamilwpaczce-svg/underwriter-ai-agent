"""Test chartu Helm (deploy/helm/underwriter) przez "helm template" - bez klastra.

Pomijany w calosci, gdy w PATH brak binarki "helm" (SPEC_ETAP9.md pkt 3) - w CI job
"testy" moze, ale nie musi miec helm zainstalowanego (patrz .github/workflows/ci-cd.yml,
komentarz przy jobie "testy"); job "k8s" ma helm zawsze i uruchamia ten sam test.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

HELM = shutil.which("helm")
CHART = Path(__file__).resolve().parent.parent / "deploy" / "helm" / "underwriter"

pytestmark = pytest.mark.skipif(HELM is None, reason="brak 'helm' w PATH")


def _renderuj(*dodatkowe_argumenty: str) -> list[dict]:
    wynik = subprocess.run(
        [HELM, "template", "underwriter", str(CHART), *dodatkowe_argumenty],
        capture_output=True,
        text=True,
        check=True,
    )
    return [d for d in yaml.safe_load_all(wynik.stdout) if d]


def _kontenery(dokumenty: list[dict]) -> list[dict]:
    """Zwraca wszystkie kontenery i initContainery (spec.template.spec albo spec dla Pod)."""
    wynik = []
    for dok in dokumenty:
        spec = dok.get("spec", {})
        szablon = spec.get("template", {}).get("spec") if "template" in spec else spec
        if not szablon:
            continue
        wynik.extend(szablon.get("initContainers", []))
        wynik.extend(szablon.get("containers", []))
    return wynik


def test_domyslne_values_kazdy_kontener_ma_limity_requesty_i_runasnonroot():
    dokumenty = _renderuj()
    kontenery = _kontenery(dokumenty)
    assert kontenery, "Nie znaleziono zadnego kontenera w wyrenderowanym chart."
    for k in kontenery:
        resources = k.get("resources", {})
        assert resources.get("requests"), f"Kontener '{k['name']}' bez resources.requests."
        assert resources.get("limits"), f"Kontener '{k['name']}' bez resources.limits."
        sc = k.get("securityContext", {})
        assert sc.get("runAsNonRoot") is True, f"Kontener '{k['name']}' bez runAsNonRoot: true."
        # Obrazy maja USER po nazwie (uzytkownik, nextjs, curl_user) - bez liczbowego
        # runAsUser kubelet odmawia startu poda (CreateContainerConfigError na kind 14.10).
        assert isinstance(sc.get("runAsUser"), int), f"Kontener '{k['name']}' bez liczbowego runAsUser."


def test_domyslne_values_brak_tagu_latest():
    dokumenty = _renderuj()
    for k in _kontenery(dokumenty):
        obraz = k.get("image", "")
        assert not obraz.endswith(":latest"), f"Kontener '{k['name']}' uzywa tagu 'latest' ({obraz})."


def test_domyslne_values_service_api_to_clusterip():
    dokumenty = _renderuj()
    serwisy_api = [
        d
        for d in dokumenty
        if d.get("kind") == "Service" and d["metadata"]["name"].endswith("-api")
    ]
    assert len(serwisy_api) == 1
    assert serwisy_api[0]["spec"].get("type", "ClusterIP") == "ClusterIP"


def test_postgres_wylaczony_nie_renderuje_statefulset_a_database_url_z_values():
    adres_z_values = "postgresql://ktos:haslo@zewnetrzny-host.example/underwriter"
    dokumenty = _renderuj(
        "--set",
        "postgres.wewnetrzny=false",
        "--set",
        "azurite.wlaczony=false",
        "--set",
        f"postgres.zewnetrznyDatabaseUrl={adres_z_values}",
    )
    statefulsety = [d for d in dokumenty if d.get("kind") == "StatefulSet"]
    assert statefulsety == [], "StatefulSet Postgresa wyrenderowany mimo postgres.wewnetrzny=false."

    sekrety_app = [
        d
        for d in dokumenty
        if d.get("kind") == "Secret" and d["metadata"]["name"].endswith("-app")
    ]
    assert len(sekrety_app) == 1
    assert sekrety_app[0]["stringData"]["DATABASE_URL"].strip() == adres_z_values
