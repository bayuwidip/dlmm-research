#!/usr/bin/env python3
"""
Runtime DuckDB Storage Skeleton v0.1

Purpose:
- Initialize a lightweight local DuckDB schema for FUTURE VPS runtime history.
- This is a storage skeleton ONLY.

This script:
- Does NOT integrate with the runner (no runner integration yet).
- Does NOT write observations automatically.
- Does NOT change pipeline behavior.
- Does NOT execute the pipeline, spawn child processes, or access the network.
- Does NOT schedule anything and does NOT talk to Telegram.

This is NOT and never enables:
- wallet creation / import / management
- private key handling
- transaction signing
- swap execution
- LP add / remove
- rebalance
- live execution
- any LIVE_ELIGIBLE_* capability

It only creates empty tables and a schema-metadata row. It holds history only;
it never holds wallet material, private keys, or any secret, and it confers no
execution capability (see docs/target_architecture.md §7 — SSOT / Storage Layer).
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

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

# Exact message required when the optional duckdb dependency is missing.
DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)

SCHEMA_NAME = "runtime_storage"
SCHEMA_VERSION = 1
SCHEMA_NOTES = (
    "Runtime DuckDB storage skeleton v0.1. Schema-only; not wired to the runner. "
    "History only; no wallet, key, signing, swap, LP, rebalance, or live execution."
)

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

# Ordered so the printed schema and creation order are deterministic.
SCHEMA_STATEMENTS: "OrderedDict[str, str]" = OrderedDict()

SCHEMA_STATEMENTS["runtime_schema_meta"] = """
CREATE TABLE IF NOT EXISTS runtime_schema_meta (
    schema_name    TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    safety_phase   TEXT NOT NULL,
    notes          TEXT NOT NULL
);
""".strip()

SCHEMA_STATEMENTS["pipeline_runs"] = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id                  TEXT PRIMARY KEY,
    started_at              TEXT NOT NULL,
    ended_at                TEXT,
    duration_seconds        DOUBLE,
    status                  TEXT NOT NULL,
    safety_phase            TEXT NOT NULL,
    continue_on_ohlcv_error BOOLEAN NOT NULL,
    stale_lock_replaced     BOOLEAN NOT NULL,
    log_file                TEXT,
    summary_json_file       TEXT,
    summary_md_file         TEXT,
    created_at              TEXT NOT NULL
);
""".strip()

SCHEMA_STATEMENTS["pipeline_steps"] = """
CREATE TABLE IF NOT EXISTS pipeline_steps (
    run_id           TEXT NOT NULL,
    step_index       INTEGER NOT NULL,
    step_name        TEXT NOT NULL,
    command          TEXT NOT NULL,
    started_at       TEXT,
    ended_at         TEXT,
    duration_seconds DOUBLE,
    exit_code        INTEGER,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    PRIMARY KEY (run_id, step_index)
);
""".strip()

SCHEMA_STATEMENTS["strategy_observations"] = """
CREATE TABLE IF NOT EXISTS strategy_observations (
    observation_id              TEXT PRIMARY KEY,
    run_id                      TEXT,
    observed_at                 TEXT NOT NULL,
    pair_key                    TEXT NOT NULL,
    pair_label                  TEXT,
    representative_pool_address TEXT,
    strategy_class_v2           TEXT NOT NULL,
    pair_status_v2              TEXT,
    test_lane                   TEXT,
    live_eligibility            TEXT,
    required_capability         TEXT,
    risk_flag_count             INTEGER,
    risk_flags                  TEXT,
    observation_ready           BOOLEAN NOT NULL,
    readiness_reason            TEXT,
    created_at                  TEXT NOT NULL
);
""".strip()

SCHEMA_STATEMENTS["risk_flags"] = """
CREATE TABLE IF NOT EXISTS risk_flags (
    flag_id     TEXT PRIMARY KEY,
    observed_at TEXT NOT NULL,
    pair_key    TEXT,
    pair_label  TEXT,
    risk_flag   TEXT NOT NULL,
    severity    TEXT NOT NULL,
    source      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
""".strip()

SCHEMA_STATEMENTS["risk_decisions"] = """
CREATE TABLE IF NOT EXISTS risk_decisions (
    risk_decision_id        TEXT PRIMARY KEY,
    imported_at             TIMESTAMP,
    pair_key                TEXT,
    pair_label              TEXT,
    strategy_class_v2       TEXT,
    pair_status_v2          TEXT,
    test_lane               TEXT,
    live_eligibility        TEXT,
    required_capability     TEXT,
    risk_flag_count         INTEGER,
    risk_flags              TEXT,
    risk_decision           TEXT,
    risk_action             TEXT,
    max_allowed_action      TEXT,
    risk_blockers           TEXT,
    risk_warnings           TEXT,
    risk_required_next_step TEXT,
    risk_policy_reason      TEXT,
    safety_phase            TEXT,
    source_csv              TEXT
);
""".strip()

SCHEMA_STATEMENTS["fee_tvl_observations"] = """
CREATE TABLE IF NOT EXISTS fee_tvl_observations (
    observation_id          TEXT PRIMARY KEY,
    run_id                  TEXT NOT NULL,
    observed_at             TEXT NOT NULL,
    pair_key                TEXT NOT NULL,
    pair_label              TEXT,
    pool_address            TEXT,
    fees_active_tvl_pct     DOUBLE,
    volume_24h_usd          DOUBLE,
    active_tvl_usd          DOUBLE,
    source_row_date         TEXT,
    safety_phase            TEXT NOT NULL
);
""".strip()

# Reserved for FUTURE paper/live phases. Schema-only. The current pipeline must
# NOT write to this table. Its presence here is a placeholder, not a capability.
SCHEMA_STATEMENTS["future_position_events"] = """
CREATE TABLE IF NOT EXISTS future_position_events (
    event_id           TEXT PRIMARY KEY,
    event_time         TEXT NOT NULL,
    phase              TEXT NOT NULL,
    position_id        TEXT,
    pair_key           TEXT,
    pair_label         TEXT,
    event_type         TEXT NOT NULL,
    event_payload_json TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
""".strip()

REQUIRED_TABLES = tuple(SCHEMA_STATEMENTS.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def build_schema_sql() -> str:
    """Build the full SQL schema as a single string, prefixed by the safety banner.

    The SAFETY_BANNER is embedded as SQL comments so the schema text itself
    carries the hard safety boundary.
    """
    banner = "\n".join("-- " + line for line in SAFETY_BANNER.splitlines())
    header = (
        "-- Runtime DuckDB Storage Skeleton v0.1\n"
        f"-- safety_phase: {SAFETY_PHASE}\n"
        f"-- schema_name: {SCHEMA_NAME}  schema_version: {SCHEMA_VERSION}\n"
        "--\n"
        + banner
    )
    parts = [header]
    parts.extend(SCHEMA_STATEMENTS.values())
    return "\n\n".join(parts) + "\n"


def require_duckdb():
    """Import and return the duckdb module, or raise a clear error.

    Kept as a single chokepoint so the missing-dependency path is testable by
    monkeypatching this function. Dependencies are never auto-installed.
    """
    try:
        import duckdb  # noqa: PLC0415  (deferred import is intentional)
    except ImportError as exc:
        raise RuntimeError(DUCKDB_MISSING_MSG) from exc
    return duckdb


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def create_schema(conn) -> None:
    """Run idempotent CREATE TABLE IF NOT EXISTS statements. Never drops data."""
    for statement in SCHEMA_STATEMENTS.values():
        conn.execute(statement)


def upsert_schema_meta(conn, now: str) -> None:
    """Insert the schema-metadata row, or update it in place if already present.

    This never deletes rows from any table; it only writes/refreshes the single
    runtime_schema_meta marker row.
    """
    existing = conn.execute(
        "SELECT created_at FROM runtime_schema_meta WHERE schema_name = ?",
        [SCHEMA_NAME],
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO runtime_schema_meta "
            "(schema_name, schema_version, created_at, updated_at, safety_phase, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [SCHEMA_NAME, SCHEMA_VERSION, now, now, SAFETY_PHASE, SCHEMA_NOTES],
        )
    else:
        conn.execute(
            "UPDATE runtime_schema_meta "
            "SET schema_version = ?, updated_at = ?, safety_phase = ?, notes = ? "
            "WHERE schema_name = ?",
            [SCHEMA_VERSION, now, SAFETY_PHASE, SCHEMA_NOTES, SCHEMA_NAME],
        )


def list_tables(conn):
    """Return the set of table names in the main schema of the connection."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


def validate_schema(conn) -> None:
    """Validate the initialized database. Raises RuntimeError on any failure."""
    present = list_tables(conn)
    missing = [name for name in REQUIRED_TABLES if name not in present]
    if missing:
        raise RuntimeError(f"Schema validation failed: missing tables: {missing}")

    meta = conn.execute(
        "SELECT schema_name, schema_version, safety_phase "
        "FROM runtime_schema_meta WHERE schema_name = ?",
        [SCHEMA_NAME],
    ).fetchone()
    if meta is None:
        raise RuntimeError(
            f"Schema validation failed: no runtime_schema_meta row for '{SCHEMA_NAME}'."
        )

    name, version, phase = meta
    if name != SCHEMA_NAME:
        raise RuntimeError(
            f"Schema validation failed: schema_name '{name}' != '{SCHEMA_NAME}'."
        )
    if version != SCHEMA_VERSION:
        raise RuntimeError(
            f"Schema validation failed: schema_version {version} != {SCHEMA_VERSION}."
        )
    if phase != SAFETY_PHASE:
        raise RuntimeError(
            f"Schema validation failed: safety_phase '{phase}' != '{SAFETY_PHASE}'."
        )


def init_db(db_path: str, force: bool = False):
    """Create/open the DuckDB database and initialize the schema idempotently.

    `force` only guarantees the idempotent CREATE TABLE IF NOT EXISTS statements
    are (re-)run; it never drops or resets data. Returns the resolved Path.
    """
    duckdb = require_duckdb()

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(path))
    try:
        create_schema(conn)
        upsert_schema_meta(conn, utc_now_iso())
        validate_schema(conn)
    finally:
        conn.close()

    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Runtime DuckDB Storage Skeleton v0.1 — initialize a local DuckDB "
            "schema for future VPS runtime history. Schema-only; no runner "
            "integration, no execution, no wallet/signing/swap/LP/rebalance/live."
        )
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to the DuckDB database file (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created; create no runtime directory or db file.",
    )
    parser.add_argument(
        "--print-schema",
        action="store_true",
        help="Print the SQL schema to stdout.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run idempotent CREATE TABLE IF NOT EXISTS statements; never drops data.",
    )
    return parser.parse_args(argv)


def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  RUNTIME DUCKDB STORAGE SKELETON v0.1")
    print("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        print(f"  {line}")
    print("------------------------------------------------------------")


def main(argv=None) -> int:
    args = parse_args(argv)

    print_safety_banner()

    if args.print_schema:
        print(build_schema_sql())

    if args.dry_run:
        print("DRY RUN — no runtime directory or database file will be created.")
        print(f"  Would create db path : {args.db_path}")
        print(f"  Would create parent  : {Path(args.db_path).parent}")
        print(f"  Schema name          : {SCHEMA_NAME}")
        print(f"  Schema version       : {SCHEMA_VERSION}")
        print(f"  Safety phase         : {SAFETY_PHASE}")
        print("  Would create tables  :")
        for name in REQUIRED_TABLES:
            print(f"    - {name}")
        print("DRY RUN COMPLETE — nothing written.")
        return 0

    path = init_db(args.db_path, force=args.force)

    print(f"  Database     : {path}")
    print(f"  Schema name  : {SCHEMA_NAME}")
    print(f"  Version      : {SCHEMA_VERSION}")
    print(f"  Force        : {args.force}")
    print(f"  Tables       : {', '.join(REQUIRED_TABLES)}")
    print("  RESULT: SCHEMA INITIALIZED AND VALIDATED")
    print("  NOTE  : Storage skeleton only. Not wired to the runner. No execution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
