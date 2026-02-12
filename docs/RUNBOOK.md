,# WikiGuard Operations Runbook

> **Last Updated**: February 2026  
> **Maintainers**: Platform Engineering Team  
> **On-Call Escalation**: #wikiguard-alerts Slack channel

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Component Reference](#component-reference)
- [Standard Operations](#standard-operations)
  - [Deploy](#1-deploy)
  - [Restart](#2-restart)
  - [Stop](#3-stop)
- [Data Recovery Operations](#data-recovery-operations)
  - [Replay](#4-replay)
  - [Backfill](#5-backfill)
- [Troubleshooting](#troubleshooting)
- [Monitoring & Alerting](#monitoring--alerting)
- [Emergency Procedures](#emergency-procedures)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           WikiGuard Streaming Pipeline                                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │   WIKIMEDIA      │
    │  EventStreams    │
    │    (SSE API)     │
    └────────┬─────────┘
             │ Server-Sent Events
             ▼
┌────────────────────────┐        ┌─────────────────────────────────────────────────────┐
│     ECS FARGATE        │        │                   AMAZON MSK                         │
│  ┌──────────────────┐  │        │  ┌─────────────────────────────────────────────┐    │
│  │ sse_consumer.py  │  │  TLS   │  │              cleaned_events                 │    │
│  │                  │──┼────────┼──│  (filtered by entity-allowlist.yaml)        │    │
│  │ - Entity Filter  │  │        │  │  - Retention: 7 days                        │    │
│  │ - Kafka Producer │  │        │  │  - Partitions: Based on wiki                │    │
│  └──────────────────┘  │        │  └─────────────────────────────────────────────┘    │
└────────────────────────┘        └──────────────────────┬──────────────────────────────┘
                                                         │
                         ┌───────────────────────────────┴────────────────────────────┐
                         │                  EMR SERVERLESS                             │
                         │     (Spark Structured Streaming - Medallion Architecture)   │
                         │                                                             │
┌────────────────────────┴─────────────────────────────────────────────────────────────┴──┐
│                                                                                          │
│  ┌────────────────────┐    ┌────────────────────┐    ┌────────────────────┐             │
│  │   BRONZE APP       │    │    SILVER APP      │    │     GOLD APP       │             │
│  │ ┌────────────────┐ │    │ ┌────────────────┐ │    │ ┌────────────────┐ │             │
│  │ │bronze_writer.py│ │    │ │silver_writer.py│ │    │ │ gold_writer.py │ │             │
│  │ └───────┬────────┘ │    │ └───────┬────────┘ │    │ └───────┬────────┘ │             │
│  │         │          │    │         │          │    │         │          │             │
│  │ Trigger: 2 min     │    │ Trigger: 10 min    │    │ Trigger: 10 min    │             │
│  │ Kafka → Iceberg    │    │ Dedupe, Enrich     │    │ Aggregate Metrics  │             │
│  └─────────┼──────────┘    └─────────┼──────────┘    └─────────┼──────────┘             │
│            │                         │                         │                        │
│            │    ┌────────────────────┴─────────────────────────┘                        │
│            │    │                                                                       │
│            ▼    ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │                         DATA QUALITY GATE                                        │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │   │
│  │  │   PyDeequ   │  │  SQL Checks │  │   Metrics   │  │     Alert Manager       │ │   │
│  │  │ Constraints │  │  Freshness  │  │  Pass Rate  │  │  SNS (Critical)         │ │   │
│  │  │ Statistical │  │  Validity   │  │  Batch ID   │  │  Slack (Warning)        │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────────┘ │   │
│  └───────────────────────────────────┬─────────────────────────────────────────────┘   │
│                                      │                                                  │
│                          ┌───────────┴───────────┐                                      │
│                          ▼                       ▼                                      │
│                   ┌────────────┐          ┌──────────────┐                              │
│                   │   PASSED   │          │  QUARANTINE  │                              │
│                   └────────────┘          └──────────────┘                              │
└──────────────────────────┼───────────────────────┼──────────────────────────────────────┘
                           │                       │
                           ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              AMAZON S3 LAKEHOUSE                                         │
│                          (Apache Iceberg + Parquet)                                      │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐    │
│  │                           MEDALLION LAYERS                                       │    │
│  │                                                                                  │    │
│  │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐ │    │
│  │   │     BRONZE      │  │     SILVER      │  │            GOLD                 │ │    │
│  │   │                 │  │                 │  │                                 │ │    │
│  │   │ bronze_events   │  │ silver_events   │  │ gold_entity_metrics_10min      │ │    │
│  │   │ (raw JSON)      │  │ (parsed,dedupe) │  │ gold_user_metrics_10min        │ │    │
│  │   │                 │  │                 │  │ gold_global_metrics_10min      │ │    │
│  │   │ Partition:      │  │ Partition:      │  │                                 │ │    │
│  │   │  event_date     │  │  event_date     │  │ Partition: metric_date         │ │    │
│  │   └─────────────────┘  └─────────────────┘  └─────────────────────────────────┘ │    │
│  │                                                                                  │    │
│  │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐ │    │
│  │   │ QUARANTINE      │  │ QUARANTINE      │  │ QUARANTINE                      │ │    │
│  │   │ bronze_         │  │ silver_         │  │ gold_quarantine                 │ │    │
│  │   │ quarantine      │  │ quarantine      │  │                                 │ │    │
│  │   └─────────────────┘  └─────────────────┘  └─────────────────────────────────┘ │    │
│  └─────────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐    │
│  │                          SUPPORTING PATHS                                        │    │
│  │  📁 /scripts/           - PySpark scripts                                       │    │
│  │  📁 /checkpoints/       - Spark Structured Streaming checkpoints                │    │
│  │  📁 /emr-serverless-logs/ - Spark driver/executor logs                          │    │
│  └─────────────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────┬──────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                            AWS GLUE DATA CATALOG                                         │
│                                                                                          │
│  Database: wikiguard_lakehouse                                                           │
│  Tables: bronze_events, silver_events, gold_*_metrics, *_quarantine                     │
│  Format: Apache Iceberg (ACID, Time Travel, Schema Evolution)                           │
└──────────────────────────────────┬──────────────────────────────────────────────────────┘
                                   │
                         ┌─────────┴─────────┐
                         ▼                   ▼
              ┌──────────────────┐  ┌──────────────────┐
              │  AMAZON ATHENA   │  │ AMAZON QUICKSIGHT│
              │                  │  │                  │
              │  SQL Queries     │  │  Dashboards      │
              │  Ad-hoc Analysis │  │  Visualizations  │
              └──────────────────┘  └──────────────────┘
```

### Data Flow Summary

| Stage | Source | Destination | Trigger |
|-------|--------|-------------|---------|
| **Ingest** | Wikimedia SSE | MSK `cleaned_events` | Real-time | 
| **Bronze** | MSK Kafka | `bronze_events` Iceberg | 2 min micro-batch | 
| **Silver** | `bronze_events` | `silver_events` Iceberg | 10 min micro-batch | 
| **Gold** | `silver_events` | `gold_*_metrics` Iceberg | 10 min micro-batch | 

---

## Component Reference

### Infrastructure Components

| Component | AWS Service | Configuration | Notes |
|-----------|-------------|---------------|-------|
| **Ingest Service** | ECS Fargate | 0.25 vCPU, 0.5 GB | Single task, auto-restart |
| **Message Queue** | Amazon MSK | 2× kafka.t3.small | TLS, 7-day retention |
| **Bronze Processing** | EMR Serverless | 1 vCPU, 2 GB | Streaming, always-on |
| **Silver Processing** | EMR Serverless | 2 vCPU, 6 GB | Streaming, quality gates |
| **Gold Processing** | EMR Serverless | 1 vCPU, 2 GB | Streaming, aggregations |
| **Storage** | S3 + Iceberg | Standard tier | Partitioned by date |
| **Catalog** | Glue Data Catalog | - | Schema registry |
| **Alerts** | SNS + Slack | - | Critical → SNS, Warning → Slack |

---

## Standard Operations

### 1. Deploy

#### 1.1 Initial Deployment

**Prerequisites:**
- AWS CLI configured with appropriate IAM permissions
- Terraform >= 1.5.0 installed
- S3 bucket for Terraform state (bootstrap first)

**Step 1: Bootstrap Terraform Backend**

```bash
cd infrastructure/terraform/bootstrap
terraform init
terraform apply -auto-approve

```

**Step 2: Configure Variables**

```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars

# Edit terraform.tfvars with your values:
# - project_name
# - environment
# - notification_email
# - aws_region
```

**Step 3: Deploy Infrastructure**

```bash
terraform init
terraform plan -out=deploy.tfplan

# Review the plan carefully
terraform apply deploy.tfplan
```

**Step 4: Build and Push Docker Image**

```bash
cd scripts/ingest
./build_and_push_docker.sh
```

**Step 5: Start Pipeline**

```bash
cd scripts
./start_pipeline.sh
```

**Verification Checklist:**
- [ ] ECS service running: `aws ecs describe-services --cluster wikiguard-cluster --services wikiguard-ingest-service`
- [ ] EMR apps started: `./scripts/processing/serverless_monitor.sh`
- [ ] Data flowing to Bronze: Check Athena for `bronze_events`
- [ ] Alerts configured: Test SNS subscription

---

#### 1.2 Deploy Code Changes Only

When updating PySpark scripts without infrastructure changes:

```bash

# Restart EMR jobs to pick up changes
cd ../../scripts/processing
./serverless_cancel_all.sh
./serverless_submit_bronze.sh
./serverless_submit_silver.sh
./serverless_submit_gold.sh
```

---

#### 1.3 Deploy Entity Allowlist Changes

When adding/removing monitored Wikipedia entities:

```bash
# 1. Edit the allowlist
vim config/entity-allowlist.yaml

# 2. Restart ECS to pick up changes
aws ecs update-service \
  --cluster wikiguard-cluster \
  --service wikiguard-ingest-service \
  --force-new-deployment

# 3. Wait for new task to be running
aws ecs wait services-stable \
  --cluster wikiguard-cluster \
  --services wikiguard-ingest-service
```

> **Note**: Existing events in Kafka for removed entities will still be processed by Bronze/Silver/Gold. New events will be filtered at ingestion.

---

### 2. Restart

#### 2.1 Full Pipeline Restart

Use this when all components need to be restarted (e.g., after maintenance):

```bash
# Stop everything
./scripts/stop_pipeline.sh

# Wait for jobs to terminate (check status)
./scripts/processing/serverless_monitor.sh

# Start everything
./scripts/start_pipeline.sh
```

#### 2.2 Restart ECS Ingest Only

```bash
# Force new deployment (picks up latest Docker image and config)
aws ecs update-service \
  --cluster wikiguard-cluster \
  --service wikiguard-ingest-service \
  --force-new-deployment

# Or scale down and up
aws ecs update-service --cluster wikiguard-cluster --service wikiguard-ingest-service --desired-count 0
sleep 30
aws ecs update-service --cluster wikiguard-cluster --service wikiguard-ingest-service --desired-count 1
```

#### 2.3 Restart Individual EMR Job

```bash
cd scripts/processing

# Cancel specific job (get APP_ID from serverless_monitor.sh)
source emr_serverless_helpers.sh
get_terraform_outputs

# Submit new job
./serverless_submit_bronze.sh
```

#### 2.4 Recovery After Extended Downtime

⚠️ **Important**: After extended ECS downtime (hours/days), stale events will fail Silver quality checks.

```bash
# 1. Check Kafka lag
aws kafka describe-cluster --cluster-arn <MSK_ARN>

# 2. Start pipeline normally
./scripts/start_pipeline.sh

# 3. Monitor quarantine for expected stale event failures
# Silver quarantine will contain events with processing_lag > 3600s
```

Expected behavior:
- Bronze processes all backlogged Kafka messages
- Silver **quarantines** events older than 1 hour (freshness check fails)
- This is by design - prevents stale data from affecting analytics

---

### 3. Stop

#### 3.1 Graceful Shutdown (Recommended)

```bash
./scripts/stop_pipeline.sh
```

This script:
1. Stops ECS Ingest (scale to 0)
2. Cancels all EMR Serverless jobs
3. EMR applications remain in STARTED state (faster restart)

#### 3.2 Complete Shutdown (Cost Saving)

```bash
# Stop everything including EMR applications
./scripts/stop_pipeline.sh

# Also stop EMR applications (saves compute charges)
cd scripts/processing
source emr_serverless_helpers.sh
get_terraform_outputs

aws emr-serverless stop-application --application-id $BRONZE_APP_ID --region $AWS_REGION
aws emr-serverless stop-application --application-id $SILVER_APP_ID --region $AWS_REGION
aws emr-serverless stop-application --application-id $GOLD_APP_ID --region $AWS_REGION
```

> **Note**: Restarting after stopping EMR applications takes ~2-3 minutes longer.

---

## Data Recovery Operations

### 4. Replay

**Use Case**: Reprocess data from Kafka when Bronze processing failed or data was corrupted.

#### 4.1 Replay from Kafka Offset

Bronze reads from Kafka using Spark Structured Streaming checkpoints. To replay:

**Option A: Replay from Earliest (Full Reprocess)**

```bash
# 1. Delete Bronze checkpoint
cd infrastructure/terraform
S3_BUCKET=$(terraform output -raw s3_lakehouse_bucket)

aws s3 rm s3://$S3_BUCKET/checkpoints/bronze/ --recursive

# 2. Modify bronze_writer.py starting offset (temporary)
# Change: starting_offsets = "earliest"  # instead of "latest"

# 3. Restart Bronze job
cd ../../scripts/processing
./serverless_cancel_all.sh  # Cancel existing
./serverless_submit_bronze.sh

# 4. After replay completes, revert to "latest"
```

**Option B: Replay from Specific Offset**

```bash
# 1. Create JSON offset specification
OFFSETS='{"cleaned_events":{"0":1000,"1":1000}}'  # partition:offset pairs

# 2. Submit Bronze with specific offsets
# Edit serverless_submit_bronze.sh temporarily:
# SCRIPT_ARGS=("$MSK_BROKERS" "$S3_BUCKET" "$GLUE_DATABASE" "cleaned_events" "$OFFSETS")
```

#### 4.2 Replay Silver from Bronze

When Silver processing failed but Bronze is intact:

```bash
# 1. Delete Silver checkpoint
aws s3 rm s3://$S3_BUCKET/checkpoints/silver/ --recursive

# 2. Optionally truncate Silver table (Iceberg)
# Via Athena:
# DELETE FROM wikiguard_lakehouse.silver_events WHERE event_date >= '2026-02-01';

# 3. Restart Silver job
./scripts/processing/serverless_cancel_all.sh
./scripts/processing/serverless_submit_silver.sh
```

#### 4.3 Replay Gold from Silver

```bash
# 1. Delete Gold checkpoint
aws s3 rm s3://$S3_BUCKET/checkpoints/gold/ --recursive

# 2. Optionally truncate Gold tables
# DELETE FROM wikiguard_lakehouse.gold_entity_metrics_10min WHERE metric_date >= '2026-02-01';

# 3. Restart Gold job
./scripts/processing/serverless_submit_gold.sh
```

---

### 5. Backfill

**Use Case**: Populate historical data or recover from data loss.

#### 5.1 Backfill from Kafka (Within Retention)

MSK retains messages for 7 days by default. Backfill within this window:

```bash
# 1. Stop current processing
./scripts/stop_pipeline.sh

# 2. Clear all checkpoints
S3_BUCKET=$(terraform output -raw s3_lakehouse_bucket)
aws s3 rm s3://$S3_BUCKET/checkpoints/ --recursive

# 3. Start from earliest offset
# Temporarily modify bronze_writer.py:
#   starting_offsets = "earliest"

# 4. Start pipeline
./scripts/start_pipeline.sh

# 5. Monitor progress
./scripts/processing/serverless_monitor.sh

# 6. Once caught up, revert to "latest"
```

#### 5.2 Backfill from External Source (Beyond Retention)

For data older than Kafka retention, use batch Iceberg writes:

```bash
# 1. Prepare backfill data in S3
aws s3 cp backfill_data/ s3://$S3_BUCKET/backfill/ --recursive

# 2. Create a batch Spark job for backfill
# Example: backfill_bronze.py
```

**Sample Backfill Script** (`src/processing/backfill_bronze.py`):

```python
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

# Read historical data
backfill_df = spark.read.json("s3://bucket/backfill/")

# Transform to Bronze schema
bronze_df = backfill_df.select(
    col("id").alias("event_id"),
    to_json(struct("*")).alias("event_data"),
    lit("backfill").alias("kafka_topic"),
    lit(0).alias("kafka_partition"),
    lit(0).alias("kafka_offset"),
    current_timestamp().alias("ingestion_timestamp"),
    to_date(col("timestamp")).alias("event_date")
)

# Append to Bronze Iceberg table
bronze_df.writeTo("glue_catalog.wikiguard_lakehouse.bronze_events").append()
```

**Submit Backfill Job:**

```bash
aws emr-serverless start-job-run \
  --application-id $BRONZE_APP_ID \
  --execution-role-arn $EXECUTION_ROLE_ARN \
  --name "Bronze-Backfill" \
  --job-driver '{
    "sparkSubmit": {
      "entryPoint": "s3://bucket/scripts/backfill_bronze.py"
    }
  }'
```

#### 5.3 Backfill Using Iceberg Time Travel

Iceberg supports time travel to recover from accidental deletes:

```sql
-- View table history
SELECT * FROM wikiguard_lakehouse.bronze_events.history;

-- Rollback to specific snapshot
CALL glue_catalog.system.rollback_to_snapshot('wikiguard_lakehouse.bronze_events', 12345678901234);

-- Or query at specific time
SELECT * FROM wikiguard_lakehouse.bronze_events FOR TIMESTAMP AS OF timestamp '2026-02-01 00:00:00';
```

#### 5.4 Backfill Quarantined Data

After fixing data quality issues, reprocess quarantined records:

```bash
# 1. Export quarantine to staging
# Via Athena:
CREATE TABLE wikiguard_lakehouse.silver_quarantine_staging AS
SELECT * FROM wikiguard_lakehouse.silver_quarantine
WHERE event_date = '2026-02-07'
  AND quarantine_reason LIKE '%freshness%';

# 2. Create a script to re-parse and insert fixed records
# 3. Run batch job to insert into silver_events
# 4. Clean up quarantine staging
```

---

## Troubleshooting

### Common Issues

#### Issue: Bronze Job Stuck in PENDING

**Symptoms**: Job stays in PENDING/SUBMITTED state for > 5 minutes

**Cause**: Usually MSK connectivity issues or vCPU quota exceeded

**Resolution**:
```bash
# Check EMR app status
aws emr-serverless get-application --application-id $BRONZE_APP_ID

# Check job details for error
aws emr-serverless get-job-run --application-id $BRONZE_APP_ID --job-run-id <JOB_ID>

# Check if vCPU quota exceeded
aws service-quotas get-service-quota \
  --service-code emr-serverless \
  --quota-code L-2A8EEB2E
```

#### Issue: Silver Quality Gate Failing All Records

**Symptoms**: All Silver batches going to quarantine

**Cause**: Usually stale data after downtime (processing_lag > 3600s)

**Resolution**:
```sql
-- Check quarantine reason
SELECT quarantine_reason, failed_checks, COUNT(*) 
FROM wikiguard_lakehouse.silver_quarantine
WHERE event_date = current_date
GROUP BY 1, 2;

-- If freshness failures after downtime, this is expected
-- Wait for fresh data to start flowing
```

#### Issue: ECS Task Keeps Restarting

**Symptoms**: ECS task restarts every few minutes

**Cause**: Usually Kafka connection issues or entity filter errors

**Resolution**:
```bash
# Check ECS logs
aws logs get-log-events \
  --log-group-name /ecs/wikiguard-ingest \
  --log-stream-name $(aws logs describe-log-streams \
    --log-group-name /ecs/wikiguard-ingest \
    --order-by LastEventTime \
    --descending \
    --limit 1 \
    --query 'logStreams[0].logStreamName' \
    --output text)

# Verify entity allowlist syntax
python -c "import yaml; yaml.safe_load(open('config/entity-allowlist.yaml'))"
```

#### Issue: No Data in Gold Tables

**Symptoms**: Gold tables empty despite Silver having data

**Cause**: Gold job not running or Silver watermark not advancing

**Resolution**:
```bash
# Check Gold job status
./scripts/processing/serverless_monitor.sh

# Check Silver watermark
# View recent Silver events
aws athena start-query-execution \
  --query-string "SELECT MAX(ingestion_timestamp) FROM wikiguard_lakehouse.silver_events" \
  --result-configuration OutputLocation=s3://$S3_BUCKET/athena-results/
```

---

## Monitoring & Alerting

### Key Metrics to Monitor

| Metric | Source | Warning | Critical |
|--------|--------|---------|----------|
| Bronze processing lag | EMR logs | > 5 min | > 15 min |
| Silver quality pass rate | DQ metrics | < 95% | < 80% |
| Kafka consumer lag | MSK metrics | > 10K msgs | > 100K msgs |
| EMR job failures | CloudWatch | 1 failure | 3 failures |
| ECS task restarts | CloudWatch | 2 restarts | 5 restarts |

### Monitoring Commands

```bash
# Full pipeline status
./scripts/processing/serverless_monitor.sh

# ECS status
aws ecs describe-services \
  --cluster wikiguard-cluster \
  --services wikiguard-ingest-service \
  --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}'

# Recent failures
aws emr-serverless list-job-runs \
  --application-id $BRONZE_APP_ID \
  --states FAILED \
  --max-results 5

# Data freshness check (Athena)
SELECT 
  'bronze' as layer,
  MAX(ingestion_timestamp) as latest,
  CURRENT_TIMESTAMP - MAX(ingestion_timestamp) as lag
FROM wikiguard_lakehouse.bronze_events
UNION ALL
SELECT 
  'silver',
  MAX(ingestion_timestamp),
  CURRENT_TIMESTAMP - MAX(ingestion_timestamp)
FROM wikiguard_lakehouse.silver_events;
```

### Alert Configuration

Alerts are configured via:
- **SNS Topic**: `wikiguard-alerts` (Critical alerts → Email)
- **Slack Channel**: `#wikiguard-alerts` (Warning + Critical)

Modify alert destinations in:
- `infrastructure/terraform/modules/sns/main.tf`
- `infrastructure/terraform/modules/secrets-manager/main.tf` (Slack token)

---

## Emergency Procedures

### E1: Complete Pipeline Failure

```bash
# 1. Stop all components
./scripts/stop_pipeline.sh

# 2. Check infrastructure health
terraform plan  # Should show no changes

# 3. Verify MSK cluster
aws kafka describe-cluster --cluster-arn <ARN>

# 4. Check for AWS service issues
# https://status.aws.amazon.com/

# 5. Restart pipeline
./scripts/start_pipeline.sh

# 6. Monitor recovery
./scripts/processing/serverless_monitor.sh
```

### E2: Data Corruption Detected

```bash
# 1. Stop pipeline immediately
./scripts/stop_pipeline.sh

# 2. Identify corrupted data timeframe
# Query Athena for anomalies

# 3. Use Iceberg time travel to recover
# See Section 5.3

# 4. Document incident and root cause
```

### E3: Cost Runaway

```bash
# 1. Stop all EMR jobs
./scripts/processing/serverless_cancel_all.sh

# 2. Stop ECS
aws ecs update-service --cluster wikiguard-cluster --service wikiguard-ingest-service --desired-count 0

# 3. Stop EMR applications
aws emr-serverless stop-application --application-id $BRONZE_APP_ID
aws emr-serverless stop-application --application-id $SILVER_APP_ID
aws emr-serverless stop-application --application-id $GOLD_APP_ID

# 4. Investigate cost in AWS Cost Explorer
# 5. Review EMR executor sizing
```

---

## Appendix

### A. File Locations

| File | Purpose |
|------|---------|
| `scripts/start_pipeline.sh` | Start all components |
| `scripts/stop_pipeline.sh` | Stop all components |
| `scripts/processing/serverless_monitor.sh` | Monitor EMR jobs |
| `scripts/processing/serverless_cancel_all.sh` | Cancel all EMR jobs |
| `config/entity-allowlist.yaml` | Wikipedia entities to monitor |
| `src/processing/data_quality.py` | Quality gate definitions |
| `infrastructure/terraform/` | All infrastructure as code |

### B. Checkpoint Locations

| Layer | S3 Path |
|-------|---------|
| Bronze | `s3://<bucket>/checkpoints/bronze/` |
| Silver | `s3://<bucket>/checkpoints/silver/` |
| Gold | `s3://<bucket>/checkpoints/gold/` |

### C. Log Locations

| Component | Log Location |
|-----------|--------------|
| ECS Ingest | CloudWatch `/ecs/wikiguard-ingest` |
| Bronze EMR | `s3://<bucket>/emr-serverless-logs/bronze/` |
| Silver EMR | `s3://<bucket>/emr-serverless-logs/silver/` |
| Gold EMR | `s3://<bucket>/emr-serverless-logs/gold/` |

---

*End of Runbook*
