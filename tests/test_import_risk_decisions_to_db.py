#!/usr/bin/env python3
"""Tests for scripts/import_risk_decisions_to_db.py
(Risk Decisions Importer v0.1).

Tests that need a real DuckDB database are skipped when the optional `duckdb`
package is not installed, so the suite always runs. The safety-banner,
missing-file, row-validation, id-generation, forbidden-token, and
missing-dependency paths do not need duckdb.
"""

import copy
import csv
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
IMPORTER_PATH = REPO_ROOT / "scripts" / "import_risk_decisions_to_db.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


imp = _load_module("import_risk_decisions_to_db", IMPORTER_PATH)
idb = _load_module("init_runtime_db", INIT_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


SAFETY_PHASE = "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY"

# A CORE paper-review-candidate row (matches the safe apply_risk_policy output).
SAMPLE_ROW = {
    "pair_key": "MINTAAA|MINTBBB",
    "pair_label": "USDC-SOL",
    "strategy_class_v2": "CORE",
    "pair_status_v2": "PAPER TEST",
    "test_lane": "CLEAN",
    "live_eligibility": "PAPER_TEST_ALLOWED",
    "required_capability": "PAPER_SIM",
    "risk_flag_count": "0",
    "risk_flags": "none",
    "risk_decision": "PAPER_REVIEW_CANDIDATE",
    "risk_action": "REVIEW_FOR_FUTURE_PAPER_SIMULATION",
    "max_allowed_action": "FUTURE_PAPER_SIMULATION_REVIEW",
    "risk_blockers": "none",
    "risk_warnings": "none",
    "risk_required_next_step": (
        "Eligible for FUTURE paper-simulation REVIEW only. This is NOT a paper "
        "entry, NOT a paper trade, and NOT live readiness. No position is "
        "created and no order is placed."
    ),
    "risk_policy_reason": (
        "PAPER_REVIEW_CANDIDATE: CORE + CLEAN lane + PAPER_TEST_ALLOWED with no "
        "blockers and no high-warning flags. Future paper-simulation review "
        "only; the risk engine grants no execution capability."
    ),
    "safety_phase": SAFETY_PHASE,
}

# A REJECTED row that carries the legit negation NOT_LIVE_ELIGIBLE — this must be
# accepted (it contains the substring LIVE_ELIGIBLE but is not a live grant).
SAMPLE_ROW_REJECTED = {
    "pair_key": "MINTCCC|MINTDDD",
    "pair_label": "ANSEM-SOL",
    "strategy_class_v2": "REJECT",
    "pair_status_v2": "REJECT",
    "test_lane": "QUARANTINE",
    "live_eligibility": "NOT_LIVE_ELIGIBLE",
    "required_capability": "NONE",
    "risk_flag_count": "3",
    "risk_flags": "FEE_TVL_DISTORTION|EXTREME_VOLATILITY|LOW_DATA_COMPLETENESS",
    "risk_decision": "REJECTED",
    "risk_action": "REJECT",
    "max_allowed_action": "NONE",
    "risk_blockers": "CLASSIFIED_REJECT|TEST_LANE_QUARANTINE|NOT_LIVE_ELIGIBLE",
    "risk_warnings": "EXTREME_VOLATILITY|LOW_DATA_COMPLETENESS",
    "risk_required_next_step": (
        "No action. Pair was rejected by strategy classification. Do not "
        "observe-for-entry and do not consider for paper review."
    ),
    "risk_policy_reason": (
        "REJECTED: strategy_class_v2='REJECT', pair_status_v2='REJECT'. "
        "Classifier reject is upheld by the risk engine."
    ),
    "safety_phase": SAFETY_PHASE,
}

CSV_HEADER = list(imp.REQUIRED_CSV_COLUMNS)


def _write_csv(directory, rows, name="risk_decisions.csv", header=None):
    path = Path(directory) / name
    cols = header if header is not None else CSV_HEADER
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in cols})
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
        self.assertEqual(imp.SAFETY_PHASE, SAFETY_PHASE)

    def test_safety_banner_contains_all_boundary_terms(self):
        for term in [
            "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
            "No wallet",
            "No private key",
            "No signing",
            "No swap",
            "No LP",
            "No rebalance",
            "No live execution",
            "No LIVE_ELIGIBLE_*",
        ]:
            self.assertIn(term, imp.SAFETY_BANNER)

    def test_required_schema_tables(self):
        self.assertEqual(
            imp.REQUIRED_SCHEMA_TABLES, ("runtime_schema_meta", "risk_decisions")
        )

    def test_forbidden_write_tables_listed(self):
        self.assertEqual(
            set(imp.FORBIDDEN_WRITE_TABLES),
            {
                "pipeline_runs",
                "pipeline_steps",
                "strategy_observations",
                "risk_flags",
                "future_position_events",
            },
        )

    def test_risk_decision_id_prefix(self):
        self.assertEqual(imp.RISK_DECISION_ID_PREFIX, "risk_")


# ---------------------------------------------------------------------------
# Row validation (no duckdb required)
# ---------------------------------------------------------------------------

class TestRowValidation(unittest.TestCase):
    def test_valid_row_passes(self):
        imp.validate_row(copy.deepcopy(SAMPLE_ROW), 0)  # must not raise

    def test_not_live_eligible_negation_accepted(self):
        # The legit negation must NOT trip the forbidden-token guard.
        imp.validate_row(copy.deepcopy(SAMPLE_ROW_REJECTED), 0)

    def test_safe_existing_wording_accepted(self):
        # Lowercase explanatory wording such as "no execution" / "not live
        # readiness" must be accepted.
        rec = copy.deepcopy(SAMPLE_ROW)
        rec["risk_policy_reason"] = (
            "Future paper-simulation review only; the risk engine grants no "
            "execution capability and asserts no live readiness."
        )
        imp.validate_row(rec, 0)  # must not raise

    def test_invalid_risk_decision_fails(self):
        bad = copy.deepcopy(SAMPLE_ROW)
        bad["risk_decision"] = "APPROVED"
        with self.assertRaises(imp.RiskDecisionValidationError):
            imp.validate_row(bad, 0)

    def test_invalid_risk_action_fails(self):
        bad = copy.deepcopy(SAMPLE_ROW)
        bad["risk_action"] = "ENTER_POSITION"
        with self.assertRaises(imp.RiskDecisionValidationError):
            imp.validate_row(bad, 0)

    def test_invalid_max_allowed_action_fails(self):
        bad = copy.deepcopy(SAMPLE_ROW)
        bad["max_allowed_action"] = "LIVE"
        with self.assertRaises(imp.RiskDecisionValidationError):
            imp.validate_row(bad, 0)

    def test_invalid_safety_phase_fails(self):
        bad = copy.deepcopy(SAMPLE_ROW)
        bad["safety_phase"] = "LIVE_PHASE"
        with self.assertRaises(imp.RiskDecisionValidationError):
            imp.validate_row(bad, 0)

    def test_forbidden_live_eligible_grant_fails(self):
        bad = copy.deepcopy(SAMPLE_ROW)
        bad["live_eligibility"] = "LIVE_ELIGIBLE_TINY_SIZE"
        with self.assertRaises(imp.RiskDecisionValidationError):
            imp.validate_row(bad, 0)

    def test_forbidden_token_in_any_field_fails(self):
        for col, token in [
            ("risk_required_next_step", "EXECUTE"),
            ("required_capability", "WALLET"),
            ("risk_policy_reason", "REBALANCE"),
            ("risk_blockers", "SWAP"),
        ]:
            bad = copy.deepcopy(SAMPLE_ROW)
            bad[col] = f"do {token} now"
            with self.assertRaises(imp.RiskDecisionValidationError):
                imp.validate_row(bad, 0)

    def test_contains_forbidden_token_helper(self):
        self.assertIsNone(imp.contains_forbidden_token("NOT_LIVE_ELIGIBLE"))
        self.assertIsNone(imp.contains_forbidden_token("no execution, not live"))
        self.assertEqual(
            imp.contains_forbidden_token("LIVE_ELIGIBLE_FULL"),
            imp.FORBIDDEN_LIVE_PREFIX,
        )
        self.assertEqual(imp.contains_forbidden_token("PAPER_ENTRY"), "PAPER_ENTRY")


# ---------------------------------------------------------------------------
# Deterministic id generation (no duckdb required)
# ---------------------------------------------------------------------------

class TestIdGeneration(unittest.TestCase):
    def test_risk_decision_id_is_deterministic(self):
        a = imp.compute_risk_decision_id(copy.deepcopy(SAMPLE_ROW))
        b = imp.compute_risk_decision_id(copy.deepcopy(SAMPLE_ROW))
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("risk_"))

    def test_risk_decision_id_changes_with_inputs(self):
        base = imp.compute_risk_decision_id(copy.deepcopy(SAMPLE_ROW))
        other = copy.deepcopy(SAMPLE_ROW)
        other["risk_decision"] = "OBSERVE_ONLY"
        self.assertNotEqual(base, imp.compute_risk_decision_id(other))


# ---------------------------------------------------------------------------
# CSV loading (no duckdb required)
# ---------------------------------------------------------------------------

class TestCsvLoading(unittest.TestCase):
    def test_missing_required_column_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            header = [c for c in CSV_HEADER if c != "risk_decision"]
            path = _write_csv(tmp, [SAMPLE_ROW], header=header)
            with self.assertRaises(imp.RiskDecisionValidationError):
                imp.load_risk_decisions(str(path))

    def test_missing_csv_raises(self):
        with self.assertRaises(FileNotFoundError):
            imp.load_risk_decisions("/no/such/risk_decisions.csv")


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
# Missing-file behavior
# ---------------------------------------------------------------------------

class TestMissingFiles(unittest.TestCase):
    def test_missing_db_fails_and_does_not_create_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            csv_path = _write_csv(tmp, [SAMPLE_ROW])
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            self.assertNotEqual(rc, 0)
            self.assertFalse(db_path.exists(), "must not create the DB")
            self.assertFalse(db_path.parent.exists(), "must not create runtime dir")
            self.assertIn("init_runtime_db.py", err.getvalue())

    def test_missing_csv_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            placeholder_db = Path(tmp) / "runtime" / "dlmm.duckdb"
            placeholder_db.parent.mkdir(parents=True, exist_ok=True)
            placeholder_db.write_text("not-a-real-db")
            missing_csv = Path(tmp) / "nope.csv"
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = imp.main(
                    [
                        "--db-path",
                        str(placeholder_db),
                        "--risk-decisions-csv",
                        str(missing_csv),
                    ]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("Risk decisions CSV not found", err.getvalue())


# ---------------------------------------------------------------------------
# DB-backed behavior (requires duckdb)
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestImportWithDb(unittest.TestCase):
    def _counts(self, db_path):
        conn = duckdb.connect(str(db_path))
        try:
            rd = conn.execute("SELECT COUNT(*) FROM risk_decisions").fetchone()[0]
            runs = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
            steps = conn.execute("SELECT COUNT(*) FROM pipeline_steps").fetchone()[0]
            obs = conn.execute(
                "SELECT COUNT(*) FROM strategy_observations"
            ).fetchone()[0]
            flags = conn.execute("SELECT COUNT(*) FROM risk_flags").fetchone()[0]
            fpe = conn.execute(
                "SELECT COUNT(*) FROM future_position_events"
            ).fetchone()[0]
        finally:
            conn.close()
        return rd, runs, steps, obs, flags, fpe

    def test_dry_run_performs_no_db_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_csv(tmp, [SAMPLE_ROW, SAMPLE_ROW_REJECTED])
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--risk-decisions-csv",
                        str(csv_path),
                        "--dry-run",
                    ]
                )
            self.assertEqual(rc, 0)
            rd, *_ = self._counts(db_path)
            self.assertEqual(rd, 0, "dry-run must not write risk_decisions")
            self.assertIn("DRY RUN", buf.getvalue())

    def test_valid_csv_imports_risk_decisions_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_csv(tmp, [SAMPLE_ROW, SAMPLE_ROW_REJECTED])
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            self.assertEqual(rc, 0)
            rd, runs, steps, obs, flags, fpe = self._counts(db_path)
            self.assertEqual(rd, 2)
            self.assertEqual((runs, steps, obs, flags, fpe), (0, 0, 0, 0, 0))

    def test_imported_columns_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_csv(tmp, [SAMPLE_ROW])
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            conn = duckdb.connect(str(db_path))
            try:
                row = conn.execute(
                    "SELECT risk_decision, max_allowed_action, source_csv, "
                    "risk_flag_count FROM risk_decisions WHERE pair_key = ?",
                    [SAMPLE_ROW["pair_key"]],
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(row[0], "PAPER_REVIEW_CANDIDATE")
            self.assertEqual(row[1], "FUTURE_PAPER_SIMULATION_REVIEW")
            self.assertEqual(row[2], str(csv_path))
            self.assertEqual(row[3], 0)

    def test_duplicate_import_fails_without_upsert(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_csv(tmp, [SAMPLE_ROW])
            with redirect_stdout(io.StringIO()):
                rc1 = imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            self.assertEqual(rc1, 0)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc2 = imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            self.assertNotEqual(rc2, 0)
            self.assertIn("already exists", err.getvalue())
            self.assertIn("--upsert", err.getvalue())
            rd, *_ = self._counts(db_path)
            self.assertEqual(rd, 1, "failed duplicate must not add a row")

    def test_duplicate_import_succeeds_with_upsert_no_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_csv(tmp, [SAMPLE_ROW])
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--risk-decisions-csv",
                        str(csv_path),
                        "--upsert",
                    ]
                )
            self.assertEqual(rc, 0)
            rd, *_ = self._counts(db_path)
            self.assertEqual(rd, 1, "upsert must not duplicate the row")

    def test_deterministic_id_stable_across_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_csv(tmp, [SAMPLE_ROW])
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            conn = duckdb.connect(str(db_path))
            try:
                first_id = conn.execute(
                    "SELECT risk_decision_id FROM risk_decisions"
                ).fetchone()[0]
            finally:
                conn.close()
            with redirect_stdout(io.StringIO()):
                imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--risk-decisions-csv",
                        str(csv_path),
                        "--upsert",
                    ]
                )
            conn = duckdb.connect(str(db_path))
            try:
                ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT risk_decision_id FROM risk_decisions"
                    ).fetchall()
                ]
            finally:
                conn.close()
            self.assertEqual(ids, [first_id])
            self.assertEqual(
                first_id, imp.compute_risk_decision_id(SAMPLE_ROW)
            )

    def test_upsert_replaces_changed_passthrough_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_csv(tmp, [SAMPLE_ROW])
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            # Change only an id-irrelevant passthrough field; id stays the same.
            modified = copy.deepcopy(SAMPLE_ROW)
            modified["risk_warnings"] = "REVIEWED_NOTE"
            mod_csv = _write_csv(tmp, [modified], name="mod.csv")
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--risk-decisions-csv",
                        str(mod_csv),
                        "--upsert",
                    ]
                )
            self.assertEqual(rc, 0)
            conn = duckdb.connect(str(db_path))
            try:
                total = conn.execute("SELECT COUNT(*) FROM risk_decisions").fetchone()[0]
                warn = conn.execute(
                    "SELECT risk_warnings FROM risk_decisions WHERE pair_key = ?",
                    [SAMPLE_ROW["pair_key"]],
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(total, 1, "upsert must not duplicate")
            self.assertEqual(warn, "REVIEWED_NOTE", "upsert must replace the row")

    def test_importer_never_writes_future_position_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_csv(tmp, [SAMPLE_ROW, SAMPLE_ROW_REJECTED])
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            _, runs, steps, obs, flags, fpe = self._counts(db_path)
            self.assertEqual(fpe, 0, "must not write future_position_events")
            self.assertEqual((runs, steps, obs, flags), (0, 0, 0, 0))

    def test_invalid_enum_fails_via_main_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            bad = copy.deepcopy(SAMPLE_ROW)
            bad["risk_decision"] = "APPROVED"
            csv_path = _write_csv(tmp, [bad])
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            self.assertNotEqual(rc, 0)
            rd, *_ = self._counts(db_path)
            self.assertEqual(rd, 0, "invalid enum must not write any row")

    def test_forbidden_token_fails_via_main_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            bad = copy.deepcopy(SAMPLE_ROW)
            bad["live_eligibility"] = "LIVE_ELIGIBLE_FULL"
            csv_path = _write_csv(tmp, [bad])
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            self.assertNotEqual(rc, 0)
            rd, *_ = self._counts(db_path)
            self.assertEqual(rd, 0, "forbidden token must not write any row")

    def test_safe_existing_sample_csv_imports(self):
        # The real generated CSV (with NOT_LIVE_ELIGIBLE + lowercase prose) must
        # import cleanly.
        real_csv = REPO_ROOT / "data" / "risk_decisions.csv"
        if not real_csv.is_file():
            self.skipTest("data/risk_decisions.csv not present")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(real_csv)]
                )
            self.assertEqual(rc, 0)
            rd, runs, steps, obs, flags, fpe = self._counts(db_path)
            self.assertGreater(rd, 0)
            self.assertEqual((runs, steps, obs, flags, fpe), (0, 0, 0, 0, 0))

    def test_missing_schema_table_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "empty.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(db_path))
            conn.close()
            csv_path = _write_csv(tmp, [SAMPLE_ROW])
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("init_runtime_db.py", err.getvalue())

    def test_invalid_db_safety_phase_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            conn = duckdb.connect(str(db_path))
            conn.execute(
                "UPDATE runtime_schema_meta SET safety_phase = ?",
                ["LIVE_ELIGIBLE_CORE"],
            )
            conn.close()
            csv_path = _write_csv(tmp, [SAMPLE_ROW])
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--risk-decisions-csv", str(csv_path)]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("safety_phase", err.getvalue())
            rd, *_ = self._counts(db_path)
            self.assertEqual(rd, 0, "invalid db safety_phase must not write")


if __name__ == "__main__":
    unittest.main()
