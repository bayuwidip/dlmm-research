#!/usr/bin/env python3
"""
NO_ELIGIBLE_FEE_POOL Diagnostics v0.1

Purpose:
- Read an EXISTING runtime DuckDB database (default: runtime/dlmm.duckdb) and
  write a read-only Markdown + CSV diagnostic that explains which pairs are
  repeatedly blocked by the NO_ELIGIBLE_FEE_POOL risk flag, and why, using only
  existing runtime history tables.

Motivation:
- The ARGUS 5-run report surfaced a recurring blocker
  (BLOCKED:NO_ELIGIBLE_FEE_POOL) that is highly concentrated on a small set of
  pairs while future_position_events remained 0. This report is a DIAGNOSTIC
  ONLY: it explains the blocker; it does not change any threshold, risk rule,
  classification, or candidate status, and it recommends no such change.

This is READ-ONLY HISTORICAL REPORTING ONLY. It is a reporting layer over the
runtime history tables and nothing more.

This script:
- Opens an EXISTING database in read-only mode only.
- Does NOT write to the database (no INSERT / UPDATE / DELETE / CREATE / DROP /
  ALTER).
- Does NOT initialize or create the schema.
- Does NOT create the runtime directory or the database file.
- Does NOT run the pipeline, spawn child processes, or access the network.
- Reads the future_position_events COUNT only. A non-zero count is a HARD SAFETY
  VIOLATION: the process writes NO report and exits non-zero. It never writes
  future_position_events.

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
- threshold / risk-policy / candidate-status changes

The diagnostic is read-only historical reporting. It does not authorize paper
entries, live entries, wallet use, swaps, LP actions, or rebalances.
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

# Hard safety boundary lines, rendered in the report. Each is phrased as a
# negation so the diagnostic never reads as an authorization.
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
    "No threshold changes",
    "No risk policy changes",
    "No candidate status changes",
)

# Diagnostic-only notice rendered near the top of the report.
DIAGNOSTIC_NOTICE = (
    "This is a proposal-only / diagnostic-only report. It explains an existing "
    "blocker from runtime history. It does not authorize paper entries, live "
    "entries, wallet use, swaps, LP actions, or rebalances, and it recommends "
    "no threshold, risk-policy, classification, or candidate-status change."
)

# Exact message required when the optional duckdb dependency is missing.
DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)

# Project-wide sentinel for any field that cannot be populated from the data.
DATA_NOT_AVAILABLE = "DATA_NOT_AVAILABLE"

# The risk flag / blocker this diagnostic is about.
TARGET = "NO_ELIGIBLE_FEE_POOL"
TARGET_LIKE = f"%{TARGET}%"

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"
DEFAULT_OUT_MD = "reports/runtime/no_eligible_fee_pool_diagnostics.md"
DEFAULT_OUT_CSV = "reports/runtime/no_eligible_fee_pool_diagnostics.csv"
DEFAULT_LIMIT = 50

# Runtime tables this diagnostic reads when present.
OPTIONAL_TABLES = (
    "pipeline_runs",
    "strategy_observations",
    "risk_flags",
    "risk_decisions",
    "future_position_events",
)

# CSV column order (exact, per spec).
CSV_COLUMNS = (
    "pair_key",
    "pair_label",
    "no_eligible_fee_pool_flag_count",
    "no_eligible_fee_pool_decision_count",
    "latest_risk_decision",
    "latest_risk_action",
    "latest_max_allowed_action",
    "observed_strategy_classes",
    "observed_lanes",
    "first_seen_at",
    "last_seen_at",
    "diagnostic_note",
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


def _clean(value) -> str:
    """Return a stripped string for a possibly-None DB value."""
    return "" if value is None else str(value).strip()


def _join_or_na(values) -> str:
    """Join a set of non-empty strings (sorted) with '|', or the NA sentinel."""
    cleaned = sorted({v for v in (_clean(x) for x in values) if v})
    return "|".join(cleaned) if cleaned else DATA_NOT_AVAILABLE


def _minmax_or_na(values):
    """Return (min, max) of non-empty ISO timestamp strings, or NA sentinels."""
    cleaned = sorted(v for v in (_clean(x) for x in values) if v)
    if not cleaned:
        return DATA_NOT_AVAILABLE, DATA_NOT_AVAILABLE
    return cleaned[0], cleaned[-1]


# ---------------------------------------------------------------------------
# Data gathering (read-only; each source is defensive against a missing table)
# ---------------------------------------------------------------------------

def gather_flag_rows(conn, present):
    """Return NO_ELIGIBLE_FEE_POOL rows from risk_flags, or [] if unavailable."""
    if "risk_flags" not in present:
        return None
    return _rows(
        conn,
        "SELECT pair_key, pair_label, observed_at FROM risk_flags "
        "WHERE risk_flag = ?",
        [TARGET],
    )


def gather_decision_rows(conn, present):
    """Return risk_decisions whose reason text mentions NO_ELIGIBLE_FEE_POOL.

    "Reason" here means any of the human-readable reason fields the risk engine
    writes (blockers, policy reason, required next step, warnings). Returns None
    when the table is absent.
    """
    if "risk_decisions" not in present:
        return None
    return _rows(
        conn,
        "SELECT pair_key, pair_label, risk_decision, risk_action, "
        "max_allowed_action, CAST(imported_at AS VARCHAR) AS imported_at, "
        "risk_decision_id "
        "FROM risk_decisions WHERE "
        "COALESCE(risk_blockers, '') ILIKE ? "
        "OR COALESCE(risk_policy_reason, '') ILIKE ? "
        "OR COALESCE(risk_required_next_step, '') ILIKE ? "
        "OR COALESCE(risk_warnings, '') ILIKE ?",
        [TARGET_LIKE, TARGET_LIKE, TARGET_LIKE, TARGET_LIKE],
    )


def gather_observations(conn, present):
    """Return strategy_observations rows used for class/lane context, or None."""
    if "strategy_observations" not in present:
        return None
    return _rows(
        conn,
        "SELECT pair_key, pair_label, strategy_class_v2, test_lane, observed_at "
        "FROM strategy_observations",
    )


def aggregate_pairs(flag_rows, decision_rows, observation_rows, limit):
    """Aggregate the per-pair diagnostic records.

    Returns (records, totals) where records is a deterministically sorted list of
    dicts (one per affected pair) and totals is a small summary dict. ``limit``
    bounds only the count of records returned (the "top affected pairs"); when
    limit is None, all affected pairs are returned.
    """
    flag_rows = flag_rows or []
    decision_rows = decision_rows or []
    observation_rows = observation_rows or []

    # Index observations by pair for class/lane/timestamp context.
    obs_classes = {}
    obs_lanes = {}
    obs_times = {}
    obs_labels = {}
    for pair_key, pair_label, cls, lane, observed_at in observation_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        obs_classes.setdefault(pk, []).append(cls)
        obs_lanes.setdefault(pk, []).append(lane)
        obs_times.setdefault(pk, []).append(observed_at)
        obs_labels.setdefault(pk, []).append(pair_label)

    # Per-pair accumulators keyed by pair_key.
    pairs = {}

    def _pair(pk):
        return pairs.setdefault(
            pk,
            {
                "labels": [],
                "flag_count": 0,
                "decision_count": 0,
                "decisions": [],  # (sort_key, decision, action, max_action)
                "times": [],
            },
        )

    for pair_key, pair_label, observed_at in flag_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = _pair(pk)
        rec["flag_count"] += 1
        rec["labels"].append(pair_label)
        rec["times"].append(observed_at)

    for (pair_key, pair_label, decision, action, max_action, imported_at,
         decision_id) in decision_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = _pair(pk)
        rec["decision_count"] += 1
        rec["labels"].append(pair_label)
        rec["times"].append(imported_at)
        # Sort key picks the most recent decision deterministically: latest
        # imported_at, then highest risk_decision_id as a stable tiebreak.
        sort_key = (_clean(imported_at), _clean(decision_id))
        rec["decisions"].append(
            (sort_key, _clean(decision), _clean(action), _clean(max_action))
        )

    records = []
    for pk, rec in pairs.items():
        labels = list(rec["labels"]) + obs_labels.get(pk, [])
        non_empty_labels = sorted({_clean(x) for x in labels if _clean(x)})
        label = non_empty_labels[0] if non_empty_labels else DATA_NOT_AVAILABLE

        if rec["decisions"]:
            latest = max(rec["decisions"], key=lambda d: d[0])
            latest_decision = latest[1] or DATA_NOT_AVAILABLE
            latest_action = latest[2] or DATA_NOT_AVAILABLE
            latest_max = latest[3] or DATA_NOT_AVAILABLE
        else:
            latest_decision = DATA_NOT_AVAILABLE
            latest_action = DATA_NOT_AVAILABLE
            latest_max = DATA_NOT_AVAILABLE

        first_seen, last_seen = _minmax_or_na(
            list(rec["times"]) + obs_times.get(pk, [])
        )

        records.append(
            {
                "pair_key": pk,
                "pair_label": label,
                "flag_count": rec["flag_count"],
                "decision_count": rec["decision_count"],
                "latest_risk_decision": latest_decision,
                "latest_risk_action": latest_action,
                "latest_max_allowed_action": latest_max,
                "observed_strategy_classes": _join_or_na(obs_classes.get(pk, [])),
                "observed_lanes": _join_or_na(obs_lanes.get(pk, [])),
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "diagnostic_note": make_note(
                    rec["flag_count"], rec["decision_count"]
                ),
            }
        )

    # Deterministic sort: decision_count desc, flag_count desc, label, key.
    records.sort(
        key=lambda r: (
            -r["decision_count"],
            -r["flag_count"],
            r["pair_label"],
            r["pair_key"],
        )
    )

    totals = {
        "total_flags": len(flag_rows),
        "total_decisions": len(decision_rows),
        "affected_pairs": len(records),
    }

    if limit is not None:
        records = records[:limit]

    return records, totals


def make_note(flag_count: int, decision_count: int) -> str:
    """Return a short, safe diagnostic note for one affected pair."""
    if decision_count > 0 and flag_count > 0:
        return (
            "Repeatedly blocked by NO_ELIGIBLE_FEE_POOL; verify the pool fee "
            "tier / bin step / liquidity data for this pair is present and "
            "current before any manual review."
        )
    if decision_count > 0:
        return (
            "Blocked by NO_ELIGIBLE_FEE_POOL in risk decisions but no matching "
            "risk flag recorded; verify the reason-field source data."
        )
    if flag_count > 0:
        return (
            "Flagged NO_ELIGIBLE_FEE_POOL without a recorded blocking decision; "
            "verify pool fee / bin / liquidity data."
        )
    return "No NO_ELIGIBLE_FEE_POOL activity recorded for this pair."


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_diagnostics(conn, present, limit: int) -> dict:
    """Gather all diagnostic data into a plain dict (read-only queries only)."""
    fpe_present = "future_position_events" in present
    fpe_count = table_count(conn, "future_position_events") if fpe_present else None
    fpe_violation = bool(fpe_present and fpe_count and fpe_count > 0)

    run_present = "pipeline_runs" in present
    run_count = table_count(conn, "pipeline_runs") if run_present else None

    flag_rows = gather_flag_rows(conn, present)
    decision_rows = gather_decision_rows(conn, present)
    observation_rows = gather_observations(conn, present)

    records, totals = aggregate_pairs(
        flag_rows, decision_rows, observation_rows, limit
    )

    return {
        "fpe_present": fpe_present,
        "fpe_count": fpe_count,
        "fpe_violation": fpe_violation,
        "run_present": run_present,
        "run_count": run_count,
        "flags_present": flag_rows is not None,
        "decisions_present": decision_rows is not None,
        "observations_present": observation_rows is not None,
        "records": records,
        "totals": totals,
    }


def _md_cell(value) -> str:
    """Render one Markdown table cell: stringify and escape pipe characters."""
    s = "" if value is None else str(value)
    return s.replace("|", "\\|").replace("\n", " ")


def md_table(headers, rows) -> list:
    """Render a Markdown table as a list of lines, or a '(no rows)' note."""
    if not rows:
        return ["_(no rows)_"]
    lines = ["| " + " | ".join(str(h) for h in headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return lines


def section(lines: list, title: str) -> None:
    lines.append("")
    lines.append(f"## {title}")
    lines.append("")


def _present_note(flag) -> str:
    return "" if flag else " _(table missing — reported as no data)_"


def render_markdown(diag: dict, db_path: str, limit: int) -> str:
    """Render the full Markdown diagnostic from a gathered diag dict."""
    totals = diag["totals"]
    lines = []
    lines.append("# NO_ELIGIBLE_FEE_POOL Diagnostics v0.1")
    lines.append("")
    lines.append(f"- generated_at (UTC): {utc_now_iso()}")
    lines.append(f"- safety_phase: {SAFETY_PHASE}")
    lines.append(f"- database path: {db_path}")
    lines.append(f"- top affected pairs limit: {limit}")
    lines.append("")
    lines.append(DIAGNOSTIC_NOTICE)

    # --- Hard safety boundary ---
    section(lines, "Safety Boundary")
    for line in SAFETY_BOUNDARY_LINES:
        lines.append(f"- {line}")
    lines.append("")
    lines.append(
        "The Risk Policy Engine has veto / reporting authority only — no "
        "execution authority."
    )

    # --- Summary ---
    section(lines, "Summary")
    run_count = (
        diag["run_count"] if diag["run_present"] else DATA_NOT_AVAILABLE
    )
    fpe_count = (
        diag["fpe_count"] if diag["fpe_present"] else DATA_NOT_AVAILABLE
    )
    lines.append(f"- pipeline run count: {run_count}{_present_note(diag['run_present'])}")
    lines.append(
        f"- future_position_events count: {fpe_count} (expected 0)"
        f"{_present_note(diag['fpe_present'])}"
    )
    lines.append(
        f"- total NO_ELIGIBLE_FEE_POOL flags: {totals['total_flags']}"
        f"{_present_note(diag['flags_present'])}"
    )
    lines.append(
        f"- total NO_ELIGIBLE_FEE_POOL decisions: {totals['total_decisions']}"
        f"{_present_note(diag['decisions_present'])}"
    )
    lines.append(f"- affected pair count: {totals['affected_pairs']}")
    if not diag["observations_present"]:
        lines.append(
            "- strategy_observations: _table missing — class/lane context "
            "reported as no data_"
        )

    if diag["fpe_violation"]:
        lines.append("")
        lines.append("> **HARD SAFETY VIOLATION**")
        lines.append(
            f"> future_position_events count = {diag['fpe_count']} (expected 0). "
            "No diagnostic report is produced while this is non-zero."
        )

    # --- Top affected pairs ---
    section(lines, "Top Affected Pairs")
    rows = [
        (
            r["pair_label"],
            r["pair_key"],
            r["decision_count"],
            r["flag_count"],
            r["latest_risk_decision"],
            r["latest_risk_action"],
            r["latest_max_allowed_action"],
            r["observed_strategy_classes"],
            r["observed_lanes"],
            r["first_seen_at"],
            r["last_seen_at"],
        )
        for r in diag["records"]
    ]
    lines.extend(
        md_table(
            (
                "pair_label",
                "pair_key",
                "decision_count",
                "flag_count",
                "latest_risk_decision",
                "latest_risk_action",
                "latest_max_allowed_action",
                "observed_strategy_classes",
                "observed_lanes",
                "first_seen_at",
                "last_seen_at",
            ),
            rows,
        )
    )

    # --- Diagnostic interpretation ---
    section(lines, "Diagnostic Interpretation")
    lines.append(
        "a. A repeated NO_ELIGIBLE_FEE_POOL blocker may be valid: the affected "
        "pairs may genuinely have no fee pool that meets the screening criteria, "
        "in which case the blocker is the risk engine working as intended."
    )
    lines.append(
        "b. A repeated blocker may instead indicate missing or stale input data "
        "— absent pool fee-tier, bin-step, or liquidity fields — so the engine "
        "cannot find an eligible fee pool even where one may exist."
    )
    lines.append(
        "c. No threshold or risk-rule change is recommended by this report. It "
        "is diagnostic only; resolving (a) versus (b) is a manual data-quality "
        "check, not a policy change."
    )

    # --- Next safe manual checks ---
    section(lines, "Next Safe Manual Checks")
    lines.append(
        "- For each top affected pair, confirm whether the source pool rows "
        "actually carry fee-tier / bin-step / liquidity fields, or whether those "
        "fields are DATA_NOT_AVAILABLE."
    )
    lines.append(
        "- Cross-check the pair against the raw API snapshot in data/raw/ to see "
        "whether an eligible fee pool exists upstream."
    )
    lines.append(
        "- Confirm the affected pairs' strategy classes / lanes above match "
        "expectations; a CORE/TACTICAL pair stuck on this blocker is the most "
        "worthwhile to inspect by hand."
    )
    lines.append(
        "- Take no automated action: this report neither requests nor permits "
        "any threshold, risk-policy, classification, or candidate-status change."
    )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def write_csv(path: Path, records) -> None:
    """Write the per-pair diagnostic CSV with the exact spec column order."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for r in records:
            writer.writerow(
                [
                    r["pair_key"],
                    r["pair_label"],
                    r["flag_count"],
                    r["decision_count"],
                    r["latest_risk_decision"],
                    r["latest_risk_action"],
                    r["latest_max_allowed_action"],
                    r["observed_strategy_classes"],
                    r["observed_lanes"],
                    r["first_seen_at"],
                    r["last_seen_at"],
                    r["diagnostic_note"],
                ]
            )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  NO_ELIGIBLE_FEE_POOL DIAGNOSTICS v0.1")
    print("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        print(f"  {line}")
    print("------------------------------------------------------------")


def run_diagnostics(
    db_path: str,
    out_md: str,
    out_csv: str,
    limit: int,
    dry_run: bool,
) -> int:
    """Top-level flow used by the CLI. Returns a process exit code."""
    # --- duckdb dependency (exact message, never auto-install) ---
    try:
        require_duckdb()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    # --- DB must already exist; never create or initialize it ---
    if not db_exists(db_path):
        print(
            f"ERROR: Runtime DuckDB not found: {db_path}\n"
            "This diagnostic does not create or initialize the database.",
            file=sys.stderr,
        )
        return 2

    conn = open_readonly(db_path)
    try:
        present = list_tables(conn)
        diag = build_diagnostics(conn, present, limit)
    finally:
        conn.close()

    totals = diag["totals"]

    # --- Hard safety: future_position_events must be 0; write NOTHING if not ---
    if diag["fpe_violation"]:
        print(
            "HARD SAFETY VIOLATION: future_position_events count = "
            f"{diag['fpe_count']} (expected 0). No report written.",
            file=sys.stderr,
        )
        return 4

    if dry_run:
        print("DRY RUN — no Markdown or CSV files will be written.")
        print(f"  database read   : {db_path}")
        print(f"  would write md  : {out_md}")
        print(f"  would write csv : {out_csv} ({len(diag['records'])} rows)")
        print(f"  pipeline runs   : {diag['run_count']}")
        print(
            "  future_position_events count: "
            f"{diag['fpe_count']} (expected 0)"
        )
        print(f"  total NO_ELIGIBLE_FEE_POOL flags    : {totals['total_flags']}")
        print(f"  total NO_ELIGIBLE_FEE_POOL decisions: {totals['total_decisions']}")
        print(f"  affected pairs  : {totals['affected_pairs']}")
        print("DRY RUN COMPLETE — nothing written.")
        return 0

    # --- Write Markdown ---
    md = render_markdown(diag, db_path, limit)
    md_path = Path(out_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    print(f"Wrote Markdown diagnostic: {md_path}")

    # --- Write CSV ---
    csv_path = Path(out_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(csv_path, diag["records"])
    print(f"Wrote CSV diagnostic: {csv_path} ({len(diag['records'])} rows)")

    print(f"future_position_events count: {diag['fpe_count']} (expected 0)")
    print(DIAGNOSTIC_NOTICE)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "NO_ELIGIBLE_FEE_POOL Diagnostics v0.1 — read an existing runtime "
            "DuckDB database and write a read-only Markdown + CSV diagnostic of "
            "which pairs are repeatedly blocked by NO_ELIGIBLE_FEE_POOL and why. "
            "Read-only; never writes the DB, never initializes schema, no "
            "pipeline run, no network, no positions, no signals, no "
            "wallet/signing/swap/LP/rebalance/live, no threshold/risk-policy/"
            "candidate-status changes."
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
        help=f"Path to write the Markdown diagnostic (default: {DEFAULT_OUT_MD}).",
    )
    parser.add_argument(
        "--out-csv",
        default=DEFAULT_OUT_CSV,
        help=f"Path to write the CSV diagnostic (default: {DEFAULT_OUT_CSV}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        metavar="N",
        help=(
            "Maximum number of top affected pairs to include in both outputs "
            f"(default: {DEFAULT_LIMIT})."
        ),
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
    limit = args.limit if args.limit is not None and args.limit >= 0 else None
    return run_diagnostics(
        db_path=args.db_path,
        out_md=args.out_md,
        out_csv=args.out_csv,
        limit=limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
