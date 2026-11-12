"""The everyday status command must not mutate workloads or print credentials."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def test_status_only_reads_workloads_and_namespaces(tmp_path):
    calls = tmp_path / 'calls.jsonl'
    kubectl = tmp_path / 'kubectl'
    kubectl.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['TEORIA_TEST_STATUS_CALLS'],'a') as stream:stream.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1:] == ['config','current-context']: print('k3d-teoria')
elif sys.argv[1:3] == ['get','namespace']: print('namespace/'+sys.argv[3])
else: print('fixture workload status')
''')
    kubectl.chmod(0o755)
    environment = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
                   'TEORIA_TEST_STATUS_CALLS': str(calls), 'TEORIA_K3D_REVISION': '',
                   'TEORIA_K3D_KUBECONFIG': str(tmp_path / 'kubeconfig')}
    result = subprocess.run(['bash', str(ROOT / 'deploy/kubernetes/k3d/local.sh'), 'status'],
                            env=environment, text=True, capture_output=True, check=True)
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    assert commands[0] == ['config', 'current-context']
    assert all('get' in args or args == ['config', 'current-context'] for args in commands)
    assert not any(word in args for args in commands for word in ('secret', 'secrets', 'apply', 'delete', 'exec', 'rollout'))
    assert 'fixture workload status' in result.stdout
