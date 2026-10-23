// MarketLens Application State & Controllers

const state = {
  competitors: [],
  selectedCompetitorId: null,
  selectedCompetitorData: null,
  systemStatus: null,
  activeTab: 'articles',
  isScanning: false,
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  loadSystemStatus();
  loadCompetitors();
  setupEventListeners();
});

// --- API Calls ---
async function loadSystemStatus() {
  try {
    const res = await fetch('/api/status');
    state.systemStatus = await res.json();
    renderSystemStatus();
  } catch (err) {
    console.error('Failed to load system status:', err);
  }
}

async function loadCompetitors() {
  try {
    const res = await fetch('/api/competitors');
    state.competitors = await res.json();
    renderSidebarList();

    if (state.competitors.length > 0) {
      if (!state.selectedCompetitorId || !state.competitors.find(c => c.id === state.selectedCompetitorId)) {
        selectCompetitor(state.competitors[0].id);
      } else {
        selectCompetitor(state.selectedCompetitorId);
      }
    } else {
      state.selectedCompetitorId = null;
      state.selectedCompetitorData = null;
      renderMainDashboard();
    }
  } catch (err) {
    console.error('Failed to load competitors:', err);
  }
}

async function selectCompetitor(id) {
  state.selectedCompetitorId = id;
  renderSidebarList();
  try {
    const res = await fetch(`/api/competitors/${id}`);
    if (res.ok) {
      state.selectedCompetitorData = await res.json();
      renderMainDashboard();
    }
  } catch (err) {
    console.error('Failed to fetch competitor details:', err);
  }
}

async function handleAddCompetitor(domain) {
  if (!domain.trim()) return;
  const btn = document.getElementById('btn-add-comp');
  btn.disabled = true;
  btn.innerText = 'Indexing...';

  startLiveScanStream(domain.trim(), false);

  try {
    const res = await fetch('/api/competitors', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain: domain.trim(), auto_scan: true }),
    });
    const data = await res.json();
    document.getElementById('input-domain').value = '';
    await loadCompetitors();
    if (data.competitor) {
      await selectCompetitor(data.competitor.id);
    }
    stopLiveScanStream(true, data.initial_scan || { ai_summary: 'Initial baseline indexed.' });
  } catch (err) {
    stopLiveScanStream(false, { error_message: err.message });
    alert('Failed to add competitor: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerText = 'Add & Index';
  }
}

let scanTimerInterval = null;
let scanStartTime = null;
let scanStepTimeouts = [];

async function triggerScan(isReindexing = false) {
  if (!state.selectedCompetitorId || state.isScanning) return;
  state.isScanning = true;

  const comp = state.competitors.find(c => c.id === state.selectedCompetitorId);
  const domainName = comp ? comp.normalized_domain : 'competitor';

  startLiveScanStream(domainName, isReindexing);

  try {
    const res = await fetch(`/api/competitors/${state.selectedCompetitorId}/scan`, {
      method: 'POST',
    });
    const scanResult = await res.json();
    await selectCompetitor(state.selectedCompetitorId);
    await loadCompetitors();

    stopLiveScanStream(true, scanResult);
  } catch (err) {
    stopLiveScanStream(false, { error_message: err.message });
  } finally {
    state.isScanning = false;
  }
}

async function resetBaseline() {
  if (!state.selectedCompetitorId) return;
  if (!confirm('Re-index this competitor? This will clear the previous index and freshly crawl all posts with live streaming feedback.')) return;

  try {
    await fetch(`/api/competitors/${state.selectedCompetitorId}/demo/reset-baseline`, {
      method: 'POST',
    });
    // Immediately trigger live scan so the user sees real-time crawling and articles repopulate
    await triggerScan(true);
  } catch (err) {
    alert('Re-index failed: ' + err.message);
  }
}

async function deleteCompetitor() {
  if (!state.selectedCompetitorId) return;
  if (!confirm('Delete this competitor and all indexed records?')) return;

  try {
    await fetch(`/api/competitors/${state.selectedCompetitorId}`, { method: 'DELETE' });
    await loadCompetitors();
  } catch (err) {
    alert('Delete error: ' + err.message);
  }
}

async function sendAlert(channel) {
  const compDomain = state.selectedCompetitorData?.competitor?.normalized_domain || 'competitor';
  try {
    const res = await fetch('/api/alerts/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel,
        competitor_id: state.selectedCompetitorId,
      }),
    });
    const data = await res.json();
    if (data.success) {
      alert(`Alert for ${compDomain} dispatched successfully to ${channel.toUpperCase()}!`);
    } else {
      alert(`Could not send alert to ${channel.toUpperCase()}: ${data.message || 'Check channel settings'}`);
    }
  } catch (err) {
    alert('Alert dispatch failed: ' + err.message);
  }
}
window.testAlert = sendAlert;

// --- Renderers ---
function formatEnrichmentBadge(status) {
  if (!status) return `<span class="badge badge-neutral"><span class="status-dot"></span> Indexed</span>`;
  const s = String(status).toUpperCase();
  if (s.startsWith('SUCCESS') || s.includes('ENRICHED')) {
    return `<span class="badge badge-success" title="${status}"><span class="status-dot"></span> Enriched</span>`;
  }
  if (s.includes('PENDING')) {
    return `<span class="badge badge-warning"><span class="status-dot"></span> Pending</span>`;
  }
  if (s.includes('FAIL') || s.includes('ERROR')) {
    return `<span class="badge badge-danger" title="${status}"><span class="status-dot"></span> Failed</span>`;
  }
  return `<span class="badge badge-neutral">${status}</span>`;
}

function renderSystemStatus() {
  const el = document.getElementById('system-status-pills');
  if (!el || !state.systemStatus) return;

  const s = state.systemStatus;
  const aiIsActive = s.groq_ai.configured;
  const slackIsActive = s.notifications.slack.configured;
  const emailIsActive = s.notifications.email.configured;

  el.innerHTML = `
    <div class="integrations-card">
      <div style="font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--gray-500); margin-bottom: 2px;">
        Active Integrations
      </div>
      <div class="integration-row">
        <span class="integration-name">
          <span class="integration-dot ${aiIsActive ? '' : 'inactive'}"></span>
          AI Intelligence
        </span>
        <span class="integration-value">${aiIsActive ? 'Operational' : 'Offline'}</span>
      </div>
      <div class="integration-row">
        <span class="integration-name">
          <span class="integration-dot ${slackIsActive ? '' : 'inactive'}"></span>
          Slack Alerts
        </span>
        <span class="integration-value">${slackIsActive ? 'Connected' : 'Offline'}</span>
      </div>
      <div class="integration-row">
        <span class="integration-name">
          <span class="integration-dot ${emailIsActive ? '' : 'inactive'}"></span>
          Email Alerts
        </span>
        <span class="integration-value">${emailIsActive ? 'Ready' : 'Offline'}</span>
      </div>
    </div>
  `;
}

function renderSidebarList() {
  const listEl = document.getElementById('competitors-list');
  if (!listEl) return;

  if (state.competitors.length === 0) {
    listEl.innerHTML = `<div style="padding: 16px; color: var(--gray-500); font-size: 13px; text-align: center;">No competitors tracked yet. Add one above!</div>`;
    return;
  }

  listEl.innerHTML = state.competitors.map(c => {
    const activeCls = c.id === state.selectedCompetitorId ? 'active' : '';
    let statusBadge = '<span class="badge badge-success" style="font-size: 10px; height: 18px;"><span class="status-dot"></span> Active</span>';
    if (c.status === 'NO_BLOG') {
      statusBadge = '<span class="badge badge-warning" style="font-size: 10px; height: 18px;">No Blog</span>';
    } else if (c.status === 'BLOCKED') {
      statusBadge = '<span class="badge badge-danger" style="font-size: 10px; height: 18px;">Shielded 403</span>';
    }

    return `
      <div class="sidebar-item ${activeCls}" onclick="selectCompetitor(${c.id})">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <strong style="font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${c.normalized_domain}</strong>
          ${statusBadge}
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--gray-500); font-family: var(--mono);">
          <span>${c.articles_count} posts</span>
          <span>${c.last_scan_at ? new Date(c.last_scan_at).toLocaleDateString() : 'Never'}</span>
        </div>
      </div>
    `;
  }).join('');
}

function renderMainDashboard() {
  const container = document.getElementById('main-content-view');
  if (!container) return;

  if (!state.selectedCompetitorData) {
    container.innerHTML = `
      <div style="text-align: center; padding: 80px 20px;">
        <h2 style="font-family: var(--serif); font-size: 26px; color: var(--slate);">Welcome to MarketLens</h2>
        <p style="color: var(--gray-500); max-width: 480px; margin: 12px auto 24px;">Enter a competitor domain on the left (e.g. <code>buffer.com</code>, <code>clickup.com</code>, or <code>zapier.com</code>) to crawl their blog, detect new posts, and track pricing changes.</p>
      </div>
    `;
    return;
  }

  const { competitor, articles, scans, pricing_changes } = state.selectedCompetitorData;

  container.innerHTML = `
    <!-- Top Action Bar -->
    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; flex-wrap: wrap; gap: 16px;">
      <div>
        <div class="label">Competitor Profile</div>
        <h1 style="margin: 4px 0 6px;">${competitor.normalized_domain}</h1>
        <div style="display: flex; gap: 8px; align-items: center; font-size: 13px; color: var(--gray-500);">
          <span>Blog: <a href="${competitor.blog_url || '#'}" target="_blank" style="color: var(--clay);">${competitor.blog_url || 'Detecting...'}</a></span>
          <span>&bull;</span>
          <span>Pricing: <a href="${competitor.pricing_url || '#'}" target="_blank" style="color: var(--clay);">${competitor.pricing_url || 'Detecting...'}</a></span>
        </div>
      </div>

      <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
        <button class="btn btn-primary" onclick="triggerScan()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
          Scan Now
        </button>
        <button class="btn btn-secondary" onclick="sendAlert('email')" title="Send live competitor alert to Email">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
          Send Email
        </button>
        <button class="btn btn-secondary" onclick="sendAlert('slack')" title="Send live competitor alert to Slack">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 10c-.83 0-1.5-.67-1.5-1.5v-5c0-.83.67-1.5 1.5-1.5s1.5.67 1.5 1.5v5c0 .83-.67 1.5-1.5 1.5z"/><path d="M20.5 10H19V8.5c0-.83.67-1.5 1.5-1.5s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/><path d="M9.5 14c.83 0 1.5.67 1.5 1.5v5c0 .83-.67 1.5-1.5 1.5S8 21.33 8 20.5v-5c0-.83.67-1.5 1.5-1.5z"/><path d="M3.5 14H5v1.5c0 .83-.67 1.5-1.5 1.5S2 16.33 2 15.5 2.67 14 3.5 14z"/><path d="M14 14.5c0-.83.67-1.5 1.5-1.5h5c.83 0 1.5.67 1.5 1.5s-.67 1.5-1.5 1.5h-5c-.83 0-1.5-.67-1.5-1.5z"/></svg>
          Send Slack
        </button>
        <button class="btn btn-secondary" onclick="resetBaseline()" title="Reset historical baseline and re-index">Re-index</button>
        <button class="btn btn-ghost" onclick="deleteCompetitor()" style="color: var(--danger);">Delete</button>
      </div>
    </div>

    <!-- Scanning / Alert Status Drawer -->
    <div id="scanning-banner-container"></div>

    <!-- Stats Overview Panel -->
    <div class="panel" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); border-radius: var(--radius-panel);">
      <div style="padding: 18px 24px; border-right: 1px solid var(--gray-100);">
        <div class="label">Total Articles</div>
        <div style="font-family: var(--serif); font-size: 28px; margin-top: 4px;">${articles.length}</div>
      </div>
      <div style="padding: 18px 24px; border-right: 1px solid var(--gray-100);">
        <div class="label">Last Crawl Date</div>
        <div style="font-family: var(--mono); font-size: 15px; margin-top: 8px; color: var(--gray-700);">
          ${competitor.last_scan_at ? new Date(competitor.last_scan_at).toLocaleString() : 'Never'}
        </div>
      </div>
      <div style="padding: 18px 24px; border-right: 1px solid var(--gray-100);">
        <div class="label">Monitoring Status</div>
        <div style="margin-top: 6px;">
          ${competitor.status === 'ACTIVE' 
            ? '<span class="badge badge-success"><span class="status-dot"></span> Active & Monitoring</span>'
            : competitor.status === 'NO_BLOG'
            ? '<span class="badge badge-warning">No Blog Detected</span>'
            : '<span class="badge badge-danger">Shielded (403 Anti-Bot)</span>'}
        </div>
      </div>
      <div style="padding: 18px 24px;">
        <div class="label">Pricing Changes</div>
        <div style="font-family: var(--serif); font-size: 28px; margin-top: 4px;">${pricing_changes.length}</div>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="tab-bar">
      <button class="tab-btn ${state.activeTab === 'articles' ? 'active' : ''}" onclick="switchTab('articles')">
        <span>Indexed Articles</span>
        <span class="tab-pill">${articles.length}</span>
      </button>
      <button class="tab-btn ${state.activeTab === 'scans' ? 'active' : ''}" onclick="switchTab('scans')">
        <span>Scan History</span>
        <span class="tab-pill">${scans.length}</span>
      </button>
      <button class="tab-btn ${state.activeTab === 'pricing' ? 'active' : ''}" onclick="switchTab('pricing')">
        <span>Pricing Tracker</span>
        <span class="tab-pill">${pricing_changes.length}</span>
      </button>
    </div>

    <!-- Tab Content -->
    ${state.activeTab === 'articles' ? renderArticlesTable(articles) : ''}
    ${state.activeTab === 'scans' ? renderScansTable(scans) : ''}
    ${state.activeTab === 'pricing' ? renderPricingPanel(pricing_changes, competitor) : ''}
  `;
}

function switchTab(tab) {
  state.activeTab = tab;
  renderMainDashboard();
}

function renderArticlesTable(articles) {
  if (articles.length === 0) {
    return `
      <div class="panel" style="padding: 40px; text-align: center; color: var(--gray-500);">
        No articles detected yet. Click <strong>Scan Now</strong> to run the crawler.
      </div>
    `;
  }

  return `
    <div class="panel">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th style="width: 44%;">Article Title & URL</th>
              <th>Target Keyword</th>
              <th>Search Volume</th>
              <th>Intent</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${articles.map(a => {
              const volFormatted = a.search_volume ? `${a.search_volume.toLocaleString()}/mo` : 'N/A';
              const pub = a.published_at ? new Date(a.published_at).toLocaleDateString() : '';

              return `
                <tr>
                  <td>
                    <div style="font-weight: 500; margin-bottom: 3px;">
                      <a href="${a.normalized_url}" target="_blank" style="color: var(--slate); text-decoration: none;">${a.title}</a>
                    </div>
                    <div style="font-family: var(--mono); font-size: 11px; color: var(--gray-500); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 450px;">
                      ${pub ? `<span>${pub} &bull; </span>` : ''}
                      <span>${a.normalized_url}</span>
                    </div>
                  </td>
                  <td>
                    <code style="font-family: var(--mono); background: var(--gray-100); padding: 2px 6px; border-radius: 4px; font-size: 12px; color: var(--slate);">
                      ${a.target_keyword || 'N/A'}
                    </code>
                  </td>
                  <td style="font-family: var(--mono); font-size: 13px;">
                    ${volFormatted}
                  </td>
                  <td>
                    <span class="badge badge-${a.search_intent === 'Commercial' ? 'warning' : a.search_intent === 'Transactional' ? 'accent' : 'neutral'}">
                      ${a.search_intent || 'Informational'}
                    </span>
                  </td>
                  <td>
                    ${formatEnrichmentBadge(a.enrichment_status)}
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderScansTable(scans) {
  if (scans.length === 0) {
    return `<div class="panel" style="padding: 40px; text-align: center; color: var(--gray-500);">No scans executed yet.</div>`;
  }

  return `
    <div class="panel">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Scan Time</th>
              <th>Type</th>
              <th>Status</th>
              <th>Articles Found</th>
              <th>New Posts Flagged</th>
              <th>AI Strategic Summary</th>
            </tr>
          </thead>
          <tbody>
            ${scans.map(s => `
              <tr>
                <td style="font-family: var(--mono); font-size: 12px;">${new Date(s.started_at).toLocaleString()}</td>
                <td>
                  <span class="badge badge-${s.is_baseline ? 'neutral' : 'accent'}">
                    ${s.is_baseline ? 'Baseline' : 'Delta Scan'}
                  </span>
                </td>
                <td>
                  <span class="badge badge-${s.status === 'COMPLETED' ? 'success' : s.status === 'NO_BLOG' ? 'warning' : 'danger'}">
                    <span class="status-dot"></span> ${s.status === 'COMPLETED' ? 'Completed' : s.status}
                  </span>
                </td>
                <td style="font-family: var(--mono);">${s.total_articles_found}</td>
                <td style="font-family: var(--mono); font-weight: 600; color: ${s.new_articles_found > 0 ? 'var(--clay)' : 'inherit'};">
                  ${s.new_articles_found}
                </td>
                <td style="font-size: 13px; color: var(--gray-700); max-width: 340px;">
                  ${s.ai_summary 
                    ? `<div style="font-size: 12px; color: var(--slate); background: var(--ivory); padding: 8px 12px; border-radius: 4px; border-left: 2px solid var(--clay); line-height: 1.45;">${s.ai_summary}</div>`
                    : `<span style="color: var(--gray-500); font-family: var(--mono); font-size: 12px;">${s.error_message || '—'}</span>`
                  }
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderPricingPanel(pricingChanges, competitor) {
  const targetUrl = competitor.pricing_url || 'https://' + competitor.normalized_domain + '/pricing';

  return `
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 style="margin: 0 0 4px; font-size: 16px;">Pricing & Packaging Intelligence</h3>
          <div style="font-size: 13px; color: var(--gray-500);">
            Monitored Target: <a href="${targetUrl}" target="_blank" style="color: var(--clay); text-decoration: none;">${targetUrl}</a>
          </div>
        </div>
        <div>
          <span class="badge badge-neutral" style="font-size: 11px;">
            SHA-256 DOM Integrity Lock
          </span>
        </div>
      </div>

      <div style="padding: 24px;">
        ${pricingChanges.length === 0 ? `
          <div style="text-align: center; padding: 40px 20px;">
            <div style="width: 48px; height: 48px; border-radius: 50%; background: var(--gray-100); color: var(--gray-700); display: inline-flex; align-items: center; justify-content: center; margin-bottom: 12px;">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </div>
            <h4 style="margin: 0 0 6px; font-size: 15px;">Baseline Pricing Snapshot Active</h4>
            <p style="color: var(--gray-500); font-size: 13px; max-width: 440px; margin: 0 auto; line-height: 1.5;">
              MarketLens indexed the initial pricing table DOM and hashed plan tiers. On future automated or manual scans, any detected change will be summarized by AI and alerted in real-time.
            </p>
          </div>
        ` : `
          <div class="pricing-timeline">
            ${pricingChanges.map(pc => `
              <div class="pricing-event">
                <div class="pricing-event-header">
                  <span class="pricing-event-meta">
                    Detected: ${new Date(pc.detected_at).toLocaleString()}
                  </span>
                  <span class="badge badge-warning" style="font-size: 11px;">
                    <span class="status-dot"></span> Plan Delta Detected
                  </span>
                </div>
                <div class="pricing-change-summary">
                  ${pc.summary}
                </div>
              </div>
            `).join('')}
          </div>
        `}
      </div>
    </div>
  `;
}

function startLiveScanStream(domain, isReindexing) {
  const container = document.getElementById('scanning-banner-container');
  if (!container) return;

  if (scanTimerInterval) clearInterval(scanTimerInterval);
  scanStepTimeouts.forEach(t => clearTimeout(t));
  scanStepTimeouts = [];

  scanStartTime = Date.now();
  const titlePrefix = isReindexing ? 'Re-indexing' : 'Crawling & Monitoring';

  container.innerHTML = `
    <div class="scanner-box">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span class="badge badge-accent">Live Crawler Stream</span>
          <strong style="font-size: 14px; color: var(--slate);">${titlePrefix}: ${domain}</strong>
        </div>
        <div style="display: flex; align-items: center; gap: 12px;">
          <div style="font-family: var(--mono); font-size: 12px; color: var(--gray-700);">
            Elapsed: <span id="scan-timer-display" style="font-weight: 600; color: var(--clay);">00:00.0s</span>
          </div>
        </div>
      </div>

      <div class="scanner-progress-bar">
        <div class="scanner-progress-fill"></div>
      </div>

      <div class="scanner-log" id="scanner-live-log">
        <div class="scanner-log-item active" id="step-0">
          <span style="color: var(--gray-500); font-size: 10px;">[00:00.0s]</span>
          <span>Handshake initialized with browser fingerprint (Chrome 122 / Windows)...</span>
        </div>
      </div>
    </div>
  `;

  scanTimerInterval = setInterval(() => {
    const elapsedMs = Date.now() - scanStartTime;
    const sec = (elapsedMs / 1000).toFixed(1);
    const timerEl = document.getElementById('scan-timer-display');
    if (timerEl) {
      timerEl.innerText = `00:${sec.padStart(4, '0')}s`;
    }
  }, 100);

  const steps = [
    { delay: 600, id: 'step-1', tag: 'TIER 1 FEEDS', text: 'Probing RSS & Atom endpoints (/blog/feed, /rss.xml, /feed)...' },
    { delay: 1400, id: 'step-2', tag: 'TIER 2 SITEMAP', text: 'Inspecting sitemap.xml and robots.txt Sitemap directives...' },
    { delay: 2200, id: 'step-3', tag: 'TIER 3 HTML', text: 'Parsing editorial DOM, OpenGraph tags, and JSON-LD schema...' },
    { delay: 3000, id: 'step-4', tag: 'PRICING', text: 'Snapshotting pricing tiers & calculating SHA-256 content hash...' },
    { delay: 3800, id: 'step-5', tag: 'GROQ AI', text: 'Extracting target SEO keywords & intent classification...' },
    { delay: 4600, id: 'step-6', tag: 'DELTA SYNC', text: 'Comparing with database & evaluating alert dispatch conditions...' },
  ];

  steps.forEach(s => {
    const timeout = setTimeout(() => {
      const logEl = document.getElementById('scanner-live-log');
      if (!logEl) return;
      const elapsedMs = Date.now() - scanStartTime;
      const sec = (elapsedMs / 1000).toFixed(1);

      logEl.querySelectorAll('.scanner-log-item').forEach(el => el.classList.remove('active'));

      const item = document.createElement('div');
      item.className = 'scanner-log-item active';
      item.id = s.id;
      item.innerHTML = `
        <span style="color: var(--gray-500); font-size: 10px;">[00:${sec.padStart(4, '0')}s]</span>
        <span style="color: var(--clay); font-weight: 600;">[${s.tag}]</span>
        <span>${s.text}</span>
      `;
      logEl.appendChild(item);
      logEl.scrollTop = logEl.scrollHeight;
    }, s.delay);
    scanStepTimeouts.push(timeout);
  });
}

function stopLiveScanStream(success, result) {
  if (scanTimerInterval) {
    clearInterval(scanTimerInterval);
    scanTimerInterval = null;
  }
  scanStepTimeouts.forEach(t => clearTimeout(t));
  scanStepTimeouts = [];

  const totalTime = ((Date.now() - (scanStartTime || Date.now())) / 1000).toFixed(1);
  const container = document.getElementById('scanning-banner-container');
  if (!container) return;

  const logEl = document.getElementById('scanner-live-log');
  if (logEl) {
    logEl.querySelectorAll('.scanner-log-item').forEach(el => el.classList.remove('active'));
    const finalItem = document.createElement('div');
    finalItem.className = 'scanner-log-item done';
    finalItem.innerHTML = `
      <span style="color: var(--olive); font-size: 10px;">[00:${totalTime.padStart(4, '0')}s]</span>
      <span style="color: var(--olive); font-weight: 600;">[FINISHED]</span>
      <strong>${result.ai_summary || result.error_message || 'Scan completed successfully.'}</strong>
    `;
    logEl.appendChild(finalItem);
    logEl.scrollTop = logEl.scrollHeight;
  }

  const fill = container.querySelector('.scanner-progress-fill');
  if (fill) {
    fill.style.animation = 'none';
    fill.style.width = '100%';
    fill.style.background = success ? 'var(--olive)' : 'var(--danger)';
  }

  const timerEl = document.getElementById('scan-timer-display');
  if (timerEl) {
    timerEl.innerHTML = `<span style="color: var(--olive); font-weight: 600;">Done in ${totalTime}s</span>`;
  }

  const header = container.querySelector('.scanner-box > div');
  if (header && !header.querySelector('.btn-dismiss')) {
    const dismissBtn = document.createElement('button');
    dismissBtn.className = 'btn btn-ghost btn-sm btn-dismiss';
    dismissBtn.innerText = 'Dismiss';
    dismissBtn.onclick = () => { container.innerHTML = ''; };
    header.appendChild(dismissBtn);
  }
}

// --- Event Listeners & Modals ---
function setupEventListeners() {
  document.getElementById('form-add-comp').addEventListener('submit', (e) => {
    e.preventDefault();
    const domain = document.getElementById('input-domain').value;
    handleAddCompetitor(domain);
  });
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.style.display = 'flex';
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.style.display = 'none';
}
