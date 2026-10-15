# Weather Agent - Google ADK with MCP Server

AI agent built with **Google Agent Development Kit (ADK)** that uses tools from a local **MCP server** via Streamable HTTP transport.

## Architecture

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────────┐
│   User Browser  │ ───> │  ADK Web UI      │ ───> │  Weather Agent      │
│   localhost:8000│      │  (Google ADK)    │      │  (Agent with MCP)   │
└─────────────────┘      └──────────────────┘      └─────────────────────┘
                                                             │
                                                             │ Streamable HTTP
                                                             ▼
                                                   ┌─────────────────────┐
                                                   │  MCP Server         │
                                                   │  localhost:8085/mcp │
                                                   │  FastMCP + Tools    │
                                                   └─────────────────────┘
                                                             │
                                                             ▼
                                                   ┌─────────────────────┐
                                                   │  WeatherAPI.com     │
                                                   └─────────────────────┘
```

## Features

- **Remote MCP Tools**: Connects to MCP server via Streamable HTTP
- **3 Weather Tools**:
  - `get_current_weather(city)` - Real-time weather conditions
  - `get_forecast(city, days)` - Weather forecast up to 3 days
  - `health_check()` - Server health verification
- **Web Interface**: UI via ADK web
- **Streaming Responses**: Real-time AI responses

## Quick Start

### 1. Start the MCP Server

```bash
cd ../mcp-server
export WEATHERAPI_KEY="your_weatherapi_key"
uv run python weather.py
```

### 2. Setup Environment

```bash
cd mcp-client

# Create .env file with your Google API key
# Get free key from: https://aistudio.google.com/apikey
echo "GOOGLE_API_KEY=your_google_api_key_here" > .env
```

### 3. Install Dependencies

```bash
uv sync
```

### 4. Run the Agent

```bash
uv run adk web
```

### 5. Use the Agent

1. Open browser: http://localhost:8000
2. Select `weather_agent` from dropdown
3. Ask questions like:
   - "What's the weather in Brisbane?"
   - "Give me a 3-day forecast for Tokyo"
   - "How's the weather in New York?"

## Project Structure

```
mcp-client/
├── weather_agent/
│   ├── agent.py           # Main agent with MCP connection
│   └── __init__.py
├── pyproject.toml
├── .env                   # Environment variables (create this)
└── README.md
```

## Configuration

### Agent Configuration

In `weather_agent/agent.py`:

```python
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8085/mcp")

connection_params = StreamableHTTPConnectionParams(
    url=MCP_SERVER_URL,
    timeout=30.0,
)

root_agent = build_agent()   # Agent(model=GEMINI_MODEL or "gemini-3.8-flash", tools=[McpToolset(...)])
```

## Troubleshooting

### Agent won't connect to MCP server

1. **404 errors**: MCP server is not running or wrong port
   - Ensure the MCP server is running on port 8085
   - Check `MCP_SERVER_URL` (env var / `.env`, default `http://localhost:8085/mcp`)

2. **405 errors**: Port conflict with another application
   - Check what's running on the port: `lsof -i :8085`
   - Change port in both server and client if needed

3. **Timeout errors**: Server not started
   - Start the MCP server first, then the ADK client

### Failure behaviour (no silent fallback)

`McpToolset` connects lazily, so creating it does not prove the server works. Use `uv run python verify_setup.py`
(MCP initialize → list_tools → `health_check`). If the toolset cannot even be constructed, `weather_agent` raises
`RuntimeError`. Set `ALLOW_NO_TOOLS_FALLBACK=1` only if you deliberately want a degraded agent with no tools; it
then reports `AGENT_MODE == "degraded"`, logs an error, and instructs the model to say weather is unavailable.
If the server is down at request time, ADK surfaces the connection error for that request.

## Environment Variables

Create `mcp-client/.env` (git-ignored; never commit it):
```bash
GOOGLE_API_KEY=<your Gemini key>
MCP_SERVER_URL=http://localhost:8085/mcp    # optional
GEMINI_MODEL=gemini-3.8-flash               # optional
```
Note: `gemini-2.5-flash` is no longer available to new API keys (HTTP 404). Run `adk web` from `mcp-client`
(port 8000), so do not run the Module 03 auth server on 8000 at the same time.

## Resources

- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [MCP Specification](https://modelcontextprotocol.io/)
- [FastMCP GitHub](https://github.com/jlowin/fastmcp)
- [WeatherAPI](https://www.weatherapi.com/)
