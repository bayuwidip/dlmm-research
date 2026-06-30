#!/usr/bin/env python3
"""
Runtime DuckDB Inspector v0.1

Purpose:
- Read-only audit/inspection tool for the runtime DuckDB database
  (default: runtime/dlmm.duckdb).

This script:
- Opens an EXISTING database in read-only mode only.
- Does NOT write to the database.
- Does NOT initialize or create schema.
- Does NOT create the runtime directory or the database file.
- Does NOT integrate with the runner (no runner integration).
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

It is an audit/inspection tool only. It reads counts and metadata. Reading the
future_position_events row count is NOT active execution capability; this tool
only displays the count and latest event metadata and never generates paper or
live instructions.

See docs/target_architecture.md §7 (SSOT / Storage Layer) and
docs/project_checkpoint.md §2 (Hard Safety Boundary).
"""

from __future__ import annotations

import argparse
import json
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

# Final note printed on every human-readable inspection.
INSPECTION_ONLY_NOTE = "Inspection only. No database writes. No execution authority."

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"

# Tables the runtime schema skeleton (init_runtime_db.py) is expected to define.
# Order is deterministic for printing.
REQUIRED_TABLES = (
    "runtime_schema_meta",
    "pipeline_runs",
    "pipeline_steps",
    "strategy_observations",
    "risk_flags",
    "future_position_events",
)


# ---------------------------------------------------------------------------
# Dependency chokepoint
# ---------------------------------------------------------------------------

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
# Read-only database access
# ---------------------------------------------------------------------------

def db_exists(db_path: str) -> bool:
    """Return True only if db_path points to an existing regular file.

    This never creates anything; it is a pure filesystem check.
    """
    return Path(db_path).is_file()


def open_readonly(db_path: str):
    """Open an EXISTING DuckDB database in read-only mode.

    The caller must ensure the file exists; this function never creates the
    database file or its parent directory. Read-only mode is what guarantees no
    writes occur during inspection.
    """
    duckdb = require_duckdb()
    return duckdb.connect(str(db_path), read_only=True)


def _rows_as_dicts(conn, sql: str, params=None):
    """Run a SELECT and return rows as a list of column-keyed dicts."""
    cur = conn.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def list_tables(conn):
    """Return the set of table names in the main schema of the connection."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


def get_required_tables_status(present):
    """Map each required table name to a bool: present in the database or not."""
    return {name: (name in present) for name in REQUIRED_TABLES}


def get_table_counts(conn, present):
    """Return row counts per required table.

    Missing tables map to None (cannot be counted), present tables to an int.
    """
    counts = {}
    for name in REQUIRED_TABLES:
        if name in present:
            counts[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        else:
            counts[name] = None
    return counts


def get_schema_meta(conn, present):
    """Return the runtime_schema_meta marker as a dict, or None if unavailable."""
    if "runtime_schema_meta" not in present:
        return None
    rows = _rows_as_dicts(
        conn,
        "SELECT schema_name, schema_version, safety_phase, updated_at "
        "FROM runtime_schema_meta ORDER BY schema_name LIMIT 1",
    )
    return rows[0] if rows else None


def get_latest_runs(conn, present, limit: int):
    """Return the latest pipeline_runs rows (most recent first), or []."""
    if limit <= 0 or "pipeline_runs" not in present:
        return []
    return _rows_as_dicts(
        conn,
        "SELECT run_id, started_at, ended_at, status, safety_phase "
        "FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
        [limit],
    )


def get_latest_observations(conn, present, limit: int):
    """Return the latest strategy_observations rows (most recent first), or []."""
    if limit <= 0 or "strategy_observations" not in present:
        return []
    return _rows_as_dicts(
        conn,
        "SELECT observation_id, observed_at, pair_label, strategy_class_v2, "
        "pair_status_v2, live_eligibility "
        "FROM strategy_observations ORDER BY observed_at DESC LIMIT ?",
        [limit],
    )


def get_future_position_events_summary(conn, present, counts):
    """Return a display-only summary of future_position_events.

    This reports the row count and the latest event metadata for audit purposes
    ONLY. It never produces paper or live instructions and confers no execution
    capability — future_position_events is a reserved placeholder table.
    """
    summary = {"count": counts.get("future_position_events"), "latest_event": None}
    if "future_position_events" not in present:
        return summary
    rows = _rows_as_dicts(
        conn,
        "SELECT event_id, event_time, phase, event_type, pair_label "
        "FROM future_position_events ORDER BY event_time DESC LIMIT 1",
    )
    if rows:
        summary["latest_event"] = rows[0]
    return summary


# ---------------------------------------------------------------------------
# Report assembly (pure-ish: opens db read-only, never writes)
# ---------------------------------------------------------------------------

def build_report(db_path: str, latest_runs: int, latest_observations: int) -> dict:
    """Build the inspection report as a plain dict.

    Never creates the database file or its parent directory. If the database
    file does not exist, the report records exists=False and status=DB_NOT_FOUND
    without attempting to open anything.
    """
    report = {
        "db_path": str(db_path),
        "exists": db_exists(db_path),
        "schema_meta": None,
        "required_tables": {name: False for name in REQUIRED_TABLES},
        "table_counts": {name: None for name in REQUIRED_TABLES},
        "latest_runs": [],
        "latest_observations": [],
        "future_position_events": {"count": None, "latest_event": None},
        "status": "DB_NOT_FOUND",
        "safety_phase": SAFETY_PHASE,
        "inspection_only": True,
    }

    if not report["exists"]:
        return report

    conn = open_readonly(db_path)
    try:
        present = list_tables(conn)
        report["required_tables"] = get_required_tables_status(present)
        report["table_counts"] = get_table_counts(conn, present)
        report["schema_meta"] = get_schema_meta(conn, present)
        report["latest_runs"] = get_latest_runs(conn, present, latest_runs)
        report["latest_observations"] = get_latest_observations(
            conn, present, latest_observations
        )
        report["future_position_events"] = get_future_position_events_summary(
            conn, present, report["table_counts"]
        )
        all_present = all(report["required_tables"].values())
        report["status"] = "OK" if all_present else "INCOMPLETE_SCHEMA"
    finally:
        conn.close()

    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_json(report: dict) -> str:
    """Render the report as a JSON string (stable key order)."""
    ordered = {
        "db_path": report["db_path"],
        "exists": report["exists"],
        "schema_meta": report["schema_meta"],
        "required_tables": report["required_tables"],
        "table_counts": report["table_counts"],
        "latest_runs": report["latest_runs"],
        "latest_observations": report["latest_observations"],
        "future_position_events": report["future_position_events"],
        "status": report["status"],
        "safety_phase": report["safety_phase"],
        "inspection_only": report["inspection_only"],
    }
    return json.dumps(ordered, indent=2, default=str)


def _format_meta(meta) -> list:
    if not meta:
        return ["  (no runtime_schema_meta row found)"]
    return [
        f"  schema_name    : {meta.get('schema_name')}",
        f"  schema_version : {meta.get('schema_version')}",
        f"  safety_phase   : {meta.get('safety_phase')}",
        f"  updated_at     : {meta.get('updated_at')}",
    ]


def render_human(report: dict) -> str:
    """Render the report as a human-readable summary string."""
    lines = []
    lines.append("------------------------------------------------------------")
    lines.append("  RUNTIME DUCKDB INSPECTOR v0.1")
    lines.append("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        lines.append(f"  {line}")
    lines.append("------------------------------------------------------------")

    lines.append(f"Database path : {report['db_path']}")
    lines.append(f"Exists        : {report['exists']}")
    lines.append(f"Status        : {report['status']}")
    lines.append(f"Safety phase  : {report['safety_phase']}")

    if not report["exists"]:
        lines.append("")
        lines.append("Database file does not exist. Nothing to inspect.")
        lines.append("This inspector does not create the database or its directory.")
        lines.append("")
        lines.append(INSPECTION_ONLY_NOTE)
        return "\n".join(lines)

    lines.append("")
    lines.append("Schema metadata:")
    lines.extend(_format_meta(report["schema_meta"]))

    lines.append("")
    lines.append("Required tables:")
    for name in REQUIRED_TABLES:
        present = report["required_tables"].get(name, False)
        mark = "present" if present else "MISSING"
        count = report["table_counts"].get(name)
        count_str = "-" if count is None else str(count)
        lines.append(f"  {name:<26} {mark:<8} rows={count_str}")

    lines.append("")
    runs = report["latest_runs"]
    lines.append(f"Latest pipeline_runs ({len(runs)}):")
    if not runs:
        lines.append("  (none)")
    for r in runs:
        lines.append(
            f"  {r.get('run_id')} | {r.get('started_at')} -> "
            f"{r.get('ended_at')} | {r.get('status')}"
        )

    lines.append("")
    obs = report["latest_observations"]
    lines.append(f"Latest strategy_observations ({len(obs)}):")
    if not obs:
        lines.append("  (none)")
    for o in obs:
        lines.append(
            f"  {o.get('observed_at')} | {o.get('pair_label')} | "
            f"{o.get('strategy_class_v2')} | {o.get('pair_status_v2')} | "
            f"{o.get('live_eligibility')}"
        )

    # Display-only: counts and latest metadata, never instructions.
    lines.append("")
    fpe = report["future_position_events"]
    lines.append(f"future_position_events (display only): count={fpe.get('count')}")
    latest = fpe.get("latest_event")
    if latest:
        lines.append(
            f"  latest: {latest.get('event_time')} | {latest.get('phase')} | "
            f"{latest.get('event_type')} | {latest.get('pair_label')}"
        )
    else:
        lines.append("  latest: (none)")

    lines.append("")
    lines.append(INSPECTION_ONLY_NOTE)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Runtime DuckDB Inspector v0.1 — read-only audit of the runtime "
            "DuckDB database. Read-only; never writes, never initializes schema, "
            "no runner integration, no execution, no "
            "wallet/signing/swap/LP/rebalance/live."
        )
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to the DuckDB database file (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the inspection report as JSON to stdout.",
    )
    parser.add_argument(
        "--table-counts",
        action="store_true",
        help="(Always computed) Include row counts per required table.",
    )
    parser.add_argument(
        "--latest-runs",
        type=int,
        default=5,
        metavar="N",
        help="Show the latest N pipeline_runs (default: 5).",
    )
    parser.add_argument(
        "--latest-observations",
        type=int,
        default=5,
        metavar="N",
        help="Show the latest N strategy_observations (default: 5).",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    report = build_report(
        args.db_path,
        latest_runs=args.latest_runs,
        latest_observations=args.latest_observations,
    )

    if args.json:
        print(render_json(report))
    else:
        print(render_human(report))

    # Missing database is a non-zero exit (clear message already rendered).
    if not report["exists"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
