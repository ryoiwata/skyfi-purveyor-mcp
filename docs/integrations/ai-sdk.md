# Connecting Purveyor to Vercel AI SDK

Use Purveyor's satellite imagery tools in Next.js and Node.js applications with the Vercel AI SDK.

## Prerequisites

- Node.js 18+ and npm/pnpm
- Next.js project (or Node.js app)
- Purveyor deployed with a public HTTPS URL
- SkyFi API key and Anthropic or OpenAI API key

## Setup

```bash
npm install ai @ai-sdk/anthropic
```

### Next.js API Route (App Router)

```typescript
// app/api/chat/route.ts
import { anthropic } from "@ai-sdk/anthropic";
import { experimental_createMCPClient as createMCPClient, streamText } from "ai";

export async function POST(request: Request) {
  const { messages } = await request.json();

  // Connect to Purveyor
  const mcpClient = await createMCPClient({
    transport: {
      type: "sse",
      url: "https://your-server.com/mcp",
      headers: {
        "X-Skyfi-Api-Key": process.env.SKYFI_API_KEY!,
      },
    },
  });

  const tools = await mcpClient.tools();

  const result = streamText({
    model: anthropic("claude-opus-4-6"),
    messages,
    tools,
    onFinish: async () => {
      await mcpClient.close();
    },
  });

  return result.toDataStreamResponse();
}
```

### React Chat Component

```tsx
// app/page.tsx
"use client";

import { useChat } from "ai/react";

export default function SatelliteChat() {
  const { messages, input, handleInputChange, handleSubmit, isLoading } = useChat({
    api: "/api/chat",
  });

  return (
    <div className="flex flex-col h-screen max-w-2xl mx-auto p-4">
      <h1 className="text-2xl font-bold mb-4">Satellite Imagery Assistant</h1>

      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`p-3 rounded-lg ${
              message.role === "user" ? "bg-blue-50 ml-8" : "bg-gray-50 mr-8"
            }`}
          >
            <p className="font-semibold text-sm text-gray-500 mb-1">
              {message.role === "user" ? "You" : "Assistant"}
            </p>
            <p className="whitespace-pre-wrap">{message.content}</p>
          </div>
        ))}
        {isLoading && (
          <div className="bg-gray-50 rounded-lg p-3 mr-8">
            <p className="text-gray-400 animate-pulse">Searching satellite catalog...</p>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={input}
          onChange={handleInputChange}
          placeholder="Ask about satellite imagery..."
          className="flex-1 border rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={isLoading}
        />
        <button
          type="submit"
          disabled={isLoading || !input}
          className="bg-blue-500 text-white px-6 py-2 rounded-lg hover:bg-blue-600 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
```

### Environment Variables

```bash
# .env.local
ANTHROPIC_API_KEY=sk-ant-...
SKYFI_API_KEY=your-skyfi-api-key
```

### Node.js Script (without Next.js)

```typescript
import { anthropic } from "@ai-sdk/anthropic";
import { experimental_createMCPClient as createMCPClient, generateText } from "ai";

async function main() {
  const mcpClient = await createMCPClient({
    transport: {
      type: "sse",
      url: "https://your-server.com/mcp",
      headers: {
        "X-Skyfi-Api-Key": process.env.SKYFI_API_KEY!,
      },
    },
  });

  const tools = await mcpClient.tools();

  const { text } = await generateText({
    model: anthropic("claude-opus-4-6"),
    tools,
    messages: [
      {
        role: "user",
        content: "Search for recent Sentinel-2 open data imagery of Amsterdam.",
      },
    ],
    maxSteps: 5,
  });

  console.log(text);
  await mcpClient.close();
}

main().catch(console.error);
```

## Troubleshooting

**"experimental_createMCPClient is not a function"**
- Ensure you're using `ai` package version >= 3.4.0
- Import from `"ai"` not `"ai/mcp"`: `import { experimental_createMCPClient } from "ai"`

**CORS errors in browser**
- Purveyor defaults to `ALLOWED_ORIGINS=*` which allows all origins
- If you've set `ALLOWED_ORIGINS`, add your domain to the list
- API routes handle MCP calls server-side — CORS only matters for direct browser calls

**Tool calls not streaming**
- Use `streamText` instead of `generateText` for streaming responses
- Ensure `maxSteps` is set to allow multi-turn tool calls (default is 1)

**Connection timeout after deployment**
- Check Purveyor's health endpoint: `curl https://your-server.com/health`
- Increase timeout in MCP client config if needed
