# Purveyor Console — Technical Specification

## System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser (Next.js, Vercel)                                       │
│                                                                  │
│  ┌─────────────────┐    ┌──────────────────────────────────┐    │
│  │   Chat Panel    │    │          Map Panel               │    │
│  │  (assistant-ui) │    │       (MapLibre GL JS)           │    │
│  │                 │    │                                  │    │
│  │  StreamRuntime  │    │  MapContext (React Context)      │    │
│  │  ToolUI comps   │    │  GeoJSON sources + layers        │    │
│  └────────┬────────┘    └──────────────┬───────────────────┘    │
│           │  SSE                       │  dispatch(mapAction)   │
│           │  POST /api/chat            │                        │
└───────────┼────────────────────────────┼────────────────────────┘
            │                            │
            ▼                            ▲
┌──────────────────────────────────────────────────────────────────┐
│  LangGraph Backend (Python FastAPI)                              │
│                                                                  │
│  POST /api/chat → SSE stream                                     │
│    text_delta | tool_call | tool_result | done                   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  LangGraph Agent                                         │   │
│  │  START → agent → [has_tool_calls] → tools → agent → END  │   │
│  │                                                          │   │
│  │  OpenAI gpt-4o + Purveyor MCP tools                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└──────────────────────────────────────────┬───────────────────────┘
                                           │ MCP Streamable HTTP
                                           │ X-Skyfi-Api-Key header
                                           ▼
                              ┌─────────────────────────┐
                              │  Purveyor MCP Server    │
                              │  (AWS Fargate)          │
                              │  20 tools, SkyFi API    │
                              └─────────────────────────┘
```

---

## LangGraph Agent Architecture

### Graph Definition

```python
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing import TypedDict, Annotated

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    current_aoi: str | None          # WKT of most recent AOI (context for agent)
    active_confirmation: dict | None  # Pending confirmation token + metadata

def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END

builder = StateGraph(AgentState)
builder.add_node("agent", call_model)
builder.add_node("tools", call_tools)
builder.set_entry_point("agent")
builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
builder.add_edge("tools", "agent")
graph = builder.compile()
```

### Node Implementations

**agent node:** Calls OpenAI gpt-4o with the full message history and the tool list discovered from Purveyor MCP. Returns an AIMessage which may contain tool_calls.

```python
async def call_model(state: AgentState, config: RunnableConfig) -> AgentState:
    skyfi_api_key = config["configurable"]["skyfi_api_key"]
    tools = await get_purveyor_tools(skyfi_api_key)
    model = ChatOpenAI(model="gpt-4o", streaming=True)
    model_with_tools = model.bind_tools(tools)
    response = await model_with_tools.ainvoke(state["messages"])
    return {"messages": [response]}
```

**tools node:** Executes all tool calls present in the last AIMessage. Uses `ToolNode` from LangGraph or a custom executor that passes the SkyFi API key via MCP headers.

```python
async def call_tools(state: AgentState, config: RunnableConfig) -> AgentState:
    skyfi_api_key = config["configurable"]["skyfi_api_key"]
    tools = await get_purveyor_tools(skyfi_api_key)
    tool_node = ToolNode(tools)
    return await tool_node.ainvoke(state)
```

### MCP Tool Discovery

Tools are discovered once per API request via `MultiServerMCPClient`. Because each user has a different API key, the MCP client must be instantiated per-request (not at startup).

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

PURVEYOR_MCP_URL = "http://purveyor-691022321.us-east-1.elb.amazonaws.com/mcp"

async def get_purveyor_tools(skyfi_api_key: str) -> list:
    """Discover and return Purveyor MCP tools for the given API key."""
    async with MultiServerMCPClient({
        "purveyor": {
            "url": PURVEYOR_MCP_URL,
            "transport": "streamable_http",
            "headers": {"X-Skyfi-Api-Key": skyfi_api_key},
        }
    }) as client:
        return client.get_tools()
```

Note: For performance, consider caching the tool list per API key with a 5-minute TTL since Purveyor's tool schema does not change between calls.

### Streaming Architecture

The backend uses LangGraph's `astream_events` API to emit a structured SSE stream to the frontend.

```python
async def stream_agent_response(messages: list, skyfi_api_key: str):
    """Yields SSE-formatted events for the frontend."""
    config = {"configurable": {"skyfi_api_key": skyfi_api_key}}

    async for event in graph.astream_events(
        {"messages": messages, "current_aoi": None, "active_confirmation": None},
        config=config,
        version="v2",
    ):
        kind = event["event"]

        # Text token streamed from the LLM
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if chunk.content:
                yield format_sse("text_delta", {"token": chunk.content})

        # Tool call initiated (before execution)
        elif kind == "on_tool_start":
            yield format_sse("tool_call", {
                "tool": event["name"],
                "input": event["data"].get("input", {}),
            })

        # Tool call completed
        elif kind == "on_tool_end":
            yield format_sse("tool_result", {
                "tool": event["name"],
                "output": event["data"].get("output", {}),
            })

    yield format_sse("done", {})

def format_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
```

---

## API Layer (FastAPI)

### Endpoints

**POST /api/chat**

Accepts a conversation turn and returns an SSE stream.

Request body:
```typescript
{
  messages: Array<{
    role: "user" | "assistant" | "tool",
    content: string,
  }>,
  skyfi_api_key: string,
}
```

Response: `Content-Type: text/event-stream`

SSE event types:

| Event | Payload | When |
|-------|---------|------|
| `text_delta` | `{ token: string }` | Each text token from the LLM |
| `tool_call` | `{ tool: string, input: object }` | Before tool execution starts |
| `tool_result` | `{ tool: string, output: object }` | After tool execution completes |
| `error` | `{ message: string, code: string }` | On recoverable errors |
| `done` | `{}` | Conversation turn complete |

**GET /api/health**

Returns `{ status: "ok", purveyor_connected: bool, timestamp: string }`. Used by the status bar.

### FastAPI Application

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Purveyor Console Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to Vercel domain in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.post("/api/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(
        stream_agent_response(request.messages, request.skyfi_api_key),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

---

## Frontend Architecture

### Directory Structure

```
console/
├── app/
│   ├── layout.tsx              # Root layout: providers, fonts, global styles
│   ├── page.tsx                # Main split-view page
│   └── globals.css             # Tailwind base + custom CSS vars
├── components/
│   ├── layout/
│   │   ├── SplitView.tsx       # Resizable left/right panel layout
│   │   └── StatusBar.tsx       # Top bar: connection, account, orders
│   ├── chat/
│   │   ├── ChatPanel.tsx       # assistant-ui Thread wrapper
│   │   ├── MessageInput.tsx    # Input with scenario buttons above it
│   │   └── ScenarioButtons.tsx # Pre-built demo scenario buttons
│   ├── map/
│   │   ├── MapPanel.tsx        # MapLibre GL JS React wrapper
│   │   ├── MapContext.tsx      # React context for map state + actions
│   │   └── MapSync.tsx         # Invisible component: subscribes to tool results, dispatches map actions
│   ├── tools/                  # Custom ToolUI renderers (registered with assistant-ui)
│   │   ├── ArchiveResultCard.tsx
│   │   ├── PricingTable.tsx
│   │   ├── FeasibilityCard.tsx
│   │   ├── OrderConfirmation.tsx
│   │   ├── MonitoringSetupCard.tsx
│   │   └── WhoamiCard.tsx
│   ├── developer/
│   │   └── McpCallsInspector.tsx  # Expandable raw tool I/O panel
│   └── ui/                     # shadcn/ui components (Button, Card, Badge, etc.)
├── lib/
│   ├── api.ts                  # fetch wrapper for POST /api/chat, GET /api/health
│   ├── sse-client.ts           # SSE stream reader, event parser, typed event emitter
│   ├── map-sync.ts             # Maps tool names to MapAction objects
│   ├── runtime.ts              # assistant-ui custom runtime (calls LangGraph API)
│   └── tool-registry.ts        # Maps tool names to ToolUI components
└── types/
    ├── sse-events.ts           # TypeScript types for SSE event payloads
    └── map-actions.ts          # TypeScript types for map dispatch actions
```

### assistant-ui Integration

assistant-ui is used for the chat panel UI. A custom runtime bridges it to the LangGraph SSE backend.

```typescript
// lib/runtime.ts
import { useLocalRuntime, type ChatModelAdapter } from "@assistant-ui/react";

const langGraphAdapter: ChatModelAdapter = {
  async *run({ messages, abortSignal }) {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, skyfi_api_key: getSkyFiApiKey() }),
      signal: abortSignal,
    });

    const reader = response.body!.getReader();
    // Parse SSE stream, yield text_delta and tool_result events
    // to assistant-ui's streaming protocol
    for await (const event of parseSseStream(reader)) {
      if (event.type === "text_delta") {
        yield { type: "text-delta", textDelta: event.token };
      } else if (event.type === "tool_result") {
        yield { type: "tool-result", toolName: event.tool, result: event.output };
      }
    }
  }
};

export function usePurveyorRuntime() {
  return useLocalRuntime(langGraphAdapter);
}
```

Custom ToolUI components are registered to render specific tool results:

```typescript
// components/chat/ChatPanel.tsx
import { AssistantMessage, useAssistantRuntime } from "@assistant-ui/react";

const toolComponents = {
  search_archives: ArchiveResultCard,
  get_pricing: PricingTable,
  check_feasibility: FeasibilityCard,
  create_archive_order: OrderConfirmation,
  create_tasking_order: OrderConfirmation,
  setup_monitoring: MonitoringSetupCard,
  whoami: WhoamiCard,
};

// Register via AssistantMessage.Unstable_Tool or equivalent assistant-ui API
// Consult latest assistant-ui docs — API may be makeAssistantToolUI or similar
```

### MapLibre Integration

The map is initialized in a React ref and controlled programmatically via the MapContext.

```typescript
// components/map/MapPanel.tsx
import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import { useMapContext } from "./MapContext";

export function MapPanel() {
  const mapRef = useRef<maplibregl.Map | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { registerMap } = useMapContext();

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current!,
      style: "https://tiles.openfreemap.org/styles/liberty",  // Free tile source
      center: [-98.5, 39.5],   // Center of continental US
      zoom: 4,
    });
    mapRef.current = map;
    registerMap(map);
    return () => map.remove();
  }, []);

  return <div ref={containerRef} className="w-full h-full" />;
}
```

The MapContext provides dispatch functions for map actions:

```typescript
// components/map/MapContext.tsx
type MapAction =
  | { type: "FLY_TO"; center: [number, number]; zoom?: number }
  | { type: "DRAW_AOI"; wkt: string; label?: string }
  | { type: "PLOT_ARCHIVES"; archives: ArchiveResult[] }
  | { type: "DRAW_FEASIBILITY"; lat: number; lon: number; score: number }
  | { type: "DRAW_PASS_TRACKS"; tracks: PassPrediction[] }
  | { type: "DRAW_MONITORING_ZONE"; wkt: string; notificationId: string }
  | { type: "HIGHLIGHT_ARCHIVE"; archiveId: string }
  | { type: "CLEAR_LAYER"; layer: string };

interface MapContextValue {
  dispatch: (action: MapAction) => void;
  registerMap: (map: maplibregl.Map) => void;
}
```

### Map Sync Logic

`MapSync.tsx` is an invisible component that subscribes to tool results from the SSE stream and dispatches map actions.

```typescript
// components/map/MapSync.tsx
// This component renders null but subscribes to the tool result event stream.
// It translates tool names + outputs to MapAction dispatches.

function parseToolResultToMapAction(tool: string, output: unknown): MapAction | null {
  switch (tool) {
    case "geocode_location": {
      const { longitude, latitude } = output as GeocodedLocation;
      return { type: "FLY_TO", center: [longitude, latitude], zoom: 12 };
    }
    case "search_archives": {
      const { archives } = output as ArchiveSearchResult;
      return { type: "PLOT_ARCHIVES", archives };
    }
    case "create_aoi_from_point": {
      const { wkt } = output as AoiResult;
      return { type: "DRAW_AOI", wkt };
    }
    case "calculate_aoi_area": {
      const { area_sq_km, wkt } = output as AoiAreaResult;
      return { type: "DRAW_AOI", wkt, label: `${area_sq_km.toLocaleString()} sq km` };
    }
    case "check_feasibility": {
      const { score, aoi_centroid } = output as FeasibilityResult;
      return { type: "DRAW_FEASIBILITY", ...aoi_centroid, score };
    }
    case "get_pass_predictions": {
      const { tracks } = output as PassPredictionsResult;
      return { type: "DRAW_PASS_TRACKS", tracks };
    }
    case "setup_monitoring": {
      const { notification_id, aoi } = output as MonitoringResult;
      return { type: "DRAW_MONITORING_ZONE", wkt: aoi, notificationId: notification_id };
    }
    case "get_archive_details": {
      const { archive_id } = output as ArchiveDetailResult;
      return { type: "HIGHLIGHT_ARCHIVE", archiveId: archive_id };
    }
    default:
      return null;
  }
}
```

---

## Map Action Implementations

Full detail on how each MapAction translates to MapLibre operations:

### FLY_TO
```typescript
map.flyTo({ center: action.center, zoom: action.zoom ?? 12, duration: 1500 });
```

### DRAW_AOI
Parse WKT POLYGON string → GeoJSON Feature. Add/update source `"aoi"`. Style:
- Fill: `rgba(59, 130, 246, 0.15)` (blue transparent)
- Border: `rgba(59, 130, 246, 0.8)` solid, 2px
- If label provided: add a symbol layer at polygon centroid

```typescript
const geojson = wktToGeoJSON(action.wkt);  // Use wellknown or @terraformer/wkt library
map.getSource("aoi")
  ? (map.getSource("aoi") as GeoJSONSource).setData(geojson)
  : map.addSource("aoi", { type: "geojson", data: geojson });
// Add/update fill + line layers if not present
map.fitBounds(bbox(geojson), { padding: 80 });
```

### PLOT_ARCHIVES
Convert archives to GeoJSON FeatureCollection. Each feature's geometry is the archive footprint WKT. Properties include all archive metadata for popup rendering.

Marker color by provider (deterministic hash to hue for unknown providers):
- PLANET → green `#22c55e`
- MAXAR → blue `#3b82f6`
- AIRBUS → orange `#f97316`
- SATELLOGIC → purple `#a855f7`
- Other → gray `#6b7280`

```typescript
// Add popup on marker click
map.on("click", "archives-layer", (e) => {
  const props = e.features![0].properties;
  new maplibregl.Popup()
    .setLngLat(e.lngLat)
    .setHTML(renderArchivePopup(props))
    .addTo(map);
});
```

### DRAW_FEASIBILITY
Draw a circle with radius proportional to AOI size. Color:
- Score ≥ 0.7: green `#22c55e`
- Score 0.4–0.7: yellow `#eab308`
- Score < 0.4: red `#ef4444`

### DRAW_PASS_TRACKS
Each track is a GeoJSON LineString (great circle arc between start and end lat/lon). Style: dashed line, color matches provider, label at midpoint with timestamp.

### DRAW_MONITORING_ZONE
Draw polygon in green with a CSS animation on the border. Add a label "Monitoring Active" at centroid. Store notification_id as a property for future reference.

---

## Inline Confirmation Flow

When `create_archive_order` or `create_tasking_order` returns a `confirmation_url`:

1. The SSE `tool_result` event contains `{ tool: "create_archive_order", output: { confirmation_url: "...", estimated_cost_cents: 45000, ... } }`
2. `OrderConfirmation.tsx` renders as the ToolUI for this result
3. The component extracts the token from the URL path: `/confirm/{token}`
4. The component renders: order metadata, cost (`$450.00`), Confirm + Cancel buttons
5. On Confirm click:
   ```typescript
   const response = await fetch(confirmation_url, {
     method: "POST",
     headers: { "Content-Type": "application/x-www-form-urlencoded" },
     body: "action=confirm",
   });
   ```
   Note: This is a cross-origin request to the Purveyor server. Purveyor returns CORS `*`, so this works.
6. On success (200): show "Order placed! SkyFi Order ID: {id}" with green checkmark
7. On error: show error message with error code from Purveyor's HTML response body

State machine for confirmation widget:
```
idle → confirming → confirmed
     → cancelling → cancelled
     → error
```

---

## Tile Source

Use [OpenFreeMap](https://openfreemap.org/) which provides free MapLibre-compatible tiles:

```typescript
style: "https://tiles.openfreemap.org/styles/liberty"
```

No API key required. Self-hostable if needed. Falls back to any PMTiles or Maptiler URL.

---

## Environment Variables

### Frontend (Next.js — Vercel)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_AGENT_API_URL` | Yes | URL of LangGraph FastAPI backend |
| `NEXT_PUBLIC_PURVEYOR_MCP_URL` | No | Displayed in status bar (informational) |

The SkyFi API key is entered by the user at runtime via a settings panel. It is NOT a build-time env var.

### Backend (LangGraph FastAPI)

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key for gpt-4o |
| `PURVEYOR_MCP_URL` | Yes | Purveyor MCP server URL |
| `ALLOWED_ORIGINS` | No | CORS origins (default: `*`) |
| `LOG_LEVEL` | No | `info` (default) |

---

## Dependencies

### Frontend (package.json additions)
```json
{
  "@assistant-ui/react": "latest",
  "maplibre-gl": "^4.x",
  "@types/maplibre-gl": "^4.x",
  "wellknown": "^0.5.0",
  "@turf/bbox": "^7.x",
  "@turf/centroid": "^7.x",
  "tailwindcss": "^3.x",
  "shadcn/ui": "via npx shadcn@latest add",
  "next": "14.x",
  "typescript": "^5.x"
}
```

### Backend (pyproject.toml additions or requirements.txt)
```
langgraph>=0.2
langchain-openai>=0.2
langchain-mcp-adapters>=0.1
fastapi>=0.115
uvicorn[standard]>=0.32
pydantic>=2.0
structlog>=24.0
python-dotenv>=1.0
```

---

## Security Considerations

- SkyFi API key travels: user's browser → HTTPS → LangGraph backend → MCP header to Purveyor. Never stored.
- LangGraph backend must be HTTPS in production. Use Railway/Render with TLS termination.
- Confirmation POSTs go directly browser → Purveyor's `/confirm/{token}`. Purveyor handles CORS.
- No authentication on the Console itself — it's a demo app. A real deployment would add auth.
- OpenAI API key is a server-side secret, never exposed to the browser.
