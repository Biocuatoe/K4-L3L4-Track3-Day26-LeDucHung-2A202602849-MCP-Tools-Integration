"""weather_agent.agent — cấu hình MCP, hành vi lỗi tường minh, fallback phải bật chủ động."""

import importlib

import pytest

from weather_agent import agent as agent_module


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-tests")


def find_toolset(agent):
    return next(t for t in agent.tools if hasattr(t, "_connection_params"))


def test_default_agent_uses_mcp_toolset():
    assert agent_module.AGENT_MODE == "mcp"
    toolset = find_toolset(agent_module.root_agent)
    assert toolset._connection_params.url.endswith("/mcp")
    assert agent_module.root_agent.name == "weather_agent"


def test_expected_tools_are_the_three_weather_tools():
    assert set(agent_module.EXPECTED_TOOLS) == {"get_current_weather", "get_forecast", "health_check"}
    toolset = find_toolset(agent_module.root_agent)
    assert set(toolset.tool_filter) == set(agent_module.EXPECTED_TOOLS)


def test_instruction_forbids_inventing_data():
    assert "never invent" in agent_module.INSTRUCTION


def test_mcp_server_url_comes_from_environment(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://example.test:9999/mcp")
    reloaded = importlib.reload(agent_module)
    try:
        assert find_toolset(reloaded.root_agent)._connection_params.url == "http://example.test:9999/mcp"
    finally:
        monkeypatch.undo()
        importlib.reload(agent_module)


def test_model_is_configurable(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "some-other-model")
    reloaded = importlib.reload(agent_module)
    try:
        assert reloaded.root_agent.model == "some-other-model"
    finally:
        monkeypatch.undo()
        importlib.reload(agent_module)


def _break_toolset(monkeypatch):
    def boom(**kwargs):
        raise ConnectionError("simulated toolset failure")
    monkeypatch.setattr(agent_module, "McpToolset", boom)


def test_toolset_failure_raises_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_NO_TOOLS_FALLBACK", raising=False)
    _break_toolset(monkeypatch)
    with pytest.raises(RuntimeError, match="MCP toolset"):
        agent_module.build_agent("http://localhost:1/mcp")


def test_fallback_requires_explicit_opt_in_and_is_visible(monkeypatch):
    _break_toolset(monkeypatch)
    degraded = agent_module.build_agent("http://localhost:1/mcp", allow_fallback=True)
    try:
        assert agent_module.AGENT_MODE == "degraded"
        assert not degraded.tools
        assert "UNAVAILABLE" in degraded.instruction
    finally:
        monkeypatch.undo()
        agent_module.build_agent()  # đưa AGENT_MODE về "mcp"


def test_fallback_env_var(monkeypatch):
    monkeypatch.setenv("ALLOW_NO_TOOLS_FALLBACK", "1")
    _break_toolset(monkeypatch)
    try:
        assert not agent_module.build_agent("http://localhost:1/mcp").tools
    finally:
        monkeypatch.undo()
        agent_module.build_agent()
