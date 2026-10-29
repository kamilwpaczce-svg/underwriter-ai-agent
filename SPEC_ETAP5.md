# Etap 5 — dostawca Azure: Azure OpenAI (gpt-5-mini) + Document Intelligence

Cel: drugi dostawca LLM obok Gemini, zgodny ze stosem klienta (Azure), bez zmiany grafu.
Skany i zdjęcia czyta OCR Document Intelligence, a nie model językowy.

## Zasoby (już istnieją, utworzone 2026-10-10)

| zasób | wartość |
|---|---|
| grupa | `rg-underwriter-demo`, swedencentral, subskrypcja Free Trial (spendingLimit On) |
| Azure OpenAI | `https://uw-demo-aoai-xx1.openai.azure.com/`, wdrożenie **`gpt-5-mini`** (2025-08-07, GlobalStandard, 50k TPM) |
| Document Intelligence | `https://uw-demo-docint-xx1.cognitiveservices.azure.com/`, **F0** (500 stron/mies., niski limit zapytań) |
| uwierzytelnienie | **tylko Entra ID** — klucze API wyłączone (`disableLocalAuth=true`). Lokalnie `az login`; w etapie 6 Managed Identity |

Test dymny 2026-10-10 przeszedł: `AzureOpenAI(api_version="2025-04-01-preview", azure_ad_token_provider=...)`
z `reasoning_effort="minimal"` oraz `prebuilt-read` na W08 (poprawnie „620 tys. PLN”, Gemini czytał 600).

## Zakres

1. **`agent/ocr_azure.py`** — OCR przez `azure-ai-documentintelligence`, model `prebuilt-read`
   (rozważ `prebuilt-layout`, jeśli tabele/układ szablonu 2 tego wymagają — zdecyduj na podstawie wyników W01–W08, uzasadnij).
   - Wejście: bajty + typ MIME (PDF, JPG). Wyjście: tekst.
   - **Pamięć podręczna na dysku** kluczowana SHA-256 bajtów (`.cache_ocr/`, w `.gitignore`) — F0 ma 500 stron
     miesięcznie, powtórne ewaluacje nie mogą zjadać limitu. Trafienie w cache = zero wywołań.
   - Obsługa 429 z F0: jedno ponowienie z odczekaniem wg `Retry-After`, potem wyjątek. Bez pętli.
2. **`agent/model_azure.py`** — `ModelAzure` implementujący `ModelAgenta` (Protocol w `agent/model.py`).
   - `langchain-openai` `AzureChatOpenAI` + `with_structured_output` na tych samych schematach Pydantic co Gemini
     (`agent/schematy.py`), te same prompty/instrukcje co `ModelGemini` — wydziel wspólne, jeśli są zaszyte w klasie Gemini,
     **bez zmiany zachowania Gemini** (testy Gemini muszą przejść bez zmian).
   - Media z `CzesciDokumentu` (PDF, JPG) → tekst z OCR, dołączony do tekstu dokumentu z wyraźnym znacznikiem
     (np. `--- OCR: <nazwa/typ> ---`). Do modelu idzie wyłącznie tekst. `.eml` — treść maila + OCR załączników.
   - Węzeł `ocen` nadal **nie widzi surowego dokumentu** (obrona przed wstrzyknięciem poleceń) — nie zmieniać.
   - Uwierzytelnienie: `azure.identity` z łańcuchem, który lokalnie działa przez Azure CLI bez kilkunastosekundowych
     opóźnień (np. `ChainedTokenCredential(ManagedIdentityCredential(), AzureCliCredential())` albo `DefaultAzureCredential`
     z wyłączeniem zbędnych źródeł) i w etapie 6 przejdzie na Managed Identity bez zmiany kodu. **Żadnych kluczy API.**
   - `max_retries=1`; `reasoning_effort` konfigurowalny (`minimal` / `low`, domyślnie `low`); temperatura — gpt-5-mini
     może nie przyjmować `temperature` — sprawdź, nie ustawiaj, jeśli API odrzuca.
   - Metadane tokenów jak w Gemini (`MetadaneWywolania`).
   - Wyjątek limitu (429 z Azure OpenAI) musi się mapować na ten sam mechanizm przerwania przebiegu co RateLimit Gemini.
3. **Konfiguracja** (zmienne środowiskowe, `.env.example` uzupełnić): `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`
   (domyślnie `gpt-5-mini`), `AZURE_OPENAI_API_VERSION` (domyślnie `2025-04-01-preview`), `AZURE_OPENAI_REASONING`
   (domyślnie `low`), `AZURE_DOCINT_ENDPOINT`.
4. **API:** `MODEL_AGENTA=azure` w `api/ustawienia.py` / `api/agent_serwis.py::zbuduj_model`. Domyślny model API **zostaje
   atrapą**.
5. **Ewaluacja:** `ewaluacja/uruchom.py` przyjmuje model `azure` (te same bezpieczniki: maks. 6 wywołań na dokument,
   100 na przebieg, limit tokenów, przerwanie przy limicie). Koszt w wynikach: cena gpt-5-mini jako stała z komentarzem
   „cennik do weryfikacji” (przyjmij 0,25 USD / 1M wejście, 2,00 USD / 1M wyjście, jeśli w repo nie ma lepszego źródła).
   W wynikach dodatkowo liczba stron OCR i trafień cache.
6. **README:** sekcja „Etap 5” — Entra zamiast kluczy, OCR przed LLM, cache OCR, jak uruchomić.

## Testy

- Wszystkie dotychczasowe testy (131 passed / 1 skipped) przechodzą bez zmian w ich treści.
- Nowe testy jednostkowe **bez sieci** (mock klienta OCR i LLM): budowa wiadomości z OCR, cache (trafienie = brak wywołania),
  ponowienie 429 dokładnie raz, mapowanie 429 LLM na przerwanie, wybór modelu `azure` w API i ewaluacji, brak pola klucza w konfiguracji.
- Testy na żywo z markerem `azure` (domyślnie pomijane, jak `integracja`): OCR W08 zawiera „620”; `ModelAzure` na W01 daje
  poprawną klasyfikację i NIP.
- Wolno uruchomić na żywo **tylko** testy z markerem `azure` (2–3 dokumenty, koszt ułamek centa). **Pełnej ewaluacji 14 przypadków
  nie uruchamiać** — zrobi to koordynator.

## Zakazy

- Nie czytać plików z kluczami (`~/.gemini_api_key*`), nie wywoływać Gemini.
- Nie tworzyć, nie zmieniać i nie usuwać zasobów Azure (`az` tylko do odczytu, jeśli w ogóle).
- Nie zatrzymywać działającego API (:8000), serwera Next.js (:3000) ani kontenerów `underwriter_agent_demo-*`.
- Nie zmieniać `frontend/`, grafu (`agent/graf.py`) ani logiki węzłów poza tym, co konieczne do wstrzyknięcia OCR — każdą zmianę
  w `agent/wezly.py` uzasadnić w raporcie.
