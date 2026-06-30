#!/usr/bin/env python3
"""
Run Summary Importer to DuckDB v0.1

Purpose:
- Import an EXISTING read-only runtime run summary JSON (produced by
  scripts/run_readonly_pipeline.py) into the runtime DuckDB database
  (default: runtime/dlmm.duckdb).

This is an OFFLINE / IMPORT tool ONLY. It is a bookkeeper that copies a summary
file's contents into two history tables and nothing more.

This script:
- Does NOT run the pipeline.
- Does NOT integrate with the runner (no runner integration yet).
- Does NOT spawn child processes.
- Does NOT access the network.
- Does NOT schedule anything (no cron / systemd) and does NOT talk to Telegram.
- Does NOT inspect wallets.
- Does NOT create the database (it requires an existing, initialized DB).
- Writes ONLY to pipeline_runs and pipeline_steps.

It deliberately does NOT write:
- strategy_observations
- risk_flags
- future_position_events

This is NOT and never enables:
- wallet creation / import / management
- private key handling
- transaction signing
- swap execution
- LP add / remove
- rebalance
- live execution
- any LIVE_ELIGIBLE_* capability
- paper / live / execution instructions of any kind

See docs/target_architecture.md §7 (SSOT / Storage Layer) and
docs/project_checkpoint.md §2 (Hard Safety Boundary).
"""

from __future__ import annotations

import argparse
import json
import sys
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

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"

# Tables this importer requires to already exist in the target DB.
REQUIRED_SCHEMA_TABLES = (
    "runtime_schema_meta",
    "pipeline_runs",
    "pipeline_steps",
)

# Required top-level fields in the summary JSON.
REQUIRED_RUN_FIELDS = (
    "run_id",
    "started_at",
    "ended_at",
    "duration_seconds",
    "status",
    "safety_phase",
    "continue_on_ohlcv_error",
    "stale_lock_replaced",
    "log_file",
    "steps",
)

# Required fields in each step object of the summary JSON.
REQUIRED_STEP_FIELDS = (
    "name",
    "command",
    "started_at",
    "ended_at",
    "duration_seconds",
    "exit_code",
    "status",
)

# Tables this importer must NEVER write to in this phase.
FORBIDDEN_WRITE_TABLES = (
    "strategy_observations",
    "risk_flags",
    "future_position_events",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SummaryValidationError(ValueError):
    """Raised when the summary JSON is missing required fields or is malformed."""


class SafetyPhaseError(ValueError):
    """Raised when the summary's safety_phase does not match the required phase."""


class DuplicateRunError(RuntimeError):
    """Raised when a run_id already exists and --upsert was not provided."""


class SchemaError(RuntimeError):
    """Raised when the target DB is missing one of the required schema tables."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


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
# File + JSON loading and validation
# ---------------------------------------------------------------------------

def db_exists(db_path: str) -> bool:
    """Return True only if db_path points to an existing regular file."""
    return Path(db_path).is_file()


def summary_exists(summary_json: str) -> bool:
    """Return True only if summary_json points to an existing regular file."""
    return Path(summary_json).is_file()


def load_summary(summary_json: str) -> dict:
    """Load and parse the summary JSON file.

    Raises FileNotFoundError if the file is missing, SummaryValidationError if
    the JSON is unparseable or is not a JSON object.
    """
    path = Path(summary_json)
    if not path.is_file():
        raise FileNotFoundError(f"Summary JSON not found: {summary_json}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise SummaryValidationError(
            f"Summary JSON is not valid JSON: {summary_json} ({exc})"
        ) from exc
    if not isinstance(data, dict):
        raise SummaryValidationError(
            f"Summary JSON must be a JSON object, got {type(data).__name__}."
        )
    return data


def validate_summary(summary: dict) -> None:
    """Validate required top-level and per-step fields. Raises on any failure."""
    missing = [f for f in REQUIRED_RUN_FIELDS if f not in summary]
    if missing:
        raise SummaryValidationError(
            f"Summary JSON missing required top-level field(s): {missing}"
        )

    steps = summary["steps"]
    if not isinstance(steps, list):
        raise SummaryValidationError(
            f"Summary 'steps' must be a list, got {type(steps).__name__}."
        )

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise SummaryValidationError(
                f"Summary step #{i} must be a JSON object, got {type(step).__name__}."
            )
        step_missing = [f for f in REQUIRED_STEP_FIELDS if f not in step]
        if step_missing:
            raise SummaryValidationError(
                f"Summary step #{i} missing required field(s): {step_missing}"
            )


def validate_safety_phase(summary: dict) -> None:
    """Validate that the summary safety_phase matches the required phase exactly."""
    phase = summary.get("safety_phase")
    if phase != SAFETY_PHASE:
        raise SafetyPhaseError(
            f"Summary safety_phase '{phase}' != required '{SAFETY_PHASE}'. "
            "Refusing to import."
        )


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------

def connect_db(db_path: str):
    """Open an EXISTING DuckDB database for read/write.

    The caller must ensure the file exists; this function never creates the
    database file or its parent directory.
    """
    duckdb = require_duckdb()
    return duckdb.connect(str(db_path))


def list_tables(conn):
    """Return the set of table names in the main schema of the connection."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


def validate_schema_tables(conn) -> None:
    """Verify the required schema tables exist. Raises SchemaError if not."""
    present = list_tables(conn)
    missing = [name for name in REQUIRED_SCHEMA_TABLES if name not in present]
    if missing:
        raise SchemaError(
            "Target DB is missing required table(s): "
            f"{missing}. Run scripts/init_runtime_db.py first."
        )


def run_exists(conn, run_id: str) -> bool:
    """Return True if a pipeline_runs row already exists for run_id."""
    row = conn.execute(
        "SELECT 1 FROM pipeline_runs WHERE run_id = ? LIMIT 1", [run_id]
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Import planning + execution
# ---------------------------------------------------------------------------

def build_run_row(summary: dict, summary_json_path: str, now: str) -> dict:
    """Build the pipeline_runs row dict from a validated summary."""
    return {
        "run_id": summary["run_id"],
        "started_at": summary["started_at"],
        "ended_at": summary["ended_at"],
        "duration_seconds": summary["duration_seconds"],
        "status": summary["status"],
        "safety_phase": summary["safety_phase"],
        "continue_on_ohlcv_error": bool(summary["continue_on_ohlcv_error"]),
        "stale_lock_replaced": bool(summary["stale_lock_replaced"]),
        "log_file": summary["log_file"],
        "summary_json_file": str(summary_json_path),
        # summary_md_file is optional; null when not present in the summary.
        "summary_md_file": summary.get("summary_md_file"),
        "created_at": now,
    }


def build_step_rows(summary: dict, now: str) -> list:
    """Build the pipeline_steps row dicts from a validated summary."""
    rows = []
    for index, step in enumerate(summary["steps"]):
        rows.append(
            {
                "run_id": summary["run_id"],
                "step_index": index,
                "step_name": step["name"],
                "command": step["command"],
                "started_at": step["started_at"],
                "ended_at": step["ended_at"],
                "duration_seconds": step["duration_seconds"],
                "exit_code": step["exit_code"],
                "status": step["status"],
                "created_at": now,
            }
        )
    return rows


def _insert_run_row(conn, row: dict) -> None:
    conn.execute(
        "INSERT INTO pipeline_runs "
        "(run_id, started_at, ended_at, duration_seconds, status, safety_phase, "
        "continue_on_ohlcv_error, stale_lock_replaced, log_file, "
        "summary_json_file, summary_md_file, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            row["run_id"],
            row["started_at"],
            row["ended_at"],
            row["duration_seconds"],
            row["status"],
            row["safety_phase"],
            row["continue_on_ohlcv_error"],
            row["stale_lock_replaced"],
            row["log_file"],
            row["summary_json_file"],
            row["summary_md_file"],
            row["created_at"],
        ],
    )


def _insert_step_rows(conn, rows: list) -> None:
    for row in rows:
        conn.execute(
            "INSERT INTO pipeline_steps "
            "(run_id, step_index, step_name, command, started_at, ended_at, "
            "duration_seconds, exit_code, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                row["run_id"],
                row["step_index"],
                row["step_name"],
                row["command"],
                row["started_at"],
                row["ended_at"],
                row["duration_seconds"],
                row["exit_code"],
                row["status"],
                row["created_at"],
            ],
        )


def import_summary(
    conn,
    summary: dict,
    summary_json_path: str,
    upsert: bool,
    now: "str | None" = None,
) -> dict:
    """Import a validated summary into pipeline_runs and pipeline_steps.

    Writes ONLY to pipeline_runs and pipeline_steps. Never touches
    strategy_observations, risk_flags, or future_position_events.

    If the run_id already exists:
    - without upsert: raises DuplicateRunError (no writes performed).
    - with upsert: idempotently replaces ONLY that run_id's rows (delete the
      existing pipeline_runs row and its pipeline_steps, then re-insert).

    Returns a small dict describing what was written.
    """
    if now is None:
        now = utc_now_iso()

    run_id = summary["run_id"]
    existed = run_exists(conn, run_id)

    if existed and not upsert:
        raise DuplicateRunError(
            f"run_id '{run_id}' already exists in pipeline_runs. "
            "Re-run with --upsert to replace it."
        )

    run_row = build_run_row(summary, summary_json_path, now)
    step_rows = build_step_rows(summary, now)

    if existed and upsert:
        # Replace only this run_id; never affect other run_ids.
        conn.execute("DELETE FROM pipeline_steps WHERE run_id = ?", [run_id])
        conn.execute("DELETE FROM pipeline_runs WHERE run_id = ?", [run_id])

    _insert_run_row(conn, run_row)
    _insert_step_rows(conn, step_rows)

    return {
        "run_id": run_id,
        "replaced": bool(existed and upsert),
        "runs_written": 1,
        "steps_written": len(step_rows),
    }


# ---------------------------------------------------------------------------
# Orchestration (no DB writes happen in dry-run)
# ---------------------------------------------------------------------------

def _print_plan(summary: dict, summary_json_path: str, existed: bool, upsert: bool) -> None:
    print("Would import the following run summary:")
    print(f"  run_id            : {summary['run_id']}")
    print(f"  status            : {summary['status']}")
    print(f"  started_at        : {summary['started_at']}")
    print(f"  ended_at          : {summary['ended_at']}")
    print(f"  safety_phase      : {summary['safety_phase']}")
    print(f"  summary_json_file : {summary_json_path}")
    print(f"  summary_md_file   : {summary.get('summary_md_file')}")
    print(f"  steps             : {len(summary['steps'])}")
    for index, step in enumerate(summary["steps"]):
        print(
            f"    [{index}] {step['name']} | status={step['status']} "
            f"| exit={step['exit_code']}"
        )
    print(f"  run_id exists     : {existed}")
    if existed and not upsert:
        print("  NOTE: run_id already exists; a real import would FAIL "
              "without --upsert.")
    elif existed and upsert:
        print("  NOTE: run_id already exists; --upsert would REPLACE only "
              "this run_id.")
    print("  writes only to    : pipeline_runs, pipeline_steps")
    print(f"  never writes to   : {', '.join(FORBIDDEN_WRITE_TABLES)}")


def run_import(
    db_path: str,
    summary_json: str,
    dry_run: bool,
    upsert: bool,
) -> int:
    """Top-level flow used by the CLI. Returns a process exit code.

    Validates files and JSON, then (unless dry-run) writes ONLY to
    pipeline_runs and pipeline_steps.
    """
    # --- File presence checks (no DB creation ever) ---
    if not db_exists(db_path):
        print(
            f"ERROR: Target DuckDB not found: {db_path}\n"
            "This importer does not create the database. "
            "Run scripts/init_runtime_db.py first.",
            file=sys.stderr,
        )
        return 2

    if not summary_exists(summary_json):
        print(f"ERROR: Summary JSON not found: {summary_json}", file=sys.stderr)
        return 2

    # --- Load + validate JSON (no DB access yet) ---
    try:
        summary = load_summary(summary_json)
        validate_summary(summary)
        validate_safety_phase(summary)
    except (SummaryValidationError, SafetyPhaseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # --- Open DB and validate schema (read for dry-run, write otherwise) ---
    try:
        conn = connect_db(db_path)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    try:
        try:
            validate_schema_tables(conn)
        except SchemaError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        existed = run_exists(conn, summary["run_id"])

        if dry_run:
            print("DRY RUN — no database writes will be performed.")
            _print_plan(summary, summary_json, existed, upsert)
            print("DRY RUN COMPLETE — nothing written.")
            return 0

        try:
            result = import_summary(conn, summary, summary_json, upsert=upsert)
        except DuplicateRunError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        verb = "Replaced" if result["replaced"] else "Imported"
        print(
            f"{verb} run_id '{result['run_id']}': "
            f"{result['runs_written']} pipeline_runs row, "
            f"{result['steps_written']} pipeline_steps rows."
        )
        print("Wrote only to pipeline_runs and pipeline_steps.")
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Summary Importer to DuckDB v0.1 — import an existing read-only "
            "runtime summary JSON into the runtime DuckDB (pipeline_runs + "
            "pipeline_steps only). Offline import only; no pipeline run, no "
            "network, no child processes, no scheduler, no Telegram, no "
            "wallet/signing/swap/LP/rebalance/live."
        )
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to the existing DuckDB database file (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--summary-json",
        required=True,
        help="Path to the run summary JSON produced by run_readonly_pipeline.py.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate files and JSON, print what would be imported; write nothing.",
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="Idempotently replace an existing run_id's rows (only that run_id).",
    )
    return parser.parse_args(argv)


def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  RUN SUMMARY IMPORTER TO DUCKDB v0.1")
    print("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        print(f"  {line}")
    print("------------------------------------------------------------")


def main(argv=None) -> int:
    args = parse_args(argv)
    print_safety_banner()
    return run_import(
        db_path=args.db_path,
        summary_json=args.summary_json,
        dry_run=args.dry_run,
        upsert=args.upsert,
    )


if __name__ == "__main__":
    raise SystemExit(main())
