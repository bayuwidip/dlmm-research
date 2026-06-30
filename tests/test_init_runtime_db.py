#!/usr/bin/env python3
"""Tests for scripts/init_runtime_db.py (Runtime DuckDB Storage Skeleton v0.1).

Tests that require a real DuckDB database are skipped if the optional `duckdb`
package is not installed, so the suite always runs. The dry-run, print-schema,
safety-banner, and missing-dependency paths do not need duckdb installed.
"""

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("init_runtime_db", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


idb = _load_module()

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


class TestSafetyConstants(unittest.TestCase):
    def test_safety_phase_exact(self):
        self.assertEqual(
            idb.SAFETY_PHASE,
            "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
        )

    def test_safety_banner_contains_all_boundary_terms(self):
        required_terms = [
            "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
            "No wallet",
            "No private key",
            "No signing",
            "No swap",
            "No LP",
            "No rebalance",
            "No live execution",
            "No LIVE_ELIGIBLE_*",
        ]
        for term in required_terms:
            self.assertIn(term, idb.SAFETY_BANNER)

    def test_schema_version_is_one(self):
        self.assertEqual(idb.SCHEMA_VERSION, 1)

    def test_schema_name(self):
        self.assertEqual(idb.SCHEMA_NAME, "runtime_storage")


class TestSchemaSql(unittest.TestCase):
    def test_schema_sql_contains_all_safety_boundary_terms(self):
        sql = idb.build_schema_sql()
        for line in idb.SAFETY_BANNER.splitlines():
            self.assertIn(line, sql)

    def test_schema_sql_contains_all_required_tables(self):
        sql = idb.build_schema_sql()
        for name in idb.REQUIRED_TABLES:
            self.assertIn(name, sql)

    def test_required_tables_match_spec(self):
        expected = {
            "runtime_schema_meta",
            "pipeline_runs",
            "pipeline_steps",
            "strategy_observations",
            "risk_flags",
            "future_position_events",
        }
        self.assertEqual(set(idb.REQUIRED_TABLES), expected)

    def test_schema_uses_create_if_not_exists_only(self):
        sql = idb.build_schema_sql().upper()
        # Idempotent and non-destructive: no DROP, no DELETE, no TRUNCATE.
        self.assertNotIn("DROP TABLE", sql)
        self.assertNotIn("DELETE FROM", sql)
        self.assertNotIn("TRUNCATE", sql)
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"), len(idb.REQUIRED_TABLES))


class TestPrintSchemaAndDryRun(unittest.TestCase):
    def test_print_schema_outputs_table_names(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = idb.main(["--print-schema", "--dry-run"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        for name in idb.REQUIRED_TABLES:
            self.assertIn(name, out)

    def test_dry_run_creates_no_db_file_and_no_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = idb.main(["--db-path", str(db_path), "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertFalse(db_path.exists(), "dry-run must not create the db file")
            self.assertFalse(
                db_path.parent.exists(), "dry-run must not create the runtime parent dir"
            )

    def test_dry_run_with_print_schema_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = idb.main(["--db-path", str(db_path), "--dry-run", "--print-schema"])
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertFalse(db_path.exists())
            self.assertFalse(db_path.parent.exists())
            # Schema still printed.
            self.assertIn("runtime_schema_meta", out)


class TestMissingDependency(unittest.TestCase):
    def test_missing_duckdb_message_is_exact(self):
        self.assertEqual(
            idb.DUCKDB_MISSING_MSG,
            "duckdb package is required. Install with: python3 -m pip install duckdb",
        )

    def test_init_db_raises_clear_error_when_duckdb_missing(self):
        # Monkeypatch the dependency-check chokepoint to simulate a missing package.
        original = idb.require_duckdb

        def fake_require_duckdb():
            raise RuntimeError(idb.DUCKDB_MISSING_MSG)

        idb.require_duckdb = fake_require_duckdb
        try:
            with self.assertRaises(RuntimeError) as ctx:
                idb.init_db("unused/path/dlmm.duckdb")
            self.assertEqual(str(ctx.exception), idb.DUCKDB_MISSING_MSG)
        finally:
            idb.require_duckdb = original

    def test_require_duckdb_uses_clear_message_when_import_fails(self):
        # Simulate ImportError by blocking the duckdb import via sys.modules.
        original = idb.require_duckdb
        sentinel = sys.modules.get("duckdb", None)

        # Restore the real function (in case a prior test left a patch).
        idb.require_duckdb = original
        sys.modules["duckdb"] = None  # forces `import duckdb` to raise ImportError
        try:
            with self.assertRaises(RuntimeError) as ctx:
                idb.require_duckdb()
            self.assertEqual(str(ctx.exception), idb.DUCKDB_MISSING_MSG)
        finally:
            if sentinel is None:
                sys.modules.pop("duckdb", None)
            else:
                sys.modules["duckdb"] = sentinel


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestInitDb(unittest.TestCase):
    def test_init_creates_db_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            path = idb.init_db(str(db_path))
            self.assertTrue(db_path.exists(), "init must create the db file")
            self.assertEqual(path, db_path)

    def test_required_tables_exist_after_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            idb.init_db(str(db_path))
            conn = duckdb.connect(str(db_path))
            try:
                present = idb.list_tables(conn)
            finally:
                conn.close()
            for name in idb.REQUIRED_TABLES:
                self.assertIn(name, present)

    def test_schema_meta_row_exists_with_version_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            idb.init_db(str(db_path))
            conn = duckdb.connect(str(db_path))
            try:
                row = conn.execute(
                    "SELECT schema_name, schema_version, safety_phase "
                    "FROM runtime_schema_meta WHERE schema_name = ?",
                    [idb.SCHEMA_NAME],
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)
            name, version, phase = row
            self.assertEqual(name, "runtime_storage")
            self.assertEqual(version, 1)
            self.assertEqual(phase, idb.SAFETY_PHASE)

    def test_init_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            idb.init_db(str(db_path))
            # Second run must not error and must keep exactly one meta row.
            idb.init_db(str(db_path))
            conn = duckdb.connect(str(db_path))
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM runtime_schema_meta"
                ).fetchone()[0]
                present = idb.list_tables(conn)
            finally:
                conn.close()
            self.assertEqual(count, 1)
            for name in idb.REQUIRED_TABLES:
                self.assertIn(name, present)

    def test_force_does_not_drop_existing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            idb.init_db(str(db_path))

            # Insert a row to simulate existing history.
            conn = duckdb.connect(str(db_path))
            try:
                conn.execute(
                    "INSERT INTO pipeline_runs "
                    "(run_id, started_at, status, safety_phase, "
                    "continue_on_ohlcv_error, stale_lock_replaced, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        "run-1",
                        idb.utc_now_iso(),
                        "SUCCESS",
                        idb.SAFETY_PHASE,
                        False,
                        False,
                        idb.utc_now_iso(),
                    ],
                )
            finally:
                conn.close()

            # Re-init with --force; data must survive.
            idb.init_db(str(db_path), force=True)

            conn = duckdb.connect(str(db_path))
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM pipeline_runs WHERE run_id = ?", ["run-1"]
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 1, "--force must not drop existing data")

    def test_validate_schema_passes_after_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            idb.init_db(str(db_path))
            conn = duckdb.connect(str(db_path))
            try:
                # Should not raise.
                idb.validate_schema(conn)
            finally:
                conn.close()

    def test_main_default_path_initializes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = idb.main(["--db-path", str(db_path)])
            self.assertEqual(rc, 0)
            self.assertTrue(db_path.exists())


if __name__ == "__main__":
    unittest.main()
