"""
Module: tests.test_error_detail

Unit tests for how the MCP server turns the backend's error body into the sentence an assistant reads: a plain
detail passes through, and a structured detail (`{"code", "message"}`, such as `uploads_disabled`) reads as its
message followed by its code. No backend is needed.
"""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("fastmcp")

import server  # noqa: E402 - needs fastmcp, checked above


def _response(body: object) -> httpx.Response:
    return httpx.Response(403, json=body)


def test_plain_detail_is_unchanged():
    assert server._detail(_response({"detail": "Not allowed."})) == "Not allowed."


def test_structured_detail_reads_message_then_code():
    body = {"detail": {"code": "uploads_disabled", "message": "File uploads are disabled on this deployment."}}
    assert server._detail(_response(body)) == "File uploads are disabled on this deployment. (uploads_disabled)"


def test_structured_detail_without_a_message_falls_back_to_the_raw_body():
    assert "uploads_disabled" in server._detail(_response({"detail": {"code": "uploads_disabled"}}))
