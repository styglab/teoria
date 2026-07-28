import argparse
import asyncio
import json
from pathlib import Path

import yaml
from dotenv import load_dotenv

from teoria.registry.loader import RegistryLoadError, RegistryLoader
from teoria.registry.validator import RegistryValidator
from teoria.verification.source import create_source_verification_graph


def _add_verify_parser(subparsers: argparse._SubParsersAction) -> None:
    verify_parser = subparsers.add_parser("verify", help="run a registry verification workflow")
    verify_subparsers = verify_parser.add_subparsers(dest="registry_type", required=True)
    source_parser = verify_subparsers.add_parser("source", help="verify a Source Registry")
    source_parser.add_argument("--profile", choices=("static", "build", "live"), default="static")
    source_parser.add_argument("--registries", default="registries", type=Path)
    source_parser.add_argument("--source")
    source_parser.add_argument("--operation")
    source_parser.add_argument("--input", type=Path)


def _load_input(path: Path | None) -> dict:
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("verification input must be an object")
    return value


async def _verify_source(args: argparse.Namespace) -> int:
    try:
        input_data = _load_input(args.input)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"ERROR invalid_verification_input: {exc}")
        return 1
    graph = create_source_verification_graph()
    result = await graph.ainvoke(
        {
            "registry_root": str(args.registries),
            "source_id": args.source,
            "operation_id": args.operation,
            "profile": args.profile,
            "input_data": input_data,
            "diagnostics": [],
            "completed_steps": [],
            "step_results": [],
            "status": "pending",
        }
    )
    for step in result.get("step_results", []):
        print(f"{step['status'].upper()} {step['name']}")
    for diagnostic in result.get("diagnostics", []):
        location = f" [{diagnostic['location']}]" if diagnostic.get("location") else ""
        print(f"{diagnostic['severity'].upper()} {diagnostic['code']}: {diagnostic['path']}{location}: {diagnostic['message']}")
    if result.get("prepared_request"):
        request = result["prepared_request"]
        print(f"REQUEST {request['method']} {request['url']}")
        if request.get("authentication"):
            print(f"AUTH {request['authentication']['environment_variable']}")
    status = result.get("status", "failed")
    success_labels = {"static": "VALID", "build": "BUILDABLE", "live": "VERIFIED"}
    display_status = success_labels[args.profile] if status == "passed" else status.upper()
    print(f"STATUS {display_status}")
    return 0 if result.get("status") == "passed" else 1


def main() -> int:
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(prog="teoria")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate authored registries")
    validate_parser.add_argument("path", nargs="?", default="registries", type=Path)
    validate_parser.add_argument("--source", help="validate only one source id")
    _add_verify_parser(subparsers)
    args = parser.parse_args()

    if args.command == "verify" and args.registry_type == "source":
        return asyncio.run(_verify_source(args))

    try:
        catalog = RegistryLoader(args.path).load()
    except RegistryLoadError as exc:
        for diagnostic in exc.diagnostics:
            print(diagnostic)
        return 1

    diagnostics = RegistryValidator().validate(catalog, source_id=args.source)
    for diagnostic in diagnostics:
        print(diagnostic)
    if diagnostics:
        return 1

    source_count = 1 if args.source else len(catalog.sources)
    print(f"Validated {source_count} sources and {len(catalog.formats)} formats.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
