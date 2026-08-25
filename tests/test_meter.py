"""Meter tests — the sidecar that makes read-vs-write countable (umbrella #228 Layer 3).

Three properties are load-bearing and each has a test that FAILS if the property
is removed: the meter never raises into the tool path, it never stores an
argument, and its totals are the truth about what was served.
"""

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from boonyard import meter

# Pinned so a window assertion never drifts with the wall clock.
PINNED = date(2026, 8, 25)


def _at(day: str, hour: int = 12) -> str:
    """A local-ISO timestamp on ``day`` (YYYY-MM-DD)."""
    return f"{day}T{hour:02d}:00:00"


class MeterPathTests(unittest.TestCase):
    def test_default_path_is_the_node_s_sibling(self):
        self.assertEqual(meter.default_meter_path("node/journal.db"), Path("node") / "meter.db")


class RecordTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "node" / "meter.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _rows(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT ts, tool, node, kind FROM meter")]
        finally:
            conn.close()

    def test_record_inserts_one_row_and_creates_the_sidecar(self):
        self.assertTrue(meter.record(self.path, "search_text", node="umbrella", kind="read"))
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tool"], "search_text")
        self.assertEqual(rows[0]["node"], "umbrella")
        self.assertEqual(rows[0]["kind"], "read")

    def test_record_stamps_local_wall_clock_not_utc(self):
        meter.record(self.path, "recent")
        self.assertTrue(self._rows()[0]["ts"].startswith(date.today().isoformat()))

    def test_record_never_raises_and_reports_failure(self):
        """THE METER MUST NOT BE ABLE TO BREAK A READ.

        Parent is a FILE, so the sidecar can never be created. record() must
        report False rather than letting an OSError escape into the tool path.
        """
        blocker = Path(self._tmp.name) / "blocker"
        blocker.write_text("i am a file, not a directory", encoding="utf-8")
        self.assertFalse(meter.record(blocker / "meter.db", "search_text"))

    def test_record_with_no_path_is_a_no_op(self):
        self.assertFalse(meter.record(None, "search_text"))

    def test_record_takes_no_argument_parameter_at_all(self):
        """Arguments are structurally unloggable: the function cannot accept them.

        The cheapest guarantee that a query string never reaches disk is an API
        that has nowhere to put one. If a future signature grows an args/params
        field, this fails and the reviewer has to justify it.
        """
        import inspect

        params = set(inspect.signature(meter.record).parameters)
        self.assertEqual(params, {"meter_path", "tool", "node", "kind", "ts"})
        for forbidden in ("args", "arguments", "params", "query", "payload"):
            self.assertNotIn(forbidden, params)


class ReadStatsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "meter.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _seed(self, spec):
        for day, tool, kind, n in spec:
            for _ in range(n):
                meter.record(self.path, tool, node="umbrella", kind=kind, ts=_at(day))

    def test_totals_and_ratio(self):
        self._seed(
            [
                ("2026-08-25", "search_text", "read", 6),
                ("2026-08-25", "recent", "read", 2),
                ("2026-08-25", "log_entry", "write", 4),
            ]
        )
        stats = meter.read_stats(7, today=PINNED, meter_path=self.path)
        self.assertEqual(stats["totals"], {"reads": 8, "writes": 4, "ratio": 2.0})
        self.assertEqual(stats["by_tool"], {"search_text": 6, "log_entry": 4, "recent": 2})
        self.assertEqual(stats["warnings"], [])

    def test_ratio_when_nothing_was_written(self):
        self._seed([("2026-08-25", "search_text", "read", 3)])
        stats = meter.read_stats(7, today=PINNED, meter_path=self.path)
        self.assertEqual(stats["totals"]["ratio"], 3.0)

    def test_ratio_below_one_is_the_failure_shape(self):
        """Twelve writes and zero searches — the session #228 called invisibly broken."""
        self._seed([("2026-08-25", "log_entry", "write", 12)])
        stats = meter.read_stats(7, today=PINNED, meter_path=self.path)
        self.assertEqual(stats["totals"], {"reads": 0, "writes": 12, "ratio": 0.0})

    def test_window_is_inclusive_of_today_and_bounded(self):
        self._seed(
            [
                ("2026-08-25", "recent", "read", 1),
                ("2026-08-24", "recent", "read", 1),
                ("2026-08-01", "recent", "read", 1),
            ]
        )
        one_day = meter.read_stats(1, today=PINNED, meter_path=self.path)
        self.assertEqual(one_day["since"], "2026-08-25")
        self.assertEqual(one_day["until"], "2026-08-25")
        self.assertEqual(one_day["totals"]["reads"], 1)
        week = meter.read_stats(7, today=PINNED, meter_path=self.path)
        self.assertEqual(week["since"], "2026-08-19")
        self.assertEqual(week["totals"]["reads"], 2)  # the 08-01 row is out of window
        wide = meter.read_stats(60, today=PINNED, meter_path=self.path)
        self.assertEqual(wide["totals"]["reads"], 3)

    def test_by_day_is_ordered_and_split_by_kind(self):
        self._seed(
            [
                ("2026-08-24", "recent", "read", 2),
                ("2026-08-25", "log_entry", "write", 1),
                ("2026-08-25", "search_text", "read", 3),
            ]
        )
        by_day = meter.read_stats(7, today=PINNED, meter_path=self.path)["by_day"]
        self.assertEqual(
            by_day,
            [
                {"date": "2026-08-24", "reads": 2, "writes": 0},
                {"date": "2026-08-25", "reads": 3, "writes": 1},
            ],
        )

    def test_absent_meter_warns_and_does_not_raise(self):
        stats = meter.read_stats(7, today=PINNED, meter_path=self.path)
        self.assertEqual(stats["totals"], {"reads": 0, "writes": 0, "ratio": 0.0})
        self.assertEqual(stats["warnings"][0]["kind"], "meter_absent")

    def test_unreadable_meter_warns_and_does_not_raise(self):
        self.path.write_bytes(b"this is not a database")
        stats = meter.read_stats(7, today=PINNED, meter_path=self.path)
        self.assertEqual(stats["warnings"][0]["kind"], "meter_unreadable")
        self.assertEqual(stats["totals"]["reads"], 0)

    def test_no_meter_configured_warns(self):
        stats = meter.read_stats(7, today=PINNED, meter_path=None)
        self.assertEqual(stats["warnings"][0]["kind"], "meter_disabled")

    def test_pinned_today_accepts_a_string(self):
        self.assertEqual(
            meter.read_stats(1, today="2026-08-25", meter_path=self.path)["until"], "2026-08-25"
        )


if __name__ == "__main__":
    unittest.main()
