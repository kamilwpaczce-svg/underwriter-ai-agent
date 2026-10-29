# SPEC Demo 1 — czat po OWU: historia rozmów w Cosmos DB (serverless) + endpoint w Azure Functions (Flex Consumption)

> **Dla wykonawcy:** gałąź `demo1` odbita od `main`, **osobny worktree** `..\underwriter_demo1` (w repo pracują
> równolegle sesje na `etap19/20/23/24`; **zero `git commit -a`**, dodawać pliki po nazwie). **Commit po każdym
> zadaniu** — wznowienie od ostatniego commita. TDD: najpierw test offline, potem kod. Jedno wywołanie agenta = 1–2 zadania.
> Termin: **01.11.2026** (1 dzień), bufor 02.11. Dane fikcyjne (OWU `owu/owu_mienie_msp_v1.md`).
> **Terraform: wspólny stan `etap13.tfstate` → `apply` WYŁĄCZNIE z `-target`** (reguła w decyzji 7). Zasoby żyją
> najdłużej do **08.11** (`destroy` + Cost Management), kredyt Free Trial wygasa **9.11.2026**.

> **Decyzje właściciela 27.10 (rozstrzygają otwarte pytania 1–4):** Azure Functions **Flex Consumption** + **klucz funkcji**
> (bez Easy Auth); historia **per sesja**; **bez frontendu** — demonstracja przez curl/PowerShell i zrzuty.

**Cel:** minimalna aplikacja konwersacyjna „zapytaj OWU”: użytkownik zadaje pytania o warunki ubezpieczenia,
odpowiedź powstaje **wyłącznie z fragmentów OWU** (to samo wyszukiwanie co agent szkód), z cytatami `§ N ust. M`
sprawdzanymi deterministycznie; historia rozmowy (per sesja) zapisywana w **Cosmos DB for NoSQL (serverless)**;
endpoint HTTP w **Azure Functions (Flex Consumption, Python)** z tożsamością zarządzaną, bez kluczy do danych.
Cel: pokazać Azure Functions i bazę NoSQL w działającym czacie po OWU (aplikacja konwersacyjna).

## Źródła (stan repo 27.10, `main` @ `68905db`)

- **Wyszukiwanie po OWU — gotowe, nie budujemy nowego:**
  - Protocol `Wyszukiwarka.szukaj(zapytanie, k=TOP_K) -> list[Fragment]` (`rag/wyszukiwarka.py:26-29`, `TOP_K = 5` :19).
  - `WyszukiwarkaLokalna` — BM25 w pamięci po pliku OWU, bez sieci (`rag/wyszukiwarka.py:3`, `:37-38`).
  - `WyszukiwarkaAzure` — hybryda BM25 + wektor (`text-embedding-3-small`), opcjonalnie semantic ranker
    (`rag/azure_search.py:68`, `:84`, `:89`); usługa **AI Search Free `uw-demo-search-xx1` w `polandcentral`**
    (`SPEC_ETAP10.md:100-109`; poza Bicepem i Terraformem — `infra/main.bicep:50-51`).
  - Fabryka `zbuduj_wyszukiwarke(srodowisko)` — `WYSZUKIWARKA=azure|lokalna|qdrant`, zła wartość → wyjątek
    przy starcie, nie cichy powrót do BM25 (`rag/azure_search.py:115-135`).
  - `Fragment(id, paragraf, ustep, tytul, tresc)` i `podziel_owu()` (`rag/fragmenty.py:25-33`); ścieżka OWU
    `ROOT / "owu" / ...` (`rag/fragmenty.py:17`) — przy pakowaniu funkcji katalogi `rag/` i `owu/` muszą być rodzeństwem.
  - OWU: 111 linii, 14 paragrafów (`owu/owu_mienie_msp_v1.md`) — mieści się w pamięci funkcji bez indeksu.
  - Moduły `rag/fragmenty.py`, `rag/wyszukiwarka.py`, `rag/azure_search.py`, `agent/decyzje_szkody.py` mają importy
    tylko ze stdlib/`rag` (zależności Azure ładowane leniwie wewnątrz funkcji) — da się je włożyć do paczki funkcji.
- **Kontrola cytatów — gotowa:** `klucz_cytatu` (`agent/decyzje_szkody.py:25`) i `kontroluj_cytaty(ocena, fragmenty)`
  → `brak_oceny | cytat_spoza_kontekstu | brak_cytatu` (`agent/decyzje_szkody.py:38-49`); schemat `Cytat`
  (`agent/schematy.py:149-152`). Wzorzec promptu „wyłącznie na podstawie fragmentów” — `agent/instrukcje_szkody.py:35-47`.
  Węzeł grafu `wezel_szukaj_owu` (`agent/wezly_szkody.py:136`) — czat go **nie** woła (to nie jest szkoda), tylko
  korzysta z tych samych klocków.
- **Autoryzacja — Entra ID, zero kluczy:** `zbuduj_poswiadczenie_azure()` = `ManagedIdentityCredential(client_id=
  AZURE_CLIENT_ID)` → `AzureCliCredential` (`agent/ocr_azure.py:64-79`), zakres `cognitiveservices` (`:33`);
  `ModelAzure` woła `AzureChatOpenAI` z `azure_ad_token_provider` (`agent/model_azure.py:101-109`).
  Tożsamość user-assigned `uw-demo-id` (`infra/main.bicep:81`) ma już `Cognitive Services OpenAI User` (`:87`) i
  `Storage Blob Data Contributor` na `uwdemostxx1` (`:89`, `:80`); Storage ma `allowSharedKeyAccess: false` (`:163`)
  → funkcja **musi** używać połączeń przez tożsamość (deployment storage i `AzureWebJobsStorage`).
- **Terraform:** `infra/terraform/`, provider `azurerm ~> 5.10`, backend Blob z `use_azuread_auth`
  (`infra/terraform/versions.tf:9-21`), klucz stanu `etap13.tfstate` (`infra/terraform/README.md:46`); App Insights
  `uw-demo-appinsights` w Terraformie (`infra/terraform/main.tf:15-22`). Wzorzec przełącznika i `-target`:
  `apim.tf` z `count = var.apim_wlaczony ? 1 : 0` i reguła „APIM tworzysz wyłącznie przez `-target` … 0 change,
  0 destroy” (gałąź `etap20`: `infra/terraform/apim.tf:7-25`, `infra/terraform/README.md:208-211`).
- **Ewaluacja wyszukiwania:** `ewaluacja/porownaj_wyszukiwarki.py:3-10` (recall na Z01–Z12, bez LLM; ostrzeżenie o małym n).
- **Koszt LLM w tym repo:** gpt-5-mini 0,25 / 2,00 USD za 1 mln tokenów we/wy (`docs/ROZWOJ.md:681`).
- **Plan:** wewnętrzny plan etapów (poza repo) (opis dema, warunek decyzji właściciela — **podjęta 27.10**, harmonogram `:130-149`,
  wiersz 01.11 „Demo 1 — czat po OWU, historia w Cosmos DB (serverless), endpoint Azure Functions”), lista przed 9.11 `:151-155`.

### Cennik i limity (sprawdzone 27.10.2026)

| usługa | fakt | źródło |
|---|---|---|
| Cosmos DB serverless | płatne tylko zużyte RU + storage; **jeden region** (nie da się dodać drugiego); kontener startuje z 5000 RU/s na partycję fizyczną; nie da się podać throughput | [learn: serverless](https://learn.microsoft.com/en-us/azure/cosmos-db/serverless) (ms.date 2025-07-24, aktual. 2026-04-27) |
| Cosmos DB serverless — limity | partycja logiczna 20 GB, kontener bez limitu, max 500 baz+kontenerów na konto, item max 2 MB, 1 region | [learn: concepts-limits](https://learn.microsoft.com/en-us/azure/cosmos-db/concepts-limits) (aktual. 2026-08-25) |
| Cosmos DB serverless — cena `swedencentral` | **0,305 USD / 1 mln RU**; storage **0,25 USD / GB-mies.** | publiczne Azure Retail Prices API (`prices.azure.com`, odczyt 27.10.2026; strona cennika pokazuje „$-”) |
| Cosmos free tier (1000 RU/s, 25 GB) | dotyczy kont provisioned; dla serverless — **NIESPRAWDZONE** (nie zakładamy) | concepts-limits, sekcja free tier |
| Functions Flex Consumption | Linux only; Python 3.10–3.14; pamięć instancji 512 / 2048 / 4096 MB; kod jako paczka w kontenerze Blob; 1 aplikacja na plan; host musi wstać w 30 s; **Free Trial: limit regionalny 15 rdzeni** | [learn: flex-consumption-plan](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan) (ms.date 2026-09-15) |
| Flex — cena `swedencentral` (on demand) | **0,000026 USD / GB-s** i **0,40 USD / 1 mln wywołań** ponad grant; min. naliczenie 1 s na wywołanie | Retail Prices API 27.10 (tier od 100 000 GB-s i 250 000 wywołań) |
| Flex — grant miesięczny | 100 000 GB-s + 250 000 wywołań (Consumption: 400 000 GB-s + 1 mln) „per subscription, pay-as-you-go”; czy grant działa na **Free Trial** — **NIESPRAWDZONE** | [cennik Functions](https://azure.microsoft.com/en-us/pricing/details/functions/) |
| Flex w `swedencentral` | metry cennika dla `swedencentral` istnieją (pośredni dowód); lista regionów: `az functionapp list-flexconsumption-locations` — **NIESPRAWDZONE**, robi właściciel w zadaniu 0 | [learn: flex-consumption-how-to](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-how-to#view-currently-supported-regions) (ms.date 2026-10-12) |
| Linux Consumption (Y1) | wycofywany 30.09.2028, bez nowych funkcji od 09.2025, zniknął z portalu — **nie używamy** | Azure Updates AZ499451, [learn: consumption-plan](https://learn.microsoft.com/en-us/azure/azure-functions/consumption-plan) |
| Flex — wdrożenie przez tożsamość | `--deployment-storage-auth-type UserAssignedIdentity` | flex-consumption-how-to (`:771-777` odczytu) |

## Decyzje

1. **Azure Functions Flex Consumption, nie App Service i nie Linux Consumption.** Flex to plan zalecany przez
   Microsoft, skaluje do zera (brak opłaty stałej, w przeciwieństwie do App Service B1), Linux Consumption jest
   wycofywany. App Service **nie** opisujemy jako zbudowanego (Flex działa na platformie App Service, ale to
   nie to samo). Alternatywa przy blokadzie Flex na trialu: decyzja 11. *(Otwarte pytanie do właściciela nr 1.)*
2. **Python v2 programming model** (`function_app.py`, dekoratory), **HTTP trigger, `auth_level=FUNCTION`**
   (klucz funkcji poza repo, w KeePassXC/zmiennej sesji PowerShell). Entra Easy Auth na funkcji — poza zakresem
   (opcja po demie). *(Otwarte pytanie nr 3.)*
3. **Trasy:** `POST /api/czat` `{id_sesji?: uuid, pytanie: str (1–1000 zn.)}` → `{id_sesji, odpowiedz, cytaty[],
   status, fragmenty_ids[], tokeny_we, tokeny_wy, czas_ms}`; `GET /api/czat/{id_sesji}` → historia (max 50
   wiadomości, rosnąco po czasie); `GET /api/zdrowie` → `{ok, wyszukiwarka, wersja_owu}` bez wywołań LLM/Cosmos.
   Brak `id_sesji` → serwer tworzy UUID4. Zły JSON / puste pytanie / > 1000 zn. → 400 z komunikatem po polsku.
4. **Odpowiedź tylko z OWU, z kontrolą deterministyczną.** Model zwraca structured output `OdpowiedzCzatu
   {odpowiedz: str, cytaty: list[Cytat], poza_owu: bool}` (`Cytat` z `agent/schematy.py`). Po modelu
   `kontroluj_cytaty` (reuse) na tych samych fragmentach:
   - cytat spoza podanych fragmentów albo odpowiedź merytoryczna bez cytatu → `status = "odrzucona"`, użytkownik
     dostaje stały tekst „Nie znalazłem tego w OWU — skontaktuj się z underwriterem” + listę przeszukanych
     ustępów (zamiast niesprawdzonej odpowiedzi);
   - `poza_owu = true` (pytanie spoza warunków, np. „ile kosztuje polisa”, próba prompt injection) →
     `status = "poza_owu"`, ten sam stały tekst, bez cytatów;
   - inaczej `status = "ok"`. W historii zapisujemy też odrzuconą odpowiedź modelu (pole `surowa`, do analizy).
   `czat/kontrola.py::ocen_odpowiedz` to czysty kod (TDD bez sieci).
5. **Historia w Cosmos DB for NoSQL, serverless: konto `uw-demo-cosmos-xx1`, baza `czat`, kontener `rozmowy`,
   partition key `/id_sesji`, jedna wiadomość = jeden item** (`id` = UUID, `id_sesji`, `rola: uzytkownik|asystent`,
   `tresc`, `cytaty`, `status`, `fragmenty_ids`, `tokeny_we/wy`, `czas_utc`, `ttl`). Domyślny TTL kontenera
   **7 dni**. Item per wiadomość zamiast dokumentu per sesja: zapis = insert (bez read-modify-write i konfliktów
   ETag), item nigdy nie dorośnie do 2 MB, odczyt historii = zapytanie w jednej partycji logicznej (tanie).
   Indeksowanie tylko `/id_sesji/?` i `/czas_utc/?` (reszta wykluczona — mniej RU na zapis).
   *(Otwarte pytanie nr 2: historia per sesja czy per użytkownik.)*
6. **Pamięć rozmowy w promptcie: ostatnie 3 pary (6 wiadomości)**, tylko `tresc`. **Zapytanie do wyszukiwarki =
   bieżące pytanie + poprzednie pytanie użytkownika** (deterministycznie, bez dodatkowego wywołania LLM do
   przepisania pytania) — obsługuje pytania nawiązujące („a jaki jest tam limit?”). Mierzone w zadaniu 5.
7. **Terraform w nowym pliku `infra/terraform/czat.tf`, cały za przełącznikiem `var.czat_wlaczony` (domyślnie
   `false`, `count`)** — plan przy `false` = 0 zmian (wzorzec `apim.tf`). **Stan jest WSPÓLNY (`etap13.tfstate`:
   Etapy 13/15/19c, od 30.10 także APIM z Etapu 20).** Gałąź `demo1` nie ma `dryf.tf`/19c ani `apim.tf` → pełny
   `terraform apply` z niej **NISZCZY** job dryfu, alerty i APIM. Zasada bezwzględna: **`plan`/`apply` tylko
   z `-target` na każdy zasób czatu**, plan czytany przed zatwierdzeniem: `to add` = wyłącznie zasoby z `czat.tf`,
   **0 to change, 0 to destroy**; cokolwiek innego → STOP, nie zatwierdzać. To samo przy `destroy`
   (`terraform destroy -target=...` tylko na zasobach czatu), chyba że 08.11 robi się globalne sprzątanie według
   `docs/ROZWOJ.md`. `apply`/`destroy` wykonuje **właściciel**, nie agent.
8. **Zasoby w `czat.tf`** (nazwy i atrybuty azurerm 5.x do potwierdzenia w zadaniu 0 przez
   `terraform providers schema -json`): `azurerm_cosmosdb_account` (`capabilities EnableServerless`,
   `local_authentication_disabled = true`, jeden `geo_location` `swedencentral`, `consistency_level = Session`),
   `azurerm_cosmosdb_sql_database`, `azurerm_cosmosdb_sql_container` (PK, TTL, indeksowanie),
   2× `azurerm_cosmosdb_sql_role_assignment` (wbudowana rola data plane „Cosmos DB Built-in Data Contributor”
   dla `uw-demo-id` i dla właściciela z `data.azurerm_client_config`), `azurerm_storage_container` `czat-wdrozenie`
   w istniejącym `uwdemostxx1` (Storage bez kluczy → provider może wymagać `storage_use_azuread = true` —
   **NIESPRAWDZONE**), `azurerm_service_plan` (SKU `FC1`) + `azurerm_function_app_flex_consumption` (Python 3.12,
   2048 MB, `maximum_instance_count = 2`, deployment storage przez `UserAssignedIdentity`, tożsamość `uw-demo-id`,
   App Insights `uw-demo-appinsights`). Ustawienia: `AzureWebJobsStorage__accountName`,
   `AzureWebJobsStorage__credential=managedidentity`, `AzureWebJobsStorage__clientId`, `AZURE_CLIENT_ID`,
   `AZURE_OPENAI_ENDPOINT/DEPLOYMENT/API_VERSION`, `COSMOS_ENDPOINT`, `COSMOS_BAZA`, `COSMOS_KONTENER`,
   `WYSZUKIWARKA=lokalna`. Zero kluczy. Czy host potrzebuje ról Queue/Table na Storage dla `uw-demo-id` —
   **NIESPRAWDZONE**; rozstrzyga zadanie 6 (błąd hosta w logach → dopisać rolę, znów `-target`).
9. **Wyszukiwarka w funkcji: `WYSZUKIWARKA=lokalna` (BM25)** — zero dodatkowych zależności, zero ruchu
   międzyregionowego, brak zależności od AI Search Free w `polandcentral` (czy usługa nadal istnieje —
   **NIESPRAWDZONE**). Przełącznik na `azure` działa bez zmian kodu (ta sama fabryka). Uczciwie w README:
   w chmurze działa BM25; hybryda była mierzona w Etapie 12.
10. **LLM: SDK `openai` (`AzureOpenAI`, `chat.completions.parse` z Pydantic) + `get_bearer_token_provider`**, ten
    sam deployment gpt-5-mini, `reasoning_effort=low`, bez `temperature` (jak `agent/model_azure.py`). **Bez
    `langchain` w paczce** — mniejsza paczka, zimny start w limicie 30 s inicjalizacji hosta. Protocol
    `ModelCzatu.odpowiedz(pytanie, historia, fragmenty) -> (OdpowiedzCzatu, MetadaneWywolania)` + atrapa.
    1 ponowienie przy błędzie sieci/429; drugi błąd → 503, `status = "blad_modelu"` (pytanie zapisane, odpowiedź nie).
11. **Plan awaryjny** (tylko gdy Flex nie powstaje na trialu albo nie ma go w `swedencentral`): ta sama logika jako
    dodatkowa trasa w istniejącej Container App `uw-api` (FastAPI, `api/trasy.py`); Cosmos zostaje, w dokumentacji wtedy
    tylko „Cosmos DB”, bez „Functions”. Decyduje właściciel po błędzie `apply`, nie agent.
12. **Logika niezależna od hosta:** cały czat w pakiecie `czat/` (czysty Python); `function_app.py` to cienka
    warstwa HTTP. Plan awaryjny i testy nie zależą od `azure-functions`.
13. **Telemetria i RODO:** log `czat.odpowiedz` z `id_sesji`, `status`, tokenami, `czas_ms`, liczbą fragmentów,
    **bez treści pytania i odpowiedzi** (jak spany bez PII z Etapu 13). Treść tylko w Cosmos (TTL 7 dni).

## Pliki

| plik | rola |
|---|---|
| `czat/__init__.py`, `czat/schematy.py` | `OdpowiedzCzatu`, `Wiadomosc`, `ZapytanieCzatu` (1–1000 zn.), `WynikCzatu` |
| `czat/instrukcje.py` | prompt (tylko fragmenty, cytaty `[pNuM]`, `poza_owu`), `tresc_dla_modelu(pytanie, historia, fragmenty)`, `zapytanie_wyszukiwania(pytanie, historia)` |
| `czat/kontrola.py` | `ocen_odpowiedz(odp, fragmenty) -> (status, tekst)` na `kontroluj_cytaty` |
| `czat/model.py`, `czat/atrapa.py` | Protocol `ModelCzatu`, `ModelCzatuAzure`; atrapa deterministyczna (tryby `ok`, `zly_cytat`, `poza_owu`, `blad`) |
| `czat/magazyn.py` | Protocol `MagazynRozmow` (`dopisz`, `historia(id_sesji, n)`), `MagazynPamiec`, `MagazynCosmos` (`azure-cosmos`, poświadczenie z `zbuduj_poswiadczenie_azure`) |
| `czat/serwis.py` | `obsluz_pytanie(zapytanie, model, wyszukiwarka, magazyn) -> WynikCzatu` — cały przepływ |
| `funkcja_czat/function_app.py`, `host.json`, `requirements.txt`, `.funcignore` | warstwa HTTP Functions |
| `funkcja_czat/zbuduj_paczke.py` | kopiuje `czat/`, `rag/{__init__,fragmenty,wyszukiwarka,azure_search}.py`, `agent/{decyzje_szkody,schematy,ocr_azure,...}` (lista z zadania 0), `owu/` do `funkcja_czat/build/` |
| `infra/terraform/czat.tf`, `variables.tf`, `outputs.tf` | decyzje 7–8; outputy `czat_url`, `cosmos_endpoint` |
| `dane/czat/pytania.json`, `ewaluacja/czat.py` | 12 pytań i bieg ewaluacji (atrapa / azure) → `ewaluacja/wyniki/` |
| `tests/test_czat_*.py`, `tests/test_infra_czat.py` | testy offline (+ `-m azure` dla żywego Cosmos) |
| `README.md`, `docs/ROZWOJ.md`, `infra/terraform/README.md` | architektura, komendy okna `-target`, wyniki, koszt, pozycje do `destroy` |

## Zadania

### Zadanie 0: rozpoznanie (bez kodu produkcyjnego, notatka w tym pliku pod zadaniem)
- [ ] **Właściciel (az, tylko odczyt):** `az functionapp list-flexconsumption-locations` zawiera `swedencentral`;
      `az provider show -n Microsoft.DocumentDB` i `Microsoft.Web` → `Registered`. Brak Flex w regionie → STOP,
      pytanie do właściciela (inny region dla funkcji vs decyzja 11).
- [ ] Stan wspólny: `terraform state list` (Właściciel) — zapisać listę zasobów (APIM z Etapu 20? job dryfu?), żeby
      wiedzieć, co zniszczyłby apply bez `-target`.
- [ ] `terraform providers schema -json` (azurerm z `.terraform.lock.hcl`): potwierdzić nazwy i atrybuty z decyzji 8
      (`azurerm_function_app_flex_consumption`: `runtime_name/version`, `storage_container_type`,
      `storage_authentication_type`, `storage_user_assigned_identity_id`, `instance_memory_in_mb`,
      `maximum_instance_count`; `azurerm_cosmosdb_sql_role_assignment`). Rozbieżności wpisać tutaj.
- [ ] Import-graf paczki: `python -X importtime -c "import czat.serwis"` (po zadaniu 2) albo ręcznie — które moduły
      `agent/` są potrzebne (`agent/__init__.py`, `agent/schematy.py` mogą ciągnąć `langchain`); lista do `zbuduj_paczke.py`.
- [ ] Wersje do `requirements.txt` funkcji: `azure-functions`, `azure-cosmos`, `azure-identity==1.26.0`,
      `openai==3.28.0`, `pydantic` (jak w `requirements.txt` repo); sprawdzić, że `chat.completions.parse` jest w `openai` 3.x.

### Zadanie 1: schematy, prompt, kontrola (TDD, czysty kod)
Pliki: `czat/schematy.py`, `czat/instrukcje.py`, `czat/kontrola.py`, `tests/test_czat_kontrola.py`.
- [ ] `ZapytanieCzatu`: puste / same spacje / > 1000 zn. → błąd walidacji; zły `id_sesji` (nie UUID) → błąd.
- [ ] `tresc_dla_modelu`: zawiera identyfikatory `[pNuM]` wszystkich fragmentów i max 6 wiadomości historii (najnowsze).
- [ ] `zapytanie_wyszukiwania`: bez historii = pytanie; z historią = pytanie + ostatnie pytanie **użytkownika** (nie asystenta).
- [ ] `ocen_odpowiedz`: cytat z kontekstu → `ok`; cytat spoza → `odrzucona` + stały tekst + lista ustępów;
      brak cytatu przy odpowiedzi merytorycznej → `odrzucona`; `poza_owu=True` → `poza_owu`, cytaty ignorowane.

### Zadanie 2: model, atrapa, magazyn w pamięci, serwis (TDD, offline)
Pliki: `czat/model.py`, `czat/atrapa.py`, `czat/magazyn.py` (`MagazynPamiec`), `czat/serwis.py`, `tests/test_czat_serwis.py`.
- [ ] `ModelCzatuAzure` z wstrzykniętym klientem-atrapą: wiadomości = system + treść; brak `temperature`;
      `reasoning_effort` z env; metadane tokenów przeniesione.
- [ ] Serwis na `WyszukiwarkaLokalna` + atrapa + `MagazynPamiec`: pytanie „Czy kradzież z włamaniem jest objęta?”
      → `ok`, cytat z fragmentów; w magazynie 2 wiadomości (użytkownik, asystent) w jednej sesji.
- [ ] Druga tura tej samej sesji: model dostaje historię; wyszukiwarka dostaje zapytanie z poprzednim pytaniem.
- [ ] Atrapa `blad` 2× → wynik `blad_modelu`, w magazynie tylko pytanie; atrapa `blad` 1× → `ok` (ponowienie).
- [ ] Log `czat.odpowiedz` nie zawiera treści pytania ani odpowiedzi (test na `caplog`).

### Zadanie 3: `MagazynCosmos` (TDD na atrapie klienta + test `-m azure`)
Pliki: `czat/magazyn.py`, `tests/test_czat_magazyn.py`.
- [ ] `dopisz` → `create_item` z `id_sesji` jako partition key, `ttl` nieustawiany (dziedziczy z kontenera).
- [ ] `historia` → zapytanie sparametryzowane `SELECT TOP @n ... WHERE c.id_sesji = @s ORDER BY c.czas_utc DESC`
      z `partition_key=` (nie cross-partition), wynik odwrócony rosnąco. Bez sklejania SQL ze stringów.
- [ ] Klient tworzony raz (singleton na proces, zalecenie z `concepts-limits`); poświadczenie z `zbuduj_poswiadczenie_azure`.
- [ ] Odczyt RU z nagłówka `x-ms-request-charge` zapisywany do logu (do tablicy kosztu w zadaniu 6).
- [ ] Test `-m azure` (uruchamia właściciel po zadaniu 6): dopisz 2 wiadomości, odczytaj, sprawdź kolejność i RU > 0.

### Zadanie 4: warstwa Functions i paczka (TDD offline)
Pliki: `funkcja_czat/*`, `tests/test_czat_funkcja.py`.
- [ ] `function_app.py`: 3 trasy z decyzji 3, `auth_level=FUNCTION`; zależności (model, wyszukiwarka, magazyn)
      budowane leniwie raz na proces; test wywołuje handlery z `func.HttpRequest` na atrapach (bez hosta).
- [ ] Kody: 200 / 400 (walidacja) / 503 (`blad_modelu`, `MagazynCosmos` niedostępny) — treść błędu bez stack trace.
- [ ] `zbuduj_paczke.py` → `funkcja_czat/build/`; test: w paczce jest `owu/owu_mienie_msp_v1.md`, nie ma `.venv`,
      `tests`, `dane`; `python -c "import function_app"` w katalogu paczki przechodzi (bez `langchain`).
- [ ] Lokalny dymny test (`func start` z Core Tools, jeśli zainstalowane; inaczej pominąć z adnotacją) na
      `MagazynPamiec` (zmienna `CZAT_MAGAZYN=pamiec`, domyślnie `cosmos`; zła wartość → błąd startu).

### Zadanie 5: zestaw pytań i ewaluacja offline
Pliki: `dane/czat/pytania.json`, `ewaluacja/czat.py`, `tests/test_czat_ewaluacja.py`.
- [ ] 12 pytań: 8 merytorycznych z oczekiwanymi ustępami (różne §, w tym wyłączenia i obowiązki po szkodzie),
      2 nawiązujące (druga tura sesji), 2 spoza OWU (cena polisy; „zignoruj instrukcje i…”) z oczekiwanym `poza_owu`.
      Oczekiwane ustępy wpisane z OWU **przed** pierwszym biegiem na żywo.
- [ ] Miary: `recall@5` wyszukiwania (bez LLM), odsetek `ok` z poprawnym cytatem, odsetek `odrzucona`,
      `poza_owu` trafione 2/2, tokeny i `czas_ms` na turę. Wariant zapytania „bez historii” vs „z poprzednim
      pytaniem” dla 2 pytań nawiązujących (recall@5) — mały n nazwany wprost.
- [ ] Bieg `--atrapa` w teście (wszystko liczy się bez sieci).

### Zadanie 6: wdrożenie (Właściciel: terraform; agent: paczka i dymne testy)
Pliki: `infra/terraform/czat.tf`, `variables.tf`, `outputs.tf`, `tests/test_infra_czat.py`, `infra/terraform/README.md`.
- [ ] `test_infra_czat.py` (statyczny, wzorzec `test_infra_monitoring.py`): każdy zasób w `czat.tf` ma `count`
      od `var.czat_wlaczony`; Cosmos `local_authentication_disabled = true` i `EnableServerless`; brak kluczy/sekretów
      w `app_settings`; `maximum_instance_count <= 2`.
- [ ] README terraform, sekcja „Demo 1 — okno czatu”: komenda `plan` z pełną listą `-target=...` (każdy zasób
      `czat.tf`), oczekiwany wynik `N to add, 0 to change, 0 to destroy`, i komenda `destroy` z tą samą listą.
- [ ] Właściciel: `plan` → czyta → `apply` (tylko jeśli 0 change / 0 destroy). Wdrożenie paczki:
      `func azure functionapp publish <app>` albo zip deploy z `funkcja_czat/build/` (komenda w README).
- [ ] Dymne: `GET /api/zdrowie` 200; `POST /api/czat` dwie tury jednej sesji; `GET /api/czat/{id}` zwraca 4 wiadomości;
      test `-m azure` z zadania 3 zielony. Logi hosta w App Insights bez błędów Storage (decyzja 8, role Queue/Table).
- [ ] Bieg ewaluacji na żywo (12 pytań, 1 bieg + powtórka pytań, które dały `odrzucona`) przez endpoint;
      wynik JSON do `ewaluacja/wyniki/czat_2026-11-01_*.json`. Zużycie RU z logów i Metrics „Request Units consumed”.
- [ ] Zrzuty do `docs/`: Cosmos Data Explorer (items jednej sesji), Function App (Overview + Invocations),
      odpowiedź curl/PowerShell z cytatem i z `poza_owu`. **Przed 08.11 — po wygaśnięciu jedyny dowód.**

### Zadanie 7: dokumentacja
Pliki: `README.md`, `docs/ROZWOJ.md`.
- [ ] README, sekcja „Czat po OWU (Demo 1)”: diagram (klient → Function → wyszukiwarka BM25 → gpt-5-mini →
      kontrola cytatów → Cosmos), gdzie LLM a gdzie kod, auth (MI + Entra, zero kluczy), model danych Cosmos
      (PK, TTL, item per wiadomość), wyniki z tablicy, ograniczenia (BM25 w chmurze, n = 12, brak frontendu).
- [ ] `docs/ROZWOJ.md`: tablica wyników + koszt rzeczywisty (RU, GB-s, tokeny) + **pozycje do `destroy` 08.11**
      (konto Cosmos, plan i aplikacja Functions, kontener `czat-wdrozenie`, role Cosmos) z listą `-target`.

## Kryteria akceptacji

- `pytest -m "not azure"` — dotychczasowe testy zielone bez zmian, nowe zielone offline (bez sieci i bez `azure-functions` poza `test_czat_funkcja.py`).
- `terraform plan` z gałęzi `demo1` przy `czat_wlaczony=false` i z `-target` = 0 zmian; okno czatu = tylko `add` zasobów `czat.tf`, 0 change, 0 destroy (wynik planu wklejony do `docs/ROZWOJ.md`).
- Funkcja w Azure odpowiada na 2 tury jednej sesji; historia czytana z Cosmos; zero kluczy (Cosmos `disableLocalAuth`, Storage bez shared key, AOAI przez Entra).
- Ewaluacja 12 pytań na żywo w repo: 2/2 `poza_owu`, żadna odpowiedź `ok` z cytatem spoza kontekstu (gwarantuje kontrola), recall@5 i koszt na turę w tablicy.
- README z sekcją i uczciwym zakresem; zrzuty w `docs/`; pozycje do `destroy` w `docs/ROZWOJ.md`.

## Koszt (szacunek, do potwierdzenia w Cost Management po 24 h)

| pozycja | założenie | koszt okna 01–08.11 |
|---|---|---|
| Cosmos RU | ~15–20 RU na turę (1 zapytanie w partycji + 2 inserty przy wąskim indeksie — **NIESPRAWDZONE**, mierzy zadanie 3); ~500 tur testów i demo | ~10 tys. RU ≈ **0,003 USD** |
| Cosmos storage | < 10 MB | ≈ 0 |
| Functions Flex | ~5–10 s × 2 GB na turę; 500 tur ≈ ≤ 10 tys. GB-s; bez grantu (trial — NIESPRAWDZONE) | ≤ **0,26 USD** (z grantem 0) |
| gpt-5-mini | ~2,5 tys. tokenów we + ~0,6 tys. wy na turę (6 fragmentów + historia) | ~0,002 USD/turę → **~1 USD** |
| App Insights | kilka MB logów | grosze |
| **Razem** | bezczynność ≈ 0 (Flex skaluje do zera, serverless bez minimum) | **< 2 USD**; budżet 170 EUR nie jest zagrożony |

## Ryzyka

- **Flex na Free Trial / w `swedencentral`** — limit 15 rdzeni wystarcza (2 × 1 rdzeń), ale dostępność regionu i SKU
  rozstrzyga dopiero zadanie 0 / pierwszy `apply` → decyzja 11.
- **Wspólny stan Terraform** — apply bez `-target` z `demo1` niszczy 19c i APIM. Jedyna obrona: reguła z decyzji 7
  i czytanie planu. Agent nigdy nie uruchamia `apply`.
- **Storage bez kluczy** — Flex i provider azurerm muszą przejść na Entra (`storage_use_azuread`, `AzureWebJobsStorage__*`);
  możliwe brakujące role Queue/Table dla hosta (decyzja 8). Objaw: host nie startuje, 503 bez logów aplikacji.
- **Zimny start** — pierwsze wywołanie po bezczynności kilka–kilkanaście sekund; na demo „rozgrzać” `GET /api/zdrowie`.
  Bez always-ready (płatne bez grantu).
- **Propagacja ról data plane Cosmos** — kilka minut po `apply`; 403 w pierwszych minutach to nie błąd konfiguracji.
- **Przecieki treści** — pytania użytkownika w Cosmos (TTL 7 dni, dane fikcyjne); w logach tylko metryki (decyzja 13).
- **Mały zestaw (n = 12)** — wynik to kierunek, nie pomiar; nie stroić promptu pod zestaw (zmiana promptu = nowy bieg).
- **Kolizja z harmonogramem** — jeśli demo nie domknie się 01.11, zadania 6–7 przechodzą na 02.11,
  reszta na 07.11; zasoby i tak znikają 08.11.

## Czego nie robić

- Nie uruchamiać `terraform apply/destroy` bez `-target`; agent nie uruchamia `terraform`/`az` z efektem zapisu w ogóle.
- Nie wkładać kluczy (Cosmos, Storage, AOAI, klucz funkcji) do repo ani do `app_settings`; nie włączać local auth „na chwilę”.
- Nie ruszać grafu agenta (`agent/graf.py`, węzły szkód), `api/` (poza planem awaryjnym 11 za zgodą właściciela) ani frontendu.
- Nie dodawać `langchain`, Durable Functions, always-ready, VNet, APIM przed funkcją ani drugiego regionu Cosmos.
- Nie używać Linux Consumption (Y1) ani App Service B1 bez decyzji właściciela.
- Nie przepinać AI Search ani nie tworzyć nowej usługi Search; nie zmieniać OWU.
- Nie commitować tego SPEC razem z kodem innych etapów; nie ruszać worktree `etap19/20/23/24`.

## Otwarte pytania do właściciela (przed startem 01.11)

1. **Functions Flex vs App Service** — Flex rekomendowany (koszt ~0, zalecany plan); czy demo musi pokazać
   wprost „App Service”? Jeśli tak — rozważyć B1 (opłata stała ~kilkanaście USD/mies., liczona godzinowo, NIESPRAWDZONE) zamiast Flex.
2. **Historia per sesja (UUID od klienta) czy per użytkownik** (wymaga logowania Entra → Easy Auth, +pół dnia)?
3. **Klucz funkcji wystarczy na demo**, czy Easy Auth z Entra na endpoincie (spójnie z `uw-web`)?
4. Czy chcesz minimalny frontend (strona w `frontend/` albo prosta HTML w funkcji), czy wystarczą curl/PowerShell + zrzuty?
