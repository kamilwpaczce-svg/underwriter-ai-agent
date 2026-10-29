# Etap 6 — wdrożenie na Azure: Container Apps, Managed Identity, GitHub Actions

Cel: ten sam system co lokalnie (API + agent + panel Next.js), działający w Azure,
wdrażany z prywatnego repo GitHub, **bez ani jednego klucza/sekretu dostępu do usług Azure**
(Managed Identity + OIDC). Jedyny sekret aplikacji to hasło Postgresa (sekret Container Apps).

Termin: przed 9.11.2026 (wygasa kredyt trialu). Zgoda właściciela na zasoby i koszt: 2026-10-11.

## Architektura docelowa

```
przeglądarka ──HTTPS──> uw-web (Container App, ingress ZEWNĘTRZNY, Easy Auth Entra)
                           │  Next.js: strony + proxy /api/* (route handler)
                           └──HTTP wewnątrz środowiska──> uw-api (ingress WEWNĘTRZNY, bez dostępu z internetu)
                                                            ├─ Postgres Flexible B1ms (SSL, hasło z sekretu)
                                                            ├─ Blob Storage (Managed Identity)
                                                            ├─ Azure OpenAI gpt-5-mini (Managed Identity)
                                                            └─ Document Intelligence F0 (Managed Identity)
GitHub Actions (prywatne repo) ──OIDC──> ACR (push obrazów) + az containerapp update
```

Dlaczego proxy w Next.js, a nie API wystawione publicznie: Easy Auth działa na ciasteczku
domeny `uw-web`; przeglądarka nie dośle go do innej domeny (`uw-api`), więc API publiczne
musiałoby mieć osobne uwierzytelnienie albo stać otworem (każdy spala kredyt na LLM).
Z proxy API nie ma w ogóle adresu w internecie, a CORS przestaje być potrzebny.

## Zasoby (grupa `rg-underwriter-demo`, swedencentral — istniejąca)

| zasób | nazwa | SKU | koszt do 9.11 |
|---|---|---|---|
| Log Analytics | `uw-demo-logs` | PerGB2018, retencja 30 dni | ~0 (5 GB/mies. gratis) |
| Container Apps Environment | `uw-demo-env` | Consumption | 0 |
| Container App API | `uw-api` | 0,5 vCPU / 1 GiB, min 0, **max 1** replika | ~0 (pula darmowa) |
| Container App frontend | `uw-web` | 0,25 vCPU / 0,5 GiB, min 0, max 1 | ~0 |
| Container Registry | `uwdemoacrxx1` | Basic, admin user **wyłączony** | ~5 USD |
| Postgres Flexible | `uw-demo-pg-xx2` (polandcentral) | Standard_B1ms, 32 GB, wersja 17, backup 7 dni, bez HA | 0 (750 h free) / ~15 USD |
| Storage Account | `uwdemostxx1` | Standard_LRS, StorageV2, `allowSharedKeyAccess=false`, kontener `wnioski` prywatny | < 0,1 USD |
| User-assigned MI | `uw-demo-id` | — | 0 |

API max 1 replika celowo: agent biegnie w tle w procesie API, a migracje Alembic odpalają się
przy starcie — dwie repliki = wyścig migracji. Opisać w README jako świadomy kompromis demo.

### Role dla `uw-demo-id` (zakres: pojedynczy zasób, nie grupa)

| rola | zasób |
|---|---|
| AcrPull | `uwdemoacrxx1` |
| Cognitive Services OpenAI User | `uw-demo-aoai-xx1` |
| Cognitive Services User | `uw-demo-docint-xx1` |
| Storage Blob Data Contributor | `uwdemostxx1` |

### Postgres — dostęp sieciowy

Publiczny endpoint + reguła „Allow public access from any Azure service” (0.0.0.0) + wymuszony SSL.
Container Apps Consumption nie ma stałych adresów wychodzących. **W README jako świadomy kompromis**:
produkcyjnie VNet-integrated environment + private endpoint Postgresa (koszt i czas nieuzasadnione w demo).
Uwierzytelnienie hasłem (nie Entra) — też kompromis, opisany jw.; hasło generuje właściciel w PowerShellu,
trafia wyłącznie do parametru `@secure()` Bicepa i sekretu Container Apps. Nigdy do repo, logów ani do sesji Claude.

## Zakres — kod

1. **Poświadczenie** (`agent/ocr_azure.py::zbuduj_poswiadczenie_azure`): `ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))` —
   tożsamość przypisana przez użytkownika wymaga `client_id`; bez zmiennej zachowanie jak dziś (system-assigned / dalej Azure CLI).
   Test jednostkowy: z `AZURE_CLIENT_ID` w env poświadczenie dostaje ten client_id (atrapa/monkeypatch, bez sieci).
2. **Blob przez Managed Identity** (`api/ustawienia.py`, `api/magazyn.py`, miejsce budowy `MagazynBlob`):
   nowa zmienna `AZURE_STORAGE_ACCOUNT_URL` (np. `https://uwdemostxx1.blob.core.windows.net`).
   Dokładnie jedna z dwóch: `AZURE_STORAGE_CONNECTION_STRING` (lokalnie, Azurite) **albo** `AZURE_STORAGE_ACCOUNT_URL`
   (Azure, poświadczenie z pkt 1). Obie albo żadna → czytelny `RuntimeError` przy starcie. Testy konfiguracji dla 4 przypadków.
   `utworz_kontener_jesli_brak` musi działać z rolą Data Contributor (tworzenie kontenera przez data plane jest dozwolone) —
   ale kontener i tak tworzy Bicep; brak uprawnień do create nie może wywrócić startu (ResourceExistsError już obsłużony; dodać
   obsługę 403 → log ostrzeżenia, start dalej).
3. **Migracje przy starcie**: `docker/start_api.sh` (albo `.py`) — gdy `MIGRACJE_PRZY_STARCIE=1`: `alembic upgrade head`, potem `exec uvicorn`.
   Błąd migracji = proces kończy się kodem ≠ 0 (kontener nie wstaje cicho bez schematu). Dockerfile API: CMD na ten skrypt;
   zachowanie lokalne (compose) bez zmiennej = jak dziś.
4. **Proxy w Next.js**: `frontend/app/api/[...sciezka]/route.ts` (GET, POST) przekazuje żądanie do `process.env.API_URL_WEWNETRZNY`
   (czytane **w czasie działania**, nie przy buildzie; domyślnie `http://localhost:8000`). Strumień ciała (multipart upload),
   status, `content-type`, `content-disposition` przekazywane bez zmian. Nagłówek `X-Uzytkownik`: jeśli w żądaniu jest
   `x-ms-client-principal-name` (ustawia go Easy Auth i nadpisuje podrobione), proxy wysyła go jako `X-Uzytkownik`
   (tylko ASCII — inaczej odrzuć 400), w przeciwnym razie przekazuje `X-Uzytkownik` od klienta (dev lokalny).
   `lib/api.ts`: `ADRES_API` = `/api` — przeglądarka zawsze mówi tylko do własnego originu. `NEXT_PUBLIC_API_URL` usunąć
   z kodu, Dockerfile frontendu i compose (zostaje `API_URL_WEWNETRZNY` jako env w czasie działania).
   Formularz decyzji: gdy aplikacja działa za Easy Auth, identyfikator z formularza jest ignorowany przez proxy —
   pokazać to w UI (np. endpoint `GET /api/.ja` w route handlerze zwracający nazwę z nagłówka albo null; jeśli jest — pole
   identyfikatora wypełnione i zablokowane). Testy Vitest dla proxy (atrapa fetch) i dla zachowania formularza.
   E2E Playwright muszą przejść lokalnie przez proxy (Next ↔ API na localhost).
5. **CORS** w API zostaje (dev bez proxy nikomu nie szkodzi), ale w Azure `CORS_ORIGINS` nie jest ustawiane.

## Zakres — infrastruktura jako kod

6. **`infra/main.bicep`** (+ `infra/main.bicepparam` bez sekretów) — wszystkie zasoby i role z tabel wyżej,
   istniejące zasoby Azure OpenAI / Document Intelligence przez `existing`. Parametry: `hasloPostgres` (`@secure()`),
   `obrazApi`, `obrazWeb` (domyślnie publiczny obraz zastępczy `mcr.microsoft.com/k8se/quickstart:latest` — pierwsze
   wdrożenie, zanim CI wypchnie prawdziwe obrazy), `adresIpAdmina` (opcjonalna reguła firewalla Postgresa dla właściciela; domyślnie pusta = brak reguły).
   Env API: `MODEL_AGENTA=azure`, `AZURE_CLIENT_ID`, endpointy z etapu 5, `AZURE_STORAGE_ACCOUNT_URL`, `KONTENER_BLOB`,
   `MIGRACJE_PRZY_STARCIE=1`, `DATABASE_URL` jako **secretRef** (sekret zbudowany w Bicepie z parametru, `sslmode=require`).
   Env web: `API_URL_WEWNETRZNY=http://uw-api`. Rejestr przez tożsamość (`registries[].identity`), nie hasło.
   Outputy: FQDN `uw-web`, nazwa ACR, client_id tożsamości. **Żadnego outputu z hasłem/connection stringiem.**
   Weryfikacja: `az bicep build` bez błędów i ostrzeżeń lintera (lub ostrzeżenia uzasadnione w komentarzu).
   Ponowne uruchomienie Bicepa nie może cofać obrazów do zastępczych — README: przekazuj bieżące obrazy jako parametry
   (podać gotową komendę PowerShell, która je odczytuje).
7. **`infra/README.md`** — komendy PowerShell (`$AZ = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"`, `& $AZ ...`),
   w kolejności, każda opisana jednym zdaniem:
   a) rejestracja dostawców (już zrobiona przez właściciela, jeśli tak — pominąć), b) generowanie hasła Postgres w PowerShellu
   do zmiennej (bez wypisywania), c) `deployment group create`, d) aplikacja Entra dla Easy Auth + `az containerapp auth microsoft update`
   (sekret klienta przekazany ze zmiennej, nie wypisany) + `--unauthenticated-client-action RedirectToLoginPage`,
   e) aplikacja Entra dla GitHub OIDC + federated credential (`repo:<owner>/<repo>:ref:refs/heads/main`) + role
   (AcrPush na ACR, Contributor na **dwóch Container Apps**, nie na grupie), f) zmienne repo GitHub (`gh variable set`, nie secrets —
   to identyfikatory, nie sekrety). Uwaga przy `az.cmd`: `--query` z nawiasami/przecinkami psuje się — używać `-o tsv` z prostym
   `--query` albo `ConvertFrom-Json`.

## Zakres — CI/CD

8. **`.github/workflows/ci-cd.yml`**: na push do `main` i ręcznie (`workflow_dispatch`).
   Job `testy`: Python 3.x (wersja jak w `.venv`), `pip install -r requirements.txt`, `pytest -q` (bez markera `azure`, bez sieci);
   Node 22: `npm ci`, `npm run lint`, `npx vitest run`, `npm run build`.
   Job `wdrozenie` (needs: testy, tylko `main`): `azure/login` przez OIDC (`permissions: id-token: write`), `az acr login`,
   `docker build` + `docker push` obu obrazów z tagiem `${{ github.sha }}` (budowa na runnerze — bez ACR Tasks),
   `az containerapp update --image` dla `uw-api` i `uw-web`, potem test dymny: `GET https://<fqdn uw-web>/` musi zwrócić
   302/401 (Easy Auth działa — strona NIE jest publiczna) — jeśli 200, job FAIL. Zero sekretów w workflow poza OIDC.
   Akcje przypięte do wersji głównej (`@v4` itp.).

## Repo

9. `git init` w `underwriter_agent_demo/`, `.gitignore` uzupełnić (frontend/node_modules, .next, test-results,
   playwright-report, .env*, poza `.env.example`). **Nie tworzyć repo na GitHubie i nie pushować** — robi to sesja główna
   po przeglądzie (repo prywatne, zgoda właściciela 2026-10-11). Przed pierwszym commitem: skan na sekrety
   (`AIza`, `AccountKey=` inne niż publiczny klucz deweloperski Azurite `Eby8vdM02x...`, `-----BEGIN`, `password=` poza compose).

## Testy i weryfikacja (wykonawca)

- `pytest -q` całość zielona (było 152 passed / 3 skipped) + nowe testy z pkt 1–3.
- Frontend: lint, Vitest, build, Playwright e2e na żywym lokalnym API — przez proxy.
- `docker build` obu obrazów lokalnie; uruchomić kontener API z `MIGRACJE_PRZY_STARCIE=1` na compose-owym Postgresie i sprawdzić `/zdrowie`.
- `az bicep build --file infra/main.bicep` (tylko kompilacja lokalna — **żadnych `az deployment`, `az ... create`, `gh repo create`, `git push`**).
- Raport: lista plików, wyniki testów (liczby), czego nie dało się sprawdzić.

## Zakazy

- Żadnych operacji tworzących/zmieniających zasoby Azure ani GitHub. Żadnego `az login`, żadnego `get_token` drukowanego.
- Nie czytać plików z kluczami (`~/.gemini_api_key*`, `.env`). Nie uruchamiać ewaluacji ani wywołań płatnych API.
- Nie zmieniać logiki agenta, reguł, promptów ani danych.
- Zero cyrylicy i emoji w plikach; UTF-8.
