import os
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


class EnvironmentSecretProvider(MappingSecretProvider):
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        super().__init__(environment if environment is not None else os.environ)
