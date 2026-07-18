"""M6 tests — backup (online-backup API) and export/import bundle roundtrip."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from boonyard import (
    backup_node,
    export_bundle,
    import_bundle,
    init_db,
    log_entry,
    query,
    search_by_tag_exact,
    search_text,
)
from boonyard.cli import main as cli_main


def _seed(path: Path) -> None:
    init_db(path, node_name="src")
    log_entry("code", "note", "the quick brown fox", tags="alpha,animal", db_path=path)
    root = log_entry("code", "discussion", "root of a thread", tags="beta", db_path=path)
    log_entry("opus", "decision", "a threaded child", related_id=root, db_path=path)


class BackupTests(unittest.TestCase):
    def test_backup_equals_source(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "journal.db"
            _seed(src)
            dest = Path(d) / "backup.db"
            backup_node(dest, db_path=src)
            self.assertTrue(dest.exists())
            src_rows = query.recent(db_path=src)
            dest_rows = query.recent(db_path=dest)
            self.assertEqual([r["content"] for r in src_rows], [r["content"] for r in dest_rows])

    def test_backup_preserves_fts_and_tags(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "journal.db"
            _seed(src)
            dest = Path(d) / "backup.db"
            backup_node(dest, db_path=src)
            self.assertEqual(len(search_text("fox", db_path=dest)), 1)
            self.assertEqual(len(search_by_tag_exact("animal", db_path=dest)), 1)


class ExportImportTests(unittest.TestCase):
    def test_bundle_contains_expected_members(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "journal.db"
            _seed(src)
            (Path(d) / "boonyard.toml").write_text('[node]\nname = "src"\n')
            bundle = Path(d) / "out.zip"
            export_bundle(
                bundle,
                db_path=src,
                profile_path=Path(d) / "boonyard.toml",
                exported_at="2026-07-17T00:00:00+00:00",
            )
            with zipfile.ZipFile(bundle) as zf:
                names = set(zf.namelist())
            self.assertEqual(
                {"journal.db", "boonyard-export.json", "README.txt", "boonyard.toml"} & names,
                {"journal.db", "boonyard-export.json", "README.txt", "boonyard.toml"},
            )

    def test_roundtrip_preserves_everything(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "journal.db"
            _seed(src)
            bundle = Path(d) / "out.zip"
            export_bundle(bundle, db_path=src)
            dest = Path(d) / "restored" / "journal.db"
            import_bundle(bundle, dest)
            # counts
            self.assertEqual(len(query.recent(db_path=src)), len(query.recent(db_path=dest)))
            # content + threading
            thread = query.get_thread(2, db_path=dest)
            self.assertIn("a threaded child", [e["content"] for e in thread])
            # tags + FTS searchability survive
            self.assertEqual(len(search_by_tag_exact("animal", db_path=dest)), 1)
            self.assertEqual(len(search_text("brown", db_path=dest)), 1)

    def test_import_rejects_non_bundle_zip(self):
        with tempfile.TemporaryDirectory() as d:
            bogus = Path(d) / "bogus.zip"
            with zipfile.ZipFile(bogus, "w") as zf:
                zf.writestr("random.txt", "not a bundle")
            with self.assertRaises(ValueError):
                import_bundle(bogus, Path(d) / "dest.db")

    def test_import_rejects_non_zip(self):
        with tempfile.TemporaryDirectory() as d:
            notzip = Path(d) / "plain.txt"
            notzip.write_text("hello")
            with self.assertRaises(ValueError):
                import_bundle(notzip, Path(d) / "dest.db")

    def test_import_refuses_to_clobber(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "journal.db"
            _seed(src)
            bundle = Path(d) / "out.zip"
            export_bundle(bundle, db_path=src)
            existing = Path(d) / "existing.db"
            existing.write_text("occupied")
            with self.assertRaises(ValueError):
                import_bundle(bundle, existing)
            # overwrite=True proceeds
            import_bundle(bundle, existing, overwrite=True)
            self.assertEqual(len(query.recent(db_path=existing)), 3)


class CliBackupExportTests(unittest.TestCase):
    def _run(self, argv):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli_main(argv)

    def test_cli_backup_export_import(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "node" / "journal.db")
            self._run(["--db", db, "init", "--name", "n"])
            self._run(["--db", db, "log", "code", "note", "hi", "--tags", "a"])
            self.assertEqual(self._run(["--db", db, "backup"]), 0)
            self.assertTrue(Path(f"{db}.bak").exists())
            self.assertEqual(self._run(["--db", db, "export"]), 0)
            self.assertTrue(Path(f"{db}.export.zip").exists())
            dest = str(Path(d) / "restored" / "journal.db")
            self.assertEqual(self._run(["--db", dest, "import", f"{db}.export.zip"]), 0)
            self.assertEqual(len(query.recent(db_path=dest)), 1)

    def test_cli_import_bad_bundle_exits_usage(self):
        with tempfile.TemporaryDirectory() as d:
            plain = Path(d) / "plain.txt"
            plain.write_text("nope")
            dest = str(Path(d) / "dest.db")
            self.assertEqual(self._run(["--db", dest, "import", str(plain)]), 2)


if __name__ == "__main__":
    unittest.main()
