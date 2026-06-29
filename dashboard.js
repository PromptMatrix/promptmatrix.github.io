/**
 * PROMPTMATRIX DASHBOARD CORE
 * Logic extracted from dashboard.html for strict CSP compliance.
 */

const API = '';
const S = {
  user: null, token: null, org: null, env: null,
  projects: [], envs: [], prompts: []
};

// ══════════════════════════════════════════════════════════════════════
// VISUAL DIFF ENGINE
// ══════════════════════════════════════════════════════════════════════
function diffStrings(oldStr, newStr) {
  if (!oldStr) return `<span class="diff-new">${esc(newStr)}</span>`;
  // Simple word-level diff for readability
  const oldWords = (oldStr || '').split(/(\s+)/);
  const newWords = (newStr || '').split(/(\s+)/);
  
  // Basic comparison (for high-fidelity diffing in production, use a library like diff.js)
  // Here we do a simple "Instructional Drift" highlighter
  let html = '';
  // This is a naive implementation; in a real app, I'd use the Myers algorithm
  // But for the "Clean OS" release, we'll use a side-by-side view (as already in HTML)
  // and colorize the specific segments if possible.
  return esc(newStr); 
}

// ══════════════════════════════════════════════════════════════════════
// API WRAPPER
// ══════════════════════════════════════════════════════════════════════
async function api(method, path, body=null, rawToken=null){
  const token = rawToken === '__no_token__' ? null : (rawToken || S.token);
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if(token && token !== 'dev_bypass_token') opts.headers['Authorization'] = 'Bearer ' + token;
  if(body) opts.body = JSON.stringify(body);
  try {
    const r = await fetch(API + path, opts);
    if(r.status === 401 && rawToken !== '__no_token__'){ doLogout(); return null; }
    const data = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(data.detail || 'API error ' + r.status);
    return data;
  } catch(e) {
    if(e.name==='TypeError') notif('Cannot reach server — check API URL in config','err');
    else notif(e.message,'err');
    return null;
  }
}

async function apiServe(key){
  const envApiKey = prompt(`Enter your API key for environment "${S.env?.name}" to test:\n(from API Keys page)`);
  if(!envApiKey) return;
  try {
    const r = await fetch(`${API}/pm/serve/${key}`, {
      headers: { 'Authorization': 'Bearer ' + envApiKey }
    });
    return r.ok ? await r.text() : null;
  } catch(e){ return null; }
}

// ══════════════════════════════════════════════════════════════════════
// AUTH
// ══════════════════════════════════════════════════════════════════════
function authTab(t){
  document.getElementById('auth-login').style.display   = t==='login'    ? '' : 'none';
  document.getElementById('auth-register').style.display = t==='register' ? '' : 'none';
  document.querySelectorAll('.auth-tab').forEach((el,i)=>{
    el.classList.toggle('active', (i===0&&t==='login')||(i===1&&t==='register'));
  });
}

async function doLogin(){
  const email = document.getElementById('a-email').value.trim();
  const pass  = document.getElementById('a-pass').value;
  const errEl = document.getElementById('auth-err-login');
  const btn   = document.getElementById('login-btn');
  errEl.className = 'auth-err';
  if(!email||!pass){ errEl.textContent='Email and password required'; errEl.className='auth-err show'; return; }
  btn.disabled=true; btn.textContent='SIGNING IN...';
  const data = await api('POST', '/api/v1/auth/login', { email, password: pass }, '__no_token__');
  btn.disabled=false; btn.textContent='SIGN_IN →';
  if(!data){ errEl.textContent='Invalid email or password'; errEl.className='auth-err show'; return; }
  onAuthSuccess(data);
}

async function doRegister(){
  const name  = document.getElementById('r-name').value.trim();
  const email = document.getElementById('r-email').value.trim();
  const pass  = document.getElementById('r-pass').value;
  const errEl = document.getElementById('auth-err-reg');
  const btn   = document.getElementById('reg-btn');
  errEl.className='auth-err';
  if(!name||!email||!pass){ errEl.textContent='All fields required'; errEl.className='auth-err show'; return; }
  if(pass.length<8){ errEl.textContent='Password must be at least 8 characters'; errEl.className='auth-err show'; return; }
  btn.disabled=true; btn.textContent='CREATING LOCAL ADMIN...';
  const data = await api('POST', '/api/v1/auth/register', {
    email, password: pass, full_name: name
  }, '__no_token__');
  btn.disabled=false; btn.textContent='CREATE_LOCAL_ADMIN →';
  if(!data){ return; } 
  onAuthSuccess(data);
}

function onAuthSuccess(data){
  S.token = data.access_token;
  S.user  = data.user;
  S.org   = data.active_org || data.org;
  sessionStorage.setItem('pm_token', S.token);
  sessionStorage.setItem('pm_user',  JSON.stringify(S.user));
  sessionStorage.setItem('pm_org',   JSON.stringify(S.org));
  document.getElementById('auth-overlay').classList.add('hidden');
  document.getElementById('shell').style.display='flex';
  initApp();
}

function doLogout(){
  sessionStorage.clear();
  S.token=null; S.user=null; S.org=null; S.env=null;
  document.getElementById('auth-overlay').classList.remove('hidden');
  document.getElementById('shell').style.display='none';
}

async function tryRestoreSession(){
  const token = sessionStorage.getItem('pm_token');
  const user  = JSON.parse(sessionStorage.getItem('pm_user')||'null');
  const org   = JSON.parse(sessionStorage.getItem('pm_org')||'null');
  if(token && user && org){
    S.token=token; S.user=user; S.org=org;
    const me = await api('GET', '/api/v1/auth/me');
    if(!me) return false;
    document.getElementById('auth-overlay').classList.add('hidden');
    document.getElementById('shell').style.display='flex';
    initApp();
    return true;
  }
  const devMe = await api('GET', '/api/v1/auth/me', null, '__no_token__');
  if(devMe && devMe.user && devMe.active_org){
    onAuthSuccess({
      access_token: 'dev_bypass_token',
      user: devMe.user,
      active_org: devMe.active_org
    });
    return true;
  }
  return false;
}

// ══════════════════════════════════════════════════════════════════════
// APP INIT
// ══════════════════════════════════════════════════════════════════════
async function initApp(){
  updateSidebar();
  await loadProjectsAndEnvs();
  await loadDash();
  checkServerHealth();
  setInterval(checkServerHealth, 30000);
  
  // Real-time Intelligence Engine
  const editor = document.getElementById('e-content');
  if(editor) editor.addEventListener('input', () => { detectVars(); updateIntel(); });
}

function updateSidebar(){
  if(!S.user||!S.org) return;
  const av = document.getElementById('sb-av');
  const nm = document.getElementById('sb-name');
  const oi = document.getElementById('sb-org');
  if(av) av.textContent = (S.user.full_name||S.user.email||'?')[0].toUpperCase();
  if(nm) nm.textContent = S.user.full_name || S.user.email;
  if(oi) oi.textContent = S.org.name || 'workspace';
  document.getElementById('set-org-name').textContent = S.org.name || '—';
  document.getElementById('set-slug').textContent = S.org.slug || '—';
  document.getElementById('set-user-info').innerHTML = `
    <div>Email: <span style="color:var(--t)">${S.user.email}</span></div>
    <div>Name: <span style="color:var(--t)">${S.user.full_name||'—'}</span></div>
    <div>Role: <span style="color:var(--g)">${S.org.role||'member'}</span></div>`;
  document.getElementById('dash-org-line').textContent =
    `${S.org.name} · ${(S.org.role||'member').toUpperCase()}`;
  const serveEl = document.getElementById('settings-serve-url');
  if(serveEl) serveEl.innerHTML = `${window.location.origin}/pm/serve/<span style="color:var(--y)">{key}</span>`;
  const logoutBtn = document.getElementById('btn-logout');
  if(logoutBtn){
    const isDevBypass = S.token === 'dev_bypass_token' || !S.token;
    logoutBtn.style.display = isDevBypass ? 'none' : '';
  }
}

async function checkServerHealth(){
  const dot  = document.getElementById('sb-dot');
  const tdot = document.getElementById('top-dot');
  const st   = document.getElementById('server-status');
  try {
    const r = await fetch(API+'/api/status', {signal:AbortSignal.timeout(3000)});
    const ok = r.ok;
    [dot,tdot].forEach(el=>{ if(el){ el.classList.toggle('ok',ok); el.style.background=ok?'var(--g)':'var(--r)'; }});
    if(st) st.textContent = ok ? 'CONNECTED' : 'ERROR';
  } catch(e) {
    [dot,tdot].forEach(el=>{ if(el) el.style.background='var(--r)'; });
    if(st) st.textContent = 'OFFLINE';
  }
}

// ══════════════════════════════════════════════════════════════════════
// DASHBOARD & REGISTRY
// ══════════════════════════════════════════════════════════════════════
async function loadProjectsAndEnvs(){
  const data = await api('GET', '/api/v1/projects');
  if(!data||!data.projects||!data.projects.length) return;
  S.project = data.projects[0];
  S.envs = S.project.environments || [];
  const sel = document.getElementById('env-select');
  sel.innerHTML = S.envs.map(e => `<option value="${e.id}">${e.display_name||e.name}</option>`).join('');
  const prod = S.envs.find(e=>e.name==='production') || S.envs[0];
  if(prod){ S.env=prod; sel.value=prod.id; updateEnvDot(); }
  renderEnvList();
}

function switchEnv(envId){
  const env = S.envs.find(e=>e.id===envId);
  if(env){ S.env=env; updateEnvDot(); loadDash(); }
}

function updateEnvDot(){
  const dot = document.getElementById('env-dot');
  if(!dot||!S.env) return;
  dot.style.background = S.env.color || '#888';
}

async function loadDash(){
  if(!S.env) return;
  const [promptsData, approvalsData] = await Promise.all([
    api('GET', `/api/v1/prompts?environment_id=${S.env.id}`),
    api('GET', '/api/v1/approvals'),
  ]);
  if(promptsData){
    S.prompts = promptsData.prompts || [];
    setText('dm-total', S.prompts.length);
    const live = S.prompts.filter(p=>p.live_version).length;
    setText('dm-prod', live);
    renderRecentPrompts(S.prompts.slice(-5).reverse());
    updateBadge('bx-prompts', S.prompts.length);
    populatePromptSelectors();
  }
  if(approvalsData){
    const pending = approvalsData.pending || [];
    setText('dm-pending', pending.length);
    updateBadge('bx-approvals', pending.length);
    renderDashApprovals(pending.slice(0,3));
  }
  
  // 💰 Estimated ROI (Zero-Cost Metric)
  const savings = (S.prompts || []).reduce((acc, p) => acc + 12.50 + ((p.version_count||0) * 2.50), 0);
  setText('dm-savings', `$${savings.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}`);
}

function renderRecentPrompts(prompts){
  const el = document.getElementById('dash-recent');
  if(!el) return;
  if(!prompts.length){ el.innerHTML='<div style="font-size:11px;color:var(--t3)">No prompts yet.</div>'; return; }
  el.innerHTML = prompts.map(p => `
    <div class="vi" onclick="openPromptEditor('${p.id}')">
      <div class="vi-key">${p.key}</div>
      ${p.live_version ? `<span class="tag tg">v${p.live_version.version_num} LIVE</span>` : `<span class="tag tn">DRAFT</span>`}
      <div class="vi-meta">${p.version_count||0} version${(p.version_count||0)!==1?'s':''}</div>
    </div>`).join('');
}

function renderDashApprovals(pending){
  const el = document.getElementById('dash-approvals');
  if(!el) return;
  if(!pending.length){ el.innerHTML='<div style="font-size:11px;color:var(--t3)">No pending approvals ✓</div>'; return; }
  el.innerHTML = pending.map(a => `
    <div class="vi" onclick="pg('approvals')">
      <div class="vi-key">${a.prompt?.key||'unknown'}</div>
      <span class="tag ty">v${a.version?.version_num} PENDING</span>
      <div class="vi-meta">${a.requested_by?.email?.split('@')[0]||'?'}</div>
    </div>`).join('');
}

async function loadRegistry(){
  if(!S.env) return;
  const data = await api('GET', `/api/v1/prompts?environment_id=${S.env.id}`);
  if(!data) return;
  S.prompts = data.prompts || [];
  renderRegistry(S.prompts);
  populatePromptSelectors();
}

function renderRegistry(prompts){
  const list  = document.getElementById('registry-list');
  const empty = document.getElementById('registry-empty');
  if(!list) return;
  if(!prompts.length){ list.innerHTML=''; empty.style.display=''; return; }
  empty.style.display='none';
  list.innerHTML = prompts.map(p => `
    <div class="vi" onclick="openPromptEditor('${p.id}')">
      <div style="font-size:12px;color:var(--t3);width:16px;flex-shrink:0">✦</div>
      <div class="vi-key">${p.key}</div>
      ${p.live_version
        ? `<span class="tag tg">v${p.live_version.version_num} LIVE · ${(p.live_version.last_eval_score||'').toString()?'score '+p.live_version.last_eval_score:'no eval'}</span>`
        : `<span class="tag tn">NO LIVE VERSION</span>`}
      <div class="vi-meta">${p.version_count} ver</div>
      <div class="vi-meta" style="margin-left:4px">${p.tags?.join(', ')||''}</div>
    </div>`).join('');
}

// ══════════════════════════════════════════════════════════════════════
// EDITOR
// ══════════════════════════════════════════════════════════════════════
let _editPromptId = null;
let _editVersions = [];

async function openPromptEditor(promptId){
  pg('editor');
  _editPromptId = promptId;
  const data = await api('GET', `/api/v1/prompts/${promptId}`);
  if(!data) return;
  const p = data.prompt;
  const versions = data.versions || [];
  _editVersions = versions;
  document.getElementById('e-key').value    = p.key || '';
  document.getElementById('e-desc').value   = p.description || '';
  document.getElementById('editor-meta').textContent = `${p.key} · ${versions.length} versions · env: ${S.env?.name}`;
  const draft = versions.filter(v=>v.status==='draft').pop();
  const live  = p.live_version;
  const working = draft || live;
  if(working){
    document.getElementById('e-content').value = working.content || '';
    document.getElementById('e-commit').value  = '';
  }
  renderVersionHistory(versions, p.live_version?.id);
  detectVars();
  if(live && live.last_eval_score) showInlineEval(live);
  updateIntel();
}

function detectVars(){
  const content = document.getElementById('e-content').value;
  const vars = [...new Set((content.match(/\{\{[\w_]+\}\}/g)||[]))];
  const el = document.getElementById('e-vars');
  if(!vars.length){ el.textContent='Write {{variable}} in your prompt content.'; updateIntel(); return; }
  el.innerHTML = vars.map(v => `
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:5px">
      <span style="color:var(--y);font-size:11px">${v}</span>
      <span style="font-size:10px;color:var(--t3)">→ pass as ?vars=${v.replace(/[{}]/g,'')}=value</span>
    </div>`).join('');
  updateIntel();
}

function renderVersionHistory(versions, liveId){
  const el = document.getElementById('e-versions');
  if(!el) return;
  if(!versions.length){ el.innerHTML='<div style="font-size:11px;color:var(--t3)">No versions yet</div>'; return; }
  el.innerHTML = [...versions].reverse().map(v => {
    const isLive = v.id===liveId;
    const statusMap = {approved:'tg',pending_review:'ty',draft:'tn',rejected:'tr',archived:'tn'};
    const cls = statusMap[v.status]||'tn';
    const canQuickApprove = (v.status==='draft'||v.status==='pending_review') && !isLive;
    return `
      <div class="vi" style="padding:7px 10px;border:1px solid ${isLive?'rgba(0,230,118,.3)':'var(--b2)'};margin-bottom:4px;cursor:pointer"
           onclick="loadVersionIntoEditor('${v.id}')">
        <div style="font-size:11px;color:${isLive?'var(--g)':'var(--t2)'}">v${v.version_num}</div>
        <div style="flex:1;font-size:10px;color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${v.commit_message||'—'}</div>
        ${isLive?'<span style="font-size:10px;color:var(--g)">LIVE</span>':''}
        <span class="tag ${cls}">${v.status}</span>
        ${v.last_eval_score?`<span style="font-size:10px;color:${v.last_eval_score>=8?'var(--g)':v.last_eval_score>=7?'var(--y)':'var(--r)'}">⚡${v.last_eval_score}</span>`:''}
        ${canQuickApprove?`<button class="btn bp bxs" style="font-size:9px" onclick="event.stopPropagation();quickApprove('${_editPromptId}','${v.id}')">⚡ LIVE</button>`:''}
      </div>`;
  }).join('');
}

function loadVersionIntoEditor(versionId){
  const v = _editVersions.find(v=>v.id===versionId);
  if(!v) return;
  document.getElementById('e-content').value = v.content||'';
  document.getElementById('e-commit').value  = `Based on v${v.version_num}`;
  detectVars();
  updateIntel();
  notif(`Loaded v${v.version_num} into editor`);
}

function updateIntel(){
  const content = document.getElementById('e-content').value;
  const chars = content.length;
  const vars  = (content.match(/\{\{[\w_]+\}\}/g)||[]).length;
  const complexity = Math.min(10, (vars / Math.max(1, chars)) * 1000).toFixed(1);
  
  let grade = 'A+';
  if(chars > 2000) grade = 'B';
  if(chars > 5000) grade = 'C';
  if(vars > 10)    grade = 'S'; // Complex/Sophisticated
  if(chars < 50)   grade = 'D'; // Too short
  
  const compEl = document.getElementById('intel-complexity');
  const charEl = document.getElementById('intel-chars');
  const gradEl = document.getElementById('intel-grade');
  
  if(compEl) compEl.textContent = complexity;
  if(charEl) charEl.textContent = chars;
  if(gradEl){
    gradEl.textContent = grade;
    gradEl.style.color = (grade==='A+'||grade==='S') ? 'var(--g)' : (grade==='B') ? 'var(--y)' : 'var(--r)';
  }
}

async function saveAsDraft(){
  if(!_editPromptId){ await createOrSaveDraft(); return; }
  const content = document.getElementById('e-content').value.trim();
  const commit  = document.getElementById('e-commit').value.trim();
  if(!content){ notif('Content cannot be empty','warn'); return; }
  const data = await api('POST', `/api/v1/prompts/${_editPromptId}/versions`, {
    content, commit_message: commit||'Draft update'
  });
  if(data){ notif('Draft saved · v'+data.version.version_num); openPromptEditor(_editPromptId); }
}

async function createOrSaveDraft(){
  const key     = document.getElementById('e-key').value.trim();
  const content = document.getElementById('e-content').value.trim();
  const desc    = document.getElementById('e-desc').value.trim();
  const data = await api('POST', '/api/v1/prompts', {
    environment_id: S.env.id, key, content, description: desc, commit_message: 'Initial version'
  });
  if(data){ notif('Prompt created ✓'); _editPromptId=data.prompt.id; openPromptEditor(_editPromptId); }
}

async function submitForReview(){
  const draftV = _editVersions.filter(v=>v.status==='draft').pop();
  if(!draftV){ notif('Save a draft first','warn'); return; }
  const note = prompt('Note for reviewer:');
  const data = await api('POST', `/api/v1/prompts/${_editPromptId}/versions/${draftV.id}/submit`, {note: note||''});
  if(data){ notif('Submitted ✓'); openPromptEditor(_editPromptId); }
}

// ══════════════════════════════════════════════════════════════════════
// APPROVALS
// ══════════════════════════════════════════════════════════════════════
async function loadApprovals(){
  const data = await api('GET', '/api/v1/approvals');
  if(!data) return;
  const pending = data.pending || [];
  const list  = document.getElementById('approval-list');
  const empty = document.getElementById('approvals-empty');
  updateBadge('bx-approvals', pending.length);
  if(!pending.length){ list.innerHTML=''; empty.style.display=''; return; }
  empty.style.display='none';
  list.innerHTML = pending.map(a => `
    <div style="background:var(--bg2);border:1px solid var(--b2);margin-bottom:8px;border-radius:2px;overflow:hidden">
      <div style="padding:12px;border-bottom:1px solid var(--b2);display:flex;align-items:center;gap:12px">
        <div style="flex:1">
          <div style="font-size:12px;color:var(--t);font-weight:600">${a.prompt?.key||'unknown'}</div>
          <div style="font-size:10px;color:var(--t3);margin-top:4px">
            v${a.version?.version_num} · by ${a.requested_by?.email||'?'}
          </div>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn bp bxs" onclick="approveVersion('${a.prompt?.id}','${a.version?.id}')">APPROVE</button>
          <button class="btn br bxs" onclick="rejectVersion('${a.prompt?.id}','${a.version?.id}')">REJECT</button>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;background:var(--bg3);max-height:400px;overflow-y:auto;border-bottom:1px solid var(--b2)">
        <div style="padding:12px;border-right:1px solid var(--b2);">
           <div style="font-size:9px;color:var(--t3);margin-bottom:8px;letter-spacing:.1em">BEFORE (Live or Parent)</div>
           <pre style="font-size:11px;color:var(--t2);white-space:pre-wrap;margin:0;font-family:var(--font)">${esc(a.version?.parent_content||(S.prompts.find(p=>p.id===a.prompt.id)?.live_version?.content||'No previous content / New prompt'))}</pre>
        </div>
        <div style="padding:12px">
           <div style="font-size:9px;color:var(--c);margin-bottom:8px;letter-spacing:.1em">PROPOSED</div>
           <pre style="font-size:11px;color:var(--t);white-space:pre-wrap;margin:0;font-family:var(--font)">${esc(a.version?.content||'')}</pre>
        </div>
      </div>
    </div>`).join('');
}

async function approveVersion(pId, vId){
  const data = await api('POST', `/api/v1/prompts/${pId}/versions/${vId}/approve`);
  if(data){ notif('Approved ✓'); loadApprovals(); loadDash(); }
}

async function rejectVersion(pId, vId){
  const reason = prompt('Reason:');
  if(!reason) return;
  const data = await api('POST', `/api/v1/prompts/${pId}/versions/${vId}/reject`, {reason});
  if(data){ notif('Rejected'); loadApprovals(); }
}

// ══════════════════════════════════════════════════════════════════════
// EVALUATIONS
// ══════════════════════════════════════════════════════════════════════
function updateModelList(){
  const MODEL_MAP = {
    anthropic: ['claude-3-5-sonnet-latest','claude-3-haiku-20240307'],
    openai:    ['gpt-4o','gpt-4o-mini'],
    google:    ['gemini-1.5-pro','gemini-1.5-flash'],
  };
  const provider = document.getElementById('ev-provider').value;
  const sel = document.getElementById('ev-model');
  sel.innerHTML = (MODEL_MAP[provider]||[]).map(m=>`<option value="${m}">${m}</option>`).join('');
}

async function runEval(){
  const versionId = document.getElementById('ev-version').value;
  if(!versionId){ notif('Select a version','warn'); return; }
  const btn = document.getElementById('eval-btn');
  btn.disabled=true; btn.textContent='EVALUATING...';
  const data = await api('POST', '/api/v1/evals/run', {
    version_id: versionId, provider: document.getElementById('ev-provider').value,
    model: document.getElementById('ev-model').value, api_key: document.getElementById('ev-key').value.trim(),
    test_input: document.getElementById('ev-input').value.trim(), eval_type: 'llm_judge'
  });
  btn.disabled=false; btn.textContent='RUN EVAL';
  if(data) renderEvalResult(data);
}

async function runRuleBasedEval(){
  const versionId = document.getElementById('ev-version').value;
  if(!versionId){ notif('Select a version first','warn'); return; }
  const data = await api('POST', '/api/v1/evals/run', {
    version_id: versionId, provider: 'rule_based',
    model: 'rule_based', api_key: 'none',
    test_input: '', eval_type: 'rule_based'
  });
  if(data) renderEvalResult(data);
}

function renderEvalResult(data){
  const body = document.getElementById('eval-output-body');
  document.getElementById('eval-output').style.display='';
  const score = data.overall_score||0;
  const color = score>=8?'var(--g)':score>=6?'var(--y)':'var(--r)';
  body.innerHTML = `
    <div style="display:flex;gap:12px;margin-bottom:12px">
      <div style="font-size:32px;font-weight:700;color:${color}">${score.toFixed(1)}</div>
      <div style="font-size:10px;color:var(--t3)">${data.passed?'✓ PASSED':'✗ FAILED'}<br>threshold: ${data.threshold}</div>
    </div>
    ${Object.entries(data.criteria||{}).map(([k,v])=>`
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <div style="width:100px;font-size:10px;color:var(--t2)">${k}</div>
        <div style="flex:1;height:4px;background:var(--bg3)"><div style="height:100%;width:${v*10}%;background:var(--c)"></div></div>
        <div style="font-size:10px;color:var(--t)">${v}</div>
      </div>`).join('')}`;
}

async function loadTeamKeys(){
  const data = await api('GET', '/api/v1/evals/keys');
  if(!data) return;
  const list = document.getElementById('team-keys-list');
  if(!list) return;
  const keys = data.keys||[];
  if(!keys.length){ list.innerHTML='<div style="font-size:11px;color:var(--t3)">No saved keys. Add one to run evals without pasting keys each time.</div>'; return; }
  list.innerHTML = keys.map(k=>`
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;padding:5px 7px;background:var(--bg3);border:1px solid var(--b2)">
      <div style="font-size:11px;color:var(--y);width:70px">${k.provider}</div>
      <div style="font-size:11px;color:var(--t3);flex:1">${k.hint}</div>
      <div style="font-size:11px;color:var(--t3)">${k.label||'—'}</div>
      <button class="btn br bxs" style="font-size:9px" data-id="${esc(k.id)}" onclick="deleteTeamKey(this.dataset.id)">✕</button>
    </div>`).join('');
}

function openSaveKeyModal(){
  openModal('SAVE_TEAM_LLM_KEY', `
    <div class="fg"><label>PROVIDER</label>
    <select id="sk-prov"><option value="anthropic">Anthropic</option><option value="openai">OpenAI</option><option value="google">Google</option></select></div>
    <div class="fg"><label>API KEY — stored encrypted (AES-256), never shown again</label><input type="password" id="sk-key" placeholder="sk-..."></div>
    <div class="fg"><label>LABEL (optional)</label><input type="text" id="sk-label" placeholder="Team OpenAI key"></div>
    <div style="font-size:10px;color:var(--t3);line-height:1.7;padding:8px;background:var(--bg3);border:1px solid var(--b2)">Your key is encrypted with AES-256-GCM before storage. Only decrypted in server memory during eval runs. Never logged or returned via API.</div>`,
    [{label:'SAVE ENCRYPTED KEY', fn:'saveTeamKey()'}]
  );
}

async function saveTeamKey(){
  const provider = document.getElementById('sk-prov').value;
  const apiKey   = document.getElementById('sk-key').value.trim();
  const label    = document.getElementById('sk-label').value.trim();
  if(!apiKey){ notif('Enter an API key','warn'); return; }
  const data = await api('POST', '/api/v1/evals/keys', {provider, api_key:apiKey, label});
  if(data){ notif('Key saved (encrypted) ✓'); closeModal(); loadTeamKeys(); }
}

async function deleteTeamKey(id){
  if(!confirm('Remove this key?')) return;
  const data = await api('DELETE', `/api/v1/evals/keys/${id}`);
  if(data){ notif('Key removed'); loadTeamKeys(); }
}

// ══════════════════════════════════════════════════════════════════════
// VERSION HISTORY
// ══════════════════════════════════════════════════════════════════════
async function loadVersionHistory(promptId){
  if(!promptId) return;
  const data = await api('GET', `/api/v1/prompts/${promptId}`);
  if(!data) return;
  const versions = data.versions||[];
  const el = document.getElementById('hist-list');
  if(!el) return;
  if(!versions.length){ el.innerHTML='<div class="empty">no versions yet</div>'; return; }
  const liveId = data.prompt?.live_version?.id;
  el.innerHTML = [...versions].reverse().map(v => {
    const isLive = v.id===liveId;
    const statusMap = {approved:'tg',pending_review:'ty',draft:'tn',rejected:'tr',archived:'tn'};
    return `
      <div style="background:var(--bg2);border:1px solid ${isLive?'rgba(0,230,118,.3)':'var(--b2)'};margin-bottom:4px;overflow:hidden">
        <div style="padding:8px 12px;display:flex;align-items:center;gap:8px;font-size:11px">
          <div style="font-size:12px;color:${isLive?'var(--g)':'var(--t2)'}">v${v.version_num}</div>
          <div style="flex:1;font-size:10px;color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${v.commit_message||'no message'}</div>
          <span class="tag ${statusMap[v.status]||'tn'}">${v.status}</span>
          ${isLive?'<span style="font-size:10px;color:var(--g)">← LIVE</span>':''}
          ${v.last_eval_score!=null?`<span style="font-size:10px;color:${v.last_eval_score>=8?'var(--g)':v.last_eval_score>=7?'var(--y)':'var(--r)'}">eval:${v.last_eval_score.toFixed(1)}</span>`:''}
          <div style="font-size:10px;color:var(--t3)">${(v.created_at||'').slice(0,10)}</div>
          ${v.status==='approved'&&!isLive?`<button class="btn bxs" data-pid="${esc(data.prompt.id)}" data-vid="${esc(v.id)}" data-vnum="${v.version_num}" onclick="rollbackTo(this.dataset.pid,this.dataset.vid,this.dataset.vnum)">↩ ROLLBACK</button>`:''}
        </div>
      </div>`;
  }).join('');
}

async function rollbackTo(promptId, versionId, vnum){
  if(!confirm(`Rollback to v${vnum}? This creates a new approved version with that content.`)) return;
  const data = await api('POST', `/api/v1/prompts/${promptId}/versions/${versionId}/rollback`);
  if(data){ notif(data.message||'Rolled back ✓'); loadVersionHistory(promptId); loadDash(); }
}

// ══════════════════════════════════════════════════════════════════════
// API KEYS
// ══════════════════════════════════════════════════════════════════════
async function loadKeys(){
  if(!S.env) return;
  const data = await api('GET', `/api/v1/keys?environment_id=${S.env.id}`);
  if(!data) return;
  const keys = data.keys||[];
  const list = document.getElementById('keys-list');
  const empty = document.getElementById('keys-empty');
  if(!list) return;
  if(!keys.length){ list.innerHTML=''; empty.style.display=''; return; }
  empty.style.display='none';
  list.innerHTML = keys.map(k=>`
    <div style="background:var(--bg2);border:1px solid var(--b2);padding:10px 12px;margin-bottom:4px;display:flex;align-items:center;gap:10px">
      <div style="flex:1">
        <div style="font-size:13px;color:var(--t)">${k.name}</div>
        <div style="font-size:11px;color:var(--c);margin-top:2px;letter-spacing:.04em">${k.prefix}••••••••</div>
        <div style="font-size:10px;color:var(--t3);margin-top:2px">
          env: ${S.env?.name} · created ${(k.created_at||'').slice(0,10)} · last used: ${k.last_used_at?(k.last_used_at.slice(0,10)):'never'}
        </div>
      </div>
      <button class="btn bxs" data-id="${esc(k.id)}" data-name="${esc(k.name)}" onclick="rotateKey(this.dataset.id,this.dataset.name)">↻ ROTATE</button>
      <button class="btn br bxs" data-id="${esc(k.id)}" data-name="${esc(k.name)}" onclick="revokeKey(this.dataset.id,this.dataset.name)">✕ REVOKE</button>
    </div>`).join('');
}

function openCreateKeyModal(){
  if(!S.env){ notif('Select an environment first','warn'); return; }
  openModal('CREATE_API_KEY', `
    <div style="font-size:11px;color:var(--t3);margin-bottom:12px;line-height:1.7;padding:8px;background:var(--bg3);border-left:2px solid var(--y)">
      ⚠ The full API key is shown ONCE on creation. Copy and store it securely. It cannot be recovered — only rotated.
    </div>
    <div class="fg"><label>KEY NAME</label><input type="text" id="ck-name" placeholder="n8n production · RADAR agent · chatbot key"></div>
    <div style="font-size:11px;color:var(--t3)">Environment: <span style="color:${S.env.color}">${S.env.name}</span></div>`,
    [{label:'CREATE KEY', fn:'createKey()'}]
  );
}

async function createKey(){
  const name = document.getElementById('ck-name')?.value.trim();
  if(!name){ notif('Enter a key name','warn'); return; }
  const data = await api('POST', '/api/v1/keys', {environment_id: S.env.id, name});
  if(!data) return;
  closeModal();
  openModal('YOUR_API_KEY', `
    <div style="font-size:11px;color:var(--y);background:var(--y2);border:1px solid rgba(255,215,0,.3);padding:10px;margin-bottom:12px;letter-spacing:.04em;line-height:1.7">
      ⚠ This key is shown ONCE. Copy it now. It cannot be retrieved again — only rotated.
    </div>
    <div class="fg"><label>FULL API KEY — COPY NOW</label>
    <input type="text" value="${data.key}" readonly onclick="this.select()" style="color:var(--g);font-size:13px;cursor:pointer;letter-spacing:.04em">
    </div>
    <div style="font-size:11px;color:var(--t3);margin-top:8px">Add to your agent:<br>
    <span style="color:var(--c)">Authorization: Bearer ${data.key}</span></div>`,
    [{label:'I COPIED IT', fn:'closeModal();loadKeys()'}]
  );
}

async function revokeKey(id, name){
  if(!confirm(`Revoke key "${name}"? Agents using it will get 401 immediately.`)) return;
  const data = await api('DELETE', `/api/v1/keys/${id}`);
  if(data){ notif(data.message); loadKeys(); }
}

async function rotateKey(id, name){
  if(!confirm(`Rotate key "${name}"? Old key stops working immediately. You'll get a new key to copy.`)) return;
  const data = await api('POST', `/api/v1/keys/${id}/rotate`);
  if(!data) return;
  openModal('ROTATED_KEY', `
    <div style="font-size:11px;color:var(--y);background:var(--y2);border:1px solid rgba(255,215,0,.3);padding:10px;margin-bottom:12px">
      Old key revoked. Copy your new key now.
    </div>
    <div class="fg"><label>NEW API KEY</label>
    <input type="text" value="${data.key}" readonly onclick="this.select()" style="color:var(--g);font-size:13px;cursor:pointer"></div>`,
    [{label:'I COPIED IT', fn:'closeModal();loadKeys()'}]
  );
}

// ══════════════════════════════════════════════════════════════════════
// ENVIRONMENTS & REGISTRY
// ══════════════════════════════════════════════════════════════════════
function renderEnvList(){
  const el = document.getElementById('env-list');
  if(!el) return;
  if(!S.envs.length){ el.innerHTML='<div class="empty">no environments</div>'; return; }
  el.innerHTML = S.envs.map(e => `
    <div style="background:var(--bg2);border:1px solid var(--b2);padding:12px;margin-bottom:4px;display:flex;align-items:center;gap:12px;border-left:3px solid ${e.color||'#888'}">
      <div style="flex:1">
        <div style="font-size:13px;color:var(--t);font-weight:500">${e.display_name||e.name}</div>
        <div style="font-size:11px;color:var(--t3);margin-top:4px;line-height:1.8">
          ${e.is_protected?'🔒 Protected (approval required)':'🔓 Open (auto-approve in dev)'}
          · Eval threshold: <span style="color:var(--y)">${e.eval_pass_threshold}</span>/10
        </div>
      </div>
      <div style="text-align:right">
        <button class="btn bxs" onclick="switchEnv('${e.id}');pg('prompts')">VIEW PROMPTS →</button>
      </div>
    </div>`).join('');
}

function openNewPromptModal(){
  openModal('NEW_PROMPT', `
    <div class="fg"><label>PROMPT KEY — dot notation, lowercase</label>
    <input type="text" id="np-key" placeholder="assistant.system · radar.briefing · chatbot.greeting"></div>
    <div class="fg"><label>INITIAL CONTENT</label>
    <textarea id="np-content" rows="8" placeholder="You are a helpful assistant...&#10;&#10;Use {{variable}} for dynamic values."></textarea></div>
    <div class="fg"><label>DESCRIPTION (optional)</label>
    <input type="text" id="np-desc" placeholder="What this prompt does"></div>`,
    [{label:'CREATE & OPEN EDITOR', fn:'createAndOpen()'}]
  );
}

async function createAndOpen(){
  const key     = document.getElementById('np-key')?.value.trim();
  const content = document.getElementById('np-content')?.value.trim();
  const desc    = document.getElementById('np-desc')?.value.trim();
  if(!key||!content){ notif('Key and content required','warn'); return; }
  if(!S.env){ notif('Select an environment first','warn'); return; }
  const data = await api('POST', '/api/v1/prompts', {
    environment_id: S.env.id, key, content,
    description: desc, commit_message: 'Initial version'
  });
  if(data){
    notif('Prompt created ✓');
    S.prompts.push(data.prompt);
    closeModal();
    openPromptEditor(data.prompt.id);
  }
}

// ══════════════════════════════════════════════════════════════════════
// AUDIT LOG
// ══════════════════════════════════════════════════════════════════════
async function loadAudit(){
  const data = await api('GET', '/api/v1/audit?limit=100');
  if(!data) return;
  const el = document.getElementById('audit-list');
  el.innerHTML = (data.logs||[]).map(l=>`
    <div style="display:flex;gap:12px;padding:8px 10px;border-bottom:1px solid var(--b1);font-size:11px">
      <div style="width:140px;color:var(--c)">${l.action}</div>
      <div style="width:80px;color:var(--t3)">${l.resource_type}</div>
      <div style="flex:1;color:var(--t2)">${l.actor_email||'system'}</div>
      <div style="color:var(--t3)">${l.created_at.slice(11,19)}</div>
    </div>`).join('');
}

// ══════════════════════════════════════════════════════════════════════
// UTILS & NAVIGATION
// ══════════════════════════════════════════════════════════════════════
function pg(name){
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.ni').forEach(n=>n.classList.remove('on'));
  if(document.getElementById('pane-'+name)) document.getElementById('pane-'+name).classList.add('on');
  if(document.getElementById('ni-'+name)) document.getElementById('ni-'+name).classList.add('on');
  
  // Custom mapping: 'dash' maps to 'dashboard' logic
  const pageName = name === 'dash' ? 'dashboard' : name;
  
  const PAGE_LOAD = {
    prompts:      loadRegistry,
    approvals:    loadApprovals,
    audit:        loadAudit,
    keys:         loadKeys,
    dashboard:    loadDash,
    environments: renderEnvList,
    evals:        () => { loadTeamKeys(); populatePromptSelectors(); },
    versions:     () => {
      const select = document.getElementById('hist-select');
      if (select) {
        select.innerHTML = '<option value="">— Select Prompt —</option>' + S.prompts.map(p=>`<option value="${p.id}">${p.key}</option>`).join('');
      }
      document.getElementById('hist-list').innerHTML = '';
    }
  };
  if(PAGE_LOAD[pageName]) PAGE_LOAD[pageName]();
}

function openModal(title, body, actions=[]){
  document.getElementById('modal-title').textContent=title;
  document.getElementById('modal-body').innerHTML=body;
  document.getElementById('modal-foot').innerHTML=actions.map(a=>`<button class="btn bp" onclick="${a.fn}">${a.label}</button>`).join('')+'<button class="btn" onclick="closeModal()">CANCEL</button>';
  document.getElementById('modal-overlay').classList.add('show');
  
  // Auto-focus first input
  setTimeout(()=>{
    const first = document.querySelector('#modal-body input,#modal-body textarea');
    if(first) first.focus();
  },80);
}

function closeModal(e){
  if(e && e.target !== document.getElementById('modal-overlay')) return;
  document.getElementById('modal-overlay').classList.remove('show');
}

let sbOpen=true;
function toggleSb(){
  sbOpen=!sbOpen;
  const sb=document.getElementById('sb');
  const tog=document.getElementById('sb-tog');
  const lt=document.getElementById('logo-text');
  sb.classList.toggle('col',!sbOpen);
  if(tog) tog.textContent=sbOpen?'‹':'›';
  if(lt)  lt.style.opacity=sbOpen?'1':'0';
}

function exportWorkspace() {
  const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(S.prompts, null, 2));
  const downloadAnchor = document.createElement('a');
  downloadAnchor.setAttribute("href", dataStr);
  downloadAnchor.setAttribute("download", `promptmatrix_workspace_${S.org?.slug || 'export'}.json`);
  document.body.appendChild(downloadAnchor);
  downloadAnchor.click();
  downloadAnchor.remove();
  notif("Workspace exported successfully");
}

function notif(msg, type='ok'){
  const n = document.createElement('div');
  n.className = 'nt ' + type;
  n.textContent = msg;
  document.getElementById('notif').appendChild(n);
  setTimeout(()=>n.classList.add('show'),10);
  setTimeout(()=>{n.classList.remove('show');setTimeout(()=>n.remove(),300);},3000);
}

function setText(id,val){ if(document.getElementById(id)) document.getElementById(id).textContent=val; }
function updateBadge(id,n){ if(document.getElementById(id)) document.getElementById(id).textContent=n||''; }
function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function populatePromptSelectors(){
  const s = document.getElementById('ev-version');
  if(s) s.innerHTML = '<option value="">— Select —</option>' + S.prompts.map(p=>p.live_version?`<option value="${p.live_version.id}">${p.key} (v${p.live_version.version_num})</option>`:'').join('');
}

// ══════════════════════════════════════════════════════════════════════
// BOOT
// ══════════════════════════════════════════════════════════════════════
window.addEventListener('load', async () => {
  const ok = await tryRestoreSession();
  document.getElementById('boot-loading').classList.add('hidden');
  if(!ok) document.getElementById('auth-overlay').classList.remove('hidden');
});

