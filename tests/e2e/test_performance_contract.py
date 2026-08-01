"""Performance properties, asserted as behaviour rather than as a stopwatch.

A test that fails when a machine is busy is a test people learn to ignore, so
almost nothing here measures time. What it measures is *work*: how many rows a
paged query returns, how many SQL statements a page costs, how much of a file
the reader has to touch. Those numbers do not move when the CI runner is loaded,
and they are the ones that decide whether the API survives a file at the
documented 200,000 row limit.

The one timing assertion is deliberately loose - it exists to catch an
accidental O(n^2), not to police a few milliseconds.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import event

from app.core.config import PROJECT_ROOT
from app.models.session import engine
from app.services.files.readers import read_tabular
from tests.e2e.conftest import CSV_MIME, assert_pagination, ok, upload

pytestmark = pytest.mark.slow

V1 = "/api/v1"


class StatementCounter:
    """Count the SQL statements a block of code executes."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> StatementCounter:
        event.listen(engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *_exc: object) -> None:
        event.remove(engine, "before_cursor_execute", self._record)

    def _record(self, _conn, _cursor, statement, *_args) -> None:  # noqa: ANN001
        self.statements.append(statement)

    @property
    def count(self) -> int:
        return len(self.statements)


@pytest.fixture(scope="module")
def analysis_id(client) -> str:
    """One analysis over the full demo dataset."""
    path = PROJECT_ROOT / "data" / "sample" / "sample_purchase_orders.csv"
    if not path.is_file():
        pytest.skip("the demo purchase order dataset is not generated")
    uploaded = upload(client, path, f"{V1}/po-risk/upload", filename=path.name, mime=CSV_MIME)
    analysis = ok(
        client.post(
            f"{V1}/po-risk/analyze",
            json={"upload_id": uploaded["upload_id"], "generate_ai_summary": False},
        )
    )
    return analysis["analysis_id"]


class TestPagingIsBounded:
    def test_a_page_of_findings_reads_only_that_page(self, client, analysis_id):
        """The ordering and the window both belong in SQL.

        This endpoint used to read every matching finding into memory, sort it
        in Python and slice - returning 25 rows after building all of them. On
        the demo file that is 131 objects for 25 rows; at the row limit it is
        tens of thousands, on every page load.
        """
        everything = ok(
            client.get(f"{V1}/po-risk/analyses/{analysis_id}/findings", params={"limit": 1000})
        )
        assert everything["total"] > 25, "the demo dataset is too small for this check"

        with StatementCounter() as counter:
            page = ok(
                client.get(
                    f"{V1}/po-risk/analyses/{analysis_id}/findings",
                    params={"limit": 25, "offset": 0},
                )
            )

        assert len(page["findings"]) == 25
        # One existence check, one count, one page. A handful more would be
        # fine; an N+1 would be dozens.
        assert counter.count <= 6, f"a page of findings cost {counter.count} statements"

        # The LIMIT really reached the database rather than a Python slice.
        assert any(
            "LIMIT" in statement.upper() for statement in counter.statements
        ), "no LIMIT was sent to the database"

    def test_the_severity_order_survived_moving_into_sql(self, client, analysis_id):
        """Critical first, then by exposure - the same order as before."""
        page = ok(
            client.get(f"{V1}/po-risk/analyses/{analysis_id}/findings", params={"limit": 200})
        )
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        ranks = [rank[item["severity"]] for item in page["findings"]]
        assert ranks == sorted(ranks), "findings are no longer ordered most serious first"

        for first, second in zip(page["findings"], page["findings"][1:], strict=False):
            if first["severity"] == second["severity"]:
                assert (first["estimated_financial_exposure"] or 0) >= (
                    second["estimated_financial_exposure"] or 0
                ), "within a severity, the larger exposure must come first"

    def test_paging_through_everything_visits_each_finding_once(self, client, analysis_id):
        """A stable order is what makes paging safe; without one, rows repeat."""
        seen: list[str] = []
        offset = 0
        while True:
            page = ok(
                client.get(
                    f"{V1}/po-risk/analyses/{analysis_id}/findings",
                    params={"limit": 40, "offset": offset},
                )
            )
            assert_pagination(page, items_key="findings")
            if not page["findings"]:
                break
            seen.extend(item["finding_id"] for item in page["findings"])
            offset += 40
            if offset > page["total"]:
                break

        assert len(seen) == len(set(seen)), "paging returned the same finding twice"
        assert len(seen) == page["total"]

    def test_a_list_endpoint_refuses_an_unbounded_limit(self, client):
        """`limit=1000000` is how one request becomes a full table scan."""
        response = client.get(f"{V1}/po-risk/analyses", params={"limit": 1_000_000})
        assert response.status_code == 422


class TestFileReading:
    def test_the_demo_spend_file_parses_quickly(self):
        """A loose ceiling that catches an accidental per-cell Python loop.

        3,640 rows x 33 columns. Measured on the machine this was written on:
        ~127 ms with the Python parser and the per-cell cleaner, ~87 ms with the
        C parser and the vectorised one - about a third off, and the gap grows
        with row count because both halves are linear in cells rather than rows.

        The assertion is 500 ms, roughly six times the fast figure. It is not
        policing milliseconds; it fails if the vectorised path is bypassed and
        6.6 million Python calls come back at the row limit.
        """
        path = PROJECT_ROOT / "data" / "sample" / "sample_spend_transactions.csv"
        if not path.is_file():
            pytest.skip("the demo spend dataset is not generated")
        content = path.read_bytes()

        best = min(
            (self._time(read_tabular, content, ".csv") for _ in range(3)),
        )
        assert best < 0.5, f"reading the demo spend file took {best * 1000:.0f} ms"

    @staticmethod
    def _time(function, *args) -> float:
        started = time.perf_counter()
        function(*args)
        return time.perf_counter() - started

    def test_the_row_limit_is_enforced_before_analysis(self):
        """A file past the row limit is refused by the reader, not the engine."""
        from app.core.config import settings
        from app.core.exceptions import FileValidationError

        header = b"LIFNR,NAME1\n"
        row = b"0000100001,Acme\n"
        oversized = header + row * (settings.max_rows_per_upload + 10)

        with pytest.raises(FileValidationError) as raised:
            read_tabular(oversized, ".csv")
        assert "row limit" in str(raised.value).lower()

    def test_cleaning_preserves_the_values_the_engines_depend_on(self):
        """The vectorised path must agree with the per-cell rule exactly.

        Leading zeros survive, blanks and placeholders become null, and a real
        value with internal spaces is only trimmed at the ends. Module 3 shipped
        a bug because ``"None"`` round-tripped differently from ``None``.
        """
        content = (
            b"LIFNR,NAME1,NOTE\n"
            b'0000004711,  Acme GmbH  ,"a  b"\n'
            b"0000004712,,-\n"
            b"0000004713,N/A,nan\n"
        )

        frame = read_tabular(content, ".csv").dataframe

        assert frame.loc[0, "LIFNR"] == "0000004711", "a leading zero was lost"
        assert frame.loc[0, "NAME1"] == "Acme GmbH"
        assert frame.loc[0, "NOTE"] == "a  b", "internal spacing must be preserved"
        assert frame.loc[1, "NAME1"] is None
        assert frame.loc[1, "NOTE"] is None
        assert frame.loc[2, "NAME1"] is None
        assert frame.loc[2, "NOTE"] is None

    def test_a_json_file_keeps_its_real_types(self):
        """The vectorised path must not be taken for mixed content.

        ``.str.strip()`` turns a number into ``NaN``; JSON records carry real
        numbers, so those columns have to use the per-cell rule.
        """
        content = (
            b'[{"LIFNR": "0000004711", "MENGE": 10, "NETPR": 5.5, "OK": true},'
            b' {"LIFNR": "0000004712", "MENGE": 20, "NETPR": 6.5, "OK": false}]'
        )
        frame = read_tabular(content, ".json").dataframe

        assert frame.loc[0, "MENGE"] == 10
        assert frame.loc[0, "NETPR"] == 5.5
        assert frame.loc[0, "OK"] is True or frame.loc[0, "OK"] == True  # noqa: E712
        assert frame.loc[0, "LIFNR"] == "0000004711"


class TestAnalysisCost:
    def test_running_an_analysis_does_not_scale_statements_with_rows(
        self, client, analysis_id
    ):
        """Persisting N findings must not be N inserts plus N selects.

        The check is deliberately generous: what it catches is a loop that
        issues a query per row, which is the shape that turns a 30-second
        analysis into an overnight one.
        """
        path = PROJECT_ROOT / "data" / "sample" / "sample_purchase_orders.csv"
        if not path.is_file():
            pytest.skip("the demo purchase order dataset is not generated")
        uploaded = upload(client, path, f"{V1}/po-risk/upload", filename=path.name, mime=CSV_MIME)

        with StatementCounter() as counter:
            analysis = ok(
                client.post(
                    f"{V1}/po-risk/analyze",
                    json={"upload_id": uploaded["upload_id"], "generate_ai_summary": False},
                )
            )

        rows = analysis["record_count"]
        assert rows > 1000, "the demo dataset is too small for this check"
        assert counter.count < rows / 4, (
            f"{counter.count} statements for {rows} rows looks like a per-row query"
        )
