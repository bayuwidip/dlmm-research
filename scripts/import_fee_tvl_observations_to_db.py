#!/usr/bin/env python3
"""
Fee/TVL Observations Importer to DuckDB v0.1

Purpose:
- Import fee/TVL observations from an EXISTING data/pools_watchlist.csv into
  the runtime DuckDB database as append-only history for later calibration work.

This is an OFFLINE / IMPORT tool ONLY. It reads an existing CSV and writes one
fee_tvl_observations row per pair for the provided run_id. It requires an
existing, initialized DuckDB and refuses to run unless --write-db is passed.

This script:
- Does NOT run the pipeline.
- Does NOT spawn child processes.
- Does NOT access the network.
- Does NOT create the database (it requires an existing, initialized DB).
- Does NOT create data/pools_watchlist.csv (it requires an existing CSV).
- Writes ONLY to fee_tvl_observations.

It deliberately does NOT write:
- pipeline_runs
- pipeline_steps
- strategy_observations
- risk_flags
- risk_decisions
- future_position_events

This is NOT and never enables wallet, private key handling, signing, swaps, LP
actions, rebalancing, live execution, signals, or paper position creation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path


SAFETY_PHASE = "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY"

SAFETY_BANNER = "\n".join(
    [
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
)

DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)

DEFAULT_POOLS_WATCHLIST_CSV = "data/pools_watchlist.csv"
OBSERVATION_ID_PREFIX = "fee_tvl_"

REQUIRED_SCHEMA_TABLES = (
    "runtime_schema_meta",
    "fee_tvl_observations",
)

FORBIDDEN_WRITE_TABLES = (
    "pipeline_runs",
    "pipeline_steps",
    "strategy_observations",
    "risk_flags",
    "risk_decisions",
    "future_position_events",
)

REQUIRED_CSV_COLUMNS = (
    "tanggal",
    "pool",
    "pair",
    "fees_active_tvl_pct",
    "volume_24h_usd",
    "active_tvl_usd",
)


class FeeTvlValidationError(ValueError):
    """Raised when the pools watchlist CSV is missing columns or malformed."""


class SafetyPhaseError(ValueError):
    """Raised when the DB safety_phase does not match the required phase."""


class SchemaError(RuntimeError):
    """Raised when the target DB is missing one of the required schema tables."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_duckdb():
    try:
        import duckdb  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(DUCKDB_MISSING_MSG) from exc
    return duckdb


def sha256_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"


def db_exists(db_path: str) -> bool:
    return Path(db_path).is_file()


def csv_exists(csv_path: str) -> bool:
    return Path(csv_path).is_file()


def connect_db(db_path: str):
    duckdb = require_duckdb()
    return duckdb.connect(str(db_path))


def list_tables(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


def validate_schema_tables(conn) -> None:
    present = list_tables(conn)
    missing = [name for name in REQUIRED_SCHEMA_TABLES if name not in present]
    if missing:
        raise SchemaError(
            "Target DB is missing required table(s): "
            f"{missing}. Run scripts/init_runtime_db.py first."
        )


def get_db_safety_phase(conn):
    row = conn.execute(
        "SELECT safety_phase FROM runtime_schema_meta ORDER BY schema_name LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def validate_db_safety_phase(conn) -> None:
    phase = get_db_safety_phase(conn)
    if phase != SAFETY_PHASE:
        raise SafetyPhaseError(
            f"DB safety_phase '{phase}' != required '{SAFETY_PHASE}'. "
            "Refusing to import."
        )


def _coerce_optional_float(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _sort_key_for_best_fee(row: dict):
    fee = row.get("fees_active_tvl_pct")
    volume = row.get("volume_24h_usd")
    active_tvl = row.get("active_tvl_usd")
    return (
        fee if fee is not None else float("-inf"),
        volume if volume is not None else float("-inf"),
        active_tvl if active_tvl is not None else float("-inf"),
        str(row.get("pool_address") or ""),
    )


def load_pools_watchlist(csv_path: str) -> list:
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Pools watchlist CSV not found: {csv_path}")

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        missing = [c for c in REQUIRED_CSV_COLUMNS if c not in header]
        if missing:
            raise FeeTvlValidationError(
                f"Pools watchlist CSV missing required column(s): {missing}"
            )
        rows = [dict(row) for row in reader]

    normalized = []
    for index, row in enumerate(rows):
        pair_label = (row.get("pair") or "").strip()
        if not pair_label:
            raise FeeTvlValidationError(f"Row #{index}: pair is required.")
        pool_address = (row.get("pool") or "").strip()
        if not pool_address:
            raise FeeTvlValidationError(f"Row #{index}: pool is required.")
        normalized.append(
            {
                "pair_key": pair_label,
                "pair_label": pair_label,
                "pool_address": pool_address,
                "fees_active_tvl_pct": _coerce_optional_float(
                    row.get("fees_active_tvl_pct")
                ),
                "volume_24h_usd": _coerce_optional_float(row.get("volume_24h_usd")),
                "active_tvl_usd": _coerce_optional_float(row.get("active_tvl_usd")),
                "source_row_date": (row.get("tanggal") or "").strip(),
            }
        )
    return normalized


def build_observation_rows(source_rows: list, run_id: str, observed_at: str) -> list:
    """Return one deterministic fee/TVL observation row per pair.

    pools_watchlist.csv is pool-level legacy audit data, so multiple rows can
    share a pair label. For pair-level history, keep the row with the strongest
    available fee/TVL metric, then volume, then active TVL, with pool address as
    a deterministic final tie-breaker.
    """
    best_by_pair = {}
    for row in source_rows:
        pair_key = row["pair_key"]
        current = best_by_pair.get(pair_key)
        if current is None or _sort_key_for_best_fee(row) > _sort_key_for_best_fee(current):
            best_by_pair[pair_key] = row

    out = []
    for pair_key in sorted(best_by_pair):
        row = best_by_pair[pair_key]
        obs_id = sha256_id(OBSERVATION_ID_PREFIX, run_id, pair_key)
        out.append(
            {
                "observation_id": obs_id,
                "run_id": run_id,
                "observed_at": observed_at,
                "pair_key": pair_key,
                "pair_label": row["pair_label"],
                "pool_address": row["pool_address"],
                "fees_active_tvl_pct": row["fees_active_tvl_pct"],
                "volume_24h_usd": row["volume_24h_usd"],
                "active_tvl_usd": row["active_tvl_usd"],
                "source_row_date": row["source_row_date"],
                "safety_phase": SAFETY_PHASE,
            }
        )
    return out


def observation_exists(conn, observation_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM fee_tvl_observations WHERE observation_id = ? LIMIT 1",
        [observation_id],
    ).fetchone()
    return row is not None


def insert_observation_row(conn, row: dict) -> None:
    conn.execute(
        "INSERT INTO fee_tvl_observations "
        "(observation_id, run_id, observed_at, pair_key, pair_label, "
        "pool_address, fees_active_tvl_pct, volume_24h_usd, active_tvl_usd, "
        "source_row_date, safety_phase) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            row["observation_id"],
            row["run_id"],
            row["observed_at"],
            row["pair_key"],
            row["pair_label"],
            row["pool_address"],
            row["fees_active_tvl_pct"],
            row["volume_24h_usd"],
            row["active_tvl_usd"],
            row["source_row_date"],
            row["safety_phase"],
        ],
    )


def import_fee_tvl_observations(conn, rows: list) -> dict:
    """Append new rows, skipping rows already present for the same run_id/pair."""
    written = 0
    skipped_existing = 0
    for row in rows:
        if observation_exists(conn, row["observation_id"]):
            skipped_existing += 1
            continue
        insert_observation_row(conn, row)
        written += 1
    return {"rows_written": written, "rows_skipped_existing": skipped_existing}


def run_import(
    db_path: str,
    pools_watchlist_csv: str,
    run_id: str,
    dry_run: bool,
) -> int:
    if not db_exists(db_path):
        print(
            "DuckDB database not found. Run scripts/init_runtime_db.py first.\n"
            f"  (looked for: {db_path})",
            file=sys.stderr,
        )
        return 2

    if not csv_exists(pools_watchlist_csv):
        print(
            f"ERROR: Pools watchlist CSV not found: {pools_watchlist_csv}\n"
            "This importer does not create the watchlist file.",
            file=sys.stderr,
        )
        return 2

    now = utc_now_iso()
    try:
        source_rows = load_pools_watchlist(pools_watchlist_csv)
        rows = build_observation_rows(source_rows, run_id=run_id, observed_at=now)
    except (FileNotFoundError, FeeTvlValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        conn = connect_db(db_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    try:
        try:
            validate_schema_tables(conn)
            validate_db_safety_phase(conn)
        except (SchemaError, SafetyPhaseError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        if dry_run:
            print("DRY RUN — no database writes will be performed.")
            print(f"  pools watchlist csv    : {pools_watchlist_csv}")
            print(f"  source rows read       : {len(source_rows)}")
            print(f"  run_id                 : {run_id}")
            print(f"  fee/TVL rows to import : {len(rows)}")
            print("  writes only to         : fee_tvl_observations")
            print(f"  never writes to        : {', '.join(FORBIDDEN_WRITE_TABLES)}")
            print("DRY RUN COMPLETE — nothing written.")
            return 0

        result = import_fee_tvl_observations(conn, rows)
        print(
            f"Imported {result['rows_written']} fee_tvl_observations row(s); "
            f"skipped {result['rows_skipped_existing']} existing row(s)."
        )
        print("Wrote only to fee_tvl_observations.")
        return 0
    finally:
        conn.close()


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fee/TVL Observations Importer to DuckDB v0.1 — import existing "
            "data/pools_watchlist.csv into an existing runtime DuckDB. Requires "
            "--write-db. Writes only fee_tvl_observations; never writes "
            "future_position_events."
        )
    )
    parser.add_argument(
        "--write-db",
        default=None,
        metavar="PATH",
        help="Path to an EXISTING initialized DuckDB database. Required.",
    )
    parser.add_argument(
        "--pools-watchlist-csv",
        default=DEFAULT_POOLS_WATCHLIST_CSV,
        help=(
            "Path to pools_watchlist.csv "
            f"(default: {DEFAULT_POOLS_WATCHLIST_CSV})."
        ),
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Current pipeline run_id. Re-running the same run_id is idempotent.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print planned import counts; write nothing.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.write_db:
        print("ERROR: --write-db is required", file=sys.stderr)
        return 2
    return run_import(
        db_path=args.write_db,
        pools_watchlist_csv=args.pools_watchlist_csv,
        run_id=args.run_id,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
