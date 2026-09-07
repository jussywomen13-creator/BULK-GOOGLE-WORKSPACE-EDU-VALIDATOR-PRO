/* Bulk Email Validator Pro — client. All stats come from backend JSON. */

const API = {
  async json(url, options = {}) {
    if (options.body && typeof options.body !== "string") {
      options.body = JSON.stringify(options.body);
      options.headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    }
    const res = await fetch(url, options);
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { error: text }; }
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  },
  get(url) { return this.json(url); },
  post(url, body) { return this.json(url, { method: "POST", body }); },
};

const state = {
  view: "dashboard",
  jobs: [],
  activeJobId: null,
  resultsPage: 1,
  selectedResults: new Set(),
  refreshTimer: null,
};

const STATUS_COLORS = {
  DELIVERABILITY_LIKELY: "badge-DELIVERABILITY_LIKELY",
  INVALID: "badge-INVALID",
  RISKY: "badge-RISKY",
  CATCH_ALL: "badge-CATCH_ALL",
  DISPOSABLE: "badge-DISPOSABLE",
  ROLE: "badge-ROLE",
  DUPLICATE: "badge-DUPLICATE",
  UNKNOWN: "badge-UNKNOWN",
  ERROR: "badge-ERROR",
  PENDING: "badge-PENDING",
};
const JOB_STATUS_LABELS = {
  pending: "Pending", queued: "Queued", running: "Running",
  paused: "Paused", stopped: "Stopped", completed: "Completed",
};

function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(t._timer); t._timer = setTimeout(() => t.classList.remove("show"), 2400);
}
function fmtNumber(n) { return (n === null || n === undefined) ? "—" : Number(n).toLocaleString(); }
function fmtEta(sec) { if (sec === null || sec === undefined || sec < 0) return "—"; if (sec === 0) return "Done"; if (sec < 60) return sec + "s"; const m = Math.floor(sec / 60); const s = sec % 60; return `${m}m ${s}s`; }
function fmtDate(iso) { return iso ? new Date(iso + "Z").toLocaleString() : "—"; }
function statusBadge(status) { return `<span class="badge ${STATUS_COLORS[status] || "badge-PENDING"}">${status.replace(/_/g, " ")}</span>`; }
function jobStatusBadge(status) { return `<span class="badge badge-${status.toUpperCase()}">${JOB_STATUS_LABELS[status] || status}</span>`; }

async function init() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
  document.getElementById("menu-btn").addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));
  document.querySelectorAll("[data-go-new]").forEach((b) => b.addEventListener("click", () => switchView("new")));
  document.querySelectorAll("[data-go-jobs]").forEach((b) => b.addEventListener("click", () => switchView("jobs")));

  document.getElementById("refresh-jobs").addEventListener("click", refreshJobs);
  document.getElementById("refresh-history").addEventListener("click", refreshHistory);
  document.getElementById("refresh-results").addEventListener("click", refreshResults);
  document.getElementById("refresh-export").addEventListener("click", refreshExport);
  document.getElementById("result-search").addEventListener("input", debounce(() => { state.resultsPage = 1; refreshResults(); }, 300));
  document.getElementById("result-status").addEventListener("change", () => { state.resultsPage = 1; refreshResults(); });
  document.getElementById("result-domain").addEventListener("input", debounce(() => { state.resultsPage = 1; refreshResults(); }, 300));
  document.getElementById("result-page-size").addEventListener("change", () => { state.resultsPage = 1; refreshResults(); });
  document.getElementById("result-job-select").addEventListener("change", () => { state.activeJobId = Number(document.getElementById("result-job-select").value); state.resultsPage = 1; refreshResults(); });
  document.getElementById("export-job-select").addEventListener("change", refreshExport);

  document.getElementById("new-job-form").addEventListener("submit", createJob);

  // Drag and drop upload.
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const dropFileLabel = document.getElementById("dropzone-file");
  const pickBtn = document.getElementById("dropzone-pick");
  pickBtn.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => { if (fileInput.files[0]) dropFileLabel.textContent = fileInput.files[0].name; else dropFileLabel.textContent = "No file selected"; });
  ["dragenter", "dragover"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); }));
  dropzone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (!files || !files.length) return;
    const dt = new DataTransfer();
    dt.items.add(files[0]);
    fileInput.files = dt.files;
    dropFileLabel.textContent = files[0].name;
  });
  document.getElementById("copy-selected").addEventListener("click", copySelected);
  document.getElementById("export-selected").addEventListener("click", exportSelected);
  document.getElementById("select-all").addEventListener("change", (e) => {
    document.querySelectorAll(".result-check").forEach((c) => c.checked = e.target.checked);
  });
  document.getElementById("run-ai").addEventListener("click", runAi);
  document.getElementById("ai-job-select").addEventListener("change", () => {});

  await loadServerStatus();
  await refreshDashboard();
  await refreshJobs();
  await refreshHistory();
  await refreshResults();
  await refreshExport();
  await refreshDropdowns();
  await refreshSettings();
}

function debounce(fn, ms) { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; }

function switchView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  const titles = {
    dashboard: "Dashboard", new: "New Validation Job", jobs: "Active Jobs",
    history: "Job History", results: "Results", export: "Export",
    settings: "Settings", ai: "AI Analysis",
  };
  document.getElementById("view-title").textContent = titles[view] || "Dashboard";
  document.getElementById("sidebar").classList.remove("open");
  if (view === "dashboard") refreshDashboard();
  if (view === "jobs") refreshJobs();
  if (view === "history") refreshHistory();
  if (view === "results") refreshResults();
  if (view === "export") refreshExport();
}

async function loadServerStatus() {
  try {
    const h = await API.get("/health");
    document.getElementById("server-state").textContent = h.status === "ok" ? "OK" : "DOWN";
    document.getElementById("ai-state").textContent = h.deepseek_ai ? "ON" : "OFF";
  } catch (e) {
    document.getElementById("server-state").textContent = "OFFLINE";
  }
}

async function refreshDashboard() {
  const jobs = await API.get("/api/jobs");
  const active = jobs.jobs.filter((j) => ["running", "pending", "queued", "paused"].includes(j.status));
  const job = active[0] || jobs.jobs[0];
  state.jobs = jobs.jobs;
  if (job) state.activeJobId = job.id;

  const pick = (j, key) => j ? fmtNumber(j[key]) : "—";
  document.getElementById("dm-submitted").textContent = pick(job, "submitted_count");
  document.getElementById("dm-unique").textContent = pick(job, "unique_count");
  document.getElementById("dm-processed").textContent = pick(job, "processed_count");
  document.getElementById("dm-remaining").textContent = pick(job, "remaining_count");
  document.getElementById("dm-likely").textContent = pick(job, "valid_count");
  document.getElementById("dm-invalid").textContent = pick(job, "invalid_count");
  document.getElementById("dm-risky").textContent = pick(job, "risky_count");
  document.getElementById("dm-catch").textContent = pick(job, "catch_all_count");
  document.getElementById("dm-disposable").textContent = pick(job, "disposable_count");
  document.getElementById("dm-role").textContent = pick(job, "role_count");
  document.getElementById("dm-unknown").textContent = pick(job, "unknown_count");
  document.getElementById("dm-errors").textContent = pick(job, "error_count");

  const progress = job ? (job.progress || 0) : 0;
  document.getElementById("live-progress").textContent = progress + "%";
  document.getElementById("live-progress-bar").style.width = progress + "%";
  document.getElementById("live-speed").textContent = job ? `${job.speed || 0}/s` : "0/s";
  document.getElementById("live-eta").textContent = fmtEta(job ? job.eta_seconds : null);
  document.getElementById("live-status").innerHTML = job ? jobStatusBadge(job.status) : "—";
  document.getElementById("live-start").textContent = fmtDate(job && job.start_time);
  document.getElementById("live-end").textContent = fmtDate(job && job.completed_time);

  // recent jobs
  const table = document.getElementById("recent-jobs");
  if (!jobs.jobs.length) { table.innerHTML = `<div class="empty">No jobs yet.</div>`; return; }
  table.innerHTML = jobTable(jobs.jobs.slice(0, 6));
}

function jobTable(rows) {
  return `<table><thead><tr><th>#</th><th>Name</th><th>Status</th><th>Unique</th><th>Processed</th><th>Remaining</th><th>Created</th></tr></thead><tbody>${
    rows.map((j) => `<tr>
      <td>${j.id}</td>
      <td>${escapeHtml(j.name)}</td>
      <td>${jobStatusBadge(j.status)}</td>
      <td>${fmtNumber(j.unique_count)}</td>
      <td>${fmtNumber(j.processed_count)}</td>
      <td>${fmtNumber(j.remaining_count)}</td>
      <td>${fmtDate(j.created_at)}</td>
    </tr>`).join("")
  }</tbody></table>`;
}

async function refreshJobs() {
  const jobs = await API.get("/api/jobs");
  const active = jobs.jobs.filter((j) => ["running", "pending", "queued", "paused"].includes(j.status));
  const table = document.getElementById("jobs-table");
  if (!active.length) { table.innerHTML = `<div class="empty">No active jobs. Start one from New Validation Job.</div>`; return; }
  table.innerHTML = `<table><thead><tr><th>#</th><th>Name</th><th>Status</th><th>Progress</th><th>Unique</th><th>Processed</th><th>Remaining</th><th>Actions</th></tr></thead><tbody>${
    active.map((j) => `<tr>
      <td>${j.id}</td><td>${escapeHtml(j.name)}</td><td>${jobStatusBadge(j.status)}</td>
      <td>${j.progress}%</td><td>${fmtNumber(j.unique_count)}</td><td>${fmtNumber(j.processed_count)}</td><td>${fmtNumber(j.remaining_count)}</td>
      <td>${jobActions(j)}</td>
    </tr>`).join("")
  }</tbody></table>`;
}

function jobActions(j) {
  const buttons = [];
  if (j.status === "running" || j.status === "pending" || j.status === "queued") buttons.push(`<button class="btn" data-act="pause" data-id="${j.id}">Pause</button>`);
  if (j.status === "running") buttons.push(`<button class="btn btn-danger" data-act="stop" data-id="${j.id}">Stop</button>`);
  if (j.status === "paused") buttons.push(`<button class="btn" data-act="resume" data-id="${j.id}">Resume</button>`);
  if (j.status === "pending") buttons.push(`<button class="btn" data-act="start" data-id="${j.id}">Start</button>`);
  if (j.status === "completed" || j.status === "stopped") buttons.push(`<button class="btn" data-act="results" data-id="${j.id}">Results</button>`);
  return buttons.join(" ");
}

async function refreshHistory() {
  const jobs = await API.get("/api/jobs");
  const done = jobs.jobs.filter((j) => ["completed", "stopped"].includes(j.status));
  const table = document.getElementById("history-table");
  if (!done.length) { table.innerHTML = `<div class="empty">No completed jobs yet.</div>`; return; }
  table.innerHTML = `<table><thead><tr><th>#</th><th>Name</th><th>Status</th><th>Unique</th><th>Processed</th><th>Likely</th><th>Invalid</th><th>Risky</th><th>Unknown</th><th>Completed</th></tr></thead><tbody>${
    done.map((j) => `<tr>
      <td>${j.id}</td><td>${escapeHtml(j.name)}</td><td>${jobStatusBadge(j.status)}</td>
      <td>${fmtNumber(j.unique_count)}</td><td>${fmtNumber(j.processed_count)}</td><td>${fmtNumber(j.valid_count)}</td><td>${fmtNumber(j.invalid_count)}</td><td>${fmtNumber(j.risky_count)}</td><td>${fmtNumber(j.unknown_count)}</td><td>${fmtDate(j.completed_time)}</td>
    </tr>`).join("")
  }</tbody></table>`;
}

async function refreshDropdowns() {
  const jobs = await API.get("/api/jobs");
  state.jobs = jobs.jobs;
  for (const id of ["result-job-select", "export-job-select", "ai-job-select"]) {
    const sel = document.getElementById(id);
    const current = Number(sel.value) || 0;
    sel.innerHTML = `<option value="">Select a job…</option>` + jobs.jobs.map((j) => `<option value="${j.id}" ${j.id === (current || jobs.jobs[0]?.id) ? "selected" : ""}>#${j.id} ${escapeHtml(j.name)} (${j.status})</option>`).join("");
  }
  if (state.activeJobId) {
    document.getElementById("result-job-select").value = state.activeJobId;
    document.getElementById("export-job-select").value = state.activeJobId;
    document.getElementById("ai-job-select").value = state.activeJobId;
  }
}

async function createJob(ev) {
  ev.preventDefault();
  const form = ev.target;
  const btn = document.getElementById("submit-new");
  const status = document.getElementById("new-job-status");
  const fd = new FormData(form);
  const text = (fd.get("text") || "").toString().trim();
  const file = fd.get("file");
  const hasFile = file && file.name;
  if (!text && !hasFile) { toast("Paste emails or upload a file."); return; }
  btn.disabled = true; status.textContent = "Creating job…";
  try {
    let job;
    if (hasFile) {
      job = await API.json("/api/jobs", { method: "POST", body: fd });
    } else {
      const payload = { name: fd.get("name"), text, concurrency: fd.get("concurrency"), batch_size: fd.get("batch_size"), dns_timeout: fd.get("dns_timeout") };
      job = await API.post("/api/jobs", payload);
    }
    status.textContent = `Job #${job.id} created (${job.unique_count} unique).`;
    toast(`Job #${job.id} started.`);
    document.getElementById("file-input").value = "";
    form.reset(); form.elements.name.value = "Validation Job";
    await refreshDashboard(); await refreshJobs(); await refreshDropdowns();
  } catch (e) {
    status.textContent = e.message; toast(e.message);
  } finally { btn.disabled = false; }
}

async function act(id, act) {
  try {
    const job = await API.post(`/api/jobs/${id}/${act}`);
    toast(`Job #${id} ${act}d.`);
    await refreshJobs(); await refreshDashboard(); await refreshHistory();
  } catch (e) { toast(e.message); }
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const id = Number(b.dataset.id);
  if (b.dataset.act === "results") { state.activeJobId = id; switchView("results"); return; }
  await act(id, b.dataset.act);
});

async function refreshResults() {
  const sel = document.getElementById("result-job-select");
  const jobId = sel.value ? Number(sel.value) : state.activeJobId;
  if (!jobId) { document.getElementById("results-table").innerHTML = `<div class="empty">Select a job to view results.</div>`; return; }
  state.activeJobId = jobId;
  const search = document.getElementById("result-search").value;
  const status = document.getElementById("result-status").value;
  const domain = document.getElementById("result-domain").value;
  const per_page = document.getElementById("result-page-size").value || "50";
  const q = new URLSearchParams({ page: state.resultsPage, per_page, search, status, domain });
  try {
    const data = await API.get(`/api/jobs/${jobId}/results?${q.toString()}`);
    renderResults(data);
  } catch (e) { toast(e.message); }
}

function renderResults(data) {
  const table = document.getElementById("results-table");
  if (!data.items.length) { table.innerHTML = `<div class="empty">No results for this filter.</div>`; return; }
  table.innerHTML = `<table><thead><tr><th></th><th>Email</th><th>Status</th><th>Reason</th><th>Domain</th><th>MX</th><th>Risks</th><th>Checked</th><th>Source</th></tr></thead><tbody>${
    data.items.map((r) => `<tr>
      <td><input type="checkbox" class="result-check" value="${r.id}" data-email="${escapeAttr(r.email)}" ${state.selectedResults.has(r.id) ? "checked" : ""} /></td>
      <td><button class="btn copy-email" data-email="${escapeAttr(r.email)}">${escapeHtml(r.email)}</button></td>
      <td>${statusBadge(r.status)}</td>
      <td>${escapeHtml(r.reason || "")}</td>
      <td>${escapeHtml(r.domain || "")}</td>
      <td>${(r.mx_records || []).length}</td>
      <td>${(r.risk_signals || []).map((s) => escapeHtml(s.label)).join(", ") || "—"}</td>
      <td>${fmtDate(r.checked_at)}</td>
      <td>${escapeHtml(r.source || "")}</td>
    </tr>`).join("")
  }</tbody></table>`;
  const pag = document.getElementById("results-pagination");
  const pages = data.pages || 0;
  pag.innerHTML = "";
  for (let i = 1; i <= pages; i++) {
    const b = el(`<button class="${i === data.page ? "active" : ""}">${i}</button>`);
    b.addEventListener("click", () => { state.resultsPage = i; refreshResults(); });
    pag.appendChild(b);
  }
  const jobs = state.jobs;
  if (!document.getElementById("result-status").options.length) {
    const s = document.getElementById("result-status");
    const statuses = ["", "DELIVERABILITY_LIKELY", "INVALID", "RISKY", "CATCH_ALL", "DISPOSABLE", "ROLE", "DUPLICATE", "UNKNOWN", "ERROR"];
    s.innerHTML = statuses.map((v) => `<option value="${v}">${v ? v.replace(/_/g, " ") : "Status"}</option>`).join("");
  }
}

async function copySelected() {
  const selected = Array.from(document.querySelectorAll(".result-check:checked")).map((c) => c.dataset.email);
  if (!selected.length) { toast("Select at least one row."); return; }
  try {
    await navigator.clipboard.writeText(selected.join("\n"));
    toast(`Copied ${selected.length} emails.`);
  } catch (e) {
    const ta = el("<textarea></textarea>");
    ta.value = selected.join("\n"); document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
    toast(`Copied ${selected.length} emails.`);
  }
}

async function exportSelected() {
  const ids = Array.from(document.querySelectorAll(".result-check:checked")).map((c) => Number(c.value));
  if (!ids.length) { toast("Select at least one row."); return; }
  const exportType = window.prompt("Export type", "FULL_REPORT");
  if (!exportType) return;
  const jobId = state.activeJobId;
  if (!jobId) return;
  try {
    const res = await fetch(`/api/jobs/${jobId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, export_type: exportType }),
    });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^";]+)"?/i);
    const name = m ? m[1] : `${exportType}.csv`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
    toast("Selected exported.");
  } catch (e) { toast(e.message); }
}

async function refreshExport() {
  const sel = document.getElementById("export-job-select");
  const jobId = sel.value ? Number(sel.value) : state.activeJobId;
  if (!jobId) { document.getElementById("export-grid").innerHTML = `<div class="empty">Select a job to export.</div>`; return; }
  const types = [
    ["FULL_REPORT", "full report"], ["VALID", "valid (likely deliverable)"], ["INVALID", "invalid"],
    ["RISKY", "risky"], ["CATCH_ALL", "catch-all"], ["DISPOSABLE", "disposable"], ["ROLE", "role"],
    ["UNKNOWN", "unknown"], ["DUPLICATE", "duplicates"], ["VALID_EMAILS", "valid .txt"],
  ];
  document.getElementById("export-grid").innerHTML = types.map(([t, label]) => `<div class="export-card"><strong>${t}</strong><span class="muted">${label}</span><button class="btn" data-export="${t}">Download</button></div>`).join("");
  document.querySelectorAll("[data-export]").forEach((b) => b.addEventListener("click", async () => {
    const job = state.activeJobId;
    if (!job) return;
    window.location.href = `/api/jobs/${job}/export/${b.dataset.export}`;
  }));
}

async function refreshSettings() {
  try {
    const h = await API.get("/health");
    document.getElementById("setting-ai").textContent = h.deepseek_ai ? "Enabled (DEEPSEEK_API_KEY set)" : "Disabled — core validation works without AI";
    const s = await API.get("/api/stats");
    document.getElementById("setting-db").textContent = s.total_jobs ? h.database : "SQLite (local)";
  } catch (e) {}
}

async function runAi() {
  const jobId = Number(document.getElementById("ai-job-select").value);
  if (!jobId) { toast("Select a job."); return; }
  const out = document.getElementById("ai-output");
  out.textContent = "Analyzing…";
  try {
    const result = await API.post("/api/analyze", { job_id: jobId });
    if (result.report) {
      out.textContent = JSON.stringify(result.report, null, 2);
    } else if (result.content) {
      out.textContent = result.content;
    } else {
      out.textContent = JSON.stringify(result, null, 2);
    }
  } catch (e) { out.textContent = "Error: " + e.message; }
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest(".copy-email");
  if (!b) return;
  try { await navigator.clipboard.writeText(b.dataset.email); toast("Email copied."); } catch (err) { toast("Copy failed."); }
});

function escapeHtml(s) { return String(s ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m])); }
function escapeAttr(s) { return escapeHtml(s); }

// Auto refresh dashboard/jobs while running.
setInterval(async () => {
  try {
    if (state.view === "dashboard") await refreshDashboard();
    if (state.view === "jobs") await refreshJobs();
    if (state.view === "history") await refreshHistory();
  } catch (e) {}
}, 2500);

document.addEventListener("DOMContentLoaded", init);
