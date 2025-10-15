"""Tests for UI diagnostics helpers."""

from __future__ import annotations

from requests import HTTPError, Response

from ui.utils import diagnostics


def _make_http_error(status: int) -> HTTPError:
    response = Response()
    response.status_code = status
    response.url = "http://example.test"
    return HTTPError(f"{status} error", response=response)


def test_safe_call_marks_404_as_skipped() -> None:
    """A 404 response should be treated as an optional capability."""

    def _call() -> None:
        raise _make_http_error(404)

    status, _, payload, message = diagnostics._safe_call(_call)

    assert status == "skipped"
    assert payload is None
    assert "404" in message


def test_safe_call_other_http_errors_fail() -> None:
    """Non-404 HTTP errors continue to be surfaced as failures."""

    def _call() -> None:
        raise _make_http_error(500)

    status, _, payload, message = diagnostics._safe_call(_call)

    assert status == "fail"
    assert payload is None
    assert message.startswith("HTTPError:")
