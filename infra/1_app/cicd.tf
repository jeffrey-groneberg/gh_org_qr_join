# --- GitHub Actions OIDC app-deploy identity -------------------------------
# A user-assigned managed identity that the *app* workflow assumes via OpenID
# Connect (no stored secret / publish profile). RBAC is the minimal "Website
# Contributor" scoped to just this Web App, so a compromised app pipeline cannot
# touch anything else. The privileged *infra* identity lives in 0_bootstrap.

data "azurerm_subscription" "current" {}

# The infra CI identity is created in 0_bootstrap; read it here so it can be made
# an owner of the Entra admin app (see entra.tf).
data "azurerm_user_assigned_identity" "infra" {
  name                = var.infra_identity_name
  resource_group_name = var.app_resource_group_name
}

resource "azurerm_user_assigned_identity" "github_deploy" {
  name                = "${local.app_name}-gh-deploy"
  resource_group_name = data.azurerm_resource_group.app.name
  location            = data.azurerm_resource_group.app.location
}

# Federated credential: Entra trusts GitHub-issued OIDC tokens, but only when
# the token's subject is exactly this repo running in this environment. GitHub
# derives the subject from the real execution context and signs it; a token from
# any other repo/branch/environment produces a different subject and is rejected.
resource "azurerm_federated_identity_credential" "github_deploy" {
  name                      = "github-${var.github_environment}"
  user_assigned_identity_id = azurerm_user_assigned_identity.github_deploy.id

  audience = ["api://AzureADTokenExchange"]
  issuer   = "https://token.actions.githubusercontent.com"
  subject  = "repo:${var.github_repository}:environment:${var.github_environment}"
}

# Least-privilege RBAC: manage/deploy ONLY this Web App (not the plan, Cosmos,
# the resource group, or anything else). The scope is built from the resource
# group id + app name (rather than referencing the Web App resource) so changing
# this CI/CD wiring never forces a plan/change on the app.
resource "azurerm_role_assignment" "github_deploy" {
  scope                = "${data.azurerm_resource_group.app.id}/providers/Microsoft.Web/sites/${local.app_name}"
  role_definition_name = "Website Contributor"
  principal_id         = azurerm_user_assigned_identity.github_deploy.principal_id
}
