# Entra app registration that backs App Service Easy Auth for the admin UI.
# It declares an app role; users holding that role get the `roles` claim, which
# the Flask app reads from the Easy Auth principal to authorize /admin.

data "azuread_client_config" "current" {}

resource "random_uuid" "admin_role" {}

resource "azuread_application" "admin" {
  display_name     = "${local.app_name}-admin"
  owners           = [data.azuread_client_config.current.object_id, data.azurerm_user_assigned_identity.infra.principal_id]
  sign_in_audience = "AzureADMyOrg"

  web {
    redirect_uris = ["${local.app_url}/.auth/login/aad/callback"]

    implicit_grant {
      id_token_issuance_enabled = true
    }
  }

  app_role {
    allowed_member_types = ["User"]
    description          = "Administrators who can manage the joinable organization list."
    display_name         = "Admin"
    enabled              = true
    id                   = random_uuid.admin_role.result
    value                = var.admin_app_role_value
  }

  # Owners are set once (the human operator + the infra CI identity) and then
  # left alone. Without this, the list would be recomputed from whoever runs
  # Terraform (data.azuread_client_config.current), so a CI run would try to
  # drop the human owner — a runner-dependent flip-flop.
  lifecycle {
    ignore_changes = [owners]
  }
}

resource "azuread_service_principal" "admin" {
  client_id = azuread_application.admin.client_id
  owners    = [data.azuread_client_config.current.object_id, data.azurerm_user_assigned_identity.infra.principal_id]

  # See azuread_application.admin: freeze owners so a CI run doesn't recompute
  # (and drop) the human owner.
  lifecycle {
    ignore_changes = [owners]
  }
}

# Client secret used by Easy Auth (surfaced to the app as the well-known setting
# MICROSOFT_PROVIDER_AUTHENTICATION_SECRET).
resource "azuread_application_password" "admin" {
  application_id = azuread_application.admin.id
  display_name   = "easy-auth"
}

# Optional: assign the admin app role to specific users.
resource "azuread_app_role_assignment" "admins" {
  for_each = toset(var.admin_principal_object_ids)

  app_role_id         = random_uuid.admin_role.result
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.admin.object_id
}
