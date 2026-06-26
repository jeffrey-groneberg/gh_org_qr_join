variable "location" {
  description = "Azure region for the bootstrap resources."
  type        = string
  default     = "westeurope"
}

variable "app_resource_group_name" {
  description = "Resource group that holds the application (1_app deploys into it). Created here so the CI identity can be granted RBAC on it before 1_app runs."
  type        = string
  default     = "rg-qr-org-join"
}

variable "state_resource_group_name" {
  description = "Resource group holding the Terraform remote-state Storage Account."
  type        = string
  default     = "rg-qr-org-join-tfstate"
}

variable "state_storage_account_name" {
  description = "Globally-unique name for the Terraform state Storage Account (3-24 lowercase alphanumeric)."
  type        = string
  default     = "qrorgjointfstate"
}

variable "state_container_name" {
  description = "Blob container holding the 1_app state file."
  type        = string
  default     = "tfstate"
}

variable "infra_identity_name" {
  description = "Name of the user-assigned identity the infra workflow assumes via OIDC."
  type        = string
  default     = "qr-org-join-gh-infra"
}

# --- GitHub Actions OIDC ----------------------------------------------------
variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to assume the infra identity via OIDC."
  type        = string
  default     = "jeffrey-groneberg/gh_org_qr_join"

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "github_repository must be in 'owner/name' form."
  }
}

variable "github_infra_environment" {
  description = "GitHub Environment whose deployments may assume the infra identity (pinned in the OIDC subject)."
  type        = string
  default     = "production-infra"
}
