#!/usr/bin/env python3
"""Tests for scripts/build_pair_stability_diagnostics.py (pair stability diag).

These tests verify the diagnostic is strictly READ-ONLY historical reporting:

- A missing database fails and creates nothing (no DB initialization).
- A dry run writes no files.
- A Markdown + CSV diagnostic is written for a safe DB.
- future_position_events count > 0 fails hard and writes no report.
- future_position_events count == 0 passes.
- Stable repeated PAPER_REVIEW_CANDIDATE pairs become STABLE_REVIEW_CANDIDATE
  with safe wording.
- Repeated OBSERVE_ONLY pairs become STABLE_OBSERVE_ONLY.
- Pairs whose strategy class changes become CHURNING_CLASS.
- Pairs whose lane changes become CHURNING_LANE.
- Mostly blocked pairs become MOSTLY_BLOCKED.
- One-off pairs become ONE_OFF.
- Insufficient run count produces an evidence-insufficiency note.
- The CSV has exactly the required columns.
- Output is deterministically sorted.
- Missing optional tables do not crash the run.
- The script never modifies any DuckDB table.
- Forbidden-action semantics do not appear except in safety / forbidden wording.

Tests that need a real DuckDB database are skipped when the optional `duckdb`
package is not installed, so the suite always runs.
"""

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DIAG_PATH = REPO_ROOT / "scripts" / "build_pair_stability_diagnostics.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diag = _load_module("build_pair_stability_diagnostics", DIAG_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

# The init skeleton is loaded only to build a real fixture database; it is not
# under test here.
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


def _insert_observation(conn, obs_id, pair_key, pair_label, cls, lane,
                        run_id="run-1",
                        observed_at="2026-06-30T00:10:00+00:00"):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO strategy_observations "
        "(observation_id, run_id, observed_at, pair_key, pair_label, "
        "strategy_class_v2, test_lane, observation_ready, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [obs_id, run_id, observed_at, pair_key, pair_label, cls, lane, True, now],
    )


def _insert_decision(conn, dec_id, pair_key, pair_label, decision="OBSERVE_ONLY",
                     action="CONTINUE_OBSERVATION", max_action="OBSERVE_ONLY",
                     imported_at="2026-06-30T01:00:00"):
    conn.execute(
        "INSERT INTO risk_decisions "
        "(risk_decision_id, imported_at, pair_key, pair_label, "
        "strategy_class_v2, pair_status_v2, risk_decision, risk_action, "
        "max_allowed_action, risk_blockers, risk_warnings, risk_policy_reason, "
        "safety_phase) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [dec_id, imported_at, pair_key, pair_label, "CORE", "WATCHLIST",
         decision, action, max_action, "", "", "", idb.SAFETY_PHASE],
    )


def _make_db(tmp, *, runs=5):
    """Create and populate a fixture runtime DB exercising every label.

    Returns the database path. With ``runs`` pipeline_runs rows, evidence is
    sufficient when runs >= min_runs.
    """
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    idb.init_db(str(db_path))

    conn = duckdb.connect(str(db_path))
    try:
        for i in range(runs):
            _insert_run(conn, f"run-{i + 1}")

        # --- STABLE_REVIEW_CANDIDATE: stable class/lane over 3 runs, repeatedly
        #     a paper-review candidate. ---
        for i in range(3):
            _insert_observation(
                conn, f"rev-{i}", "mintR|mintU", "REV-USDC", "CORE", "CLEAN",
                run_id=f"run-{i + 1}",
                observed_at=f"2026-06-30T0{i}:10:00+00:00",
            )
        for i in range(3):
            _insert_decision(
                conn, f"rev-d{i}", "mintR|mintU", "REV-USDC",
                decision="PAPER_REVIEW_CANDIDATE",
                action="REVIEW_FOR_FUTURE_PAPER_SIMULATION",
                max_action="FUTURE_PAPER_SIMULATION_REVIEW",
                imported_at=f"2026-06-30T1{i}:00:00",
            )

        # --- STABLE_OBSERVE_ONLY: stable class/lane over 3 runs, observe-only. ---
        for i in range(3):
            _insert_observation(
                conn, f"obs-{i}", "mintO|mintU", "OBS-USDC", "TACTICAL",
                "RISKY_BUT_INTERESTING", run_id=f"run-{i + 1}",
                observed_at=f"2026-06-30T0{i}:10:00+00:00",
            )
        for i in range(3):
            _insert_decision(
                conn, f"obs-d{i}", "mintO|mintU", "OBS-USDC",
                decision="OBSERVE_ONLY", action="CONTINUE_OBSERVATION",
                max_action="OBSERVE_ONLY",
                imported_at=f"2026-06-30T1{i}:00:00",
            )

        # --- CHURNING_CLASS: class flips across runs. ---
        _insert_observation(conn, "cc-0", "mintC|mintU", "CC-USDC", "CORE",
                            "CLEAN", run_id="run-1",
                            observed_at="2026-06-30T00:10:00+00:00")
        _insert_observation(conn, "cc-1", "mintC|mintU", "CC-USDC", "TACTICAL",
                            "CLEAN", run_id="run-2",
                            observed_at="2026-06-30T01:10:00+00:00")
        _insert_observation(conn, "cc-2", "mintC|mintU", "CC-USDC", "CORE",
                            "CLEAN", run_id="run-3",
                            observed_at="2026-06-30T02:10:00+00:00")

        # --- CHURNING_LANE: class stable, lane flips across runs. ---
        _insert_observation(conn, "cl-0", "mintL|mintU", "CL-USDC", "CORE",
                            "CLEAN", run_id="run-1",
                            observed_at="2026-06-30T00:10:00+00:00")
        _insert_observation(conn, "cl-1", "mintL|mintU", "CL-USDC", "CORE",
                            "RISKY_BUT_INTERESTING", run_id="run-2",
                            observed_at="2026-06-30T01:10:00+00:00")

        # --- MOSTLY_BLOCKED: stable class/lane over 2 runs, all blocked. ---
        _insert_observation(conn, "mb-0", "mintB|mintU", "MB-USDC", "CORE",
                            "CLEAN", run_id="run-1",
                            observed_at="2026-06-30T00:10:00+00:00")
        _insert_observation(conn, "mb-1", "mintB|mintU", "MB-USDC", "CORE",
                            "CLEAN", run_id="run-2",
                            observed_at="2026-06-30T01:10:00+00:00")
        _insert_decision(conn, "mb-d0", "mintB|mintU", "MB-USDC",
                         decision="BLOCKED", action="FIX_DATA_OR_CLASSIFICATION",
                         max_action="NONE", imported_at="2026-06-30T10:00:00")
        _insert_decision(conn, "mb-d1", "mintB|mintU", "MB-USDC",
                         decision="BLOCKED", action="FIX_DATA_OR_CLASSIFICATION",
                         max_action="NONE", imported_at="2026-06-30T11:00:00")

        # --- ONE_OFF: appears in a single run only. ---
        _insert_observation(conn, "oo-0", "mintZ|mintU", "OO-USDC", "CORE",
                            "CLEAN", run_id="run-1",
                            observed_at="2026-06-30T00:10:00+00:00")
    finally:
        conn.close()
    return db_path


def _make_partial_db(tmp):
    """Create a DB with only future_position_events + pipeline_runs tables."""
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE future_position_events ("
            "event_id TEXT, event_time TEXT, phase TEXT, event_type TEXT, "
            "event_payload_json TEXT, created_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE pipeline_runs ("
            "run_id TEXT, started_at TEXT, ended_at TEXT, status TEXT)"
        )
    finally:
        conn.close()
    return db_path


def _read_csv(path):
    import csv
    with Path(path).open(newline="", encoding="utf-8") as fh:
        yield from csv.DictReader(fh)


# ---------------------------------------------------------------------------
# Constant / safety-boundary tests (no duckdb required)
# ---------------------------------------------------------------------------

class TestSafetyConstants(unittest.TestCase):
    def test_safety_phase_exact(self):
        self.assertEqual(
            diag.SAFETY_PHASE,
            "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
        )

    def test_safety_boundary_lines_present(self):
        for term in ("No wallet", "No private key", "No signing", "No swap",
                     "No rebalance", "No live execution", "No LIVE_ELIGIBLE_*",
                     "No signal generation", "No paper position creation",
                     "No future_position_events writes", "No threshold changes",
                     "No risk policy changes", "No candidate status changes"):
            self.assertTrue(
                any(term in line for line in diag.SAFETY_BOUNDARY_LINES),
                f"missing boundary line: {term}",
            )

    def test_csv_columns_exact(self):
        # (13) CSV has exactly the required columns, in order.
        self.assertEqual(
            diag.CSV_COLUMNS,
            (
                "pair_key",
                "pair_label",
                "observation_count",
                "distinct_run_count",
                "first_seen_at",
                "last_seen_at",
                "observed_strategy_classes",
                "strategy_class_change_count",
                "observed_lanes",
                "lane_change_count",
                "latest_strategy_class",
                "latest_lane",
                "latest_risk_decision",
                "latest_risk_action",
                "latest_max_allowed_action",
                "paper_review_candidate_count",
                "blocked_count",
                "rejected_count",
                "not_evaluated_count",
                "stability_label",
                "diagnostic_note",
            ),
        )

    def test_duckdb_missing_message_exact(self):
        self.assertEqual(
            diag.DUCKDB_MISSING_MSG,
            "duckdb package is required. Install with: "
            "python3 -m pip install duckdb",
        )

    def test_review_phrase_is_safe(self):
        # (13) Safe wording for stable review candidates.
        self.assertEqual(
            diag.REVIEW_PHRASE,
            "human/council may review for future paper-simulation design "
            "consideration",
        )
        low = diag.REVIEW_PHRASE.lower()
        for unsafe in ("enter paper", "paper trade", "open position", "signal"):
            self.assertNotIn(unsafe, low)


# ---------------------------------------------------------------------------
# Missing database (no duckdb required for the fail path before connect)
# ---------------------------------------------------------------------------

class TestMissingDatabase(unittest.TestCase):
    def test_missing_db_fails_and_creates_nothing(self):
        # (1) Missing DB fails and does not create the DB.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            out_md = Path(tmp) / "out" / "diag.md"
            out_csv = Path(tmp) / "out" / "diag.csv"
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = diag.main([
                    "--db-path", str(db_path),
                    "--out-md", str(out_md),
                    "--out-csv", str(out_csv),
                ])
            self.assertNotEqual(rc, 0)
            self.assertFalse(db_path.exists(), "must not create the db file")
            self.assertFalse(
                db_path.parent.exists(), "must not create the runtime parent dir"
            )
            self.assertFalse(out_md.exists(), "must not write the report")
            self.assertFalse(out_csv.exists(), "must not write the csv")


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestDiagnostics(unittest.TestCase):
    def _run(self, db_path, tmp, *, dry_run=False, limit=100, min_runs=5,
             runs_label="out"):
        out_md = Path(tmp) / runs_label / "diag.md"
        out_csv = Path(tmp) / runs_label / "diag.csv"
        argv = [
            "--db-path", str(db_path),
            "--out-md", str(out_md),
            "--out-csv", str(out_csv),
            "--limit", str(limit),
            "--min-runs", str(min_runs),
        ]
        if dry_run:
            argv.append("--dry-run")
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            rc = diag.main(argv)
        return rc, out_md, out_csv, buf.getvalue() + err.getvalue()

    def _labels_by_key(self, out_csv):
        return {r["pair_key"]: r for r in _read_csv(out_csv)}

    def test_dry_run_writes_no_files(self):
        # (2) Dry run writes no Markdown or CSV files.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, out_md, out_csv, _ = self._run(db_path, tmp, dry_run=True)
            self.assertEqual(rc, 0)
            self.assertFalse(out_md.exists(), "dry run must not write Markdown")
            self.assertFalse(out_csv.exists(), "dry run must not write CSV")

    def test_writes_markdown_and_csv(self):
        # (3) Diagnostic writes Markdown and CSV for a safe DB.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, out_md, out_csv, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            self.assertTrue(out_csv.exists())
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("# Pair Stability Diagnostics v0.1", text)
            self.assertIn("generated_at (UTC):", text)
            self.assertIn("Summary by Stability Label", text)
            self.assertIn("Interpretation Notes", text)

    def test_future_position_events_nonzero_fails_and_no_report(self):
        # (4) future_position_events > 0 fails hard and writes no report.
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
            rc, out_md, out_csv, out = self._run(db_path, tmp)
            self.assertNotEqual(rc, 0)
            self.assertFalse(out_md.exists(), "must write no report on violation")
            self.assertFalse(out_csv.exists(), "must write no csv on violation")
            self.assertIn("HARD SAFETY VIOLATION", out)

    def test_future_position_events_zero_passes(self):
        # (5) future_position_events == 0 passes.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, out_md, _, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("future_position_events count: 0 (expected 0)", text)
            self.assertNotIn("HARD SAFETY VIOLATION", text)

    def test_stable_review_candidate(self):
        # (6) Stable repeated PAPER_REVIEW_CANDIDATE -> STABLE_REVIEW_CANDIDATE,
        #     with safe wording.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, out_md, out_csv, _ = self._run(db_path, tmp)
            by_key = self._labels_by_key(out_csv)
            row = by_key["mintR|mintU"]
            self.assertEqual(row["stability_label"], "STABLE_REVIEW_CANDIDATE")
            self.assertEqual(row["paper_review_candidate_count"], "3")
            self.assertIn(
                "human/council may review for future paper-simulation design "
                "consideration",
                row["diagnostic_note"],
            )
            for unsafe in ("enter paper", "paper trade", "open position",
                           "signal"):
                self.assertNotIn(unsafe, row["diagnostic_note"].lower())
            # Safe phrase is also visible in the Markdown report.
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("Top Stable Review Candidates", text)
            self.assertIn(
                "human/council may review for future paper-simulation design "
                "consideration",
                text,
            )

    def test_stable_observe_only(self):
        # (7) Repeated OBSERVE_ONLY -> STABLE_OBSERVE_ONLY.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            by_key = self._labels_by_key(out_csv)
            self.assertEqual(
                by_key["mintO|mintU"]["stability_label"], "STABLE_OBSERVE_ONLY"
            )

    def test_churning_class(self):
        # (8) Changing strategy_class -> CHURNING_CLASS.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            by_key = self._labels_by_key(out_csv)
            row = by_key["mintC|mintU"]
            self.assertEqual(row["stability_label"], "CHURNING_CLASS")
            self.assertEqual(row["strategy_class_change_count"], "2")

    def test_churning_lane(self):
        # (9) Changing lane (class stable) -> CHURNING_LANE.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            by_key = self._labels_by_key(out_csv)
            row = by_key["mintL|mintU"]
            self.assertEqual(row["stability_label"], "CHURNING_LANE")
            self.assertEqual(row["strategy_class_change_count"], "0")
            self.assertEqual(row["lane_change_count"], "1")

    def test_mostly_blocked(self):
        # (10) Mostly blocked -> MOSTLY_BLOCKED.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            by_key = self._labels_by_key(out_csv)
            row = by_key["mintB|mintU"]
            self.assertEqual(row["stability_label"], "MOSTLY_BLOCKED")
            self.assertEqual(row["blocked_count"], "2")

    def test_one_off(self):
        # (11) One-off pair -> ONE_OFF.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            by_key = self._labels_by_key(out_csv)
            self.assertEqual(
                by_key["mintZ|mintU"]["stability_label"], "ONE_OFF"
            )

    def test_evidence_insufficiency_note(self):
        # (12) Insufficient run count produces an evidence-insufficiency note.
        with tempfile.TemporaryDirectory() as tmp:
            # Only 2 pipeline runs, but require 5 -> insufficient evidence.
            db_path = _make_db(tmp, runs=2)
            _, out_md, _, _ = self._run(db_path, tmp, min_runs=5)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("evidence sufficiency: INSUFFICIENT", text)

    def test_evidence_sufficient_note(self):
        # Companion to (12): enough runs -> SUFFICIENT note.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, runs=5)
            _, out_md, _, _ = self._run(db_path, tmp, min_runs=3)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("evidence sufficiency: SUFFICIENT", text)

    def test_csv_has_required_columns(self):
        # (13) CSV header is exactly the required columns in order.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            header = out_csv.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(header, ",".join(diag.CSV_COLUMNS))

    def test_deterministic_sort(self):
        # (14) Deterministic sort across independent runs.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv1, _ = self._run(db_path, tmp, runs_label="a")
            order1 = [r["pair_key"] for r in _read_csv(out_csv1)]
            # STABLE_REVIEW_CANDIDATE (priority 0) sorts before everything else.
            self.assertEqual(order1[0], "mintR|mintU")
            import shutil
            with tempfile.TemporaryDirectory() as tmp2:
                db2 = Path(tmp2) / "runtime" / "dlmm.duckdb"
                db2.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(db_path, db2)
                _, _, out_csv2, _ = self._run(db2, tmp2)
                order2 = [r["pair_key"] for r in _read_csv(out_csv2)]
            self.assertEqual(order1, order2)

    def test_missing_optional_tables_does_not_crash(self):
        # (15) Missing optional tables (observations/decisions) do not crash.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_partial_db(tmp)
            rc, out_md, out_csv, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("table missing", text)
            self.assertIn("total pairs analysed: 0", text)

    def test_script_does_not_modify_duckdb(self):
        # (16) No DuckDB tables are modified (size + mtime stable across runs).
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            before_size = os.path.getsize(db_path)
            before_mtime = os.path.getmtime(db_path)
            self._run(db_path, tmp, runs_label="a")
            self._run(db_path, tmp, runs_label="b")
            self.assertEqual(before_size, os.path.getsize(db_path),
                             "db size must not change")
            self.assertEqual(before_mtime, os.path.getmtime(db_path),
                             "db mtime must not change")

    def test_no_forbidden_action_semantics_except_safety_text(self):
        # (17) Forbidden-action semantics do not appear except in safety /
        # forbidden (negated) wording.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, out_md, _, _ = self._run(db_path, tmp)
            text = out_md.read_text(encoding="utf-8")
            forbidden = (
                "approved", "execute", "signal", "live eligible",
                "open position", "paper trade", "swap", "rebalance", "wallet",
                "private key",
            )
            markers = ("no ", "never", "not ", "without", "forbidden",
                       "does not", "do not", "neither", "authorizes nothing")
            for line in text.splitlines():
                low = line.lower()
                for term in forbidden:
                    if term in low:
                        self.assertTrue(
                            any(m in low for m in markers),
                            f"forbidden term '{term}' outside safety text: "
                            f"{line!r}",
                        )


# ---------------------------------------------------------------------------
# duckdb-missing path (monkeypatch the dependency chokepoint)
# ---------------------------------------------------------------------------

class TestDuckdbMissing(unittest.TestCase):
    def test_missing_duckdb_prints_exact_message_and_exits_nonzero(self):
        original = diag.require_duckdb

        def _raise():
            raise RuntimeError(diag.DUCKDB_MISSING_MSG)

        diag.require_duckdb = _raise
        try:
            err = io.StringIO()
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = diag.main(["--db-path", "nonexistent.duckdb"])
            self.assertNotEqual(rc, 0)
            self.assertIn(diag.DUCKDB_MISSING_MSG, err.getvalue())
        finally:
            diag.require_duckdb = original


if __name__ == "__main__":
    unittest.main()
