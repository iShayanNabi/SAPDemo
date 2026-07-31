"""Streamlit page for the Contract Assistant.

Like every page in this app it contains no business logic: it uploads a
contract document, asks the FastAPI backend to extract and analyse it, and
renders what comes back. Every clause, date, obligation and risk is produced
server-side by the deterministic engine in ``app/modules/contract_assistant``,
with a page number, a section heading, an excerpt and a confidence score
attached.

The page is deliberately blunt about two things:

* a scanned document is reported as unprocessable, not analysed as empty;
* text found inside an uploaded contract is data. If a document tries to
  instruct the application, the page shows that as a finding.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from streamlit_app.components.api_client import ApiClient, ApiError  # noqa: E402
from streamlit_app.components.ui import (  # noqa: E402
    disclaimer,
    origin_badge,
    severity_badge,
    show_error,
)

st.set_page_config(page_title="Contract Assistant", page_icon="📄", layout="wide")

client = ApiClient()

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
BAND_COLORS = {
    "low": "#3B8C4E",
    "medium": "#F2C037",
    "high": "#E8710A",
    "critical": "#B3261E",
}
IMPORTANCE_ICONS = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
}

EXPORT_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "json": "application/json",
}

st.title("Contract Assistant")
st.write(
    "Upload a contract, and the assistant extracts its clauses, key dates, obligations and "
    "risks - each with the page it came from, the heading it sat under, a supporting excerpt "
    "and a confidence score. Then ask questions and get answers built from those same "
    "extractions, with citations."
)
st.caption(
    "Extraction is deterministic pattern matching, not a language model. This is an assistive "
    "review, **not legal advice**."
)


# ---------------------------------------------------------------------------
# Sidebar: backend, capability and sample contracts
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
    except ApiError as error:
        st.error(error.message)
        st.caption("Start the backend in a second terminal, then reload this page.")
        st.code("uvicorn app.main:app --reload", language="bash")
        st.stop()

    st.header("Supported documents")
    try:
        capability = client.contract_extractors()
        st.write("**Works with no extra setup:** " + ", ".join(capability["document_extensions"]))
        ocr = capability["ocr"]
        if ocr["ocr_available"]:
            st.success(f"OCR provider active: {ocr['resolved_provider']}")
        else:
            st.warning("No OCR provider configured - scanned documents cannot be processed.")
        with st.expander("OCR providers"):
            for provider in ocr["providers"]:
                if provider["provider"] == "none":
                    continue
                state = "available" if provider["available"] else "not configured"
                st.write(f"**{provider['label']}** - {state}")
                st.caption(provider["cost_note"])
                st.caption(provider["setup_hint"])
    except ApiError as error:
        show_error(error.message, error.details)

    st.header("Demo contracts")
    try:
        sample = client.contract_sample_info()
        if sample.get("available"):
            st.caption(
                f"{sample['contract_count']} fictional contracts, "
                f"{sample['scenario_count']} documented scenarios."
            )
            names = {item["title"]: item["name"] for item in sample["contracts"]}
            chosen_title = st.selectbox("Contract", list(names), key="sample_choice")
            chosen_format = st.radio(
                "Format", ["pdf", "docx", "txt"], horizontal=True, key="sample_format"
            )
            stem = f"sample_contract_{names[chosen_title]}"
            try:
                payload = client.contract_sample_file(stem, chosen_format)
                st.download_button(
                    f"Download .{chosen_format}",
                    data=payload,
                    file_name=f"{stem}.{chosen_format}",
                    mime=MIME_TYPES[chosen_format],
                    use_container_width=True,
                )
            except ApiError as error:
                st.caption(error.message)
            summary = next(
                item["summary"] for item in sample["contracts"] if item["name"] == names[chosen_title]
            )
            st.caption(summary)
        else:
            st.caption("Run: python scripts/generate_contract_sample_data.py")
    except ApiError:
        pass


# ---------------------------------------------------------------------------
# Presentation helpers - formatting only, no contract logic lives here
# ---------------------------------------------------------------------------
def _plain(value: Any, fallback: str = "not stated") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _confidence(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


def _band_chip(band: str | None, score: float) -> str:
    colour = BAND_COLORS.get((band or "").lower(), "#666666")
    return (
        f"<span style='background:{colour};color:#fff;padding:3px 10px;border-radius:12px;"
        f"font-size:0.85rem;'>{(band or 'unknown').upper()} &middot; {score:g}/100</span>"
    )


def _reference_caption(record: dict[str, Any]) -> str:
    parts = []
    if record.get("page_number"):
        parts.append(f"page {record['page_number']}")
    if record.get("section_heading"):
        parts.append(f"“{record['section_heading']}”")
    if record.get("confidence") is not None:
        parts.append(f"confidence {_confidence(record['confidence'])}")
    return " &middot; ".join(parts) if parts else "no source reference"


def _clause_frame(clauses: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Clause": clause["label"],
                "Found": "Yes" if clause["present"] else "No",
                "Required": "Yes" if clause["required"] else "No",
                "Importance": clause["importance"],
                "Confidence": clause["confidence"] if clause["present"] else None,
                "Review?": "Check page" if clause.get("needs_review") else "",
                "Page": clause.get("page_number"),
                "Section heading": clause.get("section_heading") or "",
                "Extracted values": ", ".join(
                    f"{key}={value}" for key, value in (clause.get("values") or {}).items()
                ),
                "Supporting excerpt": clause.get("excerpt", "")[:300],
            }
            for clause in clauses
        ]
    )


def _risk_frame(risks: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "Severity": risk["severity"].upper(),
                "Rule": risk["rule_id"],
                "Category": risk["category"],
                "Finding": risk["title"],
                "Explanation (rule-based)": risk["explanation"],
                "Recommended action": risk["recommended_action"],
                "Page": risk.get("page_number"),
                "Section heading": risk.get("section_heading") or "",
                "Supporting excerpt": (risk.get("excerpt") or "")[:250],
            }
            for risk in risks
        ]
    )
    if frame.empty:
        return frame
    frame["_order"] = frame["Severity"].str.lower().map(SEVERITY_ORDER).fillna(9)
    return frame.sort_values(["_order", "Rule"]).drop(columns="_order")


def _obligation_frame(obligations: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ID": item["obligation_id"],
                "Party": item.get("party") or item.get("party_role") or "not attributed",
                "Duty type": item["duty_type"],
                "Prohibition": "Yes" if item.get("is_prohibition") else "",
                "Page": item.get("page_number"),
                "Section heading": item.get("section_heading") or "",
                "Obligation (verbatim)": item["text"],
                "Confidence": item.get("confidence"),
            }
            for item in obligations
        ]
    )


# ---------------------------------------------------------------------------
# 1. Upload
# ---------------------------------------------------------------------------
st.subheader("1. Upload a contract")

uploaded = st.file_uploader(
    "Text-based PDF, DOCX or TXT",
    type=["pdf", "docx", "txt", "md"],
    help=(
        "A text-based PDF works with no extra setup. A scanned document needs an OCR provider; "
        "if none is configured the assistant will say so rather than analysing an empty file."
    ),
)

if uploaded is not None and st.button("Upload and extract text", type="primary"):
    try:
        extension = Path(uploaded.name).suffix.lstrip(".").lower()
        result = client.contract_upload(
            uploaded.name, uploaded.getvalue(), MIME_TYPES.get(extension, "application/octet-stream")
        )
        st.session_state["contract"] = result
        st.session_state.pop("analysis", None)
        st.session_state.pop("chat_history", None)
    except ApiError as error:
        show_error(error.message, error.details)

contract = st.session_state.get("contract")

if contract:
    st.subheader("2. Extraction status")
    extraction = contract["extraction"]
    columns = st.columns(5)
    columns[0].metric("Pages", contract["page_count"])
    columns[1].metric("Characters", f"{contract['char_count']:,}")
    columns[2].metric("Extractor", extraction["extractor"])
    columns[3].metric("Page basis", extraction["page_basis"])
    columns[4].metric("OCR used", "Yes" if extraction["ocr_used"] else "No")

    if contract["status"] == "needs_ocr":
        st.error(contract["message"], icon="🚫")
    else:
        st.success(contract["message"], icon="✅")
    for note in extraction.get("notes", []):
        st.caption(f"• {note}")

    with st.expander("Extracted text preview"):
        for page in contract.get("preview", []):
            st.markdown(f"**Page {page['page_number']}** ({page['char_count']:,} characters)")
            st.text(page["preview"])

    # -----------------------------------------------------------------------
    # 3. Analyse
    # -----------------------------------------------------------------------
    st.subheader("3. Analyse")
    left, middle, right = st.columns([2, 2, 3])
    as_of = left.date_input(
        "Assessment date",
        value=date.today(),
        help="Expiry and notice-deadline windows are measured against this date.",
    )
    want_ai = middle.checkbox(
        "Add AI summary",
        value=False,
        help=(
            "Optional. The AI only explains results the engine already computed; it never "
            "extracts a clause or decides a risk."
        ),
    )

    if right.button(
        "Extract clauses, dates and risks",
        type="primary",
        disabled=not contract["is_analyzable"],
        use_container_width=True,
    ):
        with st.spinner("Analysing the contract…"):
            try:
                st.session_state["analysis"] = client.contract_analyze(
                    contract["contract_id"],
                    as_of_date=as_of.isoformat(),
                    generate_ai_summary=want_ai,
                )
                st.session_state.pop("chat_history", None)
            except ApiError as error:
                show_error(error.message, error.details)

    if not contract["is_analyzable"]:
        st.info(
            "This document has no extractable text, so there is nothing to analyse. Upload a "
            "text-based version, or configure an OCR provider.",
            icon="ℹ️",
        )

analysis = st.session_state.get("analysis")

if analysis:
    summary = analysis["summary"]

    # -----------------------------------------------------------------------
    # 4. Contract summary
    # -----------------------------------------------------------------------
    st.subheader("4. Contract summary")
    st.markdown(f"### {_plain(analysis['contract_title'], 'Title not extracted')}")
    st.markdown(_band_chip(summary["risk_band"], summary["risk_score"]), unsafe_allow_html=True)

    if analysis["summary"]["injection_detected"]:
        st.error(
            "This document contains text written as an instruction to an automated system. It "
            "was treated strictly as data: nothing in it was executed, and it did not change "
            "any extraction. See the risk findings below.",
            icon="🛡️",
        )

    metrics = st.columns(5)
    metrics[0].metric(
        "Clauses found", f"{summary['clauses_found']} / {summary['clauses_expected']}"
    )
    metrics[1].metric("Missing required", summary["missing_clause_count"])
    metrics[2].metric("Obligations", summary["obligation_count"])
    metrics[3].metric("Risk findings", summary["risk_count"])
    metrics[4].metric("Sections detected", summary["section_count"])

    if analysis["parties"]:
        st.markdown("**Parties**")
        for party in analysis["parties"]:
            role = f" — *{party['role']}*" if party.get("role") else ""
            st.markdown(f"- **{party['name']}**{role}")
            st.caption(_reference_caption(party), unsafe_allow_html=True)
    else:
        st.caption("No party names could be extracted from this document.")

    if analysis["ai_narrative"]["available"]:
        with st.container(border=True):
            st.markdown(
                f"**AI summary** ({origin_badge(analysis['ai_narrative']['origin'])} — explains "
                f"the extraction, never a source of it)"
            )
            st.write(analysis["ai_narrative"]["summary"])
            for item in analysis["ai_narrative"]["key_findings"]:
                st.markdown(f"- {item}")
    elif analysis["ai_narrative"]["error"]:
        st.warning(
            f"The AI summary was unavailable: {analysis['ai_narrative']['error']} "
            f"The extraction below is unaffected."
        )

    # -----------------------------------------------------------------------
    # 5. Key dates
    # -----------------------------------------------------------------------
    st.subheader("5. Key dates")
    dates = analysis["key_dates"]
    st.caption(
        "‘Basis’ says whether a date was printed in the document (**stated**) or computed from "
        "other values (**derived_…**). A derived date is never presented as one the contract "
        "actually stated."
    )
    date_rows = [
        ("Effective date", "effective_date"),
        ("Expiration date", "expiration_date"),
        ("Renewal date", "renewal_date"),
        ("Notice deadline", "notice_deadline"),
        ("Signature date", "signature_date"),
    ]
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Date": label,
                    "Value": _plain(dates.get(key)),
                    "Basis": _plain(dates.get(f"{key}_basis"), "-"),
                    "Page": dates.get(f"{key}_page"),
                    "Supporting excerpt": _plain(dates.get(f"{key}_excerpt"), "-"),
                }
                for label, key in date_rows
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    term_columns = st.columns(4)
    term_columns[0].metric("Auto-renewal", "Yes" if dates.get("auto_renewal") else "No")
    term_columns[1].metric("Initial term", _plain(dates.get("term_length_label"), "-"))
    term_columns[2].metric("Notice period", _plain(dates.get("notice_period_label"), "-"))
    term_columns[3].metric("Renewal term", _plain(dates.get("renewal_term_label"), "-"))

    if dates.get("days_to_expiration") is not None:
        days = dates["days_to_expiration"]
        if days < 0:
            st.error(f"This contract expired {abs(days)} day(s) ago.", icon="⏰")
        elif days <= 90:
            st.warning(f"This contract expires in {days} day(s).", icon="⏰")
    if dates.get("days_to_notice_deadline") is not None and dates.get("auto_renewal"):
        days = dates["days_to_notice_deadline"]
        if days < 0:
            st.error(
                f"The notice deadline to prevent automatic renewal passed {abs(days)} day(s) "
                f"ago.",
                icon="🔁",
            )
        elif days <= 45:
            st.warning(f"Notice to prevent renewal is due in {days} day(s).", icon="🔁")

    # -----------------------------------------------------------------------
    # 6-9. Clauses, obligations, risks, missing clauses
    # -----------------------------------------------------------------------
    clause_tab, obligation_tab, risk_tab, missing_tab, source_tab = st.tabs(
        ["Clauses", "Obligations", "Risk findings", "Missing clauses", "Source references"]
    )

    with clause_tab:
        st.caption(
            "Every found clause carries the page, the heading, an excerpt and a confidence "
            "score. A clause below the review threshold is marked ‘Check page’."
        )
        only_found = st.checkbox("Show found clauses only", value=False)
        clauses = [c for c in analysis["clauses"] if c["present"] or not only_found]
        st.dataframe(_clause_frame(clauses), use_container_width=True, hide_index=True)

    with obligation_tab:
        st.caption(
            "Each obligation is quoted verbatim from the document. A party is named only when "
            "the sentence actually names one - it is never guessed."
        )
        if analysis["obligations"]:
            st.dataframe(
                _obligation_frame(analysis["obligations"]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No obligation sentences were extracted from this document.")

    with risk_tab:
        st.caption("Findings come from the configured rules. They are not legal advice.")
        if analysis["risks"]:
            counts = summary["severity_counts"]
            badge_row = " ".join(
                severity_badge(level) + f" {counts.get(level, 0)}"
                for level in ("critical", "high", "medium", "low")
            )
            st.markdown(badge_row, unsafe_allow_html=True)
            st.dataframe(_risk_frame(analysis["risks"]), use_container_width=True, hide_index=True)
        else:
            st.success("No contract rule was triggered by this document.")

        if analysis["rule_errors"]:
            st.warning(
                f"{len(analysis['rule_errors'])} rule(s) failed and were skipped. The other "
                f"rules still produced findings."
            )
            st.json(analysis["rule_errors"])

    with missing_tab:
        if analysis["missing_clauses"]:
            for item in analysis["missing_clauses"]:
                icon = IMPORTANCE_ICONS.get(item["importance"], "•")
                st.markdown(f"{icon} **{item['label']}** ({item['importance']} importance)")
                st.caption(item["message"])
        else:
            st.success("Every clause type the configuration marks as required was found.")

    with source_tab:
        st.caption(
            "Every reference the analysis produced, so any statement on this page can be "
            "checked against the original document."
        )
        references = []
        for clause in analysis["clauses"]:
            for reference in clause.get("references", []):
                references.append(
                    {
                        "Source of": clause["label"],
                        "Page": reference.get("page_number"),
                        "Section heading": reference.get("section_heading") or "",
                        "Confidence": reference.get("confidence"),
                        "Excerpt": reference.get("excerpt", ""),
                    }
                )
        if references:
            st.dataframe(pd.DataFrame(references), use_container_width=True, hide_index=True)
        else:
            st.info("No source references were produced.")

        if analysis["injection_markers"]:
            st.markdown("**Instruction-like text found in this document (neutralised, not run)**")
            for marker in analysis["injection_markers"]:
                st.code(marker, language=None)

    # -----------------------------------------------------------------------
    # 10. Contract chat
    # -----------------------------------------------------------------------
    st.subheader("6. Ask this contract a question")
    st.caption(
        "Answers are built from the extracted clauses and cite the page they came from. When "
        "the contract does not cover a question, the assistant says so."
    )

    try:
        suggestions = client.contract_methodology()["suggested_questions"]
    except ApiError:
        suggestions = ["What are the payment terms?", "When does this contract expire?"]

    history = st.session_state.setdefault("chat_history", [])

    picked = st.selectbox("Suggested questions", ["(type your own)"] + suggestions)
    default_question = "" if picked == "(type your own)" else picked
    question = st.text_input("Question", value=default_question, key="contract_question")
    ask_columns = st.columns([1, 1, 4])
    rephrase = ask_columns[1].checkbox("AI rephrasing", value=False)

    if ask_columns[0].button("Ask", type="primary") and question.strip():
        try:
            history.append(
                client.contract_question(
                    analysis["contract_id"], question, generate_ai_summary=rephrase
                )
            )
        except ApiError as error:
            show_error(error.message, error.details)

    for entry in reversed(history):
        with st.container(border=True):
            st.markdown(f"**Q:** {entry['question']}")
            if entry["answered"]:
                st.markdown(f"**A:** *(intent: {entry['intent']})*")
            else:
                st.markdown(f"**A:** *(not covered - {entry['unavailable_reason']})*")
            st.text(entry["answer"])

            if entry["citations"]:
                st.markdown("**Sources**")
                for citation in entry["citations"]:
                    st.caption(_reference_caption(citation), unsafe_allow_html=True)
                    st.markdown(f"> {citation['excerpt']}")
            if entry["ai_narrative"]["available"]:
                st.caption(
                    f"AI rephrasing ({origin_badge(entry['ai_narrative']['origin'])}): "
                    f"{entry['ai_narrative']['summary']}"
                )
            if entry["follow_up_suggestions"]:
                st.caption("Try next: " + " · ".join(entry["follow_up_suggestions"]))

    # -----------------------------------------------------------------------
    # 11. Export
    # -----------------------------------------------------------------------
    st.subheader("7. Export")
    st.caption(
        "Every export carries the page, heading, excerpt and confidence for each row, plus the "
        "standing disclaimer."
    )
    export_columns = st.columns(3)
    for column, fmt, label in (
        (export_columns[0], "xlsx", "Excel workbook (6 sheets)"),
        (export_columns[1], "csv", "Clause table (CSV)"),
        (export_columns[2], "json", "Full payload (JSON)"),
    ):
        with column:
            try:
                payload = client.contract_export(analysis["contract_id"], fmt)
                st.download_button(
                    label,
                    data=payload,
                    file_name=f"contract_{analysis['contract_id'][:8]}.{fmt}",
                    mime=EXPORT_MIME[fmt],
                    use_container_width=True,
                )
            except ApiError as error:
                st.caption(error.message)

    st.caption(analysis["disclaimer"])

elif contract is None:
    st.info(
        "Upload a contract to begin, or download one of the fictional demo contracts from the "
        "sidebar.",
        icon="👈",
    )

disclaimer()
