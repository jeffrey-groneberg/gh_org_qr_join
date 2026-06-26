output "app_resource_group_name" {
  description = "Resource group 1_app deploys into (pass to 1_app via app_resource_group_name)."
  value       = azurerm_resource_group.app.name
}

# --- Remote-state backend values (use to `terraform init` 1_app) -----------
output "state_resource_group_name" {
  description = "Resource group of the Terraform state Storage Account."
  value       = azurerm_resource_group.state.name
}

output "state_storage_account_name" {
  description = "Terraform state Storage Account name."
  value       = azurerm_storage_account.state.name
}

output "state_container_name" {
  description = "Terraform state blob container."
  value       = azurerm_storage_container.state.name
}

# --- Infra CI identity (set in GitHub) -------------------------------------
output "infra_identity_name" {
  description = "Name of the infra CI identity (pass to 1_app via infra_identity_name + infra_identity_resource_group_name)."
  value       = azurerm_user_assigned_identity.infra.name
}

output "infra_identity_client_id" {
  description = "AZURE_INFRA_CLIENT_ID — client ID the infra workflow authenticates with."
  value       = azurerm_user_assigned_identity.infra.client_id
}

output "infra_identity_principal_id" {
  description = "Object (principal) ID of the infra identity — set as an owner of the Entra admin app in 1_app."
  value       = azurerm_user_assigned_identity.infra.principal_id
}

output "infra_identity_subject" {
  description = "OIDC subject the infra identity trusts (repo + infra environment)."
  value       = azurerm_federated_identity_credential.infra.subject
}

output "tenant_id" {
  description = "AZURE_TENANT_ID."
  value       = data.azurerm_subscription.current.tenant_id
}

output "subscription_id" {
  description = "AZURE_SUBSCRIPTION_ID."
  value       = data.azurerm_subscription.current.subscription_id
}
