"""Konfiguracja wdrozenia modulu szkodowego (Etap 10): Bicep, .env.example, dokumentacja."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BICEP = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")


def _env_kontenera(nazwa: str) -> str:
    """Tekst tablicy `env: [...]` kontenera o podanej nazwie (bez parsera Bicep).

    Etap 13 - `uw-api` ma teraz `env: concat([...], warunek ? [] : [...])` (env
    APPLICATIONINSIGHTS_CONNECTION_STRING istnieje tylko, gdy appInsightsConnectionString
    nie jest puste), wiec zamkniecie wycinka to `)`, nie `]`. `uw-web` nadal ma zwykle
    `env: [...]` - zamkniecie `]` dziala jak wczesniej.
    """
    poczatek = BICEP.index(f"name: '{nazwa}'")
    env = BICEP.index("env: ", poczatek)
    if BICEP.startswith("env: concat([", env):
        koniec = BICEP.index("\n          )", env)
    else:
        koniec = BICEP.index("\n          ]", env)
    return BICEP[env:koniec]


def test_bicep_api_ma_zmienne_wyszukiwarki():
    env = _env_kontenera("uw-api")
    for nazwa, wartosc in (
        ("AZURE_SEARCH_ENDPOINT", "azureSearchEndpoint"),
        ("AZURE_SEARCH_INDEX", "azureSearchIndex"),
        ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "azureOpenAiEmbeddingDeployment"),
        ("WYSZUKIWARKA", "'azure'"),
        ("AZURE_SEARCH_SEMANTIC", "azureSearchSemantic"),
    ):
        assert f"{{ name: '{nazwa}', value: {wartosc} }}" in env


def test_bicep_wartosci_domyslne_zgodne_z_kodem():
    from rag.azure_search import EMBEDDING_DOMYSLNY, INDEKS_DOMYSLNY

    assert "param azureSearchEndpoint string = 'https://uw-demo-search-xx1.search.windows.net'" in BICEP
    assert f"param azureSearchIndex string = '{INDEKS_DOMYSLNY}'" in BICEP
    assert f"param azureOpenAiEmbeddingDeployment string = '{EMBEDDING_DOMYSLNY}'" in BICEP
    assert "param azureSearchSemantic string = '0'" in BICEP


def test_bicep_nie_tworzy_uslugi_search_i_nie_ma_kluczy():
    """Usluga AI Search istnieje poza Bicepem (trafi do Terraform); dostep tylko przez RBAC."""
    assert "Microsoft.Search/" not in BICEP
    assert not re.search(r"AZURE_SEARCH_(API_)?KEY", BICEP)
    assert "API_URL_WEWNETRZNY" not in _env_kontenera("uw-api")  # wycinek nie siega env kontenera web


def test_env_example_opisuje_wyszukiwarke_bez_kluczy():
    tekst = (ROOT / ".env.example").read_text(encoding="utf-8")
    for nazwa in ("WYSZUKIWARKA", "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_INDEX",
                  "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "AZURE_SEARCH_SEMANTIC"):
        assert f"# {nazwa}=" in tekst
    assert not re.search(r"AZURE_SEARCH_(API_)?KEY", tekst)


def test_dokumentacja_modulu_szkodowego():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Modul szkodowy (RAG)" in readme
    assert "recall_wyszukiwania_at_5" in readme and "cytat_trafiony" in readme
    ai_act = (ROOT / "docs" / "AI_ACT.md").read_text(encoding="utf-8")
    assert "## 7. Ocena szkod (Etap 10)" in ai_act
    assert "zatwierdza czlowiek" in ai_act
