# 0_bootstrap — the day-0 layer.
#
# Creates everything that must exist BEFORE the application layer (1_app) can
# run in CI: the application resource group, the Terraform remote-state Storage
# Account, and the privileged GitHub Actions OIDC identity (in identity.tf).
# Run once by a human (`az login` + apply); thereafter 1_app runs in CI.

data "azurerm_subscription" "current" {}

# Application resource group (1_app populates it via a data source). Created here
# so the infra CI identity can be granted RBAC scoped to it before 1_app exists.
resource "azurerm_resource_group" "app" {
  name     = var.app_resource_group_name
  location = var.location
}

# --- Terraform remote state backend (consumed by 1_app) --------------------
resource "azurerm_resource_group" "state" {
  name     = var.state_resource_group_name
  location = var.location
}

resource "azurerm_storage_account" "state" {
  name                     = var.state_storage_account_name
  resource_group_name      = azurerm_resource_group.state.name
  location                 = azurerm_resource_group.state.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false # Entra ID (AAD) auth only — no account keys

  blob_properties {
    versioning_enabled = true
  }
}

resource "azurerm_storage_container" "state" {
  name                  = var.state_container_name
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}
