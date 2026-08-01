"""Public demonstration presentation for the Streamlit pages.

Three jobs, all presentation:

:func:`demo_banner`
    The standing "Public Demo — Fictional Data Only" notice and the list of
    things a visitor must not paste in. Rendered at the top of every page.
:func:`guided_demo`
    The panel that explains what a module is for, which part of its answer is
    arithmetic and which part is prose, and offers the Load Demo action.
:func:`remember` / :func:`mine`
    A browser-session record of the identifiers this visitor created, so a
    history or list view can show their own work rather than everybody's.

That last one deserves its limits stated plainly, because it is easy to mistake
for a security control and it is not one. It filters what this page *renders*.
The API underneath has no user accounts, so a caller that reaches it directly
can still list every record. What actually keeps a stranger away from the API is
that the API has no public hostname and the demonstration hostname sits behind
an access policy - see ``docs/DEMO_SECURITY_CHECKLIST.md``. Per-visitor
ownership needs the model in ``docs/API_AUTHENTICATION_PLAN.md``, which is not
built.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from streamlit_app.components.api_client import ApiClient, ApiError

#: Cached per browser session under this key so the banner does not cost an
#: HTTP round trip on every rerun. Streamlit reruns the whole script on every
#: widget interaction, so "once per session" is the difference between one call
#: and one call per click.
_STATUS_KEY = "_demo_status"
_MINE_KEY = "_demo_owned_ids"


def demo_status(client: ApiClient | None = None) -> dict[str, Any]:
    """Return the demonstration status, fetched once per browser session.

    A backend that cannot be reached is reported as *not* a demonstration:
    the banner is a promise about how this deployment is configured, and
    guessing that promise from a failed request would be the wrong way round.
    """
    if _STATUS_KEY not in st.session_state:
        try:
            st.session_state[_STATUS_KEY] = (client or ApiClient()).demo_status()
        except ApiError:
            st.session_state[_STATUS_KEY] = {"demo_mode": False, "uploads_enabled": True}
    return st.session_state[_STATUS_KEY]


def is_demo_mode(client: ApiClient | None = None) -> bool:
    """Whether this deployment is a public demonstration."""
    return bool(demo_status(client).get("demo_mode"))


def uploads_enabled(client: ApiClient | None = None) -> bool:
    """Whether the visitor may upload their own file."""
    return bool(demo_status(client).get("uploads_enabled", True))


def demo_banner(client: ApiClient | None = None) -> None:
    """Render the public demonstration banner, if this is one.

    Silent when demo mode is off, so a developer's local run looks exactly as
    it did before this existed.
    """
    status = demo_status(client)
    if not status.get("demo_mode"):
        return

    st.warning(f"**{status.get('banner_headline', 'Public Demo — Fictional Data Only')}**")
    do_not_submit = status.get("do_not_submit") or []
    with st.expander("What you must not enter here", expanded=False):
        st.markdown(
            "Everything in this environment is fictional sample data, and anything you type "
            "is stored in a shared demonstration database with no user accounts. **Do not "
            "enter:**\n"
            + "\n".join(f"- {item}" for item in do_not_submit)
            + "\n\nFile uploads are disabled. Each module runs on the bundled fictional "
            "dataset described on its page."
        )


def upload_disabled_notice(what: str = "file") -> None:
    """Explain, where the uploader used to be, why it is not there."""
    st.info(
        f"**{what.capitalize()} upload is disabled in this public demonstration.** "
        f"Use *Load the demonstration data* below to run this module on its bundled "
        f"fictional dataset. To analyse your own {what}s, run the project locally - the "
        f"README has the five commands.",
        icon="🔒",
    )


# ---------------------------------------------------------------------------
# Session-scoped ownership
# ---------------------------------------------------------------------------
def remember(kind: str, identifier: str) -> None:
    """Record that this browser session created ``identifier``."""
    if not identifier:
        return
    owned: dict[str, list[str]] = st.session_state.setdefault(_MINE_KEY, {})
    bucket = owned.setdefault(kind, [])
    if identifier not in bucket:
        bucket.append(identifier)


def mine(kind: str) -> list[str]:
    """Return the identifiers of ``kind`` this browser session created."""
    return list(st.session_state.get(_MINE_KEY, {}).get(kind, []))


def filter_to_mine(
    rows: list[dict[str, Any]], kind: str, id_field: str, *, client: ApiClient | None = None
) -> list[dict[str, Any]]:
    """Narrow a list response to this session's own records, in demo mode only.

    Outside demo mode the list is returned untouched - a local developer wants
    to see every analysis on their own machine, and always has.
    """
    if not is_demo_mode(client):
        return rows
    owned = set(mine(kind))
    return [row for row in rows if row.get(id_field) in owned]


def session_scope_caption(kind_label: str = "records") -> None:
    """State what a filtered list is, and is not, showing."""
    if not is_demo_mode():
        return
    st.caption(
        f"Showing only the {kind_label} created in this browser session. This is a display "
        f"filter for a shared demonstration database, not per-user ownership: this "
        f"environment has no accounts."
    )


# ---------------------------------------------------------------------------
# The guided demonstration panel
# ---------------------------------------------------------------------------
def module_spec(module_key: str, client: ApiClient | None = None) -> dict[str, Any] | None:
    """Return one module's demonstration description, fetched once per session."""
    key = "_demo_modules"
    if key not in st.session_state:
        try:
            st.session_state[key] = (client or ApiClient()).demo_modules()
        except ApiError:
            st.session_state[key] = []
    for spec in st.session_state[key]:
        if spec.get("module") == module_key:
            return spec
    return None


def explain_module(module_key: str, steps: list[str] | None = None) -> None:
    """Render the business question, the deterministic/AI split and the steps."""
    spec = module_spec(module_key)
    if spec is None:
        return

    with st.expander("About this demonstration", expanded=False):
        st.markdown(f"**The question this answers.** {spec['business_question']}")
        st.markdown(f"**Computed by code.** {spec['deterministic_summary']}")
        st.markdown(f"**Written by AI.** {spec['ai_summary']}")
        st.markdown(f"**What you get.** {spec['expected_output']}")
        if steps:
            st.markdown("**Steps.**")
            for number, step in enumerate(steps, start=1):
                st.markdown(f"{number}. {step}")
        files = ", ".join(f"`{d['filename']}`" for d in spec.get("datasets", []))
        if files:
            st.caption(f"Fictional demonstration input: {files}")


def load_demo_button(
    module_key: str,
    *,
    label: str = "Load the demonstration data",
    client: ApiClient | None = None,
    key: str | None = None,
) -> dict[str, Any] | None:
    """Render the Load Demo action and return the loaded handles when pressed.

    Returns ``None`` on every rerun where the button was not pressed, which is
    the Streamlit idiom: the caller stores the result in ``st.session_state``
    itself, exactly as it does for an upload.
    """
    spec = module_spec(module_key, client)
    if spec is not None and not spec.get("loadable", False):
        st.error(
            "The bundled demonstration file for this module is not present. Regenerate the "
            "sample data with the matching scripts/generate_*_sample_data.py script."
        )
        return None

    if not st.button(label, type="primary", key=key or f"load_demo_{module_key}"):
        return None

    with st.spinner("Loading the bundled fictional dataset..."):
        try:
            return (client or ApiClient()).demo_load(module_key)
        except ApiError as error:
            st.error(error.message)
            return None
