#!/usr/bin/env python3
"""Tests for scripts/build_fee_pool_diagnostics.py (NO_ELIGIBLE_FEE_POOL diag).

These tests verify the diagnostic is strictly READ-ONLY historical reporting:

- A missing database fails and creates nothing (no DB initialization).
- A dry run writes no files.
- A Markdown + CSV diagnostic is written for a safe DB.
- future_position_events count > 0 fails hard and writes no report.
- future_position_events count == 0 passes.
- A DB with no NO_ELIGIBLE_FEE_POOL rows still produces an honest empty report.
- Repeated risk_flags are counted per pair.
- Repeated risk_decisions are counted per pair.
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
DIAG_PATH = REPO_ROOT / "scripts" / "build_fee_pool_diagnostics.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diag = _load_module("build_fee_pool_diagnostics", DIAG_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

# The init skeleton is loaded only to build a real fixture database; it is not
# under test here.
idb = _load_module("init_runtime_db", INIT_PATH) if HAS_DUCKDB else None

TARGET = "NO_ELIGIBLE_FEE_POOL"


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
                        observed_at="2026-06-30T00:10:00+00:00"):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO strategy_observations "
        "(observation_id, observed_at, pair_key, pair_label, "
        "strategy_class_v2, test_lane, observation_ready, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [obs_id, observed_at, pair_key, pair_label, cls, lane, True, now],
    )


def _insert_flag(conn, flag_id, pair_key, pair_label, flag=TARGET,
                 severity="SEVERE", observed_at="2026-06-30T00:10:00+00:00"):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO risk_flags "
        "(flag_id, observed_at, pair_key, pair_label, risk_flag, severity, "
        "source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [flag_id, observed_at, pair_key, pair_label, flag, severity,
         "test", now],
    )


def _insert_decision(conn, dec_id, pair_key, pair_label, decision="BLOCKED",
                     action="NO_ACTION", max_action="NONE", blockers=TARGET,
                     reason="", imported_at=None):
    conn.execute(
        "INSERT INTO risk_decisions "
        "(risk_decision_id, imported_at, pair_key, pair_label, "
        "strategy_class_v2, pair_status_v2, risk_decision, risk_action, "
        "max_allowed_action, risk_blockers, risk_warnings, risk_policy_reason, "
        "safety_phase) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [dec_id, imported_at, pair_key, pair_label, "CORE", "WATCHLIST",
         decision, action, max_action, blockers, "", reason, idb.SAFETY_PHASE],
    )


def _make_db(tmp, *, with_target=True):
    """Create and populate a fixture runtime DB. Returns its path."""
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    idb.init_db(str(db_path))

    conn = duckdb.connect(str(db_path))
    try:
        _insert_run(conn, "run-1")
        _insert_run(conn, "run-2")

        _insert_observation(conn, "obs-1", "mintA|mintB", "AAA-USDC",
                            "TACTICAL", "RISKY_BUT_INTERESTING")
        _insert_observation(conn, "obs-1b", "mintA|mintB", "AAA-USDC",
                            "CORE", "CLEAN")
        _insert_observation(conn, "obs-2", "mintC|mintD", "BBB-USDC",
                            "REJECT", "QUARANTINE")

        if with_target:
            # Pair AAA: three flags, two blocking decisions (most repeated).
            _insert_flag(conn, "flag-1", "mintA|mintB", "AAA-USDC")
            _insert_flag(conn, "flag-2", "mintA|mintB", "AAA-USDC")
            _insert_flag(conn, "flag-3", "mintA|mintB", "AAA-USDC")
            _insert_decision(conn, "dec-1", "mintA|mintB", "AAA-USDC",
                             imported_at="2026-06-30T01:00:00")
            _insert_decision(conn, "dec-2", "mintA|mintB", "AAA-USDC",
                             decision="BLOCKED", action="REJECT",
                             max_action="OBSERVE_ONLY",
                             imported_at="2026-06-30T02:00:00")

            # Pair BBB: one flag, one decision (reason via policy_reason field).
            _insert_flag(conn, "flag-4", "mintC|mintD", "BBB-USDC")
            _insert_decision(conn, "dec-3", "mintC|mintD", "BBB-USDC",
                             blockers="",
                             reason=f"blocked: {TARGET} present",
                             imported_at="2026-06-30T03:00:00")

            # A decision unrelated to the target (must not be counted).
            _insert_decision(conn, "dec-x", "mintE|mintF", "CCC-USDC",
                             decision="REJECTED", blockers="LOW_LIQUIDITY",
                             reason="score below threshold")
            # A flag unrelated to the target (must not be counted).
            _insert_flag(conn, "flag-x", "mintE|mintF", "CCC-USDC",
                         flag="LOW_VOLUME", severity="MEDIUM")
    finally:
        conn.close()
    return db_path


def _make_partial_db(tmp):
    """Create a DB with future_position_events but no flag/decision tables."""
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
                     "No threshold changes", "No risk policy changes",
                     "No candidate status changes"):
            self.assertTrue(
                any(term in line for line in diag.SAFETY_BOUNDARY_LINES),
                f"missing boundary line: {term}",
            )

    def test_csv_columns_exact(self):
        # (9) CSV has exactly the required columns, in order.
        self.assertEqual(
            diag.CSV_COLUMNS,
            (
                "pair_key",
                "pair_label",
                "no_eligible_fee_pool_flag_count",
                "no_eligible_fee_pool_decision_count",
                "latest_risk_decision",
                "latest_risk_action",
                "latest_max_allowed_action",
                "observed_strategy_classes",
                "observed_lanes",
                "first_seen_at",
                "last_seen_at",
                "diagnostic_note",
            ),
        )

    def test_duckdb_missing_message_exact(self):
        self.assertEqual(
            diag.DUCKDB_MISSING_MSG,
            "duckdb package is required. Install with: "
            "python3 -m pip install duckdb",
        )


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
    def _run(self, db_path, tmp, *, dry_run=False, limit=50):
        out_md = Path(tmp) / "out" / "diag.md"
        out_csv = Path(tmp) / "out" / "diag.csv"
        argv = [
            "--db-path", str(db_path),
            "--out-md", str(out_md),
            "--out-csv", str(out_csv),
            "--limit", str(limit),
        ]
        if dry_run:
            argv.append("--dry-run")
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            rc = diag.main(argv)
        return rc, out_md, out_csv, buf.getvalue() + err.getvalue()

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
            self.assertIn("# NO_ELIGIBLE_FEE_POOL Diagnostics v0.1", text)
            self.assertIn("generated_at (UTC):", text)
            self.assertIn("Diagnostic Interpretation", text)
            self.assertIn("Next Safe Manual Checks", text)

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

    def test_no_target_rows_produces_honest_empty_report(self):
        # (6) No NO_ELIGIBLE_FEE_POOL rows still produces an honest empty report.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, with_target=False)
            rc, out_md, out_csv, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            self.assertTrue(out_csv.exists())
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("affected pair count: 0", text)
            self.assertIn("total NO_ELIGIBLE_FEE_POOL flags: 0", text)
            self.assertIn("total NO_ELIGIBLE_FEE_POOL decisions: 0", text)
            self.assertIn("_(no rows)_", text)
            # CSV has only the header row.
            csv_lines = [
                ln for ln in out_csv.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            self.assertEqual(len(csv_lines), 1)

    def test_repeated_flags_counted(self):
        # (7) Repeated risk_flags are counted per pair.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            rows = list(_read_csv(out_csv))
            by_key = {r["pair_key"]: r for r in rows}
            self.assertEqual(
                by_key["mintA|mintB"]["no_eligible_fee_pool_flag_count"], "3"
            )
            self.assertEqual(
                by_key["mintC|mintD"]["no_eligible_fee_pool_flag_count"], "1"
            )

    def test_repeated_decisions_counted(self):
        # (8) Repeated risk_decisions are counted per pair.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            rows = list(_read_csv(out_csv))
            by_key = {r["pair_key"]: r for r in rows}
            self.assertEqual(
                by_key["mintA|mintB"]["no_eligible_fee_pool_decision_count"], "2"
            )
            self.assertEqual(
                by_key["mintC|mintD"]["no_eligible_fee_pool_decision_count"], "1"
            )
            # The unrelated pair must not appear at all.
            self.assertNotIn("mintE|mintF", by_key)

    def test_csv_has_required_columns(self):
        # (9) CSV header is exactly the required columns in order.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            header = out_csv.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(header, ",".join(diag.CSV_COLUMNS))

    def test_deterministic_sort(self):
        # (10) Deterministic sort by decision count desc, flag count desc, label.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv1, _ = self._run(db_path, tmp)
            order1 = [r["pair_key"] for r in _read_csv(out_csv1)]
            # AAA (2 decisions) must precede BBB (1 decision).
            self.assertEqual(order1, ["mintA|mintB", "mintC|mintD"])
            # Re-running yields the identical order.
            with tempfile.TemporaryDirectory() as tmp2:
                # copy the db to a fresh location for an independent run
                import shutil
                db2 = Path(tmp2) / "runtime" / "dlmm.duckdb"
                db2.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(db_path, db2)
                _, _, out_csv2, _ = self._run(db2, tmp2)
                order2 = [r["pair_key"] for r in _read_csv(out_csv2)]
            self.assertEqual(order1, order2)

    def test_latest_decision_uses_most_recent(self):
        # The latest decision/action reflects the most recent imported_at.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            by_key = {r["pair_key"]: r for r in _read_csv(out_csv)}
            self.assertEqual(
                by_key["mintA|mintB"]["latest_risk_action"], "REJECT"
            )
            self.assertEqual(
                by_key["mintA|mintB"]["latest_max_allowed_action"], "OBSERVE_ONLY"
            )

    def test_observed_classes_and_lanes(self):
        # Class/lane context is aggregated across observations.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            by_key = {r["pair_key"]: r for r in _read_csv(out_csv)}
            self.assertEqual(
                by_key["mintA|mintB"]["observed_strategy_classes"], "CORE|TACTICAL"
            )
            self.assertEqual(
                by_key["mintA|mintB"]["observed_lanes"], "CLEAN|RISKY_BUT_INTERESTING"
            )

    def test_missing_optional_tables_does_not_crash(self):
        # (11) Missing optional tables (flags/decisions/observations) do not crash.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_partial_db(tmp)
            rc, out_md, out_csv, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("table missing", text)
            self.assertIn("affected pair count: 0", text)

    def test_script_does_not_modify_duckdb(self):
        # (12) No DuckDB tables are modified (size + mtime stable across runs).
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

    def test_no_forbidden_action_semantics_except_safety_text(self):
        # (13) Forbidden-action semantics do not appear except in safety /
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
                       "does not", "do not", "neither")
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


# ---------------------------------------------------------------------------
# Small CSV reader helper
# ---------------------------------------------------------------------------

def _read_csv(path):
    import csv
    with Path(path).open(newline="", encoding="utf-8") as fh:
        yield from csv.DictReader(fh)


if __name__ == "__main__":
    unittest.main()
