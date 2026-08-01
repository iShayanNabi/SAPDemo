"""Authentication seams. Declared, wired, and deliberately not enforced.

This lab has no user accounts. It runs on one machine, on fictional data, and
asking somebody to log in before they can look at a demo would be a worse
product. So **nothing here rejects a request today**, and everything in it is
written so that turning authentication on later is a change to this file plus a
migration, not a change to 130 routes.

Three things exist:

:class:`Principal`
    Who is making the request. In demo mode this is a fixed local principal with
    every role, which is what makes the seam free: code written against
    ``principal.organization_id`` works unchanged the day that value starts
    coming from a token.

:func:`get_principal`
    The FastAPI dependency. It reads an ``Authorization: Bearer`` header if one
    is present, and returns the demo principal when it is not. It never raises.

:func:`require_roles`
    A dependency factory that checks a role. In demo mode the check passes,
    because the demo principal holds every role - not because the check is
    skipped. That distinction matters: the code path is exercised on every
    request today, so it cannot be the thing that breaks when it starts saying
    no.

**Why declare this at all rather than add it later?** Because the shape of the
answer determines the shape of the queries. "Which analyses can this caller
see?" has to be answered by a ``WHERE`` clause, and retrofitting that clause into
a codebase that never had one is how multi-tenant data leaks happen. Writing the
scope down now - even as a value that is always the same - means the question
gets asked while it is cheap.

The full model (JWT, users, organisations, workspaces, roles, tenant isolation)
is in ``docs/API_AUTHENTICATION_PLAN.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated

from fastapi import Depends, Header

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


class Role(str, Enum):
    """What a principal is allowed to do.

    Deliberately small. Four roles cover every action in the lab, and a role set
    somebody can hold in their head is one they will actually apply correctly.
    """

    #: Read analyses, reports and dashboards. Cannot upload or change anything.
    VIEWER = "viewer"
    #: Upload files and run analyses. The everyday role.
    ANALYST = "analyst"
    #: Approve a test case or a blueprint section - a statement about somebody
    #: else's work, so it is a separate permission from making the work.
    APPROVER = "approver"
    #: Manage an organisation's members and settings.
    ADMIN = "admin"


class AuthorizationError(AppError):
    """The caller is known but is not allowed to do this.

    Distinct from "not authenticated" on purpose: 403 tells a client the token
    was fine and retrying with the same one is pointless, where 401 tells it to
    get a new one. Conflating them produces a login loop.
    """

    code = "forbidden"
    http_status = 403


#: The organisation and workspace every demo record belongs to. A real
#: deployment issues one per customer; here there is exactly one, so the columns
#: that will hold it can be added and populated without a nullable state.
DEMO_ORGANIZATION_ID = "org_local_demo"
DEMO_WORKSPACE_ID = "ws_local_demo"


@dataclass(frozen=True)
class Principal:
    """Who is making the request.

    ``is_anonymous`` is the honest field: in demo mode it is ``True`` and every
    role is granted anyway. A response or a log line that wants to say "acting
    as" can therefore tell the difference between a real user and the local
    demo, which is what stops a demo screenshot from looking like an audit
    trail.
    """

    subject: str
    organization_id: str
    workspace_id: str
    roles: frozenset[Role] = field(default_factory=frozenset)
    display_name: str | None = None
    is_anonymous: bool = True

    def has_role(self, role: Role) -> bool:
        """Whether this principal holds ``role``."""
        return role in self.roles

    def require(self, role: Role) -> None:
        """Raise :class:`AuthorizationError` unless this principal holds ``role``."""
        if not self.has_role(role):
            raise AuthorizationError(
                f"This action needs the '{role.value}' role.",
                details={"required_role": role.value, "held_roles": sorted(r.value for r in self.roles)},
            )

    @property
    def audit_label(self) -> str:
        """A short label for a log line or an ``approved_by`` field."""
        if self.is_anonymous:
            return "local demo user"
        return self.display_name or self.subject


#: The principal every request gets while authentication is off. Every role, so
#: the permission checks run and pass rather than being bypassed.
DEMO_PRINCIPAL = Principal(
    subject="local-demo",
    organization_id=DEMO_ORGANIZATION_ID,
    workspace_id=DEMO_WORKSPACE_ID,
    roles=frozenset(Role),
    display_name="Local demo user",
    is_anonymous=True,
)


def authentication_enabled() -> bool:
    """Whether tokens are required. Always ``False`` today.

    A single place to look, so nothing has to infer it from the presence of a
    setting. When this becomes configurable the callers below already ask.
    """
    return False


def get_principal(
    authorization: Annotated[str | None, Header(include_in_schema=False)] = None,
) -> Principal:
    """FastAPI dependency resolving the caller.

    Never raises. With authentication off it returns :data:`DEMO_PRINCIPAL`
    whether or not a token was sent, so a front end can attach an
    ``Authorization`` header during development without the API caring.

    When authentication is switched on, this is the one function that changes:
    verify the JWT, look the subject up, build a :class:`Principal` from its
    claims, and raise a 401 for a missing or invalid token. Every route and every
    query that already asks for a principal keeps working.
    """
    if not authentication_enabled():
        if authorization:
            # Worth a debug line rather than silence: somebody wiring a front end
            # needs to know the header arrived and was intentionally ignored.
            logger.debug("An Authorization header was sent; authentication is off, so it is ignored.")
        return DEMO_PRINCIPAL

    raise NotImplementedError(  # pragma: no cover - unreachable until auth is on
        "Token verification is not implemented. See docs/API_AUTHENTICATION_PLAN.md."
    )


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_roles(*roles: Role) -> Callable[[Principal], Principal]:
    """Build a dependency that requires every role in ``roles``.

    Usage on a route that will eventually be restricted::

        @router.post("/upload", dependencies=[Depends(require_roles(Role.ANALYST))])

    Today the demo principal holds every role, so the check runs and passes. It
    is not a no-op decorated to look like one: the failing branch is real code
    with a real error class and a real status code, so the day it starts firing
    it produces a documented 403 rather than a surprise.
    """

    def dependency(principal: CurrentPrincipal) -> Principal:
        for role in roles:
            principal.require(role)
        return principal

    return dependency


def tenant_scope(principal: Principal) -> dict[str, str]:
    """The filter every list query will eventually apply.

    Returned as a mapping rather than a SQLAlchemy clause so it can be attached
    to a query, written into a new row, or logged, from one definition.

    Nothing uses it yet, and that is the point of writing it down: "which rows
    can this caller see" is a question that has to be answered in the query
    itself, and a codebase that has never asked it is one where the answer gets
    added in ten places and forgotten in the eleventh.
    """
    return {
        "organization_id": principal.organization_id,
        "workspace_id": principal.workspace_id,
    }


def describe_auth_state() -> dict[str, object]:
    """A UI/log-safe description of the authentication configuration."""
    return {
        "enabled": authentication_enabled(),
        "scheme": "bearer",
        "mode": "local demo (no accounts, every request is the demo principal)",
        "environment": settings.environment,
        "organization_id": DEMO_ORGANIZATION_ID,
        "workspace_id": DEMO_WORKSPACE_ID,
        "roles": [role.value for role in Role],
        "plan": "docs/API_AUTHENTICATION_PLAN.md",
    }
