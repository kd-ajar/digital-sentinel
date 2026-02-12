#!/bin/bash
# ============================================================================
# Monitor EMR Serverless Medallion Pipeline
# Shows status of all 3 applications and running jobs
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/emr_serverless_helpers.sh"

echo "========================================================"
echo "EMR Serverless - Medallion Pipeline Status"
echo "========================================================"

# Get Terraform outputs
get_terraform_outputs

echo ""
echo "Application Status:"
echo "-------------------"

# Check Bronze application
BRONZE_STATE=$(aws emr-serverless get-application \
    --application-id "$BRONZE_APP_ID" \
    --region "$AWS_REGION" \
    --query 'application.state' \
    --output text)
echo -e "Bronze ($BRONZE_APP_ID): ${BRONZE_STATE}"

# Check Silver application
SILVER_STATE=$(aws emr-serverless get-application \
    --application-id "$SILVER_APP_ID" \
    --region "$AWS_REGION" \
    --query 'application.state' \
    --output text)
echo -e "Silver ($SILVER_APP_ID): ${SILVER_STATE}"

# Check Gold application
GOLD_STATE=$(aws emr-serverless get-application \
    --application-id "$GOLD_APP_ID" \
    --region "$AWS_REGION" \
    --query 'application.state' \
    --output text)
echo -e "Gold ($GOLD_APP_ID): ${GOLD_STATE}"

echo ""
echo "Running Jobs:"
echo "-------------"

echo ""
echo -e "${BLUE}Bronze Jobs:${NC}"
aws emr-serverless list-job-runs \
    --application-id "$BRONZE_APP_ID" \
    --region "$AWS_REGION" \
    --states RUNNING SUBMITTED PENDING SCHEDULED \
    --query 'jobRuns[*].{Id:id,Name:name,State:state,CreatedAt:createdAt}' \
    --output table 2>/dev/null || echo "No running jobs"

echo ""
echo -e "${BLUE}Silver Jobs:${NC}"
aws emr-serverless list-job-runs \
    --application-id "$SILVER_APP_ID" \
    --region "$AWS_REGION" \
    --states RUNNING SUBMITTED PENDING SCHEDULED \
    --query 'jobRuns[*].{Id:id,Name:name,State:state,CreatedAt:createdAt}' \
    --output table 2>/dev/null || echo "No running jobs"

echo ""
echo -e "${BLUE}Gold Jobs:${NC}"
aws emr-serverless list-job-runs \
    --application-id "$GOLD_APP_ID" \
    --region "$AWS_REGION" \
    --states RUNNING SUBMITTED PENDING SCHEDULED \
    --query 'jobRuns[*].{Id:id,Name:name,State:state,CreatedAt:createdAt}' \
    --output table 2>/dev/null || echo "No running jobs"

echo ""
echo "Recent Failed Jobs (last 5):"
echo "---------------------------"

echo ""
echo -e "${RED}Bronze Failed:${NC}"
aws emr-serverless list-job-runs \
    --application-id "$BRONZE_APP_ID" \
    --region "$AWS_REGION" \
    --states FAILED \
    --max-results 5 \
    --query 'jobRuns[*].{Id:id,Name:name,State:state,CreatedAt:createdAt}' \
    --output table 2>/dev/null || echo "No failed jobs"

echo ""
echo -e "${RED}Silver Failed:${NC}"
aws emr-serverless list-job-runs \
    --application-id "$SILVER_APP_ID" \
    --region "$AWS_REGION" \
    --states FAILED \
    --max-results 5 \
    --query 'jobRuns[*].{Id:id,Name:name,State:state,CreatedAt:createdAt}' \
    --output table 2>/dev/null || echo "No failed jobs"

echo ""
echo -e "${RED}Gold Failed:${NC}"
aws emr-serverless list-job-runs \
    --application-id "$GOLD_APP_ID" \
    --region "$AWS_REGION" \
    --states FAILED \
    --max-results 5 \
    --query 'jobRuns[*].{Id:id,Name:name,State:state,CreatedAt:createdAt}' \
    --output table 2>/dev/null || echo "No failed jobs"

echo ""
echo "Data in S3:"
echo "-----------"
echo "Bronze events:"
aws s3 ls "s3://$S3_BUCKET/data/bronze_events/" --recursive --summarize 2>/dev/null | tail -2 || echo "No data yet"
echo ""
echo "Silver events:"
aws s3 ls "s3://$S3_BUCKET/data/silver_events/" --recursive --summarize 2>/dev/null | tail -2 || echo "No data yet"
echo ""
echo "Gold metrics:"
aws s3 ls "s3://$S3_BUCKET/data/gold_entity_metrics_5min/" --recursive --summarize 2>/dev/null | tail -2 || echo "No data yet"
