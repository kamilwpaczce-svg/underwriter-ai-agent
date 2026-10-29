# Etap 13 — Terraform: Application Insights + alert awarii

Nowe zasoby monitoringu od Etapu 13 idą przez Terraform (`infra/terraform/`), nie przez
Bicep. Istniejące zasoby (Container Apps, Postgres, Storage, Log Analytics — Etap 6)
zostają w `infra/main.bicep`, bez migracji stanu do Terraform (decyzja hybrydowa, patrz
(wewnętrzny plan etapów, poza repo)). `main.tf` czyta Log Analytics przez
`data`, nie tworzy go ponownie.

Komendy poniżej wykonuje właściciel ręcznie. Żadna nie została uruchomiona przez agenta poza
`terraform fmt -check`, `terraform init -backend=false` i `terraform validate` (bez
backendu, bez `plan`/`apply`, zero zasobów utworzonych).

## Zero sekretów w repo

- Parametry backendu (`resource_group_name`, `storage_account_name`, `container_name`,
  `key`) podaje się przy `init`, nie w `versions.tf` — tylko `use_azuread_auth = true`
  jest w repo.
- `var.email_alertow` nie ma wartości domyślnej w repo — właściciel podaje ją przy `plan`/`apply`
  (`-var="email_alertow=..."` albo plik `*.tfvars` lokalny, w `.gitignore`).
- Output `connection_string` jest `sensitive = true` — nie trafia do logów `plan`/`apply`
  bez `-json`; i tak nigdy nie wklejać go do repo.

## a) Kontener stanu w istniejącym koncie Storage

Sprawdź najpierw, czy kontener i rola już istnieją (Bicep z Etapu 6 mógł to już zrobić):

```powershell
$AZ = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
$RG = "rg-underwriter-demo"

& $AZ storage account list -g $RG -o json
& $AZ role assignment list --resource-group $RG -o json
```

Jeśli kontenera `tfstate` brak, utwórz go w koncie Storage z Bicepa (nazwa konta —
patrz `infra/main.bicep`) i nadaj sobie rolę `Storage Blob Data Contributor` na tym
koncie (wymagana przez `use_azuread_auth = true`).

## b) Init z backendem

```powershell
terraform init `
  -backend-config="resource_group_name=rg-underwriter-demo" `
  -backend-config="storage_account_name=<nazwa konta z main.bicep>" `
  -backend-config="container_name=tfstate" `
  -backend-config="key=etap13.tfstate"
```

## c) Plan i apply

```powershell
terraform plan -var="email_alertow=<adres>"
```

**Wykonuj z gałęzi `etap13`** (`git switch etap13`; z `etap14` plan pokaże `+6`, bo dojdzie
Foundry — patrz „Kolejność" w sekcji Etapu 14). Przeczytać razem z właścicielem: plan ma pokazać dokładnie 3 zasoby `to add`
(`azurerm_application_insights.uw`, `azurerm_monitor_action_group.uw`,
`azurerm_monitor_scheduled_query_rules_alert_v2.awaria`) i **zero** `to destroy`.
Dopiero potem:

```powershell
terraform apply -var="email_alertow=<adres>"
```

## d) Podłączenie connection stringa do `uw-api`

```powershell
$CS = terraform output -raw connection_string
& $AZ containerapp secret set -n uw-api -g $RG --secrets appinsights-cs=$CS
& $AZ containerapp update -n uw-api -g $RG --set-env-vars `
  APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-cs `
  OTEL_SERVICE_NAME=uw-api `
  OTEL_PYTHON_FASTAPI_EXCLUDED_URLS=zdrowie
```

Wykluczenie `/zdrowie` jest obowiązkowe — sonda Container Apps pyta je co 15 s
(`api/main.py:29` filtruje z tego samego powodu access log); bez wykluczenia ~5,8 tys.
spanów dziennie zagłusza ślady wniosków w Log Analytics. Po wdrożeniu sprawdzić KQL:

```kql
AppRequests | where Name has "zdrowie" | count
```

→ oczekiwane 0.

## e) Przed ewentualnym pełnym `deployment group create` (pełny Bicep) po Terraform

`infra/main.bicep` ma parametr `appInsightsConnectionString` (Zadanie 6, Etap 13) —
od rundy poprawek 1/5 jest **wymagany, bez wartości domyślnej** (jak `hasloPostgres`):
brak zmiennej środowiskowej ma wywrócić build Bicepa głośno (`BCP427`), nie po cichu
skasować sekret `appinsights-cs` i zmienne `OTEL_*`/`APPLICATIONINSIGHTS_CONNECTION_STRING`
w `uw-api`. Zanim więc puścisz pełny `deployment group create` (np. po zmianie czegoś
innego w `main.bicep`), zrób w tej samej sesji PowerShell:

```powershell
$env:APPINSIGHTS_CONNECTION_STRING_ETAP13 = terraform -chdir=infra/terraform output -raw connection_string
```

(wymaga, żeby `terraform apply` z kroku c) już przeszło — inaczej nie ma czego odczytać).
Bez tego `main.bicepparam` sam odmówi (`readEnvironmentVariable` bez wartości domyślnej).

**Przypomnienie (infra/README.md, krok d — Easy Auth):** pełny `deployment group create`
nie zna sekretu klienta aplikacji Entra na `uw-web` (nie może trafić do Bicepa) — po
każdym pełnym wdrożeniu trzeba ręcznie powtórzyć `az containerapp auth microsoft update`
z kroku d), inaczej `uw-web` zostaje publicznie dostępne bez logowania.

## Koszt (do potwierdzenia w kalkulatorze przed `apply`)

App Insights pay-per-GB na istniejącym Log Analytics (ruch demo ≈ MB → grosze);
reguła alertu logów co 5 min ≈ 1,5 USD/mies.; action group (mail) — darmowe.

## Etap 14 — projekt Foundry do ewaluacji sędzią LLM (`foundry.tf`)

Nowe konto `AIServices` (`uw-demo-ai-xx1`, bez kluczy — `local_auth_enabled = false`,
tylko Entra) i projekt `uw-demo-ewaluacja` (`azurerm_cognitive_account_project`, nowe
doświadczenie Foundry; **nie** hub classic `azurerm_ai_foundry`). Konto `uw-demo-aoai-xx1`
z Bicepa nie jest ruszane — sędzia `gpt-5-mini` zostaje na nim (DSZ0 pkt 1).
Koszt: konto i projekt bez opłaty stałej (założenie, DSZ0 pkt 9 — sprawdzić w Cost
Management po 24 h), rola 0 USD. **Bez upgrade'u trialu**, `spendingLimit On`.

Zmienne opcjonalne (domyślnie wyłączone): `wdroz_sedziego_4o_mini` (fallback, niepotrzebny
wg DSZ0 pkt 1; model jest „Deprecating", wycofanie 2027-04-14) i `polacz_storage` (połączenie
Storage + 2 role `Storage Blob Data Owner` na koncie z Bicepa — zmiana uprawnień, włączać
dopiero po błędzie uploadu/403 z pierwszego `evaluate`).

**Ostrzeżenie przy `polacz_storage = true`:** rola `Storage Blob Data Owner` ma zakres
całego konta Storage, na którym leży też kontener `tfstate` (stan zawiera connection string
App Insights). Tożsamość projektu Foundry i Twoje konto dostaną więc odczyt/zapis stanu
Terraform. Przed włączeniem rozważyć zawężenie roli do dedykowanego kontenera na wyniki
ewaluacji (zakres roli w `foundry.tf` celowo nie został zmieniony — narzuca go brief).

**Kolejność (liniowo, bez wracania):** oba etapy dzielą ten sam stan (`etap13.tfstate`),
a `foundry.tf` istnieje tylko na gałęzi `etap14`. Dlatego Etap 13 stosuje się z gałęzi `etap13`:

1. `git switch etap13`. Na tej gałęzi nie ma `foundry.tf`, więc plan Etapu 13 to dokładnie
   `+3 to add` (kroki a)-c) powyżej; README na `etap13` nie zawiera sekcji Etapu 14 — ta
   sekcja czeka na gałęzi `etap14`). Katalog `.terraform` jest poza gitem i przeżywa przełączenie.
2. `terraform plan` (`+3`) → `terraform apply` → krok d) (sekret `appinsights-cs`, zmienne
   `OTEL_*`), Bicep wg kroku e), jeśli go puszczasz, i test alarmu wg opisu Etapu 13 (`docs/ROZWOJ.md`).
3. `git switch etap14` i dalej poniżej: plan Etapu 14 to `+3` (Foundry) → apply.

**`+6` w planie znaczy: jesteś na `etap14` przed apply Etapu 13 — zrób `git switch etap13`**
(krok 1), nie stosuj planu z `+6`.

`terraform init` nie jest potrzebny, jeśli katalog `.terraform` jest już zainicjalizowany z
backendem (krok b)). Inaczej wykonać init z parametrami inline z kroku b) — pliku
`backend.hcl` nie ma w repo.

```powershell
cd infra\terraform
terraform plan -var="email_alertow=<adres>" -out etap14.tfplan
terraform apply etap14.tfplan
terraform output -raw foundry_projekt_endpoint
```

Oczekiwany plan: `+3 to add` (konto AIServices, projekt, rola `Foundry User`, dawniej `Azure AI User`), 0 change,
0 destroy (Etap 13 zastosowany z gałęzi `etap13`, patrz „Kolejność"). Jeśli widzisz `+6`
(dochodzą App Insights, action group, alert), stop: `git switch etap13` i zastosuj najpierw
Etap 13. Jakakolwiek zmiana/usunięcie zasobów Etapu 13 = **stop**, nie apply. Wynik
`output` → `$env:AZURE_AI_PROJECT_ENDPOINT`.

**Pułapka soft-delete:** po `terraform destroy` konto AIServices zostaje na 48 h w
soft-delete i blokuje nazwę oraz subdomenę `uw-demo-ai-xx1`, więc ponowny `apply` w tym
oknie padnie. Przed ponownym `apply` albo wyczyść konto:

```powershell
& $AZ cognitiveservices account purge -g rg-underwriter-demo -n uw-demo-ai-xx1 -l swedencentral
```

albo podaj inną nazwę: `-var="foundry_konto=<inna-nazwa>"` (zmienna `foundry_konto` w
`variables.tf` jest jednocześnie subdomeną `*.services.ai.azure.com`; wtedy zmieni się też
URL w `foundry_projekt_endpoint`).

Po apply sprawdzić (DSZ0): (8) `terraform state show azurerm_cognitive_account_project.ewaluacja`
— czy atrybut `endpoints` zgadza się z URL z outputu (output budowany z formatu README
`azure-ai-evaluation`, nie z atrybutu); (4) czy rola `Foundry User` (dawniej `Azure AI User`) wystarcza do zapisu
wyników `evaluate` (403 = brak roli); (3) czy `evaluate` z projektem działa bez
`polacz_storage`; (9) koszt konta po 24 h.
