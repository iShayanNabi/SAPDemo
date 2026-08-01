"""Helpers shared by the end-to-end workflow tests.

Every assertion about the *envelope* lives here rather than in the workflow
tests, so a module that quietly stops returning ``{success, data, error, meta}``
fails ten tests instead of none.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from httpx import Response

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIME = "text/csv"
JSON_MIME = "application/json"
PDF_MIME = "application/pdf"

#: Every value a module may report as the origin of a piece of output.
VALID_ORIGINS = {"rule_based", "ai_generated", "mock_ai", "forecast", "demo_data"}

#: Every severity value the lab publishes, weakest first.
SEVERITY_ORDER = ("low", "medium", "high", "critical")


def envelope(response: Response, *, expected_status: int = 200) -> dict[str, Any]:
    """Assert the shared response envelope and return the whole body.

    The checks here are the contract a future website depends on: one status
    code, one shape, one place to look for data and one place to look for an
    error - never both at once.
    """
    assert response.status_code == expected_status, response.text
    body = response.json()

    assert set(body) == {"success", "data", "error", "meta"}, (
        f"{response.request.url} returned keys {sorted(body)}"
    )
    assert isinstance(body["success"], bool)
    assert body["success"] is (expected_status < 400)

    if body["success"]:
        assert body["error"] is None, "a successful response must not carry an error"
    else:
        assert body["data"] is None, "a failed response must not carry data"
        assert set(body["error"]) == {"code", "message", "details"}
        assert body["error"]["code"] and body["error"]["message"]

    meta = body["meta"]
    assert meta["api_version"] == "v1"
    # The timestamp must be parseable and timezone aware: a website that renders
    # "2 minutes ago" cannot do it from a naive local time.
    stamp = datetime.fromisoformat(meta["timestamp"])
    assert stamp.tzinfo is not None, f"meta.timestamp is not timezone aware: {meta['timestamp']}"
    return body


def ok(response: Response, *, expected_status: int = 200) -> Any:
    """Assert a successful envelope and return its ``data`` block."""
    return envelope(response, expected_status=expected_status)["data"]


def failure(response: Response, *, expected_status: int) -> dict[str, Any]:
    """Assert an error envelope and return its ``error`` block."""
    return envelope(response, expected_status=expected_status)["error"]


def download(response: Response, *, expect_extension: str) -> bytes:
    """Assert a binary download response and return its bytes.

    Exports deliberately do *not* use the JSON envelope - they return the file
    itself so a browser can stream it straight to disk - so they get their own
    contract: a real payload, a media type and a filename to save it under.
    """
    assert response.status_code == 200, response.text
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition, f"missing attachment disposition: {disposition!r}"
    assert f".{expect_extension}" in disposition, (
        f"filename in {disposition!r} does not end with .{expect_extension}"
    )
    assert response.headers.get("content-type")
    content = response.content
    assert content, "the export was empty"
    return content


def upload(client, path_or_bytes, url: str, *, filename: str, mime: str = CSV_MIME) -> Any:
    """POST a file to an upload endpoint and return the ``data`` block."""
    content = (
        path_or_bytes.read_bytes() if hasattr(path_or_bytes, "read_bytes") else path_or_bytes
    )
    return ok(client.post(url, files={"file": (filename, content, mime)}))


def assert_pagination(block: dict[str, Any], *, items_key: str) -> None:
    """Assert the shared pagination contract on a list payload."""
    for key in ("total", "limit", "offset"):
        assert key in block, f"list payload is missing '{key}': {sorted(block)}"
        assert isinstance(block[key], int)
    assert block["total"] >= 0
    assert block["limit"] >= 1
    assert block["offset"] >= 0
    assert len(block[items_key]) <= block["limit"]
    assert len(block[items_key]) <= block["total"]


def assert_identifier(value: Any, *, label: str = "identifier") -> str:
    """Assert a public identifier is a non-empty, URL-safe string."""
    assert isinstance(value, str) and value, f"{label} is not a non-empty string: {value!r}"
    assert " " not in value and "/" not in value, f"{label} is not URL-safe: {value!r}"
    return value


def assert_timestamp(value: Any, *, label: str = "timestamp") -> datetime:
    """Assert a reported timestamp is ISO-8601 and timezone aware."""
    assert isinstance(value, str) and value, f"{label} is not a string: {value!r}"
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, f"{label} is not timezone aware: {value!r}"
    return parsed


@pytest.fixture(scope="session")
def client(api_client):
    """Alias so the workflow tests read as HTTP journeys rather than fixtures."""
    return api_client
