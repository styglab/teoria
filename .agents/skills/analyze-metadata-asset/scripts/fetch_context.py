#!/usr/bin/env python3
"""Compatibility entrypoint for metadata enrichment."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "enrich-metadata-asset" / "scripts" / "fetch_context.py"), run_name="__main__")
