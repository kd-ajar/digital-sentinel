#!/bin/bash
# ============================================================================
# Submit Bronze Writer to EMR Serverless
# Streaming job: Kafka → Bronze Iceberg
# 
# Config for streaming (I/O bound, not CPU heavy):
# - Driver: 1 vCPU, 2GB memory
# - Executor: 1 vCPU, 2GB memory (1 instance)
# - Total: ~2 vCPU per job
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/emr_serverless_helpers.sh"

echo "============================================"
echo "EMR Serverless - Bronze Writer (Streaming)"
echo "============================================"

# Get Terraform outputs
echo "Loading configuration..."
get_terraform_outputs

echo ""
echo "Configuration:"
echo "  Bronze App ID: $BRONZE_APP_ID"
echo "  S3 Bucket: $S3_BUCKET"
echo "  Glue Database: $GLUE_DATABASE"
echo "  MSK Brokers: $MSK_BROKERS"
echo "  Execution Role: $EXECUTION_ROLE_ARN"
echo ""

# Upload scripts
upload_scripts
aws s3 cp "$PROJECT_ROOT/src/processing/bronze_writer.py" "s3://$S3_BUCKET/scripts/bronze_writer.py"

# Start application
start_application "$BRONZE_APP_ID" "Bronze"

# Submit Bronze job
# Bronze streaming config (small & stable for I/O bound MSK ingestion)
# Keep total memory under 20GB: driver(2g) + executor(2g) + overhead ~= 6GB
DRIVER_CORES="1"
DRIVER_MEMORY="2g"
EXECUTOR_CORES="1"
EXECUTOR_MEMORY="2g"

# Script arguments: bootstrap_servers, s3_bucket, glue_database, topic, starting_offsets
# Use cleaned_events topic which has _metadata.canonical_entity from SSE consumer
SCRIPT_ARGS=("$MSK_BROKERS" "$S3_BUCKET" "$GLUE_DATABASE" "cleaned_events" "latest")

JOB_RUN_ID=$(aws emr-serverless start-job-run \
    --application-id "$BRONZE_APP_ID" \
    --execution-role-arn "$EXECUTION_ROLE_ARN" \
    --name "Bronze-Writer-Streaming" \
    --job-driver "{
        \"sparkSubmit\": {
            \"entryPoint\": \"s3://${S3_BUCKET}/scripts/bronze_writer.py\",
            \"entryPointArguments\": [\"${MSK_BROKERS}\", \"${S3_BUCKET}\", \"${GLUE_DATABASE}\", \"cleaned_events\", \"latest\"],
            \"sparkSubmitParameters\": \"--py-files s3://${S3_BUCKET}/scripts/data_quality.py,s3://${S3_BUCKET}/scripts/processing_dependencies.zip --conf spark.driver.cores=${DRIVER_CORES} --conf spark.driver.memory=${DRIVER_MEMORY} --conf spark.executor.cores=${EXECUTOR_CORES} --conf spark.executor.memory=${EXECUTOR_MEMORY} --conf spark.executor.instances=1 --conf spark.dynamicAllocation.enabled=false --conf spark.jars=/usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1,com.amazon.deequ:deequ:2.0.13-spark-3.5 --conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.glue_catalog.warehouse=s3://${S3_BUCKET}/ --conf spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions --conf spark.sql.defaultCatalog=glue_catalog --conf spark.hadoop.hive.metastore.client.factory.class=com.amazonaws.glue.catalog.metastore.AWSGlueDataCatalogHiveClientFactory\"
        }
    }" \
    --configuration-overrides "{
        \"applicationConfiguration\": [
            {
                \"classification\": \"spark-defaults\",
                \"properties\": {
                    \"spark.driver.env.SPARK_VERSION\": \"3.5\",
                    \"spark.executorEnv.SPARK_VERSION\": \"3.5\",
                    \"spark.driver.env.SNS_TOPIC_ARN\": \"${SNS_TOPIC_ARN}\",
                    \"spark.driver.env.SLACK_CHANNEL\": \"#wikiguard-bronze\"
                }
            }
        ],
        \"monitoringConfiguration\": {
            \"s3MonitoringConfiguration\": {
                \"logUri\": \"s3://${S3_BUCKET}/emr-serverless-logs/bronze/\"
            }
        }
    }" \
    --region "$AWS_REGION" \
    --query 'jobRunId' \
    --output text)

echo ""
echo -e "${GREEN}Bronze Writer submitted successfully!${NC}"
echo "Job Run ID: $JOB_RUN_ID"
echo ""
echo "Monitor job status:"
echo "  aws emr-serverless get-job-run --application-id $BRONZE_APP_ID --job-run-id $JOB_RUN_ID --region $AWS_REGION"
echo ""
echo "View logs:"
echo "  aws s3 ls s3://$S3_BUCKET/emr-serverless-logs/bronze/"
echo ""
echo "Cancel job (if needed):"
echo "  aws emr-serverless cancel-job-run --application-id $BRONZE_APP_ID --job-run-id $JOB_RUN_ID --region $AWS_REGION"
