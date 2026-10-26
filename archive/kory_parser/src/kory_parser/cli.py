"""Single-document CLI. Writes are explicit; private document content is not logged."""

import argparse
import json
import time
from pathlib import Path

from .api import parse
from .models import ParseOptions


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a document with the independent Python engine")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--pdf-backend", choices=("pymupdf",), default="pymupdf", help=argparse.SUPPRESS)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--images", action="store_true")
    parser.add_argument(
        "--contents", action="store_true", help="Include experimental structured contents in JSON"
    )
    parser.add_argument("--numbered-structure", action=argparse.BooleanOptionalAction, default=True,
                        help="Recover source-indented HWPX manual numbering as list blocks and levels")
    args = parser.parse_args()
    start = time.perf_counter()
    result = parse(
        args.input,
        ParseOptions(
            ocr=args.ocr, images=args.images, pdf_backend=args.pdf_backend, extract_contents=args.contents,
            recover_numbered_structure=args.numbered_structure
        ),
    )
    seconds = time.perf_counter() - start
    content = (
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        if args.format == "json"
        else result.markdown
    )
    args.output.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "success": result.success,
                "format": result.file_type,
                "error_code": result.error_code,
                "warnings": [w.code for w in result.warnings],
                "parse_seconds": seconds,
            }
        )
    )
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
