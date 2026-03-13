output "service_url" {
  description = "Public URL of the Purveyor Cloud Run service"
  value       = google_cloud_run_v2_service.main.uri
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name for local proxy access"
  value       = google_sql_database_instance.main.connection_name
  sensitive   = true
}

output "service_account_email" {
  description = "Cloud Run service account email"
  value       = google_service_account.run.email
}

output "skyfi_api_key_secret" {
  description = "Secret Manager secret ID for SKYFI_API_KEY (update this with your key)"
  value       = google_secret_manager_secret.skyfi_api_key.secret_id
}
