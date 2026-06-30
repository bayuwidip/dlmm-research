#!/usr/bin/env python3
"""Tests for scripts/inspect_runtime_db.py (Runtime DuckDB Inspector v0.1).

Tests that require a real DuckDB database are skipped if the optional `duckdb`
package is not installed, so the suite always runs. The safety-constant and
missing-dependency paths do not need duckdb installed.

These tests verify the inspector is strictly read-only: it never creates the
database file or its parent directory, and it never writes to an existing
database.
"""

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSPECT_PATH = REPO_ROOT / "scripts" / "inspect_runtime_db.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


insp = _load_module("inspect_runtime_db", INSPECT_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

# The init skeleton is loaded only to build a real fixture database for the
# duckdb-backed tests; it is not under test here.
idb = _load_module("init_runtime_db", INIT_PATH) if HAS_DUCKDB else None


def _make_db(tmp):
    """Create and minimally populate a fixture runtime DB. Returns its path."""
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    idb.init_db(str(db_path))

    conn = duckdb.connect(str(db_path))
    try:
        now = idb.utc_now_iso()
        conn.execute(
            "INSERT INTO pipeline_runs "
            "(run_id, started_at, ended_at, status, safety_phase, "
            "continue_on_ohlcv_error, stale_lock_replaced, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["run-1", "2026-06-30T00:00:00+00:00", "2026-06-30T00:05:00+00:00",
             "SUCCESS", idb.SAFETY_PHASE, False, False, now],
        )
        conn.execute(
            "INSERT INTO pipeline_runs "
            "(run_id, started_at, ended_at, status, safety_phase, "
            "continue_on_ohlcv_error, stale_lock_replaced, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["run-2", "2026-06-30T01:00:00+00:00", "2026-06-30T01:05:00+00:00",
             "SUCCESS", idb.SAFETY_PHASE, False, False, now],
        )
        conn.execute(
            "INSERT INTO strategy_observations "
            "(observation_id, observed_at, pair_key, pair_label, "
            "strategy_class_v2, pair_status_v2, live_eligibility, "
            "observation_ready, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ["obs-1", "2026-06-30T00:10:00+00:00", "mintA|mintB", "USDC-SOL",
             "CORE", "PAPER TEST", "PAPER_TEST_ALLOWED", True, now],
        )
    finally:
        conn.close()
    return db_path


class TestSafetyConstants(unittest.TestCase):
    def test_safety_phase_exact(self):
        self.assertEqual(
            insp.SAFETY_PHASE,
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
            self.assertIn(term, insp.SAFETY_BANNER)

    def test_required_tables_match_spec(self):
        expected = {
            "runtime_schema_meta",
            "pipeline_runs",
            "pipeline_steps",
            "strategy_observations",
            "risk_flags",
            "future_position_events",
        }
        self.assertEqual(set(insp.REQUIRED_TABLES), expected)


class TestMissingDependency(unittest.TestCase):
    def test_missing_duckdb_message_is_exact(self):
        self.assertEqual(
            insp.DUCKDB_MISSING_MSG,
            "duckdb package is required. Install with: python3 -m pip install duckdb",
        )

    def test_open_readonly_raises_clear_error_when_duckdb_missing(self):
        # Monkeypatch the dependency-check chokepoint to simulate a missing pkg.
        original = insp.require_duckdb

        def fake_require_duckdb():
            raise RuntimeError(insp.DUCKDB_MISSING_MSG)

        insp.require_duckdb = fake_require_duckdb
        try:
            with self.assertRaises(RuntimeError) as ctx:
                insp.open_readonly("unused/path/dlmm.duckdb")
            self.assertEqual(str(ctx.exception), insp.DUCKDB_MISSING_MSG)
        finally:
            insp.require_duckdb = original


class TestMissingDatabase(unittest.TestCase):
    def test_missing_db_exits_nonzero_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = insp.main(["--db-path", str(db_path)])
            self.assertNotEqual(rc, 0)
            self.assertFalse(db_path.exists(), "must not create the db file")
            self.assertFalse(
                db_path.parent.exists(), "must not create the runtime parent dir"
            )

    def test_missing_db_json_is_valid_and_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = insp.main(["--db-path", str(db_path), "--json"])
            self.assertNotEqual(rc, 0)
            data = json.loads(buf.getvalue())  # must be valid JSON
            self.assertFalse(data["exists"])
            self.assertEqual(data["status"], "DB_NOT_FOUND")
            self.assertTrue(data["inspection_only"])
            self.assertFalse(db_path.parent.exists())


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestInspectExistingDb(unittest.TestCase):
    def test_required_table_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            report = insp.build_report(str(db_path), 5, 5)
            self.assertTrue(report["exists"])
            self.assertEqual(report["status"], "OK")
            for name in insp.REQUIRED_TABLES:
                self.assertTrue(
                    report["required_tables"][name], f"{name} should be present"
                )

    def test_table_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            report = insp.build_report(str(db_path), 5, 5)
            counts = report["table_counts"]
            self.assertEqual(counts["pipeline_runs"], 2)
            self.assertEqual(counts["strategy_observations"], 1)
            self.assertEqual(counts["future_position_events"], 0)

    def test_latest_pipeline_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            report = insp.build_report(str(db_path), 5, 5)
            runs = report["latest_runs"]
            self.assertEqual(len(runs), 2)
            # Most recent first.
            self.assertEqual(runs[0]["run_id"], "run-2")
            self.assertEqual(runs[1]["run_id"], "run-1")

    def test_latest_pipeline_runs_respects_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            report = insp.build_report(str(db_path), 1, 5)
            self.assertEqual(len(report["latest_runs"]), 1)
            self.assertEqual(report["latest_runs"][0]["run_id"], "run-2")

    def test_latest_strategy_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            report = insp.build_report(str(db_path), 5, 5)
            obs = report["latest_observations"]
            self.assertEqual(len(obs), 1)
            self.assertEqual(obs[0]["pair_label"], "USDC-SOL")
            self.assertEqual(obs[0]["strategy_class_v2"], "CORE")

    def test_schema_meta_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            report = insp.build_report(str(db_path), 5, 5)
            meta = report["schema_meta"]
            self.assertIsNotNone(meta)
            self.assertEqual(meta["safety_phase"], insp.SAFETY_PHASE)
            self.assertIn("schema_name", meta)
            self.assertIn("schema_version", meta)
            self.assertIn("updated_at", meta)

    def test_json_output_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = insp.main(["--db-path", str(db_path), "--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            for key in (
                "db_path", "exists", "schema_meta", "required_tables",
                "table_counts", "latest_runs", "latest_observations",
                "status", "safety_phase", "inspection_only",
            ):
                self.assertIn(key, data)
            self.assertTrue(data["inspection_only"])
            self.assertEqual(data["safety_phase"], insp.SAFETY_PHASE)

    def test_human_output_includes_inspection_only_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = insp.main(["--db-path", str(db_path)])
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn(insp.INSPECTION_ONLY_NOTE, out)
            self.assertIn(
                "Inspection only. No database writes. No execution authority.", out
            )

    def test_future_position_events_display_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            report = insp.build_report(str(db_path), 5, 5)
            fpe = report["future_position_events"]
            self.assertEqual(fpe["count"], 0)
            self.assertIsNone(fpe["latest_event"])

    def test_inspector_does_not_write_to_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            before_mtime = os.path.getmtime(db_path)
            before_size = os.path.getsize(db_path)

            # Run inspection multiple times in both modes.
            buf = io.StringIO()
            with redirect_stdout(buf):
                insp.main(["--db-path", str(db_path)])
                insp.main(["--db-path", str(db_path), "--json"])

            after_mtime = os.path.getmtime(db_path)
            after_size = os.path.getsize(db_path)
            self.assertEqual(before_size, after_size, "db size must not change")
            self.assertEqual(before_mtime, after_mtime, "db mtime must not change")

    def test_incomplete_schema_status(self):
        # A database missing a required table reports INCOMPLETE_SCHEMA, not OK.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(db_path))
            try:
                # Create only one of the required tables.
                conn.execute(
                    "CREATE TABLE runtime_schema_meta ("
                    "schema_name TEXT, schema_version INTEGER, "
                    "safety_phase TEXT, updated_at TEXT)"
                )
            finally:
                conn.close()
            report = insp.build_report(str(db_path), 5, 5)
            self.assertEqual(report["status"], "INCOMPLETE_SCHEMA")
            self.assertFalse(report["required_tables"]["pipeline_runs"])
            self.assertIsNone(report["table_counts"]["pipeline_runs"])


if __name__ == "__main__":
    unittest.main()
