# Only three knobs shape a deployment: the region, the resource group, and the
# app name (which becomes the URL). Everything else is either derived or a
# credential that must be supplied. Sensible defaults let the app "just work".

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "westeurope"
}

variable "resource_group_name" {
  description = "Resource group to create and deploy into."
  type        = string
  default     = "rg-qr-org-join"
}

variable "app_name" {
  description = <<-EOT
    Globally-unique name for the App Service (becomes <app_name>.azurewebsites.net).
    Leave empty to auto-generate "<app_name_prefix>-<random>" so you never have to
    invent a unique name.
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

variable "app_base_url" {
  description = <<-EOT
    Override only if the app uses a regional hostname or custom domain. Empty
    derives https://<app_name>.azurewebsites.net; it must match the AAD redirect URI.
  EOT
  type        = string
  default     = ""
}

# --- Credentials / inputs that cannot be defaulted -------------------------
variable "tenant_id" {
  description = "Entra (Azure AD) tenant ID used for Easy Auth admin login."
  type        = string
}

variable "operator_ip_cidr" {
  description = <<-EOT
    Public IP/CIDR of the operator running `terraform apply`. The Key Vault denies
    all public traffic except this address so Terraform can seed the secrets; the
    app reads them over the private endpoint.
  EOT
  type        = string
}

variable "github_client_id" {
  description = "GitHub OAuth App client ID (participant identity)."
  type        = string
}

variable "github_client_secret" {
  description = "GitHub OAuth App client secret."
  type        = string
  sensitive   = true
}

variable "github_app_id" {
  description = "GitHub App ID used to mint installation tokens for invitations."
  type        = string
}

variable "github_app_private_key" {
  description = "GitHub App RSA private key (PEM contents)."
  type        = string
  sensitive   = true
}

# --- Optional access grants (assign in the portal otherwise) ---------------
variable "admin_principal_object_ids" {
  description = "Object IDs of users to grant the admin app role."
  type        = list(string)
  default     = []
}

variable "cosmos_data_principal_object_ids" {
  description = "Object IDs of users to grant Cosmos data-plane access (e.g. developers on the VNet)."
  type        = list(string)
  default     = []
}
