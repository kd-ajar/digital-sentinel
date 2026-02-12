┌─────────────────────────────────────────────────────────────────────┐
│                         CALLER (e.g., silver_writer)                │
│                                                                     │
│   quality_gate.validate_and_filter(batch_df, batch_id, skip=True)   │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  1. SETUP                                                           │
│     • Generate batch_id if not provided                             │
│     • Create quarantine table (Iceberg) if not exists               │
│     • Initialize metrics dict                                       │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. PYDEEQU CHECKS (Optional - skipped if skip_pydeequ=True)        │
│     • Build Check object with constraints (isComplete, isPositive)  │
│     • Run VerificationSuite on DataFrame                            │
│     • Collect constraint results (Success/Failure)                  │
│     • Store failed check names in failed_checks list                │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  3. ADD QUALITY FLAGS (SQL-based row-level validation)              │
│     • Call add_quality_flags(df) - layer-specific implementation    │
│     • Adds column: is_quality_passed (Boolean)                      │
│     • Silver also adds: has_schema_violations, is_valid_type,       │
│                         is_fresh, is_temporal_valid                 │
│     → Returns df_with_flags (lazy DataFrame)                        │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  4. SPLIT INTO PASSED / FAILED                                      │
│     • passed_df = filter(is_quality_passed == True)  [lazy]         │
│     • failed_df = filter(is_quality_passed == False) [lazy]         │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  5. COUNT (Single Spark Action)                                     │
│     • groupBy("is_quality_passed").count().collect()                │
│     • Extract passed_count and failed_count from result             │
│     • Calculate pass_rate = passed / total                          │
│     → This is the ONLY materialization in validate_and_filter       │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  6. DETERMINE SEVERITY                                              │
│     • CRITICAL: pass_rate < 80% OR critical checks failed           │
│     • WARNING: pass_rate < 95%                                      │
│     • SUCCESS: pass_rate >= 95%                                     │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  7. SEND ALERTS (if CRITICAL or WARNING)                            │
│     • CRITICAL → SNS + Slack                                        │
│     • WARNING → Slack only                                          │
│     • SUCCESS → Log only                                            │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  8. RETURN TO CALLER                                                │
│                                                                     │
│     return (passed_df, failed_df, metrics)                          │
│                                                                     │
│     • passed_df: lazy, not yet cached                               │
│     • failed_df: lazy, not yet cached                               │
│     • metrics: dict with counts, pass_rate, failed_checks           │
└─────────────────────────────────────────────────────────────────────┘



class StreamingQualityProcessor:
    """Deprecated - use layer-specific QualityGate classes"""
    def __init__(self, spark, s3_bucket, layer="silver", enable_cloudwatch=False):
        logger.warning("StreamingQualityProcessor is deprecated")
        self.spark = spark
        self.s3_bucket = s3_bucket
        self.layer = layer
    
    def process_batch(self, df, batch_id):
        logger.warning("Legacy process_batch called - no action")
        return {}
