"""Streamlit page for the SAP Test Case Generator.

Like every page in this app it contains no business logic. It collects the
process description, asks the FastAPI backend to generate a suite, and renders
what comes back. Every identifier, every priority, every step number and every
execution record is produced server-side, so a future React front end calling
the same endpoints gets the same suite.

The page is deliberately blunt about one thing: these are **drafts**. Nothing
here has been executed in an SAP system, and the page says which cases a model
wrote and which the deterministic templates filled.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from streamlit_app.components.api_client import ApiClient, ApiError  # noqa: E402
from streamlit_app.components.ui import disclaimer, origin_badge, show_error  # noqa: E402

st.set_page_config(page_title="SAP Test Case Generator", page_icon="🧪", layout="wide")

client = ApiClient()

PRIORITY_COLORS = {
    "critical": "#B3261E",
    "high": "#E8710A",
    "medium": "#F2C037",
    "low": "#3B8C4E",
}
RESULT_ICONS = {"passed": "✅", "failed": "❌", "blocked": "⛔", "not_run": "⚪"}
SOURCE_LABELS = {
    "ai_generated": "AI drafted",
    "template": "Template (no model)",
    "manual": "Added by hand",
    "duplicated": "Duplicated",
}
EXPORT_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "json": "application/json",
    "pdf": "application/pdf",
}

st.title("SAP Test Case Generator")
st.write(
    "Describe an SAP business process and get a structured test suite you can edit, approve, "
    "execute and export. The identifiers, the test-type coverage, the priorities and the step "
    "numbering are calculated by deterministic Python; only the wording of each case is drafted "
    "by the AI provider."
)
st.caption(
    "These are **draft** test cases produced from what you type below. Nothing here has been "
    "executed or validated in a live SAP system, and this application is not connected to one."
)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _priority_badge(priority: str) -> str:
    colour = PRIORITY_COLORS.get(priority, "#666666")
    return (
        f"<span style='background:{colour};color:#fff;padding:2px 8px;border-radius:10px;"
        f"font-size:0.75rem;'>{priority.upper()}</span>"
    )


def _cases_frame(cases: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Test Case ID": case["test_case_id"],
                "Type": case["test_type_label"],
                "Title": case["title"],
                "Priority": case["priority"],
                "Owner": case["owner"],
                "Status": case["status"],
                "Result": case["execution_result"]
                + (" (predates script)" if case["execution_is_stale"] else ""),
                "Steps": len(case["steps"]),
                "Drafted by": SOURCE_LABELS.get(case["source"], case["source"]),
                "Evidence": case["evidence_reference"],
            }
            for case in cases
        ]
    )


# ---------------------------------------------------------------------------
# Sidebar: backend status, demo processes, saved suites
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
                "Mock mode drafts complete, predictable test cases locally. No API key is "
                "needed and no request leaves this machine."
            )
    except ApiError as error:
        st.error(error.message)
        st.caption("Start the backend in a second terminal, then reload this page.")
        st.code("uvicorn app.main:app --reload", language="bash")
        st.stop()

    st.header("Demo processes")
    sample_choice = None
    try:
        sample = client.test_case_sample_info()
        if sample.get("available"):
            titles = {item["title"]: item["name"] for item in sample["processes"]}
            chosen_title = st.selectbox("Fictional process", list(titles), key="tcg_sample")
            sample_choice = titles[chosen_title]
            summary = next(
                item["summary"]
                for item in sample["processes"]
                if item["name"] == sample_choice
            )
            st.caption(summary)
            if st.button("Load into the form", use_container_width=True):
                st.session_state["tcg_loaded"] = client.test_case_sample(sample_choice)
                st.rerun()
        else:
            st.caption(
                "No demo processes found. Generate them with:\n"
                "`python scripts/generate_test_case_sample_data.py`"
            )
    except ApiError as error:
        show_error(error.message, error.details)

    st.header("Saved suites")
    try:
        listing = client.test_case_suites(limit=15)
        if listing["suites"]:
            labels = {
                f"{item['name'][:40]} ({item['test_case_count']} cases)": item["suite_id"]
                for item in listing["suites"]
            }
            picked = st.selectbox("Open a suite", ["-"] + list(labels), key="tcg_saved")
            if picked != "-" and st.button("Open", use_container_width=True):
                st.session_state["tcg_suite"] = client.test_case_suite(labels[picked])
                st.rerun()
        else:
            st.caption("No suite has been generated yet.")
    except ApiError as error:
        show_error(error.message, error.details)

    disclaimer()


# ---------------------------------------------------------------------------
# 1. The process form
# ---------------------------------------------------------------------------
loaded: dict[str, Any] = st.session_state.get("tcg_loaded", {})
prefill: dict[str, Any] = loaded.get("context", {}) if loaded else {}

try:
    catalog = client.test_case_catalog()
except ApiError as error:
    show_error(error.message, error.details)
    st.stop()

type_labels = {item["label"]: item["test_type"] for item in catalog["test_types"]}
type_descriptions = {item["test_type"]: item["description"] for item in catalog["test_types"]}

st.subheader("1. Describe the process")

with st.form("tcg_process_form"):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        sap_product = st.text_input(
            "SAP product", value=prefill.get("sap_product", "SAP S/4HANA 2023")
        )
    with col_b:
        sap_module = st.text_input("SAP module", value=prefill.get("sap_module", "MM"))
    with col_c:
        business_process = st.text_input(
            "Business process",
            value=prefill.get("business_process", "Procure to Pay - standard purchase order"),
        )

    process_description = st.text_area(
        "Process description",
        value=prefill.get("process_description", ""),
        height=140,
        help="What the process does, in your own words. The more concrete, the better the draft.",
        placeholder=(
            "A requisitioner raises a purchase requisition, a buyer converts it into a purchase "
            "order, the warehouse posts the goods receipt and accounts payable posts the invoice."
        ),
    )

    col_1, col_2 = st.columns(2)
    with col_1:
        preconditions = st.text_area(
            "Preconditions (one per line)",
            value="\n".join(prefill.get("preconditions", [])),
            height=110,
        )
        systems_involved = st.text_area(
            "Systems involved (one per line)",
            value="\n".join(prefill.get("systems_involved", [])),
            height=90,
        )
        user_roles = st.text_area(
            "User roles (one per line)",
            value="\n".join(prefill.get("user_roles", [])),
            height=90,
        )
    with col_2:
        business_rules = st.text_area(
            "Business rules (one per line)",
            value="\n".join(prefill.get("business_rules", [])),
            height=110,
        )
        integrations = st.text_area(
            "Integrations (one per line)",
            value="\n".join(prefill.get("integrations", [])),
            height=90,
        )
        test_data_requirements = st.text_area(
            "Test data requirements (one per line)",
            value="\n".join(prefill.get("test_data_requirements", [])),
            height=90,
        )

    st.markdown("**2. Choose the test types and the size of the suite**")
    default_labels = [
        label
        for label, value in type_labels.items()
        if value in (loaded.get("suggested_test_types") or ["sit", "uat", "negative"])
    ]
    chosen_labels = st.multiselect(
        "Test types",
        list(type_labels),
        default=default_labels,
        help=(
            "Types are covered in the order you pick them. If you ask for fewer test cases "
            "than types, the ones you picked last go without a case - and the suite says so."
        ),
    )
    col_x, col_y, col_z = st.columns(3)
    with col_x:
        test_case_count = st.number_input(
            "Number of test cases",
            min_value=1,
            max_value=int(catalog["max_test_cases"]),
            value=int(loaded.get("suggested_test_case_count", 8)),
        )
    with col_y:
        default_owner = st.text_input("Default owner (optional)", value="")
    with col_z:
        use_ai = st.checkbox(
            "Draft the wording with AI",
            value=True,
            help=(
                "Off means the deterministic templates write every case. The suite is complete "
                "either way - identifiers, coverage and priorities are identical."
            ),
        )

    generate_clicked = st.form_submit_button("Generate test cases", type="primary")

with st.expander("What each test type covers"):
    for label, value in type_labels.items():
        st.markdown(f"**{label}** - {type_descriptions[value]}")

if generate_clicked:
    if not chosen_labels:
        st.error("Choose at least one test type.")
    else:
        context = {
            "sap_product": sap_product,
            "sap_module": sap_module,
            "business_process": business_process,
            "process_description": process_description,
            "preconditions": _lines(preconditions),
            "business_rules": _lines(business_rules),
            "systems_involved": _lines(systems_involved),
            "integrations": _lines(integrations),
            "user_roles": _lines(user_roles),
            "test_data_requirements": _lines(test_data_requirements),
        }
        try:
            with st.spinner("Planning the suite and drafting the test cases..."):
                st.session_state["tcg_suite"] = client.test_case_generate(
                    context,
                    test_types=[type_labels[label] for label in chosen_labels],
                    test_case_count=int(test_case_count),
                    default_owner=default_owner or None,
                    use_ai=use_ai,
                )
            st.session_state.pop("tcg_loaded", None)
            st.rerun()
        except ApiError as error:
            show_error(error.message, error.details)


suite: dict[str, Any] | None = st.session_state.get("tcg_suite")
if not suite:
    st.info("Fill in the process above, or load a demo process from the sidebar, then generate.")
    st.stop()


def refresh() -> None:
    """Reload the open suite from the API after a change."""
    st.session_state["tcg_suite"] = client.test_case_suite(suite["suite_id"])


# ---------------------------------------------------------------------------
# 3. The suite
# ---------------------------------------------------------------------------
st.divider()
st.subheader(f"3. {suite['name']}")

summary = suite["summary"]
cols = st.columns(6)
cols[0].metric("Test cases", summary["test_case_count"])
cols[1].metric("Steps", summary["step_count"])
cols[2].metric("AI drafted", summary["ai_drafted_count"])
cols[3].metric("Approved", summary["approved_count"])
cols[4].metric("Executed", summary["executed_count"])
cols[5].metric(
    "Pass rate",
    "-" if summary["pass_rate_pct"] is None else f"{summary['pass_rate_pct']}%",
    help="Of the runs that reached a verdict. Blocked runs have no verdict and are excluded.",
)

if summary["stale_execution_count"]:
    st.warning(
        f"{summary['stale_execution_count']} recorded result(s) were reached against a script "
        "that has since been edited or redrafted. They are kept but marked, because a verdict "
        "against steps that no longer exist is not a verdict about this suite. Re-run those "
        "test cases and record the result again."
    )

ai_info = suite["ai"]
st.caption(
    f"Wording origin: **{origin_badge(ai_info.get('origin'))}** "
    f"(provider: {ai_info.get('provider') or 'none'}, "
    f"prompt: {ai_info.get('prompt_version') or '-'}) - "
    f"identifiers, coverage, priorities and step numbering are rule-based. "
    f"Config v{suite['config_version']}, engine v{suite['engine_version']}."
)
if ai_info.get("error"):
    st.warning(
        f"The AI provider was not usable ({ai_info['error']}) so the deterministic templates "
        "filled every case. The suite is complete."
    )
for note in suite.get("notes", []):
    st.info(note)
if suite.get("injection_detected"):
    st.warning(
        "The process description contained text written as an instruction to an automated "
        "system. It was filtered before drafting and was never acted on. Fields: "
        + ", ".join(suite["injection_markers"])
    )
if suite.get("uncovered_test_types"):
    st.warning(
        "No test case could be allocated to: "
        + ", ".join(suite["uncovered_test_types"])
        + ". Raise the test-case count and generate again to cover them."
    )

with st.expander("Coverage by test type", expanded=True):
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Test type": item["label"],
                    "Planned": item["planned"],
                    "In suite": item["generated"],
                    "AI drafted": item["ai_drafted"],
                    "From template": item["template_built"],
                    "Added by hand": item["manual"],
                }
                for item in suite["coverage"]
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Coverage counts test cases per type. It says nothing about how much of the SAP "
        "process is functionally covered."
    )

if suite.get("generation_issues"):
    with st.expander(f"Drafting issues ({len(suite['generation_issues'])})"):
        st.caption(
            "Each of these was recovered from: the deterministic template filled the gap and "
            "the suite kept the test case."
        )
        st.dataframe(
            pd.DataFrame(suite["generation_issues"]), use_container_width=True, hide_index=True
        )


# ---------------------------------------------------------------------------
# 4. The editable table
# ---------------------------------------------------------------------------
st.subheader("4. Test cases")

cases: list[dict[str, Any]] = suite["test_cases"]
by_id = {case["test_case_id"]: case for case in cases}

edited = st.data_editor(
    _cases_frame(cases),
    use_container_width=True,
    hide_index=True,
    disabled=["Test Case ID", "Type", "Steps", "Drafted by", "Result"],
    column_config={
        "Priority": st.column_config.SelectboxColumn(options=catalog["priorities"]),
        "Status": st.column_config.SelectboxColumn(options=catalog["statuses"]),
        "Title": st.column_config.TextColumn(width="large"),
    },
    key="tcg_table",
)

if st.button("Save table edits"):
    original = _cases_frame(cases)
    changed = 0
    errors: list[str] = []
    for index, row in edited.iterrows():
        before = original.loc[index]
        payload: dict[str, Any] = {}
        for column, field in (
            ("Title", "title"),
            ("Priority", "priority"),
            ("Owner", "owner"),
            ("Status", "status"),
            ("Evidence", "evidence_reference"),
        ):
            if str(row[column]) != str(before[column]):
                payload[field] = row[column]
        if not payload:
            continue
        try:
            client.test_case_update(by_id[row["Test Case ID"]]["id"], payload)
            changed += 1
        except ApiError as error:
            errors.append(f"{row['Test Case ID']}: {error.message}")
    for message in errors:
        st.error(message)
    if changed:
        st.success(f"Saved {changed} change(s).")
        refresh()
        st.rerun()
    elif not errors:
        st.info("Nothing changed in the table.")


# ---------------------------------------------------------------------------
# 5. The step editor and the execution record
# ---------------------------------------------------------------------------
st.subheader("5. Edit one test case")

selected_id = st.selectbox(
    "Test case",
    [case["test_case_id"] for case in cases],
    format_func=lambda value: f"{value} - {by_id[value]['title'][:60]}",
)
case = by_id[selected_id]

head_left, head_right = st.columns([3, 1])
with head_left:
    st.markdown(
        f"### {case['test_case_id']} {_priority_badge(case['priority'])}",
        unsafe_allow_html=True,
    )
    st.caption(
        f"{case['test_type_label']} - focus chosen by the planner - "
        f"drafted by {SOURCE_LABELS.get(case['source'], case['source'])} "
        f"({origin_badge(case['output_origin'])}) - "
        f"regenerated {case['regenerated_count']} time(s)"
    )
with head_right:
    st.metric("Result", f"{RESULT_ICONS.get(case['execution_result'], '')} {case['execution_result']}")

if case["execution_is_stale"]:
    st.warning(
        "The result recorded below was reached against an earlier version of these steps. "
        "Re-run the test and record the result again to clear this."
    )
for note in case.get("validation_notes", []):
    st.caption(f"Drafting note: {note}")

script_tab, execution_tab, actions_tab = st.tabs(
    ["Script", "Execution result", "Regenerate, duplicate, delete"]
)

with script_tab:
    with st.form(f"tcg_script_{case['id']}"):
        title = st.text_input("Title", value=case["title"])
        objective = st.text_area("Objective", value=case["objective"], height=80)
        col_p, col_d = st.columns(2)
        with col_p:
            preconditions_text = st.text_area(
                "Preconditions (one per line)",
                value="\n".join(case["preconditions"]),
                height=140,
            )
        with col_d:
            test_data_text = st.text_area(
                "Test data (one per line)", value="\n".join(case["test_data"]), height=140
            )

        st.markdown("**Test steps** - the numbering is rewritten by the backend on save.")
        steps_frame = st.data_editor(
            pd.DataFrame(
                [
                    {
                        "Step": step["step_number"],
                        "Action": step["action"],
                        "Step test data": step.get("test_data") or "",
                        "Step expected result": step.get("expected_result") or "",
                    }
                    for step in case["steps"]
                ]
            ),
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            disabled=["Step"],
            key=f"tcg_steps_{case['id']}",
        )
        expected_result = st.text_area(
            "Overall expected result", value=case["expected_result"], height=80
        )
        owner = st.text_input("Owner", value=case["owner"])
        comments = st.text_area("Comments", value=case["comments"], height=70)

        if st.form_submit_button("Save this test case", type="primary"):
            steps = [
                {
                    "action": str(row["Action"]).strip(),
                    "test_data": str(row["Step test data"]).strip() or None,
                    "expected_result": str(row["Step expected result"]).strip() or None,
                }
                for _, row in steps_frame.iterrows()
                if str(row["Action"]).strip()
            ]
            if not steps:
                st.error("A test case must keep at least one step.")
            else:
                try:
                    client.test_case_update(
                        case["id"],
                        {
                            "title": title,
                            "objective": objective,
                            "preconditions": _lines(preconditions_text),
                            "test_data": _lines(test_data_text),
                            "steps": steps,
                            "expected_result": expected_result,
                            "owner": owner,
                            "comments": comments,
                        },
                    )
                    st.success("Saved.")
                    refresh()
                    st.rerun()
                except ApiError as error:
                    show_error(error.message, error.details)

with execution_tab:
    st.caption(
        "Recording an execution never changes the script, and regenerating the script never "
        "erases what you record here."
    )
    approver = st.text_input("Approved by", value=case["approved_by"] or "")
    col_ok, col_undo = st.columns(2)
    with col_ok:
        if st.button("Approve this test", use_container_width=True):
            if not approver.strip():
                st.error("Enter who is approving the test.")
            else:
                try:
                    client.test_case_approve(case["id"], approver.strip())
                    refresh()
                    st.rerun()
                except ApiError as error:
                    show_error(error.message, error.details)
    with col_undo:
        if st.button("Remove approval", use_container_width=True, disabled=not case["approved_at"]):
            try:
                client.test_case_approve(
                    case["id"], case["approved_by"] or "unknown", approved=False
                )
                refresh()
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)

    with st.form(f"tcg_exec_{case['id']}"):
        result = st.radio(
            "Pass or fail",
            catalog["execution_results"],
            index=catalog["execution_results"].index(case["execution_result"]),
            horizontal=True,
        )
        actual_result = st.text_area("Actual result", value=case["actual_result"], height=110)
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            executed_by = st.text_input("Executed by", value=case["executed_by"] or "")
        with col_e2:
            evidence = st.text_input("Evidence reference", value=case["evidence_reference"])
        if st.form_submit_button("Record execution result", type="primary"):
            try:
                client.test_case_execution(
                    case["id"],
                    execution_result=result,
                    actual_result=actual_result,
                    executed_by=executed_by or None,
                    evidence_reference=evidence,
                )
                st.success("Execution recorded.")
                refresh()
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)

with actions_tab:
    st.markdown("**Redraft this test case**")
    st.caption(
        "The identifier and its place in the suite are kept. The approval is cleared, because "
        "it belonged to the script that is being replaced."
    )
    instruction = st.text_input(
        "Instruction for the redraft (optional)",
        placeholder="Focus on the second release step for orders above 10,000 EUR",
    )
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        keep_execution = st.checkbox("Keep the execution record", value=True)
    with col_r2:
        redraft_with_ai = st.checkbox("Redraft with AI", value=True)
    if st.button("Regenerate this test case", type="primary"):
        try:
            client.test_case_regenerate(
                case["id"],
                instruction=instruction or None,
                use_ai=redraft_with_ai,
                keep_execution_record=keep_execution,
            )
            st.success("Redrafted.")
            refresh()
            st.rerun()
        except ApiError as error:
            show_error(error.message, error.details)

    st.divider()
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        if st.button("Duplicate this test case", use_container_width=True):
            try:
                created = client.test_case_duplicate(case["id"])
                st.success(f"Created {created['test_case_id']}.")
                refresh()
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)
    with col_d2:
        if st.button("Delete this test case", use_container_width=True):
            try:
                removed = client.test_case_delete(case["id"])
                if removed["lost_test_types"]:
                    st.warning(
                        "The suite no longer covers: "
                        + ", ".join(removed["lost_test_types"])
                    )
                st.success(f"Deleted {removed['test_case_id']}.")
                refresh()
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)


# ---------------------------------------------------------------------------
# 6. Add a test case
# ---------------------------------------------------------------------------
st.subheader("6. Add a test case")
with st.form("tcg_add"):
    col_n1, col_n2 = st.columns([1, 3])
    with col_n1:
        new_type_label = st.selectbox("Test type", list(type_labels))
    with col_n2:
        new_title = st.text_input("Title", placeholder="Purchase order output is re-sent")
    new_objective = st.text_area("Objective (optional)", height=70)
    st.caption(
        "Leave the steps empty and the configured template steps for the chosen type are used, "
        "so the added row is a usable test rather than an empty shell."
    )
    if st.form_submit_button("Add test case"):
        if len(new_title.strip()) < 3:
            st.error("Enter a title of at least three characters.")
        else:
            try:
                created = client.test_case_add(
                    suite["suite_id"],
                    {
                        "test_type": type_labels[new_type_label],
                        "title": new_title.strip(),
                        "objective": new_objective,
                    },
                )
                st.success(f"Added {created['test_case_id']}.")
                refresh()
                st.rerun()
            except ApiError as error:
                show_error(error.message, error.details)


# ---------------------------------------------------------------------------
# 7. Export
# ---------------------------------------------------------------------------
st.subheader("7. Export")
st.caption(
    "CSV and XLSX carry the test-case table (XLSX adds a row-per-step sheet and the coverage "
    "and methodology sheets). JSON carries everything. PDF is the readable test script."
)
export_columns = st.columns(4)
for column, file_format in zip(export_columns, ("csv", "xlsx", "json", "pdf")):
    with column:
        try:
            payload = client.test_case_export(suite["suite_id"], file_format)
            st.download_button(
                f"Download .{file_format}",
                data=payload,
                file_name=f"test_suite_{suite['suite_id'][:8]}.{file_format}",
                mime=EXPORT_MIME[file_format],
                use_container_width=True,
            )
        except ApiError as error:
            st.caption(error.message)

st.caption(catalog["disclaimer"])
