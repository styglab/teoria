from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx


RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})


class RuntimeAPIError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        attempts: int,
        retryable: bool,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.attempts = attempts
        self.retryable = retryable
        self.http_status = http_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "attempts": self.attempts,
            "retryable": self.retryable,
            "http_status": self.http_status,
        }


class RuntimeAPIClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 150.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.25,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.client_factory = client_factory
        self.sleep = sleep

    async def list_capabilities(self) -> list[dict[str, Any]]:
        response, attempts = await self._request(
            "GET", "/v1/capabilities", retryable=True
        )
        try:
            capabilities = response.json()["capabilities"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeAPIError(
                "invalid_runtime_response",
                "Runtime API capability discovery response is invalid",
                attempts=attempts,
                retryable=False,
                http_status=response.status_code,
            ) from exc
        if not isinstance(capabilities, list):
            raise RuntimeAPIError(
                "invalid_runtime_response",
                "Runtime API capability discovery response is invalid",
                attempts=attempts,
                retryable=False,
                http_status=response.status_code,
            )
        return capabilities

    async def execute(
        self,
        capability_id: str,
        inputs: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        response, attempts = await self._request(
            "POST",
            f"/v1/capabilities/{capability_id}:execute",
            json={"inputs": inputs, "options": options},
            retryable=False,
        )
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeAPIError(
                "invalid_runtime_response",
                "Runtime API capability response is not valid JSON",
                attempts=attempts,
                retryable=False,
                http_status=response.status_code,
            ) from exc
        if not isinstance(result, dict):
            raise RuntimeAPIError(
                "invalid_runtime_response",
                "Runtime API capability response is not an object",
                attempts=attempts,
                retryable=False,
                http_status=response.status_code,
            )
        return result

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        retryable: bool,
    ) -> tuple[httpx.Response, int]:
        attempts = self.max_attempts if retryable else 1
        for attempt in range(1, attempts + 1):
            try:
                async with self.client_factory(timeout=self.timeout_seconds) as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=self.headers,
                        json=json,
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                can_retry = retryable and attempt < attempts
                if can_retry:
                    await self.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
                    continue
                code = "runtime_timeout" if isinstance(exc, httpx.TimeoutException) else "runtime_network_error"
                raise RuntimeAPIError(
                    code,
                    f"Runtime API request failed: {exc}",
                    attempts=attempt,
                    retryable=retryable,
                ) from exc

            if response.is_success:
                return response, attempt
            status_retryable = response.status_code in RETRYABLE_STATUS_CODES
            if retryable and status_retryable and attempt < attempts:
                delay = self.retry_backoff_seconds * (2 ** (attempt - 1))
                retry_after = response.headers.get("retry-after")
                if retry_after is not None:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass
                await self.sleep(delay)
                continue
            raise self._response_error(
                response,
                attempts=attempt,
                retryable=status_retryable,
            )
        raise AssertionError("Runtime API request loop exited unexpectedly")

    @staticmethod
    def _response_error(
        response: httpx.Response,
        *,
        attempts: int,
        retryable: bool,
    ) -> RuntimeAPIError:
        code = "runtime_api_error"
        message = response.text or f"Runtime API returned HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail", payload)
            if isinstance(detail, dict):
                code = str(detail.get("code", code))
                message = str(detail.get("message", detail.get("reason", message)))
            elif detail is not None:
                message = str(detail)
        return RuntimeAPIError(
            code,
            message,
            attempts=attempts,
            retryable=retryable,
            http_status=response.status_code,
        )
