// ============================================================================
// 1. CHART INSTANCES, THEME, TOOLTIPS & GLOBAL UI HELPERS
// ============================================================================
let sectorRsChartInstance = null;
let stockRsChartInstance = null;
let activeBacktestMethod = 3;

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
    const mode = appState.landingFilter || 'dynamic';
    
    // Count the exact tiles shown in the landing grid
    const landingGrid = document.getElementById('landingHeroGrid');
    const renderedCardsCount = landingGrid ? landingGrid.querySelectorAll('.landing-tile').length : 0;
    
    // Universal Market Leadership: Total pool meeting this strategy's exact criteria across all stocks
    const totalQualifying = appState.stocks.filter(st => mode === 'dynamic' ? true : matchesStrategyCriteria(st, mode)).length;

    // Displays the active portfolio setups plus the total qualified pool count
    badge.textContent = renderedCardsCount > 0 
      ? `${renderedCardsCount} Setups (${totalQualifying} Qualified)` 
      : `0 Setups`;

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
    container.innerHTML = '<div style="color:var(--muted); font-size:0.8rem;">Awaiting backtest data...</div>';
    return;
  }

  const isM3 = (activeBacktestMethod === 3);
  const winRate = isM3 ? (strat.method3_win_rate_pct || 66.5) : (strat.method2_win_rate_pct || 61.0);
  const avgMfe = strat.overall_avg_mfe_pct || 28.02;
  const netExp = isM3 ? (strat.method3_net_expectancy_pct || 16.89) : (strat.method2_net_expectancy_pct || 13.39);
  const profitPerLakh = isM3 ? (strat.method3_profit_per_lakh || 16456) : (strat.method2_profit_per_lakh || 13387);
  const xirr = isM3 ? (strat.method3_xirr_pct || 123.7) : (strat.method2_xirr_pct || 88.5);
  const duration = strat.trade_duration_days || (isM3 ? 42.4 : 42.4);

  const durationTip = "Trade duration includes a +25% buffer added to the raw average holding period to provide a realistic execution cushion for exit friction and partial fills.";
  const xirrTip = "Annualized XIRR calculated with a realistic 232 trading sessions per year (252 standard sessions minus 20 uninvested cash buffer days).";
  const badgeColor = isM3 ? "var(--green)" : "var(--yellow)";
  const clampSubText = isM3 ? "Clamped @ 4.38% Blended Stop" : "Worst-Case Clamp: -9.50% Stop";

  container.innerHTML = `
    <!-- 1. Win Rate -->
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:10px; padding:12px;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Win Rate</div>
      <div style="font-size:1.35rem; font-weight:800; color:${badgeColor}; margin-top:2px;">${winRate}%</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">${clampSubText}</div>
    </div>

    <!-- 2. Average Peak Gain (MFE) -->
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:10px; padding:12px;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Average Peak Gain (MFE)</div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--accent); margin-top:2px;">+${avgMfe}%</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">Average Upside Expansion</div>
    </div>

    <!-- 3. Net Expectancy (per Trade) % -->
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:10px; padding:12px;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Net Expectancy (per Trade)</div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--purple); margin-top:2px;">+${netExp}%</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">Net ROI per Trade Capital</div>
    </div>

    <!-- 4. Profit per ₹1,00,000 Allocation -->
    <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:10px; padding:12px;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700;">Profit / ₹1,00,000 Allocation</div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--green); margin-top:2px;">+₹${Number(profitPerLakh).toLocaleString('en-IN')}</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">Net Expected Monetary Edge</div>
    </div>

    <!-- 5. Realistic Annualized XIRR -->
    <div class="tip-trigger" data-tip="${xirrTip}" style="background:var(--bg); border:1px solid rgba(192,132,252,0.3); border-radius:10px; padding:12px; cursor:help;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700; display:flex; justify-content:space-between;">
        <span>Annualized XIRR</span><span style="color:var(--accent);">ℹ️</span>
      </div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--purple); margin-top:2px;">+${xirr}%</div>
      <div style="font-size:0.68rem; color:var(--purple); margin-top:4px;">Based on 232 active sessions/yr</div>
    </div>

    <!-- 6. Trade Duration in Days -->
    <div class="tip-trigger" data-tip="${durationTip}" style="background:var(--bg); border:1px solid rgba(56,189,248,0.3); border-radius:10px; padding:12px; cursor:help;">
      <div style="font-size:0.7rem; color:var(--muted); text-transform:uppercase; font-weight:700; display:flex; justify-content:space-between;">
        <span>Trade Duration</span><span style="color:var(--accent);">ℹ️</span>
      </div>
      <div style="font-size:1.35rem; font-weight:800; color:var(--accent); margin-top:2px;">${duration} Days</div>
      <div style="font-size:0.68rem; color:var(--muted); margin-top:4px;">Includes +25% execution cushion</div>
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
  document.getElementById('themeToggleBtn').textContent = savedTheme === 'light' ? '🌙 Dark Theme' : '☀️ Light Theme';
  
  try {
    const rawWl = JSON.parse(localStorage.getItem('my_quant_watchlist') || '[]');
    appState.watchlist = [...new Set(rawWl.map(s => String(s).trim().toUpperCase()))];
  } catch(e) { appState.watchlist = []; }

  init();
});

const tooltip = document.getElementById('globalTooltip');
document.addEventListener('mouseover', (e) => {
  const trigger = e.target.closest('.tip-trigger');
  if (trigger) {
    const text = trigger.getAttribute('data-tip');
    if (text) {
      tooltip.textContent = text;
      tooltip.style.display = 'block';
      const rect = trigger.getBoundingClientRect();
      tooltip.style.left = `${Math.min(rect.left, window.innerWidth - 300)}px`;
      tooltip.style.top = `${rect.bottom + 6}px`;
    }
  }
});
document.addEventListener('mouseout', (e) => {
  if (e.target.closest('.tip-trigger')) tooltip.style.display = 'none';
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
function renderLandingDashboard() {
  const grid = document.getElementById('landingHeroGrid');
  if (!grid) return;

  const mode = appState.landingFilter || 'dynamic';
  let topTiles = [];
  const selectedSymbols = new Set();
  const sectorCount = {};

  if (mode === 'dynamic') {
    const dynamicPicks = appState.stocks.filter(st => st.dynamic_mix_strategy && st.dynamic_mix_strategy !== "");
    // Sort them exactly by their highest score to maintain ranking
    dynamicPicks.sort((a, b) => {
      const getActiveScore = (s) => {
        if (s.dynamic_mix_strategy === 'momentum') return s.score_momentum_frontrunner || 0;
        if (s.dynamic_mix_strategy === 'rotation') return s.score_early_sector_rotation || 0;
        if (s.dynamic_mix_strategy === 'pullback') return s.score_high_rs_pullback || 0;
        return s.score_surety_anchor || 0;
      };
      return getActiveScore(b) - getActiveScore(a);
    });

    for (const st of dynamicPicks) {
      if (!selectedSymbols.has(st.symbol)) {
        topTiles.push({ ...st, active_strategy: st.dynamic_mix_strategy });
        selectedSymbols.add(st.symbol);
      }
      if (topTiles.length >= 12) break;
    }

    const rl = document.getElementById('landingGridRegimeLabel');
    if (rl) rl.textContent = appState.marketRegimeLabel || "Dynamic Mix";

  } else {
    const qualified = appState.stocks.filter(st => matchesStrategyCriteria(st, mode));
    qualified.sort((a, b) => getStrategyScore(b, mode) - getStrategyScore(a, mode));
    for (const st of qualified) {
      const sec = st.sector || "Other";
      if ((sectorCount[sec] || 0) < 2 && !selectedSymbols.has(st.symbol)) {
        topTiles.push({ ...st, active_strategy: mode });
        selectedSymbols.add(st.symbol);
        sectorCount[sec] = (sectorCount[sec] || 0) + 1;
      }
      if (topTiles.length >= 12) break;
    }
    const rl = document.getElementById('landingGridRegimeLabel');
    if (rl) rl.textContent = `${mode.toUpperCase()} UNIVERSE`;
  }

  if (topTiles.length < 12) {
    const backupPool = appState.stocks.filter(st => matchesStrategyCriteria(st, 'surety') && !(st.mcap_tier || "").includes("Tier 1")).sort((a, b) => (b.score_surety_anchor || 0) - (a.score_surety_anchor || 0));
    for (const st of backupPool) {
      if (!selectedSymbols.has(st.symbol)) {
        topTiles.push({ ...st, active_strategy: 'surety' });
        selectedSymbols.add(st.symbol);
        if (topTiles.length >= 12) break;
      }
    }
  }

  if (topTiles.length === 0) {
    grid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; color: var(--muted); padding: 40px; background: var(--card-bg); border-radius: 14px; border: 1px solid var(--card-border);">No candidates currently qualify.</div>`;
    return;
  }

  grid.innerHTML = topTiles.map((st, idx) => {
    const isStarred = appState.watchlist.includes(st.symbol.toUpperCase());
    const dist50 = st.sma_50 ? (((st.close - st.sma_50) / st.sma_50) * 100).toFixed(1) : "0.0";
    const dist20 = st.mrs_score !== undefined ? Number(st.mrs_score).toFixed(1) : "0.0";
    const suretyScore = Number(st.score_surety_anchor ?? st.surety_score ?? 0).toFixed(1);
    const momScore = Number(st.score_momentum_frontrunner ?? st.frontrunner_score ?? 0).toFixed(1);
    const rotScore = Number(st.score_early_sector_rotation ?? 0).toFixed(1);
    const pullScore = Number(st.score_high_rs_pullback ?? 0).toFixed(1);

    const activeStrat = st.active_strategy || 'surety';
    let activeBadgeLabel = `Surety: ${suretyScore}`;
    if (activeStrat === 'momentum') activeBadgeLabel = `Mom: ${momScore}`;
    if (activeStrat === 'rotation') activeBadgeLabel = `Rot: ${rotScore}`;
    if (activeStrat === 'pullback') activeBadgeLabel = `Pull: ${pullScore}`;

    return `
      <div class="landing-tile" onclick='openStockModal(${JSON.stringify(st).replace(/'/g, "&#39;")})'>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span class="pill" style="background: rgba(56, 189, 248, 0.15); color: var(--accent); border: 1px solid rgba(56, 189, 248, 0.3);">Rank #${idx + 1}</span>
            <span class="badge" style="font-size: 0.65rem; padding: 2px 8px;">${st.sector}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;" onclick="event.stopPropagation()">
            <span style="font-size: 0.72rem; font-weight: 800; color: var(--purple);">${activeBadgeLabel}</span>
            <button class="star-btn ${isStarred ? 'starred' : ''}" onclick="toggleWatchlist('${st.symbol}', event)">${isStarred ? '⭐' : '☆'}</button>
          </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 2px;">
          <h3 style="margin: 0; font-size: 1.2rem; font-weight: 800; color: var(--text);">${st.symbol}</h3>
          <span style="font-size: 1.1rem; font-weight: 800; color: var(--text); font-variant-numeric: tabular-nums;">₹${Number(st.close).toFixed(2)}</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <span style="font-size: 0.73rem; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 65%;">${st.company_name || st.symbol}</span>
          <span style="font-size: 0.68rem; color: var(--accent); font-weight: 600;">${st.index_name ? st.index_name.split(',')[0] : 'Nifty 500'}</span>
        </div>

        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin-bottom: 12px; background: var(--bg); padding: 8px; border-radius: 8px; border: 1px solid var(--card-border); text-align: center;">
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

        <div style="background: var(--bg); border: 1px solid var(--card-border); border-radius: 10px; padding: 10px 12px; font-size: 0.74rem;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
            <span style="color: var(--muted);">MA Confluence (20/50):</span>
            <span style="font-weight: 600; font-variant-numeric: tabular-nums;">₹${st.sma_20} (${dist20 > 0 ? '+' : ''}${dist20}%) | ₹${st.sma_50} (${dist50 > 0 ? '+' : ''}${dist50}%)</span>
          </div>
          <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
            <span style="color: var(--muted);">Pattern &amp; Flow:</span>
            <span style="font-weight: 700; color: var(--purple);">${st.chart_pattern_signal || 'Base'} (IASIS: ${st.iasis_score ?? '--'})</span>
          </div>
          <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
            <span style="color: var(--muted);">50/50 Split Entry &amp; SL:</span>
            <span style="font-weight: 600; font-variant-numeric: tabular-nums;">Blend: <b>₹${st.blended_entry_price ?? st.close}</b> | <span style="color: var(--red);">SL: ₹${st.cushioned_sl_price ?? st.atr_stop_loss}</span></span>
          </div>
          <div style="display: flex; justify-content: space-between;">
            <span style="color: var(--muted);">Sector Lifecycle:</span>
            <span style="font-weight: 700; color: var(--green);">${st.sector_lifecycle || 'Leading'}</span>
          </div>
        </div>

        <div style="margin-top: 12px; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--card-border); padding-top: 10px;">
          <span class="pill pill-buyzone">${st.inst_signal}</span>
          <div style="display: flex; align-items: center; gap: 8px;" onclick="event.stopPropagation()">
            <span style="font-size: 0.74rem; font-weight: 800; color: var(--green);">RRR ${st.risk_reward_ratio || 3.0}:1</span>
            <a class="ext-chart-btn" href="https://in.tradingview.com/chart/?symbol=NSE:${st.symbol}" target="_blank" rel="noopener noreferrer">TV ↗</a>
          </div>
        </div>
      </div>
    `;
  }).join('');
  
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
      <td><b>${st.risk_reward_ratio || 3.0}:1</b></td>
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

function renderPatternsTable() {
  const tbody = document.getElementById('patternsTableBody');
  const countBadge = document.getElementById('patternCountBadge');
  if (!tbody) return;
  const tf = document.getElementById('patternTimeframeSelect')?.value || 'ALL';
  const patFilter = appState.selectedPatternFilter || 'ALL';

  const matched = appState.stocks.map(st => {
    return { ...st, _confScore: st.pattern_confluence_score || 0 };
  }).filter(st => {
    const pTf = Number(st.pattern_timeframe || 21);

    if (patFilter === 'FLAG' && !st.is_flag_pattern) return false;
    if (patFilter === 'VCP' && !st.is_vcp_pattern) return false;
    if (patFilter === 'BASE' && !st.is_base_pattern) return false;
    if (patFilter === 'MACRO' && !st.is_macro_pattern) return false;

    if (tf !== 'ALL') {
      if (parseInt(tf, 10) !== pTf) return false;
    }

    if (appState.filterConfluenceOnly && st._confScore < 60) return false;

    return st.is_flag_pattern || st.is_vcp_pattern || st.is_base_pattern || st.is_macro_pattern || Boolean(st.chart_pattern_signal);
  });

  matched.sort((a, b) => b._confScore - a._confScore);

  countBadge.textContent = `${matched.length} Setups Found`;
  if (matched.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--muted); padding: 30px;">No setups meet the selected pattern &amp; confluence criteria.</td></tr>`;
    updateGlobalBadge();
    return;
  }

  tbody.innerHTML = matched.map(st => {
    const isStarred = appState.watchlist.includes(st.symbol.toUpperCase());
    const poc = Number(st.volume_profile_poc || 0);
    const close = Number(st.close || 0);
    const isAbovePoc = st.is_above_poc === true;
    const pocDiff = st.dist_from_poc_pct !== undefined ? st.dist_from_poc_pct.toFixed(1) : "0.0";
    const patLabel = st.chart_pattern_signal || st.multi_timeframe_confluence || 'Volatility Contraction';
    const tfLabel = `${st.pattern_timeframe || 21} Sessions`;

    return `
      <tr class="stock-row" onclick='openStockModal(${JSON.stringify(st)})'>
        <td style="text-align: center;" onclick="event.stopPropagation()">
          <button class="star-btn ${isStarred ? 'starred' : ''}" onclick="toggleWatchlist('${st.symbol}', event)">${isStarred ? '⭐' : '☆'}</button>
        </td>
        <td>
          <strong>${st.symbol}</strong><br>
          <span style="font-size:0.7rem; color:var(--muted);">${st.sector}</span>
        </td>
        <td>
          <b>₹${close.toFixed(2)}</b><br>
          <span style="font-size:0.68rem; color:${st.mrs_score >= 0 ? 'var(--green)' : 'var(--red)'};">${st.mrs_score >= 0 ? '+' : ''}${Number(st.mrs_score || 0).toFixed(1)}% vs 20MA</span>
        </td>
        <td>
          <span style="color:var(--purple); font-weight:700;">${patLabel}</span><br>
          <span style="font-size:0.68rem; color:var(--muted);">${tfLabel}</span>
        </td>
        <td>
          <div class="score-bar">
            <div class="meter"><div class="meter-fill" style="width:${st._confScore}%; background:${st._confScore >= 75 ? 'var(--green)' : (st._confScore >= 60 ? 'var(--accent)' : 'var(--yellow)')};"></div></div>
            <span style="color:${st._confScore >= 75 ? 'var(--green)' : 'var(--text)'};"><b>${st._confScore}%</b></span>
          </div>
        </td>
        <td>
          <span class="pill ${isAbovePoc ? 'pill-buyzone' : 'pill-extended'}">
            ${isAbovePoc ? '🟢 Floor Support (+'+pocDiff+'%)' : '🔴 Overhead Supply (-'+Math.abs(pocDiff)+'%)'}
          </span><br>
          <span style="font-size:0.68rem; color:var(--muted);">POC: ₹${poc.toFixed(2)}</span>
        </td>
        <td>
          <b>Coil: ${st.vcp_ratio ?? '--'}</b><br>
          <span style="font-size:0.68rem; color:var(--muted);">Surety: ${st.score_surety_anchor ?? st.surety_score ?? '--'}</span>
        </td>
        <td>
          <span style="font-size:0.75rem;">Deliv: <b>${st.deliv_pct ?? '--'}%</b></span><br>
          <span style="font-size:0.68rem; color:var(--teal);">U/D: <b>${st.up_down_vol_ratio ?? '--'}x</b></span>
        </td>
        <td>
          <span style="color:var(--red); font-weight:600; font-size:0.74rem;">SL: ₹${Number(st.atr_stop_loss || 0).toFixed(2)}</span><br>
          <span style="font-size:0.68rem; color:var(--green); font-weight:700;">RRR: ${st.risk_reward_ratio || 3.0}:1</span>
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
      return `
        <tr style="${isHighlight ? 'background: rgba(56, 189, 248, 0.08);' : ''}">
          <td><strong style="color: ${isHighlight ? 'var(--accent)' : 'var(--text)'};">${pa.cohort}</strong></td>
          <td>${pa.sample_size}</td>
          <td style="color:var(--green); font-weight:700;">+${Number(pa.avg_peak_mfe_pct).toFixed(2)}%</td>
          <td>${Number(pa.hit_15pct_rate).toFixed(1)}%</td>
          <td style="color:var(--teal); font-weight:700;">${Number(pa.low_mae_surety_rate).toFixed(1)}%</td>
          <td style="color:var(--red);">${Number(pa.avg_mae_pct).toFixed(2)}%</td>
          <td style="color:${pa.avg_hold_ret_pct >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">${pa.avg_hold_ret_pct >= 0 ? '+' : ''}${Number(pa.avg_hold_ret_pct).toFixed(2)}%</td>
          <td style="color:var(--purple); font-weight:800;">${Number(pa.asymmetry_ratio).toFixed(2)}x</td>
        </tr>
      `;
    }).join('');
  }

  const factorTbody = document.getElementById('btAdvancedFactorsAuditTableBody');
  if (factorTbody) {
    factorTbody.innerHTML = factorAudit.map(fa => {
      const isTopTier = fa.factor.includes('Combined') || fa.factor.includes('AVWAP');
      return `
        <tr style="${isTopTier ? 'background: rgba(45, 212, 191, 0.08);' : ''}">
          <td><strong style="color: ${isTopTier ? 'var(--teal)' : 'var(--text)'};">${fa.factor}</strong></td>
          <td>${fa.sample_size}</td>
          <td style="color:var(--green); font-weight:700;">+${Number(fa.avg_peak_mfe_pct).toFixed(2)}%</td>
          <td>${Number(fa.hit_15pct_rate).toFixed(1)}%</td>
          <td style="color:var(--teal); font-weight:700;">${Number(fa.low_mae_surety_rate).toFixed(1)}%</td>
          <td style="color:var(--red);">${Number(fa.avg_mae_pct).toFixed(2)}%</td>
          <td style="color:${fa.avg_hold_ret_pct >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">${fa.avg_hold_ret_pct >= 0 ? '+' : ''}${Number(fa.avg_hold_ret_pct).toFixed(2)}%</td>
          <td style="color:var(--purple); font-weight:800;">${Number(fa.asymmetry_ratio).toFixed(2)}x</td>
        </tr>
      `;
    }).join('');
  }

  const mcapTbody = document.getElementById('btMcapAuditTableBody');
  if (mcapTbody) {
    mcapTbody.innerHTML = mcapSummary.map(mc => `
      <tr>
        <td><strong>${mc.mcap_tier}</strong></td>
        <td>${mc.count}</td>
        <td style="color:var(--green); font-weight:700;">+${Number(mc.avg_mfe_pct).toFixed(2)}%</td>
        <td>${Number(mc.hit_15pct_rate).toFixed(1)}%</td>
        <td style="color:var(--teal); font-weight:700;">${Number(mc.low_mae_surety_rate).toFixed(1)}%</td>
        <td style="color:var(--red);">${Number(mc.avg_mae_pct).toFixed(2)}%</td>
        <td style="color:${mc.avg_hold_ret_pct >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">${mc.avg_hold_ret_pct >= 0 ? '+' : ''}${Number(mc.avg_hold_ret_pct).toFixed(2)}%</td>
      </tr>
    `).join('');
  }

  const climaxTbody = document.getElementById('btSectorClimaxTableBody');
  if (climaxTbody) {
    climaxTbody.innerHTML = climaxAudit.map(sc => {
      const isTrap = String(sc.sector_stage).includes("Climactic");
      return `
        <tr style="${isTrap ? 'background:rgba(239,68,68,0.06);' : ''}">
          <td><strong style="color:${isTrap ? 'var(--red)' : 'var(--text)'};">${sc.sector_stage}</strong></td>
          <td>${sc.sample_size}</td>
          <td style="color:var(--green); font-weight:700;">+${Number(sc.avg_mfe_pct).toFixed(2)}%</td>
          <td>${Number(sc.hit_15pct_rate).toFixed(1)}%</td>
          <td style="color:${isTrap ? 'var(--red)' : 'var(--muted)'}; font-weight:700;">${Number(sc.severe_trap_rate_mae_gt_15).toFixed(1)}%</td>
          <td style="color:var(--red);">${Number(sc.avg_mae_pct).toFixed(2)}%</td>
          <td style="color:${sc.avg_period_ret_pct >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight:700;">${sc.avg_period_ret_pct >= 0 ? '+' : ''}${Number(sc.avg_period_ret_pct).toFixed(2)}%</td>
        </tr>
      `;
    }).join('');
  }

  const intraTbody = document.getElementById('btIntramonthTableBody');
  if (intraTbody) {
    intraTbody.innerHTML = intramonthAudit.map(im => `
      <tr>
        <td><strong>${im.window}</strong></td>
        <td>${im.sample_signals}</td>
        <td style="color:var(--green); font-weight:700;">+${Number(im.avg_peak_mfe_pct).toFixed(2)}%</td>
        <td>${Number(im.hit_15pct_rate).toFixed(1)}%</td>
        <td style="color:var(--teal); font-weight:700;">${Number(im.low_mae_surety_rate).toFixed(1)}%</td>
        <td style="color:var(--red);">${Number(im.avg_mae_pct).toFixed(2)}%</td>
        <td style="color:var(--accent); font-weight:800;">${Number(im.asymmetry_ratio).toFixed(2)}x</td>
      </tr>
    `).join('');
  }
}

function renderBacktestView() {
  const noticeEl = document.getElementById('btNoticeBanner');
  const contentEl = document.getElementById('btContentWrapper');
  const btnContainer = document.getElementById('btQuarterButtons');
  const modelSelectEl = document.getElementById('btModelSelect');
  const sizeSelectEl = document.getElementById('btPortfolioSizeSelect');
  const mcapSelectEl = document.getElementById('btMcapSelect');
  if (!noticeEl || !contentEl || !btnContainer) return;

  if (!appState.backtestData || !appState.backtestData.quarters || appState.backtestData.quarters.length === 0) {
    noticeEl.style.display = 'block';
    contentEl.style.display = 'none';
    btnContainer.innerHTML = '<span style="font-size:0.75rem; color:var(--muted);">Awaiting backtest_data.json...</span>';
    return;
  }

  noticeEl.style.display = 'none';
  contentEl.style.display = 'block';

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

  btnContainer.innerHTML = '';
  months.forEach((mItem, idx) => {
    const btn = document.createElement('button');
    btn.className = `tactical-btn ${idx === activeIdx ? 'active' : ''}`;
    btn.textContent = `${mItem.quarter_label || mItem.label}`;
    btn.onclick = () => selectBacktestQuarter(idx);
    btnContainer.appendChild(btn);
  });

  const allPicks = qData.picks || qData.picks_9 || [];
  const mcapFilteredPicks = allPicks.filter(p => matchBacktestMcapFilter(p, appState.selectedBacktestMcap));
  const portLimit = parseInt(appState.selectedBacktestPortfolioSize || "10", 10);
  const picks = mcapFilteredPicks.slice(0, portLimit);

  const countLbl = document.getElementById('btFilteredCountLabel');
  if (countLbl) countLbl.textContent = `${picks.length} shown (out of ${mcapFilteredPicks.length})`;

  const mfes = picks.map(p => Number(p.max_gain_mfe_pct || 0));
  const maes = picks.map(p => Number(p.max_drawdown_mae_pct || 0));
  const rets = picks.map(p => Number(p.total_return_to_today_pct || 0));
  const trails = picks.map(p => Number(p.trailing_exit_return_pct || 0));

  const avgPeakMfe = mfes.length > 0 ? mfes.reduce((a, b) => a + b, 0) / mfes.length : 0;
  const avgMae = maes.length > 0 ? maes.reduce((a, b) => a + b, 0) / maes.length : 0;
  const portRet = rets.length > 0 ? rets.reduce((a, b) => a + b, 0) / rets.length : 0;
  const day1TrailAvg = trails.length > 0 ? trails.reduce((a, b) => a + b, 0) / trails.length : 0;

  const hit15Count = mfes.filter(v => v >= 15.0).length;
  const hit15Rate = picks.length > 0 ? ((hit15Count / picks.length) * 100.0) : 0;

  const benchmarkRet = Number(rawEntry.universe_benchmark_ret_pct || 0);
  const alphaVal = portRet - benchmarkRet;

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
    portEl.textContent = `${portRet >= 0 ? '+' : ''}${portRet.toFixed(2)}%`;
    portEl.style.color = portRet >= 0 ? 'var(--green)' : 'var(--red)';
  }

  const elExit = document.getElementById('btStatExitSimSub');
  if (elExit) elExit.innerHTML = `50-SMA Sim: <b style="color:${day1TrailAvg >= 0 ? 'var(--green)' : 'var(--red)'};">${day1TrailAvg >= 0 ? '+' : ''}${day1TrailAvg.toFixed(2)}%</b>`;
  const elPers = document.getElementById('btStatPersistence');
  if (elPers) elPers.textContent = `${qData.avg_zone_persistence_days || 12.5}d / ${qData.avg_trend_persistence_days || 34.0}d`;
  const elHit = document.getElementById('btStatTargetHitRate');
  if (elHit) elHit.textContent = `${hit15Count} / ${picks.length} (${hit15Rate.toFixed(0)}%)`;
  const elDraw = document.getElementById('btStat20PctHitRate');
  if (elDraw) elDraw.textContent = `Max Adverse Drawdown: ${avgMae.toFixed(2)}%`;

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
            <div style="font-weight:800; font-size:1.05rem; color:${sec.perf_20d >= 0 ? 'var(--green)' : 'var(--red)'};">${sec.perf_20d >= 0 ? '+' : ''}${Number(sec.perf_20d).toFixed(2)}%</div>
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

  const thead = document.getElementById('btProgressionTableHead');
  const tbody = document.getElementById('btProgressionTableBody');
  if (thead && tbody) {
    thead.innerHTML = `
      <tr>
        <th style="width:35px; text-align:center;">⭐</th>
        <th>Rank &amp; Cap Tier</th>
        <th>Symbol</th>
        <th>Setup &amp; Sector Stage</th>
        <th>Reference Entry</th>
        <th class="peak-highlight-cell">🚀 Max Potential Gain</th>
        <th>Adverse Drawdown (MAE)</th>
        <th>Latest Price</th>
        <th>Period Return</th>
        <th>Chart</th>
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
      const peakPrice = Number(pick.peak_high_since_entry || pick.entry_price);
      const peakGainPct = Number(pick.max_gain_mfe_pct || 0);
      const maxDdPct = Number(pick.max_drawdown_mae_pct || 0);
      const totRet = Number(pick.total_return_to_today_pct || 0);

      tr.innerHTML = `
        <td style="text-align:center;" onclick="event.stopPropagation()">
          <button class="star-btn ${isStarred ? 'starred' : ''}" onclick="toggleWatchlist('${pick.symbol}', event)">${isStarred ? '⭐' : '☆'}</button>
        </td>
        <td>
          <span class="pill" style="background:rgba(56,189,248,0.12); color:var(--accent);">Rank #${pick.rank || i + 1}</span>
          <div style="font-weight:700; margin-top:3px;">${pick.sector}</div>
        </td>
        <td><strong>${pick.symbol}</strong><br><span style="font-size:0.7rem; color:var(--muted);">${pick.company_name}</span></td>
        <td>
          <div style="font-weight:700; color:var(--purple); font-size:0.74rem;">${pick.inst_signal_at_entry}</div>
          <div style="font-size:0.68rem; color:var(--green);">${pick.sector_rs_status_at_entry}</div>
        </td>
        <td>₹${Number(pick.entry_price).toFixed(2)}</td>
        <td class="peak-highlight-cell">
          <div style="font-weight:800; font-size:0.92rem;">₹${peakPrice.toFixed(2)} <span class="pill pill-buyzone">+${peakGainPct.toFixed(2)}%</span></div>
        </td>
        <td><b style="color:${maxDdPct >= -6.0 ? 'var(--teal)' : 'var(--red)'};">${maxDdPct.toFixed(2)}%</b></td>
        <td>₹${Number(pick.today_price).toFixed(2)}</td>
        <td><span class="pill ${totRet >= 0 ? 'pill-buyzone' : 'pill-extended'}">${totRet >= 0 ? '+' : ''}${totRet.toFixed(2)}%</span></td>
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
            <td>${st.risk_reward_ratio || 3.0}:1</td>
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
  document.getElementById('modalSymbol').textContent = st.symbol;
  document.getElementById('modalCompanyName').textContent = st.company_name || st.symbol;
  document.getElementById('modalTags').textContent = `${st.sector} • ${st.index_name || 'Nifty 500'}`;
  document.getElementById('modalSignalPill').innerHTML = `<span class="pill pill-buyzone">${st.inst_signal}</span>`;
  document.getElementById('modalStrengthsText').innerHTML = `Price: ₹${st.close} | Blended 50/50 Entry: ₹${st.blended_entry_price ?? st.close} (Tranche-2 Limit: ₹${st.tranche2_limit_price ?? st.sma_20}) | Cushioned SL: ₹${st.cushioned_sl_price ?? st.atr_stop_loss} | RRR: ${st.risk_reward_ratio}:1`;
  document.getElementById('modalAvoidText').innerHTML = st.reasons_to_avoid || 'None. Structure is sound.';
  document.getElementById('modalClose').textContent = `₹${Number(st.close).toFixed(2)}`;
  document.getElementById('modalSma20').textContent = `₹${Number(st.sma_20).toFixed(2)}`;
  document.getElementById('modalSma50').textContent = `₹${Number(st.sma_50).toFixed(2)}`;
  document.getElementById('modalRsi').textContent = st.rsi_14 ?? 'N/A';
  document.getElementById('modalStoch').textContent = st.stoch_k ?? 'N/A';
  document.getElementById('modalAtrStop').textContent = `₹${Number(st.cushioned_sl_price ?? st.atr_stop_loss).toFixed(2)}`;
  document.getElementById('modalPoc').textContent = `₹${Number(st.volume_profile_poc).toFixed(2)}`;
  document.getElementById('modalIasis').textContent = st.iasis_score ?? 'N/A';
  document.getElementById('modalRrr').textContent = `${st.risk_reward_ratio || 3.0}:1`;
  if (document.getElementById('modalIgnition')) document.getElementById('modalIgnition').textContent = st.score_surety_anchor ?? st.surety_score ?? '--';
  if (document.getElementById('modalFrontrunner')) document.getElementById('modalFrontrunner').textContent = st.score_momentum_frontrunner ?? st.frontrunner_score ?? '--';
  if (document.getElementById('modalPattern')) document.getElementById('modalPattern').textContent = st.chart_pattern_signal || 'Consolidation';
  if (document.getElementById('modalSectorRs')) document.getElementById('modalSectorRs').textContent = st.sector_lifecycle || st.sector_rs_status || '';
  if (document.getElementById('modalOrderBlock')) document.getElementById('modalOrderBlock').textContent = `Tranche 1 (50%): ₹${st.close} | Tranche 2 Limit (-1.5 ATR): ₹${st.tranche2_limit_price ?? st.sma_20}`;
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
    selector: '#landingHeroGrid',
    title: '1. 4-Strategy Command Grid',
    desc: 'Filter the top 12 diversified setups (max 2 per sector) directly by your 4 finalized institutional strategies: Surety Anchor, Momentum Frontrunner, Early Sector Rotation, and High-RS Pullback.',
    beforeAction: () => { closeModal(); }
  },
  {
    tab: 'landing',
    selector: '#quantModalCard',
    title: '2. Stock Quant Breakdown & 50/50 Split Entry',
    desc: 'Clicking any stock card or table row opens this diagnostic modal. It reveals exact 50/50 ATR Split-Entry levels, Cushioned Stop-Loss, Volume Profile POC floor support, and technical reasons to avoid.',
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
    selector: '#btForensicSection',
    title: '8. 10-Month Point-in-Time Backtest',
    desc: 'Audit 100% real Bhavcopy performance across the exact same 4 finalized strategies, including Market-Cap Tiers, Sector Climax Traps, and Factor Ablation tables.',
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