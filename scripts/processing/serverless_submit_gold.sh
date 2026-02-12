#!/bin/bash
# ============================================================================
# Submit Gold Writer to EMR Serverless
# Streaming job: Silver Iceberg → Gold Iceberg (10-min aggregations)
# 
# Config for Gold (aggregations, windowing):
# - Driver: 1 vCPU, 2GB memory
# - Executor: 1 vCPU, 2GB memory (1-2 instances with dynamic allocation)
# - Total: ~3-4 vCPU per job
# - Small data volume, doesn't need big parallelism
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/emr_serverless_helpers.sh"

echo "============================================"
echo "EMR Serverless - Gold Writer (Streaming)"
echo "============================================"

# Get Terraform outputs
echo "Loading configuration..."
get_terraform_outputs

echo ""
echo "Configuration:"
echo "  Gold App ID: $GOLD_APP_ID"
echo "  S3 Bucket: $S3_BUCKET"
echo "  Glue Database: $GLUE_DATABASE"
echo "  Execution Role: $EXECUTION_ROLE_ARN"
echo ""

# Upload scripts
aws s3 cp "$PROJECT_ROOT/src/processing/gold_writer.py" "s3://$S3_BUCKET/scripts/gold_writer.py"

# Start application
start_application "$GOLD_APP_ID" "Gold"

# Submit Gold job
# Gold config - OPTIMIZED for 16 vCPU quota
# Uses dynamic allocation to scale 1-2 executors as needed
DRIVER_CORES="1"  
DRIVER_MEMORY="2g"
EXECUTOR_CORES="1"
EXECUTOR_MEMORY="2g"

# Script arguments: s3_bucket, glue_database
JOB_RUN_ID=$(aws emr-serverless start-job-run \
    --application-id "$GOLD_APP_ID" \
    --execution-role-arn "$EXECUTION_ROLE_ARN" \
    --name "Gold-Writer-Streaming" \
    --job-driver "{
        \"sparkSubmit\": {
            \"entryPoint\": \"s3://${S3_BUCKET}/scripts/gold_writer.py\",
            \"entryPointArguments\": [\"${S3_BUCKET}\", \"${GLUE_DATABASE}\"],
            \"sparkSubmitParameters\": \"--py-files s3://${S3_BUCKET}/scripts/data_quality.py,s3://${S3_BUCKET}/scripts/processing_dependencies.zip --packages com.amazon.deequ:deequ:2.0.13-spark-3.5 --conf spark.driver.cores=${DRIVER_CORES} --conf spark.driver.memory=${DRIVER_MEMORY} --conf spark.executor.cores=${EXECUTOR_CORES} --conf spark.executor.memory=${EXECUTOR_MEMORY} --conf spark.executor.instances=1 --conf spark.dynamicAllocation.enabled=true --conf spark.dynamicAllocation.minExecutors=1 --conf spark.dynamicAllocation.maxExecutors=2 --conf spark.dynamicAllocation.initialExecutors=1 --conf spark.jars=/usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar --conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.glue_catalog.warehouse=s3://${S3_BUCKET}/ --conf spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions --conf spark.sql.defaultCatalog=glue_catalog --conf spark.hadoop.hive.metastore.client.factory.class=com.amazonaws.glue.catalog.metastore.AWSGlueDataCatalogHiveClientFactory --conf spark.emr-serverless.driverEnv.SNS_TOPIC_ARN=${SNS_TOPIC_ARN} --conf spark.emr-serverless.driverEnv.SLACK_CHANNEL=#wikiguard-gold\"
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
                \"logUri\": \"s3://${S3_BUCKET}/emr-serverless-logs/gold/\"
            }
        }
    }" \
    --region "$AWS_REGION" \
    --query 'jobRunId' \
    --output text)

echo ""
echo -e "${GREEN}Gold Writer submitted successfully!${NC}"
echo "Job Run ID: $JOB_RUN_ID"
echo ""
echo "Monitor job status:"
echo "  aws emr-serverless get-job-run --application-id $GOLD_APP_ID --job-run-id $JOB_RUN_ID --region $AWS_REGION"
echo ""
echo "View logs:"
echo "  aws s3 ls s3://$S3_BUCKET/emr-serverless-logs/gold/"
echo ""
echo "Cancel job (if needed):"
echo "  aws emr-serverless cancel-job-run --application-id $GOLD_APP_ID --job-run-id $JOB_RUN_ID --region $AWS_REGION"
