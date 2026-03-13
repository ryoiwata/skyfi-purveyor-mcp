# Purveyor on AWS (ECS Fargate + RDS + ALB)

Deploys Purveyor to AWS using ECS Fargate for the application, RDS Postgres for persistence, and an Application Load Balancer for HTTPS termination.

## Prerequisites

- Terraform >= 1.5.0
- AWS CLI configured (`aws configure`)
- Docker image pushed to a registry (GitHub Container Registry, ECR, etc.)
- ACM certificate for your domain

## Architecture

```
Internet → ALB (HTTPS) → ECS Fargate (Purveyor) → RDS Postgres
                                                 → ElastiCache Redis (optional)
```

## Usage

```bash
cd deploy/terraform/aws

# Copy and edit the example vars file
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

# Initialize
terraform init

# Review plan
terraform plan

# Apply
terraform apply
```

## Post-Deploy Setup

### 1. Set SKYFI_API_KEY in SSM

```bash
aws ssm put-parameter \
  --name "/purveyor/SKYFI_API_KEY" \
  --value "your-skyfi-api-key" \
  --type "SecureString" \
  --overwrite
```

### 2. Point DNS to ALB

Get the ALB DNS name from Terraform outputs:
```bash
terraform output alb_dns_name
```

Create a CNAME record: `purveyor.example.com` → the ALB DNS name.

### 3. Verify Health

```bash
curl https://purveyor.example.com/health
```

## Estimated Monthly Cost (us-east-1)

| Service | Config | ~Cost/month |
|---------|--------|-------------|
| ECS Fargate | 0.5 vCPU, 1GB | ~$15 |
| RDS Postgres | db.t3.micro | ~$13 |
| ALB | 1 instance | ~$20 |
| ElastiCache (optional) | cache.t3.micro | ~$12 |
| **Total (without Redis)** | | **~$48** |
| **Total (with Redis)** | | **~$60** |

## Variables

See `variables.tf` for full documentation of all available variables.
