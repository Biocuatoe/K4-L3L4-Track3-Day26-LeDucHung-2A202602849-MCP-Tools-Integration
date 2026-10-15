"""Weather Agent — Gemini (Google ADK) dùng tool từ một MCP server qua Streamable HTTP.

Biến môi trường (đặt trong .env, xem README):
    GOOGLE_API_KEY            API key Gemini (ADK/google-genai tự đọc)
    MCP_SERVER_URL            URL endpoint MCP, mặc định http://localhost:8085/mcp
    GEMINI_MODEL              tên model, mặc định gemini-3.8-flash (gemini-2.5-flash đã bị Google gỡ với key mới)
    ALLOW_NO_TOOLS_FALLBACK   "1" để CHO PHÉP chạy chế độ suy giảm (không có tool)
                              khi khởi tạo MCP toolset lỗi. Mặc định: KHÔNG — lỗi
                              được ném ra để không giả vờ là weather agent đầy đủ.

Lưu ý: McpToolset kết nối LAZY (chỉ khi agent cần danh sách tool), nên tạo được
đối tượng chưa chứng minh server hoạt động. Dùng `python verify_setup.py` để
kiểm tra MCP thật (initialize → list_tools → gọi health_check).
"""

from __future__ import annotations

import logging
import os

from google.adk import Agent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams

logger = logging.getLogger(__name__)

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8085/mcp")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
EXPECTED_TOOLS = ("get_current_weather", "get_forecast", "health_check")

INSTRUCTION = (
    "You are a weather assistant. For ANY question about current weather or forecasts "
    "you MUST call the provided tools (get_current_weather, get_forecast); never invent "
    "weather data. Forecasts support at most 3 days. If a tool returns an error, tell "
    "the user what went wrong instead of guessing."
)
DEGRADED_INSTRUCTION = (
    "The weather tools are UNAVAILABLE because the MCP server connection could not be "
    "initialised. Tell the user you cannot provide weather data right now; never invent it."
)

#: "mcp" khi có MCP toolset, "degraded" khi chạy fallback không có tool (phải bật tường minh).
AGENT_MODE = "mcp"


def build_agent(url: str = MCP_SERVER_URL, *, allow_fallback: bool | None = None) -> Agent:
    """Tạo agent. Lỗi khởi tạo MCP toolset được ném ra trừ khi fallback được bật tường minh."""
    global AGENT_MODE
    if allow_fallback is None:
        allow_fallback = os.getenv("ALLOW_NO_TOOLS_FALLBACK") == "1"
    try:
        toolset = McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=url,
                timeout=30.0,  # Cloud Run cold start có thể chậm
            ),
            tool_filter=list(EXPECTED_TOOLS),
        )
        AGENT_MODE = "mcp"
        logger.info("Weather agent configured with MCP server %s", url)
        return Agent(name="weather_agent", model=MODEL, instruction=INSTRUCTION, tools=[toolset])
    except Exception as exc:
        if not allow_fallback:
            raise RuntimeError(
                f"Không khởi tạo được MCP toolset cho {url}: {type(exc).__name__}: {exc}. "
                "Đặt ALLOW_NO_TOOLS_FALLBACK=1 nếu muốn chạy chế độ suy giảm không có tool."
            ) from exc
        AGENT_MODE = "degraded"
        logger.error("DEGRADED MODE: weather agent has NO tools (%s: %s)", type(exc).__name__, exc)
        return Agent(name="weather_agent", model=MODEL, instruction=DEGRADED_INSTRUCTION)


root_agent = build_agent()
