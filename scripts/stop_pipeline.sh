#!/bin/bash
set -e

echo "🛑 Stopping WikiGuard Pipeline..."

# 1. Stop ECS Ingest
echo "Stopping ECS Fargate ingest service..."
aws ecs update-service --cluster wikiguard-cluster --service wikiguard-ingest-service --desired-count 0 --query 'service.desiredCount' --output text

# 2. Cancel EMR jobs
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/processing"

echo "Cancelling EMR Serverless jobs..."
./serverless_cancel_all.sh

echo "✅ Pipeline stopped!"
