import glob
import json
import os
from datetime import datetime
import pandas as pd
import numpy as np

# Import helper functions and constants from pipeline.py without modifying pipeline.py
from pipeline import (
    BASE_DIR,
    DATA_DIR,
    CSV_STORE,
    METADATA_FILE,
    NIFTY_50_SYMBOLS,
    NIFTY_NEXT_50_SYMBOLS,
    load_index_mappings,
    ensure_metadata,
    detect_genuine_chart_patterns,
)

BACKTEST_JSON = os.path.join(BASE_DIR, "backtest_data.json")
BACKTEST_SUMMARY_JSON = os.path.join(BASE_DIR, "backtest_summary.json")
BACKTEST_CSV = os.path.join(DATA_DIR, "backtest_results.csv")


def get_first_trading_date_on_or_after(all_dates: list, target_iso: str) -> str:
    """Finds the actual first NSE trading date in csv_store on or after a target date."""
    candidates = [d for d in all_dates if d >= target_iso]
    return candidates[0] if candidates else all_dates[-1]


def determine_monthly_dates(all_dates: list):
    """
    Generates the 10 point-in-time dates representing the 1st trading session
    of every month from January 2026 through October 2026.
    """
    monthly_checkpoints = []
    for month in range(1, 11):
        cal_date = f"2026-{month:02d}-01"
        trading_date = get_first_trading_date_on_or_after(all_dates, cal_date)
        dt = datetime.strptime(trading_date, "%Y-%m-%d")
        label = dt.strftime("%b %Y")
        monthly_checkpoints.append({
            "label": label,
            "month_num": month,
            "cal_date": cal_date,
            "date": trading_date,
        })
    return monthly_checkpoints, all_dates[-1]


def normalize_corporate_actions(df_all: pd.DataFrame) -> tuple:
    """
    Detects overnight Stock Splits and Bonus Issues in raw NSE Bhavcopy series
    (where open[t] / close[t-1] drops by >= 42% on the ex-date) and backward-adjusts
    historical OHLC & volume prior to the ex-date.
    """
    standard_ratios = np.array([0.50, 1.0 / 3.0, 0.25, 0.20, 0.10, 2.0 / 3.0, 0.40, 0.30])
    adjusted_groups = []
    adjusted_events = []

    for sym, grp in df_all.groupby("symbol", sort=False):
        g = grp.sort_values("date").copy()
        if len(g) < 5:
            adjusted_groups.append(g)
            continue

        closes = g["close"].values.astype(float)
        opens = g["open"].values.astype(float)
        highs = g["high"].values.astype(float)
        lows = g["low"].values.astype(float)
        vols = g["volume"].values.astype(float)
        delivs = g["deliv_qty"].values.astype(float)
        dates = g["date"].values

        for i in range(1, len(g)):
            prev_c = closes[i - 1]
            if prev_c <= 0:
                continue
            overnight_ratio = opens[i] / prev_c
            close_ratio = closes[i] / prev_c

            if 0.08 <= overnight_ratio <= 0.58 and 0.08 <= close_ratio <= 0.62:
                nearest_idx = int(np.argmin(np.abs(standard_ratios - overnight_ratio)))
                snap_ratio = float(standard_ratios[nearest_idx])
                adj_factor = snap_ratio if abs(overnight_ratio - snap_ratio) <= 0.06 else overnight_ratio

                closes[:i] *= adj_factor
                opens[:i] *= adj_factor
                highs[:i] *= adj_factor
                lows[:i] *= adj_factor
                vols[:i] = vols[:i] / max(adj_factor, 0.05)
                delivs[:i] = delivs[:i] / max(adj_factor, 0.05)

                adjusted_events.append({
                    "symbol": sym,
                    "ex_date": str(dates[i]),
                    "raw_prev_close": round(float(prev_c), 2),
                    "ex_open": round(float(opens[i]), 2),
                    "adj_factor": round(float(adj_factor), 4),
                })

        g["open"] = np.round(opens, 2)
        g["high"] = np.round(highs, 2)
        g["low"] = np.round(lows, 2)
        g["close"] = np.round(closes, 2)
        g["volume"] = np.round(vols, 0)
        g["deliv_qty"] = np.round(delivs, 0)
        adjusted_groups.append(g)

    df_clean = pd.concat(adjusted_groups, ignore_index=True).sort_values(by=["symbol", "date"]).reset_index(drop=True)
    return df_clean, adjusted_events


def classify_mcap_tier(symbol: str, index_name: str) -> str:
    """
    Classifies a constituent into a Market-Cap Risk Tier using NSE index membership.
    """
    sym_up = str(symbol).strip().upper()
    idx_up = str(index_name).upper()
    tokens = [t.strip() for t in idx_up.split(",") if t.strip()]

    if (
        sym_up in NIFTY_50_SYMBOLS
        or sym_up in NIFTY_NEXT_50_SYMBOLS
        or "NIFTY 50" in tokens
        or "NIFTY NEXT 50" in tokens
    ):
        return "Tier 1: Large Cap (Nifty 100)"
    if "NIFTY MIDCAP 150" in tokens:
        return "Tier 2: Mid Cap (Midcap 150)"
    if "NIFTY SMALLCAP 250" in tokens:
        return "Tier 3: Small Cap (Smallcap 250)"
    if "NIFTY MICROCAP 250" in tokens:
        return "Tier 4: Microcap (Microcap 250)"
    return "Tier 2/3: Mid & Small Cap (Nifty 500 Core)"


def classify_sector_lifecycle(row: pd.Series) -> tuple:
    """
    Identifies whether an outperforming sector is in Early Sector Rotation, Prime Leadership,
    or Climactic Exhaustion (Buyer Trap), and returns (lifecycle_label, score_multiplier).
    """
    p20 = float(row.get("perf_20d", 0.0))
    p63 = float(row.get("perf_63d", 0.0))
    sma50_pct = float(row.get("above_sma_pct", 50.0))
    adv_pct = float(row.get("advance_pct", 50.0))
    quad = str(row.get("quadrant", "Neutral"))
    rs_rat = float(row.get("rs_ratio", 100.0))

    mult = 1.0
    reasons = []

    if sma50_pct > 76.0:
        b_pen = float(np.clip(1.0 - ((sma50_pct - 76.0) / 34.0), 0.55, 1.0))
        mult *= b_pen
        reasons.append(f"Breadth Saturated ({sma50_pct:.0f}% >50SMA)")

    if p20 > 8.5:
        v_pen = float(np.clip(1.0 - ((p20 - 8.5) / 14.0), 0.45, 1.0))
        mult *= v_pen
        reasons.append(f"20D Parabolic (+{p20:.1f}%)")

    if p63 > 22.0 and sma50_pct > 68.0:
        m_pen = float(np.clip(1.0 - ((p63 - 22.0) / 32.0), 0.60, 1.0))
        mult *= m_pen
        reasons.append(f"63D Extended (+{p63:.1f}%)")

    if rs_rat >= 102.0 and adv_pct < 46.0:
        mult *= 0.78
        reasons.append("Internal Breadth Divergence")

    if reasons and mult <= 0.84:
        return f"⚠️ Climactic Exhaustion ({', '.join(reasons[:2])})", round(float(np.clip(mult, 0.42, 0.85)), 3)

    if quad == "Improving" or (quad == "Leading" and sma50_pct < 38.0):
        return "🔄 Early Sector Rotation", 1.08

    if quad in ["Leading", "Improving"] and 35.0 <= sma50_pct <= 76.0 and 0.3 <= p20 <= 8.5:
        bonus = 1.06 if (42.0 <= sma50_pct <= 70.0 and 1.0 <= p20 <= 6.5) else 1.03
        return "🟢 Prime Institutional Leadership", round(float(bonus), 3)

    if quad == "Weakening":
        return "🟡 Decelerating Sector", 0.80

    return "🔴 Lagging Sector Regime", 0.65


def evaluate_point_in_time(df_all: pd.DataFrame, cutoff_date: str):
    """
    Runs the quant engine strictly on real Bhavcopy data <= cutoff_date (zero lookahead bias).
    """
    df_past = df_all[df_all["date"] <= cutoff_date].copy()
    dates = sorted(df_past["date"].unique())
    if len(dates) < 25:
        raise ValueError(f"Insufficient trading sessions ({len(dates)}) before {cutoff_date}.")

    latest_date = dates[-1]
    latest_df = df_past[df_past["date"] == latest_date].copy().drop_duplicates(subset=["symbol"])

    lookback_idx_20 = max(0, len(dates) - 20)
    lookback_date_20 = dates[lookback_idx_20]
    df_20_ago = (
        df_past[df_past["date"] == lookback_date_20][["symbol", "close"]]
        .rename(columns={"close": "close_20d_ago"})
        .drop_duplicates(subset=["symbol"])
    )

    lookback_idx_63 = max(0, len(dates) - 63)
    lookback_date_63 = dates[lookback_idx_63]
    df_63_ago = (
        df_past[df_past["date"] == lookback_date_63][["symbol", "close"]]
        .rename(columns={"close": "close_63d_ago"})
        .drop_duplicates(subset=["symbol"])
    )

    sec_base = pd.merge(latest_df, df_20_ago, on="symbol", how="left")
    sec_base = pd.merge(sec_base, df_63_ago, on="symbol", how="left")
    sec_base["close_20d_ago"] = sec_base["close_20d_ago"].fillna(sec_base["close"])
    sec_base["close_63d_ago"] = sec_base["close_63d_ago"].fillna(sec_base["close"])

    df_250d_all = df_past[df_past["date"].isin(dates[-250:])].sort_values(by=["symbol", "date"])
    market_pivot = df_250d_all.pivot(index="date", columns="symbol", values="close").ffill().dropna(how="all")
    market_benchmark = market_pivot.mean(axis=1)

    sector_benchmarks = {}
    for sec_name, sec_grp in df_250d_all.groupby("sector"):
        if sec_name == "General Equities":
            continue
        sec_pivot = sec_grp.pivot(index="date", columns="symbol", values="close").ffill().dropna(how="all")
        if not sec_pivot.empty:
            sector_benchmarks[sec_name] = sec_pivot.mean(axis=1)

    mkt_len = len(market_benchmark)
    bm_ret_21 = (market_benchmark.iloc[-1] / (market_benchmark.iloc[-min(21, mkt_len)] + 1e-5)) - 1.0
    bm_ret_63 = (market_benchmark.iloc[-1] / (market_benchmark.iloc[-min(63, mkt_len)] + 1e-5)) - 1.0
    bm_ret_126 = (market_benchmark.iloc[-1] / (market_benchmark.iloc[-min(126, mkt_len)] + 1e-5)) - 1.0
    bm_ret_250 = (market_benchmark.iloc[-1] / (market_benchmark.iloc[0] + 1e-5)) - 1.0

    stock_tech_rows = []
    for sym, grp in df_250d_all.groupby("symbol"):
        prices = grp["close"].values
        volumes = grp["volume"].values
        highs = grp["high"].values
        lows = grp["low"].values
        deliv_qtys = grp["deliv_qty"].values
        opens = grp["open"].values

        n_bars = len(prices)
        if n_bars < 20:
            continue

        p_series = pd.Series(prices)
        close = float(prices[-1])
        sma_20 = round(float(np.mean(prices[-min(20, n_bars):])), 2)
        ema_10_series = p_series.ewm(span=10, adjust=False).mean()
        ema_21_series = p_series.ewm(span=21, adjust=False).mean()
        sma_50_series = p_series.rolling(min(50, n_bars), min_periods=10).mean()

        ema_10 = float(ema_10_series.iloc[-1])
        ema_21 = float(ema_21_series.iloc[-1])
        sma_50 = round(float(sma_50_series.iloc[-1]), 2)
        sma_50_10d_ago = float(sma_50_series.iloc[-min(10, len(sma_50_series))])
        sma_50_rising = sma_50 >= (sma_50_10d_ago * 0.998)
        sma_200 = round(float(p_series.rolling(min(200, n_bars), min_periods=20).mean().iloc[-1]), 2)

        tr_arr = np.maximum(
            highs[-20:] - lows[-20:],
            np.maximum(
                np.abs(highs[-20:] - np.roll(prices, 1)[-20:]),
                np.abs(lows[-20:] - np.roll(prices, 1)[-20:]),
            ),
        )
        atr_20 = float(np.mean(tr_arr))
        atr_pct = round(float((atr_20 / (close + 1e-5)) * 100.0), 2)

        # 1. Volume Profile POC
        poc_bars = min(50, n_bars)
        sub_highs = highs[-poc_bars:]
        sub_lows = lows[-poc_bars:]
        sub_vols = volumes[-poc_bars:]
        p_min, p_max = float(np.min(sub_lows)), float(np.max(sub_highs))
        
        if p_max > p_min:
            n_bins = 20
            bins = np.linspace(p_min, p_max, n_bins + 1)
            vol_profile = np.zeros(n_bins)
            typical_prices = (sub_highs + sub_lows + prices[-poc_bars:]) / 3.0
            bin_indices = np.clip(np.digitize(typical_prices, bins) - 1, 0, n_bins - 1)
            for b_idx, v_qty in zip(bin_indices, sub_vols):
                vol_profile[b_idx] += v_qty
            max_bin_idx = int(np.argmax(vol_profile))
            volume_profile_poc = round(float((bins[max_bin_idx] + bins[max_bin_idx + 1]) / 2.0), 2)
        else:
            volume_profile_poc = close

        # 2. Confluence Feature 1: Opening/Session Relative Volume (RVOL) Expansion
        vol_20_avg = float(np.mean(volumes[-min(20, n_bars):])) + 1e-5
        session_rvol = round(float(volumes[-1] / vol_20_avg), 2)
        is_rvol_expanded = session_rvol >= 1.5

        # 3. Confluence Feature 2: Supply Exhaustion Ratio (Up Volume vs Down Volume over trailing 15 sessions)
        sub_15_diff = np.diff(prices[-16:]) if n_bars >= 16 else np.diff(prices)
        sub_15_vols = volumes[-len(sub_15_diff):]
        up_vol_15 = np.sum(sub_15_vols[sub_15_diff > 0]) if np.any(sub_15_diff > 0) else 1.0
        down_vol_15 = np.sum(sub_15_vols[sub_15_diff < 0]) if np.any(sub_15_diff < 0) else 1.0
        supply_exhaustion_ratio = round(float(up_vol_15 / (down_vol_15 + 1e-5)), 2)

        # 4. Confluence Feature 3: Multi-Timeframe RS Slope Acceleration (10d vs 30d RS growth)
        stock_series = grp.set_index("date")["close"]
        common_s_idx = stock_series.index.intersection(market_benchmark.index)
        stk_sub = stock_series.loc[common_s_idx]
        bm_sub = market_benchmark.loc[common_s_idx]
        rs_full_series = (stk_sub / bm_sub).values
        if len(rs_full_series) >= 30:
            rs_slope_10 = (rs_full_series[-1] - rs_full_series[-10]) / (rs_full_series[-10] + 1e-5)
            rs_slope_30 = (rs_full_series[-1] - rs_full_series[-30]) / (rs_full_series[-30] + 1e-5)
            rs_acceleration = round(float(rs_slope_10 - (rs_slope_30 / 3.0)), 4)
        else:
            rs_acceleration = 0.0

        diffs = np.diff(prices)
        avg_g = np.mean(np.where(diffs > 0, diffs, 0)[-14:]) if len(diffs) >= 14 else 1.0
        avg_l = np.mean(np.where(diffs < 0, -diffs, 0)[-14:]) if len(diffs) >= 14 else 1.0
        rsi_14 = round(100.0 - (100.0 / (1.0 + (avg_g / (avg_l + 1e-5)))), 1)

        min_l, max_h = np.min(lows[-20:]), np.max(highs[-20:])
        stoch_k = round(float(np.clip((prices[-1] - min_l) / (max_h - min_l + 1e-5) * 100.0, 0, 100)), 1)

        ma_spread_pct = float(((max(ema_10, ema_21, sma_50) - min(ema_10, ema_21, sma_50)) / (close + 1e-5)) * 100.0)
        is_ma_pinched = ma_spread_pct <= 2.8

        roll_20 = p_series.rolling(20)
        bb_mid = float(roll_20.mean().iloc[-1])
        bb_std = float(roll_20.std().iloc[-1])
        upper_bb = bb_mid + (2.0 * bb_std)
        lower_bb = bb_mid - (2.0 * bb_std)
        upper_kc = sma_20 + (1.5 * atr_20)
        lower_kc = sma_20 - (1.5 * atr_20)
        is_squeezed = (upper_bb <= upper_kc) and (lower_bb >= lower_kc)

        bb_width = max(1e-4, upper_bb - lower_bb)
        kc_width = max(1e-4, upper_kc - lower_kc)
        bb_kc_ratio = float(bb_width / kc_width)

        vol_5d = float(np.mean(volumes[-5:]))
        vol_50d = float(np.mean(volumes[-min(50, n_bars):])) + 1e-5
        vol_dryup_ratio = float(vol_5d / vol_50d)

        sec_name = grp["sector"].iloc[-1] if "sector" in grp.columns else "Capital Goods"
        sec_bm = sector_benchmarks.get(sec_name, market_benchmark)
        sec_sub = sec_bm.reindex(common_s_idx).ffill().bfill()
        sec_rs_series = (stk_sub / (sec_sub + 1e-5)).values

        if len(rs_full_series) >= 63:
            rs_63_high = np.max(rs_full_series[-63:-1])
            price_63_high = np.max(highs[-63:-1])
            is_rs_divergent = (rs_full_series[-1] >= rs_63_high) and (close < price_63_high * 0.99)
        else:
            is_rs_divergent = False

        if len(sec_rs_series) >= 63:
            sec_rs_63_high = np.max(sec_rs_series[-63:-1])
            price_63_high_sec = np.max(highs[-63:-1])
            is_sec_rs_divergent = (sec_rs_series[-1] >= sec_rs_63_high) and (close < price_63_high_sec * 0.99)
            sec_rs_new_high = sec_rs_series[-1] >= np.max(sec_rs_series[-21:])
            sec_rs_outperforming = sec_rs_series[-1] >= sec_rs_series[-min(20, len(sec_rs_series))]
        elif len(sec_rs_series) >= 21:
            is_sec_rs_divergent = False
            sec_rs_new_high = sec_rs_series[-1] >= np.max(sec_rs_series[-21:])
            sec_rs_outperforming = sec_rs_series[-1] >= sec_rs_series[-min(20, len(sec_rs_series))]
        else:
            is_sec_rs_divergent = False
            sec_rs_new_high = True
            sec_rs_outperforming = True

        if is_sec_rs_divergent:
            sector_rs_status = "🎯 Sector RS Pre-Breakout"
        elif sec_rs_new_high:
            sector_rs_status = "🔥 Sector RS New High"
        elif sec_rs_outperforming:
            sector_rs_status = "🟢 Outperforming Sector"
        else:
            sector_rs_status = "🔴 Lagging Sector"

        is_pocket_pivot = False
        is_pocket_pivot_5d = False
        if n_bars >= 15:
            diffs_10 = np.diff(prices[-11:])
            down_vols = volumes[-10:][diffs_10 < 0]
            max_down_vol = np.max(down_vols) if len(down_vols) > 0 else 0
            is_pocket_pivot = (close > prices[-2]) and (volumes[-1] > max_down_vol) and (close >= ema_10)

            for back_i in range(1, min(6, n_bars - 11)):
                idx_end = n_bars - back_i
                c_bar = prices[idx_end]
                prev_bar = prices[idx_end - 1]
                v_bar = volumes[idx_end]
                d_10 = np.diff(prices[idx_end - 10 : idx_end + 1])
                dv_10 = volumes[idx_end - 9 : idx_end + 1][d_10 < 0]
                max_dv = np.max(dv_10) if len(dv_10) > 0 else 0
                if (c_bar > prev_bar) and (v_bar > max_dv) and (close >= ema_10 * 0.995) and (close >= c_bar * 0.985):
                    is_pocket_pivot_5d = True
                    break
        is_pocket_pivot_5d = is_pocket_pivot or is_pocket_pivot_5d

        base_high = float(np.max(highs[-min(30, n_bars):]))
        base_low = float(np.min(lows[-min(30, n_bars):]))
        base_depth_pct = float(((base_high - base_low) / (base_high + 1e-5)) * 100.0)

        stk_ret_21 = (close / (prices[-min(21, n_bars)] + 1e-5)) - 1.0
        stk_ret_63 = (close / (prices[-min(63, n_bars)] + 1e-5)) - 1.0
        stk_ret_126 = (close / (prices[-min(126, n_bars)] + 1e-5)) - 1.0
        stk_ret_250 = (close / (prices[0] + 1e-5)) - 1.0
        prior_63d_pct = round(float(stk_ret_63 * 100.0), 2)
        dist_from_50_pct = round(float(((close - sma_50) / (sma_50 + 1e-5)) * 100.0), 2)

        rs_spread_21 = (stk_ret_21 - bm_ret_21) * 100.0
        rs_spread_63 = (stk_ret_63 - bm_ret_63) * 100.0
        rs_spread_126 = (stk_ret_126 - bm_ret_126) * 100.0
        rs_spread_250 = (stk_ret_250 - bm_ret_250) * 100.0
        raw_multi_rs = float((0.40 * rs_spread_63) + (0.30 * rs_spread_126) + (0.20 * rs_spread_250) + (0.10 * rs_spread_21))

        vcp_rat, pattern, _ = detect_genuine_chart_patterns(prices, volumes, highs, lows)

        if len(diffs) >= 1:
            up_vol = np.sum(volumes[1:][diffs > 0][-50:]) if np.any(diffs > 0) else 1.0
            down_vol = np.sum(volumes[1:][diffs < 0][-50:]) if np.any(diffs < 0) else 1.0
            up_down_ratio = round(float(up_vol / (down_vol + 1e-5)), 2)
        else:
            up_down_ratio = 1.0

        deliv_cash_all = deliv_qtys[-min(30, n_bars):] * prices[-min(30, n_bars):]
        diffs_deliv = diffs[-min(29, len(diffs)):]
        deliv_up = np.sum(deliv_cash_all[1:][diffs_deliv > 0]) if np.any(diffs_deliv > 0) else 1.0
        deliv_down = np.sum(deliv_cash_all[1:][diffs_deliv < 0]) if np.any(diffs_deliv < 0) else 1.0
        deliv_flow_ratio = float(deliv_up / (deliv_down + 1e-5))
        
        recent_deliv_pct = float(np.mean(deliv_qtys[-5:] / (volumes[-5:] + 1e-5)) * 100.0) if np.sum(volumes[-5:]) > 0 else 30.0

        pinch_pts = float(np.clip(20.0 * (1.0 - (ma_spread_pct / 6.5)), 2.0, 20.0))
        squeeze_pts = float(np.clip(15.0 * (1.35 - bb_kc_ratio), 2.0, 15.0))
        flow_pts = float(np.clip(40.0 * (np.log1p(min(deliv_flow_ratio, 6.0)) / np.log1p(4.2)), 4.0, 40.0))
        base_pts = float(np.clip(25.0 * (1.0 - (base_depth_pct / 32.0)), 2.0, 25.0)) if close >= sma_50 else 4.0

        raw_iasis = pinch_pts + squeeze_pts + flow_pts + base_pts
        if close < sma_200 and close < sma_50:
            iasis_score = round(float(min(35.0, raw_iasis * 0.40)), 1)
        else:
            iasis_score = round(float(np.clip(raw_iasis, 10.0, 99.0)), 1)

        sma_200_20d_ago = np.mean(prices[-min(220, n_bars):-20]) if n_bars >= 30 else sma_200
        sma_200_slope = (sma_200 - sma_200_20d_ago) / (sma_200_20d_ago + 1e-5)
        h_52 = float(np.max(highs))
        l_52 = float(np.min(lows))
        trend_score = 0.0
        if close > sma_200:
            trend_score += 25.0
        if close > sma_50:
            trend_score += 25.0
        if sma_50 > sma_200:
            trend_score += 20.0
        if sma_200_slope >= 0:
            trend_score += 10.0
        if (close / (h_52 + 1e-5)) >= 0.75:
            trend_score += 10.0 * min(1.0, (close / (h_52 + 1e-5)) / 0.90)
        if (close / (l_52 + 1e-5)) >= 1.25:
            trend_score += 10.0 * min(1.0, ((close / (l_52 + 1e-5)) - 1.0) / 0.50)
        trend_score = round(float(np.clip(trend_score, 5.0, 99.0)), 1)

        raw_struct_stop = min(close - (2.2 * atr_20), sma_50 * 0.975)
        structural_stop = round(float(max(close * 0.915, raw_struct_stop)), 2)

        stock_tech_rows.append({
            "symbol": sym,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "sma_50_rising": sma_50_rising,
            "stage2_aligned": bool((close > sma_50) and (sma_50 > sma_200) and sma_50_rising),
            "ema_10": ema_10,
            "ema_21": ema_21,
            "rsi_14": rsi_14,
            "stoch_k": stoch_k,
            "atr_20": atr_20,
            "atr_pct": atr_pct,
            "structural_stop": structural_stop,
            "volume_profile_poc": volume_profile_poc,
            "poc_floor_support": bool(close >= volume_profile_poc),
            "session_rvol": session_rvol,
            "is_rvol_expanded": is_rvol_expanded,
            "supply_exhaustion_ratio": supply_exhaustion_ratio,
            "rs_acceleration": rs_acceleration,
            "deliv_pct": round(recent_deliv_pct, 1),
            "vcp_ratio": float(vcp_rat),
            "bb_kc_ratio": bb_kc_ratio,
            "ma_spread_pct": round(ma_spread_pct, 2),
            "vol_dryup_ratio": round(vol_dryup_ratio, 2),
            "chart_pattern_signal": pattern,
            "sector_rs_status": sector_rs_status,
            "iasis_score": iasis_score,
            "raw_multi_rs": raw_multi_rs,
            "trend_score": trend_score,
            "up_down_vol_ratio": up_down_ratio,
            "is_pocket_pivot": is_pocket_pivot,
            "is_pocket_pivot_5d": is_pocket_pivot_5d,
            "is_squeezed": is_squeezed,
            "is_ma_pinched": is_ma_pinched,
            "is_rs_divergent": (is_rs_divergent or is_sec_rs_divergent),
            "flow_ratio": round(deliv_flow_ratio, 2),
            "prior_63d_run_pct": prior_63d_pct,
            "prior_63d_run_pct": prior_63d_pct,
            "dist_from_50_pct": dist_from_50_pct,
            "base_depth_pct": round(base_depth_pct, 2),
        })

    ranked = pd.merge(latest_df, pd.DataFrame(stock_tech_rows), on="symbol", how="inner").drop_duplicates(subset=["symbol"])
    ranked = ranked[ranked["sector"] != "General Equities"].copy()

    ranked["mcap_tier"] = ranked.apply(lambda r: classify_mcap_tier(r["symbol"], r.get("index_name", "")), axis=1)
    ranked["mrs_score"] = (((ranked["close"] / (ranked["sma_20"] + 1e-5)) - 1.0) * 100.0).round(1)
    ranked["atr_stop_loss"] = ranked["structural_stop"]
    ranked["above_sma50"] = ranked["close"] >= ranked["sma_50"]
    ranked["above_200sma"] = ranked["close"] >= ranked["sma_200"]

    sec_base_clean = sec_base[sec_base["sector"] != "General Equities"].copy()
    sector_summary = (
        sec_base_clean.groupby("sector")
        .agg(
            daily_perf=("close", lambda x: round(float(((x - sec_base_clean.loc[x.index, "open"]) / (sec_base_clean.loc[x.index, "open"] + 1e-5)).mean() * 100.0), 2)),
            advance_pct=("close", lambda x: round(float((x > sec_base_clean.loc[x.index, "open"]).mean() * 100.0), 2)),
            perf_20d=("close", lambda x: round(float(((x - sec_base_clean.loc[x.index, "close_20d_ago"]) / (sec_base_clean.loc[x.index, "close_20d_ago"] + 1e-5)).mean() * 100.0), 2)),
            perf_63d=("close", lambda x: round(float(((x - sec_base_clean.loc[x.index, "close_63d_ago"]) / (sec_base_clean.loc[x.index, "close_63d_ago"] + 1e-5)).mean() * 100.0), 2)),
            stock_count=("symbol", "count"),
        )
        .reset_index()
    )

    above_sma50_map = ranked.groupby("sector")["above_sma50"].mean().mul(100.0).round(2).to_dict()
    sector_summary["above_sma_pct"] = sector_summary["sector"].map(lambda s: above_sma50_map.get(s, 50.0))
    sector_summary["rs_ratio"] = (100.0 + sector_summary["perf_20d"] * 0.35).round(2)
    sector_summary["rs_momentum"] = (100.0 + (sector_summary["advance_pct"] - 50.0) * 0.1).round(2)
    sector_summary["quadrant"] = sector_summary.apply(
        lambda r: "Leading"
        if r["rs_ratio"] >= 100 and r["rs_momentum"] >= 100
        else ("Improving" if r["rs_ratio"] < 100 and r["rs_momentum"] >= 100 else ("Weakening" if r["rs_ratio"] >= 100 else "Lagging")),
        axis=1,
    )

    lifecycle_res = sector_summary.apply(classify_sector_lifecycle, axis=1)
    sector_summary["sector_lifecycle"] = [r[0] for r in lifecycle_res]
    sector_summary["sector_climax_mult"] = [r[1] for r in lifecycle_res]

    raw_sec_comp = (
        0.45 * sector_summary["rs_ratio"]
        + 0.35 * (100.0 + (sector_summary["above_sma_pct"] - 50.0) * 0.15)
        + 0.20 * sector_summary["rs_momentum"]
    )
    sector_summary["sector_composite_score"] = (
        raw_sec_comp - np.where(sector_summary["sector_climax_mult"] < 0.88, (1.0 - sector_summary["sector_climax_mult"]) * 12.0, 0.0)
    ).round(2)

    sec_perf_map = dict(zip(sector_summary["sector"], sector_summary["perf_20d"]))
    sec_mult_map = dict(zip(sector_summary["sector"], sector_summary["sector_climax_mult"]))
    sec_life_map = dict(zip(sector_summary["sector"], sector_summary["sector_lifecycle"]))

    ranked["beta_neutral_mrs"] = (ranked["mrs_score"] - ranked["sector"].map(lambda s: sec_perf_map.get(s, 0.0))).round(1)
    ranked["sector_climax_mult"] = ranked["sector"].map(lambda s: sec_mult_map.get(s, 1.0))
    ranked["sector_lifecycle"] = ranked["sector"].map(lambda s: sec_life_map.get(s, "Neutral"))

    rs_percentile = (ranked["raw_multi_rs"].rank(pct=True) * 100.0).round(1)
    peer_rs_percentile = (ranked["beta_neutral_mrs"].rank(pct=True) * 100.0).round(1)
    up_down_pct = (ranked["up_down_vol_ratio"].rank(pct=True) * 100.0).round(1)

    s_pts = np.clip(28.0 * (1.35 - ranked["bb_kc_ratio"]), 4.0, 28.0)
    m_pts = np.clip(24.0 * (1.0 - (ranked["ma_spread_pct"] / 6.0)), 4.0, 24.0)
    v_pts = np.clip(24.0 * (1.0 - ((ranked["vcp_ratio"] - 0.40) / 0.60)), 5.0, 24.0)
    d_pts = (
        np.where(ranked["is_rs_divergent"], 14.0, 0.0)
        + np.where(ranked["is_pocket_pivot_5d"], 10.0, 0.0)
        + np.clip(6.0 * (1.0 - ranked["vol_dryup_ratio"]), 0.0, 6.0)
    )
    ignition_raw = s_pts + m_pts + v_pts + d_pts

    ext_multiplier = np.where(
        ranked["mrs_score"] <= 3.8,
        1.0,
        np.clip(1.0 - ((ranked["mrs_score"] - 3.8) / 6.0), 0.25, 1.0),
    )
    ranked["ignition_score"] = (ignition_raw * ext_multiplier).clip(5.0, 99.0).round(1)

    ranked["frontrunner_score"] = (
        0.30 * ranked["trend_score"]
        + 0.35 * rs_percentile
        + 0.20 * peer_rs_percentile
        + 0.15 * up_down_pct
    ).clip(5.0, 99.0).round(1)

    # Smooth Continuous High-Surety (Low-MAE) Score
    mrs_anchor_pts = 28.0 * np.exp(-((ranked["mrs_score"] - 0.5) ** 2) / 6.5)
    sma50_anchor_pts = 22.0 * np.clip(1.0 - (np.maximum(0.0, ranked["dist_from_50_pct"] - 1.2) / 7.5), 0.0, 1.0)
    base_tight_pts = 15.0 * np.clip(1.0 - (ranked["base_depth_pct"] / 25.0), 0.0, 1.0)

    p63 = ranked["prior_63d_run_pct"]
    mom_curve = np.where(
        p63 < 0.0,
        0.45,
        np.where(
            p63 < 6.0,
            0.55 + 0.45 * (p63 / 6.0),
            np.where(p63 <= 32.0, 1.0, np.clip(1.0 - ((p63 - 32.0) / 35.0), 0.65, 1.0)),
        ),
    )
    flow_curve = np.clip(0.65 + 0.35 * ((ranked["iasis_score"] - 48.0) / 18.0), 0.55, 1.05)

    raw_surety = (
        mrs_anchor_pts
        + sma50_anchor_pts
        + base_tight_pts
        + (0.20 * ranked["iasis_score"])
        + (0.15 * ranked["frontrunner_score"])
    )
    ranked["surety_score"] = (raw_surety * mom_curve * flow_curve * np.clip(ranked["sector_climax_mult"], 0.82, 1.06)).clip(5.0, 99.0).round(1)

    # Institutional Pattern & Advanced Factor Confluence Score (0 - 100)
    def calculate_confluence_score(r):
        pts = 0.0
        iasis = float(r.get("iasis_score", 50.0))
        deliv_pct = float(r.get("deliv_pct", 30.0))
        up_down = float(r.get("up_down_vol_ratio", 1.0))
        rvol_val = float(r.get("session_rvol", 1.0))
        supply_ex = float(r.get("supply_exhaustion_ratio", 1.0))
        rs_accel = float(r.get("rs_acceleration", 0.0))

        # Flow & Tape (30 max)
        if iasis >= 65.0:
            pts += 10.0
        elif iasis >= 55.0:
            pts += 6.0
        if deliv_pct >= 35.0:
            pts += 5.0
        if up_down >= 1.2:
            pts += 5.0
        if rvol_val >= 1.5:
            pts += 5.0
        if supply_ex >= 1.5:
            pts += 5.0

        # Volume Profile POC Floor & RS Acceleration (25 max)
        if bool(r.get("poc_floor_support", False)):
            pts += 15.0
        else:
            pts -= 10.0
        if rs_accel > 0.0:
            pts += 10.0

        # Sector & RS Leadership (25 max)
        s_rs = str(r.get("sector_rs_status", ""))
        front_score = float(r.get("frontrunner_score", 50.0))
        if "Leading" in s_rs or "New High" in s_rs:
            pts += 12.0
        elif "Lagging" not in s_rs:
            pts += 6.0
        if front_score >= 75.0:
            pts += 13.0
        elif front_score >= 60.0:
            pts += 8.0

        # Base Geometry & Low-Risk Equilibrium (20 max)
        if float(r.get("vcp_ratio", 1.0)) <= 0.65:
            pts += 8.0
        elif float(r.get("vcp_ratio", 1.0)) <= 0.80:
            pts += 4.0
        if -2.0 <= float(r.get("mrs_score", 0.0)) <= 4.5:
            pts += 6.0
        pts += 6.0

        return float(np.clip(round(pts, 1), 0.0, 100.0))

    ranked["pattern_confluence_score"] = ranked.apply(calculate_confluence_score, axis=1)

    def get_signal(r):
        c_pattern = r["chart_pattern_signal"]
        if r["mrs_score"] > 8.0:
            return "⚠️ Statistically Extended (>8% vs 20-SMA)"
        if r["is_pocket_pivot_5d"] and (r["is_squeezed"] or r["is_ma_pinched"]):
            return "🚀 Pocket Pivot Ignition"
        if c_pattern == "🚩 High-Tight Flag & Pole":
            return "🚩 Bull Flag & Pole"
        if c_pattern == "🎯 VCP Coiled Spring":
            return "🎯 VCP Coiled Spring"
        if r["is_rs_divergent"]:
            return "🎯 RS Pre-Breakout Coil"
        if r["flow_ratio"] >= 1.6 and r["above_200sma"]:
            return "⚡ Stealth Accumulation"
        if -3.0 <= r["mrs_score"] <= 0.5 and r["stoch_k"] < 35 and r["above_200sma"]:
            return "🔄 High-RS Pullback"
        if -0.5 <= r["mrs_score"] <= 3.5 and 45 <= r["rsi_14"] <= 65 and r["above_200sma"]:
            return "🟢 SMA Value-Confluence Zone"
        if r["frontrunner_score"] >= 80.0:
            return "🔥 Momentum Frontrunner"
        return "Consolidation / Base"

    ranked["inst_signal"] = ranked.apply(get_signal, axis=1)

    sec_adj = np.clip(ranked["sector_climax_mult"], 0.72, 1.06)

    ranked["score_kinetic_launchpad"] = (
        (0.30 * ranked["frontrunner_score"] + 0.30 * ranked["iasis_score"] + 0.20 * ranked["ignition_score"] + 0.20 * ranked["surety_score"]) * sec_adj
    ).round(1)
    ranked["score_surety_anchor"] = (
        (0.45 * ranked["surety_score"] + 0.30 * ranked["iasis_score"] + 0.25 * ranked["frontrunner_score"]) * sec_adj
    ).round(1)
    ranked["score_institutional_stealth"] = (
        (0.45 * ranked["iasis_score"] + 0.25 * ranked["frontrunner_score"] + 0.15 * ranked["ignition_score"] + 0.15 * ranked["surety_score"]) * sec_adj
    ).round(1)
    ranked["score_launchpad_vcp"] = (
        (0.40 * ranked["ignition_score"] + 0.25 * ranked["iasis_score"] + 0.20 * ranked["frontrunner_score"] + 0.15 * ranked["surety_score"]) * sec_adj
    ).round(1)
    ranked["score_sector_rs_leader"] = (
        (0.35 * peer_rs_percentile + 0.30 * ranked["frontrunner_score"] + 0.20 * ranked["iasis_score"] + 0.15 * ranked["surety_score"]) * sec_adj
    ).round(1)
    ranked["score_momentum_frontrunner"] = (
        (0.45 * ranked["frontrunner_score"] + 0.25 * ranked["trend_score"] + 0.15 * ranked["iasis_score"] + 0.15 * ranked["surety_score"]) * sec_adj
    ).round(1)
    ranked["score_high_rs_pullback"] = (
        (0.35 * ranked["frontrunner_score"] + 0.30 * (100.0 - ranked["stoch_k"]) + 0.20 * ranked["iasis_score"] + 0.15 * ranked["surety_score"]) * sec_adj
    ).round(1)
    ranked["score_quant_confluence"] = (
        (0.30 * ranked["ignition_score"] + 0.25 * ranked["iasis_score"] + 0.20 * rs_percentile + 0.15 * ranked["frontrunner_score"] + 0.10 * ranked["surety_score"]) * sec_adj
    ).round(1)
    ranked["score_baseline"] = (
        0.45 * ranked["frontrunner_score"] + 0.35 * ranked["ignition_score"] + 0.20 * ranked["iasis_score"]
    ).round(1)

    ranked["score_absolute_pure"] = (
        0.35 * ranked["frontrunner_score"]
        + 0.30 * ranked["iasis_score"]
        + 0.20 * ranked["surety_score"]
        + 0.15 * ranked["ignition_score"]
    ).round(1)

    return sector_summary, ranked


def lookup_real_close_on_or_after(symbol_df: pd.DataFrame, target_date: str):
    sub = symbol_df[symbol_df["date"] >= target_date]
    if not sub.empty:
        row = sub.iloc[0]
        return round(float(row["close"]), 2), str(row["date"])
    sub_before = symbol_df[symbol_df["date"] <= target_date]
    if not sub_before.empty:
        row = sub_before.iloc[-1]
        return round(float(row["close"]), 2), str(row["date"])
    return None, None


def simulate_signal_persistence(
    fut_slice: pd.DataFrame,
    entry_price: float,
    atr_20: float,
) -> dict:
    if fut_slice.empty or len(fut_slice) < 2:
        return {
            "zone_persistence_days": 1,
            "trend_persistence_days": 1,
            "active_5d": True,
            "active_10d": True,
        }

    closes = fut_slice["close"].values
    s20 = fut_slice["sma20_roll"].values
    s50 = fut_slice["sma50_roll"].values

    init_s50 = float(s50[0]) if len(s50) > 0 and not np.isnan(s50[0]) else entry_price * 0.95
    invalidation_level = max(entry_price * 0.915, min(entry_price - (2.2 * atr_20), init_s50 * 0.975))

    zone_days = 0
    window_20 = min(20, len(fut_slice))
    for i in range(window_20):
        c_val = float(closes[i])
        s20_val = float(s20[i]) if not np.isnan(s20[i]) else c_val
        s50_val = float(s50[i]) if not np.isnan(s50[i]) else c_val
        mrs_i = ((c_val / (s20_val + 1e-5)) - 1.0) * 100.0
        if c_val >= invalidation_level and c_val >= s50_val * 0.97 and -3.8 <= mrs_i <= 5.8:
            zone_days += 1

    trend_days = 0
    for i in range(len(fut_slice)):
        c_val = float(closes[i])
        s50_val = float(s50[i]) if not np.isnan(s50[i]) else c_val
        dynamic_floor = max(invalidation_level, s50_val * 0.965) if i >= 5 else invalidation_level
        if c_val >= dynamic_floor:
            trend_days += 1
        else:
            break

    return {
        "zone_persistence_days": max(1, int(zone_days)),
        "trend_persistence_days": max(1, int(trend_days)),
        "active_5d": bool(trend_days >= min(5, len(fut_slice))),
        "active_10d": bool(trend_days >= min(10, len(fut_slice))),
    }


def simulate_structural_trailing_exit(
    fut_slice: pd.DataFrame,
    entry_price: float,
    atr_20: float,
    sma50_series: np.ndarray,
    sma20_series: np.ndarray,
) -> float:
    if fut_slice.empty or len(fut_slice) < 2:
        return 0.0

    closes = fut_slice["close"].values
    highs = fut_slice["high"].values

    init_s50 = float(sma50_series[0]) if len(sma50_series) > 0 else entry_price * 0.95
    initial_stop = max(entry_price * 0.915, min(entry_price - (2.2 * atr_20), init_s50 * 0.975))

    stage = 0
    running_peak = entry_price

    for idx in range(1, len(fut_slice)):
        c_val = float(closes[idx])
        h_val = float(highs[idx])
        s50_val = float(sma50_series[idx])
        s20_val = float(sma20_series[idx])

        if h_val > running_peak:
            running_peak = h_val

        if running_peak >= entry_price * 1.40:
            stage = 2
        elif running_peak >= entry_price * 1.20 and stage < 1:
            stage = 1

        if stage == 0:
            if c_val < initial_stop:
                return round(((c_val - entry_price) / entry_price) * 100.0, 2)
        elif stage == 1:
            dynamic_stop = max(entry_price * 1.05, s50_val * 0.975)
            if c_val < dynamic_stop:
                return round(((c_val - entry_price) / entry_price) * 100.0, 2)
        else:
            dynamic_stop = max(entry_price * 1.20, s50_val * 0.99, s20_val * 0.955, running_peak * 0.84)
            if c_val < dynamic_stop:
                return round(((c_val - entry_price) / entry_price) * 100.0, 2)

    final_close = float(closes[-1])
    return round(((final_close - entry_price) / entry_price) * 100.0, 2)


def simulate_ideal_buy_trigger(
    sym_df_with_mas: pd.DataFrame,
    signal_date: str,
    mrs_at_t0: float,
    atr_at_t0: float,
    today_price: float,
) -> dict:
    fut_all = sym_df_with_mas[sym_df_with_mas["date"] >= signal_date].reset_index(drop=True)
    if len(fut_all) < 2:
        return {
            "triggered": False,
            "trigger_type": "⏳ Pending Confirmation",
            "trigger_date": signal_date,
            "wait_days": 0,
            "ideal_entry_price": 0.0,
            "ideal_mfe_pct": 0.0,
            "ideal_mae_pct": 0.0,
            "ideal_hold_ret_pct": 0.0,
            "ideal_trail_ret_pct": 0.0,
        }

    t0_high = float(fut_all["high"].iloc[0])
    t0_close = float(fut_all["close"].iloc[0])
    is_pocket_t0 = bool(fut_all["is_pocket_pivot_5d"].iloc[0]) if "is_pocket_pivot_5d" in fut_all.columns else (
        bool(fut_all["is_pocket_pivot"].iloc[0]) if "is_pocket_pivot" in fut_all.columns else False
    )

    init_s50 = float(fut_all["sma50_roll"].iloc[0]) if not np.isnan(fut_all["sma50_roll"].iloc[0]) else t0_close * 0.95
    invalidation_level = max(t0_close * 0.915, min(t0_close - (2.2 * atr_at_t0), init_s50 * 0.975))

    if (mrs_at_t0 <= 1.8) or (is_pocket_t0 and mrs_at_t0 <= 4.8):
        post_slice = fut_all.copy()
        pk = float(post_slice["high"].max())
        lw = float(post_slice["low"].min())
        return {
            "triggered": True,
            "trigger_type": "🟢 20-SMA Equilibrium (+1d)" if mrs_at_t0 <= 1.8 else "🚀 Pocket Pivot Ignition",
            "trigger_date": signal_date,
            "wait_days": 0,
            "ideal_entry_price": t0_close,
            "ideal_mfe_pct": round(((pk - t0_close) / t0_close) * 100.0, 2),
            "ideal_mae_pct": round(((lw - t0_close) / t0_close) * 100.0, 2),
            "ideal_hold_ret_pct": round(((today_price - t0_close) / t0_close) * 100.0, 2) if today_price else 0.0,
            "ideal_trail_ret_pct": simulate_structural_trailing_exit(
                post_slice, t0_close, atr_at_t0, post_slice["sma50_roll"].values, post_slice["sma20_roll"].values
            ),
        }

    triggered_idx = None
    ideal_entry_price = None
    trigger_type = None
    consecutive_sma_breaks = 0

    for idx in range(1, len(fut_all)):
        row = fut_all.iloc[idx]
        prev_row = fut_all.iloc[idx - 1]

        o_val = float(row["open"])
        h_val = float(row["high"])
        l_val = float(row["low"])
        c_val = float(row["close"])
        s20_val = float(row["sma20_roll"])
        s50_val = float(row["sma50_roll"]) if not np.isnan(row["sma50_roll"]) else c_val
        prev_c = float(prev_row["close"])

        if c_val < invalidation_level or c_val < s50_val * 0.965:
            consecutive_sma_breaks += 1
            if consecutive_sma_breaks >= 2:
                break
        else:
            consecutive_sma_breaks = 0

        is_green_bar = (c_val > o_val) and (c_val >= prev_c * 0.998)

        if mrs_at_t0 <= 2.2:
            pivot_trigger = round(t0_high * 1.0015, 2)
            if h_val >= pivot_trigger and c_val > o_val:
                triggered_idx = idx
                ideal_entry_price = round(max(o_val, min(h_val, pivot_trigger)), 2)
                trigger_type = f"🚀 Pivot Expansion (+{idx}d)"
                break
            elif l_val <= s20_val * 1.012 and c_val >= s50_val * 0.98 and is_green_bar:
                triggered_idx = idx
                ideal_entry_price = round(c_val, 2)
                trigger_type = f"🟢 20-SMA Support Test (+{idx}d)"
                break
        else:
            if l_val <= s20_val * 1.018 and c_val >= s50_val * 0.975 and is_green_bar:
                potential_entry = round(c_val, 2)
                if potential_entry <= t0_close * 0.998:
                    triggered_idx = idx
                    ideal_entry_price = potential_entry
                    trigger_type = f"🔄 Mean-Reversion @ 20SMA (+{idx}d)"
                    break

    if triggered_idx is None:
        return {
            "triggered": False,
            "trigger_type": "🛡️ Filtered Waterfall (Structure Broken)",
            "trigger_date": signal_date,
            "wait_days": 0,
            "ideal_entry_price": t0_close,
            "ideal_mfe_pct": 0.0,
            "ideal_mae_pct": 0.0,
            "ideal_hold_ret_pct": 0.0,
            "ideal_trail_ret_pct": 0.0,
        }

    post_trigger_slice = fut_all.iloc[triggered_idx:].reset_index(drop=True)
    trig_date = str(post_trigger_slice["date"].iloc[0])

    peak_after_trig = float(post_trigger_slice["high"].max())
    low_after_trig = float(post_trigger_slice["low"].min())

    ideal_mfe = round(((peak_after_trig - ideal_entry_price) / ideal_entry_price) * 100.0, 2)
    ideal_mae = round(((low_after_trig - ideal_entry_price) / ideal_entry_price) * 100.0, 2)
    ideal_hold_ret = round(((today_price - ideal_entry_price) / ideal_entry_price) * 100.0, 2) if today_price else 0.0

    ideal_trail_ret = simulate_structural_trailing_exit(
        post_trigger_slice,
        ideal_entry_price,
        atr_at_t0,
        post_trigger_slice["sma50_roll"].values,
        post_trigger_slice["sma20_roll"].values,
    )

    return {
        "triggered": True,
        "trigger_type": trigger_type,
        "trigger_date": trig_date,
        "wait_days": int(triggered_idx),
        "ideal_entry_price": ideal_entry_price,
        "ideal_mfe_pct": ideal_mfe,
        "ideal_mae_pct": ideal_mae,
        "ideal_hold_ret_pct": ideal_hold_ret,
        "ideal_trail_ret_pct": ideal_trail_ret,
    }


def select_top_stocks_for_model(
    model_name: str,
    ranked_at_q: pd.DataFrame,
    sector_summary: pd.DataFrame,
    target_count: int = 20,
) -> tuple:
    valid_secs = sector_summary[
        (sector_summary["stock_count"] >= 5)
        & (sector_summary["sector"] != "General Equities")
    ].copy()

    prime_secs = valid_secs[
        (valid_secs["quadrant"].isin(["Leading", "Improving"]))
        & (valid_secs["sector_climax_mult"] >= 0.85)
        & (valid_secs["perf_20d"] <= 11.5)
    ].sort_values(by=["sector_composite_score", "above_sma_pct", "rs_ratio"], ascending=False)

    if len(prime_secs) >= 6:
        top_sectors_df = prime_secs.head(6)
    else:
        fallback_secs = valid_secs[
            valid_secs["quadrant"].isin(["Leading", "Improving"])
        ].sort_values(by=["sector_composite_score", "rs_ratio"], ascending=False)
        top_sectors_df = pd.concat([prime_secs, fallback_secs, valid_secs], ignore_index=True).drop_duplicates(subset=["sector"]).head(6)

    top_sector_names = list(top_sectors_df["sector"].values)
    top_3_sectors = top_sectors_df.head(3).to_dict(orient="records")
    top_5_sectors = top_sectors_df.head(5).to_dict(orient="records")

    pool = ranked_at_q.copy()
    score_col = f"score_{model_name}" if f"score_{model_name}" in pool.columns else "score_kinetic_launchpad"

    if model_name == "kinetic_launchpad":
        qualified = pool[
            (pool["stage2_aligned"])
            & (pool["frontrunner_score"] >= 74.0)
            & (pool["iasis_score"] >= 58.0)
            & (pool["mrs_score"] >= -2.5)
            & (pool["mrs_score"] <= 4.5)
            & (pool["dist_from_50_pct"] <= 9.0)
            & (pool["prior_63d_run_pct"] >= 6.5)
            & (pool["prior_63d_run_pct"] <= 35.0)
            & (pool["base_depth_pct"] <= 24.0)
            & (pool["flow_ratio"] >= 1.15)
            & (pool["sector_rs_status"] != "🔴 Lagging Sector")
            & (~pool["inst_signal"].str.contains("Extended"))
        ].sort_values(by=[score_col, "surety_score", "frontrunner_score"], ascending=False)

    elif model_name == "surety_anchor":
        qualified = pool[
            (pool["stage2_aligned"])
            & (pool["surety_score"] >= 58.0)
            & (pool["iasis_score"] >= 58.0)
            & (pool["frontrunner_score"] >= 73.0)
            & (pool["mrs_score"] >= -2.2)
            & (pool["mrs_score"] <= 2.2)
            & (pool["dist_from_50_pct"] <= 5.5)
            & (pool["prior_63d_run_pct"] >= 6.5)
            & (pool["prior_63d_run_pct"] <= 32.0)
            & (pool["base_depth_pct"] <= 22.0)
            & (pool["sector_rs_status"] != "🔴 Lagging Sector")
        ].sort_values(by=[score_col, "surety_score"], ascending=False)

    elif model_name == "institutional_stealth":
        qualified = pool[
            (pool["stage2_aligned"])
            & (pool["iasis_score"] >= 60.0)
            & (pool["flow_ratio"] >= 1.25)
            & (pool["up_down_vol_ratio"] >= 1.10)
            & (pool["mrs_score"] <= 5.0)
            & (pool["prior_63d_run_pct"] >= 5.0)
            & (pool["sector_rs_status"] != "🔴 Lagging Sector")
            & (~pool["inst_signal"].str.contains("Extended"))
        ].sort_values(by=[score_col, "iasis_score"], ascending=False)

    elif model_name == "launchpad_vcp":
        qualified = pool[
            (pool["stage2_aligned"])
            & (pool["frontrunner_score"] >= 72.0)
            & (pool["prior_63d_run_pct"] >= 6.0)
            & (pool["prior_63d_run_pct"] <= 32.0)
            & (pool["mrs_score"] >= -2.5)
            & (pool["mrs_score"] <= 4.5)
            & (pool["dist_from_50_pct"] <= 9.5)
            & (pool["ignition_score"] >= 42.0)
            & (~pool["inst_signal"].str.contains("Extended"))
        ].sort_values(by=[score_col, "ignition_score"], ascending=False)

    elif model_name == "sector_rs_leader":
        qualified = pool[
            (pool["stage2_aligned"])
            & (pool["sector_rs_status"].isin(["🔥 Sector RS New High", "🎯 Sector RS Pre-Breakout"]))
            & (pool["mrs_score"] <= 5.0)
            & (pool["prior_63d_run_pct"] >= 6.0)
            & (pool["prior_63d_run_pct"] <= 38.0)
            & (~pool["inst_signal"].str.contains("Extended"))
        ].sort_values(by=[score_col, "raw_multi_rs"], ascending=False)

    elif model_name == "momentum_frontrunner":
        qualified = pool[
            (pool["stage2_aligned"])
            & (pool["trend_score"] >= 75.0)
            & (pool["frontrunner_score"] >= 78.0)
            & (pool["mrs_score"] <= 6.5)
            & (pool["dist_from_50_pct"] <= 12.5)
            & (pool["prior_63d_run_pct"] >= 8.0)
            & (pool["sector_rs_status"] != "🔴 Lagging Sector")
        ].sort_values(by=[score_col, "frontrunner_score"], ascending=False)

    elif model_name == "high_rs_pullback":
        qualified = pool[
            (pool["above_200sma"])
            & (pool["close"] >= pool["sma_50"] * 0.985)
            & (pool["frontrunner_score"] >= 73.0)
            & (pool["prior_63d_run_pct"] >= 6.0)
            & (pool["mrs_score"] >= -4.0)
            & (pool["mrs_score"] <= 1.5)
            & ((pool["rsi_14"] <= 56.0) | (pool["stoch_k"] <= 45.0))
            & (pool["sector_rs_status"] != "🔴 Lagging Sector")
        ].sort_values(by=[score_col, "frontrunner_score"], ascending=False)

    elif model_name == "quant_confluence":
        qualified = pool[
            (pool["stage2_aligned"])
            & (pool["mrs_score"] <= 4.5)
            & (pool["dist_from_50_pct"] <= 10.0)
            & (pool["prior_63d_run_pct"] >= 6.0)
            & (pool["prior_63d_run_pct"] <= 35.0)
            & (pool["ignition_score"] >= 40.0)
            & (pool["iasis_score"] >= 58.0)
            & (pool["sector_rs_status"] != "🔴 Lagging Sector")
            & (~pool["inst_signal"].str.contains("Extended"))
        ].sort_values(by=[score_col, "ignition_score"], ascending=False)

    else:
        qualified = pool[pool["above_200sma"]].sort_values(by=["score_baseline"], ascending=False)

    seen_sectors = {}
    capped_picks = []

    for _, row in qualified.iterrows():
        sec = row["sector"]
        cnt = seen_sectors.get(sec, 0)
        if cnt < 2:
            capped_picks.append(row)
            seen_sectors[sec] = cnt + 1
        if len(capped_picks) >= target_count:
            break

    if len(capped_picks) < target_count:
        remaining_needed = target_count - len(capped_picks)
        used_syms = {r["symbol"] for r in capped_picks}
        extras = qualified[~qualified["symbol"].isin(used_syms)].head(remaining_needed)
        selected = pd.concat([pd.DataFrame(capped_picks), extras], ignore_index=True).head(target_count)
    else:
        selected = pd.DataFrame(capped_picks).head(target_count)

    return top_3_sectors, top_5_sectors, selected, top_sector_names


def evaluate_candidate_slice(
    df_candidates: pd.DataFrame,
    symbol_groups: dict,
    m_start_date: str,
    latest_date_overall: str,
) -> dict:
    if df_candidates.empty:
        return {
            "count": 0,
            "hold_win_rate_pct": 0.0,
            "trail_win_rate_pct": 0.0,
            "avg_mfe_pct": 0.0,
            "hit_15pct_rate": 0.0,
            "low_mae_rate": 0.0,
            "avg_mae_pct": 0.0,
            "avg_hold_ret_pct": 0.0,
            "avg_trail_ret_pct": 0.0,
            "conf_count": 0,
            "conf_mfe_pct": 0.0,
            "conf_mae_pct": 0.0,
            "conf_trail_ret_pct": 0.0,
            "top_winners": [],
            "top_losers": [],
            "tickers": [],
        }

    mfes, maes, rets, trails = [], [], [], []
    conf_mfes, conf_maes, conf_trails = [], [], []
    ticker_details = []

    for _, stk_row in df_candidates.iterrows():
        sym = str(stk_row["symbol"])
        sym_df = symbol_groups.get(sym, pd.DataFrame())
        if sym_df.empty:
            continue

        entry_price = round(float(stk_row["close"]), 2)
        atr_20_val = float(stk_row["atr_20"])
        mrs_t0 = float(stk_row["mrs_score"])
        today_price, _ = lookup_real_close_on_or_after(sym_df, latest_date_overall)

        fut_slice = sym_df[sym_df["date"] >= m_start_date].reset_index(drop=True)
        if fut_slice.empty:
            continue

        peak_high = float(fut_slice["high"].max())
        min_low = float(fut_slice["low"].min())
        mfe_pct = round(((peak_high - entry_price) / entry_price) * 100.0, 2)
        mae_pct = round(((min_low - entry_price) / entry_price) * 100.0, 2)
        hold_ret = round(((today_price - entry_price) / entry_price) * 100.0, 2) if today_price else 0.0
        trail_ret = simulate_structural_trailing_exit(
            fut_slice, entry_price, atr_20_val, fut_slice["sma50_roll"].values, fut_slice["sma20_roll"].values
        )
        ideal_sim = simulate_ideal_buy_trigger(sym_df, m_start_date, mrs_t0, atr_20_val, today_price)

        mfes.append(mfe_pct)
        maes.append(mae_pct)
        rets.append(hold_ret)
        trails.append(trail_ret)

        if ideal_sim["triggered"]:
            conf_mfes.append(ideal_sim["ideal_mfe_pct"])
            conf_maes.append(ideal_sim["ideal_mae_pct"])
            conf_trails.append(ideal_sim["ideal_trail_ret_pct"])

        ticker_details.append({
            "symbol": sym,
            "sector": str(stk_row.get("sector", "")),
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "hold_ret_pct": hold_ret,
            "trail_ret_pct": ideal_sim["ideal_trail_ret_pct"] if ideal_sim["triggered"] else trail_ret,
            "triggered": ideal_sim["triggered"],
        })

    sorted_by_ret = sorted(ticker_details, key=lambda x: x["hold_ret_pct"], reverse=True)
    top_w = [f"{x['symbol']}({x['hold_ret_pct']:+.1f}%/MFE:+{x['mfe_pct']:.0f}%)" for x in sorted_by_ret[:3]]
    top_l = [f"{x['symbol']}({x['hold_ret_pct']:+.1f}%/Trail:{x['trail_ret_pct']:+.1f}%)" for x in sorted_by_ret[-2:]]

    return {
        "count": len(rets),
        "hold_win_rate_pct": round(float((np.array(rets) > 0).mean() * 100.0), 1),
        "trail_win_rate_pct": round(float((np.array(trails) > 0).mean() * 100.0), 1),
        "avg_mfe_pct": round(float(np.mean(mfes)), 2),
        "hit_15pct_rate": round(float((np.array(mfes) >= 15.0).mean() * 100.0), 1),
        "low_mae_rate": round(float((np.array(maes) >= -6.0).mean() * 100.0), 1),
        "avg_mae_pct": round(float(np.mean(maes)), 2),
        "avg_hold_ret_pct": round(float(np.mean(rets)), 2),
        "avg_trail_ret_pct": round(float(np.mean(trails)), 2),
        "conf_count": len(conf_trails),
        "conf_mfe_pct": round(float(np.mean(conf_mfes)), 2) if conf_mfes else 0.0,
        "conf_mae_pct": round(float(np.mean(conf_maes)), 2) if conf_maes else 0.0,
        "conf_trail_ret_pct": round(float(np.mean(conf_trails)), 2) if conf_trails else 0.0,
        "top_winners": top_w,
        "top_losers": top_l,
        "tickers": [x["symbol"] for x in ticker_details],
    }


def run_intramonth_timing_audit(symbol_groups: dict, all_dates: list, latest_date_overall: str) -> list:
    eval_dates = [d for d in all_dates if "2026-01-01" <= d <= "2026-09-15"]
    window_buckets = {
        "Window 1: Days 01-05 (Month-Start / Post-Expiry)": [],
        "Window 2: Days 06-10 (Early-Month 20-SMA Pullback)": [],
        "Window 3: Days 11-16 (Mid-Month Equilibrium Coil)": [],
        "Window 4: Days 17-23 (Pre-Rollover Support Test)": [],
        "Window 5: Days 24-31 (F&O Expiry Rollover Base)": [],
    }

    for sig_date in eval_dates[::2]:
        day_num = int(sig_date.split("-")[2])
        if day_num <= 5:
            b_key = "Window 1: Days 01-05 (Month-Start / Post-Expiry)"
        elif day_num <= 10:
            b_key = "Window 2: Days 06-10 (Early-Month 20-SMA Pullback)"
        elif day_num <= 16:
            b_key = "Window 3: Days 11-16 (Mid-Month Equilibrium Coil)"
        elif day_num <= 23:
            b_key = "Window 4: Days 17-23 (Pre-Rollover Support Test)"
        else:
            b_key = "Window 5: Days 24-31 (F&O Expiry Rollover Base)"

        for sym, g in symbol_groups.items():
            row_match = g[g["date"] == sig_date]
            if row_match.empty:
                continue
            r = row_match.iloc[0]
            if not (r["above_200_roll"] and r["above_50_roll"]):
                continue
            mrs_v = float(r["mrs_roll"])
            dist50_v = float(r["dist50_roll"])
            if not (-2.0 <= mrs_v <= 2.5 and dist50_v <= 6.0 and r["is_pocket_or_coil"]):
                continue

            fut = g[g["date"] >= sig_date]
            if len(fut) < 15:
                continue
            entry_p = float(r["close"])
            pk_p = float(fut["high"].max())
            lw_p = float(fut["low"].min())
            end_p = float(fut["close"].iloc[-1])

            mfe = ((pk_p - entry_p) / entry_p) * 100.0
            mae = ((lw_p - entry_p) / entry_p) * 100.0
            ret = ((end_p - entry_p) / entry_p) * 100.0
            window_buckets[b_key].append((mfe, mae, ret))

    audit_summary = []
    for w_name, items in window_buckets.items():
        if not items:
            continue
        mfes = np.array([x[0] for x in items])
        maes = np.array([x[1] for x in items])
        rets = np.array([x[2] for x in items])
        audit_summary.append({
            "window": w_name,
            "sample_signals": len(items),
            "avg_peak_mfe_pct": round(float(np.mean(mfes)), 2),
            "hit_15pct_rate": round(float((mfes >= 15.0).mean() * 100.0), 1),
            "low_mae_surety_rate": round(float((maes >= -6.0).mean() * 100.0), 1),
            "avg_mae_pct": round(float(np.mean(maes)), 2),
            "avg_period_ret_pct": round(float(np.mean(rets)), 2),
            "asymmetry_ratio": round(float(np.mean(mfes) / max(1.0, abs(np.mean(maes)))), 2),
        })
    return audit_summary


def run_quarterly_backtest():
    found_files = glob.glob(os.path.join(CSV_STORE, "**/*.csv"), recursive=True)
    if not found_files:
        print("[!] No Bhavcopy CSV files found in ./data/csv_store. Please run pipeline.py first.")
        return

    symbol_meta = load_index_mappings()
    target_symbols = list(symbol_meta.keys())
    ensure_metadata(target_symbols)

    print(f"[*] Reading {len(found_files)} real Bhavcopy session files from {CSV_STORE}...")
    df_all = pd.concat([pd.read_csv(f) for f in found_files], ignore_index=True).drop_duplicates(subset=["symbol", "date"])
    df_all = df_all[df_all["symbol"].isin(target_symbols)]
    master_df = pd.read_csv(METADATA_FILE).drop_duplicates(subset=["symbol"])
    df_all = pd.merge(df_all, master_df, on="symbol", how="left").fillna(
        {"sector": "Capital Goods", "company_name": df_all["symbol"]}
    )
    df_all = df_all[df_all["sector"] != "General Equities"].sort_values(by=["symbol", "date"]).reset_index(drop=True)

    print("[*] Running Corporate Action Split/Bonus Continuity Normalizer on Bhavcopy series...")
    df_all, corp_action_events = normalize_corporate_actions(df_all)
    print(f"    -> Normalized {len(corp_action_events)} split/bonus ex-date discontinuities across the universe.")

    all_dates = sorted(df_all["date"].unique())
    monthly_checkpoints, latest_date_overall = determine_monthly_dates(all_dates)

    print("[*] Pre-computing rolling moving averages & 5-session pocket-pivot memory...")
    symbol_groups = {}
    for sym, grp in df_all.groupby("symbol"):
        g = grp.sort_values("date").copy()
        g["sma20_roll"] = g["close"].rolling(20, min_periods=5).mean()
        g["sma50_roll"] = g["close"].rolling(50, min_periods=10).mean()
        g["sma200_roll"] = g["close"].rolling(200, min_periods=20).mean()
        g["ema10_roll"] = g["close"].ewm(span=10, adjust=False).mean()
        g["vol20_roll"] = g["volume"].rolling(20, min_periods=5).mean()
        g["mrs_roll"] = (((g["close"] / (g["sma20_roll"] + 1e-5)) - 1.0) * 100.0).round(2)
        g["dist50_roll"] = (((g["close"] / (g["sma50_roll"] + 1e-5)) - 1.0) * 100.0).round(2)
        g["above_200_roll"] = g["close"] >= g["sma200_roll"]
        g["above_50_roll"] = g["close"] >= g["sma50_roll"]
        g["is_pocket_or_coil"] = (g["close"] > g["open"]) & (g["volume"] >= g["vol20_roll"] * 1.1)

        price_diff = g["close"].diff()
        down_vol_series = pd.Series(np.where(price_diff < 0, g["volume"], 0.0), index=g.index)
        max_down_10 = down_vol_series.rolling(10, min_periods=3).max().shift(1).fillna(0.0)
        g["is_pocket_pivot"] = (price_diff > 0) & (g["volume"] > max_down_10) & (g["close"] >= g["ema10_roll"])
        g["is_pocket_pivot_5d"] = (
            g["is_pocket_pivot"].rolling(5, min_periods=1).max().astype(bool)
            & (g["close"] >= g["ema10_roll"] * 0.995)
        )
        symbol_groups[sym] = g

    MODELS = [
        ("kinetic_launchpad", "💎 Institutional Kinetic Base (Refined Funnel)"),
        ("surety_anchor", "🛡️ High-Surety Institutional Anchor (Low-MAE)"),
        ("institutional_stealth", "⚡ Institutional Flow & Volume Absorption"),
        ("momentum_frontrunner", "🏎️ Momentum Frontrunners (Stage-2)"),
        ("quant_confluence", "🎯 Multi-Factor Quant Confluence"),
        ("high_rs_pullback", "🔄 High-RS Pullback Structure (Mean Reversion)"),
        ("sector_rs_leader", "🔥 Sector RS Leader & Pre-Breakout"),
        ("launchpad_vcp", "🚀 Launchpad VCP & Squeeze"),
        ("baseline", "📊 Baseline Composite (Legacy)"),
    ]

    months_payload = []
    all_csv_rows = []
    monthly_forensic_rows = []

    model_stats_accumulator = {
        m_key: {
            "trades": 0,
            "wins": 0,
            "total_return": 0.0,
            "total_trail_return": 0.0,
            "total_mfe": 0.0,
            "total_mfe_30d": 0.0,
            "total_mfe_60d": 0.0,
            "hits_15": 0,
            "hits_20": 0,
            "low_mae_count": 0,
            "total_mae": 0.0,
            "total_zone_persist": 0.0,
            "total_trend_persist": 0.0,
            "active_10d_count": 0,
            "trig_trades": 0,
            "trig_avoided": 0,
            "trig_total_mfe": 0.0,
            "trig_hits_15": 0,
            "trig_total_hold_ret": 0.0,
            "trig_total_trail_ret": 0.0,
            "trig_total_mae": 0.0,
        }
        for m_key, _ in MODELS
    }

    mcap_stats_accumulator = {}
    sector_lifecycle_accumulator = {}

    pattern_confluence_accumulator = {
        "Cohort 1: Baseline Setups (No Pattern Required)": [],
        "Cohort 2: Standalone Pattern (Geometric Detection Only)": [],
        "Cohort 3: Pattern + Full Institutional Confluence (POC Floor + Flow)": [],
        "Pattern Breakdown: 🎯 VCP Coiled Spring": [],
        "Pattern Breakdown: 🚩 Bull Flag & Pole": [],
        "Pattern Breakdown: 🟢 Multi-Month Base": [],
        "Pattern Breakdown: ⚡ Stage 2 Macro Base": [],
    }

    advanced_factors_accumulator = {
        "1. Base Universe Stage-2 Setups": [],
        "2. AVWAP Defense (Close >= 100D MaxVol VWAP)": [],
        "3. High Closing Range Accumulation (CR >= 0.55)": [],
        "4. Volatility Compression Black Hole (ATR5/ATR50 <= 0.50)": [],
        "5. Combined Institutional Alpha (AVWAP + CR + POC Support)": [],
    }

    print("\n" + "=" * 150)
    print("RUNNING 10-MONTH BACKTEST: 3 SETUPS IN PIPELINE + INSTITUTIONAL CONFLUENCE (AVWAP + CR + BLACK HOLE)")
    print(f"100% Real Bhavcopy Data | Unconstrained Horizon Evaluated Forward to EOD: {latest_date_overall}")
    print("=" * 150)

    for m_info in monthly_checkpoints:
        m_label = m_info["label"]
        m_start_date = m_info["date"]
        print(f"[*] Evaluating Month: {m_label} (Signal Date: {m_start_date})...")

        sector_summary, ranked_at_m = evaluate_point_in_time(df_all, m_start_date)

        u_start = df_all[df_all["date"] == m_start_date]["close"].mean()
        u_end = df_all[df_all["date"] == latest_date_overall]["close"].mean()
        universe_ret = round(float(((u_end - u_start) / (u_start + 1e-5)) * 100.0), 2)

        univ_above_50sma_pct = round(float(ranked_at_m["above_sma50"].mean() * 100.0), 1)
        univ_stage2_pct = round(float(ranked_at_m["stage2_aligned"].mean() * 100.0), 1)
        if univ_above_50sma_pct >= 55.0:
            mkt_regime = f"🟢 Bullish Expansion ({univ_above_50sma_pct:.0f}% >50SMA)"
        elif univ_above_50sma_pct >= 38.0:
            mkt_regime = f"🟡 Selective Rotation ({univ_above_50sma_pct:.0f}% >50SMA)"
        else:
            mkt_regime = f"🔴 Defensive / Contraction ({univ_above_50sma_pct:.0f}% >50SMA)"

        for _, stk in ranked_at_m[ranked_at_m["stage2_aligned"]].iterrows():
            sym_p = str(stk["symbol"])
            s_df = symbol_groups.get(sym_p)
            if s_df is None:
                continue
            fut_p = s_df[s_df["date"] >= m_start_date].reset_index(drop=True)
            if len(fut_p) < 10:
                continue

            e_p = float(stk["close"])
            pk_p = float(fut_p["high"].max())
            lw_p = float(fut_p["low"].min())
            end_p = float(fut_p["close"].iloc[-1])
            mfe_v = ((pk_p - e_p) / e_p) * 100.0
            mae_v = ((lw_p - e_p) / e_p) * 100.0
            ret_v = ((end_p - e_p) / e_p) * 100.0

            pat_name = str(stk.get("chart_pattern_signal", "")).strip()
            conf_score = float(stk.get("pattern_confluence_score", 50.0))
            poc_floor = bool(stk.get("poc_floor_support", False))
            is_leading_sec = str(stk.get("sector_rs_status", "")) != "🔴 Lagging Sector"

            avwap_supp = bool(stk.get("avwap_support", False))
            cr_val = float(stk.get("avg_closing_range", 0.50))
            vol_comp = float(stk.get("volatility_compression_ratio", 1.0))

            advanced_factors_accumulator["1. Base Universe Stage-2 Setups"].append((mfe_v, mae_v, ret_v))
            if avwap_supp:
                advanced_factors_accumulator["2. AVWAP Defense (Close >= 100D MaxVol VWAP)"].append((mfe_v, mae_v, ret_v))
            if cr_val >= 0.55:
                advanced_factors_accumulator["3. High Closing Range Accumulation (CR >= 0.55)"].append((mfe_v, mae_v, ret_v))
            if vol_comp <= 0.50:
                advanced_factors_accumulator["4. Volatility Compression Black Hole (ATR5/ATR50 <= 0.50)"].append((mfe_v, mae_v, ret_v))
            if avwap_supp and cr_val >= 0.55 and poc_floor:
                advanced_factors_accumulator["5. Combined Institutional Alpha (AVWAP + CR + POC Support)"].append((mfe_v, mae_v, ret_v))

            pattern_confluence_accumulator["Cohort 1: Baseline Setups (No Pattern Required)"].append((mfe_v, mae_v, ret_v))

            if pat_name:
                pattern_confluence_accumulator["Cohort 2: Standalone Pattern (Geometric Detection Only)"].append((mfe_v, mae_v, ret_v))
                if "VCP" in pat_name:
                    pattern_confluence_accumulator["Pattern Breakdown: 🎯 VCP Coiled Spring"].append((mfe_v, mae_v, ret_v))
                elif "Flag" in pat_name:
                    pattern_confluence_accumulator["Pattern Breakdown: 🚩 Bull Flag & Pole"].append((mfe_v, mae_v, ret_v))
                elif "Multi-Month" in pat_name:
                    pattern_confluence_accumulator["Pattern Breakdown: 🟢 Multi-Month Base"].append((mfe_v, mae_v, ret_v))
                elif "Macro" in pat_name:
                    pattern_confluence_accumulator["Pattern Breakdown: ⚡ Stage 2 Macro Base"].append((mfe_v, mae_v, ret_v))

            if pat_name and poc_floor and conf_score >= 65.0 and is_leading_sec:
                pattern_confluence_accumulator["Cohort 3: Pattern + Full Institutional Confluence (POC Floor + Flow)"].append((mfe_v, mae_v, ret_v))

        for _, r_row in ranked_at_m[ranked_at_m["above_200sma"] & (ranked_at_m["close"] >= ranked_at_m["sma_50"])].iterrows():
            sym_r = str(r_row["symbol"])
            s_df = symbol_groups.get(sym_r)
            if s_df is None:
                continue
            f_sl = s_df[s_df["date"] >= m_start_date]
            if len(f_sl) < 10:
                continue
            ep = float(r_row["close"])
            pk = float(f_sl["high"].max())
            lw = float(f_sl["low"].min())
            td_p = float(f_sl["close"].iloc[-1])
            mfe_r = ((pk - ep) / ep) * 100.0
            mae_r = ((lw - ep) / ep) * 100.0
            ret_r = ((td_p - ep) / ep) * 100.0

            s_life = str(r_row.get("sector_lifecycle", "Neutral"))
            life_bucket = (
                "1_Prime_Leadership (35-76% >50SMA, 20D <=8.5%)"
                if "Prime" in s_life
                else (
                    "2_Climactic_Exhaustion_Trap (>76% >50SMA or 20D >8.5%)"
                    if "Climactic" in s_life
                    else ("3_Early_Sector_Rotation" if "Early" in s_life else "4_Decelerating_or_Lagging")
                )
            )
            if life_bucket not in sector_lifecycle_accumulator:
                sector_lifecycle_accumulator[life_bucket] = []
            sector_lifecycle_accumulator[life_bucket].append((mfe_r, mae_r, ret_r))

        month_modes_output = {}
        top_qualifying_sectors = []

        for m_key, m_desc in MODELS:
            top_3_sectors, top_5_sectors, top_stocks, top_sec_names = select_top_stocks_for_model(
                m_key, ranked_at_m, sector_summary, target_count=20
            )
            if m_key == "kinetic_launchpad":
                top_qualifying_sectors = top_sec_names

            stock_records = []
            for rank_idx, (_, stk_row) in enumerate(top_stocks.iterrows(), start=1):
                sym = str(stk_row["symbol"])
                sym_df = symbol_groups.get(sym, pd.DataFrame())

                entry_price = round(float(stk_row["close"]), 2)
                atr_20_val = float(stk_row["atr_20"])
                atr_stop = round(float(stk_row["atr_stop_loss"]), 2)
                mrs_t0 = float(stk_row["mrs_score"])
                mcap_tier = str(stk_row.get("mcap_tier", "Tier 2/3: Mid & Small Cap"))
                sec_life = str(stk_row.get("sector_lifecycle", "🟢 Prime Institutional Leadership"))
                sec_mult = float(stk_row.get("sector_climax_mult", 1.0))
                surety_val = float(stk_row.get("surety_score", 50.0))
                poc_val = float(stk_row.get("volume_profile_poc", entry_price))
                poc_floor = bool(stk_row.get("poc_floor_support", entry_price >= poc_val))
                conf_score = float(stk_row.get("pattern_confluence_score", 50.0))
                cr_val = float(stk_row.get("avg_closing_range", 0.50))
                avwap_val = float(stk_row.get("avwap_100d_maxvol", entry_price))
                avwap_supp = bool(stk_row.get("avwap_support", entry_price >= avwap_val))
                vol_comp = float(stk_row.get("volatility_compression_ratio", 1.0))

                today_price, today_actual_date = lookup_real_close_on_or_after(sym_df, latest_date_overall)

                fut_slice = sym_df[sym_df["date"] >= m_start_date].reset_index(drop=True)
                if not fut_slice.empty:
                    max_pos = int(fut_slice["high"].values.argmax())
                    peak_row = fut_slice.iloc[max_pos]
                    peak_high = round(float(peak_row["high"]), 2)
                    peak_date = str(peak_row["date"])
                    days_to_peak = max_pos
                    peak_gain_pct = round(((peak_high - entry_price) / entry_price) * 100.0, 2)

                    slice_30d = fut_slice.iloc[: min(31, len(fut_slice))]
                    mfe_30d_pct = round(((float(slice_30d["high"].max()) - entry_price) / entry_price) * 100.0, 2)

                    slice_60d = fut_slice.iloc[: min(61, len(fut_slice))]
                    mfe_60d_pct = round(((float(slice_60d["high"].max()) - entry_price) / entry_price) * 100.0, 2)

                    min_pos = int(fut_slice["low"].values.argmin())
                    low_row = fut_slice.iloc[min_pos]
                    min_low = round(float(low_row["low"]), 2)
                    max_drawdown_mae_pct = round(((min_low - entry_price) / entry_price) * 100.0, 2)

                    trailing_exit_ret = simulate_structural_trailing_exit(
                        fut_slice,
                        entry_price,
                        atr_20_val,
                        fut_slice["sma50_roll"].values,
                        fut_slice["sma20_roll"].values,
                    )

                    ideal_sim = simulate_ideal_buy_trigger(
                        sym_df, m_start_date, mrs_t0, atr_20_val, today_price
                    )

                    persist_sim = simulate_signal_persistence(fut_slice, entry_price, atr_20_val)
                else:
                    peak_high, peak_date, days_to_peak, peak_gain_pct = entry_price, m_start_date, 0, 0.0
                    mfe_30d_pct, mfe_60d_pct = 0.0, 0.0
                    min_low, max_drawdown_mae_pct = entry_price, 0.0
                    trailing_exit_ret = 0.0
                    ideal_sim = {
                        "triggered": False,
                        "trigger_type": "Unconfirmed",
                        "trigger_date": m_start_date,
                        "wait_days": 0,
                        "ideal_entry_price": entry_price,
                        "ideal_mfe_pct": 0.0,
                        "ideal_mae_pct": 0.0,
                        "ideal_hold_ret_pct": 0.0,
                        "ideal_trail_ret_pct": 0.0,
                    }
                    persist_sim = {
                        "zone_persistence_days": 1,
                        "trend_persistence_days": 1,
                        "active_5d": True,
                        "active_10d": True,
                    }

                total_return_pct = (
                    round(((today_price - entry_price) / entry_price) * 100.0, 2)
                    if (today_price and entry_price)
                    else 0.0
                )

                base_pattern = str(stk_row.get("chart_pattern_signal", ""))
                trig_badge = (
                    f"{ideal_sim['trigger_type']} @ ₹{ideal_sim['ideal_entry_price']}"
                    if ideal_sim["triggered"]
                    else ideal_sim["trigger_type"]
                )
                combined_pattern_label = f"{base_pattern} | {trig_badge}" if base_pattern else trig_badge

                stock_record = {
                    "rank": rank_idx,
                    "symbol": sym,
                    "company_name": str(stk_row.get("company_name", sym)),
                    "sector": str(stk_row.get("sector", "Capital Goods")),
                    "index_name": str(stk_row.get("index_name", "Nifty 500")),
                    "mcap_tier": mcap_tier,
                    "inst_signal_at_entry": str(stk_row.get("inst_signal", "Consolidation")),
                    "chart_pattern_at_entry": combined_pattern_label,
                    "base_chart_pattern": base_pattern,
                    "pattern_confluence_score": conf_score,
                    "volume_profile_poc": poc_val,
                    "poc_floor_support": poc_floor,
                    "avg_closing_range": cr_val,
                    "avwap_100d_maxvol": avwap_val,
                    "avwap_support": avwap_supp,
                    "volatility_compression_ratio": vol_comp,
                    "sector_rs_status_at_entry": str(stk_row.get("sector_rs_status", "Normal")),
                    "sector_lifecycle_at_entry": sec_life,
                    "sector_climax_mult_at_entry": sec_mult,
                    "surety_score_at_entry": surety_val,
                    "ignition_score_at_entry": float(stk_row.get("ignition_score", 50.0)),
                    "frontrunner_score_at_entry": float(stk_row.get("frontrunner_score", 50.0)),
                    "iasis_score_at_entry": float(stk_row.get("iasis_score", 50.0)),
                    "mrs_20d_at_entry_pct": mrs_t0,
                    "dist_50d_at_entry_pct": float(stk_row.get("dist_from_50_pct", 0.0)),
                    "prior_63d_run_pct": float(stk_row.get("prior_63d_pct", 0.0)),
                    "zone_persistence_days": persist_sim["zone_persistence_days"],
                    "trend_persistence_days": persist_sim["trend_persistence_days"],
                    "entry_date": m_start_date,
                    "entry_price": entry_price,
                    "atr_stop_loss": atr_stop,
                    "peak_high_since_entry": peak_high,
                    "peak_date": peak_date,
                    "days_to_peak": days_to_peak,
                    "max_gain_mfe_pct": peak_gain_pct,
                    "mfe_30d_pct": mfe_30d_pct,
                    "mfe_60d_pct": mfe_60d_pct,
                    "min_low_since_entry": min_low,
                    "max_drawdown_mae_pct": max_drawdown_mae_pct,
                    "today_date": today_actual_date,
                    "today_price": today_price,
                    "total_return_to_today_pct": total_return_pct,
                    "trailing_exit_return_pct": trailing_exit_ret,
                    "ideal_triggered": ideal_sim["triggered"],
                    "ideal_trigger_type": ideal_sim["trigger_type"],
                    "ideal_trigger_date": ideal_sim["trigger_date"],
                    "ideal_entry_price": ideal_sim["ideal_entry_price"],
                    "ideal_mfe_pct": ideal_sim["ideal_mfe_pct"],
                    "ideal_mae_pct": ideal_sim["ideal_mae_pct"],
                    "ideal_hold_ret_pct": ideal_sim["ideal_hold_ret_pct"],
                    "ideal_trail_ret_pct": ideal_sim["ideal_trail_ret_pct"],
                }
                stock_records.append(stock_record)

                if m_key in ["kinetic_launchpad", "surety_anchor"]:
                    if mcap_tier not in mcap_stats_accumulator:
                        mcap_stats_accumulator[mcap_tier] = []
                    mcap_stats_accumulator[mcap_tier].append({
                        "mfe": peak_gain_pct,
                        "mae": max_drawdown_mae_pct,
                        "ret": total_return_pct,
                        "trail": ideal_sim["ideal_trail_ret_pct"] if ideal_sim["triggered"] else trailing_exit_ret,
                        "zone_p": persist_sim["zone_persistence_days"],
                        "trend_p": persist_sim["trend_persistence_days"],
                    })

                all_csv_rows.append({
                    "model_name": m_key,
                    "signal_month": m_label,
                    "signal_date": m_start_date,
                    "rank": rank_idx,
                    "symbol": sym,
                    "company_name": stock_record["company_name"],
                    "sector": stock_record["sector"],
                    "mcap_tier": mcap_tier,
                    "sector_lifecycle": sec_life,
                    "signal_at_entry": stock_record["inst_signal_at_entry"],
                    "pattern_and_trigger": combined_pattern_label,
                    "base_pattern": base_pattern,
                    "pattern_confluence_score": conf_score,
                    "volume_profile_poc": poc_val,
                    "poc_floor_support": poc_floor,
                    "avg_closing_range": cr_val,
                    "avwap_100d_maxvol": avwap_val,
                    "avwap_support": avwap_supp,
                    "volatility_compression_ratio": vol_comp,
                    "sector_rs_at_entry": stock_record["sector_rs_status_at_entry"],
                    "surety_score": surety_val,
                    "frontrunner_score": stock_record["frontrunner_score_at_entry"],
                    "iasis_score": stock_record["iasis_score_at_entry"],
                    "ignition_score": stock_record["ignition_score_at_entry"],
                    "prior_63d_run_pct": stock_record["prior_63d_run_pct"],
                    "zone_persistence_days": persist_sim["zone_persistence_days"],
                    "trend_persistence_days": persist_sim["trend_persistence_days"],
                    "day1_entry_price": entry_price,
                    "peak_price": peak_high,
                    "peak_date": peak_date,
                    "days_to_peak": days_to_peak,
                    "day1_mfe_pct": peak_gain_pct,
                    "mfe_30d_pct": mfe_30d_pct,
                    "mfe_60d_pct": mfe_60d_pct,
                    "day1_mae_pct": max_drawdown_mae_pct,
                    "today_price": today_price,
                    "day1_hold_return_pct": total_return_pct,
                    "day1_trailing_exit_pct": trailing_exit_ret,
                    "ideal_triggered": ideal_sim["triggered"],
                    "ideal_trigger_date": ideal_sim["trigger_date"],
                    "ideal_entry_price": ideal_sim["ideal_entry_price"],
                    "ideal_mfe_pct": ideal_sim["ideal_mfe_pct"],
                    "ideal_mae_pct": ideal_sim["ideal_mae_pct"],
                    "ideal_hold_return_pct": ideal_sim["ideal_hold_ret_pct"],
                    "ideal_trailing_exit_pct": ideal_sim["ideal_trail_ret_pct"],
                })

            rets = [s["total_return_to_today_pct"] for s in stock_records]
            trail_rets = [s["trailing_exit_return_pct"] for s in stock_records]
            mfes = [s["max_gain_mfe_pct"] for s in stock_records]
            mfes_30 = [s["mfe_30d_pct"] for s in stock_records]
            mfes_60 = [s["mfe_60d_pct"] for s in stock_records]
            maes = [s["max_drawdown_mae_pct"] for s in stock_records]
            z_pers = [s["zone_persistence_days"] for s in stock_records]
            t_pers = [s["trend_persistence_days"] for s in stock_records]

            avg_ret = round(float(np.mean(rets)), 2) if rets else 0.0
            avg_trail_ret = round(float(np.mean(trail_rets)), 2) if trail_rets else 0.0
            win_rate = round(float((np.array(rets) > 0).mean() * 100.0), 1) if rets else 0.0
            avg_mfe = round(float(np.mean(mfes)), 2) if mfes else 0.0
            avg_mfe_30 = round(float(np.mean(mfes_30)), 2) if mfes_30 else 0.0
            avg_mfe_60 = round(float(np.mean(mfes_60)), 2) if mfes_60 else 0.0
            hit_15 = round(float((np.array(mfes) >= 15.0).mean() * 100.0), 1) if mfes else 0.0
            hit_20 = round(float((np.array(mfes) >= 20.0).mean() * 100.0), 1) if mfes else 0.0
            avg_mae = round(float(np.mean(maes)), 2) if maes else 0.0
            avg_zone_p = round(float(np.mean(z_pers)), 1) if z_pers else 1.0
            avg_trend_p = round(float(np.mean(t_pers)), 1) if t_pers else 1.0

            acc = model_stats_accumulator[m_key]
            acc["trades"] += len(rets)
            acc["wins"] += int((np.array(rets) > 0).sum())
            acc["total_return"] += float(np.sum(rets))
            acc["total_trail_return"] += float(np.sum(trail_rets))
            acc["total_mfe"] += float(np.sum(mfes))
            acc["total_mfe_30d"] += float(np.sum(mfes_30))
            acc["total_mfe_60d"] += float(np.sum(mfes_60))
            acc["hits_15"] += int((np.array(mfes) >= 15.0).sum())
            acc["hits_20"] += int((np.array(mfes) >= 20.0).sum())
            acc["low_mae_count"] += int((np.array(maes) >= -6.0).sum())
            acc["total_mae"] += float(np.sum(maes))
            acc["total_zone_persist"] += float(np.sum(z_pers))
            acc["total_trend_persist"] += float(np.sum(t_pers))
            acc["active_10d_count"] += int(sum(1 for s in stock_records if s["trend_persistence_days"] >= 10))

            trig_picks = [s for s in stock_records if s["ideal_triggered"]]
            acc["trig_trades"] += len(trig_picks)
            acc["trig_avoided"] += len(stock_records) - len(trig_picks)
            for tp in trig_picks:
                acc["trig_total_mfe"] += tp["ideal_mfe_pct"]
                if tp["ideal_mfe_pct"] >= 15.0:
                    acc["trig_hits_15"] += 1
                acc["trig_total_hold_ret"] += tp["ideal_hold_ret_pct"]
                acc["trig_total_trail_ret"] += tp["ideal_trail_ret_pct"]
                acc["trig_total_mae"] += tp["ideal_mae_pct"]

            month_modes_output[m_key] = {
                "model_key": m_key,
                "model_name": m_desc,
                "evaluation_date": latest_date_overall,
                "picks_count": len(stock_records),
                "portfolio_avg_return_pct": avg_ret,
                "trailing_exit_avg_return_pct": avg_trail_ret,
                "portfolio_win_rate_pct": win_rate,
                "avg_peak_mfe_pct": avg_mfe,
                "avg_mfe_30d_pct": avg_mfe_30,
                "avg_mfe_60d_pct": avg_mfe_60,
                "hit_15pct_target_rate_pct": hit_15,
                "hit_20pct_target_rate_pct": hit_20,
                "avg_drawdown_mae_pct": avg_mae,
                "avg_zone_persistence_days": avg_zone_p,
                "avg_trend_persistence_days": avg_trend_p,
                "universe_benchmark_return_pct": universe_ret,
                "alpha_vs_universe_pct": round(avg_ret - universe_ret, 2),
                "top_3_sectors": top_3_sectors,
                "top_5_sectors": top_5_sectors,
                "picks": stock_records,
                "picks_9": stock_records[:20],
            }

        # Architectural Slices for Comparison
        strict_aplus_pool = ranked_at_m[
            (ranked_at_m["stage2_aligned"])
            & (ranked_at_m["frontrunner_score"] >= 75.0)
            & (ranked_at_m["iasis_score"] >= 60.0)
            & (ranked_at_m["surety_score"] >= 58.0)
            & (ranked_at_m["prior_63d_run_pct"] >= 7.5)
            & (ranked_at_m["prior_63d_run_pct"] <= 34.0)
            & (ranked_at_m["mrs_score"] >= -2.0)
            & (ranked_at_m["mrs_score"] <= 3.5)
            & (ranked_at_m["dist_from_50_pct"] <= 6.5)
            & (ranked_at_m["base_depth_pct"] <= 22.0)
            & (ranked_at_m["flow_ratio"] >= 1.20)
            & (ranked_at_m["atr_pct"] <= 5.2)
            & (ranked_at_m["sector_rs_status"] != "🔴 Lagging Sector")
            & (
                ranked_at_m["sector"].isin(top_qualifying_sectors)
                | (ranked_at_m["surety_score"] >= 64.0)
            )
        ].sort_values(by=["score_surety_anchor", "score_kinetic_launchpad"], ascending=False).head(10)

        top_down_10_pool = ranked_at_m[
            (ranked_at_m["sector"].isin(top_qualifying_sectors))
            & (ranked_at_m["stage2_aligned"])
            & (ranked_at_m["frontrunner_score"] >= 73.0)
            & (ranked_at_m["iasis_score"] >= 56.0)
            & (ranked_at_m["prior_63d_run_pct"] >= 6.0)
            & (ranked_at_m["mrs_score"] <= 4.5)
            & (ranked_at_m["dist_from_50_pct"] <= 9.0)
        ].sort_values(by=["score_kinetic_launchpad", "surety_score"], ascending=False).head(10)

        absolute_10_pool = ranked_at_m[
            (ranked_at_m["stage2_aligned"])
            & (ranked_at_m["frontrunner_score"] >= 75.0)
            & (ranked_at_m["iasis_score"] >= 60.0)
            & (ranked_at_m["prior_63d_run_pct"] >= 7.0)
            & (ranked_at_m["mrs_score"] <= 4.0)
            & (ranked_at_m["dist_from_50_pct"] <= 8.0)
            & (ranked_at_m["sector_rs_status"] != "🔴 Lagging Sector")
        ].sort_values(by=["score_absolute_pure", "surety_score"], ascending=False).head(10)

        strict_aplus_eval = evaluate_candidate_slice(strict_aplus_pool, symbol_groups, m_start_date, latest_date_overall)
        top_down_10_eval = evaluate_candidate_slice(top_down_10_pool, symbol_groups, m_start_date, latest_date_overall)
        absolute_10_eval = evaluate_candidate_slice(absolute_10_pool, symbol_groups, m_start_date, latest_date_overall)

        _, _, sa_top20_df, _ = select_top_stocks_for_model("surety_anchor", ranked_at_m, sector_summary, target_count=20)
        sa_top5_eval = evaluate_candidate_slice(sa_top20_df.head(5), symbol_groups, m_start_date, latest_date_overall)
        sa_top10_eval = evaluate_candidate_slice(sa_top20_df.head(10), symbol_groups, m_start_date, latest_date_overall)
        sa_top20_eval = evaluate_candidate_slice(sa_top20_df, symbol_groups, m_start_date, latest_date_overall)

        _, _, mf_top20_df, _ = select_top_stocks_for_model("momentum_frontrunner", ranked_at_m, sector_summary, target_count=20)
        mf_top10_eval = evaluate_candidate_slice(mf_top20_df.head(10), symbol_groups, m_start_date, latest_date_overall)
        mf_top20_eval = evaluate_candidate_slice(mf_top20_df, symbol_groups, m_start_date, latest_date_overall)

        _, _, hrp_top20_df, _ = select_top_stocks_for_model("high_rs_pullback", ranked_at_m, sector_summary, target_count=20)
        hrp_top10_eval = evaluate_candidate_slice(hrp_top20_df.head(10), symbol_groups, m_start_date, latest_date_overall)

        monthly_forensic_rows.append({
            "month": m_label,
            "signal_date": m_start_date,
            "market_regime": mkt_regime,
            "univ_above_50sma_pct": univ_above_50sma_pct,
            "univ_stage2_pct": univ_stage2_pct,
            "universe_benchmark_ret_pct": universe_ret,
            "qualifying_top_6_sectors": top_qualifying_sectors,
            "strict_aplus_dynamic": strict_aplus_eval,
            "top_down_sector_top10": top_down_10_eval,
            "absolute_score_all_sectors_top10": absolute_10_eval,
            "surety_anchor_top5": sa_top5_eval,
            "surety_anchor_top10": sa_top10_eval,
            "surety_anchor_top20": sa_top20_eval,
            "momentum_frontrunner_top10": mf_top10_eval,
            "momentum_frontrunner_top20": mf_top20_eval,
            "high_rs_pullback_top10": hrp_top10_eval,
        })

        primary_view = dict(month_modes_output["kinetic_launchpad"])
        primary_view["quarter_label"] = m_label
        primary_view["start_date"] = m_start_date
        primary_view["modes"] = month_modes_output

        months_payload.append(primary_view)

    print("[*] Running Intra-Month Setup Timing Audit across 2026 sessions...")
    intramonth_audit = run_intramonth_timing_audit(symbol_groups, all_dates, latest_date_overall)

    mcap_summary_list = []
    for tier_label in sorted(mcap_stats_accumulator.keys()):
        t_items = mcap_stats_accumulator[tier_label]
        mfes_t = np.array([x["mfe"] for x in t_items])
        maes_t = np.array([x["mae"] for x in t_items])
        rets_t = np.array([x["ret"] for x in t_items])
        trails_t = np.array([x["trail"] for x in t_items])
        zp_t = np.array([x["zone_p"] for x in t_items])
        tp_t = np.array([x["trend_p"] for x in t_items])
        mcap_summary_list.append({
            "mcap_tier": tier_label,
            "count": len(t_items),
            "avg_mfe_pct": round(float(np.mean(mfes_t)), 2),
            "hit_15pct_rate": round(float((mfes_t >= 15.0).mean() * 100.0), 1),
            "low_mae_surety_rate": round(float((maes_t >= -6.0).mean() * 100.0), 1),
            "avg_mae_pct": round(float(np.mean(maes_t)), 2),
            "avg_hold_ret_pct": round(float(np.mean(rets_t)), 2),
            "avg_trail_ret_pct": round(float(np.mean(trails_t)), 2),
            "avg_zone_days": round(float(np.mean(zp_t)), 1),
            "avg_trend_days": round(float(np.mean(tp_t)), 1),
        })

    sector_climax_audit_list = []
    for life_key in sorted(sector_lifecycle_accumulator.keys()):
        l_items = sector_lifecycle_accumulator[life_key]
        mfes_l = np.array([x[0] for x in l_items])
        maes_l = np.array([x[1] for x in l_items])
        rets_l = np.array([x[2] for x in l_items])
        sector_climax_audit_list.append({
            "sector_stage": life_key,
            "sample_size": len(l_items),
            "avg_mfe_pct": round(float(np.mean(mfes_l)), 2),
            "hit_15pct_rate": round(float((mfes_l >= 15.0).mean() * 100.0), 1),
            "severe_trap_rate_mae_gt_15": round(float((maes_l <= -15.0).mean() * 100.0), 1),
            "avg_mae_pct": round(float(np.mean(maes_l)), 2),
            "avg_period_ret_pct": round(float(np.mean(rets_l)), 2),
        })

    pattern_audit_summary = []
    for cohort_label, records in pattern_confluence_accumulator.items():
        if not records:
            continue
        p_mfes = np.array([x[0] for x in records])
        p_maes = np.array([x[1] for x in records])
        p_rets = np.array([x[2] for x in records])
        pattern_audit_summary.append({
            "cohort": cohort_label,
            "sample_size": len(records),
            "avg_peak_mfe_pct": round(float(np.mean(p_mfes)), 2),
            "hit_15pct_rate": round(float((p_mfes >= 15.0).mean() * 100.0), 1),
            "low_mae_surety_rate": round(float((p_maes >= -6.0).mean() * 100.0), 1),
            "avg_mae_pct": round(float(np.mean(p_maes)), 2),
            "avg_hold_ret_pct": round(float(np.mean(p_rets)), 2),
            "asymmetry_ratio": round(float(np.mean(p_mfes) / max(1.0, abs(np.mean(p_maes)))), 2),
        })

    advanced_factors_summary = []
    for factor_label, records in advanced_factors_accumulator.items():
        if not records:
            continue
        f_mfes = np.array([x[0] for x in records])
        f_maes = np.array([x[1] for x in records])
        f_rets = np.array([x[2] for x in records])
        advanced_factors_summary.append({
            "factor": factor_label,
            "sample_size": len(records),
            "avg_peak_mfe_pct": round(float(np.mean(f_mfes)), 2),
            "hit_15pct_rate": round(float((f_mfes >= 15.0).mean() * 100.0), 1),
            "low_mae_surety_rate": round(float((f_maes >= -6.0).mean() * 100.0), 1),
            "avg_mae_pct": round(float(np.mean(f_maes)), 2),
            "avg_hold_ret_pct": round(float(np.mean(f_rets)), 2),
            "asymmetry_ratio": round(float(np.mean(f_mfes) / max(1.0, abs(np.mean(f_maes)))), 2),
        })

    pd.DataFrame(all_csv_rows).to_csv(BACKTEST_CSV, index=False)

    final_json = {
        "generated_at_eod": latest_date_overall,
        "corporate_actions_normalized_count": len(corp_action_events),
        "quarter_checkpoints": monthly_checkpoints,
        "mcap_tier_summary": mcap_summary_list,
        "sector_climax_audit": sector_climax_audit_list,
        "intramonth_timing_audit": intramonth_audit,
        "pattern_confluence_audit": pattern_audit_summary,
        "advanced_factors_audit": advanced_factors_summary,
        "monthly_forensics": monthly_forensic_rows,
        "quarters": months_payload,
    }
    with open(BACKTEST_JSON, "w") as f:
        json.dump(final_json, f, indent=2)

    compact_summary = {
        "generated_at_eod": latest_date_overall,
        "corporate_actions_normalized": corp_action_events,
        "mcap_tier_summary": mcap_summary_list,
        "sector_climax_audit": sector_climax_audit_list,
        "intramonth_timing_audit": intramonth_audit,
        "pattern_confluence_audit": pattern_audit_summary,
        "advanced_factors_audit": advanced_factors_summary,
        "monthly_forensics": monthly_forensic_rows,
    }
    with open(BACKTEST_SUMMARY_JSON, "w") as f:
        json.dump(compact_summary, f, indent=2)

    # =========================================================================
    # PRINT CONSOLE DIAGNOSTIC TABLES
    # =========================================================================
    print("\n" + "=" * 150)
    print("TABLE 1: 10-MONTH STRATEGY LEADERBOARD (20-STOCK PORTFOLIOS ACROSS ALL 10 MONTHS)")
    print("=" * 150)
    print(
        f"{'Strategy Model':<48} | {'Peak MFE':<8} | {'PeriodRet':<9} | {'LowMAE%':<7} | {'Zone/Trnd Days':<14} || "
        f"{'Conf/Filt':<9} | {'Conf MFE':<8} | {'Conf Trail':<10} | {'Conf MAE'}"
    )
    print("-" * 150)

    summary_rows = []
    for m_key, m_desc in MODELS:
        st = model_stats_accumulator[m_key]
        n_tr = max(1, st["trades"])
        n_trig = max(1, st["trig_trades"])
        summary_rows.append({
            "name": m_desc,
            "d1_mfe": st["total_mfe"] / n_tr,
            "d1_ret": st["total_return"] / n_tr,
            "low_mae_pct": (st["low_mae_count"] / n_tr) * 100.0,
            "persist_str": f"{st['total_zone_persist']/n_tr:>4.1f}d / {st['total_trend_persist']/n_tr:>4.1f}d",
            "trig_str": f"{st['trig_trades']}/{st['trig_avoided']}",
            "id_mfe": st["trig_total_mfe"] / n_trig,
            "id_trail": st["trig_total_trail_ret"] / n_trig,
            "id_mae": st["trig_total_mae"] / n_trig,
        })

    summary_rows.sort(key=lambda x: (x["id_trail"] + x["d1_ret"] * 0.5), reverse=True)
    for r in summary_rows:
        print(
            f"{r['name']:<48} | +{r['d1_mfe']:>5.2f}%  | {r['d1_ret']:>+7.2f}%  | {r['low_mae_pct']:>5.1f}%  | {r['persist_str']:<14} || "
            f"{r['trig_str']:<9} | +{r['id_mfe']:>5.2f}%  | {r['id_trail']:>+8.2f}%  | {r['id_mae']:>6.2f}%"
        )

    print("\n" + "=" * 150)
    print("TABLE 5: CHART PATTERN & CONFLUENCE CONFIRMATION AUDIT")
    print("=" * 150)
    print(f"{'Cohort / Setup Strategy':<72} | {'N':<6} | {'Peak MFE':<8} | {'>=15%':<6} | {'LowMAE%':<7} | {'Avg MAE':<8} | {'PeriodRet':<9} | {'Asymmetry'}")
    print("-" * 150)
    for pa in pattern_audit_summary:
        print(
            f"{pa['cohort']:<72} | {pa['sample_size']:<6} | +{pa['avg_peak_mfe_pct']:>5.2f}%  | {pa['hit_15pct_rate']:>4.1f}% | "
            f"{pa['low_mae_surety_rate']:>5.1f}%  | {pa['avg_mae_pct']:>6.2f}%  | {pa['avg_hold_ret_pct']:>+7.2f}%  | {pa['asymmetry_ratio']:>4.2f}x"
        )

    print("\n" + "=" * 150)
    print("TABLE 6: ADVANCED INSTITUTIONAL FACTORS ABLATION AUDIT (AVWAP • CLOSING RANGE • VOLATILITY BLACK HOLE)")
    print("=" * 150)
    print(f"{'Factor Tested':<72} | {'N':<6} | {'Peak MFE':<8} | {'>=15%':<6} | {'LowMAE%':<7} | {'Avg MAE':<8} | {'PeriodRet':<9} | {'Asymmetry'}")
    print("-" * 150)
    for fa in advanced_factors_summary:
        print(
            f"{fa['factor']:<72} | {fa['sample_size']:<6} | +{fa['avg_peak_mfe_pct']:>5.2f}%  | {fa['hit_15pct_rate']:>4.1f}% | "
            f"{fa['low_mae_surety_rate']:>5.1f}%  | {fa['avg_mae_pct']:>6.2f}%  | {fa['avg_hold_ret_pct']:>+7.2f}%  | {fa['asymmetry_ratio']:>4.2f}x"
        )

    print("\n" + "=" * 150)
    print(f"[✓] Saved full UI data to: {BACKTEST_JSON}")
    print(f"[✓] Saved compact 10-month summary to: {BACKTEST_SUMMARY_JSON}")
    print(f"[✓] Saved CSV trade log to: {BACKTEST_CSV}")
    print("=" * 150)


if __name__ == "__main__":
    run_quarterly_backtest()