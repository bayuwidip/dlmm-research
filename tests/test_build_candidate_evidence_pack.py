#!/usr/bin/env python3
"""Tests for scripts/build_candidate_evidence_pack.py."""

import csv
import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "scripts" / "build_candidate_evidence_pack.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = _load_module("build_candidate_evidence_pack", REPORT_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

idb = _load_module("init_runtime_db", INIT_PATH) if HAS_DUCKDB else None


def _insert_run(conn, run_id):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO pipeline_runs "
        "(run_id, started_at, ended_at, status, safety_phase, "
        "continue_on_ohlcv_error, stale_lock_replaced, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [run_id, now, now, "SUCCESS", idb.SAFETY_PHASE, False, False, now],
    )


def _insert_observation(conn, obs_id, pair_key, pair_label, cls="CORE", lane="CLEAN", run_id="run-1"):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO strategy_observations "
        "(observation_id, run_id, observed_at, pair_key, pair_label, "
        "strategy_class_v2, test_lane, observation_ready, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [obs_id, run_id, now, pair_key, pair_label, cls, lane, True, now],
    )


def _insert_decision(
    conn,
    dec_id,
    pair_key,
    pair_label,
    decision="PAPER_REVIEW_CANDIDATE",
    action="REVIEW_FOR_FUTURE_PAPER_SIMULATION",
    max_action="FUTURE_PAPER_SIMULATION_REVIEW",
    blockers="",
    warnings="",
    imported_at="2026-06-30T12:00:00",
):
    conn.execute(
        "INSERT INTO risk_decisions "
        "(risk_decision_id, imported_at, pair_key, pair_label, "
        "strategy_class_v2, pair_status_v2, test_lane, risk_decision, "
        "risk_action, max_allowed_action, risk_blockers, risk_warnings, safety_phase) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            dec_id,
            imported_at,
            pair_key,
            pair_label,
            "CORE",
            "WATCHLIST",
            "CLEAN",
            decision,
            action,
            max_action,
            blockers,
            warnings,
            idb.SAFETY_PHASE,
        ],
    )


def _insert_flag(conn, flag_id, pair_key, pair_label, risk_flag):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO risk_flags "
        "(flag_id, observed_at, pair_key, pair_label, risk_flag, severity, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [flag_id, now, pair_key, pair_label, risk_flag, "MEDIUM", "test", now],
    )


def _candidate(conn, idx, pair_key, pair_label, obs_runs=7):
    for run_num in range(1, obs_runs + 1):
        _insert_observation(
            conn,
            f"obs-{idx}-{run_num}",
            pair_key,
            pair_label,
            run_id=f"run-{run_num}",
        )
    minute = idx % 60
    _insert_decision(conn, f"dec-{idx}", pair_key, pair_label, imported_at=f"2026-06-30T12:{minute:02d}:00")


def _make_db(tmp, *, runs=7, candidates=True):
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    idb.init_db(str(db_path))
    conn = duckdb.connect(str(db_path))
    try:
        for i in range(1, runs + 1):
            _insert_run(conn, f"run-{i}")
        if candidates:
            for idx, (pair_key, pair_label) in enumerate(
                [
                    ("mintUSDC|mintSOL", "USDC-SOL"),
                    ("mintJUP|mintSOL", "JUP-SOL"),
                    ("mintUSDC|mintCBBTC", "USDC-cbBTC"),
                    ("mintHYPE|mintUSDC", "HYPE-USDC"),
                    ("mintHYPE|mintSOL", "HYPE-SOL"),
                    ("mintTRUMP|mintUSDC", "TRUMP-USDC"),
                ],
                start=1,
            ):
                _candidate(conn, idx, pair_key, pair_label, obs_runs=runs)
        _candidate(conn, 20, "mintB|mintU", "BLOCKED-USDC", obs_runs=runs)
        _insert_decision(
            conn,
            "dec-blocked-latest",
            "mintB|mintU",
            "BLOCKED-USDC",
            decision="BLOCKED",
            action="FIX_DATA_OR_CLASSIFICATION",
            max_action="NONE",
            imported_at="2026-06-30T23:00:00",
        )
        _candidate(conn, 21, "mintR|mintU", "REJECTED-USDC", obs_runs=runs)
        _insert_decision(
            conn,
            "dec-rejected-latest",
            "mintR|mintU",
            "REJECTED-USDC",
            decision="REJECTED",
            action="REJECT",
            max_action="NONE",
            imported_at="2026-06-30T23:00:00",
        )
        _insert_observation(conn, "obs-noncore", "mintN|mintU", "NONCORE-USDC", cls="TACTICAL")
        _insert_decision(conn, "dec-noncore", "mintN|mintU", "NONCORE-USDC")
        _insert_observation(conn, "obs-nonclean", "mintQ|mintU", "QUARANTINE-USDC", lane="QUARANTINE")
        _insert_decision(conn, "dec-nonclean", "mintQ|mintU", "QUARANTINE-USDC")
    finally:
        conn.close()
    return db_path


def _make_partial_db(tmp):
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE future_position_events (event_id TEXT)")
        conn.execute("CREATE TABLE pipeline_runs (run_id TEXT)")
    finally:
        conn.close()
    return db_path


def _read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestMissingDatabase(unittest.TestCase):
    def test_missing_db_fails_and_does_not_create_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            out_md = Path(tmp) / "out" / "pack.md"
            out_csv = Path(tmp) / "out" / "pack.csv"
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = report.main(["--db-path", str(db_path), "--out-md", str(out_md), "--out-csv", str(out_csv)])
            self.assertNotEqual(rc, 0)
            self.assertFalse(db_path.exists())
            self.assertFalse(out_md.exists())
            self.assertFalse(out_csv.exists())


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestCandidateEvidencePack(unittest.TestCase):
    def _run(self, db_path, tmp, *, dry_run=False, min_runs=5, limit=20, out_dir="out"):
        out_md = Path(tmp) / out_dir / "candidate_evidence_pack.md"
        out_csv = Path(tmp) / out_dir / "candidate_evidence_pack.csv"
        argv = [
            "--db-path", str(db_path),
            "--out-md", str(out_md),
            "--out-csv", str(out_csv),
            "--min-runs", str(min_runs),
            "--limit", str(limit),
        ]
        if dry_run:
            argv.append("--dry-run")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = report.main(argv)
        return rc, out_md, out_csv, out.getvalue() + err.getvalue()

    def test_dry_run_writes_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_md, out_csv, text = self._run(_make_db(tmp), tmp, dry_run=True)
            self.assertEqual(rc, 0)
            self.assertIn("DRY RUN", text)
            self.assertFalse(out_md.exists())
            self.assertFalse(out_csv.exists())

    def test_safe_db_writes_markdown_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_md, out_csv, _ = self._run(_make_db(tmp), tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            self.assertTrue(out_csv.exists())
            self.assertIn("# Candidate Evidence Pack v0.1", out_md.read_text(encoding="utf-8"))

    def test_future_position_events_nonzero_fails_hard_and_writes_no_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            conn = duckdb.connect(str(db_path))
            try:
                conn.execute(
                    "INSERT INTO future_position_events "
                    "(event_id, event_time, phase, event_type, event_payload_json, created_at) "
                    "VALUES ('evt-1', 'now', 'PAPER', 'NOTE', '{}', 'now')"
                )
            finally:
                conn.close()
            rc, out_md, out_csv, text = self._run(db_path, tmp)
            self.assertNotEqual(rc, 0)
            self.assertIn("HARD SAFETY VIOLATION", text)
            self.assertFalse(out_md.exists())
            self.assertFalse(out_csv.exists())

    def test_future_position_events_zero_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_md, _, _ = self._run(_make_db(tmp), tmp)
            self.assertEqual(rc, 0)
            self.assertIn("future_position_events count: 0 (expected 0)", out_md.read_text(encoding="utf-8"))

    def test_selects_only_required_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            conn = duckdb.connect(str(db_path))
            try:
                _candidate(conn, 30, "mintUSDC|mintSPCX", "USDC-SPCX")
            finally:
                conn.close()
            _, _, out_csv, _ = self._run(db_path, tmp)
            labels = {row["pair_label"] for row in _read_csv(out_csv)}
            self.assertEqual(labels, {"USDC-SOL", "JUP-SOL", "USDC-cbBTC", "HYPE-USDC", "HYPE-SOL", "TRUMP-USDC"})

    def test_ignores_blocked_rejected_not_clean_not_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, out_csv, _ = self._run(_make_db(tmp), tmp)
            labels = {row["pair_label"] for row in _read_csv(out_csv)}
            for label in ("BLOCKED-USDC", "REJECTED-USDC", "NONCORE-USDC", "QUARANTINE-USDC"):
                self.assertNotIn(label, labels)

    def test_deterministic_priority_sort(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, out_csv, _ = self._run(_make_db(tmp), tmp)
            labels = [row["pair_label"] for row in _read_csv(out_csv)]
            self.assertEqual(labels, ["USDC-SOL", "JUP-SOL", "USDC-cbBTC", "HYPE-USDC", "HYPE-SOL", "TRUMP-USDC"])

    def test_parses_token_mints_from_pair_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, out_csv, _ = self._run(_make_db(tmp), tmp)
            row = _read_csv(out_csv)[0]
            self.assertEqual(row["token_a_mint"], "mintUSDC")
            self.assertEqual(row["token_b_mint"], "mintSOL")
            self.assertEqual(row["token_identity_status"], "NEEDS_MANUAL_REVIEW")

    def test_malformed_pair_key_gets_needs_more_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, candidates=False)
            conn = duckdb.connect(str(db_path))
            try:
                _candidate(conn, 99, "bad-key", "USDC-SOL")
            finally:
                conn.close()
            _, _, out_csv, _ = self._run(db_path, tmp)
            row = _read_csv(out_csv)[0]
            self.assertEqual(row["token_identity_status"], "NEEDS_MORE_DATA")
            self.assertEqual(row["pool_identity_status"], "NEEDS_MORE_DATA")
            self.assertIn("malformed pair_key", row["evidence_gaps"])

    def test_usdc_sol_clean_candidate_gets_review_only_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, out_csv, _ = self._run(_make_db(tmp), tmp)
            row = {r["pair_label"]: r for r in _read_csv(out_csv)}["USDC-SOL"]
            self.assertEqual(row["suggested_council_verdict"], "REVIEW_ONLY_PASS")

    def test_non_usdc_sol_clean_candidates_default_to_needs_more_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, out_csv, _ = self._run(_make_db(tmp), tmp)
            by_label = {r["pair_label"]: r for r in _read_csv(out_csv)}
            for label in ("JUP-SOL", "USDC-cbBTC", "HYPE-USDC", "HYPE-SOL", "TRUMP-USDC"):
                self.assertEqual(by_label[label]["suggested_council_verdict"], "NEEDS_MORE_DATA")

    def test_blocker_count_greater_than_zero_rejects_for_now(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            conn = duckdb.connect(str(db_path))
            try:
                _insert_decision(
                    conn,
                    "dec-jup-blocker",
                    "mintJUP|mintSOL",
                    "JUP-SOL",
                    blockers="NO_ELIGIBLE_FEE_POOL",
                    imported_at="2026-06-30T23:00:00",
                )
            finally:
                conn.close()
            _, _, out_csv, _ = self._run(db_path, tmp)
            row = {r["pair_label"]: r for r in _read_csv(out_csv)}["JUP-SOL"]
            self.assertEqual(row["blocker_count"], "1")
            self.assertEqual(row["suggested_council_verdict"], "REJECT_FOR_NOW")

    def test_risk_flag_count_greater_than_zero_needs_more_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            conn = duckdb.connect(str(db_path))
            try:
                _insert_flag(conn, "flag-usdc", "mintUSDC|mintSOL", "USDC-SOL", "LOW_LIQUIDITY")
            finally:
                conn.close()
            _, _, out_csv, _ = self._run(db_path, tmp)
            row = {r["pair_label"]: r for r in _read_csv(out_csv)}["USDC-SOL"]
            self.assertEqual(row["risk_flag_count_total"], "1")
            self.assertEqual(row["suggested_council_verdict"], "NEEDS_MORE_DATA")

    def test_csv_has_required_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, out_csv, _ = self._run(_make_db(tmp), tmp)
            self.assertEqual(out_csv.read_text(encoding="utf-8").splitlines()[0], ",".join(report.CSV_COLUMNS))

    def test_markdown_includes_diagnostic_and_not_paper_simulation_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out_md, _, _ = self._run(_make_db(tmp), tmp)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("diagnostic-only evidence pack", text)
            self.assertIn("not paper simulation", text)

    def test_missing_optional_tables_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out_md, out_csv, _ = self._run(_make_partial_db(tmp), tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            self.assertTrue(out_csv.exists())
            self.assertIn("table missing", out_md.read_text(encoding="utf-8"))

    def test_no_duckdb_tables_are_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            before_size = os.path.getsize(db_path)
            before_mtime = os.path.getmtime(db_path)
            self._run(db_path, tmp)
            self.assertEqual(before_size, os.path.getsize(db_path))
            self.assertEqual(before_mtime, os.path.getmtime(db_path))

    def test_forbidden_action_semantics_only_in_safety_notices(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out_md, _, _ = self._run(_make_db(tmp), tmp)
            text = out_md.read_text(encoding="utf-8")
            terms = ("approved", "execute", "signal", "live eligible", "open position", "paper trade", "enter paper")
            allowed_markers = ("no ", "not ", "does not", "never", "forbidden")
            for line in text.splitlines():
                low = line.lower()
                for term in terms:
                    if term in low:
                        self.assertTrue(any(marker in low for marker in allowed_markers), line)

    def test_min_runs_changes_evidence_sufficiency_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, runs=3)
            _, out_md_a, _, _ = self._run(db_path, tmp, min_runs=5, out_dir="a")
            _, out_md_b, _, _ = self._run(db_path, tmp, min_runs=3, out_dir="b")
            self.assertIn("evidence sufficiency: INSUFFICIENT", out_md_a.read_text(encoding="utf-8"))
            self.assertIn("evidence sufficiency: SUFFICIENT", out_md_b.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
