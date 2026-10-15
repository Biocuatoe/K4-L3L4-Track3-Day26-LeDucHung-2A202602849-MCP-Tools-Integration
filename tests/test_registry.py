"""Module 03 — ToolRegistry: tìm kiếm, chọn version, cấu hình sai, dispatch stdio / HTTP."""

import json
from pathlib import Path

import pytest

import registry_client as rc
from conftest import TEST_TOKEN

REAL_REGISTRY = Path(rc.__file__).parent / "registry.json"


def make_registry(tmp_path, tools, servers=None, name="registry.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"tools": tools, "servers": servers or {}}), encoding="utf-8")
    return rc.ToolRegistry(path)


def tool(version="1.0.0", tags=("x",), server="s", deprecated=False, desc="d", **extra):
    return {"description": desc, "version": version, "tags": list(tags), "server": server,
            "deprecated": deprecated, **extra}


# ── tìm kiếm ─────────────────────────────────────────────────────────
def test_exact_lookup():
    reg = rc.ToolRegistry()
    assert reg.get("get_weather_v2")["version"] == "2.0.0"
    with pytest.raises(KeyError):
        reg.get("missing")


def test_search_by_tag_and_keyword_and_empty():
    reg = rc.ToolRegistry()
    assert {r["tool"] for r in reg.search(tag="weather")} == {"get_weather", "get_weather_v2"}
    assert [r["tool"] for r in reg.search(tag="email")] == ["send_email"]
    assert [r["tool"] for r in reg.search(keyword="FORECAST")] == ["get_weather_v2"]
    assert reg.search(tag="nonexistent") == []
    assert reg.search() == []


def test_search_matches_tag_or_keyword_without_duplicates():
    reg = rc.ToolRegistry()
    names = [r["tool"] for r in reg.search(tag="weather", keyword="forecast")]
    assert sorted(names) == ["get_weather", "get_weather_v2"]


def test_best_match_prefers_highest_semantic_version(tmp_path):
    reg = make_registry(tmp_path, {"a": tool("2.0.0"), "b": tool("10.0.0"), "c": tool("9.9.9")})
    assert reg.best_match(tag="x")["tool"] == "b"  # "10.0.0" > "2.0.0" (không so chuỗi)


def test_best_match_skips_deprecated_unless_all_deprecated(tmp_path):
    reg = make_registry(tmp_path, {"new": tool("1.0.0"), "old": tool("5.0.0", deprecated=True)})
    assert reg.best_match(tag="x")["tool"] == "new"
    reg = make_registry(
        tmp_path, {"old1": tool("1.0.0", deprecated=True), "old2": tool("3.0.0", deprecated=True)}
    )
    assert reg.best_match(tag="x")["tool"] == "old2"


def test_best_match_tie_is_deterministic(tmp_path):
    reg = make_registry(tmp_path, {"zeta": tool("1.0.0"), "alpha": tool("1.0.0")})
    assert reg.best_match(tag="x")["tool"] == "alpha"


def test_best_match_no_result_raises_keyerror():
    with pytest.raises(KeyError):
        rc.ToolRegistry().best_match(tag="nope")


# ── cấu hình không hợp lệ ────────────────────────────────────────────
def test_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(rc.RegistryError, match="JSON"):
        rc.ToolRegistry(p)


def test_missing_file(tmp_path):
    with pytest.raises(rc.RegistryError):
        rc.ToolRegistry(tmp_path / "nope.json")


def test_wrong_top_level_shape(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(rc.RegistryError):
        rc.ToolRegistry(p)


def test_tool_missing_fields_or_bad_version(tmp_path):
    with pytest.raises(rc.RegistryError, match="thiếu"):
        make_registry(tmp_path, {"t": {"description": "d"}})
    with pytest.raises(rc.RegistryError, match="version"):
        make_registry(tmp_path, {"t": tool("not-a-version")})


def test_real_registry_is_consistent():
    data = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
    for name, cfg in data["tools"].items():
        assert cfg["server"] in data["servers"], name
    for name, srv in data["servers"].items():
        assert srv["transport"] in {"stdio", "streamable-http"}, name


# ── connect_and_call ─────────────────────────────────────────────────
async def test_missing_server_definition(tmp_path):
    reg = make_registry(tmp_path, {"t": tool(server="ghost")})
    with pytest.raises(rc.RegistryError, match="chưa được định nghĩa"):
        await rc.connect_and_call(reg.get("t"), {})


async def test_unsupported_transport(tmp_path):
    reg = make_registry(tmp_path, {"t": tool()}, {"s": {"transport": "carrier-pigeon"}})
    with pytest.raises(rc.RegistryError, match="Transport"):
        await rc.connect_and_call(reg.get("t"), {})


async def test_missing_required_argument():
    match = rc.ToolRegistry().get("get_weather")
    with pytest.raises(rc.RegistryError, match="city"):
        await rc.connect_and_call(match, {})


async def test_stdio_dispatch_from_different_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reg = rc.ToolRegistry()
    out = await rc.connect_and_call(reg.get("get_weather"), {"city": "Hanoi"})
    assert out == "Hanoi: 29°C, trời mưa"
    best = reg.best_match(tag="weather")
    assert best["tool"] == "get_weather_v2"
    data = json.loads(await rc.connect_and_call(best, {"city": "Hanoi", "units": "fahrenheit"}))
    assert data["units"] == "fahrenheit"


async def test_relative_script_resolved_against_registry_dir(tmp_path):
    """Registry nằm ở thư mục khác: script tương đối phải tính từ thư mục registry đó."""
    (tmp_path / "srv").mkdir()
    (tmp_path / "srv" / "echo_server.py").write_text(
        "from mcp.server.mcpserver import MCPServer\n"
        "m = MCPServer('echo')\n"
        "@m.tool()\n"
        "def echo(text: str) -> str:\n    return 'echo:' + text\n"
        "m.run()\n",
        encoding="utf-8",
    )
    reg = make_registry(
        tmp_path,
        {"echo": tool(server="echo", parameters={"text": {"type": "string", "required": True}})},
        {"echo": {"transport": "stdio", "command": "python", "args": ["srv/echo_server.py"]}},
    )
    assert await rc.connect_and_call(reg.get("echo"), {"text": "hi"}) == "echo:hi"


async def test_tool_error_is_reported_as_registry_error():
    match = rc.ToolRegistry().get("get_weather_v2")
    with pytest.raises(rc.RegistryError, match="units"):
        await rc.connect_and_call(match, {"city": "Hanoi", "units": "kelvin"})


async def test_stdio_server_that_cannot_start_gives_sanitized_error(tmp_path):
    reg = make_registry(
        tmp_path, {"t": tool()}, {"s": {"transport": "stdio", "command": "no-such-binary-xyz"}}
    )
    with pytest.raises(rc.RegistryError, match="thất bại"):
        await rc.connect_and_call(reg.get("t"), {})


def _http_registry(tmp_path, url):
    return make_registry(
        tmp_path,
        {"get_weather": tool(parameters={"city": {"required": True}})},
        {"s": {"transport": "streamable-http", "url": url,
               "auth": {"type": "bearer", "token_env": "TEST_MCP_TOKEN"}}},
    )


async def test_http_dispatch_with_bearer_token(auth_server_url, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MCP_TOKEN", TEST_TOKEN)
    reg = _http_registry(tmp_path, auth_server_url)
    out = await rc.connect_and_call(reg.get("get_weather"), {"city": "Hanoi"})
    assert out == "Hanoi: 29°C, trời mưa"


async def test_http_dispatch_missing_token_env(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_MCP_TOKEN", raising=False)
    reg = _http_registry(tmp_path, "http://127.0.0.1:1/mcp")
    with pytest.raises(rc.RegistryError, match="TEST_MCP_TOKEN"):
        await rc.connect_and_call(reg.get("get_weather"), {"city": "Hanoi"})


async def test_http_dispatch_rejected_token_does_not_leak(auth_server_url, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MCP_TOKEN", "leaky-secret-wrong-token")
    reg = _http_registry(tmp_path, auth_server_url)
    with pytest.raises(rc.RegistryError) as exc:
        await rc.connect_and_call(reg.get("get_weather"), {"city": "Hanoi"})
    assert "leaky-secret-wrong-token" not in str(exc.value)
