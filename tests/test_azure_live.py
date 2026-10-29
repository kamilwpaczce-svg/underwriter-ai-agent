"""Testy NA ZYWO Etapu 5: prawdziwe wywolania Azure OpenAI (gpt-5-mini) i Document
Intelligence przez Entra ID (`az login`). Domyslnie pomijane - jak `integracja` - bo
kosztuja prawdziwe zapytania i zuzywaja limit F0 Document Intelligence.

Uruchomienie (PowerShell/Bash z az.cmd w PATH, po `az login`):
    pytest -q -m azure

Zakres celowo ograniczony do 2 dokumentow (W01, W08) - SPEC_ETAP5.md zabrania
uruchamiania tu pelnej ewaluacji 14 przypadkow.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLIK_W01 = ROOT / "dane" / "wnioski" / "W01.pdf"
PLIK_W08 = ROOT / "dane" / "wnioski" / "W08.pdf"

sys.path.insert(0, str(ROOT / "generator"))
from nip import normalizuj_nip  # noqa: E402

pytestmark = pytest.mark.azure


@pytest.fixture(autouse=True)
def _tylko_na_jawne_zadanie(request):
    """Bezpiecznik niezalezny od zmiennych srodowiskowych: nawet jesli operator ma
    AZURE_OPENAI_ENDPOINT/AZURE_DOCINT_ENDPOINT juz ustawione w powloce, zwykle
    `pytest -q` (bez `-m azure`) ma te testy pominac, nie uruchomic na zywo."""
    markexpr = request.config.getoption("markexpr") or ""
    if "azure" not in markexpr:
        pytest.skip("Test na zywo Azure - uruchom jawnie: pytest -q -m azure")


def test_ocr_w08_zawiera_620():
    from agent.ocr_azure import ocr_bajtow

    wynik = ocr_bajtow(PLIK_W08.read_bytes(), "application/pdf")
    print(f"\nOCR W08: {wynik.liczba_stron} str., z_cache={wynik.z_cache}, {len(wynik.tekst)} znakow")
    assert "620" in wynik.tekst


def test_model_azure_klasyfikuje_i_ekstrahuje_w01_poprawnie():
    from agent.model_azure import ModelAzure
    from agent.wczytywanie import wczytaj_plik

    model = ModelAzure()
    czesci = wczytaj_plik(str(PLIK_W01))

    klasyfikacja, metadane_klas = model.klasyfikuj(czesci)
    print(f"\nKlasyfikacja W01: {klasyfikacja.typ_dokumentu} | tokeny={metadane_klas}")
    assert klasyfikacja.typ_dokumentu == "WNIOSEK"

    ekstrakcja, metadane_ekstr = model.ekstrahuj(czesci)
    nip_otrzymany = normalizuj_nip(str(ekstrakcja.pola.nip))
    print(f"Ekstrakcja W01: NIP={nip_otrzymany} | tokeny={metadane_ekstr}")
    assert nip_otrzymany == "1234563201"
