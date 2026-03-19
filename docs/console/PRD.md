# Purveyor Console — Product Requirements Document

## Problem Statement

Purveyor is a remote MCP server that wraps SkyFi's satellite imagery API. While technically capable and well-architected, it is invisible to non-technical audiences: there is no visual interface demonstrating what it does or why it matters. A text-only CLI demo fails to communicate the geographic nature of the product — satellite imagery is fundamentally visual and spatial.

The Purveyor Console solves this by providing a split-view demo application: a conversational chat panel on the left where an AI agent uses Purveyor's tools, and an interactive map on the right that reacts in real time to every tool call. When the agent searches for satellite imagery over Los Angeles, footprint markers appear on the map. When it draws an area of interest, a polygon materializes. When it generates a tasking order, an inline confirmation widget replaces the click-away URL.

This makes Purveyor legible to every audience simultaneously.

---

## User Personas

### Demo Presenter
A developer or founder running a live or recorded demo for an external audience. Needs to complete a full search → order → confirm flow in under 2 minutes without surprises. Values reliability above all: no broken loading states, no silent failures, no map that doesn't update. Uses pre-built scenario buttons to start scripted flows.

### Investor / Executive Watching Demo
No technical background in MCP or satellite imagery. Needs to immediately understand the value proposition: "AI agent that finds and orders satellite imagery, visually, in real time." Key moments that land: the map flying to a typed location, archive thumbnail cards appearing in chat, the cost clearly displayed before confirming an order. Does not read tool JSON.

### Developer Evaluating MCP Integration
Wants to understand Purveyor as a buildable platform. Needs to see the MCP tool calls firing — what inputs go in, what structured outputs come back. Will toggle the "View MCP Calls" panel to inspect raw tool I/O. Interested in the LangGraph agent architecture and how the map sync works. May want to clone the console repo and run it locally against a self-hosted Purveyor instance.

### Enterprise Customer Evaluating SkyFi + AI
Evaluating whether to build satellite imagery workflows into their platform. Needs to see: imagery search by location name, cost transparency before ordering, in-app order confirmation (not a redirect), monitoring setup. Cares about the full workflow being self-contained.

---

## Functional Requirements

### P0 — Must Have for Demo

**P0.1 — Chat Panel with Streaming Responses**
The left panel displays a conversation. User messages appear immediately. Agent responses stream token-by-token. Tool call loading indicators appear while tools execute. The panel is scrollable with the most recent message always visible.

**P0.2 — Interactive Map Panel**
The right panel shows a full-height MapLibre GL JS map. Default view is the contiguous United States at zoom ~4. The map is interactive (pan, zoom, click markers) at all times, including while the agent is responding.

**P0.3 — Map Syncs with Tool Results**
Tool results are parsed from the SSE stream and dispatched to the map in real time:
- `geocode_location` → map flies to the resolved location
- `search_archives` → archive footprint markers plotted with metadata popups
- `create_aoi_from_point` → AOI polygon drawn in blue, map fits bounds
- `calculate_aoi_area` → area label added to existing polygon

**P0.4 — Archive Result Cards**
When `search_archives` returns results, each archive renders as a card in the chat (via custom ToolUI component). Cards show: provider logo/name, resolution tier, capture date, cloud cover percentage, estimated price, thumbnail image (if available), and a "View on SkyFi" link. Cards are compact and scannable.

**P0.5 — Inline Order Confirmation Widget**
When `create_archive_order` or `create_tasking_order` returns a `confirmation_url`, the chat renders an inline confirmation card instead of showing a bare URL. The card shows: order type, location description, product/resolution, estimated cost (prominent), cost breakdown. Two buttons: "Confirm Order" (green) and "Cancel" (gray). Clicking Confirm POSTs `action=confirm` to Purveyor's `/confirm/{token}` endpoint. Clicking Cancel POSTs `action=cancel`. Success and error states are shown inline.

**P0.6 — Pre-Built Demo Scenario Buttons**
Three scenario buttons appear above the chat input:
- **Research** — "Find recent high-resolution imagery of the Port of Los Angeles"
- **Order** — "Search for and order cloud-free imagery of the Suez Canal from the last 30 days"
- **Monitor** — "Set up monitoring for new imagery over Donetsk, Ukraine"

Clicking a button populates the chat input and auto-submits, starting the scripted flow.

**P0.7 — Connection Status Bar**
A slim status bar at the top shows: Purveyor connection status (connected/disconnected), current user email (from `whoami`), and active order count.

---

### P1 — Impressive Polish

**P1.1 — Feasibility Overlay**
When `check_feasibility` returns results, a color-coded circle overlay appears on the map at the AOI centroid: green (high feasibility score), yellow (medium), red (low). Clicking the overlay shows the full feasibility breakdown in a popup.

**P1.2 — Satellite Pass Tracks**
When `get_pass_predictions` returns results, satellite ground tracks are drawn as curved lines on the map. Each track is labeled with the satellite name and overpass time. Clicking a track shows a popup with full pass details.

**P1.3 — Monitoring Zone Rendering**
When `setup_monitoring` succeeds, the monitored AOI is drawn in green with a pulsing border animation. A label shows "Monitoring Active" with the notification ID. The zone persists on the map for the session.

**P1.4 — Pricing Comparison Table**
When `get_pricing` returns results, a structured table renders in the chat showing: provider, product type, resolution tier, and price per sq km. Rows are grouped by resolution tier. The cheapest option per tier is highlighted.

**P1.5 — Developer MCP Inspector**
A toggle button in the header labeled "MCP Calls" shows/hides an expandable panel below each agent message. The panel shows all tool calls made during that message turn, with three tabs per call: Tool Name, Input JSON (pretty-printed), Output JSON (pretty-printed). Useful for developers to understand what Purveyor is returning.

**P1.6 — Order History Panel**
A slide-out drawer (triggered by clicking an "Orders" button in the status bar) shows a list of orders placed during the session: order ID, type, location, status, cost. Each row is expandable to show full order details.

---

### P2 — Nice to Have

**P2.1 — Dark Mode**
Full dark mode via Tailwind dark class toggle. Preserves all map colors and tool card readability.

**P2.2 — Shareable Demo Links**
URL encodes the first user message so `/console?demo=research` pre-populates and auto-starts the Research scenario. Useful for async demos where the recipient runs it themselves.

**P2.3 — Export Conversation**
"Export" button in the header downloads the current conversation as a Markdown file with tool call results included as code blocks.

**P2.4 — Responsive Layout**
Layout degrades gracefully down to 1024px viewport width. Below 768px, map panel hides and chat is full-width (mobile is out of scope for demo).

**P2.5 — Webhook Notification Toast**
If a monitoring webhook fires during the session, a toast notification appears: "New imagery detected over [location] — [provider], [date]."

---

## Non-Functional Requirements

- **Performance:** Initial page load under 3 seconds on a standard broadband connection. Map tiles load within 1 second of navigation. Tool result cards render within 100ms of receiving the SSE `tool_result` event.
- **Browser support:** Chrome 120+, Firefox 120+, Safari 17+. No Internet Explorer.
- **Minimum viewport:** 1024px width. Layout does not break below this until 768px.
- **Reliability:** If Purveyor MCP is unreachable, show a clear error in the status bar and in the chat. No silent failures. If OpenAI is rate-limited, show a "thinking..." indicator and retry.
- **Security:** SkyFi API key is sent from the frontend to the LangGraph backend via HTTPS only. Key is never stored in localStorage or cookies. Key is passed per-request and held in memory only.

---

## Success Metrics

The primary success metric is demo completability:

> **A presenter with no preparation can complete a full Search → Order → Confirm flow in under 2 minutes during a live demo.**

Secondary metrics:
- All three pre-built scenario buttons work end-to-end without errors
- Map updates are visible within 500ms of receiving a tool result
- Developer toggle shows accurate tool I/O for every call
- Confirmation widget successfully places a real order via Purveyor's confirmation endpoint
- No page reloads required during a demo session

---

## Out of Scope

- Multi-user sessions or authentication to the Console itself (single-user demo app)
- Persistent conversation history across page reloads
- Mobile layout (below 768px)
- Direct SkyFi API calls from the frontend (all SkyFi calls go through Purveyor MCP)
- The Console is not a production application — it is a demonstration tool
