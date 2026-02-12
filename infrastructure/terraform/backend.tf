# Remote Backend Configuration
# S3 for state storage + DynamoDB for state locking

terraform {
  backend "s3" {
    bucket         = "wikiguard-14012026-state" 
    key            = "terraform.tfstate"
    region         = "us-east-1"                      
    encrypt        = true
    dynamodb_table = "wikiguard-terraform-lock"
    workspace_key_prefix = "workspaces"             
  }
}