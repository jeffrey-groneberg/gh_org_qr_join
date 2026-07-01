# Post-apply guardrail: surface the one case the IaC cannot resolve on its own.
#
# APP_BASE_URL, the GitHub OAuth callback, the QR targets, and the Entra redirect
# URI are all derived from `local.app_url` (built from `app_name`) because the
# Web App and the Entra app reference each other — using the Web App's *computed*
# hostname on both sides would create a dependency cycle.
#
# For a default App Service this constructed URL is exact. If a custom domain or
# Azure's unique-default-hostname feature assigns a different hostname, this check
# warns you (non-blocking) to set `app_base_url` and re-apply so everything lines
# up.
check "app_base_url_matches_hostname" {
  assert {
    condition = (
      var.app_base_url != "" ||
      azurerm_linux_web_app.this.default_hostname == "${local.app_name}.azurewebsites.net"
    )
    error_message = format(
      "App Service was assigned hostname '%s', which differs from the constructed APP_BASE_URL 'https://%s.azurewebsites.net'. Set the 'app_base_url' variable to 'https://%s' and re-apply so the QR codes, GitHub OAuth callback, and Entra redirect URI all match.",
      azurerm_linux_web_app.this.default_hostname,
      local.app_name,
      azurerm_linux_web_app.this.default_hostname,
    )
  }
}
