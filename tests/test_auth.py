"""Module 03 — xác thực bearer token trên server Streamable HTTP thật."""


import httpx
import pytest
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

import auth_server
from conftest import TEST_LIMITED_TOKEN, TEST_TOKEN

INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
               "clientInfo": {"name": "t", "version": "0"}},
}
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def post(url, auth=None):
    headers = dict(HEADERS)
    if auth is not None:
        headers["Authorization"] = auth
    return httpx.post(url, json=INIT, headers=headers, timeout=10)


def test_missing_token_is_401(auth_server_url):
    assert post(auth_server_url).status_code == 401


@pytest.mark.parametrize("header", [
    "Bearer wrong-token", "Bearer", TEST_TOKEN,  # thiếu scheme
    f"Basic {TEST_TOKEN}", f"Token {TEST_TOKEN}",
])
def test_invalid_or_malformed_authorization_is_401(auth_server_url, header):
    assert post(auth_server_url, header).status_code == 401


def test_valid_token_without_required_scope_is_403(auth_server_url):
    assert post(auth_server_url, f"Bearer {TEST_LIMITED_TOKEN}").status_code == 403


def test_valid_token_initializes(auth_server_url):
    r = post(auth_server_url, f"Bearer {TEST_TOKEN}")
    assert r.status_code == 200


def test_401_response_does_not_echo_token(auth_server_url):
    r = post(auth_server_url, "Bearer super-secret-wrong-token")
    assert "super-secret-wrong-token" not in r.text


async def test_authenticated_client_discovers_and_calls_tool(auth_server_url):
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    async with http:
        async with Client(streamable_http_client(auth_server_url, http_client=http)) as client:
            tools = (await client.list_tools()).tools
            assert [t.name for t in tools] == ["get_weather"]
            result = await client.call_tool("get_weather", {"city": "Hanoi"})
            assert result.content[0].text == "Hanoi: 29°C, trời mưa"


async def test_unauthenticated_client_cannot_initialize(auth_server_url):
    http = create_mcp_http_client(headers={"Authorization": "Bearer nope"})
    with pytest.raises(BaseException) as exc_info:  # noqa: B017 - anyio có thể bọc trong ExceptionGroup
        async with http:
            async with Client(streamable_http_client(auth_server_url, http_client=http)) as client:
                await client.list_tools()
    assert "nope" not in str(exc_info.value)


def test_load_tokens_from_environment_only():
    assert auth_server.load_tokens({}) == {}
    tokens = auth_server.load_tokens({"MCP_AUTH_TOKEN": "a", "MCP_LIMITED_TOKEN": "b"})
    assert tokens["a"][1] == [auth_server.REQUIRED_SCOPE]
    assert tokens["b"][1] == []


def test_source_has_no_hardcoded_default_credentials():
    from pathlib import Path
    for name in ("auth_server.py", "auth_client.py", "registry_client.py"):
        text = (Path(auth_server.__file__).parent / name).read_text(encoding="utf-8")
        assert "dev-token-abc123" not in text and "prod-key-xyz789" not in text
