// Etap 14 - projekt Microsoft Foundry (nowe doswiadczenie, nie hub classic) do logowania
// ewaluacji sedziego LLM. Konto AIServices bez kluczy (tylko Entra). Sedzia domyslnie
// gpt-5-mini na istniejacym koncie z Bicepa - tu tylko fallback 4o-mini (warunkowo;
// DSZ0 pkt 1: gpt-5-mini z is_reasoning_model=True dziala, wiec fallback niepotrzebny).
resource "azurerm_cognitive_account" "foundry" {
  name                       = var.foundry_konto
  location                   = data.azurerm_resource_group.rg.location
  resource_group_name        = data.azurerm_resource_group.rg.name
  kind                       = "AIServices"
  sku_name                   = "S0"
  project_management_enabled = true
  custom_subdomain_name      = var.foundry_konto
  local_auth_enabled         = false

  identity {
    type = "SystemAssigned"
  }
}

// DSZ0 pkt 8: provider wymaga bloku identity i location takze na projekcie.
resource "azurerm_cognitive_account_project" "ewaluacja" {
  name                 = var.foundry_projekt
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  location             = data.azurerm_resource_group.rg.location
  display_name         = "Underwriter - ewaluacja szkod"

  identity {
    type = "SystemAssigned"
  }
}

data "azurerm_client_config" "biezacy" {}

// principal_id = ten, kto wykonuje apply (data.azurerm_client_config). Apply z SP/CI przypisalby
// role temu SP, nie właścicielowi - wtedy podmienic principal_id na object_id uzytkownika.
resource "azurerm_role_assignment" "wlasciciel_ai_user" {
  scope = azurerm_cognitive_account.foundry.id
  // "Foundry User" (dawniej "Azure AI User") - po GUID, bo Microsoft zmienil nazwe roli i apply 21.10
  // padl na "could not find role". DSZ0 pkt 4: czy wystarcza do zapisu - sprawdzic przebiegiem (403).
  role_definition_id = "/subscriptions/${data.azurerm_client_config.biezacy.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
  principal_id       = data.azurerm_client_config.biezacy.object_id
}

resource "azurerm_cognitive_deployment" "sedzia_4o_mini" {
  count                = var.wdroz_sedziego_4o_mini ? 1 : 0
  name                 = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = "2024-07-18" // DSZ0 pkt 7: dostepny w swedencentral, ale Deprecating - wycofanie wnioskowania 2027-04-14
  }
  sku {
    name     = "GlobalStandard"
    capacity = 50 // tys. TPM; trial ma limit 200 dla 4o-mini
  }
}

data "azurerm_storage_account" "uw" {
  count               = var.polacz_storage ? 1 : 0
  name                = var.storage_konto
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_cognitive_account_connection_entra_id" "storage" {
  count                = var.polacz_storage ? 1 : 0
  name                 = "uw-storage-ewaluacja"
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  category             = "AzureStorageAccount"
  target               = data.azurerm_storage_account.uw[0].primary_blob_endpoint
  metadata = {
    ResourceId = data.azurerm_storage_account.uw[0].id
  }
}

// [Z6]: evaluate z projektem wymaga Storage Blob Data Owner dla uzytkownika i tozsamosci projektu.
resource "azurerm_role_assignment" "storage_wlasciciel" {
  count                = var.polacz_storage ? 1 : 0
  scope                = data.azurerm_storage_account.uw[0].id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = data.azurerm_client_config.biezacy.object_id
}

resource "azurerm_role_assignment" "storage_projekt" {
  count                = var.polacz_storage ? 1 : 0
  scope                = data.azurerm_storage_account.uw[0].id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_cognitive_account_project.ewaluacja.identity[0].principal_id
}
