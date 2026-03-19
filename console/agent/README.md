# Purveyor Console — Agent Backend

LangGraph + FastAPI backend that bridges the Next.js chat UI to the Purveyor MCP server.

## Architecture

```
Frontend (Next.js)  →  POST /api/chat  →  FastAPI  →  LangGraph  →  Purveyor MCP  →  SkyFi API
                         SSE stream ←         ← astream_events ←
```

## Setup

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
# or, if using uv:
uv sync
```

Create a `.env` file (copy from `.env.example`):
```
OPENAI_API_KEY=sk-...
SKYFI_API_KEY=...           # Your SkyFi Platform API key
PURVEYOR_MCP_URL=http://purveyor-691022321.us-east-1.elb.amazonaws.com/mcp
```

## Running

```bash
source .venv/bin/activate
uvicorn server:app --reload --port 8001
```

Server listens at `http://localhost:8001`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | SSE stream: runs LangGraph agent, emits text/tool events |
| GET | `/api/health` | Health check |

### SSE Event Types

| Event | Payload | When |
|-------|---------|------|
| `text_delta` | `{ token: string }` | Each LLM text token |
| `tool_call` | `{ tool: string, input: object }` | Before tool execution |
| `tool_result` | `{ tool: string, output: object }` | After tool execution |
| `error` | `{ message: string, code: string }` | On errors |
| `done` | `{}` | Turn complete |

## Manual Testing

```bash
# Test agent + whoami tool
python test_agent.py whoami

# Test SSE streaming events
python test_agent.py stream

# Direct curl test
curl -N -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"skyfi_api_key":"your-key"}'
```

## Files

| File | Purpose |
|------|---------|
| `server.py` | FastAPI app with SSE streaming endpoint |
| `graph.py` | LangGraph StateGraph definition |
| `tools.py` | MCP client factory + tool discovery (5-min cache) |
| `system_prompt.py` | Agent system prompt |
| `test_agent.py` | Manual smoke tests |
