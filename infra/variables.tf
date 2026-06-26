variable "app_name" {
  description = <<-EOT
    Globally-unique name for the App Service (becomes <app_name>.azurewebsites.net).
    Leave empty to auto-generate "<app_name_prefix>-<random>" — recommended, so you
    never have to invent a unique name.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.app_name == "" || can(regex("^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$", var.app_name))
    error_message = "app_name must be 2-60 chars, lowercase alphanumeric or hyphens, not starting/ending with a hyphen."
  }
}

variable "app_name_prefix" {
  description = "Prefix for the auto-generated app name when app_name is left empty."
  type        = string
  default     = "qr-org-join"
}

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "westeurope"
}

variable "cosmos_location" {
  description = "Region for the Cosmos DB account. Empty uses var.location; override if that region is capacity-constrained for Cosmos."
  type        = string
  default     = ""
}

variable "resource_group_name" {
  description = "Name of the resource group to create."
  type        = string
  default     = "rg-qr-org-join"
}

variable "sku_name" {
  description = "App Service Plan SKU. B1 is the smallest tier that supports Always On."
  type        = string
  default     = "B1"
}

variable "python_version" {
  description = "Python runtime version for the Linux web app."
  type        = string
  default     = "3.12"
}

variable "log_retention_in_days" {
  description = "Log Analytics workspace retention for Application Insights data."
  type        = number
  default     = 30
}

variable "app_base_url" {
  description = <<-EOT
    Public HTTPS base URL of the app (no trailing slash). Leave empty to derive
    https://<app_name>.azurewebsites.net. Override if your app uses a regional
    hostname or a custom domain — it must match the AAD redirect URI.
  EOT
  type        = string
  default     = ""
}

# --- Admin authorization (Entra app role via Easy Auth) --------------------
variable "tenant_id" {
  description = "Entra (Azure AD) tenant ID used for Easy Auth."
  type        = string
}

variable "admin_app_role_value" {
  description = "Value of the Entra app role that grants admin access (matches ENTRA_ADMIN_ROLE)."
  type        = string
  default     = "admin"
}

variable "admin_principal_object_ids" {
  description = "Object IDs of users to assign the admin app role to (optional; assign in the portal otherwise)."
  type        = list(string)
  default     = []
}

variable "cosmos_data_principal_object_ids" {
  description = "Object IDs of users to grant Cosmos data-plane access (e.g. developers running locally with az login)."
  type        = list(string)
  default     = []
}

# --- GitHub credentials (provided to the app as secret app settings) -------
variable "github_client_id" {
  description = "GitHub OAuth App client ID (participant identity)."
  type        = string
}

variable "github_client_secret" {
  description = "GitHub OAuth App client secret."
  type        = string
  sensitive   = true
}

variable "github_invite_token" {
  description = "GitHub classic PAT with admin:org scope, used to create invitations for all orgs."
  type        = string
  sensitive   = true
}
