// ShortPipeline — painel: utilidades, sidebar e rotas (JS puro, sem build; os arquivos de web/js são carregados em ordem pelo index.html)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (name, cls = "") => `<svg class="i ${cls}"><use href="#i-${name}"/></svg>`;

const STATUS = { queued: "Na fila", running: "Rodando", waiting_approval: "Aguardando aprovação", done: "Pronto", failed: "Falhou", canceled: "Cancelado" };
const STAGE_ICON = { ideia: "bulb", roteiro: "file", critica: "check", narracao: "mic", imagens: "image", capa: "cover", legendas: "cc", som: "volume", render: "film", revisao: "eye", upload: "send",
  download: "download", transcricao: "wave", selecao: "wand", recorte: "scissors" };
const stagesOf = (job) => META.kind_stages[job.kind || "short"] || META.stages;

let META = null;
let CFG = null;
let CFG_DIRTY = false;
let timer = null;
let stopTimelineAudio = null;
let channelTab = null;

// ------------------------------------------------------------------ utilidades
async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.body && typeof opts.body !== "string" && !(opts.body instanceof FormData)) {
    init.body = JSON.stringify(opts.body);
    init.headers = { "Content-Type": "application/json" };
  }
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r;
}

function toast(msg, err = false) {
  const d = document.createElement("div");
  d.className = "toast" + (err ? " err" : "");
  d.innerHTML = `${icon(err ? "alert" : "check")}<span>${esc(msg)}</span>`;
  $("#toast").appendChild(d);
  setTimeout(() => d.remove(), err ? 7000 : 3200);
}

async function act(fn, okMsg) {
  try { await fn(); if (okMsg) toast(okMsg); } catch (e) { toast(e.message, true); }
}

const chanIds = () => Object.keys(CFG?.channels || {});
const chanName = (id) => CFG?.channels?.[id]?.name || id;
const chanIdx = (id) => Math.max(0, chanIds().indexOf(id)) % 4;
const chanChip = (id) => `<span class="chan"><span class="av c${chanIdx(id)}">${esc(chanName(id).slice(0, 1).toUpperCase())}</span>${esc(chanName(id))}</span>`;
const badge = (status) => `<span class="badge ${status}"><span class="dot"></span>${STATUS[status] || status}</span>`;
const ago = (ts) => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "agora";
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  return `há ${Math.floor(s / 86400)} d`;
};
const secs = (a, b) => {
  if (!a || !b) return "";
  const s = Math.round(b - a);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
};
const fileUrl = (job, rel) => `/api/jobs/${job.id}/file/${rel}`;
const relPath = (job, abs) => (abs ? abs.split(`/jobs/${job.id}/`)[1] : null);

function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("theme", t); } catch {}
}
$("#themeBtn").onclick = () => setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");

// ------------------------------------------------------------------ steppers
function segs(job) {
  return `<div class="segs">${stagesOf(job).map((s) => {
    const st = job.stages[s] || {};
    return `<div class="seg ${st.status === "review_pending" ? "waiting" : st.status || "pending"}" title="${esc(META.stage_labels[s])}${st.error ? ": " + esc(st.error) : ""}"></div>`;
  }).join("")}</div>`;
}

function stepper(job) {
  return `<div class="stepper">${stagesOf(job).map((s) => {
    const st = job.stages[s] || {};
    const status = st.status === "review_pending" ? "waiting" : st.status || "pending";
    const ic = status === "done" ? "check" : status === "failed" ? "x" : status === "running" ? "loader" : STAGE_ICON[s];
    const meta = status === "done" ? secs(st.started, st.ended) : status === "waiting" ? "aguardando" : (st.detail || "");
    return `<div class="st ${status}" title="${esc(st.error || "")}">
      <div class="node">${icon(ic, status === "running" ? "spin" : "")}</div>
      <div class="name">${META.stage_labels[s]}</div>
      <div class="meta ellipsis">${esc(meta)}</div></div>`;
  }).join("")}</div>`;
}

// ------------------------------------------------------------------ sidebar
function renderSidebar(data) {
  $("#navChannels").innerHTML = chanIds().map((id) => {
    const st = data?.stats?.[id] || {};
    const live = (st.running || 0) + (st.queued || 0);
    return `<a class="nav-item" href="#canais/${id}"><span class="av c${chanIdx(id)}" style="width:18px;height:18px;border-radius:5px;display:grid;place-items:center;font-size:10px;font-weight:700;color:#fff">${esc(chanName(id).slice(0, 1))}</span>
      <span class="ellipsis">${esc(chanName(id))}</span><span class="count ${live ? "live" : ""}">${live || ""}</span></a>`;
  }).join("");
  if (data) {
    const running = Object.values(data.stats).reduce((a, s) => a + (s.running || 0) + (s.queued || 0), 0);
    $("#navCount").textContent = running || "";
    $("#navCount").classList.toggle("live", running > 0);
  }
}

function renderWorker() {
  const paused = META.paused;
  $("#worker").innerHTML = `<div class="row"><span class="status-dot ${paused ? "paused" : "on"}"></span>
      <div class="grow"><div style="font-weight:550;font-size:13px">${paused ? "Fila pausada" : "Fila ativa"}</div>
      <div class="tiny faint">${paused ? "nenhum short novo inicia" : "processando automaticamente"}</div></div>
      <button class="btn icon sm" id="wbtn" title="${paused ? "Retomar" : "Pausar"}">${icon(paused ? "play" : "pause", "sm")}</button></div>`;
  $("#wbtn").onclick = () => act(async () => {
    const r = await api(`/api/worker/${paused ? "resume" : "pause"}`, { method: "POST" });
    META.paused = r.paused;
    renderWorker();
  });
}

// ------------------------------------------------------------------ roteamento
function route() {
  clearInterval(timer);
  stopTimelineAudio?.();
  const [page, arg] = (location.hash.slice(1) || "painel").split("/");
  const active = page === "job" ? "painel" : page;
  $$(".sidebar .nav-item").forEach((a) => {
    const href = a.getAttribute("href").slice(1);
    a.classList.toggle("active", href === active || (page === "canais" && href === `canais/${arg || channelTab}`));
  });
  $$("[data-nav=canais]").forEach((a) => a.classList.toggle("active", page === "canais"));
  window.scrollTo(0, 0);
  if (page === "job") return pageJob(arg);
  if (page === "canais") return pageChannels(arg);
  if (page === "analytics") return pageAnalytics(arg);
  if (page === "provedores") return pageProviders();
  return pageDashboard();
}

let lastHash = location.hash;
window.addEventListener("hashchange", () => {
  if (CFG_DIRTY && !confirm("Há alterações não salvas. Sair mesmo assim?")) {
    history.replaceState(null, "", lastHash);
    return;
  }
  CFG_DIRTY = false;
  lastHash = location.hash;
  route();
});
