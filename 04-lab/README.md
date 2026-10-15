# Lab 04 — Weather Agent with Remote MCP Server

A weather agent built with Google ADK that connects to an MCP server via Streamable HTTP transport.

## Architecture

```
┌─────────────────┐   Streamable HTTP    ┌─────────────────┐      REST       ┌─────────────────┐
│   ADK Agent     │ ──────────────────── │   MCP Server    │ ─────────────── │  WeatherAPI.com │
│  (mcp-client)   │   localhost:8085/mcp │  (mcp-server)   │                 │                 │
└─────────────────┘                      └─────────────────┘                 └─────────────────┘
```

## Tools

| Tool | Description |
|------|-------------|
| `get_current_weather(city)` | Get current weather conditions for a city |
| `get_forecast(city, days)` | Get weather forecast (1–3 days) |
| `health_check()` | Verify server is running |

## ADK làm gì trong Lab này?

ADK (Agent Development Kit) đóng vai trò **MCP Client** 
```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  1. KẾT NỐI tới MCP Server qua Streamable HTTP                  │
│     StreamableHTTPConnectionParams(url="localhost:8085/mcp")    │
│                                                                 │
│  2. KHÁM PHÁ tools tự động (list_tools)                         │
│     McpToolset → tự hỏi server "anh có tool gì?"                │
│     → nhận về: get_current_weather, get_forecast, health_check  │
│                                                                 │
│  3. TRUYỀN tools cho LLM (Gemini)                               │
│     Agent(model="gemini-3.8-flash", tools=[weather_tools])      │
│     → Gemini biết nó có thể gọi 3 tools trên                    │
│                                                                 │
│  4. ĐIỀU PHỐI vòng lặp Function Calling                         │
│     User hỏi → Gemini chọn tool → ADK gọi MCP Server            │
│     → nhận kết quả → đưa lại cho Gemini tổng hợp                │
│                                                                 │
│  5. CUNG CẤP giao diện web (adk web)                            │
│     → http://localhost:8000 để chat với agent                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

So với bài 02 (viết client thủ công bằng `mcp.ClientSession`), ADK giúp bạn **không phải viết vòng lặp function calling thủ công** nữa. Toàn bộ luồng list_tools → model quyết định → call_tool → model tổng hợp được ADK xử lý tự động.

## Setup

### 1. MCP Server

```bash
cd mcp-server
uv sync

# Put your WeatherAPI key (free at https://weatherapi.com) in mcp-server/.env:
#   WEATHERAPI_KEY=<your key>        (optional: PORT=8085, HOST=127.0.0.1)
# Start the server (Streamable HTTP, port 8085 by default; add --stdio for stdio mode)
uv run --frozen --env-file .env python weather.py
```

The server will be available at `http://localhost:8085/mcp`.

### 2. ADK Agent (Client)

```bash
cd mcp-client
uv sync

# Put your Gemini key in mcp-client/.env:  GOOGLE_API_KEY=<your key>
# Verify the whole chain with real MCP calls (server must be running):
uv run python verify_setup.py        # --offline skips the checks that need the server

# Start ADK web interface
uv run adk web
```

Open http://localhost:8000 in your browser, select `weather_agent`, and ask about the weather.

## Configuration

| Variable | Where | Description |
|----------|-------|-------------|
| `WEATHERAPI_KEY` | mcp-server | API key from weatherapi.com |
| `GOOGLE_API_KEY` | mcp-client/.env | Gemini API key |
| `PORT` | mcp-server (env) | Override server port (default: 8085; Cloud Run sets it) |
| `HOST` | mcp-server (env) | Bind address (default `127.0.0.1`; the Dockerfile sets `0.0.0.0`) |
| `GEMINI_MODEL` | mcp-client | Model id (default `gemini-3.8-flash`) |
| `ALLOW_NO_TOOLS_FALLBACK` | mcp-client | `1` = allow a visible degraded agent without tools if MCP setup fails (default: fail loudly) |
| `MCP_SERVER_URL` | mcp-client/.env | MCP endpoint the agent connects to (default: `http://localhost:8085/mcp`; set to your Cloud Run URL + `/mcp` when deployed) |

## Server behaviour & limits

- `get_forecast(city, days)` accepts **1–3** only (free-tier limit); other values are rejected with an error instead of being silently clamped.
- Errors (missing key, invalid key, unknown city, timeout, network, invalid JSON, missing fields) are returned as MCP tool errors with sanitized messages — the API key never appears in tool output, logs, or URLs.
- Tests: `cd mcp-server && uv run --frozen pytest` (WeatherAPI mocked) and `cd mcp-client && uv run --frozen pytest`.

## Docker / Cloud Run

```powershell
cd 04-lab/mcp-server
docker build -t weather-mcp .
docker run --rm -p 8080:8080 -e WEATHERAPI_KEY=$env:WEATHERAPI_KEY weather-mcp   # MCP at http://localhost:8080/mcp
```

The image installs from `uv.lock`, runs as a non-root user, listens on `0.0.0.0:$PORT` (default 8080), and never contains `.env` (`.dockerignore`). Pass the key at runtime or via Cloud Run secrets. Deploying to Cloud Run creates a public, billable service — do it deliberately, e.g.
`gcloud run deploy weather-mcp --source . --set-secrets WEATHERAPI_KEY=<secret>:latest`, then set `MCP_SERVER_URL=https://<service>.run.app/mcp` in `mcp-client/.env`.
