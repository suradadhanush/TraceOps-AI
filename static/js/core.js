/* ── Config ────────────────────────────────────────────────────────────────── */
const API_BASE = window.TRACEOPS_API || localStorage.getItem('TRACEOPS_API') || '';

/* ── Current user (set on app load) ───────────────────────────────────────── */
let CURRENT_USER = null;

/* ── API Client ────────────────────────────────────────────────────────────── */
const api = {
  async request(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' }, credentials: 'include' };
    if (body) opts.body = JSON.stringify(body);
    try {
      const res = await fetch(`${API_BASE}${path}`, opts);
      if (res.status === 401) { window.location.href = '/auth/login'; throw new Error('Not authenticated'); }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (e) {
      if (e.name === 'TypeError') throw new Error('Cannot reach API.');
      throw e;
    }
  },
  get:    (p)    => api.request('GET', p),
  post:   (p, b) => api.request('POST', p, b),
  delete: (p)    => api.request('DELETE', p),

  /* Auth */
  getMe:   ()  => api.get('/auth/me'),
  logout:  ()  => api.post('/auth/logout'),

  /* User */
  getDashboard: () => api.get('/user/dashboard'),
  getStats:     () => api.get('/user/stats'),
  getActivity:  (q) => api.get(`/user/activity${q||''}`),
  getRepos:     () => api.get('/user/repositories'),

  /* Integrations */
  getCatalog:       () => api.get('/integrations/catalog'),
  getIntegrations:  () => api.get('/integrations/'),
  connectApiKey:    (p, b) => api.post(`/integrations/connect/api_key/${p}`, b),
  disconnect:       (p)    => api.delete(`/integrations/${p}`),
  syncIntegration:  (p)    => api.post(`/integrations/${p}/sync`),

  /* Tasks */
  startTask:  (b) => api.post('/task/start', b),
  endTask:    (b) => api.post('/task/end', b),
  listTasks:  (s) => api.get(`/task/${s ? '?status='+s : ''}`),
  getTask:    (id)=> api.get(`/task/${id}`),

  /* Events */
  ingestEvent:  (b) => api.post('/event/', b),
  listEvents:   (q) => api.get(`/event/${q||''}`),
  ingestDeploy: (b) => api.post('/event/deploy', b),
  ingestError:  (b) => api.post('/event/error', b),

  /* Reports */
  dailyReport:    ()  => api.get('/report/daily'),
  dailyMarkdown:  ()  => api.get('/report/daily/markdown'),
  generateReport: ()  => api.post('/report/generate'),
  validateDeploy: (b) => api.post('/report/validate', b),

  /* Metrics */
  getMetrics:        () => api.get('/metrics/public'),
  submitManualScore: (b)=> api.post('/metrics/score/manual', b),
  loopFeedback:      (b)=> api.post('/metrics/loop/feedback', b),

  /* Proxy */
  proxyOpenAI:    (b) => api.post('/proxy/openai', b),
  proxyAnthropic: (b) => api.post('/proxy/anthropic', b),

  /* Health */
  health:     () => api.get('/health'),
  healthDeep: () => api.get('/health/deep'),
};

/* ── Toast ─────────────────────────────────────────────────────────────────── */
function toast(msg, type = 'info', duration = 3500) {
  const c = document.getElementById('toast-container');
  if (!c) return;
  const icons = { success:'✅', error:'❌', info:'ℹ️', warn:'⚠️' };
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span>${icons[type]||icons.info}</span><span>${msg}</span>`;
  c.appendChild(el);
  setTimeout(() => { el.style.opacity='0'; el.style.transform='translateX(20px)'; el.style.transition='.3s'; setTimeout(()=>el.remove(),300); }, duration);
}

/* ── Modal ─────────────────────────────────────────────────────────────────── */
function openModal(id)  { const m=document.getElementById(id); if(m){m.style.display='flex';m.classList.add('fade-in');} }
function closeModal(id) { const m=document.getElementById(id); if(m) m.style.display='none'; }
document.addEventListener('click', e => { if(e.target.classList.contains('modal-overlay')) e.target.style.display='none'; });

/* ── Loading ───────────────────────────────────────────────────────────────── */
function setLoading(btn, loading) {
  if (!btn) return;
  if (loading) { btn._orig=btn.innerHTML; btn.innerHTML='<span class="spinner"></span>'; btn.disabled=true; }
  else { btn.innerHTML=btn._orig||btn.innerHTML; btn.disabled=false; }
}

/* ── Helpers ───────────────────────────────────────────────────────────────── */
function scoreGrade(s) {
  if(s>=80) return {grade:'A',color:'var(--green)'};
  if(s>=60) return {grade:'B',color:'var(--cyan)'};
  if(s>=40) return {grade:'C',color:'var(--yellow)'};
  if(s>=20) return {grade:'D',color:'var(--purple-l)'};
  return          {grade:'F',color:'var(--red)'};
}

function renderScoreRing(score, size=80) {
  const r=size/2-6, circ=2*Math.PI*r, fill=(score/100)*circ;
  const {grade,color}=scoreGrade(score);
  return `<div class="score-ring" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <circle cx="${size/2}" cy="${size/2}" r="${r}" stroke="rgba(255,255,255,.06)" stroke-width="5" fill="none"/>
      <circle cx="${size/2}" cy="${size/2}" r="${r}" stroke="${color}" stroke-width="5" fill="none"
        stroke-dasharray="${fill} ${circ}" stroke-linecap="round" style="filter:drop-shadow(0 0 6px ${color})"/>
    </svg>
    <div class="score-ring-value"><div style="font-size:${size*.22}px;color:${color}">${score}</div><div style="font-size:${size*.14}px;color:var(--text-muted);text-align:center">${grade}</div></div>
  </div>`;
}

function fmtDate(d)     { if(!d) return '—'; return new Date(d).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}); }
function fmtDateTime(d) { if(!d) return '—'; return new Date(d).toLocaleString('en-IN',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}); }
function timeAgo(d) {
  if(!d) return '—';
  const s=Math.floor((Date.now()-new Date(d))/1000);
  if(s<60) return `${s}s ago`; if(s<3600) return `${Math.floor(s/60)}m ago`;
  if(s<86400) return `${Math.floor(s/3600)}h ago`; return `${Math.floor(s/86400)}d ago`;
}
function duration(s,e) {
  if(!s||!e) return '—';
  const sec=Math.floor((new Date(e)-new Date(s))/1000);
  if(sec<60) return `${sec}s`; if(sec<3600) return `${Math.floor(sec/60)}m`; return `${Math.floor(sec/3600)}h ${Math.floor((sec%3600)/60)}m`;
}
function eventBadge(type) {
  const map={commit:['badge-purple','⟨/⟩'],deploy:['badge-blue','🚀'],ai:['badge-cyan','🤖'],error:['badge-red','⚠'],pr:['badge-green','↗']};
  const [cls,icon]=map[type]||['badge-purple','•'];
  return `<span class="badge ${cls}">${icon} ${type}</span>`;
}
function statusBadge(status) {
  const m={active:'badge-green',completed:'badge-blue',failed:'badge-red',pending:'badge-yellow',success:'badge-green',partial:'badge-yellow',connected:'badge-green',disconnected:'badge-red',error:'badge-red'};
  return `<span class="badge ${m[status]||'badge-purple'}">${status}</span>`;
}

async function copyToClipboard(text) {
  try { await navigator.clipboard.writeText(text); toast('Copied','success',1500); } catch { toast('Copy failed','error'); }
}

/* ── User avatar ───────────────────────────────────────────────────────────── */
function renderAvatar(user, size=32) {
  if (user?.avatar_url) {
    return `<img src="${user.avatar_url}" width="${size}" height="${size}" style="border-radius:50%;object-fit:cover" alt="${user.name||'User'}"/>`;
  }
  const initials = (user?.name||user?.email||'U').slice(0,1).toUpperCase();
  return `<div style="width:${size}px;height:${size}px;border-radius:50%;background:linear-gradient(135deg,var(--purple),var(--blue));display:flex;align-items:center;justify-content:center;font-family:var(--font-display);font-weight:700;font-size:${size*.45}px">${initials}</div>`;
}

/* ── Sidebar ───────────────────────────────────────────────────────────────── */
function initSidebar() {
  const sidebar=document.getElementById('sidebar');
  const overlay=document.getElementById('sidebar-overlay');
  document.getElementById('menu-btn')?.addEventListener('click',()=>{sidebar?.classList.toggle('open');overlay?.classList.toggle('show');});
  overlay?.addEventListener('click',()=>{sidebar?.classList.remove('open');overlay?.classList.remove('show');});
}

/* ── Init ──────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => { initSidebar(); });
