from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from teoria.features.metadata_management.intelligence.asset_assessment.prompts import (
    SYSTEM_INSTRUCTION,
)
from teoria.integrations.codex import CodexRunner


class AssessmentError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def assessment_model_identity(model: str | None) -> str:
    """Persist the execution backend as well as the optional pinned model."""
    return f"codex:{model or 'default'}"


class AssessmentModelClient:
    """Schema-constrained Codex inference; no HTTP gateway or model fallback."""

    def __init__(self, *, model: str | None = None, timeout: int = 180, runner=None):
        self.model = assessment_model_identity(model)
        self.runner = runner or CodexRunner(model=model, concurrency=1, timeout=timeout)

    async def generate(self, *, instruction: str, context: dict, output_type):
        directory = await asyncio.to_thread(
            tempfile.mkdtemp, prefix="teoria_assessment_"
        )
        try:
            result = await self.runner.generate(
                SYSTEM_INSTRUCTION + instruction,
                context,
                Path(directory) / "answer.json",
                output_schema=output_type.model_json_schema(),
            )
            if len(json.dumps(result, ensure_ascii=False).encode()) > 200_000:
                raise AssessmentError("model_response_too_large")
            return output_type.model_validate(result)
        except TimeoutError:
            raise AssessmentError("model_timeout") from None
        except (ValueError, TypeError):
            raise AssessmentError("model_output_invalid") from None
        except (OSError, RuntimeError) as exc:
            if isinstance(exc, AssessmentError):
                raise
            raise AssessmentError("model_unavailable") from None
        finally:
            # Temporary inference output and receipts never become metadata artifacts.
            await asyncio.to_thread(shutil.rmtree, directory)
