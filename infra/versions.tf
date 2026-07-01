terraform {
  required_version = ">= 1.5.0"

  # Local state on purpose: this is a single-layer, user-run deployment. A human
  # runs `terraform init && terraform apply` with `az login`; there is no remote
  # backend, no CI identity, and no bootstrap layer. The state file is gitignored.

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.78"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.9"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      # Recover soft-deleted vaults with the same name instead of failing.
      recover_soft_deleted_key_vaults = true
    }
  }
}

provider "azuread" {}
