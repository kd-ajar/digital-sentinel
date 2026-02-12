# WikiGuard Infrastructure - Terraform

Terraform configuration for deploying WikiGuard on AWS.

> **Operations Guide**: See [docs/RUNBOOK.md](../../docs/RUNBOOK.md) for deployment, restart, and recovery procedures.

## Architecture Overview

```
┌─────────────────┐     ┌─────────────┐     ┌─────────────────┐
│  Wikimedia SSE  │────▶│ ECS Fargate │────▶│   Amazon MSK    │
│   EventStreams  │     │  (Ingest)   │     │    (Kafka)      │
└─────────────────┘     └─────────────┘     └────────┬────────┘
                                                     │
                        ┌────────────────────────────┼────────────────────────────┐
                        │                            ▼                            │
                        │  ┌─────────────────────────────────────────────────┐   │
                        │  │              EMR Serverless (Spark)              │   │
                        │  │  ┌─────────┐   ┌─────────┐   ┌─────────┐       │   │
                        │  │  │ Bronze  │──▶│ Silver  │──▶│  Gold   │       │   │
                        │  │  └─────────┘   └─────────┘   └─────────┘       │   │
                        │  └─────────────────────────────────────────────────┘   │
                        │                            │                            │
                        │                            ▼                            │
                        │  ┌─────────────────────────────────────────────────┐   │
                        │  │     S3 Lakehouse (Iceberg Tables)               │   │
                        │  │  bronze/ ──▶ silver/ ──▶ gold/                  │   │
                        │  └─────────────────────────────────────────────────┘   │
                        │                                                         │
                        │                    Private VPC                          │
                        └─────────────────────────────────────────────────────────┘
                                                     │
                                                     ▼
                        ┌─────────────────────────────────────────────────────────┐
                        │  Athena ──▶ QuickSight (Analytics & Dashboards)        │
                        └─────────────────────────────────────────────────────────┘
```

## Prerequisites

- [Terraform](https://www.terraform.io/downloads) >= 1.5.0
- [AWS CLI](https://aws.amazon.com/cli/) configured with appropriate credentials
- An AWS account with permissions to create the required resources

## Quick Start

### 1. Bootstrap State Backend (First Time Only)

```bash
cd bootstrap
terraform init
terraform apply
```

This creates the S3 bucket and DynamoDB table for Terraform state.

### 2. Configure Variables

```bash
cd ..
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your values:
```hcl
aws_region       = "us-east-1"
environment      = "dev"
project_name     = "wikiguard"
s3_bucket_prefix = "wikiguard-YYYYMMDD"  # Use unique prefix
notification_email = "your-email@example.com"
```

### 3. Update Backend Configuration

Edit `backend.tf` with your state bucket name:
```hcl
backend "s3" {
  bucket         = "your-state-bucket-name"
  key            = "terraform.tfstate"
  region         = "us-east-1"
  dynamodb_table = "terraform-state-locks"
  encrypt        = true
}
```

### 4. Initialize and Deploy

```bash
# Initialize Terraform
terraform init

# Create workspace (optional, for multi-environment)
terraform workspace new dev

# Review the plan
terraform plan

# Apply changes
terraform apply
```

## Module Structure

| Module | Description |
|--------|-------------|
| `vpc` | VPC with public/private subnets, NAT gateways, S3 endpoint |
| `s3` | S3 bucket for lakehouse data (Iceberg tables) |
| `msk` | Amazon MSK (Kafka) cluster |
| `ecs` | ECS Fargate cluster and service for ingestion |
| `emr-serverless` | EMR Serverless applications for Bronze/Silver/Gold processing |
| `glue` | Glue Data Catalog for Iceberg tables |
| `iam` | IAM roles and policies |
| `sns` | SNS topic for data quality alerts |
| `secrets-manager` | Secrets Manager for Slack token |
| `athena` | Athena workgroup for analytics |

## Outputs

After deployment, Terraform outputs important values:

```bash
terraform output
```

Key outputs:
- `s3_lakehouse_bucket` - S3 bucket for data
- `msk_bootstrap_brokers_tls` - Kafka bootstrap servers
- `ecs_cluster_name` - ECS cluster name
- `emr_serverless_*_app_id` - EMR Serverless application IDs

## Cost Optimization

This deployment is optimized for development/learning:

- **MSK**: `kafka.t3.small` (smallest instance type)
- **ECS**: 0.25 vCPU / 512 MB (minimal task size)
- **EMR Serverless**: Pay-per-use, auto-stops after 15 min idle
- **NAT Gateway**: 3 AZs (can reduce to 2 for dev, msk need min 2 AZs)


## Cleanup

To destroy all resources:

```bash
terraform destroy
```

**Note**: S3 bucket must be emptied before destruction:
```bash
aws s3 rm s3://your-bucket-name --recursive
```

## Troubleshooting

### State Lock Error
```bash
terraform force-unlock <LOCK_ID>
```
## Files

| File | Description |
|------|-------------|
| `main.tf` | Root module configuration |
| `variables.tf` | Input variable definitions |
| `outputs.tf` | Output values |
| `providers.tf` | Provider configuration |
| `backend.tf` | State backend configuration (gitignored) |
| `backend.tf.example` | Example backend configuration |
| `terraform.tfvars` | Variable values (gitignored) |
| `terraform.tfvars.example` | Example variable values |

## Security Notes

- All resources are deployed in private subnets
- MSK uses TLS encryption in transit
- S3 bucket has versioning and encryption enabled
- IAM follows least-privilege principle
- No hardcoded credentials in code

## License

MIT
