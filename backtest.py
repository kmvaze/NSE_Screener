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
    of every month from January 2026 through November 2026.
    """
    monthly_checkpoints = []
    for month in range(1, 12):
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
        prices = grp["close"].values.astype(float)
        volumes = grp["volume"].values.astype(float)
        highs = grp["high"].values.astype(float)
        lows = grp["low"].values.astype(float)
        deliv_qtys = grp["deliv_qty"].values.astype(float) if "deliv_qty" in grp.columns else np.zeros_like(prices)

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
        sma_50_5d_ago = float(sma_50_series.iloc[-min(6, len(sma_50_series))])
        sma_50_10d_ago = float(sma_50_series.iloc[-min(10, len(sma_50_series))])
        sma_50_rising = sma_50 >= (sma_50_10d_ago * 0.998)
        sma_200 = round(float(p_series.rolling(min(200, n_bars), min_periods=20).mean().iloc[-1]), 2)

        above_sma50_5d_ago = bool(prices[-min(6, n_bars)] >= sma_50_5d_ago)

        tr_arr = np.maximum(
            highs[-20:] - lows[-20:],
            np.maximum(
                np.abs(highs[-20:] - np.roll(prices, 1)[-20:]),
                np.abs(lows[-20:] - np.roll(prices, 1)[-20:]),
            ),
        )
        atr_20 = float(np.mean(tr_arr))
        atr_pct = round(float((atr_20 / (close + 1e-5)) * 100.0), 2)

        poc_bars = min(50, n_bars)
        hist, bins = np.histogram(prices[-poc_bars:], bins=10, weights=volumes[-poc_bars:])
        poc = round(float((bins[np.argmax(hist)] + bins[np.argmax(hist) + 1]) / 2.0), 2)

        cr = float((close - lows[-1]) / (highs[-1] - lows[-1] + 1e-5))

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

        # ---------------------------------------------------------------------
        # EMPIRICAL KINETIC ALPHA SCORE (SYNCHRONIZED WITH PIPELINE.PY)
        # ---------------------------------------------------------------------
        atr_fuel_pts = float(np.clip(((atr_pct - 2.2) / 2.4) * 30.0, 2.0, 30.0))
        base_coil_pts = float(np.clip(25.0 * np.exp(-((base_depth_pct - 21.5) ** 2) / 65.0), 3.0, 25.0)) if close >= sma_50 else 4.0
        flow_pts = float(np.clip(30.0 * (np.log1p(min(deliv_flow_ratio, 6.0)) / np.log1p(4.0)), 4.0, 30.0))
        ud_pts = float(np.clip(((up_down_ratio - 1.0) / 1.5) * 15.0, 2.0, 15.0))

        raw_iasis = atr_fuel_pts + base_coil_pts + flow_pts + ud_pts
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

        is_tier1_sym = (sym in NIFTY_50_SYMBOLS) or (sym in NIFTY_NEXT_50_SYMBOLS)
        atr_mult = 2.8 if is_tier1_sym else 2.5
        max_sl_floor = 0.935 if is_tier1_sym else 0.885

        raw_struct_stop = min(close - (atr_mult * atr_20), sma_50 * (0.965 if is_tier1_sym else 0.960))
        structural_stop = round(float(max(close * max_sl_floor, raw_struct_stop)), 2)

        stock_tech_rows.append({
            "symbol": sym,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "sma_50_rising": sma_50_rising,
            "above_sma50_5d_ago": above_sma50_5d_ago,
            "stage2_aligned": bool((close > sma_50) and (sma_50 > sma_200) and sma_50_rising),
            "ema_10": ema_10,
            "ema_21": ema_21,
            "rsi_14": rsi_14,
            "stoch_k": stoch_k,
            "atr_20": atr_20,
            "atr_pct": atr_pct,
            "structural_stop": structural_stop,
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
            "closing_range": round(cr, 3),
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

    tech_df = pd.DataFrame(stock_tech_rows)
    sec_lag_cols = sec_base[["symbol", "close_20d_ago", "close_63d_ago"]].drop_duplicates(subset=["symbol"])

    ranked = pd.merge(latest_df, tech_df, on="symbol", how="inner")
    ranked = pd.merge(ranked, sec_lag_cols, on="symbol", how="left")
    ranked = ranked.drop_duplicates(subset=["symbol"])
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

    tier_above_sma50 = ranked.groupby("mcap_tier")["above_sma50"].mean().mul(100.0).to_dict()
    universe_20d_ret = float(((ranked["close"] / (ranked["close_20d_ago"] + 1e-5)) - 1.0).mean() * 100.0)
    tier_20d_ret = ranked.groupby("mcap_tier").apply(
        lambda g: float((((g["close"] / (g["close_20d_ago"] + 1e-5)) - 1.0).mean() * 100.0))
    ).to_dict()

    def compute_selective_tier_mult(row):
        tier = str(row["mcap_tier"])
        b = tier_above_sma50.get(tier, 50.0)
        ret_diff = tier_20d_ret.get(tier, 0.0) - universe_20d_ret
        is_poc_supported = float(row["close"]) >= float(row["volume_profile_poc"])

        if "Tier 1" in tier:
            if ret_diff > 1.5 and is_poc_supported and float(row.get("trend_score", 0)) >= 75.0:
                return 0.96
            return 0.85

        if b < 25.0 or ret_diff < -2.5:
            return 0.92
        elif ret_diff > 0.0 and b >= 50.0:
            return 1.06
        return 1.02

    ranked["tier_climax_mult"] = ranked.apply(compute_selective_tier_mult, axis=1)

    global_rs_pct = ranked["raw_multi_rs"].rank(pct=True) * 100.0
    tier_rs_pct = ranked.groupby("mcap_tier")["raw_multi_rs"].rank(pct=True) * 100.0
    rs_percentile = ((0.80 * global_rs_pct) + (0.20 * tier_rs_pct)).round(1)
    ranked["blended_rs_percentile"] = rs_percentile

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
    stoch_multiplier = np.where(ranked["stoch_k"] <= 75.0, 1.0, 0.78)
    ranked["ignition_score"] = (ignition_raw * ext_multiplier * stage_multiplier * stoch_multiplier).clip(5.0, 99.0).round(1)

    ranked["frontrunner_score"] = (
        0.25 * ranked["trend_score"]
        + 0.45 * rs_percentile
        + 0.15 * peer_rs_percentile
        + 0.15 * up_down_pct
    ).clip(5.0, 99.0).round(1)

    mom_struct_penalty = np.where(ranked["mrs_score"] < -1.0, 0.75, 1.0)
    rot_struct_penalty = np.where(ranked["sector_lifecycle"].str.contains("Rotation|Leadership|Improving|Prime"), 1.08, 0.72)
    poc_multiplier = np.where(ranked["close"] >= ranked["volume_profile_poc"], 1.06, 0.85)
    sec_adj = np.clip(ranked["sector_climax_mult"], 0.84, 1.08)

    kinetic_mult = np.where(
        (ranked["atr_pct"] >= 3.20) & (ranked["rsi_14"] <= 62.5),
        1.08,
        np.where(ranked["atr_pct"] < 2.80, 0.72, 0.96),
    )

    # 1. Strategy 1: High-Surety Institutional Anchor
    dist_poc_pct_series = np.where(
        ranked["volume_profile_poc"] > 0,
        ((ranked["close"] - ranked["volume_profile_poc"]) / (ranked["volume_profile_poc"] + 1e-5)) * 100.0,
        0.0,
    )
    poc_floor_pts = 28.0 * np.exp(-((dist_poc_pct_series - 2.0) ** 2) / 14.0)
    atr_anchor_pts = np.clip(((ranked["atr_pct"] - 2.3) / 2.2) * 22.0, 3.0, 22.0)
    deliv_anchor_pts = np.clip(25.0 * (np.log1p(np.minimum(ranked["flow_ratio"], 5.0)) / np.log1p(3.5)), 4.0, 25.0)

    raw_surety = (
        poc_floor_pts
        + atr_anchor_pts
        + deliv_anchor_pts
        + (0.15 * rs_percentile)
        + (0.10 * ranked["iasis_score"])
    )
    ranked["score_surety_anchor"] = (raw_surety * sec_adj * poc_multiplier * ranked["tier_climax_mult"] * kinetic_mult).clip(5.0, 99.0).round(1)
    ranked["surety_score"] = ranked["score_surety_anchor"]

    # 2. Strategy 2: Momentum Frontrunner
    rsi_headroom_mult = np.where(ranked["rsi_14"] <= 62.5, 1.05, 0.78)
    dist50_sweet_pts = np.clip(((ranked["dist_from_50_pct"] - 2.0) / 10.0) * 20.0, 2.0, 20.0)
    ranked["score_momentum_frontrunner"] = (
        (0.45 * rs_percentile + 0.25 * ranked["iasis_score"] + 0.15 * ranked["trend_score"] + dist50_sweet_pts)
        * sec_adj
        * mom_struct_penalty
        * ranked["tier_climax_mult"]
        * kinetic_mult
        * rsi_headroom_mult
    ).clip(5.0, 99.0).round(1)

    # 3. Strategy 3: Early Sector Rotation Leader
    ranked["score_early_sector_rotation"] = (
        (0.35 * rs_percentile + 0.25 * peer_rs_percentile + 0.25 * ranked["iasis_score"] + 0.15 * ranked["ignition_score"])
        * rot_struct_penalty
        * poc_multiplier
        * ranked["tier_climax_mult"]
        * kinetic_mult
    ).clip(5.0, 99.0).round(1)

    # 4. Strategy 4: High-RS Pullback Structure
    pullback_depth_pts = 30.0 * np.exp(-((ranked["mrs_score"] - (-1.0)) ** 2) / 8.5)
    stoch_oversold_pts = 20.0 * np.clip(1.0 - (ranked["stoch_k"] / 65.0), 0.0, 1.0)
    cr_series = ranked["closing_range"]
    pullback_qual_bonus = np.where(
        (ranked["vol_dryup_ratio"] <= 0.88) | (cr_series >= 0.60),
        15.0,
        np.clip(15.0 * (cr_series / 0.60), 0.0, 15.0),
    )
    pullback_penalty = np.where((ranked["session_rvol"] >= 1.6) & (cr_series < 0.35), 0.75, 1.0)

    ranked["score_high_rs_pullback"] = (
        (pullback_depth_pts + stoch_oversold_pts + pullback_qual_bonus + 0.25 * rs_percentile + 0.15 * ranked["iasis_score"])
        * sec_adj
        * pullback_penalty
        * ranked["tier_climax_mult"]
        * kinetic_mult
    ).clip(5.0, 99.0).round(1)

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

        if mrs > 8.0 or float(r.get("dist_from_50_pct", 0.0)) > 18.0 or float(r.get("prior_63d_pct", 0.0)) > 42.0:
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

        if top_label == "📉 High-RS Pullback" and (mrs <= 1.5 or stoch_val < 52.0) and close_val >= sma50_val * 0.98:
            return "📉 High-RS Pullback"
        if top_label == "🔄 Early Sector Rotation Leader" and ("Rotation" in s_life or "Prime" in s_life or "Leading" in s_life):
            return "🔄 Early Sector Rotation Leader"
        if top_label == "🚀 Momentum Frontrunner" and float(r["blended_rs_percentile"]) >= 78.0 and close_val >= sma50_val:
            return "🚀 Momentum Frontrunner"
        if c_pattern == "🎯 VCP Coiled Spring" and mrs <= 3.0:
            return "🎯 VCP Coiled Spring"
        if bool(r.get("is_pocket_pivot_5d", False)) and (bool(r.get("is_squeezed", False)) or bool(r.get("is_ma_pinched", False))) and mrs <= 3.5:
            return "⚡ Pocket Pivot Ignition"
        if s_anchor >= 50.0 and close_val >= sma50_val * 0.98:
            return "🛡️ High-Surety Anchor"

        return top_label

    ranked["inst_signal"] = ranked.apply(get_signal, axis=1)

    def classify_unified_risk(r):
        tier_str = str(r.get("mcap_tier", ""))
        atr_pct_val = float(r.get("atr_pct", 3.0))
        c = float(r["close"])
        s200 = float(r["sma_200"])
        is_above_poc = bool(c >= float(r.get("volume_profile_poc", 0)))
        s_surety = float(r.get("score_surety_anchor", 0))
        s_pull = float(r.get("score_high_rs_pullback", 0))
        s_mom = float(r.get("score_momentum_frontrunner", 0))

        if ("Tier 1" in tier_str or "Tier 2" in tier_str) and atr_pct_val <= 3.6 and c >= s200 and is_above_poc and (s_surety >= 58.0 or s_pull >= 58.0):
            return "Low"
        elif ("Tier 4" in tier_str) or (atr_pct_val >= 4.2) or (s_mom >= 72.0 and "Tier 1" not in tier_str):
            return "High"
        return "Medium"

    ranked["risk_suitability"] = ranked.apply(classify_unified_risk, axis=1)

    market_breadth_pct = float((ranked["above_sma50"].mean()) * 100.0)
    breadth_5d_ago_pct = float((ranked["above_sma50_5d_ago"].mean()) * 100.0)
    breadth_5d_change = round(market_breadth_pct - breadth_5d_ago_pct, 2)

    bm_sma_20 = float(market_benchmark.rolling(20).mean().iloc[-1])
    bm_mrs = float(((float(market_benchmark.iloc[-1]) / (bm_sma_20 + 1e-5)) - 1.0) * 100.0)

    return sector_summary, ranked, market_breadth_pct, breadth_5d_change, bm_mrs


def select_dynamic_portfolio(ranked_at_q: pd.DataFrame, sector_summary: pd.DataFrame, breadth: float, breadth_5d_change: float, bm_mrs: float):
    active_rot = len(sector_summary[(sector_summary["stock_count"] >= 3) & (sector_summary["sector_lifecycle"].str.contains("Rotation|Prime|Leadership"))])

    if breadth >= 52.0:
        regime = f"🟢 Bull Expansion ({breadth:.1f}% | 5D {breadth_5d_change:+.1f}%)"
        max_slots = 10
        q = {
            "score_high_rs_pullback": 4,
            "score_momentum_frontrunner": 4,
            "score_early_sector_rotation": 2 if active_rot > 0 else 0,
            "score_surety_anchor": 2,
        }
    elif breadth < 28.0 or breadth_5d_change <= -7.5:
        regime = f"⚡ Capitulation Spring ({breadth:.1f}% | 5D {breadth_5d_change:+.1f}%)"
        max_slots = 8
        q = {
            "score_high_rs_pullback": 5,
            "score_early_sector_rotation": 3 if active_rot > 0 else 0,
            "score_surety_anchor": 2,
            "score_momentum_frontrunner": 2,
        }
    elif breadth_5d_change >= 3.5:
        regime = f"🔄 Early Thrust ({breadth:.1f}% | 5D {breadth_5d_change:+.1f}%)"
        max_slots = 8
        q = {
            "score_early_sector_rotation": 4 if active_rot > 0 else 0,
            "score_high_rs_pullback": 4 + (4 if active_rot == 0 else 0),
            "score_momentum_frontrunner": 2,
            "score_surety_anchor": 2,
        }
    else:
        regime = f"🛑 Stagnant Chop Lockdown ({breadth:.1f}% | 5D {breadth_5d_change:+.1f}%)"
        max_slots = 4
        q = {
            "score_high_rs_pullback": 3,
            "score_surety_anchor": 2,
            "score_momentum_frontrunner": 1,
            "score_early_sector_rotation": 0,
        }

    picks, seen_sec, seen_sym = [], {}, set()
    min_rs_req = 84.0 if max_slots <= 4 else 78.0

    # Forensic Anti-Fizzle + Dual-RS Quality Gate
    quality_gate = (
        (ranked_at_q["close"] >= ranked_at_q["sma_200"]) &
        (ranked_at_q["close"] >= ranked_at_q["volume_profile_poc"] * 0.99) &
        (~ranked_at_q["mcap_tier"].str.contains("Tier 1", na=False)) &
        (ranked_at_q["atr_pct"] >= 3.05) &
        (ranked_at_q["base_depth_pct"].between(14.5, 28.0)) &
        (ranked_at_q["rsi_14"] <= 63.0) &
        (ranked_at_q["up_down_vol_ratio"] >= 1.20) &
        (ranked_at_q["blended_rs_percentile"] >= min_rs_req) &
        (
            (~ranked_at_q["sector_lifecycle"].str.contains("Lagging|Decelerating", na=False)) |
            ((ranked_at_q["blended_rs_percentile"] >= 88.0) & (ranked_at_q["beta_neutral_mrs"] >= 3.5))
        )
    )

    for k, limit in q.items():
        if limit <= 0:
            continue
        sub = ranked_at_q[quality_gate].copy()
        if k == "score_surety_anchor":
            mask = (sub["close"] >= sub["sma_50"] * 0.985) & (sub["mrs_score"].between(-4.0, 4.0))
        elif k == "score_momentum_frontrunner":
            mask = (sub["stage2_aligned"]) & (sub["mrs_score"].between(-1.5, 5.0))
        elif k == "score_early_sector_rotation":
            sub = sub[sub["sector_lifecycle"].str.contains("Rotation|Prime|Leadership", na=False)]
            mask = (sub["beta_neutral_mrs"] >= 1.0)
        elif k == "score_high_rs_pullback":
            mask = (sub["close"] >= sub["sma_50"] * 0.985) & (sub["mrs_score"].between(-5.5, 1.8)) & (sub["stoch_k"] <= 68.0)
        else:
            mask = sub["close"] > 0

        qual = sub[mask].sort_values(by=[k, "blended_rs_percentile"], ascending=False)
        added = 0
        for _, r in qual.iterrows():
            if added >= limit or len(picks) >= max_slots:
                break
            sym, sec = r["symbol"], r["sector"]
            if sym in seen_sym:
                continue
            if seen_sec.get(sec, 0) < 2:
                r_copy = r.copy()
                r_copy["assigned_strategy"] = k
                picks.append(r_copy)
                seen_sym.add(sym)
                seen_sec[sec] = seen_sec.get(sec, 0) + 1
                added += 1

    if len(picks) < max_slots:
        backfill_pool = ranked_at_q[
            quality_gate & (~ranked_at_q["symbol"].isin(seen_sym))
        ].sort_values(by=["score_high_rs_pullback", "blended_rs_percentile"], ascending=False)

        for _, r in backfill_pool.iterrows():
            if len(picks) >= max_slots:
                break
            sym, sec = r["symbol"], r["sector"]
            if seen_sec.get(sec, 0) < 2:
                r_copy = r.copy()
                r_copy["assigned_strategy"] = "score_high_rs_pullback"
                picks.append(r_copy)
                seen_sym.add(sym)
                seen_sec[sec] = seen_sec.get(sec, 0) + 1

    df_picks = pd.DataFrame(picks).head(max_slots) if picks else ranked_at_q.head(0)
    top3 = sector_summary.sort_values("sector_composite_score", ascending=False).head(3).to_dict(orient="records")
    top5 = sector_summary.sort_values("sector_composite_score", ascending=False).head(5).to_dict(orient="records")

    return top3, top5, df_picks, regime


def select_top_stocks_for_model(
    model_name: str,
    ranked_at_q: pd.DataFrame,
    sector_summary: pd.DataFrame,
    target_count: int = 16,
) -> tuple:
    valid_secs = sector_summary[
        (sector_summary["stock_count"] >= 3)
        & (sector_summary["sector"] != "General Equities")
    ].copy()

    top_sectors_df = valid_secs.sort_values(by=["sector_composite_score", "rs_ratio"], ascending=False).head(5)
    top_3_sectors = top_sectors_df.head(3).to_dict(orient="records")
    top_5_sectors = top_sectors_df.head(5).to_dict(orient="records")

    # Apply Forensic Anti-Fizzle Gate across all 4 strategies
    quality_gate = (
        (ranked_at_q["close"] >= ranked_at_q["sma_200"]) &
        (ranked_at_q["close"] >= ranked_at_q["volume_profile_poc"] * 0.99) &
        (~ranked_at_q["mcap_tier"].str.contains("Tier 1", na=False)) &
        (ranked_at_q["atr_pct"] >= 3.05) &
        (ranked_at_q["base_depth_pct"].between(14.5, 28.0)) &
        (ranked_at_q["rsi_14"] <= 63.0) &
        (ranked_at_q["up_down_vol_ratio"] >= 1.18) &
        (ranked_at_q["blended_rs_percentile"] >= 75.0) &
        (~ranked_at_q["sector_lifecycle"].str.contains("Lagging|Decelerating", na=False))
    )

    pool = ranked_at_q[quality_gate].copy()
    close_s = pool["close"]
    s50_s = pool["sma_50"]
    mrs_s = pool["mrs_score"]
    stoch_s = pool["stoch_k"]

    if model_name == "score_surety_anchor":
        mask = (close_s >= s50_s * 0.985) & (mrs_s.between(-4.0, 4.5))
        qualified = pool[mask].sort_values(by=["score_surety_anchor", "iasis_score"], ascending=False)
    elif model_name == "score_momentum_frontrunner":
        mask = (close_s >= s50_s) & (pool["stage2_aligned"]) & (mrs_s.between(-1.5, 5.5))
        qualified = pool[mask].sort_values(by=["score_momentum_frontrunner", "blended_rs_percentile"], ascending=False)
    elif model_name == "score_early_sector_rotation":
        s_life_s = pool["sector_lifecycle"].astype(str)
        s_rs_s = pool["sector_rs_status"].astype(str)
        mask = (~s_rs_s.str.contains("Lagging") | ~s_life_s.str.contains("Lagging") | (pool["beta_neutral_mrs"] >= 1.0))
        qualified = pool[mask].sort_values(by=["score_early_sector_rotation", "iasis_score"], ascending=False)
    elif model_name == "score_high_rs_pullback":
        mask = (close_s >= s50_s * 0.985) & (mrs_s.between(-5.5, 2.0)) & (stoch_s <= 68.0)
        qualified = pool[mask].sort_values(by=["score_high_rs_pullback", "blended_rs_percentile"], ascending=False)
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

    selected = pd.DataFrame(capped_picks).head(target_count) if capped_picks else qualified.head(0)
    return top_3_sectors, top_5_sectors, selected


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
    invalidation_level = max(entry_price * 0.905, min(entry_price - (2.5 * atr_20), init_s50 * 0.970))

    zone_days = 0
    window_20 = min(20, len(fut_slice))
    for i in range(window_20):
        c_val = float(closes[i])
        s20_val = float(s20[i]) if not np.isnan(s20[i]) else c_val
        s50_val = float(s50[i]) if not np.isnan(s50[i]) else c_val
        mrs_i = ((c_val / (s20_val + 1e-5)) - 1.0) * 100.0
        if c_val >= invalidation_level and c_val >= s50_val * 0.975 and -5.0 <= mrs_i <= 6.0:
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


def find_technical_ignition_trigger(fut_slice: pd.DataFrame, poc_val: float, max_stalk_days: int = 18) -> int:
    """
    High-Win-Rate Technical Ignition Trigger (Synchronized with pipeline.py):
      1. Structural Floor: Close above 50-SMA and POC support.
      2. Tight Pre-Trigger Coil: Prior 2-day range or volume contraction before breakout.
      3. Multi-MA Alignment: Close >= 10-EMA and 20-SMA aligned.
      4. High Closing Range (CR >= 0.65) + Institutional RVOL / 20-SMA Support Reclaim.
    """
    n = min(len(fut_slice), max_stalk_days)
    if n < 3:
        return -1

    closes = fut_slice["close"].values.astype(float)
    opens = fut_slice["open"].values.astype(float)
    highs = fut_slice["high"].values.astype(float)
    lows = fut_slice["low"].values.astype(float)
    vols = fut_slice["volume"].values.astype(float)
    s20 = fut_slice["sma20_roll"].values.astype(float)
    s50 = fut_slice["sma50_roll"].values.astype(float)
    e10 = fut_slice["ema10_roll"].values.astype(float)
    v20 = fut_slice["vol20_roll"].values.astype(float)

    for i in range(2, n):
        c, o, h, l, v = closes[i], opens[i], highs[i], lows[i], vols[i]
        prev_c, prev_h, prev_l = closes[i - 1], highs[i - 1], lows[i - 1]
        s20_i = s20[i] if not np.isnan(s20[i]) else c
        s50_i = s50[i] if not np.isnan(s50[i]) else c * 0.95
        e10_i = e10[i] if not np.isnan(e10[i]) else c
        v20_i = max(1.0, v20[i]) if not np.isnan(v20[i]) else max(1.0, v)

        if c < s50_i * 0.985 or c < poc_val * 0.99:
            continue

        dist_from_20 = (c - s20_i) / (s20_i + 1e-5)
        if dist_from_20 > 0.040:
            continue

        cr = (c - l) / (h - l + 1e-5)
        rvol = v / v20_i

        prior_range_pct = (max(highs[max(0, i - 2):i]) - min(lows[max(0, i - 2):i])) / (prev_c + 1e-5)
        prior_vol_quiet = (vols[i - 1] <= v20_i * 1.08) or (prior_range_pct <= 0.060)

        is_ignition = bool(
            prior_vol_quiet and
            (c > o) and (c >= prev_h) and
            (c >= e10_i) and (e10_i >= s50_i * 0.99) and
            (c >= s20_i * 0.995) and
            (cr >= 0.65) and (rvol >= 1.25)
        )

        tested_support = bool(
            (prev_l <= s20_i * 1.012) or (l <= s20_i * 1.012) or
            (prev_l <= e10_i * 1.008) or (l <= poc_val * 1.010)
        )
        is_reclaim = bool(
            tested_support and (c > o) and (c >= prev_c * 1.008) and
            (c >= e10_i * 0.995) and (cr >= 0.65) and (c >= s50_i * 0.990)
        )

        if is_ignition or is_reclaim:
            return i

    return -1


def simulate_method2_execution(
    fut_slice: pd.DataFrame,
    entry_price: float,
    entry_bar_idx: int = 0,
    mcap_tier: str = "Tier 2: Mid Cap",
    is_tier1: bool = False,
    structural_stop: float = None,
) -> dict:
    """
    Fast-Recycling 3-Tranche Runup Harvester (Synchronized with pipeline.py):
      - Pre-Target Shield: At +4.5% gain (+4.0% T1), activates Breakeven+ Shield (+1.0% / +0.8% T1).
        Only exits on shield if price falls back AND closes below the 10-Day EMA.
      - Tranche 1 (34%): Harvested at +10.0% (+8.0% T1) -> Locks trade as a winner.
      - Tranche 2 (33%): Harvested at +20.0% (+15.0% T1) or trails 20-Day SMA / 2.5x ATR Chandelier.
      - Tranche 3 (33%): Harvested at +32.0% (+24.0% T1) or trails 20-Day SMA / 2.8x ATR Chandelier
        (keeps holding duration ~20-23 days so capital recycles fast while capturing big trends).
    """
    if is_tier1 or "Tier 1" in mcap_tier:
        t1_target_pct = 8.0
        t2_target_pct = 15.0
        t3_climax_pct = 24.0
        risk_clamp_pct = -5.0
        shield_trig, shield_lock = 4.0, 0.8
    else:
        t1_target_pct = 10.0
        t2_target_pct = 20.0
        t3_climax_pct = 32.0
        risk_clamp_pct = -6.5
        shield_trig, shield_lock = 4.5, 1.0

    t1_price = round(entry_price * (1.0 + (t1_target_pct / 100.0)), 2)
    t2_price = round(entry_price * (1.0 + (t2_target_pct / 100.0)), 2)
    t3_price = round(entry_price * (1.0 + (t3_climax_pct / 100.0)), 2)
    risk_clamp_price = round(entry_price * (1.0 + (risk_clamp_pct / 100.0)), 2)
    base_stop = structural_stop if (structural_stop and structural_stop > 0) else risk_clamp_price
    effective_stop = min(base_stop, round(entry_price * (0.945 if is_tier1 else 0.920), 2))

    if fut_slice.empty or len(fut_slice) < 2:
        return {
            "is_win": False,
            "exit_date": str(fut_slice["date"].iloc[-1]) if not fut_slice.empty else None,
            "exit_price": entry_price,
            "days_to_exit": 1,
            "realized_return_pct": 0.0,
            "trade_pnl_inr": 0.0,
            "exit_reason": "Insufficient Data",
            "target_price": t1_price,
            "stop_price": risk_clamp_price,
            "target_pct": t1_target_pct,
            "stop_pct": risk_clamp_pct,
        }

    start_idx = max(0, min(entry_bar_idx, len(fut_slice) - 2))
    sim_slice = fut_slice.iloc[start_idx:].reset_index(drop=True)

    dates = sim_slice["date"].values
    highs = sim_slice["high"].values.astype(float)
    lows = sim_slice["low"].values.astype(float)
    closes = sim_slice["close"].values.astype(float)
    ema10_arr = sim_slice["ema10_roll"].values.astype(float) if "ema10_roll" in sim_slice.columns else closes
    sma20_arr = sim_slice["sma20_roll"].values.astype(float) if "sma20_roll" in sim_slice.columns else closes * 0.96

    # Approximate ATR from rolling high-low range
    tr_approx = highs - lows
    atr_arr = pd.Series(tr_approx).rolling(14, min_periods=1).mean().values

    position_capital = 100000.0

    exit_idx = len(sim_slice) - 1
    exit_date = str(dates[-1])
    exit_price = float(closes[-1])
    realized_ret = 0.0
    is_win = False
    exit_reason = "Open at Horizon End"

    running_peak = entry_price
    highest_close = entry_price
    shield_active = False
    t1_booked = False
    t2_booked = False
    t1_ret = 0.0
    t2_ret = 0.0
    t3_ret = 0.0
    consecutive_stop_closes = 0

    for idx in range(1, len(sim_slice)):
        d_str = str(dates[idx])
        h_val = float(highs[idx])
        c_val = float(closes[idx])
        e10_val = float(ema10_arr[idx]) if not np.isnan(ema10_arr[idx]) else c_val
        s20_val = float(sma20_arr[idx]) if not np.isnan(sma20_arr[idx]) else c_val * 0.96
        atr_val = float(atr_arr[idx]) if not np.isnan(atr_arr[idx]) else entry_price * 0.03

        if h_val > running_peak:
            running_peak = h_val
        if c_val > highest_close:
            highest_close = c_val

        peak_gain_now = ((running_peak - entry_price) / entry_price) * 100.0
        close_gain_now = ((c_val - entry_price) / entry_price) * 100.0

        # PHASE 1: BEFORE TRANCHE 1 (+10%) IS HIT
        if not t1_booked:
            if h_val >= t1_price:
                t1_booked = True
                t1_ret = t1_target_pct
                if h_val >= t2_price:
                    t2_booked = True
                    t2_ret = t2_target_pct
                if h_val >= t3_price:
                    t3_ret = t3_climax_pct
                    realized_ret = round((0.34 * t1_ret) + (0.33 * t2_ret) + (0.33 * t3_ret), 2)
                    exit_idx = idx
                    exit_date = d_str
                    exit_price = round(entry_price * (1.0 + (realized_ret / 100.0)), 2)
                    is_win = True
                    exit_reason = f"Full 3-Tranche Harvest (+{realized_ret:.1f}%)"
                    break
                continue

            if peak_gain_now >= shield_trig:
                shield_active = True

            if shield_active:
                shield_price = round(entry_price * (1.0 + (shield_lock / 100.0)), 2)
                if c_val <= shield_price and c_val < e10_val:
                    exit_idx = idx
                    exit_date = d_str
                    exit_price = shield_price
                    realized_ret = round(shield_lock, 2)
                    is_win = True
                    exit_reason = f"Breakeven Shield (+{shield_lock}%)"
                    break

            if c_val < effective_stop:
                consecutive_stop_closes += 1
                if consecutive_stop_closes >= 2 or c_val < entry_price * 0.89:
                    exit_idx = idx
                    exit_date = d_str
                    realized_ret = round(risk_clamp_pct, 2)
                    exit_price = round(entry_price * (1.0 + (risk_clamp_pct / 100.0)), 2)
                    is_win = False
                    exit_reason = f"Stop Loss ({risk_clamp_pct}%)"
                    break
            else:
                consecutive_stop_closes = 0

        # PHASE 2: TRANCHE 1 (+10%) BANKED -> MANAGE T2 (+20%) & T3 (+32% / 20-SMA TRAIL)
        else:
            if not t2_booked and h_val >= t2_price:
                t2_booked = True
                t2_ret = t2_target_pct

            if h_val >= t3_price:
                if not t2_booked:
                    t2_booked = True
                    t2_ret = t2_target_pct
                t3_ret = t3_climax_pct
                realized_ret = round((0.34 * t1_ret) + (0.33 * t2_ret) + (0.33 * t3_ret), 2)
                exit_idx = idx
                exit_date = d_str
                exit_price = round(entry_price * (1.0 + (realized_ret / 100.0)), 2)
                is_win = True
                exit_reason = f"3-Tranche Climax Harvest (+{realized_ret:.1f}%)"
                break

            if not t2_booked:
                t2_floor_price = entry_price * 1.025
                t2_trail_stop = max(t2_floor_price, s20_val * 0.985, highest_close - (2.5 * atr_val))
                if c_val < t2_trail_stop:
                    t2_booked = True
                    t2_ret = max(2.5, close_gain_now)

            # Trail T3 on MAX of 20-SMA, 2.8x ATR Chandelier, or locked floor (fast capital recycling)
            t3_locked_pct = 12.0 if peak_gain_now >= 22.0 else (6.0 if peak_gain_now >= 15.0 else 2.0)
            t3_floor_price = entry_price * (1.0 + (t3_locked_pct / 100.0))
            t3_trail_stop = max(t3_floor_price, s20_val * 0.985, highest_close - (2.8 * atr_val))

            if c_val < t3_trail_stop:
                t3_ret = max(t3_locked_pct, close_gain_now)
                if not t2_booked:
                    t2_booked = True
                    t2_ret = max(2.5, close_gain_now)
                realized_ret = round((0.34 * t1_ret) + (0.33 * t2_ret) + (0.33 * t3_ret), 2)
                exit_idx = idx
                exit_date = d_str
                exit_price = round(entry_price * (1.0 + (realized_ret / 100.0)), 2)
                is_win = True
                exit_reason = f"20-SMA Trend Runner (+{realized_ret:.1f}% Blended)"
                break

    if exit_reason == "Open at Horizon End":
        close_gain_end = ((float(closes[-1]) - entry_price) / entry_price) * 100.0
        if t1_booked:
            final_t2 = t2_ret if t2_booked else max(2.5, close_gain_end)
            final_t3 = max(2.0, close_gain_end)
            realized_ret = round((0.34 * t1_ret) + (0.33 * final_t2) + (0.33 * final_t3), 2)
            is_win = True
            exit_reason = f"Open Trend Runner (+{realized_ret:.1f}% Blended)"
        elif shield_active and close_gain_end > 0:
            realized_ret = round(max(shield_lock, close_gain_end), 2)
            is_win = True
            exit_reason = f"Open (Shield Protected +{realized_ret:.1f}%)"
        else:
            realized_ret = round(max(risk_clamp_pct, close_gain_end), 2)
            is_win = bool(realized_ret > 0.0)

    trade_pnl_inr = round((realized_ret / 100.0) * position_capital, 2)

    return {
        "is_win": is_win,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "days_to_exit": max(1, int(exit_idx)),
        "realized_return_pct": realized_ret,
        "trade_pnl_inr": trade_pnl_inr,
        "exit_reason": exit_reason,
        "target_price": t1_price,
        "stop_price": risk_clamp_price,
        "target_pct": t1_target_pct,
        "stop_pct": risk_clamp_pct,
    }


def compute_daily_progress_metrics(all_csv_rows: list, all_dates: list, model_key: str = "dynamic_regime_portfolio") -> tuple:
    """
    Constructs a day-by-day equity curve & tracking log across all 2026 trading sessions
    for the specified strategy model (default: dynamic_regime_portfolio):
      - active_open_positions: Count of live open trades on that EOD date
      - entries_today / exits_today: Daily trade turnover
      - daily_realized_pnl_inr: Closed trade P&L booked on that date
      - cumulative_pnl_inr / cumulative_roc_pct: Running equity curve & Return on Capital
      - running_win_rate_pct: Cumulative win rate as of that date
      - drawdown_from_peak_pct: Running peak-to-trough drawdown %
    """
    scan_dates = [d for d in all_dates if d >= "2026-01-01"]
    model_trades = [r for r in all_csv_rows if r.get("strategy_model") == model_key]

    if not scan_dates or not model_trades:
        return [], {
            "total_trading_days": len(scan_dates),
            "peak_concurrent_positions": 0,
            "avg_concurrent_positions": 0.0,
            "cumulative_net_profit_inr": 0.0,
            "max_equity_drawdown_pct": 0.0,
            "profitable_days_ratio_pct": 0.0,
        }

    t_df = pd.DataFrame(model_trades)
    reference_capital = 800000.0  # ₹8 Lakh reference 8-slot book
    cum_pnl = 0.0
    cum_wins = 0
    cum_closed = 0
    peak_equity = reference_capital
    max_dd_pct = 0.0

    daily_series = []
    open_counts = []
    positive_pnl_days = 0
    active_exit_days = 0

    for d in scan_dates:
        entries_today = int((t_df["signal_date"] == d).sum())
        exits_df = t_df[t_df["exit_date"] == d]
        exits_today = int(len(exits_df))

        # Active open positions on date d: entered <= d and exit_date > d
        open_now = int(((t_df["signal_date"] <= d) & (t_df["exit_date"] > d)).sum())
        open_counts.append(open_now)

        day_pnl = float(exits_df["method2_pnl_inr"].sum()) if exits_today > 0 else 0.0
        day_wins = int(exits_df["is_method2_win"].sum()) if exits_today > 0 else 0

        if exits_today > 0:
            active_exit_days += 1
            if day_pnl > 0:
                positive_pnl_days += 1

        cum_pnl += day_pnl
        cum_closed += exits_today
        cum_wins += day_wins

        current_equity = reference_capital + cum_pnl
        if current_equity > peak_equity:
            peak_equity = current_equity
        dd_now = ((current_equity - peak_equity) / peak_equity) * 100.0
        if dd_now < max_dd_pct:
            max_dd_pct = dd_now

        running_wr = round((cum_wins / cum_closed) * 100.0, 1) if cum_closed > 0 else 0.0
        cum_roc_pct = round((cum_pnl / reference_capital) * 100.0, 2)

        daily_series.append({
            "date": str(d),
            "active_open_positions": open_now,
            "entries_today": entries_today,
            "exits_today": exits_today,
            "daily_realized_pnl_inr": round(day_pnl, 2),
            "cumulative_pnl_inr": round(cum_pnl, 2),
            "cumulative_roc_pct": cum_roc_pct,
            "closed_trades_to_date": cum_closed,
            "running_win_rate_pct": running_wr,
            "drawdown_from_peak_pct": round(dd_now, 2),
        })

    summary = {
        "reference_capital_inr": reference_capital,
        "total_trading_days": len(scan_dates),
        "peak_concurrent_positions": int(max(open_counts)) if open_counts else 0,
        "avg_concurrent_positions": round(float(np.mean(open_counts)), 1) if open_counts else 0.0,
        "cumulative_net_profit_inr": round(cum_pnl, 2),
        "cumulative_roc_pct": round((cum_pnl / reference_capital) * 100.0, 2),
        "max_equity_drawdown_pct": round(max_dd_pct, 2),
        "profitable_exit_days_pct": round((positive_pnl_days / max(1, active_exit_days)) * 100.0, 1),
    }

    return daily_series, summary


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
            end_p = float(fut["close"].iloc[-1])

            eval_window = fut.iloc[:min(35, len(fut))]
            lw_p = float(eval_window["low"].min())

            mfe = ((pk_p - entry_p) / entry_p) * 100.0
            act_dd = ((lw_p - entry_p) / entry_p) * 100.0
            ret = ((end_p - entry_p) / entry_p) * 100.0
            window_buckets[b_key].append((mfe, act_dd, ret))

    audit_summary = []
    for w_name, items in window_buckets.items():
        if not items:
            continue
        mfes = np.array([x[0] for x in items])
        act_dds = np.array([x[1] for x in items])
        rets = np.array([x[2] for x in items])
        audit_summary.append({
            "window": w_name,
            "sample_signals": len(items),
            "avg_peak_mfe_pct": round(float(np.mean(mfes)), 2),
            "hit_15pct_rate": round(float((mfes >= 15.0).mean() * 100.0), 1),
            "low_drawdown_surety_rate": round(float((act_dds >= -6.0).mean() * 100.0), 1),
            "low_mae_surety_rate": round(float((act_dds >= -6.0).mean() * 100.0), 1),
            "avg_active_drawdown_pct": round(float(np.mean(act_dds)), 2),
            "avg_mae_pct": round(float(np.mean(act_dds)), 2),
            "avg_period_ret_pct": round(float(np.mean(rets)), 2),
            "asymmetry_ratio": round(float(np.mean(mfes) / max(1.0, abs(np.mean(act_dds)))), 2),
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

    MODELS = [
        ("dynamic_regime_portfolio", "⚡ Dynamic Regime-Gated Portfolio (Top 12)"),
        ("score_surety_anchor", "🛡️ Strategy 1: High-Surety Institutional Anchor"),
        ("score_momentum_frontrunner", "🚀 Strategy 2: Momentum Frontrunner"),
        ("score_early_sector_rotation", "🔄 Strategy 3: Early Sector Rotation Leader"),
        ("score_high_rs_pullback", "📉 Strategy 4: High-RS Pullback Structure"),
    ]

    months_payload = []
    all_csv_rows = []

    model_stats_accumulator = {
        m_key: {
            "trades": 0, "wins": 0, "total_m2_return": 0.0, "total_m2_profit_inr": 0.0,
            "total_mfe": 0.0, "total_mfe_30d": 0.0, "total_mfe_60d": 0.0,
            "hits_15": 0, "hits_20": 0, "low_drawdown_count": 0, "total_active_drawdown": 0.0,
            "total_zone_persist": 0.0, "total_trend_persist": 0.0,
            "total_days_to_peak": 0.0, "total_days_to_exit": 0.0,
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

    print("\n" + "=" * 168)
    print("RUNNING INSTITUTIONAL BACKTEST: 3-TRANCHE RUNUP HARVESTER & ANTI-FIZZLE ENGINE")
    print(f"Point-in-Time Monthly Cohorts | Evaluated to: {latest_date_overall}")
    print("=" * 168)

    for m_info in monthly_checkpoints:
        m_label = m_info["label"]
        m_start_date = m_info["date"]
        print(f"[*] Auditing Month: {m_label} (Stalking Date: {m_start_date})...")

        sector_summary, ranked_at_m, market_breadth_pct, breadth_5d_change, bm_mrs = evaluate_point_in_time(df_all, m_start_date)

        u_start = df_all[df_all["date"] == m_start_date]["close"].mean()
        u_end = df_all[df_all["date"] == latest_date_overall]["close"].mean()
        universe_ret = round(float(((u_end - u_start) / (u_start + 1e-5)) * 100.0), 2)

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
            fut_act_p = fut_p.iloc[:min(45, len(fut_p))]
            lw_p = float(fut_act_p["low"].min())
            end_p = float(fut_p["close"].iloc[-1])
            mfe_v = ((pk_p - e_p) / e_p) * 100.0
            act_dd_v = ((lw_p - e_p) / e_p) * 100.0
            ret_v = ((end_p - e_p) / e_p) * 100.0

            pat_name = str(stk.get("chart_pattern_signal", "")).strip()
            poc_floor = bool(stk.get("poc_floor_support", False))
            is_leading_sec = str(stk.get("sector_rs_status", "")) != "🔴 Lagging Sector"

            advanced_factors_accumulator["1. Base Universe Stage-2 Setups"].append((mfe_v, act_dd_v, ret_v))
            if poc_floor:
                advanced_factors_accumulator["2. AVWAP Defense (Close >= 100D MaxVol VWAP)"].append((mfe_v, act_dd_v, ret_v))
            if float(stk.get("deliv_pct", 0.0)) >= 45.0:
                advanced_factors_accumulator["3. High Closing Range Accumulation (CR >= 0.55)"].append((mfe_v, act_dd_v, ret_v))
            if float(stk.get("vcp_ratio", 1.0)) <= 0.65:
                advanced_factors_accumulator["4. Volatility Compression Black Hole (ATR5/ATR50 <= 0.50)"].append((mfe_v, act_dd_v, ret_v))
            if poc_floor and float(stk.get("deliv_pct", 0.0)) >= 45.0:
                advanced_factors_accumulator["5. Combined Institutional Alpha (AVWAP + CR + POC Support)"].append((mfe_v, act_dd_v, ret_v))

            pattern_confluence_accumulator["Cohort 1: Baseline Setups (No Pattern Required)"].append((mfe_v, act_dd_v, ret_v))
            if pat_name:
                pattern_confluence_accumulator["Cohort 2: Standalone Pattern (Geometric Detection Only)"].append((mfe_v, act_dd_v, ret_v))
                if "VCP" in pat_name:
                    pattern_confluence_accumulator["Pattern Breakdown: 🎯 VCP Coiled Spring"].append((mfe_v, act_dd_v, ret_v))
                elif "Flag" in pat_name:
                    pattern_confluence_accumulator["Pattern Breakdown: 🚩 Bull Flag & Pole"].append((mfe_v, act_dd_v, ret_v))
                elif "Multi-Month" in pat_name:
                    pattern_confluence_accumulator["Pattern Breakdown: 🟢 Multi-Month Base"].append((mfe_v, act_dd_v, ret_v))
                elif "Macro" in pat_name:
                    pattern_confluence_accumulator["Pattern Breakdown: ⚡ Stage 2 Macro Base"].append((mfe_v, act_dd_v, ret_v))

            if pat_name and poc_floor and is_leading_sec:
                pattern_confluence_accumulator["Cohort 3: Pattern + Full Institutional Confluence (POC Floor + Flow)"].append((mfe_v, act_dd_v, ret_v))

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
            f_act = f_sl.iloc[:min(45, len(f_sl))]
            lw = float(f_act["low"].min())
            td_p = float(f_sl["close"].iloc[-1])
            mfe_r = ((pk - ep) / ep) * 100.0
            act_dd_r = ((lw - ep) / ep) * 100.0
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
            sector_lifecycle_accumulator[life_bucket].append((mfe_r, act_dd_r, ret_r))

        month_modes_output = {}

        for m_key, m_desc in MODELS:
            if m_key == "dynamic_regime_portfolio":
                top_3_sectors, top_5_sectors, top_stocks, regime_desc = select_dynamic_portfolio(
                    ranked_at_m, sector_summary, market_breadth_pct, breadth_5d_change, bm_mrs
                )
            else:
                top_3_sectors, top_5_sectors, top_stocks = select_top_stocks_for_model(
                    m_key, ranked_at_m, sector_summary, target_count=16
                )
                regime_desc = "Fixed Strategy Evaluation"

            stock_records = []
            for rank_idx, (_, stk_row) in enumerate(top_stocks.iterrows(), start=1):
                sym = str(stk_row["symbol"])
                sym_df = symbol_groups.get(sym, pd.DataFrame())

                base_close = round(float(stk_row["close"]), 2)
                atr_20_val = float(stk_row["atr_20"])
                atr_stop = round(float(stk_row["atr_stop_loss"]), 2)
                mcap_tier = str(stk_row.get("mcap_tier", "Tier 2: Mid Cap"))
                is_tier1 = "Tier 1" in mcap_tier
                sec_life = str(stk_row.get("sector_lifecycle", "🟢 Prime Institutional Leadership"))
                sec_mult = float(stk_row.get("sector_climax_mult", 1.0))
                surety_val = float(stk_row.get("score_surety_anchor", 50.0))
                poc_val = float(stk_row.get("volume_profile_poc", base_close))
                poc_floor = bool(stk_row.get("poc_floor_support", base_close >= poc_val))

                fut_slice = sym_df[sym_df["date"] >= m_start_date].reset_index(drop=True)
                if not fut_slice.empty:
                    entry_bar_idx = find_technical_ignition_trigger(fut_slice, poc_val, max_stalk_days=18)
                    if entry_bar_idx == -1:
                        continue

                    actual_entry_row = fut_slice.iloc[entry_bar_idx]
                    actual_entry_date = str(actual_entry_row["date"])
                    actual_entry_price = round(float(actual_entry_row["close"]), 2)
                    adj_stop_loss = round(max(actual_entry_price * (0.935 if is_tier1 else 0.885), atr_stop), 2)

                    trade_slice = fut_slice.iloc[entry_bar_idx:].reset_index(drop=True)
                    max_pos = int(trade_slice["high"].values.argmax())
                    peak_row = trade_slice.iloc[max_pos]
                    peak_high = round(float(peak_row["high"]), 2)
                    days_to_peak = max(1, max_pos)
                    peak_gain_pct = round(((peak_high - actual_entry_price) / actual_entry_price) * 100.0, 2)

                    slice_30d = trade_slice.iloc[: min(31, len(trade_slice))]
                    mfe_30d_pct = round(((float(slice_30d["high"].max()) - actual_entry_price) / actual_entry_price) * 100.0, 2)

                    slice_60d = trade_slice.iloc[: min(61, len(trade_slice))]
                    mfe_60d_pct = round(((float(slice_60d["high"].max()) - actual_entry_price) / actual_entry_price) * 100.0, 2)

                    trade_sim = simulate_method2_execution(
                        fut_slice=fut_slice,
                        entry_price=actual_entry_price,
                        entry_bar_idx=entry_bar_idx,
                        mcap_tier=mcap_tier,
                        is_tier1=is_tier1,
                        structural_stop=adj_stop_loss,
                    )

                    is_m2_win = trade_sim["is_win"]
                    days_to_exit = trade_sim["days_to_exit"]
                    exit_date_str = trade_sim["exit_date"]
                    exit_price_val = trade_sim["exit_price"]
                    m2_return_pct = trade_sim["realized_return_pct"]
                    m2_pnl_inr = trade_sim["trade_pnl_inr"]
                    exit_reason = trade_sim["exit_reason"]
                    target_price_val = trade_sim["target_price"]
                    stop_price_val = trade_sim["stop_price"]

                    active_holding_len = max(1, min(len(trade_slice), days_to_exit + 1))
                    active_slice = trade_slice.iloc[:active_holding_len]

                    min_pos = int(active_slice["low"].values.argmin())
                    low_row = active_slice.iloc[min_pos]
                    min_low_active = round(float(low_row["low"]), 2)
                    active_drawdown_pct = round(((min_low_active - actual_entry_price) / actual_entry_price) * 100.0, 2)

                    persist_sim = simulate_signal_persistence(trade_slice, actual_entry_price, atr_20_val)

                else:
                    actual_entry_price, actual_entry_date = base_close, m_start_date
                    peak_high, days_to_peak, peak_gain_pct = actual_entry_price, 1, 0.0
                    mfe_30d_pct, mfe_60d_pct = 0.0, 0.0
                    min_low_active, active_drawdown_pct = actual_entry_price, 0.0
                    days_to_exit = 1
                    exit_date_str, exit_price_val = m_start_date, actual_entry_price
                    persist_sim = {
                        "zone_persistence_days": 1,
                        "trend_persistence_days": 1,
                        "active_5d": True,
                        "active_10d": True,
                    }
                    is_m2_win = False
                    m2_return_pct = 0.0
                    m2_pnl_inr = 0.0
                    exit_reason = "No Data"
                    target_price_val = round(actual_entry_price * 1.10, 2)
                    stop_price_val = round(actual_entry_price * 0.935, 2)

                base_pattern = str(stk_row.get("chart_pattern_signal", ""))
                adj_days_to_exit = round(float(days_to_exit) * 1.25, 1)

                stock_record = {
                    "rank": rank_idx,
                    "symbol": sym,
                    "company_name": str(stk_row.get("company_name", sym)),
                    "sector": str(stk_row.get("sector", "Capital Goods")),
                    "index_name": str(stk_row.get("index_name", "Nifty 500")),
                    "mcap_tier": mcap_tier,
                    "risk_suitability": str(stk_row.get("risk_suitability", "Medium")),
                    "inst_signal_at_entry": str(stk_row.get("inst_signal", "Consolidation")),
                    "chart_pattern_at_entry": base_pattern,
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
                    "entry_date": actual_entry_date,
                    "entry_price": actual_entry_price,
                    "target_price": target_price_val,
                    "stop_price": stop_price_val,
                    "exit_date": exit_date_str,
                    "exit_price": exit_price_val,
                    "exit_reason": exit_reason,
                    "raw_days_to_exit": days_to_exit,
                    "adjusted_days_to_exit": adj_days_to_exit,
                    "is_method2_win": is_m2_win,
                    "method2_return_pct": m2_return_pct,
                    "method2_pnl_inr": m2_pnl_inr,
                    "max_gain_mfe_pct": peak_gain_pct,
                    "mfe_30d_pct": mfe_30d_pct,
                    "mfe_60d_pct": mfe_60d_pct,
                    "days_to_peak": days_to_peak,
                    "min_low_in_trade": min_low_active,
                    "active_trade_drawdown_pct": active_drawdown_pct,
                }
                stock_records.append(stock_record)

                if m_key == "score_surety_anchor":
                    if mcap_tier not in mcap_stats_accumulator:
                        mcap_stats_accumulator[mcap_tier] = []
                    mcap_stats_accumulator[mcap_tier].append({
                        "mfe": peak_gain_pct,
                        "drawdown": active_drawdown_pct,
                        "ret": m2_return_pct,
                        "win": is_m2_win,
                    })

                all_csv_rows.append({
                    "strategy_model": m_key,
                    "signal_month": m_label,
                    "signal_date": actual_entry_date,
                    "rank": rank_idx,
                    "symbol": sym,
                    "company_name": stock_record["company_name"],
                    "sector": stock_record["sector"],
                    "mcap_tier": mcap_tier,
                    "sector_lifecycle": sec_life,
                    "signal_at_entry": stock_record["inst_signal_at_entry"],
                    "pattern": base_pattern,
                    "entry_price": actual_entry_price,
                    "target_price": target_price_val,
                    "stop_price": stop_price_val,
                    "exit_date": exit_date_str,
                    "exit_price": exit_price_val,
                    "exit_reason": exit_reason,
                    "days_to_exit": days_to_exit,
                    "adjusted_days_to_exit": adj_days_to_exit,
                    "is_method2_win": is_m2_win,
                    "realized_return_pct": m2_return_pct,
                    "method2_pnl_inr": m2_pnl_inr,
                    "max_gain_mfe_pct": peak_gain_pct,
                    "mfe_30d_pct": mfe_30d_pct,
                    "mfe_60d_pct": mfe_60d_pct,
                    "days_to_peak": days_to_peak,
                    "active_trade_drawdown_pct": active_drawdown_pct,
                })

            m2_rets = [s["method2_return_pct"] for s in stock_records]
            mfes = [s["max_gain_mfe_pct"] for s in stock_records]
            mfes_30 = [s["mfe_30d_pct"] for s in stock_records]
            mfes_60 = [s["mfe_60d_pct"] for s in stock_records]
            act_dds = [s["active_trade_drawdown_pct"] for s in stock_records]
            z_pers = [s["zone_persistence_days"] for s in stock_records]
            t_pers = [s["trend_persistence_days"] for s in stock_records]
            pk_days = [s["days_to_peak"] for s in stock_records]
            ex_days = [s["raw_days_to_exit"] for s in stock_records]

            avg_m2_ret = round(float(np.mean(m2_rets)), 2) if m2_rets else 0.0
            m2_wins_m = sum(1 for s in stock_records if s["is_method2_win"])
            win_rate = round((m2_wins_m / max(1, len(stock_records))) * 100.0, 1)

            avg_mfe = round(float(np.mean(mfes)), 2) if mfes else 0.0
            avg_mfe_30 = round(float(np.mean(mfes_30)), 2) if mfes_30 else 0.0
            avg_mfe_60 = round(float(np.mean(mfes_60)), 2) if mfes_60 else 0.0
            hit_15 = round(float((np.array(mfes) >= 15.0).mean() * 100.0), 1) if mfes else 0.0
            hit_20 = round(float((np.array(mfes) >= 20.0).mean() * 100.0), 1) if mfes else 0.0
            avg_act_dd = round(float(np.mean(act_dds)), 2) if act_dds else 0.0
            avg_pk_d = round(float(np.mean(pk_days)), 1) if pk_days else 1.0
            avg_ex_d = round(float(np.mean(ex_days)), 1) if ex_days else 1.0
            avg_adj_hold_d = round(avg_ex_d * 1.25, 1)

            acc = model_stats_accumulator[m_key]
            acc["trades"] += len(m2_rets)
            acc["wins"] += m2_wins_m
            acc["total_m2_return"] += float(np.sum(m2_rets))
            acc["total_m2_profit_inr"] += sum(s["method2_pnl_inr"] for s in stock_records)
            acc["total_mfe"] += float(np.sum(mfes))
            acc["total_mfe_30d"] += float(np.sum(mfes_30))
            acc["total_mfe_60d"] += float(np.sum(mfes_60))
            acc["hits_15"] += int((np.array(mfes) >= 15.0).sum())
            acc["hits_20"] += int((np.array(mfes) >= 20.0).sum())
            acc["low_drawdown_count"] += int((np.array(act_dds) >= -6.0).sum())
            acc["total_active_drawdown"] += float(np.sum(act_dds))
            acc["total_zone_persist"] += float(np.sum(z_pers))
            acc["total_trend_persist"] += float(np.sum(t_pers))
            acc["total_days_to_peak"] += float(np.sum(pk_days))
            acc["total_days_to_exit"] += float(np.sum(ex_days))

            month_modes_output[m_key] = {
                "model_key": m_key,
                "model_name": m_desc,
                "regime_detected": regime_desc,
                "picks_count": len(stock_records),
                "portfolio_win_rate_pct": win_rate,
                "portfolio_avg_return_pct": avg_m2_ret,
                "avg_peak_mfe_pct": avg_mfe,
                "avg_mfe_30d_pct": avg_mfe_30,
                "avg_mfe_60d_pct": avg_mfe_60,
                "hit_15pct_target_rate_pct": hit_15,
                "hit_20pct_target_rate_pct": hit_20,
                "avg_active_drawdown_pct": avg_act_dd,
                "avg_days_to_peak": avg_pk_d,
                "raw_trade_duration_days": avg_ex_d,
                "adjusted_trade_duration_days": avg_adj_hold_d,
                "universe_benchmark_return_pct": universe_ret,
                "alpha_vs_universe_pct": round(avg_m2_ret - universe_ret, 2),
                "top_3_sectors": top_3_sectors,
                "top_5_sectors": top_5_sectors,
                "picks": stock_records,
                "picks_9": stock_records[:20],
                "dynamic_picks_conservative": [s for s in stock_records if s.get("risk_suitability") == "Low"],
                "dynamic_picks_balanced": [s for s in stock_records if s.get("risk_suitability") == "Medium"],
                "dynamic_picks_aggressive": [s for s in stock_records if s.get("risk_suitability") == "High"],
            }

        primary_view = dict(month_modes_output["dynamic_regime_portfolio"])
        primary_view["quarter_label"] = m_label
        primary_view["start_date"] = m_start_date
        primary_view["universe_benchmark_ret_pct"] = universe_ret
        primary_view["modes"] = month_modes_output

        months_payload.append(primary_view)

    print("[*] Running Intra-Month Setup Timing Audit across 2026 sessions...")
    intramonth_audit = run_intramonth_timing_audit(symbol_groups, all_dates, latest_date_overall)

    print("[*] Computing Daily Progress & Tracking Equity Curve across 2026 sessions...")
    daily_progress_series, daily_progress_summary = compute_daily_progress_metrics(
        all_csv_rows, all_dates, model_key="dynamic_regime_portfolio"
    )

    mcap_summary_list = []
    for tier_label in sorted(mcap_stats_accumulator.keys()):
        t_items = mcap_stats_accumulator[tier_label]
        mfes_t = np.array([x["mfe"] for x in t_items])
        dds_t = np.array([x["drawdown"] for x in t_items])
        rets_t = np.array([x["ret"] for x in t_items])
        wins_t = [x["win"] for x in t_items]
        mcap_summary_list.append({
            "mcap_tier": tier_label, "count": len(t_items),
            "win_rate_pct": round((sum(wins_t) / max(1, len(wins_t))) * 100.0, 1),
            "avg_mfe_pct": round(float(np.mean(mfes_t)), 2),
            "hit_15pct_rate": round(float((mfes_t >= 15.0).mean() * 100.0), 1),
            "low_drawdown_surety_rate": round(float((dds_t >= -6.0).mean() * 100.0), 1),
            "avg_active_drawdown_pct": round(float(np.mean(dds_t)), 2),
            "avg_hold_ret_pct": round(float(np.mean(rets_t)), 2),
        })

    sector_climax_audit_list = []
    for life_key in sorted(sector_lifecycle_accumulator.keys()):
        l_items = sector_lifecycle_accumulator[life_key]
        mfes_l = np.array([x[0] for x in l_items])
        dds_l = np.array([x[1] for x in l_items])
        rets_l = np.array([x[2] for x in l_items])
        sector_climax_audit_list.append({
            "sector_stage": life_key, "sample_size": len(l_items),
            "avg_mfe_pct": round(float(np.mean(mfes_l)), 2),
            "hit_15pct_rate": round(float((mfes_l >= 15.0).mean() * 100.0), 1),
            "severe_trap_rate_dd_gt_15": round(float((dds_l <= -15.0).mean() * 100.0), 1),
            "avg_active_drawdown_pct": round(float(np.mean(dds_l)), 2),
            "avg_period_ret_pct": round(float(np.mean(rets_l)), 2),
        })

    pattern_audit_summary = []
    for cohort_label, records in pattern_confluence_accumulator.items():
        if not records:
            continue
        p_mfes, p_dds, p_rets = np.array([x[0] for x in records]), np.array([x[1] for x in records]), np.array([x[2] for x in records])
        pattern_audit_summary.append({
            "cohort": cohort_label, "sample_size": len(records),
            "avg_peak_mfe_pct": round(float(np.mean(p_mfes)), 2),
            "hit_15pct_rate": round(float((p_mfes >= 15.0).mean() * 100.0), 1),
            "low_drawdown_surety_rate": round(float((p_dds >= -6.0).mean() * 100.0), 1),
            "avg_active_drawdown_pct": round(float(np.mean(p_dds)), 2),
            "avg_hold_ret_pct": round(float(np.mean(p_rets)), 2),
            "asymmetry_ratio": round(float(np.mean(p_mfes) / max(1.0, abs(np.mean(p_dds)))), 2),
        })

    advanced_factors_summary = []
    for factor_label, records in advanced_factors_accumulator.items():
        if not records:
            continue
        f_mfes, f_dds, f_rets = np.array([x[0] for x in records]), np.array([x[1] for x in records]), np.array([x[2] for x in records])
        advanced_factors_summary.append({
            "factor": factor_label, "sample_size": len(records),
            "avg_peak_mfe_pct": round(float(np.mean(f_mfes)), 2),
            "hit_15pct_rate": round(float((f_mfes >= 15.0).mean() * 100.0), 1),
            "low_drawdown_surety_rate": round(float((f_dds >= -6.0).mean() * 100.0), 1),
            "avg_active_drawdown_pct": round(float(np.mean(f_dds)), 2),
            "avg_hold_ret_pct": round(float(np.mean(f_rets)), 2),
            "asymmetry_ratio": round(float(np.mean(f_mfes) / max(1.0, abs(np.mean(f_dds)))), 2),
        })

    pd.DataFrame(all_csv_rows).to_csv(BACKTEST_CSV, index=False)

    # =========================================================================
    # 3-TRANCHE RUNUP HARVESTER ROLLUP
    # =========================================================================
    strategy_macro_summary = {}
    active_sessions = 232.0

    for m_key, m_desc in MODELS:
        acc = model_stats_accumulator[m_key]
        n_tr = acc["trades"]

        if n_tr == 0:
            strategy_macro_summary[m_key] = {
                "strategy_key": m_key, "strategy_name": m_desc,
                "total_signals_tracked": 0, "win_rate_pct": 0.0,
                "net_expectancy_pct": 0.0, "profit_per_lakh_inr": 0.0,
                "annualized_xirr_pct": 0.0, "overall_avg_mfe_pct": 0.0,
                "overall_avg_active_drawdown_pct": 0.0, "hit_15pct_rate": 0.0,
                "hit_20pct_rate": 0.0, "trade_duration_days": 0.0,
                "annualized_turnover_velocity": 0.0,
            }
            continue

        wr = round((acc["wins"] / n_tr) * 100.0, 1)
        avg_mfe_val = round(acc["total_mfe"] / n_tr, 2)
        avg_act_dd = round(acc["total_active_drawdown"] / n_tr, 2)
        hit_15_rate = round((acc["hits_15"] / n_tr) * 100.0, 1)
        hit_20_rate = round((acc["hits_20"] / n_tr) * 100.0, 1)
        low_dd_rate = round((acc["low_drawdown_count"] / n_tr) * 100.0, 1)

        avg_pk_days = round(acc["total_days_to_peak"] / n_tr, 1)
        raw_hold_days = round(acc["total_days_to_exit"] / n_tr, 1)
        adj_hold_days = round(raw_hold_days * 1.25, 1)

        cycles_per_year = round(active_sessions / max(1.0, adj_hold_days), 1)

        net_roi = round(acc["total_m2_return"] / n_tr, 2)
        profit_per_lakh = round(acc["total_m2_profit_inr"] / n_tr, 2)
        roi_dec = net_roi / 100.0
        xirr = round(((1.0 + roi_dec) ** cycles_per_year - 1.0) * 100.0, 1) if (adj_hold_days > 0 and roi_dec > -1.0) else 0.0

        strategy_macro_summary[m_key] = {
            "strategy_key": m_key,
            "strategy_name": m_desc,
            "total_signals_tracked": n_tr,
            "win_rate_pct": wr,
            "net_expectancy_pct": net_roi,
            "profit_per_lakh_inr": profit_per_lakh,
            "annualized_xirr_pct": xirr,
            "overall_avg_mfe_pct": avg_mfe_val,
            "overall_avg_active_drawdown_pct": avg_act_dd,
            "hit_15pct_rate": hit_15_rate,
            "hit_20pct_rate": hit_20_rate,
            "low_drawdown_surety_rate": low_dd_rate,
            "avg_days_to_peak": avg_pk_days,
            "raw_trade_duration_days": raw_hold_days,
            "trade_duration_days": adj_hold_days,
            "annualized_turnover_velocity": cycles_per_year,
            "active_business_sessions_per_year": int(active_sessions),
            "execution_model": "Method 2.5: 3-Tranche Runup Harvester (+4.5% Shield | 34% @ +10% | 33% @ +20% | 33% @ +32%/20-SMA)",
        }

    dyn_acc = model_stats_accumulator["dynamic_regime_portfolio"]
    n_dyn = max(1, dyn_acc["trades"])

    global_macro_stats = {
        "total_audited_windows": len(monthly_checkpoints),
        "total_signals_tracked": dyn_acc["trades"],
        "win_rate_pct": strategy_macro_summary["dynamic_regime_portfolio"]["win_rate_pct"],
        "net_expectancy_pct": strategy_macro_summary["dynamic_regime_portfolio"]["net_expectancy_pct"],
        "profit_per_lakh_inr": strategy_macro_summary["dynamic_regime_portfolio"]["profit_per_lakh_inr"],
        "annualized_xirr_pct": strategy_macro_summary["dynamic_regime_portfolio"]["annualized_xirr_pct"],
        "overall_avg_mfe_pct": round(dyn_acc["total_mfe"] / n_dyn, 2),
        "overall_avg_active_drawdown_pct": round(dyn_acc["total_active_drawdown"] / n_dyn, 2),
        "hit_15pct_rate": round((dyn_acc["hits_15"] / n_dyn) * 100.0, 1),
        "hit_20pct_rate": round((dyn_acc["hits_20"] / n_dyn) * 100.0, 1),
        "annualized_turnover_velocity": strategy_macro_summary["dynamic_regime_portfolio"]["annualized_turnover_velocity"],
        "trade_duration_days": strategy_macro_summary["dynamic_regime_portfolio"]["trade_duration_days"],
        "active_business_sessions_per_year": 232,
        "daily_progress_summary": daily_progress_summary,
    }

    clean_checkpoints = [
        {"label": c["label"], "month_num": c["month_num"], "cal_date": c["cal_date"], "date": c["date"]}
        for c in monthly_checkpoints
    ]

    final_json = {
        "generated_at_eod": latest_date_overall,
        "corporate_actions_normalized_count": len(corp_action_events),
        "quarter_checkpoints": clean_checkpoints,
        "global_macro_summary": global_macro_stats,
        "strategies_summary": strategy_macro_summary,
        "daily_progress_summary": daily_progress_summary,
        "daily_progress_audit": daily_progress_series,
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
        "daily_progress_summary": daily_progress_summary,
        "mcap_tier_summary": mcap_summary_list,
        "sector_climax_audit": sector_climax_audit_list,
        "intramonth_timing_audit": intramonth_audit,
        "pattern_confluence_audit": pattern_audit_summary,
        "advanced_factors_audit": advanced_factors_summary,
    }

    with open(BACKTEST_SUMMARY_JSON, "w") as f:
        json.dump(compact_summary, f, indent=2)

    print("\n" + "=" * 148)
    print("3-TRANCHE RUNUP HARVESTER STRATEGY LEADERBOARD (UNIFORM REAL-DATA ACCOUNTING)")
    print("=" * 148)
    print(
        f"{'Strategy Model':<42} | {'Signals':<7} | {'Win Rate%':<9} | "
        f"{'Net Exp%':<8} | {'Exp / 1L':<12} | {'Duration':<10} | {'Velocity':<8} | {'Peak MFE':<9} | {'XIRR'}"
    )
    print("-" * 148)
    for m_key, m_desc in MODELS:
        sm = strategy_macro_summary[m_key]
        print(
            f"{m_desc[:40]:<42} | {sm['total_signals_tracked']:<7} | {sm['win_rate_pct']:>7.1f}%  | "
            f"+{sm['net_expectancy_pct']:>6.2f}% | +₹{sm['profit_per_lakh_inr']:>9,.2f} | {sm['trade_duration_days']:>4.1f} days  | "
            f"{sm['annualized_turnover_velocity']:>4.1f}x   | +{sm['overall_avg_mfe_pct']:>5.2f}%   | +{sm['annualized_xirr_pct']:>5.1f}%"
        )

    print("\n" + "=" * 148)
    print(
        f"DAILY PROGRESS TRACKING ({daily_progress_summary['total_trading_days']} Sessions) | "
        f"Peak Concurrent Slots: {daily_progress_summary['peak_concurrent_positions']} | "
        f"Avg Open Slots: {daily_progress_summary['avg_concurrent_positions']} | "
        f"Max Drawdown: {daily_progress_summary['max_equity_drawdown_pct']}% | "
        f"Cumulative P&L: +₹{daily_progress_summary['cumulative_net_profit_inr']:,.0f}"
    )
    print(f"[✓] Saved full backtest data to:    {BACKTEST_JSON}")
    print(f"[✓] Saved macro-summary data to:    {BACKTEST_SUMMARY_JSON}")
    print(f"[✓] Saved raw trade log CSV to:     {BACKTEST_CSV}")
    print("=" * 148)


if __name__ == "__main__":
    run_quarterly_backtest()