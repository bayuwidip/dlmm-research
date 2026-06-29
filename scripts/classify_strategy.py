#!/usr/bin/env python3
"""
classify_strategy.py — Strategy Classification v0.2 (pair-level).

Status: READ_ONLY · RESEARCH_ONLY · SCREENING_ONLY · PAPER_ONLY.
Tidak ada wallet, private key, transaction signing, swap, add/remove LP,
rebalance, atau live execution. Skrip ini HANYA membaca dua CSV hasil pipeline
dan menulis satu CSV klasifikasi + satu report. Murni transformasi data.

INPUT (tidak dimodifikasi):
  - data/pair_watchlist.csv     (primary view; satu baris per pasangan)
  - data/ohlcv_top_pairs.csv    (metrik OHLCV; hanya Top 20 representative pool)

OUTPUT:
  - data/strategy_classification_v2.csv
  - reports/strategy_classification_v2.md

PRINSIP:
  - OHLCV tidak tersedia / bukan OK  -> strategy_class_v2 = NOT_EVALUATED
    (volatilitas tak terukur tidak boleh jadi REJECT).
  - Volatilitas EXTREME TIDAK otomatis REJECT. Ia bisa TACTICAL bila likuiditas,
    volume, kualitas fee, dan kualitas data layak. REJECT hanya bila ada isu berat:
    blacklist, tidak ada pool fee-eligible, likuiditas/volume tak layak, atau
    isu data berat.
  - TACTICAL = reporting/watchlist saja. Tidak ada izin paper entry / live /
    wallet / execution / LP / rebalance.
  - Fase sekarang: live_eligibility TIDAK PERNAH menjadi LIVE_ELIGIBLE_*.
  - Field tak tersedia ditulis DATA_NOT_AVAILABLE (bukan tebakan, bukan kosong).

Join INPUT: representative pool address (best_eligible dulu, fallback max_tvl),
mengikuti pick_pool() di fetch_ohlcv_top_pairs.py agar konsisten 1:1.
"""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAIR_CSV = ROOT / "data" / "pair_watchlist.csv"
OHLCV_CSV = ROOT / "data" / "ohlcv_top_pairs.csv"
OUT_CSV = ROOT / "data" / "strategy_classification_v2.csv"
REPORT_PATH = ROOT / "reports" / "strategy_classification_v2.md"
LOG_DIR = ROOT / "logs"

NA = "DATA_NOT_AVAILABLE"

# --- Enum yang diizinkan (final, sesuai keputusan v0.2) ---
STRATEGY_CLASSES = ("CORE", "TACTICAL", "REJECT", "NOT_EVALUATED")
TEST_LANES = ("CLEAN", "RISKY_BUT_INTERESTING", "QUARANTINE", "NOT_EVALUATED")
# Catatan: LIVE_ELIGIBLE_* sengaja TIDAK ada di set ini (fase PAPER_ONLY).
LIVE_ELIGIBILITY = ("NOT_EVALUATED", "OBSERVE_ONLY", "PAPER_TEST_ALLOWED",
                    "NOT_LIVE_ELIGIBLE")
REQUIRED_CAPABILITIES = ("NONE", "OBSERVE", "PAPER_SIM")
FORBIDDEN_LIVE_ELIGIBILITY = ("LIVE_ELIGIBLE_TINY_SIZE", "LIVE_ELIGIBLE_LIMITED",
                              "LIVE_ELIGIBLE_FULL")

# --- Ambang screening v0.2 (konstanta bernama; tidak ada magic number inline) ---
FLOOR_TVL = 50_000          # di bawah ini -> likuiditas tak layak (severe)
FLOOR_VOL = 50_000          # di bawah ini -> volume tak layak (severe)
MIN_DATA_COMPLETENESS = 50.0  # % candle minimal agar data dianggap layak (severe bila kurang)
PAPER_THRESHOLD_CORE = 70.0   # pair_score_v2_core minimal agar CORE naik ke PAPER TEST
OBS_DAYS_CORE = 14            # jendela observasi minimal sebelum eskalasi (forward-looking)
OBS_DAYS_TACTICAL = 30       # tactical lebih volatil -> observasi lebih lama

# Skor volatilitas per-bucket untuk dua lane (deterministik).
VOL_SCORE_CORE = {"LOW": 100.0, "MODERATE": 75.0, "HIGH": 40.0, "EXTREME": 15.0}
VOL_SCORE_TACTICAL = {"LOW": 30.0, "MODERATE": 60.0, "HIGH": 90.0, "EXTREME": 100.0}

# Flag risiko yang dianggap "berat" -> memicu REJECT (gabungan, bukan volatilitas saja).
SEVERE_FLAGS = frozenset({
    "BLACKLISTED", "NO_ELIGIBLE_FEE_POOL", "LOW_LIQUIDITY", "LOW_VOLUME",
    "DATA_QUALITY_NA", "LOW_DATA_COMPLETENESS",
})

OUT_HEADER = [
    "pair_label", "pair_key", "representative_pool_address",
    "ohlcv_status", "ohlcv_volatility_bucket", "pair_score_total_v1",
    "strategy_class_v2", "pair_score_v2_core", "pair_score_v2_tactical",
    "pair_status_v2", "risk_flag_count", "risk_flags", "test_lane",
    "live_eligibility", "minimum_observation_days", "required_capability",
    "v2_classification_reason",
]


def log(msg):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "strategy_classifier.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def fnum(value):
    """Float aman; None jika bukan angka (termasuk DATA_NOT_AVAILABLE/'')."""
    try:
        if value is None:
            return None
        s = str(value).strip()
        if s == "" or s == NA:
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def pick_representative_address(prow):
    """
    Pilih representative pool address: best_eligible dulu, fallback max_tvl.
    Mengikuti pick_pool() di fetch_ohlcv_top_pairs.py agar join 1:1 konsisten.
    Mengembalikan (address_or_NA, source_or_NA).
    """
    be = (prow.get("best_eligible_fee_pool_address") or "").strip()
    if be and be != NA:
        return be, "best_eligible_fee_pool_address"
    mt = (prow.get("max_tvl_pool_address") or "").strip()
    if mt and mt != NA:
        return mt, "max_tvl_pool_address"
    return NA, NA


def load_ohlcv_lookup():
    """Bangun lookup address -> baris OHLCV. Mengembalikan {} bila file tak ada."""
    lookup = {}
    if not OHLCV_CSV.exists():
        log(f"CATATAN: {OHLCV_CSV.name} belum ada -> semua pasangan NOT_EVALUATED.")
        return lookup
    with OHLCV_CSV.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            addr = (r.get("representative_pool_address") or "").strip()
            if addr and addr != NA:
                lookup[addr] = r
    return lookup


def compute_risk_flags(prow, orow):
    """
    Kumpulkan flag risiko struktural (pair) + turunan OHLCV (bila ada).
    orow boleh None (OHLCV tidak tersedia). Mengembalikan list flag (urut stabil).
    """
    flags = []

    # --- Struktural, dari pair_watchlist (selalu bisa dihitung) ---
    blacklisted = fnum(prow.get("blacklisted_pool_count"))
    if blacklisted is not None and blacklisted > 0:
        flags.append("BLACKLISTED")

    sanity = (prow.get("fee_ratio_sanity_flag") or "").strip()
    elig = fnum(prow.get("eligible_fee_pool_count"))
    if (elig is not None and elig == 0) or sanity == "no_eligible_fee_pool":
        flags.append("NO_ELIGIBLE_FEE_POOL")

    tvl = fnum(prow.get("total_tvl_usd"))
    if tvl is None or tvl < FLOOR_TVL:
        flags.append("LOW_LIQUIDITY")

    vol = fnum(prow.get("total_volume_24h_usd"))
    if vol is None or vol < FLOOR_VOL:
        flags.append("LOW_VOLUME")

    if sanity == "low_tvl_distortion":
        flags.append("FEE_TVL_DISTORTION")
    if sanity == NA:
        flags.append("DATA_QUALITY_NA")

    # --- Turunan OHLCV (hanya bila OHLCV OK) ---
    if orow is None:
        flags.append("OHLCV_UNAVAILABLE")
        return flags

    status = (orow.get("ohlcv_status") or "").strip()
    bucket = (orow.get("ohlcv_volatility_bucket") or "").strip()  # placeholder; diisi caller
    if status != "OK" or bucket == NA or bucket == "":
        flags.append("OHLCV_UNAVAILABLE")
        return flags

    if bucket == "EXTREME":
        flags.append("EXTREME_VOLATILITY")
    elif bucket == "HIGH":
        flags.append("HIGH_VOLATILITY")

    completeness = fnum(orow.get("data_completeness_pct"))
    if completeness is None or completeness < MIN_DATA_COMPLETENESS:
        flags.append("LOW_DATA_COMPLETENESS")

    return flags


def score_v2(prow, vol_bucket):
    """
    Hitung (pair_score_v2_core, pair_score_v2_tactical) dari field numerik yang
    tersedia. Hanya dipanggil saat OHLCV OK & bucket valid.
    """
    s_liq = fnum(prow.get("score_liquidity")) or 0.0
    s_vol = fnum(prow.get("score_volume")) or 0.0
    s_fee = fnum(prow.get("score_fee")) or 0.0
    s_tok = fnum(prow.get("score_token_quality")) or 0.0
    s_data = fnum(prow.get("score_data_quality")) or 0.0
    vc = VOL_SCORE_CORE.get(vol_bucket, 0.0)
    vt = VOL_SCORE_TACTICAL.get(vol_bucket, 0.0)

    core = (0.25 * s_liq + 0.15 * s_vol + 0.20 * s_fee +
            0.10 * s_tok + 0.10 * s_data + 0.20 * vc)
    tactical = (0.20 * s_liq + 0.20 * s_vol + 0.20 * s_fee +
                0.05 * s_tok + 0.10 * s_data + 0.25 * vt)
    return round(core, 2), round(tactical, 2)


def clamp_live_eligibility(value):
    """Pengaman keras: live_eligibility tidak boleh LIVE_ELIGIBLE_* di fase ini."""
    if value in FORBIDDEN_LIVE_ELIGIBILITY or value not in LIVE_ELIGIBILITY:
        return "NOT_LIVE_ELIGIBLE"
    return value


def classify(prow, ohlcv_lookup):
    """Klasifikasikan satu pasangan. Mengembalikan dict baris output."""
    pair_label = prow.get("pair_label", NA)
    pair_key = prow.get("pair_key", NA)
    addr, _source = pick_representative_address(prow)
    pair_score_v1 = prow.get("pair_score_total", NA)

    orow = ohlcv_lookup.get(addr) if addr != NA else None
    ohlcv_status = (orow.get("ohlcv_status").strip()
                    if orow and orow.get("ohlcv_status") else
                    ("DATA_NOT_AVAILABLE" if addr == NA else "DATA_NOT_AVAILABLE"))
    vol_bucket = (orow.get("volatility_bucket").strip()
                  if orow and orow.get("volatility_bucket") else NA)

    # Susun objek OHLCV ternormalisasi untuk perhitungan flag (nama field disamakan).
    norm_orow = None
    if orow is not None:
        norm_orow = dict(orow)
        norm_orow["ohlcv_volatility_bucket"] = vol_bucket

    flags = compute_risk_flags(prow, norm_orow)

    base = {
        "pair_label": pair_label,
        "pair_key": pair_key,
        "representative_pool_address": addr,
        "ohlcv_status": ohlcv_status,
        "ohlcv_volatility_bucket": vol_bucket,
        "pair_score_total_v1": pair_score_v1,
        "pair_score_v2_core": NA,
        "pair_score_v2_tactical": NA,
        "risk_flag_count": len(flags),
        "risk_flags": "|".join(flags) if flags else "none",
    }

    ohlcv_ok = (orow is not None and ohlcv_status == "OK"
                and vol_bucket in VOL_SCORE_CORE)

    # --- Gate 1: OHLCV tidak tersedia -> NOT_EVALUATED (bukan REJECT) ---
    if not ohlcv_ok:
        reason = (f"OHLCV tidak tersedia (status={ohlcv_status}, "
                  f"bucket={vol_bucket}); volatilitas tak terukur -> NOT_EVALUATED. "
                  f"Bukan REJECT.")
        base.update({
            "strategy_class_v2": "NOT_EVALUATED",
            "pair_status_v2": "NOT_EVALUATED",
            "test_lane": "NOT_EVALUATED",
            "live_eligibility": clamp_live_eligibility("NOT_EVALUATED"),
            "minimum_observation_days": NA,
            "required_capability": "NONE",
            "v2_classification_reason": reason,
        })
        return base

    # OHLCV OK -> hitung skor dua lane (selalu, untuk transparansi).
    core_score, tactical_score = score_v2(prow, vol_bucket)
    base["pair_score_v2_core"] = core_score
    base["pair_score_v2_tactical"] = tactical_score

    severe = sorted(set(flags) & SEVERE_FLAGS)

    # --- Gate 2: REJECT hanya bila ada isu berat (gabungan) ---
    if severe:
        reason = (f"REJECT: isu berat {severe} (vol bucket={vol_bucket}). "
                  f"Volatilitas saja tidak memicu REJECT; ini kombinasi severe.")
        base.update({
            "strategy_class_v2": "REJECT",
            "pair_status_v2": "REJECT",
            "test_lane": "QUARANTINE",
            "live_eligibility": clamp_live_eligibility("NOT_LIVE_ELIGIBLE"),
            "minimum_observation_days": NA,
            "required_capability": "NONE",
            "v2_classification_reason": reason,
        })
        return base

    # --- Gate 3: TACTICAL (volatilitas HIGH/EXTREME tapi metrik layak) ---
    if vol_bucket in ("HIGH", "EXTREME"):
        reason = (f"TACTICAL: volatilitas {vol_bucket} dengan likuiditas/volume/"
                  f"fee/data layak. Reporting/watchlist saja — tanpa paper entry, "
                  f"tanpa execution/LP/rebalance/wallet.")
        base.update({
            "strategy_class_v2": "TACTICAL",
            "pair_status_v2": "WATCHLIST",
            "test_lane": "RISKY_BUT_INTERESTING",
            "live_eligibility": clamp_live_eligibility("OBSERVE_ONLY"),
            "minimum_observation_days": OBS_DAYS_TACTICAL,
            "required_capability": "OBSERVE",
            "v2_classification_reason": reason,
        })
        return base

    # --- Gate 4: CORE (volatilitas LOW/MODERATE, metrik layak) ---
    if core_score >= PAPER_THRESHOLD_CORE:
        status_v2 = "PAPER TEST"
        live_elig = "PAPER_TEST_ALLOWED"
        cap = "PAPER_SIM"
    else:
        status_v2 = "WATCHLIST"
        live_elig = "OBSERVE_ONLY"
        cap = "OBSERVE"
    reason = (f"CORE: volatilitas {vol_bucket}, core_score={core_score} "
              f"(ambang PAPER={PAPER_THRESHOLD_CORE}). Tetap PAPER_ONLY; "
              f"tidak ada izin live di fase ini.")
    base.update({
        "strategy_class_v2": "CORE",
        "pair_status_v2": status_v2,
        "test_lane": "CLEAN",
        "live_eligibility": clamp_live_eligibility(live_elig),
        "minimum_observation_days": OBS_DAYS_CORE,
        "required_capability": cap,
        "v2_classification_reason": reason,
    })
    return base


def write_csv(rows):
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, NA) for k in OUT_HEADER})


def write_report(rows):
    from collections import Counter
    cls_counts = Counter(r["strategy_class_v2"] for r in rows)
    lane_counts = Counter(r["test_lane"] for r in rows)
    elig_counts = Counter(r["live_eligibility"] for r in rows)

    lines = []
    lines.append("# Strategy Classification v0.2 Report")
    lines.append("")
    lines.append(f"- Run timestamp (UTC): {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Total pairs classified: {len(rows)}")
    lines.append("- Phase: READ_ONLY · RESEARCH_ONLY · SCREENING_ONLY · PAPER_ONLY")
    lines.append("")
    lines.append("## strategy_class_v2 counts")
    for c in STRATEGY_CLASSES:
        lines.append(f"- {c}: {cls_counts.get(c, 0)}")
    lines.append("")
    lines.append("## test_lane counts")
    for c in TEST_LANES:
        lines.append(f"- {c}: {lane_counts.get(c, 0)}")
    lines.append("")
    lines.append("## live_eligibility counts")
    for c in LIVE_ELIGIBILITY:
        lines.append(f"- {c}: {elig_counts.get(c, 0)}")
    lines.append("- LIVE_ELIGIBLE_* : 0 (forbidden in this phase — never emitted)")
    lines.append("")
    lines.append("## Classified pairs")
    lines.append("")
    lines.append("> CORE/TACTICAL/REJECT only appear when OHLCV is OK. While the "
                 "OHLCV endpoint returns API_ERROR for all pairs, every row is "
                 "NOT_EVALUATED by design — this is the honest outcome, not a bug.")
    lines.append("")
    lines.append("| Pair | OHLCV | Vol bucket | Class | Status v2 | Core | Tactical "
                 "| Lane | Live elig | Min obs days | Capability | Risk flags |")
    lines.append("|---|---|---|---|---|---:|---:|---|---|---:|---|---|")
    for r in rows:
        lines.append(
            f"| {r['pair_label']} | {r['ohlcv_status']} "
            f"| {r['ohlcv_volatility_bucket']} | {r['strategy_class_v2']} "
            f"| {r['pair_status_v2']} | {r['pair_score_v2_core']} "
            f"| {r['pair_score_v2_tactical']} | {r['test_lane']} "
            f"| {r['live_eligibility']} | {r['minimum_observation_days']} "
            f"| {r['required_capability']} | {r['risk_flags']} |"
        )
    lines.append("")
    lines.append("## Method notes")
    lines.append("")
    lines.append("- **OHLCV unavailable -> NOT_EVALUATED** (volatility cannot be "
                 "measured; not a REJECT).")
    lines.append("- **Extreme volatility is NOT auto-REJECT.** It becomes TACTICAL "
                 "when liquidity/volume/fee/data are acceptable; REJECT only when "
                 "combined with a severe issue (blacklist, no eligible fee pool, "
                 "unacceptable liquidity/volume, or severe data issue).")
    lines.append("- **TACTICAL is reporting/watchlist only** — no paper entry, no "
                 "execution, no LP, no rebalance, no wallet.")
    lines.append(f"- Severe flags (trigger REJECT): {sorted(SEVERE_FLAGS)}.")
    lines.append(f"- Floors: TVL>={FLOOR_TVL:,}, Vol24h>={FLOOR_VOL:,}, "
                 f"data_completeness>={MIN_DATA_COMPLETENESS}%.")
    lines.append("- Pool-level scoring stays legacy audit trail only; this v0.2 "
                 "view is pair-level (primary).")
    lines.append("")
    lines.append("---")
    lines.append("**No wallet · No private key · No signing · No swap · No LP · "
                 "No rebalance · No live execution. Research only; PAPER_ONLY.**")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    log("=== Strategy Classification v0.2 start (read-only, PAPER_ONLY) ===")
    if not PAIR_CSV.exists():
        log(f"FATAL: {PAIR_CSV} tidak ada. Jalankan build_watchlist.py dulu.")
        return 1
    with PAIR_CSV.open(newline="", encoding="utf-8") as f:
        pair_rows = list(csv.DictReader(f))
    if not pair_rows:
        log("FATAL: pair_watchlist.csv kosong (hanya header). Tidak ada yang diklasifikasi.")
        return 1

    ohlcv_lookup = load_ohlcv_lookup()
    log(f"pasangan dibaca: {len(pair_rows)}; OHLCV lookup entries: {len(ohlcv_lookup)}")

    out_rows = [classify(p, ohlcv_lookup) for p in pair_rows]

    write_csv(out_rows)
    write_report(out_rows)

    from collections import Counter
    counts = Counter(r["strategy_class_v2"] for r in out_rows)
    log(f"CSV ditulis: {OUT_CSV.name} ({len(out_rows)} baris)")
    log(f"Report ditulis: reports/{REPORT_PATH.name}")
    log(f"strategy_class_v2: CORE={counts.get('CORE', 0)}, "
        f"TACTICAL={counts.get('TACTICAL', 0)}, REJECT={counts.get('REJECT', 0)}, "
        f"NOT_EVALUATED={counts.get('NOT_EVALUATED', 0)}")
    log("=== Strategy Classification v0.2 selesai ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
