"""Version snapshots and version comparison.

A blueprint is a document people argue about, so it needs two things a report
does not: the ability to freeze what it said at a point in time, and the ability
to say precisely what changed since.

Both are deterministic and both live here, away from the database and away from
the AI layer, so a comparison can be tested on two literals.

Two matching decisions are the whole of the design, and getting either of them
wrong produces a diff that is technically accurate and completely useless:

* **Sections are matched by ``section_key``, never by position.** Insert one
  custom section at the top and a position-matched diff reports every section
  below it as rewritten.
* **Items are matched by title, never by item identifier.** Item identifiers are
  renumbered 1..n on every edit - that is what keeps a printed list readable -
  so inserting one item at the top of a section would otherwise report every
  item below it as changed.

The snapshot itself is a plain, fully materialised copy of the section list. It
holds no reference back to the live rows, because a "version" that changes when
somebody edits the document afterwards is not a version.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping
from typing import Any

from app.core.logging import get_logger
from app.schemas.blueprint import (
    BlueprintSectionSchema,
    SectionChange,
    SectionDiffSchema,
    VersionComparisonSchema,
)

logger = get_logger(__name__)

__all__ = [
    "MAX_DIFF_LINES",
    "build_snapshot",
    "compare_snapshots",
    "snapshot_counts",
]

#: How many unified-diff lines one section reports. A section rewritten from end
#: to end produces a diff nobody reads; the count of changes is the useful part.
MAX_DIFF_LINES = 40

#: The item fields a comparison treats as content. ``item_id`` is deliberately
#: absent: it is renumbered on every edit and says nothing about the item.
_ITEM_CONTENT_FIELDS = ("detail", "category", "reference", "owner", "rating")


def build_snapshot(sections: Iterable[BlueprintSectionSchema]) -> list[dict[str, Any]]:
    """Freeze the current sections into a self-contained snapshot.

    ``model_dump`` produces plain data with no link back to the ORM rows, which
    is exactly what a version needs: editing the blueprint tomorrow must not
    change what version 1 says today.
    """
    return [section.model_dump(mode="json") for section in sections]


def snapshot_counts(snapshot: list[Mapping[str, Any]]) -> dict[str, int]:
    """Return the headline counts of a snapshot, for the version list."""
    approved = sum(1 for section in snapshot if section.get("approved_at"))
    needs_input = sum(
        1 for section in snapshot if str(section.get("status")) == "needs_input"
    )
    items = sum(len(section.get("items") or []) for section in snapshot)
    return {
        "section_count": len(snapshot),
        "item_count": items,
        "approved_count": approved,
        "needs_input_count": needs_input,
    }


def _item_key(item: Mapping[str, Any]) -> str:
    return str(item.get("title") or "").strip().lower()


def _item_content(item: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(item.get(field) or "").strip() for field in _ITEM_CONTENT_FIELDS)


def _narrative_diff(before: str, after: str) -> list[str]:
    """Return a capped unified diff of two narratives."""
    lines = list(
        difflib.unified_diff(
            (before or "").splitlines(),
            (after or "").splitlines(),
            fromfile="from",
            tofile="to",
            lineterm="",
            n=1,
        )
    )
    if len(lines) > MAX_DIFF_LINES:
        dropped = len(lines) - MAX_DIFF_LINES
        lines = lines[:MAX_DIFF_LINES] + [f"... {dropped} further diff line(s) not shown"]
    return lines


def _compare_items(
    before: list[Mapping[str, Any]], after: list[Mapping[str, Any]]
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(added, removed, changed)`` item titles between two versions."""
    before_map = {_item_key(item): item for item in before if _item_key(item)}
    after_map = {_item_key(item): item for item in after if _item_key(item)}

    added = [
        str(after_map[key].get("title"))
        for key in after_map
        if key not in before_map
    ]
    removed = [
        str(before_map[key].get("title"))
        for key in before_map
        if key not in after_map
    ]
    changed = [
        str(after_map[key].get("title"))
        for key in after_map
        if key in before_map and _item_content(before_map[key]) != _item_content(after_map[key])
    ]
    return added, removed, changed


def compare_snapshots(
    blueprint_id: str,
    from_version: int,
    to_version: int,
    before: list[Mapping[str, Any]],
    after: list[Mapping[str, Any]],
    *,
    from_label: str = "",
    to_label: str = "",
) -> VersionComparisonSchema:
    """Compare two snapshots section by section.

    Every section that exists in either version appears in the result, including
    the unchanged ones: a comparison that only lists what moved leaves a reader
    unable to tell "unchanged" from "not looked at".
    """
    before_map = {str(section.get("section_key")): section for section in before}
    after_map = {str(section.get("section_key")): section for section in after}

    # Report in the reading order of the newer version, then anything that only
    # the older version had, so a removed section is never silently dropped.
    ordered: list[str] = [str(section.get("section_key")) for section in after]
    ordered += [key for key in (str(s.get("section_key")) for s in before) if key not in after_map]

    diffs: list[SectionDiffSchema] = []
    for key in ordered:
        old = before_map.get(key)
        new = after_map.get(key)

        if old is None and new is not None:
            diffs.append(
                SectionDiffSchema(
                    section_key=key,
                    title=str(new.get("title") or key),
                    change=SectionChange.ADDED,
                    narrative_changed=bool(str(new.get("narrative") or "").strip()),
                    items_added=[str(item.get("title")) for item in (new.get("items") or [])],
                    status_to=str(new.get("status") or ""),
                    position_to=new.get("position"),
                )
            )
            continue
        if new is None and old is not None:
            diffs.append(
                SectionDiffSchema(
                    section_key=key,
                    title=str(old.get("title") or key),
                    change=SectionChange.REMOVED,
                    narrative_changed=bool(str(old.get("narrative") or "").strip()),
                    items_removed=[str(item.get("title")) for item in (old.get("items") or [])],
                    status_from=str(old.get("status") or ""),
                    position_from=old.get("position"),
                )
            )
            continue
        if old is None or new is None:  # pragma: no cover - defensive
            continue

        narrative_changed = (str(old.get("narrative") or "").strip()
                             != str(new.get("narrative") or "").strip())
        added, removed, changed = _compare_items(
            list(old.get("items") or []), list(new.get("items") or [])
        )
        status_from = str(old.get("status") or "")
        status_to = str(new.get("status") or "")
        approval_changed = (old.get("approved_by") or "") != (new.get("approved_by") or "")
        title_changed = str(old.get("title") or "") != str(new.get("title") or "")

        modified = any(
            [
                narrative_changed,
                added,
                removed,
                changed,
                status_from != status_to,
                approval_changed,
                title_changed,
            ]
        )
        diffs.append(
            SectionDiffSchema(
                section_key=key,
                title=str(new.get("title") or key),
                change=SectionChange.MODIFIED if modified else SectionChange.UNCHANGED,
                narrative_changed=narrative_changed,
                items_added=added,
                items_removed=removed,
                items_changed=changed,
                status_from=status_from,
                status_to=status_to,
                approval_changed=approval_changed,
                position_from=old.get("position"),
                position_to=new.get("position"),
                narrative_diff=(
                    _narrative_diff(str(old.get("narrative") or ""), str(new.get("narrative") or ""))
                    if narrative_changed
                    else []
                ),
            )
        )

    common_before = [
        str(section.get("section_key"))
        for section in before
        if str(section.get("section_key")) in after_map
    ]
    common_after = [
        str(section.get("section_key"))
        for section in after
        if str(section.get("section_key")) in before_map
    ]

    comparison = VersionComparisonSchema(
        blueprint_id=blueprint_id,
        from_version=from_version,
        to_version=to_version,
        from_label=from_label,
        to_label=to_label,
        sections_added=sum(1 for item in diffs if item.change is SectionChange.ADDED),
        sections_removed=sum(1 for item in diffs if item.change is SectionChange.REMOVED),
        sections_modified=sum(1 for item in diffs if item.change is SectionChange.MODIFIED),
        sections_unchanged=sum(1 for item in diffs if item.change is SectionChange.UNCHANGED),
        reordered=common_before != common_after,
        section_diffs=diffs,
    )
    logger.info(
        "Compared blueprint %s v%d -> v%d: %d added, %d removed, %d modified",
        blueprint_id,
        from_version,
        to_version,
        comparison.sections_added,
        comparison.sections_removed,
        comparison.sections_modified,
    )
    return comparison
