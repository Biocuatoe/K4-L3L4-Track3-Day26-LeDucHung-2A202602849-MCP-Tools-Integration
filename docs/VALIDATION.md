# Validation report

Everything below was executed on 2026-10-15 on the author's Windows 10 machine unless marked **blocked** or **not run**.
No credential values appear in this report; command outputs were checked before being recorded.

## Environment

| Item | Value |
|---|---|
| OS / shell | Windows 10 Pro, Git Bash + PowerShell |
| Root venv | Python 3.11.9, `mcp` 2.3.0 (from `requirements.txt`), pytest 9.1, ruff 0.17 |
| Lab 04 server env | uv 0.12.15, `mcp` 1.28.1, FastMCP API (`uv.lock`, `uv sync --frozen`) |
| Lab 04 client env | Python 3.14 (uv-managed, requires ≥3.12), `google-adk` 2.3.0, `mcp` 1.28.1 |
| Docker | 29.8.0 client installed; daemon not running (see Blocked) |

The three environments are kept separate (root MCP SDK v2 vs. Lab 04 on `mcp` 1.28.1). `uv.lock` files only gained
the new `dev` dependency group (pytest, pytest-asyncio); no runtime package versions changed.

## Automated tests (offline, no keys, no network)

| Command | Result |
|---|---|
| `python -m pytest -q` (repo root, Modules 01–03 + hygiene) | **76 passed** |
| `cd 04-lab/mcp-server; uv run --frozen pytest -q` | **34 passed** |
| `cd 04-lab/mcp-client; uv run --frozen pytest -q` | **23 passed** |
| Total | **133 passed, 0 failed, 0 skipped** |
| `ruff check .` | All checks passed |
| `python -m compileall` over all sources | OK |
| `registry.json` parsed (also a test) | OK |

What the tests cover: Function Calling dispatch/schema/validation/tool errors/loop limit with a fake model;
MCP discovery + invocation in-process and over a real stdio subprocess (from a different cwd);
HTTP auth against a real uvicorn server (valid, missing, invalid, malformed, scope-less token → 200/401/401/403);
registry search, semantic version selection, deprecated handling, invalid config, stdio and Streamable-HTTP dispatch,
sanitized errors; v1 compatibility and v2 defaults/forecast/Celsius/Fahrenheit (forecast converted too)/invalid units/resource;
WeatherAPI success, key/city/days validation, HTTP 400/401/403/5xx, timeout, network failure, bad JSON, missing fields,
and that the key never appears in logs/errors (all with `httpx.MockTransport`); verifier steps/exit codes against a real
local MCP server; agent configuration, explicit failure and opt-in degraded mode; repo hygiene (no `.env`/`.DS_Store`
tracked, no secret-like strings in tracked files).

## Module-by-module status

| Module | Status | Evidence |
|---|---|---|
| 01 Function Calling | Verified | Unit tests + **live** Gemini smoke test (`gemini-3.8-flash`): model requested `get_weather` for two cities, app executed, final Vietnamese answer returned |
| 02 MCP basics | Verified | `weather_client.py` run end-to-end; protocol tests (initialize → list_tools → call_tool, errors flagged `is_error`) |
| 03 Auth | Verified (demo-grade) | Real HTTP server tests; scope enforced at endpoint level only (documented); no default credentials in source |
| 03 Registry | Verified | Unit + dispatch tests; `registry_client.py` run end-to-end (selects `get_weather_v2`) |
| 03 Versioning | Verified | Unit + protocol tests; `versioned_client.py` run end-to-end |
| 04 Server | Verified live | See below |
| 04 Verifier | Verified live | 8/8 steps passed with the real server running |
| 04 ADK agent | Verified live | See below |

## Live integration (real credentials loaded from the existing `.env` files, never printed)

1. **WeatherAPI**: reached via the running MCP server. `get_current_weather("Hanoi")` and `get_forecast("Danang", 3)`
   returned real data; `days=0`/`7`, an unknown city (`HTTP 400 … No matching location found`) and a blank city were
   returned as `isError=true` with sanitized messages. The server's console log was checked against the real key values:
   **not present**.
2. **MCP protocol against the real server** (`verify_setup.py`): HTTP reachability (GET → 406, as expected for a bare GET),
   `initialize` (server `weather`, protocol 2025-11-25), `list_tools` (`get_current_weather`, `get_forecast`,
   `health_check`), `health_check` call, agent import — all passed.
3. **Gemini ADK agent**: with the server running, an `InMemoryRunner` request "What is the current weather in Hanoi?
   Use your tools." produced a real `function_call` `get_current_weather {'city': 'Hanoi'}`, a matching
   `function_response` (≈600 chars from the MCP server), and a final model answer built from it.
4. **Model finding**: the originally configured `gemini-2.5-flash` returns `404 NOT_FOUND … no longer available to new users`
   for this key (provider message recommended `gemini-3.8-flash`; the key's model list includes it). Defaults in
   Module 01 and the ADK agent were changed to `gemini-3.8-flash` (override with `GEMINI_MODEL`). Several attempts hit
   transient `503 UNAVAILABLE` ("high demand") before succeeding; this was a provider-side condition, not a code failure.

## CI

GitHub Actions (`.github/workflows/ci.yml`, offline only): the first run on commit `71ca066` **failed** — the repo-hygiene test flagged a secret-shaped *fake* key in a test file (it had passed locally only because the new file was not yet tracked). Commit `5e1e08e` fixed the fixture and the run on it **succeeded** (root modules on Python 3.11 and 3.12, Lab 04 server, Lab 04 client).

## Blocked / not run

| Item | Status | Reason / next step |
|---|---|---|
| Docker image build + container smoke test | **Blocked** | `docker build` failed: Docker Desktop daemon not running (`npipe:////./pipe/dockerDesktopLinuxEngine` not found). The Dockerfile was rewritten (uv + `uv.lock`, non-root, `HOST=0.0.0.0`, `.dockerignore`) but is **untested**. Start Docker Desktop, then `cd 04-lab/mcp-server; docker build -t weather-mcp .` |
| Cloud Run deployment | **Not run** | Public/billable; deliberately not attempted. Instructions in `04-lab/README.md` |
| `adk web` browser UI | **Not run** | The ADK runner path (same agent object) was exercised programmatically instead |

## Known limitations

- Module 03 authentication is a static-token teaching demo, not production auth; scopes are enforced per endpoint, not per tool.
- Modules 01–03 data are mock datasets, labelled as such.
- `McpToolset` connects lazily; a down MCP server surfaces as an error on the first request, and `verify_setup.py` is the
  tool to catch it beforehand.
- `uv.lock` resolution-marker lines were reformatted by the installed uv version when adding the dev group (no version changes).
