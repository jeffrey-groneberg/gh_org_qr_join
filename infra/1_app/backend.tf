terraform {
  # Remote state in Azure Storage (shared by your laptop and GitHub Actions).
  # The Storage Account + container are created once by ./bootstrap.sh. Auth is
  # via Entra ID (AAD) — no storage keys: locally through `az login`, in CI
  # through the GitHub OIDC identity.
  backend "azurerm" {
    resource_group_name  = "rg-qr-org-join-tfstate"
    storage_account_name = "qrorgjointfstate"
    container_name       = "tfstate"
    key                  = "qr-org-join.tfstate"
    use_azuread_auth     = true
  }
}
