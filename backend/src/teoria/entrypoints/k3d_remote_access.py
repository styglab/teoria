"""Plan, apply, verify and recover the optional k3d IP access profile.

Input: k3d/.local/remote_access.env. config.json records the last successful apply.
No cluster or Docker changes occur in --check (the default).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
from uuid import uuid4
from urllib.parse import urlsplit

PROXY = 'teoria-k3d-remote-access'
ROLE = 'k3d-remote-access'
IMAGE = 'nginx:1.27-alpine'
HELPER_IMAGE = 'busybox:1.36'
REGISTRY_FILE = '/etc/rancher/k3s/registries.yaml'
REGISTRY_CA = '/etc/rancher/k3s/harbor_ca.crt'
API_ENV = ('TEORIA_IMAGE_REGISTRY_URL', 'TEORIA_IMAGE_REGISTRY_PUBLIC_HOST')
SECRET_NAMES = [('teoria', 'teoria-secrets'), ('teoria', 'model-control'),
                ('teoria', 'teoria-registry'), ('teoria-models', 'model-images')]


def external_addresses(address, platform_port=18443, harbor_port=18444):
    value = ipaddress.IPv4Address(address)
    if value.is_unspecified or value.is_multicast or value.is_loopback:
        raise ValueError("Use the Docker host's reachable IPv4 address")
    if platform_port == harbor_port or any(not 1024 <= p <= 65535 for p in (platform_port, harbor_port)):
        raise ValueError('Use two different unprivileged HTTPS ports')
    return {'address': str(value), 'platform_port': platform_port, 'harbor_port': harbor_port,
            'platform_url': f'https://{value}:{platform_port}', 'harbor_url': f'https://{value}:{harbor_port}'}


def read_configuration(root: Path, config=None, *, address=None, platform_port=None, harbor_port=None):
    """Explicit CLI > env file > legacy successful receipt; no shell evaluation."""
    path = Path(config) if config else root / 'deploy/kubernetes/k3d/.local/remote_access.env'
    values = {}
    if path.exists():
        names = {'TEORIA_K3D_ADDRESS': 'address', 'TEORIA_K3D_PLATFORM_PORT': 'platform_port',
                 'TEORIA_K3D_HARBOR_PORT': 'harbor_port'}
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            if not separator or key.strip() not in names or names[key.strip()] in values:
                raise ValueError('Invalid or duplicate remote access configuration key')
            values[names[key.strip()]] = value.strip()
    elif config:
        raise ValueError('Remote access configuration file does not exist')
    else:
        receipt = root / 'deploy/kubernetes/k3d/.local/remote_access/config.json'
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            values = {key: saved[key] for key in ('address', 'platform_port', 'harbor_port')}
    for key, value in [('address', address), ('platform_port', platform_port), ('harbor_port', harbor_port)]:
        if value is not None:
            values[key] = value
    if not values and not path.exists() and config is None:
        return None
    if not values.get('address'):
        raise ValueError('Configure TEORIA_K3D_ADDRESS or --address')
    return external_addresses(values['address'], int(values.get('platform_port', 18443)),
                              int(values.get('harbor_port', 18444)))


def deployment_registry(root):
    """Normal deployment uses the same input and refuses unapplied address changes."""
    settings = read_configuration(root)
    if (root / 'deploy/kubernetes/k3d/.local/remote_access/pending.json').exists():
        raise ValueError('Remote access recovery is pending; run --recover first')
    if settings is None:
        return ''
    receipt = root / 'deploy/kubernetes/k3d/.local/remote_access/config.json'
    if not receipt.exists():
        raise ValueError('Apply remote access before using its Registry in a deployment')
    applied = json.loads(receipt.read_text())
    if any(applied.get(key) != value for key, value in settings.items()):
        raise ValueError('Remote access input differs from the applied configuration; run --check and --apply first')
    return settings['harbor_url'].removeprefix('https://')


def harbor_chart_path(root):
    metadata = json.loads((root / 'deploy/kubernetes/harbor/chart.json').read_text())
    version = metadata['version']
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Invalid Harbor chart version')
    filename = 'harbor-' + version + '.tgz'
    cached = root / 'deploy/kubernetes/k3d/.local/cache/charts' / filename
    return cached if cached.exists() else root / 'deploy/kubernetes/k3d/.local' / filename


def nginx_configuration(settings, *, template=None):
    template = template or Path(__file__).resolve().parents[4] / 'deploy/kubernetes/k3d/remote_access.conf.template'
    return Path(template).read_text().replace('${PLATFORM_PORT}', str(settings['platform_port'])).replace(
        '${HARBOR_PORT}', str(settings['harbor_port'])).replace('${ADDRESS}', settings['address'])


def configuration_text(settings):
    return ('TEORIA_K3D_ADDRESS=' + settings['address'] + '\nTEORIA_K3D_PLATFORM_PORT=' +
            str(settings['platform_port']) + '\nTEORIA_K3D_HARBOR_PORT=' + str(settings['harbor_port']) + '\n')


def write_private(path, data):
    """Atomic state writes; failure never leaves a truncated successful receipt."""
    path = Path(path)
    ancestor = path.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    owner = ancestor.stat()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = path.parent
    while parent != ancestor:
        if os.geteuid() == 0:
            os.chown(parent, owner.st_uid, owner.st_gid)
        parent = parent.parent
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data if isinstance(data, bytes) else data.encode())
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(0o600)
            if os.geteuid() == 0:
                os.chown(temporary, owner.st_uid, owner.st_gid)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def secret_updates(settings, secrets):
    """Select only profile-owned keys, preserving DB credentials and other registries."""
    host = settings['harbor_url'].removeprefix('https://')
    result = {}
    for namespace, name in SECRET_NAMES:
        data = secrets[name]['data']
        if name == 'teoria-secrets':
            changes = dict(zip(API_ENV, (settings['harbor_url'], host)))
        elif name == 'model-control':
            allowed = base64.b64decode(data['TEORIA_MODEL_ALLOWED_REGISTRIES']).decode().split(',')
            changes = {'TEORIA_MODEL_ALLOWED_REGISTRIES': ','.join(dict.fromkeys([*filter(None, allowed), host]))}
        else:
            config = json.loads(base64.b64decode(data['.dockerconfigjson']))
            auths = config['auths']
            source = auths.get(host) or auths.get('harbor.teoria.localhost')
            if not source:
                raise ValueError('Pull Secret requires the existing local Harbor login')
            auths[host] = copy.deepcopy(source)
            changes = {'.dockerconfigjson': json.dumps(config)}
        result[name] = {key: base64.b64encode(value.encode()).decode() for key, value in changes.items()}
    return result


async def verify_endpoints(settings, ca_file, credentials):
    """Read-only TLS/authentication probes, with no insecure TLS or external redirects."""
    import httpx

    context = ssl.create_default_context(cafile=str(ca_file))
    platform, harbor = settings['platform_url'], settings['harbor_url']
    basic = 'Basic ' + base64.b64encode(credentials['PREFECT_API_AUTH_STRING'].encode()).decode()
    probes = [
        (platform + '/health', {}, 200),
        (platform + '/admin-api/v1/admin/auth/session', {}, 401),
        (platform + '/admin-api/v1/admin/auth/session', {'Authorization': 'Bearer ' + credentials['TEORIA_ADMIN_API_TOKEN']}, 200),
        (platform + '/admin-api/v1/admin/image-registry/repositories?limit=1', {'Authorization': 'Bearer ' + credentials['TEORIA_ADMIN_API_TOKEN']}, 200),
        (platform + '/prefect/api/health', {'Authorization': basic}, 200),
        (platform + '/mlflow/health', {}, 401),
        (platform + '/mlflow/health', {'Authorization': basic}, 200),
        (harbor + '/api/v2.0/health', {}, 200),
        (harbor + '/v2/', {}, 401),
    ]
    async with httpx.AsyncClient(verify=context, trust_env=False, follow_redirects=False, timeout=15) as client:
        slots = asyncio.Semaphore(4)
        async def probe(url, headers, expected):
            async with slots:
                response = await client.get(url, headers=headers)
                if response.status_code != expected:
                    raise RuntimeError('Remote endpoint authentication/health check failed')
                if url.endswith('/v2/'):
                    challenge = response.headers.get('WWW-Authenticate', '')
                    match = re.search(r'\brealm="([^"]+)"', challenge)
                    realm = urlsplit(match.group(1)) if match else None
                    origin = urlsplit(harbor)
                    if not challenge.startswith('Bearer ') or realm is None or (realm.scheme, realm.netloc, realm.path) != (origin.scheme, origin.netloc, '/service/token'):
                        raise RuntimeError('Harbor Registry challenge points to a different public origin')
        await asyncio.gather(*(probe(*item) for item in probes))


class DevelopmentAccess:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.local = self.root / 'deploy/kubernetes/k3d/.local'
        self.directory = self.local / 'remote_access'
        self.environment = {**os.environ, 'KUBECONFIG': str(self.local / 'kubeconfig')}
        self.journal = None
        self.applying = False

    def run(self, *args, body=None):
        environment = self.environment
        if self.journal and args[:2] == ('bash', self.root / 'deploy/kubernetes/harbor/deploy.sh'):
            environment = {**environment, 'TEORIA_K3D_ACCESS_LOCK_HELD': '1'}
        try:
            result = subprocess.run(list(map(str, args)), input=body, text=True, capture_output=True,
                                    env=environment, timeout=1200)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError(f'{args[0]} command could not complete') from None
        if result.returncode:
            if self.journal or self.applying:
                write_private(self.directory / 'last_error.log', result.stderr + result.stdout)
            raise RuntimeError(f'{args[0]} {args[1]} failed; diagnostics are private')
        return result.stdout

    def kubectl(self, *args, body=None):
        return self.run('kubectl', *args, body=body)

    def get(self, namespace, kind, name):
        value = self.kubectl('-n', namespace, 'get', kind, name, '--ignore-not-found', '-o', 'json')
        return json.loads(value) if value.strip() else None

    def patch(self, namespace, kind, name, value, *, patch_type='merge'):
        self.kubectl('-n', namespace, 'patch', kind, name, '--type', patch_type,
                     '--patch-file', '/dev/stdin', body=json.dumps(value))

    def apply(self, item):
        self.kubectl('apply', '-f', '-', body=json.dumps(item))

    def inspect(self, name):
        value = json.loads(self.run('docker', 'container', 'ls', '-a', '--filter', 'name=^/' + name + '$', '--format', '{{json .}}') or 'null')
        return json.loads(self.run('docker', 'inspect', value['ID']))[0] if value else None

    def node_file(self, path, content=None, *, remove=False):
        if content is not None:
            self.run('docker', 'exec', '-i', 'k3d-teoria-server-0', 'sh', '-c', 'cat > "$1"', 'sh', path, body=content)
        elif remove:
            self.run('docker', 'exec', 'k3d-teoria-server-0', 'rm', '--', path)
        else:
            value = self.run('docker', 'exec', 'k3d-teoria-server-0', 'sh', '-c',
                             'if [ -f "$1" ]; then printf "present\\n"; cat "$1"; else printf "absent\\n"; fi', 'sh', path)
            return value.partition('\n')[2] if value.startswith('present\n') else None

    def daemon_ca(self, host, content=None, *, remove=False):
        command = ('rm -- "/certs/$1/ca.crt"' if remove else
                   'mkdir -p "/certs/$1"; cat > "/certs/$1/ca.crt"' if content is not None else
                   'if [ -f "/certs/$1/ca.crt" ]; then printf "present\\n"; cat "/certs/$1/ca.crt"; else printf "absent\\n"; fi')
        value = self.run('docker', 'run', '--pull=never', '--rm', '-i', '--network', 'none',
                         '--mount', 'type=bind,source=/etc/docker/certs.d,target=/certs' + (',readonly' if content is None and not remove else ''),
                         HELPER_IMAGE, 'sh', '-ec', command, 'sh', host, body=content)
        if content is None and not remove:
            return value.partition('\n')[2] if value.startswith('present\n') else None

    def restore_node(self, settings):
        import yaml
        host = settings['harbor_url'].removeprefix('https://')
        config = yaml.safe_load(self.node_file(REGISTRY_FILE) or '') or {}
        config.setdefault('configs', {}).setdefault(host, {}).setdefault('tls', {})['ca_file'] = REGISTRY_CA
        self.node_file(REGISTRY_FILE, yaml.safe_dump(config))
        directory = '/var/lib/rancher/k3s/agent/etc/containerd/certs.d/' + host
        self.run('docker', 'exec', 'k3d-teoria-server-0', 'mkdir', '-p', directory)
        self.node_file(directory + '/hosts.toml', self.host_configuration(host))

    @staticmethod
    def host_configuration(host):
        return f'server = "https://{host}/v2"\ncapabilities = ["pull", "resolve"]\nca = ["{REGISTRY_CA}"]\n[host]\n'

    def host_root(self):
        hostname = os.getenv('HOSTNAME', '')
        if hostname:
            result = subprocess.run(['docker', 'inspect', hostname, '--format', '{{json .Mounts}}'],
                                    capture_output=True, text=True, timeout=30)
            for mount in json.loads(result.stdout) if result.returncode == 0 else []:
                if mount['Destination'] == str(self.root):
                    return Path(mount['Source'])
        return self.root

    def proxy_arguments(self, release):
        owner = self.root.stat()
        host = self.host_root() / release.relative_to(self.root)
        return ['--network', 'k3d-teoria', '--user', f'{owner.st_uid}:{owner.st_gid}', '--read-only',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--tmpfs', f'/tmp:rw,noexec,nosuid,size=64m,uid={owner.st_uid},gid={owner.st_gid}',
                '--mount', 'type=bind,source=' + str(host / 'nginx.conf') + ',target=/etc/nginx/nginx.conf,readonly',
                '--mount', 'type=bind,source=' + str(host / 'tls') + ',target=/certs,readonly']

    def save_journal(self):
        write_private(Path(self.journal['release']) / 'transaction.json', json.dumps(self.journal))

    def touch(self, name):
        self.journal['touched'].append(name)
        self.save_journal()

    def prepare(self, settings):
        """Validate prerequisites and stage candidate files before changing installed resources."""
        import yaml
        if self.kubectl('config', 'current-context').strip() != 'k3d-teoria':
            raise ValueError('Only the dedicated k3d-teoria context is supported')
        for name in ('k3d-teoria-server-0', 'k3d-teoria-serverlb'):
            if not (self.inspect(name) or {}).get('State', {}).get('Running'):
                raise ValueError('Start the existing k3d cluster before applying IP access')
        proxy = self.inspect(PROXY)
        if proxy and proxy['Config'].get('Labels', {}).get('io.teoria.role') != ROLE:
            raise ValueError('Existing proxy is not owned by the k3d access profile')
        desired_ports = {str(settings['platform_port']), str(settings['harbor_port'])}
        for line in self.run('docker', 'container', 'ls', '--format', '{{.ID}}').splitlines():
            container = json.loads(self.run('docker', 'inspect', line))[0]
            for bindings in (container['HostConfig'].get('PortBindings') or {}).values():
                if container.get('Id') != (proxy or {}).get('Id') and any(
                    item['HostPort'] in desired_ports and item.get('HostIp', '') in {'', '0.0.0.0', '::', settings['address']}
                    for item in bindings or []):
                    raise ValueError('A requested IP/port is already published by another container')
        for image in (IMAGE, HELPER_IMAGE):
            self.run('docker', 'image', 'inspect', image)  # Closed networks: never pull implicitly.
        owned_bindings = {(item.get('HostIp', ''), int(item['HostPort']))
                          for bindings in ((proxy or {}).get('HostConfig', {}).get('PortBindings') or {}).values()
                          for item in bindings or []}
        listeners = self.run('docker', 'run', '--pull=never', '--rm', '--network', 'host', '--read-only', '--cap-drop', 'ALL',
                             HELPER_IMAGE, 'cat', '/proc/net/tcp', '/proc/net/tcp6')
        for line in listeners.splitlines():
            fields = line.split()
            if len(fields) < 4 or fields[3] != '0A':
                continue
            raw_ip, raw_port = fields[1].split(':')
            port = int(raw_port, 16)
            if str(port) not in desired_ports:
                continue
            address_bytes = b''.join(bytes.fromhex(raw_ip[i:i+8])[::-1] for i in range(0, len(raw_ip), 8))
            listener = ipaddress.ip_address(address_bytes)
            if getattr(listener, 'ipv4_mapped', None):
                listener = listener.ipv4_mapped
            if listener.is_unspecified or str(listener) == settings['address']:
                if not any(p == port and ip in {'', '0.0.0.0', '::', settings['address']} for ip, p in owned_bindings):
                    raise ValueError('A requested IP/port is already used on the Docker host')

        for name in ('harbor.crt', 'harbor.key', 'tls.crt'):
            if not (self.local / name).is_file():
                raise ValueError('Prepare local Harbor chart and TLS materials before applying IP access')
        if not harbor_chart_path(self.root).is_file():
            raise ValueError('Prepare the pinned Harbor chart in .local/cache/charts')
        self.run('openssl', 'x509', '-in', self.local / 'harbor.crt', '-checkend', '604800', '-noout')
        secrets = {name: self.get(namespace, 'secret', name) for namespace, name in SECRET_NAMES}
        if any(value is None for value in secrets.values()):
            raise ValueError('Prepare platform/model Registry Secrets before applying IP access')
        updates = secret_updates(settings, secrets)
        credentials = {key: base64.b64decode(secrets['teoria-secrets']['data'][key]).decode()
                       for key in ('TEORIA_ADMIN_API_TOKEN', 'PREFECT_API_AUTH_STRING')}
        if not all(credentials.values()):
            raise ValueError('Prepare API and Prefect credentials before applying IP access')
        admin = self.get('teoria', 'deployment', 'admin-api')
        worker = self.get('teoria', 'deployment', 'model-training-worker')
        if not admin or not worker:
            raise ValueError('Deploy the platform before configuring remote IP access')
        ingress = self.get('harbor', 'ingress', 'harbor-ingress')
        previous_ingress = self.get('harbor', 'ingress', 'harbor-ip-access')
        if not ingress or previous_ingress and previous_ingress['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') != 'teoria-k3d-remote-access':
            raise ValueError('Expected Harbor Ingress ownership was not found')
        history = json.loads(self.run('helm', 'history', 'harbor', '-n', 'harbor', '-o', 'json'))
        if history[-1]['status'] != 'deployed':
            raise ValueError('Recover the existing Harbor Helm release before changing its URL')
        values = json.loads(self.run('helm', 'get', 'values', 'harbor', '-n', 'harbor', '--all', '-o', 'json'))
        node_before = self.node_file(REGISTRY_FILE)
        host = settings['harbor_url'].removeprefix('https://')
        node_config = yaml.safe_load(node_before or '') or {}
        previous_ca = copy.deepcopy(node_config.get('configs', {}).get(host, {}).get('tls', {}).get('ca_file'))
        host_path = '/var/lib/rancher/k3s/agent/etc/containerd/certs.d/' + host + '/hosts.toml'
        host_before = self.node_file(host_path)
        daemon_before = self.daemon_ca(host)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        if os.geteuid() == 0:
            owner = self.root.stat()
            os.chown(self.directory, owner.st_uid, owner.st_gid)
        release = Path(tempfile.mkdtemp(prefix='release_', dir=self.directory))
        tls = release / 'tls'
        tls.mkdir()
        self.run('openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', tls / 'server.key',
                 '-out', tls / 'server.csr', '-subj', '/CN=' + settings['address'])
        (tls / 'extensions.cnf').write_text('basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:' + settings['address'] + '\n')
        self.run('openssl', 'x509', '-req', '-in', tls / 'server.csr', '-CA', self.local / 'harbor.crt',
                 '-CAkey', self.local / 'harbor.key', '-set_serial', '0x' + os.urandom(16).hex(),
                 '-out', tls / 'server.crt', '-days', '365', '-sha256', '-extfile', tls / 'extensions.cnf')
        (tls / 'ca.crt').write_bytes((self.local / 'harbor.crt').read_bytes())
        (tls / 'upstream_ca.crt').write_bytes((self.local / 'harbor.crt').read_bytes() + (self.local / 'tls.crt').read_bytes())
        self.run('openssl', 'verify', '-CAfile', tls / 'ca.crt', '-verify_ip', settings['address'], tls / 'server.crt')
        (release / 'nginx.conf').write_text(nginx_configuration(settings, template=self.root / 'deploy/kubernetes/k3d/remote_access.conf.template'))
        owner = self.root.stat()
        for path in [release, tls, *release.rglob('*')]:
            if path.stat().st_uid != owner.st_uid:
                os.chown(path, owner.st_uid, owner.st_gid)
            path.chmod(0o700 if path.is_dir() else 0o600 if path.name == 'server.key' else 0o644)
        previous_helm_url = values.get('externalURL')
        values['externalURL'] = settings['harbor_url']
        write_private(release / 'harbor_values.json', json.dumps(values))
        self.run('bash', self.root / 'deploy/kubernetes/harbor/deploy.sh', '--overlay', 'k3d',
                 '--chart', harbor_chart_path(self.root), '--values', release / 'harbor_values.json',
                 '--external-url', settings['harbor_url'], '--render')
        self.run('docker', 'run', '--pull=never', '--rm', *self.proxy_arguments(release), '--entrypoint', 'nginx', IMAGE, '-t')
        ingress_spec = {'ingressClassName': ingress['spec']['ingressClassName'], 'rules': [{'http': ingress['spec']['rules'][0]['http']}]}
        local_files = [self.local / 'remote_access.env', self.directory / 'config.json', self.local / 'access.json',
                       self.directory / 'tls/ca.crt']
        before_files = {str(path): base64.b64encode(path.read_bytes()).decode() if path.exists() else None for path in local_files}
        container = next(c for c in admin['spec']['template']['spec']['containers'] if c['name'] == 'admin-api')
        before_env = {value['name']: value for value in container.get('env', []) if value['name'] in API_ENV}
        return {'release': str(release), 'settings': settings, 'touched': [],
                'before': {'secrets': secrets, 'updates': updates, 'admin_env': before_env, 'files': before_files,
                           'ingress': previous_ingress, 'ingress_spec': ingress_spec, 'helm_revision': int(history[-1]['revision']),
                           'helm_external_url': previous_helm_url,
                           'proxy_id': proxy['Id'] if proxy else None, 'proxy_running': bool(proxy and proxy['State']['Running']),
                           'backup_proxy': PROXY + '-previous-' + uuid4().hex[:12], 'node_ca': previous_ca,
                           'host_path': host_path, 'host_file': host_before, 'daemon_ca': daemon_before}}

    def switch_proxy(self):
        settings, before = self.journal['settings'], self.journal['before']
        self.touch('proxy')
        if before['proxy_id']:
            if before['proxy_running']:
                self.run('docker', 'stop', before['proxy_id'])
            self.run('docker', 'rename', before['proxy_id'], before['backup_proxy'])
        self.run('docker', 'run', '--pull=never', '-d', '--name', PROXY, '--restart', 'unless-stopped',
                 '--label', 'io.teoria.role=' + ROLE, '--label', 'io.teoria.transaction=' + Path(self.journal['release']).name,
                 *self.proxy_arguments(Path(self.journal['release'])),
                 '-p', f"{settings['address']}:{settings['platform_port']}:{settings['platform_port']}",
                 '-p', f"{settings['address']}:{settings['harbor_port']}:{settings['harbor_port']}",
                 '--entrypoint', 'nginx', IMAGE, '-g', 'daemon off;')

    def rollout(self):
        self.kubectl('-n', 'teoria', 'rollout', 'restart', 'deployment/model-training-worker')
        for name in ('admin-api', 'model-training-worker'):
            self.kubectl('-n', 'teoria', 'rollout', 'status', 'deployment/' + name, '--timeout=180s')

    def verify(self, settings, release=None):
        data = self.get('teoria', 'secret', 'teoria-secrets')['data']
        credentials = {key: base64.b64decode(data[key]).decode() for key in ('TEORIA_ADMIN_API_TOKEN', 'PREFECT_API_AUTH_STRING')}
        ca = Path(release) / 'tls/ca.crt' if release else self.directory / 'tls/ca.crt'
        async def ready():
            import httpx
            for attempt in range(10):
                try:
                    await verify_endpoints(settings, ca, credentials)
                    return
                except (httpx.HTTPError, RuntimeError):
                    if attempt == 9:
                        raise RuntimeError('Remote HTTPS/authentication checks failed after retries') from None
                    await asyncio.sleep(2)
        asyncio.run(ready())

    def expose(self, settings):
        self.applying = True
        if (self.directory / 'pending.json').exists():
            raise ValueError('A previous access change needs --recover before another apply')
        self.journal = self.prepare(settings)
        self.save_journal()
        write_private(self.directory / 'pending.json', json.dumps({'release': self.journal['release']}))
        before = self.journal['before']
        host = settings['harbor_url'].removeprefix('https://')
        try:
            self.touch('ingress')
            self.apply({'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress',
                        'metadata': {'namespace': 'harbor', 'name': 'harbor-ip-access',
                                     'labels': {'app.kubernetes.io/managed-by': 'teoria-k3d-remote-access'}},
                        'spec': before['ingress_spec']})
            self.touch('helm')
            self.run('bash', self.root / 'deploy/kubernetes/harbor/deploy.sh', '--overlay', 'k3d',
                     '--chart', harbor_chart_path(self.root), '--values', Path(self.journal['release']) / 'harbor_values.json',
                     '--external-url', settings['harbor_url'])
            self.touch('node')
            self.restore_node(settings)
            self.touch('daemon')
            self.daemon_ca(host, (self.local / 'harbor.crt').read_text())
            for namespace, name in SECRET_NAMES:
                changes = before['updates'][name]
                self.touch('secret:' + name)
                self.patch(namespace, 'secret', name, {'data': changes})
            self.touch('admin')
            env = [{'name': key, 'value': value, 'valueFrom': None} for key, value in zip(API_ENV, (settings['harbor_url'], host))]
            self.patch('teoria', 'deployment', 'admin-api', {'spec': {'template': {'spec': {'containers': [{'name': 'admin-api', 'env': env}]}}}}, patch_type='strategic')
            self.rollout()
            self.switch_proxy()
            self.verify(settings, self.journal['release'])
            access = json.loads((self.local / 'access.json').read_text()) if (self.local / 'access.json').exists() else {}
            access.update(platform_url=settings['platform_url'], harbor_url=settings['harbor_url'],
                          windows_ca_file=str(self.directory / 'tls/ca.crt'))
            file_updates = {
                str(self.local / 'remote_access.env'): configuration_text(settings).encode(),
                str(self.directory / 'config.json'): (json.dumps(settings, indent=2) + '\n').encode(),
                str(self.directory / 'tls/ca.crt'): (Path(self.journal['release']) / 'tls/ca.crt').read_bytes(),
                str(self.local / 'access.json'): (json.dumps(access, indent=2) + '\n').encode(),
            }
            before['file_updates'] = {name: base64.b64encode(data).decode() for name, data in file_updates.items()}
            self.touch('files')
            for name, data in file_updates.items():
                write_private(Path(name), data)
        except BaseException:
            try:
                self.recover()
            except Exception:
                raise RuntimeError('Access change failed and recovery is incomplete; keep private state and run --recover') from None
            raise RuntimeError('Access change failed; the previous configuration was restored') from None
        self.directory.joinpath('pending.json').unlink()
        # Keep the immutable mounted files, discard saved Secret bodies after successful commit.
        write_private(Path(self.journal['release']) / 'transaction.json', json.dumps({'settings': settings, 'status': 'committed'}))
        if before['proxy_id']:
            try:
                self.run('docker', 'rm', before['proxy_id'])
            except RuntimeError:
                print('Access configuration applied; the previous stopped proxy was retained for cleanup')
        Path(self.journal['release']).joinpath('harbor_values.json').unlink(missing_ok=True)
        self.journal = None

    def restore_secret(self, namespace, name):
        before = self.journal['before']
        resource = self.get(namespace, 'secret', name)
        current = resource['data']
        changes = {}
        for key, applied in before['updates'][name].items():
            old = before['secrets'][name]['data'].get(key)
            now = current.get(key)
            if now == old:
                continue
            if key == '.dockerconfigjson':
                host = self.journal['settings']['harbor_url'].removeprefix('https://')
                original = json.loads(base64.b64decode(old))
                wanted = json.loads(base64.b64decode(applied))
                active = json.loads(base64.b64decode(now))
                original_auth = original['auths'].get(host)
                if active['auths'].get(host) == original_auth:
                    continue
                if active['auths'].get(host) != wanted['auths'].get(host):
                    raise RuntimeError('Registry credentials changed concurrently; recovery stopped')
                if original_auth is None:
                    active['auths'].pop(host, None)
                else:
                    active['auths'][host] = original_auth
                changes[key] = base64.b64encode(json.dumps(active).encode()).decode()
            elif key == 'TEORIA_MODEL_ALLOWED_REGISTRIES':
                original = base64.b64decode(old).decode().split(',')
                additions = set(base64.b64decode(applied).decode().split(',')) - set(original)
                active = base64.b64decode(now).decode().split(',')
                changes[key] = base64.b64encode(','.join(item for item in active if item not in additions).encode()).decode()
            else:
                if now != applied:
                    raise RuntimeError('An owned Secret key changed concurrently; automatic recovery stopped')
                changes[key] = old
        if changes:
            self.patch(namespace, 'secret', name, {'metadata': {'resourceVersion': resource['metadata']['resourceVersion']}, 'data': changes})

    def recover(self):
        """Recover only values touched by this transaction; keep the journal on any conflict."""
        import yaml
        if self.journal is None:
            pending = json.loads((self.directory / 'pending.json').read_text())
            release = Path(pending['release']).resolve()
            if release.parent != self.directory.resolve() or not re.fullmatch(r'release_[a-z0-9_]+', release.name):
                raise ValueError('Invalid recovery journal path')
            self.journal = json.loads((release / 'transaction.json').read_text())
        settings, before = self.journal['settings'], self.journal['before']
        touched = set(self.journal['touched'])
        host = settings['harbor_url'].removeprefix('https://')
        failures = []
        def attempt(action):
            try:
                action()
            except Exception:
                failures.append('recovery step failed')
        if 'proxy' in touched:
            def proxy():
                current = self.inspect(PROXY)
                if current and current['Id'] != before['proxy_id']:
                    if current['Config'].get('Labels', {}).get('io.teoria.transaction') != Path(self.journal['release']).name:
                        raise RuntimeError('Proxy ownership changed during recovery')
                    self.run('docker', 'rm', '-f', current['Id'])
                if before['proxy_id']:
                    self.run('docker', 'rename', before['proxy_id'], PROXY) if not current or current['Id'] != before['proxy_id'] else None
                    if before['proxy_running']:
                        self.run('docker', 'start', before['proxy_id'])
            attempt(proxy)
        if 'admin' in touched:
            def admin():
                current = self.get('teoria', 'deployment', 'admin-api')
                env = next(c for c in current['spec']['template']['spec']['containers'] if c['name'] == 'admin-api').get('env', [])
                now = {v['name']: v for v in env if v['name'] in API_ENV}
                expected = dict(zip(API_ENV, (settings['harbor_url'], host)))
                restore = []
                for key in API_ENV:
                    old = before['admin_env'].get(key)
                    if now.get(key) == old:
                        continue
                    if now.get(key, {}).get('value') != expected[key]:
                        raise RuntimeError('Admin endpoint changed concurrently')
                    restore.append({**old, 'value': old.get('value'), 'valueFrom': old.get('valueFrom')} if old else {'name': key, '$patch': 'delete'})
                if restore:
                    self.patch('teoria', 'deployment', 'admin-api', {'metadata': {'resourceVersion': current['metadata']['resourceVersion']},
                        'spec': {'template': {'spec': {'containers': [{'name': 'admin-api', 'env': restore}]}}}}, patch_type='strategic')
            attempt(admin)
        for namespace, name in reversed(SECRET_NAMES):
            if 'secret:' + name in touched:
                attempt(lambda namespace=namespace, name=name: self.restore_secret(namespace, name))
        if 'node' in touched:
            def node():
                config = yaml.safe_load(self.node_file(REGISTRY_FILE) or '') or {}
                tls = config.setdefault('configs', {}).setdefault(host, {}).setdefault('tls', {})
                if tls.get('ca_file') not in (REGISTRY_CA, before['node_ca']):
                    raise RuntimeError('Node Registry CA changed concurrently')
                if before['node_ca'] is None:
                    tls.pop('ca_file', None)
                else:
                    tls['ca_file'] = before['node_ca']
                if not tls:
                    config['configs'][host].pop('tls', None)
                if not config['configs'][host]:
                    config['configs'].pop(host)
                if not config['configs']:
                    config.pop('configs')
                self.node_file(REGISTRY_FILE, yaml.safe_dump(config))
                current = self.node_file(before['host_path'])
                if current != before['host_file']:
                    if current != self.host_configuration(host):
                        raise RuntimeError('Node Registry host file changed concurrently')
                    self.node_file(before['host_path'], before['host_file']) if before['host_file'] is not None else self.node_file(before['host_path'], remove=True)
            attempt(node)
        if 'daemon' in touched:
            def daemon():
                current = self.daemon_ca(host)
                if current != before['daemon_ca']:
                    if current != (self.local / 'harbor.crt').read_text():
                        raise RuntimeError('Docker Registry CA changed concurrently')
                    self.daemon_ca(host, before['daemon_ca']) if before['daemon_ca'] is not None else self.daemon_ca(host, remove=True)
            attempt(daemon)
        if 'helm' in touched:
            def helm():
                latest = int(json.loads(self.run('helm', 'history', 'harbor', '-n', 'harbor', '-o', 'json'))[-1]['revision'])
                if latest == before['helm_revision']:
                    return
                if latest == before.get('helm_rollback_revision'):
                    history = json.loads(self.run('helm', 'history', 'harbor', '-n', 'harbor', '-o', 'json'))
                    values = json.loads(self.run('helm', 'get', 'values', 'harbor', '-n', 'harbor', '--all', '-o', 'json'))
                    if history[-1]['status'] == 'deployed' and values.get('externalURL') == before.get('helm_external_url'):
                        before['helm_revision'] = latest
                        self.save_journal()
                        return
                    raise RuntimeError('The interrupted Harbor rollback needs explicit recovery')
                if latest != before['helm_revision'] + 1:
                    raise RuntimeError('Harbor release changed concurrently; recover it explicitly')
                before['helm_rollback_revision'] = latest + 1
                self.save_journal()
                self.run('helm', 'rollback', 'harbor', str(before['helm_revision']), '-n', 'harbor', '--wait', '--timeout', '15m')
                # Persist the new revision so a retry after a later failure is idempotent.
                before['helm_revision'] = int(json.loads(self.run('helm', 'history', 'harbor', '-n', 'harbor', '-o', 'json'))[-1]['revision'])
                self.save_journal()
            attempt(helm)
        if 'ingress' in touched:
            def ingress():
                current = self.get('harbor', 'ingress', 'harbor-ip-access')
                if current and current['spec'] == before['ingress_spec']:
                    if current['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') != 'teoria-k3d-remote-access':
                        raise RuntimeError('Harbor IP Ingress ownership changed concurrently')
                    if before['ingress']:
                        self.patch('harbor', 'ingress', 'harbor-ip-access', [{'op': 'test', 'path': '/metadata/resourceVersion', 'value': current['metadata']['resourceVersion']}, {'op': 'replace', 'path': '/spec', 'value': before['ingress']['spec']}], patch_type='json')
                    else:
                        self.kubectl('-n', 'harbor', 'delete', 'ingress', 'harbor-ip-access')
                elif current != before['ingress']:
                    raise RuntimeError('Harbor IP Ingress changed concurrently')
            attempt(ingress)
        if 'files' in touched:
            def file(name, content):
                path = Path(name)
                now = base64.b64encode(path.read_bytes()).decode() if path.exists() else None
                if now == content:
                    return
                if path == self.local / 'access.json':
                    active = json.loads(base64.b64decode(now)) if now else {}
                    previous = json.loads(base64.b64decode(content)) if content else {}
                    expected = json.loads(base64.b64decode(before['file_updates'][name]))
                    for key in ('platform_url', 'harbor_url', 'windows_ca_file'):
                        if active.get(key) not in (previous.get(key), expected.get(key)):
                            raise RuntimeError('Access display settings changed concurrently')
                        if key in previous:
                            active[key] = previous[key]
                        else:
                            active.pop(key, None)
                    if active or content is not None:
                        write_private(path, json.dumps(active, indent=2) + '\n')
                    else:
                        path.unlink(missing_ok=True)
                else:
                    if now != before['file_updates'][name]:
                        raise RuntimeError('Access input/receipt changed concurrently; recovery stopped')
                    write_private(path, base64.b64decode(content)) if content is not None else path.unlink(missing_ok=True)
            for name, content in before['files'].items():
                attempt(lambda name=name, content=content: file(name, content))
        if 'admin' in touched:
            attempt(self.rollout)
        if failures:
            raise RuntimeError('Recovery is incomplete; private transaction state was retained')
        self.directory.joinpath('pending.json').unlink(missing_ok=True)
        write_private(Path(self.journal['release']) / 'transaction.json', json.dumps({'settings': settings, 'status': 'recovered'}))
        Path(self.journal['release']).joinpath('harbor_values.json').unlink(missing_ok=True)
        self.journal = None


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--address')
    parser.add_argument('--platform-port', type=int)
    parser.add_argument('--harbor-port', type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='offline plan only; no files, containers or cluster changes')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--verify', action='store_true', help='read-only TLS and API authentication probes')
    mode.add_argument('--recover', action='store_true')
    mode.add_argument('--registry-host', action='store_true', help=argparse.SUPPRESS)
    mode.add_argument('--restore-node', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    access = DevelopmentAccess(args.root)
    try:
        if args.registry_host:
            print(deployment_registry(args.root))
            return
        if args.recover or args.restore_node or args.apply:
            # The same lock serializes the ordinary platform deployment and address changes.
            with (Path.home() / '.teoria-deploy.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if args.recover:
                    access.recover()
                    print('Previous access configuration recovered')
                    return
                if args.restore_node:
                    settings = json.loads((access.directory / 'config.json').read_text())
                    if (access.directory / 'pending.json').exists():
                        raise ValueError('Recover the pending remote access change before restoring the node')
                    access.restore_node(external_addresses(settings['address'], settings['platform_port'], settings['harbor_port']))
                    return
                settings = read_configuration(args.root, args.config, address=args.address,
                                              platform_port=args.platform_port, harbor_port=args.harbor_port)
                if settings is None:
                    raise ValueError('Configure remote_access.env or --address')
                access.expose(settings)
        else:
            settings = read_configuration(args.root, args.config, address=args.address,
                                          platform_port=args.platform_port, harbor_port=args.harbor_port)
            if settings is None:
                raise ValueError('Configure remote_access.env or --address')
            if args.verify:
                access.verify(settings)
            else:
                receipt = access.directory / 'config.json'
                previous = json.loads(receipt.read_text()) if receipt.exists() else None
                applied = {key: previous.get(key) for key in settings} if previous else None
                print(json.dumps({'applied': applied, 'desired': settings, 'pending_recovery': (access.directory / 'pending.json').exists(),
                    'changes': ['proxy TLS/ports', 'Harbor externalURL/IP Ingress', 'Registry trust and selected Secret keys',
                                'Admin Registry endpoint and worker restart'],
                    'apply': 'Use --apply while the existing cluster is running; connection interruption is possible'}, indent=2))
                return
        print(json.dumps(settings, indent=2))
    except Exception as exc:
        # Never print kubectl/helm output or a credential-bearing exception body.
        reason = str(exc) if type(exc) in {ValueError, RuntimeError} else type(exc).__name__
        parser.exit(1, f'Remote access operation failed: {reason}. Check private recovery logs if present.\n')


if __name__ == '__main__':
    main()
