#!/usr/bin/env python3
"""Tests for scripts/import_strategy_observations_to_db.py
(Strategy Observations Importer v0.1).

Tests that need a real DuckDB database are skipped when the optional `duckdb`
package is not installed, so the suite always runs. The safety-banner,
missing-file, record-validation, id-generation, severity-mapping, and
missing-dependency paths do not need duckdb.
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
IMPORTER_PATH = REPO_ROOT / "scripts" / "import_strategy_observations_to_db.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


imp = _load_module("import_strategy_observations_to_db", IMPORTER_PATH)
idb = _load_module("init_runtime_db", INIT_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


# A record in the legacy observe_strategy.py JSONL shape: uses observed_at_utc,
# no observation_id, no observation_ready.
SAMPLE_RECORD = {
    "run_id": "2026-06-30T01:32:46+00:00",
    "observed_at_utc": "2026-06-30T01:32:46+00:00",
    "pair_key": "MINTAAA|MINTBBB",
    "pair_label": "USDC-SOL",
    "representative_pool_address": "POOL111",
    "strategy_class_v2": "CORE",
    "pair_status_v2": "PAPER TEST",
    "test_lane": "CLEAN",
    "live_eligibility": "PAPER_TEST_ALLOWED",
    "required_capability": "PAPER_SIM",
    "risk_flag_count": "0",
    "risk_flags": "none",
}

# A record carrying severe + high + info risk flags to exercise severity mapping.
SAMPLE_RECORD_FLAGGED = {
    "run_id": "2026-06-30T01:32:46+00:00",
    "observed_at_utc": "2026-06-30T01:32:46+00:00",
    "pair_key": "MINTCCC|MINTDDD",
    "pair_label": "ANSEM-SOL",
    "representative_pool_address": "POOL222",
    "strategy_class_v2": "REJECT",
    "pair_status_v2": "REJECT",
    "test_lane": "QUARANTINE",
    "live_eligibility": "NOT_LIVE_ELIGIBLE",
    "required_capability": "NONE",
    "risk_flag_count": "3",
    "risk_flags": "MALFORMED_PAIR_LABEL|LOW_LIQUIDITY|EXTREME_VOLATILITY",
}


def _write_jsonl(directory, records, name="obs.jsonl"):
    path = Path(directory) / name
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
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

    def test_required_schema_tables(self):
        self.assertEqual(
            imp.REQUIRED_SCHEMA_TABLES,
            ("runtime_schema_meta", "strategy_observations", "risk_flags"),
        )

    def test_forbidden_write_tables_listed(self):
        self.assertEqual(
            set(imp.FORBIDDEN_WRITE_TABLES),
            {"pipeline_runs", "pipeline_steps", "future_position_events"},
        )

    def test_risk_flag_source_constant(self):
        self.assertEqual(imp.RISK_FLAG_SOURCE, "strategy_observations_jsonl")


# ---------------------------------------------------------------------------
# Record validation + normalization (no duckdb required)
# ---------------------------------------------------------------------------

class TestRecordValidation(unittest.TestCase):
    def test_valid_record_passes(self):
        imp.validate_observation(copy.deepcopy(SAMPLE_RECORD), 0)  # must not raise

    def test_observed_at_alias_accepted(self):
        # observed_at_utc satisfies the observed_at requirement.
        rec = copy.deepcopy(SAMPLE_RECORD)
        self.assertEqual(
            imp.resolve_observed_at(rec), "2026-06-30T01:32:46+00:00"
        )
        rec2 = copy.deepcopy(SAMPLE_RECORD)
        del rec2["observed_at_utc"]
        rec2["observed_at"] = "2026-07-01T00:00:00+00:00"
        self.assertEqual(imp.resolve_observed_at(rec2), "2026-07-01T00:00:00+00:00")

    def test_missing_required_field_fails(self):
        bad = copy.deepcopy(SAMPLE_RECORD)
        del bad["pair_key"]
        with self.assertRaises(imp.ObservationValidationError):
            imp.validate_observation(bad, 0)

    def test_missing_observed_at_and_alias_fails(self):
        bad = copy.deepcopy(SAMPLE_RECORD)
        del bad["observed_at_utc"]
        with self.assertRaises(imp.ObservationValidationError):
            imp.validate_observation(bad, 0)

    def test_forbidden_live_eligibility_fails(self):
        bad = copy.deepcopy(SAMPLE_RECORD)
        bad["live_eligibility"] = "LIVE_ELIGIBLE_TINY_SIZE"
        with self.assertRaises(imp.ObservationValidationError):
            imp.validate_observation(bad, 0)

    def test_observation_ready_defaults_false_when_absent(self):
        row = imp.build_observation_row(copy.deepcopy(SAMPLE_RECORD), "NOW")
        self.assertIs(row["observation_ready"], False)

    def test_observation_ready_coerced_when_present(self):
        rec = copy.deepcopy(SAMPLE_RECORD)
        rec["observation_ready"] = "true"
        row = imp.build_observation_row(rec, "NOW")
        self.assertIs(row["observation_ready"], True)


# ---------------------------------------------------------------------------
# Deterministic id generation (no duckdb required)
# ---------------------------------------------------------------------------

class TestIdGeneration(unittest.TestCase):
    def test_observation_id_is_deterministic(self):
        a = imp.compute_observation_id(copy.deepcopy(SAMPLE_RECORD))
        b = imp.compute_observation_id(copy.deepcopy(SAMPLE_RECORD))
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("obs_"))

    def test_observation_id_uses_existing_when_present(self):
        rec = copy.deepcopy(SAMPLE_RECORD)
        rec["observation_id"] = "obs_explicit"
        self.assertEqual(imp.compute_observation_id(rec), "obs_explicit")

    def test_observation_id_changes_with_inputs(self):
        rec = copy.deepcopy(SAMPLE_RECORD)
        base = imp.compute_observation_id(rec)
        rec2 = copy.deepcopy(SAMPLE_RECORD)
        rec2["strategy_class_v2"] = "TACTICAL"
        self.assertNotEqual(base, imp.compute_observation_id(rec2))

    def test_flag_id_is_deterministic_from_observation_id_and_flag(self):
        obs_row = imp.build_observation_row(
            copy.deepcopy(SAMPLE_RECORD_FLAGGED), "NOW"
        )
        rows = imp.build_risk_flag_rows(
            obs_row, copy.deepcopy(SAMPLE_RECORD_FLAGGED), "NOW"
        )
        again = imp.build_risk_flag_rows(
            obs_row, copy.deepcopy(SAMPLE_RECORD_FLAGGED), "NOW"
        )
        self.assertEqual([r["flag_id"] for r in rows],
                         [r["flag_id"] for r in again])
        for r in rows:
            self.assertTrue(r["flag_id"].startswith("flag_"))


# ---------------------------------------------------------------------------
# Risk-flag parsing + severity mapping (no duckdb required)
# ---------------------------------------------------------------------------

class TestRiskFlagMapping(unittest.TestCase):
    def test_parse_flags_handles_none_sentinel_and_pipes(self):
        self.assertEqual(imp.parse_risk_flags("none"), [])
        self.assertEqual(imp.parse_risk_flags(""), [])
        self.assertEqual(imp.parse_risk_flags(None), [])
        self.assertEqual(
            imp.parse_risk_flags("A|B|A"), ["A", "B"]
        )
        self.assertEqual(imp.parse_risk_flags(["X", "Y"]), ["X", "Y"])

    def test_severity_mapping(self):
        self.assertEqual(imp.severity_for("MALFORMED_PAIR_LABEL"), "SEVERE")
        self.assertEqual(imp.severity_for("BLACKLISTED"), "SEVERE")
        self.assertEqual(imp.severity_for("NO_ELIGIBLE_FEE_POOL"), "SEVERE")
        self.assertEqual(imp.severity_for("LOW_LIQUIDITY"), "HIGH")
        self.assertEqual(imp.severity_for("LOW_VOLUME"), "HIGH")
        self.assertEqual(imp.severity_for("DATA_QUALITY_NA"), "HIGH")
        self.assertEqual(imp.severity_for("LOW_DATA_COMPLETENESS"), "HIGH")
        self.assertEqual(imp.severity_for("EXTREME_VOLATILITY"), "INFO")
        self.assertEqual(imp.severity_for("ANYTHING_ELSE"), "INFO")

    def test_risk_flag_rows_carry_correct_severity_and_source(self):
        obs_row = imp.build_observation_row(
            copy.deepcopy(SAMPLE_RECORD_FLAGGED), "NOW"
        )
        rows = imp.build_risk_flag_rows(
            obs_row, copy.deepcopy(SAMPLE_RECORD_FLAGGED), "NOW"
        )
        by_flag = {r["risk_flag"]: r for r in rows}
        self.assertEqual(by_flag["MALFORMED_PAIR_LABEL"]["severity"], "SEVERE")
        self.assertEqual(by_flag["LOW_LIQUIDITY"]["severity"], "HIGH")
        self.assertEqual(by_flag["EXTREME_VOLATILITY"]["severity"], "INFO")
        for r in rows:
            self.assertEqual(r["source"], "strategy_observations_jsonl")


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
            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD])
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--observations-jsonl", str(jsonl)]
                )
            self.assertNotEqual(rc, 0)
            self.assertFalse(db_path.exists(), "must not create the DB")
            self.assertFalse(db_path.parent.exists(), "must not create runtime dir")
            self.assertIn("init_runtime_db.py", err.getvalue())

    def test_missing_jsonl_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            placeholder_db = Path(tmp) / "runtime" / "dlmm.duckdb"
            placeholder_db.parent.mkdir(parents=True, exist_ok=True)
            placeholder_db.write_text("not-a-real-db")
            missing_jsonl = Path(tmp) / "nope.jsonl"
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = imp.main(
                    [
                        "--db-path",
                        str(placeholder_db),
                        "--observations-jsonl",
                        str(missing_jsonl),
                    ]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("Observations JSONL not found", err.getvalue())


# ---------------------------------------------------------------------------
# DB-backed behavior (requires duckdb)
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestImportWithDb(unittest.TestCase):
    def _counts(self, db_path):
        conn = duckdb.connect(str(db_path))
        try:
            obs = conn.execute(
                "SELECT COUNT(*) FROM strategy_observations"
            ).fetchone()[0]
            flags = conn.execute("SELECT COUNT(*) FROM risk_flags").fetchone()[0]
            runs = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
            steps = conn.execute("SELECT COUNT(*) FROM pipeline_steps").fetchone()[0]
            fpe = conn.execute(
                "SELECT COUNT(*) FROM future_position_events"
            ).fetchone()[0]
        finally:
            conn.close()
        return obs, flags, runs, steps, fpe

    def test_dry_run_performs_no_db_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD, SAMPLE_RECORD_FLAGGED])
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--observations-jsonl",
                        str(jsonl),
                        "--dry-run",
                        "--import-risk-flags",
                    ]
                )
            self.assertEqual(rc, 0)
            obs, flags, _, _, _ = self._counts(db_path)
            self.assertEqual(obs, 0, "dry-run must not write strategy_observations")
            self.assertEqual(flags, 0, "dry-run must not write risk_flags")
            self.assertIn("DRY RUN", buf.getvalue())

    def test_valid_jsonl_imports_observation_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD, SAMPLE_RECORD_FLAGGED])
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    ["--db-path", str(db_path), "--observations-jsonl", str(jsonl)]
                )
            self.assertEqual(rc, 0)
            obs, flags, _, _, _ = self._counts(db_path)
            self.assertEqual(obs, 2)
            self.assertEqual(flags, 0, "risk_flags not imported without flag flag")

    def test_observed_at_alias_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD])
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--observations-jsonl", str(jsonl)]
                )
            conn = duckdb.connect(str(db_path))
            try:
                observed_at = conn.execute(
                    "SELECT observed_at FROM strategy_observations LIMIT 1"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(observed_at, "2026-06-30T01:32:46+00:00")

    def test_duplicate_observation_id_fails_without_upsert(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD])
            with redirect_stdout(io.StringIO()):
                rc1 = imp.main(
                    ["--db-path", str(db_path), "--observations-jsonl", str(jsonl)]
                )
            self.assertEqual(rc1, 0)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc2 = imp.main(
                    ["--db-path", str(db_path), "--observations-jsonl", str(jsonl)]
                )
            self.assertNotEqual(rc2, 0)
            self.assertIn("already exists", err.getvalue())
            obs, _, _, _, _ = self._counts(db_path)
            self.assertEqual(obs, 1, "failed duplicate must not add a row")

    def test_duplicate_observation_id_succeeds_with_upsert(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)

            # Import an unrelated record that must remain untouched.
            other_jsonl = _write_jsonl(
                tmp, [SAMPLE_RECORD_FLAGGED], name="other.jsonl"
            )
            with redirect_stdout(io.StringIO()):
                imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--observations-jsonl",
                        str(other_jsonl),
                    ]
                )

            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD])
            with redirect_stdout(io.StringIO()):
                imp.main(
                    ["--db-path", str(db_path), "--observations-jsonl", str(jsonl)]
                )

            # Re-import the same record with a changed pass-through field via upsert.
            modified = copy.deepcopy(SAMPLE_RECORD)
            modified["pair_status_v2"] = "WATCHLIST"
            modified_jsonl = _write_jsonl(tmp, [modified], name="mod.jsonl")
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--observations-jsonl",
                        str(modified_jsonl),
                        "--upsert",
                    ]
                )
            self.assertEqual(rc, 0)

            conn = duckdb.connect(str(db_path))
            try:
                total = conn.execute(
                    "SELECT COUNT(*) FROM strategy_observations"
                ).fetchone()[0]
                status = conn.execute(
                    "SELECT pair_status_v2 FROM strategy_observations "
                    "WHERE pair_key = ?",
                    [SAMPLE_RECORD["pair_key"]],
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(total, 2, "upsert must not duplicate or drop rows")
            self.assertEqual(status, "WATCHLIST", "upsert must replace the row")

    def test_import_risk_flags_imports_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD_FLAGGED])
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--observations-jsonl",
                        str(jsonl),
                        "--import-risk-flags",
                    ]
                )
            self.assertEqual(rc, 0)
            obs, flags, _, _, _ = self._counts(db_path)
            self.assertEqual(obs, 1)
            self.assertEqual(flags, 3, "three distinct risk flags expected")

            conn = duckdb.connect(str(db_path))
            try:
                sev = dict(
                    conn.execute(
                        "SELECT risk_flag, severity FROM risk_flags"
                    ).fetchall()
                )
            finally:
                conn.close()
            self.assertEqual(sev["MALFORMED_PAIR_LABEL"], "SEVERE")
            self.assertEqual(sev["LOW_LIQUIDITY"], "HIGH")
            self.assertEqual(sev["EXTREME_VOLATILITY"], "INFO")

    def test_upsert_risk_flags_replaces_only_affected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)

            # Unrelated flagged record imported with risk flags.
            other_jsonl = _write_jsonl(
                tmp, [SAMPLE_RECORD_FLAGGED], name="other.jsonl"
            )
            with redirect_stdout(io.StringIO()):
                imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--observations-jsonl",
                        str(other_jsonl),
                        "--import-risk-flags",
                    ]
                )
            _, flags_before, _, _, _ = self._counts(db_path)
            self.assertEqual(flags_before, 3)

            # A different record (clean) imported then upserted with one flag.
            rec = copy.deepcopy(SAMPLE_RECORD)
            rec["risk_flags"] = "LOW_VOLUME"
            jsonl = _write_jsonl(tmp, [rec])
            with redirect_stdout(io.StringIO()):
                imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--observations-jsonl",
                        str(jsonl),
                        "--upsert",
                        "--import-risk-flags",
                    ]
                )
            # Re-import same record with two flags via upsert.
            rec2 = copy.deepcopy(SAMPLE_RECORD)
            rec2["risk_flags"] = "LOW_VOLUME|NO_ELIGIBLE_FEE_POOL"
            jsonl2 = _write_jsonl(tmp, [rec2], name="rec2.jsonl")
            with redirect_stdout(io.StringIO()):
                imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--observations-jsonl",
                        str(jsonl2),
                        "--upsert",
                        "--import-risk-flags",
                    ]
                )
            conn = duckdb.connect(str(db_path))
            try:
                other_flags = conn.execute(
                    "SELECT COUNT(*) FROM risk_flags WHERE pair_key = ?",
                    [SAMPLE_RECORD_FLAGGED["pair_key"]],
                ).fetchone()[0]
                rec_flags = sorted(
                    r[0]
                    for r in conn.execute(
                        "SELECT risk_flag FROM risk_flags WHERE pair_key = ?",
                        [SAMPLE_RECORD["pair_key"]],
                    ).fetchall()
                )
            finally:
                conn.close()
            self.assertEqual(other_flags, 3, "unrelated flags untouched")
            self.assertEqual(rec_flags, ["LOW_VOLUME", "NO_ELIGIBLE_FEE_POOL"])

    def test_importer_does_not_write_other_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD, SAMPLE_RECORD_FLAGGED])
            with redirect_stdout(io.StringIO()):
                imp.main(
                    [
                        "--db-path",
                        str(db_path),
                        "--observations-jsonl",
                        str(jsonl),
                        "--import-risk-flags",
                    ]
                )
            _, _, runs, steps, fpe = self._counts(db_path)
            self.assertEqual(runs, 0, "must not write pipeline_runs")
            self.assertEqual(steps, 0, "must not write pipeline_steps")
            self.assertEqual(fpe, 0, "must not write future_position_events")

    def test_invalid_db_safety_phase_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            # Corrupt the DB safety_phase directly.
            conn = duckdb.connect(str(db_path))
            conn.execute(
                "UPDATE runtime_schema_meta SET safety_phase = ?",
                ["LIVE_ELIGIBLE_CORE"],
            )
            conn.close()
            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD])
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--observations-jsonl", str(jsonl)]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("safety_phase", err.getvalue())
            obs, _, _, _, _ = self._counts(db_path)
            self.assertEqual(obs, 0, "invalid safety_phase must not write")

    def test_missing_required_field_fails_via_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            bad = copy.deepcopy(SAMPLE_RECORD)
            del bad["strategy_class_v2"]
            jsonl = _write_jsonl(tmp, [bad])
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--observations-jsonl", str(jsonl)]
                )
            self.assertNotEqual(rc, 0)
            obs, _, _, _, _ = self._counts(db_path)
            self.assertEqual(obs, 0)

    def test_missing_schema_table_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "empty.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(db_path))
            conn.close()
            jsonl = _write_jsonl(tmp, [SAMPLE_RECORD])
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    ["--db-path", str(db_path), "--observations-jsonl", str(jsonl)]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("init_runtime_db.py", err.getvalue())


if __name__ == "__main__":
    unittest.main()
