#!/bin/bash
set -e

echo "🚀 Starting WikiGuard Pipeline..."

# 1. Start ECS Ingest
echo "Starting ECS Fargate ingest service..."
aws ecs update-service --cluster wikiguard-cluster --service wikiguard-ingest-service --desired-count 1 --query 'service.desiredCount' --output text

# Wait for ECS to stabilize
echo "Waiting for ECS service to start..."
aws ecs wait services-stable --cluster wikiguard-cluster --services wikiguard-ingest-service

# 2. Start EMR Serverless jobs
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/processing"

echo "Submitting Bronze job..."
./serverless_submit_bronze.sh

echo "Submitting Silver job..."
./serverless_submit_silver.sh

echo "Submitting Gold job..."
./serverless_submit_gold.sh

echo "✅ Pipeline started!"
