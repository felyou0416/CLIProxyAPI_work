let tokenUsagePanelLoaded = false;
let tokenUsageData = null;
let tokenUsageActiveRange = 15;

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function getLocalDateString(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function formatTokenCount(num) {
  const val = Number(num || 0);
  if (val >= 1000000) {
    let formatted = (val / 1000000).toFixed(1);
    if (formatted.endsWith('.0')) formatted = formatted.slice(0, -2);
    return formatted + 'M';
  }
  if (val >= 1000) {
    let formatted = (val / 1000).toFixed(1);
    if (formatted.endsWith('.0')) formatted = formatted.slice(0, -2);
    return formatted + 'K';
  }
  return val.toString();
}

async function loadTokenUsagePanel(force = false) {
  if (tokenUsagePanelLoaded && !force) return;

  // Show loading state
  const ids = ['metric-total-tokens', 'metric-prompt-tokens', 'metric-completion-tokens', 'metric-request-count', 'metric-avg-tokens', 'metric-active-days', 'metric-peak-tokens'];
  ids.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '...';
  });

  const chartContainer = document.getElementById('daily-bar-chart');
  if (chartContainer) {
    chartContainer.innerHTML = '<div class="metric-empty">loading...</div>';
  }

  const modelRankingList = document.getElementById('model-ranking-list');
  const clientRankingList = document.getElementById('client-ranking-list');
  const providerRankingList = document.getElementById('provider-ranking-list');
  
  if (modelRankingList) modelRankingList.innerHTML = '<div class="metric-empty">loading...</div>';
  if (clientRankingList) clientRankingList.innerHTML = '<div class="metric-empty">loading...</div>';
  if (providerRankingList) providerRankingList.innerHTML = '<div class="metric-empty">loading...</div>';

  try {
    if (force) {
      // Force refresh by pinging request-events with limit=1 to trigger cache refresh
      await api('/api/request-events?refresh=1&limit=1').catch(() => {});
    }

    const res = await api('/api/cumulative-stats');
    tokenUsageData = res.stats || {};
    
    // Update metadata refreshed time
    const metaEl = document.getElementById('token-usage-meta');
    if (metaEl) {
      const refreshed = res.stats?.updated_at 
        ? new Date(Number(res.stats.updated_at) * 1000).toLocaleTimeString() 
        : new Date().toLocaleTimeString();
      metaEl.textContent = `最近刷新: ${refreshed}`;
    }

    renderTokenMetrics();
    renderDailyBarChart();
    renderTokenRankings();

    tokenUsagePanelLoaded = true;
  } catch (error) {
    console.error('Failed to load token usage stats:', error);
    const errMsg = `<div class="metric-empty error-text">加载失败: ${error.message || '未知错误'}</div>`;
    if (chartContainer) chartContainer.innerHTML = errMsg;
    if (modelRankingList) modelRankingList.innerHTML = errMsg;
    if (clientRankingList) clientRankingList.innerHTML = errMsg;
    if (providerRankingList) providerRankingList.innerHTML = errMsg;
  }
}

function renderTokenMetrics() {
  if (!tokenUsageData) return;
  const totals = tokenUsageData.totals || {};
  const daily = tokenUsageData.daily || {};

  const totalTokens = Number(totals.total_tokens || 0);
  const promptTokens = Number(totals.prompt_tokens || 0);
  const completionTokens = Number(totals.completion_tokens || 0);
  const requestCount = Number(totals.request_count || 0);

  // Set Total tokens
  document.getElementById('metric-total-tokens').textContent = formatTokenCount(totalTokens);
  document.getElementById('metric-prompt-tokens').textContent = formatTokenCount(promptTokens);
  document.getElementById('metric-completion-tokens').textContent = formatTokenCount(completionTokens);

  // Set Request Count
  document.getElementById('metric-request-count').textContent = requestCount.toLocaleString();

  // Set Avg tokens per request
  const avg = requestCount > 0 ? Math.round(totalTokens / requestCount) : 0;
  document.getElementById('metric-avg-tokens').textContent = formatTokenCount(avg);

  // Set Active days and peak day
  const dailyDays = Object.keys(daily);
  document.getElementById('metric-active-days').textContent = dailyDays.length + ' 天';

  let peakTokens = 0;
  let peakDate = '-';
  for (const [date, dayData] of Object.entries(daily)) {
    const dayTotal = Number(dayData.total_tokens || 0);
    if (dayTotal > peakTokens) {
      peakTokens = dayTotal;
      peakDate = date;
    }
  }

  const peakSub = peakTokens > 0 ? `${formatTokenCount(peakTokens)} (${peakDate.substring(5)})` : '-';
  document.getElementById('metric-peak-tokens').textContent = peakSub;
}

function setTokenRange(days) {
  tokenUsageActiveRange = days;
  
  // Toggle button active class
  document.querySelectorAll('.range-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  const activeBtn = document.getElementById(`range-btn-${days}`);
  if (activeBtn) activeBtn.classList.add('active');

  renderDailyBarChart();
}

function renderDailyBarChart() {
  const chartContainer = document.getElementById('daily-bar-chart');
  if (!chartContainer || !tokenUsageData) return;

  const range = tokenUsageActiveRange;
  let chartData = [];

  if (range === 'hourly') {
    const hourly = tokenUsageData.hourly || {};
    const now = new Date();
    for (let i = 23; i >= 0; i--) {
      const d = new Date(now.getTime() - i * 3600 * 1000);
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const h = String(d.getHours()).padStart(2, '0');
      const hourStr = `${y}-${m}-${day} ${h}:00`;
      
      const record = hourly[hourStr] || { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, request_count: 0 };
      chartData.push({
        date: hourStr,
        label: `${h}:00`,
        prompt: Number(record.prompt_tokens || 0),
        completion: Number(record.completion_tokens || 0),
        total: Number(record.total_tokens || 0),
        requests: Number(record.request_count || 0)
      });
    }
  } else {
    const daily = tokenUsageData.daily || {};
    const rangeDays = Number(range || 15);

    // Generate date series for the last rangeDays
    const dates = [];
    for (let i = rangeDays - 1; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      dates.push(getLocalDateString(d));
    }

    chartData = dates.map(dateStr => {
      const record = daily[dateStr] || { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, request_count: 0 };
      return {
        date: dateStr,
        label: dateStr.substring(5), // MM-DD
        prompt: Number(record.prompt_tokens || 0),
        completion: Number(record.completion_tokens || 0),
        total: Number(record.total_tokens || 0),
        requests: Number(record.request_count || 0)
      };
    });
  }

  const maxTotal = Math.max(...chartData.map(d => d.total));
  const scaleMax = maxTotal > 0 ? maxTotal : 100;

  if (maxTotal === 0) {
    chartContainer.innerHTML = '<div class="metric-empty">指定时间段内暂无 Token 消耗数据</div>';
    return;
  }

  let html = '';
  chartData.forEach(item => {
    const heightPercent = Math.max(1, (item.total / scaleMax) * 100);
    const promptPercent = item.total > 0 ? (item.prompt / item.total) * 100 : 0;
    const completionPercent = item.total > 0 ? (item.completion / item.total) * 100 : 0;

    html += `
      <div class="chart-bar-column" 
           data-date="${item.date}" 
           data-total="${formatTokenCount(item.total)}" 
           data-prompt="${formatTokenCount(item.prompt)}" 
           data-completion="${formatTokenCount(item.completion)}" 
           data-requests="${item.requests.toLocaleString()}">
        <div class="chart-bar-wrapper" style="height: ${heightPercent}%;">
          ${item.completion > 0 ? `<div class="chart-bar-segment completion" style="height: ${completionPercent}%;"></div>` : ''}
          ${item.prompt > 0 ? `<div class="chart-bar-segment prompt" style="height: ${promptPercent}%;"></div>` : ''}
        </div>
        <div class="chart-bar-label">${item.label}</div>
      </div>
    `;
  });

  chartContainer.innerHTML = html;
  initChartTooltipEvents();

  // Auto-scroll to the right so that the most recent data is visible first
  setTimeout(() => {
    const chartWrapper = document.querySelector('.bar-chart-wrapper');
    if (chartWrapper) {
      chartWrapper.scrollLeft = chartWrapper.scrollWidth;
    }
  }, 50);
}

function initChartTooltipEvents() {
  const container = document.getElementById('daily-bar-chart');
  const tooltip = document.getElementById('chart-global-tooltip');
  const card = document.querySelector('.chart-container-card');
  if (!container || !tooltip || !card) return;

  container.querySelectorAll('.chart-bar-column').forEach(column => {
    column.addEventListener('mouseenter', () => {
      const date = column.dataset.date;
      const total = column.dataset.total;
      const prompt = column.dataset.prompt;
      const completion = column.dataset.completion;
      const requests = column.dataset.requests;

      tooltip.innerHTML = `
        <div class="tooltip-date">${date}</div>
        <div class="tooltip-row">
          <span class="tooltip-dot total"></span>
          <span>总计: <strong>${total}</strong></span>
        </div>
        <div class="tooltip-row">
          <span class="tooltip-dot prompt"></span>
          <span>Prompt: <strong>${prompt}</strong></span>
        </div>
        <div class="tooltip-row">
          <span class="tooltip-dot completion"></span>
          <span>Completion: <strong>${completion}</strong></span>
        </div>
        <div class="tooltip-row">
          <span class="tooltip-dot requests"></span>
          <span>请求数: <strong>${requests}</strong></span>
        </div>
      `;
      tooltip.style.display = 'flex';
    });

    column.addEventListener('mousemove', (e) => {
      tooltip.style.left = `${e.clientX}px`;
      tooltip.style.top = `${e.clientY - 12}px`;
      tooltip.style.transform = 'translate(-50%, -100%)';
    });

    column.addEventListener('mouseleave', () => {
      tooltip.style.display = 'none';
    });
  });
}

function renderTokenRankings() {
  if (!tokenUsageData) return;

  const modelRanking = tokenUsageData.model_ranking || [];
  const clientRanking = tokenUsageData.client_ranking || [];
  const providerRanking = tokenUsageData.provider_ranking || [];

  renderRankingList('model-ranking-list', modelRanking, 'model');
  renderRankingList('client-ranking-list', clientRanking, 'client');
  renderRankingList('provider-ranking-list', providerRanking, 'provider');
}

function renderRankingList(elementId, items, nameKey) {
  const container = document.getElementById(elementId);
  if (!container) return;

  if (!items || items.length === 0) {
    container.innerHTML = '<div class="metric-empty">暂无排行数据</div>';
    return;
  }

  // Get max total tokens in this category to calculate widths
  const maxTokens = Math.max(...items.map(item => Number(item.total_tokens || 0)));
  const scaleMax = maxTokens > 0 ? maxTokens : 1;

  // Render top 10 items
  const topItems = items.slice(0, 10);
  let html = '';

  topItems.forEach((item, index) => {
    const name = item[nameKey] || 'unknown';
    const total = Number(item.total_tokens || 0);
    const prompt = Number(item.prompt_tokens || 0);
    const completion = Number(item.completion_tokens || 0);
    const count = Number(item.request_count || 0);

    const widthPercent = (total / scaleMax) * 100;
    
    // Create detailed title attribute
    const detailTitle = `Prompt: ${formatTokenCount(prompt)} | Completion: ${formatTokenCount(completion)} | 请求数: ${count.toLocaleString()}`;

    // Check for actual_model_distribution (only relevant for model ranking)
    const dist = (nameKey === 'model') ? (item.actual_model_distribution || null) : null;
    const hasDist = dist && Object.keys(dist).length > 0;

    html += `
      <div class="ranking-item${hasDist ? ' has-distribution' : ''}" title="${detailTitle}">
        <div class="ranking-info">
          <span class="ranking-name-wrap">
            <span class="ranking-badge">${index + 1}</span>
            <span class="ranking-name">${escapeHtml(name)}</span>
            ${hasDist ? `<span class="ranking-expand-btn" onclick="toggleActualModelDist(event)">▶ <span class="dist-badge">${Object.keys(dist).length}</span></span>` : ''}
          </span>
          <span class="ranking-value">${formatTokenCount(total)}</span>
        </div>
        <div class="ranking-bar-bg">
          <div class="ranking-bar-fill" style="width: ${widthPercent}%;"></div>
        </div>
        ${hasDist ? buildActualModelDistHtml(dist, total) : ''}
      </div>
    `;
  });

  container.innerHTML = html;
}

function buildActualModelDistHtml(distribution, parentTotal) {
  // Sort sub-entries by total_tokens descending
  const entries = Object.entries(distribution).sort(
    (a, b) => Number(b[1].total_tokens || 0) - Number(a[1].total_tokens || 0)
  );

  let html = '<div class="actual-model-dist" style="display: none;">';
  entries.forEach(([actualModel, data]) => {
    const subTotal = Number(data.total_tokens || 0);
    const subPrompt = Number(data.prompt_tokens || 0);
    const subCompletion = Number(data.completion_tokens || 0);
    const subCount = Number(data.request_count || 0);
    const subPct = parentTotal > 0 ? ((subTotal / parentTotal) * 100).toFixed(1) : 0;
    const barPct = parentTotal > 0 ? (subTotal / parentTotal) * 100 : 0;
    const subTitle = `Prompt: ${formatTokenCount(subPrompt)} | Completion: ${formatTokenCount(subCompletion)} | 请求数: ${subCount.toLocaleString()}`;

    html += `
      <div class="dist-item" title="${subTitle}">
        <div class="dist-info">
          <span class="dist-indent"></span>
          <span class="dist-name">${escapeHtml(actualModel)}</span>
          <span class="dist-value">${formatTokenCount(subTotal)} <span class="dist-pct">(${subPct}%)</span></span>
        </div>
        <div class="dist-bar-bg">
          <div class="dist-bar-fill" style="width: ${barPct}%;"></div>
        </div>
      </div>
    `;
  });
  html += '</div>';
  return html;
}

function toggleActualModelDist(event) {
  event.stopPropagation();
  const btn = event.currentTarget;
  const rankingItem = btn.closest('.ranking-item');
  const distContainer = rankingItem ? rankingItem.querySelector('.actual-model-dist') : null;
  if (!distContainer) return;

  const isHidden = distContainer.style.display === 'none' || !distContainer.style.display;
  distContainer.style.display = isHidden ? 'block' : 'none';
  // Toggle arrow: ▶ collapsed, ▼ expanded
  const arrow = btn.childNodes[0];
  if (arrow && arrow.nodeType === 3) {
    arrow.textContent = isHidden ? '▼' : '▶';
  }
}
