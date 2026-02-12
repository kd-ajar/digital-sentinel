"""
Bronze Layer Writer - Spark Structured Streaming
Reads from MSK cleaned_events topic and writes to bronze_events or quarantine as apache iceberg table
With PyDeequ-based Quality Gate
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, current_timestamp, to_date
)
import sys
import os
import logging

# Import quality gate
from data_quality import BronzeQualityGate, AlertManager

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


def read_from_kafka(spark, bootstrap_servers, topic, starting_offsets="latest"):
    """Read streaming data from Kafka/MSK"""
    
    logger.info(f"Reading from Kafka topic: {topic}")
    logger.info(f"Bootstrap servers: {bootstrap_servers}")
    
    df = spark.readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", bootstrap_servers) \
        .option("subscribe", topic) \
        .option("startingOffsets", starting_offsets) \
        .option("kafka.security.protocol", "SSL") \
        .option("failOnDataLoss", "false") \
        .option("kafka.request.timeout.ms", "120000") \
        .option("kafka.session.timeout.ms", "60000") \
        .option("kafka.heartbeat.interval.ms", "10000") \
        .option("kafka.connections.max.idle.ms", "180000") \
        .option("kafka.metadata.max.age.ms", "180000") \
        .option("kafka.reconnect.backoff.ms", "1000") \
        .option("kafka.reconnect.backoff.max.ms", "10000") \
        .option("kafka.retry.backoff.ms", "500") \
        .load()
    
    logger.info("Kafka stream initiated")
    return df


def transform_to_bronze_schema(df):
    """Transform Kafka data to Bronze schema"""
    
    logger.info("Applying Bronze schema transformation")
    
    # Extract Kafka metadata and value
    # Use explicit event_date for partitioning (hidden partitioning not supported in streaming)
    bronze_df = df.select(
        # Kafka metadata
        col("key").cast("string").alias("event_id"),
        col("value").cast("string").alias("event_data"),
        col("topic").alias("kafka_topic"),
        col("partition").alias("kafka_partition"),
        col("offset").alias("kafka_offset"),
        
        # Add ingestion metadata
        current_timestamp().alias("ingestion_timestamp"),
        # Explicit date column for partitioning (hidden partitioning not supported in streaming)
        to_date(current_timestamp()).alias("event_date")
    )
    
    logger.info("Bronze schema applied")
    return bronze_df


def create_bronze_batch_processor(spark, table_name, glue_database, s3_bucket, alert_manager=None):
    """Create a batch processor with quality gate"""
    
    quality_gate = BronzeQualityGate(
        spark=spark,
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        alert_manager=alert_manager
    )
    
    def process_batch(batch_df, batch_id):
        """Process each micro-batch with quality gate"""
        if batch_df.rdd.isEmpty():
            logger.info(f"Batch {batch_id}: Empty batch, skipping")
            return
        
        record_count = batch_df.count()
        logger.info(f"Batch {batch_id}: Processing {record_count} records")
        
        # Apply quality gate - returns (passed_df, failed_df, metrics)
        passed_df, failed_df, metrics = quality_gate.validate_and_filter(
            df=batch_df,
            batch_id=f"bronze_{batch_id}"
        )
        
        # Layer writer handles ALL writing: passed records to target, failed records to quarantine
        passed_count = passed_df.count()
        failed_count = failed_df.count()
        
        # Write passed records to bronze table
        if passed_count > 0:
            # Remove quality flag column before writing
            clean_df = passed_df.drop("is_quality_passed")
            
            try:
                clean_df.writeTo(table_name).option("fanout-enabled", "true").append()
                logger.info(f"Batch {batch_id}: Successfully wrote {passed_count} records to bronze table")
            except Exception as e:
                logger.error(f"Batch {batch_id}: Failed to write passed records to bronze table: {e}")
                raise Exception(f"Bronze table write failed: {e}")
        
        # Write failed records to quarantine (quality gate's responsibility was only to identify them)
        if failed_count > 0:
            failed_checks = metrics.get("failed_checks", [])
            try:
                quality_gate.quarantine_writer.write_to_quarantine(
                    failed_df=failed_df,
                    layer="bronze",
                    batch_id=f"bronze_{batch_id}",
                    failed_checks=failed_checks
                )
                logger.warning(f"Batch {batch_id}: Quarantined {failed_count} records due to quality failures")
            except Exception as e:
                logger.error(f"Batch {batch_id}: Failed to quarantine failed records: {e}")
                raise Exception(f"Quarantine write failed: {e}")
        
        logger.info(f"Batch {batch_id}: Complete - pass_rate={metrics.get('pass_rate', 1.0):.2%}")
    
    return process_batch


def write_to_iceberg_with_quality(df, table_name, checkpoint_location, glue_database, 
                                   s3_bucket, trigger_interval="2 minutes", alert_manager=None):
    """Write streaming data to Iceberg table with quality gate"""
    
    spark = df.sparkSession
    logger.info(f"Writing to Iceberg table with quality gate: {table_name}")
    
    # Create batch processor with quality gate
    batch_processor = create_bronze_batch_processor(
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

    logger.info(f"Streaming query started with checkpoint: {checkpoint_location}")
    return query


def main():
    """Main entry point for Bronze layer Spark job"""
    
    # Configuration from command line arguments or environment
    if len(sys.argv) < 4:
        logger.error("Usage: bronze_writer.py <bootstrap_servers> <s3_bucket> <glue_database>")
        sys.exit(1)
    
    bootstrap_servers = sys.argv[1]
    s3_bucket = sys.argv[2]
    glue_database = sys.argv[3]
    
    # Optional parameters
    topic = sys.argv[4] if len(sys.argv) > 4 else "raw_events"
    starting_offsets = sys.argv[5] if len(sys.argv) > 5 else "latest"
    
    logger.info(f"Starting Bronze Writer")
    logger.info(f"Bootstrap Servers: {bootstrap_servers}")
    logger.info(f"S3 Bucket: {s3_bucket}")
    logger.info(f"Glue Database: {glue_database}")
    logger.info(f"Topic: {topic}")
    logger.info(f"Starting Offsets: {starting_offsets}")
    
    # Get existing Spark session
    spark = get_spark_session()
    
    # Create Iceberg table if it doesn't exist
    # Using explicit event_date partitioning (hidden partitioning not supported in streaming)
    create_bronze_table_sql = f"""
    CREATE TABLE IF NOT EXISTS glue_catalog.`{glue_database}`.bronze_events (
        event_id STRING,
        event_data STRING,
        kafka_topic STRING,
        kafka_partition INT,
        kafka_offset BIGINT,
        ingestion_timestamp TIMESTAMP,
        event_date DATE
    )
    USING iceberg
    PARTITIONED BY (event_date)
    LOCATION 's3://{s3_bucket}/data/bronze_events/'
    TBLPROPERTIES (
        'format-version' = '2',
        'write.format.default' = 'parquet',
        'write.parquet.compression-codec' = 'snappy'
    )
    """
    
    logger.info("Creating Bronze Iceberg table if not exists...")
    spark.sql(create_bronze_table_sql)
    logger.info("Bronze table ready")
    
    # Read from Kafka
    kafka_df = read_from_kafka(
        spark=spark,
        bootstrap_servers=bootstrap_servers,
        topic=topic,
        starting_offsets=starting_offsets
    )
    
    # Transform to Bronze schema
    bronze_df = transform_to_bronze_schema(kafka_df)
    
    # Iceberg table and checkpoint paths
    iceberg_table = f"glue_catalog.`{glue_database}`.`bronze_events`"
    checkpoint_path = f"s3://{s3_bucket}/checkpoints/bronze_events/"
    
    # Initialize alert manager
    alert_manager = AlertManager(
        sns_topic_arn=os.getenv("SNS_TOPIC_ARN"),
        slack_channel=os.getenv("SLACK_CHANNEL", "#data-quality"),
        slack_token=os.getenv("SLACK_BOT_TOKEN")
    )
    
    # Write to Iceberg with quality gate
    query = write_to_iceberg_with_quality(
        df=bronze_df,
        table_name=iceberg_table,
        checkpoint_location=checkpoint_path,
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        trigger_interval="2 minutes",
        alert_manager=alert_manager
    )
    
    # Monitor streaming query
    logger.info("Bronze writer is running. Monitoring query progress...")
    logger.info(f"Query ID: {query.id}")
    logger.info(f"Query Name: {query.name}")
    
    # Log progress every 30 seconds
    while query.isActive:
        try:
            progress = query.lastProgress
            if progress:
                logger.info(
                    f"Progress: "
                    f"batchId={progress['batchId']}, "
                    f"numInputRows={progress.get('numInputRows', 0)}, "
                    f"inputRowsPerSecond={progress.get('inputRowsPerSecond', 0):.2f}, "
                    f"processedRowsPerSecond={progress.get('processedRowsPerSecond', 0):.2f}"
                )
        except Exception as e:
            logger.warning(f"Error getting progress: {e}")
        
        query.awaitTermination()  # Wait 30 seconds
    
    # Handle query termination
    if query.exception():
        logger.error(f"Query failed with exception: {query.exception()}")
        raise query.exception()
    else:
        logger.info("Query terminated successfully")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Job interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Job failed with error: {e}", exc_info=True)
        sys.exit(1)
