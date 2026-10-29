# Monitoring — Etap 13 (OpenTelemetry → Application Insights)

Ten dokument opisuje telemetrię `uw-api` (spany, atrybuty, RODO), decyzje za
alertem awarii (`infra/terraform/main.tf`) i wynik testu alertu w obu stanach
(`obserwowalnosc/test_alarmu.py`). Zasoby Terraform: Application Insights
workspace-based na istniejącym Log Analytics, action group (mail), reguła
`azurerm_monitor_scheduled_query_rules_alert_v2` — przypięta do **workspace'u Log
Analytics**, nie do zasobu App Insights. Szczegóły w `infra/terraform/README.md`.

## Architektura — trzy poziomy spanów

```
wniosek.uruchom  (albo wniosek.wznow)        <- SerwisAgenta, cały przebieg
  |-- wezel.wczytaj
  |-- wezel.klasyfikuj
  |     |-- llm.klasyfikuj                   <- ModelSledzony, jedno wywołanie modelu
  |-- wezel.ekstrahuj
  |     |-- llm.ekstrahuj
  |-- wezel.waliduj
  |-- wezel.ocen
  |     |-- llm.ocen
  |-- wezel.kontrola
  |-- wezel.zatwierdzenie                    <- interrupt() — czeka na człowieka
  (gałąź SZKODA: wezel.ekstrahuj_szkode/llm.ekstrahuj_szkode, wezel.sprawdz_polise,
   wezel.szukaj_owu, wezel.ocen_pokrycie/llm.ocen_pokrycie, wezel.kontrola_cytatow)
```

- **`wniosek.*`** (`api/agent_serwis.py::SerwisAgenta`) — cały przebieg grafu dla
  jednego wniosku. `uruchom_nowy` (wywoływany z `BackgroundTasks` po odpowiedzi
  202) jest **nowym korzeniem z linkiem** do spanu żądania HTTP — żądanie kończy
  się przed przetwarzaniem, a dziecko dłuższe od rodzica psuło widok w App
  Insights. `wznow` jest synchroniczny w requeście (`api/trasy.py`) — zwykle
  dziecko bieżącego spanu, bez linku.
- **`wezel.<nazwa>`** (`obserwowalnosc/wezly.py::sledz_wezel`) — każdy węzeł
  LangGraph (`agent/graf.py`). `GraphInterrupt` (punkt zatrzymania grafu,
  oczekiwanie na decyzję człowieka) **nie jest błędem** — tylko inne wyjątki
  ustawiają status ERROR.
- **`llm.<operacja>`** (`obserwowalnosc/model_sledzony.py::ModelSledzony`) —
  proxy na `ModelAgenta`, niezależne od dostawcy (Azure OpenAI, Gemini, vLLM,
  atrapa). Operacje: `klasyfikuj`, `ekstrahuj`, `ocen`, `ekstrahuj_szkode`,
  `ocen_pokrycie`.

Kontekst OTel przechodzi przez wykonawcę LangGraph (contextvars) — zagnieżdżenie
rodzic/dziecko jest zachowane, mimo że węzły są wywoływane przez graf, nie wprost
(sprawdzone w `tests/test_telemetria.py::test_przebieg_grafu_spany_zagniezdzone...`).

### Mapowanie na tabele Application Insights (sprawdzone, context7/learn.microsoft.com)

Każdy własny span (`wniosek.*`, `wezel.*`, `llm.*`) jest tworzony bez `kind=`
(`tracer().start_as_current_span(nazwa, ...)`), więc domyślnie ma
`SpanKind.INTERNAL`. Dystrybucja `azure-monitor-opentelemetry` eksportuje
spany INTERNAL do tabeli **`AppDependencies`** z `DependencyType = "InProc"`
(Microsoft Learn: *"By default, the span is in the dependencies table with a
dependency type of InProc. [...] we recommend setting kind = SpanKind.SERVER
[...] to ensure it appears in the requests table."* — `opentelemetry-add-
modify.md`). Jedyny span `SpanKind.SERVER` w `uw-api` to ten tworzony przez
auto-instrumentację FastAPI dla samego żądania HTTP (`AppRequests`).

**Konsekwencja dla alertu** (`infra/terraform/main.tf`): zapytanie zaczyna się
od `union AppRequests, AppDependencies`, więc **złapie spany `wniosek.*` i
`llm.*` niezależnie od tego, do której tabeli trafiły**. Nazwy tabel
(`AppRequests`, `AppDependencies`) i kolumny (`Name`, `Success`, `OperationId`)
to schemat **workspace'u Log Analytics** — dlatego reguła ma `scopes` na
workspace, a zapytania z tego dokumentu odpala się w **Logs workspace'u Log
Analytics** (portal: zasób Log Analytics → `Logs`), **nie** w Logs zasobu App
Insights (tam obowiązuje stary schemat: `requests`, `dependencies`,
`operation_Id`).

`OperationId` w workspace (klasyczne `operation_Id` w Application Insights) =
`TraceId` OpenTelemetry — ten sam identyfikator dla całego drzewa spanów
jednego wniosku. Skrypt `obserwowalnosc/test_alarmu.py` drukuje go jako
`operation_Id=...`.

## Atrybuty

| Atrybut | Na jakim spanie | Źródło | Znaczenie |
|---|---|---|---|
| `uw.wniosek_id` | `wniosek.*` | `_span_wniosku` (`api/agent_serwis.py`) | `thread_id` grafu (= id wniosku w bazie) |
| `uw.typ_dokumentu` | `wniosek.*` | `_opisz_wynik` | `WNIOSEK` / `SZKODA` / `INNY` |
| `uw.decyzja` | `wniosek.*` | `_opisz_wynik` | Decyzja końcowa (`AKCEPTACJA`/`ODMOWA`/...) albo pusty string |
| `uw.status` | `wniosek.*` | `_opisz_wynik` | `czeka_na_decyzje` (interrupt) / `zakonczony` |
| `uw.blad` | `wniosek.*` | `_opisz_wynik` | `True`, gdy węzeł grafu zakończył się błędem albo brak decyzji końcowej po 1. przebiegu |
| `error.type` | `wniosek.*`, `wezel.*`, `llm.*` | każdy, przy wyjątku | Nazwa klasy wyjątku (np. `TimeoutError`, `ValueError`, `BladWezlaGrafu` — kod, nie treść) |
| `gen_ai.operation.name` | `llm.*` | `ModelSledzony._wywolaj` | Nazwa operacji (`klasyfikuj`, `ocen`, ...) |
| `gen_ai.system` | `llm.*` | `ModelSledzony._wywolaj` | `azure.ai.openai` / `gcp.gemini` / `vllm` / `atrapa` |
| `gen_ai.request.model` | `llm.*` | `ModelSledzony._wywolaj` | Nazwa modelu (np. `gpt-5-mini`) |
| `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` | `llm.*` | `ModelSledzony._wywolaj` (z `MetadaneWywolania`) | Tokeny wejścia/wyjścia tego wywołania |

Atrybuty standardowe auto-instrumentacji FastAPI/requests (`http.method`,
`http.route`, `http.status_code`, ...) nie są w tej tabeli — są domyślne z
pakietu, nie własne.

## Zasada RODO

**Zero treści dokumentu, NIP, nazwisk, adresów w telemetrii** — tylko
identyfikatory, kody, nazwy węzłów/operacji, liczby. W kodzie to:

- `ModelSledzony._wywolaj` i `obserwowalnosc/wezly.py::sledz_wezel` wywołują
  `start_as_current_span(..., record_exception=False, set_status_on_exception=False)`
  **zawsze** — komunikat wyjątku SDK (OpenAI/Gemini) potrafi zacytować prompt;
  zapisywany jest tylko `error.type = type(e).__name__`, nigdy `str(e)`, a status
  ERROR ustawiany jest ręcznie, bez opisu.
- `obserwowalnosc/telemetria.py` wywołuje `configure_azure_monitor(...,
  disable_logging=True)` — bez tego dystrybucja wysyłałaby też logi Pythona
  (WARNING i wyżej), a `logger.exception` (`api/agent_serwis.py`, `api/trasy.py`,
  `agent/wezly_szkody.py`) niesie pełne komunikaty błędów z tracebackami
  (komunikat walidacji pydantic potrafi zawierać odpowiedź LLM z NIP-em i
  nazwiskiem). Test:
  `tests/test_telemetria.py::test_konfiguracja_wylacza_logi_pythona_z_powodu_pii`.
- `api/agent_serwis.py::_opisz_wynik` ustawia tylko kody (`uw.decyzja`,
  `uw.status`, `uw.blad`) — nigdy treści pól wniosku ani komunikatu błędu węzła
  (komentarz w kodzie: *"Tylko kody i flagi - zadnej tresci dokumentu"*).
- `obserwowalnosc/test_alarmu.py::_zakoncz_span` wyciąga z komunikatu błędu
  węzła (`agent/wezly.py::_wywolaj_model`) **tylko typ wyjątku** (regex na
  `"typ bledu: (\w+)"`), nigdy cały komunikat.
- Test `tests/test_telemetria.py::test_przebieg_grafu_spany_zagniezdzone...`
  przepuszcza przez graf prawdziwy dokument ze znanym NIP/nazwą
  firmy/adresem/brokerem i sprawdza, że **żaden atrybut żadnego spanu ich nie
  zawiera**.
- Ten sam przegląd trzeba powtórzyć ręcznie w portalu po pierwszym prawdziwym
  wniosku na Azure (kryterium akceptacji 4, Etap 13) — automatyczny test
  pokrywa tylko atrapy.

## Decyzja: alert = awaria, nie cisza

Demo nie ma regularnego ruchu (nie ma użytkowników składających wnioski co
godzinę) — alarm typu „brak wniosków w oknie X" mierzyłby **brak użytkownika**,
nie awarię systemu, i strzelałby cały czas między pokazami. Zamiast tego:

> **≥ 1 span `wniosek.*` albo `llm.*` z `Success == false` w oknie 15 minut**
> (ewaluacja co 5 min, próg `>= 1`) → action group (mail).

Uzasadnienie: każda prawdziwa awaria (limit LLM, zły connection string do
Azure OpenAI, wyjątek w węźle grafu) kończy się co najmniej jednym spanem ze
statusem ERROR — to jest sygnał odwrotny do „ciszy", więc nie zależy od tego,
czy ktokolwiek akurat testuje system. Reguła łapie też spany ze skryptu
`test_alarmu.py` (`cloud_RoleName = uw-test-alarmu`), nie tylko z `uw-api` —
dzięki temu da się ją przetestować bez prawdziwej awarii.

### Luka trzeciego stanu (nazwana wprost, checklista `nadzor-automatu`)

Zapytanie alertu zwraca **0 błędów** zarówno gdy system jest zdrowy, jak i gdy
**telemetria nie dochodzi w ogóle** (zły/wygasły connection string, padnięty
eksporter, zablokowany port wychodzący) — te dwa stany są nieodróżnialne z
samego wyniku zapytania. To realna luka: alert „milczy", gdy najbardziej
trzeba, żeby mówił.

Środki podjęte w tym etapie (pełny dead man's switch — cykliczny syntetyczny
wniosek + alert na jego brak — **świadomie odłożony**: budziłby kontener przy
`minReplicas 0`, kosztowałby, a demo nie ma czego pilnować między pokazami):

- **(a)** `/zdrowie` zwraca pole `"telemetria": true|false` — `true` tylko,
  gdy `skonfiguruj_telemetrie()` faktycznie włączył eksport (jest connection
  string). To nie dowodzi, że spany DOCHODZĄ do App Insights (eksporter może
  paść po starcie), ale wyłapuje najczęstszy przypadek: brak/zły sekret.
- **(b)** Każdy test alertu (`obserwowalnosc/test_alarmu.py`) **najpierw**
  potwierdza zapytaniem KQL w workspace'ie (sekcja „Test alertu w obu
  stanach", krok 3), że span testowy DOSZEDŁ, **dopiero potem** ocenia
  ciszę/alarm. Cisza bez tego dowodu nic nie znaczy.

### Zachowanie w czasie (stanowe)

Reguła ma `auto_mitigation_enabled = true` — jest **stanowa**, nie strzela przy
każdej ewaluacji z osobna:

- Awaria trwająca godzinami → **jeden** mail „Fired" na początku, alert wisi
  jako Fired w historii reguły, **bez powtórek** co 5 minut.
- Gdy okno 15 minut nie widzi już błędów → **jeden** mail „Resolved".
- Brak powtórek w 2. i 30. dniu trwania tej samej awarii jest akceptowalny dla
  demo (jeden odbiorca, maila nie da się przeoczyć w skrzynce, która nie ma
  innego ruchu). **W produkcji** (więcej odbiorców, więcej szumu w skrzynce,
  dyżury) to nie wystarczy — potrzebna eskalacja/przypomnienie (np. ponowne
  powiadomienie po N godzinach Fired, drugi kanał po czasie bez potwierdzenia)
  — tego demo świadomie nie implementuje.

## Ostatnie błędy

Zapytanie, do którego odsyła `description` reguły w `infra/terraform/main.tf`
(„1) zapytanie KQL z docs/MONITORING.md, sekcja 'Ostatnie bledy'"). Odpalać w
Logs workspace'u Log Analytics:

```kql
let bledne_spany =
    union AppRequests, AppDependencies
    | where Name startswith "wniosek." or Name startswith "llm."
    | where Success == false
    | project TimeGenerated, OperationId, Name, errorType = tostring(Properties["error.type"]);
let wnioski_id =
    union AppRequests, AppDependencies
    | where Name startswith "wniosek."
    | project OperationId, wniosekId = tostring(Properties["uw.wniosek_id"]);
bledne_spany
| join kind=leftouter wnioski_id on OperationId
| project TimeGenerated, OperationId, Name, errorType, wniosekId
| order by TimeGenerated desc
| take 50
```

Spany `llm.*` nie niosą same `uw.wniosek_id` (ustawiany tylko na `wniosek.*`) —
`join` po `OperationId` (= wspólny `TraceId` całego przebiegu) dołącza go z
rodzica. Z wynikiem (`OperationId` = wydrukowany `operation_Id`) następny krok
z `description` reguły: `GET /wnioski/{id}/audyt`.

## KQL — dodatkowe zapytania

Wszystkie w Logs workspace'u Log Analytics (nie w Logs App Insights).

### (a) Czas węzłów — p50/p95

```kql
AppDependencies
| where Name startswith "wezel."
| summarize liczba = count(), p50_ms = percentile(DurationMs, 50), p95_ms = percentile(DurationMs, 95) by Name
| order by Name asc
```

### (b) Tokeny i koszt per wniosek

Cennik `gpt-5-mini` (Azure OpenAI) — **stan na 2026-10-11, do weryfikacji**:
w repo brak oficjalnego, zaktualizowanego cennika Azure dla tego wdrożenia;
wartości orientacyjne, jedno źródło prawdy to `ewaluacja/uruchom.py:64-65`
(`CENA_GPT5_MINI_WE_USD_NA_MILION = 0.25`, `CENA_GPT5_MINI_WY_USD_NA_MILION =
2.00`) — koszt **nie jest liczony w kodzie telemetrii** (decyzja 3, Etap 13):
w spanach idą tylko tokeny, koszt liczy to zapytanie.

```kql
let cena_we_usd_na_milion = 0.25;  // gpt-5-mini wejscie, stan 2026-10-11, do weryfikacji - patrz ewaluacja/uruchom.py:64
let cena_wy_usd_na_milion = 2.00;  // gpt-5-mini wyjscie, stan 2026-10-11, do weryfikacji - patrz ewaluacja/uruchom.py:65
let tokeny_per_wniosek =
    AppDependencies
    | where Name startswith "llm."
    | extend tokeny_we = toint(Properties["gen_ai.usage.input_tokens"]), tokeny_wy = toint(Properties["gen_ai.usage.output_tokens"])
    | summarize tokeny_we = sum(tokeny_we), tokeny_wy = sum(tokeny_wy) by OperationId;
let wnioski_id =
    union AppRequests, AppDependencies
    | where Name startswith "wniosek."
    | summarize TimeGenerated = min(TimeGenerated), wniosekId = take_any(tostring(Properties["uw.wniosek_id"])) by OperationId;
tokeny_per_wniosek
| join kind=inner wnioski_id on OperationId
| extend koszt_usd = (tokeny_we / 1000000.0) * cena_we_usd_na_milion + (tokeny_wy / 1000000.0) * cena_wy_usd_na_milion
| project TimeGenerated, wniosekId, tokeny_we, tokeny_wy, koszt_usd
| order by TimeGenerated desc
```

### (c) Odsetek błędów LLM per dzień

```kql
AppDependencies
| where Name startswith "llm."
| summarize wywolania = count(), bledne = countif(Success == false) by dzien = bin(TimeGenerated, 1d)
| extend odsetek_bledow_pct = round(100.0 * bledne / wywolania, 1)
| order by dzien desc
```

### (d) Czy span doszedł — po `operation_Id`

Sprawdzenie używane w teście alertu (krok 3 poniżej). Wklej `operation_Id`
wydrukowany przez `test_alarmu.py` (w workspace kolumna nazywa się `OperationId`):

```kql
union AppRequests, AppDependencies
| where OperationId == "<operation_Id z wydruku skryptu>"
| project TimeGenerated, AppRoleName, Name, Success, DurationMs, errorType = tostring(Properties["error.type"])
| order by TimeGenerated asc
```

Oczekiwane: w stanie `zdrowy` spany `wniosek.uruchom`, `wezel.*`, `llm.*` z
`Success == true`, `AppRoleName = uw-test-alarmu`; w stanie `chory` dwa spany
`llm.klasyfikuj` z `Success == false` i `errorType = TimeoutError`. Pusty wynik
= span jeszcze nie doszedł (opóźnienie ingestu: kilka minut — odczekaj i
powtórz) albo telemetria nie dochodzi (zły connection string); wtedy **nie wolno**
oceniać ciszy alertu.

### Sprawdzenie, że `/zdrowie` nie wpływa na alert

Kontener odpytuje `/zdrowie` co ok. 15 s (sondy readiness/liveness) — auto-
-instrumentacja FastAPI tworzy dla każdego takiego żądania span
`GET /zdrowie` (`SpanKind.SERVER` → `AppRequests`), **niezależnie** od
telemetrii własnej (`wniosek.*`/`llm.*`). To zapytanie pokazuje ten ruch
osobno — żeby potwierdzić, że alert (filtr `Name startswith "wniosek." or
Name startswith "llm."`) go strukturalnie nie widzi, nawet gdy `/zdrowie`
akurat zwraca 503 (np. przy chwilowej niedostępności Blob/Postgres):

```kql
union AppRequests, AppDependencies
| where Name has "zdrowie"
| summarize liczba = count(), bledne = countif(Success == false) by Name
```

Oczekiwany wynik: wiersz `GET /zdrowie` (może mieć `bledne > 0` przy realnych
awariach magazynu/bazy) — i **ten wiersz nigdy nie wpływa** na wynik zapytania
alertu, bo `"GET /zdrowie"` nie zaczyna się od `"wniosek."` ani `"llm."`. Nie
ma dodatkowej konfiguracji wyłączającej `/zdrowie` z eksportu (np. filtra
`excluded_urls` biblioteki `opentelemetry-instrumentation-fastapi`) —
wyłączenie z alertu jest wyłącznie efektem filtra `Name` w zapytaniu KQL powyżej.
Gdyby kiedyś powstał inny alert bez tego filtra (np. „jakikolwiek błąd HTTP"),
trzeba by dołożyć jawne wykluczenie.

## Test alertu w obu stanach

Skrypt: `obserwowalnosc/test_alarmu.py --stan zdrowy|chory` (patrz docstring w
pliku). Skrypt działa **lokalnie** — do samego testu alertu wdrożenie `uw-api`
nie jest potrzebne.

### 1. Przygotowanie (kolejność)

Najpierw wykonaj w `infra/terraform/README.md` kroki **a)–c)** (kontener stanu,
`terraform init`, `terraform plan` + `apply` — powstają App Insights, action
group i reguła alertu). Kroki **d)** (sekret + zmienne środowiskowe w `uw-api`) i
**e)** (ostrzeżenie przed pełnym Bicepem — kasuje sekret Easy Auth `uw-web`,
szczegóły tylko w README) są potrzebne dopiero do przebiegu 5 (prawdziwy wniosek
przez UI), nie do przebiegów 1–4.

### 2. Connection string — z Terraform, nie z portalu

```powershell
$env:APPLICATIONINSIGHTS_CONNECTION_STRING = terraform -chdir=infra/terraform output -raw connection_string
.venv\Scripts\python.exe obserwowalnosc\test_alarmu.py --stan zdrowy
.venv\Scripts\python.exe obserwowalnosc\test_alarmu.py --stan chory
```

**Nigdy nie wpisywać connection stringa na stałe do pliku ani do repo.**

### 3. Potwierdź, że span doszedł (przed oceną ciszy/alarmu)

Zapytanie (d) z sekcji „KQL — dodatkowe zapytania", w Logs workspace'u Log
Analytics, z `operation_Id` wydrukowanym przez skrypt. Historia reguły: Azure
Monitor → Alerts → wybrana reguła → History.

### 4. Przebiegi

| # | Przebieg | Godzina | `operation_Id` | Span doszedł? | Wynik |
|---|---|---|---|---|---|
| 1 | Baseline, `--stan zdrowy`; **czekać 30 min** | 21.10 21:02:59 | `5b5a9e3addad680649c49e0f56a7e1e3` | tak (19:03:02Z) | OK — brak „Fired" w historii reguły |
| 2 | Brak zmian, drugi `--stan zdrowy` | 22.10 21:22:17 | `cfb780eb465244934583fe5bec3f9979` | tak (4 spany, Success=True) | OK — cisza |
| 3 | Chory, `--stan chory` | 22.10 21:28:44 | `6c920e15b4edded22477828679073399` | tak (`wniosek.uruchom` Success=False, 19:28:47Z) | Fired 21:31:51, „ActionsTriggered" w historii — **ale mail NIE doszedł**: adres w action group niezweryfikowany (patrz pułapka niżej) |
| 4 | Po alarmie, `--stan zdrowy` — **co najmniej 15 min od ostatniego błędu** (przebiegu 3), do maila „Resolved" | 22.10 21:34:00 | `e89a154d54bbd6590ec41afca590cb48` | tak | Resolved 21:57:58 (~29 min po błędzie), mail „Resolved" doszedł (adres zweryfikowany 21:42) |
| 5 | Prawdziwy wniosek przez UI `uw-web` (wymaga kroków d)–e) z README Terraform; kryterium akceptacji 2) | 24.10 08:07:53 (W01.pdf, rewizja uw-api--0000024) | `5652010f7f6d860d7a5794dc00d36e52` | tak | Pełne drzewo: `wniosek.uruchom` → 7 węzłów (`wczytaj`…`zatwierdzenie`) → `llm.klasyfikuj/ekstrahuj/ocen` (`gpt-5-mini`); zapytanie (b): 5474 tokenów we / 1288 wy, ~0,0039 USD. Kontrola: ten sam plik 07:58:11 na rewizji sprzed `a2371d9` (RateLimitedSampler) — doszły tylko 4 spany węzłów, bez korzenia i bez `llm.*`. AppRequests realnych tras > 0 (wykluczenie `/zdrowie` nie zabiło telemetrii) |
| 6 | Powtórka chorego po weryfikacji adresu | 24.10 08:13:21 | `03dadea5abfe25c0fca595a748a258f8` | tak | OK — mail „Fired" 08:16 z pełnym `description` |
| 7 | Zdrowy po przebiegu 6 | 24.10 08:17:37 | `882ddbde35348803aa2723eda1b6e68b` | tak | OK — Resolved 08:42:53 (~30 min po błędzie z przebiegu 6), potem cisza |

**Pułapka (22.10): adres e-mail w action group trzeba potwierdzić.** Azure wysyła
przy tworzeniu grupy mail „Action required: Verify your email…"; dopóki link nie
zostanie kliknięty, powiadomienia NIE wychodzą — a API dalej pokazuje odbiorcę jako
`"status": "Enabled"`, historia alertu ma „Action group executed", nic nie wskazuje
błędu. Link wygasa; nowy: portal → Monitor → Alerty → Grupy akcji → `uw-demo-alerty`
→ Edytuj → zapisz bez zmian (Terraform nie widzi rozjazdu). Po każdym `terraform
apply`, który odtwarza grupę, powtórzyć weryfikację i przebieg 3.

Oczekiwane wyniki (task-7-brief.md): #1 — 30 min bez maila, historia reguły
bez „Fired"; #2 — nadal cisza; #3 — mail „Fired" w ≤ 20 min, treść zawiera
instrukcje naprawy z `description` reguły; #4 — mail „Resolved" najwcześniej
15 min po ostatnim błędzie (zmierzone 22.10: ~29 min — Azure rozwiązuje alert
logów dopiero po kilku czystych ewaluacjach), potem cisza (brak drugiego „Fired"); #5 — w App Insights
drzewo `wniosek → wezel → llm` z tokenami `gpt-5-mini` (zapytanie (b)).

**Uwaga do przebiegu 5 (link spanu z `BackgroundTasks`):** `wniosek.uruchom`
jest nowym korzeniem (własny `operation_Id`) z linkiem do spanu żądania HTTP
`POST` (decyzja 7, Etap 13). Wniosek szukaj po `uw.wniosek_id` (nie po
`operation_Id` żądania), a następnie sprawdź w Transaction search, czy span
`wniosek.uruchom` pokazuje link do spanu żądania i czy widok nie jest
zepsuty. Tego linku nie sprawdzono na prawdziwym Azure.

Brak któregokolwiek dowodu = Etap 13 NIE jest w pełni ukończony dla tego
zadania (zapisać jako otwarte w handoffie, nie wymyślać wyników).

## Obawy / do sprawdzenia na prawdziwym Azure

1. **Scope reguły** — pierwotnie reguła była przypięta do zasobu App Insights,
   a zapytanie używa nazw tabel workspace'u; przegląd końcowy (poprawka 1)
   zmienił `scopes` na workspace Log Analytics. Zweryfikowane tylko
   dokumentacyjnie i przez `terraform validate` — `apply` i pierwszy
   „Fired" pokażą, czy reguła się utworzyła i ewaluuje bez błędów.
2. **`Success` dla spanu ERROR bez `record_exception`** — cały kod (celowo, RODO)
   ustawia `set_status(Status(StatusCode.ERROR))` i nigdy nie woła
   `record_exception()`. Przegląd końcowy potwierdził w kodzie eksportera, że
   `Success` zależy wyłącznie od statusu spanu; nadal do potwierdzenia przy
   pierwszym prawdziwym teście alertu (przebieg 3).
3. **Czas propagacji do Log Analytics** — zapytanie alertu działa na danych w
   Log Analytics, nie bezpośrednio na eksporterze; typowe opóźnienie ingestu
   (kilka minut) nie zostało sprawdzone (wymaga prawdziwego Azure) — stąd okno
   `PT15M` i czas „≤ 20 min" w tabeli testu mają margines.
4. **Link spanu z `BackgroundTasks`** — patrz uwaga do przebiegu 5.

## Metryki efektu (Etap 19c)

Alert z Etapu 13 mówi, czy agent **działa**. Metryki efektu mówią, czy
**pomaga**: ile kosztuje wniosek, jak często człowiek się z nim nie zgadza
i jak często agent sam odsyła sprawę dalej. Źródło: spany w
`AppDependencies` (workspace `uw-demo-logs`), zapytania w
`obserwowalnosc/metryki_efektu.kql`, widok w workbooku
„uw: metryki efektu rozwiazania (19c)” (`infra/terraform/metryki_efektu.tf`).

| metryka | definicja |
|---|---|
| koszt na wniosek | suma kosztu wywołań LLM w jednym wniosku (średnia i p95, USD) |
| SKIEROWANIE | odsetek wniosków, w których agent rekomenduje SKIEROWANIE do underwritera |
| odejścia | odsetek decyzji człowieka innych niż rekomendacja LLM **albo** silnika reguł |
| błędy | odsetek wniosków zakończonych spanem ze statusem ERROR |
| czas | p50 i p95 czasu od przyjęcia wniosku do rekomendacji |

**Dlaczego SKIEROWANIE, a nie „do człowieka”.** Każdy wniosek i tak trafia
do człowieka (przerwanie grafu przed decyzją), więc „odsetek do człowieka”
wynosiłby zawsze 100% i nic nie mówił. SKIEROWANIE to jedyny sygnał, że agent
sam uznał sprawę za zbyt niepewną.

### Wartości w stanie zdrowym (27.10, zasiew 26.10)

| metryka | wartość |
|---|---|
| wnioski | 11 |
| koszt na wniosek | śr. 0,00432 USD, p95 0,00532 USD |
| SKIEROWANIE | 27,3% (3/11) |
| odejścia | 20% (2/10) |
| błędy | 0% |
| czas | p50 14,5 s, p95 22,3 s |

### Alert `uw-demo-alert-odejscia`

Ewaluacja co godzinę (`PT1H`), okno 24 h (`P1D`). Odpala, gdy w oknie jest
co najmniej 5 decyzji człowieka i ponad 50% z nich odbiega od rekomendacji.
`auto_mitigation` zamyka alert sam, gdy warunek przestaje być spełniony.

**Zastrzeżenia:**

1. **Odejście miesza dwie rzeczy.** Liczy się, gdy człowiek różni się od LLM
   **albo** od silnika reguł. Wzrost może więc znaczyć brak zaufania do
   agenta, ale też rozjazd LLM–silnik, w którym człowiek przyznaje rację
   jednej ze stron. Przed reakcją sprawdzić w workbooku, od której strony
   człowiek odchodzi.
2. **Cisza przy małym ruchu to „nie sprawdzono”, nie „zdrowo”.** Przy mniej
   niż 5 decyzjach w 24 h alert milczy z definicji. Kafelek w workbooku
   pokazuje liczbę decyzji; zero lub kilka decyzji oznacza brak pomiaru.

### Test alertu w obu stanach

| krok | kiedy (czas lokalny) | oczekiwane | wynik |
|---|---|---|---|
| `apply` reguły i workbooka (`-target`) | 26.10 | reguła utworzona | OK |
| zasiew zdrowy (skrypt zasiewu, poza repo publicznym) | 26.10 20:04–20:07 | brak alertu przez ≥ 2 ewaluacje | OK: 27.10 ok. 19:05 brak alertu Fired, workbook pokazuje 5 metryk |
| zasiew chory (6 z 8 decyzji odbiega) | 27.10 po 21:10 (≥ 25 h po zdrowym, żeby zdrowe decyzje wypadły z okna) | alert Fired + mail | OK: alert Fired 27.10 22:08 (wartość 1 > próg 0, okno 26.10 21:07–27.10 21:07 UTC), mail z grupy `uw-demo-alerty` doszedł |
| powrót | ok. 28.10 wieczorem | alert Resolved, bez drugiego maila | OK, ale oczekiwanie było błędne: alert Resolved 28.10 23:08 (22:08:41 UTC; `az rest` AlertsManagement, `timeRange=7d`, odczyt 29.10 16:39). Drugi mail PRZYSZEDŁ 28.10 23:08 („Alert ... was resolved”), bo reguła z auto-mitygacją powiadamia także o powrocie. Resolved nastąpił ok. 25 h po Fired, kiedy decyzje z zasiewu chorego wypadły z okna 24 h. |

Zrzut workbooka: TODO (`docs/zrzuty/`).
