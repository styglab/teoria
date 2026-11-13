"""Environment selection must preserve credentials and target only an explicit cluster/role."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT/'deploy/kubernetes/envs/settings.sh'


def run(*args, environment=None):
    return subprocess.run(['bash', str(SCRIPT), *args], text=True, capture_output=True, env=environment)


@pytest.mark.parametrize('stage', ['dev','prod'])
def test_initialization_protects_existing_values_and_file_permissions(tmp_path, stage):
    target = tmp_path/'private'
    target.mkdir()
    existing = target/'secrets.env'
    existing.write_text('TEORIA_ADMIN_API_TOKEN=synthetic-preserve\n')
    result = run('init', '--env', stage, '--dir', str(target))
    assert result.returncode == 0, result.stderr
    assert target.stat().st_mode & 0o777 == 0o700
    assert existing.read_text() == 'TEORIA_ADMIN_API_TOKEN=synthetic-preserve\n'
    for name in ('connections','secrets','control','workload','specification','harbor_secrets'):
        file = target/(name+'.env')
        assert file.is_file()
        assert file.stat().st_mode & 0o777 == 0o600
    assert 'synthetic-preserve' not in result.stdout + result.stderr


@pytest.fixture
def kubectl(tmp_path):
    binary = tmp_path/'bin'
    binary.mkdir()
    record = tmp_path/'calls.jsonl'
    executable = binary/'kubectl'
    executable.write_text('''#!/usr/bin/env python3
import base64,json,os,sys
args=sys.argv[1:]
body=sys.stdin.read() if args[-2:]==['-f','-'] else ''
with open(os.environ['TEORIA_TEST_SECRET_CALLS'],'a') as stream:stream.write(json.dumps({'args':args,'body':body})+'\\n')
if args[:2]==['config','get-contexts']:
    print(args[2] if args[2]!='missing-context' else '')
elif 'create' in args:
    config='configmap' in args
    kind='ConfigMap' if config else 'Secret'
    name=args[args.index('configmap')+1] if config else args[args.index('generic')+1]
    print(json.dumps({'apiVersion':'v1','kind':kind,'metadata':{'name':name},'data':({'PREFECT_API_URL':'http://synthetic-only'} if config else {'TOKEN':base64.b64encode(b'synthetic-only').decode()})}))
elif 'apply' in args:
    if os.environ.get('TEORIA_TEST_SECRET_CONFLICT')=='1':
        print('field ownership conflict',file=sys.stderr);sys.exit(1)
    print('secret/fixture configured')
''')
    executable.chmod(0o755)
    return {**os.environ, 'PATH':str(binary)+os.pathsep+os.environ['PATH'],
            'TEORIA_TEST_SECRET_CALLS':str(record)}, record


def private_file(tmp_path, name):
    directory = tmp_path/'inputs'
    directory.mkdir(mode=0o700)
    file = directory/name
    file.write_text('PREFECT_API_URL=http://synthetic-only\n' if name=='connections.env' else 'TOKEN=synthetic-only\n')
    file.chmod(0o600)
    return directory, file


@pytest.mark.parametrize('stage', ['dev','prod'])
@pytest.mark.parametrize('role,file,namespace,secret', [
    ('connections','connections.env','teoria','teoria-mlops-connections'),
    ('platform','secrets.env','teoria','teoria-secrets'),
    ('control','control.env','teoria','model-control'),
    ('workload','workload.env','teoria-models','model-workload'),
    ('specification','specification.env','teoria','specification-processing'),
    ('harbor','harbor_secrets.env','harbor','harbor-secrets'),
])
def test_registration_uses_explicit_context_and_role_without_switching_context(tmp_path, kubectl, stage, role, file, namespace, secret):
    environment, record = kubectl
    directory, _ = private_file(tmp_path, file)
    result = run('apply','--env',stage,'--dir',str(directory),'--context','chosen-cluster','--role',role, environment=environment)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in record.read_text().splitlines()]
    assert not any('use-context' in call['args'] for call in calls)
    mutations = [c['args'] for c in calls if 'create' in c['args'] or 'apply' in c['args']]
    assert len(mutations) == 2
    for command in mutations:
        assert command[:4] == ['--context','chosen-cluster','-n',namespace]
    create = next(command for command in mutations if 'create' in command)
    apply = next(command for command in mutations if 'apply' in command)
    assert create[create.index('configmap' if role=='connections' else 'generic')+1] == secret
    assert '--from-env-file='+str(directory/file) in create
    assert '--dry-run=client' in create
    assert '--server-side' in apply
    assert '--field-manager='+('teoria-env-connections' if role=='connections' else 'teoria-env-secrets') in apply
    assert '--force-conflicts' not in apply
    assert 'synthetic-only' not in result.stdout + result.stderr


@pytest.mark.parametrize('problem', ['no-context','missing-context','placeholder','permissions'])
def test_invalid_inputs_do_not_register_any_secret(tmp_path, kubectl, problem):
    environment, record = kubectl
    directory, file = private_file(tmp_path, 'secrets.env')
    options = ['apply','--env','dev','--dir',str(directory),'--role','platform']
    if problem != 'no-context':options += ['--context', 'missing-context' if problem=='missing-context' else 'chosen-cluster']
    if problem == 'placeholder':file.write_text('TOKEN=CHANGE_ME\n')
    if problem == 'permissions':file.chmod(0o644)
    result = run(*options, environment=environment)
    assert result.returncode != 0
    calls = [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
    assert not any('create' in call['args'] or 'apply' in call['args'] for call in calls)


def test_field_ownership_conflict_is_not_forced(tmp_path, kubectl):
    environment, record = kubectl
    directory, _ = private_file(tmp_path, 'secrets.env')
    result = run('apply','--env','prod','--dir',str(directory),'--context','chosen-cluster','--role','platform',
                 environment={**environment,'TEORIA_TEST_SECRET_CONFLICT':'1'})
    assert result.returncode != 0
    assert 'field ownership conflict' in result.stderr
    assert 'Registered' not in result.stdout
    calls = [json.loads(line) for line in record.read_text().splitlines()]
    assert not any('--force-conflicts' in call['args'] for call in calls)


def test_real_environment_inputs_are_git_ignored_and_examples_are_tracked_candidates():
    for stage in ('dev','prod'):
        for name in ('connections','secrets','control','workload','specification','harbor_secrets'):
            relative = f'deploy/kubernetes/envs/{stage}/{name}.env'
            ignored = subprocess.run(['git','-c','safe.directory='+str(ROOT),'check-ignore','--no-index','-q',relative], cwd=ROOT)
            assert ignored.returncode == 0
            example = subprocess.run(['git','-c','safe.directory='+str(ROOT),'check-ignore','--no-index','-q',relative+'.example'], cwd=ROOT)
            assert example.returncode == 1


def test_filled_values_are_accepted_when_example_comments_mention_placeholder(tmp_path, kubectl):
    environment, record = kubectl
    directory=tmp_path/'operator'
    result=run('init','--env','dev','--dir',str(directory))
    assert result.returncode == 0
    file=directory/'secrets.env'
    lines=file.read_text().splitlines()
    file.write_text('\n'.join(line if line.startswith('#') else line.replace('CHANGE_ME','synthetic-value') for line in lines)+'\n')
    assert 'CHANGE_ME' in file.read_text()  # Documentation comments remain useful.
    result=run('apply','--env','dev','--dir',str(directory),'--context','chosen-cluster','--role','platform', environment=environment)
    assert result.returncode == 0, result.stderr
    assert 'synthetic-value' not in result.stdout+result.stderr


def test_credentials_cannot_be_registered_as_connections_keys(tmp_path, kubectl):
    environment, record=kubectl
    directory,file=private_file(tmp_path,'connections.env')
    file.write_text('TEORIA_ADMIN_API_TOKEN=synthetic-must-remain-private\n')
    result=run('apply','--env','dev','--dir',str(directory),'--context','chosen-cluster','--role','connections',environment=environment)
    assert result.returncode != 0
    assert 'Unknown connections key' in result.stderr
    assert 'synthetic-must-remain-private' not in result.stdout+result.stderr
    assert not record.exists()
