# Purveyor MCP — Tools Reference

Comprehensive reference for all MCP servers and skills configured in this project.

---

## Quick Setup

Copy-paste block to reproduce the full tooling environment from scratch:

```bash
# 1. Install Node.js (required for all MCP servers via npx)
# macOS: brew install node
# Ubuntu: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs

# 2. Add MCP servers — run from the project root
claude mcp add apidog --scope project -- npx -y apidog-mcp-server@latest --oas=./docs/openapi.json
claude mcp add filesystem --scope project -- npx -y @modelcontextprotocol/server-filesystem /path/to/skyfi-purveyor-mcp
claude mcp add github --scope project -e GITHUB_PERSONAL_ACCESS_TOKEN=<your_token> -- npx -y @modelcontextprotocol/server-github
claude mcp add sequential-thinking --scope project -- npx -y @modelcontextprotocol/server-sequential-thinking
claude mcp add postgres --scope project -e POSTGRES_CONNECTION_STRING=postgresql://user:pass@localhost:5432/purveyor -- npx -y @modelcontextprotocol/server-postgres
claude mcp add context7 --scope project -- npx -y @context7/mcp-server --api-key <your_ctx7_key>
claude mcp add sentry --scope project --transport http --url https://mcp.sentry.dev/mcp

# 3. Install skills
claude skills install jeffallan/claude-skills/devops-engineer
claude skills install wshobson/agents/fastapi-templates
claude skills install anthropics/skills/mcp-builder
claude skills install github/awesome-copilot/python-mcp-server-generator

# 4. Verify
claude mcp list
claude skills list
```

> **Note:** Replace `<your_token>` and `<your_ctx7_key>` with real credentials. Never commit secrets to `.mcp.json` directly — use environment variables or a secrets manager.

---

## MCP Servers

### apidog
- **Transport:** stdio
- **Command:** `npx -y apidog-mcp-server@latest --oas=./docs/openapi.json`
- **What it does:** Serves the SkyFi OpenAPI spec (`docs/openapi.json`) as queryable MCP resources, enabling Claude to read endpoint definitions, request/response schemas, and authentication details directly.
- **When to use:**
  - **Phase 1 (Task 1.1):** Read all SkyFi API endpoint schemas when building `skyfi_client.py` and `skyfi_types.py` — avoid guessing schema shapes.
  - **Phase 2 (Tasks 2.2–2.7):** Cross-reference tool parameter names against the API spec while implementing MCP tools.
  - **Phase 3 (Tasks 3.2–3.4):** Confirm webhook payload schemas when implementing the webhook receiver and notification tools.
- **Install:**
  ```bash
  claude mcp add apidog --scope project -- npx -y apidog-mcp-server@latest --oas=./docs/openapi.json
  ```

---

### filesystem
- **Transport:** stdio
- **Command:** `npx -y @modelcontextprotocol/server-filesystem <project_root>`
- **What it does:** Exposes the project directory to Claude as readable/writable MCP resources, allowing file reads, writes, directory listings, and searches within the project tree.
- **When to use:**
  - **Phase 0 (Tasks 0.1–0.5):** Scaffold the project directory structure, create config files, and verify file layout.
  - **All phases:** Read existing source files before editing; inspect generated migration files; verify Dockerfile and docker-compose structure.
- **Install:**
  ```bash
  claude mcp add filesystem --scope project -- npx -y @modelcontextprotocol/server-filesystem /absolute/path/to/skyfi-purveyor-mcp
  ```

---

### github
- **Transport:** stdio
- **Command:** `npx -y @modelcontextprotocol/server-github`
- **Env:** `GITHUB_PERSONAL_ACCESS_TOKEN`
- **What it does:** Provides read/write access to GitHub — search repos/code, manage issues and PRs, create branches, push files, and review pull requests.
- **When to use:**
  - **Phase 5 (Task 5.3):** Create and configure the CI/CD workflow files; open PRs for review.
  - **Phase 5 (Task 5.5):** Create GitHub issue templates, CONTRIBUTING.md, and the initial release.
  - **All phases:** Look up reference implementations or upstream issues in the `modelcontextprotocol` org.
- **Install:**
  ```bash
  export GITHUB_PERSONAL_ACCESS_TOKEN=<your_token>
  claude mcp add github --scope project -e GITHUB_PERSONAL_ACCESS_TOKEN=$GITHUB_PERSONAL_ACCESS_TOKEN -- npx -y @modelcontextprotocol/server-github
  ```

---

### sequential-thinking
- **Transport:** stdio
- **Command:** `npx -y @modelcontextprotocol/server-sequential-thinking`
- **What it does:** Provides a structured step-by-step reasoning tool that helps Claude break complex problems into explicit, numbered thought steps before responding.
- **When to use:**
  - **Phase 1 (Task 1.1):** Work through the full API client design — mapping all 20+ endpoints before writing any code.
  - **Phase 3 (Task 3.1):** Reason through the confirmation token flow edge cases (expiry, double-confirm, race conditions).
  - **Phase 4 (Task 4.1):** Design the sliding window rate limiter algorithm before implementation.
  - Any task where the design space has many interdependencies and a wrong early decision is expensive to reverse.
- **Install:**
  ```bash
  claude mcp add sequential-thinking --scope project -- npx -y @modelcontextprotocol/server-sequential-thinking
  ```

---

### postgres
- **Transport:** stdio
- **Command:** `npx -y @modelcontextprotocol/server-postgres`
- **Env:** `POSTGRES_CONNECTION_STRING`
- **What it does:** Connects to the local Postgres database and lets Claude run SQL queries, inspect schemas, and validate migrations directly.
- **When to use:**
  - **Phase 0 (Task 0.4):** Verify Alembic migrations created the correct table schemas and column types.
  - **Phase 3 (Tasks 3.1, 3.3):** Inspect `order_confirmations` and `webhook_events` table state during debugging.
  - **Phase 4 (Task 4.3):** Query test data when diagnosing integration test failures against a real Postgres+PostGIS instance.
- **Install:**
  ```bash
  export POSTGRES_CONNECTION_STRING=postgresql://user:pass@localhost:5432/purveyor
  claude mcp add postgres --scope project -e POSTGRES_CONNECTION_STRING=$POSTGRES_CONNECTION_STRING -- npx -y @modelcontextprotocol/server-postgres
  ```

---

### context7
- **Transport:** stdio
- **Command:** `npx -y @context7/mcp-server --api-key <key>`
- **What it does:** Fetches up-to-date library documentation and code examples for any package, so Claude can reference current API docs without relying on training data.
- **When to use:**
  - **Phase 1 (Task 1.1):** Look up current `httpx.AsyncClient` and `tenacity` retry decorator APIs.
  - **Phase 1 (Task 1.2):** Fetch `cachetools.TTLCache` and `redis.asyncio` docs.
  - **Phase 2 (Task 2.1):** Look up the current `mcp` Python SDK API for server initialization and Streamable HTTP transport.
  - **Phase 2 (Task 2.2):** Check `geopy`, `shapely`, and `pyproj` APIs for geospatial operations.
  - **Phase 0 (Task 0.4):** Verify SQLAlchemy 2.0 async session patterns and Alembic async config.
- **Install:**
  ```bash
  claude mcp add context7 --scope project -- npx -y @context7/mcp-server --api-key <your_ctx7_key>
  ```

---

### sentry
- **Transport:** http
- **URL:** `https://mcp.sentry.dev/mcp`
- **What it does:** Connects Claude to Sentry's remote MCP endpoint, enabling issue lookup, error trace inspection, and release management directly from Claude Code.
- **When to use:**
  - **Phase 4 (Task 4.2):** Verify Sentry integration is capturing exceptions correctly; inspect example error events.
  - **Phase 5 (Task 5.5):** Confirm no production errors appear after the initial release.
  - Any time a production error needs root-cause analysis — pull the full stack trace via Sentry MCP rather than copy-pasting from the dashboard.
- **Install:**
  ```bash
  claude mcp add sentry --scope project --transport http --url https://mcp.sentry.dev/mcp
  ```

---

## Skills

### devops-engineer
- **Source:** `jeffallan/claude-skills`
- **What it does:** Transforms Claude into a senior DevOps engineer that creates Dockerfiles, CI/CD pipeline configs, Kubernetes manifests, Terraform modules, GitHub Actions workflows, and incident runbooks.
- **Triggers:** Invoked when the user asks about CI/CD, Docker, Kubernetes, GitOps, Terraform, deployment automation, GitHub Actions, on-call, or platform engineering. Also triggered by the `/devops-engineer` slash command.
- **Relevant phases:**
  - **Phase 0 (Task 0.5):** Write the multi-stage Dockerfile and docker-compose profiles.
  - **Phase 5 (Task 5.3):** Create `.github/workflows/ci.yml` and `release.yml`.
  - **Phase 5 (Task 5.4):** Generate Terraform modules for AWS (ECS Fargate + RDS) and GCP (Cloud Run + Cloud SQL).
- **Install:**
  ```bash
  claude skills install jeffallan/claude-skills/devops-engineer
  ```

---

### fastapi-templates
- **Source:** `wshobson/agents`
- **What it does:** Generates production-ready FastAPI applications with async patterns, dependency injection, middleware, and comprehensive error handling boilerplate.
- **Triggers:** Invoked when building new FastAPI applications or setting up backend API projects. Also triggered by the `/fastapi-templates` slash command.
- **Relevant phases:**
  - **Phase 2 (Task 2.1):** Scaffold `src/purveyor/app.py` with lifespan handlers, CORS middleware, health endpoints, and route mounting for MCP and webhooks.
  - **Phase 3 (Tasks 3.1, 3.3):** Add confirmation page routes and webhook receiver endpoints following FastAPI best practices.
- **Install:**
  ```bash
  claude skills install wshobson/agents/fastapi-templates
  ```

---

### mcp-builder
- **Source:** `anthropics/skills`
- **What it does:** Provides expert guidance for building high-quality MCP servers — covering tool design, resource patterns, Python FastMCP and TypeScript SDK usage, and evaluation best practices.
- **Triggers:** Invoked when building MCP servers or integrating external APIs as MCP tools. Also triggered by the `/mcp-builder` slash command.
- **Relevant phases:**
  - **Phase 2 (Task 2.1):** Set up the MCP server with correct capability declarations, session management, and Streamable HTTP transport.
  - **Phase 2 (Tasks 2.2–2.7):** Design each MCP tool with proper annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`), input schemas, and human-readable output summaries.
  - **Phase 2 (Task 2.7):** Implement MCP resources with correct URI schemes and subscription support.
- **Install:**
  ```bash
  claude skills install anthropics/skills/mcp-builder
  ```

---

### python-mcp-server-generator
- **Source:** `github/awesome-copilot`
- **What it does:** Generates a complete MCP server project in Python with tools, resources, proper `pyproject.toml`, and configuration — useful for rapid scaffolding of new server projects.
- **Triggers:** Invoked when generating a new MCP server project structure. Also triggered by the `/python-mcp-server-generator` slash command.
- **Relevant phases:**
  - **Phase 0 (Task 0.1):** Use as a reference scaffold when setting up `src/purveyor/` structure and `pyproject.toml` dependencies.
  - **Phase 2 (Task 2.1):** Cross-reference generated patterns when wiring up tool handlers and server context.
- **Install:**
  ```bash
  claude skills install github/awesome-copilot/python-mcp-server-generator
  ```

---

## Tool-to-Phase Matrix

| Phase / Task | apidog | filesystem | github | seq-thinking | postgres | context7 | sentry | devops-engineer | fastapi-templates | mcp-builder | py-mcp-gen |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 0.1 Project scaffold | | ✓ | | | | | | | | | ✓ |
| 0.2–0.3 Logging/Config | | ✓ | | | | ✓ | | | | | |
| 0.4 Database/Alembic | | ✓ | | | ✓ | ✓ | | | | | |
| 0.5 Docker/Compose | | ✓ | | | | | | ✓ | | | |
| 1.1 SkyFi API client | ✓ | ✓ | | ✓ | | ✓ | | | | | |
| 1.2 Cache layer | | ✓ | | | | ✓ | | | | | |
| 1.3 Auth provider | ✓ | ✓ | | | | ✓ | | | | | |
| 2.1 MCP server setup | ✓ | ✓ | | | | ✓ | | | ✓ | ✓ | ✓ |
| 2.2–2.7 MCP tools | ✓ | ✓ | | | | ✓ | | | | ✓ | |
| 3.1 Confirmation flow | ✓ | ✓ | | ✓ | ✓ | | | | ✓ | | |
| 3.2–3.4 Orders/Webhooks | ✓ | ✓ | | | ✓ | | | | ✓ | | |
| 4.1 Rate limiting | | ✓ | | ✓ | | ✓ | | | | | |
| 4.2 Sentry/Health | | ✓ | | | ✓ | | ✓ | | | | |
| 4.3 Test suite | | ✓ | | | ✓ | | | | | | |
| 5.1 Demo agent | | ✓ | | | | ✓ | | | | | |
| 5.2 Docs | | ✓ | ✓ | | | | | | | | |
| 5.3 CI/CD | | | ✓ | | | | | ✓ | | | |
| 5.4 Terraform IaC | | | ✓ | | | | | ✓ | | | |
| 5.5 Final polish | | ✓ | ✓ | | | | ✓ | | | | |
