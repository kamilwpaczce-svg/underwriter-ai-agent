# SPEC Etap 21 — serwer MCP z narzędziami underwritera

> **Dla wykonawcy:** gałąź `etap21` odbita od `main` (worktree `underwriter_etap21`; w repo pracują inne
> sesje — **zero `git commit -a`**). **Commit po każdym zadaniu** — wznowienie od ostatniego commita.
> TDD: najpierw test offline, potem kod. Jedno wywołanie agenta = 1–2 zadania. Termin: **05–06.11.2026**,
> wg harmonogramu **1 dzień** (drugi dzień dzieli z Etapem 17). Dane fikcyjne.
> Zasoby Azure: jedna Container App `uw-mcp` + rejestracja aplikacji Entra — **tylko w zadaniu 5, za zgodą właściciela**.

> **Decyzje właściciela 27.10:** ingress zewnętrzny `uw-mcp` chroniony tokenem Entra (weryfikacja w aplikacji) — **zgoda**;
> plan B: statyczny token z `az` w nagłówku Claude Code — **zgoda**. MCP przez APIM — poza zakresem. Termin zadania 5
> (wdrożenie) do potwierdzenia przy starcie etapu.

**Cel:** serwer MCP (streamable HTTP) wystawiający **tylko do odczytu** narzędzia, z których korzysta agent
underwritingu: wyszukiwanie w OWU, sprawdzenie polisy, silnik reguł, sygnał modelu ryzyka szkody, status
wniosku. Klient MCP (Claude Code, klient z SDK) wylicza narzędzia i woła każde; bez ważnego tokenu Entra
dostaje 401. **Żadne narzędzie nie zmienia decyzji ani statusu** — wynik to sygnał pomocniczy, decyzja
zostaje u człowieka w panelu (`docs/AI_ACT.md:52`, art. 14). MCP pojawia się w wielu
współczesnych wdrożeniach agentów AI, stąd ten etap.

## Źródła (stan repo 27.10, `main` @ `68905db`)

- Plan: wewnętrzny plan etapów (poza repo) (decyzje wstępne: SDK `mcp`/FastMCP, streamable HTTP, Container App
  `uw-mcp` z obrazem API i osobną komendą; narzędzia tylko do odczytu; Entra albo klucz z Key Vault;
  span na wywołanie), harmonogram `:130-149` (05–06.11, 1 dzień), `:151-155` (przed 9.11: zrzuty, destroy).
- **Kandydaci na narzędzia (funkcje czyste lub tylko-odczyt):**
  - OWU: `rag/wyszukiwarka.py:26` Protocol `Wyszukiwarka.szukaj(zapytanie, k) -> list[Fragment]`;
    `WyszukiwarkaLokalna` (BM25, `:37`); Azure AI Search `rag/azure_search.py:68` + fabryka
    `zbuduj_wyszukiwarke(srodowisko)` `:115` (embedding przez Azure OpenAI). `Fragment` = `id, paragraf,
    ustep, tytul, tresc` (`rag/fragmenty.py:25`).
  - Polisa: `agent/polisy.py:56` `sprawdz_polise(pola, polisy, termin_zgloszenia_dni) -> {kody S01–S04,
    polisa, suma_ubezpieczenia, dni_do_zgloszenia, braki, opis}`; polisy z `wczytaj_polisy()` `:36`
    (`dane/polisy.json`, jest w obrazie — `Dockerfile:21`).
  - Silnik reguł: `generator/reguly.py:154` `oblicz_decyzje(pola, wytyczne) -> {"decyzja", "reguly"}`,
    wytyczne `wytyczne/wytyczne_mienie_v1.yaml`; w grafie woła go `wezel_kontrola` (`agent/wezly.py:178-180`).
  - Model ryzyka szkody: `ryzyko/serwowanie.py:81` `ModelRyzyka.ocen(cechy) -> {"wynik", "glowne_cechy"}`
    (docstring `:84`: „SYGNAL DLA CZLOWIEKA … nigdy decyzja”); ładowanie `ModelRyzyka.z_bloba(magazyn)` `:145`
    (każdy błąd → `None`), w API raz w lifespan `api/main.py:86-90` (`:88`); cechy `ryzyko/cechy.py:16` `CECHY` (7).
  - Status wniosku: tabela `wnioski` (`api/baza.py:42-61`: `status`, `decyzja_koncowa`, `podsumowanie`,
    `zatwierdzil`, `komentarz`, `nazwa_pliku` …); statusy `api/trasy.py:44`.
- **Odrzucone jako narzędzia:** ocena wniosku / analiza szkody całym grafem (`api/agent_serwis.py:172`
  `uruchom_nowy`) — woła LLM, zapisuje do bazy i kończy na `interrupt` (`agent/wezly.py:191`); złożenie
  decyzji `api/trasy.py:167` — zapis. Oba łamią zasadę „tylko odczyt”.
- **Autoryzacja dziś:** `uw-api` **nie ma** uwierzytelnienia — ingress wewnętrzny (`infra/main.bicep:281-301`,
  `external: false`), nagłówek `X-Uzytkownik` to jawna zaślepka (`api/trasy.py:1-6`). Entra jest tylko jako
  Easy Auth na `uw-web` (`infra/README.md:95-136`, `RedirectToLoginPage`, sekret `msft-client-secret`).
  Pełny Bicep kasuje ten sekret (`.superpowers/sdd/SPEC_ETAP14/wspolne.md:8`) — **Bicepu w tym etapie nie ruszamy**.
- **Deploy dziś:** Container Apps z Bicepu (`infra/main.bicep`), dodatki w Terraform ze **wspólnym stanem
  `etap13.tfstate`** (`infra/terraform/README.md:46`, `:132`); wzorzec dołożenia zasobu obok Bicepu:
  `infra/terraform/dryf.tf` — `data` na środowisko, tożsamość, `uw-api` z `read_secrets` (`:42-68`),
  ten sam obraz co `uw-api` (`:68`), sekrety DB i App Insights (`:101-110`). Providery: tylko `azurerm ~> 5.10`
  (`versions.tf`), **brak `azuread`**. Obraz: `python:3.14-slim`, start `docker/start_api.sh` → `uvicorn api.main:app :8000`.
- Telemetria: `obserwowalnosc/telemetria.py:56` `tracer()`, wzorzec spanu `obserwowalnosc/wezly.py:13`,
  maskowanie PII w spanach `obserwowalnosc/pii.py:93` `MaskowaniePII` (Etap 17 pkt 6).
- **Pakiet `mcp` (sprawdzone 27.10.2026):** PyPI `https://pypi.org/pypi/mcp/json` → **2.3.0**, `requires_python >=3.10`
  (data wydania 2.3.0 — NIESPRAWDZONE; poprzednia 1.30.0 z 07.09.2026). Dokumentacja v2.3.0 przez context7
  (`/modelcontextprotocol/python-sdk/v2.3.0`, pliki `docs/migration.md`, `docs/run/*.md`):
  - **`FastMCP` przemianowany na `MCPServer`**: `from mcp.server.mcpserver import MCPServer, Context`;
    import `mcp.server.fastmcp` → `ModuleNotFoundError`. Plan mówi „FastMCP” — w kodzie `MCPServer`.
  - `mcp.streamable_http_app()` → Starlette z trasą `/mcp`; opcje `stateless_http=True`, `json_response=True`;
    **za prawdziwą nazwą hosta bez `transport_security=` (allowlista) serwer odpowiada 421**.
  - Autoryzacja: serwer = resource server OAuth 2.1; `token_verifier=` (`TokenVerifier`, jedna metoda async
    token → `AccessToken | None`) + `auth=AuthSettings(issuer_url, resource_server_url, required_scopes)`;
    SDK publikuje RFC 9728 `/.well-known/oauth-protected-resource/...` i odpowiada 401 z `WWW-Authenticate`.
  - Testy: `from mcp import Client` — `async with Client(serwer) as c: await c.call_tool(...)` w pamięci
    (autoryzacja HTTP wtedy nie działa); klient HTTP `mcp.client.streamable_http.streamable_http_client`
    na **`httpx2.AsyncClient`** (nagłówek `Authorization`). W `.venv` jest `httpx2 2.13.1` i `httpx 0.28.1`.
  - Klient domyślnie negocjuje protokół **2026-07-28**; starsi klienci = tryb „legacy” (sesje).
- **Specyfikacja MCP 2026-07-28, autoryzacja** (`https://modelcontextprotocol.io/specification/latest/basic/authorization`,
  odczyt 27.10.2026): serwer **MUST** publikować Protected Resource Metadata (RFC 9728), **MUST** walidować,
  że token wydano dla niego (audience, RFC 8707), zły/wygasły token → **401**, brak zakresu → 403
  `insufficient_scope`; **MUST NOT** przyjmować ani przekazywać dalej innych tokenów; token tylko w nagłówku.
- **Claude Code** (`https://code.claude.com/docs/en/mcp`, odczyt 27.10.2026):
  `claude mcp add --transport http <nazwa> <url> --header "Authorization: Bearer <token>"`; jest też OAuth
  przez `/mcp` z `--client-id` / `--callback-port`. Ustawiony `headers.Authorization` wyłącza fallback na OAuth.
  Czy pełny przepływ OAuth Claude Code ↔ Entra ID działa (Entra nie ma DCR ani CIMD) — NIESPRAWDZONE.

## Decyzje

1. **SDK `mcp==2.3.0`, klasa `MCPServer`** (nie `FastMCP` — przemianowana w v2), transport streamable HTTP,
   `stateless_http=True`, `json_response=True` (bez sesji: 1 replika, skalowanie do 0, brak stanu do zgubienia;
   żadne narzędzie nie potrzebuje kanału zwrotnego). Osobny proces, **nie montowany w FastAPI `uw-api`**
   (Mount wyłącza lifespan podserwera i miesza autoryzację z API bez autoryzacji). Wejście: `python -m mcp_serwer`
   (uvicorn na `0.0.0.0:8001`, ścieżka `/mcp`). Wersja wpięta w `requirements.txt`; zgodność ze
   `starlette 1.7.0`, `pydantic 2.14.0`, Python 3.14 — sprawdzana w zadaniu 0.
2. **Pięć narzędzi, wszystkie tylko do odczytu, deterministyczne, bez wywołań LLM czatu:**

   | narzędzie | wejście | źródło | wynik |
   |---|---|---|---|
   | `szukaj_w_owu` | `zapytanie: str` (≤ 500 zn.), `k: int` 1–10 (dom. 5) | `Wyszukiwarka.szukaj` (Azure AI Search w chmurze, BM25 lokalnie) | lista `{id, paragraf, ustep, tytul, tresc}` |
   | `sprawdz_polise` | `nr_polisy`, `data_zdarzenia`, `data_zgloszenia`, `szacowana_kwota`, `rodzaj_mienia` (podzbiór `PolaSzkody`, `agent/schematy.py:122`) | `agent/polisy.py:56` | kody S01–S04, braki, opis, suma ubezp., dni do zgłoszenia — **bez danych ubezpieczonego z polisy** |
   | `sprawdz_reguly` | pola wniosku (model `Pola`, `agent/schematy.py:31`) | `generator/reguly.py:154` + wytyczne YAML | `{rekomendacja_silnika, reguly}` |
   | `sygnal_ryzyka` | 7 cech `CECHY` (`ryzyko/cechy.py:16`) | `ModelRyzyka.ocen` | `{wynik, glowne_cechy, wersja_modelu}` albo `MODEL_NIEDOSTEPNY` |
   | `status_wniosku` | `wniosek_id: UUID` | SELECT z `wnioski` (sesja tylko do odczytu) | `status`, `decyzja_koncowa`, `utworzono`, `zakonczono`, kody reguł/S0x z `podsumowanie` |

   `status_wniosku` **nie zwraca** `nazwa_pliku`, `zatwierdzil`, `komentarz`, `blob_nazwa` ani pól
   tekstowych `podsumowanie` (PII: nazwa, NIP, adres) — biała lista kluczy, test na Z01.
   **Poza zakresem:** analiza szkody / ocena wniosku grafem (LLM, zapis, `interrupt`), złożenie decyzji,
   upload dokumentu, prompty i zasoby MCP (`@mcp.resource`) — wzmianka w README jako „świadomie nie”.
3. **Brak wpływu na decyzję — w kodzie, nie tylko w opisie:** (a) każde narzędzie zwraca kopertę
   `{"wynik": …, "charakter": "sygnal_pomocniczy", "uwaga": "Decyzję podejmuje człowiek w panelu
   underwritera (AI Act art. 14). Ten wynik jej nie zmienia."}`; (b) `sprawdz_reguly` zwraca klucz
   `rekomendacja_silnika`, nigdy `decyzja`; (c) serwer nie importuje `api.trasy` ani `SerwisAgenta`,
   a połączenie z bazą idzie przez sesję z `SET TRANSACTION READ ONLY` (test: próba INSERT → błąd);
   (d) adnotacje narzędzi MCP `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`
   (nazwy pól w v2 po zmianie na snake_case — sprawdzić w zadaniu 0); (e) test architektoniczny: brak
   w `mcp_serwer/` wywołań `commit()`, `wznow`, `zloz_decyzje`, `ModelAgenta`.
4. **Uwierzytelnienie: token Entra ID (OAuth 2.1 resource server), weryfikowany w aplikacji przez
   `TokenVerifier`, nie klucz z Key Vault i nie Easy Auth.** Powody: specyfikacja MCP wymaga tokenów OAuth,
   audience i RFC 9728 — klucz statyczny tego nie spełnia; Easy Auth odpowiada własnym 401/302 bez
   `resource_metadata` w `WWW-Authenticate`, więc klient MCP nie odkryje serwera autoryzacji; w aplikacji
   test 401/200 da się zrobić offline. Implementacja `mcp_serwer/autoryzacja.py::WeryfikatorEntra`:
   PyJWT (`pyjwt 2.15.1` już jest w `.venv` jako zależność `msal` — dopisać jawnie do `requirements.txt`),
   `PyJWKClient` na `https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys`, sprawdza `iss`
   (`.../<tenant>/v2.0`), `aud` (= `MCP_AUDIENCE`, appId aplikacji `uw-mcp`), `exp`/`nbf`, zakres `scp`
   zawiera `narzedzia.odczyt`, algorytm tylko `RS256`. Brak zakresu → 403 `insufficient_scope`.
   Aplikacja Entra `uw-mcp`: `requestedAccessTokenVersion = 2` (inaczej Entra wydaje token v1 z
   `iss = https://sts.windows.net/...` i walidacja padnie), zakres delegowany `narzedzia.odczyt`.
   **Klient testowy:** token z `az account get-access-token --scope api://<appId>/narzedzia.odczyt`
   podany Claude Code jako `--header` (scope `local`, nie w repo; token żyje ~1 h). Pełny OAuth w Claude Code
   (`--client-id`, `/mcp`) — tylko próba w zadaniu 5, wynik do README; brak działania nie blokuje etapu.
5. **Ślad:** span `mcp.narzedzie.<nazwa>` (atrybuty: `uw.mcp.narzedzie`, `uw.mcp.wynik` = `ok|blad|brak_modelu`,
   `uw.mcp.czas_ms`, `uw.mcp.klient_oid` = `oid` z tokenu); **bez argumentów i wyników w atrybutach**
   (zapytanie może zawierać PII); `MaskowaniePII` podpięte jak w API. `OTEL_SERVICE_NAME=uw-mcp`.
6. **Wdrożenie (zadanie 5, za zgodą właściciela):** `infra/terraform/mcp.tf` — `azurerm_container_app.mcp`
   (`uw-mcp`) wg wzorca `dryf.tf`: te same `data` (środowisko, tożsamość, `uw-api` z `read_secrets`), sekrety
   `database-url` i `appinsights-cs`, zmienne AI Search/embeddingów skopiowane z `uw-api`, **ingress
   zewnętrzny** (klient z laptopa), port 8001, `min_replicas = 0`, `max_replicas = 1`, komenda
   `["python", "-m", "mcp_serwer"]`, obraz z `var.mcp_obraz` (nowy tag z kodem `mcp_serwer/`; `uw-api`
   zostaje na swoim obrazie). `MCP_URL_PUBLICZNY` z `default_domain` środowiska (resource metadata
   i allowlista `transport_security`). Rejestracja aplikacji Entra — ręcznie `az ad app create` (instrukcja
   w `infra/README.md`, sekcja h), **bez dodawania providera `azuread` do wspólnego stanu**.
   **Apply wyłącznie `terraform plan/apply -target=azurerm_container_app.mcp`** — pełny apply na wspólnym
   `etap13.tfstate` niszczy zasoby etapów 13/15/19c. Destroy przed 9.11: `terraform destroy
   -target=azurerm_container_app.mcp` + `az ad app delete`, wpis na liście w `docs/ROZWOJ.md`.
7. **Test zgodności klientem MCP — dwa poziomy:** (a) offline: `mcp.Client` w pamięci (lista 5 narzędzi,
   wywołanie każdego) + Starlette `TestClient` na `streamable_http_app()` z podmienionym JWKS (401 bez tokenu
   z `resource_metadata`, 401 zły `aud`/wygasły, 403 brak zakresu, 200 z dobrym); (b) na żywo: skrypt
   `mcp_serwer/sprawdz_zgodnosc.py <url>` (klient `streamable_http_client` + `httpx2`, token z env
   `MCP_TOKEN`, nigdy z argumentu) — `initialize`, `tools/list` = 5, `tools/call` każdego, osobno żądanie
   bez tokenu → 401; plus Claude Code (`/mcp` pokazuje 5 narzędzi, wywołanie `szukaj_w_owu`). MCP Inspector
   (`npx @modelcontextprotocol/inspector`) — opcjonalnie do zrzutu ekranu; wersja NIESPRAWDZONA.

## Pliki

| plik | rola |
|---|---|
| `mcp_serwer/__init__.py`, `mcp_serwer/__main__.py` | start uvicorn, ustawienia z env |
| `mcp_serwer/serwer.py` | `zbuduj_serwer(zaleznosci, weryfikator) -> MCPServer`, rejestracja 5 narzędzi, koperta |
| `mcp_serwer/narzedzia.py` | czyste funkcje narzędzi (bez MCP) — testowalne wprost |
| `mcp_serwer/autoryzacja.py` | `WeryfikatorEntra(TokenVerifier)` |
| `mcp_serwer/zaleznosci.py` | wyszukiwarka, polisy, wytyczne, model ryzyka (z Blob), fabryka sesji tylko-odczyt |
| `mcp_serwer/sprawdz_zgodnosc.py` | test zgodności na żywo (klient SDK) |
| `tests/test_mcp_narzedzia.py`, `tests/test_mcp_autoryzacja.py`, `tests/test_mcp_klient.py` | testy offline |
| `requirements.txt`, `Dockerfile` | `mcp==2.3.0`, `pyjwt` jawnie; `COPY mcp_serwer/ mcp_serwer/` |
| `infra/terraform/mcp.tf`, `infra/terraform/variables.tf`, `infra/README.md` (sekcja h) | Container App, Entra |
| `README.md`, `docs/AI_ACT.md`, `docs/ROZWOJ.md` | opis, wiersz art. 14, lista do destroy |

## Zadania

### Zadanie 0: rozpoznanie (bez kodu produkcyjnego, notatka w tym pliku pod zadaniem)
- [ ] `pip install mcp==2.3.0 --dry-run` w `.venv`: czy nie podbija `starlette`, `pydantic`, `anyio`, `httpx`;
      konflikt → STOP, raport (nie podbijać zależności API po cichu).
- [ ] Spike w scratchpadzie: `MCPServer` + 1 narzędzie + `TokenVerifier` atrapa, `streamable_http_app()` pod
      uvicorn; `curl` bez tokenu → 401 z `resource_metadata`; ustalić: nazwy pól adnotacji narzędzi w v2,
      parametr `transport_security` (allowlista hostów), czy serwer przyjmuje klienta w trybie legacy.
- [ ] Ustalić, czy `uw-api` ma w env zmienne AI Search/embeddingów (nazwy z `rag/azure_search.py:36-60`)
      — z `infra/main.bicep`, bez wywołań `az`.

### Zadanie 1: narzędzia jako czyste funkcje (TDD, offline)
Pliki: `mcp_serwer/narzedzia.py`, `mcp_serwer/zaleznosci.py`, `tests/test_mcp_narzedzia.py`.
- [ ] `szukaj_w_owu` na `WyszukiwarkaLokalna`: zapytanie o zalanie → fragmenty z paragrafem; `k` poza 1–10 →
      błąd walidacji; puste zapytanie → błąd.
- [ ] `sprawdz_polise`: Z09 → `S01`; Z01 → bez S01, z sumą; wynik bez danych ubezpieczonego z polisy.
- [ ] `sprawdz_reguly`: dla W01–W14 `rekomendacja_silnika` i `reguly` = `dane/oczekiwane` (ten sam silnik
      co `wezel_kontrola`); w wyniku brak klucza `decyzja`.
- [ ] `sygnal_ryzyka`: model z katalogu testowego → `wynik` w [0,1]; brak cechy → błąd z listą; model `None`
      → `MODEL_NIEDOSTEPNY` (nie wyjątek).
- [ ] `status_wniosku` (SQLite jak w testach API): biała lista kluczy; nieznany UUID → „nie znaleziono”;
      sesja tylko-odczyt — próba zapisu kończy się błędem.

### Zadanie 2: serwer MCP i klient w pamięci (TDD, offline)
Pliki: `mcp_serwer/serwer.py`, `tests/test_mcp_klient.py`.
- [ ] `Client(serwer)`: `list_tools` = dokładnie 5 nazw, każde z adnotacją tylko-do-odczytu i schematem wejścia.
- [ ] `call_tool` każdego narzędzia → koperta z `charakter == "sygnal_pomocniczy"` i `uwaga`.
- [ ] Błąd w narzędziu → wynik MCP z `is_error` (nie 500), bez śladu stosu w treści.
- [ ] Test architektoniczny z decyzji 3e (AST/grep po `mcp_serwer/`).
- [ ] Spany: `mcp.narzedzie.<nazwa>` z atrybutami z decyzji 5; test RODO — w atrybutach brak treści
      zapytania, NIP, nazwy (rozszerzyć istniejący test atrybutów).

### Zadanie 3: autoryzacja (TDD, offline)
Pliki: `mcp_serwer/autoryzacja.py`, `tests/test_mcp_autoryzacja.py`.
- [ ] Klucz RSA generowany w teście, JWKS podstawiony (bez sieci). `WeryfikatorEntra`: dobry token →
      `AccessToken` z `oid` i zakresami; zły `aud`, zły `iss`, wygasły, `alg=none`/HS256, podpis innym kluczem → `None`.
- [ ] HTTP (`TestClient` na `streamable_http_app()`): brak nagłówka → **401** + `WWW-Authenticate` z
      `resource_metadata`; zły token → 401; token bez `narzedzia.odczyt` → 403; dobry → `initialize` 200.
      **Oba stany w jednym teście** (chory i zdrowy), nie tylko „działa”.
- [ ] `GET /.well-known/oauth-protected-resource/...` zwraca `resource` = URL serwera i `authorization_servers`
      = issuer Entra.
- [ ] Brak `MCP_AUDIENCE`/`MCP_TENANT` w env → serwer nie startuje (głośny błąd, nie tryb bez autoryzacji).

### Zadanie 4: obraz i uruchomienie lokalne
Pliki: `mcp_serwer/__main__.py`, `requirements.txt`, `Dockerfile`, `mcp_serwer/sprawdz_zgodnosc.py`.
- [ ] `docker build` + `docker run` z komendą `python -m mcp_serwer`; `/mcp` odpowiada 401 bez tokenu
      (pamiętać o `COPY mcp_serwer/` — brak = `No module named mcp_serwer` dopiero w chmurze).
- [ ] `sprawdz_zgodnosc.py` przeciw lokalnemu kontenerowi z tokenem testowym podpisanym kluczem z env
      (tryb deweloperski, flaga jawna, wyłączona domyślnie): 5 narzędzi, wywołanie każdego, 401 bez tokenu.
- [ ] `pytest -m "not azure"` — wszystko zielone, dotychczasowe testy bez zmian.

### Zadanie 5: wdrożenie (**tylko po zgodzie właściciela**; zero innych zmian w chmurze)
Pliki: `infra/terraform/mcp.tf`, `infra/terraform/variables.tf`, `infra/README.md`.
- [ ] Entra: `az ad app create --display-name uw-mcp`, identifier URI `api://<appId>`, zakres `narzedzia.odczyt`,
      `requestedAccessTokenVersion=2`; zgoda dla Azure CLI jako klienta (jeśli `get-access-token` odmówi —
      AADSTS65001 — dopisać pre-autoryzację klienta; NIESPRAWDZONE).
- [ ] `az acr build` nowego tagu; `terraform plan -target=azurerm_container_app.mcp` → w planie **dokładnie
      `1 to add`, 0 change/destroy**; inaczej STOP. Potem `apply` z tym samym `-target`.
- [ ] `sprawdz_zgodnosc.py https://<fqdn>/mcp` z prawdziwym tokenem: 5 narzędzi, każde wywołane, 401 bez
      tokenu; Claude Code `claude mcp add --transport http uw-mcp https://<fqdn>/mcp --header "Authorization: Bearer …"`
      (`-s local`), `/mcp` → 5 narzędzi, wywołanie `szukaj_w_owu` i `status_wniosku`. Zrzuty do `docs/`.
- [ ] Span `mcp.narzedzie.*` widoczny w App Insights (zapytanie KQL w `docs/ROZWOJ.md`).
- [ ] Próba OAuth w Claude Code (`--client-id`, `--callback-port`) — wynik (działa / nie i dlaczego) do README.

### Zadanie 6: dokumentacja
Pliki: `README.md`, `docs/AI_ACT.md`, `docs/ROZWOJ.md`.
- [ ] README, sekcja „Serwer MCP”: lista narzędzi, dlaczego tylko odczyt (art. 14, automation bias), czego
      świadomie nie ma (graf, decyzja, upload), autoryzacja (Entra, RFC 9728, audience), jak podłączyć Claude Code.
- [ ] `docs/AI_ACT.md` — wiersz art. 14 uzupełniony o MCP (`mcp_serwer/serwer.py:<linia koperty>`).
- [ ] `docs/ROZWOJ.md` — `uw-mcp` i aplikacja Entra na liście „przed 9.11 usunąć”.

## Kryteria akceptacji

- `pytest -m "not azure"` zielone; nowe testy offline: 5 narzędzi przez `mcp.Client`, autoryzacja w obu
  stanach (401/403 i 200), biała lista `status_wniosku`, brak zapisu do bazy.
- Klient MCP na żywo (skrypt SDK i Claude Code) wylicza 5 narzędzi i wywołuje każde; bez tokenu → 401.
- Żadne narzędzie nie zwraca klucza `decyzja` ani nie zmienia stanu wniosku; koperta z `uwaga` w każdym wyniku.
- Plan Terraform przy wdrożeniu: `1 to add` z `-target`; `uw-api`, `uw-web`, Bicep — bez zmian.
- Zrzuty (`/mcp` w Claude Code, 401 w `curl`, span w App Insights) w `docs/` przed 08.11.

## Ryzyka

- **Zależności `mcp 2.3.0`** (httpx2, starlette, pydantic) mogą kolidować z obrazem API na Pythonie 3.14 → zadanie 0 STOP.
- **API v2 świeże** (rename `FastMCP` → `MCPServer`, snake_case): przykłady z sieci w większości są z v1 —
  ufać `docs/` z tagu v2.3.0, nie blogom.
- **Entra ↔ MCP:** brak DCR/CIMD w Entra — pełny OAuth z Claude Code może nie ruszyć; plan B = statyczny
  nagłówek z tokenem z `az` (decyzja 4). Token v1 vs v2 (`iss`) — najczęstsza przyczyna „zawsze 401”.
- **421 za FQDN** bez allowlisty `transport_security` — test na kontenerze z nagłówkiem `Host` innym niż localhost.
- **Wspólny `etap13.tfstate`:** apply bez `-target` niszczy zasoby 13/15/19c — dlatego plan musi pokazać `1 to add`.
- **Ingress zewnętrzny** = endpoint w internecie; chroni go tylko token. Scale-to-0 i destroy 08.11 ograniczają ekspozycję.
- **Token w konfiguracji Claude Code** (plaintext w `~/.claude.json`, scope local) — krótki czas życia, nie commitować, usunąć serwer po demie.
- Czas: 1 dzień. Kolejność cięcia przy braku czasu: zadanie 5 (próba OAuth) → MCP Inspector → spany w App Insights.

## Czego nie robić

- Nie dodawać narzędzi zapisujących (decyzja, status, upload) ani wołających graf/LLM czatu.
- Nie montować MCP w `uw-api`, nie zmieniać jego ingressu ani autoryzacji; nie dodawać providera `azuread`.
- Nie uruchamiać `infra/main.bicep` ani `terraform apply` bez `-target`; nie wdrażać bez zgody właściciela.
- Nie przekazywać tokenu klienta dalej (do AI Search, bazy) — serwer używa własnej tożsamości zarządzanej.
- Nie trzymać tokenów w repo, argumentach CLI ani logach; nie wpisywać argumentów narzędzi do spanów.
