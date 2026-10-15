"""Fixtures dùng chung. Thư mục module có dấu '-' nên thêm vào sys.path thủ công."""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
for sub in ("01-function-calling", "02-mcp-basics", "03-production"):
    sys.path.insert(0, str(ROOT / sub))

# Token CHỈ dùng cho test — không phải credential thật
TEST_TOKEN = "test-only-token"
TEST_LIMITED_TOKEN = "test-only-limited-token"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def auth_server_url():
    """Chạy auth_server thật (uvicorn, thread nền) trên cổng trống; trả về URL /mcp."""
    import auth_server

    port = _free_port()
    tokens = {
        TEST_TOKEN: ("test-user", [auth_server.REQUIRED_SCOPE]),
        TEST_LIMITED_TOKEN: ("limited-user", []),
    }
    app = auth_server.create_server(tokens, f"http://127.0.0.1:{port}").streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("auth server không khởi động được")
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)
