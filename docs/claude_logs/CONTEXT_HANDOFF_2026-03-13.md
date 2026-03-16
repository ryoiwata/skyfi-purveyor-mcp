# Purveyor (skyfi-purveyor-mcp) — Context Handoff Document

**Date:** March 13, 2026
**Purpose:** Continue this project with a new Claude instance. This document contains everything needed to pick up where we left off.

## Project Overview

**Purveyor** is a Python MCP (Model Context Protocol) server that wraps SkyFi's satellite imagery Platform API, enabling AI agents to conversationally search, order, and monitor satellite imagery. Users interact through any MCP-compatible client (Claude Web, OpenAI, Gemini, LangChain, ADK, AI SDK, etc.).

**Repo:** https://github.com/ryoiwata/skyfi-purveyor-mcp
**Stack:** Python 3.11+ · MCP Python SDK (FastMCP) · FastAPI · SQLAlchemy 2.0 async · Postgres+PostGIS (cloud) / SQLite+SpatiaLite (local) · httpx · Pydantic v2 · structlog · Fernet encryption · Docker · Terraform

## Current State — ALL 5 PHASES COMPLETE

### Implementation Summary
- **Phase 0:** Project scaffolding, config, database, Docker — ✅
- **Phase 1:** SkyFi API client (20+ methods), tiered cache, auth providers — ✅
- **Phase 2:** MCP server (FastMCP), 16 read-only tools, 5 resources, FastAPI app, CLI — ✅
- **Phase 3:** Order confirmation flow (Fernet tokens), webhooks, notifications, background tasks — ✅
- **Phase 4:** Rate limiting, Sentry, health/ready endpoints, 81% test coverage — ✅
- **Phase 5:** Demo agent (stdio), 8 integration docs, CI/CD (3 workflows), Terraform (AWS+GCP), open source polish — ✅

### Test/Quality Status
- **291 tests passing** (288 + some added during fixes)
- **81% line coverage** (target was >80%)
- **mypy strict:** 33 source files, no issues
- **ruff:** all checks passed
- **20 MCP tools** registered
- **5 MCP resources** registered

### MCP Tools (20 total)
search_archives, get_archive_details, get_pricing, check_feasibility, get_pass_predictions, list_orders, get_order_status, download_deliverable, create_tasking_order, create_archive_order, request_redelivery, cancel_pending_order, setup_monitoring, list_notifications, get_notification_history, delete_notification, geocode_location, create_aoi_from_point, calculate_aoi_area, whoami

## Key Architecture Decisions

### Order Confirmation Flow (Critical)
1. Agent calls `create_tasking_order` / `create_archive_order`
2. Purveyor encrypts (API key + order params) into **Fernet token** → becomes the URL
3. Returns `confirmation_url` to agent (NOT an order)
4. User opens `/confirm/{token}` in browser → sees cost, confirm/cancel buttons
5. User clicks Confirm → Purveyor decrypts in-memory, places order via SkyFi API
6. **API key NEVER stored in database** (NF-08). Token IS the credential carrier.
7. `order_confirmations` table stores only: token_hash, status, api_key_hash, skyfi_order_id

### Authentication
- **Local mode:** API key from config.json or .env file
- **Cloud mode:** `X-Skyfi-Api-Key` header per request (multi-tenant)
- **Confirmation tokens:** Fernet (AES-128-CBC + HMAC-SHA256), 30-min TTL

### Webhook Security
- Webhooks from SkyFi are **untrusted hints**
- Always verify against SkyFi API before updating state
- Shared secret in webhook URL + verification calls

## Key Files
- `src/purveyor/server.py` — MCP server (FastMCP instance at `mcp`)
- `src/purveyor/app.py` — FastAPI application (health, webhooks, confirmation pages)
- `src/purveyor/cli.py` — CLI entry point (serve, demo, generate-key)
- `src/purveyor/core/confirmation.py` — Fernet token encrypt/decrypt
- `src/purveyor/core/skyfi_client.py` — SkyFi API wrapper (httpx + tenacity)
- `src/purveyor/core/config.py` — Pydantic Settings
- `src/purveyor/tools/` — All 20 MCP tool implementations
- `src/purveyor/templates/confirm.html` — Jinja2 confirmation page
- `docs/DESIGN_DECISIONS.md` — 26 design decisions from structured interview
- `.claude/` — CLAUDE.md, rules (code-style, security, testing, prompts)

## Bugs Fixed During Development

### 1. structlog polluting stdio transport
**Problem:** `purveyor demo` crashed because structlog JSON lines went to stdout, corrupting MCP JSON-RPC messages.
**Fix:** Ensured all logging goes to stderr when running in stdio transport mode.

### 2. Different Fernet keys between demo and HTTP server
**Problem:** `purveyor demo` (stdio subprocess) and `purveyor serve --local` (HTTP server) each generated different ephemeral Fernet keys. Confirmation tokens from demo couldn't be decrypted by HTTP server → "Link Expired".
**Fix:** In local mode, persist the Fernet key to `purveyor.key` file (chmod 600, gitignored). Both processes read the same key. Also supports `CONFIRMATION_SECRET_KEY` in `.env`.

### 3. In-memory SQLite missing tables for demo
**Problem:** `create_archive_order` failed in demo because the stdio subprocess uses file-based SQLite (`purveyor.db`) which didn't have tables.
**Fix:** Run `DATABASE_URL=sqlite+aiosqlite:///purveyor.db uv run alembic upgrade head` to apply migrations.

### 4. Shapely deprecation warning
**Problem:** `WKTReadingError` deprecated in favor of `ShapelyError`.
**Fix:** Changed import to `from shapely.errors import ShapelyError`.

### 5. Docker build missing README.md
**Problem:** Dockerfile didn't COPY README.md, causing hatchling build to fail.
**Fix:** Added `COPY README.md ./` to the builder stage in Dockerfile.

## AWS Deployment — IN PROGRESS

### What's Done
- ECR repository created: `496780244141.dkr.ecr.us-east-1.amazonaws.com/purveyor`
- Docker image pushed: `purveyor:v1.0.0`
- SSM secrets stored: `/purveyor/confirmation-secret-key`, `/purveyor/skyfi-api-key`
- Terraform applied: VPC, subnets, ALB, RDS, ECS cluster, security groups all created
- ALB DNS: `purveyor-691022321.us-east-1.elb.amazonaws.com`

### Current Issue — ECS Tasks Can't Start
**Error:** `ResourceInitializationError: unable to pull secrets or registry auth: unable to retrieve secrets from ssm: The task cannot pull secrets from AWS Systems Manager. There is a connection issue between the task and AWS Systems Manager Parameter Store.`

**Root cause:** ECS tasks are in private subnets with `assign_public_ip = false` and no NAT gateway. They can't reach SSM, ECR, or the internet.

**Fix in progress (not yet applied):**
```bash
# In deploy/terraform/aws/main.tf:
# 1. Change assign_public_ip = false → true
# 2. Change subnets from private to public
sed -i 's/assign_public_ip = false/assign_public_ip = true/' main.tf
sed -i 's/subnets          = aws_subnet\.private\[\*\]\.id/subnets          = aws_subnet.public[*].id/' main.tf
terraform apply
```

### Terraform Modifications Made
- Removed HTTPS listener (no ACM certificate/domain)
- Replaced with HTTP-only listener on port 80
- Removed HTTP→HTTPS redirect listener
- Changed `depends_on` references from `aws_lb_listener.https` to `aws_lb_listener.http`
- Backup at `main.tf.bak`

### After ECS Fix, Test With
```bash
curl -s http://purveyor-691022321.us-east-1.elb.amazonaws.com/health | python -m json.tool
```

### Connect MCP Clients With
```bash
claude mcp add purveyor http://purveyor-691022321.us-east-1.elb.amazonaws.com/mcp --transport http --header "X-Skyfi-Api-Key: USERS-SKYFI-KEY"
```

Or JSON:
```json
{
  "mcpServers": {
    "purveyor": {
      "type": "http",
      "url": "http://purveyor-691022321.us-east-1.elb.amazonaws.com/mcp",
      "headers": {
        "X-Skyfi-Api-Key": "USERS-SKYFI-KEY"
      }
    }
  }
}
```

## Local Development

```bash
cd ~/Documents/projects/ai_engineering/gauntlet-curriculum/partner/week_4/skyfi-purveyor-mcp

# Install
uv sync

# Run tests
uv run pytest -m "not live" -v

# Run server locally
uv run purveyor serve --local

# Run demo agent (needs ANTHROPIC_API_KEY in .env)
uv sync --extra demo
uv run purveyor demo

# Type checking + linting
uv run mypy src/
uv run ruff check src/ tests/
```

### .env file (in project root, gitignored)
```
ANTHROPIC_API_KEY=sk-ant-...
SKYFI_API_KEY=...
LOCAL_MODE=true
CONFIRMATION_SECRET_KEY=... (44-char Fernet key)
```

### Important: Running demo + HTTP server together
Both terminals must share the same Fernet key (via .env or purveyor.key):
```bash
# Terminal 1: HTTP server (serves confirmation pages)
lsof -ti:8000 | xargs kill -9 2>/dev/null; sleep 1
uv run purveyor serve --local &

# Terminal 2: Demo agent
uv run purveyor demo
```

## Estimated AWS Monthly Cost
| Resource | Cost |
|----------|------|
| Fargate (0.5 vCPU, 1 GB) | ~$18 |
| RDS Postgres (db.t3.micro) | ~$15 |
| ALB | ~$16 |
| ECR storage | ~$1 |
| **Total** | **~$50/mo** |

## To Tear Down AWS Resources
```bash
cd deploy/terraform/aws
terraform destroy
# Also delete ECR repo:
aws ecr delete-repository --repository-name purveyor --force --region us-east-1
# Delete SSM params:
aws ssm delete-parameter --name "/purveyor/confirmation-secret-key" --region us-east-1
aws ssm delete-parameter --name "/purveyor/skyfi-api-key" --region us-east-1
```

## Remaining Work / Known Issues
1. **AWS deployment:** Apply the subnet fix (public subnets + public IP) and verify health check
2. **Demo agent in-memory DB:** Consider adding `Base.metadata.create_all()` in `init_db()` for `:memory:` databases
3. **MCP Elicitation:** Future enhancement — use `ctx.elicit_url()` for native confirmation prompts (post-V1)
4. **Live test directory:** `tests/live/` may not exist yet — was supposed to be created in Phase 4/5
5. **SkyFi API key in SSM:** The value stored was the placeholder "your-skyfi-api-key" — update with real key before production use
