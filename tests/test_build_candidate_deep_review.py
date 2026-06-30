#!/usr/bin/env python3
"""Tests for scripts/build_candidate_deep_review.py."""

import csv
import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "scripts" / "build_candidate_deep_review.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = _load_module("build_candidate_deep_review", REPORT_PATH)

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
        [
            run_id,
            "2026-06-30T00:00:00+00:00",
            "2026-06-30T00:05:00+00:00",
            "SUCCESS",
            idb.SAFETY_PHASE,
            False,
            False,
            now,
        ],
    )


def _insert_observation(conn, obs_id, pair_key, pair_label, cls="CORE",
                        lane="CLEAN", run_id="run-1",
                        observed_at="2026-06-30T00:10:00+00:00"):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO strategy_observations "
        "(observation_id, run_id, observed_at, pair_key, pair_label, "
        "strategy_class_v2, test_lane, observation_ready, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [obs_id, run_id, observed_at, pair_key, pair_label, cls, lane, True, now],
    )


def _insert_decision(conn, dec_id, pair_key, pair_label,
                     decision="PAPER_REVIEW_CANDIDATE",
                     action="REVIEW_FOR_FUTURE_PAPER_SIMULATION",
                     max_action="FUTURE_PAPER_SIMULATION_REVIEW",
                     blockers="", warnings="", imported_at=None):
    conn.execute(
        "INSERT INTO risk_decisions "
        "(risk_decision_id, imported_at, pair_key, pair_label, "
        "strategy_class_v2, pair_status_v2, test_lane, risk_decision, "
        "risk_action, max_allowed_action, risk_blockers, risk_warnings, "
        "safety_phase) "
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


def _insert_flag(conn, flag_id, pair_key, pair_label, risk_flag,
                 observed_at="2026-06-30T00:15:00+00:00"):
    now = idb.utc_now_iso()
    conn.execute(
        "INSERT INTO risk_flags "
        "(flag_id, observed_at, pair_key, pair_label, risk_flag, severity, "
        "source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [flag_id, observed_at, pair_key, pair_label, risk_flag, "MEDIUM", "test", now],
    )


def _candidate(conn, idx, pair_key, pair_label):
    for run_num in range(1, 4):
        _insert_observation(
            conn,
            f"obs-{idx}-{run_num}",
            pair_key,
            pair_label,
            run_id=f"run-{run_num}",
            observed_at=f"2026-06-30T0{run_num}:10:00+00:00",
        )
    _insert_decision(
        conn,
        f"dec-{idx}",
        pair_key,
        pair_label,
        imported_at=f"2026-06-30T1{idx}:00:00",
    )


def _make_db(tmp, *, runs=5, include_candidates=True):
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    idb.init_db(str(db_path))
    conn = duckdb.connect(str(db_path))
    try:
        for i in range(runs):
            _insert_run(conn, f"run-{i + 1}")

        if include_candidates:
            candidates = [
                ("mintUSDC|mintSOL", "USDC-SOL"),
                ("mintJUP|mintSOL", "JUP-SOL"),
                ("mintUSDC|mintCBBTC", "USDC-cbBTC"),
                ("mintHYPE|mintUSDC", "HYPE-USDC"),
                ("mintHYPE|mintSOL", "HYPE-SOL"),
                ("mintTRUMP|mintUSDC", "TRUMP-USDC"),
            ]
            for idx, (pair_key, pair_label) in enumerate(candidates, start=1):
                _candidate(conn, idx, pair_key, pair_label)

            _insert_flag(
                conn,
                "flag-usdc-sol",
                "mintUSDC|mintSOL",
                "USDC-SOL",
                "LOW_VOLUME_WARNING",
            )
            _insert_decision(
                conn,
                "dec-usdc-sol-latest",
                "mintUSDC|mintSOL",
                "USDC-SOL",
                blockers="",
                warnings="LOW_VOLUME_WARNING",
                imported_at="2026-06-30T23:00:00",
            )

        # Non-candidates that must be ignored.
        _insert_observation(
            conn, "blocked-obs", "mintB|mintU", "BLOCKED-USDC",
            run_id="run-1"
        )
        _insert_decision(
            conn,
            "blocked-dec",
            "mintB|mintU",
            "BLOCKED-USDC",
            decision="BLOCKED",
            action="FIX_DATA_OR_CLASSIFICATION",
            max_action="NONE",
            blockers="NO_ELIGIBLE_FEE_POOL",
        )
        _insert_observation(
            conn, "rejected-obs", "mintR|mintU", "REJECTED-USDC",
            run_id="run-1"
        )
        _insert_decision(
            conn,
            "rejected-dec",
            "mintR|mintU",
            "REJECTED-USDC",
            decision="REJECTED",
            action="REJECT",
            max_action="NONE",
        )
        _insert_observation(
            conn, "ne-obs", "mintN|mintU", "NE-USDC", run_id="run-1"
        )
        _insert_decision(
            conn,
            "ne-dec",
            "mintN|mintU",
            "NE-USDC",
            decision="NOT_EVALUATED",
            action="NO_ACTION",
            max_action="NONE",
        )
    finally:
        conn.close()
    return db_path


def _make_partial_db(tmp):
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
    with Path(path).open(newline="", encoding="utf-8") as fh:
        yield from csv.DictReader(fh)


class TestConstants(unittest.TestCase):
    def test_csv_columns_exact(self):
        self.assertEqual(
            report.CSV_COLUMNS,
            (
                "pair_key",
                "pair_label",
                "observation_count",
                "distinct_run_count",
                "first_seen_at",
                "last_seen_at",
                "strategy_class_history",
                "lane_history",
                "strategy_class_change_count",
                "lane_change_count",
                "latest_strategy_class",
                "latest_lane",
                "latest_risk_decision",
                "latest_risk_action",
                "latest_max_allowed_action",
                "risk_flags",
                "risk_flag_count",
                "blocker_history",
                "blocker_count",
                "ohlcv_data_notes",
                "liquidity_volume_volatility_notes",
                "data_gaps",
                "manual_review_notes",
                "suggested_human_council_questions",
                "diagnostic_status",
            ),
        )

    def test_duckdb_missing_message_exact(self):
        self.assertEqual(
            report.DUCKDB_MISSING_MSG,
            "duckdb package is required. Install with: "
            "python3 -m pip install duckdb",
        )

    def test_review_phrase_is_safe(self):
        self.assertEqual(
            report.REVIEW_PHRASE,
            "human/council may review for future paper-simulation design "
            "consideration",
        )


class TestMissingDatabase(unittest.TestCase):
    def test_missing_db_fails_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            out_md = Path(tmp) / "out" / "review.md"
            out_csv = Path(tmp) / "out" / "review.csv"
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = report.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--out-md",
                        str(out_md),
                        "--out-csv",
                        str(out_csv),
                    ]
                )
            self.assertNotEqual(rc, 0)
            self.assertFalse(db_path.exists())
            self.assertFalse(db_path.parent.exists())
            self.assertFalse(out_md.exists())
            self.assertFalse(out_csv.exists())


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestCandidateDeepReview(unittest.TestCase):
    def _run(self, db_path, tmp, *, dry_run=False, limit=20, min_runs=5,
             out_dir="out"):
        out_md = Path(tmp) / out_dir / "review.md"
        out_csv = Path(tmp) / out_dir / "review.csv"
        argv = [
            "--db-path",
            str(db_path),
            "--out-md",
            str(out_md),
            "--out-csv",
            str(out_csv),
            "--limit",
            str(limit),
            "--min-runs",
            str(min_runs),
        ]
        if dry_run:
            argv.append("--dry-run")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = report.main(argv)
        return rc, out_md, out_csv, out.getvalue() + err.getvalue()

    def test_dry_run_writes_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, out_md, out_csv, text = self._run(db_path, tmp, dry_run=True)
            self.assertEqual(rc, 0)
            self.assertIn("DRY RUN", text)
            self.assertFalse(out_md.exists())
            self.assertFalse(out_csv.exists())

    def test_report_writes_markdown_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, out_md, out_csv, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            self.assertTrue(out_csv.exists())
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("# Candidate Deep Review Report v0.1", text)
            self.assertIn("generated_at (UTC):", text)
            self.assertIn("Candidate Shortlist", text)
            self.assertIn("Risk/Data Quality Summary", text)

    def test_future_position_events_nonzero_fails_and_no_report(self):
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
            rc, out_md, out_csv, text = self._run(db_path, tmp)
            self.assertNotEqual(rc, 0)
            self.assertFalse(out_md.exists())
            self.assertFalse(out_csv.exists())
            self.assertIn("HARD SAFETY VIOLATION", text)

    def test_future_position_events_zero_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, out_md, _, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("future_position_events count: 0 (expected 0)", text)

    def test_selects_stable_paper_review_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            labels = {r["pair_label"] for r in _read_csv(out_csv)}
            self.assertIn("USDC-SOL", labels)
            self.assertIn("JUP-SOL", labels)
            self.assertEqual(len(labels), 6)

    def test_ignores_non_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            labels = {r["pair_label"] for r in _read_csv(out_csv)}
            self.assertNotIn("BLOCKED-USDC", labels)
            self.assertNotIn("REJECTED-USDC", labels)
            self.assertNotIn("NE-USDC", labels)

    def test_deterministic_candidate_priority_sort(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            labels = [r["pair_label"] for r in _read_csv(out_csv)]
            self.assertEqual(
                labels,
                [
                    "USDC-SOL",
                    "JUP-SOL",
                    "USDC-cbBTC",
                    "HYPE-USDC",
                    "HYPE-SOL",
                    "TRUMP-USDC",
                ],
            )

    def test_candidate_specific_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            by_label = {r["pair_label"]: r for r in _read_csv(out_csv)}
            self.assertIn("Benchmark/reference", by_label["USDC-SOL"]["manual_review_notes"])
            self.assertIn("Solana ecosystem", by_label["JUP-SOL"]["manual_review_notes"])
            self.assertIn("wrapped/bridged BTC", by_label["USDC-cbBTC"]["manual_review_notes"])
            self.assertIn("data source", by_label["USDC-cbBTC"]["manual_review_notes"])
            self.assertIn("Validate token identity", by_label["HYPE-USDC"]["manual_review_notes"])
            self.assertIn("Validate token identity", by_label["HYPE-SOL"]["manual_review_notes"])
            self.assertIn("Narrative/meme/political-risk", by_label["TRUMP-USDC"]["manual_review_notes"])

    def test_csv_has_required_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, out_csv, _ = self._run(db_path, tmp)
            header = out_csv.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(header, ",".join(report.CSV_COLUMNS))

    def test_missing_optional_tables_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_partial_db(tmp)
            rc, out_md, out_csv, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(out_md.exists())
            self.assertTrue(out_csv.exists())
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("table missing", text)
            self.assertIn("candidate count: 0", text)

    def test_script_does_not_modify_duckdb(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            before_size = os.path.getsize(db_path)
            before_mtime = os.path.getmtime(db_path)
            self._run(db_path, tmp, out_dir="a")
            self._run(db_path, tmp, out_dir="b")
            self.assertEqual(before_size, os.path.getsize(db_path))
            self.assertEqual(before_mtime, os.path.getmtime(db_path))

    def test_no_forbidden_action_semantics_except_safety_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, out_md, _, _ = self._run(db_path, tmp)
            text = out_md.read_text(encoding="utf-8")
            forbidden = (
                "approved",
                "execute",
                "signal",
                "live eligible",
                "open position",
                "paper trade",
                "enter paper",
            )
            markers = (
                "no ",
                "never",
                "not ",
                "without",
                "forbidden",
                "does not",
                "do not",
                "neither",
                "authorizes nothing",
            )
            for line in text.splitlines():
                low = line.lower()
                for term in forbidden:
                    if term in low:
                        self.assertTrue(
                            any(m in low for m in markers),
                            f"forbidden term '{term}' outside safety text: {line!r}",
                        )

    def test_min_runs_changes_evidence_sufficiency(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, runs=3)
            _, out_md_a, _, _ = self._run(db_path, tmp, min_runs=5, out_dir="a")
            self.assertIn(
                "evidence sufficiency: INSUFFICIENT",
                out_md_a.read_text(encoding="utf-8"),
            )
            _, out_md_b, _, _ = self._run(db_path, tmp, min_runs=3, out_dir="b")
            self.assertIn(
                "evidence sufficiency: SUFFICIENT",
                out_md_b.read_text(encoding="utf-8"),
            )


class TestDuckdbMissing(unittest.TestCase):
    def test_missing_duckdb_prints_exact_message_and_exits_nonzero(self):
        original = report.require_duckdb

        def _raise():
            raise RuntimeError(report.DUCKDB_MISSING_MSG)

        report.require_duckdb = _raise
        try:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = report.main(["--db-path", "nonexistent.duckdb"])
            self.assertNotEqual(rc, 0)
            self.assertIn(report.DUCKDB_MISSING_MSG, err.getvalue())
        finally:
            report.require_duckdb = original


if __name__ == "__main__":
    unittest.main()
