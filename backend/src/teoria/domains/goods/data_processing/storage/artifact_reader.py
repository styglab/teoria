"""Read trusted processing artifacts with size and checksum validation."""

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
import httpx
from teoria.domains.goods.data_processing.storage.artifact_store import (
    artifact_store,
    object_key,
)


class ArtifactReadError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def verified_artifact(
    reference: dict,
    root: Path,
    object_root: str | None = None,
    *,
    limit: int = 5 * 1024 * 1024,
) -> dict:
    if reference["size_bytes"] > limit:
        raise ArtifactReadError(413, "artifact_preview_too_large")
    uri = reference["uri"]
    parsed = urlsplit(uri)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path)).resolve()
        if parsed.netloc not in {"", "localhost"} or not path.is_relative_to(
            root.resolve()
        ):
            raise ArtifactReadError(404, "artifact_not_available")
    try:
        if parsed.scheme == "s3":
            trusted = urlsplit(object_root or "")
            prefix = trusted.path.strip("/")
            key = parsed.path.lstrip("/")
            if (
                trusted.scheme != "s3"
                or trusted.netloc != parsed.netloc
                or (prefix and not key.startswith(prefix + "/"))
            ):
                raise ArtifactReadError(404, "artifact_not_available")
            relative = key[len(prefix) + 1 :] if prefix else key
            try:
                object_key(relative)
            except ValueError:
                raise ArtifactReadError(404, "artifact_not_available") from None
            async with artifact_store(object_root) as store:
                raw = await store.get(relative, max_bytes=limit)
        elif parsed.scheme == "file":

            def read():
                if not path.is_file():
                    raise FileNotFoundError(path)
                with path.open("rb") as stream:
                    return stream.read(limit + 1)

            raw = await asyncio.to_thread(read)
        else:
            raise ArtifactReadError(422, "unsupported_artifact_storage")
    except FileNotFoundError:
        raise ArtifactReadError(404, "artifact_not_available") from None
    except httpx.HTTPError:
        raise ArtifactReadError(503, "artifact_storage_unavailable") from None
    except ValueError:
        raise ArtifactReadError(413, "artifact_preview_too_large") from None
    if len(raw) > limit:
        raise ArtifactReadError(413, "artifact_preview_too_large")
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ArtifactReadError(409, "artifact_checksum_mismatch")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise ArtifactReadError(422, "artifact_is_not_json") from None
