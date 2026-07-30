import os
from collections.abc import Mapping


class EnvironmentSecretProvider:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def get(self, name: str) -> str | None:
        value = self.environment.get(name)
        return value.strip() if value and value.strip() else None
