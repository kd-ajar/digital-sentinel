#!/bin/bash
# Script to build and push Docker image to ECR

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
AWS_REGION=${AWS_REGION:-us-east-1}
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO_NAME="wikiguard/ingest"
IMAGE_TAG=${IMAGE_TAG:-latest}

echo "🐳 Building and pushing Docker image to ECR..."
echo "Region: $AWS_REGION"
echo "Account: $AWS_ACCOUNT_ID"
echo "Repository: $ECR_REPO_NAME"
echo "Tag: $IMAGE_TAG"

# Login to ECR
echo "Logging in to ECR..."
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# Build Docker image
echo "Building Docker image..."
cd "$PROJECT_ROOT"
docker build -f infrastructure/docker/ingest/Dockerfile -t "$ECR_REPO_NAME:$IMAGE_TAG" .

# Tag image
ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:$IMAGE_TAG"
docker tag "$ECR_REPO_NAME:$IMAGE_TAG" "$ECR_URI"

# Push to ECR
echo "Pushing to ECR..."
docker push "$ECR_URI"

echo "✅ Image pushed successfully: $ECR_URI"
