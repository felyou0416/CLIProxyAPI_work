let clientsPanelLoaded = false;

function formatClientTs(ts) {
  const res = formatDashboardTs(ts);
  if (!res || res === '-') return '-';
  if (typeof res === 'object') {
    return `${res.day} ${res.time}`;
  }
  return res;
}

function showClientTextPopover(element, event) {
  if (!element || !event) return;
  event.stopPropagation();
  const fullText = element.getAttribute('title') || element.textContent;
  if (!fullText || fullText === '-') return;

  // Remove any existing popovers first
  document.querySelectorAll('.text-popover').forEach(el => el.remove());

  // Create popover element
  const popover = document.createElement('div');
  popover.className = 'text-popover';
  popover.style.position = 'absolute';
  popover.style.background = 'color-mix(in srgb, var(--panel) 98%, white)';
  popover.style.border = '1px solid var(--border)';
  popover.style.borderRadius = '8px';
  popover.style.padding = '10px 12px';
  popover.style.boxShadow = '0 10px 25px rgba(15, 23, 42, 0.12)';
  popover.style.zIndex = '1000';
  popover.style.maxWidth = '320px';
  popover.style.maxHeight = '200px';
  popover.style.overflowY = 'auto';
  popover.style.fontSize = '11px';
  popover.style.color = 'var(--text)';
  popover.style.wordBreak = 'break-all';
  popover.style.lineHeight = '1.4';

  // Add the text
  popover.textContent = fullText;

  // Append to body to compute correct layout
  document.body.appendChild(popover);

  // Position popover relative to the clicked element
  const rect = element.getBoundingClientRect();
  const popoverWidth = popover.offsetWidth;
  const popoverHeight = popover.offsetHeight;

  // Determine horizontal alignment
  let left = rect.left + window.scrollX;
  if (left + popoverWidth > window.innerWidth - 16) {
    left = window.innerWidth - popoverWidth - 16;
  }
  if (left < 16) left = 16;

  // Determine vertical alignment
  let top = rect.bottom + window.scrollY + 6;
  if (top + popoverHeight > window.innerHeight + window.scrollY - 16) {
    top = rect.top + window.scrollY - popoverHeight - 6;
  }

  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;

  // Add animation starting state
  popover.style.transform = 'translateY(-4px)';
  popover.style.opacity = '0';
  popover.style.transition = 'all 0.12s cubic-bezier(0.4, 0, 0.2, 1)';
  
  // Force reflow
  popover.offsetHeight;

  popover.style.transform = 'translateY(0)';
  popover.style.opacity = '1';

  // Dismiss on clicking anywhere else
  const dismiss = () => {
    popover.style.transform = 'translateY(-4px)';
    popover.style.opacity = '0';
    setTimeout(() => popover.remove(), 120);
    document.removeEventListener('click', dismiss);
  };
  
  popover.addEventListener('click', e => e.stopPropagation());

  setTimeout(() => {
    document.addEventListener('click', dismiss);
  }, 10);
}

function clientRowHtml(item) {
  const successRate = Number(item.success_rate || 0);
  return `
    <tr>
      <td><code>${escapeHtml(item.ip || '-')}</code></td>
      <td>${item.total_requests || 0}</td>
      <td>${Math.round(successRate * 100)}%</td>
      <td>${item.count_4xx || 0}</td>
      <td>${item.count_5xx || 0}</td>
      <td class="ellipsis-cell model-col" title="${escapeHtml(item.top_model || '')}" onclick="showClientTextPopover(this, event)"><code>${escapeHtml(item.top_model || '-')}</code></td>
      <td class="ellipsis-cell path-col" title="${escapeHtml(item.top_path || '')}" onclick="showClientTextPopover(this, event)"><code>${escapeHtml(item.top_path || '-')}</code></td>
      <td>${item.total_tokens || 0}</td>
      <td>${item.avg_latency_ms != null ? `${item.avg_latency_ms} ms` : '-'}</td>
      <td>${escapeHtml(formatClientTs(item.last_seen))}</td>
    </tr>
  `;
}

async function loadClientsPanel(force = false) {
  if (clientsPanelLoaded && !force) return;
  const body = document.getElementById('request-clients-body');
  const meta = document.getElementById('request-clients-meta');
  const limit = force ? 100 : 20;
  if (body) body.innerHTML = '<tr><td colspan="10">loading...</td></tr>';
  try {
    const data = await api(`/api/request-clients?limit=${limit}`);
    const items = Array.isArray(data.items) ? data.items : [];
    if (meta) meta.textContent = force ? `${items.length} 个客户端` : `先加载 ${items.length} 个客户端`;
    if (body) {
      body.innerHTML = items.length
        ? items.map(clientRowHtml).join('')
        : '<tr><td colspan="10">暂无客户端统计</td></tr>';
    }
    clientsPanelLoaded = true;
  } catch (error) {
    if (body) body.innerHTML = `<tr><td colspan="10">${error.message || 'load failed'}</td></tr>`;
  }
}
