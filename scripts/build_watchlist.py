#!/usr/bin/env python3
"""
build_watchlist.py — Screening + scoring engine untuk DLMM Research.

Status: RESEARCH-FIRST · PAPER-ONLY. Tidak ada execution, wallet, atau credential.

Membaca snapshot raw terbaru dari data/raw/, memetakan field datapi ke kolom
watchlist, menerapkan hard filter + scoring rubric + veto volatilitas
(sesuai DLMM_POOL_SCREENING_PROTOCOL.md), dan menulis:
  - data/pools_watchlist.csv     (mengganti baris contoh dengan data nyata)
  - data/latest_pool_report.md   (ringkasan + GAP DATA yang tidak tersedia)

PRINSIP NO-GUESS:
  Field yang tidak ada di datapi ditandai DATA_NOT_AVAILABLE, tidak ditebak.
  Field yang TIDAK tersedia dari /pools (terverifikasi terhadap skema):
    - total_lps            -> DATA_NOT_AVAILABLE (tidak ada di skema pool)
    - organic_score        -> DATA_NOT_AVAILABLE (konsep Jupiter, bukan datapi)
    - supply_concentration -> proxy kasar saja (freeze_authority/verified)
    - konsistensi fee 3-7 hari -> harus dirakit dari snapshot harian (belum ada)
"""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
LATEST_RAW = RAW_DIR / "meteora_pools_raw_latest.json"
CSV_PATH = ROOT / "data" / "pools_watchlist.csv"
PAIR_CSV_PATH = ROOT / "data" / "pair_watchlist.csv"
REPORT_PATH = ROOT / "reports" / "latest_pool_report.md"

NA = "DATA_NOT_AVAILABLE"

CSV_HEADER = [
    "tanggal", "pool", "pair", "mcap_usd", "holders", "volume_24h_usd",
    "active_tvl_usd", "fees_active_tvl_pct", "volatility_pct", "volatility_bucket",
    "total_lps", "organic_score", "supply_concentration",
    "score_safety", "score_liquidity", "score_fee", "score_volatility",
    "score_lp", "score_data", "score_total", "vol_gate_applied",
    "owner_scope_gate", "validation_gate", "max_allowed_action",
    "status", "alasan", "risiko_utama", "keputusan", "review_date",
]

# Gate proyek (dari Charter / reset konteks). Validation tetap RED di fase ini.
OWNER_SCOPE_GATE = "green"
VALIDATION_GATE = "red"
MAX_ALLOWED_ACTION = "PAPER_ONLY"

# Hard filter thresholds (dari protokol §3)
HF_MIN_MCAP = 500_000
HF_MIN_TVL = 10_000
HF_MIN_VOL_24H = 10_000
HF_MIN_HOLDERS = 200


def latest_snapshot():
    """Kembalikan path _latest.json jika ada, else None. Online-only: tak ada fallback."""
    return LATEST_RAW if LATEST_RAW.exists() else None


def num(value):
    """Ambil angka aman; kembalikan None jika tidak bisa."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def estimate_volatility_pct(pool):
    """
    Proxy volatilitas dari fee_tvl_ratio 24h sebagai indikator aktivitas/churn.
    JUJUR: ini proxy kasar, bukan volatilitas harga sebenarnya. OHLCV per-pool
    tersedia di endpoint terpisah tapi belum di-fetch di fase ini.
    Mengembalikan (nilai_pct_atau_NA, sumber_string).
    """
    # Tanpa OHLCV, volatilitas harga sejati tidak tersedia dari /pools.
    return NA, "perlu OHLCV (belum di-fetch)"


def bucket_from_pct(vpct):
    if vpct == NA or vpct is None:
        return NA
    v = float(vpct)
    if v < 2:
        return "low"
    if v < 4:
        return "moderate"
    if v < 8:
        return "high"
    return "extreme"


def map_pool(pool):
    """Memetakan satu objek pool datapi ke dict kolom watchlist."""
    tx = pool.get("token_x", {}) or {}
    ty = pool.get("token_y", {}) or {}
    fee_tvl = pool.get("fee_tvl_ratio", {}) or {}
    vol = pool.get("volume", {}) or {}

    # MCAP: pakai yang lebih besar dari kedua token sebagai proxy ukuran pair.
    mcap_x = num(tx.get("market_cap"))
    mcap_y = num(ty.get("market_cap"))
    mcap = max([m for m in (mcap_x, mcap_y) if m is not None], default=None)

    # Holders: ambil minimum dari kedua token (lebih konservatif).
    h_x = tx.get("holders")
    h_y = ty.get("holders")
    holders_vals = [h for h in (h_x, h_y) if isinstance(h, (int, float))]
    holders = min(holders_vals) if holders_vals else None

    tvl = num(pool.get("tvl"))
    vol24 = num(vol.get("24h"))
    fee_tvl_24 = num(fee_tvl.get("24h"))  # ini RATIO, satuan tergantung API
    price = num(pool.get("current_price"))

    vpct, _vsrc = estimate_volatility_pct(pool)
    vbucket = bucket_from_pct(vpct)

    # supply_concentration: proxy kasar. Bukan metrik langsung.
    fa_x = tx.get("freeze_authority_disabled")
    fa_y = ty.get("freeze_authority_disabled")
    if fa_x is True and fa_y is True:
        supply_conc = "low_proxy"
    elif fa_x is None and fa_y is None:
        supply_conc = NA
    else:
        supply_conc = "check_manual"

    return {
        "pool": pool.get("address", NA),
        "pair": pool.get("name", NA),
        "mcap_usd": mcap if mcap is not None else NA,
        "holders": int(holders) if holders is not None else NA,
        "volume_24h_usd": vol24 if vol24 is not None else NA,
        "active_tvl_usd": tvl if tvl is not None else NA,
        "fees_active_tvl_pct": fee_tvl_24 if fee_tvl_24 is not None else NA,
        "volatility_pct": vpct,
        "volatility_bucket": vbucket,
        "total_lps": NA,        # tidak ada di skema datapi /pools
        "organic_score": NA,    # konsep Jupiter, bukan datapi Meteora
        "supply_concentration": supply_conc,
        "price": price if price is not None else NA,
        "is_blacklisted": pool.get("is_blacklisted", None),
        "tags": pool.get("tags", []) or [],
    }


def hard_filter(m):
    """Kembalikan list alasan REJECT. Kosong = lolos hard filter."""
    reasons = []
    if m.get("is_blacklisted") is True:
        reasons.append("blacklisted oleh Meteora")
    mcap = m["mcap_usd"]
    if mcap == NA:
        reasons.append("mcap DATA_NOT_AVAILABLE")
    elif mcap < HF_MIN_MCAP:
        reasons.append(f"mcap {mcap:.0f} < {HF_MIN_MCAP}")
    tvl = m["active_tvl_usd"]
    if tvl == NA:
        reasons.append("tvl DATA_NOT_AVAILABLE")
    elif tvl < HF_MIN_TVL:
        reasons.append(f"tvl {tvl:.0f} < {HF_MIN_TVL}")
    vol = m["volume_24h_usd"]
    if vol == NA:
        reasons.append("volume DATA_NOT_AVAILABLE")
    elif vol < HF_MIN_VOL_24H:
        reasons.append(f"volume {vol:.0f} < {HF_MIN_VOL_24H}")
    holders = m["holders"]
    if holders == NA:
        reasons.append("holders DATA_NOT_AVAILABLE")
    elif holders < HF_MIN_HOLDERS:
        reasons.append(f"holders {holders} < {HF_MIN_HOLDERS}")
    return reasons


def score_dimensions(m):
    """
    Skor diskret per protokol §4A. Jika input NA, dimensi diberi skor data-rendah
    dan dicatat sebagai gap (bukan ditebak tinggi).
    """
    s = {}

    # Safety: tanpa organic_score (NA), kita tidak bisa nilai penuh -> konservatif.
    s["safety"] = 45 if m["organic_score"] == NA else 67

    # Liquidity dari TVL nyata
    tvl = m["active_tvl_usd"]
    if tvl == NA:
        s["liquidity"] = 0
    elif tvl > 100_000:
        s["liquidity"] = 95
    elif tvl > 50_000:
        s["liquidity"] = 80
    elif tvl > 25_000:
        s["liquidity"] = 67
    else:
        s["liquidity"] = 50

    # Fee: kita PUNYA rasio 24h, tapi BELUM konsistensi 3-7 hari -> plafon menengah.
    fee = m["fees_active_tvl_pct"]
    if fee == NA:
        s["fee"] = 0
    else:
        # konsistensi multi-hari belum dirakit -> maksimal 67 (jujur)
        s["fee"] = 67

    # Volatility: NA -> tidak bisa dinilai -> skor rendah + veto akan berlaku
    s["volatility"] = 30 if m["volatility_bucket"] == NA else {
        "low": 95, "moderate": 78, "high": 55, "extreme": 30
    }.get(m["volatility_bucket"], 30)

    # LP distribution: NA -> 0 (tidak ada data)
    s["lp"] = 0 if m["total_lps"] == NA else 65

    # Data consistency: banyak NA -> rendah
    na_count = sum(1 for k in ["total_lps", "organic_score", "volatility_bucket"]
                   if m[k] == NA)
    s["data"] = 55 if na_count == 0 else (30 if na_count <= 2 else 15)

    total = (s["safety"] * 0.25 + s["liquidity"] * 0.20 + s["fee"] * 0.20 +
             s["volatility"] * 0.15 + s["lp"] * 0.10 + s["data"] * 0.10)
    return s, round(total, 1)


def apply_status(m, score_total, hard_reasons):
    """Tentukan status + veto. Mengembalikan (status, vol_gate_applied, alasan)."""
    if hard_reasons:
        return "REJECT", "no", "; ".join(hard_reasons)

    bucket = m["volatility_bucket"]
    vol_gate = "no"
    # Veto volatilitas (protokol §5 catatan #6)
    if bucket == NA:
        # tanpa data volatilitas, tidak boleh naik ke PAPER TEST
        status_cap = "WATCHLIST"
        vol_gate = "yes (vol=NA)"
    elif bucket in ("high", "extreme"):
        status_cap = "WATCHLIST"
        vol_gate = f"yes (vol={bucket})"
    elif bucket == "moderate":
        status_cap = "PAPER TEST"
    else:  # low
        status_cap = None  # tidak dibatasi veto

    # status dasar dari skor
    if score_total < 50:
        base = "REJECT"
    elif score_total < 70:
        base = "WATCHLIST"
    elif score_total < 85:
        base = "PAPER TEST"
    else:
        base = "SMALL LIVE TEST"

    # Override satu arah: ambil yang lebih konservatif antara base dan cap
    order = {"REJECT": 0, "WATCHLIST": 1, "PAPER TEST": 2, "SMALL LIVE TEST": 3, None: 99}
    if status_cap is not None and order[status_cap] < order[base]:
        final = status_cap
    else:
        final = base

    # Validation gate merah -> tidak boleh melebihi PAPER TEST apa pun
    if order[final] > order["PAPER TEST"]:
        final = "PAPER TEST"

    alasan = f"skor {score_total}; bucket {bucket}"
    return final, vol_gate, alasan


def build_rows(pools):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    review = today  # review_date = hari ini untuk fase tool-test
    rows = []
    gaps = {"total_lps": 0, "organic_score": 0, "volatility_pct": 0,
            "mcap_usd": 0, "holders": 0}
    for pool in pools:
        m = map_pool(pool)
        for g in gaps:
            if m.get(g, NA) == NA:
                gaps[g] += 1
        hard_reasons = hard_filter(m)
        s, total = score_dimensions(m)
        status, vol_gate, alasan = apply_status(m, total, hard_reasons)
        rows.append({
            "tanggal": today, "pool": m["pool"], "pair": m["pair"],
            "mcap_usd": m["mcap_usd"], "holders": m["holders"],
            "volume_24h_usd": m["volume_24h_usd"], "active_tvl_usd": m["active_tvl_usd"],
            "fees_active_tvl_pct": m["fees_active_tvl_pct"],
            "volatility_pct": m["volatility_pct"], "volatility_bucket": m["volatility_bucket"],
            "total_lps": m["total_lps"], "organic_score": m["organic_score"],
            "supply_concentration": m["supply_concentration"],
            "score_safety": s["safety"], "score_liquidity": s["liquidity"],
            "score_fee": s["fee"], "score_volatility": s["volatility"],
            "score_lp": s["lp"], "score_data": s["data"], "score_total": total,
            "vol_gate_applied": vol_gate,
            "owner_scope_gate": OWNER_SCOPE_GATE, "validation_gate": VALIDATION_GATE,
            "max_allowed_action": MAX_ALLOWED_ACTION,
            "status": status, "alasan": alasan,
            "risiko_utama": "lihat report; banyak field NA di fase ini",
            "keputusan": "tetap PAPER_ONLY", "review_date": review,
        })
    return rows, gaps


def write_csv(rows):
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_HEADER})


def write_report(rows, gaps, source_url, total_pools, groups=None):
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    # Top candidates by score (yang tidak REJECT lebih dulu, lalu skor tertinggi)
    def sort_key(r):
        st_rank = {"PAPER TEST": 0, "WATCHLIST": 1, "REJECT": 2}.get(r["status"], 3)
        try:
            sc = float(r["score_total"])
        except (TypeError, ValueError):
            sc = -1
        return (st_rank, -sc)
    top = sorted(rows, key=sort_key)[:10]

    # Field paling sering DATA_NOT_AVAILABLE
    na_sorted = sorted(gaps.items(), key=lambda kv: kv[1], reverse=True)

    lines = []
    lines.append("# Latest Pool Report")
    lines.append("")
    lines.append(f"- Run timestamp (UTC): {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- API source: {source_url}")
    lines.append(f"- Total raw pools fetched: {total_pools}")
    lines.append(f"- Total rows generated: {len(rows)}")
    if groups is not None:
        lines.append(f"- Total unique pairs (grouped): {len(groups)}")
    lines.append(f"- Owner scope gate: {OWNER_SCOPE_GATE} | Validation gate: {VALIDATION_GATE} "
                 f"| Max action: {MAX_ALLOWED_ACTION}")
    lines.append("")
    if groups is not None:
        lines.append("## Top Pair Groups (by total TVL)")
        lines.append("")
        lines.append("Memisahkan 'pasangan mana yang menarik' dari 'pool/bin step mana "
                     "yang dipakai'. Satu pasangan bisa punya banyak pool.")
        lines.append("")
        lines.append("> **Catatan satuan fee/TVL.** Meteora API `fee_tvl_ratio` "
                     "diperlakukan sebagai bentuk persen. Contoh: 0,2 berarti 0,2%. "
                     "Diverifikasi terhadap data mentah (faktor API vs fee/tvl×100 = 1,0). "
                     "Kolom `_pct_24h` = nilai persen; `_decimal_24h` = pct/100. "
                     "Ambang protokol 0,2% memetakan ke `best_eligible_fee_tvl_pct_24h >= 0,2`.")
        lines.append("")
        lines.append("> Kolom fee memakai **best_eligible** (hanya pool dengan TVL≥10K "
                     "DAN volume24h≥10K), bukan raw max — supaya pool TVL-mendekati-nol "
                     "tidak meledakkan metrik.")
        lines.append("")
        lines.append("| Pair | Pools | Total TVL | Vol 24h | Best elig fee/TVL (%) | Sanity | Bin steps |")
        lines.append("|---|---:|---:|---:|---:|---|---|")
        # urut by TVL untuk tabel ini
        by_tvl = sorted(groups, key=lambda gr: -(gr['total_tvl_usd']
                        if isinstance(gr['total_tvl_usd'], (int, float)) else -1))
        for g in by_tvl[:15]:
            def fmt(v):
                return f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)
            lines.append(
                f"| {g['pair_label']} | {g['pool_count']} | {fmt(g['total_tvl_usd'])} "
                f"| {fmt(g['total_volume_24h_usd'])} | {g['best_eligible_fee_tvl_pct_24h']} "
                f"| {g['fee_ratio_sanity_flag']} | {g['available_bin_steps']} |"
            )
        lines.append("")

        # Section: Top Pair Scores (by pair_score_total)
        from collections import Counter as _Counter
        status_counts = _Counter(g["pair_status"] for g in groups)
        lines.append("## Top Pair Scores (by pair_score_total)")
        lines.append("")
        lines.append("Top 20 pasangan berdasarkan skor pair. Skor ini **bukan sinyal "
                     "live** dan **bukan rekomendasi entry** — ia menyusun shortlist "
                     "perhatian dari data API yang tersedia. Output tetap **PAPER_ONLY**.")
        lines.append("")
        lines.append("| Pair | Score | Status | TVL | Vol24h | Fee% | Liq | Vol | Fee | Tok | Div | Data |")
        lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for g in groups[:20]:
            def fmt(v):
                return f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)
            lines.append(
                f"| {g['pair_label']} | {g['pair_score_total']} | {g['pair_status']} "
                f"| {fmt(g['total_tvl_usd'])} | {fmt(g['total_volume_24h_usd'])} "
                f"| {g['best_eligible_fee_tvl_pct_24h']} "
                f"| {g['score_liquidity']} | {g['score_volume']} | {g['score_fee']} "
                f"| {g['score_token_quality']} | {g['score_pool_diversity']} "
                f"| {g['score_data_quality']} |"
            )
        lines.append("")
        lines.append("### Pair status counts")
        lines.append(f"- REJECT: {status_counts.get('REJECT', 0)}")
        lines.append(f"- WATCHLIST: {status_counts.get('WATCHLIST', 0)}")
        lines.append(f"- PAPER TEST: {status_counts.get('PAPER TEST', 0)}")
        lines.append("- SMALL LIVE TEST: 0 (tidak ada di level pair, sesuai desain)")
        lines.append("")
        lines.append("> Semua status PAPER TEST tetap tunduk pada validation_gate=red → "
                     "max_allowed_action=PAPER_ONLY. PAPER TEST di sini berarti 'layak "
                     "masuk paper test', bukan izin live.")
        lines.append("")

        # Section: Fee/TVL sanity warnings
        distorted = [g for g in groups if g["fee_ratio_sanity_flag"] == "low_tvl_distortion"]
        no_elig = [g for g in groups if g["fee_ratio_sanity_flag"] == "no_eligible_fee_pool"]
        lines.append("## Fee/TVL Sanity Warnings")
        lines.append("")
        lines.append(f"- Pasangan dengan distorsi TVL-rendah (raw max ≫ eligible best): "
                     f"**{len(distorted)}**")
        lines.append(f"- Pasangan tanpa pool fee-eligible (TVL/vol < 10K): "
                     f"**{len(no_elig)}**")
        if distorted:
            lines.append("")
            lines.append("Contoh distorsi (raw max % vs eligible best %):")
            lines.append("")
            lines.append("| Pair | raw_max_% | eligible_best_% | eligible pools |")
            lines.append("|---|---:|---:|---:|")
            for g in distorted[:10]:
                lines.append(
                    f"| {g['pair_label']} | {g['raw_max_fee_tvl_pct_24h']} "
                    f"| {g['best_eligible_fee_tvl_pct_24h']} | {g['eligible_fee_pool_count']} |"
                )
        lines.append("")
    lines.append("## Ringkasan Status (pool-level)")
    lines.append(f"- REJECT: {counts.get('REJECT', 0)}")
    lines.append(f"- WATCHLIST: {counts.get('WATCHLIST', 0)}")
    lines.append(f"- PAPER TEST: {counts.get('PAPER TEST', 0)}")
    lines.append(f"- SMALL LIVE TEST: {counts.get('SMALL LIVE TEST', 0)} "
                 "(harus 0 di fase ini)")
    lines.append("")
    lines.append("## Pool-level legacy screening result")
    lines.append("")
    lines.append("> Pool-level scoring is retained for audit trail only. "
                 "Current shortlist uses pair-level scoring.")
    lines.append("")
    lines.append("| Pair | Score | Status | Vol gate |")
    lines.append("|---|---:|---|---|")
    for r in top:
        lines.append(f"| {r['pair']} | {r['score_total']} | {r['status']} "
                     f"| {r['vol_gate_applied']} |")
    lines.append("")
    lines.append("## Field paling sering DATA_NOT_AVAILABLE")
    lines.append("")
    for field, cnt in na_sorted:
        lines.append(f"- `{field}`: {cnt}/{total_pools} pool")
    lines.append("")
    lines.append("## ⚠️ Catatan gap data (temuan utama fase TOOL TEST)")
    lines.append("")
    lines.append("Field berikut TIDAK tersedia dari endpoint /pools dan ditandai "
                 "DATA_NOT_AVAILABLE — bukan ditebak, bukan menyembunyikan error fetch:")
    lines.append("- `total_lps`: tidak ada di skema datapi → LP-distribution scoring "
                 "tak bisa otomatis.")
    lines.append("- `organic_score`: konsep Jupiter, bukan field Meteora → safety "
                 "scoring terbatas.")
    lines.append("- `volatility_pct`: butuh OHLCV per-pool (endpoint terpisah) → "
                 "volatility veto memakai NA-cap.")
    lines.append("")
    lines.append("Implikasi: rubric Fee Quality minta konsistensi 3–7 hari, tapi API "
                 "hanya beri bucket ≤24 jam → deret multi-hari harus dirakit dari "
                 "snapshot harian. Semua status di-cap PAPER TEST (validation_gate=red).")
    lines.append("")
    lines.append("---")
    lines.append("**No wallet · No execution · Not a live trading signal.** "
                 "Dokumen riset; data dari API publik live.")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def normalize_pair(pool):
    """
    Kunci pasangan yang stabil: urutkan kedua mint address alfabetis.
    Memakai address (bukan symbol) supaya tahan terhadap symbol duplikat/aneh.
    Mengembalikan (pair_key, pair_label).
    """
    tx = pool.get("token_x", {}) or {}
    ty = pool.get("token_y", {}) or {}
    ax = tx.get("address", "")
    ay = ty.get("address", "")
    sx = tx.get("symbol", "?")
    sy = ty.get("symbol", "?")
    # urutkan berdasarkan address agar arah pair tidak memecah grup
    if ax <= ay:
        return f"{ax}|{ay}", f"{sx}-{sy}"
    return f"{ay}|{ax}", f"{sy}-{sx}"


def _is_num(v):
    return isinstance(v, (int, float))


def score_liquidity_pair(total_tvl):
    if not _is_num(total_tvl):
        return 10
    if total_tvl >= 5_000_000:
        return 100
    if total_tvl >= 1_000_000:
        return 85
    if total_tvl >= 250_000:
        return 65
    if total_tvl >= 50_000:
        return 40
    return 10


def score_volume_pair(total_vol):
    if not _is_num(total_vol):
        return 10
    if total_vol >= 5_000_000:
        return 100
    if total_vol >= 1_000_000:
        return 85
    if total_vol >= 250_000:
        return 65
    if total_vol >= 50_000:
        return 40
    return 10


def score_fee_pair(best_pct):
    # best_pct dalam bentuk PERSEN (0,2 berarti 0,2%)
    if not _is_num(best_pct):
        return 0
    if best_pct >= 1.0:
        return 100
    if best_pct >= 0.5:
        return 85
    if best_pct >= 0.2:
        return 70
    if best_pct >= 0.05:
        return 40
    return 15


def score_token_quality_pair(min_mcap, min_holders, verified, blacklisted):
    if blacklisted and blacklisted > 0:
        return 0
    mc = min_mcap if _is_num(min_mcap) else -1
    mh = min_holders if _is_num(min_holders) else -1
    if mc >= 100_000_000 and mh >= 50_000 and verified >= 2:
        return 100
    if mc >= 10_000_000 and mh >= 10_000:
        return 80
    if mc >= 1_000_000 and mh >= 1_000:
        return 60
    if mc >= 250_000 and mh >= 200:
        return 40
    return 10


def score_pool_diversity_pair(pool_count, bin_step_count):
    if pool_count >= 5 and bin_step_count >= 4:
        return 100
    if pool_count >= 3 and bin_step_count >= 2:
        return 80
    if pool_count >= 2:
        return 60
    return 40


def score_data_quality_pair(sanity_flag):
    return {
        "ok": 100,
        "low_tvl_distortion": 70,
        "no_eligible_fee_pool": 20,
        "DATA_NOT_AVAILABLE": 0,
    }.get(sanity_flag, 0)


def assign_pair_status(score_total, blacklisted, elig_count, sanity_flag):
    # Override keras dulu
    if blacklisted and blacklisted > 0:
        return "REJECT"
    # base dari skor
    if score_total < 50:
        base = "REJECT"
    elif score_total < 70:
        base = "WATCHLIST"
    else:
        base = "PAPER TEST"
    # cap: tanpa pool fee-eligible → maksimal WATCHLIST
    if elig_count == 0 or sanity_flag == "no_eligible_fee_pool":
        order = {"REJECT": 0, "WATCHLIST": 1, "PAPER TEST": 2}
        if order[base] > order["WATCHLIST"]:
            base = "WATCHLIST"
    # Tidak ada SMALL LIVE TEST / live action di level ini sama sekali.
    return base


def group_by_pair(pools):
    """
    Kelompokkan pool mentah per pasangan token. Mengembalikan list dict grup,
    satu per pasangan unik. Field yang tidak tersedia ditandai NA.
    """
    groups = {}
    for pool in pools:
        key, label = normalize_pair(pool)
        g = groups.setdefault(key, {
            "pair_key": key, "pair_label": label, "pools": [],
        })
        g["pools"].append(pool)

    result = []
    for key, g in groups.items():
        plist = g["pools"]

        def fnum(pool, *path):
            cur = pool
            for k in path:
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(k)
            return num(cur)

        tvls = [fnum(p, "tvl") for p in plist]
        tvls = [v for v in tvls if v is not None]
        vols = [fnum(p, "volume", "24h") for p in plist]
        vols = [v for v in vols if v is not None]
        fees = [fnum(p, "fees", "24h") for p in plist]
        fees = [v for v in fees if v is not None]
        ratios = [fnum(p, "fee_tvl_ratio", "24h") for p in plist]
        ratios = [v for v in ratios if v is not None]

        # --- Fee-ratio integrity (perbaikan: jangan max() buta) ---
        # Pool layak untuk ranking fee-ratio hanya jika TVL & volume cukup,
        # supaya pool TVL-mendekati-nol tidak meledakkan rasio.
        FEE_ELIG_MIN_TVL = 10_000
        FEE_ELIG_MIN_VOL = 10_000
        eligible = []
        for p in plist:
            t = fnum(p, "tvl")
            v = fnum(p, "volume", "24h")
            r = fnum(p, "fee_tvl_ratio", "24h")
            if (t is not None and t >= FEE_ELIG_MIN_TVL
                    and v is not None and v >= FEE_ELIG_MIN_VOL
                    and r is not None):
                eligible.append((r, p))

        raw_max_pct = round(max(ratios), 6) if ratios else NA  # API sudah persen
        if eligible:
            eligible.sort(key=lambda rp: rp[0], reverse=True)
            best_elig_pct = round(eligible[0][0], 6)  # API value = persen langsung
            best_elig_addr = eligible[0][1].get("address", NA)
            elig_count = len(eligible)
            if isinstance(raw_max_pct, (int, float)) and best_elig_pct > 0:
                if raw_max_pct > best_elig_pct * 10:
                    sanity = "low_tvl_distortion"
                else:
                    sanity = "ok"
            else:
                sanity = "ok"
        else:
            best_elig_pct = NA
            best_elig_addr = NA
            elig_count = 0
            sanity = "no_eligible_fee_pool"

        if not ratios:
            sanity = "DATA_NOT_AVAILABLE"

        # Satuan eksplisit: pct = nilai API (persen), decimal = pct/100.
        # Dikonfirmasi terhadap data mentah: faktor API vs (fee/tvl*100) = 1,0.
        raw_max_decimal = (round(raw_max_pct / 100, 8)
                           if isinstance(raw_max_pct, (int, float)) else NA)
        best_elig_decimal = (round(best_elig_pct / 100, 8)
                             if isinstance(best_elig_pct, (int, float)) else NA)

        # pool dengan TVL maksimum (kandidat "pool utama" untuk pasangan ini)
        max_tvl_addr = NA
        if tvls:
            best = max(plist, key=lambda p: fnum(p, "tvl") or -1)
            max_tvl_addr = best.get("address", NA)

        # bin steps tersedia
        bin_steps = sorted({
            p.get("pool_config", {}).get("bin_step")
            for p in plist
            if isinstance(p.get("pool_config"), dict)
            and p["pool_config"].get("bin_step") is not None
        })

        # min mcap & min holders across both token sides, across all pools in group
        # verified_token_count = jumlah MINT UNIK yang verified (0/1/2 untuk pasangan)
        mcaps, holders_all = [], []
        blacklisted = 0
        verified_mints = set()   # mint address yang is_verified True
        all_mints = set()        # semua mint unik di grup (audit)
        for p in plist:
            for side in ("token_x", "token_y"):
                t = p.get(side, {}) or {}
                addr = t.get("address")
                if addr:
                    all_mints.add(addr)
                    if t.get("is_verified") is True:
                        verified_mints.add(addr)
                m = num(t.get("market_cap"))
                if m is not None:
                    mcaps.append(m)
                h = t.get("holders")
                if isinstance(h, (int, float)):
                    holders_all.append(h)
            if p.get("is_blacklisted") is True:
                blacklisted += 1
        verified = len(verified_mints)
        unique_token_count = len(all_mints)

        total_tvl = round(sum(tvls), 2) if tvls else NA
        total_vol = round(sum(vols), 2) if vols else NA
        min_mcap = round(min(mcaps), 2) if mcaps else NA
        min_hold = int(min(holders_all)) if holders_all else NA
        bin_steps_str = "|".join(str(b) for b in bin_steps) if bin_steps else NA

        # --- Part B: pair-level scoring v0.1 (hanya field API yang tersedia) ---
        s_liq = score_liquidity_pair(total_tvl)
        s_vol = score_volume_pair(total_vol)
        s_fee = score_fee_pair(best_elig_pct)
        s_tok = score_token_quality_pair(min_mcap, min_hold, verified, blacklisted)
        s_div = score_pool_diversity_pair(len(plist), len(bin_steps))
        s_data = score_data_quality_pair(sanity)
        total_score = round(
            s_liq * 0.30 + s_vol * 0.20 + s_fee * 0.20 +
            s_tok * 0.15 + s_div * 0.10 + s_data * 0.05, 2)
        pair_status = assign_pair_status(
            total_score, blacklisted, elig_count, sanity)

        result.append({
            "pair_key": key,
            "pair_label": g["pair_label"],
            "pool_count": len(plist),
            "total_tvl_usd": total_tvl,
            "total_volume_24h_usd": total_vol,
            "total_fees_24h_usd": round(sum(fees), 2) if fees else NA,
            # fee-ratio dengan satuan eksplisit (pct = nilai API; decimal = pct/100)
            "eligible_fee_pool_count": elig_count,
            "best_eligible_fee_tvl_pct_24h": best_elig_pct,
            "best_eligible_fee_tvl_decimal_24h": best_elig_decimal,
            "best_eligible_fee_pool_address": best_elig_addr,
            "raw_max_fee_tvl_pct_24h": raw_max_pct,
            "raw_max_fee_tvl_decimal_24h": raw_max_decimal,
            "fee_ratio_sanity_flag": sanity,
            "max_tvl_pool_address": max_tvl_addr,
            "available_bin_steps": bin_steps_str,
            "min_mcap_usd": min_mcap,
            "min_holders": min_hold,
            "verified_token_count": verified,
            "unique_token_count": unique_token_count,
            "blacklisted_pool_count": blacklisted,
            # scoring pair v0.1
            "score_liquidity": s_liq,
            "score_volume": s_vol,
            "score_fee": s_fee,
            "score_token_quality": s_tok,
            "score_pool_diversity": s_div,
            "score_data_quality": s_data,
            "pair_score_total": total_score,
            "pair_status": pair_status,
            "validation_gate": VALIDATION_GATE,
            "max_allowed_action": MAX_ALLOWED_ACTION,
            # field yang tetap tidak tersedia dari API
            "total_lps": NA,
            "organic_score": NA,
            "volatility_pct": NA,
        })

    # urutkan: pair_score_total desc (skor tertinggi dulu)
    def sort_key(gr):
        t = gr["pair_score_total"]
        return -(t if isinstance(t, (int, float)) else -1)
    result.sort(key=sort_key)
    return result


PAIR_CSV_HEADER = [
    "pair_label", "pair_key", "pool_count", "total_tvl_usd",
    "total_volume_24h_usd", "total_fees_24h_usd",
    "eligible_fee_pool_count",
    "best_eligible_fee_tvl_pct_24h", "best_eligible_fee_tvl_decimal_24h",
    "best_eligible_fee_pool_address",
    "raw_max_fee_tvl_pct_24h", "raw_max_fee_tvl_decimal_24h",
    "fee_ratio_sanity_flag",
    "max_tvl_pool_address", "available_bin_steps", "min_mcap_usd", "min_holders",
    "verified_token_count", "unique_token_count", "blacklisted_pool_count",
    "score_liquidity", "score_volume", "score_fee", "score_token_quality",
    "score_pool_diversity", "score_data_quality", "pair_score_total", "pair_status",
    "validation_gate", "max_allowed_action",
    "total_lps", "organic_score", "volatility_pct",
]


def write_pair_csv(groups):
    with PAIR_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PAIR_CSV_HEADER)
        w.writeheader()
        for g in groups:
            w.writerow({k: g.get(k, NA) for k in PAIR_CSV_HEADER})


def main():
    snap = latest_snapshot()
    if snap is None:
        print("FATAL: data/raw/meteora_pools_raw_latest.json tidak ada.")
        print("Jalankan fetch_meteora_pools.py dulu (online). Tidak ada fallback.")
        return 1
    try:
        data = json.loads(snap.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"FATAL: gagal baca/parse {snap.name}: {e}")
        return 1
    pools = data.get("pools", [])
    if not pools:
        print("FATAL: raw data kosong (0 pool). Tidak menulis watchlist. "
              "Online-only: kosong = gagal.")
        return 1
    source_url = data.get("source", "unknown")
    rows, gaps = build_rows(pools)
    write_csv(rows)
    groups = group_by_pair(pools)
    write_pair_csv(groups)
    write_report(rows, gaps, source_url, len(pools), groups)
    print(f"Watchlist ditulis: {CSV_PATH.name} ({len(rows)} baris)")
    print(f"Pair watchlist ditulis: {PAIR_CSV_PATH.name} ({len(groups)} pasangan unik)")
    print(f"Report ditulis: reports/{REPORT_PATH.name}")
    print(f"Gap data teratas: total_lps={gaps['total_lps']}, "
          f"organic_score={gaps['organic_score']}, volatility_pct={gaps['volatility_pct']} "
          f"(dari {len(pools)} pool)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
