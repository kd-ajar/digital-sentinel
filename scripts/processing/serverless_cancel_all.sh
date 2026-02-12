#!/bin/bash
# ============================================================================
# Cancel All EMR Serverless Jobs
# Cancels all running jobs across Bronze, Silver, Gold applications
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/emr_serverless_helpers.sh"

echo "========================================================"
echo "EMR Serverless - Cancel All Running Jobs"
echo "========================================================"

# Get Terraform outputs
get_terraform_outputs

cancel_app_jobs() {
    local app_id=$1
    local app_name=$2
    
    echo ""
    echo -e "${YELLOW}Cancelling ${app_name} jobs...${NC}"
    
    # Get all running/pending jobs
    JOB_IDS=$(aws emr-serverless list-job-runs \
        --application-id "$app_id" \
        --region "$AWS_REGION" \
        --states RUNNING SUBMITTED PENDING SCHEDULED \
        --query 'jobRuns[*].id' \
        --output text)
    
    if [ -z "$JOB_IDS" ] || [ "$JOB_IDS" == "None" ]; then
        echo -e "${GREEN}No running jobs in ${app_name}${NC}"
        return
    fi
    
    for job_id in $JOB_IDS; do
        echo "  Cancelling job: $job_id"
        aws emr-serverless cancel-job-run \
            --application-id "$app_id" \
            --job-run-id "$job_id" \
            --region "$AWS_REGION" 2>/dev/null || echo "  (already cancelled)"
    done
    
    echo -e "${GREEN}${app_name} jobs cancelled${NC}"
}

# Cancel jobs in all applications
cancel_app_jobs "$BRONZE_APP_ID" "Bronze"
cancel_app_jobs "$SILVER_APP_ID" "Silver"
cancel_app_jobs "$GOLD_APP_ID" "Gold"

echo ""
echo -e "${GREEN}All jobs cancelled!${NC}"
echo ""
echo "Applications are still running. To stop them:"
echo "  aws emr-serverless stop-application --application-id $BRONZE_APP_ID --region $AWS_REGION"
echo "  aws emr-serverless stop-application --application-id $SILVER_APP_ID --region $AWS_REGION"
echo "  aws emr-serverless stop-application --application-id $GOLD_APP_ID --region $AWS_REGION"
