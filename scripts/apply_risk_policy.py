#!/usr/bin/env python3
"""
apply_risk_policy.py — Risk Policy Engine Skeleton v0.1 (read-only).

Status: READ_ONLY · RESEARCH_ONLY · SCREENING_ONLY · PAPER_ONLY.

This is a RISK DECISION / REPORTING LAYER ONLY. It consumes the strategy
classification output (data/strategy_classification_v2.csv) and produces
explainable risk decisions. It is a transformation over data.

Core concept (target_architecture.md §8):
  The Risk Engine has VETO authority but NO execution authority. It can stop
  things and shrink things; it can never place, sign, or send anything.

It does NOT and MUST NOT:
  - create positions
  - create paper entries
  - generate ENTRY / EXIT / REBALANCE signals
  - call a wallet
  - sign transactions
  - swap
  - add / remove LP
  - rebalance
  - execute any live action
  - integrate Telegram
  - integrate a scheduler / cron / systemd
  - write to DuckDB

INPUT (not modified):
  - data/strategy_classification_v2.csv

OUTPUT (the only files this script may write, besides logs/):
  - data/risk_decisions.csv
  - reports/risk_decisions.md

This realises the first half of DEC-20260629-003: a reviewed risk policy module
comes BEFORE any execution code. This module makes no live claim and changes no
gate. PAPER_REVIEW_CANDIDATE means "eligible for FUTURE paper-simulation review
only" — it is not a paper entry, not a paper trade, and not live readiness.
"""

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "strategy_classification_v2.csv"
DEFAULT_OUTPUT = ROOT / "data" / "risk_decisions.csv"
DEFAULT_REPORT = ROOT / "reports" / "risk_decisions.md"
LOG_DIR = ROOT / "logs"

NA = "DATA_NOT_AVAILABLE"

# --- Safety phase + banner (do not weaken; preserved across all versions) ---
SAFETY_PHASE = "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY"
SAFETY_BANNER = (
    "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY\n"
    "No wallet\n"
    "No private key\n"
    "No signing\n"
    "No swap\n"
    "No LP\n"
    "No rebalance\n"
    "No live execution\n"
    "No LIVE_ELIGIBLE_*"
)

# --- Required input columns (intended schema; validated before processing) ---
REQUIRED_INPUT_COLUMNS = (
    "pair_key",
    "pair_label",
    "strategy_class_v2",
    "pair_status_v2",
    "test_lane",
    "live_eligibility",
    "required_capability",
    "risk_flag_count",
    "risk_flags",
    "v2_classification_reason",
)

# --- Output schema ---
OUT_HEADER = [
    "pair_key",
    "pair_label",
    "strategy_class_v2",
    "pair_status_v2",
    "test_lane",
    "live_eligibility",
    "required_capability",
    "risk_flag_count",
    "risk_flags",
    "risk_decision",
    "risk_action",
    "max_allowed_action",
    "risk_blockers",
    "risk_warnings",
    "risk_required_next_step",
    "risk_policy_reason",
    "safety_phase",
]

# --- Allowed output enums (the engine may only emit these) ---
RISK_DECISIONS = (
    "BLOCKED",
    "OBSERVE_ONLY",
    "PAPER_REVIEW_CANDIDATE",
    "NOT_EVALUATED",
    "REJECTED",
)
RISK_ACTIONS = (
    "NO_ACTION",
    "CONTINUE_OBSERVATION",
    "REVIEW_FOR_FUTURE_PAPER_SIMULATION",
    "FIX_DATA_OR_CLASSIFICATION",
    "REJECT",
)
MAX_ALLOWED_ACTIONS = ("NONE", "OBSERVE_ONLY", "FUTURE_PAPER_SIMULATION_REVIEW")

# --- Risk flag severity buckets ---
# Severe flags are hard blockers: the pair cannot be reviewed until resolved.
SEVERE_FLAGS = frozenset({
    "MALFORMED_PAIR_LABEL",
    "BLACKLISTED",
    "NO_ELIGIBLE_FEE_POOL",
})
# High warning flags do not hard-block but veto any paper-review candidacy
# (they force OBSERVE_ONLY at best).
HIGH_WARNING_FLAGS = frozenset({
    "LOW_LIQUIDITY",
    "LOW_VOLUME",
    "DATA_QUALITY_NA",
    "LOW_DATA_COMPLETENESS",
    "EXTREME_VOLATILITY",
    "EXTREME_RANGE_RISK",
})


def log(msg):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "risk_policy.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def parse_flags(flags_str):
    """Split a pipe-joined risk_flags string into a clean list.

    Treats 'none', '', and DATA_NOT_AVAILABLE as no-flags.
    """
    if flags_str is None:
        return []
    tokens = []
    for raw in str(flags_str).split("|"):
        t = raw.strip()
        if t and t != "none" and t != NA:
            tokens.append(t)
    return tokens


def _join(items):
    return "|".join(items) if items else "none"


def decide_row(row):
    """Apply the risk policy to one input row (dict).

    Returns a dict with the decision fields:
      risk_decision, risk_action, max_allowed_action,
      risk_blockers, risk_warnings, risk_required_next_step, risk_policy_reason

    The engine has veto authority only. It never emits an execution/entry value.
    Precedence (highest first) keeps the most conservative outcome:
      1. classifier REJECT
      2. severe flag veto (BLOCKED)
      3. quarantine / not-live-eligible veto (BLOCKED)
      4. NOT_EVALUATED (insufficient data)
      5. paper-review candidacy (only when fully clean)
      6. observe-only
      7. conservative fallback
    """
    cls = (row.get("strategy_class_v2") or "").strip()
    status = (row.get("pair_status_v2") or "").strip()
    lane = (row.get("test_lane") or "").strip()
    elig = (row.get("live_eligibility") or "").strip()

    flags = set(parse_flags(row.get("risk_flags")))
    severe = sorted(flags & SEVERE_FLAGS)
    high = sorted(flags & HIGH_WARNING_FLAGS)

    # Collect blockers/warnings for explainability (independent of which
    # branch ultimately fires).
    blockers = []
    if cls == "REJECT" or status == "REJECT":
        blockers.append("CLASSIFIED_REJECT")
    if lane == "QUARANTINE":
        blockers.append("TEST_LANE_QUARANTINE")
    if elig == "NOT_LIVE_ELIGIBLE":
        blockers.append("NOT_LIVE_ELIGIBLE")
    blockers.extend(severe)
    warnings = list(high)

    # --- 1. Classifier already rejected the pair ---
    if cls == "REJECT" or status == "REJECT":
        return {
            "risk_decision": "REJECTED",
            "risk_action": "REJECT",
            "max_allowed_action": "NONE",
            "risk_blockers": _join(blockers),
            "risk_warnings": _join(warnings),
            "risk_required_next_step": (
                "No action. Pair was rejected by strategy classification. "
                "Do not observe-for-entry and do not consider for paper review."
            ),
            "risk_policy_reason": (
                f"REJECTED: strategy_class_v2='{cls}', pair_status_v2='{status}'. "
                f"Classifier reject is upheld by the risk engine."
            ),
        }

    # --- 2. Severe risk flag veto (hard block) ---
    if severe:
        if "MALFORMED_PAIR_LABEL" in severe:
            action = "FIX_DATA_OR_CLASSIFICATION"
            nxt = (
                "Fix data/classification: positively identify and verify the "
                "missing/blank token symbol before any further consideration. "
                "Quarantined from paper-review until resolved."
            )
        else:
            action = "REJECT"
            nxt = (
                "Quarantine. Resolve the severe risk flag(s) "
                f"{severe} before the pair can re-enter screening. "
                "Not eligible for review."
            )
        return {
            "risk_decision": "BLOCKED",
            "risk_action": action,
            "max_allowed_action": "NONE",
            "risk_blockers": _join(blockers),
            "risk_warnings": _join(warnings),
            "risk_required_next_step": nxt,
            "risk_policy_reason": (
                f"BLOCKED: severe risk flag(s) {severe} present. The risk engine "
                f"vetoes any review while a severe flag is unresolved."
            ),
        }

    # --- 3. Quarantine / not-live-eligible veto (hard block) ---
    if lane == "QUARANTINE" or elig == "NOT_LIVE_ELIGIBLE":
        return {
            "risk_decision": "BLOCKED",
            "risk_action": "REJECT",
            "max_allowed_action": "NONE",
            "risk_blockers": _join(blockers),
            "risk_warnings": _join(warnings),
            "risk_required_next_step": (
                "Blocked by classification routing (quarantine / not-live-eligible). "
                "No action; not eligible for review."
            ),
            "risk_policy_reason": (
                f"BLOCKED: test_lane='{lane}', live_eligibility='{elig}'. The risk "
                f"engine upholds the classifier veto."
            ),
        }

    # --- 4. Insufficient data to evaluate ---
    if cls == "NOT_EVALUATED" or elig == "NOT_EVALUATED":
        return {
            "risk_decision": "NOT_EVALUATED",
            "risk_action": "NO_ACTION",
            "max_allowed_action": "NONE",
            "risk_blockers": _join(blockers),
            "risk_warnings": _join(warnings),
            "risk_required_next_step": (
                "No action. Insufficient data to evaluate (classification/OHLCV "
                "incomplete). Re-evaluate when data becomes available."
            ),
            "risk_policy_reason": (
                f"NOT_EVALUATED: strategy_class_v2='{cls}', live_eligibility='{elig}'. "
                f"The risk engine cannot evaluate a pair with no usable classification."
            ),
        }

    # --- 5. Paper-review candidacy (only when fully clean) ---
    paper_clean = (
        cls == "CORE"
        and elig == "PAPER_TEST_ALLOWED"
        and lane == "CLEAN"
        and not blockers
        and not high
    )
    if paper_clean:
        return {
            "risk_decision": "PAPER_REVIEW_CANDIDATE",
            "risk_action": "REVIEW_FOR_FUTURE_PAPER_SIMULATION",
            "max_allowed_action": "FUTURE_PAPER_SIMULATION_REVIEW",
            "risk_blockers": _join(blockers),
            "risk_warnings": _join(warnings),
            "risk_required_next_step": (
                "Eligible for FUTURE paper-simulation REVIEW only. This is NOT a "
                "paper entry, NOT a paper trade, and NOT live readiness. No position "
                "is created and no order is placed."
            ),
            "risk_policy_reason": (
                f"PAPER_REVIEW_CANDIDATE: CORE + CLEAN lane + PAPER_TEST_ALLOWED with "
                f"no blockers and no high-warning flags. Future paper-simulation "
                f"review only; the risk engine grants no execution capability."
            ),
        }

    # --- 6. Observe-only (tactical / observe-eligible / high warnings) ---
    if (
        cls == "TACTICAL"
        or elig == "OBSERVE_ONLY"
        or lane == "RISKY_BUT_INTERESTING"
        or high
    ):
        if high and cls == "CORE" and lane == "CLEAN":
            reason = (
                f"OBSERVE_ONLY: would-be paper-review candidate DOWNGRADED because "
                f"high-warning flag(s) {high} are present. Observation only."
            )
        else:
            reason = (
                f"OBSERVE_ONLY: strategy_class_v2='{cls}', live_eligibility='{elig}', "
                f"test_lane='{lane}', high-warning flags={high}. Reporting/watchlist "
                f"only — no paper entry."
            )
        return {
            "risk_decision": "OBSERVE_ONLY",
            "risk_action": "CONTINUE_OBSERVATION",
            "max_allowed_action": "OBSERVE_ONLY",
            "risk_blockers": _join(blockers),
            "risk_warnings": _join(warnings),
            "risk_required_next_step": (
                "Continue observation only. No paper entry, no execution. Re-review "
                "after the observation window; do not escalate from this layer."
            ),
            "risk_policy_reason": reason,
        }

    # --- 7. Conservative fallback (unrecognized combination -> no action) ---
    return {
        "risk_decision": "NOT_EVALUATED",
        "risk_action": "NO_ACTION",
        "max_allowed_action": "NONE",
        "risk_blockers": _join(blockers),
        "risk_warnings": _join(warnings),
        "risk_required_next_step": (
            "No action. Unrecognized classification combination; conservative "
            "no-action stance. Re-classify before any further consideration."
        ),
        "risk_policy_reason": (
            f"NOT_EVALUATED (fallback): unrecognized combination "
            f"strategy_class_v2='{cls}', pair_status_v2='{status}', test_lane='{lane}', "
            f"live_eligibility='{elig}'. The risk engine defaults to no action."
        ),
    }


def build_output_row(row):
    """Combine passthrough input fields with the computed decision."""
    decision = decide_row(row)
    out = {
        "pair_key": row.get("pair_key", NA),
        "pair_label": row.get("pair_label", NA),
        "strategy_class_v2": row.get("strategy_class_v2", NA),
        "pair_status_v2": row.get("pair_status_v2", NA),
        "test_lane": row.get("test_lane", NA),
        "live_eligibility": row.get("live_eligibility", NA),
        "required_capability": row.get("required_capability", NA),
        "risk_flag_count": row.get("risk_flag_count", NA),
        "risk_flags": row.get("risk_flags", NA),
        "safety_phase": SAFETY_PHASE,
    }
    out.update(decision)
    return out


def validate_columns(header):
    """Return the list of required columns missing from header."""
    return [c for c in REQUIRED_INPUT_COLUMNS if c not in header]


def read_input(input_path):
    """Read the strategy classification CSV.

    Returns (header, rows). Raises FileNotFoundError / ValueError on problems so
    main() can convert them to a non-zero exit.
    """
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = list(reader)
    missing = validate_columns(header)
    if missing:
        raise ValueError(f"input is missing required columns: {missing}")
    return header, rows


def compute_decisions(rows):
    """Map input rows to fully-built output rows."""
    return [build_output_row(r) for r in rows]


def write_csv(out_rows, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_HEADER)
        w.writeheader()
        for r in out_rows:
            w.writerow({k: r.get(k, NA) for k in OUT_HEADER})


def _top_counter(out_rows, field):
    c = Counter()
    for r in out_rows:
        for t in parse_flags(r.get(field)):
            c[t] += 1
    return c


def build_report(out_rows, input_path, output_path):
    """Build the Markdown report text (pure function for testability)."""
    decision_counts = Counter(r["risk_decision"] for r in out_rows)
    action_counts = Counter(r["risk_action"] for r in out_rows)
    blocker_counts = _top_counter(out_rows, "risk_blockers")
    warning_counts = _top_counter(out_rows, "risk_warnings")

    lines = []
    lines.append("# Risk Decisions Report")
    lines.append("")
    lines.append(f"- Generated (UTC): {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Input: `{input_path}`")
    lines.append(f"- Output: `{output_path}`")
    lines.append(f"- Total rows: {len(out_rows)}")
    lines.append("")
    lines.append("## Safety banner")
    lines.append("")
    lines.append("```")
    lines.append(SAFETY_BANNER)
    lines.append("```")
    lines.append("")
    lines.append(
        "> The Risk Engine has VETO authority but NO execution authority. It can "
        "stop and shrink; it can never place, sign, or send anything."
    )
    lines.append("")

    lines.append("## Counts by risk_decision")
    lines.append("")
    for d in RISK_DECISIONS:
        lines.append(f"- {d}: {decision_counts.get(d, 0)}")
    lines.append("")

    lines.append("## Counts by risk_action")
    lines.append("")
    for a in RISK_ACTIONS:
        lines.append(f"- {a}: {action_counts.get(a, 0)}")
    lines.append("")

    lines.append("## Top blockers")
    lines.append("")
    top_block = [(k, v) for k, v in blocker_counts.most_common() if k != "none"]
    if top_block:
        for k, v in top_block:
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Top warnings")
    lines.append("")
    top_warn = [(k, v) for k, v in warning_counts.most_common() if k != "none"]
    if top_warn:
        for k, v in top_warn:
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- none")
    lines.append("")

    def section(title, predicate, note):
        lines.append(f"## {title}")
        lines.append("")
        lines.append(note)
        lines.append("")
        subset = [r for r in out_rows if predicate(r)]
        if not subset:
            lines.append("- none")
            lines.append("")
            return
        lines.append("| Pair | Pair key | Class | Decision | Action | Max allowed | Next step |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in subset:
            lines.append(
                f"| {r['pair_label']} | {r['pair_key']} | {r['strategy_class_v2']} "
                f"| {r['risk_decision']} | {r['risk_action']} "
                f"| {r['max_allowed_action']} | {r['risk_required_next_step']} |"
            )
        lines.append("")

    section(
        "Paper review candidates",
        lambda r: r["risk_decision"] == "PAPER_REVIEW_CANDIDATE",
        "> FUTURE paper-simulation REVIEW only. NOT a paper entry, NOT a paper "
        "trade, NOT live readiness.",
    )
    section(
        "Observe-only",
        lambda r: r["risk_decision"] == "OBSERVE_ONLY",
        "> Reporting/watchlist only — continue observation, no paper entry.",
    )
    section(
        "Rejected / blocked",
        lambda r: r["risk_decision"] in ("REJECTED", "BLOCKED"),
        "> Vetoed by the risk engine — not eligible for review.",
    )

    lines.append("---")
    lines.append("")
    lines.append(
        "**This report does not authorize paper entries, live entries, LP actions, "
        "swaps, rebalances, wallet use, signing, or execution.**"
    )
    lines.append("")
    lines.append(f"_Phase: {SAFETY_PHASE}. Research only._")
    return "\n".join(lines)


def write_report(out_rows, input_path, output_path, report_path):
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = build_report(out_rows, input_path, output_path)
    path.write_text(text, encoding="utf-8")


def summarize(out_rows):
    """Return a short human-readable summary string for stdout (dry-run)."""
    decision_counts = Counter(r["risk_decision"] for r in out_rows)
    parts = [f"{d}={decision_counts.get(d, 0)}" for d in RISK_DECISIONS]
    return f"rows={len(out_rows)} | " + " ".join(parts)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Risk Policy Engine Skeleton v0.1 (read-only; veto-only).",
    )
    p.add_argument("--input", default=str(DEFAULT_INPUT),
                   help="path to strategy_classification_v2.csv")
    p.add_argument("--output", default=str(DEFAULT_OUTPUT),
                   help="path to write risk_decisions.csv")
    p.add_argument("--report", default=str(DEFAULT_REPORT),
                   help="path to write risk_decisions.md")
    p.add_argument("--dry-run", action="store_true",
                   help="validate + compute + print summary; write nothing")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    log("=== Risk Policy Engine Skeleton v0.1 start (read-only, veto-only) ===")
    log(f"Phase: {SAFETY_PHASE}")

    try:
        _header, rows = read_input(args.input)
    except FileNotFoundError as exc:
        log(f"FATAL: {exc}")
        return 1
    except ValueError as exc:
        log(f"FATAL: {exc}")
        return 1

    if not rows:
        log("FATAL: input has no data rows (header only). Nothing to evaluate.")
        return 1

    out_rows = compute_decisions(rows)

    if args.dry_run:
        log("DRY RUN: no files written.")
        print(summarize(out_rows))
        log("=== Risk Policy Engine dry-run complete ===")
        return 0

    write_csv(out_rows, args.output)
    write_report(out_rows, args.input, args.output, args.report)

    log(f"CSV written: {args.output} ({len(out_rows)} rows)")
    log(f"Report written: {args.report}")
    log(summarize(out_rows))
    log("=== Risk Policy Engine Skeleton v0.1 complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
