---
name: gen-test
description: Scaffold test files mirroring app/ structure with pytest-asyncio fixtures, DB transaction rollback, and module-specific patterns
disable-model-invocation: true
---

# Gen Test Skill

Generates test file scaffolding following project conventions.

## Project Test Structure

```
tests/
├── conftest.py              # Shared fixtures (async_client, db_session, etc.)
├── modules/
│   ├── reservations/
│   │   ├── test_models.py
│   │   ├── test_service.py
│   │   └── test_tools.py
│   ├── availability/
│   ├── customers/
│   ├── reminders/
│   └── faqs/
├── channels/
│   ├── whatsapp/
│   └── voice/
├── agent/
├── core/
└── db/
```

## Conventions

1. **Async fixtures**: Use `pytest-asyncio` with `asyncio_mode = "auto"`
2. **DB rollback**: Each test runs in a transaction that rolls back
3. **Async client**: `httpx.AsyncClient` with `ASGITransport`
4. **Module imports**: Import from `app.modules.{module}.{service|models|schemas}`
5. **Naming**: `test_{module}_{functionality}.py`

## Usage

```bash
# From project root
.claude/skills/gen-test/gen-test.sh reservations service
```

Arguments:
- Module: `reservations`, `availability`, `customers`, `reminders`, `faqs`
- Type: `models`, `service`, `tools`, `router`
- Optional: specific test name