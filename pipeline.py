import glob
import io
import json
import os
import subprocess
import zipfile
from datetime import date, datetime, timedelta
import pandas as pd
import numpy as np
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_STORE = os.path.join(DATA_DIR, "csv_store")
METADATA_FILE = os.path.join(DATA_DIR, "metadata_master.csv")
OUTPUT_JSON = os.path.join(BASE_DIR, "dashboard_data.json")
PRICE_HISTORY_JSON = os.path.join(DATA_DIR, "price_history.json")

os.makedirs(CSV_STORE, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

NIFTY_50_SYMBOLS = {
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", 
    "BAJFINANCE", "BEL", "BHARTIARTL", "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY", 
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", 
    "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT", 
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", 
    "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", 
    "TITAN", "TRENT", "ULTRACEMCO", "WIPRO"
}

NIFTY_NEXT_50_SYMBOLS = {
    "ABB", "AMBUJACEM", "BANKBARODA", "BERGEPAINT", "BHEL", "BOSCHLTD", "CANBK", "CHOLAFIN", 
    "COLPAL", "DLF", "GAIL", "GODREJCP", "HAL", "HAVELLS", "ICICIGI", "ICICIPRULI", "INDIGO", 
    "IOC", "IRCTC", "JINDALSTEL", "JIOFIN", "LTIM", "MOTHERSON", "NAUKRI", "PIDILITIND", 
    "PFC", "PNB", "RECLTD", "SIEMENS", "SRF", "TORNTPHARM", "TVSMOTOR", "UNITDSPR", "VBL", 
    "VEDL", "ZYDUSLIFE", "ZOMATO"
}


def download_with_curl(url: str) -> bytes:
    cookie_file = os.path.join(DATA_DIR, "nse_cookies.txt")
    init_cmd = ["curl", "-s", "-c", cookie_file, "-b", cookie_file, "-A", HEADERS["User-Agent"], "https://www.nseindia.com/"]
    try:
        subprocess.run(init_cmd, capture_output=True, timeout=10)
    except Exception:
        pass

    cmd = ["curl", "-s", "-L", "-b", cookie_file, "-A", HEADERS["User-Agent"], "-H", "Referer: https://www.nseindia.com/", "--compressed", url]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=25)
        if res.returncode == 0 and len(res.stdout) > 5000:
            return res.stdout
    except Exception:
        pass
    return b""


def load_index_mappings() -> dict:
    symbol_to_meta = {}
    files_to_parse = [
        (["ind_nifty50list.csv", "nifty50.csv"], "Nifty 50"),
        (["ind_niftynext50list.csv", "niftynext50.csv"], "Nifty Next 50"),
        (["ind_nifty500list.csv", "nifty500.csv"], "Nifty 500"),
        (["ind_niftymidcap150list.csv", "niftymidcap150.csv"], "Nifty Midcap 150"),
        (["ind_niftysmallcap250list.csv", "niftysmallcap250.csv"], "Nifty Smallcap 250"),
        (["ind_niftymicrocap250_list.csv", "ind_niftymicrocap250list.csv", "niftymicrocap250.csv"], "Nifty Microcap 250"),
        (["ind_niftyIPO_list.csv", "niftyipo.csv"], "Nifty IPO"),
    ]
    for filename_candidates, index_name in files_to_parse:
        valid_path = None
        for fn in filename_candidates:
            p = next((x for x in [os.path.join(DATA_DIR, fn), os.path.join(BASE_DIR, fn), fn] if os.path.exists(x)), None)
            if p:
                valid_path = p
                break
        if not valid_path:
            continue
        try:
            df = pd.read_csv(valid_path)
            df.columns = [c.strip() for c in df.columns]
            sym_col = next((c for c in df.columns if "SYMBOL" in c.upper()), df.columns[0])
            name_col = next((c for c in df.columns if "COMPANY" in c.upper() or "NAME" in c.upper()), df.columns[0])
            ind_col = next((c for c in df.columns if "INDUSTRY" in c.upper() or "SECTOR" in c.upper()), None)
            for _, r in df.iterrows():
                sym = str(r[sym_col]).strip().upper()
                if not sym or sym == "NAN":
                    continue
                cname = str(r[name_col]).strip() if pd.notna(r[name_col]) else sym
                industry = str(r[ind_col]).strip() if ind_col and pd.notna(r[ind_col]) else "General Equities"
                if sym not in symbol_to_meta:
                    symbol_to_meta[sym] = {"indices": [index_name], "company_name": cname, "sector": industry}
                else:
                    if index_name not in symbol_to_meta[sym]["indices"]:
                        symbol_to_meta[sym]["indices"].append(index_name)
        except Exception as e:
            print(f"[!] Error parsing index file {valid_path}: {e}")

    for sym in NIFTY_50_SYMBOLS:
        if sym in symbol_to_meta:
            if "Nifty 50" not in symbol_to_meta[sym]["indices"]:
                symbol_to_meta[sym]["indices"].insert(0, "Nifty 50")
            if "Nifty 500" not in symbol_to_meta[sym]["indices"]:
                symbol_to_meta[sym]["indices"].append("Nifty 500")
        else:
            symbol_to_meta[sym] = {"indices": ["Nifty 50", "Nifty 500"], "company_name": sym, "sector": "General Equities"}

    for sym in NIFTY_NEXT_50_SYMBOLS:
        if sym in symbol_to_meta:
            if "Nifty Next 50" not in symbol_to_meta[sym]["indices"]:
                symbol_to_meta[sym]["indices"].insert(0, "Nifty Next 50")
            if "Nifty 500" not in symbol_to_meta[sym]["indices"]:
                symbol_to_meta[sym]["indices"].append("Nifty 500")
        else:
            symbol_to_meta[sym] = {"indices": ["Nifty Next 50", "Nifty 500"], "company_name": sym, "sector": "General Equities"}

    return {
        sym: {
            "index": ", ".join(meta["indices"]),
            "company_name": meta["company_name"],
            "sector": meta["sector"],
        }
        for sym, meta in symbol_to_meta.items()
    }


def ensure_metadata(active_symbols: list):
    symbol_meta = load_index_mappings()
    eq_rows = [
        {
            "symbol": sym,
            "company_name": meta["company_name"],
            "sector": meta["sector"],
            "industry": meta["sector"],
            "index_name": meta["index"],
        }
        for sym, meta in symbol_meta.items()
        if sym in active_symbols
    ]
    pd.DataFrame(eq_rows).drop_duplicates(subset=["symbol"]).to_csv(METADATA_FILE, index=False)


def fetch_udiff_bhavcopy(target_date: date) -> pd.DataFrame:
    d_udiff = target_date.strftime("%Y%m%d")
    url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d_udiff}_F_0000.csv.zip"
    content = download_with_curl(url)
    if not content or len(content) < 5000:
        return pd.DataFrame()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            csv_candidates = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_candidates:
                return pd.DataFrame()
            with zf.open(csv_candidates[0]) as csv_file:
                df = pd.read_csv(csv_file)
                df.columns = [c.strip() for c in df.columns]
                series_col = "SctySrs" if "SctySrs" in df.columns else "SERIES"
                symbol_col = "TckrSymb" if "TckrSymb" in df.columns else "SYMBOL"
                df = df[df[series_col].isin(["EQ", "BE", "SM"])]
                return (
                    pd.DataFrame(
                        {
                            "symbol": df[symbol_col].astype(str).str.strip(),
                            "open": pd.to_numeric(df["OpnPric" if "OpnPric" in df.columns else "OPEN_PRICE"], errors="coerce"),
                            "high": pd.to_numeric(df["HghPric" if "HghPric" in df.columns else "HIGH_PRICE"], errors="coerce"),
                            "low": pd.to_numeric(df["LwPric" if "LwPric" in df.columns else "LOW_PRICE"], errors="coerce"),
                            "close": pd.to_numeric(df["ClsPric" if "ClsPric" in df.columns else "CLOSE_PRICE"], errors="coerce"),
                            "volume": pd.to_numeric(df["TtlTradgVol" if "TtlTradgVol" in df.columns else "TTL_TRD_QNTY"], errors="coerce"),
                        }
                    )
                    .drop_duplicates(subset=["symbol"])
                    .dropna(subset=["symbol", "close"])
                )
    except Exception:
        return pd.DataFrame()


def fetch_mto_delivery(target_date: date) -> pd.DataFrame:
    d_mto = target_date.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{d_mto}.DAT"
    content = download_with_curl(url)
    if not content or len(content) < 1000:
        return pd.DataFrame(columns=["symbol", "deliv_qty", "deliv_pct"])
    rows = []
    for line in content.decode("utf-8", errors="ignore").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 7 and parts[0] == "20" and parts[3] in ["EQ", "BE", "SM"]:
            try:
                rows.append({"symbol": parts[2], "deliv_qty": int(parts[5]), "deliv_pct": float(parts[6])})
            except Exception:
                continue
    return pd.DataFrame(rows).drop_duplicates(subset=["symbol"]) if rows else pd.DataFrame(columns=["symbol", "deliv_qty", "deliv_pct"])


def update_incremental_store(lookback_days: int = 720):
    now = datetime.now()
    max_allowed = date.today() if now.hour >= 16 and now.minute >= 30 else (date.today() - timedelta(days=1))
    target_check = max_allowed
    latest_session = None
    for _ in range(5):
        if len(download_with_curl(f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{target_check.strftime('%Y%m%d')}_F_0000.csv.zip")) > 5000:
            latest_session = target_check
            break
        target_check -= timedelta(days=1)
    if not latest_session:
        return

    for i in range(min(lookback_days, 720), -1, -1):
        target = latest_session - timedelta(days=i)
        if target.weekday() >= 5:
            continue
        date_iso = target.strftime("%Y-%m-%d")
        target_file = os.path.join(CSV_STORE, f"date={date_iso}", "part.csv")
        if os.path.exists(target_file) and target != latest_session:
            continue
        df = fetch_udiff_bhavcopy(target)
        if not df.empty:
            delivery_df = fetch_mto_delivery(target)
            merged = pd.merge(df, delivery_df, on="symbol", how="left").fillna({"deliv_qty": 0, "deliv_pct": 50.0})
            merged["date"] = date_iso
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            merged.drop_duplicates(subset=["symbol"]).to_csv(target_file, index=False)


def normalize_corporate_actions(df_all: pd.DataFrame) -> tuple:
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
    else:
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


def detect_genuine_chart_patterns(prices, volumes, highs, lows):
    n = len(prices)
    if n < 25:
        return 0.90, "", 21

    if n >= 50:
        c1 = (np.max(highs[-48:-36]) - np.min(lows[-48:-36])) / (np.max(highs[-48:-36]) + 1e-5)
        c2 = (np.max(highs[-36:-24]) - np.min(lows[-36:-24])) / (np.max(highs[-36:-24]) + 1e-5)
        c3 = (np.max(highs[-24:-12]) - np.min(lows[-24:-12])) / (np.max(highs[-24:-12]) + 1e-5)
        c4 = (np.max(highs[-12:]) - np.min(lows[-12:])) / (np.max(highs[-12:]) + 1e-5)
        if c4 <= 0.085 and ((c4 < c3 and c3 < c2) or (c1 >= 0.12 and c2 >= c3)):
            vcp_calc = round(float(np.clip(c4 / max(c1, c2, 0.12), 0.35, 0.62)), 2)
            return vcp_calc, "🎯 VCP Coiled Spring", 50

    if n >= 100:
        base_high = np.max(highs[-100:])
        base_low = np.min(lows[-100:])
        spread_100 = (base_high - base_low) / (base_low + 1e-5)
        sma_50 = np.mean(prices[-50:])
        if spread_100 <= 0.22 and prices[-1] >= sma_50:
            return 0.65, "🟢 Multi-Month Base / Cup", 100

    if n >= 25:
        pole_start = prices[-25]
        pole_peak = np.max(highs[-25:-7])
        flag_low = np.min(lows[-7:])
        pole_gain = (pole_peak - pole_start) / (pole_start + 1e-5)
        flag_pullback = (pole_peak - flag_low) / (pole_peak + 1e-5)
        vol_pole = np.mean(volumes[-25:-7])
        vol_flag = np.mean(volumes[-7:])
        if pole_gain >= 0.15 and flag_pullback <= 0.12 and vol_flag < vol_pole:
            return 0.68, "🚩 High-Tight Flag & Pole", 21

    if n >= 200:
        sma_200 = np.mean(prices[-200:])
        h_52 = np.max(highs[-200:])
        if prices[-1] >= sma_200 and (prices[-1] / (h_52 + 1e-5)) >= 0.88:
            return 0.75, "⚡ Stage 2 Macro Base", 200

    return 0.90, "", 21


def run_screener_engine():
    update_incremental_store(lookback_days=720)
    symbol_meta = load_index_mappings()
    target_symbols = list(symbol_meta.keys())
    if not target_symbols:
        return

    ensure_metadata(target_symbols)
    found_files = glob.glob(os.path.join(CSV_STORE, "**/*.csv"), recursive=True)
    if not found_files:
        return

    df_all = pd.concat([pd.read_csv(f) for f in found_files], ignore_index=True).drop_duplicates(subset=["symbol", "date"])
    df_all = df_all[df_all["symbol"].isin(target_symbols)]
    master_df = pd.read_csv(METADATA_FILE).drop_duplicates(subset=["symbol"])
    df_all = pd.merge(df_all, master_df, on="symbol", how="left").fillna({"sector": "Capital Goods", "company_name": df_all["symbol"]})
    df_all = df_all[df_all["sector"] != "General Equities"].sort_values(by=["symbol", "date"]).reset_index(drop=True)

    df_all, corp_events = normalize_corporate_actions(df_all)
    print(f"[*] Normalized {len(corp_events)} corporate split/bonus events across Bhavcopy series.")

    dates = sorted(df_all["date"].unique())
    latest_date = dates[-1]
    latest_df = df_all[df_all["date"] == latest_date].copy().drop_duplicates(subset=["symbol"])

    lookback_idx_20 = max(0, len(dates) - 20)
    lookback_date_20 = dates[lookback_idx_20]
    df_20_ago = df_all[df_all["date"] == lookback_date_20][["symbol", "close"]].rename(columns={"close": "close_20d_ago"}).drop_duplicates(subset=["symbol"])

    lookback_idx_63 = max(0, len(dates) - 63)
    lookback_date_63 = dates[lookback_idx_63]
    df_63_ago = df_all[df_all["date"] == lookback_date_63][["symbol", "close"]].rename(columns={"close": "close_63d_ago"}).drop_duplicates(subset=["symbol"])

    sec_base = pd.merge(latest_df, df_20_ago, on="symbol", how="left")
    sec_base = pd.merge(sec_base, df_63_ago, on="symbol", how="left")
    sec_base["close_20d_ago"] = sec_base["close_20d_ago"].fillna(sec_base["close"])
    sec_base["close_63d_ago"] = sec_base["close_63d_ago"].fillna(sec_base["close"])

    df_250d_all = df_all[df_all["date"].isin(dates[-250:])].sort_values(by=["symbol", "date"])
    market_pivot = df_250d_all.pivot(index="date", columns="symbol", values="close").ffill().dropna(how="all")
    market_benchmark = market_pivot.mean(axis=1)

    sector_benchmarks = {}
    sector_rs_history = {}
    for sec_name, sec_grp in df_250d_all.groupby("sector"):
        if sec_name == "General Equities":
            continue
        sec_pivot = sec_grp.pivot(index="date", columns="symbol", values="close").ffill().dropna(how="all")
        if not sec_pivot.empty:
            sec_mean = sec_pivot.mean(axis=1)
            sector_benchmarks[sec_name] = sec_mean
            common_idx = sec_mean.index.intersection(market_benchmark.index)
            if len(common_idx) > 10:
                sec_norm = (sec_mean.loc[common_idx] / sec_mean.loc[common_idx[0]]) * 100.0
                mkt_norm = (market_benchmark.loc[common_idx] / market_benchmark.loc[common_idx[0]]) * 100.0
                rel_perf = (sec_norm - mkt_norm).round(2)
                sector_rs_history[sec_name] = [{"date": str(d), "rs": float(v)} for d, v in zip(common_idx, rel_perf.iloc)]

    mkt_len = len(market_benchmark)
    bm_ret_21 = (market_benchmark.iloc[-1] / (market_benchmark.iloc[-min(21, mkt_len)] + 1e-5)) - 1.0
    bm_ret_63 = (market_benchmark.iloc[-1] / (market_benchmark.iloc[-min(63, mkt_len)] + 1e-5)) - 1.0
    bm_ret_126 = (market_benchmark.iloc[-1] / (market_benchmark.iloc[-min(126, mkt_len)] + 1e-5)) - 1.0
    bm_ret_250 = (market_benchmark.iloc[-1] / (market_benchmark.iloc[0] + 1e-5)) - 1.0

    stock_tech_rows = []
    price_history_map = {}

    for sym, grp in df_250d_all.groupby("symbol"):
        prices = grp["close"].values
        volumes = grp["volume"].values
        highs = grp["high"].values
        lows = grp["low"].values
        deliv_pcts = grp["deliv_pct"].values
        deliv_qtys = grp["deliv_qty"].values

        n_bars = len(prices)
        if n_bars < 50:
            continue

        p_series = pd.Series(prices)
        close = float(prices[-1])
        if close <= 0:
            continue

        sma_20 = round(float(np.mean(prices[-20:])), 2)
        ema_10 = float(p_series.ewm(span=10, adjust=False).mean().iloc[-1])
        ema_21 = float(p_series.ewm(span=21, adjust=False).mean().iloc[-1])
        sma_50_series = p_series.rolling(50, min_periods=20).mean()
        sma_50 = round(float(sma_50_series.iloc[-1]), 2)
        sma_50_10d_ago = float(sma_50_series.iloc[-min(10, len(sma_50_series))])
        sma_50_rising = sma_50 >= (sma_50_10d_ago * 0.998)
        sma_200 = round(float(p_series.rolling(min(200, n_bars), min_periods=40).mean().iloc[-1]), 2)

        if np.isnan(sma_20) or np.isnan(sma_50) or np.isnan(sma_200):
            continue

        tr_arr = np.maximum(
            highs[-20:] - lows[-20:],
            np.maximum(
                np.abs(highs[-20:] - np.roll(prices, 1)[-20:]),
                np.abs(lows[-20:] - np.roll(prices, 1)[-20:])
            ),
        )
        atr_20 = float(np.mean(tr_arr))
        atr_pct = round(float((atr_20 / (close + 1e-5)) * 100.0), 2)

        vol_20_avg = float(np.mean(volumes[-min(20, n_bars):])) + 1e-5
        session_rvol = round(float(volumes[-1] / vol_20_avg), 2)
        is_rvol_expanded = session_rvol >= 2.5

        sub_15_diff = np.diff(prices[-16:]) if n_bars >= 16 else np.diff(prices)
        sub_15_vols = volumes[-len(sub_15_diff):]
        up_vol_15 = np.sum(sub_15_vols[sub_15_diff > 0]) if np.any(sub_15_diff > 0) else 1.0
        down_vol_15 = np.sum(sub_15_vols[sub_15_diff < 0]) if np.any(sub_15_diff < 0) else 1.0
        supply_exhaustion_ratio = round(float(up_vol_15 / (down_vol_15 + 1e-5)), 2)
        is_supply_exhausted = supply_exhaustion_ratio >= 3.5

        stock_series_full = grp.set_index("date")["close"]
        common_s_idx_full = stock_series_full.index.intersection(market_benchmark.index)
        stk_sub_full = stock_series_full.loc[common_s_idx_full]
        bm_sub_full = market_benchmark.loc[common_s_idx_full]
        rs_full_series = (stk_sub_full / bm_sub_full).values
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

        hist, bins = np.histogram(prices[-50:], bins=10, weights=volumes[-50:])
        poc = round(float((bins[np.argmax(hist)] + bins[np.argmax(hist) + 1]) / 2.0), 2)

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

        stock_series = grp.set_index("date")["close"]
        common_s_idx = stock_series.index.intersection(market_benchmark.index)
        stk_sub = stock_series.loc[common_s_idx]
        bm_sub = market_benchmark.loc[common_s_idx]
        rs_series = (stk_sub / bm_sub).values

        sec_name = grp["sector"].iloc[-1] if "sector" in grp.columns else "Capital Goods"
        sec_bm = sector_benchmarks.get(sec_name, market_benchmark)
        sec_sub = sec_bm.reindex(common_s_idx).ffill().bfill()
        sec_rs_series = (stk_sub / (sec_sub + 1e-5)).values

        if len(rs_series) >= 63:
            rs_63_high = np.max(rs_series[-63:-1])
            price_63_high = np.max(highs[-63:-1])
            is_rs_divergent = (rs_series[-1] >= rs_63_high) and (close < price_63_high * 0.99)
            rs_is_new_high = rs_series[-1] >= np.max(rs_series[-21:])
            rs_is_lagging = rs_series[-1] <= np.min(rs_series[-63:])
        else:
            is_rs_divergent = False
            rs_is_new_high = close >= np.max(prices[-20:-1])
            rs_is_lagging = False

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
            sec_rs_new_high = rs_is_new_high
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

        dist_from_20 = (close - sma_20) / (sma_20 + 1e-5)
        dist_from_50 = (close - sma_50) / (sma_50 + 1e-5)
        dist_from_50_pct = round(float(dist_from_50 * 100.0), 2)
        dist_from_200_pct = round(float(((close - sma_200) / (sma_200 + 1e-5)) * 100.0), 2)
        is_extended_danger = dist_from_20 > 0.08

        stk_ret_21 = (close / (prices[-min(21, n_bars)] + 1e-5)) - 1.0
        stk_ret_63 = (close / (prices[-min(63, n_bars)] + 1e-5)) - 1.0
        stk_ret_126 = (close / (prices[-min(126, n_bars)] + 1e-5)) - 1.0
        stk_ret_250 = (close / (prices[0] + 1e-5)) - 1.0
        prior_63d_pct = round(float(stk_ret_63 * 100.0), 2)

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

        deliv_cash_all = deliv_qtys[-min(30, n_bars):] * prices[-min(30, n_bars):]
        diffs_deliv = diffs[-min(29, len(diffs)):]
        deliv_up = np.sum(deliv_cash_all[1:][diffs_deliv > 0]) if np.any(diffs_deliv > 0) else 1.0
        deliv_down = np.sum(deliv_cash_all[1:][diffs_deliv < 0]) if np.any(diffs_deliv < 0) else 1.0
        deliv_flow_ratio = float(deliv_up / (deliv_down + 1e-5))

        pinch_pts = float(np.clip(20.0 * (1.0 - (ma_spread_pct / 6.5)), 2.0, 20.0))
        squeeze_pts = float(np.clip(15.0 * (1.35 - bb_kc_ratio), 2.0, 15.0))
        flow_pts = float(np.clip(40.0 * (np.log1p(min(deliv_flow_ratio, 6.0)) / np.log1p(4.2)), 4.0, 40.0))
        base_pts = float(np.clip(25.0 * (1.0 - (base_depth_pct / 32.0)), 2.0, 25.0)) if close >= sma_50 else 4.0

        raw_iasis = pinch_pts + squeeze_pts + flow_pts + base_pts
        if close < sma_200 and close < sma_50:
            iasis_score = round(float(min(35.0, raw_iasis * 0.40)), 1)
        else:
            iasis_score = round(float(np.clip(raw_iasis, 10.0, 99.0)), 1)

        raw_struct_stop = min(close - (2.2 * atr_20), sma_50 * 0.975)
        structural_stop = round(float(max(close * 0.915, raw_struct_stop)), 2)

        tranche2_limit_price = round(close - (1.5 * atr_20), 2)
        blended_entry_price = round((close + tranche2_limit_price) / 2.0, 2)
        cushioned_sl_price = round(min(structural_stop, tranche2_limit_price - (1.0 * atr_20)), 2)

        risk_unit = max(1.0, blended_entry_price - cushioned_sl_price)
        target_dist = max(base_depth_pct / 100.0 * close, 2.5 * atr_20)
        rrr_calc = round(min(8.0, max(1.5, target_dist / risk_unit)), 1)

        reasons_to_avoid = []
        if close < sma_200:
            reasons_to_avoid.append("Price trading below 200-day SMA (heavy overhead supply)")
        if close < sma_50:
            reasons_to_avoid.append("Price below intermediate 50-day SMA (intermediate downtrend)")
        if is_extended_danger:
            reasons_to_avoid.append("Price extended >8% above 20 SMA (high risk of mean-reversion pullback)")
        if prior_63d_pct > 35.0:
            reasons_to_avoid.append(f"Already ran +{prior_63d_pct:.0f}% in 63 days (late-stage exhaustion risk)")
        if dist_from_200_pct > 35.0:
            reasons_to_avoid.append(f"Stretched +{dist_from_200_pct:.0f}% above 200-SMA (poor buying scope)")
        if rs_is_lagging:
            reasons_to_avoid.append("Relative strength line making 63-day lows vs benchmark")
        if up_down_ratio < 0.85:
            reasons_to_avoid.append("Down-day volume exceeds up-day volume (institutional distribution)")
        if base_depth_pct > 30.0:
            reasons_to_avoid.append("Consolidation base too deep (>30% correction, damaged structure)")

        if len(common_s_idx) > 10:
            stk_norm = (stock_series.loc[common_s_idx] / stock_series.loc[common_s_idx[0]]) * 100.0
            mkt_norm = (market_benchmark.loc[common_s_idx] / market_benchmark.loc[common_s_idx[0]]) * 100.0
            stk_rel_mkt = (stk_norm - mkt_norm).round(2)

            sec_norm = (sec_sub / (sec_sub.iloc[0] + 1e-5)) * 100.0
            stk_rel_sec = (stk_norm - sec_norm).round(2)

            price_history_map[sym] = [
                {"date": str(d), "rs": float(v_mkt), "rs_vs_sector": float(v_sec)}
                for d, v_mkt, v_sec in zip(common_s_idx, stk_rel_mkt.iloc, stk_rel_sec.iloc)
            ]
        else:
            price_history_map[sym] = []

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
            "volume_profile_poc": poc,
            "chart_pattern_signal": pattern,
            "pattern_timeframe": pattern_tf,
            "rs_line_status": "🔥 RS Line New High" if (rs_is_new_high or is_rs_divergent) else "",
            "sector_rs_status": sector_rs_status,
            "avg_deliv_20": np.mean(deliv_qtys[-min(20, n_bars):]),
            "atr_20": atr_20,
            "atr_pct": atr_pct,
            "structural_stop": structural_stop,
            "tranche2_limit_price": tranche2_limit_price,
            "blended_entry_price": blended_entry_price,
            "cushioned_sl_price": cushioned_sl_price,
            "vcp_ratio_calc": float(vcp_rat),
            "bb_kc_ratio": bb_kc_ratio,
            "ma_spread_pct": round(ma_spread_pct, 2),
            "vol_dryup_ratio": round(vol_dryup_ratio, 2),
            "iasis_score": iasis_score,
            "raw_multi_rs": raw_multi_rs,
            "trend_score": trend_score,
            "up_down_vol_ratio": up_down_ratio,
            "smooth_deliv_expansion": round(float(deliv_flow_ratio), 2),
            "smooth_deliv_pct": round(float(np.mean(deliv_pcts[-min(20, n_bars):])), 1),
            "high_52w": h_52,
            "low_52w": l_52,
            "risk_reward_calc": rrr_calc,
            "session_rvol": session_rvol,
            "is_rvol_expanded": is_rvol_expanded,
            "is_squeezed": bool(is_squeezed),
            "is_ma_pinched": bool(is_ma_pinched),
            "is_rs_divergent": bool(is_rs_divergent),
            "is_pocket_pivot_5d": bool(is_pocket_pivot_5d),
            "is_supply_exhausted": bool(is_supply_exhausted),
            "is_rs_accelerating": bool(is_rs_accelerating),
            "supply_exhaustion_ratio": supply_exhaustion_ratio,
            "flow_ratio": round(deliv_flow_ratio, 2),
            "dist_from_20": dist_from_20,
            "dist_from_50_pct": dist_from_50_pct,
            "dist_from_200_pct": dist_from_200_pct,
            "prior_63d_pct": prior_63d_pct,
            "base_depth_pct": round(base_depth_pct, 2),
            "reasons_to_avoid": "; ".join(reasons_to_avoid) if reasons_to_avoid else "None. Technical structure remains constructive.",
        })

    with open(PRICE_HISTORY_JSON, "w") as f:
        json.dump(price_history_map, f)

    ranked = pd.merge(latest_df, pd.DataFrame(stock_tech_rows), on="symbol", how="inner").drop_duplicates(subset=["symbol"])
    
    ranked["turnover_cr"] = ((ranked["volume"].fillna(0) * ranked["close"]) / 10000000.0).round(2)
    ranked["mcap_tier"] = ranked.apply(lambda r: classify_mcap_tier(r["symbol"], r.get("index_name", ""), r.get("turnover_cr", 0.0)), axis=1)
    
    ranked["d_expansion"] = ranked["smooth_deliv_expansion"]
    ranked["deliv_spike"] = (ranked["deliv_qty"] / (ranked["avg_deliv_20"] + 1)).round(2)
    ranked["vcp_ratio"] = ranked["vcp_ratio_calc"]
    ranked["mrs_score"] = (((ranked["close"] / (ranked["sma_20"] + 1e-5)) - 1.0) * 100.0).round(1)
    ranked["absorption_ratio"] = (((ranked["deliv_qty"] * ranked["close"]) / 10000000.0) / (ranked["high"] - ranked["low"] + 0.05)).round(2)
    ranked["atr_stop_loss"] = ranked["structural_stop"]
    ranked["above_sma20"] = ranked["close"] >= ranked["sma_20"]
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

    rs_63_pct = sector_summary["perf_63d"].rank(pct=True) * 100.0
    breadth_pct = sector_summary["above_sma_pct"]
    rs_20_pct = sector_summary["perf_20d"].rank(pct=True) * 100.0

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

    raw_sec_comp = (0.40 * rs_63_pct) + (0.35 * breadth_pct) + (0.25 * rs_20_pct)
    sector_summary["sector_composite_score"] = (
        raw_sec_comp - np.where(sector_summary["sector_climax_mult"] < 0.88, (1.0 - sector_summary["sector_climax_mult"]) * 15.0, 0.0)
    ).round(2)

    sector_perf_map = dict(zip(sector_summary["sector"], sector_summary["perf_20d"]))
    sector_quad_map = dict(zip(sector_summary["sector"], sector_summary["quadrant"]))
    sector_mult_map = dict(zip(sector_summary["sector"], sector_summary["sector_climax_mult"]))
    sector_life_map = dict(zip(sector_summary["sector"], sector_summary["sector_lifecycle"]))

    ranked["beta_neutral_mrs"] = (ranked["mrs_score"] - ranked["sector"].map(lambda s: sector_perf_map.get(s, 0.0))).round(1)
    ranked["sector_breadth_status"] = ranked["sector"].map(lambda s: sector_quad_map.get(s, "Neutral"))
    ranked["sector_climax_mult"] = ranked["sector"].map(lambda s: sector_mult_map.get(s, 1.0))
    ranked["sector_lifecycle"] = ranked["sector"].map(lambda s: sector_life_map.get(s, "Neutral"))
    ranked["risk_reward_ratio"] = ranked["risk_reward_calc"]
    ranked["market_breadth_status"] = "🟢 Bullish Regime" if ((latest_df["close"] > latest_df["open"]).mean() * 100.0) >= 50.0 else "🔴 Bearish Regime"

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

    # Pure Quantitative Strategy Models (Calibrated exactly to Backtest Engine)
    
    # Structural Penalty: If the stock is pulling back (MRS < 1.5%), aggressively slash the momentum score 
    # so it does not outcompete Pullback in a market crash simply due to high RS percentiles.
    mom_struct_penalty = np.where(ranked["mrs_score"] < 1.5, 0.65, 1.0)
    
    # Structural Penalty: If the sector is not actually rotating or leading, slash the rotation score.
    rot_struct_penalty = np.where(ranked["sector_lifecycle"].str.contains("Rotation|Leadership|Improving|Prime"), 1.08, 0.70)

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
    ranked["surety_score"] = (raw_surety * mom_curve * flow_curve * sec_adj).clip(5.0, 99.0).round(1)
    ranked["score_surety_anchor"] = ranked["surety_score"]

    # 2. Strategy 2: Momentum Frontrunner (Gated by mom_struct_penalty)
    ranked["score_momentum_frontrunner"] = (
        (0.40 * ranked["frontrunner_score"] + 0.30 * ranked["trend_score"] + 0.15 * ranked["iasis_score"] + 0.15 * ranked["surety_score"]) * sec_adj * mom_struct_penalty
    ).clip(5.0, 99.0).round(1)

    # 3. Strategy 3: Early Sector Rotation (Gated by rot_struct_penalty)
    ranked["score_early_sector_rotation"] = (
        (0.35 * ranked["frontrunner_score"] + 0.25 * ranked["iasis_score"] + 0.25 * ranked["surety_score"] + 0.15 * ranked["ignition_score"]) * rot_struct_penalty
    ).clip(5.0, 99.0).round(1)

    # 4. Strategy 4: High-RS Pullback Structure
    pullback_depth_pts = 30.0 * np.exp(-((ranked["mrs_score"] - (-1.5)) ** 2) / 8.0)
    stoch_oversold_pts = 30.0 * np.clip(1.0 - (ranked["stoch_k"] / 60.0), 0.0, 1.0)
    ranked["score_high_rs_pullback"] = (
        (pullback_depth_pts + stoch_oversold_pts + 0.25 * rs_percentile + 0.15 * ranked["iasis_score"]) * sec_adj
    ).clip(5.0, 99.0).round(1)

    # Exact Backtest-Synchronized Institutional Setup Classifier
    def get_signal(r):
        scores = [
            (float(r.get("score_surety_anchor", 0)), "🛡️ 1. Surety Anchor"),
            (float(r.get("score_momentum_frontrunner", 0)), "🚀 2. Momentum"),
            (float(r.get("score_early_sector_rotation", 0)), "🔄 3. Rotation"),
            (float(r.get("score_high_rs_pullback", 0)), "📉 4. Pullback"),
        ]
        scores.sort(key=lambda x: x[0], reverse=True)
        return scores[0][1]

    ranked["inst_signal"] = ranked.apply(get_signal, axis=1)
    
    market_breadth_pct = float((ranked["above_sma50"].mean()) * 100.0)
    bm_sma_20 = float(market_benchmark.rolling(20).mean().iloc[-1])
    bm_mrs = float(((float(market_benchmark.iloc[-1]) / (bm_sma_20 + 1e-5)) - 1.0) * 100.0)

    # -------------------------------------------------------------------------
    # DYNAMIC REGIME & PORTFOLIO ALLOCATION ENGINE
    # -------------------------------------------------------------------------
    active_rot = len(sector_summary[(sector_summary["stock_count"] >= 3) & (sector_summary["sector_lifecycle"].str.contains("Rotation|Prime|Leadership"))])
    
    if market_breadth_pct >= 50.0 and bm_mrs <= 3.0:
        regime_label = f"🟢 Expansion Regime ({market_breadth_pct:.1f}% >50SMA)"
        rot_q = 3 if active_rot > 0 else 0
        quotas = {"score_momentum_frontrunner": 5, "score_early_sector_rotation": rot_q, "score_high_rs_pullback": 3 + (3 - rot_q), "score_surety_anchor": 1}
    elif market_breadth_pct >= 50.0 and bm_mrs > 3.0:
        regime_label = f"⚠️ Overheated Tape (MRS +{bm_mrs:.1f}%)"
        rot_q = 2 if active_rot > 0 else 0
        quotas = {"score_high_rs_pullback": 5 + (2 - rot_q), "score_surety_anchor": 4, "score_early_sector_rotation": rot_q, "score_momentum_frontrunner": 1}
    elif market_breadth_pct < 35.0:
        regime_label = f"🛡️ Bearish Defense ({market_breadth_pct:.1f}% >50SMA)"
        quotas = {"score_surety_anchor": 5, "score_high_rs_pullback": 5, "score_momentum_frontrunner": 2, "score_early_sector_rotation": 0}
    else:
        regime_label = f"🔄 Early Recovery Thrust ({market_breadth_pct:.1f}% >50SMA)"
        rot_q = 4 if active_rot > 0 else 0
        quotas = {"score_early_sector_rotation": rot_q, "score_high_rs_pullback": 4 + (4 - rot_q), "score_momentum_frontrunner": 2, "score_surety_anchor": 2}

    dynamic_picks_map = {}
    seen_sec = {}
    
    for strat_key, limit in quotas.items():
        if limit <= 0: continue
        
        if strat_key == "score_surety_anchor":
            mask = (ranked["close"] >= ranked["sma_200"]) & (ranked["close"] >= ranked["sma_50"] * 0.97) & (ranked["mrs_score"] >= -5.0) & (ranked["mrs_score"] <= 6.0) & (~ranked["mcap_tier"].str.contains("Tier 1", na=False))
            strat_name = "surety"
        elif strat_key == "score_momentum_frontrunner":
            mask = (ranked["close"] >= ranked["sma_200"]) & (ranked["close"] >= ranked["sma_50"]) & (ranked["mrs_score"] >= -2.0) & (ranked["mrs_score"] <= 10.0)
            strat_name = "momentum"
        elif strat_key == "score_early_sector_rotation":
            mask = (ranked["close"] >= ranked["sma_200"]) & (~ranked["sector_rs_status"].str.contains("Lagging") | ~ranked["sector_lifecycle"].str.contains("Lagging") | (ranked["beta_neutral_mrs"] >= 1.5)) & (ranked["sector_lifecycle"].str.contains("Rotation|Prime|Leadership", na=False))
            strat_name = "rotation"
        elif strat_key == "score_high_rs_pullback":
            mask = (ranked["close"] >= ranked["sma_200"]) & (ranked["mrs_score"] >= -7.0) & (ranked["mrs_score"] <= 2.5) & (ranked["stoch_k"] <= 75)
            strat_name = "pullback"
        else:
            mask = ranked["close"] > 0
            strat_name = "surety"
            
        qual = ranked[mask].sort_values(by=[strat_key, "iasis_score"], ascending=False)
        added = 0
        for _, r in qual.iterrows():
            if added >= limit: break
            sym, sec = r["symbol"], r["sector"]
            if sym in dynamic_picks_map: continue
            if seen_sec.get(sec, 0) < 2:
                dynamic_picks_map[sym] = strat_name
                seen_sec[sec] = seen_sec.get(sec, 0) + 1
                added += 1

    if len(dynamic_picks_map) < 12:
        mask = (ranked["close"] >= ranked["sma_200"]) & (ranked["close"] >= ranked["sma_50"] * 0.97) & (ranked["mrs_score"] >= -5.0) & (ranked["mrs_score"] <= 6.0) & (~ranked["mcap_tier"].str.contains("Tier 1", na=False))
        backup_pool = ranked[mask].sort_values(by=["score_surety_anchor", "iasis_score"], ascending=False)
        for _, r in backup_pool.iterrows():
            if len(dynamic_picks_map) >= 12: break
            sym = r["symbol"]
            if sym not in dynamic_picks_map:
                dynamic_picks_map[sym] = "surety"
    # -------------------------------------------------------------------------

    ranked = ranked.sort_values(by=["score_surety_anchor", "score_momentum_frontrunner", "iasis_score"], ascending=False).drop_duplicates(subset=["symbol"]).reset_index(drop=True)

    output_stocks = []
    seen = set()
    for _, r in ranked.iterrows():
        sym = str(r["symbol"])
        if sym in seen:
            continue
        seen.add(sym)

        def clean(val, is_str=False):
            if pd.isna(val) or val is None:
                return None if not is_str else ""
            if is_str:
                return str(val)
            try:
                f = float(val)
                return None if np.isnan(f) else round(f, 2)
            except Exception:
                return val

        output_stocks.append({
            "symbol": sym,
            "company_name": clean(r.get("company_name", sym), True),
            "sector": clean(r.get("sector", "Capital Goods"), True),
            "industry": clean(r.get("industry", r.get("sector", "General Equities")), True),
            "index_name": clean(r.get("index_name", "Nifty 500"), True),
            "mcap_tier": clean(r.get("mcap_tier", "Tier 2: Mid Cap"), True),
            "close": clean(r.get("close")),
            "sma_20": clean(r.get("sma_20")),
            "sma_50": clean(r.get("sma_50")),
            "sma_200": clean(r.get("sma_200")),
            "stage2_aligned": bool(r.get("stage2_aligned", False)),
            "rsi_14": clean(r.get("rsi_14")),
            "stoch_k": clean(r.get("stoch_k")),
            "atr_stop_loss": clean(r.get("atr_stop_loss")),
            "tranche2_limit_price": clean(r.get("tranche2_limit_price")),
            "blended_entry_price": clean(r.get("blended_entry_price")),
            "cushioned_sl_price": clean(r.get("cushioned_sl_price")),
            "atr_pct": clean(r.get("atr_pct")),
            "volume_profile_poc": clean(r.get("volume_profile_poc")),
            "multi_timeframe_confluence": clean(r.get("multi_timeframe_confluence", ""), True),
            "fundamental_score": None,
            "fundamental_grade": "Unrated",
            "fundamental_rationale": "Pending fundamental sync.",
            "roe": None,
            "profit_growth_yoy": None,
            "trailing_pe": None,
            "forward_pe": None,
            "promoter_pledging": None,
            "debt_to_equity": None,
            "promoter_pct": "NA",
            "fii_pct": "NA",
            "dii_pct": "NA",
            "fii_change_qoq": "NA",
            "dii_change_qoq": "NA",
            "fii_dii_trend": "Promoters: NA, FII: NA, DII: NA",
            "fcf_yield": None,
            "earnings_revision": "NA",
            "chart_pattern_signal": clean(r.get("chart_pattern_signal", ""), True) if pd.notna(r.get("chart_pattern_signal")) else "",
            "pattern_timeframe": int(r.get("pattern_timeframe", 21)),
            "rs_line_status": clean(r.get("rs_line_status", ""), True),
            "sector_rs_status": clean(r.get("sector_rs_status", "🟢 Outperforming Sector"), True),
            "sector_lifecycle": clean(r.get("sector_lifecycle", "🟢 Prime Institutional Leadership"), True),
            "order_block_status": clean(r.get("order_block_status", ""), True),
            "risk_reward_ratio": clean(r.get("risk_reward_ratio")),
            "market_breadth_status": clean(r.get("market_breadth_status", "🟢 Bullish Regime"), True),
            "sector_breadth_status": clean(r.get("sector_breadth_status", "Improving"), True),
            "next_earnings_date": "N/A",
            "deliv_pct": clean(r.get("smooth_deliv_pct")),
            "deliv_spike": clean(r.get("deliv_spike")),
            "d_expansion": clean(r.get("d_expansion")),
            "vcp_ratio": clean(r.get("vcp_ratio")),
            "ma_spread_pct": clean(r.get("ma_spread_pct")),
            "base_depth_pct": clean(r.get("base_depth_pct")),
            "dist_from_50_pct": clean(r.get("dist_from_50_pct")),
            "dist_from_200_pct": clean(r.get("dist_from_200_pct")),
            "prior_63d_pct": clean(r.get("prior_63d_pct")),
            "absorption_ratio": clean(r.get("absorption_ratio")),
            "turnover_cr": clean(r.get("turnover_cr")),
            "mrs_score": clean(r.get("mrs_score")),
            "beta_neutral_mrs": clean(r.get("beta_neutral_mrs")),
            "inst_signal": clean(r.get("inst_signal", "Consolidation / Base"), True),
            "dynamic_mix_strategy": dynamic_picks_map.get(sym, ""),
            "surety_score": clean(r.get("surety_score")),
            "score_high_rs_pullback": clean(r.get("score_high_rs_pullback")),
            "score_momentum_frontrunner": clean(r.get("score_momentum_frontrunner")),
            "score_surety_anchor": clean(r.get("score_surety_anchor")),
            "score_early_sector_rotation": clean(r.get("score_early_sector_rotation")),
            "ignition_score": clean(r.get("ignition_score")),
            "frontrunner_score": clean(r.get("frontrunner_score")),
            "iasis_score": clean(r.get("iasis_score")),
            "up_down_vol_ratio": clean(r.get("up_down_vol_ratio")),
            "trend_score": clean(r.get("trend_score")),
            "session_rvol": clean(r.get("session_rvol")),
            "supply_exhaustion_ratio": clean(r.get("supply_exhaustion_ratio")),
            "rs_acceleration": clean(r.get("rs_acceleration")),
            "reasons_to_avoid": clean(r.get("reasons_to_avoid", ""), True),
        })

    payload = {
        "as_of_date": str(latest_date),
        "corporate_actions_normalized_count": len(corp_events),
        "market_breadth_pct": round(market_breadth_pct, 2),
        "benchmark_mrs_pct": round(bm_mrs, 2),
        "market_regime_label": regime_label,
        "page_size": 50,
        "total_stocks": len(output_stocks),
        "total_pages": (len(output_stocks) + 49) // 50,
        "sectors": sector_summary.to_dict(orient="records"),
        "sector_rs_history": sector_rs_history,
        "stocks": output_stocks,
    }
    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[✓] Pipeline complete. Processed {len(output_stocks)} split-normalized stocks with 4 Finalized Strategies & 50/50 ATR Split Entries.")

    # Upload the newly created file to Supabase secure-quant bucket
    upload_dashboard_to_supabase(OUTPUT_JSON)

from supabase import create_client

def upload_dashboard_to_supabase(json_path: str):
    supabase_url = os.environ.get("SUPABASE_URL", "https://ydjzbwkaxwcfkqzfndum.supabase.co")
    # MUST be the service_role key, NOT the anon key, to allow server write operations
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not service_role_key:
        print("[!] SUPABASE_SERVICE_ROLE_KEY environment variable not set. Skipping upload.")
        return

    try:
        supabase = create_client(supabase_url, service_role_key)

        with open(json_path, "rb") as f:
            # Overwrites dashboard_data.json in your storage bucket
            supabase.storage.from_("secure-quant").upload(
                path="dashboard_data.json",
                file=f,
                file_options={"cache-control": "300", "upsert": "true"},
            )
        print("[✓] Successfully uploaded latest dashboard_data.json to Supabase Storage.")
    except Exception as e:
        print(f"[!] Failed to upload to Supabase Storage: {e}")

if __name__ == "__main__":
    run_screener_engine()