#!/usr/bin/env python3
"""Tests for scripts/import_run_summary_to_db.py (Run Summary Importer v0.1).

Tests that need a real DuckDB database are skipped when the optional `duckdb`
package is not installed, so the suite always runs. The safety-banner,
missing-file, JSON-validation, and missing-dependency paths do not need duckdb.
"""

import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
IMPORTER_PATH = REPO_ROOT / "scripts" / "import_run_summary_to_db.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


imp = _load_module("import_run_summary_to_db", IMPORTER_PATH)
idb = _load_module("init_runtime_db", INIT_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


SAMPLE_SUMMARY = {
    "run_id": "20260630T034804_340325",
    "started_at": "2026-06-30T03:48:04.340325+00:00",
    "ended_at": "2026-06-30T03:48:16.209502+00:00",
    "duration_seconds": 11.869177,
    "status": "SUCCESS",
    "safety_phase": "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
    "continue_on_ohlcv_error": False,
    "ohlcv_error_tolerated": False,
    "stale_lock_replaced": False,
    "log_file": "runtime/logs/run_20260630T034804_340325.log",
    "steps": [
        {
            "name": "fetch_meteora_pools",
            "command": "/usr/bin/python3 scripts/fetch_meteora_pools.py",
            "started_at": "2026-06-30T03:48:04.340627+00:00",
            "ended_at": "2026-06-30T03:48:06.346142+00:00",
            "duration_seconds": 2.005515,
            "exit_code": 0,
            "status": "OK",
        },
        {
            "name": "build_watchlist",
            "command": "/usr/bin/python3 scripts/build_watchlist.py",
            "started_at": "2026-06-30T03:48:06.347601+00:00",
            "ended_at": "2026-06-30T03:48:06.408087+00:00",
            "duration_seconds": 0.060486,
            "exit_code": 0,
            "status": "OK",
        },
    ],
}


def _write_summary(directory, summary, name="summary.json"):
    path = Path(directory) / name
    with path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    return path


def _init_db(directory, name="dlmm.duckdb"):
    db_path = Path(directory) / "runtime" / name
    idb.init_db(str(db_path))
    return db_path


# ---------------------------------------------------------------------------
# Safety + constant checks (no duckdb required)
# ---------------------------------------------------------------------------

class TestSafetyConstants(unittest.TestCase):
    def test_safety_phase_exact(self):
        self.assertEqual(
            imp.SAFETY_PHASE,
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
            self.assertIn(term, imp.SAFETY_BANNER)

    def test_forbidden_write_tables_listed(self):
        self.assertEqual(
            set(imp.FORBIDDEN_WRITE_TABLES),
            {"strategy_observations", "risk_flags", "future_position_events"},
        )

    def test_required_schema_tables(self):
        self.assertEqual(
            imp.REQUIRED_SCHEMA_TABLES,
            ("runtime_schema_meta", "pipeline_runs", "pipeline_steps"),
        )


# ---------------------------------------------------------------------------
# JSON validation (no duckdb required)
# ---------------------------------------------------------------------------

class TestSummaryValidation(unittest.TestCase):
    def test_valid_summary_passes(self):
        imp.validate_summary(copy.deepcopy(SAMPLE_SUMMARY))  # must not raise
        imp.validate_safety_phase(copy.deepcopy(SAMPLE_SUMMARY))  # must not raise

    def test_missing_top_level_field_fails(self):
        bad = copy.deepcopy(SAMPLE_SUMMARY)
        del bad["duration_seconds"]
        with self.assertRaises(imp.SummaryValidationError):
            imp.validate_summary(bad)

    def test_missing_step_field_fails(self):
        bad = copy.deepcopy(SAMPLE_SUMMARY)
        del bad["steps"][0]["exit_code"]
        with self.assertRaises(imp.SummaryValidationError):
            imp.validate_summary(bad)

    def test_invalid_safety_phase_fails(self):
        bad = copy.deepcopy(SAMPLE_SUMMARY)
        bad["safety_phase"] = "LIVE_ELIGIBLE_CORE"
        with self.assertRaises(imp.SafetyPhaseError):
            imp.validate_safety_phase(bad)


# ---------------------------------------------------------------------------
# Missing dependency path (no duckdb required)
# ---------------------------------------------------------------------------

class TestMissingDependency(unittest.TestCase):
    def test_missing_duckdb_message_is_exact(self):
        self.assertEqual(
            imp.DUCKDB_MISSING_MSG,
            "duckdb package is required. Install with: python3 -m pip install duckdb",
        )

    def test_connect_db_raises_clear_error_when_duckdb_missing(self):
        # Monkeypatch the dependency-check chokepoint to simulate a missing package.
        original = imp.require_duckdb

        def fake_require_duckdb():
            raise RuntimeError(imp.DUCKDB_MISSING_MSG)

        imp.require_duckdb = fake_require_duckdb
        try:
            with self.assertRaises(RuntimeError) as ctx:
                imp.connect_db("unused/path/dlmm.duckdb")
            self.assertEqual(str(ctx.exception), imp.DUCKDB_MISSING_MSG)
        finally:
            imp.require_duckdb = original

    def test_require_duckdb_uses_clear_message_when_import_fails(self):
        original = imp.require_duckdb
        sentinel = sys.modules.get("duckdb", None)
        imp.require_duckdb = original
        sys.modules["duckdb"] = None  # forces `import duckdb` to raise ImportError
        try:
            with self.assertRaises(RuntimeError) as ctx:
                imp.require_duckdb()
            self.assertEqual(str(ctx.exception), imp.DUCKDB_MISSING_MSG)
        finally:
            if sentinel is None:
                sys.modules.pop("duckdb", None)
            else:
                sys.modules["duckdb"] = sentinel


# ---------------------------------------------------------------------------
# Missing-file behavior (no duckdb required for the missing-DB case)
# ---------------------------------------------------------------------------

class TestMissingFiles(unittest.TestCase):
    def test_missing_db_fails_and_does_not_create_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            summary_path = _write_summary(tmp, SAMPLE_SUMMARY)
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            self.assertNotEqual(rc, 0)
            self.assertFalse(db_path.exists(), "must not create the DB")
            self.assertFalse(db_path.parent.exists(), "must not create runtime dir")
            self.assertIn("init_runtime_db.py", err.getvalue())

    def test_missing_summary_json_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            # DB exists (create an empty placeholder file is not enough; needs schema),
            # but when duckdb is unavailable we still want the summary check to fire.
            # The summary check happens before DB open, so just point at a real file.
            placeholder_db = Path(tmp) / "runtime" / "dlmm.duckdb"
            placeholder_db.parent.mkdir(parents=True, exist_ok=True)
            placeholder_db.write_text("not-a-real-db")
            missing_summary = Path(tmp) / "nope.json"
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = imp.main(
                    [
                        "--db-path",
                        str(placeholder_db),
                        "--summary-json",
                        str(missing_summary),
                    ]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("Summary JSON not found", err.getvalue())


# ---------------------------------------------------------------------------
# DB-backed behavior (requires duckdb)
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestImportWithDb(unittest.TestCase):
    def _counts(self, db_path):
        conn = duckdb.connect(str(db_path))
        try:
            runs = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
            steps = conn.execute("SELECT COUNT(*) FROM pipeline_steps").fetchone()[0]
            fpe = conn.execute(
                "SELECT COUNT(*) FROM future_position_events"
            ).fetchone()[0]
            obs = conn.execute(
                "SELECT COUNT(*) FROM strategy_observations"
            ).fetchone()[0]
            flags = conn.execute("SELECT COUNT(*) FROM risk_flags").fetchone()[0]
        finally:
            conn.close()
        return runs, steps, fpe, obs, flags

    def test_dry_run_performs_no_db_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            summary_path = _write_summary(tmp, SAMPLE_SUMMARY)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--summary-json",
                        str(summary_path),
                        "--dry-run",
                    ]
                )
            self.assertEqual(rc, 0)
            runs, steps, _, _, _ = self._counts(db_path)
            self.assertEqual(runs, 0, "dry-run must not write pipeline_runs")
            self.assertEqual(steps, 0, "dry-run must not write pipeline_steps")
            self.assertIn("DRY RUN", buf.getvalue())

    def test_valid_summary_imports_one_run_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            summary_path = _write_summary(tmp, SAMPLE_SUMMARY)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            self.assertEqual(rc, 0)
            runs, steps, _, _, _ = self._counts(db_path)
            self.assertEqual(runs, 1)
            self.assertEqual(steps, len(SAMPLE_SUMMARY["steps"]))

    def test_summary_json_path_stored_in_run_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            summary_path = _write_summary(tmp, SAMPLE_SUMMARY)
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            conn = duckdb.connect(str(db_path))
            try:
                json_file, md_file = conn.execute(
                    "SELECT summary_json_file, summary_md_file FROM pipeline_runs "
                    "WHERE run_id = ?",
                    [SAMPLE_SUMMARY["run_id"]],
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(json_file, str(summary_path))
            self.assertIsNone(md_file, "summary_md_file should be null when absent")

    def test_summary_md_file_stored_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            summary = copy.deepcopy(SAMPLE_SUMMARY)
            summary["summary_md_file"] = "runtime/run_summaries/x.md"
            summary_path = _write_summary(tmp, summary)
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            conn = duckdb.connect(str(db_path))
            try:
                md_file = conn.execute(
                    "SELECT summary_md_file FROM pipeline_runs WHERE run_id = ?",
                    [summary["run_id"]],
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(md_file, "runtime/run_summaries/x.md")

    def test_duplicate_run_id_fails_without_upsert(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            summary_path = _write_summary(tmp, SAMPLE_SUMMARY)
            with redirect_stdout(io.StringIO()):
                rc1 = imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            self.assertEqual(rc1, 0)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc2 = imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            self.assertNotEqual(rc2, 0)
            self.assertIn("already exists", err.getvalue())
            runs, steps, _, _, _ = self._counts(db_path)
            self.assertEqual(runs, 1, "failed duplicate must not add a row")
            self.assertEqual(steps, len(SAMPLE_SUMMARY["steps"]))

    def test_upsert_replaces_only_that_run_id_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)

            # Import an unrelated run that must remain untouched.
            other = copy.deepcopy(SAMPLE_SUMMARY)
            other["run_id"] = "OTHER_RUN"
            other_path = _write_summary(tmp, other, name="other.json")
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(other_path)]
                )

            # First import of the target run (2 steps).
            summary_path = _write_summary(tmp, SAMPLE_SUMMARY)
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )

            # Upsert with a DIFFERENT number of steps (1 step) to prove replacement.
            modified = copy.deepcopy(SAMPLE_SUMMARY)
            modified["steps"] = [SAMPLE_SUMMARY["steps"][0]]
            modified["status"] = "FAILED"
            modified_path = _write_summary(tmp, modified, name="modified.json")
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--summary-json",
                        str(modified_path),
                        "--upsert",
                    ]
                )
            self.assertEqual(rc, 0)

            conn = duckdb.connect(str(db_path))
            try:
                target_steps = conn.execute(
                    "SELECT COUNT(*) FROM pipeline_steps WHERE run_id = ?",
                    [SAMPLE_SUMMARY["run_id"]],
                ).fetchone()[0]
                target_status = conn.execute(
                    "SELECT status FROM pipeline_runs WHERE run_id = ?",
                    [SAMPLE_SUMMARY["run_id"]],
                ).fetchone()[0]
                other_steps = conn.execute(
                    "SELECT COUNT(*) FROM pipeline_steps WHERE run_id = ?",
                    ["OTHER_RUN"],
                ).fetchone()[0]
                total_runs = conn.execute(
                    "SELECT COUNT(*) FROM pipeline_runs"
                ).fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(target_steps, 1, "upsert must replace target steps")
            self.assertEqual(target_status, "FAILED", "upsert must replace run row")
            self.assertEqual(other_steps, len(SAMPLE_SUMMARY["steps"]),
                             "other run_id steps must be untouched")
            self.assertEqual(total_runs, 2, "upsert must not duplicate the run row")

    def test_importer_does_not_write_future_position_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            summary_path = _write_summary(tmp, SAMPLE_SUMMARY)
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            runs, steps, fpe, obs, flags = self._counts(db_path)
            self.assertEqual(fpe, 0, "must not write future_position_events")
            self.assertEqual(obs, 0, "must not write strategy_observations")
            self.assertEqual(flags, 0, "must not write risk_flags")

    def test_invalid_safety_phase_fails_via_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            bad = copy.deepcopy(SAMPLE_SUMMARY)
            bad["safety_phase"] = "LIVE_ELIGIBLE_CORE"
            summary_path = _write_summary(tmp, bad)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            self.assertNotEqual(rc, 0)
            runs, _, _, _, _ = self._counts(db_path)
            self.assertEqual(runs, 0, "invalid safety_phase must not write")

    def test_missing_top_level_field_fails_via_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            bad = copy.deepcopy(SAMPLE_SUMMARY)
            del bad["log_file"]
            summary_path = _write_summary(tmp, bad)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            self.assertNotEqual(rc, 0)
            runs, _, _, _, _ = self._counts(db_path)
            self.assertEqual(runs, 0)

    def test_missing_step_field_fails_via_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            bad = copy.deepcopy(SAMPLE_SUMMARY)
            del bad["steps"][1]["status"]
            summary_path = _write_summary(tmp, bad)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            self.assertNotEqual(rc, 0)
            runs, _, _, _, _ = self._counts(db_path)
            self.assertEqual(runs, 0)

    def test_missing_schema_table_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Create a DB that lacks the required tables.
            db_path = Path(tmp) / "runtime" / "empty.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(db_path))
            conn.close()
            summary_path = _write_summary(tmp, SAMPLE_SUMMARY)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--summary-json", str(summary_path)]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("init_runtime_db.py", err.getvalue())


if __name__ == "__main__":
    unittest.main()
