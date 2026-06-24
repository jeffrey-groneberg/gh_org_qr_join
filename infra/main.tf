locals {
  # Use the provided name, or auto-generate "<prefix>-<random>" for global
  # uniqueness so the operator never has to invent one.
  app_name = var.app_name != "" ? var.app_name : "${var.app_name_prefix}-${random_string.suffix.result}"

  # Default to the standard azurewebsites.net hostname; override via app_base_url
  # for regional hostnames or custom domains.
  app_url = var.app_base_url != "" ? var.app_base_url : "https://${local.app_name}.azurewebsites.net"
}

# Random suffix used only when app_name is left empty. 6 lowercase-alphanumeric
# characters make a global hostname collision astronomically unlikely.
resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
}

resource "azurerm_service_plan" "this" {
  name                = "${local.app_name}-plan"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  os_type             = "Linux"
  sku_name            = var.sku_name
}

# Workspace-based Application Insights (the modern, required topology).
resource "azurerm_log_analytics_workspace" "this" {
  name                = "${local.app_name}-logs"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_in_days
}

resource "azurerm_application_insights" "this" {
  name                = "${local.app_name}-ai"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
}

# --- Cosmos DB for NoSQL (serverless, key auth disabled) -------------------
# Orgs are stored here and accessed passwordlessly via managed identity + RBAC.
resource "azurerm_cosmosdb_account" "this" {
  name                = "${local.app_name}-cosmos"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  # Force Entra ID (AAD) auth only — no account keys are issued or used.
  local_authentication_enabled = false

  capabilities {
    name = "EnableServerless"
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.this.location
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

# Grant the web app's managed identity data-plane access (Built-in Data
# Contributor: read + write items). The role's well-known GUID is
# 00000000-0000-0000-0000-000000000002.
resource "azurerm_cosmosdb_sql_role_assignment" "app" {
  resource_group_name = azurerm_resource_group.this.name
  account_name        = azurerm_cosmosdb_account.this.name
  role_definition_id  = "${azurerm_cosmosdb_account.this.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_linux_web_app.this.identity[0].principal_id
  scope               = azurerm_cosmosdb_account.this.id
}

# Optional: grant developers the same data role so they can run the app locally
# against this account with `az login` (DefaultAzureCredential).
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

  # System-assigned managed identity used for passwordless Cosmos DB access.
  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on        = true
    app_command_line = "gunicorn --bind=0.0.0.0 --workers=2 app:app"

    application_stack {
      python_version = var.python_version
    }
  }

  app_settings = {
    # Build the app with Oryx during zip/Git deploy.
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"

    # --- Application configuration (see .env.example) -----------------------
    FLASK_SECRET_KEY = random_password.flask_secret.result
    APP_BASE_URL     = local.app_url

    # Cosmos DB (orgs store) — accessed via managed identity, no keys.
    COSMOS_ENDPOINT  = azurerm_cosmosdb_account.this.endpoint
    COSMOS_DATABASE  = azurerm_cosmosdb_sql_database.this.name
    COSMOS_CONTAINER = azurerm_cosmosdb_sql_container.orgs.name

    GITHUB_CLIENT_ID     = var.github_client_id
    GITHUB_CLIENT_SECRET = var.github_client_secret
    GITHUB_INVITE_TOKEN  = var.github_invite_token

    ENTRA_ADMIN_ROLE = var.admin_app_role_value
    MEMBER_ROLE      = var.member_role

    # Application Insights (Azure Monitor OpenTelemetry reads this automatically).
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.this.connection_string

    # Consumed by Easy Auth's active_directory_v2 provider below.
    MICROSOFT_PROVIDER_AUTHENTICATION_SECRET = azuread_application_password.admin.value
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
      tenant_auth_endpoint       = "https://login.microsoftonline.com/${var.tenant_id}/v2.0/"
      client_secret_setting_name = "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET"
    }

    login {}
  }
}

resource "random_password" "flask_secret" {
  length  = 64
  special = false
}
