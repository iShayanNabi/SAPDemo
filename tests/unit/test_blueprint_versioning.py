"""Unit tests for version snapshots and version comparison.

Both matching decisions are asserted here, because getting either wrong produces
a diff that is technically accurate and completely useless:

* sections are matched by ``section_key``, never by position;
* items are matched by title, never by the identifier that gets renumbered.
"""

from __future__ import annotations

from app.modules.blueprint_generator.versioning import (
    MAX_DIFF_LINES,
    build_snapshot,
    compare_snapshots,
    snapshot_counts,
)
from app.schemas.blueprint import (
    BlueprintItemSchema,
    BlueprintSectionSchema,
    SectionChange,
    SectionStatus,
)


def _section(
    key: str,
    *,
    position: int = 1,
    narrative: str = "The original wording.",
    items: list[tuple[str, str]] | None = None,
    status: SectionStatus = SectionStatus.DRAFT,
    approved_by: str | None = None,
    title: str | None = None,
) -> BlueprintSectionSchema:
    return BlueprintSectionSchema(
        id=f"id-{key}",
        blueprint_id="bp",
        section_id=f"BP-{key.upper()[:5]}",
        section_key=key,
        position=position,
        title=title or key.replace("_", " ").title(),
        narrative=narrative,
        items=[
            BlueprintItemSchema(item_id=f"BP-X-{index:03d}", title=title_, detail=detail)
            for index, (title_, detail) in enumerate(items or [], start=1)
        ],
        status=status,
        approved_by=approved_by,
    )


def _snapshot(*sections: BlueprintSectionSchema) -> list[dict]:
    return build_snapshot(sections)


class TestSnapshot:
    def test_a_snapshot_is_plain_data_that_does_not_follow_later_edits(self):
        section = _section("scope")
        snapshot = _snapshot(section)

        section.narrative = "Rewritten after the version was saved."

        assert snapshot[0]["narrative"] == "The original wording."

    def test_snapshot_counts_report_the_headline_figures(self):
        snapshot = _snapshot(
            _section("scope", items=[("A", "a"), ("B", "b")]),
            _section("integrations", position=2, status=SectionStatus.NEEDS_INPUT),
        )
        counts = snapshot_counts(snapshot)

        assert counts == {
            "section_count": 2,
            "item_count": 2,
            "approved_count": 0,
            "needs_input_count": 1,
        }


class TestComparison:
    def test_an_unchanged_document_reports_every_section_as_unchanged(self):
        before = _snapshot(_section("scope"), _section("risks", position=2))
        after = _snapshot(_section("scope"), _section("risks", position=2))

        result = compare_snapshots("bp", 1, 2, before, after)

        assert result.sections_modified == 0
        assert result.sections_unchanged == 2
        assert result.reordered is False

    def test_unchanged_sections_are_listed_rather_than_omitted(self):
        """"Unchanged" and "not looked at" must not look the same to a reader."""
        before = _snapshot(_section("scope"), _section("risks", position=2))
        after = _snapshot(
            _section("scope", narrative="New wording."), _section("risks", position=2)
        )

        result = compare_snapshots("bp", 1, 2, before, after)

        assert {diff.section_key for diff in result.section_diffs} == {"scope", "risks"}

    def test_a_changed_narrative_is_reported_with_a_diff(self):
        before = _snapshot(_section("scope", narrative="Line one\nLine two"))
        after = _snapshot(_section("scope", narrative="Line one\nLine two changed"))

        result = compare_snapshots("bp", 1, 2, before, after)
        diff = result.section_diffs[0]

        assert diff.change is SectionChange.MODIFIED
        assert diff.narrative_changed is True
        assert any("Line two changed" in line for line in diff.narrative_diff)

    def test_a_very_long_diff_is_capped(self):
        before = _snapshot(_section("scope", narrative="\n".join(f"old {i}" for i in range(200))))
        after = _snapshot(_section("scope", narrative="\n".join(f"new {i}" for i in range(200))))

        diff = compare_snapshots("bp", 1, 2, before, after).section_diffs[0]

        assert len(diff.narrative_diff) <= MAX_DIFF_LINES + 1
        assert "not shown" in diff.narrative_diff[-1]

    def test_sections_are_matched_by_key_not_by_position(self):
        """Inserting a section must not report everything below it as rewritten."""
        before = _snapshot(
            _section("scope", position=1),
            _section("risks", position=2),
            _section("training", position=3),
        )
        after = _snapshot(
            _section("custom_001", position=1, title="Change management"),
            _section("scope", position=2),
            _section("risks", position=3),
            _section("training", position=4),
        )

        result = compare_snapshots("bp", 1, 2, before, after)

        assert result.sections_added == 1
        assert result.sections_modified == 0
        assert result.sections_unchanged == 3

    def test_a_moved_section_is_reported_as_reordered_not_as_rewritten(self):
        before = _snapshot(_section("scope", position=1), _section("risks", position=2))
        after = _snapshot(_section("risks", position=1), _section("scope", position=2))

        result = compare_snapshots("bp", 1, 2, before, after)

        assert result.reordered is True
        assert result.sections_modified == 0

    def test_a_removed_section_is_never_dropped_from_the_comparison(self):
        before = _snapshot(_section("scope"), _section("custom_001", position=2))
        after = _snapshot(_section("scope"))

        result = compare_snapshots("bp", 1, 2, before, after)

        assert result.sections_removed == 1
        removed = next(
            diff for diff in result.section_diffs if diff.change is SectionChange.REMOVED
        )
        assert removed.section_key == "custom_001"

    def test_items_are_matched_by_title_not_by_identifier(self):
        """Item identifiers are renumbered on every edit; matching on them lies."""
        before = _snapshot(
            _section("risks", items=[("Data quality", "a"), ("Resourcing", "b")])
        )
        after = _snapshot(
            _section(
                "risks",
                items=[("A new risk", "n"), ("Data quality", "a"), ("Resourcing", "b")],
            )
        )

        diff = compare_snapshots("bp", 1, 2, before, after).section_diffs[0]

        assert diff.items_added == ["A new risk"]
        assert diff.items_removed == []
        assert diff.items_changed == []

    def test_a_changed_item_detail_is_reported_as_changed(self):
        before = _snapshot(_section("risks", items=[("Data quality", "old detail")]))
        after = _snapshot(_section("risks", items=[("Data quality", "new detail")]))

        diff = compare_snapshots("bp", 1, 2, before, after).section_diffs[0]

        assert diff.items_changed == ["Data quality"]
        assert diff.items_added == []

    def test_an_approval_change_is_reported(self):
        before = _snapshot(_section("scope", status=SectionStatus.APPROVED, approved_by="Ingrid"))
        after = _snapshot(_section("scope", status=SectionStatus.DRAFT))

        diff = compare_snapshots("bp", 1, 2, before, after).section_diffs[0]

        assert diff.approval_changed is True
        assert diff.status_from == "approved"
        assert diff.status_to == "draft"
        assert diff.change is SectionChange.MODIFIED

    def test_a_renamed_section_is_modified_even_with_identical_content(self):
        before = _snapshot(_section("custom_001", title="Change management"))
        after = _snapshot(_section("custom_001", title="Organisational change"))

        diff = compare_snapshots("bp", 1, 2, before, after).section_diffs[0]

        assert diff.change is SectionChange.MODIFIED
        assert diff.title == "Organisational change"

    def test_the_labels_of_both_versions_travel_with_the_comparison(self):
        result = compare_snapshots(
            "bp",
            1,
            2,
            _snapshot(_section("scope")),
            _snapshot(_section("scope")),
            from_label="Design review",
            to_label="After workshop",
        )

        assert result.from_label == "Design review"
        assert result.to_label == "After workshop"
