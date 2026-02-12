"""
Gold Layer Writer - Spark Structured Streaming
Reads from Silver Iceberg table and writes aggregated metrics to Gold Iceberg tables
With lightweight PyDeequ-based Quality Gate for aggregation validation

Tier 2: Near-real-time (5-15 min)
- 10-minute aggregations for multi-metric correlation
- Per-entity and per-user risk metrics
- Anomaly detection features for Lookout for Metrics
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, window, count, sum as sum_col, avg, min as min_col, max as max_col,
    when, lit, current_timestamp, to_date,
    abs as abs_col, coalesce, 
    approx_count_distinct,
    stddev, percentile_approx, expr,
    concat_ws, array, floor, hour, dayofweek
)
from pyspark.sql.types import StringType
import sys
import os
import logging

# Data Quality imports - lightweight validation for aggregations
try:
    from data_quality import GoldQualityGate, AlertManager
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


def read_from_silver(spark, glue_database):
    """Read streaming data from Silver Iceberg table"""
    logger.info(f"Reading from Silver Iceberg table: {glue_database}.silver_events")
    
    df = spark.readStream \
        .format("iceberg") \
        .option("streaming-skip-delete-snapshots", "true") \
        .option("streaming-skip-overwrite-snapshots", "true") \
        .table(f"glue_catalog.`{glue_database}`.silver_events")
    
    logger.info("Silver stream initiated")
    return df


def compute_entity_metrics_10min(df):
    """
    Compute 10-minute aggregations per entity (canonical_entity or title)
    Multi-metric correlation: edits + reverts + anonymous + bytes_changed
    
    ENHANCED: Statistical anomaly detection with dynamic thresholds
    """
    logger.info("Computing 10-minute entity metrics with anomaly detection")
    
    # Use title as entity since canonical_entity may be null
    entity_metrics = df \
        .withColumn("entity", coalesce(col("canonical_entity"), col("title"))) \
        .withWatermark("ingestion_timestamp", "10 minutes") \
        .groupBy(
            window(col("ingestion_timestamp"), "10 minutes"),
            col("entity"),
            col("wiki")
        ).agg(
            # Volume metrics
            count("*").alias("total_events"),
            sum_col(when(col("event_type") == "edit", 1).otherwise(0)).alias("edit_count"),
            sum_col(when(col("event_type") == "new", 1).otherwise(0)).alias("new_page_count"),
            sum_col(when(col("event_type") == "categorize", 1).otherwise(0)).alias("categorize_count"),
            
            # Revert metrics (risk indicator)
            sum_col(when(col("is_revert") == True, 1).otherwise(0)).alias("revert_count"),
            
            # Anonymous metrics (vandalism risk)
            sum_col(when(col("is_anonymous") == True, 1).otherwise(0)).alias("anonymous_edit_count"),
            
            # Bot metrics
            sum_col(when(col("is_bot") == True, 1).otherwise(0)).alias("bot_edit_count"),
            
            # Bytes changed metrics
            sum_col(coalesce(col("bytes_changed"), lit(0))).alias("total_bytes_changed"),
            avg(coalesce(col("bytes_changed"), lit(0))).alias("avg_bytes_changed"),
            min_col(col("bytes_changed")).alias("min_bytes_changed"),
            max_col(col("bytes_changed")).alias("max_bytes_changed"),
            
            # Large edit anomalies
            sum_col(when(col("is_large_edit") == True, 1).otherwise(0)).alias("large_edit_count"),
            
            # Quality metrics - all silver records passed quality validation
            count("*").alias("quality_passed_count"),  # All silver records passed quality checks
            lit(0).alias("quality_failed_count"),  # Failed records quarantined in silver layer
            
            # User diversity
            approx_count_distinct("user_name").alias("unique_editors"),
            approx_count_distinct(when(col("is_anonymous") == True, col("user_name"))).alias("unique_anonymous_editors"),
            
            # Processing lag
            avg(col("processing_lag_seconds")).alias("avg_processing_lag_seconds"),
            max_col(col("processing_lag_seconds")).cast("long").alias("max_processing_lag_seconds"),
            
            # Comment quality
            sum_col(when(col("has_comment") == True, 1).otherwise(0)).alias("edits_with_comment"),
            
            # Time range (cast to long for Iceberg compatibility)
            min_col(col("event_timestamp")).cast("long").alias("first_event_timestamp"),
            max_col(col("event_timestamp")).cast("long").alias("last_event_timestamp")
        ) \
        .withColumn("window_start", col("window.start")) \
        .withColumn("window_end", col("window.end")) \
        .drop("window") \
        .withColumn(
            # Derived: Revert ratio (risk score component)
            "revert_ratio",
            when(col("edit_count") > 0, 
                 col("revert_count") / col("edit_count")
            ).otherwise(lit(0.0))
        ) \
        .withColumn(
            # Derived: Anonymous ratio (risk score component)
            "anonymous_ratio",
            when(col("total_events") > 0,
                 col("anonymous_edit_count") / col("total_events")
            ).otherwise(lit(0.0))
        ) \
        .withColumn(
            # Derived: Bot ratio
            "bot_ratio",
            when(col("total_events") > 0,
                 col("bot_edit_count") / col("total_events")
            ).otherwise(lit(0.0))
        ) \
        .withColumn(
            # Derived: Quality ratio
            "quality_ratio",
            when(col("total_events") > 0,
                 col("quality_passed_count") / col("total_events")
            ).otherwise(lit(1.0))
        ) \
        .withColumn(
            # ============================================
            # BASELINE THRESHOLDS (Wikipedia-wide norms)
            # These are empirically determined normal ranges.
            # Tune these values based on your observed traffic patterns:
            #   - baseline_events_avg: Average events per entity per 10-min window
            #   - baseline_events_stddev: Standard deviation for z-score calculation
            #   - baseline_revert_ratio: Normal revert rate (~12% for Wikipedia)
            #   - baseline_anonymous_ratio: Normal anonymous edit rate (~25%)
            # ============================================
            "baseline_events_avg", lit(5.0)  # Typical entity gets ~5 events/10min
        ) \
        .withColumn("baseline_events_stddev", lit(3.0)) \
        .withColumn("baseline_revert_ratio", lit(0.12)) \
        .withColumn("baseline_anonymous_ratio", lit(0.25)) \
        .withColumn(
            # ============================================
            # STATISTICAL DEVIATION FROM BASELINE
            # How many "standard deviations" above normal?
            # ============================================
            "events_zscore",
            (col("total_events") - col("baseline_events_avg")) / col("baseline_events_stddev")
        ) \
        .withColumn(
            # Deviation from normal revert rate
            "revert_deviation",
            col("revert_ratio") - col("baseline_revert_ratio")
        ) \
        .withColumn(
            # Deviation from normal anonymous rate
            "anonymous_deviation",
            col("anonymous_ratio") - col("baseline_anonymous_ratio")
        ) \
        .withColumn(
            # ============================================
            # ANOMALY FLAGS WITH STATISTICAL BACKING
            # Now based on z-score, not arbitrary thresholds
            # ============================================
            # ANOMALY FLAG: Burst activity (z-score > 2 = top 2.5%)
            "is_burst_activity",
            col("events_zscore") > 2.0
        ) \
        .withColumn(
            # ANOMALY FLAG: High revert rate (>2x baseline)
            "is_high_revert_rate",
            col("revert_ratio") > (col("baseline_revert_ratio") * 2.5)
        ) \
        .withColumn(
            # ANOMALY FLAG: Anonymous surge (>2x baseline)
            "is_anonymous_surge",
            col("anonymous_ratio") > (col("baseline_anonymous_ratio") * 2.0)
        ) \
        .withColumn(
            # ANOMALY FLAG: Large content change (>50KB total)
            "is_large_content_change",
            abs_col(col("total_bytes_changed")) > 51200
        ) \
        .withColumn(
            # ============================================
            # ANOMALY TYPE - Human readable explanation
            # ============================================
            "anomaly_types",
            concat_ws(", ",
                when(col("is_burst_activity"), lit("BURST")).otherwise(lit(None)),
                when(col("is_high_revert_rate"), lit("HIGH_REVERT")).otherwise(lit(None)),
                when(col("is_anonymous_surge"), lit("ANON_SURGE")).otherwise(lit(None)),
                when(col("is_large_content_change"), lit("LARGE_CHANGE")).otherwise(lit(None))
            )
        ) \
        .withColumn(
            # Is this an anomaly at all?
            "is_anomaly",
            col("is_burst_activity") | col("is_high_revert_rate") | 
            col("is_anonymous_surge") | col("is_large_content_change")
        ) \
        .withColumn(
            # ============================================
            # RISK SCORE (0-100) - Now with deviation weighting
            # Higher deviation = higher risk
            # ============================================
            "risk_score",
            (
                # Burst component: up to 25 points based on z-score
                when(col("events_zscore") > 3, lit(25))
                    .when(col("events_zscore") > 2, lit(15))
                    .when(col("events_zscore") > 1, lit(5))
                    .otherwise(lit(0)) +
                # Revert component: up to 30 points based on deviation
                when(col("revert_ratio") > 0.5, lit(30))
                    .when(col("revert_ratio") > 0.3, lit(20))
                    .when(col("revert_ratio") > 0.2, lit(10))
                    .otherwise(lit(0)) +
                # Anonymous component: up to 25 points
                when(col("anonymous_ratio") > 0.7, lit(25))
                    .when(col("anonymous_ratio") > 0.5, lit(15))
                    .when(col("anonymous_ratio") > 0.35, lit(5))
                    .otherwise(lit(0)) +
                # Large content component: up to 15 points
                when(col("is_large_content_change"), lit(15)).otherwise(lit(0)) +
                # Quality component: up to 5 points
                when(col("quality_ratio") < 0.9, lit(5)).otherwise(lit(0))
            )
        ) \
        .withColumn(
            # ============================================
            # SEVERITY LEVEL - Clear categorization
            # ============================================
            "severity",
            when(col("risk_score") >= 50, lit("CRITICAL"))
                .when(col("risk_score") >= 30, lit("HIGH"))
                .when(col("risk_score") >= 15, lit("MEDIUM"))
                .when(col("risk_score") > 0, lit("LOW"))
                .otherwise(lit("NORMAL"))
        ) \
        .withColumn(
            # ============================================
            # ANOMALY EXPLANATION - Human readable context
            # ============================================
            "anomaly_explanation",
            when(~col("is_anomaly"), lit("Normal activity"))
                .otherwise(
                    concat_ws(" | ",
                        when(col("is_burst_activity"), 
                             expr("concat('Events: ', cast(total_events as string), ' (', round(events_zscore, 1), 'σ above normal)')"))
                            .otherwise(lit(None)),
                        when(col("is_high_revert_rate"),
                             expr("concat('Revert rate: ', round(revert_ratio * 100, 1), '% (baseline: ', round(baseline_revert_ratio * 100, 1), '%)')"))
                            .otherwise(lit(None)),
                        when(col("is_anonymous_surge"),
                             expr("concat('Anonymous: ', round(anonymous_ratio * 100, 1), '% (baseline: ', round(baseline_anonymous_ratio * 100, 1), '%)')"))
                            .otherwise(lit(None)),
                        when(col("is_large_content_change"),
                             expr("concat('Content change: ', round(abs(total_bytes_changed) / 1024, 1), 'KB')"))
                            .otherwise(lit(None))
                    )
                )
        ) \
        .withColumn("aggregation_timestamp", current_timestamp()) \
        .withColumn("event_date", to_date(col("window_start")))
    
    logger.info("Entity metrics computed with enhanced anomaly detection")
    return entity_metrics


def compute_user_metrics_10min(df):
    """
    Compute 10-minute aggregations per user
    For detecting suspicious user behavior patterns
    
    ENHANCED: Statistical anomaly detection with baselines
    """
    logger.info("Computing 10-minute user metrics with anomaly detection")
    
    user_metrics = df \
        .withWatermark("ingestion_timestamp", "10 minutes") \
        .groupBy(
            window(col("ingestion_timestamp"), "10 minutes"),
            col("user_name"),
            col("is_bot"),
            col("is_anonymous")
        ).agg(
            # Activity volume
            count("*").alias("total_events"),
            sum_col(when(col("event_type") == "edit", 1).otherwise(0)).alias("edit_count"),
            sum_col(when(col("event_type") == "new", 1).otherwise(0)).alias("new_page_count"),
            
            # Revert behavior
            sum_col(when(col("is_revert") == True, 1).otherwise(0)).alias("revert_count"),
            
            # Content changes
            sum_col(coalesce(col("bytes_changed"), lit(0))).alias("total_bytes_changed"),
            avg(coalesce(col("bytes_changed"), lit(0))).alias("avg_bytes_changed"),
            
            # Large edits
            sum_col(when(col("is_large_edit") == True, 1).otherwise(0)).alias("large_edit_count"),
            
            # Entities touched
            approx_count_distinct(coalesce(col("canonical_entity"), col("title"))).alias("entities_edited"),
            approx_count_distinct("wiki").alias("wikis_touched"),
            
            # Quality - all silver records passed validation  
            lit(0).alias("quality_failed_count"),  # Failed records quarantined in silver layer
            
            # Comment behavior
            sum_col(when(col("has_comment") == True, 1).otherwise(0)).alias("edits_with_comment")
        ) \
        .withColumn("window_start", col("window.start")) \
        .withColumn("window_end", col("window.end")) \
        .drop("window") \
        .withColumn(
            # Derived: Revert ratio
            "revert_ratio",
            when(col("edit_count") > 0, 
                 col("revert_count") / col("edit_count")
            ).otherwise(lit(0.0))
        ) \
        .withColumn(
            # ============================================
            # BASELINE THRESHOLDS FOR USERS
            # ============================================
            "baseline_edits_avg", lit(2.0)  # Typical user: ~2 edits/10min
        ) \
        .withColumn("baseline_edits_stddev", lit(1.5)) \
        .withColumn("baseline_entities_avg", lit(1.5)) \
        .withColumn("baseline_revert_ratio", lit(0.10)) \
        .withColumn(
            # ============================================
            # STATISTICAL DEVIATION
            # ============================================
            "edits_zscore",
            (col("edit_count") - col("baseline_edits_avg")) / col("baseline_edits_stddev")
        ) \
        .withColumn(
            "entities_zscore",
            (col("entities_edited") - col("baseline_entities_avg")) / lit(1.0)
        ) \
        .withColumn(
            # ============================================
            # ANOMALY FLAGS - Statistically backed
            # ============================================
            # ANOMALY: New user blitz (high activity + multiple entities)
            "is_new_user_blitz",
            (col("edits_zscore") > 2.0) & (col("entities_edited") > 3)
        ) \
        .withColumn(
            # ANOMALY: Mass reverter (>3 reverts in 10min)
            "is_mass_reverter",
            col("revert_count") > 3
        ) \
        .withColumn(
            # ANOMALY: Cross-wiki activity (suspicious if touching many wikis)
            "is_cross_wiki_active",
            col("wikis_touched") > 2
        ) \
        .withColumn(
            # ANOMALY: High personal revert ratio
            "is_high_revert_user",
            col("revert_ratio") > (col("baseline_revert_ratio") * 3)
        ) \
        .withColumn(
            # Anomaly types combined
            "anomaly_types",
            concat_ws(", ",
                when(col("is_new_user_blitz"), lit("BLITZ")).otherwise(lit(None)),
                when(col("is_mass_reverter"), lit("MASS_REVERT")).otherwise(lit(None)),
                when(col("is_cross_wiki_active"), lit("CROSS_WIKI")).otherwise(lit(None)),
                when(col("is_high_revert_user"), lit("HIGH_REVERT")).otherwise(lit(None))
            )
        ) \
        .withColumn(
            # Is this user anomalous?
            "is_anomaly",
            col("is_new_user_blitz") | col("is_mass_reverter") | 
            col("is_cross_wiki_active") | col("is_high_revert_user")
        ) \
        .withColumn(
            # User risk score (0-100) - Enhanced
            "user_risk_score",
            (
                # Blitz behavior: up to 35 points
                when(col("edits_zscore") > 4, lit(35))
                    .when(col("is_new_user_blitz"), lit(25))
                    .when(col("edits_zscore") > 2, lit(10))
                    .otherwise(lit(0)) +
                # Mass reverter: up to 30 points
                when(col("revert_count") > 5, lit(30))
                    .when(col("is_mass_reverter"), lit(20))
                    .otherwise(lit(0)) +
                # Cross-wiki: up to 15 points
                when(col("wikis_touched") > 3, lit(15))
                    .when(col("is_cross_wiki_active"), lit(10))
                    .otherwise(lit(0)) +
                # High personal revert: up to 20 points
                when(col("revert_ratio") > 0.5, lit(20))
                    .when(col("revert_ratio") > 0.3, lit(10))
                    .otherwise(lit(0))
            )
        ) \
        .withColumn(
            # Severity level
            "severity",
            when(col("user_risk_score") >= 50, lit("CRITICAL"))
                .when(col("user_risk_score") >= 30, lit("HIGH"))
                .when(col("user_risk_score") >= 15, lit("MEDIUM"))
                .when(col("user_risk_score") > 0, lit("LOW"))
                .otherwise(lit("NORMAL"))
        ) \
        .withColumn(
            # User type for dashboard
            "user_type",
            when(col("is_bot"), lit("Bot"))
                .when(col("is_anonymous"), lit("Anonymous"))
                .otherwise(lit("Registered"))
        ) \
        .withColumn(
            # Anomaly explanation
            "anomaly_explanation",
            when(~col("is_anomaly"), lit("Normal activity"))
                .otherwise(
                    concat_ws(" | ",
                        when(col("is_new_user_blitz"),
                             expr("concat('Edits: ', cast(edit_count as string), ' across ', cast(entities_edited as string), ' entities (', round(edits_zscore, 1), 'σ)')"))
                            .otherwise(lit(None)),
                        when(col("is_mass_reverter"),
                             expr("concat('Reverts: ', cast(revert_count as string), ' in 10min')"))
                            .otherwise(lit(None)),
                        when(col("is_cross_wiki_active"),
                             expr("concat('Cross-wiki: ', cast(wikis_touched as string), ' wikis')"))
                            .otherwise(lit(None)),
                        when(col("is_high_revert_user"),
                             expr("concat('Revert ratio: ', round(revert_ratio * 100, 1), '%')"))
                            .otherwise(lit(None))
                    )
                )
        ) \
        .withColumn("aggregation_timestamp", current_timestamp()) \
        .withColumn("event_date", to_date(col("window_start")))
    
    logger.info("User metrics computed with enhanced anomaly detection")
    return user_metrics


def compute_global_metrics_10min(df):
    """
    Compute 10-minute global aggregations across all entities
    For system-wide anomaly detection and dashboard overview
    
    ENHANCED: Platform health indicators and anomaly counts
    """
    logger.info("Computing 10-minute global metrics with health indicators")
    
    global_metrics = df \
        .withWatermark("ingestion_timestamp", "10 minutes") \
        .groupBy(
            window(col("ingestion_timestamp"), "10 minutes")
        ).agg(
            # Overall volume
            count("*").alias("total_events"),
            sum_col(when(col("event_type") == "edit", 1).otherwise(0)).alias("total_edits"),
            sum_col(when(col("event_type") == "new", 1).otherwise(0)).alias("total_new_pages"),
            sum_col(when(col("event_type") == "categorize", 1).otherwise(0)).alias("total_categorize"),
            sum_col(when(col("event_type") == "log", 1).otherwise(0)).alias("total_log"),
            
            # Risk indicators
            sum_col(when(col("is_revert") == True, 1).otherwise(0)).alias("total_reverts"),
            sum_col(when(col("is_anonymous") == True, 1).otherwise(0)).alias("total_anonymous"),
            sum_col(when(col("is_bot") == True, 1).otherwise(0)).alias("total_bot"),
            sum_col(when(col("is_large_edit") == True, 1).otherwise(0)).alias("total_large_edits"),
            
            # Content
            sum_col(coalesce(col("bytes_changed"), lit(0))).alias("total_bytes_changed"),
            avg(coalesce(col("bytes_changed"), lit(0))).alias("avg_bytes_changed"),
            
            # Quality - all silver records passed validation
            lit(0).alias("total_quality_failed"),  # Failed records handled in silver layer
            
            # Diversity
            approx_count_distinct("user_name").alias("unique_users"),
            approx_count_distinct(coalesce(col("canonical_entity"), col("title"))).alias("unique_entities"),
            approx_count_distinct("wiki").alias("unique_wikis"),
            
            # Latency
            avg(col("processing_lag_seconds")).alias("avg_processing_lag"),
            max_col(col("processing_lag_seconds")).alias("max_processing_lag")
        ) \
        .withColumn("window_start", col("window.start")) \
        .withColumn("window_end", col("window.end")) \
        .drop("window") \
        .withColumn(
            "revert_ratio",
            when(col("total_edits") > 0, 
                 col("total_reverts") / col("total_edits")
            ).otherwise(lit(0.0))
        ) \
        .withColumn(
            "anonymous_ratio",
            when(col("total_events") > 0,
                 col("total_anonymous") / col("total_events")
            ).otherwise(lit(0.0))
        ) \
        .withColumn(
            "bot_ratio",
            when(col("total_events") > 0,
                 col("total_bot") / col("total_events")
            ).otherwise(lit(0.0))
        ) \
        .withColumn(
            # ============================================
            # GLOBAL BASELINES (Wikipedia platform norms)
            # ============================================
            "baseline_events_avg", lit(150.0)  # ~150 events/10min globally
        ) \
        .withColumn("baseline_events_stddev", lit(50.0)) \
        .withColumn("baseline_revert_ratio", lit(0.12)) \
        .withColumn("baseline_anonymous_ratio", lit(0.25)) \
        .withColumn(
            # ============================================
            # PLATFORM HEALTH METRICS
            # ============================================
            "events_zscore",
            (col("total_events") - col("baseline_events_avg")) / col("baseline_events_stddev")
        ) \
        .withColumn(
            "revert_deviation",
            col("revert_ratio") - col("baseline_revert_ratio")
        ) \
        .withColumn(
            "anonymous_deviation", 
            col("anonymous_ratio") - col("baseline_anonymous_ratio")
        ) \
        .withColumn(
            # ============================================
            # PLATFORM HEALTH STATUS
            # ============================================
            "platform_health",
            when(
                (col("revert_ratio") > 0.25) | (col("events_zscore") > 3),
                lit("CRITICAL")
            ).when(
                (col("revert_ratio") > 0.18) | (col("events_zscore") > 2),
                lit("WARNING")
            ).when(
                (col("revert_ratio") > 0.15) | (col("events_zscore") > 1),
                lit("ELEVATED")
            ).otherwise(lit("HEALTHY"))
        ) \
        .withColumn(
            # Events per user (engagement metric)
            "events_per_user",
            when(col("unique_users") > 0,
                 col("total_events") / col("unique_users")
            ).otherwise(lit(0.0))
        ) \
        .withColumn(
            # Events per entity (activity concentration)
            "events_per_entity",
            when(col("unique_entities") > 0,
                 col("total_events") / col("unique_entities")
            ).otherwise(lit(0.0))
        ) \
        .withColumn(
            # Health score (0-100, higher = healthier)
            "health_score",
            lit(100) - (
                # Deduct for high revert ratio
                when(col("revert_ratio") > 0.25, lit(30))
                    .when(col("revert_ratio") > 0.18, lit(20))
                    .when(col("revert_ratio") > 0.12, lit(10))
                    .otherwise(lit(0)) +
                # Deduct for abnormal volume
                when(abs_col(col("events_zscore")) > 3, lit(25))
                    .when(abs_col(col("events_zscore")) > 2, lit(15))
                    .when(abs_col(col("events_zscore")) > 1, lit(5))
                    .otherwise(lit(0)) +
                # Deduct for high anonymous ratio
                when(col("anonymous_ratio") > 0.5, lit(20))
                    .when(col("anonymous_ratio") > 0.35, lit(10))
                    .otherwise(lit(0)) +
                # Deduct for processing lag
                when(col("avg_processing_lag") > 300, lit(15))
                    .when(col("avg_processing_lag") > 120, lit(5))
                    .otherwise(lit(0))
            )
        ) \
        .withColumn(
            # Health explanation
            "health_explanation",
            when(col("platform_health") == "HEALTHY", lit("All metrics within normal range"))
                .otherwise(
                    concat_ws(" | ",
                        when(col("revert_ratio") > 0.15,
                             expr("concat('Revert ratio: ', round(revert_ratio * 100, 1), '% (baseline: 12%)')"))
                            .otherwise(lit(None)),
                        when(abs_col(col("events_zscore")) > 1,
                             expr("concat('Volume: ', round(events_zscore, 1), 'σ from normal')"))
                            .otherwise(lit(None)),
                        when(col("anonymous_ratio") > 0.35,
                             expr("concat('Anonymous: ', round(anonymous_ratio * 100, 1), '%')"))
                            .otherwise(lit(None))
                    )
                )
        ) \
        .withColumn("aggregation_timestamp", current_timestamp()) \
        .withColumn("event_date", to_date(col("window_start")))
    
    logger.info("Global metrics computed with health indicators")
    return global_metrics


def create_gold_tables(spark, s3_bucket, glue_database):
    """Create Gold Iceberg table locations - schema will be inferred from DataFrame"""
    
    # We don't pre-define columns - let Iceberg infer from DataFrame
    # This avoids nullability mismatch (required vs optional)
    
    tables = [
        ("gold_entity_metrics_10min", f"s3://{s3_bucket}/data/gold_entity_metrics_10min/"),
        ("gold_user_metrics_10min", f"s3://{s3_bucket}/data/gold_user_metrics_10min/"),
        ("gold_global_metrics_10min", f"s3://{s3_bucket}/data/gold_global_metrics_10min/"),
    ]
    
    for table_name, location in tables:
        # Check if table exists
        try:
            spark.sql(f"DESCRIBE TABLE glue_catalog.`{glue_database}`.{table_name}")
            logger.info(f"Table {table_name} already exists")
        except Exception:
            logger.info(f"Table {table_name} will be created on first write at {location}")


def create_gold_batch_processor(spark, table_name, glue_database, s3_bucket, s3_path,
                                 alert_manager=None, metric_type="entity"):
    """Create a batch processor with lightweight quality validation for gold aggregations"""
    
    # For gold, we do lightweight validation on aggregation results
    # Gold quality gate checks: entity not null, wiki not null, counts non-negative
    quality_gate = GoldQualityGate(
        spark=spark,
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        alert_manager=alert_manager
    ) if QUALITY_MODULE_AVAILABLE else None
    
    def process_batch(batch_df, batch_id):
        """Process each micro-batch with lightweight quality check"""
        # Fast empty check
        if len(batch_df.take(1)) == 0:
            logger.info(f"Batch {batch_id} ({metric_type}): Empty batch, skipping")
            return
        
        logger.info(f"Batch {batch_id} ({metric_type}): Processing batch...")
        
        if quality_gate:
            # Lightweight quality check for aggregations
            # skip_pydeequ=True for faster processing - SQL flags are sufficient
            passed_df, failed_df, metrics = quality_gate.validate_and_filter(
                df=batch_df,
                batch_id=f"gold_{metric_type}_{batch_id}",
                skip_pydeequ=True
            )
            
            # Use counts from metrics - already computed in validate_and_filter
            passed_count = metrics.get("passed_count", 0)
            failed_count = metrics.get("failed_count", 0)
            logger.info(f"Batch {batch_id} ({metric_type}): {passed_count + failed_count} aggregations ({passed_count} passed, {failed_count} failed)")
            
            # Cache passed_df before write to avoid recomputation
            if passed_count > 0:
                passed_df.cache()
            if failed_count > 0:
                failed_df.cache()
            
            # Write passed records to gold table
            if passed_count > 0:
                # Remove quality flag column before writing
                clean_df = passed_df.drop("is_quality_passed")
                
                try:
                    # Try append first, create table if it doesn't exist
                    clean_df.writeTo(table_name).option("fanout-enabled", "true").append()
                    logger.info(f"Batch {batch_id} ({metric_type}): Successfully wrote {passed_count} aggregations")
                except Exception as e:
                    if "TABLE_OR_VIEW_NOT_FOUND" in str(e) or "cannot be found" in str(e):
                        # Table doesn't exist - create it with schema inferred from DataFrame
                        logger.info(f"Batch {batch_id} ({metric_type}): Creating table {table_name} at {s3_path}")
                        clean_df.writeTo(table_name).using("iceberg").tableProperty("location", s3_path).partitionedBy("event_date").create()
                        logger.info(f"Batch {batch_id} ({metric_type}): Created table and wrote {passed_count} aggregations")
                    else:
                        logger.error(f"Batch {batch_id} ({metric_type}): Failed to write passed aggregations: {e}")
                        raise Exception(f"Gold table write failed: {e}")
            
            # Write failed records to quarantine (quality gate's responsibility was only to identify them)
            if failed_count > 0:
                failed_checks = metrics.get("failed_checks", [])
                try:
                    quality_gate.quarantine_writer.write_to_quarantine(
                        failed_df=failed_df,
                        layer="gold",
                        batch_id=f"gold_{metric_type}_{batch_id}",
                        failed_checks=failed_checks
                    )
                    logger.warning(f"Batch {batch_id} ({metric_type}): Quarantined {failed_count} aggregations due to quality failures")
                except Exception as e:
                    logger.error(f"Batch {batch_id} ({metric_type}): Failed to quarantine failed aggregations: {e}")
                    raise Exception(f"Quarantine write failed: {e}")
            
            # Release caches
            if passed_count > 0:
                passed_df.unpersist()
            if failed_count > 0:
                failed_df.unpersist()
            
            logger.info(f"Batch {batch_id} ({metric_type}): Complete - pass_rate={metrics.get('pass_rate', 1.0):.2%}")
        else:
            # No quality gate - write all records directly
            batch_df.cache()
            record_count = batch_df.count()
            try:
                batch_df.writeTo(table_name).option("fanout-enabled", "true").append()
                logger.info(f"Batch {batch_id} ({metric_type}): Wrote {record_count} aggregations (no DQ)")
            except Exception as e:
                if "TABLE_OR_VIEW_NOT_FOUND" in str(e) or "cannot be found" in str(e):
                    # Table doesn't exist - create it
                    logger.info(f"Batch {batch_id} ({metric_type}): Creating table {table_name} at {s3_path}")
                    batch_df.writeTo(table_name).using("iceberg").tableProperty("location", s3_path).partitionedBy("event_date").create()
                    logger.info(f"Batch {batch_id} ({metric_type}): Created table and wrote {record_count} aggregations")
                else:
                    logger.error(f"Batch {batch_id} ({metric_type}): Failed to write aggregations: {e}")
                    raise Exception(f"Gold write failed: {e}")
            batch_df.unpersist()
    
    return process_batch


def write_to_iceberg(df, table_name, s3_path, checkpoint_location, trigger_interval="10 minutes",
                     glue_database=None, s3_bucket=None, alert_manager=None, metric_type="entity"):
    """Write streaming aggregations to Iceberg table with lightweight quality validation
    """
    spark = df.sparkSession
    logger.info(f"Writing to Iceberg table with quality gate: {table_name} at {s3_path}")
    
    # Create batch processor with lightweight quality check
    batch_processor = create_gold_batch_processor(
        spark=spark,
        table_name=table_name,
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        s3_path=s3_path,
        alert_manager=alert_manager,
        metric_type=metric_type
    )
    
    query = df.writeStream \
        .foreachBatch(batch_processor) \
        .trigger(processingTime=trigger_interval) \
        .option("checkpointLocation", checkpoint_location) \
        .start()
    
    logger.info(f"Streaming query with quality gate started: {checkpoint_location}")
    return query


def main():
    """Main entry point for Gold layer Spark job"""
    
    if len(sys.argv) < 3:
        logger.error("Usage: gold_writer.py <s3_bucket> <glue_database>")
        sys.exit(1)
    
    s3_bucket = sys.argv[1]
    glue_database = sys.argv[2]
    
    logger.info(f"Starting Gold Writer (10-min aggregations)")
    logger.info(f"S3 Bucket: {s3_bucket}")
    logger.info(f"Glue Database: {glue_database}")
    
    spark = get_spark_session()
    
    # Create Gold tables
    create_gold_tables(spark, s3_bucket, glue_database)
    
    # Read from Silver
    silver_df = read_from_silver(spark, glue_database)
    
    # Compute aggregations
    entity_metrics = compute_entity_metrics_10min(silver_df)
    user_metrics = compute_user_metrics_10min(silver_df)
    global_metrics = compute_global_metrics_10min(silver_df)
    
    # Initialize alert manager for quality gate
    alert_manager = None
    if QUALITY_MODULE_AVAILABLE:
        logger.info("Initializing alert manager for gold quality gate...")
        alert_manager = AlertManager(
            sns_topic_arn=os.getenv("SNS_TOPIC_ARN"),
            slack_channel=os.getenv("SLACK_CHANNEL", "#data-quality"),
            slack_token=os.getenv("SLACK_BOT_TOKEN")
        )
    
    # Write to Gold tables with explicit S3 paths under /data/
    entity_query = write_to_iceberg(
        df=entity_metrics,
        table_name=f"glue_catalog.`{glue_database}`.gold_entity_metrics_10min",
        s3_path=f"s3://{s3_bucket}/data/gold_entity_metrics_10min/",
        checkpoint_location=f"s3://{s3_bucket}/checkpoints/gold_entity_metrics_10min/",
        trigger_interval="10 minutes",
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        alert_manager=alert_manager,
        metric_type="entity"
    )
    
    user_query = write_to_iceberg(
        df=user_metrics,
        table_name=f"glue_catalog.`{glue_database}`.gold_user_metrics_10min",
        s3_path=f"s3://{s3_bucket}/data/gold_user_metrics_10min/",
        checkpoint_location=f"s3://{s3_bucket}/checkpoints/gold_user_metrics_10min/",
        trigger_interval="10 minutes",
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        alert_manager=alert_manager,
        metric_type="user"
    )
    
    global_query = write_to_iceberg(
        df=global_metrics,
        table_name=f"glue_catalog.`{glue_database}`.gold_global_metrics_10min",
        s3_path=f"s3://{s3_bucket}/data/gold_global_metrics_10min/",
        checkpoint_location=f"s3://{s3_bucket}/checkpoints/gold_global_metrics_10min/",
        trigger_interval="10 minutes",
        glue_database=glue_database,
        s3_bucket=s3_bucket,
        alert_manager=alert_manager,
        metric_type="global"
    )
    
    # Monitor streaming queries
    logger.info("Gold writer is running. Monitoring query progress...")
    
    queries = [entity_query, user_query, global_query]
    query_names = ["Entity", "User", "Global"]
    
    # Run indefinitely - this is a streaming job
    try:
        spark.streams.awaitAnyTermination()
    except Exception as e:
        logger.error(f"Streaming query failed: {e}")
        raise
    
    # Check for failures
    for name, query in zip(query_names, queries):
        if query.exception():
            logger.error(f"{name} query failed: {query.exception()}")
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
