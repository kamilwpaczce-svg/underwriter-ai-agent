output "connection_string" {
  description = "Connection string App Insights - do sekretu Container Apps (az containerapp secret set), nigdy do repo."
  value       = azurerm_application_insights.uw.connection_string
  sensitive   = true
}

output "app_insights_name" {
  description = "Nazwa zasobu Application Insights."
  value       = azurerm_application_insights.uw.name
}

output "foundry_projekt_endpoint" {
  description = "URL projektu Foundry dla azure_ai_project (AZURE_AI_PROJECT_ENDPOINT). Zbudowany z formatu z README azure-ai-evaluation, nie z atrybutu endpoints - po apply porownac z `terraform state show azurerm_cognitive_account_project.ewaluacja` (DSZ0 pkt 8)."
  value       = "https://${var.foundry_konto}.services.ai.azure.com/api/projects/${var.foundry_projekt}"
}
