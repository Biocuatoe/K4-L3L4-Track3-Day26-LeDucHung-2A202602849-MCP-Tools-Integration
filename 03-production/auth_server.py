"""MCP Server có Authentication — minh hoạ bảo mật (DEMO, chưa đủ cho production).

Server chạy qua HTTP (Streamable HTTP) thay vì stdio, kèm bearer token
verification. Chỉ request mang token hợp lệ mới được phép khám phá và gọi tool.

Luồng hoạt động:
  Client gửi request HTTP kèm header "Authorization: Bearer <token>"
    → MCP SDK tự chạy BearerAuthBackend để xác minh token
    → Token hợp lệ → cho phép truy cập tool
    → Token sai / thiếu → trả về 401/403

Cách chạy:
    pip install -r ../requirements.txt     # từ thư mục gốc repo
    python auth_server.py
    # Server lắng nghe tại http://localhost:8000/mcp
"""

from __future__ import annotations

import os
import sys

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

REQUIRED_SCOPE = "weather:read"

# ⚠️ DEMO ONLY: token tĩnh lấy từ biến môi trường, KHÔNG phải xác thực production.
# Không có token mặc định nào được hard-code trong repo — bạn phải tự đặt:
#   PowerShell:  $env:MCP_AUTH_TOKEN = "chuoi-bi-mat-cua-ban"
#   bash:        export MCP_AUTH_TOKEN=chuoi-bi-mat-cua-ban
# (Tuỳ chọn) MCP_LIMITED_TOKEN: token hợp lệ nhưng KHÔNG có scope weather:read,
# dùng để minh hoạ việc server từ chối bằng 403.


def load_tokens(environ: dict[str, str] | None = None) -> dict[str, tuple[str, list[str]]]:
    """Đọc token từ môi trường -> {token: (client_id, scopes)}."""
    env = os.environ if environ is None else environ
    tokens: dict[str, tuple[str, list[str]]] = {}
    main = env.get("MCP_AUTH_TOKEN")
    if main:
        tokens[main] = ("dev-user", [REQUIRED_SCOPE])
    limited = env.get("MCP_LIMITED_TOKEN")
    if limited:
        tokens[limited] = ("limited-user", [])
    return tokens


class StaticTokenVerifier(TokenVerifier):
    """Kiểm tra bearer token dựa trên danh sách tĩnh (CHỈ để học).

    Production nên thay bằng: JWT decode, OAuth introspection, hoặc
    gọi tới identity provider (Keycloak, Auth0, Google IAM, ...).
    """

    def __init__(self, tokens: dict[str, tuple[str, list[str]]]) -> None:
        self._tokens = tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        entry = self._tokens.get(token)
        if entry is None:
            return None
        client_id, scopes = entry
        return AccessToken(token=token, client_id=client_id, scopes=list(scopes))


_MOCK_DB = {
    "Hanoi": "29°C, trời mưa",
    "Haiphong": "33°C, mưa rào",
    "Danang": "30°C, nhiều mây",
}


def create_server(
    tokens: dict[str, tuple[str, list[str]]], base_url: str = "http://localhost:8000"
) -> MCPServer:
    """Tạo MCP server có xác thực. Logic tool không biết gì về auth.

    ``required_scopes`` được SDK ÁP DỤNG ở mức endpoint HTTP: token thiếu scope
    ``weather:read`` bị từ chối 403 cho MỌI request. Lưu ý: đây là phân quyền
    theo endpoint, KHÔNG phải phân quyền riêng từng tool.
    """
    server = MCPServer(
        "weather-secure",
        auth=AuthSettings(
            issuer_url=base_url,
            resource_server_url=base_url,
            required_scopes=[REQUIRED_SCOPE],
            validate_token_resource=False,  # token tĩnh, không có audience để kiểm tra
        ),
        token_verifier=StaticTokenVerifier(tokens),
    )

    @server.tool()
    def get_weather(city: str) -> str:
        """Lấy thời tiết hiện tại của một thành phố (dữ liệu mô phỏng)."""
        return f"{city}: {_MOCK_DB.get(city, '28°C, không có dữ liệu chi tiết')}"

    return server


if __name__ == "__main__":
    tokens = load_tokens()
    if not any(REQUIRED_SCOPE in scopes for _, scopes in tokens.values()):
        print("Thiếu biến môi trường MCP_AUTH_TOKEN — xem hướng dẫn đầu file.", file=sys.stderr)
        sys.exit(2)
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    create_server(tokens, f"http://localhost:{port}").run(
        transport="streamable-http", host=host, port=port
    )
