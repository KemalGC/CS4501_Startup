# Account-wide AWS Budgets email notifications. These do NOT stop spending.
# By excluding credits, a $100 promotional balance cannot hide actual usage.
# AWS Budgets normally refreshes billing data only a few times per day;
# these notifications are not real-time and do not guarantee a spending cap.
# Monitoring-only cost budgets and their email notifications are free,
# unlike action-enabled budgets. No automatic budget actions are configured.
resource "aws_budgets_budget" "account_daily_gross_cost" {
  name         = "${local.prefix}-account-daily-gross"
  budget_type  = "COST"
  limit_amount = tostring(var.daily_budget_usd)
  limit_unit   = "USD"
  time_unit    = "DAILY"

  cost_types {
    include_credit = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 25
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }
}
