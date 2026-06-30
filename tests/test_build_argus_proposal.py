#!/usr/bin/env python3
"""Tests for scripts/build_argus_proposal.py (ARGUS Proposal Report v0.1).

NAME NOTE: ARGUS was previously called Hermes during design, but was renamed to
avoid confusion with external Hermes agent projects. These tests cover the
renamed component.

These tests verify ARGUS is strictly a PROPOSAL-ONLY, READ-ONLY reporter:

- A missing database fails and creates nothing.
- A dry run writes no files.
- A proposal Markdown + findings CSV are written when the DB has safe data.
- future_position_events count > 0 fails hard and writes no proposal.
- future_position_events count == 0 passes.
- Insufficient run count produces an INSUFFICIENT_EVIDENCE proposal with the
  required "collect more runs first" wording and no readiness language.
- Repeated PAPER_REVIEW_CANDIDATE produces a STABLE_CANDIDATE_REVIEW proposal
  with safe (review-only) wording.
- Repeated BLOCKED/REJECTED reasons produce a RECURRING_BLOCKER_REVIEW proposal.
- A malformed pair label produces a DATA_QUALITY_REVIEW proposal.
- CORE/TACTICAL churn produces a CLASSIFICATION_CHURN_REVIEW proposal.
- The findings CSV carries the exact required columns.
- Proposal ids are deterministic (ARGUS-YYYYMMDD-NNN).
- The DuckDB tables are never modified.
- No forbidden action semantics appear except inside negated safety/forbidden
  notices.
- Missing optional tables do not crash.
- --min-runs changes the evidence-sufficiency result.

Tests that need a real DuckDB database are skipped when the optional `duckdb`
package is not installed, so the suite always runs.
"""

import csv
import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ARGUS_PATH = REPO_ROOT / "scripts" / "build_argus_proposal.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"

DATE = "20260630"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


argus = _load_module("build_argus_proposal", ARGUS_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

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


def _make_db(tmp, *, n_runs=6, malformed=False, churn=False):
    """Create and populate a fixture runtime DB. Returns its path.

    Defaults give 6 runs (>= default min_runs=5), repeated PAPER_REVIEW_CANDIDATE,
    and recurring BLOCKED/REJECTED reasons. Optional flags add a malformed label
    and a CORE/TACTICAL churn case.
    """
    db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
    idb.init_db(str(db_path))

    conn = duckdb.connect(str(db_path))
    try:
        for i in range(n_runs):
            _insert_run(conn, f"run-{i}")

        _insert_observation(conn, "obs-1", "mintA|mintB", "USDC-SOL", "CORE")
        _insert_observation(conn, "obs-2", "mintA|mintB", "USDC-SOL", "CORE")
        _insert_observation(conn, "obs-3", "mintC|mintD", "FOO-BAR", "TACTICAL")
        if churn:
            # Same pair flips TACTICAL -> CORE across observations (churn).
            _insert_observation(conn, "obs-4", "mintC|mintD", "FOO-BAR", "CORE")

        _insert_flag(conn, "flag-1", "mintA|mintB", "USDC-SOL",
                     "low_liquidity", "MEDIUM")
        _insert_flag(conn, "flag-2", "mintC|mintD", "FOO-BAR",
                     "low_liquidity", "HIGH")

        # Repeated PAPER_REVIEW_CANDIDATE for the same pair (occurs twice).
        _insert_decision(conn, "dec-1", "mintA|mintB", "USDC-SOL",
                         "PAPER_REVIEW_CANDIDATE")
        _insert_decision(conn, "dec-2", "mintA|mintB", "USDC-SOL",
                         "PAPER_REVIEW_CANDIDATE")
        # Recurring BLOCKED reason (same blocker twice).
        _insert_decision(conn, "dec-3", "mintC|mintD", "FOO-BAR", "BLOCKED",
                         blockers="liquidity_too_low")
        _insert_decision(conn, "dec-4", "mintG|mintH", "GG-HH", "BLOCKED",
                         blockers="liquidity_too_low")
        # A REJECTED decision.
        _insert_decision(conn, "dec-5", "mintE|mintF", "BAZ-QUX", "REJECTED",
                         reason="score_below_threshold")

        if malformed:
            _insert_decision(conn, "dec-mal", "mintX|", "-USDT",
                             "NOT_EVALUATED", max_action="PAPER_ONLY")
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
            "run_id TEXT, started_at TEXT, ended_at TEXT, status TEXT)"
        )
        _insert_run_minimal = (
            "INSERT INTO pipeline_runs (run_id, started_at, ended_at, status) "
            "VALUES (?, ?, ?, ?)"
        )
        for i in range(6):
            conn.execute(_insert_run_minimal,
                         [f"run-{i}", "2026-06-30T00:00:00+00:00",
                          "2026-06-30T00:05:00+00:00", "SUCCESS"])
    finally:
        conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Constant / unit tests (no duckdb required)
# ---------------------------------------------------------------------------

class TestSafetyConstants(unittest.TestCase):
    def test_safety_phase_exact(self):
        self.assertEqual(
            argus.SAFETY_PHASE,
            "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
        )

    def test_duckdb_missing_message_exact(self):
        self.assertEqual(
            argus.DUCKDB_MISSING_MSG,
            "duckdb package is required. Install with: python3 -m pip install duckdb",
        )

    def test_findings_columns_exact(self):
        self.assertEqual(
            argus.FINDINGS_COLUMNS,
            (
                "proposal_id",
                "category",
                "severity",
                "observation",
                "evidence",
                "hypothesis",
                "recommendation",
                "risk_of_change",
                "suggested_test",
                "required_human_or_council_approval",
            ),
        )

    def test_malformed_label_detection(self):
        self.assertTrue(argus.is_malformed_label("-USDT"))
        self.assertTrue(argus.is_malformed_label("USDC-"))
        self.assertTrue(argus.is_malformed_label(""))
        self.assertTrue(argus.is_malformed_label(None))
        self.assertFalse(argus.is_malformed_label("USDC-SOL"))
        self.assertFalse(argus.is_malformed_label("SOL"))


# ---------------------------------------------------------------------------
# Missing database (no duckdb required for the fail path before connect)
# ---------------------------------------------------------------------------

class TestMissingDatabase(unittest.TestCase):
    def test_missing_db_fails_and_creates_nothing(self):
        # (1) Missing DB fails and does not create the DB.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            out_dir = Path(tmp) / "out"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = argus.main([
                    "--db-path", str(db_path),
                    "--out-dir", str(out_dir),
                    "--date", DATE,
                ])
            self.assertNotEqual(rc, 0)
            self.assertFalse(db_path.exists(), "must not create the db file")
            self.assertFalse(db_path.parent.exists(), "must not create runtime dir")
            self.assertFalse(out_dir.exists(), "must not write outputs")


# ---------------------------------------------------------------------------
# DuckDB-backed tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestArgus(unittest.TestCase):
    def _run(self, db_path, tmp, *, dry_run=False, min_runs=5, date=DATE,
             dashboard_dir=None):
        out_dir = Path(tmp) / "out"
        if dashboard_dir is None:
            dashboard_dir = Path(tmp) / "dash"
        argv = [
            "--db-path", str(db_path),
            "--dashboard-dir", str(dashboard_dir),
            "--out-dir", str(out_dir),
            "--date", date,
            "--min-runs", str(min_runs),
        ]
        if dry_run:
            argv.append("--dry-run")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = argus.main(argv)
        md = out_dir / f"argus_proposal_{date}.md"
        csv_path = out_dir / f"argus_findings_{date}.csv"
        return rc, md, csv_path, out_dir, buf.getvalue()

    # (2)
    def test_dry_run_writes_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, md, csv_path, out_dir, _ = self._run(db_path, tmp, dry_run=True)
            self.assertEqual(rc, 0)
            self.assertFalse(md.exists())
            self.assertFalse(csv_path.exists())
            self.assertFalse(out_dir.exists(), "dry run must not create out dir")

    # (3)
    def test_writes_markdown_and_csv_when_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, md, csv_path, _, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            self.assertTrue(md.exists())
            self.assertTrue(csv_path.exists())
            text = md.read_text(encoding="utf-8")
            self.assertIn("# ARGUS Proposal Report v0.1", text)
            self.assertIn(argus.SAFETY_PHASE, text)
            self.assertIn("PROPOSAL-ONLY", text)

    # (4)
    def test_future_position_events_nonzero_fails_hard(self):
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
            rc, md, csv_path, _, _ = self._run(db_path, tmp)
            self.assertNotEqual(rc, 0)
            self.assertFalse(md.exists(), "no proposal on hard violation")
            self.assertFalse(csv_path.exists(), "no findings on hard violation")

    # (5)
    def test_future_position_events_zero_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rc, md, _, _, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            text = md.read_text(encoding="utf-8")
            self.assertIn("count: 0 (expected 0)", text)

    # (6)
    def test_insufficient_runs_creates_insufficient_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, n_runs=2)
            rc, md, csv_path, _, _ = self._run(db_path, tmp, min_runs=5)
            self.assertEqual(rc, 0)
            categories = _csv_categories(csv_path)
            self.assertIn("INSUFFICIENT_EVIDENCE", categories)
            row = _csv_row_for(csv_path, "INSUFFICIENT_EVIDENCE")
            self.assertEqual(
                row["recommendation"],
                "Collect more runtime runs before paper simulation design.",
            )
            # No readiness / execution language in this proposal's fields.
            blob = " ".join(row[c] for c in argus.FINDINGS_COLUMNS).lower()
            for forbidden in ("approved", "entry", "execute", "signal", "live eligible"):
                self.assertNotIn(forbidden, blob,
                                 f"forbidden word '{forbidden}' in insufficient row")
            # When insufficient, no readiness-flavored proposals are emitted.
            self.assertNotIn("STABLE_CANDIDATE_REVIEW", categories)
            self.assertNotIn("RECURRING_BLOCKER_REVIEW", categories)

    # (7)
    def test_repeated_paper_review_candidate_safe_wording(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, n_runs=6)
            rc, md, csv_path, _, _ = self._run(db_path, tmp, min_runs=5)
            self.assertEqual(rc, 0)
            row = _csv_row_for(csv_path, "STABLE_CANDIDATE_REVIEW")
            self.assertIsNotNone(row)
            self.assertEqual(
                row["recommendation"],
                "human/council should review this candidate for future "
                "paper-simulation design consideration",
            )
            blob = " ".join(row[c] for c in argus.FINDINGS_COLUMNS).lower()
            for bad in ("enter paper", "paper trade", "open position"):
                self.assertNotIn(bad, blob)

    # (8)
    def test_recurring_blocked_rejected_review_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, n_runs=6)
            rc, _, csv_path, _, _ = self._run(db_path, tmp, min_runs=5)
            self.assertEqual(rc, 0)
            row = _csv_row_for(csv_path, "RECURRING_BLOCKER_REVIEW")
            self.assertIsNotNone(row)
            self.assertIn("review", row["recommendation"].lower())
            self.assertIn("liquidity_too_low", row["evidence"])

    # (9)
    def test_malformed_label_data_quality_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, malformed=True)
            rc, md, csv_path, _, _ = self._run(db_path, tmp)
            self.assertEqual(rc, 0)
            row = _csv_row_for(csv_path, "DATA_QUALITY_REVIEW")
            self.assertIsNotNone(row)
            self.assertIn("MALFORMED_PAIR_LABEL", row["observation"])
            self.assertIn("MALFORMED_PAIR_LABEL", md.read_text(encoding="utf-8"))

    # (10)
    def test_core_tactical_churn_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, n_runs=6, churn=True)
            rc, _, csv_path, _, _ = self._run(db_path, tmp, min_runs=5)
            self.assertEqual(rc, 0)
            row = _csv_row_for(csv_path, "CLASSIFICATION_CHURN_REVIEW")
            self.assertIsNotNone(row)
            self.assertIn("strategy-class", row["recommendation"].lower())

    # (11)
    def test_csv_has_required_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, csv_path, _, _ = self._run(db_path, tmp)
            with csv_path.open(newline="", encoding="utf-8") as fh:
                header = next(csv.reader(fh))
            self.assertEqual(tuple(header), argus.FINDINGS_COLUMNS)

    # (12)
    def test_deterministic_proposal_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            _, _, csv1, _, _ = self._run(db_path, tmp, date="20260630")
            ids1 = _csv_ids(csv1)
            # Re-run into a fresh out dir; ids must be identical for same data/date.
            out2 = Path(tmp) / "out2"
            buf = io.StringIO()
            with redirect_stdout(buf):
                argus.main([
                    "--db-path", str(db_path),
                    "--out-dir", str(out2),
                    "--dashboard-dir", str(Path(tmp) / "dash"),
                    "--date", "20260630",
                ])
            ids2 = _csv_ids(out2 / "argus_findings_20260630.csv")
            self.assertEqual(ids1, ids2)
            self.assertTrue(all(i.startswith("ARGUS-20260630-") for i in ids1))
            self.assertEqual(ids1[0], "ARGUS-20260630-001")

    # (13)
    def test_db_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            before_size = os.path.getsize(db_path)
            before_mtime = os.path.getmtime(db_path)
            self._run(db_path, tmp)
            self._run(db_path, tmp)
            self.assertEqual(before_size, os.path.getsize(db_path))
            self.assertEqual(before_mtime, os.path.getmtime(db_path))

    # (14)
    def test_no_forbidden_semantics_except_safety_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, malformed=True, churn=True)
            _, md, _, _, _ = self._run(db_path, tmp)
            text = md.read_text(encoding="utf-8")
            forbidden = ("wallet", "private key", "swap", "rebalance", "signing")
            allowers = ("no ", "not ", "does not", "never", "without", "reserved")
            for line in text.splitlines():
                low = line.lower()
                for term in forbidden:
                    if term in low:
                        self.assertTrue(
                            any(a in low for a in allowers),
                            f"forbidden term '{term}' outside safety text: {line!r}",
                        )

    # (15)
    def test_missing_optional_tables_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_partial_db(tmp)
            rc, md, csv_path, _, _ = self._run(db_path, tmp, min_runs=5)
            self.assertEqual(rc, 0)
            self.assertTrue(md.exists())
            self.assertTrue(csv_path.exists())
            text = md.read_text(encoding="utf-8")
            self.assertIn("section skipped", text)
            # Safety boundary proposal is always present.
            self.assertIn("SAFETY_BOUNDARY_REVIEW", _csv_categories(csv_path))

    # (16)
    def test_min_runs_changes_sufficiency(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp, n_runs=3)
            # min_runs high -> insufficient
            _, _, csv_hi, _, _ = self._run(db_path, tmp, min_runs=10, date="20260601")
            cats_hi = _csv_categories(csv_hi)
            self.assertIn("INSUFFICIENT_EVIDENCE", cats_hi)
            # min_runs low -> sufficient (no INSUFFICIENT_EVIDENCE)
            _, _, csv_lo, _, _ = self._run(db_path, tmp, min_runs=1, date="20260602")
            cats_lo = _csv_categories(csv_lo)
            self.assertNotIn("INSUFFICIENT_EVIDENCE", cats_lo)

    def test_dashboard_sources_listed_when_present(self):
        # Optional dashboard files are corroborated as input sources.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            dash = Path(tmp) / "dash"
            dash.mkdir(parents=True)
            (dash / "runtime_risk_dashboard.md").write_text("x", encoding="utf-8")
            (dash / "risk_decision_distribution.csv").write_text("a,b\n", encoding="utf-8")
            _, md, _, _, _ = self._run(db_path, tmp, dashboard_dir=dash)
            text = md.read_text(encoding="utf-8")
            self.assertIn("runtime_risk_dashboard.md", text)
            self.assertIn("risk_decision_distribution.csv", text)


# ---------------------------------------------------------------------------
# CSV reading helpers
# ---------------------------------------------------------------------------

def _read_csv_rows(csv_path):
    with Path(csv_path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _csv_categories(csv_path):
    return [r["category"] for r in _read_csv_rows(csv_path)]


def _csv_ids(csv_path):
    return [r["proposal_id"] for r in _read_csv_rows(csv_path)]


def _csv_row_for(csv_path, category):
    for r in _read_csv_rows(csv_path):
        if r["category"] == category:
            return r
    return None


if __name__ == "__main__":
    unittest.main()
