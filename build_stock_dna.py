import glob
import json
import os
from datetime import datetime
import numpy as np
import pandas as pd

from pipeline import (
    BASE_DIR,
    DATA_DIR,
    CSV_STORE,
    METADATA_FILE,
    load_index_mappings,
    ensure_metadata,
    normalize_corporate_actions,
    classify_mcap_tier,
)

DNA_OUTPUT_CSV = os.path.join(DATA_DIR, "stock_dna_profiles.csv")
DNA_SUMMARY_JSON = os.path.join(BASE_DIR, "stock_dna_summary.json")


def compute_rsi_array(closes: np.ndarray, period: int = 14) -> np.ndarray:
    diff = np.diff(closes, prepend=closes[0])
    gain = pd.Series(np.where(diff > 0, diff, 0.0)).rolling(period, min_periods=5).mean().values
    loss = pd.Series(np.where(diff < 0, -diff, 0.0)).rolling(period, min_periods=5).mean().values
    rsi = 100.0 - (100.0 / (1.0 + (gain / (loss + 1e-5))))
    return np.nan_to_num(rsi, nan=50.0)


def compute_dominant_ma_dna(
    c: np.ndarray,
    l: np.ndarray,
    h: np.ndarray,
    ema_10: np.ndarray,
    sma_20: np.ndarray,
    sma_50: np.ndarray,
    sma_200: np.ndarray,
) -> tuple:
    """
    Classifies a stock's true structural support habit during Stage-2 uptrends
    by measuring where its 10-day swing pullback troughs consistently hold.
    """
    n = len(c)
    hold_10, hold_20, hold_50 = 0, 0, 0
    valid_swings = 0

    for i in range(55, n - 12):
        # Must be in a confirmed Stage-2 uptrend
        if not (c[i] > sma_50[i] and sma_50[i] > sma_200[i]):
            continue
        # Detect a local swing peak at bar i
        if h[i] >= np.max(h[i - 5 : i + 1]) and h[i] > np.max(h[i + 1 : i + 4]):
            trough_low = np.min(l[i + 1 : i + 11])
            trough_idx = i + 1 + int(np.argmin(l[i + 1 : i + 11]))
            # Verify the stock resumed higher within 10 bars after the trough
            if np.max(h[trough_idx : min(n, trough_idx + 11)]) >= h[i] * 0.995:
                valid_swings += 1
                if trough_low >= ema_10[trough_idx] * 0.992:
                    hold_10 += 1
                elif trough_low >= sma_20[trough_idx] * 0.988:
                    hold_20 += 1
                elif trough_low >= sma_50[trough_idx] * 0.980:
                    hold_50 += 1

    if valid_swings < 3:
        return "20-SMA Swing Compounder", 50.0

    shares = {
        "10-EMA Velocity Sprinter": (hold_10 / valid_swings) * 100.0,
        "20-SMA Swing Compounder": (hold_20 / valid_swings) * 100.0,
        "50-SMA Deep Undercutter": (hold_50 / valid_swings) * 100.0,
    }
    best_ma = max(shares, key=shares.get)
    return best_ma, round(float(shares[best_ma]), 1)


def compute_impulse_velocity_days(c: np.ndarray, h: np.ndarray, rvol: np.ndarray, sma_50: np.ndarray) -> float:
    """Computes median trading days required to travel +10% after a valid Stage-2 expansion bar."""
    n = len(c)
    days_list = []
    for i in range(50, n - 30):
        if rvol[i] >= 1.4 and c[i] > sma_50[i]:
            hits = np.where(h[i + 1 : i + 31] >= c[i] * 1.10)[0]
            if len(hits) > 0:
                days_list.append(int(hits[0]) + 1)
    return round(float(np.median(days_list)), 1) if len(days_list) >= 2 else 14.0


def build_comprehensive_stock_dna():
    found_files = glob.glob(os.path.join(CSV_STORE, "**/*.csv"), recursive=True)
    if not found_files:
        print(f"[!] No Bhavcopy CSVs found in {CSV_STORE}. Run pipeline.py first.")
        return

    symbol_meta = load_index_mappings()
    target_symbols = list(symbol_meta.keys())
    ensure_metadata(target_symbols)

    print(f"[*] Loading {len(found_files)} Bhavcopy sessions to build Pure Structural Stock DNA Profiles...")
    df_all = pd.concat([pd.read_csv(f) for f in found_files], ignore_index=True).drop_duplicates(subset=["symbol", "date"])
    df_all = df_all[df_all["symbol"].isin(target_symbols)]
    master_df = pd.read_csv(METADATA_FILE).drop_duplicates(subset=["symbol"])
    df_all = pd.merge(df_all, master_df, on="symbol", how="left").fillna(
        {"sector": "Capital Goods", "company_name": df_all["symbol"]}
    )
    df_all = df_all[df_all["sector"] != "General Equities"].sort_values(by=["symbol", "date"]).reset_index(drop=True)
    df_all, _ = normalize_corporate_actions(df_all)

    all_dates = sorted(df_all["date"].unique())
    mkt_close = df_all.groupby("date")["close"].mean().reindex(all_dates).ffill()
    mkt_ret_series = mkt_close.pct_change().fillna(0.0)

    sec_close_df = df_all.pivot_table(index="date", columns="sector", values="close", aggfunc="mean").reindex(all_dates).ffill()
    sec_ret_df = sec_close_df.pct_change().fillna(0.0)

    dna_records = []

    for sym, grp in df_all.groupby("symbol", sort=False):
        g = grp.sort_values("date").reset_index(drop=True)
        n = len(g)
        if n < 120:
            continue

        sec = str(g["sector"].iloc[-1])
        c = g["close"].values.astype(float)
        o = g["open"].values.astype(float)
        h = g["high"].values.astype(float)
        l = g["low"].values.astype(float)
        v = g["volume"].values.astype(float)
        dpct = g["deliv_pct"].values.astype(float) if "deliv_pct" in g.columns else np.full(n, 50.0)
        d_arr = g["date"].values

        p_ser = pd.Series(c)
        stk_ret = p_ser.pct_change().fillna(0.0).values
        m_ret = mkt_ret_series.reindex(d_arr).fillna(0.0).values
        s_ret = sec_ret_df[sec].reindex(d_arr).fillna(0.0).values if sec in sec_ret_df.columns else m_ret

        # ---------------------------------------------------------------------
        # PART A: 500-DAY PURE STRUCTURAL STOCK GENOME (LEAK-FREE)
        # ---------------------------------------------------------------------
        # 1. Asymmetric Regime Beta (Upside Beta vs Downside Beta & Sector Beta)
        w = min(250, n)
        sr_w, mr_w, secr_w = stk_ret[-w:], m_ret[-w:], s_ret[-w:]
        up_mask = mr_w > 0.004
        dn_mask = mr_w < -0.004
        upside_beta = float(np.cov(sr_w[up_mask], mr_w[up_mask])[0, 1] / (np.var(mr_w[up_mask]) + 1e-8)) if np.sum(up_mask) > 10 else 1.0
        downside_beta = float(np.cov(sr_w[dn_mask], mr_w[dn_mask])[0, 1] / (np.var(mr_w[dn_mask]) + 1e-8)) if np.sum(dn_mask) > 10 else 1.0
        beta_asymmetry = round(upside_beta - downside_beta, 2)
        sector_beta = float(np.cov(sr_w, secr_w)[0, 1] / (np.var(secr_w) + 1e-8))

        # 2. Kaufman Trend Efficiency Ratio (30D Coiled Elasticity vs Linear Trend)
        abs_daily_chg = np.abs(np.diff(c, prepend=c[0]))
        net_30 = np.abs(c - pd.Series(c).shift(30).bfill().values)
        sum_30 = pd.Series(abs_daily_chg).rolling(30, min_periods=10).sum().values + 1e-5
        er_30 = net_30 / sum_30
        median_er_30 = float(np.nanmedian(er_30[-180:]))
        current_er_30 = float(er_30[-1])

        # 3. Volatility & Wick Polarity (Supply Absorption vs Dip Rejection)
        prev_c = np.roll(c, 1); prev_c[0] = c[0]
        tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
        atr_20 = pd.Series(tr).rolling(20, min_periods=10).mean().values
        atr_pct_now = float((atr_20[-1] / (c[-1] + 1e-5)) * 100.0)
        median_atr_pct = float(np.nanmedian((atr_20[-180:] / (c[-180:] + 1e-5)) * 100.0))

        bar_span = (h - l) + 1e-5
        body = np.abs(c - o)
        wicks = np.maximum(0.0, (h - l) - body)
        wick_atr_ratio = float(np.nanmedian(wicks[-120:] / (atr_20[-120:] + 1e-5)))

        lower_wick_pct = (np.minimum(o, c) - l) / bar_span
        upper_wick_pct = (h - np.maximum(o, c)) / bar_span
        wick_polarity_score = round(float(np.nanmedian(lower_wick_pct[-120:] - upper_wick_pct[-120:])), 3)

        if wick_polarity_score >= 0.03:
            wick_polarity_dna = "Lower-Wick Support Absorber"
        elif wick_polarity_score <= -0.03:
            wick_polarity_dna = "Upper-Wick Supply Fader"
        else:
            wick_polarity_dna = "Balanced Candle Body"

        # 4. Moving Averages, Dominant MA Affinity & 20-SMA Undercut Elasticity
        ema_10 = p_ser.ewm(span=10, adjust=False).mean().values
        sma_20 = p_ser.rolling(20, min_periods=10).mean().values
        sma_50 = p_ser.rolling(50, min_periods=20).mean().values
        sma_200 = p_ser.rolling(200, min_periods=40).mean().values

        dominant_ma_dna, dominant_ma_bounce_pct = compute_dominant_ma_dna(c, l, h, ema_10, sma_20, sma_50, sma_200)

        stg2_mask = (c[-250:] > sma_50[-250:]) & (l[-250:] < sma_20[-250:])
        if np.any(stg2_mask):
            undercuts_atr = (sma_20[-250:][stg2_mask] - l[-250:][stg2_mask]) / (atr_20[-250:][stg2_mask] + 1e-5)
            normal_undercut_atr = float(np.percentile(undercuts_atr, 80))
        else:
            normal_undercut_atr = 0.75

        # 5. Breakout Follow-Through, Impulse Velocity & Phoenix Shakeout Recovery Rate
        vol_20 = pd.Series(v).rolling(20, min_periods=10).mean().values + 1e-5
        rvol = v / vol_20
        impulse_velocity_days = compute_impulse_velocity_days(c, h, rvol, sma_50)

        bo_idxs = np.where((rvol[:-21] >= 1.5) & (c[:-21] > o[:-21]) & (c[:-21] > sma_50[:-21]))[0]
        if len(bo_idxs) >= 3:
            ret_5d_after = [(c[i + 5] - c[i]) / c[i] for i in bo_idxs]
            mfe_20d_after = [(np.max(h[i + 1 : i + 21]) - c[i]) / c[i] for i in bo_idxs]
            bo_follow_5d_pct = float(np.mean([r > 0.015 for r in ret_5d_after]) * 100.0)
            bo_mfe_20d_pct = float(np.mean(mfe_20d_after) * 100.0)

            shakeout_cases = 0
            recovered_cases = 0
            for i in bo_idxs:
                min_10 = np.min(l[i + 1 : i + 11])
                dip_pct = (min_10 - c[i]) / c[i]
                if -0.08 <= dip_pct <= -0.045 and min_10 >= sma_50[i] * 0.97:
                    shakeout_cases += 1
                    if np.max(h[i + 5 : i + 21]) >= c[i] * 1.12:
                        recovered_cases += 1
            reentry_elasticity_pct = float((recovered_cases / shakeout_cases) * 100.0) if shakeout_cases > 0 else 55.0
        else:
            bo_follow_5d_pct = 50.0
            bo_mfe_20d_pct = 12.0
            reentry_elasticity_pct = 55.0

        # 6. Institutional Delivery Baseline, Gap Risk & Amihud Liquidity Impact
        base_deliv_pct = float(np.nanmedian(dpct[-180:]))
        overnight_gaps = np.abs(o[1:] - c[:-1]) / (c[:-1] + 1e-5)
        gap_freq_pct = float(np.mean(overnight_gaps[-180:] > 0.035) * 100.0)

        turnover_cr_arr = (v[-60:] * c[-60:]) / 10000000.0 + 1e-5
        amihud_impact_dna = round(float(np.nanmedian((np.abs(stk_ret[-60:]) * 100.0) / turnover_cr_arr)), 3)

        # ---------------------------------------------------------------------
        # PURE 100-POINT STRUCTURAL STOCK DNA SCORE (EMPIRICALLY CALIBRATED)
        #   1. Coiled Base Elasticity (30 pts): Rewards ER <= 0.22 (DNA-3/4 springs)
        #   2. Velocity & Asymmetric Fuel (25 pts): Rewards DNA-2 Rockets & Upside Beta
        #   3. Supply Absorption & Clean Support (20 pts): Rewards Upper-Wick Absorption + Tight Undercuts/Low Gaps
        #   4. Liquidity Depth & Re-Entry Elasticity (25 pts): Rewards Low Amihud Slippage + Phoenix Recovery
        # ---------------------------------------------------------------------
        coil_pts = float(np.clip(30.0 * (1.0 - ((median_er_30 - 0.14) / 0.18)), 5.0, 30.0))

        is_rocket = (upside_beta >= 1.35) and (median_atr_pct >= 3.60) and (bo_follow_5d_pct >= 48.0)
        vel_pts = 25.0 if is_rocket else float(np.clip(10.0 + (beta_asymmetry * 7.5) + max(0.0, (median_atr_pct - 2.8) * 3.0), 4.0, 22.0))

        wick_abs_pts = 8.0 if wick_polarity_dna == "Upper-Wick Supply Fader" else (5.0 if wick_polarity_dna == "Balanced Candle Body" else 3.0)
        support_clean_pts = (6.0 if normal_undercut_atr <= 1.20 else 2.5) + (6.0 if gap_freq_pct <= 3.0 else 2.5)
        supply_support_pts = wick_abs_pts + support_clean_pts

        liq_pts = float(np.clip(15.0 * (1.0 - (amihud_impact_dna / 0.12)), 3.0, 15.0))
        reentry_pts = float(np.clip((reentry_elasticity_pct / 75.0) * 10.0, 2.0, 10.0))
        liq_reentry_pts = liq_pts + reentry_pts

        stock_dna_score = round(float(np.clip(coil_pts + vel_pts + supply_support_pts + liq_reentry_pts, 10.0, 99.0)), 1)

        # ---------------------------------------------------------------------
        # PART B: LIVE POINT-IN-TIME OSCILLATOR SIGNALS (KEPT SEPARATE FROM DNA SCORE)
        # ---------------------------------------------------------------------
        rsi_daily = compute_rsi_array(c, 14)
        rsi_now = float(rsi_daily[-1])
        rsi_floor_30d = float(np.percentile(rsi_daily[-30:], 10))
        rsi_in_bull_zone = bool((rsi_now >= 52.0) and (rsi_floor_30d >= 42.0))
        rsi_hh_leading_price = bool((rsi_now >= np.max(rsi_daily[-25:-1])) and (c[-1] < np.max(h[-25:-1]) * 0.992))
        rsi_hl_structure = bool(np.min(rsi_daily[-7:]) > (np.min(rsi_daily[-22:-7]) + 2.5))
        hidden_bull_div = bool(
            (c[-1] > sma_50[-1])
            and (np.min(l[-7:]) > np.min(l[-25:-7]) * 1.005)
            and (np.min(rsi_daily[-7:]) < np.min(rsi_daily[-25:-7]) - 1.5)
            and (rsi_daily[-1] > rsi_daily[-2])
        )

        w_df = pd.DataFrame({"dt": pd.to_datetime(d_arr), "close": c}).set_index("dt")
        w_close = w_df["close"].resample("W-FRI").last().dropna().values
        if len(w_close) >= 16:
            w_rsi = compute_rsi_array(w_close, 14)
            weekly_rsi_now = float(w_rsi[-1])
            weekly_rsi_bull_zone = bool(weekly_rsi_now >= 52.0)
        else:
            weekly_rsi_now = rsi_now
            weekly_rsi_bull_zone = rsi_now >= 52.0

        ema_12 = p_ser.ewm(span=12, adjust=False).mean().values
        ema_26 = p_ser.ewm(span=26, adjust=False).mean().values
        macd_line = ema_12 - ema_26
        macd_signal = pd.Series(macd_line).ewm(span=9, adjust=False).mean().values
        macd_hist = macd_line - macd_signal
        macd_norm = macd_line / (atr_20 + 1e-5)

        macd_above_zero = bool(macd_line[-1] > 0.0)
        macd_hh_hl_above_zero = bool(
            (macd_line[-1] > 0.0)
            and (np.min(macd_line[-10:]) > np.min(macd_line[-28:-10]))
            and (np.max(macd_line[-10:]) >= np.max(macd_line[-28:-10]) * 0.95)
        )
        macd_bull_cross_above_zero = bool(
            (macd_line[-1] > 0.0) and (macd_hist[-1] > 0.0) and (np.min(macd_hist[-3:]) <= 0.0)
        )
        macd_high_zone_hook = bool(
            (macd_norm[-1] >= 0.70) and (macd_hist[-1] > macd_hist[-2]) and (macd_hist[-2] <= macd_hist[-3])
        )

        low_14 = pd.Series(l).rolling(14, min_periods=5).min().values
        high_14 = pd.Series(h).rolling(14, min_periods=5).max().values
        raw_k = np.clip(((c - low_14) / (high_14 - low_14 + 1e-5)) * 100.0, 0.0, 100.0)
        stoch_k = pd.Series(raw_k).rolling(3, min_periods=1).mean().values
        stoch_d = pd.Series(stoch_k).rolling(3, min_periods=1).mean().values
        stoch_pullback_hook = bool(
            (c[-1] > sma_50[-1])
            and (macd_line[-1] > 0.0)
            and (np.min(stoch_k[-4:]) <= 48.0)
            and (stoch_k[-1] > stoch_d[-1])
            and (stoch_k[-1] > stoch_k[-2])
        )

        # DNA Behavioral Archetype Classification
        avg_turnover_cr = float(np.nanmean((v[-30:] * c[-30:]) / 10000000.0))
        mcap_tier = classify_mcap_tier(sym, g["index_name"].iloc[-1] if "index_name" in g.columns else "", avg_turnover_cr)

        if median_er_30 < 0.17 and downside_beta > 1.25 and beta_asymmetry < 0.50:
            dna_type = "DNA-4: Coiled Mean-Reverter / Spring"
            opt_entry_rule = "High WR (85.4%) on 20-SMA/POC Reclaim out of tight coil"
            opt_sl_pct = -6.5
        elif is_rocket:
            dna_type = "DNA-2: Explosive Velocity Rocket"
            opt_entry_rule = "Buy Day-1 Ignition / MACD > 0 Cross in Bull Expansion"
            opt_sl_pct = -6.5
        elif wick_atr_ratio >= 0.58 or bo_follow_5d_pct < 42.0 or median_er_30 <= 0.22:
            dna_type = "DNA-3: Wicky Shakeout Reclaimer"
            opt_entry_rule = f"Bid at {dominant_ma_dna} Reclaim Hook; keep on Phoenix Re-Entry Watch"
            opt_sl_pct = -6.5
        else:
            dna_type = "DNA-1: Smooth Linear Compounder"
            opt_entry_rule = "Require Multi-Strategy Confluence or Beta Asymmetry >= +0.75"
            opt_sl_pct = -5.5 if "Tier 1" in mcap_tier else -6.0

        dna_records.append({
            "symbol": sym,
            "company_name": str(g["company_name"].iloc[-1]),
            "sector": sec,
            "mcap_tier": mcap_tier,
            "dna_archetype": dna_type,
            "stock_dna_score": stock_dna_score,
            "coil_pts": round(coil_pts, 1),
            "vel_pts": round(vel_pts, 1),
            "supply_support_pts": round(supply_support_pts, 1),
            "liq_reentry_pts": round(liq_reentry_pts, 1),
            "dominant_ma_dna": dominant_ma_dna,
            "dominant_ma_hold_pct": dominant_ma_bounce_pct,
            "impulse_velocity_days": impulse_velocity_days,
            "wick_polarity_dna": wick_polarity_dna,
            "wick_polarity_score": wick_polarity_score,
            "amihud_impact_dna": amihud_impact_dna,
            "reentry_elasticity_pct": round(reentry_elasticity_pct, 1),
            "optimal_entry_style": opt_entry_rule,
            "recommended_sl_pct": opt_sl_pct,
            "upside_beta": round(upside_beta, 2),
            "downside_beta": round(downside_beta, 2),
            "beta_asymmetry": beta_asymmetry,
            "sector_beta": round(sector_beta, 2),
            "median_er_30": round(median_er_30, 3),
            "current_er_30": round(current_er_30, 3),
            "median_atr_pct": round(median_atr_pct, 2),
            "current_atr_pct": round(atr_pct_now, 2),
            "wick_atr_ratio": round(wick_atr_ratio, 2),
            "normal_undercut_atr": round(normal_undercut_atr, 2),
            "bo_follow_5d_pct": round(bo_follow_5d_pct, 1),
            "bo_mfe_20d_pct": round(bo_mfe_20d_pct, 1),
            "base_deliv_pct": round(base_deliv_pct, 1),
            "gap_freq_pct": round(gap_freq_pct, 1),
            "daily_rsi_14": round(rsi_now, 1),
            "weekly_rsi_14": round(weekly_rsi_now, 1),
            "weekly_rsi_bull_zone": weekly_rsi_bull_zone,
            "rsi_in_bull_zone": rsi_in_bull_zone,
            "rsi_hh_leading_price": rsi_hh_leading_price,
            "rsi_hl_structure": rsi_hl_structure,
            "hidden_bull_div": hidden_bull_div,
            "macd_norm_atr": round(float(macd_norm[-1]), 2),
            "macd_above_zero": macd_above_zero,
            "macd_hh_hl_above_zero": macd_hh_hl_above_zero,
            "macd_bull_cross_above_zero": macd_bull_cross_above_zero,
            "macd_high_zone_hook": macd_high_zone_hook,
            "stoch_k_14": round(float(stoch_k[-1]), 1),
            "stoch_pullback_hook": stoch_pullback_hook,
        })

    dna_df = pd.DataFrame(dna_records).sort_values(by=["stock_dna_score", "beta_asymmetry"], ascending=False)
    dna_df.to_csv(DNA_OUTPUT_CSV, index=False)

    with open(DNA_SUMMARY_JSON, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_symbols_profiled": len(dna_df),
                "dna_archetype_distribution": dna_df["dna_archetype"].value_counts().to_dict(),
                "dominant_ma_distribution": dna_df["dominant_ma_dna"].value_counts().to_dict(),
                "wick_polarity_distribution": dna_df["wick_polarity_dna"].value_counts().to_dict(),
                "top_20_pure_structural_dna_leaders": dna_df.head(20)[
                    [
                        "symbol", "sector", "dna_archetype", "stock_dna_score",
                        "dominant_ma_dna", "wick_polarity_dna", "impulse_velocity_days",
                        "beta_asymmetry", "median_er_30", "amihud_impact_dna", "reentry_elasticity_pct"
                    ]
                ].to_dict(orient="records"),
            },
            f,
            indent=2,
        )

    print(f"[✓] Pure Structural Stock DNA (0-100) computed for {len(dna_df)} symbols -> {DNA_OUTPUT_CSV}")
    print(dna_df.head(15)[["symbol", "dna_archetype", "stock_dna_score", "dominant_ma_dna", "wick_polarity_dna", "median_er_30", "amihud_impact_dna"]].to_string(index=False))


if __name__ == "__main__":
    build_comprehensive_stock_dna()