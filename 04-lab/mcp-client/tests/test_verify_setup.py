"""verify_setup — kiểm tra từng bước, mã thoát, và không lộ API key. Không cần key/dịch vụ thật."""

import asyncio
import socket
import threading
import time

import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

import verify_setup as vs

FAKE_KEY = "AIza-fake-key-for-tests-0123456789"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_server(tool_names):
    """Chạy một MCP server thật (Streamable HTTP) với các tool chỉ định."""
    port = free_port()
    mcp = FastMCP("fake-weather", host="127.0.0.1", port=port)
    for name in tool_names:
        def make(n):
            async def tool() -> str:
                return f"ok from {n}"
            tool.__name__ = n
            return tool
        mcp.tool()(make(name))
    server = uvicorn.Server(
        uvicorn.Config(mcp.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server, thread, f"http://127.0.0.1:{port}/mcp"


@pytest.fixture
def full_server():
    server, thread, url = run_server(sorted(vs.EXPECTED_TOOLS))
    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def partial_server():
    server, thread, url = run_server(["health_check"])
    yield url
    server.should_exit = True
    thread.join(timeout=5)


def statuses(results):
    return {r.name: r.status for r in results}


# ── environment ──────────────────────────────────────────────────────
@pytest.mark.parametrize("value", ["", "your_google_api_key_here", "  "])
def test_environment_rejects_missing_or_placeholder_key(monkeypatch, value):
    monkeypatch.setenv("GOOGLE_API_KEY", value)
    assert vs.check_environment().status == vs.FAIL


def test_environment_never_reveals_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", FAKE_KEY)
    result = vs.check_environment()
    assert result.status == vs.PASS
    assert FAKE_KEY not in result.message and FAKE_KEY[:6] not in result.message


def test_structure_check(tmp_path):
    assert vs.check_structure(tmp_path).status == vs.FAIL
    (tmp_path / "weather_agent").mkdir()
    (tmp_path / "weather_agent" / "agent.py").write_text("")
    (tmp_path / "weather_agent" / "__init__.py").write_text("")
    assert vs.check_structure(tmp_path).status == vs.PASS


def test_dependencies_check_passes_in_project_env():
    assert vs.check_dependencies().status == vs.PASS


# ── http + mcp ───────────────────────────────────────────────────────
def test_http_unreachable_is_failure():
    r = vs.check_http(f"http://127.0.0.1:{free_port()}/mcp", timeout=2)
    assert r.status == vs.FAIL and "weather.py" in r.message


def test_http_reachable_is_not_mcp_proof(full_server):
    assert vs.check_http(full_server).status == vs.PASS


def test_mcp_checks_pass_against_real_server(full_server):
    results = asyncio.run(vs.run_mcp_checks(full_server, timeout=15))
    assert statuses(results) == {
        "mcp-initialize": vs.PASS, "tool-discovery": vs.PASS, "health-check-call": vs.PASS}
    assert "ok from health_check" in results[2].message


def test_mcp_checks_report_missing_tools(partial_server):
    results = statuses(asyncio.run(vs.run_mcp_checks(partial_server, timeout=15)))
    assert results["mcp-initialize"] == vs.PASS
    assert results["tool-discovery"] == vs.FAIL
    assert results["health-check-call"] == vs.SKIP


def test_mcp_checks_fail_on_non_mcp_endpoint():
    results = statuses(asyncio.run(vs.run_mcp_checks(f"http://127.0.0.1:{free_port()}/mcp", timeout=5)))
    assert results["mcp-initialize"] == vs.FAIL
    assert results["tool-discovery"] == results["health-check-call"] == vs.SKIP


# ── orchestration / exit codes ───────────────────────────────────────
def test_main_offline_success_exit_code_0(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(vs, "_load_env", lambda: None)
    assert vs.main(["--offline"]) == 0
    out = capsys.readouterr().out
    assert FAKE_KEY not in out and "⏭️" in out


def test_main_fails_with_exit_code_1_when_key_missing(monkeypatch, capsys):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(vs, "_load_env", lambda: None)
    assert vs.main(["--offline"]) == 1
    assert "environment" in capsys.readouterr().out


def test_main_online_with_server_down_fails(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("MCP_SERVER_URL", f"http://127.0.0.1:{free_port()}/mcp")
    monkeypatch.setattr(vs, "_load_env", lambda: None)
    results = statuses(vs.run_checks(offline=False))
    assert results["http-reachability"] == vs.FAIL
    assert results["mcp-initialize"] == vs.SKIP
    assert vs.main([]) == 1


def test_main_online_full_success(monkeypatch, full_server):
    monkeypatch.setenv("GOOGLE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("MCP_SERVER_URL", full_server)
    monkeypatch.setattr(vs, "_load_env", lambda: None)
    results = vs.run_checks(offline=False)
    assert all(r.status == vs.PASS for r in results), [(r.name, r.message) for r in results]
    assert vs.main([]) == 0
