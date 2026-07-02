# Only three knobs shape a deployment: the region, the resource group, and the
# app name (which becomes the URL). Everything else is either derived or a
# credential that must be supplied. Sensible defaults let the app "just work".

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "northeurope"
}

variable "resource_group_name" {
  description = <<-EOT
    Resource group to create and deploy into. Leave empty to auto-generate
    "rg-<app_name_prefix>-<random>" (recommended) so repeat or parallel
    deployments never collide with an existing group. Follows Azure CAF naming:
    the "rg-" abbreviation + workload name + a unique instance suffix.
  EOT
  type        = string
  default     = ""

  validation {
    condition = var.resource_group_name == "" || (
      can(regex("^[a-zA-Z0-9._()-]{1,90}$", var.resource_group_name)) &&
      !endswith(var.resource_group_name, ".")
    )
    error_message = "resource_group_name must be 1-90 chars (letters, digits, hyphen, underscore, period, parentheses) and cannot end with a period."
  }
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

variable "github_app_private_key_file" {
  description = <<-EOT
    Path (relative to this infra/ directory) to the GitHub App's private-key PEM.
    Drop the downloaded .pem here — it's gitignored. Only read during the full
    apply, so it need not exist during the phase-1 name/secret resolution.
  EOT
  type        = string
  default     = "github-app.pem"
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
