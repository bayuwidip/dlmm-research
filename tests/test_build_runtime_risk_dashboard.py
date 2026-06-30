#!/usr/bin/env python3
"""Tests for scripts/build_runtime_risk_dashboard.py (Runtime / Risk Dashboard).

These tests verify the dashboard is strictly READ-ONLY historical reporting:

- A missing database fails and creates nothing.
- A dry run writes no files.
- A Markdown dashboard is written when the required tables exist.
- Missing optional tables do not crash the run.
- future_position_events count == 0 passes and is reported.
- future_position_events count  > 0 fails hard (non-zero exit, violation banner).
- The report includes the risk decision distribution.
- The report includes repeated PAPER_REVIEW_CANDIDATE candidates when present.
- The report includes BLOCKED / REJECTED reasons when present.
- The script never writes to the DuckDB tables.
- Output CSV files are created when the underlying data exists.
- The hard safety boundary text is present.
- No execution / wallet / LP / swap / rebalance semantics are introduced except
  inside the safety-boundary / interpretation (negated) text.

Tests that need a real DuckDB database are skipped when the optional `duckdb`
package is not installed, so the suite always runs.
"""

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DASH_PATH = REPO_ROOT / "scripts" / "build_runtime_risk_dashboard.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dash = _load_module("build_runtime_risk_dashboard", DASH_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

# The init skeleton is loaded only to build a real fixture database for the
# duckdb-backed tests; it is not under test here.
idb = _load_module("init_runtime_db", INIT_PATH) if HAS_DUCKDB else None


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _insert_run(conn, run_id):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO pipeline_runs "
        "(run_id, started_at, ended_at, status, safety_phase, "
        "continue_on_ohlcv_error, stale_lock_replaced, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [run_id, "2026-06-30T00:00:00+00:00", "2026-06-30T00:05:00+00:00",
         "SUCCESS", idb.SAFETY_PHASE, False, False, now],
    )


def _insert_observation(conn, obs_id, pair_key, pair_label, cls):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO strategy_observations "
        "(observation_id, observed_at, pair_key, pair_label, "
        "strategy_class_v2, pair_status_v2, observation_ready, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [obs_id, "2026-06-30T00:10:00+00:00", pair_key, pair_label,
         cls, "WATCHLIST", True, now],
    )


def _insert_flag(conn, flag_id, pair_key, pair_label, flag, severity):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO risk_flags "
        "(flag_id, observed_at, pair_key, pair_label, risk_flag, severity, "
        "source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [flag_id, "2026-06-30T00:10:00+00:00", pair_key, pair_label,
         flag, severity, "test", now],
    )


def _insert_decision(conn, dec_id, pair_key, pair_label, decision,
                     max_action="PAPER_ONLY", blockers="", reason=""):
    conn.execute(
        "INSERT INTO risk_decisions "
        "(risk_decision_id, pair_key, pair_label, strategy_class_v2, "
        "pair_status_v2, risk_decision, risk_action, max_allowed_action, "
        "risk_blockers, risk_warnings, risk_policy_reason, safety_phase) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [dec_id, pair_key, pair_label, "CORE", "WATCHLIST", decision,
         "OBSERVE", max_action, blockers, "", reason, idb.SAFETY_PHASE],
    )


def _make_db(tmp):
    """Create and populate a full fixture runtime DB. Returns its path."""
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    idb.init_db(str(db_path))

    conn = duckdb.connect(str(db_path))
    try:
        _insert_run(conn, "run-1")
        _insert_run(conn, "run-2")

        _insert_observation(conn, "obs-1", "mintA|mintB", "USDC-SOL", "CORE")
        _insert_observation(conn, "obs-2", "mintC|mintD", "FOO-BAR", "TACTICAL")

        _insert_flag(conn, "flag-1", "mintA|mintB", "USDC-SOL",
                     "low_liquidity", "MEDIUM")
        _insert_flag(conn, "flag-2", "mintC|mintD", "FOO-BAR",
                     "thin_volume", "HIGH")

        # Repeated PAPER_REVIEW_CANDIDATE for the same pair (occurs twice).
        _insert_decision(conn, "dec-1", "mintA|mintB", "USDC-SOL",
                         "PAPER_REVIEW_CANDIDATE")
        _insert_decision(conn, "dec-2", "mintA|mintB", "USDC-SOL",
                         "PAPER_REVIEW_CANDIDATE")
        # A BLOCKED decision with an explicit blocker reason.
        _insert_decision(conn, "dec-3", "mintC|mintD", "FOO-BAR", "BLOCKED",
                         blockers="liquidity_too_low")
        # A REJECTED decision whose reason comes from the policy reason field.
        _insert_decision(conn, "dec-4", "mintE|mintF", "BAZ-QUX", "REJECTED",
                         reason="score_below_threshold")
    finally:
        conn.close()
    return db_path


def _make_partial_db(tmp):
    """Create a DB with only a subset of required tables (optional ones absent)."""
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE runtime_schema_meta ("
            "schema_name TEXT, schema_version INTEGER, "
            "safety_phase TEXT, updated_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE pipeline_runs ("
            "run_id TEXT, started_at TEXT, ended_at TEXT, status TEXT, "
            "duration_seconds DOUBLE)"
        )
    finally:
        conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Constant / safety-boundary tests (no duckdb required)
# ---------------------------------------------------------------------------

class TestSafetyConstants(unittest.TestCase):
    def test_safety_phase_exact(self):
        self.assertEqual(
            dash.SAFETY_PHASE,
            "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
        )

    def test_safety_boundary_lines_present(self):
        # (12) Safety boundary text is present in the module constants.
        for term in ("No wallet", "No private key", "No signing", "No swap",
                     "No rebalance", "No live execution", "No LIVE_ELIGIBLE_*"):
            self.assertTrue(
                any(term in line for line in dash.SAFETY_BOUNDARY_LINES),
                f"missing boundary line: {term}",
            )

    def test_required_tables_match_spec(self):
        expected = {
            "runtime_schema_meta",
            "pipeline_runs",
            "pipeline_steps",
            "strategy_observations",
            "risk_flags",
            "risk_decisions",
            "future_position_events",
        }
        self.assertEqual(set(dash.REQUIRED_TABLES), expected)


# ---------------------------------------------------------------------------
# Missing database (no duckdb required for the fail path before connect)
# ---------------------------------------------------------------------------

class TestMissingDatabase(unittest.TestCase):
    def test_missing_db_fails_and_creates_nothing(self):
        # (1) Missing DB fails and does not create the DB.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            out_md = Path(tmp) / "out" / "dashboard.md"
            out_dir = Path(tmp) / "out"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = dash.main([
                    "--db-path", str(db_path),
                    "--out-md", str(out_md),
                    "--out-dir", str(out_dir),
                ])
            self.assertNotEqual(rc, 0)
            self.assertFalse(db_path.exists(), "must not create the db file")
            self.assertFalse(
                db_path.parent.exists(), "must not create the runtime parent dir"
            )
            self.assertFalse(out_md.exists(), "must not write the dashboard")


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestDashboard(unittest.TestCase):
    def _run(self, db_path, tmp, *, dry_run=False, limit=20):
        out_md = Path(tmp) / "out" / "dashboard.md"
        out_dir = Path(tmp) / "out"
        argv = [
            "--db-path", str(db_path),
            "--out-md", str(out_md),
            "--out-dir", str(out_dir),
            "--limit", str(limit),
        ]
        if dry_run:
            argv.append("--dry-run")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = dash.main(argv)
        return rc, out_md, out_dir, buf.getvalue()

    def test_dry_run_writes_no_files(self):
        # (2) Dry run writes no Markdown or CSV files.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, out_md, out_dir, _ = self._run(db_path, tmp, dry_run=True)
            self.assertEqual(rc, 0)
            self.assertFalse(out_md.exists(), "dry run must not write Markdown")
            if out_dir.exists():
                self.assertEqual(
                    list(out_dir.glob("*.csv")), [], "dry run must not write CSVs"
                )

    def test_writes_markdown_when_tables_exist(self):
        # (3) Dashboard writes Markdown when the required tables exist.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, out_md, _, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("# Runtime / Risk Dashboard Report", text)

    def test_missing_optional_tables_does_not_crash(self):
        # (4) Missing optional tables does not crash; the run still succeeds.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_partial_db(tmp)
            rc, out_md, _, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("table missing — section skipped.", text)

    def test_future_position_events_zero_passes_and_reported(self):
        # (5) future_position_events count == 0 passes and is reported.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, out_md, _, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("count: 0 (expected 0)", text)
            self.assertNotIn("HARD SAFETY VIOLATION", text)

    def test_future_position_events_nonzero_fails_hard(self):
        # (6) future_position_events count > 0 fails hard.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            conn = duckdb.connect(str(db_path))
            try:
                now = idb.utc_now_iso()
                conn.execute(
                    "INSERT INTO future_position_events "
                    "(event_id, event_time, phase, event_type, "
                    "event_payload_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ["evt-1", now, "PAPER", "NOTE", "{}", now],
                )
            finally:
                conn.close()
            rc, out_md, _, _ = self._run(db_path, tmp)
            self.assertNotEqual(rc, 0)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("HARD SAFETY VIOLATION", text)

    def test_report_includes_risk_decision_distribution(self):
        # (7) Report includes the risk decision distribution.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, out_md, _, _ = self._run(db_path, tmp)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("Risk Decision Distribution", text)
            self.assertIn("PAPER_REVIEW_CANDIDATE", text)
            self.assertIn("BLOCKED", text)
            self.assertIn("REJECTED", text)

    def test_report_includes_repeated_paper_review_candidates(self):
        # (8) Report includes repeated PAPER_REVIEW_CANDIDATE candidates.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, out_md, _, _ = self._run(db_path, tmp)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("Repeated PAPER_REVIEW_CANDIDATE Candidates", text)
            # The repeated pair (occurs twice) must surface with its count.
            self.assertIn("USDC-SOL", text)
            self.assertIn("| 2 |", text)

    def test_report_includes_blocked_rejected_reasons(self):
        # (9) Report includes BLOCKED / REJECTED reasons when present.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, out_md, _, _ = self._run(db_path, tmp)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("Repeated BLOCKED / REJECTED Reasons", text)
            self.assertIn("liquidity_too_low", text)
            self.assertIn("score_below_threshold", text)

    def test_script_does_not_write_to_duckdb(self):
        # (10) Script does not write to the DuckDB tables.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            before_size = os.path.getsize(db_path)
            before_mtime = os.path.getmtime(db_path)
            self._run(db_path, tmp)
            self._run(db_path, tmp)
            self.assertEqual(before_size, os.path.getsize(db_path),
                             "db size must not change")
            self.assertEqual(before_mtime, os.path.getmtime(db_path),
                             "db mtime must not change")

    def test_csv_files_created_when_data_exists(self):
        # (11) Output CSV files are created when data exists.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_dir, _ = self._run(db_path, tmp)
            for name in (
                "pipeline_runs_summary.csv",
                "risk_decision_distribution.csv",
                "repeated_paper_review_candidates.csv",
                "repeated_blocked_rejected.csv",
                "risk_flag_distribution.csv",
            ):
                self.assertTrue(
                    (out_dir / name).exists(), f"expected CSV: {name}"
                )

    def test_safety_boundary_text_present_in_report(self):
        # (12) Safety boundary text is present in the rendered report.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, out_md, _, _ = self._run(db_path, tmp)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("Safety Boundary", text)
            self.assertIn("No wallet", text)
            self.assertIn("No live execution", text)
            self.assertIn(dash.INTERPRETATION_NOTE, text)

    def test_no_execution_semantics_except_in_safety_text(self):
        # (13) No execution / wallet / LP / swap / rebalance semantics are
        # introduced except inside negated safety-boundary / interpretation text.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, out_md, _, _ = self._run(db_path, tmp)
            text = out_md.read_text(encoding="utf-8")
            forbidden = ("wallet", "private key", "swap", "rebalance")
            for line in text.splitlines():
                low = line.lower()
                for term in forbidden:
                    if term in low:
                        self.assertTrue(
                            "no " in low or "does not authorize" in low,
                            f"execution term '{term}' outside safety text: {line!r}",
                        )


if __name__ == "__main__":
    unittest.main()
