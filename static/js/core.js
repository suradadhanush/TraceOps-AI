/* ── Config ──────────────────────────────────────────────────────────────── */
const API_BASE = window.TRACEOPS_API || 'https://traceops-ai.onrender.com';

/* ── State ───────────────────────────────────────────────────────────────── */
const state = {
  tasks:   [],
  events:  [],
  reports: {},
  metrics: {},
  loading: false,
};

/* ── API Client ──────────────────────────────────────────────────────────── */
const api = {
  async request(method, path, body = null) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    try {
      const res = await fetch(`${API_BASE}${path}`, opts);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (e) {
      if (e.name === 'TypeError') throw new Error('Cannot reach API. Check connection.');
      throw e;
    }
  },
  get:    (p)    => api.request('GET', p),
  post:   (p, b) => api.request('POST', p, b),
  patch:  (p, b) => api.request('PATCH', p, b),
  delete: (p)    => api.request('DELETE', p),

  /* Tasks */
  startTask:  (b) => api.post('/task/start', b),
  endTask:    (b) => api.post('/task/end', b),
  listTasks:  (s) => api.get(`/task/${s ? '?status=' + s : ''}`),
  getTask:    (id)=> api.get(`/task/${id}`),

  /* Events */
  ingestEvent: (b) => api.post('/event/', b),
  listEvents:  (q) => api.get(`/event/${q || ''}`),
  ingestDeploy:(b) => api.post('/event/deploy', b),
  ingestError: (b) => api.post('/event/error', b),

  /* Reports */
  dailyReport:   ()  => api.get('/report/daily'),
  dailyMarkdown: ()  => api.get('/report/daily/markdown'),
  generateReport:()  => api.post('/report/generate'),
  validateDeploy:(b) => api.post('/report/validate', b),

  /* Metrics */
  getMetrics:       ()  => api.get('/metrics/public'),
  submitManualScore:(b) => api.post('/metrics/score/manual', b),
  loopFeedback:     (b) => api.post('/metrics/loop/feedback', b),

  /* Proxy */
  proxyOpenAI:    (b) => api.post('/proxy/openai', b),
  proxyAnthropic: (b) => api.post('/proxy/anthropic', b),

  /* Health */
  health:     ()  => api.get('/health'),
  healthDeep: ()  => api.get('/health/deep'),
};

/* ── Toast ───────────────────────────────────────────────────────────────── */
function toast(msg, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const icons = { success: '✅', error: '❌', info: 'ℹ️', warn: '⚠️' };
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span>${icons[type] || icons.info}</span><span>${msg}</span>`;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(20px)'; el.style.transition = '.3s'; setTimeout(() => el.remove(), 300); }, duration);
}

/* ── Modal ───────────────────────────────────────────────────────────────── */
function openModal(id) {
  const m = document.getElementById(id);
  if (m) { m.style.display = 'flex'; m.classList.add('fade-in'); }
}
function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.style.display = 'none';
}
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.style.display = 'none';
  }
});

/* ── Loading ─────────────────────────────────────────────────────────────── */
function setLoading(btn, loading) {
  if (!btn) return;
  if (loading) {
    btn._orig = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span>`;
    btn.disabled = true;
  } else {
    btn.innerHTML = btn._orig || btn.innerHTML;
    btn.disabled = false;
  }
}

/* ── Score grade ─────────────────────────────────────────────────────────── */
function scoreGrade(s) {
  if (s >= 80) return { grade: 'A', color: 'var(--green)' };
  if (s >= 60) return { grade: 'B', color: 'var(--cyan)' };
  if (s >= 40) return { grade: 'C', color: 'var(--yellow)' };
  if (s >= 20) return { grade: 'D', color: 'var(--purple-light)' };
  return          { grade: 'F', color: 'var(--red)' };
}

/* ── Score ring SVG ──────────────────────────────────────────────────────── */
function renderScoreRing(score, size = 80) {
  const r = (size / 2) - 6;
  const circ = 2 * Math.PI * r;
  const fill = (score / 100) * circ;
  const { grade, color } = scoreGrade(score);
  return `
  <div class="score-ring" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <circle cx="${size/2}" cy="${size/2}" r="${r}" stroke="rgba(255,255,255,0.06)" stroke-width="5" fill="none"/>
      <circle cx="${size/2}" cy="${size/2}" r="${r}" stroke="${color}" stroke-width="5" fill="none"
        stroke-dasharray="${fill} ${circ}" stroke-linecap="round"
        style="filter:drop-shadow(0 0 6px ${color})"/>
    </svg>
    <div class="score-ring-value">
      <div style="font-size:${size*0.22}px;color:${color}">${score}</div>
      <div style="font-size:${size*0.14}px;color:var(--text-muted);text-align:center">${grade}</div>
    </div>
  </div>`;
}

/* ── Mini sparkline ──────────────────────────────────────────────────────── */
function renderSparkline(data, color = 'var(--purple-light)') {
  const max = Math.max(...data, 1);
  return `<div class="mini-chart">
    ${data.map(v => `<div class="mini-bar" style="height:${Math.max((v/max)*100,8)}%;background:${color};opacity:0.7"></div>`).join('')}
  </div>`;
}

/* ── Format date ─────────────────────────────────────────────────────────── */
function fmtDate(d) {
  if (!d) return '—';
  const dt = new Date(d);
  return dt.toLocaleDateString('en-IN', { day:'numeric', month:'short', year:'numeric' });
}
function fmtTime(d) {
  if (!d) return '—';
  return new Date(d).toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit' });
}
function fmtDateTime(d) {
  if (!d) return '—';
  return `${fmtDate(d)} ${fmtTime(d)}`;
}
function timeAgo(d) {
  if (!d) return '—';
  const sec = Math.floor((Date.now() - new Date(d)) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec/60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec/3600)}h ago`;
  return `${Math.floor(sec/86400)}d ago`;
}

/* ── Duration ────────────────────────────────────────────────────────────── */
function duration(start, end) {
  if (!start || !end) return '—';
  const s = Math.floor((new Date(end) - new Date(start)) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s/60)}m`;
  return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`;
}

/* ── Level label ─────────────────────────────────────────────────────────── */
function levelLabel(l) {
  const labels = ['No Output', 'Draft', 'Working', 'Tested', 'Deployed', 'Shipped'];
  return labels[l] || l;
}

/* ── Event type badge ────────────────────────────────────────────────────── */
function eventBadge(type) {
  const map = {
    commit:  ['badge-purple', '⟨/⟩'],
    deploy:  ['badge-blue',   '🚀'],
    ai:      ['badge-cyan',   '🤖'],
    error:   ['badge-red',    '⚠'],
    pr:      ['badge-green',  '↗'],
    review:  ['badge-yellow', '👁'],
  };
  const [cls, icon] = map[type] || ['badge-purple', '•'];
  return `<span class="badge ${cls}">${icon} ${type}</span>`;
}

/* ── Status badge ────────────────────────────────────────────────────────── */
function statusBadge(status) {
  const map = {
    active:    'badge-green',
    completed: 'badge-blue',
    failed:    'badge-red',
    pending:   'badge-yellow',
    success:   'badge-green',
    partial:   'badge-yellow',
  };
  return `<span class="badge ${map[status] || 'badge-purple'}">${status}</span>`;
}

/* ── Tabs ────────────────────────────────────────────────────────────────── */
function initTabs(container) {
  const btns    = container.querySelectorAll('.tab-btn');
  const content = container.querySelector('.tab-content');
  btns.forEach(btn => {
    btn.addEventListener('click', () => {
      btns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (content) {
        content.querySelectorAll(':scope > div').forEach((p, i) => {
          p.classList.toggle('active', i === [...btns].indexOf(btn));
        });
      }
    });
  });
}

/* ── Router ──────────────────────────────────────────────────────────────── */
const router = {
  routes: {},
  register(path, fn) { this.routes[path] = fn; },
  navigate(path) {
    history.pushState({}, '', path);
    this.render(path);
  },
  render(path) {
    const handler = this.routes[path] || this.routes['/app/dashboard'];
    if (handler) handler();
    // update active nav
    document.querySelectorAll('.nav-item[data-route]').forEach(el => {
      el.classList.toggle('active', el.dataset.route === path);
    });
  },
  init() {
    window.addEventListener('popstate', () => this.render(location.pathname));
    document.addEventListener('click', e => {
      const a = e.target.closest('[data-route]');
      if (a && a.dataset.route.startsWith('/app/')) {
        e.preventDefault();
        this.navigate(a.dataset.route);
      }
    });
  }
};

/* ── Mobile sidebar toggle ───────────────────────────────────────────────── */
function initSidebar() {
  const sidebar  = document.getElementById('sidebar');
  const overlay  = document.getElementById('sidebar-overlay');
  const menuBtn  = document.getElementById('menu-btn');
  if (!sidebar) return;
  menuBtn?.addEventListener('click', () => {
    sidebar.classList.toggle('open');
    overlay.classList.toggle('show');
  });
  overlay?.addEventListener('click', () => {
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
  });
}

/* ── Animated counter ────────────────────────────────────────────────────── */
function animateCounter(el, target, suffix = '', duration = 1000) {
  const start = Date.now();
  const tick = () => {
    const elapsed = Date.now() - start;
    const progress = Math.min(elapsed / duration, 1);
    const ease = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(ease * target) + suffix;
    if (progress < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ── Copy to clipboard ───────────────────────────────────────────────────── */
async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied to clipboard', 'success', 1500);
  } catch { toast('Copy failed', 'error'); }
}

/* ── Init on load ────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  document.querySelectorAll('[data-tabs]').forEach(initTabs);
});
