output "database_name" {
  description = "Glue database name"
  value       = aws_glue_catalog_database.lakehouse.name
}

output "bronze_table_name" {
  description = "Bronze Iceberg table name"
  value       = aws_glue_catalog_table.bronze_events.name
}
