"""Streamlit page for the SAP Blueprint Generator.

Like every page in this app it contains no business logic. It collects the
project request, asks the FastAPI backend to generate a blueprint, and renders
what comes back. Every section, every organisational-structure row, every
identifier, every approval and every version comparison is produced server-side,
so a future React front end calling the same endpoints gets the same document.

The page is deliberately blunt about two things:

* this is a **proposed** blueprint that qualified SAP professionals must review,
  and nothing in it has been validated against a live SAP system;
* a section that is waiting for a project input says so, rather than being
  filled with plausible content nobody asked for.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from streamlit_app.components.api_client import ApiClient, ApiError  # noqa: E402
from streamlit_app.components.ui import origin_badge, show_error  # noqa: E402

st.set_page_config(page_title="SAP Blueprint Generator", page_icon="📐", layout="wide")

client = ApiClient()

STATUS_ICONS = {
    "approved": "✅",
    "in_review": "🔍",
    "draft": "📝",
    "needs_input": "⚠️",
}
SOURCE_LABELS = {
    "ai_generated": "AI drafted",
    "derived": "Computed from the project request",
    "template": "Template (no model)",
    "manual": "Written by a person",
}
ITEM_SOURCE_LABELS = {
    "derived": "From the project request",
    "ai_generated": "AI drafted",
    "template": "Template",
    "manual": "By hand",
}
EXPORT_MIME = {
    "markdown": "text/markdown",
    "json": "application/json",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}
EXPORT_EXTENSIONS = {"markdown": "md", "json": "json", "docx": "docx", "pdf": "pdf"}

LIST_FIELD_HELP = "One entry per line."

#: The shared ``disclaimer()`` helper talks about an uploaded file. This module
#: has no upload - its input is a form - so it states its own.
PAGE_DISCLAIMER = (
    "This page produces a proposed SAP implementation blueprint from the project request you "
    "type in. It is not connected to an SAP system, nothing in it has been validated in a live "
    "SAP environment, and it requires review by qualified SAP professionals. The structure and "
    "the factual rows come from deterministic Python rules; any AI text is labelled separately."
)

st.title("SAP Blueprint Generator")
st.write(
    "Describe an SAP implementation project and get a thirty-section blueprint you can edit, "
    "approve, version and export. The section list, the organisational structure, the module "
    "list, the integration register, the interface list, the migration sources and the security "
    "roles are computed by deterministic Python from what you enter; only the wording of each "
    "section is drafted by the AI provider."
)
st.caption(
    "This produces a **proposed** blueprint that requires review by qualified SAP "
    "professionals. No configuration, structure, interface or role described in it has been "
    "validated in a live SAP system, and this application is not connected to one."
)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _block(values: Any) -> str:
    if isinstance(values, list):
        return "\n".join(str(item) for item in values)
    return str(values or "")


def _sections_frame(sections: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "#": section["position"],
                "ID": section["section_id"],
                "Section": section["title"],
                "Status": STATUS_ICONS.get(section["status"], "") + " " + section["status"],
                "Written by": SOURCE_LABELS.get(section["source"], section["source"]),
                "Items": len(section["items"]),
                "Approved by": section["approved_by"] or "-",
                "Needs re-review": (
                    ", ".join(section["stale_dependencies"])
                    if section["stale_dependencies"]
                    else ""
                ),
                "Waiting for": ", ".join(section["missing_inputs"]),
            }
            for section in sections
        ]
    )


def _items_frame(items: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ID": item["item_id"],
                "Item": item["title"],
                "Detail": item["detail"],
                "Category": item["category"],
                "Owner": item["owner"],
                "Rating": item["rating"],
                "Reference": item["reference"],
                "Written by": ITEM_SOURCE_LABELS.get(item["source"], item["source"]),
            }
            for item in items
        ]
    )


def _load(blueprint_id: str) -> None:
    """Re-read the blueprint from the API after any change."""
    st.session_state["blueprint"] = client.blueprint(blueprint_id)


# ---------------------------------------------------------------------------
# Sidebar: backend status, demo projects, saved blueprints
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Backend status")
    try:
        health = client.health()
        st.success(f"API reachable ({health['status']})")
        st.write(
            f"**AI provider:** {health['ai_provider']}"
            + (" (mock)" if health["ai_is_mock"] else "")
        )
        if health["ai_is_mock"]:
            st.caption(
                "Mock mode: section wording is generated locally with no API call. The "
                "structure and the factual rows are identical either way."
            )
    except ApiError as error:
        st.error(error.message)
        st.code("uvicorn app.main:app --reload", language="bash")
        st.stop()

    st.divider()
    st.header("Demo projects")
    try:
        sample = client.blueprint_sample_info()
    except ApiError:
        sample = {"available": False, "projects": []}

    if sample.get("available"):
        names = [item["name"] for item in sample["projects"]]
        labels = {
            item["name"]: f"{item['title']} ({item['company']})" for item in sample["projects"]
        }
        chosen = st.selectbox(
            "Fictional project request",
            names,
            format_func=lambda name: labels.get(name, name),
        )
        summary = next(
            (item["summary"] for item in sample["projects"] if item["name"] == chosen), ""
        )
        st.caption(summary)
        if st.button("Load into the form", use_container_width=True):
            try:
                st.session_state["demo_project"] = client.blueprint_sample(chosen)["project"]
                st.success("Loaded. Scroll down and press Generate.")
            except ApiError as error:
                show_error(error.message, error.details)
    else:
        st.caption(
            "No demo projects found. Run:\n\n"
            "`python scripts/generate_blueprint_sample_data.py`"
        )

    st.divider()
    st.header("Saved blueprints")
    try:
        listing = client.blueprints(limit=25)
        if listing["blueprints"]:
            for item in listing["blueprints"]:
                if st.button(
                    f"{item['name']} ({item['section_count']} sections, "
                    f"v{item['current_version']})",
                    key=f"open_{item['blueprint_id']}",
                    use_container_width=True,
                ):
                    _load(item["blueprint_id"])
                    st.rerun()
        else:
            st.caption("None yet.")
    except ApiError as error:
        st.caption(error.message)

# ---------------------------------------------------------------------------
# The project form
# ---------------------------------------------------------------------------
demo = st.session_state.get("demo_project", {})

with st.expander("1. Project request", expanded="blueprint" not in st.session_state):
    with st.form("blueprint_form"):
        left, middle, right = st.columns(3)
        with left:
            company = st.text_input("Company", value=demo.get("company", ""))
            industry = st.text_input("Industry", value=demo.get("industry", ""))
            sap_product = st.text_input("SAP product", value=demo.get("sap_product", ""))
            modules = st.text_area(
                "Modules", value=_block(demo.get("modules")), help=LIST_FIELD_HELP, height=100
            )
            business_objectives = st.text_area(
                "Business objectives",
                value=_block(demo.get("business_objectives")),
                help=LIST_FIELD_HELP,
                height=120,
            )
            timeline = st.text_area("Timeline", value=demo.get("timeline", ""), height=90)
        with middle:
            countries = st.text_area(
                "Countries", value=_block(demo.get("countries")), help=LIST_FIELD_HELP, height=90
            )
            locations = st.text_area(
                "Locations", value=_block(demo.get("locations")), help=LIST_FIELD_HELP, height=90
            )
            company_codes = st.text_area(
                "Company codes",
                value=_block(demo.get("company_codes")),
                help=LIST_FIELD_HELP,
                height=90,
            )
            plants = st.text_area(
                "Plants", value=_block(demo.get("plants")), help=LIST_FIELD_HELP, height=90
            )
            purchasing_organizations = st.text_area(
                "Purchasing organizations",
                value=_block(demo.get("purchasing_organizations")),
                help=LIST_FIELD_HELP,
                height=90,
            )
        with right:
            systems_involved = st.text_area(
                "Systems involved",
                value=_block(demo.get("systems_involved")),
                help=LIST_FIELD_HELP,
                height=90,
            )
            integrations = st.text_area(
                "Integrations",
                value=_block(demo.get("integrations")),
                help=LIST_FIELD_HELP,
                height=90,
            )
            data_sources = st.text_area(
                "Data sources",
                value=_block(demo.get("data_sources")),
                help=LIST_FIELD_HELP,
                height=90,
            )
            user_groups = st.text_area(
                "User groups",
                value=_block(demo.get("user_groups")),
                help=LIST_FIELD_HELP,
                height=90,
            )
            constraints = st.text_area(
                "Constraints",
                value=_block(demo.get("constraints")),
                help=LIST_FIELD_HELP,
                height=90,
            )

        current_process = st.text_area(
            "Current process", value=demo.get("current_process", ""), height=140
        )
        desired_process = st.text_area(
            "Desired process", value=demo.get("desired_process", ""), height=140
        )
        assumptions = st.text_area(
            "Assumptions", value=_block(demo.get("assumptions")), help=LIST_FIELD_HELP, height=90
        )

        name_column, owner_column, ai_column = st.columns([2, 2, 1])
        with name_column:
            blueprint_name = st.text_input("Blueprint name (optional)")
        with owner_column:
            owner = st.text_input("Owner (optional)")
        with ai_column:
            use_ai = st.checkbox("Use AI wording", value=True)

        st.caption(
            "A section whose required fields are empty is returned marked **waiting for "
            "input** rather than filled in - the generator will not invent an organisational "
            "unit, an interface, a migration source or a role that you did not name."
        )
        submitted = st.form_submit_button("Generate blueprint", type="primary")

    if submitted:
        project = {
            "company": company,
            "industry": industry,
            "sap_product": sap_product,
            "modules": _lines(modules),
            "business_objectives": _lines(business_objectives),
            "current_process": current_process,
            "desired_process": desired_process,
            "countries": _lines(countries),
            "locations": _lines(locations),
            "company_codes": _lines(company_codes),
            "plants": _lines(plants),
            "purchasing_organizations": _lines(purchasing_organizations),
            "systems_involved": _lines(systems_involved),
            "integrations": _lines(integrations),
            "data_sources": _lines(data_sources),
            "user_groups": _lines(user_groups),
            "timeline": timeline,
            "constraints": _lines(constraints),
            "assumptions": _lines(assumptions),
        }
        with st.spinner("Generating the blueprint..."):
            try:
                st.session_state["blueprint"] = client.blueprint_generate(
                    project,
                    blueprint_name=blueprint_name or None,
                    owner=owner or None,
                    use_ai=use_ai,
                )
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)

blueprint = st.session_state.get("blueprint")
if not blueprint:
    st.info("Fill in the project request above, or load a demo project from the sidebar.")
    st.caption(PAGE_DISCLAIMER)
    st.stop()

blueprint_id = blueprint["blueprint_id"]
sections = blueprint["sections"]
summary = blueprint["summary"]

# ---------------------------------------------------------------------------
# Document status
# ---------------------------------------------------------------------------
st.subheader(blueprint["name"])
st.warning(blueprint["disclaimer"], icon="⚠️")

metrics = st.columns(6)
metrics[0].metric("Sections", summary["section_count"])
metrics[1].metric("Written", f"{summary['completeness_pct']}%")
metrics[2].metric("Approved", f"{summary['approved_count']}")
metrics[3].metric("Waiting for input", summary["needs_input_count"])
metrics[4].metric("Need re-review", summary["stale_section_count"])
metrics[5].metric("Saved versions", summary["version_count"])

if summary["stale_approved_count"]:
    st.error(
        f"{summary['stale_approved_count']} approved section(s) describe content that has "
        "changed since they were approved. The approval is kept, but it was given to wording "
        "that no longer matches - regenerate or re-approve them.",
        icon="🚩",
    )
if summary["missing_inputs"]:
    st.warning(
        "These project fields are empty, so the sections that need them were left unwritten: "
        + ", ".join(name.replace("_", " ") for name in summary["missing_inputs"])
        + ". Use **Update the project request** below to supply them.",
        icon="✍️",
    )
for note in blueprint["notes"]:
    st.info(note, icon="ℹ️")
if blueprint["injection_detected"]:
    st.warning(
        "The project request contained text written as an instruction to an automated system "
        "(in: " + ", ".join(blueprint["injection_markers"]) + "). It was filtered before "
        "drafting, removed from the document text and never acted on.",
        icon="🛡️",
    )

ai_info = blueprint["ai"]
st.caption(
    f"Section wording: {origin_badge(ai_info['origin'])}"
    + (f" · provider `{ai_info['provider']}`" if ai_info["provider"] else "")
    + (f" · model `{ai_info['model']}`" if ai_info["model"] else "")
    + f" · configuration v{blueprint['config_version']}"
    + f" · engine v{blueprint['engine_version']}"
    + f" · generated in {blueprint['duration_ms']} ms"
)
if ai_info["error"]:
    st.caption(f"AI note: {ai_info['error']}")

tab_navigator, tab_section, tab_versions, tab_project, tab_export = st.tabs(
    ["Sections", "Edit a section", "Versions", "Project request", "Export"]
)

# ---------------------------------------------------------------------------
# Section navigator
# ---------------------------------------------------------------------------
with tab_navigator:
    st.dataframe(_sections_frame(sections), use_container_width=True, hide_index=True)

    st.markdown("#### Read the document")
    for section in sections:
        icon = STATUS_ICONS.get(section["status"], "")
        with st.expander(f"{icon} {section['position']}. {section['title']}"):
            st.caption(
                f"`{section['section_id']}` · {section['status']} · "
                f"{SOURCE_LABELS.get(section['source'], section['source'])}"
                + (f" · approved by {section['approved_by']}" if section["approved_by"] else "")
            )
            if section["approval_is_stale"]:
                st.error(
                    "This section is approved, but it was written before "
                    + ", ".join(section["stale_dependencies"])
                    + " changed. The approval no longer describes what is written here.",
                    icon="🚩",
                )
            elif section["stale_dependencies"]:
                st.warning(
                    "Written before " + ", ".join(section["stale_dependencies"]) + " changed.",
                    icon="🔁",
                )
            if section["missing_inputs"]:
                st.warning(
                    "Waiting for: "
                    + ", ".join(name.replace("_", " ") for name in section["missing_inputs"]),
                    icon="⚠️",
                )
            st.write(section["narrative"])
            if section["items"]:
                st.dataframe(
                    _items_frame(section["items"]), use_container_width=True, hide_index=True
                )
            for note in section["validation_notes"]:
                st.caption(f"Drafting note: {note}")
            if section["comments"]:
                st.caption(f"Reviewer comment: {section['comments']}")

# ---------------------------------------------------------------------------
# Edit / regenerate / approve one section, add and delete custom sections
# ---------------------------------------------------------------------------
with tab_section:
    labels = {
        section["section_id"]: f"{section['position']}. {section['title']}"
        for section in sections
    }
    chosen_id = st.selectbox(
        "Section", list(labels), format_func=lambda key: labels[key], key="edit_section"
    )
    current = next(section for section in sections if section["section_id"] == chosen_id)

    st.caption(
        f"{current['description']} · revision {current['content_revision']} · "
        f"regenerated {current['regenerated_count']} time(s)"
    )

    edit_column, action_column = st.columns([3, 1])
    with edit_column:
        with st.form(f"edit_{chosen_id}"):
            new_title = st.text_input("Title", value=current["title"])
            new_narrative = st.text_area("Narrative", value=current["narrative"], height=260)
            st.caption(
                "Editing the title, the narrative or the items clears any approval and returns "
                "the section to draft - the approval belonged to the wording it replaced."
            )
            new_comments = st.text_area(
                "Reviewer comment", value=current["comments"], height=80
            )
            if st.form_submit_button("Save changes", type="primary"):
                changes: dict[str, Any] = {}
                if new_title != current["title"]:
                    changes["title"] = new_title
                if new_narrative != current["narrative"]:
                    changes["narrative"] = new_narrative
                if new_comments != current["comments"]:
                    changes["comments"] = new_comments
                if not changes:
                    st.info("Nothing changed.")
                else:
                    try:
                        client.blueprint_section_update(blueprint_id, chosen_id, changes)
                        _load(blueprint_id)
                        st.success("Saved.")
                        st.rerun()
                    except ApiError as error:
                        show_error(error.message, error.details)

        if current["items"]:
            st.markdown("##### Items")
            editable = pd.DataFrame(
                [
                    {
                        "Item": item["title"],
                        "Detail": item["detail"],
                        "Category": item["category"],
                        "Owner": item["owner"],
                        "Rating": item["rating"],
                    }
                    for item in current["items"]
                ]
            )
            edited = st.data_editor(
                editable, use_container_width=True, hide_index=True, num_rows="dynamic",
                key=f"items_{chosen_id}",
            )
            derived_count = sum(
                1 for item in current["items"] if item["source"] == "derived"
            )
            if derived_count:
                st.caption(
                    f"{derived_count} of these row(s) are computed from the project request. "
                    "Saving edited items replaces the whole list by hand - to keep them in "
                    "step with the request, edit the project request instead."
                )
            if st.button("Save items", key=f"save_items_{chosen_id}"):
                payload = [
                    {
                        "title": str(row["Item"]),
                        "detail": str(row["Detail"] or ""),
                        "category": str(row["Category"] or ""),
                        "owner": str(row["Owner"] or ""),
                        "rating": str(row["Rating"] or ""),
                    }
                    for _index, row in edited.iterrows()
                    if str(row["Item"]).strip()
                ]
                try:
                    client.blueprint_section_update(
                        blueprint_id, chosen_id, {"items": payload}
                    )
                    _load(blueprint_id)
                    st.success("Items saved.")
                    st.rerun()
                except ApiError as error:
                    show_error(error.message, error.details)

    with action_column:
        st.markdown("##### Regenerate")
        instruction = st.text_area(
            "Instruction (optional)", key=f"instr_{chosen_id}", height=100
        )
        regen_ai = st.checkbox("Use AI wording", value=True, key=f"ai_{chosen_id}")
        if st.button("Regenerate section", key=f"regen_{chosen_id}", use_container_width=True):
            try:
                client.blueprint_section_regenerate(
                    blueprint_id,
                    chosen_id,
                    instruction=instruction or None,
                    use_ai=regen_ai,
                )
                _load(blueprint_id)
                st.success("Regenerated.")
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)

        st.markdown("##### Approval")
        approver = st.text_input("Approved by", key=f"appr_{chosen_id}")
        approve_columns = st.columns(2)
        if approve_columns[0].button("Approve", key=f"do_appr_{chosen_id}"):
            try:
                client.blueprint_section_approve(blueprint_id, chosen_id, approver or "Reviewer")
                _load(blueprint_id)
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)
        if approve_columns[1].button("Withdraw", key=f"undo_appr_{chosen_id}"):
            try:
                client.blueprint_section_approve(
                    blueprint_id, chosen_id, approver or "Reviewer", approved=False
                )
                _load(blueprint_id)
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)

        if current["is_custom"]:
            st.markdown("##### Delete")
            if st.button("Delete this custom section", key=f"del_{chosen_id}", use_container_width=True):
                try:
                    client.blueprint_section_delete(blueprint_id, chosen_id)
                    _load(blueprint_id)
                    st.success("Deleted.")
                    st.rerun()
                except ApiError as error:
                    show_error(error.message, error.details)
        else:
            st.caption(
                "Standard sections cannot be deleted: a reader who finds twenty-nine headings "
                "cannot tell whether the thirtieth was considered and dropped or never written."
            )

    st.divider()
    st.markdown("##### Add a custom section")
    with st.form("add_section"):
        custom_title = st.text_input("Title")
        custom_kind = st.selectbox("Content kind", ["list", "table", "narrative"])
        custom_after = st.selectbox(
            "Place after",
            ["(at the end)"] + list(labels),
            format_func=lambda key: labels.get(key, key),
        )
        custom_narrative = st.text_area("Narrative", height=120)
        if st.form_submit_button("Add section"):
            try:
                client.blueprint_section_add(
                    blueprint_id,
                    {
                        "title": custom_title,
                        "content_kind": custom_kind,
                        "narrative": custom_narrative,
                        "after_section": None
                        if custom_after == "(at the end)"
                        else custom_after,
                    },
                )
                _load(blueprint_id)
                st.success("Added.")
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)

# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
with tab_versions:
    try:
        history = client.blueprint_versions(blueprint_id)
    except ApiError as error:
        history = {"versions": [], "current_version": 0, "total": 0}
        show_error(error.message, error.details)

    save_columns = st.columns([2, 2, 1])
    with save_columns[0]:
        version_label = st.text_input("Version label", value="", key="version_label")
    with save_columns[1]:
        version_by = st.text_input("Saved by", value=blueprint["owner"], key="version_by")
    with save_columns[2]:
        st.write("")
        if st.button("Save version", type="primary", use_container_width=True):
            try:
                client.blueprint_version_create(
                    blueprint_id, label=version_label, created_by=version_by
                )
                _load(blueprint_id)
                st.success("Version saved.")
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)

    if history["versions"]:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Version": item["version_number"],
                        "Label": item["label"],
                        "Saved by": item["created_by"],
                        "Sections": item["section_count"],
                        "Items": item["item_count"],
                        "Approved": item["approved_count"],
                        "Waiting for input": item["needs_input_count"],
                        "Saved at": item["created_at"],
                    }
                    for item in history["versions"]
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("##### Compare two versions")
        numbers = [item["version_number"] for item in history["versions"]]
        compare_columns = st.columns([1, 1, 1])
        from_version = compare_columns[0].selectbox("From", numbers, index=len(numbers) - 1)
        to_options = [0] + numbers
        to_version = compare_columns[1].selectbox(
            "To",
            to_options,
            index=0,
            format_func=lambda value: "current (unsaved)" if value == 0 else f"v{value}",
        )
        compare_columns[2].write("")
        if compare_columns[2].button("Compare", use_container_width=True):
            try:
                comparison = client.blueprint_version_compare(
                    blueprint_id, from_version, to_version
                )
                st.session_state["blueprint_comparison"] = comparison
            except ApiError as error:
                show_error(error.message, error.details)

        comparison = st.session_state.get("blueprint_comparison")
        if comparison and comparison["blueprint_id"] == blueprint_id:
            counts = st.columns(4)
            counts[0].metric("Added", comparison["sections_added"])
            counts[1].metric("Removed", comparison["sections_removed"])
            counts[2].metric("Modified", comparison["sections_modified"])
            counts[3].metric("Unchanged", comparison["sections_unchanged"])
            if comparison["reordered"]:
                st.info("The section order changed between these two versions.")

            changed = [
                diff for diff in comparison["section_diffs"] if diff["change"] != "unchanged"
            ]
            if not changed:
                st.success("Nothing changed between these two versions.")
            for diff in changed:
                with st.expander(f"{diff['change'].title()}: {diff['title']}"):
                    st.caption(
                        f"`{diff['section_key']}` · status {diff['status_from']} → "
                        f"{diff['status_to']}"
                        + (" · approval changed" if diff["approval_changed"] else "")
                    )
                    if diff["items_added"]:
                        st.write("**Items added:** " + ", ".join(diff["items_added"]))
                    if diff["items_removed"]:
                        st.write("**Items removed:** " + ", ".join(diff["items_removed"]))
                    if diff["items_changed"]:
                        st.write("**Items changed:** " + ", ".join(diff["items_changed"]))
                    if diff["narrative_diff"]:
                        st.code("\n".join(diff["narrative_diff"]), language="diff")
    else:
        st.caption("No versions saved yet. Save one to be able to compare against it later.")

# ---------------------------------------------------------------------------
# The project request behind this blueprint
# ---------------------------------------------------------------------------
with tab_project:
    st.caption(
        "Updating the project request rebuilds the sections whose rows are computed from it - "
        "the organisational structure, the module list, the integration register, the "
        "interface list, the migration sources and the security roles - and clears their "
        "approvals. A blueprint whose organisational structure disagrees with its own project "
        "request would be worse than one that is out of date."
    )
    project = blueprint["project"]
    with st.form("update_project"):
        updated: dict[str, Any] = {}
        text_columns = st.columns(3)
        for index, field in enumerate(
            ["company", "industry", "sap_product", "timeline"]
        ):
            with text_columns[index % 3]:
                updated[field] = st.text_area(
                    field.replace("_", " ").title(), value=str(project[field]), height=80
                )
        list_columns = st.columns(3)
        list_fields = [
            "modules",
            "business_objectives",
            "countries",
            "locations",
            "company_codes",
            "plants",
            "purchasing_organizations",
            "systems_involved",
            "integrations",
            "data_sources",
            "user_groups",
            "constraints",
            "assumptions",
        ]
        raw_lists: dict[str, str] = {}
        for index, field in enumerate(list_fields):
            with list_columns[index % 3]:
                raw_lists[field] = st.text_area(
                    field.replace("_", " ").title(),
                    value=_block(project[field]),
                    help=LIST_FIELD_HELP,
                    height=90,
                    key=f"proj_{field}",
                )
        updated["current_process"] = st.text_area(
            "Current process", value=project["current_process"], height=140
        )
        updated["desired_process"] = st.text_area(
            "Desired process", value=project["desired_process"], height=140
        )
        if st.form_submit_button("Update the project request", type="primary"):
            payload = {**updated, **{key: _lines(value) for key, value in raw_lists.items()}}
            try:
                st.session_state["blueprint"] = client.blueprint_update(
                    blueprint_id, {"project": payload}
                )
                st.success("Project request updated.")
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
with tab_export:
    st.caption(
        "Every format carries the disclaimer, the provenance of each section and the sections "
        "that are still waiting for project input."
    )
    export_columns = st.columns(4)
    for column, file_format in zip(export_columns, EXPORT_MIME):
        with column:
            if st.button(file_format.upper(), key=f"export_{file_format}", use_container_width=True):
                try:
                    st.session_state["blueprint_export"] = (
                        file_format,
                        client.blueprint_export(blueprint_id, file_format),
                    )
                except ApiError as error:
                    show_error(error.message, error.details)

    prepared = st.session_state.get("blueprint_export")
    if prepared:
        file_format, content = prepared
        st.download_button(
            f"Download the {file_format.upper()} file",
            data=content,
            file_name=f"blueprint_{blueprint_id[:8]}.{EXPORT_EXTENSIONS[file_format]}",
            mime=EXPORT_MIME[file_format],
            type="primary",
        )
        if file_format == "markdown":
            st.markdown("##### Preview")
            st.code(content.decode("utf-8")[:4000], language="markdown")

    st.divider()
    st.markdown("##### How this document was produced")
    try:
        catalogue = client.blueprint_catalog()
        methodology = catalogue["methodology"]
        st.write("**Decided by deterministic code:**")
        for item in methodology["deterministic"]:
            st.write(f"- {item}")
        st.write("**Written by a language model (when one was available):**")
        for item in methodology["ai_generated"]:
            st.write(f"- {item}")
        st.caption(
            "Sections a language model may describe but never add to: "
            + ", ".join(methodology["factual_sections_ai_cannot_add_to"])
        )
    except ApiError as error:
        show_error(error.message, error.details)

st.caption(PAGE_DISCLAIMER)
