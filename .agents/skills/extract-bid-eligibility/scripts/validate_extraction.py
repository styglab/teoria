#!/usr/bin/env python3
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_extraction.py RESULT.json", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "references/eligibility-extraction.schema.json").read_text())
    value = json.loads(Path(sys.argv[1]).read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path))
    for error in errors:
        print(f"{'.'.join(map(str, error.path))}: {error.message}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
