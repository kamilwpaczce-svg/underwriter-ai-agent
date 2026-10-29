// Etap 13 - App Insights (workspace-based, na istniejacym Log Analytics z Bicepa),
// action group i alert awarii. Decyzja 4 (wspolne.md): alert mierzy AWARIE
// (span wniosek.*/llm.* z Success == false), nie cisze - demo nie ma regularnego
// ruchu, wiec alarm "brak wnioskow" mierzylby brak uzytkownikow, nie awarie.

data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

data "azurerm_log_analytics_workspace" "uw" {
  name                = var.log_analytics_workspace_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_application_insights" "uw" {
  name                = "uw-demo-appinsights"
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  workspace_id        = data.azurerm_log_analytics_workspace.uw.id
  application_type    = "web"
  sampling_percentage = 100
}

resource "azurerm_monitor_action_group" "uw" {
  name                = "uw-demo-alerty"
  resource_group_name = data.azurerm_resource_group.rg.name
  short_name          = "uwalerty"

  email_receiver {
    name          = "underwriter-admin"
    email_address = var.email_alertow
  }
}

// Zapytanie i warunek: patrz task-5-brief.md. "bledy >= 1" = GreaterThanOrEqual na
// progu 1. Zapytanie BEZ "by" zawsze zwraca dokladnie 1 wiersz (kolumna `bledy`
// z liczba bledow, 0 w stanie zdrowym) - time_aggregation_method "Count" liczylby
// WIERSZE (zawsze 1, alert strzelalby stale), nie wartosc kolumny `bledy`. Dlatego
// "Total" + metric_measure_column = "bledy" (sumuje wartosc kolumny z jedynego
// wiersza) - "Total" wymaga metric_measure_column (niedozwolone przy "Count").
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "awaria" {
  name                = "uw-demo-alert-awaria"
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location

  // Scope = workspace Log Analytics, nie App Insights: zapytanie uzywa nazw tabel
  // workspace'u (AppRequests/AppDependencies, kolumny Name/Success); z poziomu zasobu
  // App Insights obowiazuje stary schemat (requests/dependencies). Etap 13, przeglad koncowy.
  evaluation_frequency    = "PT5M"
  window_duration         = "PT15M"
  scopes                  = [data.azurerm_log_analytics_workspace.uw.id]
  severity                = 2
  auto_mitigation_enabled = true

  display_name = "uw-api: awaria wniosku albo wywolania LLM"
  description  = <<-OPIS
    Co padlo: co najmniej 1 nieudany span wniosek.* albo llm.* w ostatnich 15 minutach
    (Success == false) - z uw-api ORAZ ze skryptu testu alarmu (AppRoleName uw-test-alarmu).
    Skutek: wniosek prawdopodobnie trafil do statusu BLAD, albo zostal skierowany do czlowieka
    z flaga bledu wywolania LLM.
    Kroki: 1) zapytanie KQL z docs/MONITORING.md, sekcja "Ostatnie błędy" (kolumny error.type,
    uw.wniosek_id); 2) GET /wnioski/{id}/audyt dla znalezionego wniosku; 3) sprawdz limit TPM
    i status uslugi uw-demo-aoai-xx1 (Azure OpenAI).
    Sciezka awaryjna: przelacz MODEL_AGENTA=atrapa przez `az containerapp update` (uw-api).
    Czego NIE robic: nie restartowac Postgresa, nie puszczac pelnego `deployment group create`
    z infra/main.bicep (kasuje sekret Easy Auth uw-web - patrz wspolne.md).
  OPIS

  criteria {
    query = <<-QUERY
      union AppRequests, AppDependencies
      | where Name startswith "wniosek." or Name startswith "llm."
      | where Success == false
      | summarize bledy = count()
    QUERY

    time_aggregation_method = "Total"
    metric_measure_column   = "bledy"
    threshold               = 1
    operator                = "GreaterThanOrEqual"
  }

  action {
    action_groups = [azurerm_monitor_action_group.uw.id]
  }
}
