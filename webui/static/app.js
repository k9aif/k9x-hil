/* k9x HIL — Case Management UI */

let currentUser = null;
let authToken = null;
let activeTab = "dashboard";
let activeAppId = null;
let allTasks = [];
let dashData = null;
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

function logout() {
  currentUser = null;
  authToken = null;
  localStorage.removeItem("k9x_hil_user");
  localStorage.removeItem("k9x_hil_token");
  allTasks = []; dashData = null; allQueues = []; activeAppId = null;
  document.getElementById("user-chip").style.display = "none";
  document.getElementById("user-menu").style.display = "none";
  document.getElementById("panel-login").classList.add("active");
  ["dashboard","mytasks","alltasks","queues"].forEach(p =>
    document.getElementById("panel-" + p).classList.remove("active"));
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
  buildAppTabs();
  // Show admin button for admins
  const adminBtn = document.getElementById("header-admin-btn");
  if (adminBtn) adminBtn.style.display = currentUser.role === "admin" ? "flex" : "none";
  switchTab("dashboard");
  loadAll();
}

// ── Application tabs ────────────────────────────────────────────────────────

function buildAppTabs() {
  const nav = document.getElementById("app-tabs");
  if (!nav || !currentUser) return;
  nav.innerHTML = "";
  const apps = currentUser.applications || [];
  if (apps.length === 0) return;

  // Group by project
  const byProject = {};
  apps.forEach(a => {
    if (!byProject[a.project]) byProject[a.project] = [];
    byProject[a.project].push(a);
  });

  Object.keys(byProject).forEach(proj => {
    const projLbl = document.createElement("div");
    projLbl.className = "nav-project-label";
    projLbl.innerHTML = `<span style="font-size:9px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px">Project:</span> ${esc(proj)}`;
    nav.appendChild(projLbl);

    const appLbl = document.createElement("div");
    appLbl.style.cssText = "font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;padding:4px 16px 2px;";
    appLbl.textContent = "Applications";
    nav.appendChild(appLbl);

    byProject[proj].forEach(a => {
      const btn = document.createElement("button");
      btn.className = "nav-item nav-app-item";
      btn.id = "nav-app-" + a.id;
      btn.innerHTML = `<span class="nav-icon">◉</span> ${esc(a.name)} <span class="nav-badge nav-app-badge" id="badge-app-${a.id}" style="display:none">0</span>`;
      btn.onclick = () => switchToApp(a.id);
      nav.appendChild(btn);
    });
  });
}

function switchToApp(appId) {
  activeAppId = appId;
  activeTab = "mytasks";
  taskFilter = "all";

  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  const navEl = document.getElementById("nav-app-" + appId);
  if (navEl) navEl.classList.add("active");

  ["dashboard","mytasks","alltasks","queues"].forEach(p => {
    document.getElementById("panel-" + p).classList.remove("active");
  });
  document.getElementById("panel-mytasks").classList.add("active");

  // Update sidebar desc
  document.querySelectorAll(".sidebar-desc").forEach(d => d.style.display = "none");
  document.getElementById("sidebar-mytasks").style.display = "block";

  const app = (currentUser.applications || []).find(a => a.id === appId);
  document.getElementById("header-tab-title").textContent = app ? app.name : "Tasks";

  loadTasksForApp(appId);
}

async function loadTasksForApp(appId) {
  try {
    const r = await authFetch("/api/tasks?application_id=" + appId);
    allTasks = await r.json();
  } catch { allTasks = []; }
  renderMyTasks();
  updateBadges();
}

// ── Data loading ────────────────────────────────────────────────────────────

async function loadAll() {
  await Promise.all([loadTasks(), loadDashboard(), loadQueues()]);
  render();
}

async function loadTasks() {
  try {
    const r = await authFetch("/api/tasks");
    allTasks = await r.json();
  } catch { allTasks = []; }
}

async function loadDashboard() {
  try {
    const r = await authFetch("/api/dashboard");
    dashData = await r.json();
  } catch { dashData = null; }
}

async function loadQueues() {
  try {
    const r = await authFetch("/api/queues");
    allQueues = await r.json();
  } catch { allQueues = []; }
}

// ── Tab switching ───────────────────────────────────────────────────────────

function switchTab(tab) {
  activeTab = tab;
  activeAppId = null;
  taskFilter = "all";

  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  const navEl = document.getElementById("nav-" + tab);
  if (navEl) navEl.classList.add("active");

  const allPanels = ["dashboard","mytasks","alltasks","queues","admin","admin-iam","admin-projects","admin-policies","admin-rules","admin-queues","admin-audit"];
  allPanels.forEach(p => {
    const panel = document.getElementById("panel-" + p);
    if (panel) panel.classList.remove("active");
    const sd = document.getElementById("sidebar-" + p);
    if (sd) sd.style.display = "none";
  });
  const panel = document.getElementById("panel-" + tab);
  if (panel) panel.classList.add("active");
  const sd = document.getElementById("sidebar-" + tab);
  if (sd) sd.style.display = "block";

  const titles = {
    dashboard: "Dashboard", mytasks: "My Tasks", alltasks: "All Tasks", queues: "Queues",
    admin: "Administration", "admin-iam": "Users & Roles", "admin-projects": "Projects & Applications",
    "admin-policies": "Policies", "admin-rules": "Rules & Automation",
    "admin-queues": "Queues & Topics", "admin-audit": "Audit Log"
  };
  document.getElementById("header-tab-title").textContent = titles[tab] || tab;

  if (tab === "dashboard") loadAll();
  else if (tab === "alltasks") { loadTasks().then(() => render()); }
  else if (tab === "queues") { loadQueues().then(() => render()); }
  else if (tab === "admin") renderAdminLanding();
  else if (tab === "admin-iam") renderAdminIAM();
  else if (tab === "admin-projects") renderAdminProjects();
  else if (tab === "admin-policies") renderAdminPolicies();
  else if (tab === "admin-rules") renderAdminRules();
  else if (tab === "admin-queues") renderAdminQueues();
  else if (tab === "admin-audit") renderAdminAudit();
  else render();
}

// ── Rendering ───────────────────────────────────────────────────────────────

function render() {
  if (activeTab === "dashboard") renderDashboard();
  if (activeTab === "mytasks")   renderMyTasks();
  if (activeTab === "alltasks")  renderAllTasks();
  if (activeTab === "queues")    renderQueues();
  updateBadges();
}

function updateBadges() {
  if (!currentUser) return;
  // Per-app badges
  (currentUser.applications || []).forEach(app => {
    const appTasks = allTasks.filter(t => t.application_id === app.id && t.assigned_to === currentUser.email && ["pending","in_progress"].includes(t.status));
    const badge = document.getElementById("badge-app-" + app.id);
    if (badge) {
      if (appTasks.length > 0) { badge.textContent = appTasks.length; badge.style.display = "inline"; }
      else { badge.style.display = "none"; }
    }
  });
  // Global my tasks badge
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

// ── Dashboard — Queue-centric, grouped by Project → Application ────────────

function renderDashboard() {
  if (!dashData) return;
  const d = dashData;
  document.getElementById("stat-cards").innerHTML = [
    statCard("Pending",     d.pending,     "var(--amber)",  "Awaiting action"),
    statCard("In Progress", d.in_progress, "var(--blue)",   "Being worked on"),
    statCard("Completed",   d.completed,   "var(--green)",  "Resolved"),
    statCard("Escalated",   d.escalated,   "var(--orange)", "Needs attention"),
    statCard("Critical",    d.critical,    "var(--red)",    "Urgent priority"),
    statCard("Unassigned",  d.unassigned,  "var(--muted)",  "Needs assignment"),
  ].join("");

  // Pie chart — status breakdown across all active tasks
  const statusCounts = { pending: d.pending, in_progress: d.in_progress, completed: d.completed, escalated: d.escalated, rejected: d.rejected };
  const pieHtml = renderPieChart(statusCounts);

  // Queue summary table with ending-soon counts, grouped by Application with
  // a subtotal row per app (Active/Ending<24h summed across its queues) so
  // the per-app rollup is visible at a glance without losing per-queue detail.
  const queueRows = allQueues.map(q => {
    const qTasks = allTasks.filter(t => t.queue_name === q.name);
    const active = qTasks.filter(t => ["pending","in_progress"].includes(t.status)).length;
    const ending24h = qTasks.filter(t => {
      if (!["pending","in_progress"].includes(t.status)) return false;
      const left = taskTimeLeft(t);
      return left !== null && left > 0 && left <= 86400000;
    }).length;
    return { name: q.name, app: q.application, topic: q.topic, active, ending24h, appId: q.application_id, queueId: q.id };
  });

  const appGroups = new Map(); // appId -> { app, rows: [] }
  for (const r of queueRows) {
    if (!appGroups.has(r.appId)) appGroups.set(r.appId, { app: r.app, rows: [] });
    appGroups.get(r.appId).rows.push(r);
  }
  const sortedApps = [...appGroups.entries()].sort((a, b) => a[1].app.localeCompare(b[1].app));

  const groupsHtml = sortedApps.map(([appId, group]) => {
    const rows = [...group.rows].sort((a, b) => a.name.localeCompare(b.name));
    const subActive = rows.reduce((s, r) => s + r.active, 0);
    const subEnding = rows.reduce((s, r) => s + r.ending24h, 0);
    const subtotalRow = `<tr class="dash-app-subtotal" onclick="filterByApplication(${appId},'${esc(group.app)}')">
      <td class="dash-app-name" colspan="2">${esc(group.app)}</td>
      <td class="dash-qt-count">${subActive}</td>
      <td class="dash-qt-urgent${subEnding > 0 ? ' dash-qt-red' : ''}">${subEnding > 0 ? subEnding : '—'}</td>
    </tr>`;
    const detailRows = rows.map(r => `<tr class="dash-queue-row" onclick="event.stopPropagation(); filterByQueue(${r.queueId},'${esc(r.name)}')">
      <td class="dash-qt-name dash-qt-nested">${esc(r.name)}</td>
      <td></td>
      <td class="dash-qt-count">${r.active}</td>
      <td class="dash-qt-urgent${r.ending24h > 0 ? ' dash-qt-red' : ''}">${r.ending24h > 0 ? r.ending24h : '—'}</td>
    </tr>`).join("");
    return subtotalRow + detailRows;
  }).join("");

  let html = `<div class="dash-overview">
    <div class="dash-pie-section">
      <div class="section-title">Status Breakdown</div>
      ${pieHtml}
    </div>
    <div class="dash-table-section">
      <div class="section-title">Queue Summary</div>
      <table class="dash-queue-table">
        <thead><tr>
          <th>Queue</th><th>Application</th><th>Active</th><th>Ending &lt;24h</th>
        </tr></thead>
        <tbody>
          ${groupsHtml}
        </tbody>
      </table>
    </div>
  </div>`;

  // Dashboard is a summary, not a task browser: stat cards + Recent Activity
  // (pie chart, Queue Summary table) only. Clicking a queue row above already
  // navigates to that queue's filtered task list via filterByQueue() -- the
  // per-app/per-queue task cards that used to repeat below this were fully
  // redundant with that click-through and with the Queues page.
  document.getElementById("recent-tasks").innerHTML = html;
}

function renderPieChart(statusCounts) {
  const entries = [
    { label: "Pending",     value: statusCounts.pending || 0,     color: "#f59e0b" },
    { label: "In Progress", value: statusCounts.in_progress || 0, color: "#6366f1" },
    { label: "Completed",   value: statusCounts.completed || 0,   color: "#10b981" },
    { label: "Escalated",   value: statusCounts.escalated || 0,   color: "#fb923c" },
    { label: "Rejected",    value: statusCounts.rejected || 0,    color: "#ef4444" },
  ];
  const total = entries.reduce((s, e) => s + e.value, 0);
  if (total === 0) return '<div class="dash-pie-empty">No tasks</div>';

  const cx = 80, cy = 80, r = 70;
  let startAngle = -Math.PI / 2;
  let paths = "";

  entries.forEach(e => {
    if (e.value === 0) return;
    const pct = e.value / total;
    const angle = pct * 2 * Math.PI;
    const endAngle = startAngle + angle;
    const largeArc = angle > Math.PI ? 1 : 0;
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    if (pct >= 1) {
      paths += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${e.color}" />`;
    } else {
      paths += `<path d="M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${largeArc},1 ${x2},${y2} Z" fill="${e.color}" />`;
    }
    startAngle = endAngle;
  });

  const legend = entries.filter(e => e.value > 0).map(e =>
    `<div class="pie-legend-item">
      <span class="pie-legend-dot" style="background:${e.color}"></span>
      <span class="pie-legend-label">${e.label}</span>
      <span class="pie-legend-value">${e.value}</span>
    </div>`
  ).join("");

  return `<div class="pie-wrap">
    <svg viewBox="0 0 160 160" width="140" height="140">${paths}</svg>
    <div class="pie-legend">${legend}</div>
  </div>`;
}

function statCard(label, value, color, sub) {
  return `<div class="stat-card">
    <div class="stat-card-label">${label}</div>
    <div class="stat-card-value" style="color:${color}">${value}</div>
    <div class="stat-card-sub">${sub}</div>
  </div>`;
}

// ── My Tasks (filtered by app if selected) ──────────────────────────────────

function renderMyTasks() {
  if (!currentUser) return;
  let mine = allTasks.filter(t => t.assigned_to === currentUser.email);
  if (activeAppId) mine = allTasks.filter(t => t.application_id === activeAppId);
  const filtered = applyFilter(mine);
  const sorted = applySort(filtered);

  document.getElementById("mytask-filters").innerHTML = filterBar();
  document.getElementById("mytask-list").innerHTML = sorted.length
    ? taskTableHtml(sorted)
    : `<div class="empty-state"><div class="empty-state-icon">◇</div><div class="empty-state-text">${activeAppId ? "No tasks in this application" : "No tasks assigned to you"}</div></div>`;
}

// ── All Tasks ───────────────────────────────────────────────────────────────

function renderAllTasks() {
  const filtered = applyFilter(allTasks);
  const sorted = applySort(filtered);
  document.getElementById("alltask-filters").innerHTML = filterBar();
  document.getElementById("alltask-list").innerHTML = sorted.length
    ? taskTableHtml(sorted)
    : '<div class="empty-state"><div class="empty-state-icon">◇</div><div class="empty-state-text">No tasks matching filter</div></div>';
}

function applyFilter(tasks) {
  if (taskFilter === "all") return tasks;
  if (taskFilter === "unassigned") return tasks.filter(t => !t.assigned_to);
  return tasks.filter(t => t.status === taskFilter);
}

function applySort(tasks) {
  return [...tasks].sort((a, b) => {
    let va = a[sortCol], vb = b[sortCol];
    if (sortCol === "time_left") { va = taskTimeLeft(a) ?? Infinity; vb = taskTimeLeft(b) ?? Infinity; }
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

function taskTableHtml(tasks) {
  const PRIORITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 };
  return `<div class="task-table-wrap"><table class="task-table">
    <thead><tr>
      <th class="tt-col-pri" onclick="setSort('priority')">Pri ${sortIcon('priority')}</th>
      <th class="tt-col-title" onclick="setSort('title')">Title ${sortIcon('title')}</th>
      <th class="tt-col-app" onclick="setSort('application_name')">Application ${sortIcon('application_name')}</th>
      <th class="tt-col-queue" onclick="setSort('queue_name')">Queue ${sortIcon('queue_name')}</th>
      <th class="tt-col-assignee" onclick="setSort('assigned_to')">Assignee ${sortIcon('assigned_to')}</th>
      <th class="tt-col-status" onclick="setSort('status')">Status ${sortIcon('status')}</th>
      <th class="tt-col-ttl" onclick="setSort('time_left')">Time Left ${sortIcon('time_left')}</th>
      <th class="tt-col-age" onclick="setSort('created_at')">Age ${sortIcon('created_at')}</th>
      <th class="tt-col-action"></th>
    </tr></thead>
    <tbody>
      ${tasks.map(t => {
        const left = taskTimeLeft(t);
        const leftLabel = timeLeftLabel(left);
        const pct = taskUrgencyPct(t);
        const color = pct !== null ? urgencyColor(pct) : "";
        const assignee = t.assigned_to ? t.assigned_to.split("@")[0] : "";
        return `<tr class="${!t.assigned_to ? 'tt-row-unassigned' : ''} ${left !== null && left <= 0 ? 'tt-row-expired' : ''}">
          <td><span class="tt-pri-dot priority-${t.priority}"></span></td>
          <td class="tt-title">${esc(t.title)}</td>
          <td class="tt-app">${esc(t.application_name || "")}</td>
          <td class="tt-queue">${esc(t.queue_name || "")}</td>
          <td class="tt-assignee">${assignee ? esc(assignee) : '<span class="tt-unassigned">Unassigned</span>'}</td>
          <td><span class="badge badge-${t.status}">${t.status.replace(/_/g," ")}</span></td>
          <td class="tt-ttl" ${color ? `style="color:${color}"` : ""}>${leftLabel}</td>
          <td class="tt-age">${timeAgo(t.created_at)}</td>
          <td><button class="btn btn-outline btn-sm" onclick="openTask(${t.id})">View</button></td>
        </tr>`;
      }).join("")}
    </tbody>
  </table></div>`;
}

// ── Queues ───────────────────────────────────────────────────────────────────

function renderQueues() {
  document.getElementById("queue-grid").innerHTML = allQueues.length
    ? allQueues.map(q => `
      <div class="queue-card" onclick="filterByQueue(${q.id},'${esc(q.name)}')">
        <div class="queue-card-name">${esc(q.name)}</div>
        <div class="queue-card-desc">${esc(q.description || "")}</div>
        <div class="queue-card-footer">
          <span class="queue-card-topic">${esc(q.topic || "")}</span>
          <span class="queue-card-count">${q.active_count} active</span>
        </div>
        <div class="queue-card-app">${esc(q.application || "")}</div>
      </div>
    `).join("")
    : '<div class="empty-state"><div class="empty-state-icon">◫</div><div class="empty-state-text">No queues configured</div></div>';
}

async function filterByQueue(queueId, queueName) {
  switchTab("alltasks");
  try {
    const r = await authFetch("/api/tasks?queue_id=" + queueId);
    allTasks = await r.json();
  } catch { allTasks = []; }
  document.getElementById("header-tab-title").textContent = queueName;
  document.getElementById("alltask-filters").innerHTML = `
    <button class="filter-btn active">${esc(queueName)}</button>
    <button class="filter-btn" onclick="switchTab('alltasks')">← All Tasks</button>
  `;
  document.getElementById("alltask-list").innerHTML = allTasks.length
    ? allTasks.map(t => taskCardHtml(t)).join("")
    : '<div class="empty-state"><div class="empty-state-icon">◇</div><div class="empty-state-text">No tasks in this queue</div></div>';
}

async function filterByApplication(applicationId, appName) {
  switchTab("alltasks");
  try {
    const r = await authFetch("/api/tasks?application_id=" + applicationId);
    allTasks = await r.json();
  } catch { allTasks = []; }
  document.getElementById("header-tab-title").textContent = appName;
  document.getElementById("alltask-filters").innerHTML = `
    <button class="filter-btn active">${esc(appName)} (all queues)</button>
    <button class="filter-btn" onclick="switchTab('alltasks')">← All Tasks</button>
  `;
  document.getElementById("alltask-list").innerHTML = allTasks.length
    ? allTasks.map(t => taskCardHtml(t)).join("")
    : '<div class="empty-state"><div class="empty-state-icon">◇</div><div class="empty-state-text">No tasks for this application</div></div>';
}

// ── Filter bar ──────────────────────────────────────────────────────────────

function filterBar() {
  const statuses = ["all","unassigned","pending","in_progress","completed","escalated","rejected"];
  return statuses.map(s =>
    `<button class="filter-btn ${taskFilter === s ? 'active' : ''}" onclick="setFilter('${s}')">${s === "all" ? "All" : s === "unassigned" ? "Unassigned" : s.replace(/_/g," ")}</button>`
  ).join("");
}

function setFilter(f) {
  taskFilter = f;
  render();
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
  const canAct   = isActive && (isMyTask || isAdmin || isManager);

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
      html += `<button class="btn btn-amber btn-sm" onclick="taskAction(${t.id},'escalate')">Escalate</button>`;
    }
    html += `</div>`;
  }

  return html;
}

async function taskAction(taskId, action) {
  const comment = document.getElementById("action-comment")?.value || "";
  try {
    await authFetch(`/api/tasks/${taskId}/action`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ action, actor: currentUser.email, comment: comment || null })
    });
    closeTaskModal();
    if (activeAppId) await loadTasksForApp(activeAppId);
    else await loadAll();
  } catch(e) { console.error(e); }
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

function renderAdminLanding() {
  const cards = [
    { id: "admin-iam",      icon: "⊛", title: "Users & Roles",           desc: "Create users, assign roles, manage HILs, Managers, and Admins across projects." },
    { id: "admin-projects", icon: "◈", title: "Projects & Applications", desc: "Create projects, register applications, assign Project and App Admins." },
    { id: "admin-policies", icon: "⊡", title: "Policies",               desc: "TTL defaults, PII handling, artifact retention, alert and notification rules." },
    { id: "admin-rules",    icon: "⊞", title: "Rules & Automation",     desc: "Auto-approve, auto-reject, escalation chains, round-robin assignment, SLA." },
    { id: "admin-queues",   icon: "◫", title: "Queues & Topics",        desc: "Kafka topic mappings, queue configuration, SLA targets per queue." },
    { id: "admin-audit",    icon: "▤", title: "Audit Log",              desc: "Full chain of custody — who did what, when. Export for compliance." },
  ];
  document.getElementById("admin-landing").innerHTML = `
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
  await loadQueues();
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
      showApp();
    } catch { logout(); }
  }
})();
