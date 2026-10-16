from __future__ import annotations

import json

import httpx

from teoria.intelligence.asset_assessment.prompts import SYSTEM_INSTRUCTION


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
    ):
        self.url, self.model, self.token, self.timeout = url, model, token, timeout
        self.max_tokens = max_tokens

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
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, json=payload, headers=headers)
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
