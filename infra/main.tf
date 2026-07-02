locals {
  # Use the provided name, or auto-generate "<prefix>-<random>" for global
  # uniqueness so the operator never has to invent one.
  app_name = var.app_name != "" ? var.app_name : "${var.app_name_prefix}-${random_string.suffix.result}"

  # Default to the standard azurewebsites.net hostname; override via app_base_url
  # for regional hostnames or custom domains.
  app_url = var.app_base_url != "" ? var.app_base_url : "https://${local.app_name}.azurewebsites.net"

  # Key Vault names are globally unique, <=24 chars, alphanumeric + hyphens.
  key_vault_name = substr(replace("${local.app_name}-kv", "--", "-"), 0, 24)

  # Value of the Entra app role that grants admin access (matches ENTRA_ADMIN_ROLE).
  admin_role_value = "admin"
}

# Random suffix used only when app_name is left empty. 6 lowercase-alphanumeric
# characters make a global hostname collision astronomically unlikely.
resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
}

# User-assigned identity for the web app. Used for BOTH passwordless Cosmos
# access AND Key Vault reference resolution. Creating it up-front (rather than a
# system-assigned identity) lets us grant it RBAC before the Web App reads any
# Key Vault reference, avoiding the "identity not yet authorized" startup race.
resource "azurerm_user_assigned_identity" "app" {
  name                = "${local.app_name}-app"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
}

resource "azurerm_service_plan" "this" {
  name                = "${local.app_name}-plan"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  os_type             = "Linux"
  # S1 (Standard) is the smallest SKU that supports regional VNet integration.
  sku_name = "S1"
}

# Workspace-based Application Insights (the modern, required topology).
resource "azurerm_log_analytics_workspace" "this" {
  name                = "${local.app_name}-logs"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
}

resource "azurerm_application_insights" "this" {
  name                = "${local.app_name}-ai"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
}

# --- Cosmos DB for NoSQL (serverless, key auth disabled, PRIVATE) ----------
# Orgs are stored here and accessed passwordlessly via managed identity + RBAC.
# Public network access is disabled; the app reaches Cosmos over a private
# endpoint (see networking.tf). Database/container creation uses the ARM control
# plane, so `terraform apply` still works from a public runner/laptop.
resource "azurerm_cosmosdb_account" "this" {
  name                = "${local.app_name}-cosmos"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  offer_type          = "Standard"

  # Force Entra ID (AAD) auth only — no account keys are issued or used.
  local_authentication_enabled = false

  # No public endpoint; access is exclusively via the private endpoint.
  public_network_access_enabled = false

  capabilities {
    name = "EnableServerless"
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = var.location
    failover_priority = 0
  }
}

resource "azurerm_cosmosdb_sql_database" "this" {
  name                = "qrorgjoin"
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
}

resource "azurerm_cosmosdb_sql_container" "orgs" {
  name                  = "orgs"
  resource_group_name   = azurerm_resource_group.this.name
  account_name          = azurerm_cosmosdb_account.this.name
  database_name         = azurerm_cosmosdb_sql_database.this.name
  partition_key_paths   = ["/id"]
  partition_key_version = 2
}

# Grant the web app's identity data-plane access (Built-in Data Contributor:
# read + write items). The role's well-known GUID is
# 00000000-0000-0000-0000-000000000002.
resource "azurerm_cosmosdb_sql_role_assignment" "app" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  role_definition_id  = "${azurerm_cosmosdb_account.this.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.app.principal_id
  scope               = azurerm_cosmosdb_account.this.id
}

# Optional: grant a user direct Cosmos data-plane access (e.g. break-glass
# debugging via the portal/VNet; requires network access to the private endpoint).
resource "azurerm_cosmosdb_sql_role_assignment" "devs" {
  for_each = toset(var.cosmos_data_principal_object_ids)

  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  role_definition_id  = "${azurerm_cosmosdb_account.this.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = each.value
  scope               = azurerm_cosmosdb_account.this.id
}

resource "azurerm_linux_web_app" "this" {
  name                = local.app_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_service_plan.this.location
  service_plan_id     = azurerm_service_plan.this.id

  https_only = true

  # Regional VNet integration: all outbound traffic (Cosmos + Key Vault private
  # endpoints, GitHub API, App Insights) is routed through the VNet so private
  # DNS resolves and the private endpoints are reachable. Inbound stays public
  # (participants scan the QR; GitHub POSTs the webhook).
  virtual_network_subnet_id = azurerm_subnet.app.id

  # User-assigned identity for Cosmos + Key Vault references.
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  # Resolve @Microsoft.KeyVault(...) app-setting references using the app's UAMI
  # (which already holds "Key Vault Secrets User"), not a system identity.
  key_vault_reference_identity_id = azurerm_user_assigned_identity.app.id

  site_config {
    always_on = true

    # Send ALL outbound through the VNet integration (needed so private DNS +
    # private endpoints are used for Cosmos and Key Vault).
    vnet_route_all_enabled = true

    # No custom app_command_line: Oryx compresses the build (output.tar.zst) and
    # its generated startup script extracts it to /tmp and runs `gunicorn app:app`
    # from there. A custom command would run in /home/site/wwwroot (where app.py
    # isn't present after extraction) and fail with "No module named 'app'".
    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    # Build the app with Oryx during zip/Git deploy.
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"

    # --- Application configuration -----------------------------------------
    # Secrets are Key Vault references, resolved by the app's UAMI over the
    # vault's private endpoint. Non-secret values are inline.
    FLASK_SECRET_KEY = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.flask_secret.versionless_id})"
    APP_BASE_URL     = local.app_url

    # Cosmos DB (orgs store) — accessed via managed identity, no keys.
    COSMOS_ENDPOINT  = azurerm_cosmosdb_account.this.endpoint
    COSMOS_DATABASE  = azurerm_cosmosdb_sql_database.this.name
    COSMOS_CONTAINER = azurerm_cosmosdb_sql_container.orgs.name

    # Tell DefaultAzureCredential which identity to use at runtime. The app has
    # only a user-assigned identity, so without this the managed-identity probe
    # would target a (non-existent) system-assigned identity and fail.
    AZURE_CLIENT_ID = azurerm_user_assigned_identity.app.client_id

    GITHUB_CLIENT_ID     = var.github_client_id
    GITHUB_CLIENT_SECRET = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.github_client_secret.versionless_id})"

    # GitHub App (least-privilege per-org invites).
    GITHUB_APP_ID          = var.github_app_id
    GITHUB_APP_PRIVATE_KEY = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.github_app_private_key.versionless_id})"
    GITHUB_WEBHOOK_SECRET  = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.github_webhook_secret.versionless_id})"

    ENTRA_ADMIN_ROLE = local.admin_role_value

    # Application Insights (Azure Monitor OpenTelemetry reads this automatically).
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.this.connection_string

    # Consumed by Easy Auth's active_directory_v2 provider below.
    MICROSOFT_PROVIDER_AUTHENTICATION_SECRET = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.easy_auth.versionless_id})"
  }

  # App Service Easy Auth (AuthV2). Unauthenticated requests are allowed so
  # participants pass through; the app redirects /admin to the login endpoint.
  auth_settings_v2 {
    auth_enabled           = true
    require_authentication = false
    unauthenticated_action = "AllowAnonymous"
    default_provider       = "azureactivedirectory"

    active_directory_v2 {
      client_id                  = azuread_application.admin.client_id
      tenant_auth_endpoint       = "https://login.microsoftonline.com/${data.azuread_client_config.current.tenant_id}/v2.0/"
      client_secret_setting_name = "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET"
    }

    login {}
  }

  # The UAMI must hold "Key Vault Secrets User" before the app resolves any
  # @Microsoft.KeyVault reference; ensure the role assignment exists first.
  depends_on = [azurerm_role_assignment.app_kv_secrets_user]
}

resource "random_password" "flask_secret" {
  length  = 64
  special = false
}

# Webhook secret shared with the GitHub App. Generated here (so it's never a
# manual input) and exposed via the `github_webhook_secret` output — paste that
# value into the GitHub App's webhook config. The app reads it from Key Vault.
resource "random_password" "webhook_secret" {
  length  = 40
  special = false
}
