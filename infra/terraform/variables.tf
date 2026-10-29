variable "resource_group_name" {
  description = "Istniejaca grupa zasobow (infra/main.bicep, Etap 6)."
  type        = string
  default     = "rg-underwriter-demo"
}

variable "log_analytics_workspace_name" {
  description = "Istniejacy workspace Log Analytics (infra/main.bicep: var nazwaLogAnalytics)."
  type        = string
  default     = "uw-demo-logs"
}

variable "email_alertow" {
  description = "Adres e-mail action group na alert awarii. Celowo bez wartosci domyslnej w repo - podaje właściciel przy `terraform apply` (-var albo plik .tfvars poza repo, patrz .gitignore)."
  type        = string
}

variable "foundry_konto" {
  description = "Nazwa nowego konta AIServices (Etap 14); jednoczesnie subdomena *.services.ai.azure.com."
  type        = string
  default     = "uw-demo-ai-xx1"
}

variable "foundry_projekt" {
  description = "Nazwa projektu Foundry na koncie AIServices (Etap 14)."
  type        = string
  default     = "uw-demo-ewaluacja"
}

variable "storage_konto" {
  description = "Istniejace konto Storage z Bicepa (Etap 6) - uzywane tylko przy polacz_storage = true."
  type        = string
  default     = "uwdemostxx1"
}

variable "wdroz_sedziego_4o_mini" {
  description = "Fallback sedziego: wdrozenie gpt-4o-mini na koncie AIServices. Domyslnie false - gpt-5-mini na koncie z Bicepa dziala (DSZ0 pkt 1)."
  type        = bool
  default     = false
}

variable "polacz_storage" {
  description = "Polaczenie Storage dla projektu + role Storage Blob Data Owner (zmiana uprawnien na koncie z Bicepa). Wlaczyc dopiero, gdy pierwszy evaluate z projektem padnie na uploadzie/403 (DSZ0 pkt 3)."
  type        = bool
  default     = false
}
