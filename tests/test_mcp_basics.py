"""Module 02 — khám phá và gọi tool qua giao thức MCP thật (in-process và stdio subprocess)."""

import sys
from pathlib import Path

from mcp import Client

import weather_client
import weather_server


async def test_in_process_discovery_and_call():
    async with Client(weather_server.mcp) as client:
        tools = (await client.list_tools()).tools
        assert [t.name for t in tools] == ["get_weather"]
        schema = tools[0].input_schema
        assert schema["required"] == ["city"]
        assert schema["properties"]["city"]["type"] == "string"

        ok = await client.call_tool("get_weather", {"city": "Hanoi"})
        assert not ok.is_error
        assert ok.content[0].text == "Hanoi: 29°C, trời mưa"

        unknown = await client.call_tool("get_weather", {"city": "Atlantis"})
        assert "không có dữ liệu" in unknown.content[0].text


async def test_invalid_arguments_flagged_as_error():
    async with Client(weather_server.mcp) as client:
        missing = await client.call_tool("get_weather", {})
        wrong_type = await client.call_tool("get_weather", {"city": 123})
        unknown_tool = await client.call_tool("nope", {"city": "x"})
        assert missing.is_error and wrong_type.is_error and unknown_tool.is_error


def test_client_uses_absolute_server_path_and_current_interpreter():
    params = weather_client.server_params()
    assert params.command == sys.executable
    assert Path(params.args[0]).is_absolute() and Path(params.args[0]).is_file()


async def test_stdio_subprocess_from_other_cwd(tmp_path, monkeypatch):
    """Server thật chạy bằng stdio; stdout chỉ chứa thông điệp MCP hợp lệ."""
    monkeypatch.chdir(tmp_path)
    async with Client(weather_client.server_params()) as client:
        result = await client.call_tool("get_weather", {"city": "Danang"})
        assert result.content[0].text == "Danang: 30°C, nhiều mây"
