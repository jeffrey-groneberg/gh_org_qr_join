output "app_name" {
  description = "Resolved App Service name (auto-generated when app_name is left empty)."
  value       = local.app_name
}

output "resource_group_name" {
  description = "Resource group the app is deployed into."
  value       = azurerm_resource_group.this.name
}

output "app_url" {
  description = "Public URL of the deployed app."
  value       = local.app_url
}

output "github_oauth_homepage_url" {
  description = "Set this as the GitHub OAuth App 'Homepage URL'."
  value       = local.app_url
}

output "default_hostname" {
  description = "Default hostname assigned by App Service (use to set app_base_url if it differs from app_url)."
  value       = azurerm_linux_web_app.this.default_hostname
}

output "github_oauth_callback_url" {
  description = "Set this as the GitHub OAuth App 'Authorization callback URL'."
  value       = "${local.app_url}/callback"
}

output "easy_auth_redirect_uri" {
  description = "Entra app redirect URI configured for Easy Auth."
  value       = "${local.app_url}/.auth/login/aad/callback"
}

output "admin_app_client_id" {
  description = "Client ID of the Entra app registration backing the admin login."
  value       = azuread_application.admin.client_id
}

output "admin_app_role_value" {
  description = "App role value that grants admin access (assign users to it)."
  value       = var.admin_app_role_value
}

output "application_insights_name" {
  description = "Application Insights component collecting logs and traces."
  value       = azurerm_application_insights.this.name
}

output "cosmosdb_account_name" {
  description = "Cosmos DB account storing the org list."
  value       = azurerm_cosmosdb_account.this.name
}

output "cosmosdb_endpoint" {
  description = "Cosmos DB endpoint (set as COSMOS_ENDPOINT for local dev)."
  value       = azurerm_cosmosdb_account.this.endpoint
}

# --- GitHub Actions OIDC deployment (set these in the GitHub repo) ----------
# These three are NOT secrets — store them as GitHub repository/environment
# *variables* (AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID) and pass
# them to azure/login@v2. No client secret or publish profile is ever needed.
output "github_deploy_client_id" {
  description = "AZURE_CLIENT_ID — client ID of the user-assigned identity GitHub Actions assumes via OIDC."
  value       = azurerm_user_assigned_identity.github_deploy.client_id
}

output "github_deploy_tenant_id" {
  description = "AZURE_TENANT_ID — tenant the deploy identity lives in."
  value       = data.azurerm_subscription.current.tenant_id
}

output "github_deploy_subscription_id" {
  description = "AZURE_SUBSCRIPTION_ID — subscription the Web App is deployed into."
  value       = data.azurerm_subscription.current.subscription_id
}

output "github_deploy_subject" {
  description = "OIDC subject this identity trusts (must match the workflow's repo + environment)."
  value       = azurerm_federated_identity_credential.github_deploy.subject
}

output "github_infra_client_id" {
  description = "AZURE_INFRA_CLIENT_ID — client ID of the privileged identity the infra workflow assumes via OIDC."
  value       = azurerm_user_assigned_identity.github_infra.client_id
}

output "github_infra_subject" {
  description = "OIDC subject the infra identity trusts (repo + infra environment)."
  value       = azurerm_federated_identity_credential.github_infra.subject
}
