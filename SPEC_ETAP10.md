# Etap 10 — moduł szkodowy: zgłoszenie szkody + RAG po OWU (Azure AI Search)

Cel: drugi typ dokumentu w tym samym agencie. Zgłoszenie szkody przechodzi przez OCR, ekstrakcję
i deterministyczne sprawdzenie polisy. Potem agent sprawdza pokrycie w **ogólnych warunkach
ubezpieczenia (OWU)** wyszukiwanych w Azure AI Search i zwraca decyzję **z cytatem paragrafu**,
którą zatwierdza człowiek. Zakres: RAG,
Vector Search, embeddingi, Azure AI Search, element agentowy (narzędzie wyszukiwania), domena szkód.

Termin: **niedziela 18.10.2026**. Wszystkie dane są fikcyjne, łącznie z OWU.

Ścieżka wniosku (underwriting) zostaje **bez zmian zachowania** — wszystkie dotychczasowe testy
i ewaluacja 14 wniosków mają dawać ten sam wynik.

## Przepływ w grafie

```
wczytaj → klasyfikuj ─WNIOSEK→ (bez zmian: ekstrahuj → waliduj → ocen → kontrola → zatwierdzenie)
                     ─INNY───→ zakoncz_inny
                     ─SZKODA─→ ekstrahuj_szkode → sprawdz_polise → szukaj_owu → ocen_pokrycie
                                → kontrola_cytatow → zatwierdzenie
```

- `TypDokumentu = Literal["WNIOSEK", "SZKODA", "INNY"]`; prompt klasyfikacji dostaje opis
  zgłoszenia szkody. `po_klasyfikacji` kieruje `SZKODA` do `ekstrahuj_szkode`.
- Błąd LLM albo `podejrzane_instrukcje=True` w `ekstrahuj_szkode` → prosto do `zatwierdzenie`
  z decyzją `SKIEROWANIE` (ten sam wzorzec co `po_ekstrakcji` dla wniosku).

### Węzły

1. **`ekstrahuj_szkode`** (LLM, structured output) → `EkstrakcjaSzkody { pola: PolaSzkody, podejrzane_instrukcje: bool }`.
   `PolaSzkody` (brak w dokumencie → `None`, model nie zgaduje):
   `nr_polisy`, `ubezpieczony`, `nip`, `data_zdarzenia` (RRRR-MM-DD), `data_zgloszenia`,
   `miejsce: Adres`, `przyczyna` (opis zdarzenia), `rodzaj_mienia: Literal["budynek","maszyny","zapasy"]`,
   `szacowana_kwota: int`, `zalaczniki: list[str]` (np. protokół straży, faktury, zdjęcia), `okolicznosci`.
2. **`sprawdz_polise`** (deterministyczny, bez LLM) — `dane/polisy.json` (~10 fikcyjnych polis:
   `nr_polisy`, `ubezpieczony`, `nip`, `okres_od`, `okres_do`, `su_budynki`, `su_maszyny`, `su_zapasy`).
   Wynik do stanu `wynik_polisy`:
   - brak polisy → `S01` (SKIEROWANIE),
   - data zdarzenia poza okresem → `S02` (ODMOWA, bez cytatu z OWU — przyczyna formalna),
   - kwota > SU dla danego rodzaju mienia → `S03` (SKIEROWANIE, nadwyżka do likwidatora),
   - zgłoszenie później niż N dni po zdarzeniu (N z OWU, np. 7) → `S04` — **tylko flaga dla LLM**,
     nie decyzja (OWU w demo pozwala na odmowę tylko, gdy opóźnienie utrudniło ustalenie szkody).
   Przy S01/S02 graf nie wywołuje LLM do oceny pokrycia — idzie prosto do `zatwierdzenie`
   (z pominięciem `kontrola_cytatow`, która dotyczy tylko decyzji z `ocen_pokrycie`).
   Przy S03 przepływ idzie dalej przez RAG (cytaty nadal potrzebne likwidatorowi); jeśli
   `ocen_pokrycie` zwróci `POKRYTA`, decyzja końcowa zmienia się na `SKIEROWANIE` z powodem `S03`.
3. **`szukaj_owu`** — zapytanie = `przyczyna` + `rodzaj_mienia` (+ `okolicznosci`); wyszukiwanie
   hybrydowe (BM25 + wektor), **top 5 fragmentów** do stanu `fragmenty_owu`.
4. **`ocen_pokrycie`** (LLM, structured output) → `OcenaPokrycia`:
   `decyzja: Literal["POKRYTA","ODMOWA","UZUPELNIENIE","SKIEROWANIE"]`,
   `cytaty: list[Cytat{paragraf, ustep, uzasadnienie}]`, `brakujace_dokumenty: list[str]`,
   `dodatkowe_zapytanie: str | None`.
   **Narzędzie:** jeśli model zwróci `dodatkowe_zapytanie` (np. definicja „pożaru”, wyłączenie),
   węzeł wykonuje jedno dodatkowe wyszukiwanie (top 3), dokleja wyniki i wywołuje model jeszcze
   raz z `dodatkowe_zapytanie` zablokowanym. **Maksymalnie 1 dodatkowe wyszukiwanie.**
   Mechanizm przez pole structured output (nie natywne function calling) — działa tak samo
   u każdego dostawcy i w atrapie. Prompt: decyzja wyłącznie na podstawie podanych fragmentów;
   `ODMOWA` wymaga cytatu wyłączenia; brak wymaganych dokumentów → `UZUPELNIENIE`.
5. **`kontrola_cytatow`** (deterministyczny) — każdy `Cytat` musi wskazywać `(paragraf, ustep)`
   obecne we fragmentach pobranych w tym przebiegu. Naruszenie → decyzja `SKIEROWANIE`,
   powód `cytat_spoza_kontekstu` w podsumowaniu. `POKRYTA` i `ODMOWA` bez żadnego cytatu → też `SKIEROWANIE`.
6. **`zatwierdzenie`** — istniejący węzeł; podsumowanie dla szkody zawiera: `typ_dokumentu`,
   `pola`, `wynik_polisy`, `decyzja`, `cytaty` (z pełną treścią fragmentu), `brakujace_dokumenty`,
   `kontrola_cytatow`. Brak migracji — `podsumowanie` jest już JSON.

### Model

`ModelAgenta` (Protocol) dostaje `ekstrahuj_szkode(czesci)` i `ocen_pokrycie(pola, wynik_polisy, fragmenty, dodatkowe=None)`.
Wymagane implementacje: **ModelAzure** i **atrapa** (`ewaluacja/atrapa.py`). ModelGemini: jeśli
wspólny kod promptów pozwala — tak; jeśli nie — jawny `NotImplementedError`, który węzeł zamienia
na `SKIEROWANIE` (nie cichy wynik).

## RAG

- **OWU:** `owu/owu_mienie_msp_v1.md` — fikcyjne OWU ubezpieczenia mienia MSP od ognia i innych
  zdarzeń losowych, spójne z produktem z `wytyczne/wytyczne_mienie_v1.yaml`. Struktura: `## § N. Tytuł`,
  ustępy numerowane `1.`, `2.`… Rozdziały: postanowienia ogólne, definicje (pożar, zalanie, huragan,
  kradzież z włamaniem, dewastacja…), przedmiot i zakres, **wyłączenia** (min. 8, w tym rażące
  niedbalstwo, zużycie, zalanie przez nieszczelny dach, mienie poza miejscem ubezpieczenia, brak
  zabezpieczeń przy kradzieży), suma ubezpieczenia, obowiązki po szkodzie (termin zgłoszenia,
  dokumenty: protokół straży/policji, faktury, zdjęcia), ustalanie odszkodowania, wypłata.
  Docelowo 15–20 stron; każdy przypadek ewaluacji musi mieć rozstrzygający paragraf.
- **`rag/fragmenty.py`** — podział po strukturze: **1 ustęp = 1 fragment**, metadane
  `paragraf`, `ustep`, `tytul`; `id = "p{paragraf}u{ustep}"`; treść fragmentu poprzedzona tytułem paragrafu.
- **`rag/wyszukiwarka.py`** — Protocol `Wyszukiwarka.szukaj(zapytanie, k) -> list[Fragment]` i dwie implementacje:
  - `WyszukiwarkaAzure` — Azure AI Search, zapytanie hybrydowe (`search_text` + `VectorizedQuery`),
    embedding zapytania z Azure OpenAI; auth `DefaultAzureCredential` (Managed Identity w Container Apps, `az login` lokalnie).
  - `WyszukiwarkaLokalna` — BM25 w pamięci po tym samym pliku OWU (bez sieci), do testów, CI i atrapy.
  - Wybór przez zmienną `WYSZUKIWARKA=azure|lokalna` (domyślnie `lokalna`, gdy brak `AZURE_SEARCH_ENDPOINT`).
- **`rag/indeksuj_owu.py`** — tworzy/aktualizuje indeks `owu-mienie-v1` (pola `id` klucz, `tresc`
  searchable, `paragraf`, `ustep`, `tytul` filterable/retrievable, `wektor` 1536 wym., HNSW) i wgrywa
  fragmenty z embeddingami. Idempotentny (upsert po `id`), wypisuje liczbę fragmentów i wersję OWU (SHA-256, 12 zn.).
- **Semantic ranker:** dostępny na planie Free (sprawdzone 14.10, sekcja Azure) — opcjonalny,
  przełączany `AZURE_SEARCH_SEMANTIC=1`; domyślnie hybryda bez niego.

## Azure (zasoby tworzy właściciel)

```powershell
$AZ = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
# AI Search, plan Free (0 zl; max 1 na subskrypcje, 50 MB, 3 indeksy)
& $AZ search service create -n uw-demo-search-xx1 -g rg-underwriter-demo -l polandcentral --sku free
# Embeddingi w istniejacym Azure OpenAI
& $AZ cognitiveservices account deployment create -n uw-demo-aoai-xx1 -g rg-underwriter-demo `
  --deployment-name text-embedding-3-small --model-name text-embedding-3-small --model-version 1 `
  --model-format OpenAI --sku-name GlobalStandard --sku-capacity 50
```

- **Stan po utworzeniu (14.10):** AI Search `uw-demo-search-xx1` powstał w **polandcentral**
  (swedencentral: `InsufficientResourcesAvailable`), endpoint `https://uw-demo-search-xx1.search.windows.net`,
  `semanticSearch: free` → **semantic ranker dostępny** (plan darmowy z limitem zapytań/mies.),
  `authOptions: aadOrApiKey` → **Entra/RBAC działa, kluczy nie używamy**. Embeddingi: wdrożenie
  `text-embedding-3-small` wersja 1 w SKU **GlobalStandard** (Standard niedostępny w swedencentral), 50k TPM.
  Semantic ranker: opcjonalny, zmienna `AZURE_SEARCH_SEMANTIC=1` (konfiguracja semantyczna `owu-semantyczna`
  na polu `tresc`, tytuł `tytul`); domyślnie wyłączony, żeby nie zjadać limitu w ewaluacji — w ewaluacji
  porównać 1 przebieg z i bez.
- **Role przypisane 14.10:** właściciel — Search Service Contributor + Search Index Data Contributor; `uw-demo-id` (API) — Search Index Data Reader (zakres: usługa Search).
- Klucze API wyłączone tam, gdzie się da (`--disable-local-auth` / auth RBAC na Search);
  role dla konta właściciela i Managed Identity API: `Search Index Data Contributor` (indeksowanie, właściciel),
  `Search Index Data Reader` (API), `Cognitive Services OpenAI User` (już jest).
- Plan Free AI Search może nie obsługiwać Managed Identity/RBAC w pełni — sprawdzić przy tworzeniu;
  jeśli wymaga kluczy, klucz zapytań w sekrecie Container Apps (nie w repo) i zapisać to tutaj jako odstępstwo.
- Koszt: AI Search Free 0 zł; embeddingi ~0,02 USD / 1 mln tokenów — indeksacja OWU i ewaluacja to grosze.
- Bicep (`infra/main.bicep`): **nie dopisywać** AI Search w tym etapie — nowe zasoby trafią do
  Terraform w punkcie 4 pakietu. Zmienne środowiskowe API (`AZURE_SEARCH_ENDPOINT`,
  `AZURE_SEARCH_INDEX`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, `WYSZUKIWARKA`) dopisać w Bicepie
  w sekcji env Container App, bo deploy idzie z niego.

## API i UI

- `POST /wnioski` przyjmuje zgłoszenie szkody bez zmian (typ rozpoznaje graf).
- `POST /wnioski/{id}/decyzja` — walidacja wartości decyzji rozszerzona o `POKRYTA`
  (pozostałe nazwy są wspólne); dla szkody dozwolone tylko decyzje szkodowe.
- Frontend, strona dokumentu: gdy `typ_dokumentu == "SZKODA"` — sekcja „Ocena pokrycia”:
  decyzja, wynik sprawdzenia polisy, **cytowane paragrafy z pełną treścią**, brakujące dokumenty,
  wynik kontroli cytatów. Lista: kolumna/etykieta typu dokumentu. Zatwierdzanie bez zmian.

## Ewaluacja

- `dane/szkody/` — **12 fikcyjnych zgłoszeń** (PDF z generatora, jak wnioski) + `dane/szkody/oczekiwane/*.json`
  z `decyzja`, `paragrafy_oczekiwane` (lista `§N ust. M`, wystarczy trafić jeden) i kluczowymi polami.
  Pokrycie: min. 3 × POKRYTA, 3 × ODMOWA (różne wyłączenia), 2 × UZUPELNIENIE, 2 × SKIEROWANIE
  (brak polisy, kwota > SU), 1 × zdarzenie poza okresem (S02 → ODMOWA), 1 × próba wstrzyknięcia
  poleceń (→ SKIEROWANIE). Razem 12.
- `ewaluacja/uruchom.py --modul szkody` (domyślnie `wnioski` — dotychczasowe zachowanie).
  Metryki: `decyzje_ok`, `cytat_trafiony` (oczekiwany paragraf wśród cytatów), `recall_wyszukiwania@5`
  (oczekiwany paragraf wśród pobranych fragmentów — mierzy sam retrieval, osobno od LLM),
  `kontrola_cytatow_odrzucila`, `dodatkowe_zapytania`, tokeny, koszt, czas.
- MLflow: ten sam eksperyment, tag `modul=szkody`, parametry `wersja_owu`, `wyszukiwarka`, `top_k`.
- Wynik z jednego przebiegu to nie dowód (lekcja z etapu 8): raportować **2 przebiegi** na prawdziwym modelu.

## Testy (offline, bez Azure)

- Podział OWU: liczba fragmentów, unikalne `id`, każdy fragment ma `paragraf`/`ustep`.
- `WyszukiwarkaLokalna`: dla 3 zapytań oczekiwany paragraf w top 5.
- `sprawdz_polise`: S01–S04 na granicach (dzień rozpoczęcia/końca okresu, kwota równa SU).
- `kontrola_cytatow`: cytat spoza kontekstu → SKIEROWANIE; ODMOWA bez cytatu → SKIEROWANIE; poprawny → bez zmian.
- `ocen_pokrycie`: atrapa zwraca `dodatkowe_zapytanie` → dokładnie 1 dodatkowe wyszukiwanie,
  drugi raz nie (limit).
- Graf: szkoda przez atrapę dochodzi do `zatwierdzenie` z cytatami; wniosek — dotychczasowe testy bez zmian.
- `WyszukiwarkaAzure`: test z atrapą klienta SDK (kształt zapytania hybrydowego), bez sieci.

## Poza zakresem (osobne punkty pakietu do 18.10)

- Metryki Azure AI Foundry (groundedness, relevance), Model Registry — punkt 3.
- Terraform — punkt 4. Service Bus / KEDA — punkt 5. AKS — punkt 6. Monitoring — punkt 7.
- Pliki etapu 9 (`deploy/`, `tests/test_helm.py`, CI job `k8s`) — kończy je inna sesja; nie ruszać.

## Kryteria akceptacji

- `pytest` — wszystkie dotychczasowe testy przechodzą bez zmian, nowe przechodzą offline.
- `python ewaluacja/uruchom.py --atrapa` (wnioski) — wynik identyczny jak przed etapem.
- `python ewaluacja/uruchom.py --atrapa --modul szkody` — 12/12 na atrapie, run w MLflow z `modul=szkody`.
- `python rag/indeksuj_owu.py` na Azure → indeks z oczekiwaną liczbą fragmentów; zapytanie testowe
  zwraca oczekiwany paragraf.
- Ewaluacja na gpt-5-mini + Azure AI Search: 2 przebiegi, wyniki i koszt w MLflow (Azure ML);
  `recall_wyszukiwania@5` raportowany osobno od `decyzje_ok`.
- Na wdrożonej aplikacji: upload zgłoszenia szkody → strona pokazuje decyzję z cytatami →
  zatwierdzenie z tożsamością Easy Auth → wpis w audycie.
- README: sekcja „Moduł szkodowy (RAG)” — architektura, jak liczona trafność cytatu, kontrola cytatów
  jako zabezpieczenie przed halucynacją; `docs/AI_ACT.md` — dopisek o ocenie szkód (decyzja zawsze
  zatwierdzana przez człowieka).
