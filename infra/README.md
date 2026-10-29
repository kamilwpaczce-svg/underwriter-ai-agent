# Etap 6 — wdrożenie na Azure (PowerShell)

Komendy poniżej wykonuje właściciel ręcznie, w podanej kolejności, po przeglądzie kodu i
Bicepa. Żadna z nich nie została uruchomiona przez agenta — ten plik jest tylko
instrukcją. `az bicep build` (kompilacja lokalna, bez wdrożenia) został uruchomiony
i przeszedł bez błędów/ostrzeżeń — patrz raport sesji.

Wszystkie komendy `az` przez pełną ścieżkę (unika konfliktu z ewentualnym innym
`az` w PATH):

```powershell
$AZ = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
```

**Uwaga o `az.cmd` i `--query`:** na Windows nawiasy `()` i przecinki `,` w wyrażeniu
`--query` bywają łamane przez cudzysłowowanie PowerShella/cmd (np.
`--query "[?contains(name,'x')]"` się wywala). Dwa bezpieczne obejścia:
- proste ścieżki pól z `-o tsv`, np. `--query id -o tsv` (bez nawiasów/przecinków) —
  działa zawsze;
- dla czegokolwiek bardziej złożonego: pobierz pełny JSON (`-o json`) i przepuść przez
  `ConvertFrom-Json`, filtruj po stronie PowerShella, nie po stronie `--query`.

Zmienna grupy zasobów (istniejąca, patrz `PROJECT_KNOWLEDGE.md` / ustalenia Etapu 5):

```powershell
$RG = "rg-underwriter-demo"
```

## a) Rejestracja dostawców zasobów

Jeśli to pierwsze użycie tych usług w tej subskrypcji, zarejestruj dostawców (jeśli
Właściciel już to zrobił przy Etapie 5 dla Cognitive Services — pomiń ten krok, sprawdź
`Microsoft.App`/`Microsoft.DBforPostgreSQL`/`Microsoft.ContainerRegistry` stanem
`Registered` w `& $AZ provider show -n <nazwa> --query registrationState -o tsv`):

```powershell
& $AZ provider register --namespace Microsoft.App
& $AZ provider register --namespace Microsoft.ContainerRegistry
& $AZ provider register --namespace Microsoft.DBforPostgreSQL
& $AZ provider register --namespace Microsoft.OperationalInsights
& $AZ provider register --namespace Microsoft.ManagedIdentity
```

Rejestracja działa asynchronicznie — jeśli `deployment group create` (krok c) zgłosi
błąd o nierozpoznanym typie zasobu, odczekaj chwilę i sprawdź stan ponownie.

## b) Hasło Postgresa — wyłącznie do zmiennej środowiskowa procesu

Hasło NIE trafia do pliku, repo, logów ani sesji Claude. Generowane lokalnie,
trzymane tylko w pamięci bieżącego procesu PowerShell:

```powershell
$b = New-Object byte[] 18
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
$env:HASLO_POSTGRES_ETAP6 = "Aa1" + ([Convert]::ToBase64String($b) -replace '[+/=]', 'x')
```

Tylko litery i cyfry (kryptograficzny generator): haslo trafia do `DATABASE_URL`
(`postgresql://uzytkownik:haslo@host/...`), wiec znaki `@ : / # % ?` rozbilyby adres
i API nie wstaloby. Przedrostek `Aa1` gwarantuje wymagania zlozonosci Azure Postgres
(3 z 4 kategorii: wielkie, male, cyfry), a 18 losowych bajtow daje ok. 144 bity entropii.

`infra/main.bicepparam` czyta je przez `readEnvironmentVariable('HASLO_POSTGRES_ETAP6')`
— nie ma go nigdzie w plikach repo. Zapisz je też w KeePassXC (ręcznie, poza tą sesją)
zanim zamkniesz terminal — po zamknięciu procesu PowerShell zmienna znika.

## c) Wdrożenie Bicepa

```powershell
& $AZ deployment group create `
  --resource-group $RG `
  --parameters infra/main.bicepparam
```

Pierwsze wdrożenie stawia `uw-api`/`uw-web` na obrazie zastępczym
(`mcr.microsoft.com/k8se/quickstart:latest` — domyślna wartość `obrazApi`/`obrazWeb`
w `main.bicep`). To jest oczekiwane — prawdziwe obrazy wejdą dopiero przez CI/CD
(krok f + `.github/workflows/ci-cd.yml`) albo ręcznie (patrz niżej).

**Ponowne wdrożenie po tym, jak CI/CD już wypchnęło obrazy:** podaj bieżące obrazy
jako parametry, inaczej ten `deployment group create` cofnie obie Container Apps do
obrazu zastępczego (Bicep nie "pamięta" zmian zrobionych poza nim przez
`az containerapp update --image`):

```powershell
$obrazApiBiezacy = & $AZ containerapp show -n uw-api -g $RG --query "properties.template.containers[0].image" -o tsv
$obrazWebBiezacy = & $AZ containerapp show -n uw-web -g $RG --query "properties.template.containers[0].image" -o tsv

& $AZ deployment group create `
  --resource-group $RG `
  --parameters infra/main.bicepparam `
  --parameters obrazApi=$obrazApiBiezacy obrazWeb=$obrazWebBiezacy
```

## d) Easy Auth (Entra ID) na `uw-web`

Aplikacja Entra dla logowania użytkowników (inny byt niż aplikacja OIDC dla GitHub
w kroku e — ta jest "redirect login", tamta "machine-to-machine"):

```powershell
$tenantId = & $AZ account show --query tenantId -o tsv
$webFqdn  = & $AZ containerapp show -n uw-web -g $RG --query properties.configuration.ingress.fqdn -o tsv

# Redirect URI callbacku Easy Auth + wydawanie id_token - bez nich logowanie konczy
# sie bledem AADSTS50011 (redirect URI mismatch) po stronie Entra.
$easyAuthApp = & $AZ ad app create --display-name "uw-web-easyauth" --sign-in-audience AzureADMyOrg `
  --web-redirect-uris "https://$webFqdn/.auth/login/aad/callback" `
  --enable-id-token-issuance true | ConvertFrom-Json
$easyAuthAppId = $easyAuthApp.appId

# Sekret klienta - do zmiennej, NIGDY Write-Host/echo.
$easyAuthSecret = (& $AZ ad app credential reset --id $easyAuthAppId --append --query password -o tsv)

# Sekret trafia do sekretow Container App (szyfrowane w Azure), potem dopiero
# podpinany jako provider Microsoft Entra.
& $AZ containerapp secret set -n uw-web -g $RG --secrets "msft-client-secret=$easyAuthSecret"

& $AZ containerapp auth microsoft update `
  -n uw-web -g $RG `
  --client-id $easyAuthAppId `
  --client-secret-name msft-client-secret `
  --issuer "https://login.microsoftonline.com/$tenantId/v2.0" `
  --yes

& $AZ containerapp auth update `
  -n uw-web -g $RG `
  --enabled true `
  --action RedirectToLoginPage `
  --redirect-provider azureactivedirectory
```

(Nazwy flag sprawdzone `--help` na zainstalowanym `az` 2026-10-11:
`--action` jest aliasem `--unauthenticated-client-action`; sekret providera to
`--client-secret-name`, NIE `--client-secret-setting-name` — tej flagi nie ma.)

Weryfikacja bez logowania w przeglądarce: `curl.exe -I https://<fqdn uw-web>/`
powinno zwrócić `302` (przekierowanie do logowania), nie `200`.

## e) OIDC dla GitHub Actions (osobna aplikacja Entra, bez haseł)

```powershell
$subId = & $AZ account show --query id -o tsv
$owner = "<github-uzytkownik>"
$repo  = "underwriter-agent-demo"   # nazwa repo na GitHubie (myslniki), nie katalogu

$oidcApp = & $AZ ad app create --display-name "uw-demo-github-oidc" | ConvertFrom-Json
$oidcAppId = $oidcApp.appId
$oidcSp = & $AZ ad sp create --id $oidcAppId | ConvertFrom-Json
$oidcSpId = $oidcSp.id
```

Federated credential (plik tymczasowy — `az.cmd` na Windows psuje cudzysłowowanie
zagnieżdżonego JSON-a podanego inline):

```powershell
$federowane = @{
  name      = "github-main"
  issuer    = "https://token.actions.githubusercontent.com"
  # ${repo} w klamrach: PowerShell czyta "$repo:ref" jako zmienna z zakresem "repo:"
  # (jak $env:PATH) i wstawia pusty napis - sprawdzone w PS 5.1: wychodzi
  # "repo:<github-uzytkownik>//heads/main" i logowanie OIDC w Actions odpada.
  # GitHub wysyla dla tego repo subject w formacie NIEZMIENNYM, z numerycznymi ID
  # wlasciciela i repo (odczytane z logu azure/login 2026-10-11, AADSTS700213 przy
  # starym formacie "repo:wlasciciel/repo:..."). ID nie zmienia sie po zmianie nazwy repo.
  subject   = "repo:${owner}@276399789/${repo}@1413982901:ref:refs/heads/main"
  audiences = @("api://AzureADTokenExchange")
} | ConvertTo-Json

$tmpPlik = New-TemporaryFile
Set-Content -Path $tmpPlik -Value $federowane -Encoding utf8
& $AZ ad app federated-credential create --id $oidcAppId --parameters "@$tmpPlik"
Remove-Item $tmpPlik
```

Role — **na pojedynczych zasobach, NIE na grupie zasobów** (zasada najmniejszych
uprawnień z `SPEC_ETAP6.md`):

```powershell
$acrId = & $AZ acr show -n uwdemoacrxx1 -g $RG --query id -o tsv
$apiId = & $AZ containerapp show -n uw-api -g $RG --query id -o tsv
$webId = & $AZ containerapp show -n uw-web -g $RG --query id -o tsv
$envId = & $AZ containerapp show -n uw-api -g $RG --query properties.managedEnvironmentId -o tsv

& $AZ role assignment create --assignee-object-id $oidcSpId --assignee-principal-type ServicePrincipal --role AcrPush --scope $acrId
& $AZ role assignment create --assignee-object-id $oidcSpId --assignee-principal-type ServicePrincipal --role Reader --scope $acrId
& $AZ role assignment create --assignee-object-id $oidcSpId --assignee-principal-type ServicePrincipal --role Contributor --scope $apiId
& $AZ role assignment create --assignee-object-id $oidcSpId --assignee-principal-type ServicePrincipal --role Contributor --scope $webId
& $AZ role assignment create --assignee-object-id $oidcSpId --assignee-principal-type ServicePrincipal --role Contributor --scope $envId
```

Po co dwie role ponad minimum:
- **Reader na ACR**: `az acr login --name` najpierw odpytuje ARM o login server
  rejestru; AcrPush daje tylko push/pull na płaszczyźnie danych.
- **Contributor na środowisku Container Apps**: `az containerapp update` wysyła
  pełną definicję aplikacji z `environmentId`, co wymaga
  `Microsoft.App/managedEnvironments/join/action` na środowisku.
Obie nadal ograniczone do pojedynczych zasobów, nie do grupy zasobów.

## f) Zmienne repo GitHub (identyfikatory, NIE sekrety)

Wymaga `gh auth login` wykonanego wcześniej (poza zakresem tej sesji). To są
identyfikatory publiczne w sensie bezpieczeństwa (client ID, nazwy zasobów) — OIDC nie
potrzebuje żadnego hasła ani tokenu po stronie GitHuba, dlatego `gh variable set`, nie
`gh secret set`:

```powershell
gh variable set AZURE_CLIENT_ID --body $oidcAppId
gh variable set AZURE_TENANT_ID --body $tenantId
gh variable set AZURE_SUBSCRIPTION_ID --body $subId
gh variable set AZURE_RESOURCE_GROUP --body $RG
gh variable set ACR_NAME --body uwdemoacrxx1
gh variable set CONTAINER_APP_API --body uw-api
gh variable set CONTAINER_APP_WEB --body uw-web
```

Te same nazwy (`vars.AZURE_CLIENT_ID` itd.) są użyte w
`.github/workflows/ci-cd.yml` — jeśli zmienisz nazwę tutaj, zmień też tam.

## g) Etap 15+: CI/CD modelu (`.github/workflows/model.yml`)

Ta sama tożsamość OIDC co deploy API (`$oidcSpId` z kroku e), dodatkowo rola na **jednym**
workspace Azure ML, nie na grupie zasobów:

```powershell
$mlwId = & $AZ ml workspace show -n uw-demo-mlw -g $RG --query id -o tsv
& $AZ role assignment create --assignee-object-id $oidcSpId --assignee-principal-type ServicePrincipal --role "AzureML Data Scientist" --scope $mlwId
```

Workflow uruchamiany tylko ręcznie (`gh workflow run model.yml -f rodzaj=zepsuty`), bo każdy
bieg to płatne minuty serverless. Kryterium akceptacji: dwa biegi z Actions - `hgb` (promocja
albo odrzucenie zależnie od championa) i `zepsuty` (odrzucenie) - oba zielone, werdykt bramki
w podsumowaniu joba.

## Świadome kompromisy demo (opisane też w `SPEC_ETAP6.md`)

- **Postgres: publiczny endpoint + reguła „Allow public access from any Azure
  service" (0.0.0.0–0.0.0.0) + hasło zamiast Entra.** Container Apps Consumption nie
  ma stałych adresów wychodzących, więc nie da się zawęzić firewalla do konkretnych
  IP bez VNet integration. Produkcyjnie: VNet-integrated environment + private
  endpoint Postgresa + uwierzytelnienie Entra — nieuzasadnione kosztowo/czasowo w
  demo kończącym się przed wygaśnięciem kredytu (9.11.2026).
- **Obie Container Apps max 1 replika.** Agent biegnie w tle w procesie API, a
  migracje Alembic (`MIGRACJE_PRZY_STARCIE=1`) odpalają się przy starcie kontenera —
  dwie repliki jednocześnie startujące = wyścig o te same migracje.
