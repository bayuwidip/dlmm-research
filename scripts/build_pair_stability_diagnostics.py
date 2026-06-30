#!/usr/bin/env python3
"""Pair Stability Diagnostics v0.1

Purpose:
- Read an EXISTING runtime DuckDB database (default: runtime/dlmm.duckdb) and
  write a read-only Markdown + CSV diagnostic describing per-pair stability
  across runtime runs: which pairs are stable, which churn, which repeatedly
  surface as PAPER_REVIEW_CANDIDATE, and which appear only once.

Motivation:
- After the ARGUS 5-run report and the NO_ELIGIBLE_FEE_POOL diagnostic, the next
  question before any future paper-simulation DESIGN work is: how stable is each
  pair across runs? This report answers that with existing runtime history only.
  It is a DIAGNOSTIC ONLY: it does not change any threshold, risk rule,
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

A "stable review candidate" in this report means only that a human/council may
review the pair for future paper-simulation design consideration. It is not an
entry, not a position, and authorizes nothing.
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
    "This is a diagnostic-only report. It describes per-pair stability across "
    "existing runtime history. It does not authorize paper entries, live "
    "entries, wallet use, swaps, LP actions, or rebalances, and it recommends "
    "no threshold, risk-policy, classification, or candidate-status change."
)

# Safe phrasing reused for stable review candidates. Avoids any wording that
# could read as an entry, position, or signal.
REVIEW_PHRASE = (
    "human/council may review for future paper-simulation design consideration"
)

# Exact message required when the optional duckdb dependency is missing.
DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)

# Project-wide sentinel for any field that cannot be populated from the data.
DATA_NOT_AVAILABLE = "DATA_NOT_AVAILABLE"

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"
DEFAULT_OUT_MD = "reports/runtime/pair_stability_diagnostics.md"
DEFAULT_OUT_CSV = "reports/runtime/pair_stability_diagnostics.csv"
DEFAULT_LIMIT = 100
DEFAULT_MIN_RUNS = 5

# Stability labels.
STABLE_REVIEW_CANDIDATE = "STABLE_REVIEW_CANDIDATE"
STABLE_OBSERVE_ONLY = "STABLE_OBSERVE_ONLY"
CHURNING_CLASS = "CHURNING_CLASS"
CHURNING_LANE = "CHURNING_LANE"
MOSTLY_BLOCKED = "MOSTLY_BLOCKED"
ONE_OFF = "ONE_OFF"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# Sort / display priority for stability labels (lower sorts first).
LABEL_PRIORITY = {
    STABLE_REVIEW_CANDIDATE: 0,
    STABLE_OBSERVE_ONLY: 1,
    CHURNING_CLASS: 2,
    CHURNING_LANE: 3,
    MOSTLY_BLOCKED: 4,
    ONE_OFF: 5,
    INSUFFICIENT_DATA: 6,
}

# Risk-decision vocabulary this diagnostic counts per pair.
DECISION_PAPER_REVIEW = "PAPER_REVIEW_CANDIDATE"
DECISION_BLOCKED = "BLOCKED"
DECISION_REJECTED = "REJECTED"
DECISION_NOT_EVALUATED = "NOT_EVALUATED"
DECISION_OBSERVE_ONLY = "OBSERVE_ONLY"

# Runtime tables this diagnostic reads when present.
OPTIONAL_TABLES = (
    "pipeline_runs",
    "strategy_observations",
    "risk_decisions",
    "future_position_events",
)

# CSV column order (exact, per spec).
CSV_COLUMNS = (
    "pair_key",
    "pair_label",
    "observation_count",
    "distinct_run_count",
    "first_seen_at",
    "last_seen_at",
    "observed_strategy_classes",
    "strategy_class_change_count",
    "observed_lanes",
    "lane_change_count",
    "latest_strategy_class",
    "latest_lane",
    "latest_risk_decision",
    "latest_risk_action",
    "latest_max_allowed_action",
    "paper_review_candidate_count",
    "blocked_count",
    "rejected_count",
    "not_evaluated_count",
    "stability_label",
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


def _transitions(seq) -> int:
    """Count consecutive changes in a time-ordered sequence of values.

    Empty/None values are dropped first so a missing reading does not register
    as a spurious change. A value appearing again later (A, B, A) counts as two
    transitions, which is the churn we want to surface.
    """
    cleaned = [v for v in (_clean(x) for x in seq) if v]
    return sum(1 for i in range(1, len(cleaned)) if cleaned[i] != cleaned[i - 1])


# ---------------------------------------------------------------------------
# Data gathering (read-only; each source is defensive against a missing table)
# ---------------------------------------------------------------------------

def gather_observation_rows(conn, present):
    """Return strategy_observations rows, or None if the table is absent."""
    if "strategy_observations" not in present:
        return None
    return _rows(
        conn,
        "SELECT pair_key, pair_label, run_id, strategy_class_v2, test_lane, "
        "observed_at, observation_id "
        "FROM strategy_observations",
    )


def gather_decision_rows(conn, present):
    """Return risk_decisions rows, or None if the table is absent."""
    if "risk_decisions" not in present:
        return None
    return _rows(
        conn,
        "SELECT pair_key, pair_label, risk_decision, risk_action, "
        "max_allowed_action, CAST(imported_at AS VARCHAR) AS imported_at, "
        "risk_decision_id "
        "FROM risk_decisions",
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _new_pair():
    return {
        "labels": [],
        # observation-level ordered samples: (observed_at, obs_id, cls, lane)
        "samples": [],
        "run_ids": [],
        "obs_times": [],
        # decision-level ordered samples: (sort_key, decision, action, max)
        "decisions": [],
        "dec_times": [],
        "paper_review_candidate_count": 0,
        "blocked_count": 0,
        "rejected_count": 0,
        "not_evaluated_count": 0,
        "observe_only_count": 0,
    }


def _classify(rec) -> str:
    """Return the stability_label for one aggregated pair record."""
    observation_count = len(rec["samples"])
    if observation_count == 0:
        return INSUFFICIENT_DATA

    # Effective number of runs the pair appears in. Prefer distinct run_id when
    # available; otherwise fall back to the observation count.
    run_ids = {_clean(r) for r in rec["run_ids"] if _clean(r)}
    appearances = len(run_ids) if run_ids else observation_count

    if appearances <= 1:
        return ONE_OFF

    ordered = sorted(rec["samples"], key=lambda s: (_clean(s[0]), _clean(s[1])))
    if _transitions(s[2] for s in ordered) > 0:
        return CHURNING_CLASS
    if _transitions(s[3] for s in ordered) > 0:
        return CHURNING_LANE

    blocked = rec["blocked_count"]
    prc = rec["paper_review_candidate_count"]
    rejected = rec["rejected_count"]
    not_eval = rec["not_evaluated_count"]
    observe = rec["observe_only_count"]

    # MOSTLY_BLOCKED: blocked is the dominant (plurality) recorded decision.
    if blocked > 0 and blocked >= max(prc, rejected, not_eval, observe):
        return MOSTLY_BLOCKED

    # STABLE_REVIEW_CANDIDATE: stable class/lane and the pair keeps surfacing as
    # a paper-review candidate. This authorizes nothing — see REVIEW_PHRASE.
    latest_decision = _latest_decision(rec)[0]
    if prc > 0 and (prc >= max(rejected, not_eval, observe)
                    or latest_decision == DECISION_PAPER_REVIEW):
        return STABLE_REVIEW_CANDIDATE

    return STABLE_OBSERVE_ONLY


def _latest_decision(rec):
    """Return (decision, action, max_action) for the most recent decision."""
    if not rec["decisions"]:
        return (DATA_NOT_AVAILABLE, DATA_NOT_AVAILABLE, DATA_NOT_AVAILABLE)
    latest = max(rec["decisions"], key=lambda d: d[0])
    return (
        latest[1] or DATA_NOT_AVAILABLE,
        latest[2] or DATA_NOT_AVAILABLE,
        latest[3] or DATA_NOT_AVAILABLE,
    )


def _latest_observation(rec):
    """Return (strategy_class, lane) for the most recent observation."""
    if not rec["samples"]:
        return (DATA_NOT_AVAILABLE, DATA_NOT_AVAILABLE)
    latest = max(rec["samples"], key=lambda s: (_clean(s[0]), _clean(s[1])))
    return (
        _clean(latest[2]) or DATA_NOT_AVAILABLE,
        _clean(latest[3]) or DATA_NOT_AVAILABLE,
    )


def make_note(label: str) -> str:
    """Return a short, safe diagnostic note for one pair's stability label."""
    if label == STABLE_REVIEW_CANDIDATE:
        return (
            "Stable across runs and repeatedly a paper-review candidate; "
            f"{REVIEW_PHRASE}. No candidate status is changed."
        )
    if label == STABLE_OBSERVE_ONLY:
        return (
            "Stable across runs and observe-only; continue observation. No "
            "candidate status is changed."
        )
    if label == CHURNING_CLASS:
        return (
            "Strategy class changes across runs; data/classification stability "
            "should be verified by hand before any review."
        )
    if label == CHURNING_LANE:
        return (
            "Test lane changes across runs while strategy class is stable; "
            "verify the lane inputs by hand before any review."
        )
    if label == MOSTLY_BLOCKED:
        return (
            "Predominantly blocked across recorded decisions; verify whether "
            "the blocker is valid or a data-quality issue. No status change."
        )
    if label == ONE_OFF:
        return (
            "Appears in only one run; insufficient repetition to judge "
            "stability. Re-observe across more runs before any review."
        )
    return (
        "No observation history recorded for this pair; nothing to assess."
    )


def aggregate_pairs(observation_rows, decision_rows, limit):
    """Aggregate per-pair stability records.

    Returns (records, totals). ``records`` is deterministically sorted; ``limit``
    bounds only the number of records returned (None means all).
    """
    observation_rows = observation_rows or []
    decision_rows = decision_rows or []

    pairs = {}

    def _pair(pk):
        return pairs.setdefault(pk, _new_pair())

    for (pair_key, pair_label, run_id, cls, lane, observed_at,
         obs_id) in observation_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = _pair(pk)
        rec["labels"].append(pair_label)
        rec["samples"].append((observed_at, obs_id, cls, lane))
        rec["run_ids"].append(run_id)
        rec["obs_times"].append(observed_at)

    for (pair_key, pair_label, decision, action, max_action, imported_at,
         decision_id) in decision_rows:
        pk = _clean(pair_key)
        if not pk:
            continue
        rec = _pair(pk)
        rec["labels"].append(pair_label)
        rec["dec_times"].append(imported_at)
        # Sort key picks the most recent decision deterministically: latest
        # imported_at, then highest risk_decision_id as a stable tiebreak.
        sort_key = (_clean(imported_at), _clean(decision_id))
        rec["decisions"].append(
            (sort_key, _clean(decision), _clean(action), _clean(max_action))
        )
        dec = _clean(decision)
        if dec == DECISION_PAPER_REVIEW:
            rec["paper_review_candidate_count"] += 1
        elif dec == DECISION_BLOCKED:
            rec["blocked_count"] += 1
        elif dec == DECISION_REJECTED:
            rec["rejected_count"] += 1
        elif dec == DECISION_NOT_EVALUATED:
            rec["not_evaluated_count"] += 1
        elif dec == DECISION_OBSERVE_ONLY:
            rec["observe_only_count"] += 1

    records = []
    for pk, rec in pairs.items():
        non_empty_labels = sorted({_clean(x) for x in rec["labels"] if _clean(x)})
        label_text = non_empty_labels[0] if non_empty_labels else DATA_NOT_AVAILABLE

        observation_count = len(rec["samples"])
        run_ids = {_clean(r) for r in rec["run_ids"] if _clean(r)}
        distinct_run_count = len(run_ids) if run_ids else DATA_NOT_AVAILABLE

        ordered = sorted(
            rec["samples"], key=lambda s: (_clean(s[0]), _clean(s[1]))
        )
        class_changes = _transitions(s[2] for s in ordered)
        lane_changes = _transitions(s[3] for s in ordered)

        first_seen, last_seen = _minmax_or_na(
            list(rec["obs_times"]) + list(rec["dec_times"])
        )
        latest_class, latest_lane = _latest_observation(rec)
        latest_decision, latest_action, latest_max = _latest_decision(rec)

        stability_label = _classify(rec)

        records.append(
            {
                "pair_key": pk,
                "pair_label": label_text,
                "observation_count": observation_count,
                "distinct_run_count": distinct_run_count,
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "observed_strategy_classes": _join_or_na(
                    s[2] for s in rec["samples"]
                ),
                "strategy_class_change_count": class_changes,
                "observed_lanes": _join_or_na(s[3] for s in rec["samples"]),
                "lane_change_count": lane_changes,
                "latest_strategy_class": latest_class,
                "latest_lane": latest_lane,
                "latest_risk_decision": latest_decision,
                "latest_risk_action": latest_action,
                "latest_max_allowed_action": latest_max,
                "paper_review_candidate_count": rec["paper_review_candidate_count"],
                "blocked_count": rec["blocked_count"],
                "rejected_count": rec["rejected_count"],
                "not_evaluated_count": rec["not_evaluated_count"],
                "stability_label": stability_label,
                "diagnostic_note": make_note(stability_label),
            }
        )

    # Deterministic sort: label priority, paper_review_candidate_count desc,
    # observation_count desc, pair_label, pair_key.
    records.sort(
        key=lambda r: (
            LABEL_PRIORITY.get(r["stability_label"], 99),
            -r["paper_review_candidate_count"],
            -r["observation_count"],
            r["pair_label"],
            r["pair_key"],
        )
    )

    label_counts = {}
    for r in records:
        label_counts[r["stability_label"]] = (
            label_counts.get(r["stability_label"], 0) + 1
        )

    totals = {
        "total_pairs": len(records),
        "total_observations": len(observation_rows),
        "total_decisions": len(decision_rows),
        "label_counts": label_counts,
    }

    if limit is not None:
        records = records[:limit]

    return records, totals


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_diagnostics(conn, present, limit: int, min_runs: int) -> dict:
    """Gather all diagnostic data into a plain dict (read-only queries only)."""
    fpe_present = "future_position_events" in present
    fpe_count = table_count(conn, "future_position_events") if fpe_present else None
    fpe_violation = bool(fpe_present and fpe_count and fpe_count > 0)

    run_present = "pipeline_runs" in present
    run_count = table_count(conn, "pipeline_runs") if run_present else None

    observation_rows = gather_observation_rows(conn, present)
    decision_rows = gather_decision_rows(conn, present)

    # Distinct runs observed in the history (independent of pipeline_runs).
    observed_run_ids = set()
    for row in observation_rows or []:
        rid = _clean(row[2])
        if rid:
            observed_run_ids.add(rid)
    distinct_observed_runs = len(observed_run_ids)

    records, totals = aggregate_pairs(observation_rows, decision_rows, limit)

    evidence_runs = max(
        run_count or 0, distinct_observed_runs
    )
    evidence_sufficient = evidence_runs >= min_runs

    return {
        "fpe_present": fpe_present,
        "fpe_count": fpe_count,
        "fpe_violation": fpe_violation,
        "run_present": run_present,
        "run_count": run_count,
        "distinct_observed_runs": distinct_observed_runs,
        "observations_present": observation_rows is not None,
        "decisions_present": decision_rows is not None,
        "evidence_runs": evidence_runs,
        "evidence_sufficient": evidence_sufficient,
        "min_runs": min_runs,
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


_PAIR_HEADERS = (
    "pair_label",
    "pair_key",
    "observation_count",
    "distinct_run_count",
    "strategy_class_change_count",
    "lane_change_count",
    "observed_strategy_classes",
    "observed_lanes",
    "latest_risk_decision",
    "latest_max_allowed_action",
    "paper_review_candidate_count",
    "blocked_count",
    "first_seen_at",
    "last_seen_at",
)


def _pair_row(r):
    return (
        r["pair_label"],
        r["pair_key"],
        r["observation_count"],
        r["distinct_run_count"],
        r["strategy_class_change_count"],
        r["lane_change_count"],
        r["observed_strategy_classes"],
        r["observed_lanes"],
        r["latest_risk_decision"],
        r["latest_max_allowed_action"],
        r["paper_review_candidate_count"],
        r["blocked_count"],
        r["first_seen_at"],
        r["last_seen_at"],
    )


def _table_for(lines, records, labels):
    rows = [_pair_row(r) for r in records if r["stability_label"] in labels]
    lines.extend(md_table(_PAIR_HEADERS, rows))


def render_markdown(diag: dict, db_path: str, limit: int) -> str:
    """Render the full Markdown diagnostic from a gathered diag dict."""
    totals = diag["totals"]
    records = diag["records"]
    lines = []
    lines.append("# Pair Stability Diagnostics v0.1")
    lines.append("")
    lines.append(f"- generated_at (UTC): {utc_now_iso()}")
    lines.append(f"- safety_phase: {SAFETY_PHASE}")
    lines.append(f"- database path: {db_path}")
    lines.append(f"- top pairs limit: {limit}")
    lines.append(f"- min_runs (evidence threshold): {diag['min_runs']}")
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
    run_count = diag["run_count"] if diag["run_present"] else DATA_NOT_AVAILABLE
    fpe_count = diag["fpe_count"] if diag["fpe_present"] else DATA_NOT_AVAILABLE
    lines.append(
        f"- pipeline run count: {run_count}{_present_note(diag['run_present'])}"
    )
    lines.append(
        f"- distinct runs in observation history: {diag['distinct_observed_runs']}"
        f"{_present_note(diag['observations_present'])}"
    )
    lines.append(
        f"- future_position_events count: {fpe_count} (expected 0)"
        f"{_present_note(diag['fpe_present'])}"
    )
    lines.append(f"- total observation rows: {totals['total_observations']}")
    lines.append(f"- total risk-decision rows: {totals['total_decisions']}")
    lines.append(f"- total pairs analysed: {totals['total_pairs']}")
    if not diag["decisions_present"]:
        lines.append(
            "- risk_decisions: _table missing — decision context reported as "
            "no data_"
        )

    # Evidence sufficiency note.
    if diag["evidence_sufficient"]:
        lines.append(
            f"- evidence sufficiency: SUFFICIENT — {diag['evidence_runs']} run(s) "
            f">= min_runs ({diag['min_runs']})."
        )
    else:
        lines.append(
            f"- evidence sufficiency: INSUFFICIENT — only {diag['evidence_runs']} "
            f"run(s) available, below min_runs ({diag['min_runs']}). Stability "
            "labels below are weakly evidenced and must not be relied upon."
        )

    if diag["fpe_violation"]:
        lines.append("")
        lines.append("> **HARD SAFETY VIOLATION**")
        lines.append(
            f"> future_position_events count = {diag['fpe_count']} (expected 0). "
            "No diagnostic report is produced while this is non-zero."
        )

    # --- Summary by stability label ---
    section(lines, "Summary by Stability Label")
    label_rows = [
        (label, totals["label_counts"].get(label, 0))
        for label in sorted(
            totals["label_counts"], key=lambda x: LABEL_PRIORITY.get(x, 99)
        )
    ]
    lines.extend(md_table(("stability_label", "pair_count"), label_rows))

    # --- Top stable review candidates ---
    section(lines, "Top Stable Review Candidates")
    lines.append(
        f"Stable across runs and repeatedly a paper-review candidate. {REVIEW_PHRASE}."
    )
    lines.append("")
    _table_for(lines, records, {STABLE_REVIEW_CANDIDATE})

    # --- Top churning pairs ---
    section(lines, "Top Churning Pairs")
    lines.append(
        "Strategy class and/or test lane changes across runs; verify input "
        "stability by hand before any review."
    )
    lines.append("")
    _table_for(lines, records, {CHURNING_CLASS, CHURNING_LANE})

    # --- Top mostly blocked pairs ---
    section(lines, "Top Mostly Blocked Pairs")
    lines.append(
        "Predominantly blocked across recorded decisions; verify whether the "
        "blocker is valid or a data-quality issue."
    )
    lines.append("")
    _table_for(lines, records, {MOSTLY_BLOCKED})

    # --- One-off candidates ---
    section(lines, "One-Off Pairs")
    lines.append(
        "Seen in only one run; insufficient repetition to judge stability."
    )
    lines.append("")
    _table_for(lines, records, {ONE_OFF})

    # --- Interpretation notes ---
    section(lines, "Interpretation Notes")
    lines.append(
        "a. A stable review candidate does NOT mean a paper entry. It is not an "
        "entry, not a position, and authorizes nothing."
    )
    lines.append(
        f"b. It means only that a {REVIEW_PHRASE}; the review is a future design "
        "step, not an action taken here."
    )
    lines.append(
        "c. No candidate status changes are made by this report."
    )
    lines.append(
        "d. No threshold or risk-policy changes are recommended by this report. "
        "It is diagnostic only."
    )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def write_csv(path: Path, records) -> None:
    """Write the per-pair stability CSV with the exact spec column order."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for r in records:
            writer.writerow([r[col] for col in CSV_COLUMNS])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  PAIR STABILITY DIAGNOSTICS v0.1")
    print("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        print(f"  {line}")
    print("------------------------------------------------------------")


def run_diagnostics(
    db_path: str,
    out_md: str,
    out_csv: str,
    limit: int,
    min_runs: int,
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
        diag = build_diagnostics(conn, present, limit, min_runs)
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
        print(f"  observed runs   : {diag['distinct_observed_runs']}")
        print(
            "  future_position_events count: "
            f"{diag['fpe_count']} (expected 0)"
        )
        print(f"  total observations: {totals['total_observations']}")
        print(f"  total decisions   : {totals['total_decisions']}")
        print(f"  total pairs       : {totals['total_pairs']}")
        print(
            "  evidence          : "
            + ("SUFFICIENT" if diag["evidence_sufficient"] else "INSUFFICIENT")
            + f" ({diag['evidence_runs']} run(s) vs min_runs {diag['min_runs']})"
        )
        for label in sorted(
            totals["label_counts"], key=lambda x: LABEL_PRIORITY.get(x, 99)
        ):
            print(f"    {label}: {totals['label_counts'][label]}")
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
            "Pair Stability Diagnostics v0.1 — read an existing runtime DuckDB "
            "database and write a read-only Markdown + CSV diagnostic of "
            "per-pair stability across runs (stable, churning, repeatedly a "
            "paper-review candidate, or one-off). Read-only; never writes the "
            "DB, never initializes schema, no pipeline run, no network, no "
            "positions, no signals, no wallet/signing/swap/LP/rebalance/live, "
            "no threshold/risk-policy/candidate-status changes."
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
            "Maximum number of top pairs to include in both outputs "
            f"(default: {DEFAULT_LIMIT})."
        ),
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        default=DEFAULT_MIN_RUNS,
        metavar="N",
        help=(
            "Minimum runs for the evidence-sufficiency note "
            f"(default: {DEFAULT_MIN_RUNS})."
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
        min_runs=args.min_runs,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
