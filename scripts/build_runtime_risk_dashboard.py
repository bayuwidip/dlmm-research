#!/usr/bin/env python3
"""
Runtime / Risk Dashboard Report v0.1

Purpose:
- Read an EXISTING runtime DuckDB database (default: runtime/dlmm.duckdb) and
  write a read-only Markdown dashboard (plus optional small CSV summaries) that
  summarizes pipeline-run history, strategy observations, risk flags, and risk
  decisions.

This is READ-ONLY HISTORICAL REPORTING ONLY. It is a reporting layer over the
runtime history tables and nothing more.

This script:
- Opens an EXISTING database in read-only mode only.
- Does NOT write to the database (no INSERT / UPDATE / DELETE / CREATE / DROP /
  ALTER).
- Does NOT initialize or create the schema.
- Does NOT create the runtime directory or the database file.
- Does NOT run the pipeline, spawn child processes, or access the network.
- Does NOT schedule anything (no cron / systemd) and does NOT talk to Telegram.
- Does NOT inspect wallets.
- Reads the future_position_events COUNT only, asserts it is 0, and never writes
  it. A non-zero count is reported as a HARD SAFETY VIOLATION and the process
  exits non-zero.

This is NOT and never enables:
- wallet creation / import / management
- private key handling
- transaction signing
- swap execution
- LP add / remove
- rebalance
- live execution
- any LIVE_ELIGIBLE_* capability
- signal generation
- paper position creation
- paper / live / execution instructions of any kind

The dashboard is read-only historical reporting. It does not authorize paper
entries, live entries, wallet use, swaps, LP actions, or rebalances.

See docs/target_architecture.md §7 (SSOT / Storage Layer) and
docs/project_checkpoint.md §2 (Hard Safety Boundary).
"""

from __future__ import annotations

import argparse
import csv
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

# Hard safety boundary lines (project_checkpoint.md §2), rendered in the report.
SAFETY_BOUNDARY_LINES = (
    "No wallet",
    "No private key",
    "No signing",
    "No swap",
    "No LP add/remove",
    "No rebalance",
    "No live execution",
    "No LIVE_ELIGIBLE_*",
    "No signal generation",
    "No paper position creation",
    "No future_position_events writes",
)

# Exact final interpretation note required by the spec.
INTERPRETATION_NOTE = (
    "Dashboard is read-only historical reporting. It does not authorize paper "
    "entries, live entries, wallet use, swaps, LP actions, or rebalances."
)

# Exact message required when the optional duckdb dependency is missing.
DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"
DEFAULT_OUT_MD = "reports/runtime/runtime_risk_dashboard.md"
DEFAULT_OUT_DIR = "reports/runtime"
DEFAULT_LIMIT = 20

# Tables the runtime schema (init_runtime_db.py) is expected to define.
# Order is deterministic for printing.
REQUIRED_TABLES = (
    "runtime_schema_meta",
    "pipeline_runs",
    "pipeline_steps",
    "strategy_observations",
    "risk_flags",
    "risk_decisions",
    "future_position_events",
)

# Statuses treated as a passing pipeline step (anything else counts as a failure
# for the failure summary). Comparison is case-insensitive.
STEP_SUCCESS_STATUSES = frozenset({"SUCCESS", "OK", "PASS", "PASSED", "SKIPPED"})


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
# Helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def db_exists(db_path: str) -> bool:
    """Return True only if db_path points to an existing regular file.

    This never creates anything; it is a pure filesystem check.
    """
    return Path(db_path).is_file()


def open_readonly(db_path: str):
    """Open an EXISTING DuckDB database in read-only mode.

    The caller must ensure the file exists; this function never creates the
    database file or its parent directory. Read-only mode is what guarantees no
    writes occur during reporting.
    """
    duckdb = require_duckdb()
    return duckdb.connect(str(db_path), read_only=True)


def list_tables(conn):
    """Return the set of table names in the main schema of the connection."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


def _rows(conn, sql: str, params=None):
    """Run a SELECT and return the raw list of tuples."""
    return conn.execute(sql, params or []).fetchall()


def table_count(conn, name: str) -> int:
    """Return COUNT(*) for a table assumed present."""
    return conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]


def count_by(conn, table: str, column: str, limit=None):
    """Return [(value, count), ...] grouped by column.

    Sorted by count descending, then value ascending, for determinism. NULLs
    are rendered as the string '(null)'.
    """
    sql = (
        f"SELECT CAST({column} AS VARCHAR) AS v, COUNT(*) AS n "
        f"FROM {table} GROUP BY 1 ORDER BY n DESC, v ASC"
    )
    rows = _rows(conn, sql)
    out = [("(null)" if v is None else v, n) for v, n in rows]
    if limit is not None:
        out = out[:limit]
    return out


# ---------------------------------------------------------------------------
# Markdown rendering helpers
# ---------------------------------------------------------------------------

def md_table(headers, rows) -> list:
    """Render a Markdown table as a list of lines.

    Empty rows render a single '(no rows)' note line instead of a table.
    """
    if not rows:
        return ["_(no rows)_"]
    lines = []
    lines.append("| " + " | ".join(str(h) for h in headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return lines


def _md_cell(value) -> str:
    """Render one Markdown table cell: stringify and escape pipe characters."""
    s = "" if value is None else str(value)
    return s.replace("|", "\\|").replace("\n", " ")


def section(lines: list, title: str) -> None:
    """Append a Markdown section header."""
    lines.append("")
    lines.append(f"## {title}")
    lines.append("")


# ---------------------------------------------------------------------------
# Data gathering (each section is defensive: missing table -> note + skip)
# ---------------------------------------------------------------------------

def gather_required_table_status(present) -> list:
    """Return [(table_name, 'present'|'MISSING'), ...] in deterministic order."""
    return [
        (name, "present" if name in present else "MISSING")
        for name in REQUIRED_TABLES
    ]


def gather_latest_runs(conn, present, limit: int):
    """Return latest pipeline_runs rows (most recent first), or None if missing."""
    if "pipeline_runs" not in present:
        return None
    return _rows(
        conn,
        "SELECT run_id, started_at, ended_at, status, duration_seconds "
        "FROM pipeline_runs ORDER BY started_at DESC, run_id DESC LIMIT ?",
        [limit],
    )


def gather_all_runs(conn, present):
    """Return every pipeline_runs row for the CSV summary, or None if missing."""
    if "pipeline_runs" not in present:
        return None
    return _rows(
        conn,
        "SELECT run_id, started_at, ended_at, status, duration_seconds "
        "FROM pipeline_runs ORDER BY started_at ASC, run_id ASC",
    )


def gather_step_failures(conn, present):
    """Return failing pipeline_steps rows, or None if the table is missing.

    A step is "failing" when its status is not one of the success statuses
    (case-insensitive). Sorted deterministically.
    """
    if "pipeline_steps" not in present:
        return None
    rows = _rows(
        conn,
        "SELECT run_id, step_index, step_name, status, exit_code "
        "FROM pipeline_steps ORDER BY run_id ASC, step_index ASC",
    )
    return [
        r for r in rows
        if str(r[3] or "").strip().upper() not in STEP_SUCCESS_STATUSES
    ]


def gather_repeated_by_decision(conn, decision: str, limit: int):
    """Group risk_decisions for one decision by pair, with occurrence counts.

    Sorted by count descending, then pair_label ascending. The natural top of
    the list surfaces repeated (count > 1) candidates first.
    """
    rows = _rows(
        conn,
        "SELECT pair_key, pair_label, COUNT(*) AS n, "
        "MIN(max_allowed_action) AS max_action "
        "FROM risk_decisions WHERE risk_decision = ? "
        "GROUP BY pair_key, pair_label "
        "ORDER BY n DESC, pair_label ASC, pair_key ASC LIMIT ?",
        [decision, limit],
    )
    return rows


def gather_blocked_rejected(conn, limit: int):
    """Group BLOCKED/REJECTED risk_decisions by pair + decision + reason.

    The reason is risk_blockers when present, else risk_policy_reason. Sorted by
    count descending, then decision, pair_label, reason.
    """
    rows = _rows(
        conn,
        "SELECT risk_decision, pair_key, pair_label, "
        "COALESCE(NULLIF(risk_blockers, ''), risk_policy_reason, '') AS reason, "
        "COUNT(*) AS n "
        "FROM risk_decisions "
        "WHERE risk_decision IN ('BLOCKED', 'REJECTED') "
        "GROUP BY risk_decision, pair_key, pair_label, reason "
        "ORDER BY n DESC, risk_decision ASC, pair_label ASC, reason ASC "
        "LIMIT ?",
        [limit],
    )
    return rows


def gather_core_tactical_stability(conn):
    """Summarize CORE/TACTICAL class stability across strategy_observations.

    For each pair that was ever CORE or TACTICAL, count its distinct
    strategy_class_v2 values across observations. A pair is "stable" when it only
    ever held a single class. Returns a list of summary tuples per focus class.
    """
    # Per-pair distinct class set and observation count.
    rows = _rows(
        conn,
        "SELECT pair_key, "
        "COUNT(DISTINCT strategy_class_v2) AS distinct_classes, "
        "COUNT(*) AS n_obs "
        "FROM strategy_observations GROUP BY pair_key",
    )
    # Which pairs ever held each focus class.
    focus = {}
    for cls in ("CORE", "TACTICAL"):
        focus[cls] = {
            r[0]
            for r in _rows(
                conn,
                "SELECT DISTINCT pair_key FROM strategy_observations "
                "WHERE strategy_class_v2 = ?",
                [cls],
            )
        }

    distinct_by_pair = {r[0]: r[1] for r in rows}
    summary = []
    for cls in ("CORE", "TACTICAL"):
        pairs = focus[cls]
        n_pairs = len(pairs)
        n_stable = sum(1 for p in pairs if distinct_by_pair.get(p, 1) == 1)
        n_changed = n_pairs - n_stable
        summary.append((cls, n_pairs, n_stable, n_changed))
    return summary


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report(conn, present, limit: int) -> dict:
    """Gather all dashboard data into a plain dict (read-only queries only)."""
    report = {
        "required_tables": gather_required_table_status(present),
        "fpe_present": "future_position_events" in present,
        "fpe_count": None,
        "fpe_violation": False,
    }

    # --- Hard safety: future_position_events must be 0 ---
    if report["fpe_present"]:
        report["fpe_count"] = table_count(conn, "future_position_events")
        report["fpe_violation"] = report["fpe_count"] > 0

    # --- Pipeline runs / steps ---
    report["latest_runs"] = gather_latest_runs(conn, present, limit)
    report["all_runs"] = gather_all_runs(conn, present)
    report["run_status_counts"] = (
        count_by(conn, "pipeline_runs", "status")
        if "pipeline_runs" in present else None
    )
    report["step_status_counts"] = (
        count_by(conn, "pipeline_steps", "status")
        if "pipeline_steps" in present else None
    )
    report["step_failures"] = gather_step_failures(conn, present)

    # --- Strategy observations ---
    if "strategy_observations" in present:
        report["obs_by_class"] = count_by(
            conn, "strategy_observations", "strategy_class_v2"
        )
        report["obs_by_status"] = count_by(
            conn, "strategy_observations", "pair_status_v2"
        )
        report["obs_by_readiness"] = count_by(
            conn, "strategy_observations", "observation_ready"
        )
        report["core_tactical_stability"] = gather_core_tactical_stability(conn)
    else:
        report["obs_by_class"] = None
        report["obs_by_status"] = None
        report["obs_by_readiness"] = None
        report["core_tactical_stability"] = None

    # --- Risk flags ---
    if "risk_flags" in present:
        report["flags_by_flag"] = count_by(conn, "risk_flags", "risk_flag")
        report["flags_by_severity"] = count_by(conn, "risk_flags", "severity")
    else:
        report["flags_by_flag"] = None
        report["flags_by_severity"] = None

    # --- Risk decisions ---
    if "risk_decisions" in present:
        report["decision_dist"] = count_by(conn, "risk_decisions", "risk_decision")
        report["action_dist"] = count_by(conn, "risk_decisions", "risk_action")
        report["max_action_dist"] = count_by(
            conn, "risk_decisions", "max_allowed_action"
        )
        report["repeated_prc"] = gather_repeated_by_decision(
            conn, "PAPER_REVIEW_CANDIDATE", limit
        )
        report["repeated_blocked"] = gather_repeated_by_decision(
            conn, "BLOCKED", limit
        )
        report["repeated_rejected"] = gather_repeated_by_decision(
            conn, "REJECTED", limit
        )
        report["blocked_rejected_reasons"] = gather_blocked_rejected(conn, limit)
    else:
        report["decision_dist"] = None
        report["action_dist"] = None
        report["max_action_dist"] = None
        report["repeated_prc"] = None
        report["repeated_blocked"] = None
        report["repeated_rejected"] = None
        report["blocked_rejected_reasons"] = None

    return report


def _dist_section(lines, title, dist, headers=("value", "count")):
    """Render a distribution section, handling the missing-table case."""
    section(lines, title)
    if dist is None:
        lines.append("_table missing — section skipped._")
        return
    lines.extend(md_table(headers, dist))


def render_markdown(report: dict, db_path: str, limit: int) -> str:
    """Render the full Markdown dashboard from a gathered report dict."""
    lines = []
    lines.append("# Runtime / Risk Dashboard Report")
    lines.append("")
    lines.append(f"- generated_at (UTC): {utc_now_iso()}")
    lines.append(f"- safety_phase: {SAFETY_PHASE}")
    lines.append(f"- database path: {db_path}")
    lines.append(f"- row limit: {limit}")

    # --- Hard safety status banner (top of report) ---
    section(lines, "Safety Boundary")
    for line in SAFETY_BOUNDARY_LINES:
        lines.append(f"- {line}")
    lines.append("")
    lines.append(
        "The Risk Policy Engine has veto / reporting authority only — no "
        "execution authority."
    )

    if report["fpe_violation"]:
        lines.append("")
        lines.append("> **HARD SAFETY VIOLATION**")
        lines.append(
            f"> future_position_events count = {report['fpe_count']} (expected 0). "
            "The current phase must never write future_position_events."
        )

    # --- Required table status ---
    section(lines, "Required Table Status")
    lines.extend(md_table(("table", "status"), report["required_tables"]))

    # --- Latest pipeline runs ---
    section(lines, "Latest Pipeline Runs")
    if report["latest_runs"] is None:
        lines.append("_table missing — section skipped._")
    else:
        lines.extend(
            md_table(
                ("run_id", "started_at", "ended_at", "status", "duration_seconds"),
                report["latest_runs"],
            )
        )

    # --- Pipeline run success/failure counts ---
    _dist_section(
        lines, "Pipeline Run Status Counts", report["run_status_counts"],
        headers=("status", "count"),
    )

    # --- Pipeline step status counts + failure summary ---
    _dist_section(
        lines, "Pipeline Step Status Counts", report["step_status_counts"],
        headers=("status", "count"),
    )

    section(lines, "Pipeline Step Failure Summary")
    if report["step_failures"] is None:
        lines.append("_table missing — section skipped._")
    elif not report["step_failures"]:
        lines.append("_No failing pipeline steps recorded._")
    else:
        lines.extend(
            md_table(
                ("run_id", "step_index", "step_name", "status", "exit_code"),
                report["step_failures"],
            )
        )

    # --- Strategy observation distributions ---
    _dist_section(
        lines, "Observation Counts by strategy_class_v2", report["obs_by_class"],
        headers=("strategy_class_v2", "count"),
    )
    _dist_section(
        lines, "Observation Counts by pair_status_v2", report["obs_by_status"],
        headers=("pair_status_v2", "count"),
    )
    _dist_section(
        lines, "Observation Counts by observation_ready", report["obs_by_readiness"],
        headers=("observation_ready", "count"),
    )

    # --- Risk flag distributions ---
    _dist_section(
        lines, "Risk Flag Counts by Flag", report["flags_by_flag"],
        headers=("risk_flag", "count"),
    )
    _dist_section(
        lines, "Risk Flag Counts by Severity", report["flags_by_severity"],
        headers=("severity", "count"),
    )

    # --- Risk decision / action / max distributions ---
    _dist_section(
        lines, "Risk Decision Distribution", report["decision_dist"],
        headers=("risk_decision", "count"),
    )
    _dist_section(
        lines, "Risk Action Distribution", report["action_dist"],
        headers=("risk_action", "count"),
    )
    _dist_section(
        lines, "Max Allowed Action Distribution", report["max_action_dist"],
        headers=("max_allowed_action", "count"),
    )

    # --- Repeated candidates ---
    section(lines, "Repeated PAPER_REVIEW_CANDIDATE Candidates")
    if report["repeated_prc"] is None:
        lines.append("_table missing — section skipped._")
    else:
        lines.extend(
            md_table(
                ("pair_key", "pair_label", "occurrences", "max_allowed_action"),
                report["repeated_prc"],
            )
        )

    section(lines, "Repeated BLOCKED Candidates")
    if report["repeated_blocked"] is None:
        lines.append("_table missing — section skipped._")
    else:
        lines.extend(
            md_table(
                ("pair_key", "pair_label", "occurrences", "max_allowed_action"),
                report["repeated_blocked"],
            )
        )

    section(lines, "Repeated REJECTED Candidates")
    if report["repeated_rejected"] is None:
        lines.append("_table missing — section skipped._")
    else:
        lines.extend(
            md_table(
                ("pair_key", "pair_label", "occurrences", "max_allowed_action"),
                report["repeated_rejected"],
            )
        )

    section(lines, "Repeated BLOCKED / REJECTED Reasons")
    if report["blocked_rejected_reasons"] is None:
        lines.append("_table missing — section skipped._")
    else:
        lines.extend(
            md_table(
                ("risk_decision", "pair_key", "pair_label", "reason", "occurrences"),
                report["blocked_rejected_reasons"],
            )
        )

    # --- CORE / TACTICAL stability ---
    section(lines, "CORE / TACTICAL Stability Summary")
    if report["core_tactical_stability"] is None:
        lines.append("_table missing — section skipped._")
    else:
        lines.extend(
            md_table(
                ("strategy_class", "pairs", "stable", "changed_class"),
                report["core_tactical_stability"],
            )
        )

    # --- future_position_events (display only, expected 0) ---
    section(lines, "future_position_events (display only, expected 0)")
    if not report["fpe_present"]:
        lines.append("_table missing — section skipped._")
    else:
        lines.append(f"- count: {report['fpe_count']} (expected 0)")
        if report["fpe_violation"]:
            lines.append("- status: **HARD SAFETY VIOLATION**")
        else:
            lines.append("- status: OK (no future_position_events rows)")

    # --- Interpretation notes ---
    section(lines, "Interpretation Notes")
    lines.append(INTERPRETATION_NOTE)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CSV outputs (small, deterministic)
# ---------------------------------------------------------------------------

def _write_csv(path: Path, header, rows) -> None:
    """Write a small CSV with a stable header and deterministic rows."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in rows:
            writer.writerow(["" if c is None else c for c in row])


def plan_csv_outputs(report: dict, out_dir: str) -> list:
    """Return [(path, header, rows), ...] for each CSV that has data.

    Only CSVs whose underlying data exists (table present and non-empty) are
    planned. Keeps outputs small and deterministic.
    """
    out = Path(out_dir)
    plans = []

    if report["all_runs"]:
        plans.append(
            (
                out / "pipeline_runs_summary.csv",
                ("run_id", "started_at", "ended_at", "status", "duration_seconds"),
                report["all_runs"],
            )
        )

    if report["decision_dist"]:
        plans.append(
            (
                out / "risk_decision_distribution.csv",
                ("risk_decision", "count"),
                report["decision_dist"],
            )
        )

    if report["repeated_prc"]:
        plans.append(
            (
                out / "repeated_paper_review_candidates.csv",
                ("pair_key", "pair_label", "occurrences", "max_allowed_action"),
                report["repeated_prc"],
            )
        )

    if report["blocked_rejected_reasons"]:
        plans.append(
            (
                out / "repeated_blocked_rejected.csv",
                ("risk_decision", "pair_key", "pair_label", "reason", "occurrences"),
                report["blocked_rejected_reasons"],
            )
        )

    if report["flags_by_flag"]:
        plans.append(
            (
                out / "risk_flag_distribution.csv",
                ("risk_flag", "count"),
                report["flags_by_flag"],
            )
        )

    return plans


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  RUNTIME / RISK DASHBOARD REPORT v0.1")
    print("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        print(f"  {line}")
    print("------------------------------------------------------------")


def run_dashboard(
    db_path: str,
    out_md: str,
    out_dir: str,
    limit: int,
    dry_run: bool,
) -> int:
    """Top-level flow used by the CLI. Returns a process exit code."""
    # --- duckdb dependency (clear message, never auto-install) ---
    try:
        require_duckdb()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    # --- DB must already exist; never create it ---
    if not db_exists(db_path):
        print(
            f"ERROR: Runtime DuckDB not found: {db_path}\n"
            "This dashboard does not create or initialize the database. "
            "Run scripts/init_runtime_db.py first.",
            file=sys.stderr,
        )
        return 2

    conn = open_readonly(db_path)
    try:
        present = list_tables(conn)
        report = build_report(conn, present, limit)
    finally:
        conn.close()

    md = render_markdown(report, db_path, limit)
    csv_plans = plan_csv_outputs(report, out_dir)

    if dry_run:
        print("DRY RUN — no Markdown or CSV files will be written.")
        print(f"  database read     : {db_path}")
        print(f"  would write md    : {out_md}")
        for path, _header, rows in csv_plans:
            print(f"  would write csv   : {path} ({len(rows)} rows)")
        if not csv_plans:
            print("  would write csv   : (none — no CSV-eligible data)")
        print(
            "  future_position_events count: "
            f"{report['fpe_count']} (expected 0)"
        )
        if report["fpe_violation"]:
            print(
                "  HARD SAFETY VIOLATION: future_position_events count > 0.",
                file=sys.stderr,
            )
            print("DRY RUN COMPLETE — nothing written.")
            return 4
        print("DRY RUN COMPLETE — nothing written.")
        return 0

    # --- Write Markdown ---
    md_path = Path(out_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    print(f"Wrote Markdown dashboard: {md_path}")

    # --- Write CSVs (only where data exists) ---
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    for path, header, rows in csv_plans:
        _write_csv(path, header, rows)
        print(f"Wrote CSV: {path} ({len(rows)} rows)")
    if not csv_plans:
        print("No CSV-eligible data; wrote no CSV files.")

    print(f"future_position_events count: {report['fpe_count']} (expected 0)")
    if report["fpe_violation"]:
        print(
            "HARD SAFETY VIOLATION: future_position_events count > 0. "
            "The current phase must never write future_position_events.",
            file=sys.stderr,
        )
        return 4

    print(INTERPRETATION_NOTE)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Runtime / Risk Dashboard Report v0.1 — read an existing runtime "
            "DuckDB database and write a read-only Markdown dashboard (plus "
            "optional small CSV summaries). Read-only; never writes the DB, "
            "never initializes schema, no pipeline run, no network, no "
            "scheduler, no Telegram, no positions, no signals, no "
            "wallet/signing/swap/LP/rebalance/live."
        )
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to the existing DuckDB database file (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--out-md",
        default=DEFAULT_OUT_MD,
        help=f"Path to write the Markdown dashboard (default: {DEFAULT_OUT_MD}).",
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Directory for the optional CSV summaries (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        metavar="N",
        help=f"Row limit for list/repeated sections (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate DB and report what would be written; write nothing.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    print_safety_banner()
    return run_dashboard(
        db_path=args.db_path,
        out_md=args.out_md,
        out_dir=args.out_dir,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
