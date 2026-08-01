"""Per-request context shared between the middleware and the response schemas.

One value lives here: the request id. The middleware mints it, stamps it on the
``X-Request-ID`` response header and stores it in a :class:`~contextvars.ContextVar`
so :class:`~app.schemas.common.ResponseMeta` can put the *same* id inside the
envelope without every one of the 130 routes having to pass it down.

Why it matters: a support conversation starts with "it said something wrong at
about half past two". Correlating that to a log line needs an id the user can
read off the response - and it has to be there on the responses that succeeded,
because those are the ones nobody thought to capture a header for.

A ``ContextVar`` (not a global) is what makes this safe: each request - and each
task in an event loop - sees its own value, and a background task started
outside a request simply sees ``None``.
"""

from __future__ import annotations

from contextvars import ContextVar

#: The id of the request currently being handled, or ``None`` outside one.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str | None) -> object:
    """Bind ``request_id`` to the current context and return the reset token."""
    return _request_id.set(request_id)


def get_request_id() -> str | None:
    """Return the current request id, or ``None`` outside a request."""
    return _request_id.get()


def reset_request_id(token: object) -> None:
    """Restore the previous value using the token from :func:`set_request_id`."""
    _request_id.reset(token)  # type: ignore[arg-type]
