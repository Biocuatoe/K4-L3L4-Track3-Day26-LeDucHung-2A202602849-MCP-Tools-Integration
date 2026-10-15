#!/usr/bin/env python3
"""Kiểm tra cài đặt Weather Agent — báo cáo từng bước độc lập.

Các bước: environment, dependencies, structure, endpoint reachability,
MCP initialize, tool discovery, health_check, agent import.

Cách chạy (từ thư mục mcp-client):
    uv run python verify_setup.py            # đầy đủ (cần MCP server đang chạy)
    uv run python verify_setup.py --offline  # bỏ qua các bước cần server

Exit code: 0 = mọi bước chạy đều đạt; 1 = có bước thất bại; 2 = tham số sai.
Script KHÔNG bao giờ in API key (kể cả một phần).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_URL = "http://localhost:8085/mcp"
EXPECTED_TOOLS = {"get_current_weather", "get_forecast", "health_check"}
PLACEHOLDERS = {"", "your_google_api_key_here", "your_key", "changeme"}

PASS, FAIL, SKIP = "pass", "fail", "skip"
ICON = {PASS: "✅", FAIL: "❌", SKIP: "⏭️ "}


@dataclass
class CheckResult:
    name: str
    status: str
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status != FAIL


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(HERE / ".env")
    except ImportError:
        pass


def server_url() -> str:
    return os.getenv("MCP_SERVER_URL", DEFAULT_URL)


def check_environment() -> CheckResult:
    key = os.getenv("GOOGLE_API_KEY", "")
    if key.strip().lower() in PLACEHOLDERS:
        return CheckResult(
            "environment", FAIL,
            "GOOGLE_API_KEY chưa được cấu hình trong .env (lấy key tại https://aistudio.google.com/apikey)",
        )
    return CheckResult("environment", PASS, f"GOOGLE_API_KEY đã đặt; MCP_SERVER_URL={server_url()}")


def check_dependencies() -> CheckResult:
    required = ["google.adk", "mcp", "dotenv", "httpx"]
    missing = []
    for pkg in required:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return CheckResult("dependencies", FAIL, f"thiếu: {', '.join(missing)} — chạy `uv sync`")
    return CheckResult("dependencies", PASS, ", ".join(required))


def check_structure(root: Path = HERE) -> CheckResult:
    needed = ["weather_agent/agent.py", "weather_agent/__init__.py"]
    missing = [p for p in needed if not (root / p).is_file()]
    if missing:
        return CheckResult("structure", FAIL, f"thiếu file: {', '.join(missing)}")
    return CheckResult("structure", PASS, ", ".join(needed))


def check_http(url: str, timeout: float = 10.0) -> CheckResult:
    """Chỉ kiểm tra TCP/HTTP có phản hồi — KHÔNG chứng minh MCP hoạt động."""
    try:
        import httpx

        response = httpx.get(url, timeout=timeout)
    except Exception as exc:
        return CheckResult(
            "http-reachability", FAIL,
            f"không kết nối được {url} ({type(exc).__name__}). "
            "Khởi động server: cd ../mcp-server && uv run python weather.py",
        )
    if response.status_code >= 500:
        return CheckResult("http-reachability", FAIL, f"server trả HTTP {response.status_code}")
    return CheckResult("http-reachability", PASS, f"HTTP {response.status_code} từ {url}")


async def run_mcp_checks(url: str, timeout: float = 30.0) -> list[CheckResult]:
    """Thực hiện initialize → list_tools → health_check bằng giao thức MCP thật."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    results: list[CheckResult] = []
    names = ["mcp-initialize", "tool-discovery", "health-check-call"]

    def rest(reason: str) -> list[CheckResult]:
        return results + [CheckResult(n, SKIP, reason) for n in names[len(results):]]

    try:
        async with asyncio.timeout(timeout):
            async with streamable_http_client(url) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    init = await session.initialize()
                    results.append(CheckResult(
                        "mcp-initialize", PASS,
                        f"server={init.serverInfo.name!r} protocol={init.protocolVersion}",
                    ))

                    listed = await session.list_tools()
                    found = {t.name for t in listed.tools}
                    missing = EXPECTED_TOOLS - found
                    if missing:
                        results.append(CheckResult(
                            "tool-discovery", FAIL,
                            f"thiếu tool: {sorted(missing)}; có: {sorted(found)}",
                        ))
                        return rest("tool-discovery thất bại")
                    results.append(CheckResult("tool-discovery", PASS, ", ".join(sorted(found))))

                    reply = await session.call_tool("health_check", {})
                    text = "".join(getattr(c, "text", "") for c in reply.content)
                    if reply.isError:
                        results.append(CheckResult("health-check-call", FAIL, f"tool báo lỗi: {text}"))
                    else:
                        results.append(CheckResult("health-check-call", PASS, text.strip()))
        return results
    except BaseException as exc:  # ExceptionGroup từ anyio cũng được xử lý
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        leaf = exc
        while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
            leaf = leaf.exceptions[0]
        step = names[len(results)] if len(results) < len(names) else names[-1]
        results.append(CheckResult(step, FAIL, f"{type(leaf).__name__}: {leaf}"))
        return rest("bước trước đó thất bại")


def check_agent_import() -> CheckResult:
    try:
        import warnings

        warnings.filterwarnings("ignore")
        sys.path.insert(0, str(HERE))
        from weather_agent import agent as agent_module

        if agent_module.AGENT_MODE != "mcp":
            return CheckResult("agent-import", FAIL, f"agent ở chế độ {agent_module.AGENT_MODE!r}, không có MCP tool")
        root = agent_module.root_agent
        return CheckResult("agent-import", PASS, f"agent={root.name} model={root.model}")
    except Exception as exc:
        return CheckResult("agent-import", FAIL, f"{type(exc).__name__}: {exc}")


def run_checks(offline: bool = False) -> list[CheckResult]:
    _load_env()
    url = server_url()
    results = [check_environment(), check_dependencies(), check_structure()]
    mcp_names = ["http-reachability", "mcp-initialize", "tool-discovery", "health-check-call"]
    if offline:
        results += [CheckResult(n, SKIP, "--offline") for n in mcp_names]
    else:
        http = check_http(url)
        results.append(http)
        if http.ok:
            try:
                results += asyncio.run(run_mcp_checks(url))
            except ImportError as exc:
                results += [CheckResult(n, FAIL, f"thiếu thư viện: {exc}") for n in mcp_names[1:]]
        else:
            results += [CheckResult(n, SKIP, "endpoint không truy cập được") for n in mcp_names[1:]]
    results.append(check_agent_import())
    return results


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="bỏ qua các bước cần MCP server")
    args = parser.parse_args(argv)

    print("=" * 60)
    print("Weather Agent Setup Verification")
    print("=" * 60)
    results = run_checks(offline=args.offline)
    for r in results:
        print(f"{ICON[r.status]} {r.name}: {r.message}")
    failed = [r for r in results if r.status == FAIL]
    print("=" * 60)
    if failed:
        print(f"❌ {len(failed)} bước thất bại: {', '.join(r.name for r in failed)}")
        return 1
    skipped = sum(r.status == SKIP for r in results)
    print(f"✅ Mọi bước đã chạy đều đạt ({skipped} bước bỏ qua)")
    if not skipped:
        print("🚀 Sẵn sàng: uv run adk web")
    return 0


if __name__ == "__main__":
    sys.exit(main())
