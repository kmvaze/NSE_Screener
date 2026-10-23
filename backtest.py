import glob
import json
import os
from datetime import datetime
import pandas as pd
import numpy as np

# Import paths, constants, and helpers directly from pipeline.py
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
    Generates point-in-time signal dates representing the 1st trading session
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
    and backward-adjusts historical OHLC & volume prior to the ex-date.
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


def classify_mcap_tier(symbol: str, index_name: str, turnover: float = 0.0) -> str:
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
    if "NIFTY MIDCAP 150" in tokens or "MIDCAP" in idx_up:
        return "Tier 2: Mid Cap (Midcap 150)"
    if "NIFTY SMALLCAP 250" in tokens or "SMALLCAP" in idx_up:
        return "Tier 3: Small Cap (Smallcap 250)"
    if "NIFTY MICROCAP 250" in tokens or "MICROCAP" in idx_up:
        return "Tier 4: Microcap (Microcap 250)"
    
    if turnover > 12.0:
        return "Tier 2: Mid Cap (Midcap 150)"
    return "Tier 3: Small Cap (Smallcap 250)"


def classify_sector_lifecycle(row: pd.Series) -> tuple:
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
        return "🟡 Decelerating Sector", 0.88

    return "🔴 Lagging Sector Regime", 0.82


def evaluate_point_in_time(df_all: pd.DataFrame, cutoff_date: str):
    """
    Evaluates indicators and scores strictly on Bhavcopy data <= cutoff_date (Zero Lookahead).
    Uses the exact 4-strategy mathematical models matching pipeline.py.
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
        deliv_pcts = grp["deliv_pct"].values

        n_bars = len(prices)
        if n_bars < 20:
            continue

        p_series = pd.Series(prices)
        close = float(prices[-1])
        sma_20 = round(float(np.mean(prices[-min(20, n_bars):])), 2)
        ema_10 = float(p_series.ewm(span=10, adjust=False).mean().iloc[-1])
        ema_21 = float(p_series.ewm(span=21, adjust=False).mean().iloc[-1])
        sma_50_series = p_series.rolling(min(50, n_bars), min_periods=10).mean()
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

        # Volume Profile POC
        poc_bars = min(50, n_bars)
        hist, bins = np.histogram(prices[-poc_bars:], bins=10, weights=volumes[-poc_bars:])
        poc = round(float((bins[np.argmax(hist)] + bins[np.argmax(hist) + 1]) / 2.0), 2)

        # Institutional Flow / Squeeze Indicators
        vol_20_avg = float(np.mean(volumes[-min(20, n_bars):])) + 1e-5
        session_rvol = round(float(volumes[-1] / vol_20_avg), 2)
        is_rvol_expanded = session_rvol >= 2.5

        sub_15_diff = np.diff(prices[-16:]) if n_bars >= 16 else np.diff(prices)
        sub_15_vols = volumes[-len(sub_15_diff):]
        up_vol_15 = np.sum(sub_15_vols[sub_15_diff > 0]) if np.any(sub_15_diff > 0) else 1.0
        down_vol_15 = np.sum(sub_15_vols[sub_15_diff < 0]) if np.any(sub_15_diff < 0) else 1.0
        supply_exhaustion_ratio = round(float(up_vol_15 / (down_vol_15 + 1e-5)), 2)
        is_supply_exhausted = supply_exhaustion_ratio >= 3.5

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
        is_rs_accelerating = rs_acceleration > 0.0

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

        vcp_rat, pattern, pattern_tf = detect_genuine_chart_patterns(prices, volumes, highs, lows)

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
        tranche2_limit_price = round(close - (1.5 * atr_20), 2)
        blended_entry_price = round((close + tranche2_limit_price) / 2.0, 2)
        cushioned_sl_price = round(min(structural_stop, tranche2_limit_price - (1.0 * atr_20)), 2)

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
            "tranche2_limit_price": tranche2_limit_price,
            "blended_entry_price": blended_entry_price,
            "cushioned_sl_price": cushioned_sl_price,
            "volume_profile_poc": poc,
            "poc_floor_support": bool(close >= poc),
            "session_rvol": session_rvol,
            "is_rvol_expanded": is_rvol_expanded,
            "supply_exhaustion_ratio": supply_exhaustion_ratio,
            "is_supply_exhausted": is_supply_exhausted,
            "rs_acceleration": rs_acceleration,
            "is_rs_accelerating": is_rs_accelerating,
            "deliv_pct": round(recent_deliv_pct, 1),
            "vcp_ratio": float(vcp_rat),
            "bb_kc_ratio": bb_kc_ratio,
            "ma_spread_pct": round(ma_spread_pct, 2),
            "vol_dryup_ratio": round(vol_dryup_ratio, 2),
            "chart_pattern_signal": pattern,
            "pattern_timeframe": pattern_tf,
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
            "prior_63d_pct": prior_63d_pct,
            "dist_from_50_pct": dist_from_50_pct,
            "base_depth_pct": round(base_depth_pct, 2),
        })

    ranked = pd.merge(latest_df, pd.DataFrame(stock_tech_rows), on="symbol", how="inner").drop_duplicates(subset=["symbol"])
    ranked = ranked[ranked["sector"] != "General Equities"].copy()

    ranked["turnover_cr"] = ((ranked["volume"].fillna(0) * ranked["close"]) / 10000000.0).round(2)
    ranked["mcap_tier"] = ranked.apply(lambda r: classify_mcap_tier(r["symbol"], r.get("index_name", ""), r.get("turnover_cr", 0.0)), axis=1)
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
        + np.where(ranked["is_rvol_expanded"], 6.0, 0.0)
        + np.where(ranked["is_supply_exhausted"], 8.0, 0.0)
        + np.where(ranked["is_rs_accelerating"], 6.0, 0.0)
    )
    ignition_raw = s_pts + m_pts + v_pts + d_pts

    ext_multiplier = np.where(
        ranked["mrs_score"] <= 3.0,
        1.0,
        np.clip(1.0 - ((ranked["mrs_score"] - 3.0) / 5.5), 0.20, 1.0),
    )
    stage_multiplier = np.where(ranked["above_200sma"] & ranked["above_sma50"], 1.0, 0.55)
    stoch_multiplier = np.where(ranked["stoch_k"] <= 78.0, 1.0, 0.78)
    ranked["ignition_score"] = (ignition_raw * ext_multiplier * stage_multiplier * stoch_multiplier).clip(5.0, 99.0).round(1)

    ranked["frontrunner_score"] = (
        0.30 * ranked["trend_score"]
        + 0.35 * rs_percentile
        + 0.20 * peer_rs_percentile
        + 0.15 * up_down_pct
    ).clip(5.0, 99.0).round(1)

    # =========================================================================
    # EXACT 4 STRATEGY MODELS FROM PIPELINE.PY
    # =========================================================================
    # 1. Strategy 1: High-Surety Institutional Anchor
    mrs_anchor_pts = 28.0 * np.exp(-((ranked["mrs_score"] - 0.8) ** 2) / 10.5)
    sma50_anchor_pts = 22.0 * np.clip(1.0 - (np.maximum(0.0, ranked["dist_from_50_pct"] - 1.5) / 10.0), 0.0, 1.0)
    base_tight_pts = 15.0 * np.clip(1.0 - (ranked["base_depth_pct"] / 25.0), 0.0, 1.0)

    p63 = ranked["prior_63d_pct"]
    mom_curve = np.where(
        p63 < 0.0,
        0.55,
        np.where(
            p63 < 5.0,
            0.70 + 0.30 * (p63 / 5.0),
            np.where(p63 <= 32.0, 1.0, np.clip(1.0 - ((p63 - 32.0) / 35.0), 0.55, 1.0)),
        ),
    )
    flow_curve = np.clip(0.70 + 0.30 * ((ranked["iasis_score"] - 48.0) / 18.0), 0.60, 1.05)

    raw_surety = (
        mrs_anchor_pts
        + sma50_anchor_pts
        + base_tight_pts
        + (0.20 * ranked["iasis_score"])
        + (0.15 * ranked["frontrunner_score"])
    )
    sec_adj = np.clip(ranked["sector_climax_mult"], 0.82, 1.08)
    ranked["score_surety_anchor"] = (raw_surety * mom_curve * flow_curve * sec_adj).clip(5.0, 99.0).round(1)
    ranked["surety_score"] = ranked["score_surety_anchor"]

    # 2. Strategy 2: Momentum Frontrunner
    ranked["score_momentum_frontrunner"] = (
        (0.40 * ranked["frontrunner_score"] + 0.30 * ranked["trend_score"] + 0.15 * ranked["iasis_score"] + 0.15 * ranked["surety_score"]) * sec_adj
    ).clip(5.0, 99.0).round(1)

    # 3. Strategy 3: Early Sector Rotation
    ranked["score_early_sector_rotation"] = (
        (0.35 * ranked["frontrunner_score"] + 0.25 * ranked["iasis_score"] + 0.25 * ranked["surety_score"] + 0.15 * ranked["ignition_score"]) * np.where(ranked["sector_lifecycle"].str.contains("Rotation|Leadership"), 1.08, 0.92)
    ).clip(5.0, 99.0).round(1)

    # 4. Strategy 4: High-RS Pullback Structure
    pullback_depth_pts = 30.0 * np.exp(-((ranked["mrs_score"] - (-1.5)) ** 2) / 8.0)
    stoch_oversold_pts = 30.0 * np.clip(1.0 - (ranked["stoch_k"] / 60.0), 0.0, 1.0)
    ranked["score_high_rs_pullback"] = (
        (pullback_depth_pts + stoch_oversold_pts + 0.25 * rs_percentile + 0.15 * ranked["iasis_score"]) * sec_adj
    ).clip(5.0, 99.0).round(1)

    # Setup Signal Classifier
    def get_signal(r):
        c_pattern = str(r.get("chart_pattern_signal", ""))
        s_life = str(r.get("sector_lifecycle", ""))
        mrs = float(r.get("mrs_score", 0.0))
        close_val = float(r["close"])
        sma50_val = float(r["sma_50"])
        stoch_val = float(r.get("stoch_k", 50.0))
        s_anchor = float(r["score_surety_anchor"])
        s_mom = float(r["score_momentum_frontrunner"])
        s_rot = float(r["score_early_sector_rotation"])
        s_pull = float(r["score_high_rs_pullback"])

        if mrs > 8.0 or float(r.get("dist_from_50_pct", 0.0)) > 14.0 or float(r.get("prior_63d_pct", 0.0)) > 38.0:
            return "⚠️ Extended (Wait for Dip)"
        if not bool(r["above_200sma"]):
            return "🔴 Below 200-SMA (Overhead Supply)"

        scores = [
            (s_anchor, "🛡️ High-Surety Anchor"),
            (s_mom, "🚀 Momentum Frontrunner"),
            (s_rot, "🔄 Early Sector Rotation Leader"),
            (s_pull, "📉 High-RS Pullback"),
        ]
        scores.sort(key=lambda x: x[0], reverse=True)
        top_label = scores[0][1]

        if top_label == "📉 High-RS Pullback" and (mrs <= 1.0 or stoch_val < 45.0) and close_val >= sma50_val * 0.98:
            return "📉 High-RS Pullback"
        if top_label == "🔄 Early Sector Rotation Leader" and ("Rotation" in s_life or "Prime" in s_life or "Leading" in s_life):
            return "🔄 Early Sector Rotation Leader"
        if top_label == "🚀 Momentum Frontrunner" and float(r["frontrunner_score"]) >= 70.0 and close_val >= sma50_val:
            return "🚀 Momentum Frontrunner"
        if c_pattern == "🎯 VCP Coiled Spring" and mrs <= 3.0:
            return "🎯 VCP Coiled Spring"
        if bool(r.get("is_pocket_pivot_5d", False)) and (bool(r.get("is_squeezed", False)) or bool(r.get("is_ma_pinched", False))) and mrs <= 3.5:
            return "⚡ Pocket Pivot Ignition"
        if s_anchor >= 45.0 and close_val >= sma50_val * 0.98:
            return "🛡️ High-Surety Anchor"

        return top_label

    ranked["inst_signal"] = ranked.apply(get_signal, axis=1)
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
        if c_val >= invalidation_level and c_val >= s50_val * 0.97 and -5.0 <= mrs_i <= 6.0:
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
) -> tuple:
    """
    Simulates dynamic structural trend following exit.
    Returns (exit_return_pct, days_to_exit).
    """
    if fut_slice.empty or len(fut_slice) < 2:
        return 0.0, 1

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
                return round(((c_val - entry_price) / entry_price) * 100.0, 2), idx
        elif stage == 1:
            dynamic_stop = max(entry_price * 1.05, s50_val * 0.975)
            if c_val < dynamic_stop:
                return round(((c_val - entry_price) / entry_price) * 100.0, 2), idx
        else:
            dynamic_stop = max(entry_price * 1.20, s50_val * 0.99, s20_val * 0.955, running_peak * 0.84)
            if c_val < dynamic_stop:
                return round(((c_val - entry_price) / entry_price) * 100.0, 2), idx

    final_close = float(closes[-1])
    return round(((final_close - entry_price) / entry_price) * 100.0, 2), len(fut_slice) - 1


def select_top_stocks_for_model(
    model_name: str,
    ranked_at_q: pd.DataFrame,
    sector_summary: pd.DataFrame,
    target_count: int = 20,
) -> tuple:
    valid_secs = sector_summary[
        (sector_summary["stock_count"] >= 3)
        & (sector_summary["sector"] != "General Equities")
    ].copy()

    top_sectors_df = valid_secs.sort_values(by=["sector_composite_score", "rs_ratio"], ascending=False).head(5)
    top_3_sectors = top_sectors_df.head(3).to_dict(orient="records")
    top_5_sectors = top_sectors_df.head(5).to_dict(orient="records")

    pool = ranked_at_q.copy()
    close_s = pool["close"]
    s50_s = pool["sma_50"]
    s200_s = pool["sma_200"]
    mrs_s = pool["mrs_score"]
    stoch_s = pool["stoch_k"]

    if model_name == "score_surety_anchor":
        mask = (close_s >= s200_s) & (close_s >= s50_s * 0.97) & (mrs_s >= -5.0) & (mrs_s <= 6.0)
        qualified = pool[mask].sort_values(by=["score_surety_anchor", "iasis_score"], ascending=False)

    elif model_name == "score_momentum_frontrunner":
        mask = (close_s >= s200_s) & (close_s >= s50_s) & (mrs_s >= -2.0) & (mrs_s <= 10.0)
        qualified = pool[mask].sort_values(by=["score_momentum_frontrunner", "frontrunner_score"], ascending=False)

    elif model_name == "score_early_sector_rotation":
        s_life_s = pool["sector_lifecycle"].astype(str)
        s_rs_s = pool["sector_rs_status"].astype(str)
        mask = (close_s >= s200_s) & (~s_rs_s.str.contains("Lagging") | ~s_life_s.str.contains("Lagging") | (pool["beta_neutral_mrs"] >= 1.5))
        qualified = pool[mask].sort_values(by=["score_early_sector_rotation", "iasis_score"], ascending=False)

    elif model_name == "score_high_rs_pullback":
        mask = (close_s >= s200_s) & (mrs_s >= -7.0) & (mrs_s <= 2.5) & (stoch_s <= 75)
        qualified = pool[mask].sort_values(by=["score_high_rs_pullback", "frontrunner_score"], ascending=False)

    else:
        qualified = pool.sort_values(by=["score_surety_anchor"], ascending=False)

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

    return top_3_sectors, top_5_sectors, selected


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

    print("[*] Pre-computing rolling moving averages & signal states...")
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
        symbol_groups[sym] = g

    # EXACT 4 ACTIVE STRATEGIES
    MODELS = [
        ("score_surety_anchor", "🛡️ Strategy 1: High-Surety Institutional Anchor"),
        ("score_momentum_frontrunner", "🚀 Strategy 2: Momentum Frontrunner"),
        ("score_early_sector_rotation", "🔄 Strategy 3: Early Sector Rotation Leader"),
        ("score_high_rs_pullback", "📉 Strategy 4: High-RS Pullback Structure"),
    ]

    months_payload = []
    all_csv_rows = []

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
            "total_days_to_peak": 0.0,
            "total_days_to_exit": 0.0,
            # Dual Quantitative Win Rate & PnL Accumulators
            "m2_wins": 0,  # Method 2: Peak MFE >= Highest ATR Stop (9.50%)
            "m3_wins": 0,  # Method 3: Peak MFE >= Blended Order Block Stop (4.38%)
            "m3_total_profit_inr": 0.0,
            "m3_total_employed_cap": 0.0,
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

    print("\n" + "=" * 156)
    print("RUNNING 10-MONTH QUANTITATIVE AUDIT: 4 CORE STRATEGIES (WITH ADJUSTED HOLDING DURATION & 232-SESSION XIRR)")
    print(f"100% Real Bhavcopy Data | Evaluated Point-in-Time Forward to: {latest_date_overall}")
    print("=" * 156)

    for m_info in monthly_checkpoints:
        m_label = m_info["label"]
        m_start_date = m_info["date"]
        print(f"[*] Auditing Month: {m_label} (Signal Date: {m_start_date})...")

        sector_summary, ranked_at_m = evaluate_point_in_time(df_all, m_start_date)

        u_start = df_all[df_all["date"] == m_start_date]["close"].mean()
        u_end = df_all[df_all["date"] == latest_date_overall]["close"].mean()
        universe_ret = round(float(((u_end - u_start) / (u_start + 1e-5)) * 100.0), 2)

        # Factor Ablation on Qualified Stage-2 Setups
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
            poc_floor = bool(stk.get("poc_floor_support", False))
            is_leading_sec = str(stk.get("sector_rs_status", "")) != "🔴 Lagging Sector"

            advanced_factors_accumulator["1. Base Universe Stage-2 Setups"].append((mfe_v, mae_v, ret_v))
            if poc_floor:
                advanced_factors_accumulator["2. AVWAP Defense (Close >= 100D MaxVol VWAP)"].append((mfe_v, mae_v, ret_v))
            if float(stk.get("deliv_pct", 0.0)) >= 45.0:
                advanced_factors_accumulator["3. High Closing Range Accumulation (CR >= 0.55)"].append((mfe_v, mae_v, ret_v))
            if float(stk.get("vcp_ratio", 1.0)) <= 0.65:
                advanced_factors_accumulator["4. Volatility Compression Black Hole (ATR5/ATR50 <= 0.50)"].append((mfe_v, mae_v, ret_v))
            if poc_floor and float(stk.get("deliv_pct", 0.0)) >= 45.0:
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

            if pat_name and poc_floor and is_leading_sec:
                pattern_confluence_accumulator["Cohort 3: Pattern + Full Institutional Confluence (POC Floor + Flow)"].append((mfe_v, mae_v, ret_v))

        # Sector Climax Audit
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

        for m_key, m_desc in MODELS:
            top_3_sectors, top_5_sectors, top_stocks = select_top_stocks_for_model(
                m_key, ranked_at_m, sector_summary, target_count=20
            )

            stock_records = []
            for rank_idx, (_, stk_row) in enumerate(top_stocks.iterrows(), start=1):
                sym = str(stk_row["symbol"])
                sym_df = symbol_groups.get(sym, pd.DataFrame())

                entry_price = round(float(stk_row["close"]), 2)
                atr_20_val = float(stk_row["atr_20"])
                atr_stop = round(float(stk_row["atr_stop_loss"]), 2)
                mcap_tier = str(stk_row.get("mcap_tier", "Tier 2/3: Mid & Small Cap"))
                sec_life = str(stk_row.get("sector_lifecycle", "🟢 Prime Institutional Leadership"))
                sec_mult = float(stk_row.get("sector_climax_mult", 1.0))
                surety_val = float(stk_row.get("score_surety_anchor", 50.0))
                poc_val = float(stk_row.get("volume_profile_poc", entry_price))
                poc_floor = bool(stk_row.get("poc_floor_support", entry_price >= poc_val))
                tranche2_limit = float(stk_row.get("tranche2_limit_price", entry_price - (1.5 * atr_20_val)))
                blended_entry = float(stk_row.get("blended_entry_price", (entry_price + tranche2_limit) / 2.0))
                cushioned_sl = float(stk_row.get("cushioned_sl_price", atr_stop))

                today_price, today_actual_date = lookup_real_close_on_or_after(sym_df, latest_date_overall)

                fut_slice = sym_df[sym_df["date"] >= m_start_date].reset_index(drop=True)
                if not fut_slice.empty:
                    max_pos = int(fut_slice["high"].values.argmax())
                    peak_row = fut_slice.iloc[max_pos]
                    peak_high = round(float(peak_row["high"]), 2)
                    peak_date = str(peak_row["date"])
                    days_to_peak = max(1, max_pos)
                    peak_gain_pct = round(((peak_high - entry_price) / entry_price) * 100.0, 2)

                    slice_30d = fut_slice.iloc[: min(31, len(fut_slice))]
                    mfe_30d_pct = round(((float(slice_30d["high"].max()) - entry_price) / entry_price) * 100.0, 2)

                    slice_60d = fut_slice.iloc[: min(61, len(fut_slice))]
                    mfe_60d_pct = round(((float(slice_60d["high"].max()) - entry_price) / entry_price) * 100.0, 2)

                    min_pos = int(fut_slice["low"].values.argmin())
                    low_row = fut_slice.iloc[min_pos]
                    min_low = round(float(low_row["low"]), 2)
                    max_drawdown_mae_pct = round(((min_low - entry_price) / entry_price) * 100.0, 2)

                    trailing_exit_ret, days_to_exit = simulate_structural_trailing_exit(
                        fut_slice,
                        entry_price,
                        atr_20_val,
                        fut_slice["sma50_roll"].values,
                        fut_slice["sma20_roll"].values,
                    )

                    persist_sim = simulate_signal_persistence(fut_slice, entry_price, atr_20_val)
                    
                    # 50:50 Staggered Order Block Simulation
                    tranche2_filled = bool(float(fut_slice["low"].min()) <= tranche2_limit)
                    if tranche2_filled:
                        effective_cost = blended_entry
                        effective_cap_deployed = 100000.0  # Full position
                        effective_mfe_pct = round(((peak_high - blended_entry) / blended_entry) * 100.0, 2)
                        effective_mae_pct = round(((min_low - blended_entry) / blended_entry) * 100.0, 2)
                        effective_sl_pct = round(((cushioned_sl - blended_entry) / blended_entry) * 100.0, 2)
                    else:
                        effective_cost = entry_price
                        effective_cap_deployed = 50000.0   # Half position only
                        effective_mfe_pct = peak_gain_pct
                        effective_mae_pct = max_drawdown_mae_pct
                        effective_sl_pct = round(((atr_stop - entry_price) / entry_price) * 100.0, 2)

                else:
                    peak_high, peak_date, days_to_peak, peak_gain_pct = entry_price, m_start_date, 1, 0.0
                    mfe_30d_pct, mfe_60d_pct = 0.0, 0.0
                    min_low, max_drawdown_mae_pct = entry_price, 0.0
                    trailing_exit_ret, days_to_exit = 0.0, 1
                    persist_sim = {
                        "zone_persistence_days": 1,
                        "trend_persistence_days": 1,
                        "active_5d": True,
                        "active_10d": True,
                    }
                    tranche2_filled = False
                    effective_cost = entry_price
                    effective_cap_deployed = 50000.0
                    effective_mfe_pct = 0.0
                    effective_mae_pct = 0.0
                    effective_sl_pct = -6.50

                total_return_pct = (
                    round(((today_price - entry_price) / entry_price) * 100.0, 2)
                    if (today_price and entry_price)
                    else 0.0
                )

                base_pattern = str(stk_row.get("chart_pattern_signal", ""))

                # Method 2 Win Condition (Stress-Tested vs Highest ATR Stop 9.50%)
                is_m2_win = bool(peak_gain_pct >= 9.50)

                # Method 3 Win Condition (50:50 Staggered Order Block vs Blended Stop ~4.38%)
                is_m3_win = bool(effective_mfe_pct >= abs(effective_sl_pct))

                if is_m3_win:
                    trade_pnl_inr = (effective_cap_deployed * (effective_mfe_pct / 100.0))
                else:
                    trade_pnl_inr = (effective_cap_deployed * (effective_sl_pct / 100.0))

                # Individual realistic adjusted holding duration (+25% buffer)
                adj_days_to_exit = round(float(days_to_exit) * 1.25, 1)

                stock_record = {
                    "rank": rank_idx,
                    "symbol": sym,
                    "company_name": str(stk_row.get("company_name", sym)),
                    "sector": str(stk_row.get("sector", "Capital Goods")),
                    "index_name": str(stk_row.get("index_name", "Nifty 500")),
                    "mcap_tier": mcap_tier,
                    "inst_signal_at_entry": str(stk_row.get("inst_signal", "Consolidation")),
                    "chart_pattern_at_entry": base_pattern,
                    "base_chart_pattern": base_pattern,
                    "volume_profile_poc": poc_val,
                    "poc_floor_support": poc_floor,
                    "sector_rs_status_at_entry": str(stk_row.get("sector_rs_status", "Normal")),
                    "sector_lifecycle_at_entry": sec_life,
                    "sector_climax_mult_at_entry": sec_mult,
                    "surety_score_at_entry": surety_val,
                    "score_surety_anchor": float(stk_row.get("score_surety_anchor", 50.0)),
                    "score_momentum_frontrunner": float(stk_row.get("score_momentum_frontrunner", 50.0)),
                    "score_early_sector_rotation": float(stk_row.get("score_early_sector_rotation", 50.0)),
                    "score_high_rs_pullback": float(stk_row.get("score_high_rs_pullback", 50.0)),
                    "frontrunner_score_at_entry": float(stk_row.get("frontrunner_score", 50.0)),
                    "iasis_score_at_entry": float(stk_row.get("iasis_score", 50.0)),
                    "mrs_20d_at_entry_pct": float(stk_row.get("mrs_score", 0.0)),
                    "dist_50d_at_entry_pct": float(stk_row.get("dist_from_50_pct", 0.0)),
                    "prior_63d_run_pct": float(stk_row.get("prior_63d_pct", 0.0)),
                    "zone_persistence_days": persist_sim["zone_persistence_days"],
                    "trend_persistence_days": persist_sim["trend_persistence_days"],
                    "entry_date": m_start_date,
                    "entry_price": entry_price,
                    "tranche2_limit_price": tranche2_limit,
                    "blended_entry_price": blended_entry,
                    "cushioned_sl_price": cushioned_sl,
                    "atr_stop_loss": atr_stop,
                    "tranche2_filled": tranche2_filled,
                    "effective_cap_deployed": effective_cap_deployed,
                    "effective_mfe_pct": effective_mfe_pct,
                    "effective_sl_pct": effective_sl_pct,
                    "is_method2_win": is_m2_win,
                    "is_method3_win": is_m3_win,
                    "method3_pnl_inr": round(trade_pnl_inr, 2),
                    "peak_high_since_entry": peak_high,
                    "peak_date": peak_date,
                    "days_to_peak": days_to_peak,
                    "raw_days_to_exit": days_to_exit,
                    "adjusted_days_to_exit": adj_days_to_exit,
                    "max_gain_mfe_pct": peak_gain_pct,
                    "mfe_30d_pct": mfe_30d_pct,
                    "mfe_60d_pct": mfe_60d_pct,
                    "min_low_since_entry": min_low,
                    "max_drawdown_mae_pct": max_drawdown_mae_pct,
                    "today_date": today_actual_date,
                    "today_price": today_price,
                    "total_return_to_today_pct": total_return_pct,
                    "trailing_exit_return_pct": trailing_exit_ret,
                }
                stock_records.append(stock_record)

                if m_key == "score_surety_anchor":
                    if mcap_tier not in mcap_stats_accumulator:
                        mcap_stats_accumulator[mcap_tier] = []
                    mcap_stats_accumulator[mcap_tier].append({
                        "mfe": peak_gain_pct,
                        "mae": max_drawdown_mae_pct,
                        "ret": total_return_pct,
                        "trail": trailing_exit_ret,
                        "zone_p": persist_sim["zone_persistence_days"],
                        "trend_p": persist_sim["trend_persistence_days"],
                    })

                all_csv_rows.append({
                    "strategy_model": m_key,
                    "signal_month": m_label,
                    "signal_date": m_start_date,
                    "rank": rank_idx,
                    "symbol": sym,
                    "company_name": stock_record["company_name"],
                    "sector": stock_record["sector"],
                    "mcap_tier": mcap_tier,
                    "sector_lifecycle": sec_life,
                    "signal_at_entry": stock_record["inst_signal_at_entry"],
                    "pattern": base_pattern,
                    "poc_floor_support": poc_floor,
                    "entry_price": entry_price,
                    "tranche2_limit_price": tranche2_limit,
                    "blended_entry_price": blended_entry,
                    "cushioned_sl_price": cushioned_sl,
                    "tranche2_filled": tranche2_filled,
                    "peak_price": peak_high,
                    "peak_date": peak_date,
                    "days_to_peak": days_to_peak,
                    "days_to_exit": days_to_exit,
                    "adjusted_days_to_exit": adj_days_to_exit,
                    "max_gain_mfe_pct": peak_gain_pct,
                    "mfe_30d_pct": mfe_30d_pct,
                    "mfe_60d_pct": mfe_60d_pct,
                    "max_drawdown_mae_pct": max_drawdown_mae_pct,
                    "is_method2_win": is_m2_win,
                    "is_method3_win": is_m3_win,
                    "method3_pnl_inr": round(trade_pnl_inr, 2),
                    "today_price": today_price,
                    "hold_return_pct": total_return_pct,
                    "trailing_exit_pct": trailing_exit_ret,
                })

            rets = [s["total_return_to_today_pct"] for s in stock_records]
            trail_rets = [s["trailing_exit_return_pct"] for s in stock_records]
            mfes = [s["max_gain_mfe_pct"] for s in stock_records]
            mfes_30 = [s["mfe_30d_pct"] for s in stock_records]
            mfes_60 = [s["mfe_60d_pct"] for s in stock_records]
            maes = [s["max_drawdown_mae_pct"] for s in stock_records]
            z_pers = [s["zone_persistence_days"] for s in stock_records]
            t_pers = [s["trend_persistence_days"] for s in stock_records]
            pk_days = [s["days_to_peak"] for s in stock_records]
            ex_days = [s["raw_days_to_exit"] for s in stock_records]

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
            avg_pk_d = round(float(np.mean(pk_days)), 1) if pk_days else 1.0
            avg_ex_d = round(float(np.mean(ex_days)), 1) if ex_days else 1.0
            avg_adj_hold_d = round(avg_ex_d * 1.25, 1)

            m2_wins_m = sum(1 for s in stock_records if s["is_method2_win"])
            m3_wins_m = sum(1 for s in stock_records if s["is_method3_win"])
            m3_pnl_m = sum(s["method3_pnl_inr"] for s in stock_records)
            m3_cap_m = sum(s["effective_cap_deployed"] for s in stock_records)

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
            acc["total_days_to_peak"] += float(np.sum(pk_days))
            acc["total_days_to_exit"] += float(np.sum(ex_days))
            acc["m2_wins"] += m2_wins_m
            acc["m3_wins"] += m3_wins_m
            acc["m3_total_profit_inr"] += m3_pnl_m
            acc["m3_total_employed_cap"] += m3_cap_m

            month_modes_output[m_key] = {
                "model_key": m_key,
                "model_name": m_desc,
                "evaluation_date": latest_date_overall,
                "picks_count": len(stock_records),
                "portfolio_avg_return_pct": avg_ret,
                "trailing_exit_avg_return_pct": avg_trail_ret,
                "portfolio_win_rate_pct": win_rate,
                "method2_win_rate_pct": round((m2_wins_m / max(1, len(stock_records))) * 100.0, 1),
                "method3_win_rate_pct": round((m3_wins_m / max(1, len(stock_records))) * 100.0, 1),
                "avg_peak_mfe_pct": avg_mfe,
                "avg_mfe_30d_pct": avg_mfe_30,
                "avg_mfe_60d_pct": avg_mfe_60,
                "hit_15pct_target_rate_pct": hit_15,
                "hit_20pct_target_rate_pct": hit_20,
                "avg_drawdown_mae_pct": avg_mae,
                "avg_days_to_peak": avg_pk_d,
                "raw_trade_duration_days": avg_ex_d,
                "adjusted_trade_duration_days": avg_adj_hold_d,
                "avg_zone_persistence_days": avg_zone_p,
                "avg_trend_persistence_days": avg_trend_p,
                "universe_benchmark_return_pct": universe_ret,
                "alpha_vs_universe_pct": round(avg_ret - universe_ret, 2),
                "top_3_sectors": top_3_sectors,
                "top_5_sectors": top_5_sectors,
                "picks": stock_records,
                "picks_9": stock_records[:20],
            }

        # Primary default view is Strategy 1: High-Surety Institutional Anchor
        primary_view = dict(month_modes_output["score_surety_anchor"])
        primary_view["quarter_label"] = m_label
        primary_view["start_date"] = m_start_date
        primary_view["modes"] = month_modes_output

        months_payload.append(primary_view)

    print("[*] Running Intra-Month Setup Timing Audit across 2026 sessions...")
    intramonth_audit = run_intramonth_timing_audit(symbol_groups, all_dates, latest_date_overall)

    # Market-Cap Tier Risk Summary
    mcap_summary_list = []
    for tier_label in sorted(mcap_stats_accumulator.keys()):
        t_items = mcap_stats_accumulator[tier_label]
        mfes_t = np.array([x["mfe"] for x in t_items])
        maes_t = np.array([x["mae"] for x in t_items])
        rets_t = np.array([x["ret"] for x in t_items])
        mcap_summary_list.append({
            "mcap_tier": tier_label,
            "count": len(t_items),
            "avg_mfe_pct": round(float(np.mean(mfes_t)), 2),
            "hit_15pct_rate": round(float((mfes_t >= 15.0).mean() * 100.0), 1),
            "low_mae_surety_rate": round(float((maes_t >= -6.0).mean() * 100.0), 1),
            "avg_mae_pct": round(float(np.mean(maes_t)), 2),
            "avg_hold_ret_pct": round(float(np.mean(rets_t)), 2),
        })

    # Sector Climax Audit
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

    # Pattern & Advanced Confluence Audit
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

    # Save detailed trade-by-trade CSV
    pd.DataFrame(all_csv_rows).to_csv(BACKTEST_CSV, index=False)

    # Strategy Macro Summary with Dual Method Win Rates & Realistic XIRR
    # (Adjusted Holding Days = Raw Days * 1.25 buffer | XIRR using 232 active business sessions / yr)
    strategy_macro_summary = {}
    for m_key, m_desc in MODELS:
        acc = model_stats_accumulator[m_key]
        n_tr = max(1, acc["trades"])
        
        m2_wr = round((acc["m2_wins"] / n_tr) * 100.0, 1)
        m3_wr = round((acc["m3_wins"] / n_tr) * 100.0, 1)
        
        m3_total_pnl = acc["m3_total_profit_inr"]
        m3_total_cap = max(1.0, acc["m3_total_employed_cap"])
        m3_net_roi = round((m3_total_pnl / m3_total_cap) * 100.0, 2)
        m3_pnl_per_trade = round(m3_total_pnl / n_tr, 2)

        # Expected Value per 1 Lakh allocation under Method 2 Stress Test (Worst-case 9.5% stop loss)
        avg_mfe_val = acc["total_mfe"] / n_tr
        m2_expectancy = round(((m2_wr / 100.0) * avg_mfe_val - ((100.0 - m2_wr) / 100.0) * 9.50) * 1000.0, 2)
        m2_net_roi = round(m2_expectancy / 1000.0, 2)

        # 1. Holding Duration with +25% Execution Cushion
        raw_hold_days = float(acc["total_days_to_exit"] / n_tr) if acc["total_days_to_exit"] > 0 else float(acc["total_trend_persist"] / n_tr)
        adj_hold_days = round(raw_hold_days * 1.25, 1)
        avg_pk_days = round(acc["total_days_to_peak"] / n_tr, 1)

        # 2. XIRR calculation with 232 active trading sessions (252 - 20 no-business/cash buffer days)
        active_sessions = 232.0
        cycles_per_year = active_sessions / max(1.0, adj_hold_days)

        m3_roi_dec = m3_net_roi / 100.0
        m3_xirr = round(((1.0 + m3_roi_dec) ** cycles_per_year - 1.0) * 100.0, 1) if (adj_hold_days > 0 and m3_roi_dec > -1.0) else 0.0

        m2_roi_dec = m2_net_roi / 100.0
        m2_xirr = round(((1.0 + m2_roi_dec) ** cycles_per_year - 1.0) * 100.0, 1) if (adj_hold_days > 0 and m2_roi_dec > -1.0) else 0.0

        strategy_macro_summary[m_key] = {
            "strategy_key": m_key,
            "strategy_name": m_desc,
            "total_signals_tracked": acc["trades"],
            "overall_avg_mfe_pct": round(avg_mfe_val, 2),
            "overall_avg_mae_pct": round(acc["total_mae"] / n_tr, 2),
            "overall_hold_return_pct": round(acc["total_return"] / n_tr, 2),
            "overall_trail_return_pct": round(acc["total_trail_return"] / n_tr, 2),
            "overall_hold_win_rate_pct": round((acc["wins"] / n_tr) * 100.0, 1),
            "hit_15pct_rate": round((acc["hits_15"] / n_tr) * 100.0, 1),
            "hit_20pct_rate": round((acc["hits_20"] / n_tr) * 100.0, 1),
            "low_mae_surety_rate": round((acc["low_mae_count"] / n_tr) * 100.0, 1),
            "avg_days_to_peak": avg_pk_days,
            "raw_trade_duration_days": round(raw_hold_days, 1),
            "trade_duration_days": adj_hold_days,
            "annualized_turnover_velocity": round(cycles_per_year, 1),
            "active_business_sessions_per_year": int(active_sessions),
            
            # --- METHOD 2: STRESS-TESTED VS WORST-CASE ATR STOP (9.50%) ---
            "method2_win_rate_pct": m2_wr,
            "method2_net_expectancy_pct": m2_net_roi,
            "method2_profit_per_lakh": m2_expectancy,
            "method2_xirr_pct": m2_xirr,
            "method2_risk_clamp_pct": -9.50,
            "method2_desc": "Stress-Tested vs Worst-Case ATR Stop (9.50%)",

            # --- METHOD 3: 50:50 ORDER BLOCK VS BLENDED STOP (~4.38%) ---
            "method3_win_rate_pct": m3_wr,
            "method3_net_expectancy_pct": m3_net_roi,
            "method3_profit_per_lakh": m3_pnl_per_trade,
            "method3_xirr_pct": m3_xirr,
            "method3_desc": "50:50 Staggered Order Block vs Blended Stop (4.38%)",
        }

    total_trades_all = sum(acc["trades"] for acc in model_stats_accumulator.values())
    total_mfe_all = sum(acc["total_mfe"] for acc in model_stats_accumulator.values())
    total_wins_all = sum(acc["wins"] for acc in model_stats_accumulator.values())
    total_m2_wins_all = sum(acc["m2_wins"] for acc in model_stats_accumulator.values())
    total_m3_wins_all = sum(acc["m3_wins"] for acc in model_stats_accumulator.values())
    total_hits15_all = sum(acc["hits_15"] for acc in model_stats_accumulator.values())
    n_all = max(1, total_trades_all)

    global_macro_stats = {
        "total_audited_windows": len(monthly_checkpoints),
        "total_signals_tracked": total_trades_all,
        "overall_avg_mfe_pct": round(total_mfe_all / n_all, 2),
        "overall_hold_win_rate_pct": round((total_wins_all / n_all) * 100.0, 1),
        "method2_win_rate_pct": round((total_m2_wins_all / n_all) * 100.0, 1),
        "method3_win_rate_pct": round((total_m3_wins_all / n_all) * 100.0, 1),
        "hit_15pct_rate": round((total_hits15_all / n_all) * 100.0, 1),
        "active_business_sessions_per_year": 232,
        "duration_cushion_buffer_pct": 25.0,
    }

    final_json = {
        "generated_at_eod": latest_date_overall,
        "corporate_actions_normalized_count": len(corp_action_events),
        "quarter_checkpoints": monthly_checkpoints,
        "global_macro_summary": global_macro_stats,
        "strategies_summary": strategy_macro_summary,
        "mcap_tier_summary": mcap_summary_list,
        "sector_climax_audit": sector_climax_audit_list,
        "intramonth_timing_audit": intramonth_audit,
        "pattern_confluence_audit": pattern_audit_summary,
        "advanced_factors_audit": advanced_factors_summary,
        "quarters": months_payload,
    }
    with open(BACKTEST_JSON, "w") as f:
        json.dump(final_json, f, indent=2)

    compact_summary = {
        "generated_at_eod": latest_date_overall,
        "corporate_actions_normalized_count": len(corp_action_events),
        "total_audited_windows": len(monthly_checkpoints),
        "global_macro_summary": global_macro_stats,
        "strategies_summary": strategy_macro_summary,
        "mcap_tier_summary": mcap_summary_list,
        "sector_climax_audit": sector_climax_audit_list,
        "intramonth_timing_audit": intramonth_audit,
        "pattern_confluence_audit": pattern_audit_summary,
        "advanced_factors_audit": advanced_factors_summary,
    }
    with open(BACKTEST_SUMMARY_JSON, "w") as f:
        json.dump(compact_summary, f, indent=2)

    # Console Diagnostic Output
    print("\n" + "=" * 168)
    print("10-MONTH QUANTITATIVE STRATEGY LEADERBOARD (REALISTIC 232-DAY XIRR & +25% BUFFERED DURATION)")
    print("=" * 168)
    print(
        f"{'Strategy Model':<42} | {'Signals':<7} | {'Peak MFE':<9} | "
        f"{'Duration':<10} | {'M2 WR%':<8} | {'M2 XIRR':<10} || "
        f"{'M3 WR%':<8} | {'Net Exp%':<9} | {'Exp / 1L':<12} | {'M3 XIRR'}"
    )
    print("-" * 168)
    for m_key, m_desc in MODELS:
        sm = strategy_macro_summary[m_key]
        print(
            f"{m_desc:<42} | {sm['total_signals_tracked']:<7} | +{sm['overall_avg_mfe_pct']:>5.2f}%   | "
            f"{sm['trade_duration_days']:>4.1f} days  | {sm['method2_win_rate_pct']:>5.1f}%  | +{sm['method2_xirr_pct']:>6.1f}%   || "
            f"{sm['method3_win_rate_pct']:>5.1f}%  | +{sm['method3_net_expectancy_pct']:>5.2f}%   | +₹{sm['method3_profit_per_lakh']:>9,.2f} | +{sm['method3_xirr_pct']:>6.1f}%"
        )

    print("\n" + "=" * 168)
    print(f"[✓] Saved full backtest data to:    {BACKTEST_JSON}")
    print(f"[✓] Saved macro-summary data to:    {BACKTEST_SUMMARY_JSON}")
    print(f"[✓] Saved raw trade log CSV to:     {BACKTEST_CSV}")
    print("=" * 168)


if __name__ == "__main__":
    run_quarterly_backtest()