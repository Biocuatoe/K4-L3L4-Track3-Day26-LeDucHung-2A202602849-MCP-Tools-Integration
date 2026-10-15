# Phân biệt MCP và Function Calling

Đây là hai khái niệm hay bị nhầm lẫn nhưng thực ra ở **hai tầng khác nhau**, và **bổ sung cho nhau** chứ không thay thế.

## Cấu trúc repo

```
day26-mcp/
├── README.md                ← Bạn đang đọc file này
├── requirements.txt         ← pip install -r requirements.txt (runtime)
├── requirements-dev.txt     ← + pytest, ruff
├── tests/                   ← test offline cho Module 01–03
├── docs/VALIDATION.md       ← báo cáo kiểm thử đã thực thi
│
├── 01-function-calling/     ← Bước 1: Function Calling thuần (Gemini SDK)
│   ├── README.md
│   └── weather_function_calling.py
│
├── 02-mcp-basics/           ← Bước 2: MCP server + client (không cần API key)
│   ├── README.md
│   ├── weather_server.py
│   └── weather_client.py
│
└── 03-production/           ← Bước 3: Auth, Tool Registry, Versioning
    ├── README.md
    ├── auth_server.py
    ├── auth_client.py
    ├── registry.json
    ├── registry_client.py
    ├── versioned_server.py
    └── versioned_client.py
│
└── 04-lab/                  ← Bước 4: Agent Google ADK + MCP server thật (WeatherAPI)
    ├── README.md
    ├── mcp-server/          ← FastMCP server (Streamable HTTP, Dockerfile cho Cloud Run)
    └── mcp-client/          ← ADK agent dùng McpToolset
```

> Bước 01–03 dùng **MCP Python SDK v2** (`mcp>=2.0`, xem `requirements.txt`).
> Lab 04 có môi trường riêng (`uv sync` trong từng thư mục).

## Quick start

**Yêu cầu:** Python 3.10+ (đã kiểm thử trên 3.11) cho Module 01–03; Lab 04 dùng [uv](https://docs.astral.sh/uv/) và môi trường riêng
(server: Python ≥3.10, client ADK: Python ≥3.12 — uv tự tải đúng phiên bản).

```powershell
# Windows PowerShell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Module 02 — MCP (không cần API key)
python 02-mcp-basics/weather_client.py

# Module 01 — Function Calling (cần Gemini API key; SDK chấp nhận GEMINI_API_KEY hoặc GOOGLE_API_KEY)
$env:GEMINI_API_KEY = "<key-của-bạn>"
python 01-function-calling/weather_function_calling.py

# Module 03 — Auth (2 terminal; token do BẠN đặt, không có token mặc định)
$env:MCP_AUTH_TOKEN = "<chuỗi-bí-mật-bất-kỳ>"
python 03-production/auth_server.py            # terminal 1
python 03-production/auth_client.py            # terminal 2 (cùng MCP_AUTH_TOKEN)

# Module 03 — Registry và Versioning
python 03-production/registry_client.py
python 03-production/versioned_client.py
```

```bash
# bash / macOS / Linux
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export GEMINI_API_KEY=...            # Module 01
export MCP_AUTH_TOKEN=...            # Module 03 auth (server và client)
```

> Console Windows dùng cp1252 mặc định: các script đã tự `reconfigure(encoding="utf-8")` để in được tiếng Việt.

### Lab 04 (thứ tự khởi động)

1. Tạo `04-lab/mcp-server/.env` (`WEATHERAPI_KEY=...`, tuỳ chọn `PORT=8085`) và `04-lab/mcp-client/.env` (`GOOGLE_API_KEY=...`, tuỳ chọn `MCP_SERVER_URL`). Cả hai file đã được `.gitignore`.
2. Terminal 1: `cd 04-lab/mcp-server; uv sync --frozen; uv run --frozen --env-file .env python weather.py`
3. Terminal 2: `cd 04-lab/mcp-client; uv sync --frozen; uv run python verify_setup.py` (kiểm tra MCP thật), rồi `uv run adk web`.

Chi tiết: [04-lab/README.md](04-lab/README.md).

### Chạy test

```powershell
python -m pytest                                   # test offline ở thư mục gốc (Module 01–03)
cd 04-lab/mcp-server; uv run --frozen pytest       # Lab 04 server (WeatherAPI được mock)
cd 04-lab/mcp-client; uv run --frozen pytest       # Lab 04 verifier + agent
ruff check .                                       # lint
```

Test mặc định KHÔNG cần API key, mạng, hay dịch vụ đang chạy. Kiểm thử live (WeatherAPI/Gemini) là thao tác thủ công — xem [docs/VALIDATION.md](docs/VALIDATION.md).

### Ghi chú an toàn / phạm vi

- Dữ liệu thời tiết ở Module 01–03 là **MOCK** (dạy học), không phải quan sát thực tế. Chỉ Lab 04 dùng dữ liệu thật (WeatherAPI).
- Xác thực ở `auth_server.py` là **DEMO**: token tĩnh lấy từ biến môi trường. Production cần JWT/OAuth (xem 03-production/README.md).
- Không commit `.env`; không in API key vào log.

---

## Định nghĩa ngắn gọn

**Function Calling** là một *khả năng của model* (capability). Model được huấn luyện để khi bạn đưa cho nó danh sách các "công cụ" (kèm schema mô tả tham số), nó có thể tự quyết định gọi công cụ nào và sinh ra JSON tham số phù hợp. Bản thân model **không chạy** function — nó chỉ nói "hãy gọi `get_weather(city='Hanoi')`". App mới là nơi chạy tool.

**MCP (Model Context Protocol)** là một *giao thức chuẩn* (protocol) — giống như USB-C hay HTTP cho thế giới AI. Nó định nghĩa cách một **MCP Client** (như Claude Code, Claude Desktop) kết nối tới các **MCP Server** để khám phá và sử dụng tools, resources, prompts một cách thống nhất.

---

## So sánh trực tiếp

| Tiêu chí | Function Calling | Model Context Protocol (MCP) |
|---|---|---|
| **Bản chất** | Tính năng của mô hình (Model capability) | Giao thức giao tiếp client–server |
| **Ai định nghĩa tool?** | Bạn hard-code trong từng app | Server tự công bố (self-describe) tool |
| **Tái sử dụng** | Phải viết lại cho mỗi app/model | Viết 1 lần, mọi MCP client dùng được |
| **Thực thi** | App của bạn tự chạy | MCP Server chạy, client điều phối |
| **Tính chuẩn hóa** | Mỗi nhà cung cấp 1 kiểu (OpenAI, Anthropic khác nhau) | Một chuẩn chung do Anthropic đề xuất |
| **Hệ sinh thái** | Khó chia sẻ dạng module đóng gói sẵn | Dễ dàng chia sẻ và tải về các "MCP Servers" mã nguồn mở |

## Quan hệ giữa chúng

Điểm quan trọng nhất: **MCP dùng Function Calling bên dưới**. Chúng không loại trừ nhau.

```
User hỏi
   │
   ▼
LLM (dùng Function Calling để quyết định gọi tool nào)
   │
   ▼
MCP Client  ──[giao thức MCP]──►  MCP Server (thực thi tool thật)
   │                                   │
   ◄───────────── kết quả ─────────────┘
   ▼
LLM tổng hợp câu trả lời
```

## Khi nào dùng cái nào?

- **Function Calling thuần**: app đơn giản, tool gắn chặt với 1 ứng dụng, không cần chia sẻ.
- **MCP**: muốn tool/tích hợp dùng lại được trên nhiều AI client, muốn tách biệt logic tool khỏi app, hoặc xây hệ sinh thái tích hợp (DB, file, API nội bộ...).

---

## Minh hoạ bằng mã nguồn

Cùng một tool `get_weather`, dưới đây là hai cách triển khai để thấy rõ sự khác biệt.

### [Cách 1 — Function Calling thuần (Google Gemini SDK)](01-function-calling/)

Tool được **định nghĩa và thực thi ngay trong app**. Model chỉ quyết định gọi tool nào, app tự chạy và đưa kết quả trở lại.

```
User hỏi → Model quyết định gọi get_weather("Hà Nội")
                    │
                    ▼
             App TỰ THỰC THI hàm get_weather
                    │
                    ▼
             Model tổng hợp câu trả lời
```

> Nhược điểm: schema viết tay, tool gắn chặt trong app — muốn dùng lại ở app khác phải copy cả schema lẫn hàm.

Chi tiết + code: xem [`01-function-calling/README.md`](01-function-calling/README.md)

### [Cách 2 — MCP (server tự công bố tool, mọi client dùng chung)](02-mcp-basics/)

Tool được tách ra **một MCP server độc lập**. Server tự "khai báo" nó có tool gì; bất kỳ MCP client nào (Claude Code, Claude Desktop, Cursor...) cũng cắm vào dùng được mà không cần biết code bên trong.

```
weather_client.py                       weather_server.py
┌─────────────┐    giao thức MCP    ┌─────────────────┐
│  list_tools │ ──────────────────▶ │ @mcp.tool()     │
│  call_tool  │ ◀────────────────── │ get_weather()   │
└─────────────┘     stdio           └─────────────────┘
```

Chi tiết + code: xem [`02-mcp-basics/README.md`](02-mcp-basics/README.md)

### Điểm khác biệt rút ra từ code

| | Function Calling thuần | MCP |
|---|---|---|
| Khai báo schema | Tự viết tay trong app | `@mcp.tool()` tự sinh từ type hints |
| Nơi thực thi tool | Trong app gọi model | Trong MCP server riêng |
| Khám phá tool | Hard-code danh sách `tools` | `session.list_tools()` tại runtime |
| Dùng lại ở app khác | Copy code | Cắm thêm client, không sửa server |
| Vai trò Function Calling | Là toàn bộ cơ chế | Là lớp model bên trong MCP |

---

## [MCP trong Production](03-production/)

Các ví dụ trên chạy tốt trên máy cá nhân, nhưng đưa vào **hệ thống production** cần giải quyết thêm ba vấn đề:

```
┌─────────────────────────────────────────────────────┐
│                  Production MCP                     │
│                                                     │
│  ┌──────────┐   ┌───────────┐   ┌───────────────┐   │
│  │ Security │   │ Registry  │   │  Versioning   │   │
│  │          │   │           │   │               │   │
│  │ • Auth   │   │ • Discover│   │ • v1 compat   │   │
│  │ • Token  │   │ • Connect │   │ • v2 features │   │
│  │ • Scopes │   │ • Health  │   │ • Deprecation │   │
│  └──────────┘   └───────────┘   └───────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 1. Security — Authentication & Authorization

MCP server phục vụ qua **HTTP** cho nhiều client → cần xác thực. MCP SDK hỗ trợ sẵn **Bearer Token** verification:

- Server: cấu hình `AuthSettings` + implement `TokenVerifier` protocol
- Client: gửi header `Authorization: Bearer <token>` qua `create_mcp_http_client(headers=...)` của MCP SDK
- Không có token → 401, token sai → 403, logic tool không biết gì về auth

| Tầng | Demo (stdio) | Production (HTTP) |
|---|---|---|
| Transport | stdio (cùng máy) | Streamable HTTP (qua mạng) |
| Auth | Không cần | Bearer token / OAuth / mTLS |
| Phạm vi truy cập | Toàn bộ | Scopes giới hạn từng client |

### 2. Tool Registry & Discovery

Agent **không hard-code** tool nào. Nó hỏi **Tool Registry** — danh mục trung tâm liệt kê tất cả tool từ mọi server — theo yêu cầu task:

```
Agent nhận task "lấy thời tiết Hà Nội"
   │
   ▼
Tool Registry: "tool nào có tag 'weather'?"
   │
   ├── get_weather v1.0 → server: weather (stdio)
   └── get_weather_v2 v2.0 → server: weather-v2 (stdio)
   │
   ▼
Agent chọn best match (v2.0, không deprecated)
   │
   ▼
Kết nối tới server weather-v2, gọi get_weather_v2(city="Hanoi")
```

Registry là **tool-centric** — đơn vị khám phá là **tool** (tag, description, parameters), không phải server.

| | Hard-code (demo) | Tool Registry (production) |
|---|---|---|
| Agent biết tool nào? | Chỉ tool được code sẵn | Tất cả tool trong registry |
| Tìm tool | Theo tên cố định | Theo tag, keyword, capability |
| Thêm tool mới | Sửa code agent | Thêm entry vào registry |
| Chọn tool | Developer quyết định | Agent tự chọn best match |

### 3. Versioning & Backward Compatibility

Server v1 có `get_weather(city)` trả chuỗi đơn giản. V2 muốn trả JSON chi tiết, thêm `include_forecast`. Nếu đổi trực tiếp → mọi client cũ break. Giải pháp — 3 kỹ thuật kết hợp:

| Kỹ thuật | Mô tả |
|---|---|
| **Tool mới song song** | `get_weather_v2` tồn tại bên cạnh `get_weather` — không xoá tool cũ |
| **Tham số optional** | `include_forecast`, `units` có default → client cũ gọi vẫn đúng |
| **Server metadata** | Resource `server://info` công bố version + deprecation notice |

Chi tiết + code cho cả 3 phần: xem [`03-production/README.md`](03-production/README.md)

### Tổng kết Production Checklist

| Khía cạnh | Dev/Demo | Production |
|---|---|---|
| **Transport** | stdio (cùng máy) | HTTP/SSE (qua mạng) |
| **Auth** | Không | Bearer token, OAuth, mTLS |
| **Discovery** | Hard-code tool/server | Tool Registry — agent tìm tool theo task |
| **Versioning** | 1 tool duy nhất | Tool v1 + v2 song song, deprecation notice |
| **Health** | Không | Health check, retry, circuit breaker |
| **Logging** | `print()` | Structured logging, tracing (OpenTelemetry) |

---

**Tóm lại:** Function Calling là *cơ chế model gọi công cụ*; MCP là *chuẩn để kết nối model với các công cụ đó* — và MCP thực chất dùng Function Calling làm nền tảng để hoạt động.
