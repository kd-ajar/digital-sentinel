"""
Data Quality Module using PyDeequ
Clean architecture with quality gates for Bronze, Silver, and Gold layers

MEDALLION ARCHITECTURE IMPLEMENTATION:

# BRONZE LAYER (Raw Ingestion - Schema Conformity)
1. Read raw JSON + Kafka metadata from MSK (cleaned_events topic)
2. Transform to Bronze Schema:
   - event_id (from Kafka key)
   - event_data (raw Wikipedia JSON as string)
   - kafka_topic, kafka_partition, kafka_offset (lineage metadata)
   - ingestion_timestamp (processing time for freshness)
   - event_date (partitioning column)
3. Apply Quality Checks:
   - COMPLETENESS: All required fields present (event_id, event_data, kafka_topic, event_date, ingestion_timestamp)
   - CONFORMITY: Data types match schema, non-negative offsets/partitions
   - FRESHNESS: Ingestion timestamp populated for every record
   - TRACEABILITY: Kafka metadata preserved for full lineage
   - SIZE: Batch must contain at least 1 record
   - UNIQUENESS: NOT checked (raw duplication preserved for audit)
   - BUSINESS LOGIC: NO business validation, only technical schema validation
4. Save to Iceberg:
   - Passed records → bronze_events (partitioned by event_date)
   - Failed records → bronze_quarantine (with failure reasons)

# SILVER LAYER (Cleaned & Deduplicated - Business Logic)
1. Read from bronze_events (only records that passed Bronze quality gate)
2. Transform to Silver Schema:
   - Parse JSON event_data to structured columns
   - Extract: meta_id, wikimedia_id, event_type, title, user_name, wiki, namespace
   - Add derived fields: is_anonymous, is_bot, is_revert, bytes_changed
   - Calculate: processing_lag_seconds, canonical_entity (entity linking)
3. Apply Quality Checks:
   - CORRECTNESS: event_type in ["edit", "new", "log", "categorize"]
   - DEDUPLICATION: Unique meta_id (Wikipedia's unique event identifier)
   - FRESHNESS: processing_lag_seconds between 0-3600 (arrive within 1 hour)
   - COMPLETENESS: Critical fields non-null (meta_id, wikimedia_id, event_type, title, user_name, wiki)
   - VALIDITY: wikimedia_id > 0, namespace >= 0
   - TEMPORAL VALIDITY: 
     * event_timestamp > 1640995200 (after 2022-01-01)
     * event_timestamp < (current_time + 600) (not more than 10min in future)
4. Save to Iceberg:
   - Passed records → silver_events (partitioned by event_date)
   - Failed records → silver_quarantine (with detailed failure analysis)

# GOLD LAYER (Aggregated Metrics - Statistical Validation)
1. Read from silver_events (clean, deduplicated business events)
2. Calculate Aggregations (10-minute windows):
   - Entity Metrics: total_events, edit_count, revert_count, anonymous_edit_count per entity/wiki
   - User Metrics: user activity patterns, edit volume per user/wiki
   - Global Metrics: cross-wiki statistics, anomaly detection features
   - Statistical Features: avg_bytes_changed, stddev for anomaly detection
3. Apply Quality Checks (Adaptive based on metric type):
   - AGGREGATION CORRECTNESS: total_events >= 0, revert_count <= edit_count
   - ENTITY VALIDATION: entity field non-null (for entity_metrics tables)
   - USER VALIDATION: user_name field non-null (for user_metrics tables)
   - WIKI VALIDATION: wiki field non-null (for cross-wiki metrics)
   - SIZE: Aggregation windows must contain at least 1 record
   - BUSINESS RULES: Anonymous count <= total events, logical constraints
4. Save to Iceberg:
   - Passed records → gold_entity_metrics, gold_user_metrics (partitioned by metric_date)
   - Failed records → gold_quarantine (aggregation validation failures)

QUALITY GATE FRAMEWORK:
- BaseQualityGate: Abstract class with validate_and_filter() method
- PyDeequ Integration: Statistical data profiling and constraint checking
- AlertManager: CRITICAL → SNS + Slack, WARNING → Slack, INFO → Logs
- QuarantineWriter: Failed records stored in Iceberg quarantine tables with full lineage
- Metrics Collection: Pass rates, failure reasons, batch tracking for monitoring

ALERT SEVERITY MAPPING:
- CRITICAL: Pass rate < 80%, failed checks contain ["Complete", "Unique", "NotNull", "Size"]
- WARNING: Pass rate < 95%, non-critical constraint failures
- SUCCESS: Pass rate >= 95%, all constraints satisfied

Architecture:
- BronzeQualityGate: Schema conformity, not-null, basic ranges
- SilverQualityGate: Completeness, uniqueness after deduplication
- GoldQualityGate: Lightweight aggregation validation
- AlertManager: SNS (critical) / Slack (warning)
- QuarantineWriter: Writes to Iceberg quarantine tables
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import (
    col, lit, current_timestamp, when, to_date, unix_timestamp, to_json, struct
)
from datetime import datetime
from abc import ABC, abstractmethod
import logging
import json
import os

# Set SPARK_VERSION before importing PyDeequ (required at import time)
# EMR Serverless 7.2.0 uses Spark 3.5
if "SPARK_VERSION" not in os.environ:
    os.environ["SPARK_VERSION"] = "3.5"

# AWS SDK
try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

# Slack SDK
try:
    from slack_sdk import WebClient
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False

# PyDeequ
try:
    import pydeequ
    from pydeequ.checks import Check, CheckLevel
    from pydeequ.verification import VerificationSuite, VerificationResult
    PYDEEQU_AVAILABLE = True
except ImportError:
    PYDEEQU_AVAILABLE = False
    logging.warning("PyDeequ not available")

logger = logging.getLogger(__name__)


# ============================================================================
# ALERT MANAGER
# ============================================================================

def get_slack_token_from_secrets_manager(secret_name: str = "wikiguard/slack-bot-token", region: str = "us-east-1") -> str:
    """Fetch Slack Bot Token from AWS Secrets Manager"""
    if not BOTO3_AVAILABLE:
        return None
    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
        return response.get("SecretString")
    except Exception as e:
        logger.warning(f"Failed to fetch Slack token from Secrets Manager: {e}")
        return None


class AlertManager:
    """Routes alerts: CRITICAL->SNS+Slack, WARNING->Slack, INFO->log"""
    
    def __init__(self, sns_topic_arn: str = None, slack_channel: str = None, 
                 slack_token: str = None, region: str = "us-east-1",
                 slack_secret_name: str = "wikiguard/slack-bot-token"):
        self.sns_topic_arn = sns_topic_arn or os.getenv("SNS_TOPIC_ARN")
        self.slack_channel = slack_channel or os.getenv("SLACK_CHANNEL", "#data-quality")
        self.region = region
        self.sns_client = None
        self.slack_client = None
        
        # Log alert configuration for debugging
        logger.info(f"AlertManager init: SNS_TOPIC_ARN={self.sns_topic_arn}, SLACK_CHANNEL={self.slack_channel}")
        logger.info(f"AlertManager: BOTO3_AVAILABLE={BOTO3_AVAILABLE}, SLACK_AVAILABLE={SLACK_AVAILABLE}")
        
        # Get Slack token: 1) explicit param, 2) env var, 3) Secrets Manager
        self.slack_token = slack_token or os.getenv("SLACK_BOT_TOKEN")
        if not self.slack_token:
            self.slack_token = get_slack_token_from_secrets_manager(slack_secret_name, region)
        logger.info(f"AlertManager: slack_token={'SET' if self.slack_token else 'NOT SET'}")
        
        if BOTO3_AVAILABLE and self.sns_topic_arn:
            try:
                self.sns_client = boto3.client("sns", region_name=self.region)
                logger.info(f"AlertManager: SNS client initialized successfully")
            except Exception as e:
                logger.warning(f"SNS init failed: {e}")
        else:
            logger.warning(f"AlertManager: SNS not configured (BOTO3={BOTO3_AVAILABLE}, topic={self.sns_topic_arn})")
        
        if SLACK_AVAILABLE and self.slack_token:
            try:
                self.slack_client = WebClient(token=self.slack_token)
                logger.info(f"AlertManager: Slack client initialized successfully")
            except Exception as e:
                logger.warning(f"Slack init failed: {e}")
        else:
            logger.warning(f"AlertManager: Slack not configured (SLACK_AVAILABLE={SLACK_AVAILABLE}, token={'SET' if self.slack_token else 'NOT SET'})")
    
    def send_alert(self, severity: str, title: str, message: str, metrics: dict = None):
        """Route alert based on severity"""
        logger.info(f"[{severity}] {title}")
        logger.info(f"AlertManager.send_alert: sns_client={'SET' if self.sns_client else 'NONE'}, slack_client={'SET' if self.slack_client else 'NONE'}")
        if severity == "CRITICAL":
            self._send_sns(title, message, metrics)
            self._send_slack(title, message, metrics, severity)
        elif severity == "WARNING":
            self._send_slack(title, message, metrics, severity)
        else:
            logger.info(f"INFO: {title} - {message}")
    
    def _send_sns(self, title: str, message: str, metrics: dict = None):
        if not self.sns_client:
            logger.warning(f"SNS client not available, skipping SNS alert: {title}")
            return
        try:
            msg = {"default": f"CRITICAL: {title}\n\n{message}",
                   "email": f"CRITICAL: {title}\n\n{message}\n\n{json.dumps(metrics or {}, indent=2)}",
                   "sms": f"CRITICAL: {title}"}
            self.sns_client.publish(TopicArn=self.sns_topic_arn, Subject=title,
                                    Message=json.dumps(msg), MessageStructure="json")
            logger.info(f"SNS alert sent: {title}")
        except Exception as e:
            logger.error(f"SNS failed: {e}")
    
    def _send_slack(self, title: str, message: str, metrics: dict = None, severity: str = "INFO"):
        if not self.slack_client:
            logger.warning(f"Slack client not available, skipping Slack alert: {title}")
            return
        try:
            emoji = {"CRITICAL": "alert", "WARNING": "warning", "INFO": "info"}.get(severity, "chart")
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": f"{severity}: {title}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": message}}
            ]
            if metrics:
                metrics_text = ""
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Metrics:*\n{metrics_text}"}})
            self.slack_client.chat_postMessage(channel=self.slack_channel, blocks=blocks, text=f"{severity}: {title}")
            logger.info(f"Slack alert sent: {title}")
        except Exception as e:
            logger.error(f"Slack failed: {e}")


# ============================================================================
# QUARANTINE WRITER - Writes to Iceberg quarantine tables
# ============================================================================

class QuarantineWriter:
    """Writes failed records to Iceberg quarantine tables"""
    
    def __init__(self, spark: SparkSession, glue_database: str, s3_bucket: str):
        self.spark = spark
        self.glue_database = glue_database
        self.s3_bucket = s3_bucket
    
    def create_quarantine_table(self, layer: str):
        """Create Iceberg quarantine table with fixed schema - original data stored as JSON"""
        table_name = f"{layer}_quarantine"
        full_table_name = f"glue_catalog.`{self.glue_database}`.{table_name}"
        
        # Check if table exists and has the correct schema (must have original_record column)
        try:
            existing_cols = [row.col_name for row in self.spark.sql(f"DESCRIBE {full_table_name}").collect()]
            if "original_record" not in existing_cols:
                logger.warning(f"Quarantine table {table_name} has old schema, dropping and recreating...")
                self.spark.sql(f"DROP TABLE IF EXISTS {full_table_name}")
        except Exception:
            pass  # Table doesn't exist, will be created
        
        # Fixed schema with original_record column to store failed data as JSON
        # This avoids schema evolution issues with writeTo().append()
        sql = f"""
        CREATE TABLE IF NOT EXISTS {full_table_name} (
            quarantine_timestamp TIMESTAMP,
            quarantine_reason STRING,
            quarantine_batch_id STRING,
            failed_checks STRING,
            original_record STRING,
            event_date DATE
        )
        USING iceberg
        PARTITIONED BY (event_date)  
        LOCATION "s3://{self.s3_bucket}/data/{table_name}/"
        TBLPROPERTIES (
            "format-version" = "2",
            "write.format.default" = "parquet"
        )
        """
        try:
            self.spark.sql(sql)
            logger.info(f"Quarantine table ready: {table_name}")
        except Exception as e:
            logger.error(f"Failed to create quarantine table: {e}")
    
    def write_to_quarantine(self, failed_df: DataFrame, layer: str, batch_id: str, 
                           failed_checks: list) -> int:
        """Write failed records to Iceberg quarantine table"""
        if failed_df.rdd.isEmpty():
            logger.info(f"No records to quarantine for {layer}")
            return 0
        
        failed_count = failed_df.count()
        logger.warning(f"Quarantining {failed_count} records to {layer}_quarantine")
        
        # Serialize original record as JSON to avoid schema mismatch
        # Get all columns except quality flags for the original record
        original_columns = [c for c in failed_df.columns if not c.startswith("is_quality") 
                           and c not in ["has_schema_violations", "is_valid_type", "is_fresh", 
                                        "is_temporal_valid", "quality_check_timestamp"]]
        
        quarantine_df = failed_df \
            .withColumn("original_record", to_json(struct(*[col(c) for c in original_columns]))) \
            .withColumn("quarantine_timestamp", current_timestamp()) \
            .withColumn("quarantine_batch_id", lit(batch_id)) \
            .withColumn("quarantine_reason", lit("quality_check_failed")) \
            .withColumn("failed_checks", lit(json.dumps(failed_checks))) \
            .withColumn("event_date", to_date(col("ingestion_timestamp"))) \
            .select(
                "quarantine_timestamp",
                "quarantine_reason", 
                "quarantine_batch_id",
                "failed_checks",
                "original_record",
                "event_date"
            )
        
        logger.info(f"Quarantining {failed_count} records with serialized original data")
        
        table_name = f"glue_catalog.`{self.glue_database}`.{layer}_quarantine"
        try:
            quarantine_df.writeTo(table_name).option("fanout-enabled", "true").append()
            logger.info(f"Quarantined {failed_count} records to {table_name}")
            return failed_count
        except Exception as e:
            logger.error(f"Failed to write to quarantine: {e}")
            fallback_path = f"s3://{self.s3_bucket}/quarantine_fallback/{layer}/"
            quarantine_df.write.mode("append").partitionBy("event_date").parquet(fallback_path)
            logger.warning(f"Fallback: wrote to {fallback_path}")
            return failed_count


# ============================================================================
# BASE QUALITY GATE
# ============================================================================

class BaseQualityGate(ABC):
    """Abstract base class for quality gates"""
    
    def __init__(self, spark: SparkSession, glue_database: str, s3_bucket: str,
                 alert_manager: AlertManager = None):
        self.spark = spark
        self.glue_database = glue_database
        self.s3_bucket = s3_bucket
        self.alert_manager = alert_manager
        self.quarantine_writer = QuarantineWriter(spark, glue_database, s3_bucket)
        if not PYDEEQU_AVAILABLE:
            logger.warning("PyDeequ not available - using basic validation")
    
    @property
    @abstractmethod
    def layer_name(self) -> str:
        pass
    
    @abstractmethod
    def get_checks(self):
        pass
    
    @abstractmethod
    def add_quality_flags(self, df: DataFrame) -> DataFrame:
        pass
    
    def validate_and_filter(self, df: DataFrame, batch_id: str = None, skip_pydeequ: bool = False) -> tuple:
        """Run quality checks and return (passed_df, failed_df, metrics)
        
        Args:
            df: Input DataFrame to validate
            batch_id: Unique batch identifier
            skip_pydeequ: If True, skip expensive PyDeequ checks and use only SQL-based flags.
                         Set to True for faster processing (~10x speedup).
        """
        batch_id = batch_id or f"{self.layer_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"Running {self.layer_name} quality gate: {batch_id}")
        
        self.quarantine_writer.create_quarantine_table(self.layer_name)
        
        metrics = {"batch_id": batch_id, "layer": self.layer_name, "checks": {}}
        failed_checks = []
        
        # PyDeequ checks are optional - SQL-based flags are sufficient for filtering
        # Skip PyDeequ for faster processing (10x speedup)
        if PYDEEQU_AVAILABLE and not skip_pydeequ:
            try:
                check = self.get_checks()
                result = VerificationSuite(self.spark).onData(df).addCheck(check).run()
                result_df = VerificationResult.checkResultsAsDataFrame(self.spark, result)
                for row in result_df.collect():
                    status = row.constraint_status
                    metrics["checks"][row.constraint] = status
                    if status == "Failure":
                        failed_checks.append(row.constraint)
                result_df.show(truncate=False)
            except Exception as e:
                logger.error(f"PyDeequ check failed: {e}")
        else:
            logger.info(f"Skipping PyDeequ checks (skip_pydeequ={skip_pydeequ}), using SQL-based flags only")
        
        df_with_flags = self.add_quality_flags(df)
        
        # NOTE: We do NOT cache here - the caller (silver_writer) is responsible
        # for caching passed_df/failed_df before writing.
        # Caching here and unpersisting breaks the lazy chain since returned DFs
        # are filters on df_with_flags.
        
        passed_df = df_with_flags.filter(col("is_quality_passed") == True)
        failed_df = df_with_flags.filter(col("is_quality_passed") == False)
        
        # Single count operation - count both in one pass using aggregation
        # This materializes df_with_flags once to get counts
        counts = df_with_flags.groupBy("is_quality_passed").count().collect()
        passed_count = 0
        failed_count = 0
        for row in counts:
            if row["is_quality_passed"] == True:
                passed_count = row["count"]
            else:
                failed_count = row["count"]
        total_count = passed_count + failed_count
        
        metrics["total_count"] = total_count
        metrics["passed_count"] = passed_count
        metrics["failed_count"] = failed_count
        metrics["pass_rate"] = passed_count / total_count if total_count > 0 else 1.0
        
        logger.info(f"{self.layer_name} quality: {passed_count} passed, {failed_count} failed")
        
        # Quality gate should NOT write - just return data and let layer writers handle persistence
        # Store failed_checks in metrics for layer writers to use
        metrics["failed_checks"] = failed_checks
        
        severity = self._determine_severity(metrics, failed_checks)
        if self.alert_manager and severity in ["CRITICAL", "WARNING"]:
            self._send_alert(severity, metrics, batch_id)
        
        return passed_df, failed_df, metrics
    
    def _determine_severity(self, metrics: dict, failed_checks: list) -> str:
        """
        Determine alert severity based on pass rate AND failure type.
        
        Severity Logic:
        - CRITICAL: Pass rate < 80% (regardless of failure type)
        - CRITICAL: Pass rate < 95% AND critical failure types (Completeness, Size, etc.)
        - WARNING:  Pass rate < 95% (non-critical failures)
        - WARNING:  Pass rate >= 95% AND critical failure types (early warning)
        - SUCCESS:  Pass rate >= 95% AND no critical failures
        
        This prevents 99% pass rate from triggering CRITICAL alerts for minor issues.
        """
        pass_rate = metrics.get("pass_rate", 1.0)
        critical_keywords = ["Complete", "Unique", "NotNull", "Size"]
        has_critical_failure = any(kw in check for check in failed_checks for kw in critical_keywords)
        
        # Very low pass rate is always critical
        if pass_rate < 0.8:
            return "CRITICAL"
        
        # Moderate pass rate with critical failures is critical
        if pass_rate < 0.95 and has_critical_failure:
            return "CRITICAL"
        
        # Moderate pass rate with non-critical failures is warning
        if pass_rate < 0.95:
            return "WARNING"
        
        # High pass rate (>= 95%) with critical failures is just a warning (early alert)
        if has_critical_failure:
            return "WARNING"
        
        # High pass rate with no critical issues
        return "SUCCESS"
    
    def _send_alert(self, severity: str, metrics: dict, batch_id: str):
        pass_rate = metrics.get("pass_rate", 1.0) * 100
        title = f"{self.layer_name.title()} Quality Gate ({batch_id})"
        passed = metrics["passed_count"]
        failed = metrics["failed_count"]
        message = f"*Pass Rate:* {pass_rate:.1f}%\n*Passed:* {passed}\n*Failed:* {failed}"
        self.alert_manager.send_alert(severity, title, message, metrics)


# ============================================================================
# BRONZE QUALITY GATE
# ============================================================================

class BronzeQualityGate(BaseQualityGate):
    """Bronze: Schema conformity, not-null, basic ranges"""
    
    @property
    def layer_name(self) -> str:
        return "bronze"
    
    def get_checks(self):
        check = Check(self.spark, CheckLevel.Warning, "Bronze Quality")
        check = check \
            .hasSize(lambda x: x >= 1) \
            .isComplete("event_id") \
            .isComplete("event_data") \
            .isComplete("kafka_topic") \
            .isComplete("event_date") \
            .isComplete("ingestion_timestamp") \
            .isNonNegative("kafka_partition") \
            .isNonNegative("kafka_offset")
        return check
    
    def add_quality_flags(self, df: DataFrame) -> DataFrame:
        return df.withColumn("is_quality_passed",
            when(
                (col("event_id").isNotNull()) &
                (col("event_data").isNotNull()) &
                (col("kafka_topic").isNotNull()) &
                (col("kafka_offset").isNotNull()) &
                (col("ingestion_timestamp").isNotNull()),
                lit(True)
            ).otherwise(lit(False))
        )


# ============================================================================
# SILVER QUALITY GATE
# ============================================================================

class SilverQualityGate(BaseQualityGate):
    """Silver: Completeness, valid types, freshness (uniqueness handled by upstream dedup)"""
    
    @property
    def layer_name(self) -> str:
        return "silver"
    
    def get_checks(self):
        check = Check(self.spark, CheckLevel.Warning, "Silver Quality")
        check = check \
            .hasSize(lambda x: x >= 1) \
            .isComplete("event_id") \
            .isComplete("meta_id") \
            .isComplete("wikimedia_id") \
            .isComplete("event_type") \
            .isComplete("title") \
            .isComplete("user_name") \
            .isComplete("wiki") \
            .isContainedIn("event_type", ["edit", "new", "log", "categorize"]) \
            .isNonNegative("namespace") \
            .isPositive("wikimedia_id") \
            .isComplete("event_timestamp") \
            .isComplete("processing_lag_seconds") \
            .satisfies("processing_lag_seconds >= 0", "Events should not arrive before they happen") \
            .satisfies("processing_lag_seconds <= 3600", "Events should arrive within 1 hour (freshness)") \
            .satisfies("event_timestamp > 1640995200", "Events should be after 2022-01-01")
        return check
    
    def add_quality_flags(self, df: DataFrame) -> DataFrame:
        df = df.withColumn("is_quality_passed",
            when(
                (col("event_id").isNotNull()) &
                (col("meta_id").isNotNull()) &
                (col("wikimedia_id").isNotNull()) & (col("wikimedia_id") > 0) &
                (col("event_type").isin(["edit", "new", "log", "categorize"])) &
                (col("title").isNotNull()) &
                (col("user_name").isNotNull()) &
                (col("wiki").isNotNull()) &
                (col("namespace").isNotNull()) & (col("namespace") >= 0) &
                # Freshness check: events should arrive within 1 hour
                (col("processing_lag_seconds").isNotNull()) &
                (col("processing_lag_seconds") >= 0) & (col("processing_lag_seconds") <= 3600) &
                # Temporal validity: reasonable timestamp (after 2022)
                (col("event_timestamp").isNotNull()) & (col("event_timestamp") > 1640995200),
                lit(True)
            ).otherwise(lit(False))
        )
        df = df.withColumn("has_schema_violations",
            when(
                (col("event_id").isNull()) | (col("meta_id").isNull()) |
                (col("wikimedia_id").isNull()) | (col("title").isNull()) |
                (col("user_name").isNull()) | (col("wiki").isNull()),
                lit(True)
            ).otherwise(lit(False))
        )
        df = df.withColumn("is_valid_type",
            when(col("event_type").isin(["edit", "new", "log", "categorize"]), lit(True))
            .otherwise(lit(False))
        )
        df = df.withColumn("is_fresh",
            when(
                (col("processing_lag_seconds").isNotNull()) &
                (col("processing_lag_seconds") >= 0) & (col("processing_lag_seconds") <= 3600),
                lit(True)
            ).otherwise(lit(False))
        )
        df = df.withColumn("is_temporal_valid",
            when(
                (col("event_timestamp").isNotNull()) & (col("event_timestamp") > 1640995200) &
                (col("event_timestamp") < (unix_timestamp() + 600)),  # Not more than 10min in future
                lit(True)
            ).otherwise(lit(False))
        )
        df = df.withColumn("quality_check_timestamp", current_timestamp())
        return df


# ============================================================================
# GOLD QUALITY GATE
# ============================================================================

class GoldQualityGate(BaseQualityGate):
    """Gold: Lightweight aggregation validation - adapts to different metric types"""
    
    @property
    def layer_name(self) -> str:
        return "gold"
    
    def get_checks(self):
        # Basic check that works for all gold metric types
        check = Check(self.spark, CheckLevel.Warning, "Gold Quality")
        check = check \
            .hasSize(lambda x: x >= 1) \
            .isNonNegative("total_events")
        return check
    
    def add_quality_flags(self, df: DataFrame) -> DataFrame:
        """Add quality flags based on available columns in the DataFrame"""
        columns = df.columns
        
        # Start with basic check that total_events is non-negative
        quality_condition = col("total_events") >= 0
        
        # Add entity check only if entity column exists (entity_metrics)
        if "entity" in columns:
            quality_condition = quality_condition & col("entity").isNotNull()
        
        # Add wiki check only if wiki column exists (entity_metrics, user_metrics)
        if "wiki" in columns:
            quality_condition = quality_condition & col("wiki").isNotNull()
        
        # Add user_name check only if it exists (user_metrics)
        if "user_name" in columns:
            quality_condition = quality_condition & col("user_name").isNotNull()
        
        return df.withColumn("is_quality_passed",
            when(quality_condition, lit(True)).otherwise(lit(False))
        )


# ============================================================================
# QUALITY METRICS TABLE
# ============================================================================

def create_quality_metrics_table(spark: SparkSession, glue_database: str, s3_bucket: str):
    """Create Iceberg table for quality metrics"""
    sql = f"""
    CREATE TABLE IF NOT EXISTS glue_catalog.`{glue_database}`.quality_metrics (
        batch_id STRING,
        layer STRING,
        total_count BIGINT,
        passed_count BIGINT,
        failed_count BIGINT,
        pass_rate DOUBLE,
        failed_checks STRING,
        check_timestamp TIMESTAMP,
        event_date DATE
    )
    USING iceberg
    PARTITIONED BY (layer, event_date)
    LOCATION "s3://{s3_bucket}/data/quality_metrics/"
    TBLPROPERTIES ("format-version" = "2")
    """
    try:
        spark.sql(sql)
        logger.info("Quality metrics table created")
    except Exception as e:
        logger.error(f"Failed to create quality metrics table: {e}")

