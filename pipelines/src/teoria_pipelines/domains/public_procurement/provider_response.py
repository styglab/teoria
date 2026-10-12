from __future__ import annotations

from typing import Any


class ConnectorResponseError(RuntimeError):
    pass


def _resolve(body: Any, record_path: str) -> Any:
    if record_path == ".":
        return body
    current = body
    for raw_segment in record_path.split("."):
        is_array = raw_segment.endswith("[]")
        segment = raw_segment[:-2] if is_array else raw_segment
        current = current[segment]
        if is_array and not isinstance(current, list):
            raise ConnectorResponseError(f"'{segment}' must be an array")
    return current


def _provider_error(body: Any) -> tuple[str | None, str | None] | None:
    if not isinstance(body, dict):
        return None
    envelope = body.get("OpenAPI_ServiceResponse", body)
    if isinstance(envelope, dict):
        header = envelope.get("cmmMsgHeader")
        if isinstance(header, dict):
            return (
                _first_text(header, "returnReasonCode", "resultCode"),
                _first_text(header, "returnAuthMsg", "errMsg", "resultMsg"),
            )
        response = envelope.get("response")
        if isinstance(response, dict) and isinstance(response.get("header"), dict):
            response_header = response["header"]
            code = _first_text(response_header, "resultCode")
            if code and code not in {"00", "0", "NORMAL_SERVICE"}:
                return code, _first_text(response_header, "resultMsg")
        for key, value in envelope.items():
            if not str(key).lower().endswith("responseerror") or not isinstance(value, dict):
                continue
            error_header = value.get("header")
            if isinstance(error_header, dict):
                return (
                    _first_text(error_header, "resultCode", "returnReasonCode"),
                    _first_text(error_header, "resultMsg", "returnAuthMsg", "errMsg"),
                )
    return None


def _first_text(values: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()[:300]
    return None
