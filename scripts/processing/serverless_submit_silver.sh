#!/bin/bash
# ============================================================================
# Submit Silver Writer to EMR Serverless
# Streaming job: Bronze Iceberg → Silver Iceberg
# 
# Config for Silver (parse, dedupe, enrich, quality checks):
# - Driver: 1 vCPU, 4GB memory
# - Executor: 1 vCPU, 6GB memory (max for 1 vCPU with overhead)
# - Total: ~2-4 vCPU per job (within 16 vCPU quota)
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/emr_serverless_helpers.sh"

echo "============================================"
echo "EMR Serverless - Silver Writer (Streaming)"
echo "============================================"

# Get Terraform outputs
echo "Loading configuration..."
get_terraform_outputs

echo ""
echo "Configuration:"
echo "  Silver App ID: $SILVER_APP_ID"
echo "  S3 Bucket: $S3_BUCKET"
echo "  Glue Database: $GLUE_DATABASE"
echo "  Execution Role: $EXECUTION_ROLE_ARN"
echo ""

# Upload scripts
upload_scripts

# Start application
start_application "$SILVER_APP_ID" "Silver"

# Submit Silver job
# Silver config - OPTIMIZED for parallelism within 16 vCPU quota
# Using 2 cores per executor for better parallelism on DQ operations
# 2 executors × 2 cores = 4 vCPU + 1 driver = 5 vCPU total
# Memory: 2 vCPU workers can have up to 16GB total (8GB per vCPU)
DRIVER_CORES="1"
DRIVER_MEMORY="4g"
EXECUTOR_CORES="2"
EXECUTOR_MEMORY="6g"

# Script arguments: s3_bucket, glue_database
JOB_RUN_ID=$(aws emr-serverless start-job-run \
    --application-id "$SILVER_APP_ID" \
    --execution-role-arn "$EXECUTION_ROLE_ARN" \
    --name "Silver-Writer-Streaming" \
    --job-driver "{
        \"sparkSubmit\": {
            \"entryPoint\": \"s3://${S3_BUCKET}/scripts/silver_writer.py\",
            \"entryPointArguments\": [\"${S3_BUCKET}\", \"${GLUE_DATABASE}\"],
            \"sparkSubmitParameters\": \"--py-files s3://${S3_BUCKET}/scripts/data_quality.py,s3://${S3_BUCKET}/scripts/processing_dependencies.zip --packages com.amazon.deequ:deequ:2.0.13-spark-3.5 --conf spark.driver.cores=${DRIVER_CORES} --conf spark.driver.memory=${DRIVER_MEMORY} --conf spark.executor.cores=${EXECUTOR_CORES} --conf spark.executor.memory=${EXECUTOR_MEMORY} --conf spark.executor.instances=1 --conf spark.dynamicAllocation.enabled=true --conf spark.dynamicAllocation.minExecutors=1 --conf spark.dynamicAllocation.maxExecutors=2 --conf spark.dynamicAllocation.initialExecutors=1 --conf spark.jars=/usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar --conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.glue_catalog.warehouse=s3://${S3_BUCKET}/ --conf spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions --conf spark.sql.defaultCatalog=glue_catalog --conf spark.hadoop.hive.metastore.client.factory.class=com.amazonaws.glue.catalog.metastore.AWSGlueDataCatalogHiveClientFactory --conf spark.emr-serverless.driverEnv.SNS_TOPIC_ARN=${SNS_TOPIC_ARN} --conf spark.emr-serverless.driverEnv.SLACK_CHANNEL=#wikiguard-silver\"
        }
    }" \
    --configuration-overrides "{
        \"applicationConfiguration\": [
            {
                \"classification\": \"spark-defaults\",
                \"properties\": {
                    \"spark.driver.env.SPARK_VERSION\": \"3.5\",
                    \"spark.executorEnv.SPARK_VERSION\": \"3.5\"
                }
            }
        ],
        \"monitoringConfiguration\": {
            \"s3MonitoringConfiguration\": {
                \"logUri\": \"s3://${S3_BUCKET}/emr-serverless-logs/silver/\"
            }
        }
    }" \
    --region "$AWS_REGION" \
    --query 'jobRunId' \
    --output text)

echo ""
echo -e "${GREEN}Silver Writer submitted successfully!${NC}"
echo "Job Run ID: $JOB_RUN_ID"
echo ""
echo "Monitor job status:"
echo "  aws emr-serverless get-job-run --application-id $SILVER_APP_ID --job-run-id $JOB_RUN_ID --region $AWS_REGION"
echo ""
echo "View logs:"
echo "  aws s3 ls s3://$S3_BUCKET/emr-serverless-logs/silver/"
echo ""
echo "Cancel job (if needed):"
echo "  aws emr-serverless cancel-job-run --application-id $SILVER_APP_ID --job-run-id $JOB_RUN_ID --region $AWS_REGION"
