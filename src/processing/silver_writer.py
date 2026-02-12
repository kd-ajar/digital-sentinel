"""
Silver Layer Writer - Spark Structured Streaming
Reads from passed records bronze_events and writes to silver_events or quarantine as apache iceberg table  
With SQL or PyDeequ-based Quality Gate  skip_pydeequ=True  # Use SQL-based flags only for speed
"""
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, from_json, to_date, 
    lit, length, when,
    unix_timestamp, from_unixtime, hour, 
    abs as abs_col, coalesce
)
from pyspark.sql.types import (
    StructType, StructField, StringType, LongType, 
    IntegerType, BooleanType
)
import sys
import os
import logging

# Data Quality imports - new clean architecture
try:
    from data_quality import SilverQualityGate, AlertManager, create_quality_metrics_table
    QUALITY_MODULE_AVAILABLE = True
except ImportError:
    QUALITY_MODULE_AVAILABLE = False
    logging.warning("Data quality module not available - running without DQ checks")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_spark_session():
    """Get existing Spark session (created by spark-submit)"""
    spark = SparkSession.builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    logger.info(f"Spark session acquired: {spark.version}")
    return spark


def read_from_bronze(spark, glue_database):
    """Read streaming data from Bronze Iceberg table in S3"""
    logger.info(f"Reading from Bronze Iceberg table: {glue_database}.bronze_events")
    
    df = spark.readStream \
        .format("iceberg") \
        .table(f"glue_catalog.`{glue_database}`.bronze_events") \
        .withWatermark("ingestion_timestamp", "1 hour")  # Watermark for deduplication
    
    logger.info("Bronze stream initiated")
    return df


def parse_event_data(df):
    """Parse event_data JSON string to extract fields for validation"""
    logger.info("Parsing event data JSON")
    
    # Define schema for actual Wikimedia event_data JSON
    event_schema = StructType([
        StructField("id", LongType(), True),
        StructField("type", StringType(), True),
        StructField("namespace", IntegerType(), True),
        StructField("title", StringType(), True),
        StructField("title_url", StringType(), True),
        StructField("comment", StringType(), True),
        StructField("timestamp", LongType(), True),
        StructField("user", StringType(), True),
        StructField("bot", BooleanType(), True),
        StructField("minor", BooleanType(), True),
        StructField("wiki", StringType(), True),
        StructField("server_url", StringType(), True),
        StructField("notify_url", StringType(), True),
        StructField("length", StructType([
            StructField("old", IntegerType(), True),
            StructField("new", IntegerType(), True)
        ]), True),
        StructField("revision", StructType([
            StructField("old", LongType(), True),
            StructField("new", LongType(), True)
        ]), True),
        StructField("meta", StructType([
            StructField("uri", StringType(), True),
            StructField("id", StringType(), True),
            StructField("dt", StringType(), True),
            StructField("domain", StringType(), True)
        ]), True),
        StructField("_metadata", StructType([
            StructField("ingestion_timestamp", StringType(), True),
            StructField("canonical_entity", StringType(), True)
        ]), True)
    ])
    
    # Parse JSON and extract fields
    parsed_df = df.withColumn(
        "parsed_event",
        from_json(col("event_data"), event_schema)
    ).select(
        col("*"),
        # Core event fields
        col("parsed_event.id").alias("wikimedia_id"),
        col("parsed_event.type").alias("event_type"),
        col("parsed_event.namespace").alias("namespace"),
        col("parsed_event.title").alias("title"),
        col("parsed_event.title_url").alias("title_url"),
        col("parsed_event.comment").alias("comment"),
        col("parsed_event.timestamp").alias("event_timestamp"),
        col("parsed_event.user").alias("user_name"),
        col("parsed_event.bot").alias("is_bot"),
        col("parsed_event.minor").alias("is_minor"),
        col("parsed_event.wiki").alias("wiki"),
        col("parsed_event.server_url").alias("server_url"),
        col("parsed_event.notify_url").alias("notify_url"),
        # Nested fields
        col("parsed_event.length.old").alias("length_old"),
        col("parsed_event.length.new").alias("length_new"),
        col("parsed_event.revision.old").alias("revision_old"),
        col("parsed_event.revision.new").alias("revision_new"),
        col("parsed_event.meta.id").alias("meta_id"),
        col("parsed_event.meta.dt").alias("meta_dt"),
        col("parsed_event.meta.domain").alias("meta_domain"),
        col("parsed_event._metadata.canonical_entity").alias("canonical_entity")
    ).withColumn(
        # Derived columns for risk metrics (used by Gold layer)
        "bytes_changed", 
        coalesce(col("length_new"), lit(0)) - coalesce(col("length_old"), lit(0))
    ).withColumn(
        "is_revert", 
        col("bytes_changed") < 0
    ).withColumn(
        "is_anonymous", 
        col("user_name").rlike(r'^(\d{1,3}\.){3}\d{1,3}$|^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$')
    ).withColumn(
        "event_hour", 
        hour(from_unixtime(col("event_timestamp")))
    ).withColumn(
        "processing_lag_seconds",
        unix_timestamp(col("ingestion_timestamp")) - col("event_timestamp")
    ).withColumn(
        "has_comment", 
        coalesce(length(col("comment")), lit(0)) > 0
    ).withColumn(
        # Large edit flag (>10KB) - useful for gold anomaly detection
        "is_large_edit",
        abs_col(coalesce(col("length_new"), lit(0)) - coalesce(col("length_old"), lit(0))) > 10240
    ).withColumn(
        # Bot consistency check - useful for gold user analysis
        "is_bot_consistent",
        when(
            col("is_bot") == True,
            col("user_name").rlike("(?i)bot")
        ).when(
            (col("is_bot") == False) | col("is_bot").isNull(),
            ~col("user_name").rlike("(?i)bot")
        ).otherwise(lit(False))
    ).withColumn(
        # Allowlist flag - entity was matched during ingestion
        "is_allowlisted",
        col("canonical_entity").isNotNull()
    ).withColumn(
        # Partitioning column
        "event_date",
        to_date(col("ingestion_timestamp"))
    )
    
    logger.info("Event data parsed with derived metrics")
    return parsed_df


def deduplicate_events(df):
    """Deduplicate events based on meta.id (handles replays)
    
    Uses dropDuplicates with watermark for streaming-compatible deduplication.
    The watermark is set on ingestion_timestamp in read_from_bronze().
    """
    logger.info("Deduplicating events (removing replays)")
    
    # Use dropDuplicates for streaming deduplication
    # This will keep the first occurrence of each meta_id within the watermark window
    # Watermark is already set in read_from_bronze() on ingestion_timestamp
    deduplicated_df = df.dropDuplicates(["meta_id"])
    
    logger.info("Deduplication complete")
    return deduplicated_df


def transform_to_silver_schema(df):
    """Transform parsed data to Silver schema - only clean data, no quality flags
    
    Note: Quality validation is handled by SilverQualityGate in the batch processor.
    Silver table contains only passed records with derived metrics for Gold layer.
    """
    logger.info("Applying Silver schema transformation")
    
    # Select columns for silver table (quality flags handled by SilverQualityGate)
    silver_df = df.select(
        # Core identifiers
        col("event_id"),
        col("event_data"),
        col("wikimedia_id"),
        col("meta_id"),
        
        # Core event fields
        col("event_type"),
        col("namespace"),
        col("title"),
        col("title_url"),
        col("comment"),
        col("event_timestamp"),
        col("user_name"),
        col("is_bot"),
        col("is_minor"),
        col("wiki"),
        col("server_url"),
        col("notify_url"),
        col("canonical_entity"),
        
        # Length and revision data
        col("length_old"),
        col("length_new"),
        col("revision_old"),
        col("revision_new"),
        
        # Kafka metadata (lineage)
        col("kafka_topic"),
        col("kafka_partition"),
        col("kafka_offset"),
        col("ingestion_timestamp"),
        
        # Derived metrics for Gold layer aggregations
        col("bytes_changed"),
        col("is_revert"),
        col("is_anonymous"),
        col("event_hour"),
        col("processing_lag_seconds"),
        col("has_comment"),
        col("is_large_edit"),
        col("is_bot_consistent"),
        col("is_allowlisted"),
        
        # Partitioning
        col("event_date")
    )
    
    logger.info("Silver schema applied")
    return silver_df


def create_silver_batch_processor(spark, table_name, glue_database, s3_bucket, alert_manager=None):
    """Create a batch processor with quality gate that filters failed records"""
    
    quality_gate = SilverQualityGate(
        spark=spark,
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        alert_manager=alert_manager
    ) if QUALITY_MODULE_AVAILABLE else None
    
    # Define columns for silver table (clean data + derived metrics for Gold)
    silver_columns = [
        "event_id", "event_data", "wikimedia_id", "meta_id",
        "event_type", "namespace", "title", "title_url", "comment",
        "event_timestamp", "user_name", "is_bot", "is_minor", "wiki",
        "server_url", "notify_url", "canonical_entity",
        "length_old", "length_new", "revision_old", "revision_new",
        "kafka_topic", "kafka_partition", "kafka_offset", "ingestion_timestamp",
        "bytes_changed", "is_revert", "is_anonymous", "event_hour",
        "processing_lag_seconds", "has_comment",
        "is_large_edit", "is_bot_consistent", "is_allowlisted",
        "event_date"
    ]
    
    def process_batch(batch_df, batch_id):
        """Process each micro-batch with quality gate - only write passed records"""
        # Fast empty check - avoids full count
        if len(batch_df.take(1)) == 0:
            logger.info(f"Batch {batch_id}: Empty batch, skipping")
            return
        
        logger.info(f"Batch {batch_id}: Processing batch...")
        
        if quality_gate:
            # Apply quality gate - returns (passed_df, failed_df, metrics)
            # skip_pydeequ=True for faster processing (~10x speedup)
            # SQL-based flags are sufficient for filtering bad records
            passed_df, failed_df, metrics = quality_gate.validate_and_filter(
                df=batch_df,
                batch_id=f"silver_{batch_id}",
                skip_pydeequ=False  # Use SQL-based flags only for speed
            )
            
            # Use counts from metrics - already computed in validate_and_filter
            passed_count = metrics.get("passed_count", 0)
            failed_count = metrics.get("failed_count", 0)
            total_count = passed_count + failed_count
            logger.info(f"Batch {batch_id}: {total_count} records ({passed_count} passed, {failed_count} failed)")
            
            # Cache the filtered DataFrames to avoid recomputation during writes
            if passed_count > 0:
                passed_df.cache()
            if failed_count > 0:
                failed_df.cache()
            
            # Write passed records to silver table
            if passed_count > 0:
                # Select only silver columns (exclude quality flags used for filtering)
                existing_cols = [c for c in silver_columns if c in passed_df.columns]
                clean_df = passed_df.select(existing_cols)
                
                try:
                    clean_df.writeTo(table_name).option("fanout-enabled", "true").append()
                    logger.info(f"Batch {batch_id}: Successfully wrote {passed_count} records to silver table")
                except Exception as e:
                    logger.error(f"Batch {batch_id}: Failed to write passed records to silver table: {e}")
                    raise Exception(f"Silver table write failed: {e}")
            
            # Write failed records to quarantine (quality gate's responsibility was only to identify them)
            if failed_count > 0:
                failed_checks = metrics.get("failed_checks", [])
                try:
                    quality_gate.quarantine_writer.write_to_quarantine(
                        failed_df=failed_df,
                        layer="silver", 
                        batch_id=f"silver_{batch_id}",
                        failed_checks=failed_checks
                    )
                    logger.warning(f"Batch {batch_id}: Quarantined {failed_count} records due to quality failures")
                except Exception as e:
                    logger.error(f"Batch {batch_id}: Failed to quarantine failed records: {e}")
                    raise Exception(f"Quarantine write failed: {e}")
            
            # Release caches
            if passed_count > 0:
                passed_df.unpersist()
            if failed_count > 0:
                failed_df.unpersist()
            
            logger.info(f"Batch {batch_id}: Complete - pass_rate={metrics.get('pass_rate', 1.0):.2%}")
        else:
            # No quality gate - write all records (backward compatibility)
            existing_cols = [c for c in silver_columns if c in batch_df.columns]
            batch_df.cache()
            record_count = batch_df.count()
            batch_df.select(existing_cols).writeTo(table_name).option("fanout-enabled", "true").append()
            logger.info(f"Batch {batch_id}: Wrote {record_count} records (no DQ)")
            batch_df.unpersist()
    
    return process_batch


def write_to_iceberg(df, table_name, checkpoint_location, trigger_interval="10 minutes",
                     glue_database=None, s3_bucket=None, alert_manager=None):
    """Write streaming data to Iceberg table with quality gate (only passed records)"""
    
    spark = df.sparkSession
    logger.info(f"Writing to Iceberg table with quality gate: {table_name}")
    
    # Create batch processor with quality gate
    batch_processor = create_silver_batch_processor(
        spark=spark,
        table_name=table_name,
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        alert_manager=alert_manager
    )
    
    query = df.writeStream \
        .foreachBatch(batch_processor) \
        .trigger(processingTime=trigger_interval) \
        .option("checkpointLocation", checkpoint_location) \
        .start()
    
    logger.info(f"Streaming query with quality gate started: {checkpoint_location}")
    return query


def main():
    """Main entry point for Silver layer Spark job"""
    
    if len(sys.argv) < 3:
        logger.error("Usage: silver_writer.py <s3_bucket> <glue_database>")
        sys.exit(1)
    
    s3_bucket = sys.argv[1]
    glue_database = sys.argv[2]
    
    starting_offsets = sys.argv[3] if len(sys.argv) > 3 else "latest"
    
    logger.info(f"Starting Silver Writer")
    logger.info(f"S3 Bucket: {s3_bucket}")
    logger.info(f"Glue Database: {glue_database}")
    
    spark = get_spark_session()
    
    # Create Silver Iceberg table - clean data only, no quality flags
    # Quality validation handled by SilverQualityGate, failed records go to quarantine
    create_silver_table_sql = f"""
    CREATE TABLE IF NOT EXISTS glue_catalog.`{glue_database}`.silver_events (
        -- Core identifiers
        event_id STRING,
        event_data STRING,
        wikimedia_id BIGINT,
        meta_id STRING,
        
        -- Core event fields
        event_type STRING,
        namespace INT,
        title STRING,
        title_url STRING,
        comment STRING,
        event_timestamp BIGINT,
        user_name STRING,
        is_bot BOOLEAN,
        is_minor BOOLEAN,
        wiki STRING,
        server_url STRING,
        notify_url STRING,
        canonical_entity STRING,
        
        -- Length and revision data
        length_old INT,
        length_new INT,
        revision_old BIGINT,
        revision_new BIGINT,
        
        -- Kafka metadata (lineage)
        kafka_topic STRING,
        kafka_partition INT,
        kafka_offset BIGINT,
        ingestion_timestamp TIMESTAMP,
        
        -- Derived metrics for Gold layer
        bytes_changed INT,
        is_revert BOOLEAN,
        is_anonymous BOOLEAN,
        event_hour INT,
        processing_lag_seconds BIGINT,
        has_comment BOOLEAN,
        is_large_edit BOOLEAN,
        is_bot_consistent BOOLEAN,
        is_allowlisted BOOLEAN,
        
        -- Partitioning
        event_date DATE
    )
    USING iceberg
    PARTITIONED BY (event_date)
    LOCATION 's3://{s3_bucket}/data/silver_events/'
    TBLPROPERTIES (
        'format-version' = '2',
        'write.format.default' = 'parquet',
        'write.parquet.compression-codec' = 'snappy'
    )
    """
    
    logger.info("Creating Silver Iceberg table if not exists...")
    spark.sql(create_silver_table_sql)
    logger.info("Silver table ready")
    
    # Read from Bronze Iceberg table
    bronze_df = read_from_bronze(
        spark=spark,
        glue_database=glue_database
    )
    
    # Parse event data + add derived metrics for Gold layer
    parsed_df = parse_event_data(bronze_df)
    
    # Deduplicate events (handles replay events)
    deduplicated_df = deduplicate_events(parsed_df)
    
    # Transform to Silver schema
    silver_df = transform_to_silver_schema(deduplicated_df)
    
    # Iceberg table and checkpoint paths
    iceberg_table = f"glue_catalog.`{glue_database}`.`silver_events`"
    checkpoint_path = f"s3://{s3_bucket}/checkpoints/silver_events/"
    
    # Initialize alert manager for quality gate notifications
    alert_manager = None
    if QUALITY_MODULE_AVAILABLE:
        logger.info("Initializing AlertManager for SilverQualityGate...")
        alert_manager = AlertManager(
            sns_topic_arn=os.getenv("SNS_TOPIC_ARN"),
            slack_channel=os.getenv("SLACK_CHANNEL", "#data-quality"),
            slack_token=os.getenv("SLACK_BOT_TOKEN")
        )
        
        # Create quality metrics table for QuickSight
        try:
            create_quality_metrics_table(spark, glue_database, s3_bucket)
        except Exception as e:
            logger.warning(f"Could not create quality metrics table: {e}")
    else:
        logger.warning("Data quality module not available - running without DQ checks")
    
    # Write to Iceberg with SilverQualityGate (only passed records, failed go to quarantine)
    # 10 minutes trigger for near-real-time processing
    # Note: isUnique removed from PyDeequ (handled by upstream dedup) for faster quality checks
    query = write_to_iceberg(
        df=silver_df,
        table_name=iceberg_table,
        checkpoint_location=checkpoint_path,
        trigger_interval="10 minutes",
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        alert_manager=alert_manager
    )

    # Monitor streaming query
    logger.info("Silver writer is running with data quality checks. Monitoring query progress...")
    
    # Run indefinitely - this is a streaming job
    try:
        query.awaitTermination()
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise
    
    if query.exception():
        logger.error(f"Query failed: {query.exception()}")
        raise query.exception()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Job interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Job failed: {e}", exc_info=True)
        sys.exit(1)