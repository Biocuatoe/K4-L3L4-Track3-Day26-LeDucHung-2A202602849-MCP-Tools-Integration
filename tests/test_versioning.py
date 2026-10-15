"""Module 03 — versioned_server: v1 tương thích ngược, v2, đổi đơn vị nhất quán."""

import json

import pytest
from mcp import Client

import versioned_server


async def call(_unused, name, args):
    """Mỗi lần gọi mở một phiên MCP in-process riêng (tránh async-generator fixture)."""
    async with Client(versioned_server.mcp) as client:
        r = await client.call_tool(name, args)
        return r, r.content[0].text


class _Session:
    """Giữ API `client.list_tools()` / `client.read_resource()` cho các test metadata."""

    def __getattr__(self, name):
        async def run(*a, **kw):
            async with Client(versioned_server.mcp) as c:
                return await getattr(c, name)(*a, **kw)

        return run


@pytest.fixture
def client():
    return _Session()


async def test_tool_discovery_has_both_versions(client):
    names = {t.name for t in (await client.list_tools()).tools}
    assert names == {"get_weather", "get_weather_v2"}


async def test_v1_contract_unchanged(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["get_weather"].input_schema["required"] == ["city"]
    assert set(tools["get_weather"].input_schema["properties"]) == {"city"}
    r, text = await call(client, "get_weather", {"city": "Hanoi"})
    assert not r.is_error and text == "Hanoi: 29°C, trời mưa"
    _, text = await call(client, "get_weather", {"city": "Atlantis"})
    assert text == "Atlantis: 28°C, không có dữ liệu chi tiết"


async def test_v2_defaults(client):
    r, text = await call(client, "get_weather_v2", {"city": "Hanoi"})
    data = json.loads(text)
    assert not r.is_error
    assert data["api_version"] == "2.0" and data["units"] == "celsius" and data["temp"] == 29
    assert "forecast" not in data


async def test_v2_unknown_city(client):
    _, text = await call(client, "get_weather_v2", {"city": "Atlantis"})
    assert json.loads(text)["error"] == "không có dữ liệu"


async def test_v2_forecast_celsius(client):
    _, text = await call(client, "get_weather_v2", {"city": "Hanoi", "include_forecast": True})
    assert [d["temp"] for d in json.loads(text)["forecast"]] == [27, 31]


async def test_v2_forecast_false_has_no_forecast(client):
    _, text = await call(client, "get_weather_v2", {"city": "Hanoi", "include_forecast": False})
    assert "forecast" not in json.loads(text)


async def test_v2_fahrenheit_converts_current_and_forecast(client):
    _, text = await call(
        client, "get_weather_v2",
        {"city": "Hanoi", "include_forecast": True, "units": "fahrenheit"},
    )
    data = json.loads(text)
    assert data["units"] == "fahrenheit"
    assert data["temp"] == 84.2
    assert [d["temp"] for d in data["forecast"]] == [80.6, 87.8]


async def test_fahrenheit_does_not_mutate_data_between_calls(client):
    await call(client, "get_weather_v2",
               {"city": "Hanoi", "include_forecast": True, "units": "fahrenheit"})
    _, text = await call(client, "get_weather_v2", {"city": "Hanoi", "include_forecast": True})
    assert [d["temp"] for d in json.loads(text)["forecast"]] == [27, 31]


@pytest.mark.parametrize("units", ["kelvin", "", "C", None])
async def test_v2_rejects_invalid_units(client, units):
    r, text = await call(client, "get_weather_v2", {"city": "Hanoi", "units": units})
    assert r.is_error


async def test_invalid_units_message_names_the_problem(client):
    r, text = await call(client, "get_weather_v2", {"city": "Hanoi", "units": "kelvin"})
    assert r.is_error and "units" in text


async def test_units_are_case_insensitive_and_normalised(client):
    _, text = await call(client, "get_weather_v2", {"city": "Hanoi", "units": "Fahrenheit"})
    assert json.loads(text)["units"] == "fahrenheit"


async def test_server_info_resource(client):
    resources = (await client.list_resources()).resources
    assert "server://info" in {str(r.uri) for r in resources}
    meta = json.loads((await client.read_resource("server://info")).contents[0].text)
    assert meta["version"] == versioned_server.SERVER_VERSION
    assert meta["deprecated_tools"] == ["get_weather"]
    assert "get_weather_v2" in meta["migration_guide"]
