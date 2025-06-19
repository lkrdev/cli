output "cloud_run_service_url" {
  description = "The URL of the deployed User Attribute Updater Cloud Run service."
  value       = google_cloud_run_v2_service.user_attribute_updater.uri
}

output "scheduler_job_name" {
  description = "The name of the Cloud Scheduler job."
  value       = google_cloud_scheduler_job.token_updater_scheduler.name
}

output "cloud_run_service_name" {
  description = "The name of the Cloud Run service."
  value       = google_cloud_run_v2_service.user_attribute_updater.name
}
