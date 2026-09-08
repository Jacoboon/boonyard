"""Two writers on one wall — the lock behaviour ADR-0014 §0.1 assumed (umbrella #412 item 4).

§0.1 keeps both doors alive on every migrated wall and justifies it with "two writers
on one SQLite file is what WAL is for". WAL lets writers and READERS coexist; it does
not let two WRITERS coexist, so the ruling asked for the lock behaviour to be measured
rather than assumed.

⚠ MEASURED, AND THE PREMISE IS HALF-WRONG. **SQLite's own default ``busy_timeout`` is
0** — true, and ``test_a_zero_timeout_fails_on_contact`` proves the failure is real.
But **Python's ``sqlite3.connect()`` defaults ``timeout=5.0``**, which sets
``busy_timeout`` to 5000 ms, and this package is stdlib ``sqlite3`` throughout. So the
effective default here was already 5000, never 0, and the "writer fails on contact"
failure mode **did not exist in this codebase**. §0.1's design call was right; its
stated reason was not, and nobody had checked which.

The explicit pragma stays anyway, for a smaller and honest reason: it PINS the value
instead of inheriting it from a module default that any caller passing ``timeout=``
would silently change. That is a guarantee made explicit, not a bug fixed.
"""

import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from boonyard import init_db, log_entry, meter
from boonyard.db import BUSY_TIMEOUT_MS, connect


class ContentionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "journal.db"
        init_db(self.db, node_name="contended")

    def _hold_write_lock(self, seconds: float) -> threading.Event:
        """Take a real write lock in another thread and hold it. Returns a 'held' flag."""
        held, done = threading.Event(), threading.Event()

        def holder():
            conn = sqlite3.connect(str(self.db))
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("BEGIN IMMEDIATE")  # the writer lock, taken for real
            conn.execute(
                "INSERT INTO entry (agent, entry_type, content) VALUES (?,?,?)",
                ("code", "note", "holder"),
            )
            held.set()
            time.sleep(seconds)
            conn.commit()
            conn.close()
            done.set()

        t = threading.Thread(target=holder, daemon=True)
        t.start()
        self.addCleanup(lambda: done.wait(timeout=5))
        held.wait(timeout=5)
        return held

    def test_a_zero_timeout_fails_on_contact(self):
        """THE FAILURE IS REAL when the timeout is genuinely 0 — SQLite's own default."""
        self._hold_write_lock(0.6)
        conn = sqlite3.connect(str(self.db), timeout=0)
        started = time.perf_counter()
        with self.assertRaises(sqlite3.OperationalError) as caught:
            conn.execute(
                "INSERT INTO entry (agent, entry_type, content) VALUES (?,?,?)",
                ("code", "note", "loser"),
            )
            conn.commit()
        elapsed = time.perf_counter() - started
        conn.close()
        self.assertIn("locked", str(caught.exception))
        self.assertLess(elapsed, 0.3, "it failed immediately rather than waiting")

    def test_but_pythons_own_default_was_never_zero(self):
        """The correction to the ruling's premise, pinned so nobody re-derives it wrong."""
        bare = sqlite3.connect(str(self.db))
        self.assertEqual(bare.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
        bare.close()
        self.assertEqual(
            sqlite3.connect(":memory:", timeout=0).execute("PRAGMA busy_timeout").fetchone()[0], 0
        )

    def test_the_package_pins_it_explicitly_rather_than_inheriting_it(self):
        with connect(self.db) as conn:
            self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], BUSY_TIMEOUT_MS)

    def test_the_package_connection_waits_and_wins(self):
        """THE FIX, measured: same collision, through db.connect, lands the row."""
        self._hold_write_lock(0.6)
        started = time.perf_counter()
        with connect(self.db) as conn:
            conn.execute(
                "INSERT INTO entry (agent, entry_type, content) VALUES (?,?,?)",
                ("code", "note", "winner"),
            )
        elapsed = time.perf_counter() - started
        self.assertGreater(elapsed, 0.3, "it should have WAITED for the holder")
        self.assertLess(elapsed, BUSY_TIMEOUT_MS / 1000)
        with connect(self.db, read_only=True) as conn:
            contents = {r["content"] for r in conn.execute("SELECT content FROM entry")}
        self.assertIn("winner", contents)
        self.assertIn("holder", contents)

    def test_two_doors_writing_the_same_wall_both_land(self):
        """§0.1's actual shape: the wall's own door and the account door, same file."""
        errors, ids = [], []
        barrier = threading.Barrier(6)

        def writer(n):
            barrier.wait()
            try:
                ids.append(log_entry("code", "note", f"door {n}", db_path=self.db))
            except Exception as exc:  # noqa: BLE001 — the point is to count these
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        self.assertEqual(errors, [], "no writer may lose the race")
        self.assertEqual(len(set(ids)), 6, "six distinct ids, no collision")

    def test_the_meter_does_not_silently_drop_a_row_under_contention(self):
        """The worst place to lose the race: every function here swallows exceptions,
        so a lock collision would discard the row in silence and the heat would just
        be missing, with nothing saying so."""
        mpath = Path(self._tmp.name) / "meter.db"
        meter.record(mpath, "warmup", node="contended")
        held, done = threading.Event(), threading.Event()

        def holder():
            conn = sqlite3.connect(str(mpath))
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO meter (ts, tool, node, kind) VALUES ('t','holder','n','read')"
            )
            held.set()
            time.sleep(0.5)
            conn.commit()
            conn.close()
            done.set()

        threading.Thread(target=holder, daemon=True).start()
        held.wait(timeout=5)
        landed = meter.record(mpath, "contended_read", node="contended")
        done.wait(timeout=5)
        self.assertTrue(landed, "the meter row must not be silently discarded")
        conn = sqlite3.connect(f"file:{mpath.as_posix()}?mode=ro", uri=True)
        tools = {r[0] for r in conn.execute("SELECT tool FROM meter")}
        conn.close()
        self.assertIn("contended_read", tools)


if __name__ == "__main__":
    unittest.main(verbosity=2)
