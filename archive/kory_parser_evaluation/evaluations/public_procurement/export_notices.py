"""Read-only attachment-frame export through a deployed Pipeline's async DB boundary."""

import argparse
import json
import subprocess
from pathlib import Path

from .history import DEFAULT_HISTORY, load_state, new_seed, used_notices

QUERY = Path(__file__).with_name("sample_notices.sql")
WORKER = """
import asyncio,json,sys
from teoria.integrations.data_operations.settings import bootstrap_pipeline_settings
from teoria.integrations.data_operations.persistence.connection import connect
async def main():
 request=json.load(sys.stdin)
 async with connect(bootstrap_pipeline_settings().data_database_url,connect_timeout=10) as conn:
  async with conn.transaction():
   await conn.execute('SET TRANSACTION READ ONLY')
   await conn.execute("SET LOCAL statement_timeout='60s'")
   cursor=await conn.execute(request['sql'],request['params'])
   rows=await cursor.fetchall()
 print(json.dumps([dict(zip(['notice_number','notice_order','work_type','notice_published_at','organization_code','notice_name','attachments'],r)) for r in rows],default=str,ensure_ascii=False))
asyncio.run(main())
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-container", required=True)
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True)
    parser.add_argument("--seed", help="Generate a fresh frame seed unless explicitly provided")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--notices-per-work-type", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.notices_per_work_type < 1:
        parser.error("Positive frame count required")
    if args.output.exists():
        parser.error("Use a new output path")
    seed = new_seed(args.seed)
    excluded = sorted(used_notices(load_state(args.history)))
    request = {
        "sql": QUERY.read_text(),
        "params": {
            "from_date": args.from_date,
            "to_date": args.to_date,
            "seed": seed,
            "frame_limit": args.notices_per_work_type,
            "excluded_notice_numbers": excluded,
        },
    }
    run = subprocess.run(
        ["docker", "exec", "-i", args.worker_container, "python", "-c", WORKER],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if run.returncode:
        print(json.dumps({"export_failed": True, "returncode": run.returncode}))
        return 2
    notices = json.loads(run.stdout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(notices, ensure_ascii=False, indent=2) + "\n")
    args.output.with_suffix(".provenance.json").write_text(
        json.dumps(
            {
                "from_date": args.from_date,
                "to_date": args.to_date,
                "seed": seed,
                "excluded_previous_notices": len(excluded),
                "history_path": str(args.history.resolve()),
                "notices_per_work_type": args.notices_per_work_type,
                "notice_count": len(notices),
                "sql": QUERY.read_text(),
                "read_only": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {"notices": len(notices), "attachment_candidates": sum(len(n["attachments"]) for n in notices)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
