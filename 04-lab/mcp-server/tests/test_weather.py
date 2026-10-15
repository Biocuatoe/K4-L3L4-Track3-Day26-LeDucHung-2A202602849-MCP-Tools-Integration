"""Lab 04 server — WeatherAPI được giả lập bằng httpx.MockTransport (không gọi mạng, không cần key thật)."""

import logging

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

import weather

FAKE_KEY = "unit-test-fake-key"

CURRENT = {
    "location": {"name": "Hanoi", "region": "", "country": "Vietnam"},
    "current": {
        "temp_c": 30.0, "temp_f": 86.0, "feelslike_c": 33.0, "feelslike_f": 91.4,
        "condition": {"text": "Sunny"}, "humidity": 60, "wind_kph": 10.0, "wind_mph": 6.2,
        "wind_dir": "N", "pressure_mb": 1010.0, "uv": 5.0, "vis_km": 10.0,
        "last_updated": "2026-01-01 12:00",
    },
}


def forecast_payload(days):
    return {
        "location": CURRENT["location"],
        "forecast": {"forecastday": [
            {"date": f"2026-01-0{i + 1}", "day": {
                "maxtemp_c": 31.0, "maxtemp_f": 87.8, "mintemp_c": 24.0, "mintemp_f": 75.2,
                "condition": {"text": "Rain"}, "daily_chance_of_rain": 80,
                "maxwind_kph": 12.0, "uv": 4.0}}
            for i in range(days)
        ]},
    }


@pytest.fixture
def upstream(monkeypatch):
    """Cho phép mỗi test đặt handler giả cho WeatherAPI; ghi lại request đã gửi."""
    monkeypatch.setenv("WEATHERAPI_KEY", FAKE_KEY)
    state = {"requests": [], "handler": lambda req: httpx.Response(200, json=CURRENT)}

    def handler(request):
        state["requests"].append(request)
        return state["handler"](request)

    monkeypatch.setattr(
        weather, "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5),
    )
    return state


async def test_current_weather_success(upstream):
    text = await weather.get_current_weather("Hanoi")
    assert "Current Weather for Hanoi, Vietnam:" in text  # vùng rỗng bị bỏ qua
    assert "30.0°C (86.0°F)" in text and "Sunny" in text
    req = upstream["requests"][0]
    assert req.url.path.endswith("/current.json") and req.url.params["q"] == "Hanoi"


async def test_city_is_stripped(upstream):
    await weather.get_current_weather("  Hanoi  ")
    assert upstream["requests"][0].url.params["q"] == "Hanoi"


@pytest.mark.parametrize("days", [1, 2, 3])
async def test_forecast_success(upstream, days):
    upstream["handler"] = lambda req: httpx.Response(200, json=forecast_payload(days))
    text = await weather.get_forecast("Hanoi", days)
    assert text.count("Chance of Rain: 80%") == days
    assert upstream["requests"][0].url.params["days"] == str(days)


@pytest.mark.parametrize("days", [0, -1, 4, 10, True, 2.5, "3", None])
async def test_forecast_rejects_invalid_days(upstream, days):
    with pytest.raises(weather.WeatherError, match="days"):
        await weather.get_forecast("Hanoi", days)
    assert upstream["requests"] == []  # không gọi upstream khi input sai


@pytest.mark.parametrize("city", ["", "   ", None, 5, "x" * 101, "a\nb"])
async def test_rejects_invalid_city(upstream, city):
    with pytest.raises(weather.WeatherError, match="city"):
        await weather.get_current_weather(city)
    assert upstream["requests"] == []


async def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("WEATHERAPI_KEY", raising=False)
    with pytest.raises(weather.WeatherError, match="WEATHERAPI_KEY"):
        await weather.get_current_weather("Hanoi")


@pytest.mark.parametrize("status", [401, 403])
async def test_invalid_key(upstream, status):
    upstream["handler"] = lambda req: httpx.Response(
        status, json={"error": {"code": 2006, "message": "API key is invalid."}})
    with pytest.raises(weather.WeatherError, match="API key") as exc:
        await weather.get_current_weather("Hanoi")
    assert FAKE_KEY not in str(exc.value)


async def test_unknown_city_400(upstream):
    upstream["handler"] = lambda req: httpx.Response(
        400, json={"error": {"code": 1006, "message": "No matching location found."}})
    with pytest.raises(weather.WeatherError, match="No matching location found"):
        await weather.get_current_weather("zzzz")


async def test_other_http_status(upstream):
    upstream["handler"] = lambda req: httpx.Response(503, text="oops")
    with pytest.raises(weather.WeatherError, match="503"):
        await weather.get_current_weather("Hanoi")


async def test_timeout(upstream):
    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)
    upstream["handler"] = boom
    with pytest.raises(weather.WeatherError, match="timeout"):
        await weather.get_current_weather("Hanoi")


async def test_network_failure_message_has_no_url_or_key(upstream):
    def boom(req):
        raise httpx.ConnectError(f"cannot connect to {req.url}", request=req)
    upstream["handler"] = boom
    with pytest.raises(weather.WeatherError) as exc:
        await weather.get_current_weather("Hanoi")
    assert FAKE_KEY not in str(exc.value) and "http" not in str(exc.value)


async def test_invalid_json(upstream):
    upstream["handler"] = lambda req: httpx.Response(200, text="<html>not json</html>")
    with pytest.raises(weather.WeatherError, match="JSON"):
        await weather.get_current_weather("Hanoi")


async def test_non_object_json(upstream):
    upstream["handler"] = lambda req: httpx.Response(200, json=[1, 2])
    with pytest.raises(weather.WeatherError):
        await weather.get_current_weather("Hanoi")


async def test_missing_fields_in_response(upstream):
    upstream["handler"] = lambda req: httpx.Response(200, json={"location": {"name": "X"}})
    with pytest.raises(weather.WeatherError, match="thiếu trường"):
        await weather.get_current_weather("Hanoi")
    upstream["handler"] = lambda req: httpx.Response(200, json={"location": {}, "forecast": {}})
    with pytest.raises(weather.WeatherError, match="thiếu trường"):
        await weather.get_forecast("Hanoi", 1)


async def test_health_check_reports_key_state_without_value(monkeypatch):
    monkeypatch.setenv("WEATHERAPI_KEY", FAKE_KEY)
    text = await weather.health_check()
    assert "configured" in text and FAKE_KEY not in text
    monkeypatch.delenv("WEATHERAPI_KEY")
    assert "MISSING" in await weather.health_check()


async def test_api_key_never_logged(upstream, caplog):
    with caplog.at_level(logging.DEBUG):
        await weather.get_current_weather("Hanoi")
    assert FAKE_KEY not in caplog.text
    assert logging.getLogger("httpx").level >= logging.WARNING


async def test_key_sent_as_query_param_only_to_weatherapi(upstream):
    await weather.get_current_weather("Hanoi")
    req = upstream["requests"][0]
    assert req.url.host == "api.weatherapi.com"
    assert req.url.params["key"] == FAKE_KEY


async def test_mcp_discovery_and_invocation(upstream):
    """Qua giao thức MCP thật (in-process): đủ 3 tool, lỗi được đánh dấu isError."""
    async with create_connected_server_and_client_session(weather.mcp._mcp_server) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert set(tools) == {"get_current_weather", "get_forecast", "health_check"}
        assert tools["get_forecast"].inputSchema["required"] == ["city"]

        ok = await session.call_tool("get_current_weather", {"city": "Hanoi"})
        assert not ok.isError and "Sunny" in ok.content[0].text

        bad = await session.call_tool("get_forecast", {"city": "Hanoi", "days": 9})
        assert bad.isError and "days" in bad.content[0].text

        health = await session.call_tool("health_check", {})
        assert not health.isError


def test_settings_defaults():
    assert weather.MAX_FORECAST_DAYS == 3
    assert weather.REQUEST_TIMEOUT.read == 15.0
    assert weather.mcp.settings.port == weather.PORT
