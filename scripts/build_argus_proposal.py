#!/usr/bin/env python3
"""
ARGUS Proposal Report v0.1

NAME NOTE: ARGUS was previously called Hermes during design, but was renamed to
avoid confusion with external Hermes agent projects (e.g.
NousResearch/hermes-agent). The original design document retains its filename
(docs/hermes_agent_design.md); it remains the scope of record for this component.

Purpose:
- Read an EXISTING runtime DuckDB database (default: runtime/dlmm.duckdb), and
  optionally read the read-only Runtime / Risk Dashboard files (Markdown + CSV),
  look for repeated patterns across runs, and write PROPOSAL-ONLY ARGUS reports
  under reports/argus/.

This is ARGUS: a proposal-only historical analysis REPORTER. It is NOT an agent
executor. Per docs/hermes_agent_design.md:

- ARGUS may observe, summarize, and propose.
- ARGUS may NOT decide, execute, or silently change the system.
- ARGUS is NOT autonomous.
- ARGUS is NOT a trading agent.
- ARGUS is NOT a coding agent.
- ARGUS is NOT a risk authority.
- ARGUS must NOT change thresholds or risk policy.
- ARGUS must NOT create signals or positions.
- ARGUS must NOT write DuckDB.
- ARGUS must NOT write future_position_events.

Every ARGUS output is a proposal addressed to a human/council. No threshold,
risk policy, candidate status, signal, paper position, live position, or
future_position_events row is ever created or changed by ARGUS.

This script:
- Opens an EXISTING database in read-only mode only.
- Does NOT write to the database (no INSERT / UPDATE / DELETE / CREATE / DROP /
  ALTER).
- Does NOT initialize or create the schema, the runtime directory, or the db file.
- Does NOT run the pipeline, call the dashboard builder, spawn child processes,
  or access the network.
- Does NOT schedule anything (no cron / systemd) and does NOT talk to Telegram.
- Does NOT read secrets or environment variables.
- Does NOT inspect wallets.
- Reads the future_position_events COUNT only, requires it to be 0, and never
  writes it. A non-zero count is a HARD SAFETY VIOLATION: ARGUS writes no
  proposal and exits non-zero.
- Writes ONLY proposal-only artifacts under reports/argus/. It never writes to
  data/, runtime/, reports/runtime/, scripts/, docs/, or the DuckDB database.

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

See docs/hermes_agent_design.md (the ARGUS scope of record; the design document
retains its original Hermes-era filename) and docs/project_checkpoint.md §2
(Hard Safety Boundary).
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
# These are NEGATED capability statements; they are the only place forbidden
# capability words may appear in an ARGUS report.
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

# Proposal-only notice rendered at the top of every report.
PROPOSAL_ONLY_NOTICE = (
    "This is a PROPOSAL-ONLY report. ARGUS may observe, summarize, and propose; "
    "it may not decide, execute, or change the system. Every entry below is a "
    "request for human/council review and confers no authority. Nothing here "
    "changes any threshold, risk policy, candidate status, signal, or position."
)

# The closing interpretation note.
INTERPRETATION_NOTE = (
    "ARGUS proposals are read-only observations addressed to a human/council. "
    "They do not authorize paper entries, live entries, wallet use, signing, "
    "swaps, LP actions, or rebalances, and they grant no execution authority."
)

# Standard approval field text, reused by every proposal.
APPROVAL_NOTE = (
    "Nothing changes without explicit human/council review and approval. "
    "This proposal confers no authority."
)

# Exact message required when the optional duckdb dependency is missing.
DUCKDB_MISSING_MSG = (
    "duckdb package is required. Install with: python3 -m pip install duckdb"
)

DEFAULT_DB_PATH = "runtime/dlmm.duckdb"
DEFAULT_DASHBOARD_DIR = "reports/runtime"
DEFAULT_OUT_DIR = "reports/argus"
DEFAULT_LIMIT = 20
DEFAULT_MIN_RUNS = 5

# Tables the runtime schema (init_runtime_db.py) is expected to define.
REQUIRED_TABLES = (
    "runtime_schema_meta",
    "pipeline_runs",
    "pipeline_steps",
    "strategy_observations",
    "risk_flags",
    "risk_decisions",
    "future_position_events",
)

# Proposal categories (closed set).
CATEGORY_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
CATEGORY_STABLE_CANDIDATE_REVIEW = "STABLE_CANDIDATE_REVIEW"
CATEGORY_RECURRING_BLOCKER_REVIEW = "RECURRING_BLOCKER_REVIEW"
CATEGORY_CLASSIFICATION_CHURN_REVIEW = "CLASSIFICATION_CHURN_REVIEW"
CATEGORY_DATA_QUALITY_REVIEW = "DATA_QUALITY_REVIEW"
CATEGORY_SAFETY_BOUNDARY_REVIEW = "SAFETY_BOUNDARY_REVIEW"

# Severity levels (closed set, ordered low -> high for reference only).
SEVERITY_INFO = "INFO"
SEVERITY_WATCH = "WATCH"
SEVERITY_REVIEW = "REVIEW"
SEVERITY_BLOCKER = "BLOCKER"

# Findings CSV columns (exact order).
FINDINGS_COLUMNS = (
    "proposal_id",
    "category",
    "severity",
    "observation",
    "evidence",
    "hypothesis",
    "recommendation",
    "risk_of_change",
    "suggested_test",
    "required_human_or_council_approval",
)

# Data-quality flag name for malformed pair labels.
MALFORMED_PAIR_LABEL = "MALFORMED_PAIR_LABEL"


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


def default_date_str() -> str:
    """Return today's UTC date as YYYYMMDD (used for output filenames + ids)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def db_exists(db_path: str) -> bool:
    """Return True only if db_path points to an existing regular file."""
    return Path(db_path).is_file()


def open_readonly(db_path: str):
    """Open an EXISTING DuckDB database in read-only mode.

    The caller must ensure the file exists; this function never creates the
    database file or its parent directory. Read-only mode is what guarantees no
    writes occur during analysis.
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


def is_malformed_label(label) -> bool:
    """Return True when a pair label has a blank/missing base or quote symbol.

    Examples treated as malformed: None, "", "-USDT" (blank base), "USDC-"
    (blank quote). A normal "USDC-SOL" is not malformed. A label without any
    separator is not flagged here (it is not a blank-side case).
    """
    if label is None:
        return True
    s = str(label).strip()
    if s == "" or s == "(null)":
        return True
    if "-" not in s:
        return False
    parts = s.split("-")
    base = parts[0].strip()
    quote = parts[-1].strip()
    return base == "" or quote == ""


# ---------------------------------------------------------------------------
# Data gathering (each section is defensive: missing table -> None + skip)
# ---------------------------------------------------------------------------

def gather_repeated_by_decision(conn, present, decision: str, limit: int):
    """Group risk_decisions for one decision by pair, with occurrence counts.

    Returns None when risk_decisions is missing. Sorted by count descending,
    then pair_label, then pair_key, for determinism.
    """
    if "risk_decisions" not in present:
        return None
    return _rows(
        conn,
        "SELECT pair_key, pair_label, COUNT(*) AS n "
        "FROM risk_decisions WHERE risk_decision = ? "
        "GROUP BY pair_key, pair_label "
        "ORDER BY n DESC, pair_label ASC, pair_key ASC LIMIT ?",
        [decision, limit],
    )


def gather_blocked_rejected_reasons(conn, present, limit: int):
    """Group BLOCKED/REJECTED risk_decisions by decision + reason, with counts.

    Reason is risk_blockers when present, else risk_policy_reason. Returns None
    when risk_decisions is missing.
    """
    if "risk_decisions" not in present:
        return None
    return _rows(
        conn,
        "SELECT risk_decision, "
        "COALESCE(NULLIF(risk_blockers, ''), risk_policy_reason, '') AS reason, "
        "COUNT(*) AS n "
        "FROM risk_decisions "
        "WHERE risk_decision IN ('BLOCKED', 'REJECTED') "
        "GROUP BY risk_decision, reason "
        "ORDER BY n DESC, risk_decision ASC, reason ASC LIMIT ?",
        [limit],
    )


def gather_core_tactical_stability(conn, present):
    """Summarize CORE/TACTICAL class stability across strategy_observations.

    For each focus class, returns (class, n_pairs, n_stable, n_changed). A pair
    is "stable" when it only ever held a single strategy_class_v2 value across
    its observations. Returns None when strategy_observations is missing.
    """
    if "strategy_observations" not in present:
        return None
    distinct_by_pair = {
        r[0]: r[1]
        for r in _rows(
            conn,
            "SELECT pair_key, COUNT(DISTINCT strategy_class_v2) AS distinct_classes "
            "FROM strategy_observations GROUP BY pair_key",
        )
    }
    summary = []
    for cls in ("CORE", "TACTICAL"):
        pairs = {
            r[0]
            for r in _rows(
                conn,
                "SELECT DISTINCT pair_key FROM strategy_observations "
                "WHERE strategy_class_v2 = ?",
                [cls],
            )
        }
        n_pairs = len(pairs)
        n_stable = sum(1 for p in pairs if distinct_by_pair.get(p, 1) == 1)
        summary.append((cls, n_pairs, n_stable, n_pairs - n_stable))
    return summary


def gather_flag_concentration(conn, present, limit: int):
    """Return [(risk_flag, count), ...] top flags, or None when missing."""
    if "risk_flags" not in present:
        return None
    return _rows(
        conn,
        "SELECT CAST(risk_flag AS VARCHAR) AS v, COUNT(*) AS n "
        "FROM risk_flags GROUP BY 1 ORDER BY n DESC, v ASC LIMIT ?",
        [limit],
    )


def gather_malformed_labels(conn, present, limit: int):
    """Return [(pair_key, pair_label, occurrences), ...] for malformed labels.

    Scans distinct (pair_key, pair_label) across risk_decisions and
    strategy_observations (whichever exist), keeps only malformed labels, and
    aggregates how many source rows reference each. Returns None when neither
    table exists.
    """
    sources = []
    if "risk_decisions" in present:
        sources.append("SELECT pair_key, pair_label FROM risk_decisions")
    if "strategy_observations" in present:
        sources.append("SELECT pair_key, pair_label FROM strategy_observations")
    if not sources:
        return None

    counts = {}
    for sql in sources:
        for pair_key, pair_label in _rows(conn, sql):
            if is_malformed_label(pair_label):
                key = (pair_key, pair_label)
                counts[key] = counts.get(key, 0) + 1

    rows = [(k[0], k[1], n) for k, n in counts.items()]
    # Deterministic: count desc, then label, then key. Render None labels as ''.
    rows.sort(key=lambda r: (-r[2], str(r[1] or ""), str(r[0] or "")))
    return rows[:limit]


def gather_dashboard_sources(dashboard_dir: str):
    """Return a sorted list of existing dashboard files ARGUS may corroborate.

    Light-touch: it only checks which dashboard files are present (the dashboard
    Markdown and any CSV summaries) so they can be listed as input sources. It
    never writes to reports/runtime and never calls the dashboard builder.
    """
    base = Path(dashboard_dir)
    if not base.is_dir():
        return []
    found = []
    md = base / "runtime_risk_dashboard.md"
    if md.is_file():
        found.append(str(md))
    found.extend(str(p) for p in sorted(base.glob("*.csv")))
    return found


# ---------------------------------------------------------------------------
# Report assembly (read-only queries only)
# ---------------------------------------------------------------------------

def gather_report(conn, present, limit: int, dashboard_dir: str) -> dict:
    """Gather all evidence into a plain dict (read-only queries only)."""
    report = {
        "required_tables": [
            (name, "present" if name in present else "MISSING")
            for name in REQUIRED_TABLES
        ],
        "fpe_present": "future_position_events" in present,
        "fpe_count": None,
        "fpe_violation": False,
        "run_count": (
            table_count(conn, "pipeline_runs")
            if "pipeline_runs" in present else 0
        ),
        "runs_table_present": "pipeline_runs" in present,
    }

    if report["fpe_present"]:
        report["fpe_count"] = table_count(conn, "future_position_events")
        report["fpe_violation"] = report["fpe_count"] > 0

    report["repeated_prc"] = gather_repeated_by_decision(
        conn, present, "PAPER_REVIEW_CANDIDATE", limit
    )
    report["blocked_rejected_reasons"] = gather_blocked_rejected_reasons(
        conn, present, limit
    )
    report["core_tactical_stability"] = gather_core_tactical_stability(conn, present)
    report["flag_concentration"] = gather_flag_concentration(conn, present, limit)
    report["malformed_labels"] = gather_malformed_labels(conn, present, limit)
    report["dashboard_sources"] = gather_dashboard_sources(dashboard_dir)
    return report


# ---------------------------------------------------------------------------
# Proposal generation (deterministic order -> deterministic ids)
# ---------------------------------------------------------------------------

def _repeated_only(rows):
    """Filter a [(key, label, n), ...] list to entries that recur (n > 1)."""
    return [r for r in (rows or []) if r[2] > 1]


def _changed_focus_classes(stability):
    """Return [(class, n_changed), ...] for focus classes with churn (>0)."""
    if not stability:
        return []
    return [(cls, n_changed) for (cls, _np, _ns, n_changed) in stability if n_changed > 0]


def build_proposals(report: dict, min_runs: int) -> list:
    """Build the ordered list of proposal dicts (without ids) from the report.

    The order here is FIXED so that proposal ids are deterministic for the same
    underlying data. Each proposal is a request for human/council review only.
    """
    proposals = []
    run_count = report["run_count"]
    sufficient = run_count >= min_runs

    # --- 1. Insufficient evidence (suppresses readiness-flavored proposals) ---
    if not sufficient:
        proposals.append(
            {
                "category": CATEGORY_INSUFFICIENT_EVIDENCE,
                "severity": SEVERITY_WATCH,
                "observation": (
                    f"Only {run_count} runtime run(s) are recorded in pipeline_runs; "
                    f"the configured evidence threshold is {min_runs}."
                ),
                "evidence": (
                    f"pipeline_runs row count = {run_count} (< min_runs = {min_runs})."
                ),
                "hypothesis": (
                    "Unproven: patterns drawn from too few runs may reflect noise "
                    "rather than a stable trend."
                ),
                "recommendation": (
                    "Collect more runtime runs before paper simulation design."
                ),
                "risk_of_change": (
                    "Acting on too few runs risks over-fitting to transient runtime "
                    "conditions. No candidate is ready; no rule should change."
                ),
                "suggested_test": (
                    "Continue read-only runtime collection and re-run this report "
                    "once more runs accumulate; compare whether patterns persist."
                ),
                "required_human_or_council_approval": APPROVAL_NOTE,
            }
        )

    # --- 2. Stable / repeated PAPER_REVIEW_CANDIDATE (only when sufficient) ---
    repeated_prc = _repeated_only(report["repeated_prc"])
    if sufficient and repeated_prc:
        labels = ", ".join(f"{r[1]} (x{r[2]})" for r in repeated_prc[:5])
        proposals.append(
            {
                "category": CATEGORY_STABLE_CANDIDATE_REVIEW,
                "severity": SEVERITY_REVIEW,
                "observation": (
                    "One or more pairs recur as PAPER_REVIEW_CANDIDATE across "
                    "recorded risk decisions."
                ),
                "evidence": (
                    f"risk_decisions grouped by pair (recurring, count > 1): {labels}."
                ),
                "hypothesis": (
                    "Unproven: these pairs may be persistently classifiable and "
                    "could merit a closer human look for future paper-simulation "
                    "design."
                ),
                "recommendation": (
                    "human/council should review this candidate for future "
                    "paper-simulation design consideration"
                ),
                "risk_of_change": (
                    "Treating recurrence as readiness would be premature. ARGUS "
                    "proposes review only; it does not open, size, or place anything."
                ),
                "suggested_test": (
                    "A human may review these pairs' recorded history and design a "
                    "read-only paper-simulation evaluation before any decision."
                ),
                "required_human_or_council_approval": APPROVAL_NOTE,
            }
        )

    # --- 3. Recurring BLOCKED / REJECTED reasons (only when sufficient) ---
    repeated_blockers = _repeated_only_reasons(report["blocked_rejected_reasons"])
    if sufficient and repeated_blockers:
        reasons = ", ".join(
            f"{d}:{reason or '(none)'} (x{n})" for (d, reason, n) in repeated_blockers[:5]
        )
        proposals.append(
            {
                "category": CATEGORY_RECURRING_BLOCKER_REVIEW,
                "severity": SEVERITY_REVIEW,
                "observation": (
                    "The same BLOCKED/REJECTED reason recurs across recorded risk "
                    "decisions."
                ),
                "evidence": (
                    f"risk_decisions BLOCKED/REJECTED grouped by reason "
                    f"(recurring, count > 1): {reasons}."
                ),
                "hypothesis": (
                    "Unproven: a recurring blocker may reflect either a genuine "
                    "data/classification issue or an overly strict rule."
                ),
                "recommendation": (
                    "human/council should review this recurring blocker pattern; "
                    "review only, do not loosen any rule or change any threshold."
                ),
                "risk_of_change": (
                    "Loosening a blocker could expose unvetted pairs. The risk "
                    "engine retains veto/reporting authority only — no execution; "
                    "ARGUS proposes review only and changes nothing."
                ),
                "suggested_test": (
                    "A human may re-examine the underlying classification/data for "
                    "the affected pairs read-only before considering any rule change."
                ),
                "required_human_or_council_approval": APPROVAL_NOTE,
            }
        )

    # --- 4. CORE / TACTICAL classification churn (only when sufficient) ---
    changed = _changed_focus_classes(report["core_tactical_stability"])
    if sufficient and changed and report["core_tactical_stability"]:
        stability = report["core_tactical_stability"]
        by_cls = {row[0]: row for row in stability}
        churn_txt = ", ".join(f"{cls}: {n} pair(s) changed class" for cls, n in changed)
        core_changed = by_cls.get("CORE", ("CORE", 0, 0, 0))[3]
        tactical_changed = by_cls.get("TACTICAL", ("TACTICAL", 0, 0, 0))[3]
        if core_changed < tactical_changed:
            stability_obs = (
                "CORE appears more stable than TACTICAL "
                f"(CORE changed={core_changed}, TACTICAL changed={tactical_changed})."
            )
        else:
            stability_obs = (
                f"Classification churn observed (CORE changed={core_changed}, "
                f"TACTICAL changed={tactical_changed})."
            )
        proposals.append(
            {
                "category": CATEGORY_CLASSIFICATION_CHURN_REVIEW,
                "severity": SEVERITY_WATCH,
                "observation": stability_obs,
                "evidence": (
                    f"strategy_observations distinct strategy_class_v2 per pair: "
                    f"{churn_txt}."
                ),
                "hypothesis": (
                    "Unproven: pairs that flip strategy_class_v2 may have borderline "
                    "metrics or noisy inputs."
                ),
                "recommendation": (
                    "human/council should collect more evidence and review the "
                    "stability pattern; do not change strategy-class rules."
                ),
                "risk_of_change": (
                    "Changing strategy-class rules on limited churn evidence could "
                    "destabilize classification. ARGUS proposes review only."
                ),
                "suggested_test": (
                    "A human may track these pairs' class across additional runs "
                    "read-only to confirm whether the churn persists."
                ),
                "required_human_or_council_approval": APPROVAL_NOTE,
            }
        )

    # --- 5. Data quality: malformed pair labels (always surfaced) ---
    malformed = report["malformed_labels"] or []
    if malformed:
        sample = ", ".join(
            f"{(r[1] if r[1] not in (None, '') else '(blank)')} (x{r[2]})"
            for r in malformed[:5]
        )
        proposals.append(
            {
                "category": CATEGORY_DATA_QUALITY_REVIEW,
                "severity": SEVERITY_REVIEW,
                "observation": (
                    f"{MALFORMED_PAIR_LABEL}: pair label(s) with a blank/missing "
                    "base or quote symbol are present in the history."
                ),
                "evidence": (
                    f"{len(malformed)} distinct malformed label(s); examples: {sample}."
                ),
                "hypothesis": (
                    "Unproven: a blank-side label likely indicates incomplete or "
                    "unverified token metadata for one side of the pair."
                ),
                "recommendation": (
                    "human/council should review these malformed labels and keep "
                    "the affected pairs quarantined from any paper-test "
                    "consideration until the token is positively identified."
                ),
                "risk_of_change": (
                    "Trusting a pair with unverified token metadata risks acting on "
                    "bad data. ARGUS proposes quarantine review only."
                ),
                "suggested_test": (
                    "A human may identify and vet the missing token symbol from a "
                    "trusted source read-only before lifting the quarantine."
                ),
                "required_human_or_council_approval": APPROVAL_NOTE,
            }
        )

    # --- 6. Safety boundary review (always last; always present) ---
    proposals.append(_build_safety_boundary_proposal(report))

    return proposals


def _repeated_only_reasons(rows):
    """Filter [(decision, reason, n), ...] to recurring entries (n > 1)."""
    return [r for r in (rows or []) if r[2] > 1]


def _build_safety_boundary_proposal(report: dict) -> dict:
    """Build the always-present SAFETY_BOUNDARY_REVIEW proposal.

    future_position_events must be 0. (A non-zero count is handled earlier as a
    hard violation and no proposal is written, so here the count is 0 or the
    table is missing.)
    """
    if not report["fpe_present"]:
        observation = (
            "future_position_events table is missing; no rows can exist, so the "
            "boundary holds, but the table could not be counted."
        )
        evidence = "future_position_events table not found in the runtime schema."
        severity = SEVERITY_REVIEW
    else:
        observation = (
            f"future_position_events count is {report['fpe_count']} (expected 0); "
            "no paper position creation, no signal generation, no live execution."
        )
        evidence = f"future_position_events row count = {report['fpe_count']}."
        severity = SEVERITY_INFO
    return {
        "category": CATEGORY_SAFETY_BOUNDARY_REVIEW,
        "severity": severity,
        "observation": observation,
        "evidence": evidence,
        "hypothesis": (
            "Unproven by nature: the boundary holds as long as no future "
            "position events are ever written in this phase."
        ),
        "recommendation": (
            "human/council should confirm the safety boundary continues to hold "
            "and that future_position_events remains 0; no action is proposed."
        ),
        "risk_of_change": (
            "Any future_position_events write would be a hard safety violation. "
            "ARGUS never writes it and proposes only continued monitoring."
        ),
        "suggested_test": (
            "Re-run the read-only dashboard/inspector and confirm "
            "future_position_events stays 0."
        ),
        "required_human_or_council_approval": APPROVAL_NOTE,
    }


def assign_ids(proposals: list, date_str: str) -> list:
    """Attach deterministic ids (ARGUS-YYYYMMDD-NNN) in the given order."""
    out = []
    for i, prop in enumerate(proposals, start=1):
        enriched = dict(prop)
        enriched["proposal_id"] = f"ARGUS-{date_str}-{i:03d}"
        out.append(enriched)
    return out


# ---------------------------------------------------------------------------
# Markdown + CSV rendering
# ---------------------------------------------------------------------------

def _md_cell(value) -> str:
    s = "" if value is None else str(value)
    return s.replace("|", "\\|").replace("\n", " ")


def _md_table(headers, rows) -> list:
    if not rows:
        return ["_(no rows)_"]
    lines = ["| " + " | ".join(str(h) for h in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return lines


def _section(lines, title):
    lines.append("")
    lines.append(f"## {title}")
    lines.append("")


def render_markdown(report: dict, proposals: list, db_path: str,
                    dashboard_dir: str, min_runs: int, date_str: str) -> str:
    """Render the full proposal-only Markdown report."""
    run_count = report["run_count"]
    sufficient = run_count >= min_runs

    lines = []
    lines.append("# ARGUS Proposal Report v0.1")
    lines.append("")
    lines.append(
        "> Name note: ARGUS was previously called Hermes during design, but was "
        "renamed to avoid confusion with external Hermes agent projects."
    )
    lines.append("")
    lines.append(f"- generated_at (UTC): {utc_now_iso()}")
    lines.append(f"- report date: {date_str}")
    lines.append(f"- safety_phase: {SAFETY_PHASE}")
    lines.append(f"- database path: {db_path}")
    lines.append(f"- dashboard dir: {dashboard_dir}")
    lines.append(f"- min_runs threshold: {min_runs}")
    lines.append("")
    lines.append(PROPOSAL_ONLY_NOTICE)

    _section(lines, "Safety Boundary")
    for line in SAFETY_BOUNDARY_LINES:
        lines.append(f"- {line}")
    lines.append("")
    lines.append(
        "ARGUS has reporting/proposal authority only — no veto, no execution. "
        "The Risk Policy Engine has veto / reporting authority only — no "
        "execution authority."
    )

    _section(lines, "Input Sources")
    lines.append(f"- runtime DuckDB (read-only): {db_path}")
    for name, status in report["required_tables"]:
        lines.append(f"  - table `{name}`: {status}")
    if report["dashboard_sources"]:
        lines.append("- dashboard files corroborated (read-only):")
        for src in report["dashboard_sources"]:
            lines.append(f"  - {src}")
    else:
        lines.append(f"- dashboard files: none found under {dashboard_dir}")

    _section(lines, "Run Count and Evidence Sufficiency")
    lines.append(f"- pipeline_runs count: {run_count}")
    lines.append(f"- min_runs threshold: {min_runs}")
    lines.append(
        f"- evidence sufficiency: {'SUFFICIENT' if sufficient else 'INSUFFICIENT'}"
    )
    if not sufficient:
        lines.append(
            "- note: evidence is insufficient — the proposal recommends collecting "
            "more runtime runs first and asserts no candidate readiness."
        )

    _section(lines, "future_position_events Count")
    if not report["fpe_present"]:
        lines.append("- future_position_events table: MISSING (no rows can exist)")
    else:
        lines.append(f"- count: {report['fpe_count']} (expected 0)")
        lines.append(
            "- status: OK (boundary holds)"
            if not report["fpe_violation"]
            else "- status: HARD SAFETY VIOLATION"
        )

    _section(lines, "Top Repeated PAPER_REVIEW_CANDIDATE Candidates")
    if report["repeated_prc"] is None:
        lines.append("_risk_decisions table missing — section skipped._")
    else:
        lines.extend(_md_table(
            ("pair_key", "pair_label", "occurrences"), report["repeated_prc"]
        ))

    _section(lines, "Recurring BLOCKED / REJECTED Reasons")
    if report["blocked_rejected_reasons"] is None:
        lines.append("_risk_decisions table missing — section skipped._")
    else:
        lines.extend(_md_table(
            ("risk_decision", "reason", "occurrences"),
            report["blocked_rejected_reasons"],
        ))

    _section(lines, "CORE / TACTICAL Stability Observations")
    if report["core_tactical_stability"] is None:
        lines.append("_strategy_observations table missing — section skipped._")
    else:
        lines.extend(_md_table(
            ("strategy_class", "pairs", "stable", "changed_class"),
            report["core_tactical_stability"],
        ))

    _section(lines, "Risk Flag Concentration Observations")
    if report["flag_concentration"] is None:
        lines.append("_risk_flags table missing — section skipped._")
    else:
        lines.extend(_md_table(
            ("risk_flag", "count"), report["flag_concentration"]
        ))

    _section(lines, "Data Quality Observations")
    if report["malformed_labels"] is None:
        lines.append("_no source tables for label inspection — section skipped._")
    elif not report["malformed_labels"]:
        lines.append(f"_No {MALFORMED_PAIR_LABEL} findings._")
    else:
        lines.append(f"Findings flagged as `{MALFORMED_PAIR_LABEL}`:")
        lines.append("")
        lines.extend(_md_table(
            ("pair_key", "pair_label", "occurrences"), report["malformed_labels"]
        ))

    _section(lines, "Proposals")
    lines.append(
        "Each proposal is a request for human/council review. ARGUS takes no "
        "action and changes nothing."
    )
    for prop in proposals:
        lines.append("")
        lines.append(f"### {prop['proposal_id']} — {prop['category']} ({prop['severity']})")
        lines.append("")
        lines.append(f"- **observation**: {prop['observation']}")
        lines.append(f"- **evidence**: {prop['evidence']}")
        lines.append(f"- **hypothesis**: {prop['hypothesis']}")
        lines.append(f"- **recommendation**: {prop['recommendation']}")
        lines.append(f"- **risk_of_change**: {prop['risk_of_change']}")
        lines.append(f"- **suggested_test**: {prop['suggested_test']}")
        lines.append(
            "- **required_human_or_council_approval**: "
            f"{prop['required_human_or_council_approval']}"
        )

    _section(lines, "Interpretation Notes")
    lines.append(INTERPRETATION_NOTE)

    return "\n".join(lines) + "\n"


def write_findings_csv(path: Path, proposals: list) -> None:
    """Write the structured findings CSV with the exact required columns."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(FINDINGS_COLUMNS)
        for prop in proposals:
            writer.writerow([prop.get(col, "") for col in FINDINGS_COLUMNS])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def print_safety_banner() -> None:
    print("------------------------------------------------------------")
    print("  ARGUS PROPOSAL REPORT v0.1 (proposal-only)")
    print("------------------------------------------------------------")
    for line in SAFETY_BANNER.splitlines():
        print(f"  {line}")
    print("------------------------------------------------------------")


def run_argus(
    db_path: str,
    dashboard_dir: str,
    out_dir: str,
    date_str: str,
    limit: int,
    min_runs: int,
    dry_run: bool,
) -> int:
    """Top-level flow used by the CLI. Returns a process exit code."""
    # --- duckdb dependency (exact message, never auto-install) ---
    try:
        require_duckdb()
    except RuntimeError as exc:
        print(str(exc))
        return 3

    # --- DB must already exist; never create it ---
    if not db_exists(db_path):
        print(
            f"ERROR: Runtime DuckDB not found: {db_path}\n"
            "ARGUS does not create or initialize the database. It reads existing "
            "runtime history only.",
            file=sys.stderr,
        )
        return 2

    conn = open_readonly(db_path)
    try:
        present = list_tables(conn)
        report = gather_report(conn, present, limit, dashboard_dir)
    finally:
        conn.close()

    out_md = Path(out_dir) / f"argus_proposal_{date_str}.md"
    out_csv = Path(out_dir) / f"argus_findings_{date_str}.csv"

    # --- Hard safety: future_position_events must be 0; else write nothing ---
    if report["fpe_violation"]:
        print(
            "HARD SAFETY VIOLATION: future_position_events count = "
            f"{report['fpe_count']} (expected 0). ARGUS writes no proposal.",
            file=sys.stderr,
        )
        return 4

    proposals = assign_ids(build_proposals(report, min_runs), date_str)
    run_count = report["run_count"]
    sufficient = run_count >= min_runs

    if dry_run:
        print("DRY RUN — no ARGUS files will be written.")
        print(f"  database read        : {db_path}")
        print(f"  dashboard dir        : {dashboard_dir}")
        print(f"  would write md       : {out_md}")
        print(f"  would write csv      : {out_csv}")
        print(f"  pipeline_runs count  : {run_count}")
        print(f"  min_runs threshold   : {min_runs}")
        print(f"  evidence sufficiency : {'SUFFICIENT' if sufficient else 'INSUFFICIENT'}")
        print(f"  future_position_events count: {report['fpe_count']} (expected 0)")
        print(f"  proposals planned    : {len(proposals)}")
        for prop in proposals:
            print(f"    - {prop['proposal_id']} {prop['category']} ({prop['severity']})")
        print("DRY RUN COMPLETE — nothing written.")
        return 0

    md = render_markdown(report, proposals, db_path, dashboard_dir, min_runs, date_str)

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    print(f"Wrote ARGUS proposal report: {out_md}")
    write_findings_csv(out_csv, proposals)
    print(f"Wrote ARGUS findings CSV: {out_csv} ({len(proposals)} proposals)")

    print(f"future_position_events count: {report['fpe_count']} (expected 0)")
    print(f"evidence sufficiency: {'SUFFICIENT' if sufficient else 'INSUFFICIENT'}")
    print(INTERPRETATION_NOTE)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "ARGUS Proposal Report v0.1 — read an existing runtime DuckDB "
            "(read-only) plus optional dashboard files and write proposal-only "
            "ARGUS reports under reports/argus/. Proposal-only; never writes "
            "the DB, never runs the pipeline, never calls the dashboard builder, "
            "no network, no scheduler, no positions, no signals, no "
            "wallet/signing/swap/LP/rebalance/live."
        )
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to the existing DuckDB database file (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--dashboard-dir",
        default=DEFAULT_DASHBOARD_DIR,
        help=(
            "Directory of read-only dashboard files to corroborate "
            f"(default: {DEFAULT_DASHBOARD_DIR})."
        ),
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Directory for ARGUS proposal outputs (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--date",
        default=None,
        metavar="YYYYMMDD",
        help="Report date for filenames and proposal ids (default: today UTC).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        metavar="N",
        help=f"Row limit for list/repeated sections (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        default=DEFAULT_MIN_RUNS,
        metavar="N",
        help=(
            "Minimum pipeline_runs for evidence sufficiency "
            f"(default: {DEFAULT_MIN_RUNS})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate DB readability and print planned outputs; write nothing.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    print_safety_banner()
    date_str = args.date or default_date_str()
    return run_argus(
        db_path=args.db_path,
        dashboard_dir=args.dashboard_dir,
        out_dir=args.out_dir,
        date_str=date_str,
        limit=args.limit,
        min_runs=args.min_runs,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
