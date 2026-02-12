# Ingest Deployment Scripts

Scripts for deploying the ECS Fargate ingestion pipeline.

> **Full documentation**: See [docs/RUNBOOK.md](../../docs/RUNBOOK.md) for complete deployment and operations guide.

## Scripts

| Script | Purpose |
|--------|---------|
| `build_and_push_docker.sh` | Build Docker image and push to ECR |

## Quick Reference

```bash
# Build and push Docker image (required before first ECS start)
./build_and_push_docker.sh

# Start ECS service
aws ecs update-service --cluster wikiguard-cluster \
  --service wikiguard-ingest-service --desired-count 1

# Stop ECS service
aws ecs update-service --cluster wikiguard-cluster \
  --service wikiguard-ingest-service --desired-count 0
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | us-east-1 | AWS region |
| `IMAGE_TAG` | latest | Docker image tag |
