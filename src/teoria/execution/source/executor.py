import os
from collections.abc import Mapping

import httpx

from teoria.execution.source.models import ExecutionResponse, PreparedRequest


class MissingCredentialError(Exception):
    pass


class SourceExecutor:
    def __init__(self, timeout_seconds: float = 15.0, environment: Mapping[str, str] | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.environment = environment if environment is not None else os.environ

    def credential(self, request: PreparedRequest) -> str | None:
        authentication = request.authentication
        if authentication is None:
            return None
        secret = self.environment.get(authentication.environment_variable)
        if secret:
            return secret
        raise MissingCredentialError(f"missing credential environment variable: {authentication.environment_variable}")

    async def execute(self, request: PreparedRequest) -> ExecutionResponse:
        query = dict(request.query)
        headers = dict(request.headers)
        authentication = request.authentication
        if authentication:
            secret = self.credential(request)
            target = query if authentication.location == "query" else headers
            target[authentication.name] = secret

        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = await client.request(
                request.method,
                request.url,
                params=query,
                headers=headers,
                json=request.body,
            )
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return ExecutionResponse(
            status_code=response.status_code,
            content_type=content_type,
            headers=dict(response.headers),
            body=body,
            elapsed_ms=response.elapsed.total_seconds() * 1000,
        )
