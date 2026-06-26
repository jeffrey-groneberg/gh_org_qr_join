# --- GitHub Actions OIDC deployment identity -------------------------------
# A user-assigned managed identity that GitHub Actions assumes via OpenID
# Connect (no stored secret / publish profile). Trust is pinned to one repo +
# one environment, and RBAC is the minimal "Website Contributor" scoped to just
# this Web App, so a compromised pipeline cannot touch anything else.

data "azurerm_subscription" "current" {}

resource "azurerm_user_assigned_identity" "github_deploy" {
  name                = "${local.app_name}-gh-deploy"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
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
# the resource group, or anything else in the subscription). The scope is built
# from the resource group id + app name (rather than referencing the Web App
# resource) so changing this CI/CD wiring never forces a plan/change on the app.
resource "azurerm_role_assignment" "github_deploy" {
  scope                = "${azurerm_resource_group.this.id}/providers/Microsoft.Web/sites/${local.app_name}"
  role_definition_name = "Website Contributor"
  principal_id         = azurerm_user_assigned_identity.github_deploy.principal_id
}
