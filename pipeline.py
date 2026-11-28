import glob
import io
import json
import os
import subprocess
import time
import zipfile
from datetime import date, datetime, timedelta
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_STORE = os.path.join(DATA_DIR, "csv_store")
METADATA_FILE = os.path.join(DATA_DIR, "metadata_master.csv")
DNA_PROFILES_CSV = os.path.join(DATA_DIR, "stock_dna_profiles.csv")
ACTIVE_LEDGER_FILE = os.path.join(DATA_DIR, "active_trades_ledger.json")
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

def load_stock_dna_profiles(max_age_days: int = 5) -> pd.DataFrame:
    needs_build = not os.path.exists(DNA_PROFILES_CSV)
    if not needs_build:
        age_days = (time.time() - os.path.getmtime(DNA_PROFILES_CSV)) / 86400.0
        if age_days > max_age_days:
            needs_build = True

    if needs_build:
        print("[*] Refreshing 500-Day Structural Stock DNA Genome via build_stock_dna.py...")
        try:
            from build_stock_dna import build_comprehensive_stock_dna
            build_comprehensive_stock_dna()
        except Exception as e:
            print(f"[!] Stock DNA refresh warning: {e}")

    if not os.path.exists(DNA_PROFILES_CSV):
        return pd.DataFrame(columns=["symbol"])

    dna_df = pd.read_csv(DNA_PROFILES_CSV).drop_duplicates(subset=["symbol"])
    keep_cols = [
        "symbol", "dna_archetype", "stock_dna_score", "dominant_ma_dna",
        "wick_polarity_dna", "impulse_velocity_days", "amihud_impact_dna",
        "reentry_elasticity_pct", "beta_asymmetry", "median_er_30"
    ]
    avail_cols = [c for c in keep_cols if c in dna_df.columns]
    return dna_df[avail_cols].copy()


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
                industry = str(r[ind_col]).strip() if ind_col and pd.notna(r[ind_col]) else "Unclassified"
                if sym not in symbol_to_meta:
                    symbol_to_meta[sym] = {"indices": [index_name], "company_name": cname, "sector": industry}
                else:
                    if index_name not in symbol_to_meta[sym]["indices"]:
                        symbol_to_meta[sym]["indices"].append(index_name)
        except Exception:
            pass

    for sym in NIFTY_50_SYMBOLS:
        if sym in symbol_to_meta:
            if "Nifty 50" not in symbol_to_meta[sym]["indices"]:
                symbol_to_meta[sym]["indices"].insert(0, "Nifty 50")
            if "Nifty 500" not in symbol_to_meta[sym]["indices"]:
                symbol_to_meta[sym]["indices"].append("Nifty 500")
        else:
            symbol_to_meta[sym] = {"indices": ["Nifty 50", "Nifty 500"], "company_name": sym, "sector": "Unclassified"}

    for sym in NIFTY_NEXT_50_SYMBOLS:
        if sym in symbol_to_meta:
            if "Nifty Next 50" not in symbol_to_meta[sym]["indices"]:
                symbol_to_meta[sym]["indices"].insert(0, "Nifty Next 50")
            if "Nifty 500" not in symbol_to_meta[sym]["indices"]:
                symbol_to_meta[sym]["indices"].append("Nifty 500")
        else:
            symbol_to_meta[sym] = {"indices": ["Nifty Next 50", "Nifty 500"], "company_name": sym, "sector": "Unclassified"}

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
            merged = pd.merge(df, delivery_df, on="symbol", how="left")
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
        
        # Forward fill delivery data instead of using placeholders
        g["deliv_qty"] = g["deliv_qty"].ffill().fillna(0)
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

    if sym_up in NIFTY_50_SYMBOLS or sym_up in NIFTY_NEXT_50_SYMBOLS or "NIFTY 50" in tokens or "NIFTY NEXT 50" in tokens:
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


def sync_active_trades_ledger(df_all, ranked_today, newly_triggered_symbols, latest_date):
    ledger = {}
    if os.path.exists(ACTIVE_LEDGER_FILE):
        try:
            with open(ACTIVE_LEDGER_FILE, "r", encoding="utf-8") as f:
                ledger = json.load(f)
        except Exception:
            pass

    today_lookup = ranked_today.set_index("symbol").to_dict(orient="index")

    for sym in newly_triggered_symbols:
        if sym not in ledger and sym in today_lookup:
            r = today_lookup[sym]
            ep = float(r["close"])
            is_t1 = "Tier 1" in str(r.get("mcap_tier", ""))
            ledger[sym] = {
                "symbol": sym,
                "entry_date": str(latest_date),
                "entry_price": round(ep, 2),
                "target_price": round(float(r["target_price"]), 2),
                "tranche2_breakout_price": round(float(r["tranche2_breakout_price"]), 2),
                "stop_loss_price": round(float(r["stop_loss_price"]), 2),
                "shield_trigger_price": round(ep * (1.04 if is_t1 else 1.045), 2),
                "shield_floor_price": round(float(r["stage1_lock_price"]), 2),
                "inst_signal": str(r.get("inst_signal", "📉 High-RS Pullback")),
                "trigger_reason": str(r.get("trigger_reason", "Pocket Pivot Ignition Fired")),
                "status": "OPEN",
            }

    active_meta_map = {}
    active_syms = [s for s, pos in ledger.items() if pos.get("status") == "OPEN"]
    
    if active_syms:
        all_hist = df_all[df_all["symbol"].isin(active_syms)].copy()
        all_hist = all_hist.sort_values(by=["symbol", "date"]).reset_index(drop=True)
        grp = all_hist.groupby("symbol")
        all_hist["ema10"] = grp["close"].transform(lambda x: x.ewm(span=10, adjust=False).mean())
        all_hist["sma50"] = grp["close"].transform(lambda x: x.rolling(50, min_periods=10).mean())
        all_hist["prev_ema10"] = grp["ema10"].shift(1)
        all_hist["prev_sma50"] = grp["sma50"].shift(1)

        for sym, pos in list(ledger.items()):
            if pos.get("status") != "OPEN":
                continue

            entry_date = str(pos["entry_date"])
            entry_price = float(pos["entry_price"])
            t1_price = float(pos["target_price"])
            t2_price = float(pos["tranche2_breakout_price"])
            sl_price = float(pos["stop_loss_price"])

            cur_meta = today_lookup.get(sym, {})
            is_t1_pos = (sym in NIFTY_50_SYMBOLS) or (sym in NIFTY_NEXT_50_SYMBOLS) or ("Tier 1" in str(cur_meta.get("mcap_tier", "")))
            risk_clamp_pct_pos = round(((sl_price - entry_price) / max(entry_price, 1e-5)) * 100.0, 2)
            if is_t1_pos:
                hard_1d_price = round(entry_price * 0.935, 2)
                intraday_cat_price = round(entry_price * 0.925, 2)
                shield1_trig, shield1_lock = 4.0, 0.8
                shield2_trig, shield2_lock = 6.0, 3.0
            else:
                hard_1d_price = round(entry_price * (1.0 + ((risk_clamp_pct_pos - 1.5) / 100.0)), 2)
                intraday_cat_price = round(entry_price * (1.0 + ((risk_clamp_pct_pos - 2.5) / 100.0)), 2)
                shield1_trig, shield1_lock = 4.5, 1.0
                shield2_trig, shield2_lock = 7.5, 4.0

            sym_hist = all_hist[(all_hist["symbol"] == sym) & (all_hist["date"] >= entry_date)]
            if sym_hist.empty:
                continue

            days_held = max(0, len(sym_hist) - 1)
            is_closed = False
            t1_booked = False
            active_shield_lock = None
            consec_sl = 0
            consec_trail_breaks = 0
            peak_high = entry_price

            for idx in range(1, len(sym_hist)):
                row_b = sym_hist.iloc[idx]
                o_v = float(row_b["open"])
                h_v = float(row_b["high"])
                l_v = float(row_b["low"])
                c_v = float(row_b["close"])
                e10_v = float(row_b["prev_ema10"]) if pd.notna(row_b["prev_ema10"]) else c_v
                s50_v = float(row_b["prev_sma50"]) if pd.notna(row_b["prev_sma50"]) else c_v * 0.94

                if not t1_booked and (o_v <= intraday_cat_price or o_v <= sl_price):
                    is_closed = True
                    break

                if not t1_booked:
                    consec_sl = (consec_sl + 1) if c_v <= sl_price else 0
                    if consec_sl >= 2 or c_v <= hard_1d_price or l_v <= intraday_cat_price:
                        is_closed = True
                        break
                    if active_shield_lock is not None:
                        shield_price = round(entry_price * (1.0 + (active_shield_lock / 100.0)), 2)
                        if (c_v <= shield_price and c_v < e10_v) or (c_v <= entry_price and c_v < e10_v):
                            is_closed = True
                            break
                    if h_v > peak_high:
                        peak_high = h_v
                    peak_gain_now = ((peak_high - entry_price) / entry_price) * 100.0

                    if h_v >= t1_price:
                        t1_booked = True
                        if h_v >= t2_price:
                            is_closed = True
                            break
                        continue

                    if peak_gain_now >= shield2_trig:
                        active_shield_lock = shield2_lock
                    elif peak_gain_now >= shield1_trig:
                        active_shield_lock = shield1_lock
                else:
                    if h_v > peak_high:
                        peak_high = h_v
                    peak_gain_now = ((peak_high - entry_price) / entry_price) * 100.0

                    if h_v >= t2_price:
                        is_closed = True
                        break
                    t2_locked_pct = 15.0 if peak_gain_now >= 24.0 else (8.0 if peak_gain_now >= 16.0 else 2.5)
                    t2_floor_price = entry_price * (1.0 + (t2_locked_pct / 100.0))

                    consec_trail_breaks = (consec_trail_breaks + 1) if (c_v < (s50_v * 0.985) or c_v < t2_floor_price) else 0
                    if consec_trail_breaks >= 2 or c_v < t2_floor_price:
                        is_closed = True
                        break

            if is_closed:
                pos["status"] = "CLOSED"
                pos["exit_date"] = str(latest_date)
                continue

            cur_row = today_lookup.get(sym, {})
            cur_close = float(cur_row.get("close", sym_hist.iloc[-1]["close"]))
            cur_sma20 = float(cur_row.get("sma_20", cur_close))
            cur_sma50 = float(cur_row.get("sma_50", cur_close))
            cur_poc = float(cur_row.get("volume_profile_poc", cur_close))
            unrealized_pct = round(((cur_close - entry_price) / entry_price) * 100.0, 2)
            dist_20_pct = ((cur_close - cur_sma20) / (cur_sma20 + 1e-5)) * 100.0

            is_fresh_today = (entry_date == str(latest_date))

            if is_fresh_today:
                lifecycle_status = "NEW_TRIGGER_TODAY"
                lifecycle_badge = "🔥 Fresh EOD Signal (Enter Today)"
                can_still_enter = True
                late_entry_note = "✅ Fresh Trigger — Valid Entry Zone"
            else:
                lifecycle_status = "ONGOING_ACTIVE"
                lifecycle_badge = f"🟢 Trading Ongoing ({days_held}d | {unrealized_pct:+.1f}%)"

                if t1_booked:
                    can_still_enter = False
                    late_entry_note = "🚫 50% Target Hit — Runner Mode Only (Do Not Enter)"
                elif (-2.5 <= unrealized_pct <= 3.5) and (dist_20_pct <= 4.0) and (cur_close >= cur_sma50 * 0.985) and (cur_close >= cur_poc * 0.99):
                    can_still_enter = True
                    late_entry_note = f"✅ Still Actionable — In Buy Zone ({unrealized_pct:+.1f}% from ₹{entry_price:.2f})"
                elif unrealized_pct > 3.5 or dist_20_pct > 4.0:
                    can_still_enter = False
                    late_entry_note = f"⚠️ Extended (+{unrealized_pct:.1f}%) — Hold Only, Wait for Dip"
                else:
                    can_still_enter = False
                    late_entry_note = f"⏳ Testing Support ({unrealized_pct:+.1f}%) — Hold With ₹{sl_price:.2f} Stop"

            active_meta_map[sym] = {
                "trade_lifecycle_status": lifecycle_status,
                "trade_lifecycle_badge": lifecycle_badge,
                "can_still_enter": can_still_enter,
                "late_entry_note": late_entry_note,
                "logged_entry_date": entry_date,
                "logged_entry_price": entry_price,
                "days_held_live": days_held,
                "unrealized_pnl_pct": unrealized_pct,
                "t1_booked_live": t1_booked,
            }

    with open(ACTIVE_LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)

    return active_meta_map


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
    df_all = pd.merge(df_all, master_df, on="symbol", how="inner")
    df_all = df_all[df_all["sector"] != "Unclassified"].sort_values(by=["symbol", "date"]).reset_index(drop=True)
    
    if "deliv_qty" in df_all.columns:
        missing_delivery = df_all[df_all["deliv_qty"].isna() | (df_all["deliv_qty"] == 0)]
        if not missing_delivery.empty:
            with open("missing_delivery_data.log", "a") as f:
                f.write(f"Missing delivery data for {len(missing_delivery)} rows.\n")

    df_all, corp_events = normalize_corporate_actions(df_all)
    print(f"[*] Normalized {len(corp_events)} corporate events.")

    dna_df = load_stock_dna_profiles(max_age_days=5)
    print(f"[*] Loaded Stock DNA Genome for {len(dna_df)} symbols.")

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

    df_250d_all = df_all[df_all["date"].isin(dates[-250:])].sort_values(by=["symbol", "date"]).copy()
    
    market_pivot = df_250d_all.pivot(index="date", columns="symbol", values="close").ffill().dropna(how="all")
    market_benchmark = market_pivot.mean(axis=1)

    sector_benchmarks = {}
    sector_rs_history = {}
    for sec_name, sec_grp in df_250d_all.groupby("sector"):
        if sec_name == "Unclassified":
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
    
    print("[*] Performing vectorized technical computations...")
    grouped = df_250d_all.groupby("symbol")
    
    df_250d_all["sma_20"] = grouped["close"].transform(lambda x: x.rolling(20, min_periods=10).mean())
    df_250d_all["ema_10"] = grouped["close"].transform(lambda x: x.ewm(span=10, adjust=False).mean())
    df_250d_all["ema_21"] = grouped["close"].transform(lambda x: x.ewm(span=21, adjust=False).mean())
    df_250d_all["sma_50"] = grouped["close"].transform(lambda x: x.rolling(50, min_periods=20).mean())
    df_250d_all["sma_200"] = grouped["close"].transform(lambda x: x.rolling(200, min_periods=40).mean())
    
    df_250d_all["prev_c"] = grouped["close"].shift(1).fillna(df_250d_all["close"])
    df_250d_all["prev_h"] = grouped["high"].shift(1)
    df_250d_all["prev_l"] = grouped["low"].shift(1)
    df_250d_all["prev2_h"] = grouped["high"].shift(1).rolling(2, min_periods=1).max()
    df_250d_all["prev2_l"] = grouped["low"].shift(1).rolling(2, min_periods=1).min()
    
    df_250d_all["sma20_10d_ago"] = grouped["sma_20"].shift(10)
    df_250d_all["sma50_10d_ago"] = grouped["sma_50"].shift(10)
    df_250d_all["sma50_20d_ago"] = grouped["sma_50"].shift(20)
    df_250d_all["sma20_slope_10d"] = ((df_250d_all["sma_20"] - df_250d_all["sma20_10d_ago"]) / (df_250d_all["sma20_10d_ago"] + 1e-5)) * 100.0
    df_250d_all["sma50_slope_20d"] = ((df_250d_all["sma_50"] - df_250d_all["sma50_20d_ago"]) / (df_250d_all["sma50_20d_ago"] + 1e-5)) * 100.0
    df_250d_all["sma_50_rising"] = df_250d_all["sma_50"] >= (df_250d_all["sma50_10d_ago"] * 0.998)
    
    df_250d_all["tr"] = np.maximum(df_250d_all["high"] - df_250d_all["low"], 
                              np.maximum(np.abs(df_250d_all["high"] - df_250d_all["prev_c"]), 
                                         np.abs(df_250d_all["low"] - df_250d_all["prev_c"])))
    df_250d_all["atr_20"] = grouped["tr"].transform(lambda x: x.rolling(20, min_periods=10).mean())
    df_250d_all["atr_pct"] = (df_250d_all["atr_20"] / (df_250d_all["close"] + 1e-5)) * 100.0
    
    df_250d_all["vol_20"] = grouped["volume"].transform(lambda x: x.rolling(20, min_periods=10).mean()) + 1e-5
    df_250d_all["prior_2d_rng"] = ((df_250d_all["prev2_h"] - df_250d_all["prev2_l"]) / (df_250d_all["prev_c"] + 1e-5)) * 100.0
    df_250d_all["prior_quiet"] = (grouped["volume"].shift(1) <= df_250d_all["vol_20"] * 1.08) | (df_250d_all["prior_2d_rng"] <= 6.0)
    df_250d_all["session_rvol"] = df_250d_all["volume"] / df_250d_all["vol_20"]
    df_250d_all["cr"] = (df_250d_all["close"] - df_250d_all["low"]) / (df_250d_all["high"] - df_250d_all["low"] + 1e-5)
    
    df_250d_all["diff"] = df_250d_all["close"] - df_250d_all["prev_c"]
    df_250d_all["gain"] = np.where(df_250d_all["diff"] > 0, df_250d_all["diff"], 0.0)
    df_250d_all["loss"] = np.where(df_250d_all["diff"] < 0, -df_250d_all["diff"], 0.0)
    df_250d_all["avg_gain"] = grouped["gain"].transform(lambda x: x.rolling(14, min_periods=5).mean())
    df_250d_all["avg_loss"] = grouped["loss"].transform(lambda x: x.rolling(14, min_periods=5).mean())
    df_250d_all["rsi_14"] = 100.0 - (100.0 / (1.0 + (df_250d_all["avg_gain"] / (df_250d_all["avg_loss"] + 1e-5))))
    df_250d_all["rsi_10d_chg"] = df_250d_all["rsi_14"] - grouped["rsi_14"].shift(10)
    
    df_250d_all["low_20"] = grouped["low"].transform(lambda x: x.rolling(20, min_periods=5).min())
    df_250d_all["high_20"] = grouped["high"].transform(lambda x: x.rolling(20, min_periods=5).max())
    df_250d_all["stoch_k"] = np.clip(((df_250d_all["close"] - df_250d_all["low_20"]) / (df_250d_all["high_20"] - df_250d_all["low_20"] + 1e-5)) * 100.0, 0.0, 100.0)
    
    df_250d_all["high_30"] = grouped["high"].transform(lambda x: x.rolling(30, min_periods=10).max())
    df_250d_all["low_30"] = grouped["low"].transform(lambda x: x.rolling(30, min_periods=10).min())
    df_250d_all["base_depth_pct"] = ((df_250d_all["high_30"] - df_250d_all["low_30"]) / (df_250d_all["high_30"] + 1e-5)) * 100.0
    
    df_250d_all["high_52w"] = grouped["high"].transform(lambda x: x.rolling(250, min_periods=40).max())
    df_250d_all["low_52w"] = grouped["low"].transform(lambda x: x.rolling(250, min_periods=40).min())
    df_250d_all["pct_of_52w_high"] = (df_250d_all["close"] / (df_250d_all["high_52w"] + 1e-5)) * 100.0
    
    df_250d_all["dist_from_20"] = (df_250d_all["close"] - df_250d_all["sma_20"]) / (df_250d_all["sma_20"] + 1e-5)
    df_250d_all["mrs_score"] = df_250d_all["dist_from_20"] * 100.0
    df_250d_all["dist_from_50_pct"] = ((df_250d_all["close"] - df_250d_all["sma_50"]) / (df_250d_all["sma_50"] + 1e-5)) * 100.0
    df_250d_all["dist_from_200_pct"] = ((df_250d_all["close"] - df_250d_all["sma_200"]) / (df_250d_all["sma_200"] + 1e-5)) * 100.0

    df_250d_all["vol_5"] = grouped["volume"].transform(lambda x: x.rolling(5, min_periods=2).mean())
    df_250d_all["vol_50"] = grouped["volume"].transform(lambda x: x.rolling(50, min_periods=15).mean()) + 1e-5
    df_250d_all["vol_dryup_ratio"] = df_250d_all["vol_5"] / df_250d_all["vol_50"]
    
    df_250d_all["up_v"] = np.where(df_250d_all["diff"] > 0, df_250d_all["volume"], 0.0)
    df_250d_all["dn_v"] = np.where(df_250d_all["diff"] < 0, df_250d_all["volume"], 0.0)
    df_250d_all["up_v_50"] = grouped["up_v"].transform(lambda x: x.rolling(50, min_periods=15).sum()) + 1.0
    df_250d_all["dn_v_50"] = grouped["dn_v"].transform(lambda x: x.rolling(50, min_periods=15).sum()) + 1.0
    df_250d_all["up_down_ratio"] = df_250d_all["up_v_50"] / df_250d_all["dn_v_50"]
    
    df_250d_all["up_v_15"] = grouped["up_v"].transform(lambda x: x.rolling(15, min_periods=5).sum()) + 1.0
    df_250d_all["dn_v_15"] = grouped["dn_v"].transform(lambda x: x.rolling(15, min_periods=5).sum()) + 1.0
    df_250d_all["supply_exhaustion_ratio"] = df_250d_all["up_v_15"] / df_250d_all["dn_v_15"]

    df_250d_all["d_cash"] = df_250d_all["deliv_qty"] * df_250d_all["close"]
    df_250d_all["deliv_up_cash"] = np.where(df_250d_all["diff"] > 0, df_250d_all["d_cash"], 0.0)
    df_250d_all["deliv_dn_cash"] = np.where(df_250d_all["diff"] < 0, df_250d_all["d_cash"], 0.0)
    df_250d_all["deliv_up"] = grouped["deliv_up_cash"].transform(lambda x: x.rolling(30, min_periods=10).sum()) + 1.0
    df_250d_all["deliv_dn"] = grouped["deliv_dn_cash"].transform(lambda x: x.rolling(30, min_periods=10).sum()) + 1.0
    df_250d_all["deliv_flow_ratio"] = df_250d_all["deliv_up"] / df_250d_all["deliv_dn"]
    df_250d_all["smooth_deliv_pct"] = grouped["deliv_pct"].transform(lambda x: x.rolling(20, min_periods=10).mean())
    df_250d_all["avg_deliv_20"] = grouped["deliv_qty"].transform(lambda x: x.rolling(20, min_periods=10).mean())

    df_250d_all["c_21_ago"] = grouped["close"].shift(21)
    df_250d_all["c_63_ago"] = grouped["close"].shift(63)
    df_250d_all["c_126_ago"] = grouped["close"].shift(126)
    df_250d_all["c_250_ago"] = grouped["close"].shift(250).fillna(grouped["close"].transform('first'))
    
    df_250d_all["stk_ret_21"] = (df_250d_all["close"] / (df_250d_all["c_21_ago"] + 1e-5)) - 1.0
    df_250d_all["stk_ret_63"] = (df_250d_all["close"] / (df_250d_all["c_63_ago"] + 1e-5)) - 1.0
    df_250d_all["stk_ret_126"] = (df_250d_all["close"] / (df_250d_all["c_126_ago"] + 1e-5)) - 1.0
    df_250d_all["stk_ret_250"] = (df_250d_all["close"] / (df_250d_all["c_250_ago"] + 1e-5)) - 1.0
    
    def get_poc(prices, volumes):
        poc_arr = np.full(len(prices), np.nan)
        for idx in range(50, len(prices)):
            w_p = prices[idx - 50 : idx + 1]
            w_v = volumes[idx - 50 : idx + 1]
            if np.sum(w_v) > 0:
                hist, bins = np.histogram(w_p, bins=10, weights=w_v)
                best_b = int(np.argmax(hist))
                poc_arr[idx] = (bins[best_b] + bins[best_b + 1]) / 2.0
        return poc_arr
        
    df_250d_all["volume_profile_poc"] = grouped.apply(lambda x: pd.Series(get_poc(x["close"].values, x["volume"].values), index=x.index)).reset_index(level=0, drop=True)
    df_250d_all["volume_profile_poc"] = df_250d_all["volume_profile_poc"].fillna(df_250d_all["sma_20"])

    def align_weekly(grp):
        w_df = pd.DataFrame({"dt": pd.to_datetime(grp["date"]), "close": grp["close"]}).set_index("dt")
        w_close = w_df["close"].resample("W-FRI").last().dropna()
        if len(w_close) >= 5:
            w_ema10 = w_close.ewm(span=10, adjust=False).mean()
            w_sma20 = w_close.rolling(20, min_periods=5).mean()
            w_aligned = ((w_close >= w_ema10) & (w_ema10 >= w_sma20 * 0.995)).astype(bool)
            return w_aligned.shift(1, fill_value=True).reindex(w_df.index, method="ffill").fillna(True).values
        else:
            return np.ones(len(grp), dtype=bool)
            
    df_250d_all["weekly_aligned"] = df_250d_all.groupby("symbol", sort=False).apply(align_weekly).explode().values.astype(bool)

    stock_tech_rows = []
    price_history_map = {}
    
    final_day = df_250d_all[df_250d_all["date"] == latest_date].copy()
    
    for _, r in final_day.iterrows():
        sym = r["symbol"]
        close = r["close"]
        if pd.isna(close) or close <= 0: continue
        
        sma_20 = r["sma_20"]
        sma_50 = r["sma_50"]
        sma_200 = r["sma_200"]
        if pd.isna(sma_20) or pd.isna(sma_50) or pd.isna(sma_200): continue
        
        atr_20 = r["atr_20"]
        atr_pct = r["atr_pct"]
        poc = r["volume_profile_poc"]
        ema_10 = r["ema_10"]
        cr = r["cr"]
        session_rvol = r["session_rvol"]
        
        is_extended_danger = r["dist_from_20"] > 0.08
        stk_ret_63 = r["stk_ret_63"]
        stk_ret_250 = r["stk_ret_250"]
        prior_63d_pct = round(stk_ret_63 * 100.0, 2)
        ret_250d_pct = round(stk_ret_250 * 100.0, 2)
        
        rs_spread_21 = (r["stk_ret_21"] - bm_ret_21) * 100.0
        rs_spread_63 = (stk_ret_63 - bm_ret_63) * 100.0
        rs_spread_126 = (r["stk_ret_126"] - bm_ret_126) * 100.0
        rs_spread_250 = (stk_ret_250 - bm_ret_250) * 100.0
        raw_multi_rs = (0.40 * rs_spread_63) + (0.30 * rs_spread_126) + (0.20 * rs_spread_250) + (0.10 * rs_spread_21)
        
        grp_data = grouped.get_group(sym)
        prices = grp_data["close"].values
        volumes = grp_data["volume"].values
        highs = grp_data["high"].values
        lows = grp_data["low"].values
        vcp_rat, pattern, pattern_tf = detect_genuine_chart_patterns(prices, volumes, highs, lows)
        
        sma_200_20d_ago = np.mean(prices[-min(220, len(prices)):-20]) if len(prices) >= 30 else sma_200
        sma_200_slope = (sma_200 - sma_200_20d_ago) / (sma_200_20d_ago + 1e-5)
        h_52 = r["high_52w"]
        l_52 = r["low_52w"]
        
        trend_score = 0.0
        if close > sma_200: trend_score += 25.0
        if close > sma_50: trend_score += 25.0
        if sma_50 > sma_200: trend_score += 20.0
        if sma_200_slope >= 0: trend_score += 10.0
        if (close / (h_52 + 1e-5)) >= 0.75: trend_score += 10.0 * min(1.0, (close / (h_52 + 1e-5)) / 0.90)
        if (close / (l_52 + 1e-5)) >= 1.25: trend_score += 10.0 * min(1.0, ((close / (l_52 + 1e-5)) - 1.0) / 0.50)
        trend_score = round(np.clip(trend_score, 5.0, 99.0), 1)

        atr_fuel_pts = np.clip(((atr_pct - 2.2) / 2.4) * 30.0, 2.0, 30.0)
        base_coil_pts = np.clip(25.0 * np.exp(-((r["base_depth_pct"] - 21.5) ** 2) / 65.0), 3.0, 25.0) if close >= sma_50 else 4.0
        flow_pts = np.clip(30.0 * (np.log1p(min(r["deliv_flow_ratio"], 6.0)) / np.log1p(4.0)), 4.0, 30.0)
        ud_pts = np.clip(((r["up_down_ratio"] - 1.0) / 1.5) * 15.0, 2.0, 15.0)

        raw_iasis = atr_fuel_pts + base_coil_pts + flow_pts + ud_pts
        if close < sma_200 and close < sma_50:
            iasis_score = round(min(35.0, raw_iasis * 0.40), 1)
        else:
            iasis_score = round(np.clip(raw_iasis, 10.0, 99.0), 1)
            
        turnover_val = float((r.get("volume", 0.0) * close) / 10000000.0)
        tier_label_sym = classify_mcap_tier(sym, str(r.get("index_name", "")), turnover_val)
        is_tier1_sym = "Tier 1" in tier_label_sym
        is_tier4_sym = "Tier 4" in tier_label_sym
        atr_mult = 2.8 if is_tier1_sym else 2.5
        max_sl_floor = 0.935 if is_tier1_sym else 0.885

        raw_struct_stop = min(close - (atr_mult * atr_20), sma_50 * (0.965 if is_tier1_sym else 0.960))
        structural_stop = round(max(close * max_sl_floor, raw_struct_stop), 2)

        t1_target_pct = 8.0 if is_tier1_sym else 10.0
        t2_target_pct = 22.0 if is_tier1_sym else 35.0
        if is_tier1_sym:
            m2_stop_pct = -5.0
        elif is_tier4_sym and close > 0:
            m2_stop_pct = float(np.clip(-round((1.85 * atr_20 / close) * 100.0, 2), -8.5, -6.5))
        else:
            m2_stop_pct = -6.5
        shield_trig_pct = 4.0 if is_tier1_sym else 4.5
        shield_lock_pct = 0.8 if is_tier1_sym else 1.0

        target_price = round(close * (1.0 + (t1_target_pct / 100.0)), 2)
        tranche2_breakout_price = round(close * (1.0 + (t2_target_pct / 100.0)), 2)
        risk_clamp_stop = round(close * (1.0 + (m2_stop_pct / 100.0)), 2)
        shield_trigger_price = round(close * (1.0 + (shield_trig_pct / 100.0)), 2)
        shield_floor_price = round(close * (1.0 + (shield_lock_pct / 100.0)), 2)

        rrr_calc = round(min(8.0, max(1.5, abs(t1_target_pct / m2_stop_pct))), 1)

        order_block_status = (
            f"50/50 Dual-Stage Plan: Entry ₹{close:.2f} | "
            f"Shield: At ₹{shield_trigger_price:.2f} (+{shield_trig_pct:.1f}%), lock ₹{shield_floor_price:.2f} (+{shield_lock_pct:.1f}% if <10EMA) | "
            f"Harvest: 50% @ ₹{target_price:.2f} (+{t1_target_pct:.0f}%), 50% Runner @ ₹{tranche2_breakout_price:.2f} (+{t2_target_pct:.0f}% / 2-Close 50-SMA) | "
            f"Stop: ₹{risk_clamp_stop:.2f} ({m2_stop_pct:.1f}% 2D Close)"
        )
        
        is_not_extended = r["dist_from_20"] <= 0.040
        has_structural_floor = (close >= sma_50 * 0.985) and (close >= poc)

        is_ignition_fired = bool(
            has_structural_floor and
            is_not_extended and
            r["prior_quiet"] and
            (close > r["open"]) and
            (close >= r["prev_h"]) and
            (close >= ema_10) and
            (ema_10 >= sma_50 * 0.99) and
            (close >= sma_20 * 0.995) and
            (cr >= 0.65) and
            (session_rvol >= 1.25)
        )

        tested_support = bool(
            (r["prev_l"] <= sma_20 * 1.012) or
            (r["low"] <= sma_20 * 1.012) or
            (r["prev_l"] <= ema_10 * 1.008) or
            (r["low"] <= poc * 1.010)
        )
        is_reclaim_fired = bool(
            has_structural_floor and
            is_not_extended and
            tested_support and
            (close > r["open"]) and
            (close >= r["prev_c"] * 1.008) and
            (close >= ema_10 * 0.995) and
            (cr >= 0.65) and
            (close >= sma_50 * 0.990)
        )
        
        rsi_14 = r["rsi_14"]
        rsi_10d_chg = r["rsi_10d_chg"]
        pct_of_52w_high = r["pct_of_52w_high"]
        no_bearish_rsi_div = not ((pct_of_52w_high >= 90.0) and (rsi_14 < 54.0) and (rsi_10d_chg < -4.0))

        passes_anti_fizzle_gate = bool(
            (close >= sma_200) and
            (close >= sma_50 * 0.985) and
            (close >= poc) and
            (r["weekly_aligned"]) and
            (no_bearish_rsi_div) and
            (ret_250d_pct >= 12.0) and
            (pct_of_52w_high >= 82.0) and
            (r["dist_from_20"] <= 0.040) and
            (r["dist_from_50_pct"] <= 14.0) and
            (atr_pct >= 3.05) and
            (r["up_down_ratio"] >= 1.20)
        )

        passes_quality_gate = bool(
            (close >= sma_200) and
            (close >= sma_50 * 0.985) and
            (close >= poc) and
            (no_bearish_rsi_div) and
            (ret_250d_pct >= 10.0) and
            (pct_of_52w_high >= 80.0) and
            (r["up_down_ratio"] >= 1.15) and
            (atr_pct >= 2.85)
        )
        
        trigger_price = round(max(r["prev_h"], ema_10 * 1.005), 2)
        
        if (is_ignition_fired or is_reclaim_fired) and passes_anti_fizzle_gate:
            execution_state = "🔥 ACTIONABLE_BUY_NOW"
            trigger_reason = "20-SMA/POC Support Reclaimed" if is_reclaim_fired else "Pocket Pivot Ignition Fired"
            is_active_trade = True
            is_potential_stalking = False
        elif passes_quality_gate:
            execution_state = "👀 STALKING_WATCHLIST"
            trigger_reason = f"Coiling in Base; Awaiting Ignition Close > ₹{trigger_price:.2f}"
            is_active_trade = False
            is_potential_stalking = True
        else:
            execution_state = "❌ EVICTED_BREAKDOWN"
            trigger_reason = "Below Structural Momentum / 50-SMA / POC Floor"
            is_active_trade = False
            is_potential_stalking = False
            
        reasons_to_avoid = []
        if close < sma_200: reasons_to_avoid.append("Price trading below 200-day SMA (heavy overhead supply)")
        if close < sma_50: reasons_to_avoid.append("Price below intermediate 50-day SMA (intermediate downtrend)")
        if close < poc: reasons_to_avoid.append(f"Price below Volume Profile POC (₹{poc:.2f} overhead resistance)")
        if ret_250d_pct < 12.0: reasons_to_avoid.append(f"Weak 1-year structural trend ({ret_250d_pct:+.1f}% < +12.0% floor)")
        if pct_of_52w_high < 82.0: reasons_to_avoid.append(f"Too far below 52W High ({pct_of_52w_high:.1f}% < 82.0% threshold)")
        if not no_bearish_rsi_div: reasons_to_avoid.append(f"Bearish RSI divergence near highs (RSI {rsi_14:.1f}, 10D chg {rsi_10d_chg:+.1f})")
        if not r["weekly_aligned"]: reasons_to_avoid.append("Weekly multi-timeframe trend not aligned (below W-10EMA/W-20SMA)")
        if atr_pct < 3.05: reasons_to_avoid.append(f"Low kinetic fuel (ATR {atr_pct:.1f}% < 3.05% threshold; prone to fizzles)")
        if is_extended_danger: reasons_to_avoid.append("Price extended >8% above 20 SMA (high risk of mean-reversion pullback)")
        if r["up_down_ratio"] < 1.15: reasons_to_avoid.append("Weak accumulation (Up/Down volume ratio < 1.15)")
        
        stock_tech_rows.append({
            "symbol": sym,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "sma_50_rising": r["sma_50_rising"],
            "sma20_slope_10d": r["sma20_slope_10d"],
            "sma50_slope_20d": r["sma50_slope_20d"],
            "above_sma50_5d_ago": r.get("above_sma50_5d_ago", True),
            "weekly_aligned": r["weekly_aligned"],
            "stage2_aligned": bool((close > sma_50) and (sma_50 > sma_200) and r["sma_50_rising"]),
            "ema_10": ema_10,
            "ema_21": r["ema_21"],
            "rsi_14": rsi_14,
            "rsi_10d_chg": rsi_10d_chg,
            "stoch_k": r["stoch_k"],
            "volume_profile_poc": poc,
            "chart_pattern_signal": pattern,
            "pattern_timeframe": pattern_tf,
            "sector_rs_status": "🟢 Outperforming Sector", 
            "avg_deliv_20": r["avg_deliv_20"],
            "atr_20": atr_20,
            "atr_pct": atr_pct,
            "structural_stop": structural_stop,
            "target_price": target_price,
            "stop_loss_price": risk_clamp_stop,
            "target_pct": t1_target_pct,
            "risk_clamp_pct": m2_stop_pct,
            "benchmark_peak_mfe_pct": 32.12,
            "tranche2_limit_price": round(close - (0.75 * atr_20), 2),
            "tranche2_breakout_price": tranche2_breakout_price,
            "tranche2_Breakout_price": tranche2_breakout_price,
            "blended_entry_price": close,
            "cushioned_sl_price": structural_stop,
            "stage1_lock_price": shield_floor_price,
            "vcp_ratio_calc": float(vcp_rat),
            "bb_kc_ratio": 1.0, 
            "ma_spread_pct": round(float(((max(ema_10, r["ema_21"], sma_50) - min(ema_10, r["ema_21"], sma_50)) / (close + 1e-5)) * 100.0), 2),
            "vol_dryup_ratio": round(r["vol_dryup_ratio"], 2),
            "closing_range": round(cr, 3),
            "iasis_score": iasis_score,
            "raw_multi_rs": raw_multi_rs,
            "trend_score": trend_score,
            "up_down_vol_ratio": r["up_down_ratio"],
            "smooth_deliv_expansion": round(float(r["deliv_flow_ratio"]), 2),
            "smooth_deliv_pct": round(float(r["smooth_deliv_pct"]), 1),
            "high_52w": h_52,
            "low_52w": l_52,
            "pct_of_52w_high": pct_of_52w_high,
            "risk_reward_calc": rrr_calc,
            "order_block_status": order_block_status,
            "session_rvol": session_rvol,
            "is_rvol_expanded": session_rvol >= 2.5,
            "is_squeezed": False,
            "is_ma_pinched": False,
            "is_rs_divergent": False,
            "is_pocket_pivot_5d": False,
            "is_supply_exhausted": r["supply_exhaustion_ratio"] >= 2.5,
            "is_rs_accelerating": False,
            "supply_exhaustion_ratio": r["supply_exhaustion_ratio"],
            "flow_ratio": round(r["deliv_flow_ratio"], 2),
            "mrs_score": r["mrs_score"],
            "dist_from_50_pct": r["dist_from_50_pct"],
            "dist_from_200_pct": r["dist_from_200_pct"],
            "prior_63d_pct": prior_63d_pct,
            "ret_250d_pct": ret_250d_pct,
            "base_depth_pct": round(r["base_depth_pct"], 2),
            "trig_a": is_ignition_fired,
            "trig_b": is_reclaim_fired,
            "trigger_price": trigger_price,
            "pyramid_confluence_price": tranche2_breakout_price,
            "execution_state": execution_state,
            "trigger_reason": trigger_reason,
            "passes_quality_gate": passes_quality_gate,
            "passes_anti_fizzle_gate": passes_anti_fizzle_gate,
            "is_active_trade": is_active_trade,
            "is_potential_stalking": is_potential_stalking,
            "reasons_to_avoid": "; ".join(reasons_to_avoid) if reasons_to_avoid else "None. Technical structure remains constructive.",
        })

    with open(PRICE_HISTORY_JSON, "w") as f:
        json.dump(price_history_map, f)

    ranked = pd.merge(latest_df, pd.DataFrame(stock_tech_rows), on="symbol", how="inner").drop_duplicates(subset=["symbol"])

    if not dna_df.empty and "stock_dna_score" in dna_df.columns:
        ranked = pd.merge(ranked, dna_df, on="symbol", how="left")
    
    # Remove artificial default rows that let unprofiled stocks bypass gates
    ranked = ranked.dropna(subset=["stock_dna_score"])

    ranked["turnover_cr"] = ((ranked["volume"].fillna(0) * ranked["close"]) / 10000000.0).round(2)
    ranked["mcap_tier"] = ranked.apply(lambda r: classify_mcap_tier(r["symbol"], r.get("index_name", ""), r.get("turnover_cr", 0.0)), axis=1)

    ranked["d_expansion"] = ranked["smooth_deliv_expansion"]
    ranked["deliv_spike"] = (ranked["deliv_qty"] / (ranked["avg_deliv_20"] + 1)).round(2)
    ranked["vcp_ratio"] = ranked["vcp_ratio_calc"]
    ranked["absorption_ratio"] = (((ranked["deliv_qty"] * ranked["close"]) / 10000000.0) / (ranked["high"] - ranked["low"] + 0.05)).round(2)
    ranked["atr_stop_loss"] = ranked["structural_stop"]
    ranked["above_sma20"] = ranked["close"] >= ranked["sma_20"]
    ranked["above_sma50"] = ranked["close"] >= ranked["sma_50"]
    ranked["above_200sma"] = ranked["close"] >= ranked["sma_200"]

    sec_base_clean = sec_base[sec_base["sector"] != "Unclassified"].copy()
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

    tier_breadth_map = ranked.groupby("mcap_tier")["above_sma50"].mean().mul(100.0).to_dict()
    sec_base_indexed = sec_base.set_index("symbol")
    lag20_series = ranked["symbol"].map(lambda s: sec_base_indexed.loc[s, "close_20d_ago"] if s in sec_base_indexed.index else np.nan)
    universe_20d_ret = float(((ranked["close"] / (lag20_series + 1e-5)) - 1.0).mean() * 100.0)

    tier_20d_ret = ranked.groupby("mcap_tier").apply(
        lambda x: ((x["close"] / (x["symbol"].map(lambda s: sec_base_indexed.loc[s, "close_20d_ago"] if s in sec_base_indexed.index else np.nan) + 1e-5)) - 1.0).mean() * 100.0
    ).to_dict()

    def compute_selective_tier_mult(row):
        tier = str(row["mcap_tier"])
        b = tier_breadth_map.get(tier, 50.0)
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
    tier_mult = ranked["tier_climax_mult"]
    sec_adj = np.clip(ranked["sector_climax_mult"], 0.84, 1.08)

    kinetic_mult = np.where(
        (ranked["atr_pct"] >= 3.20) & (ranked["rsi_14"] <= 66.0),
        1.08,
        np.where(ranked["atr_pct"] < 2.80, 0.72, 0.96),
    )

    dist_poc_pct_series = np.where(
        ranked["volume_profile_poc"] > 0,
        ((ranked["close"] - ranked["volume_profile_poc"]) / (ranked["volume_profile_poc"] + 1e-5)) * 100.0,
        0.0,
    )
    ranked["dist_poc_pct"] = np.round(dist_poc_pct_series, 2)

    ranked["sector_internal_rank"] = ranked.groupby("sector")["raw_multi_rs"].rank(ascending=False, method="min")
    sec_avg_rs_map = ranked.groupby("sector")["raw_multi_rs"].mean().to_dict()
    ranked["beats_own_sector"] = ranked["raw_multi_rs"] >= ranked["sector"].map(lambda s: sec_avg_rs_map.get(s, -999.0))

    near_52w_bonus = np.where(ranked["pct_of_52w_high"] >= 88.0, 1.05, 0.97)
    supply_ex_bonus = np.where(ranked["supply_exhaustion_ratio"] >= 2.5, 1.00, 1.00)
    weekly_mtf_bonus = np.where(ranked["weekly_aligned"], 1.03, 0.94)
    top3_sec_poc_bonus = np.where(
        (ranked["sector_internal_rank"] <= 3) & (dist_poc_pct_series >= 0.0) & (dist_poc_pct_series <= 5.5),
        1.05,
        1.00,
    )
    confluence_booster = near_52w_bonus * supply_ex_bonus * weekly_mtf_bonus * top3_sec_poc_bonus
    ranked["confluence_booster"] = np.round(confluence_booster, 3)

    not_weak_dna1 = (~ranked["dna_archetype"].str.contains("DNA-1", na=False)) | (ranked["stock_dna_score"] >= 68.0)
    has_strong_dna_edge = (
        (ranked["stock_dna_score"] >= 64.0)
        | (ranked["dominant_ma_dna"] == "50-SMA Deep Undercutter")
        | (ranked["wick_polarity_dna"] == "Upper-Wick Supply Fader")
        | (ranked["dna_archetype"].str.contains("DNA-2|DNA-4", na=False))
    )
    ranked["dna_qualified"] = not_weak_dna1 & has_strong_dna_edge

    dna_score_mult = np.where(
        ranked["dna_qualified"],
        np.where(ranked["stock_dna_score"] >= 68.0, 1.06, 1.02),
        0.78,
    )

    poc_floor_pts = 28.0 * np.exp(-((dist_poc_pct_series - 2.0) ** 2) / 14.0)
    atr_anchor_pts = np.clip(((ranked["atr_pct"] - 2.3) / 2.2) * 22.0, 3.0, 22.0)
    deliv_anchor_pts = np.clip(25.0 * (np.log1p(np.minimum(ranked["smooth_deliv_expansion"], 5.0)) / np.log1p(3.5)), 4.0, 25.0)

    raw_surety = (
        poc_floor_pts
        + atr_anchor_pts
        + deliv_anchor_pts
        + (0.15 * rs_percentile)
        + (0.10 * ranked["iasis_score"])
    )
    ranked["surety_score"] = (
        raw_surety * sec_adj * poc_multiplier * tier_mult * kinetic_mult * confluence_booster * dna_score_mult
    ).clip(5.0, 99.0).round(1)
    ranked["score_surety_anchor"] = ranked["surety_score"]

    rsi_headroom_mult = np.where(ranked["rsi_14"] <= 68.0, 1.05, 0.82)
    dist50_sweet_pts = np.clip(((ranked["dist_from_50_pct"] - 2.0) / 10.0) * 20.0, 2.0, 20.0)
    ranked["score_momentum_frontrunner"] = (
        (0.45 * rs_percentile + 0.25 * ranked["iasis_score"] + 0.15 * ranked["trend_score"] + dist50_sweet_pts)
        * sec_adj
        * mom_struct_penalty
        * tier_mult
        * kinetic_mult
        * rsi_headroom_mult
        * confluence_booster
        * dna_score_mult
    ).clip(5.0, 99.0).round(1)

    ranked["score_early_sector_rotation"] = (
        (0.35 * rs_percentile + 0.25 * peer_rs_percentile + 0.25 * ranked["iasis_score"] + 0.15 * ranked["ignition_score"])
        * rot_struct_penalty
        * poc_multiplier
        * tier_mult
        * kinetic_mult
        * confluence_booster
        * dna_score_mult
    ).clip(5.0, 99.0).round(1)

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
        * tier_mult
        * kinetic_mult
        * confluence_booster
        * dna_score_mult
    ).clip(5.0, 99.0).round(1)

    market_breadth_pct = float((ranked["above_sma50"].mean()) * 100.0)
    breadth_5d_ago_pct = float((ranked["above_sma50_5d_ago"].mean()) * 100.0)
    breadth_5d_change = round(market_breadth_pct - breadth_5d_ago_pct, 2)

    bm_sma_20 = float(market_benchmark.rolling(20).mean().iloc[-1])
    bm_mrs = float(((float(market_benchmark.iloc[-1]) / (bm_sma_20 + 1e-5)) - 1.0) * 100.0)

    active_rot = len(sector_summary[(sector_summary["stock_count"] >= 3) & (sector_summary["sector_lifecycle"].str.contains("Rotation|Prime|Leadership"))])

    if market_breadth_pct >= 55.0:
        regime_label = f"🟢 Bull Expansion ({market_breadth_pct:.1f}% >50SMA | 5D {breadth_5d_change:+.1f}%)"
        max_active_quota = 4
        branch_ok = (ranked["atr_pct"] >= 3.05) & (rs_percentile >= 76.0)
        quotas = {
            "score_high_rs_pullback": 4,
            "score_momentum_frontrunner": 4,
            "score_early_sector_rotation": 2 if active_rot > 0 else 0,
            "score_surety_anchor": 2,
        }
    elif 48.0 <= market_breadth_pct < 55.0:
        regime_label = f"🔄 Selective Mid-Tape ({market_breadth_pct:.1f}% >50SMA | 5D {breadth_5d_change:+.1f}%)"
        max_active_quota = 2
        branch_ok = (rs_percentile >= 78.0) & (
            (ranked["atr_pct"] >= 3.45) | ((ranked["sma20_slope_10d"] >= 0.96) & (ranked["session_rvol"] <= 1.05))
        )
        quotas = {
            "score_high_rs_pullback": 4,
            "score_surety_anchor": 4,
            "score_momentum_frontrunner": 2,
            "score_early_sector_rotation": 2,
        }
    elif market_breadth_pct < 28.0:
        regime_label = f"⚡ Capitulation Spring ({market_breadth_pct:.1f}% >50SMA | 5D {breadth_5d_change:+.1f}%)"
        max_active_quota = 3
        branch_ok = (rs_percentile >= 82.0) & (ranked["atr_pct"] >= 3.40)
        quotas = {
            "score_high_rs_pullback": 5,
            "score_early_sector_rotation": 3 if active_rot > 0 else 0,
            "score_surety_anchor": 2,
            "score_momentum_frontrunner": 2,
        }
    else:
        regime_label = f"🛑 Chop Dead-Zone Lockdown ({market_breadth_pct:.1f}% >50SMA | 5D {breadth_5d_change:+.1f}%)"
        max_active_quota = 0
        branch_ok = pd.Series(False, index=ranked.index)
        quotas = {
            "score_high_rs_pullback": 5,
            "score_surety_anchor": 4,
            "score_momentum_frontrunner": 2,
            "score_early_sector_rotation": 1,
        }

    ex_large = ~ranked["mcap_tier"].str.contains("Tier 1", na=False)
    tree_core_gate = ex_large & ranked["passes_anti_fizzle_gate"] & branch_ok & ranked["dna_qualified"] & (ranked["trig_a"] | ranked["trig_b"])

    ranked["qual_s1_surety"] = (
        tree_core_gate
        & ranked["dist_poc_pct"].between(0.0, 5.5)
        & (ranked["flow_ratio"] >= 1.35)
        & (ranked["sma50_slope_20d"] >= 2.5)
        & (ranked["up_down_vol_ratio"] >= 1.25)
    )
    ranked["qual_s2_momentum"] = (
        tree_core_gate
        & (rs_percentile >= 82.0)
        & (ranked["sma50_slope_20d"] >= 4.5)
        & (ranked["pct_of_52w_high"] >= 88.0)
        & ((market_breadth_pct >= 55.0) | (ranked["atr_pct"] >= 3.55))
        & (ranked["up_down_vol_ratio"] >= 1.30)
    )
    ranked["qual_s3_rotation"] = (
        tree_core_gate
        & (ranked["sector_internal_rank"] <= 3)
        & (ranked["beats_own_sector"])
        & (rs_percentile >= 80.0)
        & (ranked["sma50_slope_20d"] >= 3.0)
        & ranked["dist_poc_pct"].between(0.0, 7.5)
        & (ranked["flow_ratio"] >= 1.25)
    )
    ranked["qual_s4_pullback"] = (
        tree_core_gate
        & (rs_percentile >= 78.0)
        & ranked["mrs_score"].between(-3.5, 2.5)
        & (ranked["trig_b"])
        & ((ranked["session_rvol"] <= 1.15) | (ranked["atr_pct"] >= 3.45))
        & (ranked["sma50_slope_20d"] >= 2.5)
    )

    ranked["strat_confluence_count"] = (
        ranked["qual_s1_surety"].astype(int)
        + ranked["qual_s2_momentum"].astype(int)
        + ranked["qual_s3_rotation"].astype(int)
        + ranked["qual_s4_pullback"].astype(int)
    )

    is_lagging_sec = ranked["sector_lifecycle"].str.contains("Decelerating|Lagging", na=False)
    stage4_sec_ok = (~is_lagging_sec) | (ranked["strat_confluence_count"] >= 2)

    ranked["is_eod_confirmed"] = (
        (
            ranked["qual_s1_surety"]
            | ranked["qual_s2_momentum"]
            | ranked["qual_s3_rotation"]
            | ranked["qual_s4_pullback"]
        )
        & stage4_sec_ok
    )

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

        if bool(r.get("is_eod_confirmed", False)):
            qual_candidates = []
            if bool(r.get("qual_s1_surety", False)):
                qual_candidates.append((s_anchor, "🛡️ High-Surety Anchor"))
            if bool(r.get("qual_s3_rotation", False)):
                qual_candidates.append((s_rot, "🔄 Early Sector Rotation Leader"))
            if bool(r.get("qual_s4_pullback", False)):
                qual_candidates.append((s_pull, "📉 High-RS Pullback"))
            if bool(r.get("qual_s2_momentum", False)):
                qual_candidates.append((s_mom, "🚀 Momentum Frontrunner"))
            if qual_candidates:
                qual_candidates.sort(key=lambda x: x[0], reverse=True)
                return qual_candidates[0][1]

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

    confirmed_active_symbols = set()
    if max_active_quota > 0:
        elite_triggered_df = ranked[
            (ranked["is_eod_confirmed"] == True) &
            (ranked["turnover_cr"] >= 1.5)
        ].copy()

        if not elite_triggered_df.empty:
            elite_triggered_df["max_strat_score"] = elite_triggered_df[
                ["score_high_rs_pullback", "score_momentum_frontrunner", "score_early_sector_rotation", "score_surety_anchor"]
            ].max(axis=1)
            elite_triggered_df = elite_triggered_df.sort_values(
                by=["strat_confluence_count", "stock_dna_score", "max_strat_score", "blended_rs_percentile"],
                ascending=[False, False, False, False],
            )

            active_sec_counts = {}
            for _, r in elite_triggered_df.iterrows():
                if len(confirmed_active_symbols) >= max_active_quota:
                    break
                sym, sec = r["symbol"], r["sector"]
                if active_sec_counts.get(sec, 0) < 2:
                    confirmed_active_symbols.add(sym)
                    active_sec_counts[sec] = active_sec_counts.get(sec, 0) + 1

    active_ledger_map = sync_active_trades_ledger(
        df_all=df_all,
        ranked_today=ranked,
        newly_triggered_symbols=confirmed_active_symbols,
        latest_date=str(latest_date),
    )
    all_open_active_symbols = set(active_ledger_map.keys())

    ranked["is_active_trade"] = ranked["symbol"].isin(all_open_active_symbols)
    ranked.loc[(~ranked["is_active_trade"]) & (ranked["passes_quality_gate"]), "is_potential_stalking"] = True
    ranked.loc[(~ranked["is_active_trade"]) & (ranked["passes_quality_gate"]), "execution_state"] = "👀 STALKING_WATCHLIST"

    dynamic_picks_map = {}
    seen_sec = {}
    seen_sym = set(all_open_active_symbols)

    stalking_quality_gate = (
        (ranked["passes_quality_gate"] == True) &
        (ranked["weekly_aligned"] == True) &
        (ranked["dna_qualified"] == True) &
        (~ranked["mcap_tier"].str.contains("Tier 1", na=False)) &
        (ranked["blended_rs_percentile"] >= 75.0) &
        (
            (~ranked["sector_lifecycle"].str.contains("Lagging|Decelerating", na=False)) |
            (ranked["blended_rs_percentile"] >= 86.0)
        )
    )

    for strat_key, limit in quotas.items():
        if limit <= 0:
            continue
        sub = ranked[stalking_quality_gate].copy()

        if strat_key == "score_surety_anchor":
            strat_name = "surety"
            mask = (sub["close"] >= sub["sma_50"] * 0.985) & (sub["mrs_score"].between(-4.0, 4.0))
        elif strat_key == "score_momentum_frontrunner":
            strat_name = "momentum"
            mask = (sub["stage2_aligned"]) & (sub["mrs_score"].between(-1.5, 4.5)) & (sub["rsi_14"] <= 66.0)
        elif strat_key == "score_early_sector_rotation":
            sub = sub[sub["sector_lifecycle"].str.contains("Rotation|Prime|Leadership", na=False)]
            strat_name = "rotation"
            mask = (sub["beta_neutral_mrs"] >= 1.0)
        elif strat_key == "score_high_rs_pullback":
            strat_name = "pullback"
            mask = (sub["close"] >= sub["sma_50"] * 0.985) & (sub["mrs_score"].between(-5.0, 2.0)) & (sub["stoch_k"] <= 68.0)
        else:
            strat_name = "pullback"
            mask = sub["close"] > 0

        qual = sub[mask].sort_values(by=[strat_key, "stock_dna_score", "blended_rs_percentile"], ascending=[False, False, False])
        added = 0
        for _, r in qual.iterrows():
            if added >= limit or len(dynamic_picks_map) >= 12:
                break
            sym, sec = r["symbol"], r["sector"]
            if sym in seen_sym:
                continue
            if seen_sec.get(sec, 0) < 2:
                dynamic_picks_map[sym] = strat_name
                seen_sym.add(sym)
                seen_sec[sec] = seen_sec.get(sec, 0) + 1
                added += 1

    if len(dynamic_picks_map) < 12:
        backfill_pool = ranked[
            stalking_quality_gate & (~ranked["symbol"].isin(seen_sym))
        ].sort_values(by=["score_high_rs_pullback", "stock_dna_score", "blended_rs_percentile"], ascending=[False, False, False])

        for _, r in backfill_pool.iterrows():
            if len(dynamic_picks_map) >= 12:
                break
            sym, sec = r["symbol"], r["sector"]
            if seen_sec.get(sec, 0) < 2:
                dynamic_picks_map[sym] = "pullback"
                seen_sym.add(sym)
                seen_sec[sec] = seen_sec.get(sec, 0) + 1

    for _, r in ranked[ranked["is_active_trade"]].iterrows():
        sym = r["symbol"]
        s_map = [
            (float(r["score_high_rs_pullback"]), "pullback"),
            (float(r["score_momentum_frontrunner"]), "momentum"),
            (float(r["score_early_sector_rotation"]), "rotation"),
            (float(r["score_surety_anchor"]), "surety"),
        ]
        s_map.sort(key=lambda x: x[0], reverse=True)
        dynamic_picks_map[sym] = s_map[0][1]

    conservative_picks_set = set()
    con_candidates = ranked[
        (ranked["mcap_tier"].str.contains("Tier 1|Tier 2", na=False)) &
        (ranked["atr_pct"] >= 2.75) &
        (ranked["atr_pct"] <= 3.80) &
        (ranked["turnover_cr"] >= 10.0) &
        (ranked["close"] >= ranked["sma_200"]) &
        (ranked["close"] >= ranked["sma_50"] * 0.985) &
        (ranked["close"] >= ranked["volume_profile_poc"]) &
        ((ranked["score_surety_anchor"] >= 58.0) | (ranked["score_high_rs_pullback"] >= 58.0))
    ].sort_values(by=["score_surety_anchor", "score_high_rs_pullback"], ascending=False)

    con_sec_counts = {}
    for _, r in con_candidates.iterrows():
        if len(conservative_picks_set) >= 12:
            break
        sec = r["sector"]
        if con_sec_counts.get(sec, 0) < 2:
            conservative_picks_set.add(r["symbol"])
            con_sec_counts[sec] = con_sec_counts.get(sec, 0) + 1

    aggressive_picks_set = set()
    agg_candidates = ranked[
        (~ranked["mcap_tier"].str.contains("Tier 1", na=False)) &
        (ranked["atr_pct"] >= 3.30) &
        (ranked["turnover_cr"] >= 1.5) &
        (ranked["close"] >= ranked["sma_200"]) &
        (ranked["mrs_score"].between(-2.0, 5.5)) &
        (ranked["blended_rs_percentile"] >= 80.0)
    ].sort_values(by=["score_momentum_frontrunner", "blended_rs_percentile"], ascending=False)

    agg_sec_counts = {}
    for _, r in agg_candidates.iterrows():
        if len(aggressive_picks_set) >= 12:
            break
        sec = r["sector"]
        if agg_sec_counts.get(sec, 0) < 3:
            aggressive_picks_set.add(r["symbol"])
            agg_sec_counts[sec] = agg_sec_counts.get(sec, 0) + 1

    ranked = ranked.sort_values(
        by=["is_active_trade", "strat_confluence_count", "stock_dna_score", "score_high_rs_pullback", "score_momentum_frontrunner", "blended_rs_percentile"],
        ascending=[False, False, False, False, False, False],
    ).drop_duplicates(subset=["symbol"]).reset_index(drop=True)

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

        c = float(r.get("close", 0))
        s50 = float(r.get("sma_50", 0))
        s200 = float(r.get("sma_200", 0))
        mrs = float(r.get("mrs_score", 0))
        stoch = float(r.get("stoch_k", 50))
        secLife = str(r.get("sector_lifecycle", ""))
        secRs = str(r.get("sector_rs_status", ""))
        bn_mrs = float(r.get("beta_neutral_mrs", 0))
        vcp_rat = float(r.get("vcp_ratio", 1.0))
        pat_sig = str(r.get("chart_pattern_signal", "")).upper()
        conf_sig = str(r.get("multi_timeframe_confluence", "")).upper()
        stg2 = bool(r.get("stage2_aligned", False))

        is_surety_candidate = (c >= s200) and (c >= s50 * 0.98) and (-4.5 <= mrs <= 5.0)
        is_momentum_candidate = (c >= s200) and (c >= s50) and stg2 and (-2.0 <= mrs <= 6.0)
        is_rotation_candidate = (c >= s200) and (("LAGGING" not in secRs.upper()) or ("LAGGING" not in secLife.upper()) or (bn_mrs >= 1.5))
        is_pullback_candidate = (c >= s200) and (c >= s50 * 0.98) and (-6.0 <= mrs <= 2.0) and (stoch <= 70)

        preset_buyzone = (-1.5 <= mrs <= 3.5) and (c >= s200)
        preset_spring = (vcp_rat <= 0.68) or (pat_sig != "")
        preset_pullback_active = (-5.0 <= mrs <= 1.5) and (c >= s200)

        is_flag_pattern = ("FLAG" in pat_sig) or ("FLAG" in conf_sig)
        is_vcp_pattern = ("VCP" in pat_sig) or (vcp_rat <= 0.68)
        is_base_pattern = ("BASE" in pat_sig) or ("CUP" in pat_sig) or ("BASE" in conf_sig)
        is_macro_pattern = ("MACRO" in pat_sig) or ((c >= s50) and (s50 >= s200))

        iasis = float(r.get("iasis_score", 0))
        delivPct = float(r.get("smooth_deliv_pct", r.get("deliv_pct", 0)))
        upDown = float(r.get("up_down_vol_ratio", 1.0))
        poc = float(r.get("volume_profile_poc", 0))
        front = float(r.get("frontrunner_score", 0))

        conf_score = 0
        if iasis >= 60:
            conf_score += 20
        elif iasis >= 50:
            conf_score += 12
        if delivPct >= 50:
            conf_score += 10
        elif delivPct >= 35:
            conf_score += 6
        if upDown >= 1.25:
            conf_score += 10
        elif upDown >= 1.0:
            conf_score += 6
        if poc > 0 and c >= poc:
            conf_score += 20
            distPoc = ((c - poc) / poc) * 100
            if distPoc <= 4.0:
                conf_score += 5
        if front >= 70:
            conf_score += 15
        elif front >= 55:
            conf_score += 10
        if vcp_rat <= 0.65:
            conf_score += 10
        elif vcp_rat <= 0.8:
            conf_score += 5
        if -3.0 <= mrs <= 4.0:
            conf_score += 10

        pattern_confluence_score = min(100, max(0, int(round(conf_score))))

        dist_poc = round(((c - poc) / (poc + 1e-5)) * 100.0, 1) if poc > 0 else 0.0
        is_above_poc = bool(poc > 0 and c >= poc)

        tier_str = str(r.get("mcap_tier", ""))
        atr_pct_val = float(r.get("atr_pct", 3.0))
        s_surety = float(r.get("score_surety_anchor", 0))
        s_pull = float(r.get("score_high_rs_pullback", 0))
        s_mom = float(r.get("score_momentum_frontrunner", 0))

        if ("Tier 1" in tier_str or "Tier 2" in tier_str) and atr_pct_val <= 3.6 and c >= s200 and is_above_poc and (s_surety >= 58.0 or s_pull >= 58.0):
            risk_suitability = "Low Risk (High Win-Rate Compounder)"
        elif ("Tier 4" in tier_str) or (atr_pct_val >= 4.2) or (s_mom >= 72.0 and "Tier 1" not in tier_str):
            risk_suitability = "High Risk (Max Runup Velocity)"
        else:
            risk_suitability = "Medium Risk (Balanced Core Alpha)"

        is_active_trade = bool(r.get("is_active_trade", False))
        is_potential_stalking = bool(r.get("is_potential_stalking", False))
        exec_state = str(r.get("execution_state", "👀 STALKING_WATCHLIST"))
        ledger_info = active_ledger_map.get(sym, {})

        if is_active_trade:
            hold_status_badge = ledger_info.get("trade_lifecycle_badge", "🔥 Triggered Entry (Actionable)")
            exec_state = "🔥 ACTIONABLE_BUY_NOW"
        elif is_potential_stalking:
            hold_status_badge = "👀 Stalking Pool (Awaiting Trigger)"
        else:
            hold_status_badge = "🔄 In-Zone Structural Base"
            
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
            "weekly_aligned": bool(r.get("weekly_aligned", False)),
            "stage2_aligned": bool(r.get("stage2_aligned", False)),
            "rsi_14": clean(r.get("rsi_14")),
            "stoch_k": clean(r.get("stoch_k")),
            "target_price": clean(r.get("target_price")),
            "stop_loss_price": clean(r.get("stop_loss_price")),
            "target_pct": clean(r.get("target_pct")),
            "risk_clamp_pct": clean(r.get("risk_clamp_pct")),
            "benchmark_peak_mfe_pct": clean(r.get("benchmark_peak_mfe_pct")),
            "atr_stop_loss": clean(r.get("atr_stop_loss")),
            "tranche2_limit_price": clean(r.get("tranche2_limit_price")),
            "tranche2_breakout_price": clean(r.get("tranche2_breakout_price")),
            "tranche2_Breakout_price": clean(r.get("tranche2_breakout_price")),
            "blended_entry_price": clean(r.get("blended_entry_price")),
            "cushioned_sl_price": clean(r.get("cushioned_sl_price")),
            "stage1_lock_price": clean(r.get("stage1_lock_price")),
            "trigger_price": clean(r.get("trigger_price")),
            "pyramid_confluence_price": clean(r.get("pyramid_confluence_price")),
            "execution_state": exec_state,
            "trigger_reason": clean(r.get("trigger_reason", ""), True),
            "is_active_trade": is_active_trade,
            "is_potential_stalking": is_potential_stalking,
            "trade_lifecycle_status": ledger_info.get("trade_lifecycle_status", "STALKING" if is_potential_stalking else "WATCH"),
            "trade_lifecycle_badge": hold_status_badge,
            "can_still_enter": bool(ledger_info.get("can_still_enter", is_active_trade)),
            "late_entry_note": ledger_info.get("late_entry_note", ""),
            "logged_entry_date": ledger_info.get("logged_entry_date", str(latest_date) if is_active_trade else ""),
            "logged_entry_price": ledger_info.get("logged_entry_price", clean(r.get("close"))),
            "days_held_live": int(ledger_info.get("days_held_live", 0)),
            "unrealized_pnl_pct": float(ledger_info.get("unrealized_pnl_pct", 0.0)),
            "stock_dna_score": clean(r.get("stock_dna_score")),
            "dna_archetype": clean(r.get("dna_archetype", ""), True),
            "dominant_ma_dna": clean(r.get("dominant_ma_dna", ""), True),
            "wick_polarity_dna": clean(r.get("wick_polarity_dna", ""), True),
            "impulse_velocity_days": clean(r.get("impulse_velocity_days")),
            "amihud_impact_dna": clean(r.get("amihud_impact_dna")),
            "reentry_elasticity_pct": clean(r.get("reentry_elasticity_pct")),
            "dna_qualified": bool(r.get("dna_qualified", False)),
            "atr_pct": clean(r.get("atr_pct")),
            "volume_profile_poc": clean(r.get("volume_profile_poc")),
            "multi_timeframe_confluence": clean(r.get("multi_timeframe_confluence", ""), True),
            "chart_pattern_signal": clean(r.get("chart_pattern_signal", ""), True) if pd.notna(r.get("chart_pattern_signal")) else "",
            "pattern_timeframe": int(r.get("pattern_timeframe", 21)),
            "rs_line_status": clean(r.get("rs_line_status", ""), True),
            "sector_rs_status": clean(r.get("sector_rs_status", "🟢 Outperforming Sector"), True),
            "sector_lifecycle": clean(r.get("sector_lifecycle", "🟢 Prime Institutional Leadership"), True),
            "order_block_status": clean(r.get("order_block_status", ""), True),
            "risk_reward_ratio": clean(r.get("risk_reward_ratio")),
            "market_breadth_status": clean(r.get("market_breadth_status", "🟢 Bullish Regime"), True),
            "sector_breadth_status": clean(r.get("sector_breadth_status", "Improving"), True),
            "deliv_pct": clean(r.get("smooth_deliv_pct")),
            "deliv_spike": clean(r.get("deliv_spike")),
            "d_expansion": clean(r.get("d_expansion")),
            "vcp_ratio": clean(r.get("vcp_ratio")),
            "ma_spread_pct": clean(r.get("ma_spread_pct")),
            "closing_range": clean(r.get("closing_range")),
            "base_depth_pct": clean(r.get("base_depth_pct")),
            "dist_from_50_pct": clean(r.get("dist_from_50_pct")),
            "dist_from_200_pct": clean(r.get("dist_from_200_pct")),
            "prior_63d_pct": clean(r.get("prior_63d_pct")),
            "ret_250d_pct": clean(r.get("ret_250d_pct")),
            "pct_of_52w_high": clean(r.get("pct_of_52w_high")),
            "absorption_ratio": clean(r.get("absorption_ratio")),
            "turnover_cr": clean(r.get("turnover_cr")),
            "mrs_score": clean(r.get("mrs_score")),
            "beta_neutral_mrs": clean(r.get("beta_neutral_mrs")),
            "inst_signal": clean(r.get("inst_signal", "Consolidation / Base"), True),
            "dynamic_mix_strategy": dynamic_picks_map.get(sym, ""),
            "conservative_pick": bool(sym in conservative_picks_set),
            "balanced_pick": bool(sym in dynamic_picks_map),
            "aggressive_pick": bool(sym in aggressive_picks_set),
            "risk_suitability": risk_suitability,
            "hold_status_badge": hold_status_badge,
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
            "sector_internal_rank": int(r.get("sector_internal_rank", 99)),
            "strat_confluence_count": int(r.get("strat_confluence_count", 0)),
            "confluence_booster": clean(r.get("confluence_booster")),
            "reasons_to_avoid": clean(r.get("reasons_to_avoid", ""), True),
            "is_surety_candidate": bool(is_surety_candidate),
            "is_momentum_candidate": bool(is_momentum_candidate),
            "is_rotation_candidate": bool(is_rotation_candidate),
            "is_pullback_candidate": bool(is_pullback_candidate),
            "preset_buyzone": bool(preset_buyzone),
            "preset_spring": bool(preset_spring),
            "preset_pullback_active": bool(preset_pullback_active),
            "is_flag_pattern": bool(is_flag_pattern),
            "is_vcp_pattern": bool(is_vcp_pattern),
            "is_base_pattern": bool(is_base_pattern),
            "is_macro_pattern": bool(is_macro_pattern),
            "pattern_confluence_score": pattern_confluence_score,
            "dist_from_poc_pct": dist_poc,
            "is_above_poc": is_above_poc,
        })

    active_triggered_trades = [s for s in output_stocks if s.get("is_active_trade")]
    potential_stalking_pool = [
        s for s in output_stocks
        if (s.get("balanced_pick") or s.get("is_potential_stalking")) and not s.get("is_active_trade")
    ][:12]

    payload = {
        "as_of_date": str(latest_date),
        "corporate_actions_normalized_count": len(corp_events),
        "market_breadth_pct": round(market_breadth_pct, 2),
        "market_breadth_5d_change": breadth_5d_change,
        "benchmark_mrs_pct": round(bm_mrs, 2),
        "market_regime_label": regime_label,
        "daily_active_quota": max_active_quota,
        "page_size": 50,
        "total_stocks": len(output_stocks),
        "total_pages": (len(output_stocks) + 49) // 50,
        "active_triggered_trades_count": len(active_triggered_trades),
        "potential_stalking_pool_count": len(potential_stalking_pool),
        "risk_profile_allocations": {
            "conservative_count": len(conservative_picks_set),
            "balanced_count": len(dynamic_picks_map),
            "aggressive_count": len(aggressive_picks_set),
        },
        "sectors": sector_summary.to_dict(orient="records"),
        "sector_rs_history": sector_rs_history,
        "active_triggered_trades": active_triggered_trades,
        "potential_stalking_pool": potential_stalking_pool,
        "stocks": output_stocks,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[✓] Pipeline complete. Saved {len(output_stocks)} stocks to {OUTPUT_JSON}.")
    print(f"    -> Market Regime: {regime_label} (Max Daily Actionable Slots: {max_active_quota})")
    print(f"    -> 🎯 Upper Section (Confirmed Actionable Trades): {len(active_triggered_trades)}")
    print(f"    -> 🔭 Lower Section (Shortlisted Stalking Pool):   {len(potential_stalking_pool)}")

    upload_dashboard_to_supabase(OUTPUT_JSON)


def upload_dashboard_to_supabase(json_path: str):
    supabase_url = os.environ.get("SUPABASE_URL", "https://ydjzbwkaxwcfkqzfndum.supabase.co")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not service_role_key:
        print("[!] SUPABASE_SERVICE_ROLE_KEY environment variable not set. Skipping upload.")
        return

    try:
        supabase = create_client(supabase_url, service_role_key)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        compressed_json_str = json.dumps(data, separators=(',', ':'))
        compressed_bytes = compressed_json_str.encode('utf-8')

        supabase.storage.from_("secure-quant").upload(
            path="dashboard_data.json",
            file=compressed_bytes,
            file_options={"cache-control": "300", "upsert": "true", "content-type": "application/json"},
        )
        print("[✓] Successfully uploaded compressed dashboard_data.json to Supabase Storage.")
    except Exception as e:
        print(f"[!] Failed to upload to Supabase Storage: {e}")


if __name__ == "__main__":
    run_screener_engine()