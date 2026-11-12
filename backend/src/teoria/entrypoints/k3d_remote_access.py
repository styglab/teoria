"""Configure development IP access without recreating the k3d cluster or its data."""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import subprocess

import yaml


def external_addresses(address, platform_port=18443, harbor_port=18444):
    value = ipaddress.IPv4Address(address)
    if value.is_unspecified or value.is_multicast or value.is_loopback:
        raise ValueError("Use the Docker host's reachable IPv4 address")
    if platform_port == harbor_port or any(not 1024 <= p <= 65535 for p in (platform_port, harbor_port)):
        raise ValueError('Use two different unprivileged HTTPS ports')
    return {'address': str(value), 'platform_port': platform_port, 'harbor_port': harbor_port,
            'platform_url': f'https://{value}:{platform_port}', 'harbor_url': f'https://{value}:{harbor_port}'}


def nginx_configuration(settings):
    return '''pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events {}
http {
    access_log /dev/stdout;
    resolver 127.0.0.11 valid=10s;
    client_body_temp_path /tmp/client_body;
    proxy_temp_path /tmp/proxy;
    fastcgi_temp_path /tmp/fastcgi;
    uwsgi_temp_path /tmp/uwsgi;
    scgi_temp_path /tmp/scgi;
    map $http_upgrade $connection_upgrade { default upgrade; "" close; }
    ssl_certificate /certs/server.crt;
    ssl_certificate_key /certs/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    proxy_ssl_server_name on;
    proxy_ssl_verify on;
    proxy_ssl_trusted_certificate /certs/upstream_ca.crt;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    client_body_timeout 3600s;
    send_timeout 3600s;
    proxy_http_version 1.1;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    server {
        listen PLATFORM ssl;
        server_name ADDRESS;
        client_max_body_size 40m;
        set $cluster k3d-teoria-serverlb:443;
        proxy_ssl_name teoria.localhost;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host teoria.localhost;
        location / { proxy_pass https://$cluster; }
    }
    server {
        listen HARBOR ssl;
        server_name ADDRESS;
        client_max_body_size 0;
        proxy_request_buffering off;
        proxy_buffering off;
        set $cluster k3d-teoria-serverlb:443;
        proxy_ssl_name harbor.teoria.localhost;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $http_host;
        location / { proxy_pass https://$cluster; }
    }
}
'''.replace('PLATFORM', str(settings['platform_port'])).replace('HARBOR', str(settings['harbor_port'])).replace('ADDRESS', settings['address'])


class DevelopmentAccess:
    def __init__(self, root):
        self.root = root
        self.local = root / 'deploy/kubernetes/k3d/.local'
        self.directory = self.local / 'remote_access'
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.environment = {**os.environ, 'KUBECONFIG': str(self.local / 'kubeconfig')}

    def run(self, *args, body=None):
        result = subprocess.run(list(map(str, args)), input=body, text=True, capture_output=True,
                                env=self.environment)
        if result.returncode:
            # Some tools include credentials in error output; keep diagnostics private.
            path = self.directory / 'last_error.log'
            path.write_text(result.stderr + result.stdout)
            path.chmod(0o600)
            raise RuntimeError(f'{args[0]} {args[1]} failed; see {path}')
        return result.stdout

    def kubectl(self, *args, body=None):
        return self.run('kubectl', *args, body=body)

    def apply(self, item):
        self.kubectl('apply', '-f', '-', body=json.dumps(item))

    def restore_node(self, settings):
        # Keep K3s's source configuration as well as containerd's live hosts file.
        host = settings['harbor_url'].removeprefix('https://')
        source = '/etc/rancher/k3s/registries.yaml'
        config = yaml.safe_load(self.run('docker', 'exec', 'k3d-teoria-server-0', 'cat', source)) or {}
        config.setdefault('configs', {})[host] = {'tls': {'ca_file': '/etc/rancher/k3s/harbor_ca.crt'}}
        self.run('docker', 'exec', '-i', 'k3d-teoria-server-0', 'sh', '-c', 'cat > ' + source,
                 body=yaml.safe_dump(config))
        directory = '/var/lib/rancher/k3s/agent/etc/containerd/certs.d/' + host
        self.run('docker', 'exec', 'k3d-teoria-server-0', 'mkdir', '-p', directory)
        content = f'server = "https://{host}/v2"\ncapabilities = ["pull", "resolve"]\nca = ["/etc/rancher/k3s/harbor_ca.crt"]\n[host]\n'
        self.run('docker', 'exec', '-i', 'k3d-teoria-server-0', 'sh', '-c', 'cat > ' + directory + '/hosts.toml', body=content)

    def expose(self, settings):
        if self.kubectl('config', 'current-context').strip() != 'k3d-teoria':
            raise ValueError('Only the dedicated k3d-teoria context is supported')
        tls = self.directory / 'tls'
        tls.mkdir(mode=0o755, exist_ok=True)
        tls.chmod(0o755)
        (tls / 'upstream_ca.crt').write_bytes((self.local / 'harbor.crt').read_bytes() + (self.local / 'tls.crt').read_bytes())
        (tls / 'ca.crt').write_bytes((self.local / 'harbor.crt').read_bytes())
        certificate = tls / 'server.crt'
        key = tls / 'server.key'
        config_path = self.directory / 'config.json'
        previous = json.loads(config_path.read_text()) if config_path.exists() else None
        if previous != settings or not certificate.exists():
            self.run('openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', key,
                     '-out', tls / 'server.csr', '-subj', '/CN=' + settings['address'])
            (tls / 'extensions.cnf').write_text('basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:' + settings['address'] + '\n')
            self.run('openssl', 'x509', '-req', '-in', tls / 'server.csr', '-CA', self.local / 'harbor.crt',
                     '-CAkey', self.local / 'harbor.key', '-set_serial', '0x' + os.urandom(16).hex(),
                     '-out', certificate, '-days', '365', '-sha256', '-extfile', tls / 'extensions.cnf')
        for path in tls.iterdir():
            path.chmod(0o644)
        key.chmod(0o600)
        owner = self.root.stat()
        if key.stat().st_uid != owner.st_uid:
            os.chown(key, owner.st_uid, owner.st_gid)
        proxy = self.directory / 'nginx.conf'
        proxy.write_text(nginx_configuration(settings))
        proxy.chmod(0o644)
        # Docker bind sources belong to the daemon host, not necessarily this devcontainer.
        host_root = self.root
        hostname = os.getenv('HOSTNAME', '')
        inspected = subprocess.run(['docker', 'inspect', hostname, '--format', '{{json .Mounts}}'], capture_output=True, text=True)
        if inspected.returncode == 0:
            for mount in json.loads(inspected.stdout):
                if mount['Destination'] == str(self.root):
                    host_root = Path(mount['Source'])
        host_directory = host_root / self.directory.relative_to(self.root)
        volumes = ['-v', str(host_directory / 'nginx.conf') + ':/etc/nginx/nginx.conf:ro',
                   '-v', str(host_directory / 'tls') + ':/certs:ro']
        image = 'nginx:1.27-alpine'
        security = ['--user', f'{owner.st_uid}:{owner.st_gid}', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--tmpfs', f'/tmp:rw,noexec,nosuid,size=64m,uid={owner.st_uid},gid={owner.st_gid}']
        self.run('docker', 'run', '--rm', '--network', 'k3d-teoria', *security, *volumes, '--entrypoint', 'nginx', image, '-t')
        name = 'teoria-k3d-remote-access'
        inspected = subprocess.run(['docker', 'inspect', name, '--format', '{{index .Config.Labels "io.teoria.role"}}'], capture_output=True, text=True)
        if inspected.returncode == 0:
            if inspected.stdout.strip() != 'k3d-remote-access':
                raise ValueError('Existing container is not owned by this access profile')
            self.run('docker', 'rm', '-f', name)
        self.run('docker', 'run', '-d', '--name', name, '--restart', 'unless-stopped', '--network', 'k3d-teoria',
                 '--label', 'io.teoria.role=k3d-remote-access', *security, *volumes,
                 '-p', f"{settings['address']}:{settings['platform_port']}:{settings['platform_port']}",
                 '-p', f"{settings['address']}:{settings['harbor_port']}:{settings['harbor_port']}",
                 '--entrypoint', 'nginx', image, '-g', 'daemon off;')
        ingress = json.loads(self.kubectl('-n', 'harbor', 'get', 'ingress', 'harbor-ingress', '-o', 'json'))
        # Preserve the real IP Host for Harbor's browser CSRF checks. Named local
        # platform routes still take precedence over this development default.
        self.apply({'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress',
                    'metadata': {'namespace': 'harbor', 'name': 'harbor-ip-access',
                                 'labels': {'app.kubernetes.io/managed-by': 'teoria-k3d-remote-access'}},
                    'spec': {'ingressClassName': ingress['spec']['ingressClassName'],
                             'rules': [{'http': ingress['spec']['rules'][0]['http']}]}})
        backup = self.directory / 'harbor_previous_values.json'
        values = json.loads(self.run('helm', 'get', 'values', 'harbor', '-n', 'harbor', '-o', 'json'))
        if not backup.exists():
            backup.write_text(json.dumps(values))
            backup.chmod(0o600)
        values['externalURL'] = settings['harbor_url']
        values_path = self.directory / 'harbor_values.json'
        values_path.write_text(json.dumps(values))
        values_path.chmod(0o600)
        self.run('bash', self.root / 'deploy/kubernetes/harbor/deploy.sh', '--overlay', 'k3d',
                 '--chart', self.local / 'harbor-1.19.4.tgz', '--values', values_path)
        # Keep the local operator input consistent with the installed release.
        (self.local / 'harbor_values.yaml').write_text(json.dumps(values))
        self.restore_node(settings)
        host = settings['harbor_url'].removeprefix('https://')
        self.run('docker', 'run', '--rm',
                 '--mount', 'type=bind,source=' + str(host_root / self.local.relative_to(self.root) / 'harbor.crt') + ',target=/source,readonly',
                 '--mount', 'type=bind,source=/etc/docker/certs.d,target=/certs',
                 'busybox:1.36', 'sh', '-ec',
                 'mkdir -p "/certs/$1"; cp /source "/certs/$1/ca.crt"', 'sh', host)
        for namespace, name in [('teoria', 'teoria-secrets'), ('teoria', 'model-control'),
                                ('teoria', 'teoria-registry'), ('teoria-models', 'model-images')]:
            secret = json.loads(self.kubectl('-n', namespace, 'get', 'secret', name, '-o', 'json'))
            data = {k: base64.b64decode(v).decode() for k, v in secret['data'].items()}
            if name == 'teoria-secrets':
                data.update(TEORIA_IMAGE_REGISTRY_URL=settings['harbor_url'], TEORIA_IMAGE_REGISTRY_PUBLIC_HOST=host)
            elif name == 'model-control':
                allowed = data['TEORIA_MODEL_ALLOWED_REGISTRIES'].split(',')
                data['TEORIA_MODEL_ALLOWED_REGISTRIES'] = ','.join(dict.fromkeys([*allowed, host]))
            else:
                dockerconfig = json.loads(data['.dockerconfigjson'])
                dockerconfig['auths'][host] = dockerconfig['auths']['harbor.teoria.localhost']
                data['.dockerconfigjson'] = json.dumps(dockerconfig)
            self.kubectl('-n', namespace, 'patch', 'secret', name, '--type', 'merge', '--patch-file', '/dev/stdin',
                         body=json.dumps({'stringData': data}))
        self.kubectl('-n', 'teoria', 'set', 'env', 'deployment/admin-api',
                     'TEORIA_IMAGE_REGISTRY_URL=' + settings['harbor_url'],
                     'TEORIA_IMAGE_REGISTRY_PUBLIC_HOST=' + host)
        for name in ('admin-api', 'model-training-worker'):
            if name == 'model-training-worker':
                self.kubectl('-n', 'teoria', 'rollout', 'restart', 'deployment/' + name)
            self.kubectl('-n', 'teoria', 'rollout', 'status', 'deployment/' + name, '--timeout=180s')
        config_path.write_text(json.dumps(settings, indent=2) + '\n')
        access_path = self.local / 'access.json'
        access = json.loads(access_path.read_text())
        access.update(harbor_url=settings['harbor_url'], platform_url=settings['platform_url'],
                      windows_ca_file=str(tls / 'ca.crt'))
        access_path.write_text(json.dumps(access, indent=2) + '\n')
        for path in [self.directory, *self.directory.rglob('*')]:
            if not path.is_symlink() and path.stat().st_uid != owner.st_uid:
                os.chown(path, owner.st_uid, owner.st_gid)
        print(json.dumps(settings, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--address')
    parser.add_argument('--platform-port', type=int, default=18443)
    parser.add_argument('--harbor-port', type=int, default=18444)
    parser.add_argument('--restore-node', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    controller = DevelopmentAccess(args.root)
    if args.restore_node:
        saved = json.loads((controller.directory / 'config.json').read_text())
        settings = external_addresses(saved['address'], saved['platform_port'], saved['harbor_port'])
        controller.restore_node(settings)
    else:
        if not args.address:
            parser.error('--address is required')
        controller.expose(external_addresses(args.address, args.platform_port, args.harbor_port))


if __name__ == '__main__':
    main()
