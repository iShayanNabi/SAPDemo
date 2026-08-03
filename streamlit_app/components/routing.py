"""Opening one module from a link, safely.

The public website links to individual tools - ``/?module=po-risk`` rather than
just ``/`` - so somebody who read about the Purchase Order Risk Checker arrives
at the Purchase Order Risk Checker instead of at a list they have to search.
This module is the half of that arrangement that lives inside the protected
application.

It is deliberately small, and the size is the point. A query parameter is a
string a stranger controls, and there is exactly one thing this code may do with
it: **compare it against a fixed list.** So it does that, and nothing else:

- the value is never imported, executed, formatted into a path or joined onto a
  directory - :data:`DEMO_MODULE_PAGES` is written out by hand, and the value's
  only role is to be a key that is either in it or is not;
- an unrecognised value is not echoed back. It reaches no page, no log line and
  no session key; the visitor is told the module was not recognised, in fixed
  wording, and lands on the demonstration home page;
- nothing here is a security control. The parameter says *which page*, never
  *who is asking*. Cloudflare Access authenticates approved visitors at the
  network edge, in front of this whole hostname, and a request that has not
  passed it never reaches Streamlit at all. Application-level verification of
  the signed Access assertion is planned separately and is not implemented
  here - see ``docs/DEMO_MODULE_ROUTING.md``.

The ten identifiers mirror ``frontend/lib/demo.ts``. They are a public contract:
they appear in URLs people bookmark and paste, so they are not derived from page
file names, module ids, display names or import paths, all of which may change
without those links changing meaning.
``tests/integration/test_demo_module_contract.py`` asserts the two lists agree.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import streamlit as st

#: The query parameter the public website writes and this application reads.
MODULE_QUERY_PARAM = "module"

#: The ten public identifiers, each mapped to the page that serves it.
#:
#: Written out rather than globbed or derived from the file names on disk. A
#: glob would happily route to a file somebody dropped into ``pages/``, and a
#: derivation would silently change a public URL the day a page is renamed. The
#: paths are relative to the entrypoint (``streamlit_app/Home.py``), which is
#: what ``st.switch_page`` expects for a ``pages/`` multipage application.
DEMO_MODULE_PAGES: Mapping[str, str] = {
    "po-risk": "pages/1_PO_Risk_Checker.py",
    "spend-analytics": "pages/2_Spend_Analytics.py",
    "supplier-recommendation": "pages/3_Supplier_Recommendations.py",
    "invoice-validator": "pages/4_Invoice_Validator.py",
    "supplier-risk": "pages/5_Supplier_Risk_Copilot.py",
    "contract-assistant": "pages/6_Contract_Assistant.py",
    "inventory-predictor": "pages/7_Inventory_Predictor.py",
    "test-case-generator": "pages/8_Test_Case_Generator.py",
    "blueprint-generator": "pages/9_SAP_Blueprint_Generator.py",
    "interview-coach": "pages/10_SAP_Interview_Coach.py",
}

#: What a visitor sees when the identifier means nothing here.
#:
#: Fixed wording, and it does not repeat what was asked for. Echoing the value
#: back would put a stranger's string on the page, and naming the page that was
#: not found would publish the file layout of an application whose whole
#: hostname is meant to be private.
UNRECOGNISED_MODULE_MESSAGE = (
    "The requested module was not recognized. Showing the demo homepage."
)

#: Longer than any real identifier by a wide margin. A value past this is not a
#: near miss to be matched, it is something being tried on, and it is rejected
#: before it is normalised so that a megabyte of query string costs a length
#: check rather than a ``lower()`` over a megabyte.
_MAX_IDENTIFIER_LENGTH = 64

#: Set on the browser session once a link has been honoured.
#:
#: Holds a boolean, never the value that was requested: raw input does not go
#: into shared state, and there is nothing this needs from it anyway.
_ROUTE_APPLIED_KEY = "_demo_module_route_applied"

RouteOutcome = Literal["absent", "unrecognised", "selected"]


@dataclass(frozen=True)
class ModuleRoute:
    """What a request's ``module`` parameter turned out to mean.

    ``absent``
        No parameter, or an empty one. The demonstration home page is what was
        asked for, and nothing is said about it.
    ``unrecognised``
        Something was asked for and this application has no such module. The
        home page is shown with :data:`UNRECOGNISED_MODULE_MESSAGE`.
    ``selected``
        One of the ten. :attr:`page` is the page to open.
    """

    outcome: RouteOutcome
    module: str | None = None
    page: str | None = None

    @property
    def is_selected(self) -> bool:
        return self.outcome == "selected"

    @property
    def should_warn(self) -> bool:
        return self.outcome == "unrecognised"


#: The one instance of "nothing was asked for", so callers can compare cheaply.
NO_ROUTE = ModuleRoute(outcome="absent")


def resolve_module_route(values: Sequence[str] | None) -> ModuleRoute:
    """Turn the raw ``module`` values of a request into a decision.

    Pure: it reads no Streamlit state and changes none, which is what makes the
    interesting cases testable without a browser. ``values`` is a sequence
    because a query string may carry the same key more than once.

    Repeats are refused rather than resolved. ``?module=po-risk&module=spend``
    has no correct answer - taking the first or the last would be a guess about
    which one the visitor meant - so it is treated as unrecognised, which lands
    them on the home page with every module one click away.
    """
    if not values:
        return NO_ROUTE
    if len(values) > 1:
        return ModuleRoute(outcome="unrecognised")

    raw = values[0]
    if not isinstance(raw, str) or len(raw) > _MAX_IDENTIFIER_LENGTH:
        return ModuleRoute(outcome="unrecognised")

    # Whitespace survives a copied-and-pasted link, and case survives a URL
    # somebody typed. Nothing else is repaired: this is a lookup key, not a
    # spelling correction, and every character that is left is either in the
    # table or is not.
    candidate = raw.strip().lower()
    if not candidate:
        return NO_ROUTE

    page = DEMO_MODULE_PAGES.get(candidate)
    if page is None:
        return ModuleRoute(outcome="unrecognised")
    return ModuleRoute(outcome="selected", module=candidate, page=page)


def requested_module_route() -> ModuleRoute:
    """Read this request's ``module`` parameter and resolve it.

    ``get_all`` rather than ``get``: a repeated key is a case this has to see
    rather than one Streamlit quietly resolves by handing back the last value.
    A key that is not there at all is an empty list, which
    :func:`resolve_module_route` reads as "nothing was asked for".
    """
    return resolve_module_route(list(st.query_params.get_all(MODULE_QUERY_PARAM)))


def apply_module_route() -> ModuleRoute:
    """Open the requested module, once, and report what happened.

    Called at the top of ``Home.py``. When a module is selected this does not
    return: :func:`streamlit.switch_page` stops the current script run and the
    target page runs instead, exactly as if the visitor had clicked it in the
    sidebar. The caller therefore only ever sees ``absent`` or ``unrecognised``,
    and renders the home page for both.

    Two behaviours worth stating, because both are choices rather than
    accidents:

    **It happens once per browser session.** ``st.switch_page`` clears the query
    string as it navigates, so the parameter is gone from the URL the moment it
    has been used - but the *browser back button* puts it back. Without the
    session flag, going back from the module would re-read the parameter and
    bounce the visitor forward again, and the back button would be dead. With
    it, back returns to the home page and stays there.

    **It only ever runs on this page.** The module pages have no routing code,
    so navigating manually - the sidebar, a bookmark, the back button - is
    ordinary Streamlit navigation and this module has no opinion about it. The
    link decides where a visitor *starts*, never where they may go.
    """
    route = requested_module_route()
    page = route.page
    if page is None or st.session_state.get(_ROUTE_APPLIED_KEY):
        return route

    # Set before switching, because switch_page raises to unwind the script run
    # and anything after it is unreachable.
    st.session_state[_ROUTE_APPLIED_KEY] = True
    st.switch_page(page)
    return route  # pragma: no cover - switch_page does not return
