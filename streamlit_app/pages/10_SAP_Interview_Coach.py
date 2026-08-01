"""Streamlit page for the SAP Interview Coach.

Like every page in this app it contains no business logic. It collects the
track, mode and difficulty, asks the FastAPI backend to start a session, shows
one question at a time, posts the answer and renders the score that comes back.

Every number on this page - the overall score, each dimension, the band, the
weak areas, the study plan - is calculated server-side by the published rubric,
so a future React front end calling the same endpoints gets the same marks. The
only thing the page decides for itself is how long the candidate spent typing,
which it measures and sends; the backend records it and reports it, and no
dimension is moved by it.

The page is deliberately blunt about two things: the marking is keyword based
and says so next to every concept, and nothing here is an SAP qualification.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from streamlit_app.components.api_client import ApiClient, ApiError  # noqa: E402
from streamlit_app.components.demo import (  # noqa: E402
    demo_banner,
    explain_module,
    filter_to_mine,
    remember,
    session_scope_caption,
)
from streamlit_app.components.ui import disclaimer, origin_badge, show_error  # noqa: E402

st.set_page_config(page_title="SAP Interview Coach", page_icon="🎤", layout="wide")

client = ApiClient()

BAND_COLORS = {
    "strong": "#3B8C4E",
    "proficient": "#2E7D8F",
    "developing": "#E8710A",
    "needs_work": "#B3261E",
}
BAND_LABELS = {
    "strong": "Strong",
    "proficient": "Proficient",
    "developing": "Developing",
    "needs_work": "Needs work",
}
DIMENSION_LABELS = {
    "technical_accuracy": "Technical accuracy",
    "completeness": "Completeness",
    "clarity": "Clarity",
    "business_understanding": "Business understanding",
    "architecture": "Architecture",
}

st.title("SAP Interview Coach")
demo_banner(client)
explain_module("interview_coach")
st.write(
    "Practise SAP interview questions and get a structured, explainable score. The rubric "
    "does the marking: which expected concepts your answer covered, which keyword matched "
    "each one, what a known-wrong statement costs and how clearly the answer reads. An AI "
    "provider, when one is active, only writes the coaching prose around that result."
)
st.caption(
    "The question bank is entirely fictional. Nothing here is an SAP certification or "
    "qualification, no answer has been reviewed by SAP, and this application is not "
    "connected to an SAP system."
)


def _band_badge(band: str | None) -> str:
    if not band:
        return ""
    colour = BAND_COLORS.get(band, "#666666")
    return (
        f"<span style='background:{colour};color:#fff;padding:2px 10px;border-radius:10px;"
        f"font-size:0.75rem;'>{BAND_LABELS.get(band, band).upper()}</span>"
    )


def _reset_question_clock() -> None:
    """Restart the stopwatch shown next to the current question."""
    st.session_state["ic_question_started"] = time.monotonic()


def _elapsed() -> int:
    started = st.session_state.get("ic_question_started")
    return int(time.monotonic() - started) if started else 0


def _dimension_frame(dimensions: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Dimension": DIMENSION_LABELS.get(item["dimension"], item["dimension"]),
                "Score": item["score"] if item["applicable"] else None,
                "Band": BAND_LABELS.get(item["band"] or "", "Not scored"),
                "Weight": round(item["weight"], 3),
                "How it was reached": item["explanation"],
            }
            for item in dimensions
        ]
    )


def _concept_frame(matches: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Covered": "yes" if item["matched"] else "no",
                "Expected concept": item["label"],
                "Feeds": item["dimension"],
                "Weight": item["weight"],
                "Required": "yes" if item["required"] else "",
                "Matched on": item["matched_keyword"] or "",
                "In your answer": item["excerpt"] or (
                    "mentioned inside a negation" if item["negated"] else ""
                ),
            }
            for item in matches
        ]
    )


# ---------------------------------------------------------------------------
# Sidebar: backend status, question bank, saved sessions
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
                "Mock mode writes the coaching prose locally. The scores are produced by "
                "the rubric either way, so they are identical with or without a model."
            )
    except ApiError as error:
        st.error(error.message)
        st.caption("Start the backend in a second terminal, then reload this page.")
        st.code("uvicorn app.main:app --reload", language="bash")
        st.stop()

    st.header("Question bank")
    try:
        bank = client.interview_bank_info()
        st.write(f"**{bank['question_count']}** questions, version `{bank['bank_version']}`")
        st.caption(
            "Available per mode: "
            + ", ".join(f"{name} {count}" for name, count in bank["by_mode"].items())
        )
    except ApiError as error:
        show_error(error.message, error.details)
        st.stop()

    st.header("Previous sessions")
    try:
        listing = client.interview_sessions(limit=15)
        sessions = filter_to_mine(listing["sessions"], "interview_session", "session_id")
        session_scope_caption("sessions")
        if sessions:
            labels = {
                f"{item['name'][:34]} - {item['status']}"
                f" ({item['answered_count']}/{item['question_count']})": item["session_id"]
                for item in sessions
            }
            chosen = st.selectbox("Open a session", list(labels), key="ic_saved")
            if st.button("Load session", use_container_width=True):
                st.session_state["ic_session"] = client.interview_session(labels[chosen])
                _reset_question_clock()
                st.rerun()
        else:
            st.caption("No sessions from this browser session yet. Start one on the right.")
    except ApiError as error:
        show_error(error.message, error.details)

try:
    catalog = client.interview_catalog()
except ApiError as error:
    show_error(error.message, error.details)
    st.stop()

track_labels = {item["label"]: item["track"] for item in catalog["tracks"]}
track_lookup = {item["track"]: item for item in catalog["tracks"]}
mode_labels = {item["label"]: item["mode"] for item in catalog["modes"]}
mode_lookup = {item["mode"]: item for item in catalog["modes"]}

setup_tab, interview_tab, summary_tab, performance_tab, rules_tab = st.tabs(
    ["Set up", "Interview", "Session summary", "Performance", "How you are marked"]
)


# ---------------------------------------------------------------------------
# Set up
# ---------------------------------------------------------------------------
with setup_tab:
    st.subheader("Start an interview")

    with st.form("ic_start"):
        left, right = st.columns([2, 1])
        with left:
            chosen_tracks = st.multiselect(
                "Learning tracks",
                list(track_labels),
                default=[catalog["tracks"][0]["label"]],
                help=(
                    "The order matters. When you ask for fewer questions than tracks, the "
                    "tracks you list first keep their questions."
                ),
            )
            chosen_mode_label = st.selectbox("Interview mode", list(mode_labels))
            mode_info = mode_lookup[mode_labels[chosen_mode_label]]
            st.caption(mode_info["description"])

            chosen_difficulties = st.multiselect(
                "Difficulty (leave empty to use the mode's mix)",
                catalog["difficulties"],
                default=[],
            )
            topic_options = sorted(
                {
                    topic
                    for label in chosen_tracks
                    for topic in track_lookup[track_labels[label]]["topics"]
                }
            )
            chosen_topics = st.multiselect("Topics (optional)", topic_options, default=[])
        with right:
            question_count = st.number_input(
                "Questions",
                min_value=1,
                max_value=catalog["max_questions_per_session"],
                value=min(
                    mode_info["default_question_count"],
                    catalog["max_questions_per_session"],
                ),
            )
            candidate_name = st.text_input("Your name (optional)", value="")
            seed = st.number_input(
                "Seed",
                min_value=0,
                max_value=2_147_483_647,
                value=20260801,
                help=(
                    "The same seed, tracks, mode and difficulties always produce the same "
                    "interview, so you can repeat one exactly."
                ),
            )
            st.metric(
                "Questions available in this mode",
                mode_info["question_count"],
            )
            if mode_info["timer_enabled"]:
                st.caption(
                    f"Timed mode: {mode_info['time_limit_seconds']} seconds per question. "
                    "The clock is recorded and reported; it never changes a score."
                )

        submitted = st.form_submit_button("Start interview", type="primary")

    if submitted:
        if not chosen_tracks:
            st.warning("Choose at least one track.")
        else:
            try:
                st.session_state["ic_session"] = client.interview_start(
                    [track_labels[label] for label in chosen_tracks],
                    mode=mode_labels[chosen_mode_label],
                    difficulties=chosen_difficulties or None,
                    question_count=int(question_count),
                    topics=chosen_topics or None,
                    candidate_name=candidate_name or None,
                    seed=int(seed),
                )
                remember("interview_session", st.session_state["ic_session"]["session_id"])
                _reset_question_clock()
                st.success("Interview started. Open the **Interview** tab.")
            except ApiError as error:
                show_error(error.message, error.details)

    st.divider()
    st.subheader("Browse the question bank")
    st.caption(
        "Questions are shown without their marking schemes. The expected concepts, the "
        "reference answer and the known-wrong statements are attached to your answer once "
        "you have submitted it - a question served with its answer key is not a question."
    )
    browse_track = st.selectbox("Track", list(track_labels), key="ic_browse_track")
    try:
        browsed = client.interview_questions(track=track_labels[browse_track], limit=100)
        st.caption(f"{browsed['total']} question(s) in this track.")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "ID": item["question_id"],
                        "Topic": item["topic"],
                        "Difficulty": item["difficulty"],
                        "Modes": ", ".join(item["modes"]),
                        "Question": item["question"],
                        "Concepts expected": item["expected_concept_count"],
                    }
                    for item in browsed["questions"]
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    except ApiError as error:
        show_error(error.message, error.details)


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------
with interview_tab:
    session = st.session_state.get("ic_session")
    if not session:
        st.info("Start an interview on the **Set up** tab.", icon="👈")
    else:
        summary = session["summary"]
        head = st.columns(4)
        head[0].metric("Questions", summary["question_count"])
        head[1].metric("Answered", summary["answered_count"])
        head[2].metric(
            "Average so far",
            summary["average_score"] if summary["average_score"] is not None else "-",
        )
        head[3].metric("Status", session["status"].replace("_", " "))

        for note in session.get("notes", []):
            st.info(note, icon="ℹ️")

        pending = session.get("next_question")
        if pending is None:
            st.success(
                "Every question in this session has been answered. Complete it on the "
                "**Session summary** tab."
            )
        else:
            st.subheader(f"Question - {pending['topic']} ({pending['difficulty']})")
            st.markdown(f"**{pending['question']}**")
            meta = st.columns(3)
            meta[0].caption(f"Track: {track_lookup[pending['track']]['label']}")
            meta[1].caption(f"Concepts a complete answer covers: {pending['expected_concept_count']}")
            limit = pending.get("time_limit_seconds")
            if limit:
                elapsed = _elapsed()
                remaining = limit - elapsed
                meta[2].caption(
                    f"Time limit: {limit}s - about {max(0, remaining)}s left"
                    if remaining >= 0
                    else f"Time limit: {limit}s - {abs(remaining)}s over"
                )
                st.progress(min(1.0, elapsed / limit) if limit else 0.0)
                st.caption(
                    "The clock is recorded and reported. It does not change any score."
                )
            else:
                meta[2].caption("No time limit in this mode.")

            with st.form(f"ic_answer_{pending['question_id']}"):
                answer_text = st.text_area(
                    "Your answer",
                    height=220,
                    placeholder="Answer as you would out loud in an interview.",
                )
                controls = st.columns([1, 3])
                use_ai = controls[0].checkbox(
                    "AI coaching prose",
                    value=True,
                    help=(
                        "Off means no provider is called at all. The scores are identical "
                        "either way; only the wording of the feedback changes."
                    ),
                )
                answered = st.form_submit_button("Submit answer", type="primary")

            if answered:
                if not answer_text.strip():
                    st.warning("Type an answer, or say what you do know.")
                else:
                    try:
                        result = client.interview_answer(
                            session["session_id"],
                            answer_text,
                            question_id=pending["question_id"],
                            # The page is the only thing that knows when the
                            # candidate actually started typing, so it measures
                            # and sends it. The backend records and reports it
                            # and never lets it move a score.
                            seconds_spent=_elapsed(),
                            use_ai=use_ai,
                        )
                        st.session_state["ic_last_result"] = result
                        st.session_state["ic_session"] = client.interview_session(
                            session["session_id"]
                        )
                        _reset_question_clock()
                        st.rerun()
                    except ApiError as error:
                        show_error(error.message, error.details)

        result = st.session_state.get("ic_last_result")
        if result:
            answer = result["answer"]
            score = answer["score"]
            feedback = answer["feedback"]

            st.divider()
            st.subheader(f"Feedback - {answer['question']['question_id']}")
            st.markdown(_band_badge(score["overall_band"]), unsafe_allow_html=True)

            cards = st.columns(4)
            cards[0].metric("Overall", score["overall_score"])
            cards[1].metric("Pass mark", score["pass_score"])
            cards[2].metric("Result", "pass" if score["passed"] else "not yet")
            cards[3].metric(
                "Time",
                f"{answer['seconds_spent']}s"
                + ("" if answer["within_time_limit"] else f" (+{answer['over_by_seconds']}s)"),
            )

            if score["non_answer"]:
                st.warning(
                    "This was recorded as a non-answer, so nothing could be scored. That is "
                    "reported rather than dressed up as a very low mark.",
                    icon="🤐",
                )
            for note in score["scoring_notes"]:
                st.caption(note)

            st.dataframe(
                _dimension_frame(score["dimensions"]),
                use_container_width=True,
                hide_index=True,
            )

            columns = st.columns(2)
            with columns[0]:
                st.markdown("**Strengths**")
                for item in feedback["strengths"]:
                    st.write(f"- {item}")
                if feedback["missing_concepts"]:
                    st.markdown("**Missing concepts**")
                    for item in feedback["missing_concepts"]:
                        st.write(f"- {item}")
            with columns[1]:
                if feedback["incorrect_statements"]:
                    st.markdown("**Incorrect statements**")
                    for item in feedback["incorrect_statements"]:
                        st.error(item, icon="⚠️")
                if feedback["topics_to_study"]:
                    st.markdown("**Topics to study**")
                    for item in feedback["topics_to_study"]:
                        st.write(f"- {item}")
                if feedback["follow_up_question"]:
                    st.markdown("**Follow-up question**")
                    st.info(feedback["follow_up_question"], icon="❓")

            st.markdown("**Coaching note**")
            st.write(feedback["coaching_note"])
            st.markdown("**Improved sample answer**")
            st.write(feedback["improved_sample_answer"])
            st.caption(
                f"Feedback prose: {origin_badge(feedback['output_origin'])}"
                + (f" via {feedback['ai_provider']}" if feedback["ai_provider"] else "")
                + ". Every score above is rule-based."
            )
            if feedback["ai_error"]:
                st.caption(f"AI note: {feedback['ai_error']}")
            for note in feedback["validation_notes"]:
                st.caption(note)

            with st.expander("Concept by concept - what matched and why"):
                st.dataframe(
                    _concept_frame(score["concept_matches"]),
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "Matching is keyword based. A correct answer phrased in words the bank "
                    "does not list will score lower than it deserves, which is why the "
                    "matched keyword is shown for every concept."
                )

            with st.expander("Clarity measurement"):
                st.json(score["clarity"])

            if answer["answer_key"]:
                with st.expander("The marking scheme for this question"):
                    st.markdown("**Reference answer**")
                    st.write(answer["answer_key"]["reference_answer"])
                    st.markdown("**Suggested follow-ups**")
                    for item in answer["answer_key"]["follow_up_questions"]:
                        st.write(f"- {item['text']}")


# ---------------------------------------------------------------------------
# Session summary
# ---------------------------------------------------------------------------
with summary_tab:
    session = st.session_state.get("ic_session")
    if not session:
        st.info("Start an interview on the **Set up** tab.", icon="👈")
    else:
        summary = session["summary"]
        st.subheader(session["name"])
        st.markdown(_band_badge(summary["band"]), unsafe_allow_html=True)

        cards = st.columns(5)
        cards[0].metric(
            "Average", summary["average_score"] if summary["average_score"] is not None else "-"
        )
        cards[1].metric("Best", summary["best_score"] if summary["best_score"] is not None else "-")
        cards[2].metric("Passed", f"{summary['passed_count']}/{summary['answered_count']}")
        cards[3].metric("Time spent", f"{summary['total_seconds_spent']}s")
        cards[4].metric("Unanswered", summary["pending_count"])

        if summary["over_time_count"]:
            st.caption(
                f"{summary['over_time_count']} answer(s) went over the time limit. "
                "Recorded and reported; no score was changed by it."
            )
        if summary["stale_score_count"]:
            st.warning(
                f"{summary['stale_score_count']} score(s) were computed against a question "
                "rubric that has since changed. They are kept and still counted, but they "
                "were earned under a different marking scheme.",
                icon="⚠️",
            )

        breakdown = st.columns(3)
        with breakdown[0]:
            st.markdown("**By dimension**")
            if summary["average_by_dimension"]:
                st.bar_chart(
                    pd.DataFrame(
                        {
                            "Average": {
                                DIMENSION_LABELS.get(key, key): value
                                for key, value in summary["average_by_dimension"].items()
                            }
                        }
                    )
                )
        with breakdown[1]:
            st.markdown("**By topic**")
            if summary["average_by_topic"]:
                st.dataframe(
                    pd.DataFrame(
                        sorted(summary["average_by_topic"].items(), key=lambda pair: pair[1]),
                        columns=["Topic", "Average"],
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
        with breakdown[2]:
            st.markdown("**By difficulty**")
            if summary["average_by_difficulty"]:
                st.dataframe(
                    pd.DataFrame(
                        summary["average_by_difficulty"].items(),
                        columns=["Difficulty", "Average"],
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        if summary["most_missed_concepts"]:
            st.markdown("**Most missed concepts in this session**")
            for item in summary["most_missed_concepts"]:
                st.write(f"- {item}")

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "#": item["position"],
                        "Question": item["question"]["question_id"],
                        "Topic": item["question"]["topic"],
                        "Difficulty": item["question"]["difficulty"],
                        "Status": item["status"],
                        "Score": (item["score"] or {}).get("overall_score"),
                        "Band": BAND_LABELS.get(
                            (item["score"] or {}).get("overall_band", ""), ""
                        ),
                        "Time": f"{item['seconds_spent']}s",
                        "Attempts": item["attempt_count"],
                        "Rubric changed since": "yes" if item["scoring_is_stale"] else "",
                    }
                    for item in session["answers"]
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

        if session["status"] == "in_progress":
            closing = st.columns([1, 1, 3])
            if closing[0].button("Complete session", type="primary"):
                try:
                    st.session_state["ic_session"] = client.interview_complete(
                        session["session_id"]
                    )
                    st.rerun()
                except ApiError as error:
                    show_error(error.message, error.details)
            if closing[1].button("Abandon session"):
                try:
                    st.session_state["ic_session"] = client.interview_complete(
                        session["session_id"], abandoned=True
                    )
                    st.rerun()
                except ApiError as error:
                    show_error(error.message, error.details)
        else:
            st.success(f"This session is {session['status']}.")

        # -------------------------------------------------------------
        # Export
        # -------------------------------------------------------------
        st.divider()
        st.markdown("### Export this session")
        st.caption(
            "Every question, the answer given to it, the dimension scores with their reasons, "
            "which concepts were credited and what credited them, the coaching prose with its "
            "origin, and the study topics. The marks are the rubric's and are labelled "
            "`rule_based`; the prose is labelled with whatever wrote it. The PDF is the "
            "transcript, one answer per page."
        )
        export_columns = st.columns(4)
        for column, fmt, mime in (
            (
                export_columns[0],
                "xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            (export_columns[1], "csv", "text/csv"),
            (export_columns[2], "json", "application/json"),
            (export_columns[3], "pdf", "application/pdf"),
        ):
            with column:
                try:
                    data = client.interview_export(session["session_id"], fmt)
                except ApiError as error:
                    st.caption(f"{fmt.upper()} export unavailable: {error.message}")
                    continue
                st.download_button(
                    f"Download {fmt.upper()}",
                    data=data,
                    file_name=f"interview_session_{session['session_id'][:8]}.{fmt}",
                    mime=mime,
                    key=f"ic_export_{fmt}",
                )


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
with performance_tab:
    st.subheader("Performance across sessions")
    filters = st.columns([2, 1, 1])
    filter_tracks = filters[0].multiselect(
        "Tracks", list(track_labels), default=[], key="ic_perf_tracks"
    )
    filter_mode = filters[1].selectbox(
        "Mode", ["all", *mode_labels], key="ic_perf_mode"
    )
    session_limit = filters[2].number_input(
        "Sessions to include", min_value=1, max_value=500, value=50
    )

    try:
        performance = client.interview_performance(
            tracks=[track_labels[label] for label in filter_tracks] or None,
            mode=mode_labels[filter_mode] if filter_mode != "all" else None,
            session_limit=int(session_limit),
        )
    except ApiError as error:
        show_error(error.message, error.details)
        performance = None

    if performance:
        cards = st.columns(5)
        cards[0].metric(
            "Average score",
            performance["average_score"] if performance["average_score"] is not None else "-",
        )
        cards[1].metric("Sessions", performance["session_count"])
        cards[2].metric("Completed", performance["completed_session_count"])
        cards[3].metric("Answers", performance["answer_count"])
        cards[4].metric("Time practised", f"{performance['total_seconds_spent']}s")
        st.markdown(_band_badge(performance["band"]), unsafe_allow_html=True)

        for note in performance["notes"]:
            st.info(note, icon="ℹ️")

        if performance["score_over_time"]:
            st.markdown("**Score over time**")
            st.line_chart(
                pd.DataFrame(
                    [
                        {"Session": point["session_name"][:28], "Average": point["average_score"]}
                        for point in performance["score_over_time"]
                    ]
                ).set_index("Session")
            )

        grids = st.columns(3)
        with grids[0]:
            st.markdown("**By dimension**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Dimension": DIMENSION_LABELS.get(item["dimension"], item["dimension"]),
                            "Average": item["average_score"],
                            "Answers": item["answer_count"],
                        }
                        for item in performance["by_dimension"]
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        with grids[1]:
            st.markdown("**By difficulty**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Difficulty": item["difficulty"],
                            "Average": item["average_score"],
                            "Answers": item["answer_count"],
                        }
                        for item in performance["by_difficulty"]
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        with grids[2]:
            st.markdown("**By track**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Track": track_lookup[item["track"]]["label"],
                            "Average": item["average_score"],
                            "Answers": item["answer_count"],
                        }
                        for item in performance["by_track"]
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

        areas = st.columns(2)
        with areas[0]:
            st.markdown("**Weak areas**")
            if performance["weak_areas"]:
                for item in performance["weak_areas"]:
                    st.write(
                        f"- **{item['topic']}** - {item['average_score']} "
                        f"over {item['answer_count']} answer(s)"
                    )
            else:
                st.caption(
                    "No topic has enough answers below the threshold to be called a weakness "
                    "yet."
                )
        with areas[1]:
            st.markdown("**Strong areas**")
            if performance["strong_areas"]:
                for item in performance["strong_areas"]:
                    st.write(
                        f"- **{item['topic']}** - {item['average_score']} "
                        f"over {item['answer_count']} answer(s)"
                    )
            else:
                st.caption("No topic has enough answers above the threshold yet.")

        st.markdown("**Recommended study plan**")
        if performance["study_plan"]:
            for item in performance["study_plan"]:
                with st.expander(
                    f"{item['priority']}. {item['topic']} - averaging {item['average_score']}"
                ):
                    st.caption(item["reason"])
                    if item["focus_concepts"]:
                        st.markdown("Concepts you have missed most often here:")
                        for concept in item["focus_concepts"]:
                            st.write(f"- {concept}")
                    st.markdown("What to do:")
                    for action in item["actions"]:
                        st.write(f"- {action}")
                    if item["suggested_difficulty"]:
                        st.caption(
                            f"Suggested difficulty for the next attempt: "
                            f"{item['suggested_difficulty']}"
                        )
        else:
            st.caption(
                "Nothing to recommend yet - either no answers have been recorded, or no "
                "topic is averaging below the weak-area threshold."
            )

        st.markdown("**Recent sessions**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Session": item["name"],
                        "Mode": item["mode"],
                        "Status": item["status"],
                        "Answered": f"{item['answered_count']}/{item['question_count']}",
                        "Average": item["average_score"],
                    }
                    for item in performance["recent_sessions"]
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )


# ---------------------------------------------------------------------------
# How you are marked
# ---------------------------------------------------------------------------
with rules_tab:
    st.subheader("How an answer is marked")
    methodology = catalog["methodology"]

    st.markdown("**Decided by deterministic Python**")
    for item in methodology["deterministic"]:
        st.write(f"- {item}")
    st.markdown("**Written by an AI provider, when one is active**")
    for item in methodology["ai_generated"]:
        st.write(f"- {item}")

    weights = st.columns(2)
    with weights[0]:
        st.markdown("**Default dimension weights**")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Dimension": DIMENSION_LABELS.get(key, key), "Weight": value}
                    for key, value in methodology["dimension_weights"].items()
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "A question with no architecture concepts is not scored on architecture at all - "
            "that weight is shared among the others, and the dimension is reported blank "
            "rather than as a zero."
        )
    with weights[1]:
        st.markdown("**Bands and pass mark**")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Band": BAND_LABELS.get(key, key), "From": value}
                    for key, value in methodology["bands"].items()
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.metric("Pass mark", methodology["pass_score"])

    st.markdown("**Clarity**")
    st.json(methodology["clarity"])
    st.markdown("**Penalties**")
    st.json(methodology["penalties"])
    st.markdown("**Weak and strong areas**")
    st.json(methodology["performance"])

    if methodology.get("mode_weight_overrides"):
        st.markdown("**Weights by mode**")
        st.json(methodology["mode_weight_overrides"])

    st.caption(methodology["scoring_note"])
    st.info(catalog["disclaimer"], icon="ℹ️")
    st.caption(
        "Every threshold above lives in "
        "`app/modules/interview_coach/config/interview_rules.json`. Editing that file "
        "changes the marking with no code change."
    )

disclaimer()
