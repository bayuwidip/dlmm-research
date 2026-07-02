#!/usr/bin/env python3
"""Tests for scripts/import_fee_tvl_observations_to_db.py."""

import csv
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
IMPORTER_PATH = REPO_ROOT / "scripts" / "import_fee_tvl_observations_to_db.py"
INIT_PATH = REPO_ROOT / "scripts" / "init_runtime_db.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


imp = _load_module("import_fee_tvl_observations_to_db", IMPORTER_PATH)
idb = _load_module("init_runtime_db", INIT_PATH)

try:
    import duckdb  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


def _write_pools_csv(directory, rows=None):
    if rows is None:
        rows = [
            {
                "tanggal": "2026-06-29",
                "pool": "POOL_LOW",
                "pair": "AAA-BBB",
                "fees_active_tvl_pct": "1.2",
                "volume_24h_usd": "1000",
                "active_tvl_usd": "5000",
            },
            {
                "tanggal": "2026-06-29",
                "pool": "POOL_HIGH",
                "pair": "AAA-BBB",
                "fees_active_tvl_pct": "2.5",
                "volume_24h_usd": "900",
                "active_tvl_usd": "4000",
            },
            {
                "tanggal": "2026-06-29",
                "pool": "POOL_CCC",
                "pair": "CCC-DDD",
                "fees_active_tvl_pct": "0.7",
                "volume_24h_usd": "2000",
                "active_tvl_usd": "8000",
            },
        ]
    path = Path(directory) / "data" / "pools_watchlist.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=imp.REQUIRED_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _init_db(directory):
    db_path = Path(directory) / "runtime" / "dlmm.duckdb"
    idb.init_db(str(db_path))
    return db_path


class TestSafetyConstants(unittest.TestCase):
    def test_safety_phase_exact(self):
        self.assertEqual(
            imp.SAFETY_PHASE,
            "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY",
        )

    def test_forbidden_write_tables_listed(self):
        self.assertEqual(
            set(imp.FORBIDDEN_WRITE_TABLES),
            {
                "pipeline_runs",
                "pipeline_steps",
                "strategy_observations",
                "risk_flags",
                "risk_decisions",
                "future_position_events",
            },
        )


class TestCliGuards(unittest.TestCase):
    def test_refuses_without_write_db(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = imp.main(["--run-id", "run-1"])
        self.assertEqual(rc, 2)
        self.assertIn("--write-db is required", err.getvalue())

    def test_missing_db_does_not_create_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            csv_path = _write_pools_csv(tmp)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    [
                        "--write-db",
                        str(db_path),
                        "--pools-watchlist-csv",
                        str(csv_path),
                        "--run-id",
                        "run-1",
                    ]
                )
            self.assertEqual(rc, 2)
            self.assertFalse(db_path.exists())
            self.assertFalse(db_path.parent.exists())
            self.assertIn("init_runtime_db.py", err.getvalue())

    def test_missing_csv_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime" / "dlmm.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_text("placeholder")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    [
                        "--write-db",
                        str(db_path),
                        "--pools-watchlist-csv",
                        str(Path(tmp) / "missing.csv"),
                        "--run-id",
                        "run-1",
                    ]
                )
            self.assertEqual(rc, 2)
            self.assertIn("Pools watchlist CSV not found", err.getvalue())


class TestPlanning(unittest.TestCase):
    def test_builds_one_row_per_pair_with_best_fee_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = _write_pools_csv(tmp)
            source_rows = imp.load_pools_watchlist(str(csv_path))
            rows = imp.build_observation_rows(
                source_rows,
                run_id="run-1",
                observed_at="2026-07-01T00:00:00+00:00",
            )
        self.assertEqual(len(rows), 2)
        by_pair = {row["pair_key"]: row for row in rows}
        self.assertEqual(by_pair["AAA-BBB"]["pool_address"], "POOL_HIGH")
        self.assertEqual(by_pair["AAA-BBB"]["fees_active_tvl_pct"], 2.5)
        self.assertEqual(by_pair["AAA-BBB"]["source_row_date"], "2026-06-29")
        self.assertEqual(by_pair["AAA-BBB"]["safety_phase"], imp.SAFETY_PHASE)

    def test_observation_id_is_idempotent_per_run_id_pair(self):
        source_rows = [
            {
                "pair_key": "AAA-BBB",
                "pair_label": "AAA-BBB",
                "pool_address": "POOL",
                "fees_active_tvl_pct": 1.0,
                "volume_24h_usd": 2.0,
                "active_tvl_usd": 3.0,
                "source_row_date": "2026-06-29",
            }
        ]
        a = imp.build_observation_rows(source_rows, "run-1", "T1")[0]
        b = imp.build_observation_rows(source_rows, "run-1", "T2")[0]
        c = imp.build_observation_rows(source_rows, "run-2", "T1")[0]
        self.assertEqual(a["observation_id"], b["observation_id"])
        self.assertNotEqual(a["observation_id"], c["observation_id"])


@unittest.skipUnless(HAS_DUCKDB, "duckdb not installed")
class TestImportWithDb(unittest.TestCase):
    def _counts(self, db_path):
        conn = duckdb.connect(str(db_path))
        try:
            return {
                "fee": conn.execute(
                    "SELECT COUNT(*) FROM fee_tvl_observations"
                ).fetchone()[0],
                "runs": conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0],
                "steps": conn.execute(
                    "SELECT COUNT(*) FROM pipeline_steps"
                ).fetchone()[0],
                "obs": conn.execute(
                    "SELECT COUNT(*) FROM strategy_observations"
                ).fetchone()[0],
                "risk_decisions": conn.execute(
                    "SELECT COUNT(*) FROM risk_decisions"
                ).fetchone()[0],
                "fpe": conn.execute(
                    "SELECT COUNT(*) FROM future_position_events"
                ).fetchone()[0],
            }
        finally:
            conn.close()

    def test_import_appends_one_row_per_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_pools_csv(tmp)
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    [
                        "--write-db",
                        str(db_path),
                        "--pools-watchlist-csv",
                        str(csv_path),
                        "--run-id",
                        "run-1",
                    ]
                )
            self.assertEqual(rc, 0)
            counts = self._counts(db_path)
            self.assertEqual(counts["fee"], 2)
            self.assertEqual(counts["runs"], 0)
            self.assertEqual(counts["steps"], 0)
            self.assertEqual(counts["obs"], 0)
            self.assertEqual(counts["risk_decisions"], 0)
            self.assertEqual(counts["fpe"], 0)

    def test_reimport_same_run_id_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_pools_csv(tmp)
            args = [
                "--write-db",
                str(db_path),
                "--pools-watchlist-csv",
                str(csv_path),
                "--run-id",
                "run-1",
            ]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(imp.main(args), 0)
                self.assertEqual(imp.main(args), 0)
            self.assertEqual(self._counts(db_path)["fee"], 2)

            args[-1] = "run-2"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(imp.main(args), 0)
            self.assertEqual(self._counts(db_path)["fee"], 4)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            csv_path = _write_pools_csv(tmp)
            with redirect_stdout(io.StringIO()):
                rc = imp.main(
                    [
                        "--write-db",
                        str(db_path),
                        "--pools-watchlist-csv",
                        str(csv_path),
                        "--run-id",
                        "run-1",
                        "--dry-run",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(self._counts(db_path)["fee"], 0)

    def test_invalid_db_safety_phase_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _init_db(tmp)
            conn = duckdb.connect(str(db_path))
            conn.execute(
                "UPDATE runtime_schema_meta SET safety_phase = ?",
                ["LIVE_ELIGIBLE_CORE"],
            )
            conn.close()
            csv_path = _write_pools_csv(tmp)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = imp.main(
                    [
                        "--write-db",
                        str(db_path),
                        "--pools-watchlist-csv",
                        str(csv_path),
                        "--run-id",
                        "run-1",
                    ]
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("safety_phase", err.getvalue())
            self.assertEqual(self._counts(db_path)["fee"], 0)


if __name__ == "__main__":
    unittest.main()
