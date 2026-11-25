const TARGET_LANGUAGES = [
  ["zh-CN", "Chinese (Simplified)"],
  ["ja", "Japanese"],
  ["es", "Spanish"],
  ["de", "German"],
];

const STATUS_COPY = {
  queued: "Preparing run",
  running: "Agent working",
  awaiting_approval: "Human review",
  rendering: "Rendering outputs",
  completed: "Run completed",
  failed: "Run stopped",
};

const ICONS = {
  play: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M7 4.8v10.4L15 10 7 4.8Z" fill="currentColor"/></svg>',
  arrow: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 10h11M11 5.5 15.5 10 11 14.5" stroke="currentColor" stroke-width="1.7"/></svg>',
  check: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m4.5 10.5 3.2 3.2 7.8-8" stroke="currentColor" stroke-width="1.8"/></svg>',
  clock: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.4"/><path d="M10 6.8v3.6l2.3 1.4" stroke="currentColor" stroke-width="1.4"/></svg>',
  download: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 3.5v8M6.8 8.8 10 12l3.2-3.2M4 14.5v1.2h12v-1.2" stroke="currentColor" stroke-width="1.5"/></svg>',
  film: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="3" y="4.5" width="14" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3"/><path d="M6 4.5v11M14 4.5v11M3 9h3M14 9h3M3 12h3M14 12h3" stroke="currentColor" stroke-width="1.1"/></svg>',
};

const state = {
  config: null,
  job: null,
  recent: [],
  targetLanguage: "zh-CN",
  busy: false,
  error: "",
  videoFile: null,
  subtitleFile: null,
  pollingTimer: null,
};

const root = document.querySelector("#app");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortId(value) {
  return value.slice(0, 6).toUpperCase();
}

function formatDuration(ms) {
  if (!ms) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function artifactUrl(jobId, path) {
  if (!path) return null;
  const filename = path.split(/[\\/]/).pop();
  return filename ? `/api/jobs/${jobId}/artifacts/${encodeURIComponent(filename)}` : null;
}

async function readJson(response) {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.detail || `Request failed with ${response.status}`);
  }
  return payload;
}

const api = {
  config: () => fetch("/api/config").then(readJson),
  recent: () => fetch("/api/jobs?limit=6").then(readJson),
  job: (id) => fetch(`/api/jobs/${id}`).then(readJson),
  demo: (targetLanguage) =>
    fetch("/api/jobs/demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_language: targetLanguage }),
    }).then(readJson),
  upload: (video, subtitle, sourceLanguage, targetLanguage, mode) => {
    const body = new FormData();
    body.append("video", video);
    if (subtitle) body.append("subtitle", subtitle);
    body.append("source_language", sourceLanguage);
    body.append("target_language", targetLanguage);
    body.append("mode", mode);
    return fetch("/api/jobs", { method: "POST", body }).then(readJson);
  },
  approve: (id) => fetch(`/api/jobs/${id}/approve`, { method: "POST" }).then(readJson),
};

function stepMarkup(step) {
  const icon =
    step.status === "waiting"
      ? ICONS.clock
      : step.status === "failed"
        ? '<span class="step-failed">!</span>'
        : ICONS.check;
  return `
    <div class="step-row is-${escapeHtml(step.status)}">
      <div class="step-marker">${icon}</div>
      <div class="step-copy">
        <div class="step-number">${String(step.sequence).padStart(2, "0")}</div>
        <div class="step-title">${escapeHtml(step.label)}</div>
        <p>${escapeHtml(step.detail)}</p>
      </div>
      ${step.duration_ms > 0 ? `<time>${formatDuration(step.duration_ms)}</time>` : ""}
    </div>`;
}

function setupMarkup() {
  const targetOptions = TARGET_LANGUAGES.map(
    ([value, label]) =>
      `<option value="${value}" ${value === state.targetLanguage ? "selected" : ""}>${label}</option>`,
  ).join("");
  return `
    <section class="setup-panel">
      <div class="panel-heading">
        <div><span class="section-index">01</span><h2>Run setup</h2></div>
        <span class="mode-label">${state.config?.live_model_configured ? "MODEL READY" : "DEMO MODE"}</span>
      </div>
      <div class="intro-copy">
        <span>LOCALIZATION DESK</span>
        <h1>Make every frame<br />speak again.</h1>
        <p>A compact agent for timed translation. It plans, checks subtitle constraints, retries weak steps, then waits for human approval.</p>
      </div>
      <button class="demo-action" id="run-demo" ${state.busy ? "disabled" : ""}>
        <span>${ICONS.play}Run sample</span>
        <small>NO API KEY REQUIRED</small>
      </button>
      <div class="language-row">
        <label><span>SOURCE</span><select id="source-language" aria-label="Source language"><option value="en">English</option><option value="zh-CN">Chinese (Simplified)</option><option value="ja">Japanese</option></select></label>
        <span class="language-arrow">→</span>
        <label><span>TARGET</span><select id="target-language" aria-label="Target language">${targetOptions}</select></label>
      </div>
      <form class="upload-form" id="upload-form">
        <label class="file-field"><span>SOURCE VIDEO</span><strong id="video-name">${escapeHtml(state.videoFile?.name || "Choose a video file")}</strong><input id="video-file" type="file" accept="video/*" /></label>
        <label class="file-field compact"><span>OPTIONAL SRT</span><strong id="subtitle-name">${escapeHtml(state.subtitleFile?.name || "Use ASR when available")}</strong><input id="subtitle-file" type="file" accept=".srt,text/plain" /></label>
        <button class="upload-action" id="upload-submit" type="submit" ${!state.videoFile || state.busy ? "disabled" : ""}>Upload & localize ${ICONS.arrow}</button>
      </form>
      <div class="setup-foot"><span>FFmpeg ${state.config?.ffmpeg_available ? "ready" : "pending"}</span><span>Max ${state.config?.max_upload_mb || 80} MB</span><span>${state.config?.max_agent_steps || 8} step guard</span></div>
    </section>`;
}

function activeRunMarkup() {
  const job = state.job;
  const subtitle =
    ["awaiting_approval", "rendering", "completed"].includes(job?.status)
      ? "本地化需要同时保留时间轴、语气与语境。"
      : "A verifier stays in the loop.";
  const outputVideo = job ? artifactUrl(job.id, job.output_video_path) : null;
  const outputSrt = job ? artifactUrl(job.id, job.output_srt_path) : null;
  const trace = job ? artifactUrl(job.id, "agent_trace.json") : null;
  const canApprove = job?.status === "awaiting_approval" && !state.busy;
  return `
    <section class="run-panel">
      <div class="panel-heading light">
        <div><span class="section-index">02</span><h2>Active run</h2></div>
        ${job ? `<span class="status-chip status-${job.status}">${STATUS_COPY[job.status]}</span>` : ""}
      </div>
      <div class="video-stage">
        <div class="film-grain"></div><div class="frame-lines"></div>
        <div class="stage-copy"><span>${escapeHtml(job?.source_name || "Demo / verifier in the loop")}</span><strong>${escapeHtml(subtitle)}</strong></div>
        <button class="play-control" aria-label="Preview source video" type="button">${ICONS.play}</button>
        <div class="timecode"><span>00:00:04:12</span><span>${escapeHtml(job?.target_language || "ZH-CN")}</span></div>
      </div>
      <div class="run-progress">
        <div class="progress-label"><span>${job ? STATUS_COPY[job.status] : "Ready to localize"}</span><strong>${Math.round((job?.progress || 0) * 100)}%</strong></div>
        <div class="progress-track"><div style="width:${(job?.progress || 0) * 100}%"></div></div>
      </div>
      <div class="review-strip">
        <div><span class="review-label">TRANSLATED CUE</span><p>${escapeHtml(subtitle)}</p></div>
        <div class="review-meta"><span>24 character guard</span><span>${job?.metrics?.segments ? `${job.metrics.segments} segments` : "7.0 sec"}</span></div>
      </div>
      ${job?.error ? `<div class="error-banner">${escapeHtml(job.error)}</div>` : ""}
      <div class="run-actions">
        <button class="primary-action" id="approve-job" ${canApprove ? "" : "disabled"}>${job?.status === "completed" ? "Approved" : "Approve translation"}${ICONS.arrow}</button>
        <div class="artifact-links">
          ${outputSrt ? `<a href="${outputSrt}" download>${ICONS.download} SRT</a>` : ""}
          ${outputVideo ? `<a href="${outputVideo}" download>${ICONS.film} Video</a>` : ""}
          ${trace ? `<a href="${trace}" download>${ICONS.download} Trace</a>` : ""}
        </div>
      </div>
    </section>`;
}

function ledgerMarkup() {
  const job = state.job;
  const steps = job?.steps?.length
    ? job.steps.map(stepMarkup).join("")
    : `<div class="step-row is-queued"><div class="step-marker">${ICONS.clock}</div><div><div class="step-title">Plan the localization run</div><p>Waiting for the first tool call.</p></div></div>`;
  return `
    <aside class="ledger-panel">
      <div class="panel-heading">
        <div><span class="section-index">03</span><h2>Run ledger</h2></div>
        <span class="trace-state">LIVE TRACE</span>
      </div>
      ${job ? `
        <div class="ledger-summary">
          <div><span>RUN</span><strong>${shortId(job.id)}</strong></div>
          <div><span>RETRIES</span><strong>${job.retry_count}</strong></div>
          <div><span>STEPS</span><strong>${job.steps.length}</strong></div>
        </div>` : `<div class="ledger-empty"><div class="ledger-rule"></div><p>The agent will expose each tool call, retry, and checkpoint here.</p></div>`}
      <div class="step-list">${steps}</div>
    </aside>`;
}

function recentMarkup() {
  if (!state.recent.length) return "";
  return `<div class="recent-runs"><span>RECENT</span>${state.recent
    .slice(0, 4)
    .map(
      (entry) => `<button class="recent-job" data-job-id="${entry.id}"><strong>${shortId(entry.id)}</strong><span>${escapeHtml(entry.source_name)}</span><i class="dot dot-${entry.status}"></i></button>`,
    )
    .join("")}</div>`;
}

function render() {
  const issueCount =
    typeof state.job?.metrics?.issues === "number" ? state.job.metrics.issues : 0;
  root.innerHTML = `
    <main class="app-shell">
      <header class="topbar">
        <a class="wordmark" href="/" aria-label="Lang Loop home"><span>LANG</span><i>/</i><span>LOOP</span></a>
        <div class="topbar-center"><span class="status-light"></span>Local agent workspace</div>
        <div class="topbar-meta"><span>${state.config?.asr_configured ? "ASR + LLM" : "OFFLINE DEMO"}</span><span>v0.1</span></div>
      </header>
      ${state.error ? `<div class="global-error"><span>${escapeHtml(state.error)}</span><button id="dismiss-error">Dismiss</button></div>` : ""}
      <div class="workspace-grid">${setupMarkup()}${activeRunMarkup()}${ledgerMarkup()}</div>
      <footer class="bottom-strip">
        <div class="metric"><span>SEGMENTS</span><strong>${state.job?.metrics?.segments || "—"}</strong></div>
        <div class="metric"><span>VALIDATION NOTES</span><strong>${issueCount || "—"}</strong></div>
        <div class="metric"><span>RETRY BUDGET</span><strong>${state.job?.retry_count ?? 0} / 2</strong></div>
        ${recentMarkup()}
      </footer>
    </main>`;
  bindEvents();
}

function setBusy(value) {
  state.busy = value;
  render();
}

function showError(reason) {
  state.error = reason instanceof Error ? reason.message : String(reason);
  state.busy = false;
  render();
}

function startPolling(jobId) {
  if (state.pollingTimer) clearInterval(state.pollingTimer);
  state.pollingTimer = setInterval(async () => {
    try {
      const job = await api.job(jobId);
      state.job = job;
      if (["awaiting_approval", "completed", "failed"].includes(job.status)) {
        state.busy = false;
        clearInterval(state.pollingTimer);
        state.pollingTimer = null;
        api.recent().then((recent) => {
          state.recent = recent;
          render();
        });
      }
      render();
    } catch (reason) {
      clearInterval(state.pollingTimer);
      state.pollingTimer = null;
      showError(reason);
    }
  }, 650);
}

async function runJobCreator(creator) {
  setBusy(true);
  try {
    state.job = await creator();
    if (["awaiting_approval", "completed", "failed"].includes(state.job.status)) {
      state.busy = false;
    } else {
      startPolling(state.job.id);
    }
    render();
  } catch (reason) {
    showError(reason);
  }
}

function bindEvents() {
  document.querySelector("#run-demo")?.addEventListener("click", () =>
    runJobCreator(() => api.demo(state.targetLanguage)),
  );
  document.querySelector("#target-language")?.addEventListener("change", (event) => {
    state.targetLanguage = event.target.value;
  });
  document.querySelector("#video-file")?.addEventListener("change", (event) => {
    state.videoFile = event.target.files?.[0] || null;
    document.querySelector("#video-name").textContent =
      state.videoFile?.name || "Choose a video file";
    document.querySelector("#upload-submit").disabled = !state.videoFile || state.busy;
  });
  document.querySelector("#subtitle-file")?.addEventListener("change", (event) => {
    state.subtitleFile = event.target.files?.[0] || null;
    document.querySelector("#subtitle-name").textContent =
      state.subtitleFile?.name || "Use ASR when available";
  });
  document.querySelector("#upload-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const sourceLanguage = document.querySelector("#source-language")?.value || "en";
    const mode = state.config?.live_model_configured ? "live" : "demo";
    if (!state.videoFile) return;
    runJobCreator(() =>
      api.upload(
        state.videoFile,
        state.subtitleFile,
        sourceLanguage,
        state.targetLanguage,
        mode,
      ),
    );
  });
  document.querySelector("#approve-job")?.addEventListener("click", () =>
    runJobCreator(() => api.approve(state.job.id)),
  );
  document.querySelector("#dismiss-error")?.addEventListener("click", () => {
    state.error = "";
    render();
  });
  document.querySelectorAll(".recent-job").forEach((button) => {
    button.addEventListener("click", () =>
      runJobCreator(() => api.job(button.dataset.jobId)),
    );
  });
}

async function initialize() {
  render();
  try {
    [state.config, state.recent] = await Promise.all([api.config(), api.recent()]);
  } catch (reason) {
    state.error = reason instanceof Error ? reason.message : String(reason);
  }
  render();
}

initialize();
