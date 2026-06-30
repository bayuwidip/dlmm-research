#!/usr/bin/env python3
"""
test_validate_risk_decisions.py — tests for validate_risk_decisions() in
scripts/validate_watchlist.py.

These tests verify the read-only safety gate over the Risk Policy Engine output
(data/risk_decisions.csv). The validator never creates positions, never emits
signals, and never authorizes wallet/signing/swap/LP/rebalance/live execution;
these tests only confirm it REJECTS any such authorization leaking into the CSV.
"""

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "validate_watchlist.py"

# Load the validator module by path (scripts/ is not a package). Importing must
# not run the __main__ block.
_spec = importlib.util.spec_from_file_location("validate_watchlist", MODULE_PATH)
vw = importlib.util.module_from_spec(_spec)
sys.modules["validate_watchlist"] = vw
_spec.loader.exec_module(vw)


SAFETY_PHASE = "READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY"

# Column order matches the engine's OUT_HEADER / RISK_REQUIRED_COLUMNS.
RISK_COLUMNS = [
    "pair_key", "pair_label", "strategy_class_v2", "pair_status_v2",
    "test_lane", "live_eligibility", "required_capability",
    "risk_flag_count", "risk_flags",
    "risk_decision", "risk_action", "max_allowed_action",
    "risk_blockers", "risk_warnings", "risk_required_next_step",
    "risk_policy_reason", "safety_phase",
]


def base_row(**overrides):
    """A neutral, valid NOT_EVALUATED row; override fields per test."""
    row = {
        "pair_key": "AAA|BBB",
        "pair_label": "AAA-BBB",
        "strategy_class_v2": "NOT_EVALUATED",
        "pair_status_v2": "NOT_EVALUATED",
        "test_lane": "NOT_EVALUATED",
        "live_eligibility": "NOT_EVALUATED",
        "required_capability": "NONE",
        "risk_flag_count": "1",
        "risk_flags": "OHLCV_UNAVAILABLE",
        "risk_decision": "NOT_EVALUATED",
        "risk_action": "NO_ACTION",
        "max_allowed_action": "NONE",
        "risk_blockers": "none",
        "risk_warnings": "none",
        "risk_required_next_step": "No action. Insufficient data to evaluate.",
        "risk_policy_reason": "NOT_EVALUATED: no usable classification.",
        "safety_phase": SAFETY_PHASE,
    }
    row.update(overrides)
    return row


PAPER_REVIEW = dict(
    strategy_class_v2="CORE", pair_status_v2="PAPER TEST", test_lane="CLEAN",
    live_eligibility="PAPER_TEST_ALLOWED", required_capability="PAPER_SIM",
    risk_flag_count="0", risk_flags="none",
    risk_decision="PAPER_REVIEW_CANDIDATE",
    risk_action="REVIEW_FOR_FUTURE_PAPER_SIMULATION",
    max_allowed_action="FUTURE_PAPER_SIMULATION_REVIEW",
    risk_blockers="none", risk_warnings="none",
    risk_required_next_step=(
        "Eligible for FUTURE paper-simulation REVIEW only. This is NOT a paper "
        "entry, NOT a paper trade, and NOT live readiness."
    ),
    risk_policy_reason=(
        "PAPER_REVIEW_CANDIDATE: CORE + CLEAN. Future paper-simulation review only."
    ),
)
OBSERVE = dict(
    strategy_class_v2="TACTICAL", pair_status_v2="WATCHLIST",
    test_lane="RISKY_BUT_INTERESTING", live_eligibility="OBSERVE_ONLY",
    required_capability="OBSERVE", risk_flag_count="1",
    risk_flags="HIGH_VOLATILITY",
    risk_decision="OBSERVE_ONLY", risk_action="CONTINUE_OBSERVATION",
    max_allowed_action="OBSERVE_ONLY", risk_blockers="none",
    risk_warnings="none",
    risk_required_next_step="Continue observation only. No paper entry.",
    risk_policy_reason="OBSERVE_ONLY: tactical, reporting/watchlist only.",
)
REJECTED = dict(
    strategy_class_v2="REJECT", pair_status_v2="REJECT", test_lane="QUARANTINE",
    live_eligibility="NOT_LIVE_ELIGIBLE", required_capability="NONE",
    risk_flag_count="1", risk_flags="LOW_DATA_COMPLETENESS",
    risk_decision="REJECTED", risk_action="REJECT", max_allowed_action="NONE",
    risk_blockers="CLASSIFIED_REJECT", risk_warnings="none",
    risk_required_next_step="No action. Rejected by classification.",
    risk_policy_reason="REJECTED: classifier reject upheld.",
)
BLOCKED = dict(
    strategy_class_v2="NOT_EVALUATED", pair_status_v2="NOT_EVALUATED",
    test_lane="QUARANTINE", live_eligibility="NOT_LIVE_ELIGIBLE",
    required_capability="NONE", risk_flag_count="1",
    risk_flags="NO_ELIGIBLE_FEE_POOL",
    risk_decision="BLOCKED", risk_action="REJECT", max_allowed_action="NONE",
    risk_blockers="NO_ELIGIBLE_FEE_POOL", risk_warnings="none",
    risk_required_next_step="Quarantine. Resolve severe flag.",
    risk_policy_reason="BLOCKED: severe risk flag present.",
)


def write_risk_csv(path, rows, columns=RISK_COLUMNS):
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in columns})


class TestValidRiskDecisions(unittest.TestCase):
    def test_valid_csv_passes(self):
        rows = [base_row(**PAPER_REVIEW), base_row(**OBSERVE),
                base_row(**REJECTED), base_row(**BLOCKED), base_row()]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, rows)
            self.assertEqual(vw.validate_risk_decisions(path=p), 0)


class TestFileAndStructure(unittest.TestCase):
    def test_missing_file_fails(self):
        # The risk policy layer (scripts/apply_risk_policy.py) exists, so a
        # missing output CSV is a failure, not a skip.
        self.assertTrue(vw.RISK_POLICY_SCRIPT_PATH.exists())
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "does_not_exist.csv"
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_empty_csv_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            p.write_text("", encoding="utf-8")
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_header_only_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, [])  # header only
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_missing_required_column_fails(self):
        cols = [c for c in RISK_COLUMNS if c != "risk_decision"]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, [base_row()], columns=cols)
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)


class TestEnumValidation(unittest.TestCase):
    def _fails(self, **overrides):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, [base_row(**overrides)])
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_invalid_risk_decision_fails(self):
        self._fails(risk_decision="MAYBE_LATER")

    def test_invalid_risk_action_fails(self):
        # Keep decision NOT_EVALUATED but corrupt action enum only.
        self._fails(risk_action="GO_LIVE")

    def test_invalid_max_allowed_action_fails(self):
        self._fails(max_allowed_action="LIVE")

    def test_invalid_safety_phase_fails(self):
        self._fails(safety_phase="READ_ONLY")


class TestPaperReviewCandidate(unittest.TestCase):
    def _fails(self, **overrides):
        merged = dict(PAPER_REVIEW)
        merged.update(overrides)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, [base_row(**merged)])
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_paper_review_with_paper_entry_fails(self):
        self._fails(risk_required_next_step="PAPER_ENTRY authorized now")

    def test_paper_review_with_live_entry_fails(self):
        self._fails(risk_policy_reason="LIVE_ENTRY approved")

    def test_paper_review_wrong_action_fails(self):
        self._fails(risk_action="NO_ACTION")

    def test_paper_review_wrong_max_fails(self):
        self._fails(max_allowed_action="OBSERVE_ONLY")

    def test_paper_review_without_future_review_wording_fails(self):
        self._fails(
            risk_required_next_step="Go ahead.",
            risk_policy_reason="Looks good.",
        )


class TestObserveAndNotEvaluated(unittest.TestCase):
    def test_observe_only_wrong_max_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, [base_row(**{**OBSERVE,
                                           "max_allowed_action": "NONE"})])
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_not_evaluated_non_none_max_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, [base_row(max_allowed_action="OBSERVE_ONLY")])
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)


class TestHardBlockFlags(unittest.TestCase):
    def test_malformed_pair_label_with_review_action_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            row = base_row(**{**PAPER_REVIEW,
                              "risk_flags": "MALFORMED_PAIR_LABEL",
                              "risk_flag_count": "1"})
            write_risk_csv(p, [row])
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_blacklisted_with_review_action_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            row = base_row(**{**PAPER_REVIEW,
                              "risk_flags": "BLACKLISTED",
                              "risk_flag_count": "1"})
            write_risk_csv(p, [row])
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_malformed_pair_label_blocked_passes(self):
        # The safe shape: hard-block flag with BLOCKED + NONE is valid.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            row = base_row(**{**BLOCKED,
                              "risk_flags": "MALFORMED_PAIR_LABEL",
                              "risk_action": "FIX_DATA_OR_CLASSIFICATION"})
            write_risk_csv(p, [row])
            self.assertEqual(vw.validate_risk_decisions(path=p), 0)


class TestLiveEligibility(unittest.TestCase):
    def test_live_eligible_grant_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, [base_row(
                live_eligibility="LIVE_ELIGIBLE_TINY_SIZE")])
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_bare_live_eligible_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, [base_row(live_eligibility="LIVE_ELIGIBLE")])
            self.assertEqual(vw.validate_risk_decisions(path=p), 1)

    def test_not_live_eligible_is_allowed(self):
        # The negation NOT_LIVE_ELIGIBLE must not be a false positive.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "risk_decisions.csv"
            write_risk_csv(p, [base_row(**REJECTED)])
            self.assertEqual(vw.validate_risk_decisions(path=p), 0)


class TestMainPathWiring(unittest.TestCase):
    def test_main_block_includes_risk_validation(self):
        # The __main__ block must call validate_risk_decisions() and fold its
        # exit code into sys.exit so the gate is reachable in CI.
        src = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("rc_risk = validate_risk_decisions()", src)
        self.assertIn("rc_risk", src.split("sys.exit", 1)[1])

    def test_validator_function_is_defined(self):
        self.assertTrue(callable(vw.validate_risk_decisions))


if __name__ == "__main__":
    unittest.main()
