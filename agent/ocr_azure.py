"""OCR przez Azure Document Intelligence (prebuilt-layout, markdown) dla `agent/model_azure.py`.

Decyzja modelu OCR: `prebuilt-layout` z wyjsciem markdown, nie `prebuilt-read`. Ewaluacja
2026-10-10 na gpt-5-mini: z prebuilt-read W08 (skan formularza z etykietami w lewej kolumnie
i wartosciami w prawej) dal 9/18 pol - tekst odczytany poprawnie ("620 tys. PLN"), ale
kolumny rozjechane, wiec model przesunal kwoty o jedna pozycje (budynki <- kwota maszyn,
900 tys. trafilo do szkod). prebuilt-layout zwraca tabele HTML z parami etykieta-wartosc
(budynki 900, maszyny 450, zapasy 150, szkoda 620 - zgodnie z wzorcem). F0 obsluguje layout
w tym samym limicie 500 stron/mies.

Uwierzytelnienie: wylacznie Entra ID (zasob ma disableLocalAuth=true, zero kluczy API).

Cache na dysku kluczowany SHA-256 bajtow wejsciowych (`.cache_ocr/`, wpisany do
.gitignore): Document Intelligence w warstwie F0 ma limit 500 stron miesiecznie i niski
limit zapytan/minute - powtorne ewaluacje tych samych 14 plikow nie moga zjadac limitu.
Trafienie w cache = zero wywolan sieciowych. Dodatkowy efekt uboczny tego cache: w grafie
LangGraph wezly `klasyfikuj` i `ekstrahuj` dostaja ten sam obiekt `CzesciDokumentu` (z
tymi samymi mediami) - bez cache kazdy dokument bylby OCR-owany dwukrotnie w jednym
przebiegu (patrz `agent/model_azure.py::ModelAzure._tekst_pelny`).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL_OCR_DOMYSLNY = "prebuilt-layout"
KATALOG_CACHE_DOMYSLNY = Path(__file__).resolve().parent.parent / ".cache_ocr"
ZAKRES_TOKENU_COGNITIVE = "https://cognitiveservices.azure.com/.default"
OPOZNIENIE_PONOWIENIA_DOMYSLNE_S = 5.0


class BladOCR(RuntimeError):
    """Blad wywolania Document Intelligence (po wyczerpaniu jednego ponowienia na 429)."""


@dataclass
class WynikOCR:
    tekst: str
    liczba_stron: int
    z_cache: bool


# Liczniki globalne modulu - czytane przez `ewaluacja/uruchom.py` do raportu kosztow/limitow
# (F0: 500 stron/mies.). Stan procesu, nie trwaly - wystarczajacy dla jednorazowego CLI.
_liczniki: dict[str, int] = {"wywolania_sieciowe": 0, "stron_ocr": 0, "trafienia_cache": 0}


def liczniki_ocr() -> dict[str, int]:
    """Kopia licznikow: wywolania_sieciowe (realne zapytania do Document Intelligence),
    stron_ocr (suma stron policzonych przez realne wywolania - to zuzywa limit F0),
    trafienia_cache (OCR obsluzony z dysku, zero zuzytego limitu)."""
    return dict(_liczniki)


def resetuj_liczniki_ocr() -> None:
    _liczniki.update(wywolania_sieciowe=0, stron_ocr=0, trafienia_cache=0)


def zbuduj_poswiadczenie_azure():
    """ChainedTokenCredential: ManagedIdentityCredential (Etap 6 - Container Apps z
    przypisana przez uzytkownika tozsamoscia zarzadzana `uw-demo-id`) -> AzureCliCredential
    (dev lokalny, `az login`). Zero kluczy API - zasoby maja disableLocalAuth=true.

    `client_id` z `AZURE_CLIENT_ID`: tozsamosc przypisana przez uzytkownika (user-assigned
    managed identity) wymaga jawnego `client_id` - bez niego Azure nie wie, ktorej z
    potencjalnie wielu tozsamosci przypisanych do zasobu uzyc. Gdy zmienna nie jest
    ustawiona, `client_id=None` - zachowanie jak dotychczas (system-assigned managed
    identity, a lokalnie i tak odpada na rzecz `AzureCliCredential` ponizej).

    Lokalnie `ManagedIdentityCredential.get_token()` odpada natychmiast (brak endpointu
    IMDS/MSI w zmiennych srodowiskowych poza Azure - zero sieci), wiec faktycznie uzywany
    jest `AzureCliCredential`. `process_timeout` ograniczony, zeby brak `az login` dawal
    czytelny blad zamiast wisiec. Na Windows `az.cmd` musi byc w PATH procesu, ktory
    uruchamia Pythona (patrz README, sekcja Etap 5) - to nie jest parametr kodu, bo
    `AzureCliCredential` szuka `az`/`az.cmd` przez PATH, nie przez sciezke w kodzie."""
    import os

    from azure.identity import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential

    return ChainedTokenCredential(
        ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID")),
        AzureCliCredential(process_timeout=60),
    )


def _sciezka_cache(skrot: str, katalog_cache: Path) -> Path:
    return katalog_cache / f"{skrot}.json"


def _wczytaj_z_cache(sciezka: Path) -> WynikOCR | None:
    if not sciezka.exists():
        return None
    try:
        dane = json.loads(sciezka.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return WynikOCR(tekst=dane["tekst"], liczba_stron=dane["liczba_stron"], z_cache=True)


def _zapisz_do_cache(sciezka: Path, tekst: str, liczba_stron: int) -> None:
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    sciezka.write_text(
        json.dumps({"tekst": tekst, "liczba_stron": liczba_stron}, ensure_ascii=False),
        encoding="utf-8",
    )


def _retry_after_sekundy(wyjatek: Exception) -> float:
    naglowki = getattr(getattr(wyjatek, "response", None), "headers", None) or {}
    surowa = naglowki.get("Retry-After") if hasattr(naglowki, "get") else None
    if surowa is None:
        return OPOZNIENIE_PONOWIENIA_DOMYSLNE_S
    try:
        return max(float(surowa), 0.0)
    except (TypeError, ValueError):
        return OPOZNIENIE_PONOWIENIA_DOMYSLNE_S


def _ocr_z_jednym_ponowieniem(wywolaj):
    """Jedno ponowienie na 429, z odczekaniem wg Retry-After. Bez petli: po drugiej
    probie kazdy blad konczy sie wyjatkiem `BladOCR`."""
    try:
        return wywolaj()
    except Exception as pierwszy_blad:  # noqa: BLE001 - rozroznienie 429 ponizej
        if getattr(pierwszy_blad, "status_code", None) != 429:
            raise
        time.sleep(_retry_after_sekundy(pierwszy_blad))
        try:
            return wywolaj()
        except Exception as drugi_blad:
            raise BladOCR(
                f"Document Intelligence: blad po jednym ponowieniu 429: {drugi_blad}"
            ) from drugi_blad


def _klient_domyslny(endpoint: str | None):
    import os

    from azure.ai.documentintelligence import DocumentIntelligenceClient

    endpoint = endpoint or os.environ.get("AZURE_DOCINT_ENDPOINT")
    if not endpoint:
        raise RuntimeError("Brak zmiennej srodowiskowej AZURE_DOCINT_ENDPOINT.")
    return DocumentIntelligenceClient(endpoint, zbuduj_poswiadczenie_azure())


def ocr_bajtow(
    bajty: bytes,
    mime_type: str,
    *,
    klient: Any = None,
    endpoint: str | None = None,
    katalog_cache: str | Path | None = None,
    nazwa_modelu: str = MODEL_OCR_DOMYSLNY,
) -> WynikOCR:
    """OCR bajtow (PDF/JPG) przez Document Intelligence, z cache na dysku kluczowanym
    SHA-256 bajtow wejsciowych. Trafienie w cache = zero wywolan sieciowych.

    `mime_type` jest tylko informacyjny (log/diagnostyka) - do API zawsze idzie
    `content_type="application/octet-stream"`, dokladnie jak w sprawdzonym tescie dymnym
    z 2026-10-10 (Document Intelligence rozpoznaje format z zawartosci pliku)."""
    katalog_cache = Path(katalog_cache) if katalog_cache else KATALOG_CACHE_DOMYSLNY
    # Model OCR w kluczu: zmiana read -> layout nie moze zwracac starego tekstu z cache.
    skrot = f"{hashlib.sha256(bajty).hexdigest()}-{nazwa_modelu}"
    sciezka = _sciezka_cache(skrot, katalog_cache)

    z_cache = _wczytaj_z_cache(sciezka)
    if z_cache is not None:
        _liczniki["trafienia_cache"] += 1
        return z_cache

    if klient is None:
        klient = _klient_domyslny(endpoint)

    # markdown tylko dla layout: zachowuje tabele (pary etykieta-wartosc); read go nie obsluguje.
    dodatkowe = {"output_content_format": "markdown"} if nazwa_modelu == "prebuilt-layout" else {}

    def _wywolaj() -> Any:
        return klient.begin_analyze_document(
            nazwa_modelu, body=bajty, content_type="application/octet-stream", **dodatkowe
        ).result()

    wynik = _ocr_z_jednym_ponowieniem(_wywolaj)

    tekst = wynik.content or ""
    liczba_stron = len(wynik.pages) if wynik.pages else 0

    _liczniki["wywolania_sieciowe"] += 1
    _liczniki["stron_ocr"] += liczba_stron
    _zapisz_do_cache(sciezka, tekst, liczba_stron)
    return WynikOCR(tekst=tekst, liczba_stron=liczba_stron, z_cache=False)
