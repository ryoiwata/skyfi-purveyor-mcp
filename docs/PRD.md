# Purveyor — Product Requirements Document

**Version:** 1.0
**Project:** SkyFi MCP Server (codename: Purveyor)
**Status:** Pre-implementation
**Stakeholders:** SkyFi Engineering, SkyFi Product, Open Source Community

## 1. Problem Statement

AI systems are becoming the primary interface for an increasing share of professional workflows. In software development, research, and data analysis, AI agents already drive purchasing and provisioning decisions — choosing hosting providers, data sources, and API services on behalf of users. This trend is expanding into new verticals as agents are deployed more broadly.

Earth observation and satellite imagery is a natural fit for agentic workflows. Analysts, researchers, and operations teams frequently need to search for imagery, evaluate feasibility, compare pricing, place orders, and monitor areas of interest. Today, these steps require manual navigation of the SkyFi platform UI or direct API integration — neither of which works well when an AI agent is orchestrating the workflow.

Purveyor bridges this gap by giving any MCP-compatible AI agent native access to SkyFi's full platform capabilities through conversational interaction, while maintaining human oversight for any action that involves spending money.

## 2. Goals

### 2.1 Primary Goals

1. **Enable conversational satellite imagery ordering** — An AI agent can guide a user through the entire workflow: search → feasibility → pricing → order → delivery, all through natural language conversation.

2. **Maintain human control over purchases** — No order is placed without explicit human confirmation via an out-of-band approval step. The agent facilitates; the human decides.

3. **Work with every major AI platform** — Purveyor must function as a remote MCP server compatible with Claude Web, OpenAI, Gemini, LangChain, Google ADK, Vercel AI SDK, and any future MCP-compliant client.

4. **Support both local and cloud deployment** — A single developer can run Purveyor locally with minimal setup. A team can deploy it to cloud infrastructure for multi-user access.

5. **Ship as polished open source** — The project will be open-sourced. Documentation, code quality, and developer experience must be production-grade from day one.

### 2.2 Success Metrics

| Metric | Target |
|--------|--------|
| Time from "I need an image of X" to order confirmation URL | < 60 seconds for archive orders |
| MCP client compatibility | Verified working with Claude Web, OpenAI, and at least 2 framework integrations |
| Self-hosted setup time (local mode) | < 5 minutes from git clone to working server |
| SkyFi API coverage | 100% of public Platform API endpoints exposed as tools |
| Open source readiness | Complete docs, CI/CD, contributing guide, MIT license |

### 2.3 Non-Goals

- **Payment processing** — Purveyor facilitates the payment flow but does not process payments directly. SkyFi handles billing.
- **Image analysis** — Purveyor delivers imagery to the user's storage. Analysis of the imagery is out of scope.
- **Custom AI models** — The demo agent uses existing LLM APIs. No custom model training.
- **Mobile app** — Purveyor is a server-side component consumed by AI agents.

## 3. User Personas

### 3.1 The Analyst (End User)

**Who:** A geospatial analyst, researcher, or operations professional who uses AI assistants (Claude, ChatGPT, etc.) in their daily work.

**Need:** "I want to ask my AI assistant to find and order satellite imagery of a location without switching to a separate platform, remembering API parameters, or navigating a complex UI."

**Workflow:**
- "Show me recent high-res imagery of the Port of Rotterdam"
- "What would a new tasking order cost for this area at 50cm resolution?"
- "Is there a satellite pass over this location next week?"
- "Order the best archive image from the results — I'll confirm before it charges me"
- "Set up monitoring for new imagery of this area and notify me when something comes in"

### 3.2 The Agent Developer (Integrator)

**Who:** A developer building AI agents or workflows that need satellite imagery as a data source.

**Need:** "I want to add satellite imagery capabilities to my agent with minimal integration effort. I need clear documentation, a standard protocol, and reliable behavior."

**Workflow:**
- Connect to Purveyor as a remote MCP server
- Discover available tools via capability negotiation
- Build workflows that chain imagery search, feasibility checks, and ordering
- Handle the human confirmation step in their application's UI
- Receive webhook notifications for order completion and monitoring alerts

### 3.3 The Platform Operator (Self-Hoster)

**Who:** A DevOps engineer or team lead setting up Purveyor for their organization.

**Need:** "I want to deploy this for my team with appropriate security, observability, and infrastructure. I don't want to run 10 containers for a simple deployment."

**Workflow:**
- Choose a deployment profile (minimal, standard, full)
- Configure authentication for multi-user access
- Set up cloud storage delivery targets
- Monitor health and usage

## 4. Functional Requirements

### 4.1 Archive Search and Exploration

| ID | Requirement | Priority |
|----|-------------|----------|
| F-ARCH-01 | Users can search the SkyFi archive catalog by location (place name or coordinates), date range, resolution, product type, cloud cover, and provider | P0 |
| F-ARCH-02 | Location can be specified as a place name (resolved via OpenStreetMap) or WKT polygon | P0 |
| F-ARCH-03 | Search results include thumbnail URLs, pricing, metadata, and overlap information | P0 |
| F-ARCH-04 | Users can paginate through search results iteratively | P0 |
| F-ARCH-05 | Users can get full details for a specific archive image by ID | P0 |
| F-ARCH-06 | Search results are cached to reduce latency on follow-up queries | P1 |

### 4.2 Pricing Exploration

| ID | Requirement | Priority |
|----|-------------|----------|
| F-PRICE-01 | Users can explore pricing for all product types, resolutions, and providers | P0 |
| F-PRICE-02 | Pricing can be filtered by product type and resolution | P0 |
| F-PRICE-03 | When an AOI is provided, pricing includes area-based cost estimates | P0 |
| F-PRICE-04 | Pricing responses are cached with a 5-minute TTL | P1 |

### 4.3 Feasibility and Pass Prediction

| ID | Requirement | Priority |
|----|-------------|----------|
| F-FEAS-01 | Users can check feasibility for a tasking order (AOI + product + resolution + date range) | P0 |
| F-FEAS-02 | Feasibility results include overall score, weather score, and per-provider availability | P0 |
| F-FEAS-03 | Users can view upcoming satellite passes over an area of interest | P0 |
| F-FEAS-04 | Pass predictions include satellite ID, timing, off-nadir angle, and pricing | P0 |
| F-FEAS-05 | Users can select a specific pass from predictions for their tasking order | P1 |

### 4.4 Order Placement

| ID | Requirement | Priority |
|----|-------------|----------|
| F-ORD-01 | Users can initiate a tasking order (future satellite capture) | P0 |
| F-ORD-02 | Users can initiate an archive order (existing imagery) | P0 |
| F-ORD-03 | **All orders require human confirmation before placement** — the tool returns a confirmation URL, not a completed order | P0 |
| F-ORD-04 | The confirmation page shows order details, estimated cost, and a confirm/cancel action | P0 |
| F-ORD-05 | Confirmation tokens expire after 30 minutes | P0 |
| F-ORD-06 | After human confirmation, the order is placed via SkyFi API and the agent is notified | P0 |
| F-ORD-07 | Users can specify delivery to S3, GCS, or Azure Blob Storage | P0 |
| F-ORD-08 | Users can include custom metadata on orders | P2 |

### 4.5 Order Management

| ID | Requirement | Priority |
|----|-------------|----------|
| F-OMGMT-01 | Users can list their previous orders with filtering by type (archive/tasking) | P0 |
| F-OMGMT-02 | Users can check the status and event history of a specific order | P0 |
| F-OMGMT-03 | Users can download deliverables (image, payload, COG) for completed orders | P0 |
| F-OMGMT-04 | Users can request redelivery to a different storage bucket | P1 |
| F-OMGMT-05 | The agent is notified via webhook when order status changes | P0 |

### 4.6 AOI Monitoring and Notifications

| ID | Requirement | Priority |
|----|-------------|----------|
| F-MON-01 | Users can set up monitoring for an AOI with optional filters (GSD, product type) | P0 |
| F-MON-02 | Monitoring delivers webhook notifications when new matching imagery is ingested | P0 |
| F-MON-03 | Users can list, view history, and delete active monitors | P0 |
| F-MON-04 | The agent is notified when a monitor triggers, enabling conversational follow-up ("New imagery is available for your monitored area — would you like to order it?") | P0 |

### 4.7 Authentication

| ID | Requirement | Priority |
|----|-------------|----------|
| F-AUTH-01 | Local mode: credentials stored in a JSON config file | P0 |
| F-AUTH-02 | Cloud mode: credentials sent in request headers (X-Skyfi-Api-Key) | P0 |
| F-AUTH-03 | Users can check their account info, budget, and payment status via `whoami` | P0 |
| F-AUTH-04 | Cloud OAuth provider implementation for SSO integrations | P2 |

### 4.8 Geospatial Tools

| ID | Requirement | Priority |
|----|-------------|----------|
| F-GEO-01 | Resolve place names to coordinates and bounding boxes via OpenStreetMap | P0 |
| F-GEO-02 | Generate AOI polygons from a center point and desired area | P0 |
| F-GEO-03 | Calculate AOI area in square kilometers with validation | P0 |
| F-GEO-04 | Validate WKT polygons (vertex count, area limits, convexity) before sending to SkyFi | P0 |

### 4.9 Transport and Protocol

| ID | Requirement | Priority |
|----|-------------|----------|
| F-TRANS-01 | Implement Streamable HTTP transport (single `/mcp` endpoint) per updated MCP spec | P0 |
| F-TRANS-02 | Support JSON-RPC batching | P1 |
| F-TRANS-03 | Support capability negotiation on `initialize` | P0 |
| F-TRANS-04 | Include tool annotations (readOnly, destructive, idempotent, requiresConfirmation) | P1 |
| F-TRANS-05 | Optional legacy `/sse` endpoint for backwards compatibility | P2 |

### 4.10 Documentation and Integration Guides

| ID | Requirement | Priority |
|----|-------------|----------|
| F-DOC-01 | README with quickstart, architecture overview, and configuration reference | P0 |
| F-DOC-02 | Integration guide for Claude Web (remote MCP) | P0 |
| F-DOC-03 | Integration guide for OpenAI (remote MCP) | P0 |
| F-DOC-04 | Integration guide for Anthropic API | P0 |
| F-DOC-05 | Integration guide for Google Gemini | P1 |
| F-DOC-06 | Integration guide for LangChain/LangGraph | P0 |
| F-DOC-07 | Integration guide for Google ADK | P1 |
| F-DOC-08 | Integration guide for Vercel AI SDK | P1 |
| F-DOC-09 | Demo agent with example workflows | P0 |
| F-DOC-10 | Contributing guide for open source contributors | P1 |

### 4.11 Deployment

| ID | Requirement | Priority |
|----|-------------|----------|
| F-DEPLOY-01 | Local mode with SQLite — no external dependencies | P0 |
| F-DEPLOY-02 | Docker image that works on Fargate, Cloud Run, and docker-compose | P0 |
| F-DEPLOY-03 | Docker-compose with `minimal`, `standard`, and `full` profiles | P0 |
| F-DEPLOY-04 | Terraform IaC for AWS Fargate | P1 |
| F-DEPLOY-05 | Terraform IaC for Google Cloud Run | P1 |
| F-DEPLOY-06 | Caddy reverse proxy for self-hosted HTTPS | P1 |

## 5. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NF-01 | Response latency for cached read operations | < 200ms |
| NF-02 | Response latency for uncached SkyFi API calls | < 5s (dependent on SkyFi API) |
| NF-03 | Server startup time | < 5 seconds |
| NF-04 | Memory footprint (local mode) | < 256 MB |
| NF-05 | Concurrent MCP sessions (cloud mode) | 100+ |
| NF-06 | Test coverage | > 80% line coverage |
| NF-07 | Type coverage | 100% (mypy strict) |
| NF-08 | Zero credentials stored server-side in cloud mode | Mandatory |

## 6. Open Data Support

SkyFi provides free Sentinel-1 and Sentinel-2 imagery through their open data program. Purveyor should make this accessible:

- `search_archives` with `open_data=true` returns free imagery
- `create_archive_order` works with open data archives at zero cost
- Demo workflows should start with open data to let users explore without payment
- Free accounts can place up to 1 open data order/day; Pro accounts up to 5/day

## 7. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| SkyFi API rate limits hit during agent conversations | Agent receives errors, poor UX | Medium | Tiered caching, tenacity retries, rate limiting awareness in tool responses |
| Human skips confirmation, expects agent to auto-order | Confusion, no order placed | Medium | Clear tool response text: "I've prepared your order. Please click this link to review and confirm before it's placed." |
| MCP spec changes break compatibility | Client connections fail | Low | Pin to spec version, monitor MCP changelog, maintain backwards-compatible `/sse` endpoint |
| Self-hosted users overwhelmed by infrastructure | Abandonment | Medium | Progressive profiles (minimal/standard/full), SQLite local mode |
| SkyFi API schema changes | Tool errors | Medium | Pydantic validation surfaces issues clearly; version-pin OpenAPI spec |

## 8. Future Considerations (Post-1.0)

- **Analytics integration** — Expose SkyFi's analytics products (object detection, stockpile measurement) as MCP tools
- **Multi-order workflows** — Agent-orchestrated batch ordering across multiple AOIs
- **Cost optimization agent** — Recommend the best product/resolution/provider combination for a budget
- **Persistent agent memory** — Remember user preferences, frequently monitored areas, delivery configurations
- **Maritime AIS integration** — Combine vessel tracking with satellite imagery ordering
- **ATAK plugin coordination** — Bridge between field operators (ATAK) and agent-driven imagery procurement
