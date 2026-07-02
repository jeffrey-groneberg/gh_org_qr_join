# --- Key Vault --------------------------------------------------------------
# Holds every app secret. Public traffic is denied except the operator's IP (so
# `terraform apply` can seed the secrets); the app reads them over the private
# endpoint (see networking.tf) using its user-assigned identity.

resource "azurerm_key_vault" "this" {
  name                       = local.key_vault_name
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  tenant_id                  = data.azuread_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
    ip_rules       = [var.operator_ip_cidr]
  }
}

# The app resolves @Microsoft.KeyVault references with this role.
resource "azurerm_role_assignment" "app_kv_secrets_user" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# The operator running Terraform needs to write (seed/rotate) the secrets.
resource "azurerm_role_assignment" "operator_kv_secrets_officer" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azuread_client_config.current.object_id
}

# --- Secrets ----------------------------------------------------------------
# Each waits on the operator role assignment so the data-plane write is authorized.
resource "azurerm_key_vault_secret" "flask_secret" {
  name         = "flask-secret-key"
  value        = random_password.flask_secret.result
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.operator_kv_secrets_officer]
}

resource "azurerm_key_vault_secret" "github_client_secret" {
  name         = "github-client-secret"
  value        = var.github_client_secret
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.operator_kv_secrets_officer]
}

resource "azurerm_key_vault_secret" "github_app_private_key" {
  name         = "github-app-private-key"
  value        = file("${path.module}/${var.github_app_private_key_file}")
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.operator_kv_secrets_officer]
}

resource "azurerm_key_vault_secret" "github_webhook_secret" {
  name         = "github-webhook-secret"
  value        = random_password.webhook_secret.result
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.operator_kv_secrets_officer]
}

resource "azurerm_key_vault_secret" "easy_auth" {
  name         = "easy-auth-client-secret"
  value        = azuread_application_password.admin.value
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.operator_kv_secrets_officer]
}
