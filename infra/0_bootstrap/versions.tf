terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.78"
    }
  }

  # Local state on purpose: this is the day-0 layer that creates the remote
  # backend (and the CI identity) used by 1_app. It can't store its own state
  # remotely without a chicken-and-egg, and it's run rarely by a human. The
  # state file is gitignored; everything here is deterministically importable.
}

provider "azurerm" {
  features {}

  # The state Storage Account disables shared-key auth, so use Entra ID (AAD)
  # for data-plane reads (queue/blob properties) instead of account keys.
  storage_use_azuread = true
}
