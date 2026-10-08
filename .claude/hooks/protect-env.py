#!/usr/bin/env python
import json
import sys
from pathlib import Path

BLOCKED_NAMES = {".env", ".env.local", ".env.development", ".env.production", "pyproject.toml", "uv.lock"}


def _matches(path_text: str) -> bool:
    name = Path(path_text).name
    return name in BLOCKED_NAMES or name.startswith(".env")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    if _matches(file_path):
        sys.stdout.write(json.dumps({
            "continue": False,
            "stopReason": "Editing environment or lock files is blocked by project policy.",
            "systemMessage": "Blocked: editing .env, pyproject.toml, or uv.lock requires explicit confirmation."
        }))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
