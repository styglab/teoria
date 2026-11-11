"""Portable, secret-free contracts for externally built model images."""
from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
ModelName = Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{0,199}$")]
Image = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9.-]*(?::[0-9]+)?/[a-z0-9]+(?:[._/-][a-z0-9]+)*@sha256:[a-f0-9]{64}$", max_length=512)]


class Resources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu: float = Field(default=1, gt=0, le=64)
    memory_mib: int = Field(default=1024, ge=128, le=262144)
    gpu: int = Field(default=0, ge=0, le=8)


class ImageExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: Image
    configuration_id: Name | None = None
    configuration_revision: int | None = Field(default=None, ge=1)
    command: list[str] = Field(min_length=1, max_length=64)
    resources: Resources = Field(default_factory=Resources)

    @field_validator("command")
    @classmethod
    def command_is_bounded(cls, value):
        if any(not part or len(part) > 4096 or "\x00" in part for part in value):
            raise ValueError("command contains an invalid argument")
        return value


class TrainingRequest(ImageExecution):
    model_name: ModelName
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_uri: str = Field(min_length=1, max_length=2048)
    output_uri: str = Field(min_length=1, max_length=2048)
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=50)
    timeout_seconds: int = Field(default=3600, ge=1, le=604800)

    @field_validator("input_uri", "output_uri")
    @classmethod
    def immutable_storage_reference(cls, value):
        url = urlsplit(value)
        if url.scheme != "s3" or not url.netloc or not url.path.strip("/") or url.query or url.fragment or url.username:
            raise ValueError("use an s3://bucket/key reference without credentials or query parameters")
        return value

    @field_validator("parameters")
    @classmethod
    def no_credentials(cls, value):
        if any(re.search(r"password|secret|token|credential|api_key", key, re.I) for key in value):
            raise ValueError("credentials belong in operator-managed workload secrets")
        if len(str(value)) > 16000:
            raise ValueError("parameters are too large")
        return value


class ServingRequest(ImageExecution):
    deployment_id: Name
    model_name: ModelName
    model_version: int = Field(ge=1, strict=True)
    model_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    readiness_path: str = Field(default="/health", pattern=r"^/[a-zA-Z0-9/_-]*$", max_length=200)
    readiness_timeout_seconds: int = Field(default=120, ge=1, le=600)
    replicas: int = Field(default=1, ge=1, le=16)


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deployment_id: Name


def validate_execution(kind: str, value: dict) -> dict:
    contract = {"training": TrainingRequest, "serving": ServingRequest, "stop-serving": StopRequest}[kind]
    return contract.model_validate(value).model_dump(mode="json")
