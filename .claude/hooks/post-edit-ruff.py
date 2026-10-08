#!/usr/bin/env python
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUFF = ROOT / ".venv" / "Scripts" / "ruff.exe"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path")
    if not file_path:
        return 0

    target = Path(file_path)
    if not target.exists() or target.suffix != ".py":
        return 0

    try:
        target.relative_to(ROOT)
    except ValueError:
        return 0

    subprocess.run([str(RUFF), "check", "--fix", str(target)], cwd=ROOT, check=False)
    subprocess.run([str(RUFF), "format", str(target)], cwd=ROOT, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
