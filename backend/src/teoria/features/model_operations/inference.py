"""A separate, authenticated inference process for the explicitly synthetic demo."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from teoria.features.model_operations.demo_data import FEATURES
from teoria.integrations.mlflow.models import MODEL_NAME, download_version


class PredictionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    tenure_months: int = Field(ge=1, le=72, strict=True)
    monthly_spend: float = Field(ge=0, le=10000)
    login_days_30d: int = Field(ge=0, le=30, strict=True)
    support_tickets_30d: int = Field(ge=0, le=12, strict=True)


def create_inference_app() -> FastAPI:
    token = os.environ["TEORIA_DEMO_INFERENCE_TOKEN"]
    if len(token) < 24:
        raise ValueError("inference token must have at least 24 characters")
    state = {"model": None, "release": None}
    bearer = HTTPBearer(auto_error=False)

    async def authorize(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        if not credentials or not secrets.compare_digest(
            credentials.credentials, token
        ):
            raise HTTPException(401, "inference_authentication_required")

    def load(directory):
        import mlflow.sklearn

        path = Path(os.environ["TEORIA_DEMO_RELEASE_DIRECTORY"]) / "active.json"
        if not path.exists():
            return
        release = json.loads(path.read_text())
        version = release["model_version"]
        if (
            release["model_name"] != MODEL_NAME
            or type(version) is not int
            or version < 1
        ):
            raise ValueError("invalid demo release")
        model_path, checksum = download_version(version, directory)
        if checksum != release["sha256"]:
            raise ValueError("model checksum mismatch")
        state.update(model=mlflow.sklearn.load_model(model_path), release=release)

    @asynccontextmanager
    async def lifespan(app):
        with tempfile.TemporaryDirectory() as directory:
            await asyncio.to_thread(load, directory)
            yield

    app = FastAPI(title="Teoria Synthetic Customer Demo Inference", lifespan=lifespan)
    limit = asyncio.Semaphore(2)

    @app.get("/health")
    async def health():
        if state["model"] is None:
            raise HTTPException(503, "demo_model_not_deployed")
        return {
            "status": "ok",
            "model_version": state["release"]["model_version"],
            "synthetic": True,
        }

    @app.post("/predict", dependencies=[Depends(authorize)])
    async def predict(payload: PredictionInput):
        if state["model"] is None:
            raise HTTPException(503, "demo_model_not_deployed")

        def execute():
            import pandas as pd

            frame = pd.DataFrame(
                [[getattr(payload, name) for name in FEATURES]], columns=FEATURES
            )
            probability = float(state["model"].predict_proba(frame)[0, 1])
            return {
                "churn_probability": probability,
                "predicted_churn": probability >= 0.5,
                "model_version": state["release"]["model_version"],
                "synthetic_demo_only": True,
            }

        async with limit:
            return await asyncio.to_thread(execute)

    return app
