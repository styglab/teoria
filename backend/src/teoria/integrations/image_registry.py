"""Native async reads of Harbor projects and Distribution images.

Registry credentials and storage stay outside Teoria's application database.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit
from urllib.request import parse_http_list, parse_keqv_list

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
        provider: str = "distribution",
        project: str = "models",
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
        if provider not in {"distribution", "harbor"}:
            raise ValueError("Unsupported image registry provider")
        if not re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", project):
            raise ValueError("Invalid Harbor project")
        self.provider = provider
        self.project = project
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
        challenge = response.headers.get("www-authenticate", "")
        if response.status_code == 401 and challenge.lower().startswith("bearer "):
            repository = re.fullmatch(r"/v2/(.+)/(?:tags/list|manifests/[^/]+)", path)
            if repository is None:
                response.raise_for_status()
            fields = parse_keqv_list(parse_http_list(challenge[7:]))
            realm = urlsplit(fields.get("realm", ""))
            origin = urlsplit(self.url)
            # Credentials may only go to the configured Registry's token service.
            if ((realm.scheme, realm.netloc) != (origin.scheme, origin.netloc)
                    or realm.username or realm.password or realm.query or realm.fragment
                    or realm.path != "/service/token"):
                raise ValueError("Untrusted registry token endpoint")
            token_response = await self.client.get(
                fields["realm"], auth=self.auth,
                params={"service": fields.get("service", "harbor-registry"),
                        "scope": f"repository:{repository[1]}:pull"},
                follow_redirects=False, timeout=20,
            )
            token_response.raise_for_status()
            document = token_response.json()
            if not isinstance(document, dict):
                raise ValueError("Invalid registry token response")
            token = document.get("token") or document.get("access_token")
            if not isinstance(token, str) or not token or len(token) > 32768:
                raise ValueError("Invalid registry token response")
            response = await self.client.get(
                self.url + path, auth=None, params=params,
                headers={**(headers or {}), "Authorization": "Bearer " + token},
                follow_redirects=False, timeout=20,
            )
        response.raise_for_status()
        return response

    async def repositories(self, *, after: str = "", limit: int = 25) -> dict:
        if self.provider == "harbor":
            return await self._harbor_repositories(after=after, limit=limit)
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

    async def _harbor_repositories(self, *, after: str, limit: int) -> dict:
        # Harbor's project API works with a project-scoped reader, unlike _catalog.
        if after and not re.fullmatch(r"[1-9][0-9]{0,8}", after):
            raise ValueError("Invalid Harbor page")
        page = int(after or "1")
        response = await self._get(
            f"/api/v2.0/projects/{self.project}/repositories",
            params={"page": page, "page_size": limit, "sort": "name"},
        )
        document = response.json()
        if not isinstance(document, list):
            raise ValueError("Invalid Harbor repositories")
        names = []
        for item in document:
            name = item.get("name") if isinstance(item, dict) else None
            if (not isinstance(name, str) or len(name) > 255
                    or not re.fullmatch(REPOSITORY, name)
                    or not name.startswith(self.project + "/")):
                raise ValueError("Invalid Harbor repository")
            names.append(name)
        total = response.headers.get("x-total-count")
        has_more = page * limit < int(total) if total is not None else len(names) == limit
        return {"items": names, "next": str(page + 1) if has_more and names else None}

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
