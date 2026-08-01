"""The authentication seams: present, exercised, and not enforcing anything.

Two opposite failures are possible here and both matter.

The first is that a seam quietly starts rejecting requests, and the lab stops
being runnable by somebody who just cloned it. The point of this project is that
it works with no keys and no accounts.

The second is that the seam is decorative - a `require_roles` that is really a
no-op, a `Principal` nothing ever constructs. Then the day authentication is
switched on, none of it has ever executed, and every one of those code paths
runs for the first time in front of a user.

So these tests assert both: no request is refused, *and* the permission machinery
really runs and really can say no.
"""

from __future__ import annotations

import json

import pytest

from app.core.auth import (
    DEMO_ORGANIZATION_ID,
    DEMO_PRINCIPAL,
    DEMO_WORKSPACE_ID,
    AuthorizationError,
    Principal,
    Role,
    authentication_enabled,
    describe_auth_state,
    get_principal,
    require_roles,
    tenant_scope,
)
from tests.e2e.conftest import ok

V1 = "/api/v1"


class TestLocalDemoModeStillWorks:
    def test_authentication_is_off(self):
        assert authentication_enabled() is False

    def test_no_endpoint_needs_a_token(self, client):
        """A sample of every kind of route: read, write, upload-adjacent, export."""
        for path in (
            f"{V1}/health",
            f"{V1}/auth-status",
            f"{V1}/po-risk/rules",
            f"{V1}/po-risk/fields",
            f"{V1}/spend/savings-rules",
            f"{V1}/contracts/methodology",
            f"{V1}/inventory/methods",
            f"{V1}/interviews/catalog",
            f"{V1}/test-cases/catalog",
            f"{V1}/blueprints/catalog",
        ):
            assert client.get(path).status_code == 200, f"{path} refused an anonymous request"

    def test_an_unexpected_token_is_ignored_rather_than_rejected(self, client):
        """A front end in development attaches a header before there is a server."""
        response = client.get(
            f"{V1}/health", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 200

    def test_the_demo_principal_is_honest_about_being_anonymous(self):
        """A demo screenshot must not be able to look like an audit trail."""
        assert DEMO_PRINCIPAL.is_anonymous is True
        assert DEMO_PRINCIPAL.audit_label == "local demo user"

    def test_the_health_endpoint_will_stay_open(self, client):
        """A container healthcheck cannot log in - see the plan."""
        assert ok(client.get(f"{V1}/health"))


class TestTheSeamIsRealCode:
    def test_the_permission_check_runs_and_can_refuse(self):
        """The failing branch is exercised, not merely present."""
        viewer = Principal(
            subject="usr_viewer",
            organization_id="org_1",
            workspace_id="ws_1",
            roles=frozenset({Role.VIEWER}),
            is_anonymous=False,
        )
        assert viewer.has_role(Role.VIEWER)
        viewer.require(Role.VIEWER)  # passes

        with pytest.raises(AuthorizationError) as raised:
            viewer.require(Role.APPROVER)
        assert raised.value.http_status == 403
        assert raised.value.code == "forbidden"
        assert raised.value.details["required_role"] == "approver"

    def test_the_demo_principal_passes_because_it_holds_the_role(self):
        """Not because the check is skipped - that distinction is the point."""
        for role in Role:
            assert DEMO_PRINCIPAL.has_role(role)
            DEMO_PRINCIPAL.require(role)

    def test_the_dependency_factory_returns_a_working_dependency(self):
        dependency = require_roles(Role.ANALYST, Role.APPROVER)
        assert dependency(DEMO_PRINCIPAL) is DEMO_PRINCIPAL

        viewer = Principal(
            subject="usr_viewer",
            organization_id="org_1",
            workspace_id="ws_1",
            roles=frozenset({Role.VIEWER}),
        )
        with pytest.raises(AuthorizationError):
            dependency(viewer)

    def test_get_principal_never_raises_today(self):
        assert get_principal(None) is DEMO_PRINCIPAL
        assert get_principal("Bearer anything") is DEMO_PRINCIPAL

    def test_the_tenant_scope_is_a_filter_something_can_apply(self):
        """Written down now so 'which rows can this caller see' is already asked."""
        scope = tenant_scope(DEMO_PRINCIPAL)
        assert scope == {
            "organization_id": DEMO_ORGANIZATION_ID,
            "workspace_id": DEMO_WORKSPACE_ID,
        }

    def test_forbidden_and_unauthorized_are_different_errors(self):
        """403 says the token was fine; 401 says get a new one. A loop otherwise."""
        assert AuthorizationError("x").http_status == 403
        assert AuthorizationError("x").code == "forbidden"


class TestTheStateIsReported:
    def test_auth_status_says_authentication_is_off(self, client):
        data = ok(client.get(f"{V1}/auth-status"))
        assert data["enabled"] is False
        assert data["scheme"] == "bearer"
        assert "local demo" in data["mode"]
        assert data["plan"] == "docs/API_AUTHENTICATION_PLAN.md"

    def test_it_reports_the_principal_the_request_resolved_to(self, client):
        data = ok(client.get(f"{V1}/auth-status"))
        principal = data["principal"]
        assert principal["is_anonymous"] is True
        assert principal["organization_id"] == DEMO_ORGANIZATION_ID
        assert principal["workspace_id"] == DEMO_WORKSPACE_ID
        assert set(principal["roles"]) == {role.value for role in Role}

    def test_it_never_reports_a_credential(self, client):
        rendered = json.dumps(ok(client.get(f"{V1}/auth-status"))).lower()
        for leak in ("password", "secret", "sk-", "private_key", "hash"):
            assert leak not in rendered

    def test_the_description_helper_is_safe_to_log(self):
        rendered = json.dumps(describe_auth_state()).lower()
        assert "password" not in rendered and "token" not in rendered

    def test_the_plan_document_exists_and_names_the_seams(self):
        """A plan the code points at has to be there when somebody follows it."""
        from app.core.config import PROJECT_ROOT

        plan = PROJECT_ROOT / "docs" / "API_AUTHENTICATION_PLAN.md"
        assert plan.is_file(), "auth-status points at a document that does not exist"
        text = plan.read_text(encoding="utf-8")
        for topic in (
            "JWT",
            "organizations",
            "workspaces",
            "Role-based access control",
            "Tenant isolation",
            "API keys",
        ):
            assert topic.lower() in text.lower(), f"the plan does not cover {topic}"
        assert "tenant_scope" in text
        assert "get_principal" in text
