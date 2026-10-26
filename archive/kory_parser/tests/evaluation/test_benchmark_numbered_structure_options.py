import json
import os
import subprocess
import sys

import pytest

from evaluations.benchmark import PYTHON_WORKER


@pytest.mark.parametrize('requested', [False, True])
def test_benchmark_honors_explicit_option_even_when_library_defaults_on(tmp_path, requested):
    package = tmp_path / 'src/kory_parser'
    package.mkdir(parents=True)
    (package / 'version.py').write_text('__version__="test"\n')
    (package / '__init__.py').write_text(
        'from dataclasses import dataclass\nfrom types import SimpleNamespace\n'
        '@dataclass\nclass ParseOptions:\n ocr:bool=False\n images:bool=False\n recover_numbered_structure:bool=True\n'
        'def parse(data,options):\n return SimpleNamespace(to_dict=lambda:{"success":True,"received":options.recover_numbered_structure})\n'
    )
    source = tmp_path / 'source.bin'
    source.write_bytes(b'fixture')
    output = tmp_path / 'parsed.json'
    request = {'source': str(source), 'output': str(output), 'measurement': str(tmp_path / 'time.json'),
               'repetitions': 1, 'numbered_structure': requested}
    result = subprocess.run([sys.executable, '-c', PYTHON_WORKER], check=False, input=json.dumps(request), text=True,
                            capture_output=True, cwd=tmp_path, env=dict(os.environ, PYTHONPATH=str(tmp_path / 'src')),
                            timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())['received'] is requested
