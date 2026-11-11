"""Native async reads of a configured Docker Distribution registry.

Registry credentials and storage stay outside Teoria's application database.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

import httpx

REPOSITORY = r"[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*)*"
TAG = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json"
)


class ImageRegistryClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        url: str,
        public_host: str = "",
        username: str = "",
        password: str = "",
    ):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Image registry URL must be an HTTP(S) origin without embedded credentials"
            )
        self.client = client
        self.url = url.rstrip("/")
        self.host = public_host or parsed.netloc
        if "/" in self.host or "@" in self.host or not self.host:
            raise ValueError("Image registry public host must be hostname[:port]")
        self.auth = httpx.BasicAuth(username, password) if username else None

    async def _get(
        self, path: str, *, params: dict | None = None, headers: dict | None = None
    ) -> httpx.Response:
        # Never follow a registry-supplied URL with credentials or the Admin bearer token.
        response = await self.client.get(
            self.url + path,
            auth=self.auth,
            headers=headers,
            params=params,
            follow_redirects=False,
            timeout=20,
        )
        response.raise_for_status()
        return response

    async def repositories(self, *, after: str = "", limit: int = 25) -> dict:
        response = await self._get(
            "/v2/_catalog", params={"n": limit, **({"last": after} if after else {})}
        )
        document = response.json()
        if not isinstance(document, dict):
            raise ValueError("Invalid registry catalog")
        names = document.get("repositories") or []
        if not isinstance(names, list) or any(
            not isinstance(n, str) or len(n) > 255 or not re.fullmatch(REPOSITORY, n)
            for n in names
        ):
            raise ValueError("Invalid registry catalog")
        return {
            "items": names,
            "next": names[-1] if names and response.headers.get("link") else None,
        }

    async def tags(self, repository: str, *, after: str = "", limit: int = 25) -> dict:
        if len(repository) > 255 or not re.fullmatch(REPOSITORY, repository):
            raise ValueError("Invalid image repository")
        response = await self._get(
            f"/v2/{repository}/tags/list",
            params={"n": limit, **({"last": after} if after else {})},
        )
        document = response.json()
        if not isinstance(document, dict):
            raise ValueError("Invalid registry tags")
        tags = document.get("tags") or []
        if not isinstance(tags, list) or any(
            not isinstance(t, str) or not re.fullmatch(TAG, t, flags=re.ASCII)
            for t in tags
        ):
            raise ValueError("Invalid registry tags")
        return {
            "items": tags,
            "next": tags[-1] if tags and response.headers.get("link") else None,
        }

    async def manifest(self, repository: str, reference: str) -> dict:
        if len(repository) > 255 or not re.fullmatch(REPOSITORY, repository):
            raise ValueError("Invalid image repository")
        if not (
            re.fullmatch(TAG, reference, flags=re.ASCII)
            or re.fullmatch(r"sha256:[a-f0-9]{64}", reference)
        ):
            raise ValueError("Invalid image reference")
        response = await self._get(
            f"/v2/{repository}/manifests/{reference}",
            headers={"Accept": MANIFEST_TYPES},
        )
        digest = "sha256:" + hashlib.sha256(response.content).hexdigest()
        if reference.startswith("sha256:") and digest != reference:
            raise ValueError("Image manifest checksum mismatch")
        declared = response.headers.get("docker-content-digest")
        if declared and declared != digest:
            raise ValueError("Image manifest checksum mismatch")
        manifest = response.json()
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
            raise ValueError("Invalid image manifest")
        children = manifest.get("manifests", [])
        if not isinstance(children, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("platform", {}), dict)
            for item in children
        ):
            raise ValueError("Invalid image index")
        return {
            "repository": repository,
            "reference": reference,
            "digest": digest,
            "image": f"{self.host}/{repository}@{digest}",
            "media_type": manifest.get(
                "mediaType", response.headers.get("content-type", "")
            ),
            "platforms": [
                item.get("platform", {}) for item in manifest.get("manifests", [])
            ],
        }


def prepare_docker_archive(archive_path, directory, *, max_expanded_bytes=20*1024**3):
    """Read a single docker-save image without extracting archive-controlled paths."""
    import gzip
    import json
    from pathlib import Path, PurePosixPath
    import tarfile

    directory = Path(directory)
    tar_path = directory / "image.tar"
    with open(archive_path, "rb") as source:
        compressed = source.read(2) == b"\x1f\x8b"
        source.seek(0)
        reader = gzip.GzipFile(fileobj=source) if compressed else source
        total = 0
        with tar_path.open("wb") as output:
            while chunk := reader.read(1024*1024):
                total += len(chunk)
                if total > max_expanded_bytes:
                    raise ValueError("expanded_image_archive_too_large")
                output.write(chunk)
    with tarfile.open(tar_path, "r:") as archive:
        entries = {}
        for index, member in enumerate(archive):
            if index >= 50000:
                raise ValueError("image_archive_has_too_many_members")
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name or not (member.isfile() or member.isdir()):
                raise ValueError("unsafe_image_archive_member")
            name = str(path)
            if name in entries:
                raise ValueError("duplicate_image_archive_member")
            entries[name] = member
        def member(name, limit):
            item = entries.get(str(PurePosixPath(name)))
            if not item or not item.isfile() or item.size > limit:
                raise ValueError("invalid_image_archive_reference")
            return archive.extractfile(item)
        with member("manifest.json", 1024*1024) as stream:
            manifests = json.load(stream)
        if not isinstance(manifests, list) or len(manifests) != 1:
            raise ValueError("upload_one_docker_save_image")
        manifest = manifests[0]
        with member(manifest['Config'], 1024*1024) as stream:
            config = stream.read()
        metadata = json.loads(config)
        if metadata.get('os') != 'linux':
            raise ValueError('only_linux_images_supported')
        layers, diff_ids = manifest['Layers'], metadata['rootfs']['diff_ids']
        if len(layers) != len(diff_ids) or len(layers) > 1000:
            raise ValueError('invalid_image_layer_count')
        config_path = directory / 'config.json'
        config_path.write_bytes(config)
        descriptors = [(config_path, {'mediaType':'application/vnd.oci.image.config.v1+json',
            'digest':'sha256:'+hashlib.sha256(config).hexdigest(), 'size':len(config)})]
        expanded_layers = 0
        for index, name in enumerate(layers):
            layer_path = directory / f'layer_{index}.tar.gz'
            digest = hashlib.sha256()
            with member(name, max_expanded_bytes) as stream:
                compressed = stream.read(2) == b'\x1f\x8b'; stream.seek(0)
                reader = gzip.GzipFile(fileobj=stream) if compressed else stream
                with layer_path.open('wb') as output, gzip.GzipFile(fileobj=output,mode='wb',compresslevel=1,mtime=0) as writer:
                    while chunk := reader.read(1024*1024):
                        expanded_layers += len(chunk)
                        if expanded_layers > max_expanded_bytes:
                            raise ValueError('expanded_image_layers_too_large')
                        digest.update(chunk); writer.write(chunk)
            if 'sha256:'+digest.hexdigest() != diff_ids[index]:
                raise ValueError('image_layer_checksum_mismatch')
            digest = hashlib.sha256()
            with layer_path.open('rb') as stream:
                while chunk := stream.read(1024*1024):digest.update(chunk)
            descriptors.append((layer_path, {'mediaType':'application/vnd.oci.image.layer.v1.tar+gzip',
                'digest':'sha256:'+digest.hexdigest(),'size':layer_path.stat().st_size}))
    manifest = {'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json',
                'config':descriptors[0][1],'layers':[d for _,d in descriptors[1:]]}
    return descriptors, json.dumps(manifest,separators=(',',':')).encode()


async def import_docker_archive(registry, archive_path, directory, repository, tag):
    """Publish validated OCI content; the importer never executes the image or uses Docker."""
    import asyncio
    from urllib.parse import urljoin
    if not re.fullmatch(REPOSITORY, repository) or not re.fullmatch(TAG, tag):
        raise ValueError('invalid_image_destination')
    descriptors, manifest = await asyncio.to_thread(prepare_docker_archive, archive_path, directory)
    for path, descriptor in descriptors:
        endpoint = registry.url+'/v2/'+repository+'/blobs/'+descriptor['digest']
        response = await registry.client.head(endpoint, auth=registry.auth, timeout=30)
        if response.status_code == 200:continue
        if response.status_code != 404:response.raise_for_status()
        response = await registry.client.post(registry.url+'/v2/'+repository+'/blobs/uploads/',
                                              auth=registry.auth,content=b'',timeout=30)
        response.raise_for_status()
        upload = urljoin(registry.url+'/',response.headers['Location'])
        target, origin = urlsplit(upload), urlsplit(registry.url)
        if (target.scheme,target.netloc) != (origin.scheme,origin.netloc) or target.username or target.fragment or not target.path.startswith('/v2/'+repository+'/blobs/uploads/'):
            raise ValueError('unsafe_registry_upload_location')
        async def chunks():
            with path.open('rb') as stream:
                while data := await asyncio.to_thread(stream.read,1024*1024):yield data
        response = await registry.client.put(upload+('&' if target.query else '?')+'digest='+descriptor['digest'],
            auth=registry.auth,content=chunks(),headers={'Content-Type':'application/octet-stream','Content-Length':str(descriptor['size'])},timeout=900)
        response.raise_for_status()
        if response.headers.get('Docker-Content-Digest') != descriptor['digest']:
            raise ValueError('registry_blob_checksum_mismatch')
    response = await registry.client.put(registry.url+'/v2/'+repository+'/manifests/'+tag,
        auth=registry.auth,content=manifest,headers={'Content-Type':'application/vnd.oci.image.manifest.v1+json'},timeout=60)
    response.raise_for_status()
    digest = 'sha256:'+hashlib.sha256(manifest).hexdigest()
    if response.headers.get('Docker-Content-Digest') != digest:
        raise ValueError('registry_manifest_checksum_mismatch')
    return await registry.manifest(repository,digest)
