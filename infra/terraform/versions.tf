// Etap 13 - nowe zasoby (App Insights, action group, alert) przez Terraform;
// zasoby istniejace (Bicep, Etap 6) zostaja tam bez migracji stanu (decyzja hybrydowa,
// patrz (wewnętrzny plan etapów, poza repo)
//
// Backend: kontener "tfstate" w istniejacym koncie Storage (Bicep, Etap 6), dostep
// przez Entra ID (use_azuread_auth), bez klucza dostepu w repo. Pozostale parametry
// backendu (resource_group_name, storage_account_name, container_name, key) podaje
// Właściciel przy `terraform init -backend-config=...` - patrz infra/terraform/README.md.
terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.10"
    }
  }

  backend "azurerm" {
    use_azuread_auth = true
  }
}

provider "azurerm" {
  features {}
}
