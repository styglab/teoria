"""HTTP client boundary for Runtime consumers; MCP protocol lives in entrypoints."""

from teoria.integrations.runtime_http.runtime_client import (
    RuntimeAPIClient,
    RuntimeAPIError,
)

__all__ = ["RuntimeAPIClient", "RuntimeAPIError"]
