# Terraform Bootstrap

## Purpose

This bootstrap module creates the **remote backend infrastructure** for storing Terraform state securely in AWS. It must be run **once** before deploying the main WikiGuard infrastructure.

### What it creates:
- **S3 Bucket** - Stores Terraform state files with versioning and encryption
- **DynamoDB Table** - Provides state locking to prevent concurrent modifications

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform >= 1.0 installed

## Usage

### Step 1: Initialize and Apply Bootstrap

```bash
cd infrastructure/terraform/bootstrap

# Initialize Terraform
terraform init

# Plan (review what will be created)
terraform plan -var="state_bucket_name=wikiguard-<your-unique-id>-state"

# Apply (create the resources)
terraform apply -var="state_bucket_name=wikiguard-<your-unique-id>-state"
```

> **IMPORTANT**: The `state_bucket_name` must be globally unique across all AWS accounts. 

### Step 2: Note the Output

After successful apply, you'll see output like:
```
state_bucket_name = "wikiguard-<your-unique-id>-state"
lock_table_name   = "wikiguard-terraform-lock"
```

### Step 3: Configure Main Terraform Backend

Copy the backend configuration from the output and add it to `infrastructure/terraform/backend.tf`:

```hcl
terraform {
  backend "s3" {
    bucket         = "wikiguard-<your-unique-id>-state"
    key            = "terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "wikiguard-terraform-lock"
  }
}
```


## Security Notes

- State bucket has versioning enabled for recovery
- Server-side encryption (AES256) is enabled
- Public access is blocked
- State locking prevents concurrent modifications

## Clean Up

If you need to destroy the bootstrap resources (this will delete your state!):

```bash
terraform destroy -var="state_bucket_name=wikiguard-<your-unique-id>-state"
```

> ⚠️ **Warning**: Only destroy bootstrap after destroying all other infrastructure, or you'll lose your state file.
