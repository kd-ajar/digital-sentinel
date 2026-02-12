# Glue Data Catalog for Iceberg Tables

resource "aws_glue_catalog_database" "lakehouse" {
  name        = "${var.project_name}_lakehouse"
  description = "Iceberg lakehouse database for WikiGuard"

  catalog_id = data.aws_caller_identity.current.account_id

  tags = {
    Name        = "${var.project_name}_lakehouse"
    Environment = var.environment
  }
}

# Bronze layer Iceberg table
resource "aws_glue_catalog_table" "bronze_events" {
  name          = "bronze_events"
  database_name = aws_glue_catalog_database.lakehouse.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "table_type"           = "ICEBERG"
    "format"               = "iceberg"
    "write.format.default" = "parquet"
    "write.metadata.compression-codec" = "gzip"
  }

  storage_descriptor {
    location      = "s3://${var.s3_bucket_name}/bronze/events/"
    input_format  = "org.apache.iceberg.mr.hive.HiveIcebergInputFormat"
    output_format = "org.apache.iceberg.mr.hive.HiveIcebergOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.iceberg.mr.hive.HiveIcebergSerDe"
    }

    columns {
      name = "event_id"
      type = "string"
      comment = "Unique event identifier"
    }

    columns {
      name = "event_data"
      type = "string"
      comment = "Raw JSON event data"
    }

    columns {
      name = "kafka_topic"
      type = "string"
      comment = "Source Kafka topic"
    }

    columns {
      name = "kafka_partition"
      type = "int"
      comment = "Kafka partition"
    }

    columns {
      name = "kafka_offset"
      type = "bigint"
      comment = "Kafka offset"
    }

    columns {
      name = "ingestion_timestamp"
      type = "timestamp"
      comment = "Event ingestion timestamp"
    }

    columns {
      name = "event_date"
      type = "date"
      comment = "Partition column - event date"
    }
  }

  partition_keys {
    name = "event_date"
    type = "date"
  }
}

data "aws_caller_identity" "current" {}
