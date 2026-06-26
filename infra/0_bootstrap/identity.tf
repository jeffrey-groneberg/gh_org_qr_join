# Privileged GitHub Actions OIDC identity used ONLY by the infra workflow to run
# `terraform apply` against 1_app. It lives here (not in 1_app) so the pipeline's
# identity is never managed by the pipeline it drives — no self-management, and
# a bad app-infra change can't alter or delete its own permissions.

resource "azurerm_user_assigned_identity" "infra" {
  name                = var.infra_identity_name
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
}

resource "azurerm_federated_identity_credential" "infra" {
  name                      = "github-${var.github_infra_environment}"
  user_assigned_identity_id = azurerm_user_assigned_identity.infra.id

  audience = ["api://AzureADTokenExchange"]
  issuer   = "https://token.actions.githubusercontent.com"
  subject  = "repo:${var.github_repository}:environment:${var.github_infra_environment}"
}

# Manage all resources in the application resource group...
resource "azurerm_role_assignment" "infra_contributor" {
  scope                = azurerm_resource_group.app.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.infra.principal_id
}

# ...including the role assignments 1_app manages (Cosmos data-plane, gh-deploy).
resource "azurerm_role_assignment" "infra_rbac_admin" {
  scope                = azurerm_resource_group.app.id
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azurerm_user_assigned_identity.infra.principal_id
}

# Read/write the Terraform state blob.
resource "azurerm_role_assignment" "infra_state" {
  scope                = azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.infra.principal_id
}
