"""MCP CLIENT minh hoạ — kết nối tới weather_server.py qua giao thức MCP.

Điểm mấu chốt: client KHÔNG hard-code tool. Nó hỏi server "anh có tool gì?"
(list_tools) tại runtime, rồi gọi tool (call_tool) để SERVER thực thi và trả
kết quả về qua MCP.

Ví dụ này không cần ANTHROPIC_API_KEY — nó cho thấy lớp giao thức MCP hoạt
động độc lập với model. (Trong thực tế, một LLM sẽ dùng Function Calling để
quyết định khi nào gọi tool đã khám phá được.)

Cách chạy (cùng thư mục với weather_server.py, client tự khởi động server):
    pip install -r ../requirements.txt
    python weather_client.py
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_SCRIPT = Path(__file__).resolve().parent / "weather_server.py"


def server_params() -> StdioServerParameters:
    # Dùng đúng interpreter đang chạy client và đường dẫn tuyệt đối tới server
    # => chạy được từ bất kỳ thư mục làm việc nào.
    return StdioServerParameters(command=sys.executable, args=[str(SERVER_SCRIPT)])


async def main() -> None:
    params = server_params()

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. KHÁM PHÁ tool mà server công bố (không hard-code)
            tools = await session.list_tools()
            print("Tools server cung cấp:")
            for t in tools.tools:
                print(f"  - {t.name}: {t.description}")

            # 2. Gọi tool — SERVER thực thi rồi trả kết quả về qua MCP
            for city in ["Hanoi", "Danang", "Haiphong"]:
                result = await session.call_tool("get_weather", {"city": city})
                print(f"\ncall_tool get_weather(city={city!r}):")
                if result.is_error:
                    print("  [LỖI từ tool]", result.content[0].text)
                else:
                    print("  ->", result.content[0].text)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):  # console Windows mặc định không phải UTF-8
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
