from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    path: Path
    severity: Literal["error", "warning"] = "error"
    location: str | None = None

    def __str__(self) -> str:
        location = f" [{self.location}]" if self.location else ""
        return f"{self.severity.upper()} {self.code}: {self.path}{location}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": str(self.path),
            "severity": self.severity,
            "location": self.location,
        }
