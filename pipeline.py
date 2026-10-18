import glob
import io
import json
import os
import subprocess
import zipfile
from datetime import date, datetime, timedelta
import pandas as pd
import numpy as np

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
    try: subprocess.run(init_cmd, capture_output=True, timeout=10)
    except: pass

    cmd = ["curl", "-s", "-L", "-b", cookie_file, "-A", HEADERS["User-Agent"], "-H", "Referer: https://www.nseindia.com/", "--compressed", url]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=25)
        if res.returncode == 0 and len(res.stdout) > 5000: return res.stdout
    except: pass
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
        (["ind_niftyIPO_list.csv", "niftyipo.csv"], "Nifty IPO")
    ]
    for filename_candidates, index_name in files_to_parse:
        valid_path = None
        for fn in filename_candidates:
            p = next((x for x in [os.path.join(DATA_DIR, fn), os.path.join(BASE_DIR, fn), fn] if os.path.exists(x)), None)
            if p:
                valid_path = p
                break
        if not valid_path: continue
        try:
            df = pd.read_csv(valid_path)
            df.columns = [c.strip() for c in df.columns]
            sym_col = next((c for c in df.columns if "SYMBOL" in c.upper()), df.columns[0])
            name_col = next((c for c in df.columns if "COMPANY" in c.upper() or "NAME" in c.upper()), df.columns[0])
            ind_col = next((c for c in df.columns if "INDUSTRY" in c.upper() or "SECTOR" in c.upper()), None)
            for _, r in df.iterrows():
                sym = str(r[sym_col]).strip().upper()
                if not sym or sym == "NAN": continue
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
            "sector": meta["sector"]
        } for sym, meta in symbol_to_meta.items()
    }

def ensure_metadata(active_symbols: list):
    symbol_meta = load_index_mappings()
    eq_rows = [{
        "symbol": sym, "company_name": meta["company_name"],
        "sector": meta["sector"], "industry": meta["sector"], "index_name": meta["index"]
    } for sym, meta in symbol_meta.items() if sym in active_symbols]
    pd.DataFrame(eq_rows).drop_duplicates(subset=["symbol"]).to_csv(METADATA_FILE, index=False)

def fetch_udiff_bhavcopy(target_date: date) -> pd.DataFrame:
    d_udiff = target_date.strftime("%Y%m%d")
    url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d_udiff}_F_0000.csv.zip"
    content = download_with_curl(url)
    if not content or len(content) < 5000: return pd.DataFrame()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            csv_candidates = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_candidates: return pd.DataFrame()
            with zf.open(csv_candidates[0]) as csv_file:
                df = pd.read_csv(csv_file)
                df.columns = [c.strip() for c in df.columns]
                series_col = "SctySrs" if "SctySrs" in df.columns else "SERIES"
                symbol_col = "TckrSymb" if "TckrSymb" in df.columns else "SYMBOL"
                df = df[df[series_col].isin(["EQ", "BE", "SM"])]
                return pd.DataFrame({
                    "symbol": df[symbol_col].astype(str).str.strip(),
                    "open": pd.to_numeric(df["OpnPric" if "OpnPric" in df.columns else "OPEN_PRICE"], errors="coerce"),
                    "high": pd.to_numeric(df["HghPric" if "HghPric" in df.columns else "HIGH_PRICE"], errors="coerce"),
                    "low": pd.to_numeric(df["LwPric" if "LwPric" in df.columns else "LOW_PRICE"], errors="coerce"),
                    "close": pd.to_numeric(df["ClsPric" if "ClsPric" in df.columns else "CLOSE_PRICE"], errors="coerce"),
                    "volume": pd.to_numeric(df["TtlTradgVol" if "TtlTradgVol" in df.columns else "TTL_TRD_QNTY"], errors="coerce")
                }).drop_duplicates(subset=["symbol"]).dropna(subset=["symbol", "close"])
    except: return pd.DataFrame()

def fetch_mto_delivery(target_date: date) -> pd.DataFrame:
    d_mto = target_date.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{d_mto}.DAT"
    content = download_with_curl(url)
    if not content or len(content) < 1000: return pd.DataFrame(columns=["symbol", "deliv_qty", "deliv_pct"])
    rows = []
    for line in content.decode("utf-8", errors="ignore").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 7 and parts[0] == "20" and parts[3] in ["EQ", "BE", "SM"]:
            try: rows.append({"symbol": parts[2], "deliv_qty": int(parts[5]), "deliv_pct": float(parts[6])})
            except: continue
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
    if not latest_session: return
    
    for i in range(min(lookback_days, 720), -1, -1):
        target = latest_session - timedelta(days=i)
        if target.weekday() >= 5: continue
        date_iso = target.strftime("%Y-%m-%d")
        target_file = os.path.join(CSV_STORE, f"date={date_iso}", "part.csv")
        if os.path.exists(target_file) and target != latest_session: continue
        df = fetch_udiff_bhavcopy(target)
        if not df.empty:
            delivery_df = fetch_mto_delivery(target)
            merged = pd.merge(df, delivery_df, on="symbol", how="left").fillna({"deliv_qty": 0, "deliv_pct": 50.0})
            merged["date"] = date_iso
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            merged.drop_duplicates(subset=["symbol"]).to_csv(target_file, index=False)

def detect_genuine_chart_patterns(prices, volumes, highs, lows):
    n = len(prices)
    if n < 25:
        return 0.90, "", 21

    if n >= 25:
        pole_start = prices[-25]
        pole_peak = np.max(highs[-25:-7])
        flag_low = np.min(lows[-7:])
        pole_gain = (pole_peak - pole_start) / (pole_start + 1e-5)
        flag_pullback = (pole_peak - flag_low) / (pole_peak + 1e-5)
        vol_pole = np.mean(volumes[-25:-7])
        vol_flag = np.mean(volumes[-7:])
        if pole_gain >= 0.15 and flag_pullback <= 0.12 and vol_flag < vol_pole:
            return 0.55, "🚩 High-Tight Flag & Pole", 21

    if n >= 50:
        c1 = (np.max(highs[-48:-36]) - np.min(lows[-48:-36])) / (np.max(highs[-48:-36]) + 1e-5)
        c2 = (np.max(highs[-36:-24]) - np.min(lows[-36:-24])) / (np.max(highs[-36:-24]) + 1e-5)
        c3 = (np.max(highs[-24:-12]) - np.min(lows[-24:-12])) / (np.max(highs[-24:-12]) + 1e-5)
        c4 = (np.max(highs[-12:]) - np.min(lows[-12:])) / (np.max(highs[-12:]) + 1e-5)
        if c4 <= 0.085 and ((c4 < c3 and c3 < c2) or (c1 >= 0.12 and c2 >= c3)):
            return 0.55, "🎯 VCP Coiled Spring", 50

    if n >= 100:
        base_high = np.max(highs[-100:])
        base_low = np.min(lows[-100:])
        spread_100 = (base_high - base_low) / (base_low + 1e-5)
        sma_50 = np.mean(prices[-50:])
        if spread_100 <= 0.22 and prices[-1] >= sma_50:
            return 0.70, "🟢 Multi-Month Base / Cup", 100

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
    if not target_symbols: return

    ensure_metadata(target_symbols)
    found_files = glob.glob(os.path.join(CSV_STORE, "**/*.csv"), recursive=True)
    if not found_files: return

    df_all = pd.concat([pd.read_csv(f) for f in found_files], ignore_index=True).drop_duplicates(subset=["symbol", "date"])
    df_all = df_all[df_all["symbol"].isin(target_symbols)]
    master_df = pd.read_csv(METADATA_FILE).drop_duplicates(subset=["symbol"])
    df_all = pd.merge(df_all, master_df, on="symbol", how="left").fillna({"sector": "Capital Goods", "company_name": df_all["symbol"]})

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
        if sec_name == "General Equities": continue
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
        if n_bars < 15: continue

        p_series = pd.Series(prices)
        close = prices[-1]
        sma_20 = round(float(np.mean(prices[-min(20, n_bars):])), 2)
        ema_10 = float(p_series.ewm(span=10, adjust=False).mean().iloc[-1])
        ema_21 = float(p_series.ewm(span=21, adjust=False).mean().iloc[-1])
        sma_50 = round(float(p_series.rolling(min(50, n_bars)).mean().iloc[-1]), 2)
        sma_200 = round(float(p_series.rolling(min(200, n_bars)).mean().iloc[-1]), 2)

        tr_arr = np.maximum(highs[-20:] - lows[-20:], 
                            np.maximum(np.abs(highs[-20:] - np.roll(prices, 1)[-20:]), 
                                       np.abs(lows[-20:] - np.roll(prices, 1)[-20:])))
        atr_20 = float(np.mean(tr_arr))

        diffs = np.diff(prices)
        avg_g = np.mean(np.where(diffs > 0, diffs, 0)[-14:]) if len(diffs) >= 14 else 1.0
        avg_l = np.mean(np.where(diffs < 0, -diffs, 0)[-14:]) if len(diffs) >= 14 else 1.0
        rsi_14 = round(100.0 - (100.0 / (1.0 + (avg_g / (avg_l + 1e-5)))), 1)

        min_l, max_h = np.min(lows[-20:]), np.max(highs[-20:])
        stoch_k = round(float(np.clip((prices[-1] - min_l) / (max_h - min_l + 1e-5) * 100.0, 0, 100)), 1)
        
        hist, bins = np.histogram(prices[-50:], bins=10, weights=volumes[-50:])
        poc = round(float((bins[np.argmax(hist)] + bins[np.argmax(hist)+1]) / 2.0), 2)

        grp_copy = grp.copy()
        grp_copy["date_dt"] = pd.to_datetime(grp_copy["date"])
        w_df = grp_copy.set_index("date_dt").resample("W-FRI").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()
        w_closes = w_df["close"].values
        w_n = len(w_closes)
        
        if w_n >= 15:
            w_series = pd.Series(w_closes)
            w_ema10 = w_series.ewm(span=10, adjust=False).mean().iloc[-1]
            w_sma30 = w_series.rolling(min(30, w_n)).mean().iloc[-1]
            weekly_trend_bull = (w_closes[-1] >= w_ema10) and (w_ema10 >= w_sma30)
            weekly_trend_bear = (w_closes[-1] < w_sma30)
        else:
            weekly_trend_bull = close >= sma_50
            weekly_trend_bear = close < sma_50

        ma_spread_pct = ((max(ema_10, ema_21, sma_50) - min(ema_10, ema_21, sma_50)) / (close + 1e-5)) * 100.0
        is_ma_pinched = ma_spread_pct <= 2.8

        roll_20 = p_series.rolling(20)
        bb_mid = roll_20.mean().iloc[-1]
        bb_std = roll_20.std().iloc[-1]
        upper_bb = bb_mid + (2.0 * bb_std)
        lower_bb = bb_mid - (2.0 * bb_std)
        upper_kc = sma_20 + (1.5 * atr_20)
        lower_kc = sma_20 - (1.5 * atr_20)
        is_squeezed = (upper_bb <= upper_kc) and (lower_bb >= lower_kc)

        vol_5d = np.mean(volumes[-5:])
        vol_50d = np.mean(volumes[-min(50, n_bars):]) + 1e-5
        is_vdu = (vol_5d < 0.65 * vol_50d) and ((highs[-1] - lows[-1]) <= 0.85 * atr_20)

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

        if n_bars >= 11:
            diffs_10 = np.diff(prices[-11:])
            down_vols = volumes[-10:][diffs_10 < 0]
            max_down_vol = np.max(down_vols) if len(down_vols) > 0 else 0
            is_pocket_pivot = (close > prices[-2]) and (volumes[-1] > max_down_vol) and (close >= ema_10)
        else:
            is_pocket_pivot = False

        if n_bars >= 15:
            recent_low = np.min(lows[-15:-2])
            ob_zone_high = recent_low + (1.2 * atr_20)
            is_ob_retest = (lows[-1] <= ob_zone_high) and (close >= recent_low) and (volumes[-1] < vol_50d)
        else:
            is_ob_retest = False

        base_high = np.max(highs[-min(30, n_bars):])
        base_low = np.min(lows[-min(30, n_bars):])
        base_depth_pct = ((base_high - base_low) / (base_high + 1e-5)) * 100.0
        is_tight_base = base_depth_pct <= 22.0
        dist_from_20 = (close - sma_20) / (sma_20 + 1e-5)
        dist_from_50 = (close - sma_50) / (sma_50 + 1e-5)
        is_not_extended = dist_from_50 <= 0.08 and dist_from_20 <= 0.05
        is_extended_danger = dist_from_20 > 0.08

        stk_ret_21 = (close / (prices[-min(21, n_bars)] + 1e-5)) - 1.0
        stk_ret_63 = (close / (prices[-min(63, n_bars)] + 1e-5)) - 1.0
        stk_ret_126 = (close / (prices[-min(126, n_bars)] + 1e-5)) - 1.0
        stk_ret_250 = (close / (prices[0] + 1e-5)) - 1.0
        rs_spread_21 = (stk_ret_21 - bm_ret_21) * 100.0
        rs_spread_63 = (stk_ret_63 - bm_ret_63) * 100.0
        rs_spread_126 = (stk_ret_126 - bm_ret_126) * 100.0
        rs_spread_250 = (stk_ret_250 - bm_ret_250) * 100.0
        raw_multi_rs = (0.40 * rs_spread_63) + (0.30 * rs_spread_126) + (0.20 * rs_spread_250) + (0.10 * rs_spread_21)

        vcp_rat, pattern, pattern_tf = detect_genuine_chart_patterns(prices, volumes, highs, lows)

        if len(diffs) >= 1:
            up_vol = np.sum(volumes[1:][diffs > 0][-50:]) if np.any(diffs > 0) else 1.0
            down_vol = np.sum(volumes[1:][diffs < 0][-50:]) if np.any(diffs < 0) else 1.0
            up_down_ratio = round(float(up_vol / (down_vol + 1e-5)), 2)
        else:
            up_down_ratio = 1.0

        sma_200_20d_ago = np.mean(prices[-min(220, n_bars):-20]) if n_bars >= 30 else sma_200
        sma_200_slope = (sma_200 - sma_200_20d_ago) / (sma_200_20d_ago + 1e-5)
        h_52 = np.max(highs)
        l_52 = np.min(lows)
        trend_score = 0.0
        if close > sma_200: trend_score += 25.0
        if close > sma_50: trend_score += 25.0
        if sma_50 > sma_200: trend_score += 20.0
        if sma_200_slope >= 0: trend_score += 10.0
        if (close / (h_52 + 1e-5)) >= 0.75: trend_score += 10.0
        if (close / (l_52 + 1e-5)) >= 1.25: trend_score += 10.0

        deliv_cash_all = deliv_qtys[-min(30, n_bars):] * prices[-min(30, n_bars):]
        diffs_deliv = diffs[-min(29, len(diffs)):]
        deliv_up = np.sum(deliv_cash_all[1:][diffs_deliv > 0]) if np.any(diffs_deliv > 0) else 1.0
        deliv_down = np.sum(deliv_cash_all[1:][diffs_deliv < 0]) if np.any(diffs_deliv < 0) else 1.0
        deliv_flow_ratio = float(deliv_up / (deliv_down + 1e-5))

        squeeze_component = 40.0 if is_squeezed else (20.0 if is_ma_pinched else 5.0)
        flow_component = np.clip((deliv_flow_ratio / 1.5) * 35.0, 5.0, 35.0)
        base_component = 25.0 if (is_tight_base and close >= sma_50) else 5.0
        
        raw_iasis = squeeze_component + flow_component + base_component
        if close < sma_200 and close < sma_50:
            iasis_score = round(float(min(32.0, raw_iasis * 0.35)), 1)
        else:
            iasis_score = round(float(np.clip(raw_iasis, 10.0, 99.0)), 1)

        if (is_rs_divergent or is_sec_rs_divergent) and (is_squeezed or is_vdu):
            mtf_status = "🎯 RS Pre-Breakout Divergence"
        elif is_pocket_pivot and (is_squeezed or is_ma_pinched):
            mtf_status = "🚀 MA Pinch + Pocket Pivot"
        elif is_squeezed and is_tight_base and weekly_trend_bull:
            mtf_status = "⚡ Weekly+Daily Squeeze Coil"
        elif is_ma_pinched and is_tight_base and weekly_trend_bull:
            mtf_status = "🗜️ Tight MA Compression Base"
        elif weekly_trend_bull and close > sma_50 and sma_50 > sma_200:
            mtf_status = "🟢 Stage 2 Trend Template"
        elif weekly_trend_bear:
            mtf_status = "🔴 Macro Downtrend (Avoid)"
        else:
            mtf_status = "—"

        risk_unit = max(1.0, 1.5 * atr_20)
        target_dist = max(base_depth_pct / 100.0 * close, 2.5 * atr_20)
        rrr_calc = round(min(8.0, max(1.5, target_dist / risk_unit)), 1)

        reasons_to_avoid = []
        if close < sma_200:
            reasons_to_avoid.append("Price trading below 200-day SMA (heavy overhead supply)")
        if close < sma_50:
            reasons_to_avoid.append("Price below intermediate 50-day SMA (intermediate downtrend)")
        if is_extended_danger:
            reasons_to_avoid.append("Price extended >8% above 20 SMA (high risk of mean-reversion pullback)")
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
            "symbol": sym, "sma_20": sma_20, "sma_50": sma_50, "sma_200": sma_200,
            "ema_10": ema_10, "ema_21": ema_21,
            "rsi_14": rsi_14, "stoch_k": stoch_k, "volume_profile_poc": poc,
            "multi_timeframe_confluence": mtf_status,
            "chart_pattern_signal": pattern, "pattern_timeframe": pattern_tf,
            "rs_line_status": "🔥 RS Line New High" if (rs_is_new_high or is_rs_divergent) else "Normal RS",
            "sector_rs_status": sector_rs_status,
            "order_block_status": "⚡ Demand Zone Retest (Light Vol)" if is_ob_retest else "",
            "avg_deliv_20": np.mean(deliv_qtys[-min(20, n_bars):]),
            "atr_20": atr_20, "vcp_ratio_calc": vcp_rat,
            "iasis_score": iasis_score, "raw_multi_rs": raw_multi_rs, "trend_score": trend_score,
            "up_down_vol_ratio": up_down_ratio, 
            "smooth_deliv_expansion": round(float(deliv_flow_ratio), 2),
            "smooth_deliv_pct": round(float(np.mean(deliv_pcts[-min(20, n_bars):])), 1),
            "high_52w": h_52, "low_52w": l_52, "risk_reward_calc": rrr_calc,
            "is_pocket_pivot": is_pocket_pivot, "is_squeezed": is_squeezed,
            "is_ma_pinched": is_ma_pinched, "is_rs_divergent": (is_rs_divergent or is_sec_rs_divergent),
            "is_not_extended": is_not_extended, "flow_ratio": deliv_flow_ratio,
            "dist_from_20": dist_from_20, "is_ob_retest": is_ob_retest,
            "reasons_to_avoid": "; ".join(reasons_to_avoid) if reasons_to_avoid else "None. Technical structure remains constructive."
        })

    with open(PRICE_HISTORY_JSON, "w") as f: json.dump(price_history_map, f)

    ranked = pd.merge(latest_df, pd.DataFrame(stock_tech_rows), on="symbol", how="inner").drop_duplicates(subset=["symbol"])
    ranked["d_expansion"] = ranked["smooth_deliv_expansion"]
    ranked["deliv_spike"] = (ranked["deliv_qty"] / (ranked["avg_deliv_20"] + 1)).round(2)
    ranked["vcp_ratio"] = ranked["vcp_ratio_calc"]
    ranked["mrs_score"] = (((ranked["close"] / (ranked["sma_20"] + 1e-5)) - 1.0) * 100.0).round(1)
    ranked["absorption_ratio"] = (((ranked["deliv_qty"] * ranked["close"]) / 10000000.0) / (ranked["high"] - ranked["low"] + 0.05)).round(2)
    ranked["atr_stop_loss"] = (ranked["close"] - (1.5 * ranked["atr_20"])).round(2)
    ranked["above_sma20"] = ranked["close"] >= ranked["sma_20"]
    ranked["above_sma50"] = ranked["close"] >= ranked["sma_50"]
    ranked["turnover_cr"] = ((ranked["volume"].fillna(0) * ranked["close"]) / 10000000.0).round(2)

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
    
    sector_summary["rs_20d"] = sector_summary["perf_20d"]
    sector_summary["rs_63d"] = sector_summary["perf_63d"]
    sector_summary["breadth_pct"] = sector_summary["above_sma_pct"]

    rs_63_pct = sector_summary["rs_63d"].rank(pct=True) * 100.0
    breadth_pct = sector_summary["breadth_pct"]
    rs_20_pct = sector_summary["rs_20d"].rank(pct=True) * 100.0

    sector_summary["sector_composite_score"] = (
        (0.40 * rs_63_pct) + (0.35 * breadth_pct) + (0.25 * rs_20_pct)
    ).round(2)

    sector_summary["rs_ratio"] = (100.0 + sector_summary["perf_20d"] * 0.35).round(2)
    sector_summary["rs_momentum"] = (100.0 + (sector_summary["advance_pct"] - 50.0) * 0.1).round(2)
    sector_summary["quadrant"] = sector_summary.apply(
        lambda r: "Leading"
        if r["rs_ratio"] >= 100 and r["rs_momentum"] >= 100
        else ("Improving" if r["rs_ratio"] < 100 and r["rs_momentum"] >= 100 else ("Weakening" if r["rs_ratio"] >= 100 else "Lagging")),
        axis=1,
    )

    sector_perf_map = dict(zip(sector_summary["sector"], sector_summary["perf_20d"]))
    sector_quad_map = dict(zip(sector_summary["sector"], sector_summary["quadrant"]))

    ranked["above_200sma"] = ranked["close"] >= ranked["sma_200"]
    ranked["beta_neutral_mrs"] = (ranked["mrs_score"] - ranked["sector"].map(lambda s: sector_perf_map.get(s, 0.0))).round(1)
    ranked["sector_breadth_status"] = ranked["sector"].map(lambda s: sector_quad_map.get(s, "Neutral"))
    ranked["risk_reward_ratio"] = ranked["risk_reward_calc"]
    ranked["market_breadth_status"] = "🟢 Bullish Regime" if ((latest_df["close"] > latest_df["open"]).mean() * 100.0) >= 50.0 else "🔴 Bearish Regime"

    rs_percentile = (ranked["raw_multi_rs"].rank(pct=True) * 100.0).round(1)
    up_down_pct = (ranked["up_down_vol_ratio"].rank(pct=True) * 100.0).round(1)

    ignition_raw = (
        np.where(ranked["is_squeezed"], 30.0, 10.0) +
        np.where(ranked["is_ma_pinched"], 25.0, 5.0) +
        np.where(ranked["vcp_ratio"] <= 0.55, 25.0, 10.0) +
        np.where(ranked["is_rs_divergent"], 20.0, 0.0)
    )
    ranked["ignition_score"] = np.where(ranked["mrs_score"] > 5.0, ignition_raw * 0.35, ignition_raw).clip(5.0, 99.0).round(1)

    leader_trend = np.where(ranked["close"] > ranked["sma_50"], 40.0, 15.0)
    leader_rs = (rs_percentile * 0.35)
    leader_vol = (up_down_pct * 0.25)
    ranked["frontrunner_score"] = (leader_trend + leader_rs + leader_vol).clip(5.0, 99.0).round(1)

    def get_signal(r):
        c_pattern = r["chart_pattern_signal"]
        if r["mrs_score"] > 8.0: 
            return "⚠️ Extended (Wait for Dip)"
        if r["is_pocket_pivot"] and (r["is_squeezed"] or r["is_ma_pinched"]): 
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
        if 0.0 <= r["mrs_score"] <= 3.5 and 45 <= r["rsi_14"] <= 65 and r["above_200sma"]: 
            return "🟢 Low-Risk Buy Zone"
        if r["frontrunner_score"] >= 80.0:
            return "🔥 Momentum Frontrunner"
        return "Consolidation / Base"

    ranked["inst_signal"] = ranked.apply(get_signal, axis=1)
    ranked = ranked.sort_values(by="ignition_score", ascending=False).drop_duplicates(subset=["symbol"]).reset_index(drop=True)

    output_stocks = []
    seen = set()
    for _, r in ranked.iterrows():
        sym = str(r["symbol"])
        if sym in seen: continue
        seen.add(sym)
        
        def clean(val, is_str=False):
            if pd.isna(val) or val is None: return None if not is_str else "NA"
            if is_str: return str(val)
            try:
                f = float(val)
                return None if np.isnan(f) else round(f, 2)
            except: return val

        output_stocks.append({
            "symbol": sym, 
            "company_name": clean(r.get("company_name", sym), True),
            "sector": clean(r.get("sector", "Capital Goods"), True), 
            "industry": clean(r.get("industry", r.get("sector", "General Equities")), True),
            "index_name": clean(r.get("index_name", "Nifty 500"), True), 
            "close": clean(r.get("close")),
            "sma_20": clean(r.get("sma_20")), 
            "sma_50": clean(r.get("sma_50")), 
            "sma_200": clean(r.get("sma_200")),
            "rsi_14": clean(r.get("rsi_14")), 
            "stoch_k": clean(r.get("stoch_k")),
            "atr_stop_loss": clean(r.get("atr_stop_loss")), 
            "volume_profile_poc": clean(r.get("volume_profile_poc")),
            "multi_timeframe_confluence": clean(r.get("multi_timeframe_confluence", "—"), True),
            "fundamental_score": None, "fundamental_grade": "Unrated",
            "fundamental_rationale": "Pending fundamental sync.", 
            "roe": None, "profit_growth_yoy": None, "trailing_pe": None, "forward_pe": None, 
            "promoter_pledging": None, "debt_to_equity": None, 
            "promoter_pct": "NA", "fii_pct": "NA", "dii_pct": "NA", 
            "fii_change_qoq": "NA", "dii_change_qoq": "NA", 
            "fii_dii_trend": "Promoters: NA, FII: NA, DII: NA", 
            "fcf_yield": None, "earnings_revision": "NA",
            "chart_pattern_signal": clean(r.get("chart_pattern_signal", ""), True) if pd.notna(r.get("chart_pattern_signal")) else "",
            "pattern_timeframe": int(r.get("pattern_timeframe", 21)),
            "rs_line_status": clean(r.get("rs_line_status", "Normal RS"), True),
            "sector_rs_status": clean(r.get("sector_rs_status", "🟢 Outperforming Sector"), True),
            "order_block_status": clean(r.get("order_block_status", ""), True),
            "risk_reward_ratio": clean(r.get("risk_reward_ratio")), 
            "market_breadth_status": clean(r.get("market_breadth_status", "🟢 Bullish Regime"), True),
            "sector_breadth_status": clean(r.get("sector_breadth_status", "Improving"), True), 
            "next_earnings_date": "N/A",
            "deliv_pct": clean(r.get("deliv_pct")), 
            "deliv_spike": clean(r.get("deliv_spike")), 
            "d_expansion": clean(r.get("d_expansion")),
            "vcp_ratio": clean(r.get("vcp_ratio")), 
            "absorption_ratio": clean(r.get("absorption_ratio")), 
            "turnover_cr": clean(r.get("turnover_cr")),
            "mrs_score": clean(r.get("mrs_score")), 
            "beta_neutral_mrs": clean(r.get("beta_neutral_mrs")), 
            "inst_signal": clean(r.get("inst_signal", "Consolidation"), True),
            "ignition_score": clean(r.get("ignition_score")),
            "frontrunner_score": clean(r.get("frontrunner_score")),
            "iasis_score": clean(r.get("iasis_score")),
            "up_down_vol_ratio": clean(r.get("up_down_vol_ratio")),
            "trend_score": clean(r.get("trend_score")),
            "reasons_to_avoid": clean(r.get("reasons_to_avoid", ""), True)
        })

    payload = {
        "as_of_date": str(latest_date), 
        "page_size": 50,
        "total_stocks": len(output_stocks), 
        "total_pages": (len(output_stocks) + 49) // 50,
        "sectors": sector_summary.to_dict(orient="records"), 
        "sector_rs_history": sector_rs_history, 
        "stocks": output_stocks
    }

    with open(OUTPUT_JSON, "w") as f: 
        json.dump(payload, f, indent=2)
        
    print(f"[✓] Pipeline complete. Processed {len(output_stocks)} official stocks.")

if __name__ == "__main__":
    run_screener_engine()