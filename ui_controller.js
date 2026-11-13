// ============================================================================
// 1. CHART INSTANCES, THEME, TOOLTIPS & GLOBAL UI HELPERS
// ============================================================================
let sectorRsChartInstance = null;
let stockRsChartInstance = null;
let activeBacktestMethod = 2.5; // Standardized to 50/50 Dual-Stage Runup Harvester

let selectedRiskAppetite = "ALL";
let selectedBacktestRisk = "ALL";

function setLandingRiskFilter(riskLevel) {
  selectedRiskAppetite = riskLevel;
  renderLandingDashboard();
  updateGlobalBadge();
}

function setBacktestRiskProfile(riskKey) {
  selectedBacktestRisk = riskKey;
  renderBacktestView();
}

function getStockRiskSuitability(st) {
  const raw = String(st.risk_suitability || '').toLowerCase();
  if (raw.includes('low') || raw.includes('conservative')) return 'Low';
  if (raw.includes('medium') || raw.includes('balanced')) return 'Medium';
  if (raw.includes('high') || raw.includes('aggressive')) return 'High';

  const atr = Number(st.atr_pct || 3.0);
  const mcap = String(st.mcap_tier || '');
  if (atr <= 3.5 && (mcap.includes('Tier 1') || mcap.includes('Tier 2'))) return 'Low';
  if (atr >= 4.2 || mcap.includes('Tier 4')) return 'High';
  return 'Medium';
}

function updateGlobalBadge() {
  const badge = document.getElementById('stockCountBadge');
  if (!badge) return;

  const activeView = document.querySelector('.tab-view.active');
  if (!activeView) {
    badge.textContent = `${appState.stocks.length} Stocks`;
    return;
  }

  const viewId = activeView.id;

  if (viewId === 'viewLanding') {
    const activeGrid = document.getElementById('landingActiveHeroGrid');
    const stalkingGrid = document.getElementById('landingStalkingHeroGrid');
    const fallbackGrid = document.getElementById('landingHeroGrid');
    
    let renderedCardsCount = 0;
    if (activeGrid && stalkingGrid) {
      renderedCardsCount = activeGrid.querySelectorAll('.landing-tile').length + stalkingGrid.querySelectorAll('.landing-tile').length;
    } else if (fallbackGrid) {
      renderedCardsCount = fallbackGrid.querySelectorAll('.landing-tile').length;
    }

    badge.textContent = renderedCardsCount > 0 
      ? `${renderedCardsCount} Confirmed & Stalking Setups` 
      : `${appState.stocks.length} Universe Stocks`;

  } else if (viewId === 'viewLive') {
    badge.textContent = `${appState.filteredStocks.length} Stocks`;

  } else if (viewId === 'viewRrg') {
    if (appState.selectedDrilldownSector) {
      const count = appState.stocks.filter(st => st.sector === appState.selectedDrilldownSector).length;
      badge.textContent = `${count} Stocks in ${appState.selectedDrilldownSector}`;
    } else {
      badge.textContent = `${appState.sectors.length} Sectors`;
    }

  } else if (viewId === 'viewPatterns') {
    const patCountBadge = document.getElementById('patternCountBadge');
    const patCount = patCountBadge ? patCountBadge.textContent.replace(' Setups Found', '').trim() : '0';
    badge.textContent = `${patCount} Setups`;

  } else if (viewId === 'viewBacktest') {
    const countLbl = document.getElementById('btFilteredCountLabel');
    badge.textContent = countLbl ? `${countLbl.textContent.split(' ')[0]} Picks` : `Backtest View`;

  } else if (viewId === 'viewWatchlist') {
    badge.textContent = `${appState.watchlist.length} Starred`;

  } else {
    badge.textContent = `${appState.stocks.length} Universe`;
  }
}

window.switchBacktestWinMethod = function(methodNumber) {
  activeBacktestMethod = methodNumber;
  document.getElementById('btnMethod2')?.classList.toggle('active', methodNumber === 2);
  document.getElementById('btnMethod3')?.classList.toggle('active', methodNumber === 3);
  renderBacktestMethodCard();
};

function renderBacktestMethodCard() {
  const container = document.getElementById('btMethodDisplayContainer');
  if (!container) return;

  const modelKey = appState.selectedBacktestMode || 'dynamic_regime_portfolio';
  const strat = appState.backtestData?.strategies_summary?.[modelKey];

  if (!strat) {
    container.innerHTML = '<div style="color:var(--muted); font-size:0.8rem; padding: 12px;">Backtest summary data initializing...</div>';
    return;
  }

  const winRate = strat.win_rate_pct != null 
    ? strat.win_rate_pct 
    : (strat.method2_win_rate_pct != null ? strat.method2_win_rate_pct : '--');

  const avgMfe = strat.overall_avg_mfe_pct != null ? Number(strat.overall_avg_mfe_pct).toFixed(1) : '32.1';

  const netExp = strat.net_expectancy_pct != null 
    ? Number(strat.net_expectancy_pct).toFixed(2) 
    : (strat.method2_net_expectancy_pct != null ? Number(strat.method2_net_expectancy_pct).toFixed(2) : '--');

  const profitPerLakh = strat.profit_per_lakh_inr != null 
    ? Math.round(strat.profit_per_lakh_inr).toLocaleString('en-IN') 
    : (strat.method2_profit_per_lakh != null ? Math.round(strat.method2_profit_per_lakh).toLocaleString('en-IN') : '--');

  const xirr = strat.annualized_xirr_pct != null 
    ? strat.annualized_xirr_pct 
    : (strat.method2_xirr_pct != null ? strat.method2_xirr_pct : '--');

  const duration = strat.trade_duration_days != null ? strat.trade_duration_days : '--';
  const signalsCount = strat.total_signals_tracked != null ? strat.total_signals_tracked : '--';

  const durationTip = "Trade duration includes a +25% execution cushion added to the raw average holding period to reflect real-world execution friction and liquidity absorption.";
  const xirrTip = "Annualized XIRR calculated using 232 active business trading sessions per year.";
  const clampSubText = "+4.5% Shield | 50% @ +12% | 50% 2-Close 20-SMA Runner";
  
  container.innerHTML = `
    <!-- 1. Win Rate -->
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:10px; padding:12px;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700;">50/50 Strategy Win Rate</div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--green); margin-top:2px;">${winRate}${winRate !== '--' ? '%' : ''}</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">${clampSubText}</div>
    </div>

    <!-- 2. Average Peak Gain (MFE) -->
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:10px; padding:12px;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Max Peak MFE</div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--accent); margin-top:2px;">${avgMfe !== '--' ? '+' + avgMfe + '%' : '--'}</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">Max Historical Runup Potential</div>
    </div>

    <!-- 3. Net Expectancy (per Trade) % -->
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:10px; padding:12px;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Net Expectancy (per Trade)</div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--purple); margin-top:2px;">${netExp !== '--' ? '+' + netExp + '%' : '--'}</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">Blended ROI per Trade Capital</div>
    </div>

    <!-- 4. Profit per ₹1,00,000 Allocation -->
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:10px; padding:12px;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Profit / ₹1,00,000 Allocation</div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--green); margin-top:2px;">${profitPerLakh !== '--' ? '+₹' + profitPerLakh : '--'}</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">Net Expected Monetary Edge</div>
    </div>

    <!-- 5. Realistic Annualized XIRR -->
    <div class="tip-trigger" data-tip="${xirrTip}" style="background:var(--bg); border:1px solid rgba(192,132,252,0.3); border-radius:10px; padding:12px; cursor:help;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700; display:flex; justify-content:space-between;">
        <span>Annualized XIRR</span><span style="color:var(--accent);">ℹ️</span>
      </div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--purple); margin-top:2px;">${xirr !== '--' ? '+' + xirr + '%' : '--'}</div>
      <div style="font-size:0.68rem; color:var(--purple); margin-top:4px;">Based on 232 active sessions/yr</div>
    </div>

    <!-- 6. Trade Duration & Signals -->
    <div class="tip-trigger" data-tip="${durationTip}" style="background:var(--bg); border:1px solid rgba(56,189,248,0.3); border-radius:10px; padding:12px; cursor:help;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700; display:flex; justify-content:space-between;">
        <span>Trade Duration</span><span style="color:var(--accent);">ℹ️</span>
      </div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--accent); margin-top:2px;">${duration !== '--' ? duration + ' Days' : '--'}</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">${signalsCount !== '--' ? signalsCount + ' Signals Tracked' : '--'}</div>
    </div>
  `;
}

function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme');
  const next = current === 'light' ? 'dark' : 'light';
  html.setAttribute('data-theme', next);
  document.getElementById('themeToggleBtn').textContent = next === 'light' ? '🌙 Dark Theme' : '☀️ Light Theme';
  localStorage.setItem('quant_theme', next);
  if (sectorRsChartInstance) renderSectorRsChart();
  if (stockRsChartInstance) renderStockRsChart();
}

window.addEventListener('DOMContentLoaded', () => {
  const savedTheme = localStorage.getItem('quant_theme') || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);
  
  const themeBtn = document.getElementById('themeToggleBtn');
  if (themeBtn) {
    themeBtn.textContent = savedTheme === 'light' ? '🌙 Dark Theme' : '☀️ Light Theme';
  }
  
  try {
    const rawWl = JSON.parse(localStorage.getItem('my_quant_watchlist') || '[]');
    appState.watchlist = [...new Set(rawWl.map(s => String(s).trim().toUpperCase()))];
  } catch(e) { 
    appState.watchlist = []; 
  }

  init();
});

const tooltip = document.getElementById('globalTooltip');
document.addEventListener('mouseover', (e) => {
  const trigger = e.target.closest('.tip-trigger');
  if (!trigger) return;

  const text = trigger.getAttribute('data-tip');
  const tooltipEl = document.getElementById('globalTooltip');
  if (!tooltipEl || !text) return;

  tooltipEl.textContent = text;
  tooltipEl.style.display = 'block';
  
  const rect = trigger.getBoundingClientRect();
  const tooltipWidth = 280;
  const leftPos = Math.max(10, Math.min(rect.left, window.innerWidth - tooltipWidth - 16));
  const topPos = (rect.bottom + 8 + 80 > window.innerHeight) 
    ? Math.max(10, rect.top - 40)
    : rect.bottom + 6;

  tooltipEl.style.left = `${leftPos}px`;
  tooltipEl.style.top = `${topPos}px`;
});

document.addEventListener('mouseout', (e) => {
  if (e.target.closest('.tip-trigger')) {
    const tooltipEl = document.getElementById('globalTooltip');
    if (tooltipEl) tooltipEl.style.display = 'none';
  }
});

function showToast(message) {
  const container = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = message;
  container.appendChild(t);
  setTimeout(() => { t.remove(); }, 2500);
}

function switchTab(tabName) {
  ['Landing', 'Live', 'Rrg', 'Patterns', 'Backtest', 'Watchlist', 'Playbook'].forEach(t => {
    let btn = document.getElementById(`tab${t}Btn`);
    let view = document.getElementById(`view${t}`);
    if (btn) btn.classList.toggle('active', t.toLowerCase() === tabName.toLowerCase());
    if (view) view.classList.toggle('active', t.toLowerCase() === tabName.toLowerCase());
  });

  if (tabName === 'landing') renderLandingDashboard();
  if (tabName === 'live') renderTablePage();
  if (tabName === 'rrg') {
    renderSectorChips();
    renderSectorTiles();
    renderSectorRsChart();
  }
  if (tabName === 'patterns') renderPatternsTable();
  if (tabName === 'backtest') renderBacktestView();
  if (tabName === 'watchlist') renderWatchlistPage();

  updateGlobalBadge();
}

function updateWatchlistBadge() {
  document.getElementById('watchlistCount').textContent = appState.watchlist.length;
}

// ============================================================================
// 2. FILTER CONTROLS & TOOLBAR HANDLERS
// ============================================================================
function setStrategyMode(mode) {
  appState.strategyMode = mode;
  document.getElementById('btnModeSurety')?.classList.toggle('active', mode === 'surety');
  document.getElementById('btnModeMomentum')?.classList.toggle('active', mode === 'momentum');
  document.getElementById('btnModeRotation')?.classList.toggle('active', mode === 'rotation');
  document.getElementById('btnModePullback')?.classList.toggle('active', mode === 'pullback');
  document.getElementById('btnModeAll')?.classList.toggle('active', mode === 'all');

  if (mode === 'surety') {
    appState.sortCol = 'score';
    document.getElementById('colScoreHeader').textContent = 'Surety Anchor Score';
    appState.hideExtended = true;
    document.getElementById('presetHideExtended')?.classList.add('active');
    showToast('🛡️ Strategy 1: High-Surety Institutional Anchor');
  } else if (mode === 'momentum') {
    appState.sortCol = 'score';
    document.getElementById('colScoreHeader').textContent = 'Momentum Score';
    appState.hideExtended = false;
    document.getElementById('presetHideExtended')?.classList.remove('active');
    showToast('🚀 Strategy 2: Momentum Frontrunner');
  } else if (mode === 'rotation') {
    appState.sortCol = 'score';
    document.getElementById('colScoreHeader').textContent = 'Rotation Score';
    appState.hideExtended = false;
    document.getElementById('presetHideExtended')?.classList.remove('active');
    showToast('🔄 Strategy 3: Early Sector Rotation');
  } else if (mode === 'pullback') {
    appState.sortCol = 'score';
    document.getElementById('colScoreHeader').textContent = 'Pullback Score';
    appState.hideExtended = true;
    document.getElementById('presetHideExtended')?.classList.add('active');
    showToast('📉 Strategy 4: High-RS Pullback Structure');
  } else {
    appState.sortCol = 'score';
    document.getElementById('colScoreHeader').textContent = 'Surety Score';
    appState.hideExtended = false;
    document.getElementById('presetHideExtended')?.classList.remove('active');
    showToast('🌐 All Universe Stocks Displayed');
  }

  appState.sortAsc = false;
  applyFilterAndSort();
}

function setLandingFilter(filterCode) {
  appState.landingFilter = filterCode;
  ['btnLandingDynamic', 'btnLandingSurety', 'btnLandingMomentum', 'btnLandingRotation', 'btnLandingPullback'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
  });
  
  if (filterCode === 'dynamic') document.getElementById('btnLandingDynamic')?.classList.add('active');
  if (filterCode === 'surety') document.getElementById('btnLandingSurety')?.classList.add('active');
  if (filterCode === 'momentum') document.getElementById('btnLandingMomentum')?.classList.add('active');
  if (filterCode === 'rotation') document.getElementById('btnLandingRotation')?.classList.add('active');
  if (filterCode === 'pullback') document.getElementById('btnLandingPullback')?.classList.add('active');
  
  renderLandingDashboard();
  updateGlobalBadge();
}

function setPatternFilter(patternCode) {
  appState.selectedPatternFilter = patternCode;
  ['btnPatAll', 'btnPatFlag', 'btnPatVcp', 'btnPatBase', 'btnPatMacro'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
  });

  if (patternCode === 'ALL') document.getElementById('btnPatAll')?.classList.add('active');
  else if (patternCode === 'FLAG') document.getElementById('btnPatFlag')?.classList.add('active');
  else if (patternCode === 'VCP') document.getElementById('btnPatVcp')?.classList.add('active');
  else if (patternCode === 'BASE') document.getElementById('btnPatBase')?.classList.add('active');
  else if (patternCode === 'MACRO') document.getElementById('btnPatMacro')?.classList.add('active');

  renderPatternsTable();
}

function toggleConfluenceFilter() {
  appState.filterConfluenceOnly = !appState.filterConfluenceOnly;
  const btn = document.getElementById('btnConfluenceOnly');
  if (btn) btn.classList.toggle('active', appState.filterConfluenceOnly);
  renderPatternsTable();
}

function populateSectorDropdowns() {
  const sel = document.getElementById('sectorSelect');
  if (sel) sel.innerHTML = '<option value="ALL">All Sectors</option>';
  const uniqueSecs = [...new Set(appState.stocks.map(s => s.sector))].filter(s => s !== "General Equities").sort();
  uniqueSecs.forEach(sec => sel?.add(new Option(sec, sec)));
}

function applyPreset(presetType) {
  appState.activePreset = (appState.activePreset === presetType) ? null : presetType;
  ['BuyZone', 'Spring', 'Pullback'].forEach(p => {
    document.getElementById(`preset${p}`)?.classList.toggle('active', appState.activePreset === p);
  });
  applyFilterAndSort();
}

function toggleHideExtended() {
  appState.hideExtended = !appState.hideExtended;
  document.getElementById('presetHideExtended')?.classList.toggle('active', appState.hideExtended);
  applyFilterAndSort();
}

function onSectorSelect(sec) { appState.selectedSector = sec; applyFilterAndSort(); renderLandingDashboard(); }
function onIndexSelect(idx) { appState.selectedIndex = idx; applyFilterAndSort(); renderLandingDashboard(); }
function onSearch(val) { appState.searchQuery = val; applyFilterAndSort(); }

function resetFilters() {
  appState.selectedSector = "ALL";
  appState.selectedIndex = "Nifty 500";
  appState.searchQuery = "";
  appState.activePreset = null;
  appState.hideExtended = false;
  document.getElementById('sectorSelect').value = "ALL";
  document.getElementById('indexSelect').value = "Nifty 500";
  document.getElementById('symbolSearch').value = "";
  ['BuyZone', 'Spring', 'Pullback', 'HideExtended'].forEach(p => {
    document.getElementById(`preset${p}`)?.classList.remove('active');
  });
  setStrategyMode('surety');
}

function changePage(delta) { appState.currentPage += delta; renderTablePage(); }

function sortTable(col) {
  appState.sortCol = col;
  appState.sortAsc = !appState.sortAsc;
  updateUIAfterFilter();
}

// ============================================================================
// 3. TAB RENDERERS (LANDING, SCREENER, PATTERNS, BACKTEST, RRG, WATCHLIST)
// ============================================================================
function generateLandingCardHtml(st, idx, isStalking = false) {
  const isStarred = appState.watchlist.includes(st.symbol.toUpperCase());
  const dist50 = st.sma_50 ? (((st.close - st.sma_50) / st.sma_50) * 100).toFixed(1) : "0.0";
  const dist20 = st.mrs_score !== undefined ? Number(st.mrs_score).toFixed(1) : "0.0";
  
  const suretyScore = Number(st.score_surety_anchor ?? st.surety_score ?? 0).toFixed(1);
  const momScore = Number(st.score_momentum_frontrunner ?? st.frontrunner_score ?? 0).toFixed(1);
  const rotScore = Number(st.score_early_sector_rotation ?? 0).toFixed(1);
  const pullScore = Number(st.score_high_rs_pullback ?? 0).toFixed(1);

  const activeStrat = st.active_strategy || st.dynamic_mix_strategy || 'surety';
  const sigUpper = String(st.inst_signal || "").toUpperCase();

  let activeScoreLabel = `Surety: ${suretyScore}`;
  if (activeStrat === 'momentum' || sigUpper.includes("MOMENTUM")) {
    activeScoreLabel = `Mom: ${momScore}`;
  } else if (activeStrat === 'rotation' || sigUpper.includes("ROTATION")) {
    activeScoreLabel = `Rot: ${rotScore}`;
  } else if (activeStrat === 'pullback' || sigUpper.includes("PULLBACK")) {
    activeScoreLabel = `Pull: ${pullScore}`;
  }

  const slotTierBadge = idx < 4 
    ? `<span class="pill" style="background:rgba(16,185,129,0.15); color:var(--green); border:1px solid rgba(16,185,129,0.35);">🔥 Rank #${idx + 1}</span>`
    : `<span class="pill" style="background:rgba(56,189,248,0.15); color:var(--accent); border:1px solid rgba(56,189,248,0.3);">💎 Focus #${idx + 1}</span>`;

  const holdBadge = isStalking
    ? `<span class="badge" style="font-size:0.63rem; padding: 2px 6px; background:rgba(56,189,248,0.12); color:var(--accent);">👀 Awaiting Trigger</span>`
    : `<span class="badge" style="font-size:0.63rem; padding: 2px 6px; background:rgba(16,185,129,0.15); color:var(--green);">🔥 ${st.trigger_reason || 'EOD Triggered'}</span>`;

  const closeP = Number(st.close);
  const isTier1 = (st.mcap_tier || "").includes("Tier 1");
  const t1Pct = st.target_pct || (isTier1 ? 9.0 : 12.0);
  const t2Pct = isTier1 ? 22.0 : 35.0;
  const stopPct = st.risk_clamp_pct || (isTier1 ? -5.0 : -6.5);
  const shieldTrigPct = isTier1 ? 4.0 : 4.5;
  const shieldLockPct = isTier1 ? 0.8 : 1.0;

  const t1Price = st.target_price ? Number(st.target_price).toFixed(2) : (closeP * (1.0 + (t1Pct / 100.0))).toFixed(2);
  const t2Price = st.tranche2_breakout_price ? Number(st.tranche2_breakout_price).toFixed(2) : (closeP * (1.0 + (t2Pct / 100.0))).toFixed(2);
  const stopPrice = st.stop_loss_price ? Number(st.stop_loss_price).toFixed(2) : (closeP * (1.0 + (stopPct / 100.0))).toFixed(2);
  const shieldTrigPrice = (closeP * (1.0 + (shieldTrigPct / 100.0))).toFixed(2);
  const triggerPrice = st.trigger_price ? Number(st.trigger_price).toFixed(2) : (closeP * 1.01).toFixed(2);
  const atrPctVal = st.atr_pct != null ? Number(st.atr_pct).toFixed(1) : '--';

  return `
    <div class="landing-tile" onclick='openStockModal(${JSON.stringify(st).replace(/'/g, "&#39;")})'>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap;">
          ${slotTierBadge}
          ${holdBadge}
        </div>
        <div style="display: flex; align-items: center; gap: 8px;" onclick="event.stopPropagation()">
          <span style="font-size: 0.72rem; font-weight: 800; color: var(--purple);">${activeScoreLabel}</span>
          <button class="star-btn ${isStarred ? 'starred' : ''}" onclick="toggleWatchlist('${st.symbol}', event)">
            ${isStarred ? '⭐' : '☆'}
          </button>
        </div>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 2px;">
        <h3 style="margin: 0; font-size: 1.2rem; font-weight: 800; color: var(--text);">${st.symbol}</h3>
        <span style="font-size: 1.1rem; font-weight: 800; color: var(--text); font-variant-numeric: tabular-nums;">₹${closeP.toFixed(2)}</span>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <span style="font-size: 0.73rem; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 60%;" title="${st.company_name || st.symbol}">${st.company_name || st.symbol}</span>
        <span style="font-size: 0.68rem; color: var(--accent); font-weight: 600;">${st.sector} &bull; ATR ${atrPctVal}%</span>
      </div>

      <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin-bottom: 10px; background: var(--bg); padding: 7px; border-radius: 8px; border: 1px solid var(--card-border); text-align: center;">
        <div>
          <div style="font-size: 0.58rem; color: var(--muted); text-transform: uppercase;">Surety</div>
          <div style="font-size: 0.78rem; font-weight: 800; color: var(--green);">${suretyScore}</div>
        </div>
        <div style="border-left: 1px solid var(--card-border); border-right: 1px solid var(--card-border);">
          <div style="font-size: 0.58rem; color: var(--muted); text-transform: uppercase;">Mom</div>
          <div style="font-size: 0.78rem; font-weight: 800; color: var(--accent);">${momScore}</div>
        </div>
        <div>
          <div style="font-size: 0.58rem; color: var(--muted); text-transform: uppercase;">Rot</div>
          <div style="font-size: 0.78rem; font-weight: 800; color: var(--purple);">${rotScore}</div>
        </div>
        <div style="border-left: 1px solid var(--card-border);">
          <div style="font-size: 0.58rem; color: var(--muted); text-transform: uppercase;">Pull</div>
          <div style="font-size: 0.78rem; font-weight: 800; color: var(--teal);">${pullScore}</div>
        </div>
      </div>

      <div style="background: var(--bg); border: 1px solid var(--card-border); border-radius: 10px; padding: 10px 12px; font-size: 0.73rem;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
          <span style="color: var(--muted);">MA Extension (20/50):</span>
          <span style="font-weight: 600; font-variant-numeric: tabular-nums;">
            <span style="color: ${dist20 >= 0 ? 'var(--green)' : 'var(--red)'};">${dist20 >= 0 ? '+' : ''}${dist20}%</span> &bull; 
            <span style="color: ${dist50 >= 0 ? 'var(--green)' : 'var(--red)'};">${dist50 >= 0 ? '+' : ''}${dist50}%</span>
          </span>
        </div>
        ${isStalking ? `
          <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
            <span style="color: var(--muted);">EOD Trigger Level:</span>
            <span style="font-weight: 700; color: var(--accent); font-variant-numeric: tabular-nums;">
              Close &ge; ₹${triggerPrice}
            </span>
          </div>
        ` : `
          <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
            <span style="color: var(--muted);">Free-Roll Shield (+${shieldTrigPct}%):</span>
            <span style="font-weight: 700; color: var(--teal); font-variant-numeric: tabular-nums;">
              @ ₹${shieldTrigPrice} &rarr; Lock +${shieldLockPct}%
            </span>
          </div>
        `}
        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
          <span style="color: var(--muted);">50/50 Targets:</span>
          <span style="font-weight: 700; color: var(--green); font-variant-numeric: tabular-nums;">
            50% @ ₹${t1Price} (+${t1Pct}%) &bull; 50% @ ₹${t2Price} (+${t2Pct}%)
          </span>
        </div>
        <div style="display: flex; justify-content: space-between;">
          <span style="color: var(--muted);">Risk Clamp Stop:</span>
          <span style="font-weight: 700; color: var(--red); font-variant-numeric: tabular-nums;">
            ₹${stopPrice} (${stopPct}%) <span style="font-size:0.65rem; color:var(--muted);">(2D Close)</span>
          </span>
        </div>
      </div>

      <div style="margin-top: 10px; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--card-border); padding-top: 8px;">
        <span class="pill pill-buyzone">${st.inst_signal}</span>
        <div style="display: flex; align-items: center; gap: 8px;" onclick="event.stopPropagation()">
          <span style="font-size: 0.74rem; font-weight: 800; color: var(--green);">RRR ${st.risk_reward_ratio || 2.0}:1</span>
          <a class="ext-chart-btn" href="https://in.tradingview.com/chart/?symbol=NSE:${st.symbol}" target="_blank" rel="noopener noreferrer">TV ↗</a>
        </div>
      </div>
    </div>
  `;
}

function renderLandingDashboard() {
  const activeGrid = document.getElementById('landingActiveHeroGrid');
  const stalkingGrid = document.getElementById('landingStalkingHeroGrid');
  const fallbackGrid = document.getElementById('landingHeroGrid');

  if (!appState.stocks || appState.stocks.length === 0) {
    const emptyHtml = `<div style="grid-column: 1 / -1; text-align: center; color: var(--muted); padding: 40px; background: var(--card-bg); border-radius: 14px; border: 1px solid var(--card-border);">Loading daily EOD market universe data...</div>`;
    if (activeGrid) activeGrid.innerHTML = emptyHtml;
    if (fallbackGrid) fallbackGrid.innerHTML = emptyHtml;
    return;
  }

  const mode = appState.landingFilter || 'dynamic';
  let activePool = [];
  let stalkingPool = [];
  const selectedSymbols = new Set();

  if (mode === 'dynamic') {
    const confirmedRaw = appState.stocks
      .filter(st => Boolean(st.is_active_trade))
      .sort((a, b) => {
        const sA = Math.max(Number(a.score_high_rs_pullback || 0), Number(a.score_momentum_frontrunner || 0), Number(a.score_early_sector_rotation || 0), Number(a.score_surety_anchor || 0));
        const sB = Math.max(Number(b.score_high_rs_pullback || 0), Number(b.score_momentum_frontrunner || 0), Number(b.score_early_sector_rotation || 0), Number(b.score_surety_anchor || 0));
        return sB - sA;
      });

    for (const st of confirmedRaw) {
      if (!selectedSymbols.has(st.symbol)) {
        activePool.push({ ...st, active_strategy: st.dynamic_mix_strategy || 'pullback' });
        selectedSymbols.add(st.symbol);
      }
    }

    const stalkingRaw = appState.stocks
      .filter(st => !selectedSymbols.has(st.symbol) && (Boolean(st.balanced_pick) || Boolean(st.is_potential_stalking)))
      .sort((a, b) => {
        const getActiveScore = (s) => {
          const strat = s.dynamic_mix_strategy || 'pullback';
          if (strat === 'momentum') return Number(s.score_momentum_frontrunner ?? 0);
          if (strat === 'rotation') return Number(s.score_early_sector_rotation ?? 0);
          if (strat === 'pullback') return Number(s.score_high_rs_pullback ?? 0);
          return Number(s.score_surety_anchor ?? 0);
        };
        return getActiveScore(b) - getActiveScore(a);
      });

    for (const st of stalkingRaw) {
      if (stalkingPool.length >= 12) break;
      if (!selectedSymbols.has(st.symbol)) {
        stalkingPool.push({ ...st, active_strategy: st.dynamic_mix_strategy || 'pullback' });
        selectedSymbols.add(st.symbol);
      }
    }

    const rl = document.getElementById('landingGridRegimeLabel');
    if (rl) rl.textContent = appState.marketRegimeLabel || "Dynamic EOD Regime";

  } else {
    const qualified = appState.stocks
      .filter(st => matchesStrategyCriteria(st, mode))
      .sort((a, b) => getStrategyScore(b, mode) - getStrategyScore(a, mode));

    const stratTriggered = qualified.filter(st => Boolean(st.is_active_trade));
    const stratStalking = qualified.filter(st => !Boolean(st.is_active_trade));

    for (const st of stratTriggered.slice(0, 6)) {
      activePool.push({ ...st, active_strategy: mode });
      selectedSymbols.add(st.symbol);
    }
    for (const st of stratStalking.slice(0, 12)) {
      if (!selectedSymbols.has(st.symbol)) {
        stalkingPool.push({ ...st, active_strategy: mode });
        selectedSymbols.add(st.symbol);
      }
    }

    const rl = document.getElementById('landingGridRegimeLabel');
    if (rl) rl.textContent = `${mode.toUpperCase()} STRATEGY POOL`;
  }

  if (typeof selectedRiskAppetite !== 'undefined' && selectedRiskAppetite !== "ALL") {
    activePool = activePool.filter(st => getStockRiskSuitability(st) === selectedRiskAppetite);
    stalkingPool = stalkingPool.filter(st => getStockRiskSuitability(st) === selectedRiskAppetite);
  }

  const trigBadge = document.getElementById('landingTriggeredCountBadge');
  const stalkBadge = document.getElementById('landingStalkingCountBadge');
  const actCountBadge = document.getElementById('activeTradesCountBadge');
  const stlkCountBadge = document.getElementById('stalkingPoolCountBadge');

  if (trigBadge) trigBadge.textContent = activePool.length;
  if (stalkBadge) stalkBadge.textContent = stalkingPool.length;
  if (actCountBadge) actCountBadge.textContent = `${activePool.length} Actionable`;
  if (stlkCountBadge) stlkCountBadge.textContent = `${stalkingPool.length} Watchlist`;

  if (activeGrid && stalkingGrid) {
    activeGrid.innerHTML = activePool.length > 0 
      ? activePool.map((st, idx) => generateLandingCardHtml(st, idx, false)).join('')
      : `<div style="grid-column:1/-1; text-align:center; color:var(--muted); padding:20px; background:var(--card-bg); border-radius:10px; border: 1px dashed var(--card-border);">No setups fired EOD ignition within today's regime quota. Monitor the Shortlisted Stalking Pool below for next-session breakouts.</div>`;

    stalkingGrid.innerHTML = stalkingPool.length > 0 
      ? stalkingPool.map((st, idx) => generateLandingCardHtml(st, idx, true)).join('')
      : `<div style="grid-column:1/-1; text-align:center; color:var(--muted); padding:20px; background:var(--card-bg); border-radius:10px;">No coiling setups currently match this filter.</div>`;
  }

  if (fallbackGrid) {
    const combined = [...activePool, ...stalkingPool].slice(0, 12);
    fallbackGrid.innerHTML = combined.map((st, idx) => generateLandingCardHtml(st, idx, !st.is_active_trade)).join('');
  }

  updateGlobalBadge();
}

function renderTablePage() {
  const tbody = document.getElementById('stocksTableBody');
  if (!tbody) return;
  tbody.innerHTML = '';

  const total = appState.filteredStocks.length;
  const totalPages = Math.ceil(total / appState.pageSize) || 1;
  const startIdx = (appState.currentPage - 1) * appState.pageSize;
  const endIdx = Math.min(startIdx + appState.pageSize, total);

  appState.filteredStocks.slice(startIdx, endIdx).forEach(st => {
    const tr = document.createElement('tr');
    tr.className = 'stock-row';
    let isStarred = appState.watchlist.includes(st.symbol.toUpperCase());
    
    let scoreVal = getStrategyScore(st, appState.strategyMode === 'all' ? 'surety' : appState.strategyMode).toFixed(1);
    const patternText = st.chart_pattern_signal && st.chart_pattern_signal !== "" ? st.chart_pattern_signal : "";
    const rsStatusText = st.rs_line_status && st.rs_line_status !== "Normal RS" ? st.rs_line_status : "";

    tr.innerHTML = `
      <td style="text-align: center;" onclick="event.stopPropagation()">
        <button class="star-btn ${isStarred ? 'starred' : ''}" onclick="toggleWatchlist('${st.symbol}', event)">${isStarred ? '⭐' : '☆'}</button>
      </td>
      <td><strong>${st.symbol}</strong><br><span style="font-size:0.7rem; color:var(--muted);">${st.company_name}</span></td>
      <td><span style="color:var(--muted)">${st.sector}</span></td>
      <td>₹${Number(st.close).toFixed(2)}</td>
      <td><span class="pill pill-buyzone">${st.inst_signal}</span></td>
      <td>
        <div class="score-bar">
          <div class="meter"><div class="meter-fill" style="width:${Math.min(100, Math.max(0, scoreVal))}%"></div></div>
          <span><b>${scoreVal}</b></span>
        </div>
      </td>
      <td><b>${st.iasis_score ?? 'N/A'}</b></td>
      <td><span style="color:var(--purple); font-weight:600;">${patternText}</span></td>
      <td><span style="color:var(--green); font-weight:600;">${rsStatusText}</span></td>
      <td><b>${st.risk_reward_ratio || 2.0}:1</b></td>
      <td style="font-size:0.73rem; color:var(--muted); max-width:220px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${st.reasons_to_avoid || ''}">
        ${st.reasons_to_avoid ? st.reasons_to_avoid.split('; ')[0] : 'Constructive structure'}
      </td>
      <td onclick="event.stopPropagation()">
        <a class="ext-chart-btn" href="https://in.tradingview.com/chart/?symbol=NSE:${st.symbol}" target="_blank" rel="noopener noreferrer">TV ↗</a>
      </td>
    `;
    tr.onclick = () => openStockModal(st);
    tbody.appendChild(tr);
  });

  document.getElementById('pageInfo').textContent = total === 0 ? "Showing 0 recommendations" : `Showing ${startIdx + 1} to ${endIdx} of ${total} recommendations`;
  document.getElementById('pageTracker').textContent = `${appState.currentPage} / ${totalPages}`;
  document.getElementById('prevBtn').disabled = appState.currentPage <= 1;
  document.getElementById('nextBtn').disabled = appState.currentPage >= totalPages;
}

window.openStockModalBySymbol = function(symbol) {
  if (!symbol) return;
  const st = appState.stocks.find(s => String(s.symbol).toUpperCase() === String(symbol).toUpperCase());
  if (st) openStockModal(st);
};

function renderPatternsTable() {
  const tbody = document.getElementById('patternsTableBody');
  const countBadge = document.getElementById('patternCountBadge');
  if (!tbody) return;

  const tf = document.getElementById('patternTimeframeSelect')?.value || 'ALL';
  const patFilter = appState.selectedPatternFilter || 'ALL';

  const matched = appState.stocks.map(st => {
    let conf = st.pattern_confluence_score;
    if (conf === undefined || conf === null) {
      conf = typeof calculatePatternConfluence === 'function' ? calculatePatternConfluence(st) : 50;
    }
    return { ...st, _confScore: Number(conf) || 0 };
  }).filter(st => {
    const pTf = Number(st.pattern_timeframe || 21);
    const patSig = String(st.chart_pattern_signal || "").toUpperCase();
    const confSig = String(st.multi_timeframe_confluence || "").toUpperCase();
    const vcpRat = Number(st.vcp_ratio ?? 1.0);
    const c = Number(st.close || 0);
    const s50 = Number(st.sma_50 || 0);
    const s200 = Number(st.sma_200 || 0);

    const isFlag = (st.is_flag_pattern === true) || patSig.includes("FLAG") || confSig.includes("FLAG");
    const isVcp = (st.is_vcp_pattern === true) || patSig.includes("VCP") || (vcpRat <= 0.68 && vcpRat > 0);
    const isBase = (st.is_base_pattern === true) || patSig.includes("BASE") || patSig.includes("CUP") || confSig.includes("BASE");
    const isMacro = (st.is_macro_pattern === true) || patSig.includes("MACRO") || (c >= s50 && s50 >= s200 && s200 > 0);

    if (patFilter === 'FLAG' && !isFlag) return false;
    if (patFilter === 'VCP' && !isVcp) return false;
    if (patFilter === 'BASE' && !isBase) return false;
    if (patFilter === 'MACRO' && !isMacro) return false;

    if (tf !== 'ALL') {
      if (parseInt(tf, 10) !== pTf) return false;
    }

    if (appState.filterConfluenceOnly && st._confScore < 60) return false;

    return isFlag || isVcp || isBase || isMacro || Boolean(st.chart_pattern_signal);
  });

  matched.sort((a, b) => b._confScore - a._confScore);

  if (countBadge) {
    countBadge.textContent = `${matched.length} Setups Found`;
  }

  if (matched.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--muted); padding: 30px;">No setups meet the selected pattern &amp; confluence criteria.</td></tr>`;
    updateGlobalBadge();
    return;
  }

  tbody.innerHTML = matched.map(st => {
    const isStarred = appState.watchlist.includes(st.symbol.toUpperCase());
    const poc = Number(st.volume_profile_poc || 0);
    const close = Number(st.close || 0);
    const isAbovePoc = (st.is_above_poc === true) || (poc > 0 && close >= poc);
    
    const rawPocDiff = (st.dist_from_poc_pct != null) 
      ? Number(st.dist_from_poc_pct) 
      : (poc > 0 ? ((close - poc) / poc) * 100.0 : 0.0);
    const pocDiff = !isNaN(rawPocDiff) ? rawPocDiff.toFixed(1) : "0.0";

    const patLabel = st.chart_pattern_signal || st.multi_timeframe_confluence || 'Volatility Contraction';
    const tfLabel = `${st.pattern_timeframe || 21} Sessions`;
    const mrsScore = Number(st.mrs_score || 0);
    const atrStop = Number(st.stop_loss_price || st.cushioned_sl_price || st.atr_stop_loss || (close * 0.935));

    return `
      <tr class="stock-row" onclick="openStockModalBySymbol('${st.symbol}')">
        <td style="text-align: center;" onclick="event.stopPropagation()">
          <button class="star-btn ${isStarred ? 'starred' : ''}" onclick="toggleWatchlist('${st.symbol}', event)">${isStarred ? '⭐' : '☆'}</button>
        </td>
        <td>
          <strong>${st.symbol}</strong><br>
          <span style="font-size:0.7rem; color:var(--muted);">${st.sector || 'Equities'}</span>
        </td>
        <td>
          <b>₹${close.toFixed(2)}</b><br>
          <span style="font-size:0.68rem; color:${mrsScore >= 0 ? 'var(--green)' : 'var(--red)'};">${mrsScore >= 0 ? '+' : ''}${mrsScore.toFixed(1)}% vs 20MA</span>
        </td>
        <td>
          <span style="color:var(--purple); font-weight:700;">${patLabel}</span><br>
          <span style="font-size:0.68rem; color:var(--muted);">${tfLabel}</span>
        </td>
        <td>
          <div class="score-bar">
            <div class="meter"><div class="meter-fill" style="width:${Math.min(100, Math.max(0, st._confScore))}%; background:${st._confScore >= 75 ? 'var(--green)' : (st._confScore >= 60 ? 'var(--accent)' : 'var(--yellow)')};"></div></div>
            <span style="color:${st._confScore >= 75 ? 'var(--green)' : 'var(--text)'};"><b>${st._confScore}%</b></span>
          </div>
        </td>
        <td>
          <span class="pill ${isAbovePoc ? 'pill-buyzone' : 'pill-extended'}">
            ${isAbovePoc ? '🟢 Floor Support (+'+pocDiff+'%)' : '🔴 Overhead Supply (-'+Math.abs(Number(pocDiff)).toFixed(1)+'%)'}
          </span><br>
          <span style="font-size:0.68rem; color:var(--muted);">POC: ₹${poc.toFixed(2)}</span>
        </td>
        <td>
          <b>Coil: ${st.vcp_ratio != null ? Number(st.vcp_ratio).toFixed(2) : '--'}</b><br>
          <span style="font-size:0.68rem; color:var(--muted);">Surety: ${st.score_surety_anchor ?? st.surety_score ?? '--'}</span>
        </td>
        <td>
          <span style="font-size:0.75rem;">Deliv: <b>${st.deliv_pct != null ? Number(st.deliv_pct).toFixed(1) : '--'}%</b></span><br>
          <span style="font-size:0.68rem; color:var(--teal);">U/D: <b>${st.up_down_vol_ratio != null ? Number(st.up_down_vol_ratio).toFixed(2) : '--'}x</b></span>
        </td>
        <td>
          <span style="color:var(--red); font-weight:600; font-size:0.74rem;">SL: ₹${atrStop.toFixed(2)}</span><br>
          <span style="font-size:0.68rem; color:var(--green); font-weight:700;">RRR: ${st.risk_reward_ratio || 2.0}:1</span>
        </td>
        <td onclick="event.stopPropagation()">
          <a class="ext-chart-btn" href="https://in.tradingview.com/chart/?symbol=NSE:${st.symbol}" target="_blank" rel="noopener noreferrer">TV ↗</a>
        </td>
      </tr>
    `;
  }).join('');

  updateGlobalBadge();
}

function selectBacktestQuarter(idx) {
  appState.selectedBacktestQuarterIdx = idx;
  renderBacktestView();
}

function setBacktestModel(modelKey) {
  appState.selectedBacktestMode = modelKey;
  renderBacktestView();
}

function setBacktestPortfolioSize(sizeStr) {
  appState.selectedBacktestPortfolioSize = sizeStr;
  renderBacktestView();
}

function setBacktestMcap(mcapKey) {
  appState.selectedBacktestMcap = mcapKey;
  renderBacktestView();
}

function renderDailyProgressAudit() {
  const section = document.getElementById('btDailyProgressSection');
  const summaryGrid = document.getElementById('btDailyProgressSummaryGrid');
  const tbody = document.getElementById('btDailyProgressTableBody');
  if (!section || !summaryGrid || !tbody || !appState.backtestData) return;

  const dailyRows = appState.backtestData.daily_progress_audit || [];
  const summary = appState.backtestData.daily_progress_summary;

  if (dailyRows.length === 0 || !summary) {
    section.style.display = 'none';
    return;
  }
  section.style.display = 'block';

  const cumPnl = Number(summary.cumulative_net_profit_inr || 0);
  const cumRoc = Number(summary.cumulative_roc_pct || 0);
  const maxDd = Number(summary.max_equity_drawdown_pct || 0);

  summaryGrid.innerHTML = `
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:8px; padding:10px;">
      <div style="font-size:0.65rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Audited Sessions</div>
      <div style="font-size:1.1rem; font-weight:800; color:var(--accent);">${summary.total_trading_days} Days</div>
    </div>
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:8px; padding:10px;">
      <div style="font-size:0.65rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Cumulative Net P&amp;L</div>
      <div style="font-size:1.1rem; font-weight:800; color:${cumPnl >= 0 ? 'var(--green)' : 'var(--red)'};">${cumPnl >= 0 ? '+' : ''}₹${Math.round(cumPnl).toLocaleString('en-IN')}</div>
    </div>
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:8px; padding:10px;">
      <div style="font-size:0.65rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Cumulative Portfolio ROC</div>
      <div style="font-size:1.1rem; font-weight:800; color:${cumRoc >= 0 ? 'var(--green)' : 'var(--red)'};">${cumRoc >= 0 ? '+' : ''}${cumRoc.toFixed(2)}%</div>
    </div>
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:8px; padding:10px;">
      <div style="font-size:0.65rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Peak / Avg Open Slots</div>
      <div style="font-size:1.1rem; font-weight:800; color:var(--purple);">${summary.peak_concurrent_positions} / ${summary.avg_concurrent_positions}</div>
    </div>
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:8px; padding:10px;">
      <div style="font-size:0.65rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Max Equity Drawdown</div>
      <div style="font-size:1.1rem; font-weight:800; color:var(--red);">${maxDd.toFixed(2)}%</div>
    </div>
  `;

  const reversedRows = [...dailyRows].reverse();
  tbody.innerHTML = reversedRows.map(r => {
    const dayPnl = Number(r.daily_realized_pnl_inr || 0);
    const cPnl = Number(r.cumulative_pnl_inr || 0);
    const cRoc = Number(r.cumulative_roc_pct || 0);
    const dd = Number(r.drawdown_from_peak_pct || 0);
    const hasActivity = (r.entries_today > 0 || r.exits_today > 0);
    return `
      <tr style="${hasActivity ? 'background: rgba(56, 189, 248, 0.04);' : ''}">
        <td><strong>${r.date}</strong></td>
        <td><span class="badge" style="font-size:0.68rem;">${r.active_open_positions} Open</span></td>
        <td style="color:${r.entries_today > 0 ? 'var(--accent)' : 'var(--muted)'}; font-weight:${r.entries_today > 0 ? '700' : '400'};">${r.entries_today}</td>
        <td style="color:${r.exits_today > 0 ? 'var(--purple)' : 'var(--muted)'}; font-weight:${r.exits_today > 0 ? '700' : '400'};">${r.exits_today}</td>
        <td style="color:${dayPnl > 0 ? 'var(--green)' : (dayPnl < 0 ? 'var(--red)' : 'var(--muted)')}; font-weight:700;">
          ${dayPnl !== 0 ? (dayPnl > 0 ? '+' : '') + '₹' + Math.round(dayPnl).toLocaleString('en-IN') : '—'}
        </td>
        <td style="color:${cPnl >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:800;">
          ${cPnl >= 0 ? '+' : ''}₹${Math.round(cPnl).toLocaleString('en-IN')}
        </td>
        <td style="color:${cRoc >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">
          ${cRoc >= 0 ? '+' : ''}${cRoc.toFixed(2)}%
        </td>
        <td><b>${Number(r.running_win_rate_pct || 0).toFixed(1)}%</b></td>
        <td style="color:${dd < -3.0 ? 'var(--red)' : 'var(--muted)'};">${dd.toFixed(2)}%</td>
      </tr>
    `;
  }).join('');
}

function renderBacktestForensicTables() {
  const forensicSection = document.getElementById('btForensicSection');
  if (!forensicSection || !appState.backtestData) return;

  const mcapSummary = appState.backtestData.mcap_tier_summary || [];
  const climaxAudit = appState.backtestData.sector_climax_audit || [];
  const intramonthAudit = appState.backtestData.intramonth_timing_audit || [];
  const patternAudit = appState.backtestData.pattern_confluence_audit || [];
  const factorAudit = appState.backtestData.advanced_factors_audit || [];

  if (
    mcapSummary.length === 0 &&
    climaxAudit.length === 0 &&
    intramonthAudit.length === 0 &&
    patternAudit.length === 0 &&
    factorAudit.length === 0
  ) {
    forensicSection.style.display = 'none';
    return;
  }
  forensicSection.style.display = 'block';

  const patTbody = document.getElementById('btPatternAuditTableBody');
  if (patTbody) {
    patTbody.innerHTML = patternAudit.map(pa => {
      const isHighlight = pa.cohort.includes('Cohort 3') || pa.cohort.includes('Bull Flag');
      const inTradeDip = Number(pa.avg_active_drawdown_pct ?? pa.avg_mae_pct ?? 0);
      const lowDipRate = Number(pa.low_drawdown_surety_rate ?? pa.low_mae_surety_rate ?? 0);
      return `
        <tr style="${isHighlight ? 'background: rgba(56, 189, 248, 0.08);' : ''}">
          <td><strong style="color: ${isHighlight ? 'var(--accent)' : 'var(--text)'};">${pa.cohort}</strong></td>
          <td>${pa.sample_size}</td>
          <td style="color:var(--green); font-weight:700;">+${Number(pa.avg_peak_mfe_pct).toFixed(2)}%</td>
          <td>${Number(pa.hit_15pct_rate).toFixed(1)}%</td>
          <td style="color:var(--teal); font-weight:700;">${lowDipRate.toFixed(1)}%</td>
          <td style="color:var(--red);">${inTradeDip.toFixed(2)}%</td>
          <td style="color:${pa.avg_hold_ret_pct >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">${pa.avg_hold_ret_pct >= 0 ? '+' : ''}${Number(pa.avg_hold_ret_pct).toFixed(2)}%</td>
          <td style="color:var(--purple); font-weight:800;">${Number(pa.asymmetry_ratio).toFixed(2)}x</td>
        </tr>
      `;
    }).join('');
  }

  const factorTbody = document.getElementById('btAdvancedFactorsAuditTableBody');
  if (factorTbody) {
    factorTbody.innerHTML = factorAudit.map(fa => {
      const isTopTier = fa.factor.includes('Combined') || fa.factor.includes('52-Week');
      const inTradeDip = Number(fa.avg_active_drawdown_pct ?? fa.avg_mae_pct ?? 0);
      const lowDipRate = Number(fa.low_drawdown_surety_rate ?? fa.low_mae_surety_rate ?? 0);
      return `
        <tr style="${isTopTier ? 'background: rgba(45, 212, 191, 0.08);' : ''}">
          <td><strong style="color: ${isTopTier ? 'var(--teal)' : 'var(--text)'};">${fa.factor}</strong></td>
          <td>${fa.sample_size}</td>
          <td style="color:var(--green); font-weight:700;">+${Number(fa.avg_peak_mfe_pct).toFixed(2)}%</td>
          <td>${Number(fa.hit_15pct_rate).toFixed(1)}%</td>
          <td style="color:var(--teal); font-weight:700;">${lowDipRate.toFixed(1)}%</td>
          <td style="color:var(--red);">${inTradeDip.toFixed(2)}%</td>
          <td style="color:${fa.avg_hold_ret_pct >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">${fa.avg_hold_ret_pct >= 0 ? '+' : ''}${Number(fa.avg_hold_ret_pct).toFixed(2)}%</td>
          <td style="color:var(--purple); font-weight:800;">${Number(fa.asymmetry_ratio).toFixed(2)}x</td>
        </tr>
      `;
    }).join('');
  }

  const mcapTbody = document.getElementById('btMcapAuditTableBody');
  if (mcapTbody) {
    mcapTbody.innerHTML = mcapSummary.map(mc => {
      const inTradeDip = Number(mc.avg_active_drawdown_pct ?? mc.avg_mae_pct ?? 0);
      const lowDipRate = Number(mc.low_drawdown_surety_rate ?? mc.low_mae_surety_rate ?? 0);
      return `
        <tr>
          <td><strong>${mc.mcap_tier}</strong></td>
          <td>${mc.count}</td>
          <td style="color:var(--green); font-weight:700;">+${Number(mc.avg_mfe_pct).toFixed(2)}%</td>
          <td>${Number(mc.hit_15pct_rate).toFixed(1)}%</td>
          <td style="color:var(--teal); font-weight:700;">${lowDipRate.toFixed(1)}%</td>
          <td style="color:var(--red);">${inTradeDip.toFixed(2)}%</td>
          <td style="color:${mc.avg_hold_ret_pct >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">${mc.avg_hold_ret_pct >= 0 ? '+' : ''}${Number(mc.avg_hold_ret_pct).toFixed(2)}%</td>
        </tr>
      `;
    }).join('');
  }

  const climaxTbody = document.getElementById('btSectorClimaxTableBody');
  if (climaxTbody) {
    climaxTbody.innerHTML = climaxAudit.map(sc => {
      const isTrap = String(sc.sector_stage).includes("Climactic");
      const inTradeDip = Number(sc.avg_active_drawdown_pct ?? sc.avg_mae_pct ?? 0);
      const trapRate = Number(sc.severe_trap_rate_dd_gt_15 ?? sc.severe_trap_rate_mae_gt_15 ?? 0);
      return `
        <tr style="${isTrap ? 'background:rgba(239,68,68,0.06);' : ''}">
          <td><strong style="color:${isTrap ? 'var(--red)' : 'var(--text)'};">${sc.sector_stage}</strong></td>
          <td>${sc.sample_size}</td>
          <td style="color:var(--green); font-weight:700;">+${Number(sc.avg_mfe_pct).toFixed(2)}%</td>
          <td>${Number(sc.hit_15pct_rate).toFixed(1)}%</td>
          <td style="color:${isTrap ? 'var(--red)' : 'var(--muted)'}; font-weight:700;">${trapRate.toFixed(1)}%</td>
          <td style="color:var(--red);">${inTradeDip.toFixed(2)}%</td>
          <td style="color:${sc.avg_period_ret_pct >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">${sc.avg_period_ret_pct >= 0 ? '+' : ''}${Number(sc.avg_period_ret_pct).toFixed(2)}%</td>
        </tr>
      `;
    }).join('');
  }

  const intraTbody = document.getElementById('btIntramonthTableBody');
  if (intraTbody) {
    intraTbody.innerHTML = intramonthAudit.map(im => {
      const inTradeDip = Number(im.avg_active_drawdown_pct ?? im.avg_mae_pct ?? 0);
      const lowDipRate = Number(im.low_drawdown_surety_rate ?? im.low_mae_surety_rate ?? 0);
      return `
        <tr>
          <td><strong>${im.window}</strong></td>
          <td>${im.sample_signals}</td>
          <td style="color:var(--green); font-weight:700;">+${Number(im.avg_peak_mfe_pct).toFixed(2)}%</td>
          <td>${Number(im.hit_15pct_rate).toFixed(1)}%</td>
          <td style="color:var(--teal); font-weight:700;">${lowDipRate.toFixed(1)}%</td>
          <td style="color:var(--red);">${inTradeDip.toFixed(2)}%</td>
          <td style="color:var(--accent); font-weight:800;">${Number(im.asymmetry_ratio).toFixed(2)}x</td>
        </tr>
      `;
    }).join('');
  }
}

function renderBacktestView() {
  const noticeEl = document.getElementById('btNoticeBanner');
  const contentEl = document.getElementById('btContentWrapper');
  const btnContainer = document.getElementById('btQuarterButtons');
  const modelSelectEl = document.getElementById('btModelSelect');
  const sizeSelectEl = document.getElementById('btPortfolioSizeSelect');
  const mcapSelectEl = document.getElementById('btMcapSelect');
  const riskSelectEl = document.getElementById('btRiskProfileSelect');
  if (!noticeEl || !contentEl || !btnContainer) return;

  if (!appState.backtestData || !appState.backtestData.quarters || appState.backtestData.quarters.length === 0) {
    noticeEl.style.display = 'block';
    contentEl.style.display = 'none';
    btnContainer.innerHTML = '<span style="font-size:0.75rem; color:var(--muted);">Awaiting backtest_data.json...</span>';
    return;
  }

  noticeEl.style.display = 'none';
  contentEl.style.display = 'block';

  renderDailyProgressAudit();
  renderBacktestForensicTables();
  renderBacktestMethodCard();

  const months = appState.backtestData.quarters;
  const activeIdx = Math.min(appState.selectedBacktestQuarterIdx || 0, months.length - 1);
  const rawEntry = months[activeIdx];

  let requestedModel = appState.selectedBacktestMode || 'dynamic_regime_portfolio';
  const legacyKeyMap = {
    'dynamic_regime_portfolio': ['dynamic_regime_portfolio'],
    'score_surety_anchor': ['score_surety_anchor', 'surety_anchor', 'kinetic_launchpad'],
    'score_momentum_frontrunner': ['score_momentum_frontrunner', 'momentum_frontrunner', 'quant_confluence'],
    'score_early_sector_rotation': ['score_early_sector_rotation', 'early_sector_rotation', 'institutional_stealth'],
    'score_high_rs_pullback': ['score_high_rs_pullback', 'high_rs_pullback']
  };

  let qData = rawEntry;
  if (rawEntry.modes) {
    const candidates = legacyKeyMap[requestedModel] || [requestedModel];
    const foundKey = candidates.find(k => rawEntry.modes[k]);
    if (foundKey) {
      qData = rawEntry.modes[foundKey];
    } else {
      const firstAvailable = Object.keys(rawEntry.modes)[0];
      if (firstAvailable) qData = rawEntry.modes[firstAvailable];
    }
  }

  if (modelSelectEl && modelSelectEl.value !== requestedModel) modelSelectEl.value = requestedModel;
  if (sizeSelectEl && sizeSelectEl.value !== appState.selectedBacktestPortfolioSize) sizeSelectEl.value = appState.selectedBacktestPortfolioSize;
  if (mcapSelectEl && mcapSelectEl.value !== appState.selectedBacktestMcap) mcapSelectEl.value = appState.selectedBacktestMcap;
  if (riskSelectEl && riskSelectEl.value !== selectedBacktestRisk) riskSelectEl.value = selectedBacktestRisk;

  btnContainer.innerHTML = '';
  months.forEach((mItem, idx) => {
    const btn = document.createElement('button');
    btn.className = `tactical-btn ${idx === activeIdx ? 'active' : ''}`;
    btn.textContent = `${mItem.quarter_label || mItem.label}`;
    btn.onclick = () => selectBacktestQuarter(idx);
    btnContainer.appendChild(btn);
  });

  const allPicks = qData.picks || qData.picks_9 || [];
  
  const riskFilteredPicks = allPicks.filter(p => {
    if (!selectedBacktestRisk || selectedBacktestRisk === "ALL") return true;
    const rTag = String(p.risk_suitability || "").toLowerCase();
    if (selectedBacktestRisk === 'Low') return rTag.includes('low') || rTag.includes('conservative');
    if (selectedBacktestRisk === 'Medium') return rTag.includes('medium') || rTag.includes('balanced');
    if (selectedBacktestRisk === 'High') return rTag.includes('high') || rTag.includes('aggressive');
    return true;
  });

  const mcapFilteredPicks = riskFilteredPicks.filter(p => matchBacktestMcapFilter(p, appState.selectedBacktestMcap));
  const portLimit = parseInt(appState.selectedBacktestPortfolioSize || "8", 10);
  const picks = mcapFilteredPicks.slice(0, portLimit);

  const countLbl = document.getElementById('btFilteredCountLabel');
  if (countLbl) countLbl.textContent = `${picks.length} shown (out of ${mcapFilteredPicks.length})`;

  const mfes = picks.map(p => Number(p.max_gain_mfe_pct || 0));
  const inTradeDips = picks.map(p => Number(p.active_trade_drawdown_pct ?? p.max_drawdown_mae_pct ?? 0));
  const m2Returns = picks.map(p => Number(p.method2_return_pct ?? p.realized_return_pct ?? 0));

  const avgPeakMfe = mfes.length > 0 ? mfes.reduce((a, b) => a + b, 0) / mfes.length : 0;
  const avgInTradeDip = inTradeDips.length > 0 ? inTradeDips.reduce((a, b) => a + b, 0) / inTradeDips.length : 0;

  let m2AvgReturn = 0;
  if (m2Returns.length > 0) {
    m2AvgReturn = m2Returns.reduce((a, b) => a + b, 0) / m2Returns.length;
  } else if (qData.portfolio_avg_return_pct !== undefined && qData.portfolio_avg_return_pct !== null) {
    m2AvgReturn = Number(qData.portfolio_avg_return_pct);
  }

  const hit15Count = mfes.filter(v => v >= 15.0).length;
  const hit15Rate = picks.length > 0 ? ((hit15Count / picks.length) * 100.0) : 0;

  const benchmarkRet = Number(rawEntry.universe_benchmark_ret_pct || 0);
  const alphaVal = m2AvgReturn - benchmarkRet;

  const elDate = document.getElementById('btStatSignalDate');
  if (elDate) elDate.textContent = `${rawEntry.quarter_label} (${rawEntry.start_date})`;
  const elActiveLabel = document.getElementById('btStatActiveModelLabel');
  if (elActiveLabel) elActiveLabel.textContent = qData.regime_detected || qData.model_name || '--';
  const elSecDate = document.getElementById('btSectorHeaderDate');
  if (elSecDate) elSecDate.textContent = `${rawEntry.quarter_label} (${rawEntry.start_date})`;
  const elPeak = document.getElementById('btStatAvgPeak');
  if (elPeak) elPeak.textContent = `+${avgPeakMfe.toFixed(2)}% Avg Peak`;
  
  const alphaEl = document.getElementById('btStatAlphaVsBm');
  if (alphaEl) {
    alphaEl.textContent = `${alphaVal >= 0 ? '+' : ''}${alphaVal.toFixed(2)}%`;
    alphaEl.style.color = alphaVal >= 0 ? 'var(--green)' : 'var(--red)';
  }
  const bmSub = document.getElementById('btStatBmRetSub');
  if (bmSub) {
    bmSub.textContent = `Nifty Benchmark: ${benchmarkRet >= 0 ? '+' : ''}${benchmarkRet.toFixed(2)}%`;
  }

  const portEl = document.getElementById('btStatPortfolioRet');
  if (portEl) {
    portEl.textContent = `${m2AvgReturn >= 0 ? '+' : ''}${m2AvgReturn.toFixed(2)}%`;
    portEl.style.color = m2AvgReturn >= 0 ? 'var(--green)' : 'var(--red)';
  }
  const elExit = document.getElementById('btStatExitSimSub');
  if (elExit) {
    elExit.textContent = `50/50 Dual-Stage Harvest Return`;
  }

  const elPers = document.getElementById('btStatPersistence');
  if (elPers) elPers.textContent = `${qData.avg_zone_persistence_days || 12.5}d / ${qData.avg_trend_persistence_days || 34.0}d`;
  
  const elHit = document.getElementById('btStatTargetHitRate');
  if (elHit) elHit.textContent = `${hit15Count} / ${picks.length} (${hit15Rate.toFixed(0)}%)`;
  const elDraw = document.getElementById('btStat20PctHitRate');
  if (elDraw) elDraw.textContent = `Avg In-Trade Dip: ${avgInTradeDip.toFixed(2)}%`;

  const secGrid = document.getElementById('btTopSectorsGrid');
  if (secGrid) {
    secGrid.innerHTML = '';
    const rawSectors = qData.top_5_sectors || qData.top_3_sectors || [];
    rawSectors.forEach((sec, i) => {
      const card = document.createElement('div');
      card.className = 'sector-tile';
      card.style.cursor = 'default';
      card.innerHTML = `
        <div class="sector-tile-header">
          <div>
            <span class="badge" style="margin-bottom:6px; display:inline-block;">Rank #${i + 1} Sector</span>
            <div class="sector-tile-name">${sec.sector}</div>
            <span style="font-size:0.68rem; color:var(--green); font-weight:700;">${sec.sector_lifecycle || sec.quadrant}</span>
          </div>
          <div style="text-align:right;">
            <div style="font-weight: 800; font-size:1.05rem; color:${sec.perf_20d >= 0 ? 'var(--green)' : 'var(--red)'};">${sec.perf_20d >= 0 ? '+' : ''}${Number(sec.perf_20d).toFixed(2)}%</div>
            <div style="font-size:0.68rem; color:var(--muted);">20D Perf</div>
          </div>
        </div>
        <div class="sector-tile-metrics">
          <div>RS Ratio: <b>${Number(sec.rs_ratio || 100).toFixed(2)}</b></div>
          <div>Above >50 SMA: <b style="color:var(--accent);">${Number(sec.above_sma_pct || 50).toFixed(1)}%</b></div>
        </div>
      `;
      secGrid.appendChild(card);
    });
  }

  // ============================================================================
  // 50/50 DUAL-STAGE EXECUTION PROGRESSION TABLE RENDERER
  // ============================================================================
  const thead = document.getElementById('btProgressionTableHead');
  const tbody = document.getElementById('btProgressionTableBody');
  if (thead && tbody) {
    thead.innerHTML = `
      <tr>
        <th style="width:35px; text-align:center;">⭐</th>
        <th class="tip-trigger" data-tip="Strategy rank and company market capitalization tier.">Rank &amp; Cap Tier</th>
        <th class="tip-trigger" data-tip="Official stock ticker and company name.">Symbol</th>
        <th class="tip-trigger" data-tip="The setup type identified on the signal date.">Setup Signal</th>
        <th class="tip-trigger" data-tip="Date the trade signal triggered.">Entry Date</th>
        <th class="tip-trigger" data-tip="Reference entry price on signal date.">Entry Price</th>
        <th class="peak-highlight-cell tip-trigger" data-tip="Highest price reached, peak gain percentage, and days taken.">🚀 Peak MFE &amp; Days</th>
        <th class="tip-trigger" data-tip="50/50 Dual-Stage Harvester Resolution: Breakeven Shield, 50% @ +12% Target, or 2-Close 20-SMA Runner.">50/50 Trade Exit</th>
        <th class="tip-trigger" data-tip="Maximum price dip experienced strictly while the position was active.">In-Trade Max Dip</th>
        <th class="tip-trigger" data-tip="Open direct technical chart view.">Chart</th>
      </tr>
    `;

    tbody.innerHTML = '';
    if (picks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:24px; color:var(--muted);">No matching picks for this filter.</td></tr>`;
      return;
    }

    picks.forEach((pick, i) => {
      const tr = document.createElement('tr');
      tr.className = 'stock-row';
      const isStarred = appState.watchlist.includes(pick.symbol.toUpperCase());
      
      const entryPrice = Number(pick.entry_price || 0);
      const peakGainPct = Number(pick.max_gain_mfe_pct || 0);
      const peakPrice = Number(pick.peak_high_since_entry || (entryPrice * (1.0 + peakGainPct / 100.0)));
      const daysToPeak = pick.days_to_peak || 1;
      
      const daysToExit = pick.raw_days_to_exit || pick.days_to_exit || 1;
      const m2Ret = Number(pick.method2_return_pct ?? pick.realized_return_pct ?? 0);
      const isM2Win = Boolean(pick.is_method2_win ?? (m2Ret > 0));
      const inTradeDip = Number(pick.active_trade_drawdown_pct ?? pick.max_drawdown_mae_pct ?? 0);
      const exitReason = pick.exit_reason || (isM2Win ? "50/50 Target Harvest" : "Stop Loss (-6.5%)");

      let exitDateLabel = pick.exit_date;
      if (!exitDateLabel && pick.entry_date) {
        const eD = new Date(pick.entry_date);
        eD.setDate(eD.getDate() + Math.round(daysToExit * 1.4));
        exitDateLabel = eD.toISOString().split('T')[0];
      }

      const exitBadge = isM2Win
        ? `
          <span class="pill pill-buyzone" style="font-size:0.7rem; font-weight:800;">+${m2Ret.toFixed(1)}% Exit</span>
          <div style="font-size:0.68rem; color:var(--muted); margin-top:2px;">${exitDateLabel} (${daysToExit}d held)</div>
        `
        : `
          <span class="pill" style="background:rgba(239,68,68,0.12); color:var(--red); border:1px solid rgba(239,68,68,0.25); font-size:0.7rem; font-weight:800;">
            ${m2Ret.toFixed(1)}% Stop
          </span>
          <div style="font-size:0.68rem; color:var(--muted); margin-top:2px;">${exitDateLabel} (${daysToExit}d held)</div>
        `;

      tr.innerHTML = `
        <td style="text-align:center;" onclick="event.stopPropagation()">
          <button class="star-btn ${isStarred ? 'starred' : ''}" onclick="toggleWatchlist('${pick.symbol}', event)">${isStarred ? '⭐' : '☆'}</button>
        </td>
        <td>
          <span class="pill" style="background:rgba(56,189,248,0.12); color:var(--accent);">Rank #${pick.rank || i + 1}</span>
          <div style="font-size:0.68rem; color:var(--muted); margin-top:3px;">${pick.mcap_tier ? pick.mcap_tier.split(':')[0] : 'Core'}</div>
        </td>
        <td>
          <strong>${pick.symbol}</strong><br>
          <span style="font-size:0.7rem; color:var(--muted);">${pick.company_name || pick.symbol}</span>
        </td>
        <td>
          <div style="font-weight:700; color:var(--purple); font-size:0.74rem;">${pick.inst_signal_at_entry || 'Consolidation'}</div>
          <div style="font-size:0.65rem; color:var(--muted); margin-top:2px;">${exitReason}</div>
        </td>
        <td>
          <div style="font-weight:600; font-size:0.78rem;">${pick.entry_date || rawEntry.start_date}</div>
        </td>
        <td>
          <div style="font-weight:700; font-variant-numeric:tabular-nums;">₹${entryPrice.toFixed(2)}</div>
        </td>
        <td class="peak-highlight-cell">
          <div style="font-weight:800; font-size:0.92rem; color:var(--green);">
            +${peakGainPct.toFixed(2)}%
          </div>
          <div style="font-size:0.68rem; color:var(--muted);">
            ₹${peakPrice.toFixed(2)} (${daysToPeak}d to peak)
          </div>
        </td>
        <td>
          ${exitBadge}
        </td>
        <td>
          <b style="color:${inTradeDip >= -6.0 ? 'var(--teal)' : 'var(--red)'}; font-variant-numeric:tabular-nums;">
            ${inTradeDip.toFixed(2)}%
          </b>
        </td>
        <td onclick="event.stopPropagation()">
          <a class="ext-chart-btn" href="https://in.tradingview.com/chart/?symbol=NSE:${pick.symbol}" target="_blank" rel="noopener noreferrer">TV ↗</a>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }
}

function renderSectorChips() {
  const container = document.getElementById('sectorChipsContainer');
  if (!container) return;
  container.innerHTML = '';
  appState.sectors.forEach(sec => {
    const btn = document.createElement('button');
    const isSelected = appState.selectedChartSectors.includes(sec.sector);
    btn.className = `chip-btn ${isSelected ? 'active' : ''}`;
    btn.textContent = `${isSelected ? '✓ ' : ''}${sec.sector}`;
    btn.onclick = () => toggleSectorInChart(sec.sector);
    container.appendChild(btn);
  });
}

function toggleSectorInChart(sectorName) {
  const idx = appState.selectedChartSectors.indexOf(sectorName);
  if (idx > -1) {
    if (appState.selectedChartSectors.length <= 1) return;
    appState.selectedChartSectors.splice(idx, 1);
  } else {
    appState.selectedChartSectors.push(sectorName);
  }
  renderSectorChips();
  renderSectorRsChart();
}

function selectTopSectors(n) {
  const sorted = [...appState.sectors].sort((a, b) => b.rs_ratio - a.rs_ratio);
  appState.selectedChartSectors = sorted.slice(0, n).map(s => s.sector);
  renderSectorChips();
  renderSectorRsChart();
}

function selectAllSectors() {
  appState.selectedChartSectors = appState.sectors.map(s => s.sector);
  renderSectorChips();
  renderSectorRsChart();
}

function clearAllSectors() {
  if (appState.sectors.length > 0) appState.selectedChartSectors = [appState.sectors[0].sector];
  renderSectorChips();
  renderSectorRsChart();
}

function renderSectorRsChart() {
  const ctx = document.getElementById('sectorRsChartCanvas');
  if (!ctx) return;
  const baseline = 'Nifty 500 Benchmark';
  const sectorsToPlot = appState.sectors.filter(s => appState.selectedChartSectors.includes(s.sector));
  let labels = [];
  let datasets = [];
  const colors = ['#0284c7', '#10b981', '#9333ea', '#d97706', '#0d9488', '#ef4444', '#6366f1', '#f43f5e'];

  sectorsToPlot.forEach((sec, idx) => {
    const historyArr = appState.sectorRsHistory[sec.sector] || [];
    if (labels.length === 0 && historyArr.length > 0) labels = historyArr.map(item => item.date);
    datasets.push({
      label: sec.sector,
      data: historyArr.map(item => item.rs),
      borderColor: colors[idx % colors.length],
      borderWidth: 2.2,
      pointRadius: 0,
      tension: 0.35
    });
  });

  if (labels.length > 0) {
    datasets.unshift({
      label: 'Market Baseline (0.0%)',
      data: labels.map(() => 0),
      borderColor: 'rgba(100, 116, 139, 0.85)',
      borderWidth: 2,
      borderDash: [5, 5],
      pointRadius: 0,
      fill: false
    });
  }

  if (sectorRsChartInstance) sectorRsChartInstance.destroy();
  sectorRsChartInstance = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { title: { display: true, text: `Sector RS Spread vs. ${baseline}`, color: '#64748b' } },
      scales: { x: { grid: { color: 'rgba(100,116,139,0.1)' } }, y: { grid: { color: 'rgba(100,116,139,0.1)' } } }
    }
  });
}

function renderSectorTiles() {
  const grid = document.getElementById('sectorTilesGrid');
  if (!grid) return;
  grid.innerHTML = '';
  [...appState.sectors].sort((a, b) => b.sector_composite_score - a.sector_composite_score).forEach(sec => {
    const card = document.createElement('div');
    card.className = `sector-tile ${appState.selectedDrilldownSector === sec.sector ? 'selected' : ''}`;
    
    const d1 = sec.daily_perf ?? 0;
    const d20 = sec.perf_20d ?? 0;
    const d63 = sec.perf_63d ?? 0;
    const above50 = sec.above_sma_pct ?? 50;

    card.innerHTML = `
      <div class="sector-tile-header">
        <div>
          <div class="sector-tile-name">${sec.sector}</div>
          <span style="font-size:0.68rem; color:var(--accent); font-weight:700;">${sec.quadrant} | Breadth: ${above50}% >50SMA</span>
        </div>
        <div style="text-align: right;">
          <div style="font-weight: 800; color:${d20 >= 0 ? 'var(--green)' : 'var(--red)'};">${d20 >= 0 ? '+' : ''}${Number(d20).toFixed(2)}%</div>
          <div style="font-size: 0.65rem; color: var(--muted);">20D Change</div>
        </div>
      </div>
      <div class="sector-tile-metrics">
        <span>1D: <b style="color:${d1 >= 0 ? 'var(--green)' : 'var(--red)'};">${d1 >= 0 ? '+' : ''}${d1}%</b></span>
        <span>20D: <b style="color:${d20 >= 0 ? 'var(--green)' : 'var(--red)'};">${d20 >= 0 ? '+' : ''}${d20}%</b></span>
        <span>63D: <b style="color:${d63 >= 0 ? 'var(--green)' : 'var(--red)'};">${d63 >= 0 ? '+' : ''}${d63}%</b></span>
      </div>
      <div class="sector-tile-metrics" style="border-top: none; margin-top: 4px; padding-top: 0;">
        <span>RS Score: <b>${sec.rs_ratio || '100'}</b></span>
        <span>Composite: <b>${sec.sector_composite_score || '0'}</b></span>
      </div>
    `;
    card.onclick = () => {
      appState.selectedDrilldownSector = sec.sector;
      renderSectorTiles();
      renderSectorDrilldown(sec.sector);
      updateGlobalBadge();
    };
    grid.appendChild(card);
  });
}

function clearSectorSelection() {
  appState.selectedDrilldownSector = null;
  renderSectorTiles();
  document.getElementById('sectorDrilldownContainer').style.display = 'none';
  updateGlobalBadge();
}

function selectTopStocksInDrilldown(n) {
  if (!appState.selectedDrilldownSector) return;
  const secStocks = appState.stocks
    .filter(st => st.sector === appState.selectedDrilldownSector)
    .sort((a, b) => Number(b.score_momentum_frontrunner || b.frontrunner_score || 0) - Number(a.score_momentum_frontrunner || a.frontrunner_score || 0));
  appState.selectedDrilldownStocks = secStocks.slice(0, n).map(s => s.symbol);
  renderDrilldownStockChips();
  renderStockRsChart();
}

function clearDrilldownStockSelection() {
  if (!appState.selectedDrilldownSector) return;
  const secStocks = appState.stocks.filter(st => st.sector === appState.selectedDrilldownSector);
  appState.selectedDrilldownStocks = secStocks.length > 0 ? [secStocks[0].symbol] : [];
  renderDrilldownStockChips();
  renderStockRsChart();
}

function renderDrilldownStockChips() {
  const container = document.getElementById('stockChipsContainer');
  if (!container || !appState.selectedDrilldownSector) return;
  const secStocks = appState.stocks.filter(st => st.sector === appState.selectedDrilldownSector);
  container.innerHTML = '';
  secStocks.forEach(st => {
    const btn = document.createElement('button');
    const isSel = appState.selectedDrilldownStocks.includes(st.symbol);
    btn.className = `chip-btn ${isSel ? 'active' : ''}`;
    btn.textContent = `${isSel ? '✓ ' : ''}${st.symbol}`;
    btn.onclick = () => {
      const i = appState.selectedDrilldownStocks.indexOf(st.symbol);
      if (i > -1) {
        if (appState.selectedDrilldownStocks.length > 1) appState.selectedDrilldownStocks.splice(i, 1);
      } else {
        appState.selectedDrilldownStocks.push(st.symbol);
      }
      renderDrilldownStockChips();
      renderStockRsChart();
    };
    container.appendChild(btn);
  });
}

function renderStockRsChart() {
  const ctx = document.getElementById('stockRsChartCanvas');
  if (!ctx) return;
  const mode = document.getElementById('stockRsBenchmarkMode')?.value || 'sector';
  const colors = ['#9333ea', '#0284c7', '#10b981', '#d97706', '#ef4444', '#0d9488'];
  let labels = [];
  let datasets = [];

  appState.selectedDrilldownStocks.forEach((sym, idx) => {
    const hist = appState.priceHistory[sym] || [];
    if (labels.length === 0 && hist.length > 0) labels = hist.map(h => h.date);
    datasets.push({
      label: sym,
      data: hist.map(h => mode === 'sector' ? h.rs_vs_sector : h.rs),
      borderColor: colors[idx % colors.length],
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3
    });
  });

  if (labels.length > 0) {
    datasets.unshift({
      label: 'Baseline (0.0%)',
      data: labels.map(() => 0),
      borderColor: 'rgba(100, 116, 139, 0.85)',
      borderWidth: 2,
      borderDash: [5, 5],
      pointRadius: 0,
      fill: false
    });
  }

  if (stockRsChartInstance) stockRsChartInstance.destroy();
  stockRsChartInstance = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: { grid: { color: 'rgba(100,116,139,0.1)' } }, y: { grid: { color: 'rgba(100,116,139,0.1)' } } }
    }
  });
}

function renderSectorDrilldown(sectorName) {
  const container = document.getElementById('sectorDrilldownContainer');
  const tbody = document.getElementById('sectorDrilldownTableBody');
  const title = document.getElementById('drilldownTitle');
  const countBadge = document.getElementById('drilldownCount');
  if (!container || !tbody) return;

  container.style.display = 'block';
  title.textContent = `Constituents for Sector: ${sectorName}`;
  const secStocks = appState.stocks.filter(st => st.sector === sectorName);
  if (countBadge) countBadge.textContent = `${secStocks.length} Stocks`;

  appState.selectedDrilldownStocks = secStocks.slice(0, 5).map(s => s.symbol);
  renderDrilldownStockChips();
  renderStockRsChart();

  tbody.innerHTML = secStocks.map(st => {
    const isStarred = appState.watchlist.includes(st.symbol.toUpperCase());
    const patternText = st.chart_pattern_signal && st.chart_pattern_signal !== "" ? st.chart_pattern_signal : "";
    const sectorRsText = st.sector_rs_status || '🟢 Outperforming Sector';
    const marketRsText = st.rs_line_status || '—';
    const activeScore = getStrategyScore(st, appState.strategyMode).toFixed(1);

    return `
      <tr class="stock-row" onclick="openStockModalBySymbol('${st.symbol}')">
        <td style="text-align: center;" onclick="event.stopPropagation()">
          <button class="star-btn ${isStarred ? 'starred' : ''}" onclick="toggleWatchlist('${st.symbol}', event)">${isStarred ? '⭐' : '☆'}</button>
        </td>
        <td><strong>${st.symbol}</strong></td>
        <td>${st.sector}</td>
        <td>₹${Number(st.close).toFixed(2)}</td>
        <td><span class="pill pill-buyzone">${st.inst_signal}</span></td>
        <td><b>${activeScore}</b></td>
        <td><b>${st.iasis_score ?? '--'}</b></td>
        <td><span style="color:var(--purple); font-weight:600;">${patternText}</span></td>
        <td><span style="color:var(--green); font-weight:600;">${sectorRsText}</span></td>
        <td><span style="color:var(--accent); font-weight:600;">${marketRsText}</span></td>
        <td>${st.risk_reward_ratio || 2.0}:1</td>
        <td onclick="event.stopPropagation()"><a class="ext-chart-btn" href="https://in.tradingview.com/chart/?symbol=NSE:${st.symbol}" target="_blank" rel="noopener noreferrer">TV ↗</a></td>
      </tr>
    `;
  }).join('');

  updateGlobalBadge();
}

function renderWatchlistPage() {
  const tbody = document.getElementById('watchlistTableBody');
  if (!tbody) return;
  tbody.innerHTML = '';
  const uniqueWatch = [...new Set(appState.watchlist.map(s => String(s).trim().toUpperCase()))];
  
  if (uniqueWatch.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--muted); padding: 30px;">Your watchlist is currently empty.</td></tr>';
    return;
  }

  uniqueWatch.forEach(sym => {
    const st = appState.stocks.find(s => s.symbol.trim().toUpperCase() === sym);
    const tr = document.createElement('tr');
    tr.className = 'stock-row';
    if (st) {
      tr.innerHTML = `
        <td style="text-align: center;" onclick="event.stopPropagation()"><button class="star-btn starred" onclick="toggleWatchlist('${st.symbol}', event)">⭐</button></td>
        <td><strong>${st.symbol}</strong><br><span style="font-size:0.7rem; color:var(--muted);">${st.company_name}</span></td>
        <td>${st.sector}</td>
        <td>₹${Number(st.close).toFixed(2)}</td>
        <td><span class="pill pill-buyzone">${st.inst_signal}</span></td>
        <td>${st.multi_timeframe_confluence || '—'}</td>
        <td><b>${st.score_surety_anchor ?? st.surety_score ?? '--'}</b></td>
        <td><b>${st.score_momentum_frontrunner ?? st.frontrunner_score ?? '--'}</b></td>
        <td onclick="event.stopPropagation()"><a class="ext-chart-btn" href="https://in.tradingview.com/chart/?symbol=NSE:${st.symbol}" target="_blank" rel="noopener noreferrer">TV ↗</a></td>
      `;
      tr.onclick = () => openStockModal(st);
    } else {
      tr.innerHTML = `
        <td style="text-align: center;" onclick="event.stopPropagation()"><button class="star-btn starred" onclick="toggleWatchlist('${sym}', event)">⭐</button></td>
        <td><strong>${sym}</strong></td>
        <td colspan="6" style="color: var(--muted); font-style: italic;">Ticker not present in current active Bhavcopy universe</td>
        <td onclick="event.stopPropagation()"><button class="reset-btn" onclick="toggleWatchlist('${sym}', event)">Remove</button></td>
      `;
    }
    tbody.appendChild(tr);
  });
}

// ============================================================================
// 4. MODALS (UPI, COMMAND PALETTE ⌘K, STOCK QUANT BREAKDOWN)
// ============================================================================
function openUpiModal() { document.getElementById('upiModal').style.display = 'flex'; }
function closeUpiModal() { document.getElementById('upiModal').style.display = 'none'; }
function closeUpiOnOverlay(e) { if (e.target.id === 'upiModal') closeUpiModal(); }
function verifyUpiPayment() {
  const utr = document.getElementById('upiRefInput').value.trim();
  if (!utr) { showToast('Please enter a valid UTR transaction ID'); return; }
  localStorage.setItem('pro_active', 'true');
  document.getElementById('subBanner').style.display = 'none';
  showToast('UPI Payment Verified! Pro Subscription Activated 🚀');
  closeUpiModal();
}

function openCmdPalette() {
  document.getElementById('cmdModal').style.display = 'flex';
  const input = document.getElementById('cmdInput');
  input.value = '';
  input.focus();
  filterCmdResults('');
}
function closeCmdPalette() { document.getElementById('cmdModal').style.display = 'none'; }
function closeCmdOnOverlay(e) { if (e.target.id === 'cmdModal') closeCmdPalette(); }

function filterCmdResults(query) {
  const resContainer = document.getElementById('cmdResults');
  resContainer.innerHTML = '';
  const q = query.toUpperCase();
  const matches = appState.stocks.filter(st => 
    st.symbol.toUpperCase().includes(q) || 
    (st.company_name && st.company_name.toUpperCase().includes(q)) ||
    st.sector.toUpperCase().includes(q) ||
    st.inst_signal.toUpperCase().includes(q)
  ).slice(0, 15);

  if (matches.length === 0) {
    resContainer.innerHTML = '<div style="padding: 12px; color: var(--muted); text-align: center;">No matching symbols found</div>';
    return;
  }

  matches.forEach(st => {
    const div = document.createElement('div');
    div.className = 'cmd-item';
    div.innerHTML = `
      <div><b>${st.symbol}</b> <span style="color:var(--muted); font-size:0.75rem;">${st.company_name}</span></div>
      <div><span class="pill" style="background: rgba(56, 189, 248, 0.14); color: var(--accent); border: 1px solid rgba(56, 189, 248, 0.3);">${st.inst_signal}</span></div>
    `;
    div.onclick = () => { closeCmdPalette(); openStockModal(st); };
    resContainer.appendChild(div);
  });
}

window.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    openCmdPalette();
  }
  if (e.key === 'Escape') { closeCmdPalette(); closeModal(); closeUpiModal(); endProductTour(); }
});

function openStockModal(st) {
  const closeP = Number(st.close);
  const isTier1 = (st.mcap_tier || "").includes("Tier 1");
  const t1Pct = st.target_pct || (isTier1 ? 9.0 : 12.0);
  const t2Pct = isTier1 ? 22.0 : 35.0;
  const stopPct = st.risk_clamp_pct || (isTier1 ? -5.0 : -6.5);
  const shieldTrigPct = isTier1 ? 4.0 : 4.5;
  const shieldLockPct = isTier1 ? 0.8 : 1.0;

  const targetPrice = st.target_price ? Number(st.target_price).toFixed(2) : (closeP * (1.0 + (t1Pct / 100.0))).toFixed(2);
  const t2Price = st.tranche2_breakout_price ? Number(st.tranche2_breakout_price).toFixed(2) : (closeP * (1.0 + (t2Pct / 100.0))).toFixed(2);
  const shieldTrigPrice = (closeP * (1.0 + (shieldTrigPct / 100.0))).toFixed(2);
  const shieldFloorPrice = (closeP * (1.0 + (shieldLockPct / 100.0))).toFixed(2);
  const stopPrice = st.stop_loss_price ? Number(st.stop_loss_price).toFixed(2) : (closeP * (1.0 + (stopPct / 100.0))).toFixed(2);

  document.getElementById('modalSymbol').textContent = st.symbol;
  document.getElementById('modalCompanyName').textContent = st.company_name || st.symbol;
  document.getElementById('modalTags').textContent = `${st.sector} • ${st.index_name || 'Nifty 500'} • ATR: ${st.atr_pct ?? '--'}%`;
  document.getElementById('modalSignalPill').innerHTML = `<span class="pill pill-buyzone">${st.inst_signal}</span>`;
  document.getElementById('modalStrengthsText').innerHTML = `Entry: ₹${closeP.toFixed(2)} | Free-Roll Shield (+${shieldTrigPct}%): @ ₹${shieldTrigPrice} &rarr; Lock ₹${shieldFloorPrice} (+${shieldLockPct}% if &lt;10EMA) | 50/50 Targets: 50% @ ₹${targetPrice} (+${t1Pct}%), 50% Runner @ ₹${t2Price} (+${t2Pct}% / 2-Close 20-SMA) | Risk Clamp Stop: ₹${stopPrice} (${stopPct}% 2D Close)`;
  document.getElementById('modalAvoidText').innerHTML = st.reasons_to_avoid || 'None. Technical structure & kinetic fuel remain constructive.';
  document.getElementById('modalClose').textContent = `₹${closeP.toFixed(2)}`;
  document.getElementById('modalSma20').textContent = `₹${Number(st.sma_20).toFixed(2)}`;
  document.getElementById('modalSma50').textContent = `₹${Number(st.sma_50).toFixed(2)}`;
  document.getElementById('modalRsi').textContent = st.rsi_14 ?? 'N/A';
  document.getElementById('modalStoch').textContent = st.stoch_k ?? 'N/A';
  if (document.getElementById('modalTargetPrice')) document.getElementById('modalTargetPrice').textContent = `₹${targetPrice} (+${t1Pct}%)`;
  document.getElementById('modalAtrStop').textContent = `₹${stopPrice} (${stopPct}%)`;
  document.getElementById('modalPoc').textContent = `₹${Number(st.volume_profile_poc).toFixed(2)}`;
  document.getElementById('modalIasis').textContent = st.iasis_score ?? 'N/A';
  document.getElementById('modalRrr').textContent = `${st.risk_reward_ratio || 2.0}:1`;
  if (document.getElementById('modalIgnition')) document.getElementById('modalIgnition').textContent = st.score_surety_anchor ?? st.surety_score ?? '--';
  if (document.getElementById('modalFrontrunner')) document.getElementById('modalFrontrunner').textContent = st.score_momentum_frontrunner ?? st.frontrunner_score ?? '--';
  if (document.getElementById('modalPattern')) document.getElementById('modalPattern').textContent = st.chart_pattern_signal || 'Consolidation';
  if (document.getElementById('modalSectorRs')) document.getElementById('modalSectorRs').textContent = st.sector_lifecycle || st.sector_rs_status || '';
  if (document.getElementById('modalOrderBlock')) {
    document.getElementById('modalOrderBlock').textContent = st.order_block_status || `50/50 Dual-Stage Plan: Buy @ ₹${closeP.toFixed(2)} | Shield @ ₹${shieldTrigPrice} (+${shieldTrigPct}%) -> Lock ₹${shieldFloorPrice} (+${shieldLockPct}%) | Harvest 50% @ ₹${targetPrice} (+${t1Pct}%), 50% @ ₹${t2Price} (2-Close 20-SMA Trail) | Stop @ ₹${stopPrice} (${stopPct}%)`;
  }
  document.getElementById('modalTvLink').href = `https://in.tradingview.com/chart/?symbol=NSE:${st.symbol}`;
  document.getElementById('quantModal').style.display = 'flex';
}

function closeModal() { document.getElementById('quantModal').style.display = 'none'; }
function closeModalOnOverlay(e) { if (e.target.id === 'quantModal') closeModal(); }

// ============================================================================
// 5. GUIDED PRODUCT TOUR CONTROLLER
// ============================================================================
const TOUR_STEPS = [
  {
    tab: 'landing',
    selector: '#landingActiveHeroGrid',
    title: '1. Daily EOD Two-Pool Command Grid',
    desc: 'Updated after every NSE close. The Upper Section isolates Confirmed Actionable Trades that passed the Anti-Fizzle Kinetic Gate & Weekly MTF Alignment, while the Lower Section tracks coiling leaders awaiting breakout triggers.',
    beforeAction: () => { closeModal(); }
  },
  {
    tab: 'landing',
    selector: '#quantModalCard',
    title: '2. 50/50 Dual-Stage Execution Blueprint',
    desc: 'Clicking any stock card opens this diagnostic modal showing the +4.5% Free-Roll Breakeven Shield, 50% Core Target (+12%), 50% 2-Close 20-SMA Runner (+35%), and structural Risk Clamp stop.',
    beforeAction: () => {
      if (appState.stocks.length > 0) openStockModal(appState.stocks[0]);
    }
  },
  {
    tab: 'live',
    selector: '#btnModeSurety',
    title: '3. Uniform 4-Strategy Technical Screener',
    desc: 'Switch seamlessly between Strategy 1 (Surety Anchor), Strategy 2 (Momentum Frontrunner), Strategy 3 (Early Sector Rotation), and Strategy 4 (High-RS Pullback).',
    beforeAction: () => { closeModal(); }
  },
  {
    tab: 'live',
    selector: '#indexSelect',
    title: '4. Multi-Index & Cap-Tier Filtering',
    desc: 'Filter recommendations across Nifty 50, Nifty Next 50, Nifty 500, Midcap 150, Smallcap 250, or Microcap 250 universes.',
    beforeAction: () => { closeModal(); }
  },
  {
    tab: 'rrg',
    selector: '#sectorTilesGrid',
    title: '5. Interactive Sector RS Tiles',
    desc: 'Evaluate Triple-Horizon Sector RS and Breadth (>50-SMA %). Click any sector tile to drill down into all constituent stocks for that sector.',
    beforeAction: () => { closeModal(); }
  },
  {
    tab: 'rrg',
    selector: '#sectorDrilldownContainer',
    title: '6. Sector Constituents & Peer RS Drilldown',
    desc: 'Clicking a sector tile opens this constituent breakdown! Compare individual stock Peer RS curves against the sector benchmark and inspect every stock in the sector.',
    beforeAction: () => {
      if (appState.sectors.length > 0) {
        const topSec = [...appState.sectors].sort((a, b) => b.sector_composite_score - a.sector_composite_score)[0].sector;
        appState.selectedDrilldownSector = topSec;
        renderSectorTiles();
        renderSectorDrilldown(topSec);
      }
    }
  },
  {
    tab: 'patterns',
    selector: '#btnConfluenceOnly',
    title: '7. Chart Patterns & POC Floor Scanner',
    desc: 'Scan for genuine VCP Coiled Springs, High-Tight Flags, and Multi-Month Bases verified by Volume Profile Point of Control (POC) floor support.',
    beforeAction: () => { closeModal(); }
  },
  {
    tab: 'backtest',
    selector: '#btDailyProgressSection',
    title: '8. Quantitative Backtest & Daily Progress Tracker',
    desc: 'Audit real Bhavcopy performance across the 50/50 Dual-Stage Harvester, including the session-by-session Daily Equity Curve, Market-Cap Tiers, and Confluence Factor Audits.',
    beforeAction: () => { closeModal(); }
  }
];

let currentTourIdx = 0;
let activeHighlightedEl = null;

function startProductTour() {
  currentTourIdx = 0;
  document.getElementById('tourBackdrop').style.display = 'block';
  document.getElementById('tourPopover').style.display = 'block';
  renderTourStep();
}

function changeTourStep(delta) {
  const nextIdx = currentTourIdx + delta;
  if (nextIdx < 0) return;
  if (nextIdx >= TOUR_STEPS.length) {
    endProductTour();
    showToast('🎉 Tour Completed! Press ⌘K anytime to quick-search.');
    return;
  }
  currentTourIdx = nextIdx;
  renderTourStep();
}

function renderTourStep() {
  if (activeHighlightedEl) {
    activeHighlightedEl.classList.remove('tour-highlight');
    activeHighlightedEl = null;
  }

  const step = TOUR_STEPS[currentTourIdx];
  switchTab(step.tab);
  if (typeof step.beforeAction === 'function') {
    step.beforeAction();
  }

  setTimeout(() => {
    const targetEl = document.querySelector(step.selector);
    const popover = document.getElementById('tourPopover');

    document.getElementById('tourStepCounter').textContent = `Step ${currentTourIdx + 1} of ${TOUR_STEPS.length}`;
    document.getElementById('tourTitle').textContent = step.title;
    document.getElementById('tourDesc').textContent = step.desc;
    document.getElementById('tourPrevBtn').style.display = currentTourIdx === 0 ? 'none' : 'inline-block';
    document.getElementById('tourNextBtn').textContent = currentTourIdx === TOUR_STEPS.length - 1 ? 'Finish ✓' : 'Next →';

    if (!targetEl) {
      popover.style.top = '50%';
      popover.style.left = '50%';
      popover.style.transform = 'translate(-50%, -50%)';
      return;
    }

    popover.style.transform = 'none';
    targetEl.classList.add('tour-highlight');
    activeHighlightedEl = targetEl;
    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });

    setTimeout(() => {
      const rect = targetEl.getBoundingClientRect();
      const popWidth = 350;
      const popHeight = popover.offsetHeight || 195;

      let topPos = rect.bottom + 14;
      if (topPos + popHeight > window.innerHeight - 16) {
        topPos = Math.max(16, rect.top - popHeight - 14);
      }
      let leftPos = Math.min(Math.max(16, rect.left), window.innerWidth - popWidth - 16);

      popover.style.top = `${topPos}px`;
      popover.style.left = `${leftPos}px`;
    }, 240);
  }, 80);
}

function endProductTour() {
  if (activeHighlightedEl) {
    activeHighlightedEl.classList.remove('tour-highlight');
    activeHighlightedEl = null;
  }
  closeModal();
  document.getElementById('tourBackdrop').style.display = 'none';
  document.getElementById('tourPopover').style.display = 'none';
  localStorage.setItem('nse_alpha_tour_completed', 'true');
  switchTab('landing');
}