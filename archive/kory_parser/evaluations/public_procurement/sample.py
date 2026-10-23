"""Stratified, bounded public attachment sampling from an exported notice frame."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import secrets
import zipfile
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from .history import (
    DEFAULT_HISTORY,
    CorpusHistory,
    atomic_json,
    digest,
    family,
    new_seed,
    used_families,
    used_notices,
    validation_plan,
)

FORMATS = {"pdf", "hwp", "hwpx", "docx", "xlsx", "xls", "jpg", "png"}


def file_format(data):
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        # A CFB container also covers XLS; distinguish it after opening its directory.
        import olefile

        with olefile.OleFileIO(io.BytesIO(data)) as ole:
            return "hwp" if ole.exists("FileHeader") else "xls"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
        for name, kind in [
            ("Contents/section0.xml", "hwpx"),
            ("word/document.xml", "docx"),
            ("xl/workbook.xml", "xlsx"),
        ]:
            if name in names:
                return kind
    raise ValueError("unsupported_container")


def selection(notices, *, seed, per_notice=3, excluded_notices=frozenset()):
    """Round-robin declared format and work type; deterministic within each stratum."""
    strata = defaultdict(list)
    for notice in notices:
        if str(notice["notice_number"]).upper() in excluded_notices:
            continue
        for attachment in notice["attachments"]:
            ext = Path(attachment.get("file_name") or "").suffix.lower().lstrip(".")
            if ext not in FORMATS:
                continue
            row = {
                **attachment,
                **{
                    key: notice.get(key)
                    for key in (
                        "notice_number",
                        "notice_order",
                        "work_type",
                        "organization_code",
                        "notice_published_at",
                    )
                },
            }
            row["declared_format"] = ext
            row["rank"] = hashlib.sha256(
                f"{seed}:{row['notice_number']}:{row['notice_order']}:{row['slot']}".encode()
            ).hexdigest()
            strata[(ext, notice["work_type"])].append(row)
    queues = {key: deque(sorted(rows, key=lambda r: r["rank"])) for key, rows in sorted(strata.items())}
    notice_counts = Counter()
    while any(queues.values()):
        for queue in queues.values():
            if not queue:
                continue
            row = queue.popleft()
            group = row["notice_number"] + ":" + row["notice_order"]
            if notice_counts[group] < per_notice:
                notice_counts[group] += 1
                yield row


def allowed(url):
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"www.g2b.go.kr", "g2b.go.kr"}
        and not parsed.username
        and not parsed.password
    )


async def sample(
    notices_path,
    output,
    *,
    count=24,
    seed=None,
    history_path=DEFAULT_HISTORY,
    file_limit=25 * 1024 * 1024,
    total_limit=150 * 1024 * 1024,
):
    if count < 2 or file_limit < 1 or total_limit < file_limit:
        raise ValueError("At least two documents and positive sampling budgets are required")
    seed = new_seed(seed)
    notices_bytes = notices_path.read_bytes()
    notices = json.loads(notices_bytes)
    with CorpusHistory(history_path) as history:
        frozen = history.regression_bytes()
        output.mkdir(parents=True, exist_ok=False)
        atomic_json(output / "history_before.json", history.state)
        before_hash = digest((output / "history_before.json").read_bytes())
        (output / "regression_manifest.json").write_bytes(frozen)
        previous_hashes = set(history.state["documents"])
        previous_notices = used_notices(history.state)
        rows = list(selection(notices, seed=seed, excluded_notices=previous_notices))
        plan = validation_plan(rows, used_families(history.state), seed)
        # Never substitute already exposed families to make a validation set look full.
        if "validation" not in plan.values():
            rows = []
        desired_validation = max(1, count // 3)
        limits = {"development": count - desired_validation, "validation": desired_validation}
        selected, attempts, seen = [], [], set()
        exposed_validation_families = set()
        transferred = 0
        run_id = secrets.token_hex(12)
        history.state["runs"][run_id] = {
            "seed": seed,
            "output": str(output.resolve()),
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
            "history_before_sha256": before_hash,
        }
        history.save()
        status = "interrupted"
        try:
            async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
                for item in rows:
                    if len(selected) >= count or transferred >= total_limit:
                        break
                    group = family(item)
                    split = plan[group]
                    if split == "validation" and group in exposed_validation_families:
                        continue
                    if sum(row["split"] == split for row in selected) >= limits[split]:
                        continue
                    identifier = (
                        f"{item['notice_number'].lower()}_{item['notice_order']}_{int(item['slot']):02d}"
                    )
                    attempt = {"document_id": identifier, "status": "failed"}
                    try:
                        url = item["url"]
                        for _ in range(5):
                            if not allowed(url):
                                raise ValueError("unsupported_download_host")
                            async with client.stream("GET", url) as response:
                                if response.is_redirect:
                                    url = urljoin(url, response.headers["location"])
                                    continue
                                response.raise_for_status()
                                chunks, size = [], 0
                                async for chunk in response.aiter_bytes(65536):
                                    size += len(chunk)
                                    transferred += len(chunk)
                                    if size > file_limit or transferred > total_limit:
                                        raise ValueError("download_budget_exceeded")
                                    chunks.append(chunk)
                                data = b"".join(chunks)
                                kind = file_format(data)
                                checksum = digest(data)
                                if checksum in previous_hashes or checksum in seen:
                                    attempt["status"] = (
                                        "duplicate_history"
                                        if checksum in previous_hashes
                                        else "duplicate_current"
                                    )
                                    if checksum in previous_hashes and split == "validation":
                                        exposed_validation_families.add(group)
                                        for earlier in selected[:]:
                                            if earlier["family"] == group:
                                                selected.remove(earlier)
                                                attempts.append(
                                                    {
                                                        "document_id": earlier["document_id"],
                                                        "status": "validation_family_withdrawn",
                                                    }
                                                )
                                    # Remember a previously unknown notice alias of an old file too.
                                    history.register(
                                        [{**item, "sha256": checksum, "family": group}], run_id=run_id
                                    )
                                    break
                                seen.add(checksum)
                                destination = output / "documents" / identifier / ("original." + kind)
                                destination.parent.mkdir(parents=True)
                                destination.write_bytes(data)
                                row = {
                                    **item,
                                    "document_id": identifier,
                                    "format": kind,
                                    "sha256": checksum,
                                    "source_path": str(destination.resolve()),
                                    "bytes": len(data),
                                    "family": group,
                                    "split": split,
                                    "downloaded_at": datetime.now(UTC).isoformat(),
                                }
                                history.register([row], role=split, run_id=run_id)
                                selected.append(row)
                                attempt.update(status="downloaded", format=kind, bytes=len(data), split=split)
                                break
                        else:
                            raise ValueError("redirect_limit")
                    except (httpx.HTTPError, ValueError, OSError, zipfile.BadZipFile) as error:
                        attempt["error_type"] = type(error).__name__
                    attempts.append(attempt)
                    atomic_json(output / "manifest.json", selected)
                    atomic_json(output / "attempts.json", attempts)
                    print(json.dumps(attempt), flush=True)
                    await asyncio.sleep(0.2)
            status = "complete" if len(selected) == count else "insufficient_fresh_candidates"
        finally:
            atomic_json(output / "manifest.json", selected)
            atomic_json(output / "attempts.json", attempts)
            for split in ("development", "validation"):
                atomic_json(
                    output / (split + "_manifest.json"), [row for row in selected if row["split"] == split]
                )
            history.state["runs"][run_id].update(
                status=status, sampled_count=len(selected), finished_at=datetime.now(UTC).isoformat()
            )
            history.save()
            summary = {
                "schema_version": 1,
                "run_id": run_id,
                "status": status,
                "fresh_manifest_sha256": digest((output / "manifest.json").read_bytes()),
                "seed": seed,
                "history_path": str(history.path),
                "history_before_sha256": before_hash,
                "history_after_sha256": digest(history.path.read_bytes()),
                "previously_used_documents": len(previous_hashes),
                "excluded_previous_notice_count": sum(
                    str(n["notice_number"]).upper() in previous_notices for n in notices
                ),
                "regression_documents": history.state["regression"]["documents"],
                "regression_manifest_sha256": digest(frozen),
                "frame_sha256": digest(notices_bytes),
                "notice_frame_count": len(notices),
                "requested_count": count,
                "sampled_count": len(selected),
                "formats": dict(Counter(row["format"] for row in selected)),
                "splits": dict(Counter(row["split"] for row in selected)),
                "work_types": dict(Counter(row["work_type"] for row in selected)),
                "desired_splits": limits,
                "file_limit": file_limit,
                "total_limit": total_limit,
                "transferred_bytes": transferred,
                "attempts": attempts,
                "selection_basis": "New random seed by default; stratified hash order; prior notices and bytes excluded; validation uses unseen families; immutable regression pool copied unchanged.",
            }
            atomic_json(output / "sampling.json", summary)
            atomic_json(
                output / "cycle_manifest.json",
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": status,
                    "fresh_manifest_sha256": digest((output / "manifest.json").read_bytes()),
                    "datasets": {
                        name: {
                            "path": str((output / (name + "_manifest.json")).resolve()),
                            "sha256": digest((output / (name + "_manifest.json")).read_bytes()),
                        }
                        for name in ("regression", "development", "validation")
                    },
                },
            )
        print(
            json.dumps(
                {
                    key: summary[key]
                    for key in ["status", "seed", "sampled_count", "formats", "splits", "work_types"]
                }
            )
        )
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notices-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--seed", help="Explicit seed for reproducible selection; otherwise generate one")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    args = parser.parse_args()
    result = asyncio.run(
        sample(args.notices_json, args.output, count=args.count, seed=args.seed, history_path=args.history)
    )
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
