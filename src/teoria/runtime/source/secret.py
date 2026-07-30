from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class SecretProvider(Protocol):
    def get(self, name: str) -> str | None: ...


class MappingSecretProvider:
    def __init__(self, values: Mapping[str, str]) -> None:
        self.values = values

    def get(self, name: str) -> str | None:
        value = self.values.get(name)
        return value.strip() if value and value.strip() else None
