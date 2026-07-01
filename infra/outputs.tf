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
  value       = local.admin_role_value
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

