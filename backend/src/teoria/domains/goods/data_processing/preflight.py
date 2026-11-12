"""Read-only checks before activating specification workflows in a deployment.

Run in the configured Admin container with `python -m ...preflight`.
This does not approve data, create buckets, upload files or start workflows.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import quote

import httpx

from teoria.domains.goods.authoring_client import GoodsAuthoringClient
from teoria.domains.goods.data_processing.storage.artifact_store import S3ArtifactStore
from teoria.integrations.s3 import signed_headers


async def verify(*, authoring_transport=None, storage_transport=None) -> None:
    auth_path = Path(os.environ["TEORIA_CODEX_AUTH_PATH"])
    if not isinstance(json.loads(auth_path.read_text()), dict):
        raise ValueError("configure Codex authentication for this role")
    async with GoodsAuthoringClient(transport=authoring_transport) as api:
        response = await api.http.get("/v1/admin/auth/session")
        response.raise_for_status()
        if response.json().get("actor") != "service:specification-processing":
            raise ValueError("workflow requires its dedicated service credential")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, transport=storage_transport) as client:
        store = S3ArtifactStore(os.environ["TEORIA_SPECIFICATION_ARTIFACT_ROOT"], client)
        url = store.endpoint + "/" + quote(store.bucket, safe="")
        # HEAD bucket requires existing storage and a dedicated bucket-access policy.
        headers = signed_headers("HEAD", url, b"", access_key=store.access_key,
                                 secret_key=store.secret_key, region=store.region)
        response = await client.head(url, headers=headers)
        response.raise_for_status()


def main() -> None:
    try:
        asyncio.run(verify())
    except (KeyError, ValueError, OSError, httpx.HTTPError):
        raise SystemExit("Specification preflight failed: check service identity, Codex role authentication and S3 bucket access; credentials are not logged") from None
    print("Specification service identity, Codex credential file and S3 access verified; no workflow was executed")


if __name__ == "__main__":
    main()
