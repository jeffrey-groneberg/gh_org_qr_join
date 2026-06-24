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

resource "azurerm_linux_web_app" "this" {
  name                = local.app_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_service_plan.this.location
  service_plan_id     = azurerm_service_plan.this.id

  https_only = true

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
    # SQLite on the persistent /home volume so data survives restarts/deploys.
    DATABASE_URL = "sqlite:////home/data/qr_org_join.db"

    GITHUB_CLIENT_ID     = var.github_client_id
    GITHUB_CLIENT_SECRET = var.github_client_secret
    GITHUB_INVITE_TOKEN  = var.github_invite_token

    ENTRA_ADMIN_ROLE = var.admin_app_role_value
    MEMBER_ROLE      = var.member_role

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
