# 03 — Production (Auth, Tool Registry, Versioning)

`02-mcp-basics` chạy tốt trên máy cá nhân. Đưa vào production cần giải quyết thêm 3 vấn đề:

| Vấn đề | Demo | Production |
|---|---|---|
| **Auth** | stdio, cùng máy, ai cũng gọi | HTTP + Bearer token / OAuth |
| **Discovery** | Hard-code tool/server | Tool Registry — agent tìm tool theo task |
| **Versioning** | 1 tool duy nhất | v1 + v2 song song, deprecation notice |

## Files

| File | Vấn đề | Mô tả |
|---|---|---|
| `auth_server.py` | Auth | MCP server qua HTTP + `TokenVerifier` kiểm tra bearer token |
| `auth_client.py` | Auth | Client gửi token qua `create_mcp_http_client(headers=...)` |
| `registry.json` | Discovery | Tool Registry — danh mục tool-centric, agent tìm theo tag/keyword |
| `registry_client.py` | Discovery | Agent tra cứu registry, chọn best match, tự kết nối |
| `versioned_server.py` | Versioning | Server v2: giữ tool v1 (deprecated) + thêm v2 + resource metadata |
| `versioned_client.py` | Versioning | Client test gọi tool v1, v2 và đọc `server://info` metadata |

---

## 3a. Authentication

Server chạy qua **Streamable HTTP** thay vì stdio, kèm bearer token verification.

```powershell
# Token do BẠN tự đặt (không có token mặc định trong repo)
$env:MCP_AUTH_TOKEN = "<chuỗi-bí-mật-bất-kỳ>"      # bash: export MCP_AUTH_TOKEN=...

# Terminal 1 — khởi động server (mặc định 127.0.0.1:8000; đổi bằng MCP_HOST / MCP_PORT)
python auth_server.py

# Terminal 2 — client kết nối kèm token (cùng MCP_AUTH_TOKEN)
python auth_client.py
```

> Cổng 8000 trùng cổng mặc định của `adk web` (Lab 04) — đặt `MCP_PORT` khác nếu chạy cùng lúc.

Luồng:

```
Client                                Server
  │                                      │
  │── POST /mcp ──────────────────────▶  │
  │   Authorization: Bearer <token>      │
  │                                      │── TokenVerifier.verify_token()
  │                                      │   token hợp lệ → AccessToken
  │◀── 200 OK (tools, results) ────────  │
  │                                      │
  │── POST /mcp (token sai) ──────────▶  │
  │◀── 401 Unauthorized ───────────────  │
```

Hành vi đã kiểm chứng bằng test (`tests/test_auth.py`, server uvicorn thật):

| Tình huống | Kết quả |
|---|---|
| Token hợp lệ có scope `weather:read` | `200`, khám phá và gọi tool bình thường |
| Thiếu header `Authorization` | `401` |
| Token sai, sai scheme (`Basic`/`Token`), không có `Bearer` | `401` |
| Token hợp lệ nhưng **thiếu scope** `weather:read` (`MCP_LIMITED_TOKEN`) | `403` |

- Logic tool không biết gì về auth — SDK xử lý ở tầng transport.
- **Phân quyền chỉ ở mức endpoint**: `AuthSettings(required_scopes=["weather:read"])` buộc MỌI request phải có scope này. Việc lưu scope trong token KHÔNG tự động phân quyền riêng từng tool; muốn vậy phải tự kiểm tra scope trong từng tool.
- **Đây là DEMO, không phải xác thực production**: token tĩnh từ biến môi trường, không hết hạn, không thu hồi, không kiểm tra audience. Production cần JWT/OAuth 2.1 qua identity provider, HTTPS, và xoay vòng key.

---

## 3b. Tool Registry & Discovery

Agent **không hard-code** tool nào. Nó hỏi Tool Registry theo yêu cầu task:

```bash
python registry_client.py
```

Kết quả mong đợi:

```
=== Tool Registry ===

  get_weather v1.0.0
    Lấy thời tiết hiện tại của một thành phố
    tags: ['weather', 'current', 'vietnam']  →  server: weather
  get_weather_v2 v2.0.0
    Lấy thời tiết chi tiết — JSON, hỗ trợ forecast và đơn vị đo
    tags: ['weather', 'forecast', 'detailed', 'vietnam']  →  server: weather-v2
  ...

--- Agent cần tool có tag "weather" ---
Tìm thấy 2 tool(s):
  • get_weather v1.0.0 (server: weather)
  • get_weather_v2 v2.0.0 (server: weather-v2)

Best match: get_weather_v2 v2.0.0
Kết nối tới server [weather-v2]...
Kết quả: ...
```

Luồng:

```
Agent nhận task
   │
   ▼
ToolRegistry.search(tag="weather")  ← tìm tool theo capability
   │
   ├── get_weather v1.0 → server: weather
   └── get_weather_v2 v2.0 → server: weather-v2
   │
   ▼
ToolRegistry.best_match()  ← chọn version cao nhất, không deprecated
   │
   ▼
connect_and_call()  ← tự kết nối đúng transport (stdio/HTTP) + auth
```

`registry.json` là **tool-centric** — đơn vị khám phá là tool (tag, description, parameters), không phải server. Production thay JSON bằng DB/API với semantic search.

---

## 3c. Versioning & Backward Compatibility

Server v2 dùng 3 kỹ thuật để thêm tính năng mà không break client cũ:

```bash
# Server chạy qua stdio — client tự spawn
python versioned_client.py
```

| Kỹ thuật | Mô tả |
|---|---|
| **Tool mới song song** | `get_weather_v2` tồn tại bên cạnh `get_weather` — không xoá tool cũ |
| **Tham số optional** | `include_forecast`, `units` có default → client cũ gọi `get_weather_v2(city="Hanoi")` vẫn đúng |
| **Server metadata** | Resource `server://info` công bố version, deprecated tools, migration guide |

```
Server v2
├── get_weather(city)              ← v1, deprecated nhưng vẫn hoạt động
├── get_weather_v2(city, ...)      ← v2, thêm forecast + units
└── resource server://info         ← version + migration guide cho client
```

Kết quả mong đợi:

```
Server: weather-v2 v2.0.0
Deprecated tools: ['get_weather']
Migration: Chuyển từ get_weather sang get_weather_v2. Tham số 'city' giữ nguyên, thêm include_forecast và units.

Tools:
  - get_weather: [v1] Lấy thời tiết hiện tại — trả chuỗi đơn giản. Deprecated, dùng get_weather_v2.
  - get_weather_v2: [v2] Lấy thời tiết chi tiết — JSON, hỗ trợ forecast và đơn vị đo.

[v1] get_weather('Hanoi'):
  Hanoi: 29°C, trời mưa

[v2] get_weather_v2('Hanoi', forecast=True):
  { "api_version": "2.0", "city": "Hanoi", "temp": 29, ... }
```

Luồng:

```
versioned_client.py                     versioned_server.py
       │                                        │
       │── read_resource("server://info") ────▶ │  ← đọc metadata trước
       │◀── version, deprecated_tools ────────  │
       │                                        │
       │── list_tools() ─────────────────────▶  │  ← khám phá tool
       │◀── [get_weather, get_weather_v2] ────  │
       │                                        │
       │── call_tool("get_weather") ──────────▶ │  ← v1 deprecated, vẫn chạy
       │── call_tool("get_weather_v2") ───────▶ │  ← v2 đầy đủ tính năng
```

Client thông minh đọc `server://info` để biết tool nào deprecated, tự chọn dùng v2 nếu có, fallback v1 nếu không.

---

## Ghi chú về cài đặt hiện tại

**Registry** (`registry_client.py`):
- `best_match` chọn version semantic cao nhất trong các tool **không deprecated**; nếu tất cả deprecated thì chọn bản cao nhất trong số đó; trùng version thì chọn theo tên (ổn định).
- `ToolRegistry` ném `RegistryError` cho JSON hỏng, thiếu trường, version sai; `connect_and_call` kiểm tra tham số bắt buộc, server chưa định nghĩa, transport không hỗ trợ, tool trả lỗi, thiếu biến token — thông điệp lỗi không chứa token.
- Đường dẫn script tương đối được tính từ thư mục chứa `registry.json` (chạy được từ mọi cwd). Thiếu biến môi trường token → lỗi rõ ràng (không còn token mặc định).
- Server `email-service` và `db-gateway` là cấu hình **giả định**, chỉ để minh hoạ tìm kiếm; không có dịch vụ thật.

**Versioning** (`versioned_server.py`):
- `get_weather` (v1) giữ nguyên hợp đồng; `get_weather_v2` thêm `include_forecast`, `units` (mặc định `celsius`).
- Khi `units="fahrenheit"`, **cả `temp` lẫn mọi `forecast[].temp`** được đổi sang °F (trước đây forecast vẫn là °C). Đơn vị khác `celsius`/`fahrenheit` bị từ chối (`isError`).
- Migrate client v1 → v2: đọc `server://info` (`deprecated_tools`, `migration_guide`), đổi tên tool sang `get_weather_v2`, giữ `city`, parse kết quả là JSON thay vì chuỗi.
- Dữ liệu là mock.
