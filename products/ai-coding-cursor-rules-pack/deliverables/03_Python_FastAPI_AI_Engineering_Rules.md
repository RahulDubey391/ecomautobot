# Module 3: Python 3.12+, FastAPI & AI/LLM Engineering Rules

Copy this template into `.cursor/rules/python-fastapi-ai.mdc`, `CLAUDE.md`, or `.windsurfrules` for Python backend and AI projects.

```markdown
---
description: Production rules for Python 3.12+, FastAPI, Pydantic v2, Async SQLAlchemy, and LLM/Agent pipelines
globs: ["**/*.py"]
---

# Python 3.12+, FastAPI & AI Engineering Rules

## 1. Modern Python & Typing Standards
- Target **Python 3.12+** syntax: use builtin generic types (`list[str]`, `dict[str, Any]`), union syntax (`str | None`), and `pathlib.Path` instead of `os.path`.
- Annotate all function arguments and return values.
- Use **Pydantic v2** idioms exclusively:
  - Use `model_validate()`, `model_dump()`, `ConfigDict(from_attributes=True)`, and `@field_validator` / `@model_validator`.
  - Never use deprecated Pydantic v1 methods (`.dict()`, `.parse_obj()`, `@validator`, `class Config:`).

## 2. FastAPI Architecture (Router -> Service -> Repository)
- **Thin Routers:** FastAPI route handlers (`src/api/routes/`) must only parse requests, invoke a domain service, and return a typed `response_model`. Never write raw SQL or complex business logic inside route functions.
- **Async Event Loop Safety:** Never call blocking I/O (`requests.get`, `time.sleep`, synchronous disk/DB drivers) inside an `async def` endpoint. Use `httpx.AsyncClient`, `asyncio.sleep`, or standard `def` endpoints when calling synchronous libraries.
- **Dependency Injection:** Pass database sessions, auth principals, and external clients via `Annotated[Service, Depends(get_service)]` so endpoints remain 100% unit-testable via `app.dependency_overrides`.

## 3. AI / LLM & Agent Pipeline Engineering
- **Structured Outputs:** Always enforce schema-constrained generation (JSON Schema / Pydantic structured outputs) when extracting data or routing agent decisions. Never rely on fragile regex parsing of free-form LLM prose when structured outputs are supported.
- **Resilience & Observability:**
  - Configure explicit timeouts (`timeout=30.0`) and exponential backoff retries for rate limits (`429`) and transient `5xx` errors on every external model API call.
  - Log token usage, latency, model version, and trace IDs for every LLM invocation without logging raw user API keys or PII.
- **Prompt Separation:** Store complex system prompts and few-shot templates in versioned module constants or dedicated prompt files rather than deeply nested inline strings.

## 4. Testing with Pytest
- Write deterministic tests using `pytest` and `pytest-asyncio`.
- Mock external HTTP and LLM API calls at the boundary using `respx` or dependency overrides—never make live billable API calls in unit tests.
- Cover happy path, boundary validation errors (`422`), unauthorized access (`401`/`403`), and upstream timeout recovery.
```

