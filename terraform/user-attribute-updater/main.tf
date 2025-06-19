terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.50.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_cloud_run_v2_service" "user_attribute_updater" {
  name     = var.cloud_run_service_name
  location = var.region

  template {
    service_account = var.cloud_run_service_account_email
    containers {
      image = var.cloud_run_image
      args  = ["tools", "user-attribute-updater"]
      env {
        name  = "LOOKERSDK_CLIENT_ID"
        value = var.lookersdk_client_id
      }
      env {
        name  = "LOOKERSDK_CLIENT_SECRET"
        value = var.lookersdk_client_secret
      }
      env {
        name  = "LOOKERSDK_BASE_URL"
        value = var.lookersdk_base_url
      }
      env {
        name  = "LOOKER_WHITELISTED_BASE_URLS"
        value = var.looker_whitelisted_urls == "" ? var.lookersdk_base_url : var.looker_whitelisted_urls
      }
      resources {
        limits = {
          cpu    = var.cloud_run_cpu
          memory = var.cloud_run_memory
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

resource "google_cloud_scheduler_job" "token_updater_scheduler" {
  name        = var.scheduler_job_name
  description = "Periodically update Looker user attribute with OIDC token."
  schedule    = var.scheduler_cron_schedule
  time_zone   = var.scheduler_time_zone
  attempt_deadline = "320s" # Corresponds to max-retry-attempts 5 with default backoff

  http_target {
    uri = "${google_cloud_run_v2_service.user_attribute_updater.uri}/identity_token"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode(jsonencode({
      user_attribute = var.scheduler_message_body_user_attribute
      update_type    = var.scheduler_message_body_update_type
    }))

    oidc_token {
      service_account_email = var.scheduler_service_account_email
      audience              = google_cloud_run_v2_service.user_attribute_updater.uri
    }
  }

  retry_config {
    retry_count = 5
  }
}

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  project  = google_cloud_run_v2_service.user_attribute_updater.project
  location = google_cloud_run_v2_service.user_attribute_updater.location
  name     = google_cloud_run_v2_service.user_attribute_updater.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.scheduler_service_account_email}"
}
