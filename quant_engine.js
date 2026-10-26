// ============================================================================
// 1. CONFIGURATION, CONSTANTS & GLOBAL STATE
// ============================================================================
const SUPABASE_URL = 'https://ydjzbwkaxwcfkqzfndum.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inlkanpid2theHdjZmtxemZuZHVtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE0NTA0MTAsImV4cCI6MjEwNzAyNjQxMH0.c4GuhJeSiy_oomdsg51Phua10FrXJBDn3R9xHlB-h6E';

const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
let currentUser = null;
let userProfile = null;
let isAuthListenerAttached = false;

// Public Index Composition - Safe to expose in Frontend
const NIFTY_50_SET = new Set([
  "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", 
  "BAJFINANCE", "BEL", "BHARTIARTL", "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY", 
  "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", 
  "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT", 
  "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", 
  "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", 
  "TITAN", "TRENT", "ULTRACEMCO", "WIPRO"
]);

const NIFTY_NEXT_50_SET = new Set([
  "ABB", "AMBUJACEM", "BANKBARODA", "BERGEPAINT", "BHEL", "BOSCHLTD", "CANBK", "CHOLAFIN", 
  "COLPAL", "DLF", "GAIL", "GODREJCP", "HAL", "HAVELLS", "ICICIGI", "ICICIPRULI", "INDIGO", 
  "IOC", "IRCTC", "JINDALSTEL", "JIOFIN", "LTIM", "MOTHERSON", "NAUKRI", "PIDILITIND", 
  "PFC", "PNB", "RECLTD", "SIEMENS", "SRF", "TORNTPHARM", "TVSMOTOR", "UNITDSPR", "VBL", 
  "VEDL", "ZYDUSLIFE", "ZOMATO"
]);

let appState = {
  asOfDate: "",
  marketRegimeLabel: "",
  sectors: [],
  sectorRsHistory: {},
  priceHistory: {},
  backtestData: null,
  selectedBacktestQuarterIdx: 0,
  selectedBacktestMode: "dynamic_regime_portfolio",
  selectedBacktestPortfolioSize: "10",
  selectedBacktestMcap: "ALL",
  landingFilter: "surety",
  stocks: [],
  selectedSector: "ALL",
  selectedIndex: "Nifty 500",
  strategyMode: "surety",
  selectedPatternFilter: "ALL",
  filterConfluenceOnly: false,
  activePreset: null,
  hideExtended: false,
  searchQuery: "",
  sortCol: "score",
  sortAsc: false,
  currentPage: 1,
  pageSize: 50,
  filteredStocks: [],
  selectedChartSectors: [],
  selectedDrilldownSector: null,
  selectedDrilldownStocks: [],
  watchlist: []
};

// ============================================================================
// 2. QUANTITATIVE SCORING, STRATEGY CRITERIA & FILTERING LOGIC
// ============================================================================
function getStrategyScore(st, mode) {
  if (mode === 'surety') return Number(st.score_surety_anchor ?? st.surety_score ?? st.ignition_score ?? 0);
  if (mode === 'momentum') return Number(st.score_momentum_frontrunner ?? st.frontrunner_score ?? 0);
  if (mode === 'rotation') return Number(st.score_early_sector_rotation ?? st.ignition_score ?? 0);
  if (mode === 'pullback') return Number(st.score_high_rs_pullback ?? st.surety_score ?? 0);
  return Number(st.score_surety_anchor ?? st.surety_score ?? st.ignition_score ?? 0);
}

function matchesStrategyCriteria(st, mode) {
  if (mode === 'surety') return st.is_surety_candidate === true;
  if (mode === 'momentum') return st.is_momentum_candidate === true;
  if (mode === 'rotation') return st.is_rotation_candidate === true;
  if (mode === 'pullback') return st.is_pullback_candidate === true;
  return true;
}

function matchIndexToken(st, selectedIndex) {
  if (!selectedIndex || selectedIndex === "ALL") return true;

  const sym = String(st.symbol || "").trim().toUpperCase();
  const rawIndex = String(st.index_name || "").toUpperCase();
  const mcapTier = String(st.mcap_tier || "").toUpperCase();
  const target = selectedIndex.trim().toUpperCase();
  const tokens = rawIndex.split(',').map(s => s.trim()).filter(Boolean);

  const isLargeCap100 = NIFTY_50_SET.has(sym) || NIFTY_NEXT_50_SET.has(sym) || tokens.includes("NIFTY 50") || tokens.includes("NIFTY NEXT 50");

  if (target === "NIFTY 50") {
    return NIFTY_50_SET.has(sym) || tokens.includes("NIFTY 50");
  }

  if (target === "NIFTY NEXT 50") {
    return NIFTY_NEXT_50_SET.has(sym) || tokens.includes("NIFTY NEXT 50");
  }

  if (target === "NIFTY 500") {
    return tokens.includes("NIFTY 500") || isLargeCap100 || tokens.includes("NIFTY MIDCAP 150") || tokens.includes("NIFTY SMALLCAP 250");
  }

  if (target === "NIFTY MIDCAP 150") {
    if (tokens.includes("NIFTY MIDCAP 150") || mcapTier.includes("MID CAP")) return true;
    if (!isLargeCap100 && !tokens.includes("NIFTY SMALLCAP 250") && !tokens.includes("NIFTY MICROCAP 250") && tokens.includes("NIFTY 500")) {
      return true;
    }
    return false;
  }

  if (target === "NIFTY SMALLCAP 250") {
    if (tokens.includes("NIFTY SMALLCAP 250") || mcapTier.includes("SMALL CAP")) return true;
    if (!isLargeCap100 && !tokens.includes("NIFTY MIDCAP 150") && !tokens.includes("NIFTY MICROCAP 250") && tokens.includes("NIFTY 500")) {
      return true;
    }
    return false;
  }

  if (target === "NIFTY MICROCAP 250") {
    if (tokens.includes("NIFTY MICROCAP 250") || mcapTier.includes("MICROCAP") || mcapTier.includes("TIER 4")) return true;
    if (!isLargeCap100 && !tokens.includes("NIFTY 500")) return true;
    return false;
  }

  return tokens.includes(target);
}

function calculatePatternConfluence(st) {
  return st.pattern_confluence_score || 0;
}

function deriveBacktestMcapTier(pick) {
  if (pick.mcap_tier) return pick.mcap_tier;
  const sym = String(pick.symbol || "").toUpperCase();
  const idxStr = String(pick.index_name || "").toUpperCase();
  const tokens = idxStr.split(',').map(s => s.trim());
  if (NIFTY_50_SET.has(sym) || NIFTY_NEXT_50_SET.has(sym) || tokens.includes("NIFTY 50") || tokens.includes("NIFTY NEXT 50")) {
    return "Tier 1: Large Cap (Nifty 100)";
  }
  if (idxStr.includes("MICROCAP")) return "Tier 4: Microcap";
  if (idxStr.includes("MIDCAP")) return "Tier 2: Mid Cap";
  if (idxStr.includes("SMALLCAP")) return "Tier 3: Small Cap";
  return "Tier 2/3: Mid & Small Cap";
}

function matchBacktestMcapFilter(pick, filterKey) {
  if (!filterKey || filterKey === "ALL") return true;
  const tierStr = deriveBacktestMcapTier(pick).toUpperCase();
  if (filterKey === "LARGE") return tierStr.includes("LARGE") || tierStr.includes("TIER 1");
  if (filterKey === "MICRO") return tierStr.includes("MICROCAP") || tierStr.includes("TIER 4");
  if (filterKey === "MID_SMALL") return tierStr.includes("MID") || tierStr.includes("SMALL") || tierStr.includes("TIER 2") || tierStr.includes("TIER 3");
  return true;
}

function applyFilterAndSort() {
  appState.filteredStocks = appState.stocks.filter(st => {
    const matchSec = appState.selectedSector === "ALL" || st.sector === appState.selectedSector;
    const matchIdx = matchIndexToken(st, appState.selectedIndex);

    let matchStrategy = true;
    if (appState.strategyMode !== 'all') {
      matchStrategy = matchesStrategyCriteria(st, appState.strategyMode);
    }

    let matchPreset = true;
    if (appState.activePreset === 'BuyZone') {
      matchPreset = st.preset_buyzone === true;
    } else if (appState.activePreset === 'Spring') {
      matchPreset = st.preset_spring === true;
    } else if (appState.activePreset === 'Pullback') {
      matchPreset = st.preset_pullback_active === true;
    }

    const matchExt = !appState.hideExtended || (st.mrs_score <= 8.0);
    const query = appState.searchQuery.toUpperCase();
    const matchQuery = !query || st.symbol.toUpperCase().includes(query) || (st.company_name && st.company_name.toUpperCase().includes(query));

    return matchSec && matchIdx && matchStrategy && matchPreset && matchExt && matchQuery;
  });

  updateUIAfterFilter();
}

function updateUIAfterFilter() {
  appState.filteredStocks.sort((a, b) => {
    let vA = 0;
    let vB = 0;
    if (appState.sortCol === 'score') {
      vA = getStrategyScore(a, appState.strategyMode);
      vB = getStrategyScore(b, appState.strategyMode);
    } else {
      vA = a[appState.sortCol] ?? 0;
      vB = b[appState.sortCol] ?? 0;
    }
    return appState.sortAsc ? (vA > vB ? 1 : -1) : (vA < vB ? 1 : -1);
  });

  const arrowSpans = document.querySelectorAll('#mainStockTable thead th span[id^="sort_"]');
  arrowSpans.forEach(span => { span.textContent = ''; });
  const activeSortSpan = document.getElementById(`sort_${appState.sortCol}`);
  if (activeSortSpan) {
    activeSortSpan.textContent = appState.sortAsc ? ' ▲' : ' ▼';
  }

  appState.currentPage = 1;
  renderTablePage();
  updateGlobalBadge();
}

// ============================================================================
// 3. AUTHENTICATION, SUBSCRIPTION & DATA INITIALIZATION
// ============================================================================
async function enforceAccessControl() {
  const hostname = window.location.hostname;
  if (!hostname || hostname === 'localhost' || hostname === '127.0.0.1' || window.location.protocol === 'file:') {
    currentUser = { id: "local-dev-user", email: "developer@local.test" };
    userProfile = { is_pro: true, trial_ends_at: "2099-01-01" };
    updateAuthUI();
    return true; 
  }

  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('dev_mode') === 'true' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
    currentUser = { id: "local-dev-user", email: "developer@local.test" };
    userProfile = { is_pro: true, trial_ends_at: "2099-01-01" };
    updateAuthUI();
    return true;
  }

  let { data: { session }, error: sessionErr } = await sb.auth.getSession();
  
  if (sessionErr) {
    console.error("RAW SUPABASE SESSION ERROR:", JSON.stringify(sessionErr, null, 2));
    showToast("Session Error: " + sessionErr.message);
  }

  if (!session) {
    await new Promise(resolve => setTimeout(resolve, 1200));
    const retrySession = await sb.auth.getSession();
    session = retrySession.data.session;
  }

  if (!session) {
    currentUser = null;
    userProfile = null;
    updateAuthUI();
    return false;
  }

  currentUser = session.user;
  updateAuthUI();

  let { data: profile, error: profileErr } = await sb.from('profiles').select('*').eq('id', currentUser.id).single();

  if (profileErr || !profile) {
    const trialDays = 2; 
    const trialEnds = new Date();
    trialEnds.setDate(trialEnds.getDate() + trialDays);

    const newProfile = {
      id: currentUser.id,
      email: currentUser.email,
      trial_ends_at: trialEnds.toISOString(),
      is_pro: false
    };
    
    const { error: insertErr } = await sb.from('profiles').upsert([newProfile]);
    if (insertErr) {
      console.error("RAW PROFILES UPSERT ERROR:", JSON.stringify(insertErr, null, 2));
      showToast("DB Error: Could not sync user profile.");
      return false;
    }
    profile = newProfile;
  }

  userProfile = profile;
  evaluateAccess();
  await loadCloudWatchlist();
  return true;
}

function enforcePaywallDisplay(state) {
  const overlay = document.getElementById('paywallOverlay');
  const loginBtn = document.getElementById('modalLoginBtn');
  const desc = document.getElementById('paywallModalDesc');

  if (state === 'TRIAL_EXPIRED') {
    document.body.classList.add('content-locked');
    if (overlay) overlay.style.display = 'flex';
    
    if (!currentUser) {
      if (loginBtn) loginBtn.style.display = 'block';
      if (desc) desc.textContent = "Please sign in with your Google account to access your active 2-day trial or upgrade to Pro.";
    } else {
      if (loginBtn) loginBtn.style.display = 'none';
      if (desc) desc.textContent = "Your 2-day free trial has expired. Upgrade to Pro to continue accessing institutional momentum scans and 50/50 ATR split entries.";
    }
  } else {
    document.body.classList.remove('content-locked');
    if (overlay) overlay.style.display = 'none';
  }
}

async function loginWithGoogle() {
  const { error } = await sb.auth.signInWithOAuth({
    provider: 'google',
    options: { 
      redirectTo: window.location.origin + window.location.pathname
    }
  });
  if (error) {
    console.error("OAuth login error:", error.message);
    showToast("Login failed: " + error.message);
  }
}

async function fetchSecureScreenerData() {
  const hostname = window.location.hostname;
  
  if (!hostname || hostname === 'localhost' || hostname === '127.0.0.1' || window.location.protocol === 'file:') {
    try {
      const localRes = await fetch(`./dashboard_data.json?t=${Date.now()}`);
      if (localRes.ok) {
        enforcePaywallDisplay('ACTIVE');
        return await localRes.json();
      }
    } catch (e) {
      console.warn("Local dashboard_data.json not found in root directory.");
    }
  }

  const { data: { session } } = await sb.auth.getSession();
  
  if (!session) {
    updateAuthUI();
    return null;
  }

  try {
    // 1. Fetch Signed URL from Edge Function (Fast Permission Check)
    const { data: authData, error: authError } = await sb.functions.invoke('dynamic-endpoint', {
      method: 'GET'
    });

    if (authError || !authData || !authData.signed_url) {
      console.warn("[Functions Error]", authError);
      enforcePaywallDisplay('TRIAL_EXPIRED');
      return null;
    }

    // 2. Fetch Dashboard Payload Directly from CDN using Signed URL
    const jsonResponse = await fetch(authData.signed_url);
    if (!jsonResponse.ok) throw new Error("Failed to download payload from signed URL.");

    const payload = await jsonResponse.json();
    enforcePaywallDisplay('ACTIVE');
    return payload;

  } catch (err) {
    console.error("Failed to load secure screener data:", err);
    return null;
  }
}

// Add these helper functions at the bottom or near init()
function showLoader() {
  const loader = document.getElementById('globalLoader');
  if (loader) loader.classList.remove('hidden');
}

function hideLoader() {
  const loader = document.getElementById('globalLoader');
  if (loader) loader.classList.add('hidden');
}

// Update your init() function
async function init() {
  try {
    // 1. Auth check runs first (invisible to user, updates UI headers instantly)
    const hasAccess = await enforceAccessControl();
    if (!hasAccess) {
      document.getElementById('asOfBadge').textContent = "Access Locked - Login Required";
      return; 
    }

    if (!isAuthListenerAttached) {
      isAuthListenerAttached = true;
      sb.auth.onAuthStateChange(async (event, session) => {
        if (event === 'SIGNED_IN' && session && (!currentUser || currentUser.id !== session.user.id)) {
          currentUser = session.user;
          updateAuthUI();
          await init();
        } else if (event === 'SIGNED_OUT') {
          currentUser = null;
          userProfile = null;
          updateAuthUI();
          enforcePaywallDisplay('AUTH_REQUIRED');
        }
      });
    }

    // 🔥 SHOW LOADER HERE: Site shell is visible, now we fetch data
    showLoader();

    // A. Fetch ONLY the critical dashboard file
    const data = await fetchSecureScreenerData();

    if (!data) {
      document.getElementById('asOfBadge').textContent = "Access Restricted";
      document.getElementById('stockCountBadge').textContent = "0 Stocks";
      return; 
    }

    enforcePaywallDisplay('ACTIVE');

    appState.asOfDate = data.as_of_date || "";
    appState.marketRegimeLabel = data.market_regime_label || "Dynamic Mix Active";
    appState.sectors = (data.sectors || []).filter(s => s.sector !== "General Equities");
    appState.sectorRsHistory = data.sector_rs_history || {};
    
    const rawStocks = data.stocks || [];
    appState.stocks = rawStocks.filter(st => {
      const sym = String(st.symbol || "").trim().toUpperCase();
      if (sym === "SUNSHINE" || sym === "SUNSHINEPIX" || !st.close || !st.sma_20 || !st.sma_50) return false;
      return true;
    });

    appState.selectedChartSectors = appState.sectors.slice(0, 6).map(s => s.sector);
    
    const asOfBadge = document.getElementById('asOfBadge');
    if (asOfBadge) asOfBadge.textContent = `EOD: ${appState.asOfDate}`;
    
    // 1. CRITICAL RENDER PATH
    if (typeof renderLandingDashboard === 'function') renderLandingDashboard();
    if (typeof updateWatchlistBadge === 'function') updateWatchlistBadge();
    if (typeof updateGlobalBadge === 'function') updateGlobalBadge();
    if (typeof updateAuthUI === 'function') updateAuthUI();

    // 2. DEFERRED UI RENDERING
    setTimeout(() => {
      if (typeof populateSectorDropdowns === 'function') populateSectorDropdowns();
      if (typeof applyFilterAndSort === 'function') applyFilterAndSort();     
      if (typeof renderSectorChips === 'function') renderSectorChips();      
      if (typeof renderSectorTiles === 'function') renderSectorTiles();      
      if (typeof renderSectorRsChart === 'function') renderSectorRsChart();    
      if (typeof renderPatternsTable === 'function') renderPatternsTable();    
    }, 10);

    if (!localStorage.getItem('nse_alpha_tour_completed')) {
      setTimeout(() => {
        if (typeof startProductTour === 'function') startProductTour();
      }, 800);
    }
    
    // 3. BACKGROUND DATA FETCH 
    if (typeof loadAuxiliaryData === 'function') loadAuxiliaryData();
    
  } catch (err) {
    console.error("Initialization error:", err);
    const asOfBadge = document.getElementById('asOfBadge');
    if (asOfBadge) asOfBadge.textContent = "Run pipeline first";
  } finally {
    // 🔥 HIDE LOADER EXACTLY HERE: Runs no matter what
    hideLoader();
  }
}

async function loadAuxiliaryData() {
  try {
    const [priceRes, btRes] = await Promise.all([
      fetch(`./data/price_history.json?t=${Date.now()}`).catch(() => ({ ok: false })),
      fetch(`./backtest_data.json?t=${Date.now()}`).catch(() => ({ ok: false }))
    ]);
    
    if (priceRes.ok) {
      appState.priceHistory = await priceRes.json();
      if (stockRsChartInstance && appState.selectedDrilldownSector) {
        renderStockRsChart();
      }
    }
    
    if (btRes && btRes.ok) {
      appState.backtestData = await btRes.json();
      const btView = document.getElementById('viewBacktest');
      if (btView && btView.classList.contains('active')) {
        renderBacktestView();
      }
    }
  } catch(e) {
    console.warn("Failed to silently load auxiliary data.", e);
  }
}

// 5. Silently streams in the heavy files while the user is already viewing the dashboard
async function loadAuxiliaryData() {
  try {
    const [priceRes, btRes] = await Promise.all([
      fetch(`./data/price_history.json?t=${Date.now()}`).catch(() => ({ ok: false })),
      fetch(`./backtest_data.json?t=${Date.now()}`).catch(() => ({ ok: false }))
    ]);
    
    if (priceRes.ok) {
      appState.priceHistory = await priceRes.json();
      // If the user already clicked into a drill-down chart, refresh it seamlessly
      if (stockRsChartInstance) renderStockRsChart();
    }
    
    if (btRes.ok) {
      appState.backtestData = await btRes.json();
      // If the user already clicked the Backtest tab, render the data instantly
      if (document.getElementById('viewBacktest')?.classList.contains('active')) {
        renderBacktestView();
      }
    }
  } catch(e) {
    console.warn("Failed to silently load auxiliary data.", e);
  }
}

async function fetchUserProfile(userId) {
  if (!userId) return;
  const { data } = await sb.from('profiles').select('*').eq('id', userId).single();
  userProfile = data;
  evaluateAccess();
  await loadCloudWatchlist();
}

function evaluateAccess() {
  if (!currentUser || !userProfile) {
    enforcePaywallDisplay('ACTIVE'); 
    return;
  }

  const now = new Date();
  const trialEnd = new Date(userProfile.trial_ends_at);
  const isTrialActive = now < trialEnd;
  const isPro = userProfile.is_pro === true;

  const badge = document.getElementById('trialBadge');
  const subBanner = document.getElementById('subBanner');
  const subBannerText = document.getElementById('subBannerText');
  
  if (badge) badge.style.display = 'inline-block';

  if (isPro) {
    if (badge) {
      badge.textContent = "⭐ Pro Member";
      badge.style.borderColor = "var(--green)";
      badge.style.color = "var(--green)";
    }
    if (subBanner) subBanner.style.display = 'none';
    enforcePaywallDisplay('ACTIVE');
  } else if (isTrialActive) {
    const daysLeft = Math.ceil((trialEnd - now) / (1000 * 60 * 60 * 24));
    if (badge) {
      badge.textContent = `⏳ Free Trial (${daysLeft}d left)`;
      badge.style.borderColor = "var(--yellow)";
      badge.style.color = "var(--yellow)";
    }
    if (subBanner) {
      subBanner.style.display = 'flex';
      if (subBannerText) {
        subBannerText.innerHTML = `⏳ <strong>Free Trial Active (${daysLeft} days left):</strong> Institutional trial active.`;
      }
    }
    enforcePaywallDisplay('ACTIVE');
  } else {
    if (badge) {
      badge.textContent = "❌ Trial Expired";
      badge.style.borderColor = "var(--red)";
      badge.style.color = "var(--red)";
    }
    if (subBanner) subBanner.style.display = 'none';
    enforcePaywallDisplay('TRIAL_EXPIRED');
  }
}

async function payWithRazorpay() {
  if (!currentUser) {
    showToast("Please log in first.");
    return;
  }

  const orderReq = await fetch('/api/create-order', { method: 'POST' });
  const orderData = await orderReq.json();

  if (!orderData.id) {
    showToast("Failed to initiate payment. Please try again.");
    return;
  }

  const options = {
    "key": "rzp_live_Trdtyh6l3mOHtP", 
    "amount": orderData.amount,
    "currency": orderData.currency,
    "name": "NSE Alpha Pro",
    "description": "1 Year Institutional Access",
    "order_id": orderData.id, 
    "handler": async function (response) {
      showToast("Verifying payment securely...");
      
      const verifyReq = await fetch('/api/verify-payment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          razorpay_order_id: response.razorpay_order_id,
          razorpay_payment_id: response.razorpay_payment_id,
          razorpay_signature: response.razorpay_signature,
          user_id: currentUser.id
        })
      });

      const verifyData = await verifyReq.json();

      if (verifyData.success) {
        showToast("Payment verified! Pro access granted for 1 year 🎉");
        setTimeout(() => location.reload(), 1500);
      } else {
        showToast("Payment verification failed. Contact support.");
      }
    },
    "prefill": {
      "email": currentUser.email
    },
    "theme": {
      "color": "#38bdf8"
    }
  };
  
  const rzp = new Razorpay(options);
  rzp.open();
}

async function handleLogout() {
  await sb.auth.signOut();
  location.reload();
}

function updateAuthUI() {
  const authContainer = document.getElementById('authContainer');
  const userProfileContainer = document.getElementById('userProfileContainer');
  const emailDisplay = document.getElementById('userEmailDisplay');

  if (currentUser) {
    if (authContainer) authContainer.style.display = 'none';
    if (userProfileContainer) {
      userProfileContainer.style.display = 'flex';
      if (emailDisplay) emailDisplay.textContent = currentUser.email;
    }
  } else {
    if (authContainer) authContainer.style.display = 'block';
    if (userProfileContainer) userProfileContainer.style.display = 'none';
  }
}

// ============================================================================
// 4. WATCHLIST DATA PERSISTENCE (SUPABASE + LOCALSTORAGE)
// ============================================================================
async function loadCloudWatchlist() {
  if (!currentUser || currentUser.id === "local-dev-user") return;
  const { data } = await sb.from('watchlists').select('symbol').eq('user_id', currentUser.id);
  if (data) {
    appState.watchlist = [...new Set(data.map(item => String(item.symbol).trim().toUpperCase()))];
    localStorage.setItem('my_quant_watchlist', JSON.stringify(appState.watchlist));
    updateWatchlistBadge();
    renderTablePage();
    if (document.getElementById('viewWatchlist').classList.contains('active')) renderWatchlistPage();
    updateGlobalBadge();
  }
}

window.toggleWatchlist = async function(symbol, event) {
  if (event) event.stopPropagation();
  const sym = String(symbol).trim().toUpperCase();
  const idx = appState.watchlist.indexOf(sym);

  if (idx > -1) {
    appState.watchlist.splice(idx, 1);
    if (currentUser && currentUser.id !== "local-dev-user") {
      await sb.from('watchlists').delete().eq('user_id', currentUser.id).eq('symbol', sym);
    }
    showToast(`Removed ${sym} from Watchlist`);
  } else {
    appState.watchlist.push(sym);
    if (currentUser && currentUser.id !== "local-dev-user") {
      await sb.from('watchlists').insert([{ user_id: currentUser.id, symbol: sym }]);
    }
    showToast(`Added ${sym} to Watchlist ⭐`);
  }

  appState.watchlist = [...new Set(appState.watchlist)];
  localStorage.setItem('my_quant_watchlist', JSON.stringify(appState.watchlist));
  updateWatchlistBadge();
  renderTablePage();
  renderLandingDashboard();
  if (appState.selectedDrilldownSector) renderSectorDrilldown(appState.selectedDrilldownSector);
  if (document.getElementById('viewWatchlist').classList.contains('active')) renderWatchlistPage();
  if (document.getElementById('viewBacktest').classList.contains('active')) renderBacktestView();
  if (document.getElementById('viewPatterns').classList.contains('active')) renderPatternsTable();
  updateGlobalBadge();
};

function cleanupWatchlist() {
  const beforeCount = appState.watchlist.length;
  appState.watchlist = appState.watchlist.filter(sym => appState.stocks.some(s => s.symbol.toUpperCase() === sym));
  localStorage.setItem('my_quant_watchlist', JSON.stringify(appState.watchlist));
  updateWatchlistBadge();
  renderWatchlistPage();
  updateGlobalBadge();
  showToast(`Cleaned up ${beforeCount - appState.watchlist.length} outdated tickers`);
}

function clearWatchlist() {
  if (!confirm("Are you sure you want to clear your entire watchlist?")) return;
  appState.watchlist = [];
  localStorage.setItem('my_quant_watchlist', JSON.stringify([]));
  updateWatchlistBadge();
  renderWatchlistPage();
  renderTablePage();
  renderLandingDashboard();
  if (document.getElementById('viewPatterns').classList.contains('active')) renderPatternsTable();
  updateGlobalBadge();
  showToast("Watchlist cleared.");
}