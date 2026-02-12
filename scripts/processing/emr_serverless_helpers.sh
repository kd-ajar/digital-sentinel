#!/bin/bash
# ============================================================================
# EMR Serverless Job Submission Helper Functions
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get configuration from Terraform
get_terraform_outputs() {
    cd "$PROJECT_ROOT/infrastructure/terraform"
    
    export S3_BUCKET=$(terraform output -raw s3_lakehouse_bucket)
    export GLUE_DATABASE=$(terraform output -raw glue_database_name)
    export MSK_BROKERS=$(terraform output -raw msk_bootstrap_brokers_tls)
    export AWS_REGION=$(terraform output -raw aws_region)
    export SNS_TOPIC_ARN=$(terraform output -raw sns_topic_arn)
    
    # EMR Serverless specific
    export BRONZE_APP_ID=$(terraform output -raw emr_serverless_bronze_app_id)
    export SILVER_APP_ID=$(terraform output -raw emr_serverless_silver_app_id)
    export GOLD_APP_ID=$(terraform output -raw emr_serverless_gold_app_id)
    export EXECUTION_ROLE_ARN=$(terraform output -raw emr_serverless_execution_role_arn)
    
    cd - > /dev/null
}

# Upload PySpark scripts to S3
upload_scripts() {
    echo -e "${BLUE}Uploading PySpark scripts to S3...${NC}"
    
    # Upload individual scripts
    aws s3 cp "$PROJECT_ROOT/src/processing/bronze_writer.py" "s3://$S3_BUCKET/scripts/bronze_writer.py"
    aws s3 cp "$PROJECT_ROOT/src/processing/silver_writer.py" "s3://$S3_BUCKET/scripts/silver_writer.py"
    aws s3 cp "$PROJECT_ROOT/src/processing/gold_writer.py" "s3://$S3_BUCKET/scripts/gold_writer.py"
    aws s3 cp "$PROJECT_ROOT/src/processing/data_quality.py" "s3://$S3_BUCKET/scripts/data_quality.py"
    
    # Create a zip file with all dependencies for py-files
    echo -e "${BLUE}Creating Python dependencies zip with pydeequ...${NC}"
    
    local original_dir=$(pwd)
    local src_dir="$PROJECT_ROOT/src/processing"
    local temp_dir="$src_dir/temp_deps"
    
    # Clean up any existing temp directory
    rm -rf "$temp_dir"
    
    # Create temporary directory for dependencies
    mkdir -p "$temp_dir"
    cp "$src_dir"/*.py "$temp_dir/"
    
    # Install pydeequ and slack_sdk to temp directory (without dependencies to avoid conflicts)
    pip install pydeequ slack_sdk -t "$temp_dir/" --no-deps --quiet
    
    # Create zip from temp directory
    cd "$temp_dir"
    zip -r "$src_dir/processing_dependencies.zip" .
    
    # Upload and cleanup
    cd "$src_dir"
    aws s3 cp processing_dependencies.zip "s3://$S3_BUCKET/scripts/processing_dependencies.zip"
    rm -rf processing_dependencies.zip temp_deps
    
    # Return to original directory
    cd "$original_dir"
    
    echo -e "${GREEN}Scripts uploaded successfully!${NC}"
}

# Start an EMR Serverless application
start_application() {
    local app_id=$1
    local app_name=$2
    
    echo -e "${BLUE}Starting ${app_name} application...${NC}"
    
    # Check current state
    local state=$(aws emr-serverless get-application \
        --application-id "$app_id" \
        --region "$AWS_REGION" \
        --query 'application.state' \
        --output text)
    
    if [[ "$state" == "STARTED" ]]; then
        echo -e "${GREEN}${app_name} already started${NC}"
        return 0
    fi
    
    # Start the application
    aws emr-serverless start-application \
        --application-id "$app_id" \
        --region "$AWS_REGION"
    
    # Wait for it to start
    echo -e "${YELLOW}Waiting for ${app_name} to start...${NC}"
    while true; do
        state=$(aws emr-serverless get-application \
            --application-id "$app_id" \
            --region "$AWS_REGION" \
            --query 'application.state' \
            --output text)
        
        if [[ "$state" == "STARTED" ]]; then
            echo -e "${GREEN}${app_name} started!${NC}"
            break
        elif [[ "$state" == "STOPPED" || "$state" == "TERMINATED" ]]; then
            echo -e "${RED}${app_name} failed to start. State: ${state}${NC}"
            return 1
        fi
        
        echo -e "${YELLOW}Current state: ${state}. Waiting...${NC}"
        sleep 10
    done
}

# Stop an EMR Serverless application
stop_application() {
    local app_id=$1
    local app_name=$2
    
    echo -e "${BLUE}Stopping ${app_name} application...${NC}"
    
    aws emr-serverless stop-application \
        --application-id "$app_id" \
        --region "$AWS_REGION"
    
    echo -e "${GREEN}${app_name} stop initiated${NC}"
}

# Get Spark submit properties for Iceberg (includes Deequ for Silver/Gold)
get_spark_properties() {
    local s3_bucket=$1
    
    cat << EOF
{
    "spark.jars": "/usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar",
    "spark.jars.packages": "com.amazon.deequ:deequ:2.0.1-spark-3.3",
    "spark.sql.catalog.glue_catalog": "org.apache.iceberg.spark.SparkCatalog",
    "spark.sql.catalog.glue_catalog.warehouse": "s3://${s3_bucket}/",
    "spark.sql.catalog.glue_catalog.catalog-impl": "org.apache.iceberg.aws.glue.GlueCatalog",
    "spark.sql.catalog.glue_catalog.io-impl": "org.apache.iceberg.aws.s3.S3FileIO",
    "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    "spark.sql.defaultCatalog": "glue_catalog",
    "spark.hadoop.hive.metastore.client.factory.class": "com.amazonaws.glue.catalog.metastore.AWSGlueDataCatalogHiveClientFactory"
}
EOF
}

# Get Spark submit properties for Bronze (includes Kafka + Deequ)
get_bronze_spark_properties() {
    local s3_bucket=$1
    
    cat << EOF
{
    "spark.jars": "/usr/share/aws/iceberg/lib/iceberg-spark3-runtime.jar",
    "spark.jars.packages": "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,com.amazon.deequ:deequ:2.0.1-spark-3.3",
    "spark.sql.catalog.glue_catalog": "org.apache.iceberg.spark.SparkCatalog",
    "spark.sql.catalog.glue_catalog.warehouse": "s3://${s3_bucket}/",
    "spark.sql.catalog.glue_catalog.catalog-impl": "org.apache.iceberg.aws.glue.GlueCatalog",
    "spark.sql.catalog.glue_catalog.io-impl": "org.apache.iceberg.aws.s3.S3FileIO",
    "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    "spark.sql.defaultCatalog": "glue_catalog",
    "spark.hadoop.hive.metastore.client.factory.class": "com.amazonaws.glue.catalog.metastore.AWSGlueDataCatalogHiveClientFactory"
}
EOF
}

# Submit a job to EMR Serverless
submit_job() {
    local app_id=$1
    local job_name=$2
    local script_path=$3
    local spark_properties=$4
    local driver_cores=$5
    local driver_memory=$6
    local executor_cores=$7
    local executor_memory=$8
    shift 8
    local script_args=("$@")
    
    echo -e "${BLUE}Submitting ${job_name}...${NC}"
    
    # Build arguments array
    local args_json="["
    for arg in "${script_args[@]}"; do
        args_json+="\"$arg\","
    done
    args_json="${args_json%,}]"  # Remove trailing comma
    
    local job_run_id=$(aws emr-serverless start-job-run \
        --application-id "$app_id" \
        --execution-role-arn "$EXECUTION_ROLE_ARN" \
        --name "$job_name" \
        --job-driver "{
            \"sparkSubmit\": {
                \"entryPoint\": \"$script_path\",
                \"entryPointArguments\": $args_json,
                \"sparkSubmitParameters\": \"--py-files s3://${S3_BUCKET}/scripts/processing_dependencies.zip --conf spark.driver.cores=${driver_cores} --conf spark.driver.memory=${driver_memory} --conf spark.executor.cores=${executor_cores} --conf spark.executor.memory=${executor_memory}\"
            }
        }" \
        --configuration-overrides "{
            \"monitoringConfiguration\": {
                \"s3MonitoringConfiguration\": {
                    \"logUri\": \"s3://${S3_BUCKET}/emr-serverless-logs/\"
                }
            }
        }" \
        --region "$AWS_REGION" \
        --query 'jobRunId' \
        --output text)
    
    echo -e "${GREEN}Job submitted: ${job_name}${NC}"
    echo -e "${GREEN}Job Run ID: ${job_run_id}${NC}"
    echo "$job_run_id"
}

# Get job status
get_job_status() {
    local app_id=$1
    local job_run_id=$2
    
    aws emr-serverless get-job-run \
        --application-id "$app_id" \
        --job-run-id "$job_run_id" \
        --region "$AWS_REGION" \
        --query 'jobRun.state' \
        --output text
}

# Cancel a job
cancel_job() {
    local app_id=$1
    local job_run_id=$2
    
    echo -e "${YELLOW}Cancelling job ${job_run_id}...${NC}"
    
    aws emr-serverless cancel-job-run \
        --application-id "$app_id" \
        --job-run-id "$job_run_id" \
        --region "$AWS_REGION"
    
    echo -e "${GREEN}Job cancelled${NC}"
}

# List running jobs
list_jobs() {
    local app_id=$1
    local states=${2:-"RUNNING,SUBMITTED,PENDING"}
    
    aws emr-serverless list-job-runs \
        --application-id "$app_id" \
        --region "$AWS_REGION" \
        --states $states \
        --query 'jobRuns[*].{Id:id,Name:name,State:state,CreatedAt:createdAt}' \
        --output table
}

# Watch job progress
watch_job() {
    local app_id=$1
    local job_run_id=$2
    local job_name=$3
    
    echo -e "${BLUE}Watching ${job_name} (${job_run_id})...${NC}"
    
    while true; do
        local state=$(get_job_status "$app_id" "$job_run_id")
        
        case "$state" in
            RUNNING|SUBMITTED|PENDING|SCHEDULED)
                echo -e "${YELLOW}[$(date +%H:%M:%S)] ${job_name}: ${state}${NC}"
                sleep 30
                ;;
            SUCCESS)
                echo -e "${GREEN}[$(date +%H:%M:%S)] ${job_name}: ${state}${NC}"
                return 0
                ;;
            FAILED|CANCELLED)
                echo -e "${RED}[$(date +%H:%M:%S)] ${job_name}: ${state}${NC}"
                return 1
                ;;
            *)
                echo -e "${RED}[$(date +%H:%M:%S)] ${job_name}: Unknown state ${state}${NC}"
                return 1
                ;;
        esac
    done
}
