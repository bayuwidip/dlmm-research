#!/usr/bin/env python3
"""
test_classify_strategy.py — unit test untuk classify_strategy.classify().

Stdlib-only (unittest). Tidak ada dependency eksternal, tidak baca/tulis file,
tidak ada network. Tujuannya: membuktikan cabang CORE / TACTICAL / REJECT /
NOT_EVALUATED bekerja, karena data nyata saat ini semuanya NOT_EVALUATED
(OHLCV API_ERROR) sehingga cabang lain tak teruji oleh run biasa.

Jalankan: python -m unittest tests/test_classify_strategy.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import classify_strategy as cs  # noqa: E402

NA = cs.NA


def good_pair(**overrides):
    """Pasangan dengan metrik 'layak' (lolos semua floor). Bisa di-override."""
    base = {
        "pair_label": "FOO-BAR",
        "pair_key": "mintA|mintB",
        "best_eligible_fee_pool_address": "POOL_ADDR_1",
        "max_tvl_pool_address": "POOL_ADDR_1",
        "pair_score_total": "80.0",
        "blacklisted_pool_count": "0",
        "fee_ratio_sanity_flag": "ok",
        "eligible_fee_pool_count": "3",
        "total_tvl_usd": "1000000",
        "total_volume_24h_usd": "2000000",
        "score_liquidity": "100",
        "score_volume": "100",
        "score_fee": "100",
        "score_token_quality": "80",
        "score_data_quality": "100",
    }
    base.update(overrides)
    return base


def ohlcv_row(bucket, status="OK", completeness="95"):
    return {
        "representative_pool_address": "POOL_ADDR_1",
        "ohlcv_status": status,
        "volatility_bucket": bucket,
        "data_completeness_pct": completeness,
    }


def lookup_with(bucket, **kw):
    return {"POOL_ADDR_1": ohlcv_row(bucket, **kw)}


class TestClassify(unittest.TestCase):

    def test_not_evaluated_when_no_ohlcv_entry(self):
        out = cs.classify(good_pair(), {})  # lookup kosong
        self.assertEqual(out["strategy_class_v2"], "NOT_EVALUATED")
        self.assertEqual(out["test_lane"], "NOT_EVALUATED")
        self.assertEqual(out["live_eligibility"], "NOT_EVALUATED")
        self.assertEqual(out["pair_score_v2_core"], NA)
        self.assertEqual(out["pair_score_v2_tactical"], NA)
        self.assertIn("OHLCV_UNAVAILABLE", out["risk_flags"])

    def test_not_evaluated_when_api_error(self):
        out = cs.classify(good_pair(), lookup_with("DATA_NOT_AVAILABLE",
                                                   status="API_ERROR"))
        self.assertEqual(out["strategy_class_v2"], "NOT_EVALUATED")

    def test_core_low_volatility(self):
        out = cs.classify(good_pair(), lookup_with("LOW"))
        self.assertEqual(out["strategy_class_v2"], "CORE")
        self.assertEqual(out["test_lane"], "CLEAN")
        self.assertEqual(out["pair_status_v2"], "PAPER TEST")
        self.assertEqual(out["live_eligibility"], "PAPER_TEST_ALLOWED")
        self.assertEqual(out["required_capability"], "PAPER_SIM")
        self.assertEqual(out["minimum_observation_days"], cs.OBS_DAYS_CORE)
        self.assertNotEqual(out["pair_score_v2_core"], NA)

    def test_tactical_extreme_volatility_not_reject(self):
        out = cs.classify(good_pair(), lookup_with("EXTREME"))
        self.assertEqual(out["strategy_class_v2"], "TACTICAL")
        self.assertEqual(out["test_lane"], "RISKY_BUT_INTERESTING")
        self.assertEqual(out["pair_status_v2"], "WATCHLIST")
        self.assertEqual(out["live_eligibility"], "OBSERVE_ONLY")
        self.assertEqual(out["required_capability"], "OBSERVE")
        # Tactical TIDAK boleh mengizinkan paper entry.
        self.assertNotEqual(out["live_eligibility"], "PAPER_TEST_ALLOWED")

    def test_tactical_high_volatility(self):
        out = cs.classify(good_pair(), lookup_with("HIGH"))
        self.assertEqual(out["strategy_class_v2"], "TACTICAL")

    def test_reject_extreme_plus_blacklist(self):
        out = cs.classify(good_pair(blacklisted_pool_count="1"),
                          lookup_with("EXTREME"))
        self.assertEqual(out["strategy_class_v2"], "REJECT")
        self.assertEqual(out["test_lane"], "QUARANTINE")
        self.assertEqual(out["live_eligibility"], "NOT_LIVE_ELIGIBLE")
        self.assertIn("BLACKLISTED", out["risk_flags"])

    def test_reject_low_liquidity_even_when_low_vol(self):
        # Volatilitas rendah tapi likuiditas tak layak -> severe -> REJECT.
        out = cs.classify(good_pair(total_tvl_usd="1000"), lookup_with("LOW"))
        self.assertEqual(out["strategy_class_v2"], "REJECT")
        self.assertIn("LOW_LIQUIDITY", out["risk_flags"])

    def test_reject_no_eligible_fee_pool(self):
        out = cs.classify(
            good_pair(eligible_fee_pool_count="0",
                      fee_ratio_sanity_flag="no_eligible_fee_pool"),
            lookup_with("MODERATE"))
        self.assertEqual(out["strategy_class_v2"], "REJECT")
        self.assertIn("NO_ELIGIBLE_FEE_POOL", out["risk_flags"])

    def test_core_demoted_to_watchlist_on_low_core_score(self):
        # Metrik layak (lolos floor) tapi skor dimensi rendah -> core_score < ambang.
        weak = good_pair(score_liquidity="50", score_volume="50", score_fee="40",
                         score_token_quality="40", score_data_quality="50",
                         total_tvl_usd="60000", total_volume_24h_usd="60000")
        out = cs.classify(weak, lookup_with("LOW"))
        self.assertEqual(out["strategy_class_v2"], "CORE")
        self.assertEqual(out["pair_status_v2"], "WATCHLIST")
        self.assertEqual(out["live_eligibility"], "OBSERVE_ONLY")

    def test_live_eligibility_never_live(self):
        # Apa pun input, live_eligibility tak pernah masuk set terlarang.
        forbidden = set(cs.FORBIDDEN_LIVE_ELIGIBILITY)
        for bucket in ("LOW", "MODERATE", "HIGH", "EXTREME", "DATA_NOT_AVAILABLE"):
            for bl in ("0", "1"):
                out = cs.classify(good_pair(blacklisted_pool_count=bl),
                                  lookup_with(bucket))
                self.assertNotIn(out["live_eligibility"], forbidden)
                self.assertIn(out["live_eligibility"], cs.LIVE_ELIGIBILITY)

    def test_risk_flag_count_matches_tokens(self):
        out = cs.classify(good_pair(blacklisted_pool_count="1"),
                          lookup_with("EXTREME"))
        tokens = [t for t in out["risk_flags"].split("|") if t]
        self.assertEqual(out["risk_flag_count"], len(tokens))


if __name__ == "__main__":
    unittest.main()
