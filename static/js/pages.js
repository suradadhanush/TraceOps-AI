/* pages.js — All page renderers, auth-aware, user-scoped */
const PAGES = {};

/* ════════════════════════════════════════════════════════════════════════════
   DASHBOARD — real user data
══════════════════════════════════════════════════════════════════════════════*/
PAGES.dashboard = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="flex gap-4" style="margin-bottom:20px;flex-wrap:wrap">
      <button class="btn btn-primary" onclick="openModal('modal-start-task')">⚡ Start Task</button>
      <button class="btn btn-secondary" onclick="openModal('modal-end-task')">✅ End Task</button>
      <button class="btn btn-secondary" onclick="openModal('modal-event')">📥 Log Event</button>
      <button class="btn btn-secondary" onclick="showPage('reports')">📋 Today's Report</button>
    </div>
    <div class="grid-4" style="margin-bottom:20px" id="dash-stats">
      ${[0,1,2,3].map(()=>`<div class="stat-card"><div class="skeleton" style="height:14px;width:60%;margin-bottom:8px"></div><div class="skeleton" style="height:32px;width:50%"></div></div>`).join('')}
    </div>
    <div class="grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="section-header"><div class="section-title">🎯 Active Tasks</div><button class="btn btn-sm btn-secondary" onclick="showPage('tasks')">View All →</button></div>
        <div id="dash-tasks"><div class="skeleton" style="height:180px"></div></div>
      </div>
      <div class="card">
        <div class="section-header"><div class="section-title">⚡ Recent Activity</div><button class="btn btn-sm btn-secondary" onclick="showPage('events')">View All →</button></div>
        <div id="dash-events"><div class="skeleton" style="height:180px"></div></div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card" id="dash-score-card"><div class="section-title" style="margin-bottom:16px">📊 Score Trend</div><div class="skeleton" style="height:140px"></div></div>
      <div class="card" id="dash-integrations-card"><div class="section-title" style="margin-bottom:16px">🔌 Connected Tools</div><div class="skeleton" style="height:140px"></div></div>
    </div>
  </div>`;

  try {
    const data = await api.getDashboard();
    const today = data.today || {};
    const user  = data.user  || CURRENT_USER || {};

    // Stats
    document.getElementById('dash-stats').innerHTML = `
      <div class="stat-card">
        <div class="stat-label">Active Tasks</div>
        <div class="stat-value" style="color:var(--green)">${today.active_tasks ?? 0}</div>
        <div class="stat-delta">Running now</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Completed Today</div>
        <div class="stat-value" style="color:var(--cyan)">${today.completed_tasks ?? 0}</div>
        <div class="stat-delta">Today</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Avg Score</div>
        <div class="stat-value" style="color:var(--purple-l)">${today.average_score ?? '—'}</div>
        <div class="stat-delta">Today</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Tools Connected</div>
        <div class="stat-value" style="color:var(--yellow)">${data.integrations_connected ?? 0}</div>
        <button class="btn btn-sm btn-secondary" style="margin-top:6px" onclick="showPage('integrations')">Manage →</button>
      </div>`;

    // Active tasks
    const tasks = data.active_tasks || [];
    document.getElementById('dash-tasks').innerHTML = tasks.length
      ? tasks.map(t=>`
        <div style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)">
          <div class="dot dot-green dot-pulse"></div>
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${t.goal}</div>
            <div style="font-size:11px;color:var(--text-muted)">L${t.target_level} · ${timeAgo(t.started_at)}</div>
          </div>
          <button class="btn btn-sm btn-success" onclick="prefillEndTask('${t.id}')">End</button>
        </div>`).join('')
      : `<div class="empty-state" style="padding:28px"><div class="empty-icon">✅</div><div class="empty-title">No active tasks</div><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="openModal('modal-start-task')">Start one</button></div>`;

    // Recent events
    const events = data.recent_events || [];
    document.getElementById('dash-events').innerHTML = events.length
      ? events.slice(0,6).map(e=>`
        <div style="display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid var(--border)">
          ${eventBadge(e.event_type)}
          <div style="flex:1;font-size:12px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            ${e.metadata?.message||e.metadata?.prompt_snippet||e.source||'Event'}
          </div>
          <span style="font-size:11px;color:var(--text-muted);flex-shrink:0">${timeAgo(e.timestamp)}</span>
        </div>`).join('')
      : `<div class="empty-state" style="padding:28px"><div class="empty-icon">⚡</div><div class="empty-title">No events yet</div></div>`;

    // Score trend
    const trend = data.score_trend || [];
    document.getElementById('dash-score-card').innerHTML = `
      <div class="section-title" style="margin-bottom:16px">📊 7-Day Score Trend</div>
      ${trend.length ? `
        <div style="display:flex;align-items:flex-end;gap:6px;height:80px;margin-bottom:8px">
          ${trend.map(d=>{const pct=d.avg_score/100;const {color}=scoreGrade(Math.round(d.avg_score));return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px">
            <div style="flex:1;width:100%;background:${color};border-radius:3px;opacity:.8;height:${Math.max(pct*100,8)}%" title="${d.avg_score}"></div>
            <div style="font-size:9px;color:var(--text-muted)">${d.date.slice(5)}</div>
          </div>`;}).join('')}
        </div>
        <div style="text-align:center;font-size:12px;color:var(--text-muted)">Avg: <strong style="color:var(--purple-l)">${Math.round(trend.reduce((a,b)=>a+b.avg_score,0)/trend.length)}</strong> over ${trend.length} days</div>
      ` : `<div class="empty-state" style="padding:20px"><div class="empty-icon">📊</div><div class="empty-title">No score data yet</div><div class="empty-desc">Complete a task to generate scores</div></div>`}
      <button class="btn btn-sm btn-secondary w-full" style="margin-top:12px" onclick="openModal('modal-manual-score')">🎯 Submit Manual Score</button>`;

    // Integrations
    const integrations = data.integrations || [];
    document.getElementById('dash-integrations-card').innerHTML = `
      <div class="section-title" style="margin-bottom:16px">🔌 Connected Tools</div>
      ${integrations.length ? integrations.map(i=>`
        <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">
          <div class="dot dot-green"></div>
          <span style="font-size:13px;font-weight:600;text-transform:capitalize">${i.provider}</span>
          ${i.username ? `<span style="font-size:12px;color:var(--text-muted)">@${i.username}</span>` : ''}
        </div>`).join('')
      : `<div style="color:var(--text-muted);font-size:13px;padding:8px 0">No tools connected yet.</div>`}
      <button class="btn btn-sm btn-primary w-full" style="margin-top:12px" onclick="showPage('integrations')">Manage Integrations →</button>`;

  } catch(e) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Error loading dashboard</div><div class="empty-desc">${e.message}</div></div>`;
  }
};


/* ════════════════════════════════════════════════════════════════════════════
   INTEGRATIONS — full catalog with real status
══════════════════════════════════════════════════════════════════════════════*/
PAGES.integrations = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div style="background:rgba(6,182,212,.06);border:1px solid rgba(6,182,212,.2);border-radius:var(--radius);padding:14px;margin-bottom:20px;font-size:13px;color:var(--text-secondary)">
      🔌 Connect your tools to enrich execution data. GitHub OAuth is available now. More integrations are in beta or coming soon.
    </div>
    <div id="catalog-content"><div class="skeleton" style="height:500px;border-radius:var(--radius-lg)"></div></div>
  </div>`;

  try {
    const data = await api.getCatalog();
    let html = '';
    for (const cat of data.categories) {
      html += `<div style="margin-bottom:32px">
        <div style="font-family:var(--font-display);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);margin-bottom:14px">${cat.name}</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px">
          ${cat.integrations.map(integ => renderIntegrationCard(integ)).join('')}
        </div>
      </div>`;
    }
    document.getElementById('catalog-content').innerHTML = html;
  } catch(e) {
    document.getElementById('catalog-content').innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">${e.message}</div></div>`;
  }
};

function renderIntegrationCard(integ) {
  const statusColors = {
    available:    'badge-green',
    beta:         'badge-yellow',
    coming_soon:  'badge-purple',
    unsupported:  'badge-red',
  };
  const statusLabels = {
    available:   'Available',
    beta:        'Beta',
    coming_soon: 'Coming Soon',
    unsupported: 'Unsupported',
  };
  const isClickable   = integ.status === 'available' || integ.status === 'beta';
  const isConnected   = integ.connected;
  const isComingSoon  = integ.status === 'coming_soon';

  const connectBtn = isConnected
    ? `<div style="display:flex;gap:8px">
        <div class="badge badge-green" style="padding:5px 10px">✓ Connected${integ.username?` · @${integ.username}`:''}</div>
        <button class="btn btn-sm btn-danger" onclick="disconnectIntegration('${integ.provider}')">Disconnect</button>
        ${integ.provider==='github'?`<button class="btn btn-sm btn-secondary" onclick="syncIntegration('${integ.provider}')">↻ Sync</button>`:''}
       </div>`
    : integ.status === 'available' && integ.auth_type === 'oauth'
      ? `<a href="${integ.oauth_url||'/auth/login/'+integ.provider}" class="btn btn-sm btn-primary">Connect via OAuth</a>`
      : integ.status === 'available' && integ.auth_type === 'api_key'
        ? `<button class="btn btn-sm btn-primary" onclick="openApiKeyModal('${integ.provider}','${integ.name}')">Connect API Key</button>`
        : integ.connect_url
          ? `<a href="${integ.connect_url}" class="btn btn-sm btn-secondary">Configure →</a>`
          : `<div class="badge ${statusColors[integ.status]||'badge-purple'}">${statusLabels[integ.status]||integ.status}</div>`;

  return `
    <div class="card" style="opacity:${isComingSoon?.6:1};transition:all .2s;${isClickable?'cursor:pointer':''}">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px">
        <div style="display:flex;align-items:center;gap:10px">
          <div style="font-size:24px">${integ.icon}</div>
          <div>
            <div style="font-family:var(--font-display);font-size:14px;font-weight:700">${integ.name}</div>
            ${isConnected?`<div style="font-size:11px;color:var(--green)">● Connected</div>`:''}
          </div>
        </div>
        <span class="badge ${statusColors[integ.status]||'badge-purple'}">${statusLabels[integ.status]||integ.status}</span>
      </div>
      <div style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;line-height:1.5">${integ.description}</div>
      ${integ.features?.length ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">${integ.features.map(f=>`<span style="font-size:10px;background:var(--bg-elevated);border:1px solid var(--border);border-radius:4px;padding:2px 6px;color:var(--text-muted)">${f}</span>`).join('')}</div>` : ''}
      ${connectBtn}
    </div>`;
}

async function disconnectIntegration(provider) {
  if (!confirm(`Disconnect ${provider}? Your existing data won't be deleted.`)) return;
  try {
    await api.disconnect(provider);
    toast(`${provider} disconnected`, 'success');
    showPage('integrations');
  } catch(e) { toast(e.message, 'error'); }
}

async function syncIntegration(provider) {
  toast(`Syncing ${provider}...`, 'info', 2000);
  try {
    const r = await api.syncIntegration(provider);
    toast(r.synced ? `Synced! ${r.commits_imported||0} commits imported` : `Sync failed: ${r.message}`, r.synced ? 'success' : 'error');
  } catch(e) { toast(e.message, 'error'); }
}

function openApiKeyModal(provider, name) {
  document.getElementById('modal-info')?.remove();
  const m = document.createElement('div');
  m.className = 'modal-overlay'; m.id = 'modal-info';
  m.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <div class="modal-title">🔑 Connect ${name}</div>
        <button class="modal-close" onclick="document.getElementById('modal-info').remove()">✕</button>
      </div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px">Enter your ${name} API key. It will be stored securely on the server.</p>
      <div class="form-group">
        <label class="form-label">${name} API Key *</label>
        <input class="form-input" id="apikey-input" type="password" placeholder="Paste your API key here"/>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="document.getElementById('modal-info').remove()">Cancel</button>
        <button class="btn btn-primary" id="btn-apikey" onclick="submitApiKey('${provider}')">Connect</button>
      </div>
    </div>`;
  m.addEventListener('click', e => { if(e.target===m) m.remove(); });
  document.body.appendChild(m);
}

async function submitApiKey(provider) {
  const key = document.getElementById('apikey-input')?.value.trim();
  if (!key) { toast('API key is required', 'error'); return; }
  const btn = document.getElementById('btn-apikey');
  setLoading(btn, true);
  try {
    const r = await api.connectApiKey(provider, { api_key: key });
    document.getElementById('modal-info')?.remove();
    toast(`${provider} connected${r.username ? ` as ${r.username}` : ''}`, 'success');
    showPage('integrations');
  } catch(e) { toast(e.message, 'error'); }
  finally { setLoading(btn, false); }
}


/* ════════════════════════════════════════════════════════════════════════════
   REPOSITORIES
══════════════════════════════════════════════════════════════════════════════*/
PAGES.repositories = async function(el) {
  el.innerHTML = `<div class="slide-up"><div class="skeleton" style="height:400px;border-radius:var(--radius-lg)"></div></div>`;
  try {
    const data = await api.getRepos();
    if (!data.connected) {
      el.innerHTML = `
        <div class="card" style="text-align:center;padding:48px">
          <div style="font-size:48px;margin-bottom:16px">🐙</div>
          <div style="font-family:var(--font-display);font-size:20px;font-weight:700;margin-bottom:8px">Connect GitHub</div>
          <div style="color:var(--text-secondary);font-size:14px;margin-bottom:24px">Link your GitHub account to see repositories, commits and pull request data.</div>
          <a href="/auth/login/github" class="btn btn-primary btn-lg">Connect GitHub →</a>
        </div>`;
      return;
    }
    const repos = data.repositories || [];
    el.innerHTML = `
      <div class="slide-up">
        <div class="flex justify-between items-center" style="margin-bottom:20px">
          <div style="font-size:14px;color:var(--text-muted)">${repos.length} repositories</div>
          <button class="btn btn-secondary btn-sm" onclick="syncIntegration('github').then(()=>showPage('repositories'))">↻ Sync</button>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px">
          ${repos.map(r => `
            <div class="card" style="cursor:pointer" onclick="window.open('${r.url}','_blank')">
              <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:8px">
                <div style="font-family:var(--font-display);font-size:14px;font-weight:700">${r.name}</div>
                <span class="badge ${r.private?'badge-red':'badge-green'}">${r.private?'Private':'Public'}</span>
              </div>
              ${r.description?`<div style="font-size:12px;color:var(--text-secondary);margin-bottom:10px;line-height:1.5">${r.description.slice(0,100)}</div>`:''}
              <div style="display:flex;align-items:center;gap:14px;font-size:12px;color:var(--text-muted)">
                ${r.language?`<span>◉ ${r.language}</span>`:''}
                <span>⭐ ${r.stars}</span>
                <span>🍴 ${r.forks}</span>
                <span style="margin-left:auto">${timeAgo(r.updated_at)}</span>
              </div>
            </div>`).join('')}
        </div>
      </div>`;
  } catch(e) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">${e.message}</div></div>`;
  }
};


/* ════════════════════════════════════════════════════════════════════════════
   TASKS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.tasks = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="flex justify-between items-center" style="margin-bottom:20px;flex-wrap:wrap;gap:12px">
      <div style="display:flex;gap:6px;background:var(--bg-elevated);padding:4px;border-radius:var(--radius)">
        <button class="tab-btn active" data-filter="" onclick="filterTasks('',this)">All</button>
        <button class="tab-btn" data-filter="active" onclick="filterTasks('active',this)">Active</button>
        <button class="tab-btn" data-filter="completed" onclick="filterTasks('completed',this)">Completed</button>
      </div>
      <button class="btn btn-primary" onclick="openModal('modal-start-task')">⚡ Start Task</button>
    </div>
    <div id="tasks-list"><div class="skeleton" style="height:400px;border-radius:var(--radius-lg)"></div></div>
  </div>`;
  loadTasksList('');
};

async function filterTasks(filter, btn) {
  document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  await loadTasksList(filter);
}

async function loadTasksList(filter) {
  const list = document.getElementById('tasks-list');
  if (!list) return;
  list.innerHTML = '<div class="skeleton" style="height:300px;border-radius:var(--radius-lg)"></div>';
  try {
    const tasks = await api.listTasks(filter);
    if (!tasks.length) {
      list.innerHTML = `<div class="empty-state"><div class="empty-icon">✅</div><div class="empty-title">No ${filter||''} tasks</div><button class="btn btn-primary" onclick="openModal('modal-start-task')">Start a Task</button></div>`;
      return;
    }
    list.innerHTML = `
      <div class="card" style="padding:0;overflow:hidden">
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Goal</th><th>Status</th><th>Target</th><th>Final</th><th>Score</th><th>Started</th><th>Duration</th><th>Actions</th></tr></thead>
            <tbody id="task-tbody"></tbody>
          </table>
        </div>
      </div>`;
    const tbody = document.getElementById('task-tbody');
    tasks.forEach(t => {
      const sc = t.score;
      const {color} = sc ? scoreGrade(sc.final_score) : {color:'var(--text-muted)'};
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="max-width:260px"><div style="font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${t.goal}</div><div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono)">${t.id.slice(0,12)}...</div></td>
        <td>${statusBadge(t.status)}</td>
        <td><span class="badge badge-purple">L${t.target_level}</span></td>
        <td>${t.final_level!=null?`<span class="badge badge-blue">L${t.final_level}</span>`:'<span style="color:var(--text-muted)">—</span>'}</td>
        <td style="color:${color};font-family:var(--font-mono);font-weight:700">${sc?sc.final_score:'—'}</td>
        <td style="font-size:12px;color:var(--text-secondary)">${fmtDate(t.started_at)}</td>
        <td style="font-size:12px;font-family:var(--font-mono)">${duration(t.started_at,t.ended_at)}</td>
        <td><div style="display:flex;gap:6px">
          <button class="btn btn-sm btn-secondary" onclick="copyToClipboard('${t.id}')" title="Copy ID">📋</button>
          ${t.status==='active'?`<button class="btn btn-sm btn-success" onclick="prefillEndTask('${t.id}')">End</button>`:''}
        </div></td>`;
      tbody.appendChild(tr);
    });
  } catch(e) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">${e.message}</div></div>`;
  }
}


/* ════════════════════════════════════════════════════════════════════════════
   EVENTS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.events = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="flex justify-between items-center" style="margin-bottom:20px;flex-wrap:wrap;gap:12px">
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <select class="form-input form-select" id="ev-type" style="width:140px" onchange="loadEventsList()">
          <option value="">All Types</option>
          <option value="commit">commit</option><option value="deploy">deploy</option>
          <option value="ai">ai</option><option value="error">error</option>
        </select>
      </div>
      <button class="btn btn-primary" onclick="openModal('modal-event')">📥 Log Event</button>
    </div>
    <div id="events-list"><div class="skeleton" style="height:400px;border-radius:var(--radius-lg)"></div></div>
  </div>`;
  loadEventsList();
};

async function loadEventsList() {
  const type = document.getElementById('ev-type')?.value;
  const list = document.getElementById('events-list');
  if (!list) return;
  list.innerHTML = '<div class="skeleton" style="height:300px;border-radius:var(--radius-lg)"></div>';
  try {
    const q = `?limit=50${type?`&event_type=${type}`:''}`;
    const data = await api.listEvents(q);
    const events = data.events || data;
    if (!events.length) {
      list.innerHTML = `<div class="empty-state"><div class="empty-icon">⚡</div><div class="empty-title">No events found</div></div>`;
      return;
    }
    list.innerHTML = `
      <div class="card" style="padding:0;overflow:hidden">
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Type</th><th>Task</th><th>Source</th><th>Details</th><th>Time</th></tr></thead>
            <tbody id="ev-tbody"></tbody>
          </table>
        </div>
      </div>`;
    const tbody = document.getElementById('ev-tbody');
    events.forEach(e => {
      const meta   = e.metadata || {};
      const detail = meta.message||meta.prompt_snippet||meta.error_hash||meta.service||meta.sha||'—';
      const tr     = document.createElement('tr');
      tr.innerHTML = `
        <td>${eventBadge(e.event_type)}</td>
        <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted)">${e.task_id?e.task_id.slice(0,10)+'...':'<span style="color:var(--red);font-size:11px">unassigned</span>'}</td>
        <td><span class="badge badge-purple" style="font-size:10px">${e.source||'—'}</span></td>
        <td style="max-width:260px;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-secondary)">${String(detail).slice(0,80)}</td>
        <td style="font-size:12px;color:var(--text-muted);white-space:nowrap">${fmtDateTime(e.timestamp)}</td>`;
      tbody.appendChild(tr);
    });
  } catch(e) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">${e.message}</div></div>`;
  }
}


/* ════════════════════════════════════════════════════════════════════════════
   REPORTS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.reports = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="flex gap-4" style="margin-bottom:20px;flex-wrap:wrap">
      <button class="btn btn-primary" id="btn-gen-report" onclick="generateReport()">🔄 Generate Today's Report</button>
      <button class="btn btn-secondary" onclick="loadMarkdownReport()">📄 Markdown View</button>
    </div>
    <div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap">
      <input class="form-input" id="report-date" type="date" style="width:180px"/>
      <button class="btn btn-secondary" onclick="loadReportByDate()">Load Date</button>
    </div>
    <div id="report-content"><div class="skeleton" style="height:400px;border-radius:var(--radius-lg)"></div></div>
  </div>`;
  document.getElementById('report-date').value = new Date().toISOString().split('T')[0];
  try {
    const r = await api.dailyReport();
    renderReport(r, document.getElementById('report-content'));
  } catch {
    document.getElementById('report-content').innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-title">No report yet</div><div class="empty-desc">Click "Generate Today's Report"</div></div>`;
  }
};

async function generateReport() {
  const btn = document.getElementById('btn-gen-report'); setLoading(btn, true);
  try {
    const r = await api.generateReport();
    toast('Report generated!','success');
    renderReport(r.report||r, document.getElementById('report-content'));
  } catch(e){toast(e.message,'error');} finally{setLoading(btn,false);}
}

async function loadMarkdownReport() {
  try {
    const r = await api.dailyMarkdown();
    const md = typeof r==='string'?r:JSON.stringify(r,null,2);
    showInfoModal('📄 Daily Report',`<pre style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);white-space:pre-wrap;max-height:60vh;overflow-y:auto;padding:16px;background:var(--bg-elevated);border-radius:var(--radius)">${md}</pre>`);
  } catch(e){toast(e.message,'error');}
}

async function loadReportByDate() {
  const date = document.getElementById('report-date').value;
  if(!date) return;
  try {
    const r = await api.get(`/report/${date}`);
    renderReport(r, document.getElementById('report-content'));
  } catch {toast(`No report for ${date}`,'error');}
}

function renderReport(r, el) {
  if(!r||!r.meta){el.innerHTML=`<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-title">No report data</div></div>`;return;}
  const s=r.summary||{}, a=r.analysis||{};
  const {color}=scoreGrade(s.average_score||0);
  el.innerHTML=`
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="card card-glow">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px">
          <div><div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">DAILY REPORT · ${r.meta.date}</div><div style="font-size:24px;font-weight:800;font-family:var(--font-display)">Execution Audit</div></div>
          <div style="display:flex;align-items:center;gap:20px">
            ${renderScoreRing(Math.round(s.average_score||0),80)}
            <div><div style="font-size:13px;color:var(--text-muted)">Tasks</div><div style="font-size:18px;font-weight:800">${s.completed_tasks}/${s.total_tasks}</div><div style="font-size:12px;color:var(--text-muted)">Grade: <strong style="color:${color}">${s.score_grade}</strong></div></div>
          </div>
        </div>
      </div>
      ${(r.scores||[]).length?`<div class="card"><div class="section-title" style="margin-bottom:12px">📊 Score Breakdown</div><div style="display:flex;flex-direction:column;gap:8px">${r.scores.map(sc=>`<div style="display:flex;align-items:center;gap:12px;padding:10px;background:var(--bg-elevated);border-radius:var(--radius)"><div style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted)">${sc.task_id.slice(0,10)}...</div><div style="flex:1;display:flex;gap:10px;flex-wrap:wrap;font-size:12px"><span>L${sc.level}→<strong>${sc.outcome_score}</strong></span><span style="color:var(--green)">+${sc.velocity}</span><span style="color:var(--red)">-${sc.stability_penalty}</span><span style="color:var(--yellow)">-${sc.ai_penalty}</span></div><div style="font-size:20px;font-weight:800;color:${scoreGrade(sc.final_score).color}">${sc.final_score}</div></div>`).join('')}</div></div>`:''}
      ${a.bottlenecks?.length?`<div class="card"><div class="section-title" style="margin-bottom:12px">🧠 AI Analysis</div><div style="display:flex;flex-direction:column;gap:10px">${a.bottlenecks.slice(0,2).map(b=>`<div style="padding:12px;background:var(--bg-elevated);border-radius:var(--radius);border-left:3px solid var(--purple)"><div style="font-weight:600;font-size:13px;margin-bottom:4px">${b.title}</div><div style="font-size:12px;margin-bottom:6px"><span class="badge badge-red">${b.classification}</span></div><div style="font-size:12px;color:var(--text-secondary)">${b.evidence}</div></div>`).join('')}${a.root_cause?`<div style="padding:12px;background:var(--bg-elevated);border-radius:var(--radius)"><div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">ROOT CAUSE</div><div style="font-size:13px">${a.root_cause}</div></div>`:''}${a.corrective_actions?.length?`<div>${a.corrective_actions.slice(0,3).map((ac,i)=>`<div style="padding:10px;background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.15);border-radius:var(--radius);margin-bottom:6px;font-size:13px"><strong style="color:var(--green)">${i+1}.</strong> ${ac.action}</div>`).join('')}</div>`:''}</div></div>`:''}
    </div>`;
}


/* ════════════════════════════════════════════════════════════════════════════
   METRICS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.metrics = async function(el) {
  el.innerHTML=`<div class="slide-up"><div class="flex gap-4" style="margin-bottom:20px;flex-wrap:wrap"><button class="btn btn-primary" onclick="openModal('modal-manual-score')">🎯 Submit Score</button><button class="btn btn-secondary" id="btn-tune" onclick="runTuning()">🔧 Run Tuning</button><button class="btn btn-secondary" onclick="submitLoopFeedback()">🔄 Loop Feedback</button></div><div id="metrics-content"><div class="skeleton" style="height:400px;border-radius:var(--radius-lg)"></div></div></div>`;
  try {
    const m=await api.getMetrics();
    const cri=[['Task Coverage',m.task_id_coverage?.coverage_pct,80,'%'],['Tasks Today',m.scoring?.tasks_today,null,''],['Completed',m.scoring?.completed_today,null,'']];
    document.getElementById('metrics-content').innerHTML=`
      <div class="grid-3" style="margin-bottom:20px">
        ${cri.map(([l,v,thresh,suf])=>{const ok=thresh?v>=thresh:true;return`<div class="stat-card" style="border-color:${thresh?(ok?'rgba(16,185,129,.2)':'rgba(239,68,68,.2)'):'var(--border)'}"><div class="stat-label">${l}</div><div class="stat-value" style="color:${thresh?(ok?'var(--green)':'var(--red)'):'var(--text-primary)'}">${v??'—'}${suf}</div>${thresh?`<div class="stat-delta ${ok?'delta-up':'delta-down'}">${ok?'✓ Pass':'✗ Fail'} (min: ${thresh}${suf})</div>`:''}</div>`;}).join('')}
      </div>
      <div class="card"><div class="section-title" style="margin-bottom:12px">ℹ️ Metrics Overview</div><pre style="font-size:12px;font-family:var(--font-mono);color:var(--text-secondary);white-space:pre-wrap">${JSON.stringify(m,null,2)}</pre></div>`;
  } catch(e){document.getElementById('metrics-content').innerHTML=`<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">${e.message}</div></div>`;}
};

async function runTuning(){
  const btn=document.getElementById('btn-tune');setLoading(btn,true);
  try{const r=await api.post('/metrics/tune',{force:false});toast(r.tuned?`Tuning: ${r.message}`:r.reason,r.tuned?'success':'warn');}
  catch(e){toast(e.message,'error');}finally{setLoading(btn,false);}
}
function submitLoopFeedback(){
  const id=prompt('Task ID flagged as loop:');if(!id)return;
  const was=confirm('Was it actually a loop?\nOK=Yes, Cancel=No (false positive)');
  api.loopFeedback({task_id:id,was_actual_loop:was}).then(r=>toast(`Feedback recorded. FP rate: ${r.false_positive_rate??'—'}`,'success')).catch(e=>toast(e.message,'error'));
}


/* ════════════════════════════════════════════════════════════════════════════
   AI PROXY
══════════════════════════════════════════════════════════════════════════════*/
PAGES.proxy = async function(el) {
  el.innerHTML=`
  <div class="slide-up">
    <div style="background:rgba(6,182,212,.06);border:1px solid rgba(6,182,212,.2);border-radius:var(--radius);padding:14px;margin-bottom:20px;font-size:13px">
      <strong style="color:var(--cyan-l)">How to use:</strong> Send AI requests through this proxy to automatically log them with your Task ID. All calls are attributed to your account.
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="section-title" style="margin-bottom:14px">🤖 OpenAI Proxy</div>
        <div style="display:flex;flex-direction:column;gap:12px">
          <div class="form-group"><label class="form-label">Task ID</label><input class="form-input" id="oai-task" placeholder="Active task ID"/></div>
          <div class="form-group"><label class="form-label">OpenAI API Key</label><input class="form-input" id="oai-key" type="password" placeholder="sk-..."/></div>
          <div class="form-group"><label class="form-label">Model</label><select class="form-input form-select" id="oai-model"><option value="gpt-4o-mini">gpt-4o-mini</option><option value="gpt-4o">gpt-4o</option><option value="gpt-3.5-turbo">gpt-3.5-turbo</option></select></div>
          <div class="form-group"><label class="form-label">Prompt</label><textarea class="form-input form-textarea" id="oai-prompt" placeholder="Your prompt..."></textarea></div>
          <button class="btn btn-primary" id="btn-oai" onclick="sendOAI()">🚀 Send via Proxy</button>
          <div id="oai-result" style="display:none"></div>
        </div>
      </div>
      <div class="card">
        <div class="section-title" style="margin-bottom:14px">🧠 Anthropic Proxy</div>
        <div style="display:flex;flex-direction:column;gap:12px">
          <div class="form-group"><label class="form-label">Task ID</label><input class="form-input" id="ant-task" placeholder="Active task ID"/></div>
          <div class="form-group"><label class="form-label">Anthropic API Key</label><input class="form-input" id="ant-key" type="password" placeholder="sk-ant-..."/></div>
          <div class="form-group"><label class="form-label">Model</label><select class="form-input form-select" id="ant-model"><option value="claude-sonnet-4-20250514">claude-sonnet-4</option><option value="claude-haiku-4-5-20251001">claude-haiku-4.5</option></select></div>
          <div class="form-group"><label class="form-label">Prompt</label><textarea class="form-input form-textarea" id="ant-prompt" placeholder="Your prompt..."></textarea></div>
          <button class="btn btn-primary" id="btn-ant" onclick="sendAnt()">🚀 Send via Proxy</button>
          <div id="ant-result" style="display:none"></div>
        </div>
      </div>
    </div>
  </div>`;
};

async function sendOAI(){
  const task_id=document.getElementById('oai-task').value.trim();
  const key=document.getElementById('oai-key').value.trim();
  const model=document.getElementById('oai-model').value;
  const prompt=document.getElementById('oai-prompt').value.trim();
  if(!prompt){toast('Prompt required','error');return;}
  const btn=document.getElementById('btn-oai');setLoading(btn,true);
  const resultEl=document.getElementById('oai-result');resultEl.style.display='none';
  try{
    const h={'Content-Type':'application/json'};if(key)h['X-OpenAI-Key']=key;
    const res=await fetch(`${API_BASE}/proxy/openai`,{method:'POST',headers:h,credentials:'include',body:JSON.stringify({task_id:task_id||undefined,payload:{model,messages:[{role:'user',content:prompt}]}})});
    const data=await res.json();
    if(!res.ok)throw new Error(data.detail||`HTTP ${res.status}`);
    const text=data.choices?.[0]?.message?.content||JSON.stringify(data);
    resultEl.style.display='block';
    resultEl.innerHTML=`<div style="background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.2);border-radius:var(--radius);padding:14px;font-size:13px;color:var(--text-secondary);white-space:pre-wrap;max-height:200px;overflow-y:auto">${text}</div>`;
    toast('Response received & logged','success');
  }catch(e){toast(e.message,'error');}finally{setLoading(btn,false);}
}

async function sendAnt(){
  const task_id=document.getElementById('ant-task').value.trim();
  const key=document.getElementById('ant-key').value.trim();
  const model=document.getElementById('ant-model').value;
  const prompt=document.getElementById('ant-prompt').value.trim();
  if(!prompt){toast('Prompt required','error');return;}
  const btn=document.getElementById('btn-ant');setLoading(btn,true);
  const resultEl=document.getElementById('ant-result');resultEl.style.display='none';
  try{
    const h={'Content-Type':'application/json'};if(key)h['X-Anthropic-Key']=key;
    const res=await fetch(`${API_BASE}/proxy/anthropic`,{method:'POST',headers:h,credentials:'include',body:JSON.stringify({task_id:task_id||undefined,payload:{model,max_tokens:1000,messages:[{role:'user',content:prompt}]}})});
    const data=await res.json();
    if(!res.ok)throw new Error(data.detail||`HTTP ${res.status}`);
    const text=data.content?.[0]?.text||JSON.stringify(data);
    resultEl.style.display='block';
    resultEl.innerHTML=`<div style="background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.2);border-radius:var(--radius);padding:14px;font-size:13px;color:var(--text-secondary);white-space:pre-wrap;max-height:200px;overflow-y:auto">${text}</div>`;
    toast('Response received & logged','success');
  }catch(e){toast(e.message,'error');}finally{setLoading(btn,false);}
}


/* ════════════════════════════════════════════════════════════════════════════
   DEPLOYMENTS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.deployments = async function(el) {
  el.innerHTML=`
  <div class="slide-up">
    <div class="card" style="margin-bottom:20px">
      <div class="section-title" style="margin-bottom:14px">🚀 Validate Deployment</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px">Run L1–L4 validation checks. Required before claiming Level 5.</p>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div class="form-group"><label class="form-label">Service URL *</label><input class="form-input" id="dep-url" placeholder="https://your-app.onrender.com"/></div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">Functional Path</label><input class="form-input" id="dep-path" value="/health"/></div>
          <div class="form-group"><label class="form-label">Expected Status</label><input class="form-input" id="dep-status" type="number" value="200"/></div>
        </div>
        <div class="form-group"><label class="form-label">Expected JSON Keys (comma-separated)</label><input class="form-input" id="dep-keys" placeholder="status,version"/></div>
        <button class="btn btn-primary" id="btn-validate" onclick="runValidation()">🚀 Validate</button>
      </div>
    </div>
    <div id="validation-result"></div>
    <div class="card" style="margin-top:16px">
      <div class="section-title" style="margin-bottom:12px">📥 Log Deploy Event</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <input class="form-input" id="dep-task" placeholder="Task ID" style="flex:1;min-width:160px"/>
        <input class="form-input" id="dep-platform" placeholder="Platform (render)" style="flex:1;min-width:120px"/>
        <select class="form-input form-select" id="dep-result" style="width:130px"><option value="success">✅ success</option><option value="failed">❌ failed</option></select>
        <button class="btn btn-secondary" onclick="logDeployEvent()">Log</button>
      </div>
    </div>
  </div>`;
};

async function runValidation(){
  const url=document.getElementById('dep-url').value.trim();
  if(!url){toast('URL required','error');return;}
  const path=document.getElementById('dep-path').value||'/health';
  const status=parseInt(document.getElementById('dep-status').value)||200;
  const keysRaw=document.getElementById('dep-keys').value.trim();
  const keys=keysRaw?keysRaw.split(',').map(k=>k.trim()).filter(Boolean):[];
  const btn=document.getElementById('btn-validate');setLoading(btn,true);
  const resultEl=document.getElementById('validation-result');
  resultEl.innerHTML='<div class="skeleton" style="height:180px;border-radius:var(--radius-lg)"></div>';
  try{
    const r=await api.validateDeploy({url,functional_path:path,functional_expected_status:status,functional_expected_keys:keys.length?keys:undefined});
    const sc={success:'var(--green)',partial:'var(--yellow)',failed:'var(--red)'};
    const ic={success:'✅',partial:'⚠️',failed:'❌'};
    resultEl.innerHTML=`<div class="card" style="border-color:${r.status==='success'?'rgba(16,185,129,.3)':r.status==='partial'?'rgba(245,158,11,.3)':'rgba(239,68,68,.3)'}">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px"><div style="font-size:28px">${ic[r.status]}</div><div><div style="font-size:20px;font-weight:800;font-family:var(--font-display);color:${sc[r.status]}">${r.status.toUpperCase()}</div><div style="font-size:13px;color:var(--text-secondary)">${r.summary}</div></div><div style="margin-left:auto;font-size:26px;font-weight:800;color:${sc[r.status]}">${Math.round(r.score*100)}%</div></div>
      ${(r.checks||[]).map(c=>`<div style="display:flex;align-items:center;gap:10px;padding:9px;background:var(--bg-elevated);border-radius:var(--radius);margin-bottom:6px"><span style="font-size:14px">${c.success?'✅':'❌'}</span><div style="flex:1"><div style="font-size:12px;font-family:var(--font-mono)">${c.path}</div>${c.error?`<div style="font-size:11px;color:var(--red);margin-top:2px">${c.error}</div>`:''}</div><span style="font-size:12px;color:var(--text-muted)">${c.status_code||'—'} · ${c.latency_ms}ms</span></div>`).join('')}
      ${r.validation_level>=2?'<div style="margin-top:10px;padding:10px;background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.2);border-radius:var(--radius);font-size:12px;color:var(--green)">✅ L5 gate: PASS. You may claim Level 5.</div>':'<div style="margin-top:10px;padding:10px;background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.2);border-radius:var(--radius);font-size:12px;color:var(--red)">❌ L5 gate: FAIL. Fix issues before claiming Level 5.</div>'}
    </div>`;
    toast(`Validation: ${r.status}`,r.status==='success'?'success':r.status==='partial'?'warn':'error');
  }catch(e){resultEl.innerHTML=`<div class="card"><div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">${e.message}</div></div></div>`;}
  finally{setLoading(btn,false);}
}

async function logDeployEvent(){
  try{
    await api.ingestDeploy({task_id:document.getElementById('dep-task').value.trim()||undefined,platform:document.getElementById('dep-platform').value.trim()||'manual',status:document.getElementById('dep-result').value,timestamp:new Date().toISOString()});
    toast('Deploy event logged','success');
  }catch(e){toast(e.message,'error');}
}


/* ════════════════════════════════════════════════════════════════════════════
   SETTINGS — user profile + account
══════════════════════════════════════════════════════════════════════════════*/
PAGES.settings = async function(el) {
  const user = CURRENT_USER || {};
  el.innerHTML=`
  <div class="slide-up">
    <!-- Profile card -->
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-bottom:16px">👤 Profile</div>
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:16px">
        ${renderAvatar(user,56)}
        <div>
          <div style="font-family:var(--font-display);font-size:18px;font-weight:700">${user.name||'—'}</div>
          <div style="font-size:13px;color:var(--text-muted)">${user.email||''}</div>
          ${user.github_username?`<div style="font-size:13px;color:var(--purple-l);margin-top:2px">@${user.github_username} on GitHub</div>`:''}
        </div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        ${user.github_id?`<div class="badge badge-green">🐙 GitHub Connected</div>`:`<a href="/auth/login/github" class="btn btn-sm btn-secondary">Connect GitHub</a>`}
        ${user.google_id?`<div class="badge badge-blue">🔵 Google Connected</div>`:`<a href="/auth/login/google" class="btn btn-sm btn-secondary">Connect Google</a>`}
      </div>
    </div>

    <!-- GitHub webhook -->
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-bottom:12px">🐙 GitHub Webhook</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">Add this to your GitHub repo to auto-ingest commits.</p>
      <div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius);padding:12px;font-family:var(--font-mono);font-size:12px;color:var(--cyan-l);cursor:pointer" onclick="copyToClipboard('https://traceops-ai.onrender.com/event/github')">
        https://traceops-ai.onrender.com/event/github
        <span style="color:var(--text-muted);margin-left:8px">← click to copy</span>
      </div>
      <div style="font-size:12px;color:var(--text-muted);margin-top:8px">GitHub → Settings → Webhooks → Add webhook → Content type: application/json</div>
    </div>

    <!-- Commit format -->
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-bottom:12px">📝 Commit Tag Format</div>
      <div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius);padding:12px;font-family:var(--font-mono);font-size:13px;color:var(--purple-l)">
        git commit -m "feat: your message [TRO-&lt;task-id&gt;]"
      </div>
    </div>

    <!-- System health -->
    <div class="card">
      <div class="section-title" style="margin-bottom:14px">🩺 System Health</div>
      <div id="health-info"><div class="skeleton" style="height:80px"></div></div>
      <button class="btn btn-danger btn-sm" style="margin-top:16px" onclick="handleLogout()">🚪 Sign Out</button>
    </div>
  </div>`;

  try{
    const h=await api.healthDeep();
    document.getElementById('health-info').innerHTML=`
      <div style="display:flex;flex-direction:column;gap:8px;font-size:13px">
        ${[['API v2','ok',true],['Database',h.components?.database?.alive,true],['Redis',h.components?.redis?.alive,true],['Worker',h.components?.celery_worker?.alive,false]].map(([name,ok,required])=>`<div class="flex justify-between" style="padding:6px 0;border-bottom:1px solid var(--border)"><span>${name}${!required?' <span style="font-size:10px;color:var(--text-muted)">(optional)</span>':''}</span><div style="display:flex;align-items:center;gap:6px"><div class="dot ${ok?'dot-green':'dot-red'}"></div><span style="font-size:12px;color:${ok?'var(--green)':'var(--red)'}">${ok?'Online':'Offline'}</span></div></div>`).join('')}
      </div>`;
  }catch{}
};
