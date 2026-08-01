"""Public demonstration mode.

The lab was written to run on a laptop, where "upload your own spreadsheet" is
the whole point. Putting the same application behind a public hostname inverts
that: the file a stranger uploads is the one thing the operator cannot vouch
for, and the analysis it produces is the one thing they cannot delete on that
stranger's behalf. So demo mode is not a cosmetic banner - it removes the
ingestion path and says so.

Three rules, in the order they matter:

1. **Uploads are refused server-side.** Hiding the Streamlit widget stops an
   honest visitor and nobody else; ``ensure_uploads_allowed`` is called at the
   two choke points every upload passes through, so a route added next year is
   covered without anybody remembering to cover it.
2. **The AI provider is forced to mock.** Not "defaults to" - forced. See
   :meth:`app.core.config.Settings.resolved_ai_provider`.
3. **The data is the bundled fictional data.** There is no other data, which is
   what makes the disclaimer on every page true rather than aspirational.

Nothing here is authentication. It reduces what an anonymous visitor can *do*;
it does not give two visitors separate worlds. That limitation is stated in
:func:`describe_demo_state` so a front end can print it, and in
``docs/DEMO_SECURITY_CHECKLIST.md`` at length.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: The headline every surface shows while demo mode is on. One constant so the
#: Streamlit banner, the API status endpoint and the tests cannot drift apart.
DEMO_BANNER_HEADLINE = "Public Demo — Fictional Data Only"

#: What a visitor must not paste into this application. Written as a list rather
#: than a paragraph because it is rendered as one, and because a person scanning
#: a banner reads four bullets and no paragraphs.
DO_NOT_SUBMIT: tuple[str, ...] = (
    "confidential or commercially sensitive information",
    "personal information about yourself or anyone else",
    "real SAP data, system names, clients or credentials",
    "real supplier, purchase order, invoice or contract data",
    "proprietary company data of any kind",
)

#: The standing statement about what this environment is.
DEMO_DISCLAIMER = (
    "This is a demonstration environment running on fictional data. It is not connected to "
    "any SAP system, no output has been validated in a live SAP environment, and no figure "
    "shown here is a guarantee."
)


class DemoModeError(AppError):
    """The action is disabled because this is a public demonstration.

    403 rather than 404 or 422 on purpose: the endpoint exists, the request was
    well formed, and retrying it unchanged will not help. That is exactly what
    403 means, and it is what lets a client tell "you cannot do this here" apart
    from "you did this wrong".
    """

    code = "demo_mode_restricted"
    http_status = 403


# ---------------------------------------------------------------------------
# Trusted ingestion
# ---------------------------------------------------------------------------
# What the guard actually refuses is a payload that came from a *request*. Two
# things in this project ingest bytes that did not: the seeder, which loads the
# bundled demonstration data by driving the real API, and the guided
# demonstration loader, which hands a module a file read from ``data/sample/``.
# Both are the repository's own committed data, and both would otherwise be
# refused by the mode that exists to protect against strangers.
#
# So the block is named for the property that matters - these bytes are trusted
# - rather than for one of its two callers. Getting this wrong is not
# hypothetical: the first version guarded on "seeding", and public demo mode
# then blocked its own Load Demo button.
#
# It is a module-level flag rather than a ContextVar, and that is deliberate
# too: the seeder runs the app through FastAPI's TestClient, which drives it on
# a blocking-portal thread started before any context would have been set. A
# ContextVar set by the caller never reaches the request handler, so the
# textbook implementation is the broken one here.
#
# The flag is only ever set by these two entry points, never by a request
# handler, and it is restored in a ``finally``. A request arriving outside the
# block is refused exactly as before - there is a test for that.
_trusted_ingest = False


@contextmanager
def trusted_ingest() -> Iterator[None]:
    """Permit ingestion of the repository's own bundled data.

    Wrap only code paths whose bytes come from ``data/sample/`` or another
    committed source. Never wrap a request handler.
    """
    global _trusted_ingest
    previous = _trusted_ingest
    _trusted_ingest = True
    try:
        yield
    finally:
        _trusted_ingest = previous


def is_trusted_ingest() -> bool:
    """Whether a trusted ingestion block is currently active."""
    return _trusted_ingest


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def uploads_allowed() -> bool:
    """Whether an upload may proceed right now."""
    if settings.uploads_enabled:
        return True
    return is_trusted_ingest()


def ensure_uploads_allowed(what: str = "file") -> None:
    """Refuse an upload when this is a public demonstration.

    Args:
        what: The noun used in the message ("file", "document"), so a contract
            upload does not tell somebody their spreadsheet was rejected.

    Raises:
        DemoModeError: when demo mode is on and uploads are not permitted.
    """
    if uploads_allowed():
        return
    logger.info("Refused a %s upload: public demo mode is on.", what)
    raise DemoModeError(
        f"This public demonstration does not accept {what} uploads. It runs on bundled "
        f"fictional sample data only. Use the guided demonstration on each page, or run the "
        f"project locally to analyse your own files.",
        details={"demo_mode": True, "uploads_enabled": False},
    )


def describe_demo_state() -> dict[str, object]:
    """A UI-safe description of the demonstration configuration.

    Safe means what it says: every value below is a boolean, a fixed string or
    a configured public address. No filesystem path, no database URL, no
    provider credential and no internal hostname appears here, because this is
    served to a browser.
    """
    return {
        "demo_mode": settings.demo_mode,
        "uploads_enabled": settings.uploads_enabled,
        "ai_provider": settings.resolved_ai_provider(),
        "ai_is_mock": settings.resolved_ai_provider() == "mock",
        "banner_headline": DEMO_BANNER_HEADLINE,
        "do_not_submit": list(DO_NOT_SUBMIT),
        "disclaimer": DEMO_DISCLAIMER,
        "data_origin": "demo_data",
        "site_name": settings.public_site_name,
        "contact_email": settings.public_contact_email or None,
        "authentication": (
            "None. This environment has no user accounts, so records created by one visitor "
            "are visible to another through the API. Session-scoped views and an access "
            "policy in front of the hostname reduce that exposure; they do not replace "
            "per-user ownership."
        ),
    }
