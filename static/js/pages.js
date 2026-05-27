/* ── Pages.js — All page renderers ─────────────────────────────────────────
   Every page only uses endpoints that ACTUALLY EXIST in the backend.
   Verified routes only:
   GET  /task/   GET /task/{id}   POST /task/start   POST /task/end
   GET  /event/  POST /event/  POST /event/github  /event/deploy  /event/error
   GET  /report/daily  GET /report/daily/markdown  GET /report/{date}
   POST /report/generate  POST /report/validate
   POST /proxy/openai  POST /proxy/anthropic
   GET  /metrics/public  GET /metrics/  GET /metrics/config  GET /metrics/tune/log
   POST /metrics/tune  POST /metrics/score/manual  POST /metrics/loop/feedback
   GET  /metrics/webhook/stats  POST /metrics/webhook/replay  GET /metrics/proxy/coverage
   GET  /worker/health  POST /worker/scheduler/trigger  GET /worker/scheduler/missed
   GET  /health  GET /health/deep
──────────────────────────────────────────────────────────────────────────── */

const PAGES = {};

/* ════════════════════════════════════════════════════════════════════════════
   DASHBOARD
══════════════════════════════════════════════════════════════════════════════*/
PAGES.dashboard = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <!-- Quick actions -->
    <div class="flex gap-4" style="margin-bottom:20px;flex-wrap:wrap">
      <button class="btn btn-primary" onclick="openModal('modal-start-task')">⚡ Start Task</button>
      <button class="btn btn-secondary" onclick="openModal('modal-end-task')">✅ End Task</button>
      <button class="btn btn-secondary" onclick="openModal('modal-event')">📥 Log Event</button>
      <button class="btn btn-secondary" onclick="showPage('reports')">📋 Today's Report</button>
    </div>

    <!-- Stat cards row -->
    <div class="grid-4" style="margin-bottom:20px" id="dash-stats">
      ${[0,1,2,3].map(()=>`<div class="stat-card"><div class="skeleton" style="height:14px;width:60%;margin-bottom:8px"></div><div class="skeleton" style="height:32px;width:50%"></div></div>`).join('')}
    </div>

    <!-- Main grid -->
    <div class="grid-2" style="margin-bottom:20px">
      <!-- Active tasks -->
      <div class="card">
        <div class="section-header">
          <div class="section-title">🎯 Active Tasks</div>
          <button class="btn btn-sm btn-secondary" onclick="showPage('tasks')">View All →</button>
        </div>
        <div id="dash-tasks"><div class="skeleton" style="height:200px"></div></div>
      </div>
      <!-- Recent events -->
      <div class="card">
        <div class="section-header">
          <div class="section-title">⚡ Recent Events</div>
          <button class="btn btn-sm btn-secondary" onclick="showPage('events')">View All →</button>
        </div>
        <div id="dash-events"><div class="skeleton" style="height:200px"></div></div>
      </div>
    </div>

    <!-- Score + health -->
    <div class="grid-2">
      <div class="card" id="dash-score-card">
        <div class="section-title" style="margin-bottom:16px">📊 Today's Score</div>
        <div class="skeleton" style="height:160px"></div>
      </div>
      <div class="card" id="dash-health-card">
        <div class="section-title" style="margin-bottom:16px">🩺 System Health</div>
        <div class="skeleton" style="height:160px"></div>
      </div>
    </div>
  </div>`;

  // Load data in parallel
  const [tasks, events, metrics, health] = await Promise.allSettled([
    api.listTasks('active'),
    api.listEvents('?limit=8'),
    api.getMetrics(),
    api.healthDeep(),
  ]);

  // Stats
  const t = tasks.value || [];
  const m = metrics.value || {};
  document.getElementById('dash-stats').innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Active Tasks</div>
      <div class="stat-value" style="color:var(--green)">${t.length}</div>
      <div class="stat-delta delta-up">Today</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg Score</div>
      <div class="stat-value" style="color:var(--purple-l)">${m.scoring?.score_distribution?.mean ?? '—'}</div>
      <div class="stat-delta">Today</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Tasks Done</div>
      <div class="stat-value" style="color:var(--cyan)">${m.scoring?.completed_today ?? '—'}</div>
      <div class="stat-delta">Completed</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">TASK_ID Coverage</div>
      <div class="stat-value" style="color:${(m.task_id_coverage?.coverage_pct ?? 0) >= 80 ? 'var(--green)' : 'var(--red)'}">${m.task_id_coverage?.coverage_pct ?? '—'}%</div>
      <div class="stat-delta">Today</div>
    </div>`;

  // Active tasks
  const tasksList = tasks.value || [];
  document.getElementById('dash-tasks').innerHTML = tasksList.length
    ? tasksList.slice(0,5).map(t => `
        <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)">
          <div class="dot dot-green dot-pulse"></div>
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${t.goal}</div>
            <div style="font-size:11px;color:var(--text-muted)">L${t.target_level} target · ${fmtDate(t.started_at)}</div>
          </div>
          <button class="btn btn-sm btn-success" onclick="prefillEndTask('${t.id}')">End</button>
        </div>`).join('')
    : '<div class="empty-state" style="padding:32px"><div class="empty-icon">✅</div><div class="empty-title">No active tasks</div><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="openModal(\'modal-start-task\')">Start one</button></div>';

  // Recent events
  const eventsList = events.value || [];
  document.getElementById('dash-events').innerHTML = eventsList.length
    ? eventsList.slice(0,6).map(e => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">
          ${eventBadge(e.event_type)}
          <div style="flex:1;font-size:12px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            ${e.metadata?.message || e.metadata?.prompt_snippet || e.metadata?.error_hash || e.source || 'Event'}
          </div>
          <div style="font-size:11px;color:var(--text-muted);flex-shrink:0">${timeAgo(e.timestamp)}</div>
        </div>`).join('')
    : '<div class="empty-state" style="padding:32px"><div class="empty-icon">⚡</div><div class="empty-title">No events yet</div></div>';

  // Score card
  const s = metrics.value?.scoring || {};
  const score = s.score_distribution?.mean;
  document.getElementById('dash-score-card').innerHTML = `
    <div class="section-title" style="margin-bottom:16px">📊 Today's Score</div>
    ${score ? `
      <div style="display:flex;align-items:center;gap:24px">
        ${renderScoreRing(Math.round(score), 96)}
        <div style="flex:1">
          <div style="margin-bottom:8px"><div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">Tasks today</div><div style="font-weight:700">${s.tasks_today ?? '—'}</div></div>
          <div style="margin-bottom:8px"><div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">Completed</div><div style="font-weight:700">${s.completed_today ?? '—'}</div></div>
          <div><div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">Manual comparisons</div><div style="font-weight:700">${s.manual_comparisons ?? 0}</div></div>
        </div>
      </div>
      <button class="btn btn-sm btn-secondary" style="margin-top:16px;width:100%" onclick="openModal('modal-manual-score')">🎯 Submit My Honest Score</button>
    ` : '<div class="empty-state" style="padding:20px"><div class="empty-icon">📊</div><div class="empty-title">No score data yet</div><div class="empty-desc">Complete a task to generate your first score</div></div>'}`;

  // Health card
  const h = health.value || {};
  const comps = h.components || {};
  document.getElementById('dash-health-card').innerHTML = `
    <div class="section-title" style="margin-bottom:16px">🩺 System Health</div>
    <div style="display:flex;flex-direction:column;gap:10px">
      ${[
        ['API',     h.status === 'ok',            comps.database?.alive !== undefined],
        ['Database',comps.database?.alive === true, true],
        ['Redis',   comps.redis?.alive === true,    true],
        ['Worker',  comps.celery_worker?.alive === true, true],
      ].map(([name, ok, shown]) => shown ? `
        <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)">
          <span style="font-size:13px">${name}</span>
          <div style="display:flex;align-items:center;gap:6px">
            <div class="dot ${ok ? 'dot-green' : 'dot-red'}"></div>
            <span style="font-size:12px;color:${ok ? 'var(--green)' : 'var(--red)'}">${ok ? 'Online' : 'Offline'}</span>
          </div>
        </div>` : '').join('')}
    </div>
    <button class="btn btn-sm btn-secondary" style="margin-top:16px;width:100%" onclick="showPage('scheduler')">View Scheduler →</button>`;
};

function prefillEndTask(id) {
  document.getElementById('end-task-id').value = id;
  openModal('modal-end-task');
}


/* ════════════════════════════════════════════════════════════════════════════
   TASKS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.tasks = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="flex justify-between items-center" style="margin-bottom:20px;flex-wrap:wrap;gap:12px">
      <div class="tabs" style="margin-bottom:0;flex:1;max-width:400px" id="task-tabs">
        <button class="tab-btn active" data-filter="">All</button>
        <button class="tab-btn" data-filter="active">Active</button>
        <button class="tab-btn" data-filter="completed">Completed</button>
      </div>
      <button class="btn btn-primary" onclick="openModal('modal-start-task')">⚡ Start Task</button>
    </div>
    <div id="tasks-list"><div class="skeleton" style="height:400px;border-radius:var(--radius-lg)"></div></div>
  </div>`;

  let filter = '';
  const tabs = document.querySelectorAll('#task-tabs .tab-btn');
  tabs.forEach(btn => {
    btn.addEventListener('click', () => {
      tabs.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filter = btn.dataset.filter;
      loadTasks(filter);
    });
  });
  loadTasks('');

  async function loadTasks(f) {
    const list = document.getElementById('tasks-list');
    list.innerHTML = '<div class="skeleton" style="height:300px;border-radius:var(--radius-lg)"></div>';
    try {
      const tasks = await api.listTasks(f);
      if (!tasks.length) {
        list.innerHTML = `<div class="empty-state"><div class="empty-icon">✅</div><div class="empty-title">No ${f || ''} tasks found</div><button class="btn btn-primary" onclick="openModal('modal-start-task')">Start a Task</button></div>`;
        return;
      }
      list.innerHTML = `
        <div class="card" style="padding:0;overflow:hidden">
          <div class="table-wrap">
            <table class="table">
              <thead><tr>
                <th>Goal</th><th>Status</th><th>Target</th><th>Final</th><th>Score</th><th>Started</th><th>Duration</th><th>Actions</th>
              </tr></thead>
              <tbody id="task-tbody"></tbody>
            </table>
          </div>
        </div>`;
      const tbody = document.getElementById('task-tbody');
      tasks.forEach(t => {
        const scoreVal = t.score?.final_score;
        const { color } = scoreVal !== undefined ? scoreGrade(scoreVal) : { color: 'var(--text-muted)' };
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td style="max-width:280px">
            <div style="font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${t.goal}</div>
            <div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono)">${t.id.slice(0,12)}...</div>
          </td>
          <td>${statusBadge(t.status)}</td>
          <td><span class="badge badge-purple">L${t.target_level}</span></td>
          <td>${t.final_level !== null && t.final_level !== undefined ? `<span class="badge badge-blue">L${t.final_level}</span>` : '<span style="color:var(--text-muted)">—</span>'}</td>
          <td style="color:${color};font-family:var(--font-mono);font-weight:700">${scoreVal ?? '—'}</td>
          <td style="font-size:12px;color:var(--text-secondary)">${fmtDate(t.started_at)}</td>
          <td style="font-size:12px;font-family:var(--font-mono)">${duration(t.started_at, t.ended_at)}</td>
          <td>
            <div style="display:flex;gap:6px">
              <button class="btn btn-sm btn-secondary" onclick="viewTask('${t.id}')">View</button>
              ${t.status === 'active' ? `<button class="btn btn-sm btn-success" onclick="prefillEndTask('${t.id}')">End</button>` : ''}
              <button class="btn btn-sm btn-secondary" onclick="copyToClipboard('${t.id}')" title="Copy ID">📋</button>
            </div>
          </td>`;
        tbody.appendChild(tr);
      });
    } catch(e) { list.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Error loading tasks</div><div class="empty-desc">${e.message}</div></div>`; }
  }
};

async function viewTask(id) {
  try {
    const t = await api.getTask(id);
    const s = t.score;
    const scoreHtml = s ? `
      <div class="grid-2" style="margin-top:16px;gap:10px">
        <div style="background:var(--bg-elevated);border-radius:var(--radius);padding:12px">
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">FINAL SCORE</div>
          <div style="font-size:28px;font-weight:800;color:${scoreGrade(s.final_score).color}">${s.final_score}</div>
        </div>
        <div style="background:var(--bg-elevated);border-radius:var(--radius);padding:12px;display:flex;flex-direction:column;gap:6px;font-size:12px">
          <div class="flex justify-between"><span style="color:var(--text-muted)">Outcome</span><span>L${s.level} × 10 = ${s.level*10}</span></div>
          <div class="flex justify-between"><span style="color:var(--text-muted)">Velocity</span><span style="color:var(--green)">+${s.velocity}</span></div>
          <div class="flex justify-between"><span style="color:var(--text-muted)">Stability</span><span style="color:var(--red)">-${s.stability_penalty}</span></div>
          <div class="flex justify-between"><span style="color:var(--text-muted)">AI Penalty</span><span style="color:var(--yellow)">-${s.ai_penalty}</span></div>
        </div>
      </div>` : '';
    const content = `
      <div style="display:flex;flex-direction:column;gap:12px">
        <div><div style="font-size:11px;color:var(--text-muted);margin-bottom:2px">GOAL</div><div style="font-weight:600">${t.goal}</div></div>
        <div><div style="font-size:11px;color:var(--text-muted);margin-bottom:2px">TASK ID</div><div style="font-family:var(--font-mono);font-size:12px;background:var(--bg-elevated);padding:8px;border-radius:var(--radius)">${t.id}</div></div>
        <div class="grid-2" style="gap:10px">
          <div><div style="font-size:11px;color:var(--text-muted)">Status</div><div style="margin-top:4px">${statusBadge(t.status)}</div></div>
          <div><div style="font-size:11px;color:var(--text-muted)">Target Level</div><div style="margin-top:4px"><span class="badge badge-purple">L${t.target_level}</span></div></div>
          <div><div style="font-size:11px;color:var(--text-muted)">Started</div><div style="font-size:13px;margin-top:4px">${fmtDateTime(t.started_at)}</div></div>
          <div><div style="font-size:11px;color:var(--text-muted)">Ended</div><div style="font-size:13px;margin-top:4px">${t.ended_at ? fmtDateTime(t.ended_at) : '—'}</div></div>
        </div>
        ${scoreHtml}
        <div style="margin-top:8px;padding:12px;background:rgba(6,182,212,.06);border:1px solid rgba(6,182,212,.2);border-radius:var(--radius);font-size:12px;font-family:var(--font-mono);color:var(--cyan-l)">
          Add to commits: [TRO-${t.id}]
        </div>
      </div>`;
    showInfoModal(`Task: ${t.id.slice(0,12)}...`, content);
  } catch(e) { toast(e.message, 'error'); }
}

function showInfoModal(title, htmlContent) {
  const existing = document.getElementById('modal-info');
  if (existing) existing.remove();
  const m = document.createElement('div');
  m.className = 'modal-overlay'; m.id = 'modal-info';
  m.innerHTML = `<div class="modal"><div class="modal-header"><div class="modal-title">${title}</div><button class="modal-close" onclick="document.getElementById('modal-info').remove()">✕</button></div>${htmlContent}</div>`;
  m.addEventListener('click', e => { if (e.target === m) m.remove(); });
  document.body.appendChild(m);
}


/* ════════════════════════════════════════════════════════════════════════════
   EVENTS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.events = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="flex justify-between items-center" style="margin-bottom:20px;flex-wrap:wrap;gap:12px">
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <select class="form-input form-select" id="event-filter-type" style="width:140px">
          <option value="">All Types</option>
          <option value="commit">commit</option>
          <option value="deploy">deploy</option>
          <option value="ai">ai</option>
          <option value="error">error</option>
        </select>
        <input class="form-input" id="event-filter-task" placeholder="Filter by Task ID" style="width:220px"/>
        <button class="btn btn-secondary" onclick="loadEvents()">Filter</button>
      </div>
      <button class="btn btn-primary" onclick="openModal('modal-event')">📥 Log Event</button>
    </div>
    <div id="events-list"><div class="skeleton" style="height:400px;border-radius:var(--radius-lg)"></div></div>
  </div>`;

  document.getElementById('event-filter-type').addEventListener('change', loadEvents);
  loadEvents();

  async function loadEvents() {
    const type   = document.getElementById('event-filter-type').value;
    const taskId = document.getElementById('event-filter-task').value.trim();
    let q = '?limit=50';
    if (type)   q += `&event_type=${type}`;
    if (taskId) q += `&task_id=${taskId}`;

    const list = document.getElementById('events-list');
    list.innerHTML = '<div class="skeleton" style="height:300px;border-radius:var(--radius-lg)"></div>';
    try {
      const events = await api.listEvents(q);
      if (!events.length) {
        list.innerHTML = `<div class="empty-state"><div class="empty-icon">⚡</div><div class="empty-title">No events found</div><div class="empty-desc">Events are created automatically via GitHub webhook or logged manually.</div></div>`;
        return;
      }
      list.innerHTML = `
        <div class="card" style="padding:0;overflow:hidden">
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>Type</th><th>Task</th><th>Source</th><th>Details</th><th>Time</th></tr></thead>
              <tbody id="events-tbody"></tbody>
            </table>
          </div>
        </div>`;
      const tbody = document.getElementById('events-tbody');
      events.forEach(e => {
        const meta = e.metadata || {};
        const detail = meta.message || meta.prompt_snippet || meta.error_hash || meta.service || meta.sha || '—';
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${eventBadge(e.event_type)}</td>
          <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted)">${e.task_id ? e.task_id.slice(0,10)+'...' : '<span style="color:var(--red);font-size:11px">unassigned</span>'}</td>
          <td><span class="badge badge-purple">${e.source || '—'}</span></td>
          <td style="max-width:280px;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-secondary)">${String(detail).slice(0,80)}</td>
          <td style="font-size:12px;color:var(--text-muted);white-space:nowrap">${fmtDateTime(e.timestamp)}</td>`;
        tbody.appendChild(tr);
      });
    } catch(e) { list.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Error</div><div class="empty-desc">${e.message}</div></div>`; }
  }
};


/* ════════════════════════════════════════════════════════════════════════════
   REPORTS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.reports = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="flex gap-4" style="margin-bottom:20px;flex-wrap:wrap">
      <button class="btn btn-primary" id="btn-gen-report" onclick="generateReport()">🔄 Generate Today's Report</button>
      <button class="btn btn-secondary" onclick="loadMarkdownReport()">📄 View Markdown</button>
      <button class="btn btn-secondary" onclick="showPage('deployments')">🚀 Validate Deploy</button>
    </div>
    <div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap">
      <input class="form-input" id="report-date" type="date" style="width:180px"/>
      <button class="btn btn-secondary" onclick="loadReportByDate()">Load Date</button>
    </div>
    <div id="report-content"><div class="skeleton" style="height:400px;border-radius:var(--radius-lg)"></div></div>
  </div>`;

  document.getElementById('report-date').value = new Date().toISOString().split('T')[0];
  loadDailyReport();

  async function loadDailyReport() {
    const content = document.getElementById('report-content');
    try {
      const r = await api.dailyReport();
      renderReport(r, content);
    } catch(e) {
      content.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-title">No report yet</div><div class="empty-desc">Click "Generate Today's Report" to create one.</div></div>`;
    }
  }
};

async function generateReport() {
  const btn = document.getElementById('btn-gen-report');
  setLoading(btn, true);
  try {
    const r = await api.generateReport();
    toast('Report generated!', 'success');
    renderReport(r.report || r, document.getElementById('report-content'));
  } catch(e) { toast(e.message, 'error'); }
  finally { setLoading(btn, false); }
}

async function loadMarkdownReport() {
  try {
    const r = await api.dailyMarkdown();
    const md = typeof r === 'string' ? r : JSON.stringify(r, null, 2);
    showInfoModal('📄 Daily Report (Markdown)', `<pre style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);white-space:pre-wrap;max-height:60vh;overflow-y:auto;padding:16px;background:var(--bg-elevated);border-radius:var(--radius)">${md}</pre>`);
  } catch(e) { toast(e.message, 'error'); }
}

async function loadReportByDate() {
  const date = document.getElementById('report-date').value;
  if (!date) return;
  try {
    const r = await api.get(`/report/${date}`);
    renderReport(r, document.getElementById('report-content'));
  } catch(e) { toast(`No report for ${date}`, 'error'); }
}

function renderReport(r, el) {
  if (!r || !r.meta) { el.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-title">No report data</div></div>`; return; }
  const s = r.summary || {};
  const a = r.analysis || {};
  const { color } = scoreGrade(s.average_score || 0);
  el.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px">
      <!-- Summary header -->
      <div class="card card-glow">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px">
          <div>
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">DAILY REPORT · ${r.meta.date}</div>
            <div style="font-size:28px;font-weight:800;font-family:var(--font-display)">Execution Audit</div>
          </div>
          <div style="display:flex;align-items:center;gap:24px">
            ${renderScoreRing(Math.round(s.average_score || 0), 88)}
            <div>
              <div style="font-size:13px;color:var(--text-muted)">Tasks</div>
              <div style="font-size:20px;font-weight:800">${s.completed_tasks}/${s.total_tasks}</div>
              <div style="font-size:12px;color:var(--text-muted)">Grade: <strong style="color:${color}">${s.score_grade}</strong></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Scores row -->
      ${(r.scores || []).length ? `
      <div class="card">
        <div class="section-title" style="margin-bottom:12px">📊 Score Breakdown</div>
        <div style="display:flex;flex-direction:column;gap:8px">
          ${r.scores.map(s => `
            <div style="display:flex;align-items:center;gap:12px;padding:10px;background:var(--bg-elevated);border-radius:var(--radius)">
              <div style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted)">${s.task_id.slice(0,10)}...</div>
              <div style="flex:1;display:flex;gap:12px;flex-wrap:wrap;font-size:12px">
                <span>L${s.level} → <strong>${s.outcome_score}</strong></span>
                <span style="color:var(--green)">+${s.velocity} vel</span>
                <span style="color:var(--red)">-${s.stability_penalty} stab</span>
                <span style="color:var(--yellow)">-${s.ai_penalty} AI</span>
              </div>
              <div style="font-size:20px;font-weight:800;color:${scoreGrade(s.final_score).color}">${s.final_score}</div>
            </div>`).join('')}
        </div>
      </div>` : ''}

      <!-- Loop detection -->
      ${(r.loop_detection || []).some(l => l.loop_detected) ? `
      <div class="card" style="border-color:rgba(239,68,68,.25)">
        <div class="section-title" style="margin-bottom:12px;color:var(--red)">⚠️ Loop Detection</div>
        ${r.loop_detection.filter(l => l.loop_detected).map(l => `
          <div style="background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.15);border-radius:var(--radius);padding:12px;margin-bottom:8px">
            <div style="font-size:13px;font-weight:600">${l.loop_type} · severity ${l.severity}</div>
            ${l.evidence?.slice(0,2).map(e => `<div style="font-size:12px;color:var(--text-muted);margin-top:4px">• ${e}</div>`).join('')||''}
          </div>`).join('')}
      </div>` : ''}

      <!-- Analysis -->
      ${a.bottlenecks?.length ? `
      <div class="card">
        <div class="section-title" style="margin-bottom:12px">🧠 AI Analysis</div>
        <div style="display:flex;flex-direction:column;gap:12px">
          ${a.bottlenecks.slice(0,2).map(b => `
            <div style="padding:14px;background:var(--bg-elevated);border-radius:var(--radius);border-left:3px solid var(--purple)">
              <div style="font-weight:600;font-size:13px;margin-bottom:4px">${b.title}</div>
              <div style="font-size:12px;margin-bottom:6px"><span class="badge badge-red">${b.classification}</span> <span class="badge badge-yellow">${b.impact}</span></div>
              <div style="font-size:12px;color:var(--text-secondary)">${b.evidence}</div>
            </div>`).join('')}
          ${a.root_cause ? `<div style="padding:14px;background:var(--bg-elevated);border-radius:var(--radius)"><div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">ROOT CAUSE</div><div style="font-size:13px">${a.root_cause}</div></div>` : ''}
          ${a.corrective_actions?.length ? `
            <div>
              <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px">CORRECTIVE ACTIONS</div>
              ${a.corrective_actions.slice(0,3).map((ac,i) => `<div style="padding:10px;background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.15);border-radius:var(--radius);margin-bottom:6px;font-size:13px"><strong style="color:var(--green)">${i+1}.</strong> ${ac.action}</div>`).join('')}
            </div>` : ''}
        </div>
      </div>` : ''}
    </div>`;
}


/* ════════════════════════════════════════════════════════════════════════════
   METRICS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.metrics = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="flex gap-4" style="margin-bottom:20px;flex-wrap:wrap">
      <button class="btn btn-primary" onclick="openModal('modal-manual-score')">🎯 Submit Manual Score</button>
      <button class="btn btn-secondary" id="btn-tune" onclick="runTuning()">🔧 Run Adaptive Tuning</button>
      <button class="btn btn-secondary" onclick="submitLoopFeedback()">🔄 Loop Feedback</button>
      <button class="btn btn-secondary" onclick="replayWebhooks()">🔁 Replay Failed Webhooks</button>
    </div>
    <div id="metrics-content"><div class="skeleton" style="height:500px;border-radius:var(--radius-lg)"></div></div>
  </div>`;
  loadMetrics();
};

async function loadMetrics() {
  const el = document.getElementById('metrics-content');
  try {
    const [pub, priv, tunelog, wh, proxy] = await Promise.allSettled([
      api.getMetrics(),
      api.get('/metrics/').catch(() => null),
      api.get('/metrics/tune/log').catch(() => null),
      api.get('/metrics/webhook/stats').catch(() => null),
      api.get('/metrics/proxy/coverage').catch(() => null),
    ]);

    const m  = priv.value || pub.value || {};
    const tl = tunelog.value || {};
    const whs = wh.value?.stats || {};
    const pc = proxy.value?.coverage || {};

    const acc = m.acceptance_criteria || {};
    const cri = [
      ['TASK_ID Coverage', acc.task_id_coverage_pct],
      ['Score Deviation', acc.score_deviation_points],
      ['Loop FP Rate', acc.loop_fp_rate],
      ['Proxy Coverage', acc.proxy_coverage_pct],
    ];

    el.innerHTML = `
      <!-- Acceptance criteria -->
      <div class="card" style="margin-bottom:16px">
        <div class="section-title" style="margin-bottom:16px">🎯 Acceptance Criteria</div>
        <div class="grid-4">
          ${cri.map(([label, c]) => {
            if (!c) return `<div class="stat-card"><div class="stat-label">${label}</div><div class="stat-value" style="color:var(--text-muted)">—</div></div>`;
            const ok = c.ok;
            return `
              <div class="stat-card" style="border-color:${ok ? 'rgba(16,185,129,.25)' : 'rgba(239,68,68,.25)'}">
                <div class="stat-label">${label}</div>
                <div class="stat-value" style="color:${ok ? 'var(--green)' : 'var(--red)'}">${c.value !== null && c.value !== undefined ? (typeof c.value === 'number' ? c.value.toFixed(1) : c.value) : '—'}</div>
                <div class="stat-delta ${ok ? 'delta-up' : 'delta-down'}">${ok ? '✓ Pass' : '✗ Fail'} (thresh: ${c.threshold})</div>
              </div>`;
          }).join('')}
        </div>
      </div>

      <div class="grid-2" style="margin-bottom:16px">
        <!-- Scoring stats -->
        <div class="card">
          <div class="section-title" style="margin-bottom:14px">📊 Scoring Stats</div>
          ${renderMetricSection(m.scoring)}
        </div>

        <!-- Loop detection -->
        <div class="card">
          <div class="section-title" style="margin-bottom:14px">🔄 Loop Detection</div>
          ${renderMetricSection(m.loop_detection)}
          <div style="margin-top:12px">
            <button class="btn btn-sm btn-secondary w-full" onclick="submitLoopFeedback()">Submit Loop Feedback</button>
          </div>
        </div>
      </div>

      <div class="grid-2" style="margin-bottom:16px">
        <!-- Webhook stats -->
        <div class="card">
          <div class="section-title" style="margin-bottom:14px">🔔 Webhook Durability</div>
          <div style="display:flex;flex-direction:column;gap:8px;font-size:13px">
            ${Object.entries(whs).map(([k,v]) => `<div class="flex justify-between"><span style="color:var(--text-muted)">${k}</span><strong>${v}</strong></div>`).join('') || '<div style="color:var(--text-muted)">No data</div>'}
          </div>
          <button class="btn btn-sm btn-secondary w-full" style="margin-top:12px" onclick="replayWebhooks()">🔁 Replay Failed</button>
        </div>

        <!-- Proxy coverage -->
        <div class="card">
          <div class="section-title" style="margin-bottom:14px">🤖 Proxy Coverage</div>
          ${pc.coverage_pct !== undefined ? `
            <div style="text-align:center;margin-bottom:12px">
              ${renderScoreRing(Math.round(pc.coverage_pct), 80)}
            </div>
            <div style="font-size:12px;color:var(--text-muted)">
              ${pc.proxy_events} proxy events / ${pc.total_ai_events} total AI events today
            </div>
            ${pc.warning ? '<div style="margin-top:8px;padding:8px;background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.2);border-radius:var(--radius);font-size:12px;color:var(--red)">⚠️ Coverage below 80% threshold</div>' : ''}
          ` : '<div style="color:var(--text-muted);font-size:13px">No proxy data yet</div>'}
        </div>
      </div>

      <!-- Tuning log -->
      <div class="card">
        <div class="section-title" style="margin-bottom:14px">🔧 Adaptive Tuning Log</div>
        ${tl.entries > 0 ? `
          <div style="color:var(--text-muted);font-size:12px;margin-bottom:10px">${tl.entries} tuning run(s)</div>
          ${(tl.log || []).slice(-3).reverse().map(entry => `
            <div style="padding:12px;background:var(--bg-elevated);border-radius:var(--radius);margin-bottom:8px;font-size:12px">
              <div style="color:var(--text-muted);margin-bottom:6px">${fmtDateTime(entry.timestamp)}</div>
              ${Object.entries(entry.changes || {}).map(([k,v]) => `<div>• ${k}: <span style="color:var(--red)">${v.before}</span> → <span style="color:var(--green)">${v.after}</span></div>`).join('') || '<div style="color:var(--text-muted)">No changes (within thresholds)</div>'}
            </div>`).join('')}
        ` : '<div style="color:var(--text-muted);font-size:13px">No tuning runs yet. Submit 5+ manual scores first.</div>'}
        <button class="btn btn-sm btn-primary" style="margin-top:12px" id="btn-tune2" onclick="runTuning()">Run Adaptive Tuning</button>
      </div>`;
  } catch(e) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Error</div><div class="empty-desc">${e.message}</div></div>`;
  }
}

function renderMetricSection(data) {
  if (!data) return '<div style="color:var(--text-muted);font-size:13px">No data</div>';
  return Object.entries(data).filter(([k,v]) => v !== null && v !== undefined && typeof v !== 'object').map(([k,v]) =>
    `<div class="flex justify-between" style="font-size:13px;padding:6px 0;border-bottom:1px solid var(--border)"><span style="color:var(--text-muted)">${k.replace(/_/g,' ')}</span><strong>${typeof v === 'number' ? v.toFixed?.(2) ?? v : v}</strong></div>`
  ).join('');
}

async function runTuning() {
  const btns = ['btn-tune','btn-tune2'].map(id => document.getElementById(id)).filter(Boolean);
  btns.forEach(b => setLoading(b, true));
  try {
    const r = await api.post('/metrics/tune', { force: false });
    if (r.tuned) {
      toast(`Tuning complete: ${r.message}`, 'success');
      loadMetrics();
    } else {
      toast(r.reason, 'warn');
    }
  } catch(e) { toast(e.message, 'error'); }
  finally { btns.forEach(b => setLoading(b, false)); }
}

async function replayWebhooks() {
  try {
    const r = await api.post('/metrics/webhook/replay', {});
    toast(`Replay triggered: ${r.task_id || 'queued'}`, 'success');
  } catch(e) { toast(e.message, 'error'); }
}

function submitLoopFeedback() {
  const taskId = prompt('Enter Task ID that was flagged as a loop:');
  if (!taskId) return;
  const wasLoop = confirm('Was it actually a loop?\n\nOK = Yes (real loop)\nCancel = No (false positive)');
  api.loopFeedback({ task_id: taskId, was_actual_loop: wasLoop })
    .then(r => toast(`Feedback recorded. FP rate: ${r.false_positive_rate ?? '—'}`, 'success'))
    .catch(e => toast(e.message, 'error'));
}


/* ════════════════════════════════════════════════════════════════════════════
   AI PROXY
══════════════════════════════════════════════════════════════════════════════*/
PAGES.proxy = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="api-url-bar">
      <div class="api-status dot dot-green"></div>
      Proxy routes to: <span>https://traceops-ai.onrender.com/proxy/{provider}</span>
    </div>

    <!-- Config note -->
    <div style="background:rgba(6,182,212,.06);border:1px solid rgba(6,182,212,.2);border-radius:var(--radius);padding:14px;margin-bottom:20px;font-size:13px">
      <strong style="color:var(--cyan-l)">How to use:</strong> Instead of calling OpenAI/Anthropic directly, send your request here with a <code style="background:var(--bg-elevated);padding:2px 6px;border-radius:4px">task_id</code>. TraceOps logs the prompt, response, tokens, latency, and efficiency automatically.
    </div>

    <div class="grid-2">
      <!-- OpenAI Proxy -->
      <div class="card">
        <div class="section-title" style="margin-bottom:16px">🤖 OpenAI Proxy</div>
        <div style="display:flex;flex-direction:column;gap:12px">
          <div class="form-group">
            <label class="form-label">Task ID</label>
            <input class="form-input" id="oai-task-id" placeholder="Paste your active task ID"/>
          </div>
          <div class="form-group">
            <label class="form-label">OpenAI API Key</label>
            <input class="form-input" id="oai-key" type="password" placeholder="sk-..."/>
          </div>
          <div class="form-group">
            <label class="form-label">Model</label>
            <select class="form-input form-select" id="oai-model">
              <option value="gpt-4o-mini">gpt-4o-mini (recommended)</option>
              <option value="gpt-4o">gpt-4o</option>
              <option value="gpt-4-turbo">gpt-4-turbo</option>
              <option value="gpt-3.5-turbo">gpt-3.5-turbo</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Prompt *</label>
            <textarea class="form-input form-textarea" id="oai-prompt" placeholder="Enter your prompt..."></textarea>
          </div>
          <button class="btn btn-primary" id="btn-oai" onclick="sendOpenAI()">🚀 Send via Proxy</button>
          <div id="oai-result" style="display:none"></div>
        </div>
      </div>

      <!-- Anthropic Proxy -->
      <div class="card">
        <div class="section-title" style="margin-bottom:16px">🧠 Anthropic Proxy</div>
        <div style="display:flex;flex-direction:column;gap:12px">
          <div class="form-group">
            <label class="form-label">Task ID</label>
            <input class="form-input" id="ant-task-id" placeholder="Paste your active task ID"/>
          </div>
          <div class="form-group">
            <label class="form-label">Anthropic API Key</label>
            <input class="form-input" id="ant-key" type="password" placeholder="sk-ant-..."/>
          </div>
          <div class="form-group">
            <label class="form-label">Model</label>
            <select class="form-input form-select" id="ant-model">
              <option value="claude-sonnet-4-20250514">claude-sonnet-4 (recommended)</option>
              <option value="claude-haiku-4-5-20251001">claude-haiku-4.5</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Prompt *</label>
            <textarea class="form-input form-textarea" id="ant-prompt" placeholder="Enter your prompt..."></textarea>
          </div>
          <button class="btn btn-primary" id="btn-ant" onclick="sendAnthropic()">🚀 Send via Proxy</button>
          <div id="ant-result" style="display:none"></div>
        </div>
      </div>
    </div>

    <!-- How to use curl -->
    <div class="card" style="margin-top:16px">
      <div class="section-title" style="margin-bottom:12px">📋 Use from Terminal (curl)</div>
      <div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius);padding:16px;font-family:var(--font-mono);font-size:12px;color:var(--cyan-l);overflow-x:auto">
<pre>curl -X POST https://traceops-ai.onrender.com/proxy/openai \\
  -H "Content-Type: application/json" \\
  -H "X-OpenAI-Key: sk-..." \\
  -d '{
    "task_id": "YOUR_TASK_ID",
    "payload": {
      "model": "gpt-4o-mini",
      "messages": [{"role": "user", "content": "Your prompt here"}]
    }
  }'</pre>
      </div>
    </div>
  </div>`;
};

async function sendOpenAI() {
  const task_id = document.getElementById('oai-task-id').value.trim();
  const key     = document.getElementById('oai-key').value.trim();
  const model   = document.getElementById('oai-model').value;
  const prompt  = document.getElementById('oai-prompt').value.trim();
  if (!prompt) { toast('Prompt is required', 'error'); return; }

  const btn = document.getElementById('btn-oai');
  const resultEl = document.getElementById('oai-result');
  setLoading(btn, true);
  resultEl.style.display = 'none';
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (key) headers['X-OpenAI-Key'] = key;
    const res = await fetch(`${API_BASE}/proxy/openai`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ task_id: task_id || undefined, payload: { model, messages: [{ role: 'user', content: prompt }] } })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    const text = data.choices?.[0]?.message?.content || JSON.stringify(data);
    resultEl.style.display = 'block';
    resultEl.innerHTML = `<div style="background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.2);border-radius:var(--radius);padding:14px;font-size:13px;color:var(--text-secondary);white-space:pre-wrap;max-height:200px;overflow-y:auto">${text}</div>`;
    toast('Response received & logged', 'success');
  } catch(e) { toast(e.message, 'error'); }
  finally { setLoading(btn, false); }
}

async function sendAnthropic() {
  const task_id = document.getElementById('ant-task-id').value.trim();
  const key     = document.getElementById('ant-key').value.trim();
  const model   = document.getElementById('ant-model').value;
  const prompt  = document.getElementById('ant-prompt').value.trim();
  if (!prompt) { toast('Prompt is required', 'error'); return; }

  const btn = document.getElementById('btn-ant');
  const resultEl = document.getElementById('ant-result');
  setLoading(btn, true);
  resultEl.style.display = 'none';
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (key) headers['X-Anthropic-Key'] = key;
    const res = await fetch(`${API_BASE}/proxy/anthropic`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ task_id: task_id || undefined, payload: { model, max_tokens: 1000, messages: [{ role: 'user', content: prompt }] } })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    const text = data.content?.[0]?.text || JSON.stringify(data);
    resultEl.style.display = 'block';
    resultEl.innerHTML = `<div style="background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.2);border-radius:var(--radius);padding:14px;font-size:13px;color:var(--text-secondary);white-space:pre-wrap;max-height:200px;overflow-y:auto">${text}</div>`;
    toast('Response received & logged', 'success');
  } catch(e) { toast(e.message, 'error'); }
  finally { setLoading(btn, false); }
}


/* ════════════════════════════════════════════════════════════════════════════
   DEPLOYMENTS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.deployments = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="card" style="margin-bottom:20px">
      <div class="section-title" style="margin-bottom:16px">🚀 Validate Deployment</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px">Run multi-level validation (L1–L4) against your deployed service. Required before claiming Level 5.</p>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="form-group">
          <label class="form-label">Service URL *</label>
          <input class="form-input" id="dep-url" placeholder="https://your-app.onrender.com"/>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Functional Path</label>
            <input class="form-input" id="dep-path" value="/health" placeholder="/health"/>
          </div>
          <div class="form-group">
            <label class="form-label">Expected Status Code</label>
            <input class="form-input" id="dep-status" type="number" value="200"/>
          </div>
        </div>
        <div class="form-group">
          <label class="form-label">Expected JSON Keys (comma-separated, optional)</label>
          <input class="form-input" id="dep-keys" placeholder="status,version"/>
        </div>
        <button class="btn btn-primary" id="btn-validate" onclick="runValidation()">🚀 Run Validation</button>
      </div>
    </div>
    <div id="validation-result"></div>

    <!-- Log deploy event -->
    <div class="card" style="margin-top:20px">
      <div class="section-title" style="margin-bottom:14px">📥 Log Deploy Event</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <input class="form-input" id="dep-task" placeholder="Task ID" style="flex:1;min-width:180px"/>
        <input class="form-input" id="dep-platform" placeholder="Platform (e.g. render)" style="flex:1;min-width:140px"/>
        <select class="form-input form-select" id="dep-result" style="width:130px">
          <option value="success">✅ success</option>
          <option value="failed">❌ failed</option>
          <option value="error">⚠️ error</option>
        </select>
        <button class="btn btn-secondary" onclick="logDeployEvent()">Log</button>
      </div>
    </div>
  </div>`;
};

async function runValidation() {
  const url    = document.getElementById('dep-url').value.trim();
  const path   = document.getElementById('dep-path').value.trim() || '/health';
  const status = parseInt(document.getElementById('dep-status').value) || 200;
  const keysRaw = document.getElementById('dep-keys').value.trim();
  const keys   = keysRaw ? keysRaw.split(',').map(k => k.trim()).filter(Boolean) : [];
  if (!url) { toast('URL is required', 'error'); return; }

  const btn = document.getElementById('btn-validate');
  const resultEl = document.getElementById('validation-result');
  setLoading(btn, true);
  resultEl.innerHTML = '<div class="skeleton" style="height:200px;border-radius:var(--radius-lg)"></div>';
  try {
    const r = await api.validateDeploy({ url, functional_path: path, functional_expected_status: status, functional_expected_keys: keys.length ? keys : undefined });
    const statusColors = { success: 'var(--green)', partial: 'var(--yellow)', failed: 'var(--red)' };
    const statusIcons  = { success: '✅', partial: '⚠️', failed: '❌' };
    resultEl.innerHTML = `
      <div class="card" style="border-color:${r.status === 'success' ? 'rgba(16,185,129,.3)' : r.status === 'partial' ? 'rgba(245,158,11,.3)' : 'rgba(239,68,68,.3)'}">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
          <div style="font-size:32px">${statusIcons[r.status] || '?'}</div>
          <div>
            <div style="font-family:var(--font-display);font-size:20px;font-weight:800;color:${statusColors[r.status]}">${r.status.toUpperCase()}</div>
            <div style="font-size:13px;color:var(--text-secondary)">${r.summary}</div>
          </div>
          <div style="margin-left:auto;font-size:28px;font-weight:800;font-family:var(--font-display);color:${statusColors[r.status]}">${Math.round(r.score * 100)}%</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:8px">
          ${(r.checks || []).map(c => `
            <div style="display:flex;align-items:center;gap:10px;padding:10px;background:var(--bg-elevated);border-radius:var(--radius)">
              <div style="font-size:16px">${c.success ? '✅' : '❌'}</div>
              <div style="flex:1">
                <div style="font-size:12px;font-family:var(--font-mono)">${c.path}</div>
                ${c.error ? `<div style="font-size:11px;color:var(--red);margin-top:2px">${c.error}</div>` : ''}
              </div>
              <div style="font-size:12px;color:var(--text-muted)">${c.status_code || '—'} · ${c.latency_ms}ms</div>
            </div>`).join('')}
        </div>
        ${r.validation_level >= 2 ? '<div style="margin-top:12px;padding:10px;background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.2);border-radius:var(--radius);font-size:12px;color:var(--green)">✅ Level 5 gate: deployment validated (L'+r.validation_level+'). You may claim Level 5.</div>' : '<div style="margin-top:12px;padding:10px;background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.2);border-radius:var(--radius);font-size:12px;color:var(--red)">❌ Level 5 gate: validation did not pass L2. Fix issues before claiming Level 5.</div>'}
      </div>`;
    toast(`Validation: ${r.status}`, r.status === 'success' ? 'success' : r.status === 'partial' ? 'warn' : 'error');
  } catch(e) {
    resultEl.innerHTML = `<div class="card"><div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Validation error</div><div class="empty-desc">${e.message}</div></div></div>`;
  }
  finally { setLoading(btn, false); }
}

async function logDeployEvent() {
  const task_id  = document.getElementById('dep-task').value.trim();
  const platform = document.getElementById('dep-platform').value.trim() || 'manual';
  const status   = document.getElementById('dep-result').value;
  try {
    await api.ingestDeploy({ task_id: task_id || undefined, platform, status, timestamp: new Date().toISOString() });
    toast(`Deploy event logged: ${status}`, status === 'success' ? 'success' : 'warn');
  } catch(e) { toast(e.message, 'error'); }
}


/* ════════════════════════════════════════════════════════════════════════════
   SCHEDULER
══════════════════════════════════════════════════════════════════════════════*/
PAGES.scheduler = async function(el) {
  el.innerHTML = `
  <div class="slide-up">
    <div class="grid-2" style="margin-bottom:20px">
      <div class="card" id="worker-health"><div class="section-title" style="margin-bottom:14px">🩺 Worker Health</div><div class="skeleton" style="height:120px"></div></div>
      <div class="card">
        <div class="section-title" style="margin-bottom:14px">⚡ Manual Trigger</div>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:14px">Use when Celery beat is not running (free tier restart).</p>
        <div style="display:flex;flex-direction:column;gap:8px">
          ${[['daily_report','📋 Daily Report'],['fetch_git','🐙 Fetch Git Events'],['retry_webhooks','🔁 Retry Webhooks']].map(([job,label]) => `
            <button class="btn btn-secondary w-full" onclick="triggerJob('${job}')">${label}</button>`).join('')}
        </div>
      </div>
    </div>
    <div class="card" id="missed-schedules"><div class="section-title" style="margin-bottom:14px">⚠️ Missed Schedules</div><div class="skeleton" style="height:100px"></div></div>
  </div>`;

  // Load health
  try {
    const h = await api.healthDeep();
    const wc = h.components?.celery_worker || {};
    document.getElementById('worker-health').innerHTML = `
      <div class="section-title" style="margin-bottom:14px">🩺 Worker Health</div>
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
        <div class="dot ${wc.alive ? 'dot-green dot-pulse' : 'dot-red'}" style="width:12px;height:12px"></div>
        <div style="font-size:16px;font-weight:700;color:${wc.alive ? 'var(--green)' : 'var(--red)'}">${wc.alive ? 'Worker Online' : 'Worker Offline'}</div>
      </div>
      ${wc.workers?.length ? `<div style="font-size:12px;font-family:var(--font-mono);color:var(--text-muted)">${wc.workers.join('<br/>')}</div>` : ''}
      ${wc.error ? `<div style="font-size:12px;color:var(--red);margin-top:8px">Error: ${wc.error}</div>` : ''}
      ${!wc.alive ? '<div style="margin-top:10px;font-size:12px;color:var(--yellow)">💡 Use Manual Trigger above to run scheduled jobs</div>' : ''}`;
  } catch(e) {}

  // Load missed schedules
  try {
    const r = await api.get('/worker/scheduler/missed').catch(() => ({ missed_count: 0, recent_missed: [] }));
    const ms = document.getElementById('missed-schedules');
    ms.innerHTML = `
      <div class="section-title" style="margin-bottom:14px">⚠️ Missed Schedules <span class="badge ${r.missed_count > 0 ? 'badge-red' : 'badge-green'}">${r.missed_count} missed</span></div>
      ${r.recent_missed?.length ? r.recent_missed.map(m => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px">
          <span class="badge badge-red">MISSED</span>
          <span style="font-weight:600">${m.job}</span>
          <span style="color:var(--text-muted)">${fmtDateTime(m.triggered_at)}</span>
          ${m.error ? `<span style="color:var(--red);font-size:12px">${m.error}</span>` : ''}
        </div>`).join('')
      : '<div style="color:var(--text-muted);font-size:13px">No missed schedules ✅</div>'}`;
  } catch(e) {}
};

async function triggerJob(job) {
  try {
    const r = await api.post('/worker/scheduler/trigger', { job, force: false });
    toast(`Job triggered: ${job}`, 'success');
  } catch(e) { toast(e.message, 'error'); }
}


/* ════════════════════════════════════════════════════════════════════════════
   SETTINGS
══════════════════════════════════════════════════════════════════════════════*/
PAGES.settings = async function(el) {
  const savedApiBase = localStorage.getItem('TRACEOPS_API') || 'https://traceops-ai.onrender.com';
  const savedKey     = localStorage.getItem('TRACEOPS_METRICS_KEY') || '';

  el.innerHTML = `
  <div class="slide-up">
    <!-- API Configuration -->
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-bottom:16px">🔧 API Configuration</div>
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="form-group">
          <label class="form-label">API Base URL</label>
          <div style="display:flex;gap:8px">
            <input class="form-input" id="s-api-url" value="${savedApiBase}" style="flex:1"/>
            <button class="btn btn-secondary" onclick="saveApiUrl()">Save</button>
            <button class="btn btn-secondary" onclick="testApi()">Test</button>
          </div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px">Current: <span style="font-family:var(--font-mono);color:var(--cyan)">${API_BASE}</span></div>
        </div>
        <div class="form-group">
          <label class="form-label">Metrics API Key (X-Metrics-Key)</label>
          <div style="display:flex;gap:8px">
            <input class="form-input" id="s-metrics-key" type="password" value="${savedKey}" placeholder="Your SECRET_KEY from .env" style="flex:1"/>
            <button class="btn btn-secondary" onclick="saveMetricsKey()">Save</button>
          </div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px">Required to access /metrics/ (full) and /metrics/tune endpoints</div>
        </div>
      </div>
    </div>

    <!-- GitHub webhook setup -->
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-bottom:12px">🐙 GitHub Webhook Setup</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:14px">Add this webhook to your GitHub repo to auto-ingest commits.</p>
      <div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius);padding:12px;font-family:var(--font-mono);font-size:12px;color:var(--cyan-l);margin-bottom:10px">
        ${API_BASE}/event/github
      </div>
      <div style="font-size:12px;color:var(--text-muted)">GitHub → Settings → Webhooks → Add webhook → Content type: application/json → Event: push</div>
    </div>

    <!-- Commit tag format -->
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-bottom:12px">📝 Commit Tag Format</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">Add your Task ID to every commit message for automatic correlation.</p>
      <div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:var(--radius);padding:12px;font-family:var(--font-mono);font-size:13px;color:var(--purple-l)">
        git commit -m "feat: your message [TRO-&lt;task-id&gt;]"
      </div>
    </div>

    <!-- System info -->
    <div class="card">
      <div class="section-title" style="margin-bottom:14px">ℹ️ System Info</div>
      <div id="sys-info"><div class="skeleton" style="height:80px"></div></div>
    </div>
  </div>`;

  // Load system info
  try {
    const h = await api.healthDeep();
    document.getElementById('sys-info').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:8px;font-size:13px">
        <div class="flex justify-between"><span style="color:var(--text-muted)">API Version</span><strong>${h.components ? 'v1.0.0' : '—'}</strong></div>
        <div class="flex justify-between"><span style="color:var(--text-muted)">API URL</span><span style="font-family:var(--font-mono);font-size:12px;color:var(--cyan)">${API_BASE}</span></div>
        <div class="flex justify-between"><span style="color:var(--text-muted)">Database</span><span style="color:${h.components?.database?.alive ? 'var(--green)' : 'var(--red)'}">${h.components?.database?.alive ? 'Connected (Neon)' : 'Disconnected'}</span></div>
        <div class="flex justify-between"><span style="color:var(--text-muted)">Redis</span><span style="color:${h.components?.redis?.alive ? 'var(--green)' : 'var(--red)'}">${h.components?.redis?.alive ? 'Connected (Upstash)' : 'Disconnected'}</span></div>
        <div class="flex justify-between"><span style="color:var(--text-muted)">Worker</span><span style="color:${h.components?.celery_worker?.alive ? 'var(--green)' : 'var(--yellow)'}">${h.components?.celery_worker?.alive ? 'Running' : 'Offline (use manual trigger)'}</span></div>
      </div>`;
  } catch(e) { document.getElementById('sys-info').innerHTML = `<div style="color:var(--red);font-size:13px">Cannot reach API: ${e.message}</div>`; }
};

function saveApiUrl() {
  const url = document.getElementById('s-api-url').value.trim().replace(/\/$/, '');
  if (!url) return;
  localStorage.setItem('TRACEOPS_API', url);
  window.API_BASE = url;
  toast('API URL saved. Reload page to apply.', 'success');
}

function saveMetricsKey() {
  const key = document.getElementById('s-metrics-key').value.trim();
  localStorage.setItem('TRACEOPS_METRICS_KEY', key);
  toast('Metrics key saved', 'success');
}

async function testApi() {
  const url = document.getElementById('s-api-url').value.trim();
  try {
    const r = await fetch(`${url}/health`);
    const d = await r.json();
    toast(`API OK: ${d.service} v${d.version}`, 'success');
  } catch(e) { toast(`Cannot reach ${url}: ${e.message}`, 'error'); }
}

// Use saved API URL on load
window.API_BASE = localStorage.getItem('TRACEOPS_API') || 'https://traceops-ai.onrender.com';
