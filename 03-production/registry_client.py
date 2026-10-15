"""Tool Registry Client — agent khám phá tool từ danh mục trung tâm.

Thay vì hard-code "server nào có tool nào", agent hỏi Tool Registry:
  "Tôi cần tool có tag 'weather'" → Registry trả về tool weather mới nhất, không deprecated
  "Tôi cần tool có tag 'forecast'" → Registry trả về get_weather_v2, server weather-v2

Agent tự quyết định dùng tool nào, kết nối tới đúng server, và gọi tool —
tất cả tại runtime mà không cần hard-code.

Production thường dùng:
  - Tool registry tập trung (DB/API) với search full-text hoặc semantic
  - Kubernetes + CRD (Custom Resource Definition) cho MCP servers
  - API Gateway (Kong, Envoy) làm single entry point

Ví dụ này minh hoạ ý tưởng với một file JSON đơn giản. Các server
email-service / db-gateway trong registry.json là cấu hình GIẢ ĐỊNH (không có
dịch vụ thật phía sau) — chỉ để minh hoạ tìm kiếm.

Cách chạy:
    pip install -r ../requirements.txt     # từ thư mục gốc repo
    cd 03-production
    python registry_client.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from packaging.version import InvalidVersion, Version

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

REGISTRY_PATH = Path(__file__).parent / "registry.json"
# Đường dẫn tương đối trong registry.json được tính từ thư mục chứa file registry,
# nên script chạy đúng dù bạn đứng ở thư mục nào.
REGISTRY_DIR = REGISTRY_PATH.parent


class RegistryError(Exception):
    """Lỗi cấu hình registry hoặc lỗi khi gọi tool (thông điệp đã được làm sạch)."""


def _leaf_error(exc: BaseException) -> BaseException:
    """Lấy lỗi gốc từ ExceptionGroup của anyio để thông điệp dễ đọc."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


class ToolRegistry:
    """Danh mục trung tâm — agent tra cứu tool theo tag, tên, hoặc mô tả."""

    def __init__(self, path: Path = REGISTRY_PATH) -> None:
        self.path = Path(path)
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError as exc:
            raise RegistryError(f"Không đọc được registry {self.path}: {exc.strerror}") from exc
        except json.JSONDecodeError as exc:
            raise RegistryError(f"Registry không phải JSON hợp lệ ({self.path}): {exc}") from exc
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("tools"), dict)
            or not isinstance(data.get("servers"), dict)
        ):
            raise RegistryError("Registry phải là object có hai khoá 'tools' và 'servers'")
        for name, cfg in data["tools"].items():
            missing = [k for k in ("description", "version", "server") if k not in cfg]
            if missing:
                raise RegistryError(f"Tool {name!r} thiếu trường: {', '.join(missing)}")
            try:
                Version(cfg["version"])
            except InvalidVersion as exc:
                raise RegistryError(
                    f"Tool {name!r} có version không hợp lệ: {cfg['version']!r}"
                ) from exc
        self.tools: dict[str, dict] = data["tools"]
        self.servers: dict[str, dict] = data["servers"]
        # Thư mục để phân giải đường dẫn tương đối của script server
        self.base_dir = self.path.resolve().parent

    def _entry(self, tool_name: str, tool_cfg: dict) -> dict:
        return {
            "tool": tool_name,
            "description": tool_cfg["description"],
            "version": tool_cfg["version"],
            "deprecated": tool_cfg.get("deprecated", False),
            "parameters": tool_cfg.get("parameters", {}),
            "server_name": tool_cfg["server"],
            "server": self.servers.get(tool_cfg["server"], {}),
            "base_dir": self.base_dir,
        }

    def get(self, name: str) -> dict:
        """Tra cứu chính xác theo tên tool."""
        if name not in self.tools:
            raise KeyError(f"Không có tool tên {name!r} trong registry")
        return self._entry(name, self.tools[name])

    def search(self, *, tag: str | None = None, keyword: str | None = None) -> list[dict]:
        """Tìm tool theo tag hoặc keyword trong description (khớp một trong hai).

        Trả về danh sách kết quả, mỗi phần tử gồm thông tin tool + server.
        """
        results = []
        for tool_name, tool_cfg in self.tools.items():
            match = False
            if tag and tag in tool_cfg.get("tags", []):
                match = True
            if keyword and keyword.lower() in tool_cfg.get("description", "").lower():
                match = True
            if match:
                results.append(self._entry(tool_name, tool_cfg))
        return results

    def best_match(self, *, tag: str | None = None, keyword: str | None = None) -> dict:
        """Trả về tool phù hợp nhất (ưu tiên version cao, không deprecated).

        Nếu mọi kết quả đều deprecated thì vẫn trả về bản mới nhất trong số đó.
        Khi hai tool trùng version, chọn theo tên (a→z) để kết quả ổn định.
        """
        results = self.search(tag=tag, keyword=keyword)
        if not results:
            raise KeyError(f"Không tìm thấy tool (tag={tag}, keyword={keyword})")
        active = [r for r in results if not r["deprecated"]]
        candidates = active or results
        # So sánh theo semantic version, không so chuỗi ("10.0.0" > "2.0.0")
        best_version = max(Version(r["version"]) for r in candidates)
        tied = [r for r in candidates if Version(r["version"]) == best_version]
        return min(tied, key=lambda r: r["tool"])


def _extract_text(result) -> str:
    """Lấy text từ kết quả call_tool; ném RegistryError nếu tool báo lỗi."""
    texts = [c.text for c in result.content if getattr(c, "text", None) is not None]
    text = "\n".join(texts)
    if result.is_error:
        raise RegistryError(f"Tool trả về lỗi: {text or '(không có nội dung)'}")
    if not texts:
        raise RegistryError("Tool không trả về nội dung dạng text")
    return text


def _check_required_args(match: dict, tool_args: dict) -> None:
    missing = [
        name
        for name, spec in match.get("parameters", {}).items()
        if spec.get("required") and name not in tool_args
    ]
    if missing:
        raise RegistryError(f"Thiếu tham số bắt buộc cho {match['tool']}: {', '.join(missing)}")


@asynccontextmanager
async def _open_streams(server: dict, base_dir: Path):
    """Mở cặp stream (read, write) theo transport khai báo trong registry."""
    transport = server.get("transport")
    if transport == "stdio":
        # "python" trong registry → dùng đúng interpreter hiện tại (tránh lỗi venv)
        command = server.get("command", "python")
        if command in ("python", "python3"):
            command = sys.executable
        args = [
            str((base_dir / a).resolve()) if a.endswith(".py") else a
            for a in server.get("args", [])
        ]
        async with stdio_client(StdioServerParameters(command=command, args=args)) as streams:
            yield streams
    elif transport == "streamable-http":
        headers = {}
        auth_cfg = server.get("auth")
        if auth_cfg and auth_cfg.get("type") == "bearer":
            env_name = auth_cfg.get("token_env", "")
            token = os.environ.get(env_name)
            if not token:
                raise RegistryError(f"Thiếu biến môi trường {env_name} chứa bearer token")
            headers["Authorization"] = f"Bearer {token}"
        async with create_mcp_http_client(headers=headers) as http_client:
            async with streamable_http_client(server["url"], http_client=http_client) as streams:
                yield streams
    else:
        raise RegistryError(f"Transport không được hỗ trợ: {transport!r}")


async def connect_and_call(match: dict, tool_args: dict) -> str:
    """Kết nối tới server phù hợp và gọi tool đã tìm được.

    Mọi lỗi được chuyển thành RegistryError với thông điệp đã làm sạch (chỉ nêu
    thao tác thất bại + loại lỗi, không kèm header/token).
    """
    server = match.get("server") or {}
    tool_name = match["tool"]
    if not server:
        raise RegistryError(
            f"Server {match.get('server_name')!r} của tool {tool_name!r} chưa được định nghĩa"
        )
    _check_required_args(match, tool_args)
    transport = server.get("transport")
    try:
        async with _open_streams(server, Path(match.get("base_dir", REGISTRY_DIR))) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, tool_args)
                return _extract_text(result)
    except Exception as exc:  # noqa: BLE001 - chuyển thành lỗi đã làm sạch
        leaf = _leaf_error(exc)
        if isinstance(leaf, RegistryError):
            raise leaf from None
        raise RegistryError(
            f"Gọi {tool_name} qua {transport} thất bại: {type(leaf).__name__}"
        ) from None


async def main() -> None:
    registry = ToolRegistry()

    # ── 1. Agent liệt kê toàn bộ tool trong registry ─────────────────
    print("=== Tool Registry ===\n")
    for name, cfg in registry.tools.items():
        status = " (deprecated)" if cfg.get("deprecated") else ""
        print(f"  {name} v{cfg['version']}{status}")
        print(f"    {cfg['description']}")
        print(f"    tags: {cfg.get('tags', [])}  →  server: {cfg['server']}")
    print()

    # ── 2. Agent tìm tool theo tag (giống agent nhận task "lấy thời tiết") ─
    print('--- Agent cần tool có tag "weather" ---')
    results = registry.search(tag="weather")
    print(f"Tìm thấy {len(results)} tool(s):")
    for r in results:
        print(f"  • {r['tool']} v{r['version']} (server: {r['server_name']})")

    # ── 3. Agent chọn tool phù hợp nhất và gọi ──────────────────────
    best = registry.best_match(tag="weather")
    print(f"\nBest match: {best['tool']} v{best['version']}")
    print(f"Kết nối tới server [{best['server_name']}]...")

    output = await connect_and_call(best, {"city": "Hanoi"})
    print(f"Kết quả: {output}\n")

    # ── 4. Agent tìm tool theo keyword ───────────────────────────────
    print('--- Agent tìm tool có keyword "forecast" ---')
    results = registry.search(keyword="forecast")
    for r in results:
        print(f"  • {r['tool']}: {r['description']}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        asyncio.run(main())
    except RegistryError as exc:
        print(f"Lỗi registry: {exc}", file=sys.stderr)
        sys.exit(1)
