let authHealthPanelLoaded = false;

function formatAuthHealthTs(ts) {
  const res = formatDashboardTs(ts);
  if (!res || res === '-') return '-';
  if (typeof res === 'object') {
    return `${res.day} ${res.time}`;
  }
  return res;
}

function showTextPopover(element, event) {
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

function authHealthRowHtml(item) {
  const stateClass = item.state === 'healthy' ? 'ok' : item.state === 'degraded' ? 'warn' : 'off';
  const reasonText = item.recent_failure_reason || '';
  return `
    <tr>
      <td class="ellipsis-cell file-col" title="${escapeHtml(item.name || '')}" onclick="showTextPopover(this, event)">${escapeHtml(item.name || '-')}</td>
      <td>${escapeHtml(item.provider || '-')}</td>
      <td class="ellipsis-cell email-col" title="${escapeHtml(item.email || '')}" onclick="showTextPopover(this, event)">${escapeHtml(item.email || '-')}</td>
      <td><span class="pill ${stateClass}">${escapeHtml(item.state || 'unknown')}</span></td>
      <td>${item.available_models || 0}</td>
      <td>${item.failed_models || 0}</td>
      <td>${item.request_count || 0}</td>
      <td>${item.total_tokens || 0}</td>
      <td class="ellipsis-cell reason-col" title="${escapeHtml(reasonText)}" onclick="showTextPopover(this, event)">${escapeHtml(reasonText || '-')}</td>
      <td>${escapeHtml(formatAuthHealthTs(item.recent_failure_at))}</td>
    </tr>
  `;
}

let authHealthResizerInitialized = false;

function applyAuthHealthColumnWidths() {
  const headers = document.querySelectorAll('#section-auth-health .metric-table thead th');
  if (!headers.length) return;

  const defaultWidths = {
    0: '18%',  // 认证文件
    1: '10%',  // Provider
    2: '15%',  // 邮箱
    3: '8%',   // 状态
    4: '9%',   // 可用模型
    5: '9%',   // 失败模型
    6: '8%',   // 请求数
    7: '9%',   // 总 Token
    8: '24%',  // 最近失败
    9: '16%'   // 失败时间
  };

  headers.forEach((th, index) => {
    const saved = localStorage.getItem(`auth-health-col-${index + 1}-width`);
    if (saved) {
      th.style.width = `${saved}px`;
    } else {
      th.style.width = defaultWidths[index];
    }
  });
}

function initAuthHealthResizer() {
  applyAuthHealthColumnWidths();

  if (authHealthResizerInitialized) return;

  const headers = document.querySelectorAll('#section-auth-health .metric-table thead th');
  if (!headers.length) return;

  headers.forEach((th, index) => {
    // 在表格头部的右侧边缘（辐条位置）放置手柄。最后一列右边不需要手柄。
    if (index === headers.length - 1) return;

    if (th.querySelector('.resize-handle')) return;

    const handle = document.createElement('div');
    handle.className = 'resize-handle';
    th.appendChild(handle);

    handle.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();

      const nextTh = headers[index + 1];
      if (!nextTh) return;

      const startX = e.clientX;
      const startWidthTh = th.offsetWidth;
      const startWidthNextTh = nextTh.offsetWidth;

      handle.classList.add('is-dragging');
      th.classList.add('is-resizing');

      const onPointerMove = (moveEvent) => {
        const dx = moveEvent.clientX - startX;
        // 限制最小宽度为 50px 防止某列完全消失
        if (startWidthTh + dx > 50 && startWidthNextTh - dx > 50) {
          const newWidthTh = Math.round(startWidthTh + dx);
          const newWidthNextTh = Math.round(startWidthNextTh - dx);

          th.style.width = `${newWidthTh}px`;
          nextTh.style.width = `${newWidthNextTh}px`;

          localStorage.setItem(`auth-health-col-${index + 1}-width`, String(newWidthTh));
          localStorage.setItem(`auth-health-col-${index + 2}-width`, String(newWidthNextTh));
        }
      };

      const onPointerUp = () => {
        handle.classList.remove('is-dragging');
        th.classList.remove('is-resizing');
        document.removeEventListener('pointermove', onPointerMove);
        document.removeEventListener('pointerup', onPointerUp);
      };

      document.addEventListener('pointermove', onPointerMove);
      document.addEventListener('pointerup', onPointerUp);
    });
  });

  authHealthResizerInitialized = true;
}

async function loadAuthHealthPanel(force = false) {
  initAuthHealthResizer();
  if (authHealthPanelLoaded && !force) return;
  const body = document.getElementById('auth-health-body');
  const meta = document.getElementById('auth-health-meta');
  const limit = force ? 100 : 20;
  if (body) body.innerHTML = '<tr><td colspan="10">loading...</td></tr>';
  try {
    const data = await api(`/api/auth-health?limit=${limit}`);
    const items = Array.isArray(data.items) ? data.items : [];
    if (meta) meta.textContent = force ? `${items.length} 个认证项` : `先加载 ${items.length} 个认证项`;
    if (body) {
      body.innerHTML = items.length
        ? items.map(authHealthRowHtml).join('')
        : '<tr><td colspan="10">暂无认证健康数据</td></tr>';
    }
    initAuthHealthResizer();
    authHealthPanelLoaded = true;
  } catch (error) {
    if (body) body.innerHTML = `<tr><td colspan="10">${error.message || 'load failed'}</td></tr>`;
  }
}
