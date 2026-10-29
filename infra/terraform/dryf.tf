// Etap 15 (zadanie 6) - job dryfu cech modelu ryzyka szkody: pierwszy Container Apps Job,
// plus dwa alerty (A: dryf albo awaria joba, B: job sie nie wykonal) do ISTNIEJACEJ action group.
//
// Plik jest CALKOWICIE ADDYTYWNY: nic z main.tf / foundry.tf nie jest zmieniane. Z main.tf
// uzywa tylko: data.azurerm_resource_group.rg, data.azurerm_log_analytics_workspace.uw,
// azurerm_application_insights.uw i azurerm_monitor_action_group.uw.
//
// Zasoby z Bicepa (srodowisko, uw-api, tozsamosc, Storage) sa CZYTANE przez `data`, nie
// tworzone. Job dostaje ten sam obraz, te same sekrety (DB, App Insights) i ta sama
// tozsamosc co uw-api. Komenda: `python -m ryzyko.job_dryfu` (ryzyko/job_dryfu.py).

variable "dryf_srodowisko" {
  description = "Istniejace Container Apps Environment (infra/main.bicep: nazwaSrodowiska)."
  type        = string
  default     = "uw-demo-env"
}

variable "dryf_api" {
  description = "Istniejace Container App API - z niego bierzemy obraz, serwer ACR i sekret bazy."
  type        = string
  default     = "uw-api"
}

variable "dryf_tozsamosc" {
  description = "Istniejaca tozsamosc zarzadzana uw-api (AcrPull, Blob Data Contributor); job uzywa tej samej."
  type        = string
  default     = "uw-demo-id"
}

variable "dryf_obraz" {
  description = "Nadpisanie obrazu joba. Domyslnie null = ten sam obraz, ktory aktualnie ma uw-api (czytany przy plan/apply)."
  type        = string
  default     = null
}

variable "dryf_okno_braku_joba" {
  description = "Okno alertu B jako timespan KQL (np. 26h, 10m). Produkcyjnie 26h; do testu alertu B tymczasowo 10m (-var), potem powrot - patrz docs/MLOPS.md."
  type        = string
  default     = "26h"
}

data "azurerm_container_app_environment" "dryf" {
  name                = var.dryf_srodowisko
  resource_group_name = data.azurerm_resource_group.rg.name
}

// read_secrets = true: provider czyta wartosci sekretow uw-api (wymaga prawa listSecrets - ma je
// Właściciel jako wlasciciel). Dzieki temu job dostaje DATABASE_URL z tego samego sekretu co API,
// bez recznego kopiowania hasla. Wartosc trafia do stanu Terraform (backend Blob, Entra ID) i
// jest oznaczona jako sensitive - nie pojawia sie w wyjsciu plan/apply.
data "azurerm_container_app" "dryf_api" {
  name                = var.dryf_api
  resource_group_name = data.azurerm_resource_group.rg.name
  read_secrets        = true
}

data "azurerm_user_assigned_identity" "dryf" {
  name                = var.dryf_tozsamosc
  resource_group_name = data.azurerm_resource_group.rg.name
}

data "azurerm_storage_account" "dryf" {
  name                = var.storage_konto
  resource_group_name = data.azurerm_resource_group.rg.name
}

locals {
  dryf_obraz        = coalesce(var.dryf_obraz, data.azurerm_container_app.dryf_api.template[0].container[0].image)
  dryf_serwer_acr   = data.azurerm_container_app.dryf_api.registry[0].server
  dryf_database_url = one([for s in data.azurerm_container_app.dryf_api.secret : s.value if s.name == "database-url"])
}

resource "azurerm_container_app_job" "dryf" {
  name                         = "uw-dryf"
  location                     = data.azurerm_resource_group.rg.location
  resource_group_name          = data.azurerm_resource_group.rg.name
  container_app_environment_id = data.azurerm_container_app_environment.dryf.id
  workload_profile_name        = "Consumption" // Azure ustawia domyslnie; bez tego plan pokazuje wieczny dryf

  // Job krotki (kilka sekund + start kontenera). Brak ponowien: nieudany bieg ma byc WIDOCZNY
  // (span ERROR -> alert A), a nie po cichu powtarzany; nastepny bieg jest za 24 h albo reczny.
  replica_timeout_in_seconds = 600
  replica_retry_limit        = 0

  schedule_trigger_config {
    cron_expression          = "0 6 * * *" // UTC
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.dryf.id]
  }

  registry {
    server   = local.dryf_serwer_acr
    identity = data.azurerm_user_assigned_identity.dryf.id
  }

  secret {
    name  = "database-url"
    value = local.dryf_database_url
  }

  secret {
    name  = "appinsights-cs"
    value = azurerm_application_insights.uw.connection_string
  }

  template {
    container {
      name   = "dryf"
      image  = local.dryf_obraz
      cpu    = 0.5
      memory = "1Gi"

      command = ["python", "-m", "ryzyko.job_dryfu"]

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-cs"
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "uw-dryf"
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = data.azurerm_user_assigned_identity.dryf.client_id
      }
      env {
        name  = "AZURE_STORAGE_ACCOUNT_URL"
        value = data.azurerm_storage_account.dryf.primary_blob_endpoint
      }
      env {
        name  = "KONTENER_MODELI"
        value = "modele"
      }
    }
  }
}

// Alert A "dryf albo awaria joba" - ocenia OSTATNI span dryf.przebieg z ostatnich 25 h (nie kazdy):
// dzieki temu kolejny, zdrowy bieg zamyka alert (Resolved) od razu, a nie dopiero po 25 h.
// Zapytanie bez `by` zawsze zwraca 1 wiersz (problemy = 0 w stanie zdrowym i gdy brak spanow),
// wiec "Total" + metric_measure_column - tak samo jak alert awarii z main.tf.
// ZA_MALO_DANYCH (psi_max puste) NIE odpala alertu - swiadoma luka, patrz SPEC decyzja 10.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "dryf" {
  name                = "uw-demo-alert-dryf"
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location

  // window_duration w alertach v2 ma sztywna liste (max P2D) - 25 h nie istnieje, wiec okno jest
  // P2D, a faktyczne 25 h wycina warunek `TimeGenerated > ago(25h)` w zapytaniu.
  evaluation_frequency    = "PT5M"
  window_duration         = "P2D"
  scopes                  = [data.azurerm_log_analytics_workspace.uw.id]
  severity                = 2
  auto_mitigation_enabled = true

  display_name = "uw-dryf: dryf cech modelu ryzyka albo awaria joba"
  description  = <<-OPIS
    Co padlo: ostatni span dryf.przebieg (job uw-dryf, codziennie 06:00 UTC) z ostatnich 25 h ma
    psi_max > 0,2 (dryf cech modelu ryzyka szkody) ALBO Success == false (job sie wykonal i padl:
    brak referencji w Blob, blad bazy, PSI nie do policzenia).
    Skutek: model ryzyka szkody moze oceniac dane, ktorych nie widzial w treningu (sygnal dla
    likwidatora traci wiarygodnosc) albo monitoring dryfu nie dziala. Decyzji wnioskow to nie zmienia.
    Kroki: 1) KQL z docs/MLOPS.md, sekcja "Zapytania KQL" - atrybuty uw.dryf.status, uw.dryf.cecha_max,
    uw.dryf.psi.<cecha>, error.type, uw.dryf.etap_bledu; 2) przy bledzie: etap "referencja" = sprawdz
    modele/ryzyko_szkody/referencja.json w Blob (konto uwdemostxx1, kontener modele; zapisuje je
    pipeline_ml/eksportuj_championa), etap "baza" = polaczenie z Postgresem (uw-api /zdrowie),
    log wykonania: `az containerapp job execution list -n uw-dryf -g rg-underwriter-demo`;
    3) przy dryfie: czy zmienil sie rozklad wnioskow (nowa polisa/kanal), czy to blad zrodla danych;
    jesli dryf realny - uruchom pipeline ML od nowa (docs/MLOPS.md), potem eksportuj_championa.
    Czego NIE robic: nie kasowac wierszy z wejscia_modelu "zeby alert zniknal" (to dane monitoringu),
    nie podnosic progu 0,2 bez decyzji; wiersze zrodlo='symulacja' sprzata sie tylko skryptem
    ryzyko.zasiej_wejscia --sprzatnij.
  OPIS

  criteria {
    query = <<-QUERY
      union AppRequests, AppDependencies
      | where Name == "dryf.przebieg" and TimeGenerated > ago(25h)
      | top 1 by TimeGenerated desc
      | extend psi_max = todouble(Properties["uw.dryf.psi_max"])
      | summarize problemy = countif(Success == false or psi_max > 0.2)
    QUERY

    time_aggregation_method = "Total"
    metric_measure_column   = "problemy"
    threshold               = 1
    operator                = "GreaterThanOrEqual"
  }

  action {
    action_groups = [azurerm_monitor_action_group.uw.id]
  }
}

// Alert B "job sie nie wykonal" - brak jakiegokolwiek spanu dryf.przebieg w ostatnich 26 h (zmienna dryf_okno_braku_joba,
// czyli doba + 2 h zapasu). Kanal niezalezny od joba: zapytanie Azure Monitor po Log Analytics,
// nic w kontenerze nie musi zyc, zeby alarm przyszedl. Zlapie tez: job wylaczony/usuniety, cron
// nie strzelil, obraz bez ryzyko.job_dryfu (start kontenera pada przed spanem), brak telemetrii
// (zly connection string) i awarie samego eksportu spanow. Po pierwszym apply alert odpali sie
// do czasu pierwszego biegu - uruchom job recznie (docs/MLOPS.md).
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "dryf_brak_joba" {
  name                = "uw-demo-alert-dryf-brak-joba"
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location

  // Jak w alercie A: okno P2D, a faktyczne okno (26 h) wycina `ago(...)` w zapytaniu.
  evaluation_frequency    = "PT5M"
  window_duration         = "P2D"
  scopes                  = [data.azurerm_log_analytics_workspace.uw.id]
  severity                = 2
  auto_mitigation_enabled = true

  display_name = "uw-dryf: job dryfu sie nie wykonal"
  description  = <<-OPIS
    Co padlo: w ostatnich 26 h nie ma ANI JEDNEGO spanu dryf.przebieg - job uw-dryf
    (codziennie 06:00 UTC) sie nie wykonal albo nie zdazyl wyslac telemetrii.
    Skutek: dryf cech modelu ryzyka nie jest monitorowany; alert A (dryf/awaria) milczy, bo nie ma
    czego oceniac.
    Kroki: 1) `az containerapp job execution list -n uw-dryf -g rg-underwriter-demo -o table` - czy sa
    wykonania i z jakim statusem; 2) brak wykonan: `az containerapp job show -n uw-dryf -g
    rg-underwriter-demo --query properties.configuration.triggerType` (ma byc Schedule), czy job nie
    zostal usuniety/wstrzymany; 3) sa wykonania ze statusem Failed: log kontenera (Log Analytics,
    ContainerAppConsoleLogs_CL) - np. "No module named ryzyko.job_dryfu" = obraz joba bez nowego kodu
    (`az containerapp job update --image` na obecny obraz uw-api); 4) wykonania Succeeded, a spanow
    brak: connection string App Insights w sekrecie appinsights-cs joba; 5) uruchom reczny bieg:
    `az containerapp job start -n uw-dryf -g rg-underwriter-demo`.
    Czego NIE robic: nie wylaczac alertu, zanim nie wiadomo, czemu job milczy.
  OPIS

  criteria {
    query = <<-QUERY
      union AppRequests, AppDependencies
      | where Name == "dryf.przebieg" and TimeGenerated > ago(${var.dryf_okno_braku_joba})
      | summarize wykonania = count()
    QUERY

    time_aggregation_method = "Total"
    metric_measure_column   = "wykonania"
    threshold               = 1
    operator                = "LessThan"
  }

  action {
    action_groups = [azurerm_monitor_action_group.uw.id]
  }
}

output "dryf_job_nazwa" {
  description = "Nazwa Container Apps Job dryfu (do `az containerapp job start`)."
  value       = azurerm_container_app_job.dryf.name
}
