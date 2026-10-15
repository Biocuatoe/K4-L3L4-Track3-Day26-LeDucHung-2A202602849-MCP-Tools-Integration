"""Minh hoạ FUNCTION CALLING thuần với Google Gemini SDK.

Tool `get_weather` được định nghĩa schema thủ công VÀ thực thi ngay trong
chính file app này. Model chỉ QUYẾT ĐỊNH gọi tool nào; app mới là nơi chạy.

LƯU Ý: dữ liệu thời tiết trong file này là DỮ LIỆU GIẢ LẬP (mock) để dạy
học, KHÔNG phải quan sát thời tiết thực tế. Kết quả tool có trường
"nguồn": "mock".

Cách chạy:
    pip install -r ../requirements.txt
    export GEMINI_API_KEY=...        # hoặc GOOGLE_API_KEY (SDK chấp nhận cả hai)
    python weather_function_calling.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from google import genai
from google.genai import types

# gemini-2.5-flash đã bị Google gỡ với API key mới (404) — mặc định dùng gemini-3.8-flash.
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# Giới hạn số vòng model<->tool để tránh vòng lặp gọi tool vô hạn
MAX_TOOL_ROUNDS = 5

SYSTEM_INSTRUCTION = (
    "Bạn là trợ lý thời tiết thân thiện, trả lời bằng tiếng Việt tự nhiên. "
    "Dùng emoji phù hợp (🌧️ 🌤️ 💨 💧). "
    "Tóm tắt ngắn gọn, dễ hiểu, và đưa ra lời khuyên thực tế "
    "(ví dụ: mang ô, mặc áo mỏng, ...). "
    "Dữ liệu từ tool là dữ liệu mô phỏng; hãy nói rõ nếu người dùng hỏi nguồn."
)

# 1. App tự định nghĩa schema của tool
get_weather_declaration = types.FunctionDeclaration(
    name="get_weather",
    description="Lấy thời tiết hiện tại (dữ liệu mô phỏng) của một thành phố",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "city": types.Schema(
                type=types.Type.STRING, description="Tên thành phố"
            )
        },
        required=["city"],
    ),
)

TOOLS = [types.Tool(function_declarations=[get_weather_declaration])]

_MOCK_DATA = {
    "Hà Nội": {
        "nhiệt_độ": "29°C",
        "thời_tiết": "trời mưa nhẹ",
        "độ_ẩm": "82%",
        "gió": {"hướng": "Đông Nam", "tốc_độ": "12 km/h"},
    },
    "Hồ Chí Minh": {
        "nhiệt_độ": "33°C",
        "thời_tiết": "mưa rào",
        "độ_ẩm": "75%",
        "gió": {"hướng": "Tây Nam", "tốc_độ": "15 km/h"},
    },
    "Đà Nẵng": {
        "nhiệt_độ": "30°C",
        "thời_tiết": "nhiều mây",
        "độ_ẩm": "78%",
        "gió": {"hướng": "Đông", "tốc_độ": "10 km/h"},
    },
}


# 2. App tự thực thi tool (trong thực tế sẽ gọi API thời tiết thật)
def get_weather(city: str) -> str:
    """Trả về thời tiết MÔ PHỎNG của *city* (JSON). Dùng làm tool cho model."""
    if not isinstance(city, str) or not city.strip():
        raise ValueError("'city' phải là chuỗi không rỗng")
    city = city.strip()
    default = {"nhiệt_độ": "28°C", "thời_tiết": "không có dữ liệu chi tiết"}
    return json.dumps(
        {"city": city, "nguồn": "mock", **_MOCK_DATA.get(city, default)},
        ensure_ascii=False,
    )


# Bảng dispatch: chỉ tool nằm trong đây mới được phép thực thi
TOOL_REGISTRY = {"get_weather": get_weather}


def execute_tool_call(name: str | None, args: dict[str, Any] | None) -> dict[str, Any]:
    """Thực thi AN TOÀN một yêu cầu gọi tool của model.

    Luôn trả về dict (không raise): ``{"result": ...}`` khi thành công hoặc
    ``{"error": ...}`` khi tool lạ, tham số sai hay tool lỗi. Model nhận được
    lỗi này và có thể giải thích/thử lại thay vì làm sập app.
    """
    func = TOOL_REGISTRY.get(name or "")
    if func is None:
        return {"error": f"Tool không tồn tại: {name!r}"}
    args = dict(args or {})
    if set(args) != {"city"}:
        return {"error": f"Tham số không hợp lệ cho {name}: cần đúng 'city', nhận {sorted(args)}"}
    try:
        return {"result": func(**args)}
    except Exception as exc:  # lỗi trong tool được báo lại cho model
        return {"error": f"{type(exc).__name__}: {exc}"}


def _config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(tools=TOOLS, system_instruction=SYSTEM_INSTRUCTION)


def run(prompt: str, client: Any | None = None, max_rounds: int = MAX_TOOL_ROUNDS) -> str:
    """Gửi *prompt* tới Gemini, tự xử lý function calling và trả về câu trả lời cuối.

    *client* có thể được truyền vào (ví dụ fake trong test); mặc định tạo
    ``genai.Client()`` — đọc GEMINI_API_KEY hoặc GOOGLE_API_KEY từ môi trường.
    """
    client = client or genai.Client()
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    ]

    # 3. Gọi model — model quyết định có gọi tool hay không
    resp = client.models.generate_content(model=MODEL, contents=contents, config=_config())

    # 4. Vòng lặp: nếu model yêu cầu tool, app TỰ THỰC THI rồi đưa kết quả trả lại
    rounds = 0
    while resp.function_calls:
        rounds += 1
        if rounds > max_rounds:
            raise RuntimeError(
                f"Model vẫn yêu cầu tool sau {max_rounds} vòng — dừng để tránh vòng lặp vô hạn"
            )
        # Thêm phản hồi của model vào lịch sử hội thoại
        contents.append(resp.candidates[0].content)

        function_responses = []
        for fc in resp.function_calls:
            print(f"  [model yêu cầu] {fc.name}({fc.args})")
            outcome = execute_tool_call(fc.name, fc.args)  # <-- app chạy, không phải model
            print(f"  [app thực thi]  -> {outcome}")
            function_responses.append(
                types.Part.from_function_response(name=fc.name, response=outcome)
            )

        # Gửi kết quả tool trả về cho model
        contents.append(types.Content(role="user", parts=function_responses))
        resp = client.models.generate_content(model=MODEL, contents=contents, config=_config())

    # 5. Model tổng hợp câu trả lời cuối
    if not resp.text:
        raise RuntimeError("Model không trả về nội dung văn bản")
    return resp.text


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    question = "Thời tiết Hà Nội và Đà Nẵng hôm nay thế nào?"
    print(f"User: {question}\n")
    try:
        print("Trả lời:", run(question))
    except Exception as exc:
        print(f"Lỗi: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
