import json

import pytest

from kory_parser import ParseOptions, parse
from kory_parser.cli import main

from .test_numbered_structure import document

LINES = ['Ⅰ. Design', '  1. Unit', '    가. Frame', '    나. Processor', 'Ⅱ. Delivery', '  1. Timing']


def test_api_default_recovers_source_outline_and_explicit_false_preserves_legacy():
    data = document(LINES)
    assert ParseOptions().recover_numbered_structure is True
    default = parse(data).to_dict()
    enabled = parse(data, ParseOptions(recover_numbered_structure=True)).to_dict()
    disabled = parse(data, ParseOptions(recover_numbered_structure=False)).to_dict()
    assert default == enabled
    assert [b['level'] for b in default['blocks']] == [1, 2, 3, 3, 1, 2]
    assert all(b['type'] == 'paragraph' and b['level'] is None for b in disabled['blocks'])


@pytest.mark.parametrize('flag,enabled', [(None, True), ('--numbered-structure', True), ('--no-numbered-structure', False)])
def test_cli_defaults_and_explicit_switches_match_api(tmp_path, monkeypatch, flag, enabled):
    source = tmp_path / 'source.hwpx'
    source.write_bytes(document(LINES))
    output = tmp_path / 'parsed.json'
    args = ['kory-parser', str(source), '-o', str(output)]
    if flag:
        args.append(flag)
    monkeypatch.setattr('sys.argv', args)
    assert main() == 0
    assert json.loads(output.read_text()) == parse(source, ParseOptions(recover_numbered_structure=enabled)).to_dict()
