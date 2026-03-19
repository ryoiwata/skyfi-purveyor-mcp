# Purveyor Console — Implementation Plan

## Overview

7-day build plan for the Purveyor Console split-view demo UI. Each day has clear acceptance criteria. Tasks within a day can be parallelized by two developers if available.

**Repository structure:**
```
skyfi-purveyor-mcp/
└── console/
    ├── frontend/     # Next.js 14 app
    └── agent/        # Python LangGraph FastAPI backend
```

Both live in the same monorepo as Purveyor for simplicity. A developer working solo should treat days as milestones rather than strict calendar days.

---

## Day 1: Scaffold + LangGraph Agent

**Goal:** A working chat that calls Purveyor tools and streams responses. Map is not yet involved.

### Task 1.1 — Scaffold Next.js Frontend
**Location:** `console/frontend/`

```bash
cd console
npx create-next-app@14 frontend \
  --typescript --tailwind --eslint --app --src-dir=false --import-alias="@/*"
cd frontend
npx shadcn@latest init
npx shadcn@latest add button card badge input separator
npm install @assistant-ui/react
```

Create `app/page.tsx` with a placeholder split-view layout:
- Left: gray panel with text "Chat panel coming"
- Right: gray panel with text "Map panel coming"
- Top: status bar strip

No functionality yet — just structure and styles.

**Acceptance:** `npm run dev` shows split-view layout at localhost:3000.

---

### Task 1.2 — Scaffold Python Agent Backend
**Location:** `console/agent/`

```bash
mkdir -p console/agent
cd console/agent
python -m venv .venv && source .venv/bin/activate
pip install langgraph langchain-openai langchain-mcp-adapters fastapi uvicorn python-dotenv structlog pydantic
```

Create `agent/main.py`:
- Define `AgentState` TypedDict with `messages` and `current_aoi`
- Define `call_model` node: instantiates `ChatOpenAI(model="gpt-4o")`, binds Purveyor tools, invokes with messages
- Define `call_tools` node: uses `ToolNode` to execute tool calls
- Define `should_continue` edge function
- Compile `StateGraph` into `graph`

Create `agent/tools.py`:
- `get_purveyor_tools(skyfi_api_key: str) -> list` function
- Uses `MultiServerMCPClient` with `streamable_http` transport
- `PURVEYOR_MCP_URL` from environment variable

Create `.env` in `agent/`:
```
OPENAI_API_KEY=sk-...
PURVEYOR_MCP_URL=http://purveyor-691022321.us-east-1.elb.amazonaws.com/mcp
```

**Test manually:** Write a test script `agent/test_agent.py`:
```python
import asyncio
from main import graph

async def test():
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "Who am I? Use the whoami tool."}]},
        config={"configurable": {"skyfi_api_key": "test-key"}},
    )
    print(result["messages"][-1].content)

asyncio.run(test())
```

**Acceptance:** `python test_agent.py` returns account info from `whoami` tool. Tool call visible in console output.

---

### Task 1.3 — FastAPI Streaming Endpoint
**Location:** `console/agent/server.py`

Implement `POST /api/chat` using `StreamingResponse` + `astream_events`.

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ChatRequest(BaseModel):
    messages: list[dict]
    skyfi_api_key: str

@app.post("/api/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(
        stream_agent(request.messages, request.skyfi_api_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

async def stream_agent(messages: list, skyfi_api_key: str):
    config = {"configurable": {"skyfi_api_key": skyfi_api_key}}
    async for event in graph.astream_events(
        {"messages": messages, "current_aoi": None},
        config=config, version="v2",
    ):
        # ... parse events and yield SSE strings
        yield format_sse(...)
    yield "event: done\ndata: {}\n\n"

@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

Run with: `uvicorn server:app --reload --port 8001`

**Acceptance:** `curl -N -X POST http://localhost:8001/api/chat -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"Hello"}],"skyfi_api_key":"test"}'` streams SSE events to console.

---

### Task 1.4 — Basic Chat Panel in Next.js
**Location:** `console/frontend/`

Install SSE client utility:
```bash
npm install eventsource-parser
```

Create `lib/sse-client.ts`: function `streamChat(messages, apiKey)` that returns an async iterator of typed SSE events.

Create `lib/runtime.ts`: custom assistant-ui `ChatModelAdapter` that calls the LangGraph backend.

Replace placeholder in `app/page.tsx` left panel with `<ChatPanel />` using `<Thread />` from assistant-ui.

Wire up settings: add a small input in the UI for the SkyFi API key (stored in React state for now).

**Acceptance:** Type "What tools do you have?" in the chat, see streaming response listing Purveyor's tools. Tool calls visible as loading indicators.

---

### Day 1 Acceptance Criteria
- [ ] Split-view layout renders at localhost:3000
- [ ] LangGraph agent calls Purveyor's `whoami` tool successfully
- [ ] FastAPI backend streams SSE events with `text_delta` and `tool_result` types
- [ ] Chat panel in browser shows streaming responses from LangGraph agent
- [ ] No hardcoded API keys anywhere — all from env vars

---

## Day 2: Map Panel + Location Sync

**Goal:** The map panel is live and syncs with location-related tool results.

### Task 2.1 — MapLibre GL JS Setup
**Location:** `console/frontend/`

```bash
npm install maplibre-gl @types/maplibre-gl
```

Create `components/map/MapPanel.tsx`:
- Initialize MapLibre map in `useEffect` with `containerRef`
- Style: `https://tiles.openfreemap.org/styles/liberty`
- Default center: `[-98.5, 39.5]`, zoom: `4` (continental US)
- Add navigation controls
- Expose `map` instance via `useImperativeHandle` or context

Add MapLibre CSS import to `app/layout.tsx`:
```typescript
import "maplibre-gl/dist/maplibre-gl.css";
```

**Acceptance:** Right panel shows an interactive world map.

---

### Task 2.2 — Map Context
**Location:** `components/map/MapContext.tsx`

Define `MapAction` union type (see SPEC.md). Implement `MapContextProvider` with:
- `mapRef` (ref to the MapLibre instance)
- `dispatch(action: MapAction)` function that applies actions to the map
- `registerMap(map: maplibregl.Map)` called once map is initialized

Implement the `dispatch` function as a switch over `MapAction.type`. Start with just `FLY_TO` and `DRAW_AOI` — add others as needed in later tasks.

---

### Task 2.3 — MapSync Component
**Location:** `components/map/MapSync.tsx`

Create an invisible component that:
1. Subscribes to tool results from the SSE stream (via React context or event bus)
2. Calls `parseToolResultToMapAction(tool, output)` (see SPEC.md)
3. Dispatches resulting `MapAction` to `MapContext`

The SSE stream events need to be accessible beyond the chat runtime. Add a `ToolResultEmitter` (simple EventTarget or mitt instance) that the runtime emits to, and MapSync listens to.

---

### Task 2.4 — Implement FLY_TO and DRAW_AOI
Implement `FLY_TO` in the `dispatch` function:
```typescript
map.flyTo({ center: action.center, zoom: action.zoom ?? 12, duration: 1500 });
```

Implement `DRAW_AOI`:
```bash
npm install wellknown @turf/bbox @turf/centroid
```
- Parse WKT → GeoJSON using `wellknown.parse()`
- Add/update `"aoi"` source and `"aoi-fill"` / `"aoi-line"` layers
- Fit bounds using `@turf/bbox`
- If label provided, add text annotation at centroid

---

### Task 2.5 — Split-View Layout with Resizable Panels
Replace the static 50/50 split with a resizable two-panel layout using CSS or a library:
- Default: 40% chat / 60% map
- Drag handle in the middle
- Minimum widths: chat 320px, map 400px
- Both panels are full-height (viewport height minus status bar)

Consider `react-resizable-panels` library:
```bash
npm install react-resizable-panels
```

**Acceptance:** Type "Fly to Los Angeles" → map flies to LA. Say "Create an AOI around downtown Austin" → blue polygon appears around Austin, map fits to it.

---

### Day 2 Acceptance Criteria
- [ ] Interactive MapLibre map renders in right panel
- [ ] `geocode_location` tool result → map flies to location
- [ ] `create_aoi_from_point` tool result → blue polygon appears on map
- [ ] `calculate_aoi_area` tool result → area label appears on polygon
- [ ] Panels are resizable by dragging

---

## Day 3: Archive Search + Result Cards

**Goal:** Archive search results show as both cards in chat and markers on the map.

### Task 3.1 — PLOT_ARCHIVES Map Action
Implement `PLOT_ARCHIVES` in the map dispatch:
- Build GeoJSON FeatureCollection from archive `footprint_wkt` fields
- Provider-to-color mapping (see SPEC.md)
- Add `"archives"` GeoJSON source and `"archives-circles"` layer
- Add click handler: `map.on("click", "archives-circles", ...)` → opens popup

Archive popup HTML template (inline):
```typescript
function renderArchivePopup(props: ArchiveProperties): string {
  return `
    <div class="popup">
      <strong>${props.provider}</strong><br/>
      ${props.resolution_tier} · ${props.capture_date}<br/>
      Cloud: ${props.cloud_cover_pct}% · <strong>$${(props.price_cents / 100).toFixed(0)}</strong><br/>
      <a href="${props.skyfi_url}" target="_blank">View on SkyFi →</a>
    </div>
  `;
}
```

---

### Task 3.2 — ArchiveResultCard Component
**Location:** `components/tools/ArchiveResultCard.tsx`

Renders a compact card for each archive in a search result. One card per archive — render up to 10, show "X more results" if more.

Card fields:
- Provider name + color-coded badge
- Resolution tier badge (VERY HIGH / HIGH / MEDIUM / LOW)
- Capture date
- Cloud cover % (with color: green <10%, yellow 10-30%, red >30%)
- Price in dollars
- Thumbnail image (if `thumbnail_url` in result) — lazy loaded, show placeholder on error
- "View on SkyFi" link (opens in new tab)

```typescript
interface ArchiveResultCardProps {
  archive: ArchiveResult;
  onHighlight?: (archiveId: string) => void;  // triggers map highlight
}
```

Hovering a card calls `onHighlight` to highlight the corresponding marker on the map (add a visual state to the `"archives-circles"` paint property).

---

### Task 3.3 — Register ToolUI in assistant-ui
Register `ArchiveResultCard` as the ToolUI renderer for `search_archives` results.

The `search_archives` tool result is a list of archives wrapped in the Purveyor structured output format. The ToolUI component receives the full `output` from the SSE `tool_result` event.

```typescript
// In ChatPanel.tsx, register the tool UI
// Exact API: consult assistant-ui docs for makeAssistantToolUI or equivalent

const SearchArchivesTool = makeAssistantToolUI({
  toolName: "search_archives",
  render: ({ result }) => {
    const { archives } = result as ArchiveSearchOutput;
    return (
      <div className="flex flex-col gap-2">
        {archives.slice(0, 10).map(a => (
          <ArchiveResultCard key={a.archive_id} archive={a} />
        ))}
        {archives.length > 10 && (
          <p className="text-sm text-muted-foreground">{archives.length - 10} more results</p>
        )}
      </div>
    );
  }
});
```

---

### Task 3.4 — Archive Marker Popups
Already wired in Task 3.1 via `map.on("click", "archives-circles", ...)`. Verify:
- Clicking a marker shows popup with correct metadata
- Popup has working "View on SkyFi" link
- Popup closes when clicking elsewhere

---

### Task 3.5 — Implement HIGHLIGHT_ARCHIVE
When `get_archive_details` fires (user asks for details on a specific archive), highlight that archive's marker:
- Change its marker color to yellow
- Auto-open its popup
- Fly map to center on it

```typescript
case "HIGHLIGHT_ARCHIVE":
  map.setPaintProperty("archives-circles", "circle-color", [
    "case",
    ["==", ["get", "archive_id"], action.archiveId],
    "#fbbf24",  // yellow highlight
    ["get", "color"],  // original color
  ]);
  // Find feature and open popup
  break;
```

**Acceptance:** "Search for imagery of Houston, TX" → archive cards in chat + colored markers on map → click a marker → popup with metadata → "View on SkyFi" link works.

---

### Day 3 Acceptance Criteria
- [ ] `search_archives` results render as cards in chat with thumbnail, metadata, price
- [ ] Archive footprint markers appear on map with provider-coded colors
- [ ] Clicking a marker opens popup with metadata and SkyFi link
- [ ] Hovering a card highlights corresponding marker
- [ ] `get_archive_details` → marker highlighted + popup opened + map flies to it

---

## Day 4: Order Confirmation + Pricing

**Goal:** The full order flow works inline — no external link clicks needed.

### Task 4.1 — OrderConfirmation Component
**Location:** `components/tools/OrderConfirmation.tsx`

Receives `create_archive_order` or `create_tasking_order` tool result.

State machine: `idle | confirming | cancelling | confirmed | cancelled | error`

UI:
```
┌─────────────────────────────────────────────────────┐
│  Satellite Order — Archive                          │
│  Location: Port of Los Angeles                      │
│  Provider: PLANET · Resolution: VERY HIGH (0.5m)   │
│  Date: 2024-11-15                                   │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │  Estimated Cost         $125.00              │  │
│  │  (based on AOI area × per-sq-km rate)        │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ⚠️  This action will place a real order with SkyFi  │
│                                                     │
│  [  Cancel  ]          [ Confirm Order → ]          │
└─────────────────────────────────────────────────────┘
```

On Confirm:
```typescript
const token = new URL(confirmation_url).pathname.split("/confirm/")[1];
const res = await fetch(confirmation_url, {
  method: "POST",
  headers: { "Content-Type": "application/x-www-form-urlencoded" },
  body: "action=confirm",
  mode: "cors",
});
if (res.ok) {
  // Parse the HTML response for order ID (Purveyor returns HTML)
  // Or add a JSON endpoint to Purveyor — see note below
  setState("confirmed");
}
```

**Note on Purveyor's confirmation endpoint:** Purveyor's `/confirm/{token}` currently returns HTML. For the Console, either:
1. Parse the HTML response to extract the order ID (fragile)
2. Add a `?format=json` query param to Purveyor's confirm endpoint that returns JSON (preferred — a small enhancement to Purveyor)

Recommendation: Add `?format=json` support to Purveyor's confirm handler as a P0 prerequisite. It returns `{ status: "confirmed", order_id: "uuid" }`.

---

### Task 4.2 — Wire Confirmation to Purveyor
Implement the confirm and cancel POST requests. Handle error cases:
- `410 Gone`: token expired → show "This order link has expired. Please request a new one."
- `409 Conflict`: already confirmed/cancelled → show current status
- `502`: SkyFi API error during placement → show "Order could not be placed. SkyFi returned an error."
- Network error: show generic error with retry button

---

### Task 4.3 — Map Flash on Order
When `create_*_order` fires:
1. Flash the AOI polygon (animate border opacity 0→1→0 three times)
2. Show the confirmation widget in chat

```typescript
case "FLASH_AOI":
  // CSS animation via MapLibre paint property animation
  // Or use a temporary layer with opacity transition
  break;
```

---

### Task 4.4 — PricingTable Component
**Location:** `components/tools/PricingTable.tsx`

Renders `get_pricing` results as a grouped table:

```
Resolution Tier  | Provider   | Price/sq km
-----------------+------------+------------
VERY HIGH (0.5m) | PLANET     | $2.50
                 | MAXAR      | $3.10
HIGH (1m)        | AIRBUS     | $1.80
                 | SATELLOGIC | $1.40
```

Cheapest option per tier: green background row. All prices in USD.

---

### Task 4.5 — FeasibilityCard Component
**Location:** `components/tools/FeasibilityCard.tsx`

Renders `check_feasibility` results:
- If pending: spinner + "Feasibility check in progress... (ID: {id})"
- If complete: score gauge (0–1), feasibility level text, next available window date
- Color code: green/yellow/red by score

**Acceptance:** Type "Search for imagery of Manhattan and order the cheapest result" → agent searches, shows archives, proposes order, renders confirmation widget → click Confirm → success state with order ID.

---

### Day 4 Acceptance Criteria
- [ ] Confirmation widget renders with correct cost and order details
- [ ] Clicking "Confirm Order" places a real order via Purveyor's confirmation endpoint
- [ ] Clicking "Cancel" cancels the pending order
- [ ] Success/error states render correctly
- [ ] `get_pricing` results render as pricing comparison table
- [ ] `check_feasibility` results render with score and next window

---

## Day 5: Polish + Demo Scenarios

**Goal:** Three pre-built demo scenarios work end-to-end with polished UX.

### Task 5.1 — Scenario Buttons
**Location:** `components/chat/ScenarioButtons.tsx`

Three buttons above the chat input:

```typescript
const SCENARIOS = [
  {
    label: "Research",
    icon: "🔍",
    prompt: "I need recent high-resolution satellite imagery of the Port of Los Angeles. Search the archive, show me what's available, and tell me about the best options.",
  },
  {
    label: "Order",
    icon: "📦",
    prompt: "Find cloud-free imagery of the Suez Canal from the last 30 days. I want to order the highest resolution result available.",
  },
  {
    label: "Monitor",
    icon: "👁",
    prompt: "Set up monitoring for new satellite imagery over Donetsk, Ukraine. I want to be notified whenever new imagery becomes available.",
  },
];
```

Clicking a button: sets the chat input value AND auto-submits (dispatches a `submit` action to the runtime).

---

### Task 5.2 — Status Bar
**Location:** `components/layout/StatusBar.tsx`

Three sections:
- **Left:** Purveyor connection status (green dot "Connected" / red "Disconnected") — polls `/api/health` every 30s
- **Center:** User email from `whoami` (populated after first API call) · model name "gpt-4o"
- **Right:** "Orders" button with badge showing session order count

---

### Task 5.3 — Monitoring Zone Rendering
Implement `DRAW_MONITORING_ZONE` in the map dispatch:
- Draw the monitoring AOI as a green filled polygon
- Add a pulsing border animation using CSS keyframes injected via a MapLibre custom layer or a DOM overlay
- Add text label "Monitoring Active" at centroid

```typescript
// Pulsing border: use two line layers — one static, one animated via opacity
map.addLayer({
  id: "monitoring-pulse",
  type: "line",
  source: "monitoring",
  paint: {
    "line-color": "#22c55e",
    "line-width": 3,
    "line-opacity": ["interpolate", ["linear"], ["var", "--pulse"], 0, 0.3, 1, 1],
  },
});
// Drive --pulse via requestAnimationFrame or a CSS animation on a DOM element
```

Simpler alternative: use a Maplibre marker with a `div` element that has a CSS pulse animation.

---

### Task 5.4 — Pass Prediction Tracks
Implement `DRAW_PASS_TRACKS`:
- Each track is a GeoJSON LineString (great circle arc computed from start/end lat/lon)
- Add `"pass-tracks"` source and `"pass-tracks-line"` layer
- Style: dashed line, 2px, satellite provider color
- Add timestamp labels at midpoints using symbol layer

For great circle computation:
```bash
npm install @turf/great-circle
```

---

### Task 5.5 — Loading States and Error Handling
- Tool call loading indicators: show spinner with tool name while `tool_call` event received, replace with result on `tool_result`
- Skeleton cards for archive results while loading
- Error toast for network failures (using shadcn/ui toast)
- "Agent is thinking..." indicator when LLM is processing but no tokens yet
- Handle `error` SSE events: render error card in chat with `code` and `message`

**Acceptance:** All three scenario buttons work end-to-end without errors. Research scenario: archives on map. Order scenario: confirmation widget. Monitor scenario: monitoring zone on map.

---

### Day 5 Acceptance Criteria
- [ ] Three scenario buttons exist and auto-submit scripted prompts
- [ ] Status bar shows connection status and account info
- [ ] `setup_monitoring` result → green pulsing zone on map
- [ ] `get_pass_predictions` result → pass tracks drawn on map
- [ ] Loading states render for all tool calls
- [ ] Error states render for tool failures

---

## Day 6: Developer Features + History

**Goal:** Developer tools and history panel for technical audiences.

### Task 6.1 — MCP Calls Inspector
**Location:** `components/developer/McpCallsInspector.tsx`

A toggle button in the header "MCP Calls" shows/hides raw tool I/O.

Each agent message has a collapsible section at the bottom:
```
▼ 3 MCP Calls
  ▶ geocode_location   [Input] [Output]
  ▶ search_archives    [Input] [Output]
  ▶ get_pricing        [Input] [Output]
```

Clicking [Input] or [Output] shows a `<pre>` block with pretty-printed JSON.

Store all `tool_call` and `tool_result` events in React state, keyed by message ID.

---

### Task 6.2 — Order History Panel
**Location:** `components/layout/OrderHistoryPanel.tsx`

A shadcn/ui `Sheet` (slide-out drawer) triggered by the "Orders" button in the status bar.

Lists all orders placed during the session:
```
[ Archive Order ] Port of Los Angeles · $125.00 · Confirmed
Order ID: abc123-...
Provider: PLANET · Resolution: VERY HIGH · Date: 2024-11-15
```

Orders are accumulated from `tool_result` events where status is `confirmed`.

---

### Task 6.3 — Settings Panel
**Location:** `components/layout/SettingsPanel.tsx`

A `Sheet` triggered by a gear icon in the status bar:
- **SkyFi API Key:** text input (masked), stored in React state (not localStorage)
- **Purveyor MCP URL:** text input with default
- **Model:** dropdown (gpt-4o / gpt-4o-mini)
- **Clear Conversation:** button

---

### Task 6.4 — Responsive Layout
Verify layout at 1024px viewport width:
- Chat panel minimum width: 320px
- Map panel minimum width: 400px
- At 1024px, default split is still usable
- Status bar does not overflow
- Cards do not overflow their panel

---

### Day 6 Acceptance Criteria
- [ ] "MCP Calls" toggle shows/hides raw tool I/O for each message
- [ ] Order history panel lists confirmed orders with details
- [ ] Settings panel allows API key and model configuration
- [ ] Layout is usable at 1024px viewport width

---

## Day 7: Deploy + Demo Prep

**Goal:** Live URL works, demo video recorded.

### Task 7.1 — Deploy Frontend to Vercel

```bash
cd console/frontend
vercel deploy --prod
```

Set environment variable in Vercel dashboard:
- `NEXT_PUBLIC_AGENT_API_URL` = backend URL (set after Task 7.2)

Add `next.config.ts` rewrites if needed for CORS:
```typescript
async rewrites() {
  return [{ source: "/api/:path*", destination: `${process.env.AGENT_URL}/api/:path*` }];
}
```

---

### Task 7.2 — Deploy LangGraph Backend

Options (in order of simplicity):

**Option A: Railway**
```bash
cd console/agent
railway init
railway up
```
Set env vars: `OPENAI_API_KEY`, `PURVEYOR_MCP_URL`

**Option B: Render**
- Connect GitHub repo, select `console/agent/` as root
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn server:app --host 0.0.0.0 --port $PORT`

**Option C: Vercel Serverless Functions**
- Convert FastAPI to Vercel serverless (requires `@vercel/python`)
- Note: SSE streaming may not work well with Vercel's serverless timeout limits
- Use only if Railway/Render are not available

**Recommended:** Railway (simple, supports long-running SSE connections, free tier available)

---

### Task 7.3 — End-to-End Testing

Run all three demo scenarios on the live URL:

**Research Scenario:**
1. Enter a valid SkyFi API key in Settings
2. Click "Research" button
3. Verify: agent geocodes Port of LA → map flies → searches archives → cards render → markers on map
4. Click a marker → popup opens → "View on SkyFi" link works

**Order Scenario:**
1. Click "Order" button
2. Verify: agent searches Suez Canal → proposes order → confirmation widget renders with cost
3. Click "Confirm Order" → success state with order ID

**Monitor Scenario:**
1. Click "Monitor" button
2. Verify: agent sets up monitoring → green zone appears on map with pulsing border

Document any failures and fix before recording.

---

### Task 7.4 — Record Demo Video
Record a 3-5 minute demo video:

**Script:**
1. (0:00) Open the app, briefly explain Purveyor Console
2. (0:30) Click "Research" — narrate what's happening on the map
3. (1:30) Click "Order" — highlight the inline confirmation widget and cost transparency
4. (2:30) Click "Monitor" — show monitoring zone on map
5. (3:30) Toggle "MCP Calls" to show raw tool I/O — explain this for developers
6. (4:00) Closing: MCP server URL, how to connect your own client

Tools: Loom (free), QuickTime, or OBS.

---

### Task 7.5 — Write README
**Location:** `console/README.md`

Include:
- What Purveyor Console is (one paragraph)
- Architecture diagram (ASCII or mermaid)
- Prerequisites (Node.js 18+, Python 3.11+, OpenAI key, SkyFi key)
- Local development setup (copy-pasteable commands)
- Deployment guide (Vercel + Railway)
- Three scenario descriptions
- Link to demo video

---

### Day 7 Acceptance Criteria
- [ ] Frontend deployed to Vercel with live URL
- [ ] Backend deployed to Railway/Render with HTTPS
- [ ] All three demo scenarios work on live URL
- [ ] Demo video recorded and linked from README
- [ ] Console README is complete

---

## Task Summary

| Day | Tasks | Key Deliverable |
|-----|-------|-----------------|
| 1 | 4 | Streaming chat with live Purveyor tool calls |
| 2 | 5 | Interactive map syncing with location tools |
| 3 | 5 | Archive cards in chat + markers on map |
| 4 | 5 | Full order flow with inline confirmation |
| 5 | 5 | Three scenario buttons + polish |
| 6 | 4 | Developer inspector + history panel |
| 7 | 5 | Deployed live URL + demo video |
| **Total** | **33** | |

---

## Critical Path

The following tasks block subsequent work and should not be skipped:

1. **Task 1.2** (LangGraph agent connecting to Purveyor) — blocks everything
2. **Task 1.3** (FastAPI SSE endpoint) — blocks frontend integration
3. **Task 2.2** (MapContext) — blocks all map sync tasks
4. **Task 4.1** (Confirmation widget) — the most important demo moment; blocks Day 4 acceptance
5. **Task 7.1+7.2** (Deploy) — required for demo video

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| `langchain-mcp-adapters` API changes | Pin to a specific version in requirements.txt; read their changelog before starting |
| Purveyor's `/confirm/{token}` returns HTML, not JSON | Add `?format=json` support to Purveyor's confirm endpoint on Day 4 before Task 4.1 |
| MapLibre WKT parsing | Use `wellknown` library (mature, well-tested); test with Purveyor's actual WKT output formats |
| OpenFreeMap tiles unavailable | Fallback to `https://demotiles.maplibre.org/style.json` (MapLibre's own demo tiles) |
| SSE streaming doesn't work on Vercel | Use Railway for backend (supports long-lived connections); frontend on Vercel is fine |
| MCP tool discovery is slow (adds latency per request) | Cache tool list per API key for 5 min in the backend |
