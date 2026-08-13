#!/usr/bin/env python3
"""Validate one or more evaluation cases against the bundled schema."""

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="+", type=Path)
    args = parser.parse_args()
    schema_path = Path(__file__).parents[1] / "references/evaluation-case.schema.json"
    validator = Draft202012Validator(
        json.loads(schema_path.read_text()), format_checker=FormatChecker()
    )
    failed = False
    for path in args.cases:
        value = json.loads(path.read_text())
        errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
        if errors:
            failed = True
            for error in errors:
                location = ".".join(map(str, error.path)) or "$"
                print(f"{path}:{location}: {error.message}")
        else:
            print(f"PASS {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
