resource "aws_cognito_user_pool" "users" {
  name                     = "${local.prefix}-users"
  auto_verified_attributes = ["email"]
  username_attributes      = ["email"]
  # Google federation is available in Lite. The classic hosted UI avoids
  # enabling paid Essentials managed-login functionality by accident.
  user_pool_tier = "LITE"

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  user_pool_add_ons {
    advanced_security_mode = "OFF"
  }
}

resource "aws_cognito_identity_provider" "google" {
  user_pool_id  = aws_cognito_user_pool.users.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id        = var.google_oauth_client_id
    client_secret    = var.google_oauth_client_secret
    authorize_scopes = "openid email profile"
  }

  attribute_mapping = {
    email          = "email"
    email_verified = "email_verified"
    name           = "name"
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.prefix}-vercel-web"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret                      = false
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = [aws_cognito_identity_provider.google.provider_name]
  callback_urls                        = var.cognito_callback_urls
  logout_urls                          = var.cognito_logout_urls
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 7

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

# Must match the Authorized Redirect URI in Google Cloud OAuth client:
# https://<domain>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
resource "aws_cognito_user_pool_domain" "login" {
  domain                = "${local.prefix}-${data.aws_caller_identity.current.account_id}"
  user_pool_id          = aws_cognito_user_pool.users.id
  managed_login_version = 1
}
