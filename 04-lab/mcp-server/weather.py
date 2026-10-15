"""Weather MCP server (Streamable HTTP) — dữ liệu thật từ WeatherAPI.com.

Biến môi trường:
    WEATHERAPI_KEY  (bắt buộc) API key của weatherapi.com — chỉ đọc từ môi trường
    PORT            (tuỳ chọn) cổng lắng nghe, mặc định 8085 (Cloud Run tự đặt PORT)
    HOST            (tuỳ chọn) địa chỉ bind, mặc định 127.0.0.1 (Dockerfile đặt 0.0.0.0)

Chạy:
    uv run python weather.py            # Streamable HTTP tại http://127.0.0.1:8085/mcp
    uv run python weather.py --stdio    # chế độ stdio cho client cục bộ
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

PORT = int(os.getenv("PORT", "8085"))
HOST = os.getenv("HOST", "127.0.0.1")
mcp = FastMCP("weather", host=HOST, port=PORT)

WEATHERAPI_BASE = "https://api.weatherapi.com/v1"
USER_AGENT = "weather-app/1.0"
REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
MAX_FORECAST_DAYS = 3  # giới hạn gói miễn phí của WeatherAPI
MAX_CITY_LENGTH = 100

# httpx/httpcore ghi URL (có chứa ?key=...) ở mức INFO — tắt để không lộ API key vào log.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class WeatherError(Exception):
    """Lỗi có thông điệp AN TOÀN (không chứa API key/URL) để trả về cho client."""


def _api_key() -> str:
    key = os.getenv("WEATHERAPI_KEY")
    if not key:
        raise WeatherError(
            "WeatherAPI key chưa được cấu hình: hãy đặt biến môi trường WEATHERAPI_KEY."
        )
    return key


def _http_client() -> httpx.AsyncClient:
    """Tạo httpx client (tách ra để test có thể thay bằng MockTransport)."""
    return httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})


def validate_city(city: Any) -> str:
    if not isinstance(city, str) or not city.strip():
        raise WeatherError("'city' phải là chuỗi không rỗng.")
    city = city.strip()
    if len(city) > MAX_CITY_LENGTH or any(ord(c) < 32 for c in city):
        raise WeatherError("'city' không hợp lệ (quá dài hoặc chứa ký tự điều khiển).")
    return city


def validate_days(days: Any) -> int:
    if isinstance(days, bool) or not isinstance(days, int):
        raise WeatherError("'days' phải là số nguyên.")
    if not 1 <= days <= MAX_FORECAST_DAYS:
        raise WeatherError(
            f"'days' phải trong khoảng 1-{MAX_FORECAST_DAYS} (giới hạn gói miễn phí), nhận {days}."
        )
    return days


async def make_weather_request(endpoint: str, params: dict[str, str]) -> dict[str, Any]:
    """Gọi WeatherAPI; ném WeatherError (thông điệp đã làm sạch) nếu thất bại."""
    key = _api_key()
    url = f"{WEATHERAPI_BASE}/{endpoint}"
    try:
        async with _http_client() as client:
            response = await client.get(url, params={**params, "key": key})
    except httpx.TimeoutException:
        raise WeatherError("WeatherAPI không phản hồi kịp (timeout). Hãy thử lại sau.") from None
    except httpx.RequestError as exc:
        raise WeatherError(
            f"Không kết nối được tới WeatherAPI ({type(exc).__name__})."
        ) from None
    except Exception as exc:  # noqa: BLE001
        raise WeatherError(f"Lỗi không mong đợi khi gọi WeatherAPI ({type(exc).__name__}).") from None

    if response.status_code != 200:
        detail = ""
        try:
            err = response.json().get("error", {})
            detail = f" — {str(err.get('message', '')).rstrip('.')}" if err.get('message') else ""
        except (ValueError, AttributeError):
            pass
        status = response.status_code
        if status in (401, 403):
            raise WeatherError(
                f"WeatherAPI từ chối API key (HTTP {status}): key không hợp lệ, "
                f"bị vô hiệu hoá hoặc hết hạn mức{detail}."
            )
        if status == 400:
            raise WeatherError(
                f"WeatherAPI không xử lý được yêu cầu (HTTP 400){detail}. "
                "Hãy kiểm tra lại tên thành phố."
            )
        raise WeatherError(f"WeatherAPI trả về lỗi HTTP {status}{detail}.")

    try:
        data = response.json()
    except ValueError:
        raise WeatherError("WeatherAPI trả về dữ liệu không phải JSON hợp lệ.") from None
    if not isinstance(data, dict):
        raise WeatherError("WeatherAPI trả về JSON có cấu trúc không mong đợi.")
    return data


def _place(location: dict[str, Any]) -> str:
    return ", ".join(str(location[k]) for k in ("name", "region", "country") if location.get(k))


def _format_current(data: dict[str, Any]) -> str:
    try:
        current, location = data["current"], data["location"]
        return f"""
Current Weather for {_place(location)}:

Temperature: {current['temp_c']}°C ({current['temp_f']}°F)
Feels like: {current['feelslike_c']}°C ({current['feelslike_f']}°F)
Condition: {current['condition']['text']}
Humidity: {current['humidity']}%
Wind: {current['wind_kph']} km/h ({current['wind_mph']} mph) {current['wind_dir']}
Pressure: {current['pressure_mb']} mb
UV Index: {current['uv']}
Visibility: {current['vis_km']} km

Last updated: {current['last_updated']}
"""
    except (KeyError, TypeError):
        raise WeatherError("WeatherAPI trả về dữ liệu thiếu trường cần thiết.") from None


def _format_forecast(data: dict[str, Any]) -> str:
    try:
        location = data["location"]
        parts = [
            f"Weather Forecast for {_place(location)}:"
        ]
        for day in data["forecast"]["forecastday"]:
            d = day["day"]
            parts.append(f"""
{day['date']}:
High: {d['maxtemp_c']}°C ({d['maxtemp_f']}°F)
Low: {d['mintemp_c']}°C ({d['mintemp_f']}°F)
Condition: {d['condition']['text']}
Chance of Rain: {d['daily_chance_of_rain']}%
Max Wind: {d['maxwind_kph']} km/h
UV Index: {d['uv']}
""")
        return "\n---\n".join(parts)
    except (KeyError, TypeError):
        raise WeatherError("WeatherAPI trả về dữ liệu thiếu trường cần thiết.") from None


@mcp.tool()
async def get_current_weather(city: str) -> str:
    """Get current weather conditions for a city.

    Args:
        city: City name (e.g., "Hanoi", "Haiphong", "Danang", "Brisbane", "Sydney")
    """
    city = validate_city(city)
    data = await make_weather_request("current.json", {"q": city, "aqi": "no"})
    return _format_current(data)


@mcp.tool()
async def get_forecast(city: str, days: int = 3) -> str:
    """Get weather forecast for a city.

    Args:
        city: City name (e.g., "Hanoi", "Haiphong", "Danang", "Brisbane", "Sydney", "Melbourne")
        days: Number of days to forecast, 1-3 (free tier limit). Other values are rejected.
    """
    city = validate_city(city)
    days = validate_days(days)
    data = await make_weather_request(
        "forecast.json", {"q": city, "days": str(days), "aqi": "no", "alerts": "no"}
    )
    return _format_forecast(data)


@mcp.tool()
async def health_check() -> str:
    """Health check endpoint for deployment verification."""
    key_state = "configured" if os.getenv("WEATHERAPI_KEY") else "MISSING (set WEATHERAPI_KEY)"
    return f"✅ Weather MCP Server is running. WeatherAPI key: {key_state}."


if __name__ == "__main__":
    # Log chẩn đoán đi vào stderr để không làm hỏng giao thức stdio.
    if "--stdio" in sys.argv[1:]:
        print("Starting weather MCP server (stdio)", file=sys.stderr)
        mcp.run(transport="stdio")
    else:
        print(f"Starting weather MCP server on http://{HOST}:{PORT}/mcp", file=sys.stderr)
        mcp.run(transport="streamable-http")
