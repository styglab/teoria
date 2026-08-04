from pathlib import Path

from teoria.registry.diagnostics import Diagnostic


def check_duplicates(
    values: list[str],
    kind: str,
    path: Path,
    diagnostics: list[Diagnostic],
    location: str | None = None,
) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            diagnostics.append(Diagnostic(f"duplicate_{kind}", f"duplicate {kind} '{value}'", path, location=location))
        seen.add(value)
