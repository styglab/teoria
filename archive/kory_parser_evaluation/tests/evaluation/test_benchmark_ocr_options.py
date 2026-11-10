"""Both actual benchmark executors must receive the same requested OCR option."""

import json
import os
import subprocess
import sys

import pytest

from evaluations.benchmark import PYTHON_WORKER, benchmark
from evaluations.runner import sha


def stub_parser(root):
    package = root / "src/kory_parser"
    package.mkdir(parents=True)
    (package / "version.py").write_text('__version__ = "test"\n')
    (package / "__init__.py").write_text(
        "from types import SimpleNamespace\n"
        "class ParseOptions(SimpleNamespace): pass\n"
        "def parse(data, options):\n"
        ' return SimpleNamespace(to_dict=lambda: {"success": True, "blocks": [], "ocr_received": options.ocr})\n'
    )


@pytest.mark.parametrize("requested", [None, False, True])
def test_python_worker_uses_requested_ocr_and_preserves_default(tmp_path, requested):
    stub_parser(tmp_path)
    source = tmp_path / "source.bin"
    source.write_bytes(b"fixture")
    config = {
        "source": str(source),
        "output": str(tmp_path / "out.json"),
        "measurement": str(tmp_path / "time.json"),
        "repetitions": 3,
    }
    if requested is not None:
        config["ocr"] = requested
    result = subprocess.run(
        [sys.executable, "-c", PYTHON_WORKER],
        check=False,
        input=json.dumps(config),
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tmp_path / "src")),
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    expected = bool(requested)
    assert json.loads((tmp_path / "out.json").read_text())["ocr_received"] is expected
    assert json.loads((tmp_path / "time.json").read_text())["options"]["ocr"] is expected


def test_benchmark_sends_ocr_to_python_and_real_reference_worker(tmp_path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    stub_parser(baseline)
    stub_parser(candidate)
    reference = tmp_path / "reference"
    (reference / "dist").mkdir(parents=True)
    (reference / "package.json").write_text(
        json.dumps({"name": "kordoc", "version": "4.22.15", "type": "module"})
    )
    (reference / "dist/index.js").write_text(
        "export async function parse(data,options){return {success:true,blocks:[],ocr_received:options.ocr};}"
    )
    source = tmp_path / "source.bin"
    source.write_bytes(b"fixture")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "document_id": "case",
                    "format": "png",
                    "source_path": str(source),
                    "sha256": sha(source.read_bytes()),
                }
            ]
        )
    )
    output = tmp_path / "results"
    report = benchmark(manifest, baseline, reference, output, candidate=candidate, ocr=True)
    assert report["ocr"] is True
    for engine in ("baseline", "candidate", "kordoc"):
        assert report["results"][0]["engines"][engine]["success"]
        assert json.loads((output / "case" / (engine + ".json")).read_text())["ocr_received"] is True
        assert report["results"][0]["engines"][engine]["options"]["ocr"] is True
