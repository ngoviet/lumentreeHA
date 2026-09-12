"""Contract tests for core/api_client.py's response and header handling.

Two vendor-API misreadings were corrected on this branch and are pinning here:

1. ``returnValue: 998`` means "endpoint does not exist" -- a catch-all 404 --
   and must surface as a plain :class:`ApiException`, *not* as an auth failure.
   Only ``203`` (and HTTP 401/403) mean the token was rejected.
2. Requests authenticate with the ``Authorization`` header, not a ``token``
   header.

Both behaviours are absent from the rest of the suite, so a regression in
either would ship unnoticed.  The client is driven through its real
constructor and its real ``_request`` path against a stub aiohttp session that
records the wire traffic, so the assertions are about what the client does to
a server, not about how its source reads.
"""

from __future__ import annotations

import asyncio

import pytest
from custom_components.lumentree.core.exceptions import ApiException, AuthException


class _StubResponse:
    """The slice of ``aiohttp.ClientResponse`` that ``_request`` touches."""

    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._payload = payload
        self.ok = 200 <= status < 300

    async def text(self) -> str:
        return str(self._payload)

    async def json(self, content_type: str | None = None) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise AssertionError(f"stub raise_for_status on {self.status}")


class _StubRequest:
    """Async context manager mirroring ``session.request(...)``."""

    def __init__(self, response: _StubResponse, recorder: list, url: str, headers: dict) -> None:
        self._response = response
        self._recorder = recorder
        self._url = url
        self._headers = headers

    async def __aenter__(self) -> _StubResponse:
        # Record one hit per attempt so retry behaviour is observable.
        self._recorder.append({"url": self._url, "headers": dict(self._headers)})
        return self._response

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _StubSession:
    """Minimal stand-in for ``aiohttp.ClientSession``."""

    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self.payload = payload
        self.calls: list[dict] = []

    def request(self, method: str, url: str, **kwargs):
        return _StubRequest(
            _StubResponse(self.status, self.payload), self.calls, url, kwargs.get("headers", {})
        )


@pytest.fixture
def make_client(lumentree_api_client):
    """Build a real API client whose ``session`` is a recording stub.

    Returns ``(client, session)``; ``session.calls`` holds one entry per wire
    request the client made.
    """

    def _make(return_value: int, msg: str = "stub", status: int = 200, token: str | None = "abc"):
        session = _StubSession(status, {"returnValue": return_value, "msg": msg})
        client = lumentree_api_client.LumentreeHttpApiClient(session=session)
        if token is not None:
            client.set_token(token)
        return client, session

    return _make


def test_return_value_998_is_an_api_error_not_an_auth_failure(make_client) -> None:
    """998 is the vendor's catch-all 404, so it must not trigger re-auth.

    A regression that treated 998 as an auth failure would send the
    integration into a token-refresh loop against a nonexistent endpoint.
    """
    client, session = make_client(998, msg="您访问对页面不存在")

    with pytest.raises(ApiException) as exc_info:
        asyncio.run(client._request("GET", "/lesvr/getYearData", params={}, requires_auth=True))

    assert not isinstance(exc_info.value, AuthException), (
        "998 must not be classified as an authentication failure"
    )
    assert "998" in str(exc_info.value), f"the return code should be reported: {exc_info.value!r}"


def test_return_value_998_is_not_retried(make_client) -> None:
    """A nonexistent endpoint will never start existing -- one attempt only."""
    client, session = make_client(998, msg="您访问对页面不存在")

    with pytest.raises(ApiException):
        asyncio.run(client._request("GET", "/lesvr/getYearData", params={}, requires_auth=True))

    assert len(session.calls) == 1, f"998 was retried {len(session.calls)} times"


def test_return_value_203_is_still_an_auth_failure(make_client) -> None:
    """The 203 control: 998 is not merely swallowed by a blanket error path.

    If 998 stopped raising AuthException because *everything* stopped raising
    it, this test fails and the correction has been over-applied.
    """
    client, _session = make_client(203, msg="no permission")

    with pytest.raises(AuthException):
        asyncio.run(client._request("GET", "/lesvr/getYearData", params={}, requires_auth=True))


def test_requests_authenticate_with_the_authorization_header(make_client) -> None:
    """The vendor expects ``Authorization: <token>``, not a ``token`` header."""
    client, session = make_client(1, status=200, token="test-token-abc")

    result = asyncio.run(
        client._request("GET", "/lesvr/getYearData", params={}, requires_auth=True)
    )

    assert result["returnValue"] == 1
    assert len(session.calls) == 1
    sent = session.calls[0]["headers"]
    assert sent.get("Authorization") == "test-token-abc", f"headers sent: {sent!r}"
    assert "token" not in sent, f"a legacy 'token' header was sent: {sent!r}"


def test_a_request_without_a_token_is_refused_before_hitting_the_wire(make_client) -> None:
    """``requires_auth`` requests must not be sent unauthenticated."""
    client, session = make_client(1, token=None)

    with pytest.raises(AuthException):
        asyncio.run(client._request("GET", "/lesvr/getYearData", params={}, requires_auth=True))

    assert session.calls == [], "an unauthenticated request reached the wire"
