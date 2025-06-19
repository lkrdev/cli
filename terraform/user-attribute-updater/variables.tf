variable "project_id" {
  description = "The Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "The Google Cloud region for deployments."
  type        = string
  default     = "us-central1"
}

variable "cloud_run_service_name" {
  description = "The name of the Cloud Run service."
  type        = string
  default     = "lkr-access-token-updater"
}

variable "cloud_run_image" {
  description = "The Docker image for the Cloud Run service."
  type        = string
  default     = "us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest"
}

variable "cloud_run_service_account_email" {
  description = "The email of the service account for the Cloud Run service."
  type        = string
}

variable "scheduler_job_name" {
  description = "The name of the Cloud Scheduler job."
  type        = string
  default     = "lkr-token-updater-scheduler"
}

variable "scheduler_service_account_email" {
  description = "The email of the service account for the Cloud Scheduler job to use for OIDC auth."
  type        = string
}

variable "lookersdk_client_id" {
  description = "Looker SDK Client ID."
  type        = string
  sensitive   = true
}

variable "lookersdk_client_secret" {
  description = "Looker SDK Client Secret."
  type        = string
  sensitive   = true
}

variable "lookersdk_base_url" {
  description = "Looker SDK Base URL (e.g., https://your.looker.instance.com)."
  type        = string
}

variable "looker_whitelisted_urls" {
  description = "Comma-separated list of Looker whitelisted URLs for the user attribute updater. Defaults to lookersdk_base_url."
  type        = string
  default     = ""
}

variable "scheduler_cron_schedule" {
  description = "The cron schedule for the scheduler job (e.g., '0 * * * *')."
  type        = string
  default     = "0 * * * *"
}

variable "scheduler_message_body_user_attribute" {
  description = "The user attribute name to be updated by the scheduler."
  type        = string
  default     = "cloud_run_access_token"
}

variable "scheduler_message_body_update_type" {
  description = "The update type for the user attribute (e.g., 'default')."
  type        = string
  default     = "default"
}

variable "scheduler_time_zone" {
  description = "The time zone for the scheduler job."
  type        = string
  default     = "Etc/UTC"
}

variable "cloud_run_cpu" {
  description = "The CPU limit for the Cloud Run service."
  type        = number
  default     = 1
}

variable "cloud_run_memory" {
  description = "The memory limit for the Cloud Run service (e.g., '2Gi')."
  type        = string
  default     = "2Gi"
}
