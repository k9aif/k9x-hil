/* k9x HIL — Case Management UI */

let currentUser = null;
let authToken = null;
let activeTab = "home";
let activeAppId = null;
let activeQueue = "";           // application page: "" = all queues, else a queue name
let allTasks = [];
let allQueues = [];
let taskFilter = "all";
let sortCol = "created_at";
let sortDir = -1; // -1 = newest first

// ── Auth ────────────────────────────────────────────────────────────────────

function authFetch(url, opts = {}) {
  const headers = Object.assign({}, opts.headers || {},
    authToken ? { "Authorization": "Bearer " + authToken } : {});
  return fetch(url, Object.assign({}, opts, { headers })).then(r => {
    if (r.status === 401) { logout(); throw new Error("Session expired"); }
    return r;
  });
}

function doLogin(e) {
  e.preventDefault();
  const email = document.getElementById("login-email").value;
  const pass  = document.getElementById("login-pass").value;
  fetch("/api/auth/login", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({email, password: pass})
  })
  .then(r => { if (!r.ok) throw new Error("Invalid credentials"); return r.json(); })
  .then(u => {
    currentUser = u;
    authToken = u.token;
    localStorage.setItem("k9x_hil_user", JSON.stringify(u));
    localStorage.setItem("k9x_hil_token", u.token);
    showApp();
  })
  .catch(() => {
    document.getElementById("login-error").textContent = "Invalid email or password";
  });
}

const PANELS = ["home","app","mytasks","admin","admin-iam","admin-projects","admin-policies","admin-rules","admin-queues","admin-audit"];

function logout() {
  currentUser = null;
  authToken = null;
  localStorage.removeItem("k9x_hil_user");
  localStorage.removeItem("k9x_hil_token");
  allTasks = []; allQueues = []; activeAppId = null; activeQueue = "";
  document.getElementById("user-chip").style.display = "none";
  document.getElementById("user-menu").style.display = "none";
  document.getElementById("nav-current").innerHTML = "";
  PANELS.forEach(p => { const el = document.getElementById("panel-" + p); if (el) el.classList.remove("active"); });
  document.getElementById("panel-login").classList.add("active");
}

function toggleUserMenu() {
  const m = document.getElementById("user-menu");
  m.style.display = m.style.display === "none" ? "block" : "none";
}

function showApp() {
  document.getElementById("login-error").textContent = "";
  document.getElementById("panel-login").classList.remove("active");
  document.getElementById("user-chip").style.display = "flex";
  document.getElementById("user-avatar").textContent = currentUser.name.charAt(0);
  document.getElementById("user-name").textContent = currentUser.name;
  document.getElementById("user-menu-email").textContent = currentUser.email;
  document.getElementById("user-menu-role").textContent = currentUser.role;
  const adminBtn = document.getElementById("header-admin-btn");
  if (adminBtn) adminBtn.style.display = currentUser.role === "admin" ? "flex" : "none";
  switchTab("home");
}

// ── Navigation: Projects → Application ──────────────────────────────────────
// Home lists the user's projects and their applications; choosing an
// application opens one page with its tasks by status. The sidebar only shows
// where you are (project › application), not every application.

function appsByProject() {
  const byProject = new Map();
  (currentUser.applications || []).forEach(a => {
    if (!byProject.has(a.project)) byProject.set(a.project, []);
    byProject.get(a.project).push(a);
  });
  return [...byProject.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

function renderNavCurrent() {
  const el = document.getElementById("nav-current");
  if (!el) return;
  const app = activeAppId && (currentUser.applications || []).find(a => a.id === activeAppId);
  el.innerHTML = app ? `<div class="nav-current">
      <div class="nav-current-label">Project</div>
      <div class="nav-current-project" onclick="switchTab('home')" title="All projects">${esc(app.project)}</div>
      <div class="nav-current-label">Application</div>
      <div class="nav-current-app">${esc(app.name)}</div>
    </div>` : "";
}

function switchToApp(appId) {
  activeAppId = appId;
  activeTab = "app";
  activeQueue = "";
  taskFilter = "all";
  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  PANELS.forEach(p => { const el = document.getElementById("panel-" + p); if (el) el.classList.remove("active"); });
  document.getElementById("panel-app").classList.add("active");
  const app = (currentUser.applications || []).find(a => a.id === appId);
  document.getElementById("header-tab-title").textContent = app ? app.name : "Tasks";
  renderNavCurrent();
  loadTasksForApp(appId);
}

async function loadTasksForApp(appId) {
  try {
    const [rt, rq] = await Promise.all([authFetch("/api/tasks?application_id=" + appId),
                                        authFetch("/api/queues?application_id=" + appId)]);
    allTasks = await rt.json();
    allQueues = await rq.json();
  } catch { allTasks = []; allQueues = []; }
  renderApp();
  updateBadges();
}

// ── Data loading ────────────────────────────────────────────────────────────

async function loadTasks() {
  try {
    const r = await authFetch("/api/tasks");
    allTasks = await r.json();
  } catch { allTasks = []; }
}

// ── Tab switching ───────────────────────────────────────────────────────────

function switchTab(tab) {
  activeTab = tab;
  activeAppId = null;
  activeQueue = "";
  taskFilter = "all";

  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  const navEl = document.getElementById("nav-" + tab);
  if (navEl) navEl.classList.add("active");
  PANELS.forEach(p => { const el = document.getElementById("panel-" + p); if (el) el.classList.remove("active"); });
  const panel = document.getElementById("panel-" + tab);
  if (panel) panel.classList.add("active");
  renderNavCurrent();

  const titles = {
    home: "Projects", mytasks: "My Tasks",
    admin: "Administration", "admin-iam": "Users & Roles", "admin-projects": "Projects & Applications",
    "admin-policies": "Policies", "admin-rules": "Rules & Automation",
    "admin-queues": "Queues & Topics", "admin-audit": "Audit Log"
  };
  document.getElementById("header-tab-title").textContent = titles[tab] || tab;

  if (tab === "home" || tab === "mytasks") loadTasks().then(() => render());
  else if (tab === "admin") renderAdminLanding();
  else if (tab === "admin-iam") renderAdminIAM();
  else if (tab === "admin-projects") renderAdminProjects();
  else if (tab === "admin-policies") renderAdminPolicies();
  else if (tab === "admin-rules") renderAdminRules();
  else if (tab === "admin-queues") renderAdminQueues();
  else if (tab === "admin-audit") renderAdminAudit();
}

// ── Rendering ───────────────────────────────────────────────────────────────

function render() {
  if (activeTab === "home")    { renderHome(); renderJobSearch(); }
  if (activeTab === "app")     renderApp();
  if (activeTab === "mytasks") renderMyTasks();
  updateBadges();
}

function updateBadges() {
  if (!currentUser || activeTab === "app") return;   // the app page holds only that app's tasks
  const myCount = allTasks.filter(t => t.assigned_to === currentUser.email && ["pending","in_progress"].includes(t.status)).length;
  const badge = document.getElementById("badge-mytasks");
  if (badge) {
    if (myCount > 0) { badge.textContent = myCount; badge.style.display = "inline"; }
    else { badge.style.display = "none"; }
  }
}

// ── Urgency helpers ─────────────────────────────────────────────────────────

function taskExpiry(t) {
  if (t.due_date) return new Date(t.due_date).getTime();
  if (t.ttl_hours && t.created_at) return new Date(t.created_at).getTime() + t.ttl_hours * 3600000;
  return null;
}

function taskTimeLeft(t) {
  const exp = taskExpiry(t);
  if (!exp) return null;
  return exp - Date.now();
}

function taskUrgencyPct(t) {
  if (!t.ttl_hours || !t.created_at) return null;
  const total = t.ttl_hours * 3600000;
  const elapsed = Date.now() - new Date(t.created_at).getTime();
  return Math.min(100, Math.max(0, (elapsed / total) * 100));
}

function urgencyColor(pct) {
  if (pct >= 90) return "var(--red)";
  if (pct >= 70) return "var(--orange)";
  if (pct >= 50) return "var(--amber)";
  return "var(--green)";
}

function timeLeftLabel(ms) {
  if (ms === null) return "";
  if (ms <= 0) return "EXPIRED";
  const h = Math.floor(ms / 3600000);
  if (h < 1) return Math.floor(ms / 60000) + "m left";
  if (h < 24) return h + "h left";
  const d = Math.floor(h / 24);
  return d + "d " + (h % 24) + "h left";
}

// ── Home: projects and their applications ───────────────────────────────────

const OPEN_STATUSES = ["pending", "in_progress", "escalated"];
const isOpen = t => OPEN_STATUSES.includes(t.status);
// Critical is a priority, not a status: the Critical tab lists critical tasks still open.
const isCritical = t => String(t.priority || "").toLowerCase() === "critical" && isOpen(t);

function countsFor(tasks) {
  return {
    all: tasks.length,
    pending: tasks.filter(t => t.status === "pending").length,
    in_progress: tasks.filter(t => t.status === "in_progress").length,
    escalated: tasks.filter(t => t.status === "escalated").length,
    completed: tasks.filter(t => t.status === "completed").length,
    rejected: tasks.filter(t => t.status === "rejected").length,
    critical: tasks.filter(isCritical).length,
  };
}

function renderHome() {
  const el = document.getElementById("project-grid");
  if (!el || !currentUser) return;
  const projects = appsByProject();
  if (!projects.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">◇</div><div class="empty-state-text">No applications are assigned to you yet.</div></div>';
    return;
  }
  el.innerHTML = projects.map(([project, apps]) => `
    <div class="project-card">
      <div class="project-card-title">${esc(project)}</div>
      <table class="project-app-table">
        <thead><tr><th>Application</th><th>Pending</th><th>In progress</th><th>Escalated</th><th>Critical</th><th>Completed</th></tr></thead>
        <tbody>
          ${apps.sort((a, b) => a.name.localeCompare(b.name)).map(a => {
            const c = countsFor(allTasks.filter(t => t.application_id === a.id));
            const n = (v, cls) => v ? `<span class="${cls}">${v}</span>` : '<span class="muted">—</span>';
            return `<tr class="project-app-row" onclick="switchToApp(${a.id})" title="Open ${esc(a.name)}">
              <td class="project-app-name">${esc(a.name)} <span class="project-app-go">›</span></td>
              <td>${n(c.pending, "cnt-pending")}</td>
              <td>${n(c.in_progress, "cnt-progress")}</td>
              <td>${n(c.escalated, "cnt-escalated")}</td>
              <td>${n(c.critical, "cnt-critical")}</td>
              <td>${n(c.completed, "cnt-completed")}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>`).join("");
}

// ── Application page: status tabs, queue filter, sortable table ─────────────

function renderApp() {
  if (!currentUser || !activeAppId) return;
  const app = (currentUser.applications || []).find(a => a.id === activeAppId);
  document.getElementById("app-crumb").innerHTML = app
    ? `<a onclick="switchTab('home')">Projects</a> › ${esc(app.project)} › <strong>${esc(app.name)}</strong>` : "";
  const inQueue = activeQueue ? allTasks.filter(t => t.queue_name === activeQueue) : allTasks;
  const queues = [...new Set([...allQueues.map(q => q.name), ...allTasks.map(t => t.queue_name).filter(Boolean)])].sort();
  const queueSelect = queues.length > 1 ? `<select class="queue-select" onchange="setQueue(this.value)" title="Filter by queue">
      <option value="">All queues</option>
      ${queues.map(q => `<option value="${esc(q)}" ${q === activeQueue ? "selected" : ""}>${esc(q)}</option>`).join("")}
    </select>` : "";
  document.getElementById("app-filters").innerHTML = statusTabs(inQueue) + queueSelect;
  const rows = applySort(applyFilter(inQueue));
  document.getElementById("app-list").innerHTML = rows.length
    ? taskTableHtml(rows, false)
    : '<div class="empty-state"><div class="empty-state-icon">◇</div><div class="empty-state-text">No tasks here</div></div>';
}

function setQueue(q) {
  activeQueue = q;
  render();
}

// ── My Tasks ────────────────────────────────────────────────────────────────

function renderMyTasks() {
  if (!currentUser) return;
  const mine = allTasks.filter(t => t.assigned_to === currentUser.email);
  document.getElementById("mytask-filters").innerHTML = statusTabs(mine);
  const rows = applySort(applyFilter(mine));
  document.getElementById("mytask-list").innerHTML = rows.length
    ? taskTableHtml(rows, true)
    : '<div class="empty-state"><div class="empty-state-icon">◇</div><div class="empty-state-text">No tasks assigned to you</div></div>';
}

// ── Status tabs, filtering and sorting ──────────────────────────────────────

function statusTabs(tasks) {
  const c = countsFor(tasks);
  const tabs = [["all", "All"], ["pending", "Pending"], ["in_progress", "In progress"], ["escalated", "Escalated"],
                ["completed", "Completed"], ["critical", "Critical"]];
  if (c.rejected) tabs.push(["rejected", "Rejected"]);
  return `<div class="status-tabs">${tabs.map(([k, label]) =>
    `<button class="status-tab status-tab-${k} ${taskFilter === k ? "active" : ""}" onclick="setFilter('${k}')">${label} <span class="status-tab-count">${c[k]}</span></button>`
  ).join("")}</div>`;
}

function applyFilter(tasks) {
  if (taskFilter === "all") return tasks;
  if (taskFilter === "critical") return tasks.filter(isCritical);
  return tasks.filter(t => t.status === taskFilter);
}

const PRIORITY_RANK = { critical: 0, high: 1, medium: 2, low: 3 };
const STATUS_RANK = { escalated: 0, pending: 1, in_progress: 2, completed: 3, rejected: 4, expired: 5 };

function applySort(tasks) {
  return [...tasks].sort((a, b) => {
    let va = a[sortCol], vb = b[sortCol];
    if (sortCol === "time_left") { va = taskTimeLeft(a) ?? Infinity; vb = taskTimeLeft(b) ?? Infinity; }
    if (sortCol === "priority") { va = PRIORITY_RANK[String(a.priority).toLowerCase()] ?? 9; vb = PRIORITY_RANK[String(b.priority).toLowerCase()] ?? 9; }
    if (sortCol === "status") { va = STATUS_RANK[a.status] ?? 9; vb = STATUS_RANK[b.status] ?? 9; }
    if (va == null) va = "";
    if (vb == null) vb = "";
    if (typeof va === "string") va = va.toLowerCase();
    if (typeof vb === "string") vb = vb.toLowerCase();
    if (va < vb) return -1 * sortDir;
    if (va > vb) return 1 * sortDir;
    return 0;
  });
}

function setSort(col) {
  if (sortCol === col) sortDir *= -1;
  else { sortCol = col; sortDir = 1; }
  render();
}

function sortIcon(col) {
  if (sortCol !== col) return '<span class="sort-icon">⇅</span>';
  return sortDir === 1 ? '<span class="sort-icon active">▲</span>' : '<span class="sort-icon active">▼</span>';
}

// Every column header sorts (click again to reverse). showApp: add the
// Application column where rows can come from several applications.
function taskTableHtml(tasks, showApp) {
  const th = (col, label, cls, title) =>
    `<th class="${cls}" onclick="setSort('${col}')"${title ? ` title="${title}"` : ""}>${label} ${sortIcon(col)}</th>`;
  return `<div class="task-table-wrap"><table class="task-table">
    <thead><tr>
      ${th("correlation_id", "Job ID", "tt-col-job", "The calling system's job id (correlation id)")}
      ${th("title", "Title", "tt-col-title")}
      ${showApp ? th("application_name", "Application", "tt-col-app") : ""}
      ${th("queue_name", "Queue", "tt-col-queue")}
      ${th("status", "Status", "tt-col-status")}
      ${th("priority", "Priority", "tt-col-pri")}
      ${th("assigned_to", "Assigned to", "tt-col-assignee")}
      ${th("time_left", "Time left", "tt-col-ttl")}
      ${th("created_at", "Created", "tt-col-age")}
    </tr></thead>
    <tbody>
      ${tasks.map(t => {
        const left = taskTimeLeft(t);
        const pct = taskUrgencyPct(t);
        const color = pct !== null && isOpen(t) ? urgencyColor(pct) : "";
        const assignee = t.assigned_to ? t.assigned_to.split("@")[0] : "";
        return `<tr class="tt-row ${!t.assigned_to ? 'tt-row-unassigned' : ''} ${left !== null && left <= 0 && isOpen(t) ? 'tt-row-expired' : ''}" onclick="openTask(${t.id})" title="Open task">
          <td class="tt-job">${esc(t.correlation_id || "—")}</td>
          <td class="tt-title" title="${esc(t.title)}">${esc(t.title)}</td>
          ${showApp ? `<td class="tt-app">${esc(t.application_name || "")}</td>` : ""}
          <td class="tt-queue">${esc(t.queue_name || "")}</td>
          <td><span class="badge badge-${t.status}">${t.status.replace(/_/g," ")}</span></td>
          <td><span class="tt-pri-dot priority-${t.priority}"></span> ${esc(t.priority || "")}</td>
          <td class="tt-assignee">${assignee ? esc(assignee) : '<span class="tt-unassigned">Unassigned</span>'}</td>
          <td class="tt-ttl" ${color ? `style="color:${color}"` : ""}>${isOpen(t) ? timeLeftLabel(left) : ""}</td>
          <td class="tt-age" title="${esc(formatDate(t.created_at))}">${timeAgo(t.created_at)}</td>
        </tr>`;
      }).join("")}
    </tbody>
  </table></div>`;
}

function setFilter(f) {
  taskFilter = f;
  render();
}


// ── Job ID search (Projects page) ───────────────────────────────────────────
// A calling system's job id travels as the task's correlation_id (DAS: JOB-YYYYMMDD-XXXXXX).
// Lists every task that job raised, across applications and queues, in the sortable table.
let jobSearch = null;   // { term, tasks } while a search is shown

async function searchJob(e) {
  if (e) e.preventDefault();
  const term = (document.getElementById("job-search-input").value || "").trim();
  if (!term) { jobSearch = null; renderJobSearch(); return; }
  document.getElementById("job-search-results").innerHTML = `<div class="empty-state">Searching…</div>`;
  let tasks = [];
  try {
    const r = await authFetch("/api/tasks?correlation_id=" + encodeURIComponent(term));
    tasks = r.ok ? await r.json() : [];
  } catch { tasks = []; }
  jobSearch = { term, tasks };
  renderJobSearch();
}

function clearJobSearch() {
  jobSearch = null;
  document.getElementById("job-search-input").value = "";
  renderJobSearch();
}

function renderJobSearch() {
  const box = document.getElementById("job-search-results");
  if (!box) return;
  if (!jobSearch) { box.innerHTML = ""; return; }
  const { term, tasks } = jobSearch;
  box.innerHTML = tasks.length
    ? `<div class="section-title">${tasks.length} task${tasks.length > 1 ? "s" : ""} for “${esc(term)}” <a class="clear-search" onclick="clearJobSearch()">clear</a></div>` +
      taskTableHtml(applySort(tasks), true)
    : `<div class="empty-state">No task with a Job ID containing “${esc(term)}”. <a class="clear-search" onclick="clearJobSearch()">clear</a></div>`;
}

// ── Task card HTML ──────────────────────────────────────────────────────────

function taskCardHtml(t) {
  const ago = timeAgo(t.created_at);
  const assignee = t.assigned_to ? t.assigned_to.split("@")[0] : "Unassigned";
  const appLabel = t.application_name ? `<span class="task-app-label">${esc(t.application_name)}</span>` : "";
  const queueLabel = t.queue_name || "";
  return `<div class="task-card" onclick="openTask(${t.id})">
    <div class="task-priority-bar priority-${t.priority}"></div>
    <div class="task-card-body">
      <div class="task-card-title">${esc(t.title)}</div>
      <div class="task-card-meta">
        ${appLabel}
        <span>${esc(queueLabel)}</span>
        <span>·</span>
        <span>${esc(assignee)}</span>
        <span>·</span>
        <span>${ago}</span>
      </div>
    </div>
    <div class="task-card-right">
      <span class="badge badge-${t.status}">${t.status.replace(/_/g," ")}</span>
      <span class="badge badge-${t.priority}">${t.priority}</span>
    </div>
  </div>`;
}

// ── Task detail modal ───────────────────────────────────────────────────────

async function openTask(id) {
  try {
    const r = await authFetch("/api/tasks/" + id);
    const t = await r.json();
    document.getElementById("modal-title").textContent = t.title;
    document.getElementById("modal-body").innerHTML = taskDetailHtml(t);
    document.getElementById("task-modal").style.display = "flex";

    const hasS3Artifact = (t.artifacts || []).some(a => typeof a === "string" && a.startsWith("s3://"));
    if (hasS3Artifact) loadDocumentPreview(id);
  } catch(e) { console.error(e); }
}

async function loadDocumentPreview(taskId) {
  const el = document.getElementById("doc-preview-" + taskId);
  if (!el) return;
  try {
    const r = await authFetch("/api/tasks/" + taskId + "/document");
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      el.textContent = "Could not load document: " + (err.detail || r.statusText);
      return;
    }
    const data = await r.json();
    el.textContent = data.content;
  } catch(e) {
    el.textContent = "Could not load document: " + e.message;
  }
}

// Any orchestrator's agent can put anything in Task.payload -- these are
// just common shapes worth special-casing so a human doesn't have to parse
// JSON to find the one sentence that explains the task. Everything else
// still falls through to a plain label/value table.
const PAYLOAD_NARRATIVE_KEYS = ["fraud_rationale", "rationale", "agent_rationale", "explanation"];
const PAYLOAD_SKIP_KEYS = ["correlation_id"]; // already shown in the Details grid above

function humanizeKey(k) {
  return k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function formatPayloadScalar(key, val) {
  if (typeof val === "number") {
    return /amount|price|cost|exposure/i.test(key) ? "$" + val.toLocaleString() : val.toLocaleString();
  }
  if (typeof val === "object") return JSON.stringify(val);
  return String(val);
}

function renderPayloadSection(payload) {
  const entries = Object.entries(payload).filter(
    ([k, v]) => v !== null && v !== undefined && v !== "" && !PAYLOAD_SKIP_KEYS.includes(k)
  );
  if (!entries.length) return "";

  const narrative = entries.find(([k]) => PAYLOAD_NARRATIVE_KEYS.includes(k));
  const tagGroups = entries.filter(([k, v]) => Array.isArray(v) && (!narrative || k !== narrative[0]));
  const rows = entries.filter(([k, v]) =>
    !Array.isArray(v) && (!narrative || k !== narrative[0])
  );

  let html = `<div class="modal-section"><div class="modal-section-title">Payload (from agent)</div>`;

  if (narrative) {
    html += `<div class="modal-why">${esc(String(narrative[1]))}</div>`;
  }

  for (const [k, arr] of tagGroups) {
    html += `<div class="modal-kv-label" style="margin-bottom:4px">${esc(humanizeKey(k))}</div>
      <div class="signal-tags">${arr.map(v => `<span class="signal-tag">${esc(String(v))}</span>`).join("")}</div>`;
  }

  if (rows.length) {
    html += `<div class="modal-kv" style="${tagGroups.length ? 'margin-top:8px' : ''}">` +
      rows.map(([k, v]) =>
        `<span class="modal-kv-label">${esc(humanizeKey(k))}</span><span class="modal-kv-value">${esc(formatPayloadScalar(k, v))}</span>`
      ).join("") +
      `</div>`;
  }

  html += `</div>`;
  return html;
}

function taskDetailHtml(t) {
  const isMyTask = currentUser && t.assigned_to === currentUser.email;
  const isAdmin  = currentUser && currentUser.role === "admin";
  const isManager = currentUser && currentUser.role === "manager";
  const canClaim = currentUser && !t.assigned_to && ["pending"].includes(t.status);
  const isActive = ["pending","in_progress"].includes(t.status);
  const isEscalated = t.status === "escalated";
  // Escalated tasks were handed up for someone with more authority to
  // decide -- only a manager or admin can, and they must be able to (before
  // this, no one could: the buttons required pending/in_progress).
  const canAct   = (isActive && (isMyTask || isAdmin || isManager))
                || (isEscalated && (isAdmin || isManager));
  const canEscalate = isActive && (isMyTask || isAdmin || isManager);

  let html = `
    <div class="modal-section">
      <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
        <span class="badge badge-${t.status}">${t.status.replace(/_/g," ")}</span>
        <span class="badge badge-${t.priority}">${t.priority}</span>
        ${t.pii ? '<span class="badge badge-pii">PII</span>' : ''}
        ${t.ttl_hours ? `<span class="badge badge-ttl">TTL ${t.ttl_hours}h → ${t.ttl_action || 'expire'}</span>` : ''}
      </div>
      <div class="modal-desc">${esc(t.description || "")}</div>
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Details</div>
      <div class="modal-kv">
        <span class="modal-kv-label">Application</span>
        <span class="modal-kv-value">${esc(t.application_name || "—")}</span>
        <span class="modal-kv-label">Queue</span>
        <span class="modal-kv-value">${esc(t.queue_name || "—")}</span>
        <span class="modal-kv-label">Orchestrator</span>
        <span class="modal-kv-value">${esc(t.source_orchestrator || "—")}</span>
        <span class="modal-kv-label">Topic</span>
        <span class="modal-kv-value">${esc(t.source_topic || "—")}</span>
        <span class="modal-kv-label">Reply To</span>
        <span class="modal-kv-value">${esc(t.reply_to || "—")}</span>
        <span class="modal-kv-label">Correlation ID</span>
        <span class="modal-kv-value">${esc(t.correlation_id || "—")}</span>
        <span class="modal-kv-label">Assigned to</span>
        <span class="modal-kv-value">${esc(t.assigned_to || "Unassigned")}</span>
        <span class="modal-kv-label">Created</span>
        <span class="modal-kv-value">${formatDate(t.created_at)}</span>
        ${t.due_date ? `<span class="modal-kv-label">Due</span><span class="modal-kv-value">${formatDate(t.due_date)}</span>` : ""}
        ${t.completed_at ? `<span class="modal-kv-label">Completed</span><span class="modal-kv-value">${formatDate(t.completed_at)}</span>` : ""}
      </div>
    </div>
  `;

  if (t.payload) {
    html += renderPayloadSection(t.payload);
  }

  if (t.artifacts && t.artifacts.length > 0) {
    // Artifacts arrive either as plain URI strings (e.g. "s3://bucket/key",
    // the current DAS/JCIDS shape) or as {name, pii} objects -- support both.
    html += `<div class="modal-section">
      <div class="modal-section-title">Artifacts</div>
      <div class="artifact-list">
        ${t.artifacts.map(a => {
          const uri = typeof a === "string" ? a : (a.url || a.name || "");
          const label = typeof a === "string" ? a : (a.name || a.url || "");
          const pii = typeof a === "object" && a.pii;
          const isWebLink = /^https?:\/\//i.test(uri);
          const title = isWebLink ? "Open document" : "Object storage URI -- see Document Preview below";
          return `<div class="artifact-item">
            <span class="artifact-icon">📄</span>
            <a class="artifact-name artifact-link" href="${esc(uri)}" target="_blank" rel="noopener" title="${esc(title)}">${esc(label)}</a>
            ${pii ? '<span class="badge badge-pii" style="font-size:9px">PII</span>' : ''}
          </div>`;
        }).join("")}
      </div>
    </div>`;
  }

  const s3Artifact = (t.artifacts || []).find(a => typeof a === "string" && a.startsWith("s3://"));
  if (s3Artifact) {
    html += `<div class="modal-section">
      <div class="modal-section-title">Document Preview</div>
      <div class="modal-payload" id="doc-preview-${t.id}">Loading document from object storage…</div>
    </div>`;
  }

  if (t.jira_ticket) {
    html += `<div class="modal-section">
      <div class="modal-section-title">Jira Ticket</div>
      <div class="artifact-list">
        <div class="artifact-item">
          <span class="artifact-icon">🎫</span>
          <span class="artifact-name">${esc(t.jira_ticket)}</span>
        </div>
      </div>
    </div>`;
  }

  if (t.result) {
    html += `<div class="modal-section">
      <div class="modal-section-title">Result (human decision)</div>
      <div class="modal-payload" style="color:var(--green)">${esc(JSON.stringify(t.result, null, 2))}</div>
    </div>`;
  }

  // Timeline
  if (t.actions && t.actions.length > 0) {
    html += `<div class="modal-section">
      <div class="modal-section-title">Timeline</div>
      <div class="timeline">
        ${t.actions.map(a => {
          const dotColor = a.action === "completed" ? "var(--green)"
            : a.action === "escalated" ? "var(--orange)"
            : a.action === "rejected" ? "var(--red)"
            : "var(--accent)";
          return `<div class="timeline-item">
            <div class="timeline-dot" style="background:${dotColor}"></div>
            <div class="timeline-content">
              <div class="timeline-action"><span class="timeline-actor">${esc(a.actor || "system")}</span> ${esc(a.action)}</div>
              ${a.comment ? `<div class="timeline-comment">${esc(a.comment)}</div>` : ""}
              <div class="timeline-time">${formatDate(a.created_at)}</div>
            </div>
          </div>`;
        }).join("")}
      </div>
    </div>`;
  }

  // Why there are no buttons, when a task is still open but not yours to decide
  if (!canClaim && !canAct && (isActive || isEscalated)) {
    const who = t.assigned_to ? t.assigned_to.split("@")[0] : "";
    const why = isEscalated
      ? "Escalated — waiting for a manager or admin to decide."
      : `Assigned to ${esc(who)} — only they, a manager or an admin can decide this task.`;
    html += `<div class="modal-section"><div class="modal-action-note">${why}</div></div>`;
  }

  // Actions
  if (canClaim || canAct) {
    html += `<div class="modal-section">
      <div class="modal-section-title">Comment</div>
      <textarea class="modal-comment-input" id="action-comment" placeholder="Add a note (optional)..."></textarea>
    </div>`;
    html += `<div class="modal-actions">`;
    if (canClaim) {
      html += `<button class="btn btn-primary btn-sm" onclick="taskAction(${t.id},'claim')">Claim Task</button>`;
    }
    if (canAct) {
      html += `<button class="btn btn-green btn-sm" onclick="taskAction(${t.id},'complete')">Approve</button>`;
      html += `<button class="btn btn-red btn-sm" onclick="taskAction(${t.id},'reject')">Reject</button>`;
      if (canEscalate) {
        html += `<button class="btn btn-amber btn-sm" onclick="taskAction(${t.id},'escalate')">Escalate</button>`;
      }
    }
    html += `</div>`;
    html += `<div class="modal-action-error" id="action-error" role="alert"></div>`;
  }

  return html;
}

async function taskAction(taskId, action) {
  const comment = document.getElementById("action-comment")?.value || "";
  const errEl = document.getElementById("action-error");
  const buttons = document.querySelectorAll(".modal-actions button");
  const showError = (msg) => {
    if (errEl) errEl.textContent = msg;
    buttons.forEach(b => { b.disabled = false; });
  };
  if (errEl) errEl.textContent = "";
  buttons.forEach(b => { b.disabled = true; });   // no double-submits

  let r;
  try {
    r = await authFetch(`/api/tasks/${taskId}/action`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ action, actor: currentUser.email, comment: comment || null })
    });
  } catch (e) {
    console.error(e);
    return showError("Couldn't reach the server — the action was not recorded. Try again.");
  }
  // authFetch only throws on 401; a 400/404/409 used to be treated as
  // success here, so a failed click just closed the dialog silently.
  if (!r.ok) {
    let detail = "";
    try { detail = (await r.json()).detail || ""; } catch (_) {}
    if (r.status === 409) return showError("Someone else already decided this task. Close and reopen it to see the current state.");
    return showError(detail ? `Not recorded: ${detail}` : `Not recorded (HTTP ${r.status}).`);
  }

  if (activeAppId) await loadTasksForApp(activeAppId);
  else { await loadTasks(); if (jobSearch) await searchJob(); render(); }
  // Claiming makes the task yours -- reopen it so Approve/Reject are right
  // there, instead of closing the dialog and making the user find it again.
  if (action === "claim" || action === "start") await openTask(taskId);
  else closeTaskModal();
}

function closeTaskModal() { document.getElementById("task-modal").style.display = "none"; }
function closeModal(e) { if (e.target === e.currentTarget) closeTaskModal(); }

// ── Helpers ─────────────────────────────────────────────────────────────────

function esc(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function timeAgo(iso) {
  if (!iso) return "";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s/60) + "m ago";
  if (s < 86400) return Math.floor(s/3600) + "h ago";
  return Math.floor(s/86400) + "d ago";
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

// ── Administration panels ───────────────────────────────────────────────────

let HIL_PROFILE = "public";
fetch("/api/meta").then(r => r.json()).then(m => {
  HIL_PROFILE = m.profile || "public";
  // HIL_BADGE from the instance's env file (e.g. "Internal"); none if unset
  document.querySelectorAll(".hil-badge").forEach(el => {
    el.textContent = m.badge || "";
    el.hidden = !m.badge;
  });
  if (m.badge) document.title = `${document.title} · ${m.badge}`;
}).catch(() => {});

function renderAdminLanding() {
  const cards = [
    { id: "admin-iam",      icon: "⊛", title: "Users & Roles",           desc: "Create users, assign roles, manage HILs, Managers, and Admins across projects." },
    { id: "admin-projects", icon: "◈", title: "Projects & Applications", desc: "Create projects, register applications, assign Project and App Admins." },
    { id: "admin-policies", icon: "⊡", title: "Policies",               desc: "TTL defaults, PII handling, artifact retention, alert and notification rules." },
    { id: "admin-rules",    icon: "⊞", title: "Rules & Automation",     desc: "Auto-approve, auto-reject, escalation chains, round-robin assignment, SLA." },
    { id: "admin-queues",   icon: "◫", title: "Queues & Topics",        desc: "Kafka topic mappings, queue configuration, SLA targets per queue." },
    { id: "admin-audit",    icon: "▤", title: "Audit Log",              desc: "Full chain of custody — who did what, when. Export for compliance." },
  ];
  const note = HIL_PROFILE === "public"
    ? `<div class="admin-readonly-note">Public demo: users and roles are view-only here.</div>` : "";
  document.getElementById("admin-landing").innerHTML = `${note}
    <div class="admin-card-grid">
      ${cards.map(c => `<div class="admin-console-card" onclick="switchTab('${c.id}')">
        <div class="admin-console-icon">${c.icon}</div>
        <div class="admin-console-body">
          <div class="admin-console-title">${c.title}</div>
          <div class="admin-console-desc">${c.desc}</div>
        </div>
      </div>`).join("")}
    </div>
  `;
}

async function renderAdminIAM() {
  let users = [];
  try { const r = await authFetch("/api/users"); users = await r.json(); } catch {}
  let apps = [];
  try { const r = await authFetch("/api/applications"); apps = await r.json(); } catch {}

  document.getElementById("admin-iam-content").innerHTML = `
    <div class="admin-section">
      <div class="section-title">Users</div>
      <table class="dash-queue-table">
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Department</th><th>Team</th></tr></thead>
        <tbody>
          ${users.map(u => `<tr>
            <td class="dash-qt-name">${esc(u.name)}</td>
            <td>${esc(u.email)}</td>
            <td><span class="badge badge-${u.role === 'admin' ? 'escalated' : u.role === 'manager' ? 'in_progress' : 'completed'}">${u.role}</span></td>
            <td class="dash-qt-app">${esc(u.department || "—")}</td>
            <td class="dash-qt-app">${esc(u.team || "—")}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>

    <div class="admin-section" style="margin-top:24px">
      <div class="section-title">Applications</div>
      <table class="dash-queue-table">
        <thead><tr><th>Application</th><th>Project</th><th>Queues</th></tr></thead>
        <tbody>
          ${apps.map(a => `<tr>
            <td class="dash-qt-name">${esc(a.name)}</td>
            <td class="dash-qt-app">${esc(a.project)}</td>
            <td class="dash-qt-count">${a.queue_count}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>

    <div class="admin-hint">
      <div class="section-title" style="margin-top:24px">Planned</div>
      <div class="admin-planned-list">
        <div class="admin-planned-item">Create / edit users</div>
        <div class="admin-planned-item">Assign users to applications</div>
        <div class="admin-planned-item">Role & group management</div>
        <div class="admin-planned-item">SSO / LDAP integration</div>
      </div>
    </div>
  `;
}

function renderAdminPolicies() {
  const queueOptions = allQueues.map(q => `<option value="${q.id}">${esc(q.name)}</option>`).join("");

  document.getElementById("admin-policies-content").innerHTML = `
    <div class="admin-section">
      <div class="section-title">Queue Policies</div>
      <p class="admin-desc">Default TTL, PII handling, and auto-action rules per queue.</p>
      <table class="dash-queue-table" style="margin-top:12px">
        <thead><tr><th>Queue</th><th>TTL</th><th>Auto Action</th><th>PII</th></tr></thead>
        <tbody>
          ${allQueues.map(q => `<tr>
            <td class="dash-qt-name">${esc(q.name)}</td>
            <td>${q.ttl_hours ? q.ttl_hours + 'h' : '—'}</td>
            <td>${q.ttl_action ? `<span class="badge badge-${q.ttl_action === 'reject' ? 'rejected' : q.ttl_action === 'approve' ? 'completed' : 'pending'}">${q.ttl_action}</span>` : '—'}</td>
            <td>${q.pii ? '<span class="badge badge-pii">PII</span>' : '—'}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>

    <div class="admin-section" style="margin-top:24px">
      <div class="section-title">Add Policy</div>
      <div class="admin-form">
        <div class="admin-form-row">
          <label class="admin-form-label">Template</label>
          <select class="admin-form-input" id="policy-template" onchange="policyTemplateChanged()">
            <option value="">— select template —</option>
            <option value="ttl">TTL / Auto-Action</option>
            <option value="pii">PII Handling</option>
            <option value="retention">Artifact Retention</option>
            <option value="alert">Alert / Notification</option>
          </select>
        </div>
        <div id="policy-params"></div>
      </div>
    </div>
  `;
}

function policyTemplateChanged() {
  const tpl = document.getElementById("policy-template").value;
  const queueOptions = allQueues.map(q => `<option value="${q.id}">${esc(q.name)}</option>`).join("");
  let html = "";

  if (tpl === "ttl") {
    html = `
      <div class="admin-form-row"><label class="admin-form-label">Queue</label>
        <select class="admin-form-input">${queueOptions}</select></div>
      <div class="admin-form-row"><label class="admin-form-label">TTL (hours)</label>
        <input class="admin-form-input" type="number" value="168" min="1" /></div>
      <div class="admin-form-row"><label class="admin-form-label">Action on Expiry</label>
        <select class="admin-form-input">
          <option value="reject">Reject</option><option value="approve">Auto-Approve</option>
          <option value="escalate">Escalate</option><option value="expire">Expire (no action)</option>
        </select></div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" disabled>Save Policy</button>
    `;
  } else if (tpl === "pii") {
    html = `
      <div class="admin-form-row"><label class="admin-form-label">Queue</label>
        <select class="admin-form-input">${queueOptions}</select></div>
      <div class="admin-form-row"><label class="admin-form-label">PII Enabled</label>
        <select class="admin-form-input"><option value="1">Yes</option><option value="0">No</option></select></div>
      <div class="admin-form-row"><label class="admin-form-label">Mask Fields</label>
        <input class="admin-form-input" placeholder="payload.ssn, payload.name" /></div>
      <div class="admin-form-row"><label class="admin-form-label">Auto-Purge After</label>
        <select class="admin-form-input"><option value="30">30 days</option><option value="90">90 days</option><option value="365">1 year</option></select></div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" disabled>Save Policy</button>
    `;
  } else if (tpl === "retention") {
    html = `
      <div class="admin-form-row"><label class="admin-form-label">Queue</label>
        <select class="admin-form-input">${queueOptions}</select></div>
      <div class="admin-form-row"><label class="admin-form-label">Retain Artifacts</label>
        <select class="admin-form-input"><option value="30">30 days</option><option value="90">90 days</option><option value="365">1 year</option><option value="0">Forever</option></select></div>
      <div class="admin-form-row"><label class="admin-form-label">Delete Completed Tasks After</label>
        <select class="admin-form-input"><option value="0">Never</option><option value="90">90 days</option><option value="365">1 year</option></select></div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" disabled>Save Policy</button>
    `;
  } else if (tpl === "alert") {
    html = `
      <div class="admin-form-row"><label class="admin-form-label">Queue</label>
        <select class="admin-form-input">${queueOptions}</select></div>
      <div class="admin-form-row"><label class="admin-form-label">Alert On</label>
        <select class="admin-form-input">
          <option value="created">Task Created</option><option value="ttl_warning">TTL Warning (80%)</option>
          <option value="escalated">Escalated</option><option value="expired">Expired</option>
        </select></div>
      <div class="admin-form-row"><label class="admin-form-label">Channel</label>
        <select class="admin-form-input">
          <option value="email">Email</option><option value="sms">SMS</option>
          <option value="slack">Slack Webhook</option><option value="webhook">Custom Webhook</option>
        </select></div>
      <div class="admin-form-row"><label class="admin-form-label">Recipients</label>
        <input class="admin-form-input" placeholder="user@k9x.ai, manager@k9x.ai" /></div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" disabled>Save Policy</button>
    `;
  }

  document.getElementById("policy-params").innerHTML = html;
}

function renderAdminRules() {
  const RULE_TEMPLATES = [
    { id: "auto_approve",  name: "Auto-Approve All",    desc: "Automatically approve all pending tasks in a queue when conditions are met.", status: "not configured" },
    { id: "auto_reject",   name: "Auto-Reject Expired", desc: "Reject tasks that exceed TTL with no human action. Publishes auto:true to reply_to.", status: "active" },
    { id: "escalation",    name: "Escalation Chain",    desc: "Auto-escalate to manager when task reaches a percentage of TTL without action.", status: "not configured" },
    { id: "round_robin",   name: "Round-Robin Assignment", desc: "Distribute incoming tasks evenly across workers assigned to the application.", status: "not configured" },
    { id: "sla_breach",    name: "SLA Breach Alert",    desc: "Alert when task exceeds SLA target time. Track SLA compliance per queue.", status: "not configured" },
    { id: "bulk_action",   name: "Bulk Approve/Reject", desc: "Allow admins to approve or reject all pending tasks in a queue with one action.", status: "not configured" },
  ];
  const queueOptions = allQueues.map(q => `<option value="${q.id}">${esc(q.name)}</option>`).join("");

  document.getElementById("admin-rules-content").innerHTML = `
    <div class="admin-section">
      <div class="section-title">Active Rules</div>
      <div class="admin-rules-grid">
        ${RULE_TEMPLATES.map(r => `<div class="admin-rule-card${r.status === 'active' ? ' admin-rule-active' : ''}" onclick="configureRule('${r.id}')">
          <div class="admin-rule-title">${esc(r.name)}</div>
          <div class="admin-rule-desc">${esc(r.desc)}</div>
          <div class="admin-rule-status">
            <span class="badge badge-${r.status === 'active' ? 'completed' : 'pending'}">${r.status}</span>
          </div>
        </div>`).join("")}
      </div>
    </div>

    <div class="admin-section" style="margin-top:24px">
      <div class="section-title">Configure Rule</div>
      <div class="admin-form" id="rule-config-form">
        <div class="admin-form-hint">Click a rule card above to configure it.</div>
      </div>
    </div>
  `;
}

function configureRule(ruleId) {
  const queueOptions = allQueues.map(q => `<option value="${q.id}">${esc(q.name)}</option>`).join("");
  let html = "";

  const titles = {
    auto_approve: "Auto-Approve All", auto_reject: "Auto-Reject Expired",
    escalation: "Escalation Chain", round_robin: "Round-Robin Assignment",
    sla_breach: "SLA Breach Alert", bulk_action: "Bulk Approve/Reject"
  };

  html += `<div class="admin-form-title">${titles[ruleId] || ruleId}</div>`;

  if (ruleId === "auto_approve" || ruleId === "auto_reject") {
    html += `
      <div class="admin-form-row"><label class="admin-form-label">Apply to Queue</label>
        <select class="admin-form-input"><option value="all">All Queues</option>${queueOptions}</select></div>
      <div class="admin-form-row"><label class="admin-form-label">Condition</label>
        <select class="admin-form-input">
          <option value="ttl_expired">TTL Expired</option><option value="low_priority">Low Priority Only</option>
          <option value="always">Always (all pending)</option>
        </select></div>
      <div class="admin-form-row"><label class="admin-form-label">Enabled</label>
        <select class="admin-form-input"><option value="1">Yes</option><option value="0">No</option></select></div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" disabled>Save Rule</button>
    `;
  } else if (ruleId === "escalation") {
    html += `
      <div class="admin-form-row"><label class="admin-form-label">Apply to Queue</label>
        <select class="admin-form-input"><option value="all">All Queues</option>${queueOptions}</select></div>
      <div class="admin-form-row"><label class="admin-form-label">Escalate at % of TTL</label>
        <input class="admin-form-input" type="number" value="80" min="10" max="99" />%</div>
      <div class="admin-form-row"><label class="admin-form-label">Escalate to</label>
        <select class="admin-form-input"><option value="manager">Manager</option><option value="admin">Admin</option></select></div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" disabled>Save Rule</button>
    `;
  } else if (ruleId === "round_robin") {
    html += `
      <div class="admin-form-row"><label class="admin-form-label">Apply to Queue</label>
        <select class="admin-form-input"><option value="all">All Queues</option>${queueOptions}</select></div>
      <div class="admin-form-row"><label class="admin-form-label">Assignment Strategy</label>
        <select class="admin-form-input">
          <option value="round_robin">Round Robin</option><option value="least_busy">Least Busy</option>
          <option value="random">Random</option>
        </select></div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" disabled>Save Rule</button>
    `;
  } else if (ruleId === "sla_breach") {
    html += `
      <div class="admin-form-row"><label class="admin-form-label">Apply to Queue</label>
        <select class="admin-form-input"><option value="all">All Queues</option>${queueOptions}</select></div>
      <div class="admin-form-row"><label class="admin-form-label">SLA Target (hours)</label>
        <input class="admin-form-input" type="number" value="24" min="1" /></div>
      <div class="admin-form-row"><label class="admin-form-label">Alert Channel</label>
        <select class="admin-form-input">
          <option value="email">Email</option><option value="slack">Slack</option><option value="webhook">Webhook</option>
        </select></div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" disabled>Save Rule</button>
    `;
  } else if (ruleId === "bulk_action") {
    html += `
      <div class="admin-form-row"><label class="admin-form-label">Apply to Queue</label>
        <select class="admin-form-input">${queueOptions}</select></div>
      <div class="admin-form-row"><label class="admin-form-label">Action</label>
        <select class="admin-form-input">
          <option value="approve_all">Approve All Pending</option>
          <option value="reject_all">Reject All Pending</option>
        </select></div>
      <div class="admin-form-row"><label class="admin-form-label">Comment</label>
        <input class="admin-form-input" placeholder="Bulk action reason..." /></div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" disabled>Execute</button>
    `;
  }

  document.getElementById("rule-config-form").innerHTML = html;
}

async function renderAdminProjects() {
  let projects = [];
  try { const r = await authFetch("/api/projects"); projects = await r.json(); } catch {}
  let apps = [];
  try { const r = await authFetch("/api/applications"); apps = await r.json(); } catch {}

  document.getElementById("admin-projects-content").innerHTML = `
    <div class="admin-section">
      <div class="section-title">Projects</div>
      <table class="dash-queue-table">
        <thead><tr><th>Project</th><th>Description</th><th>Applications</th></tr></thead>
        <tbody>
          ${projects.map(p => `<tr>
            <td class="dash-qt-name">${esc(p.name)}</td>
            <td class="dash-qt-app">${esc(p.description || "")}</td>
            <td class="dash-qt-count">${p.app_count}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>

    <div class="admin-section" style="margin-top:24px">
      <div class="section-title">Applications</div>
      <table class="dash-queue-table">
        <thead><tr><th>Application</th><th>Project</th><th>Queues</th></tr></thead>
        <tbody>
          ${apps.map(a => `<tr>
            <td class="dash-qt-name">${esc(a.name)}</td>
            <td class="dash-qt-app">${esc(a.project)}</td>
            <td class="dash-qt-count">${a.queue_count}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

async function renderAdminQueues() {
  try { allQueues = await (await authFetch("/api/queues")).json(); } catch { allQueues = []; }
  document.getElementById("admin-queues-content").innerHTML = `
    <div class="admin-section">
      <div class="section-title">Queue → Topic Mappings</div>
      <table class="dash-queue-table">
        <thead><tr><th>Queue</th><th>Application</th><th>Kafka Topic</th><th>TTL</th><th>Auto Action</th><th>PII</th><th>Active</th></tr></thead>
        <tbody>
          ${allQueues.map(q => `<tr>
            <td class="dash-qt-name">${esc(q.name)}</td>
            <td class="dash-qt-app">${esc(q.application || "")}</td>
            <td style="font-family:monospace;font-size:11px;color:var(--muted)">${esc(q.topic || "")}</td>
            <td>${q.ttl_hours ? q.ttl_hours + 'h' : '—'}</td>
            <td>${q.ttl_action ? `<span class="badge badge-${q.ttl_action === 'reject' ? 'rejected' : q.ttl_action === 'approve' ? 'completed' : 'pending'}">${q.ttl_action}</span>` : '—'}</td>
            <td>${q.pii ? '<span class="badge badge-pii">PII</span>' : '—'}</td>
            <td class="dash-qt-count">${q.active_count}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderAdminAudit() {
  document.getElementById("admin-audit-content").innerHTML = `
    <div class="admin-section">
      <div class="section-title">Audit Trail</div>
      <p class="admin-desc">Every task action — created, assigned, started, approved, rejected, escalated — logged with actor and timestamp.</p>
      <div class="admin-planned-list" style="margin-top:16px">
        <div class="admin-planned-item">Full audit log viewer with search and filters</div>
        <div class="admin-planned-item">Export to CSV / JSON for compliance reporting</div>
        <div class="admin-planned-item">Chain of custody per task — from creation to resolution</div>
        <div class="admin-planned-item">User activity report — actions per user per period</div>
      </div>
    </div>
  `;
}

// ── Theme toggle ────────────────────────────────────────────────────────────

function toggleTheme() {
  const dark = document.body.classList.toggle("dark");
  localStorage.setItem("k9x_hil_dark", dark ? "1" : "0");
  const btn = document.getElementById("theme-btn");
  if (btn) btn.textContent = dark ? "☀️" : "🌙";
}

function initTheme() {
  const saved = localStorage.getItem("k9x_hil_dark");
  if (saved === "1") {
    document.body.classList.add("dark");
    const btn = document.getElementById("theme-btn");
    if (btn) btn.textContent = "☀️";
  }
}

// ── Init ────────────────────────────────────────────────────────────────────

(function init() {
  initTheme();
  const saved = localStorage.getItem("k9x_hil_user");
  const savedToken = localStorage.getItem("k9x_hil_token");
  if (saved && savedToken) {
    try {
      currentUser = JSON.parse(saved);
      authToken = savedToken;
    } catch { logout(); return; }
    // The cached login response can be stale (e.g. the user's role changed
    // since they signed in) -- refresh it before showing the app. If the
    // refresh fails for any reason other than an expired session, fall back
    // to the cached copy rather than blocking the UI.
    fetch("/api/auth/me", { headers: { "Authorization": "Bearer " + authToken } })
      .then(r => {
        if (r.status === 401) { logout(); return null; }
        return r.ok ? r.json() : undefined;
      })
      .then(me => {
        if (me === null) return;              // session expired -> login shown
        if (me) {
          currentUser = Object.assign({}, currentUser, me);
          localStorage.setItem("k9x_hil_user", JSON.stringify(currentUser));
        }
        showApp();
      })
      .catch(() => showApp());
  }
})();
