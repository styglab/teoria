from __future__ import annotations

import json

import httpx

from teoria.features.metadata_management.intelligence.asset_assessment.prompts import (
    SYSTEM_INSTRUCTION,
)


class AssessmentError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class AssessmentModelClient:
    """Configured chat-completions gateway. No implicit external destination."""

    def __init__(
        self,
        url: str,
        model: str,
        token: str | None,
        *,
        timeout: float = 90,
        max_tokens: int = 6000,
        client: httpx.AsyncClient | None = None,
    ):
        self.url, self.model, self.token, self.timeout = url, model, token, timeout
        self.max_tokens = max_tokens
        self._http_client = client
        self._owns_http_client = False

    async def __aenter__(self):
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_http_client = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if self._owns_http_client:
            client, self._http_client = self._http_client, None
            self._owns_http_client = False
            await client.aclose()

    async def _post(self, payload: dict, headers: dict):
        if self._http_client is not None:
            return await self._http_client.post(
                self.url, json=payload, headers=headers, timeout=self.timeout
            )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.post(self.url, json=payload, headers=headers)

    async def generate(self, *, instruction: str, context: dict, output_type):
        system = SYSTEM_INSTRUCTION + instruction
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "context": context,
                            "schema": output_type.model_json_schema(),
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = await self._post(payload, headers)
            response.raise_for_status()
            if len(response.content) > 200_000:
                raise AssessmentError("model_response_too_large")
            content = response.json()["choices"][0]["message"]["content"]
            return output_type.model_validate_json(content)
        except httpx.TimeoutException:
            raise AssessmentError("model_timeout") from None
        except httpx.HTTPError:
            raise AssessmentError("model_unavailable") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise AssessmentError("model_output_invalid") from None
