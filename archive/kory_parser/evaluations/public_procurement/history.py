"""Local corpus use history and an immutable regression pool for sampling cycles."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY = PROJECT / ".artifacts/corpus_history/state.json"


def new_seed(value=None):
    if value is None:
        return secrets.token_hex(16)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Seed must be nonempty")
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def load_state(path):
    if not path.exists():
        return {"schema_version": 1, "documents": {}, "runs": {}, "regression": None}
    state = json.loads(path.read_text())
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or not isinstance(state.get("documents"), dict)
        or not isinstance(state.get("runs"), dict)
    ):
        raise ValueError("Invalid corpus history; refuse to reset it")
    return state


def notice_number(row):
    if row.get("notice_number"):
        return str(row["notice_number"]).upper()
    for key in ["notice_group", "source_path", "document_id"]:
        match = re.search(r"R\d{2}BK\d+", str(row.get(key, "")), re.IGNORECASE)
        if match:
            return match[0].upper()
    return None


def family(row):
    if row.get("family"):
        return row["family"]
    if row.get("organization_code") and row.get("work_type"):
        return f"{row['organization_code']}:{row['work_type']}"
    return row.get("template_family") or (
        "notice:" + notice_number(row) if notice_number(row) else "source:" + row["sha256"]
    )


def used_notices(state):
    return {number for entry in state["documents"].values() for number in entry["notice_numbers"]}


def used_families(state):
    return {value for entry in state["documents"].values() for value in entry["families"]}


class CorpusHistory:
    def __init__(self, path=DEFAULT_HISTORY):
        self.path = Path(path).resolve()
        self.lock = None
        self.state = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.path.with_suffix(".lock").open("a+")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.state = load_state(self.path)
        except BaseException:
            self.lock.close()
            raise
        return self

    def __exit__(self, *args):
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
        self.lock.close()

    def save(self):
        atomic_json(self.path, self.state)

    def register(self, rows, *, role=None, run_id=None):
        for row in rows:
            checksum = row["sha256"]
            if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
                raise ValueError("Corpus history requires input SHA-256")
            entry = self.state["documents"].setdefault(
                checksum,
                {
                    "sha256": checksum,
                    "notice_numbers": [],
                    "families": [],
                    "roles": [],
                    "run_ids": [],
                    "first_seen_at": datetime.now(UTC).isoformat(),
                },
            )
            for key, value in [
                ("notice_numbers", notice_number(row)),
                ("families", family(row)),
                ("roles", role or row.get("split")),
                ("run_ids", run_id),
            ]:
                if value is not None and value not in entry[key]:
                    entry[key].append(value)
            if row.get("source_path"):
                entry["source_path"] = row["source_path"]
            if row.get("document_id"):
                entry["document_id"] = row["document_id"]
        self.save()

    def regression_bytes(self):
        record = self.state.get("regression")
        if not record:
            raise ValueError("Freeze a regression pool before sampling")
        data = Path(record["path"]).read_bytes()
        if digest(data) != record["sha256"]:
            raise ValueError("Frozen regression manifest changed")
        return data

    def freeze_regression(self, rows, *, source_root=PROJECT.parents[1]):
        unique = {}
        identifiers = set()
        for row in rows:
            if row["sha256"] in unique:
                continue
            path = Path(row["source_path"])
            if not path.is_absolute():
                path = source_root / path
            path = path.resolve()
            if digest(path.read_bytes()) != row["sha256"]:
                raise ValueError("Regression input checksum mismatch")
            identifier = re.sub(r"[^a-z0-9_]+", "_", row["document_id"].lower())
            if identifier in identifiers:
                identifier += "_" + row["sha256"][:12]
            identifiers.add(identifier)
            unique[row["sha256"]] = {
                "document_id": identifier,
                "source_path": str(path),
                "sha256": row["sha256"],
                "format": row["format"],
                "split": "regression",
                "family": family(row),
                "notice_number": notice_number(row),
            }
        if not unique:
            raise ValueError("Regression pool cannot be empty")
        frozen = sorted(unique.values(), key=lambda r: r["document_id"])
        data = (json.dumps(frozen, ensure_ascii=False, indent=2) + "\n").encode()
        if self.state.get("regression"):
            if digest(self.regression_bytes()) != digest(data):
                raise ValueError(
                    "Regression pool is frozen; use a new history for an intentional new version"
                )
            return
        destination = self.path.with_name("regression_manifest.json")
        if destination.exists():
            raise ValueError("Unregistered regression manifest already exists")
        atomic_json(destination, frozen)
        self.state["regression"] = {
            "path": str(destination),
            "sha256": digest(data),
            "documents": len(frozen),
            "frozen_at": datetime.now(UTC).isoformat(),
        }
        self.register(rows, role="regression")


def validation_plan(rows, previous_families, seed):
    families = {family(row) for row in rows}
    fresh = sorted(families - previous_families, key=lambda f: digest(f"{seed}:{f}".encode()))
    count = min(max(1, len(families) // 3), len(fresh), max(0, len(families) - 1))
    validation = set(fresh[:count])
    return {value: "validation" if value in validation else "development" for value in families}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["register", "freeze-regression", "status"])
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--role", choices=["regression", "development", "validation"])
    parser.add_argument("--source-root", type=Path, default=PROJECT.parents[1])
    args = parser.parse_args()
    rows = []
    for path in args.manifest:
        value = json.loads(path.read_text())
        if not isinstance(value, list):
            parser.error("Use an array corpus manifest")
        rows.extend(value)
    if args.action != "status" and not rows:
        parser.error("At least one nonempty manifest is required")
    with CorpusHistory(args.history) as history:
        if args.action == "register":
            history.register(rows, role=args.role)
        elif args.action == "freeze-regression":
            history.freeze_regression(rows, source_root=args.source_root)
        print(
            json.dumps(
                {
                    "used_documents": len(history.state["documents"]),
                    "used_notices": len(used_notices(history.state)),
                    "runs": len(history.state["runs"]),
                    "regression": history.state.get("regression"),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
