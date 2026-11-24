// ShortPipeline — painel (JS puro, sem build)
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
let channelTab = null;

// ------------------------------------------------------------------ utilidades
async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.body && typeof opts.body !== "string") {
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
    return `<div class="seg ${st.status || "pending"}" title="${esc(META.stage_labels[s])}${st.error ? ": " + esc(st.error) : ""}"></div>`;
  }).join("")}</div>`;
}

function stepper(job) {
  return `<div class="stepper">${stagesOf(job).map((s) => {
    const st = job.stages[s] || {};
    const status = st.status || "pending";
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

// ------------------------------------------------------------------ criar
let newKind = "short";
function openNewDialog(channel, kind) {
  $("#nChan").innerHTML = chanIds().map((id) => `<option value="${id}">${esc(chanName(id))}</option>`).join("");
  if (channel && CFG.channels[channel]) $("#nChan").value = channel;
  setNewKind(kind || newKind);
  $("#nFileInfo").textContent = "";
  $("#nProgress").hidden = true;
  $("#newDialog").showModal();
}
function setNewKind(k) {
  newKind = k;
  $$("#nKind button").forEach((b) => b.classList.toggle("active", b.dataset.k === k));
  $$("#newDialog [data-for]").forEach((el) => { el.hidden = !el.dataset.for.split(" ").includes(k); });
  const ch = CFG.channels[$("#nChan").value] || {};
  $("#nMinutes").placeholder = `${ch.long?.target_minutes ?? 8} (padrão do canal)`;
  const cl = ch.clips || {};
  $("#nClipCount").placeholder = cl.count ?? 5;
  $("#nClipMin").placeholder = cl.min_seconds ?? 25;
  $("#nClipMax").placeholder = cl.max_seconds ?? 60;
  $("#nGoLabel").textContent = k === "cortes" ? "Criar cortes" : "Adicionar à fila";
}
$$("#nKind button").forEach((b) => b.onclick = () => setNewKind(b.dataset.k));
$("#nChan").addEventListener("change", () => setNewKind(newKind));

const btnTrends = $("#btnOpenTrends");
if (btnTrends) {
  btnTrends.onclick = async () => {
    const drawer = $("#trendsDrawer");
    if (!drawer.hidden) {
      drawer.hidden = true;
      return;
    }
    drawer.hidden = false;
    drawer.innerHTML = `<span class="small faint">Buscando pautas quentes no Google Trends...</span>`;
    try {
      const list = await api("/api/trends?geo=BR");
      if (!list?.length) {
        drawer.innerHTML = `<span class="small faint">Nenhuma tendência encontrada.</span>`;
        return;
      }
      drawer.innerHTML = list.map((t) => `
        <span class="ai-chip" style="font-size:11px;cursor:pointer" data-trend="${esc(t.query)}" title="${esc(t.news_title || t.query)}">
          🔥 <b>${esc(t.query)}</b> <span class="faint">(${esc(t.traffic || 'alta')})</span>
        </span>
      `).join("");
      $$("[data-trend]", drawer).forEach((chip) => {
        chip.onclick = () => {
          $("#nTopic").value = chip.dataset.trend;
          drawer.hidden = true;
        };
      });
    } catch (e) {
      drawer.innerHTML = `<span class="small err">Falha ao buscar tendências: ${esc(e.message)}</span>`;
    }
  };
}

$("#nFile").addEventListener("change", () => {
  const f = $("#nFile").files[0];
  $("#nFileInfo").textContent = f ? `${f.name} · ${(f.size / 1e6).toFixed(0)} MB` : "";
  if (f) $("#nUrl").value = "";
});

function uploadFile(file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const fd = new FormData();
    fd.append("file", file);
    xhr.open("POST", "/api/uploads");
    $("#nProgress").hidden = false;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) $("#nProgress > div").style.width = `${(e.loaded / e.total) * 100}%`; };
    xhr.onload = () => (xhr.status < 300 ? resolve(JSON.parse(xhr.responseText)) : reject(new Error(JSON.parse(xhr.responseText || "{}").detail || "Falha no envio")));
    xhr.onerror = () => reject(new Error("Falha no envio"));
    xhr.send(fd);
  });
}

$("#newForm").addEventListener("submit", (e) => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const btn = $("#nGo");
  btn.disabled = true;
  act(async () => {
    const body = { channel: $("#nChan").value, kind: newKind };
    if (newKind === "cortes") {
      const file = $("#nFile").files[0];
      body.url = $("#nUrl").value.trim();
      if (file) { const up = await uploadFile(file); body.upload_id = up.id; body.file_name = up.name; }
      if (!body.url && !body.upload_id) throw new Error("Cole um link ou escolha um arquivo");
      body.count = +$("#nClipCount").value || null;
      body.min_seconds = +$("#nClipMin").value || null;
      body.max_seconds = +$("#nClipMax").value || null;
      body.instructions = $("#nInstr").value;
    } else {
      body.topic = $("#nTopic").value;
      body.count = +$("#nCount").value || 1;
      if (newKind === "long") body.minutes = +$("#nMinutes").value || null;
    }
    const r = await api("/api/jobs", { method: "POST", body });
    $("#newDialog").close();
    $("#newForm").reset();
    if (r.created.length === 1) location.hash = `#job/${r.created[0]}`;
    else if (location.hash.startsWith("#painel") || !location.hash) route();
    else location.hash = "#painel";
  }, newKind === "cortes" ? "Fonte enviada; os cortes aparecem quando a seleção terminar" : "Adicionado à fila").finally(() => { btn.disabled = false; });
});

// ------------------------------------------------------------------ pipeline
const KIND_FILTERS = [["", "Tudo"], ["short", "Shorts"], ["long", "Longos"], ["fonte,corte", "Cortes"]];
const kindTag = (k) => k === "short" ? "" : `<span class="tag kind-${k}">${esc(META.kind_labels[k] || k)}</span>`;

async function pageDashboard() {
  const app = $("#app");
  const filter = sessionStorage.getItem("filter") || "";
  const kf = sessionStorage.getItem("kind") || "";
  app.innerHTML = `
    <div class="page-head">
      <div class="grow"><h1>Pipeline</h1><p>Shorts, vídeos longos e cortes, da pauta à publicação.</p></div>
      <button class="btn" id="newCut">${icon("scissors")}Cortes</button>
      <button class="btn" id="newLong">${icon("film")}Vídeo longo</button>
      <button class="btn primary" id="newBtn">${icon("plus")}Novo short</button>
    </div>
    <div class="kpis" id="kpis">${Array(5).fill('<div class="card kpi"><div class="skeleton" style="height:58px"></div></div>').join("")}</div>
    <div class="toolbar">
      <div class="segmented" id="kfilter">${KIND_FILTERS.map(([v, l]) => `<button data-k="${v}" class="${kf === v ? "active" : ""}">${l}</button>`).join("")}</div>
      <div class="segmented" id="filter">
        <button data-f="" class="${!filter ? "active" : ""}">Todos os canais</button>
        ${chanIds().map((id) => `<button data-f="${id}" class="${filter === id ? "active" : ""}"><span class="av c${chanIdx(id)}" style="width:14px;height:14px;border-radius:4px;display:grid;place-items:center;font-size:9px;font-weight:700;color:#fff">${esc(chanName(id).slice(0, 1))}</span>${esc(chanName(id))}</button>`).join("")}
      </div>
    </div>
    <div class="card table">
      <div class="thead"><div>Vídeo</div><div>Canal</div><div>Status</div><div>Etapas</div><div style="text-align:right">Criado</div></div>
      <div id="jobs"><div style="padding:20px"><div class="skeleton" style="height:56px"></div></div></div>
    </div>`;
  const ch0 = () => sessionStorage.getItem("filter");
  $("#newBtn").onclick = () => openNewDialog(ch0(), "short");
  $("#newLong").onclick = () => openNewDialog(ch0(), "long");
  $("#newCut").onclick = () => openNewDialog(ch0(), "cortes");
  $$("#filter button").forEach((b) => b.onclick = () => {
    sessionStorage.setItem("filter", b.dataset.f);
    $$("#filter button").forEach((x) => x.classList.toggle("active", x === b));
    load();
  });
  $$("#kfilter button").forEach((b) => b.onclick = () => {
    sessionStorage.setItem("kind", b.dataset.k);
    $$("#kfilter button").forEach((x) => x.classList.toggle("active", x === b));
    load();
  });

  async function load() {
    const f = sessionStorage.getItem("filter") || "";
    const k = sessionStorage.getItem("kind") || "";
    const q = new URLSearchParams();
    if (f) q.set("channel", f);
    if (k) q.set("kind", k);
    const data = await api(`/api/jobs?${q}`);
    META.paused = data.paused;
    renderWorker();
    renderSidebar(data);
    const totals = { running: 0, queued: 0, waiting_approval: 0, done: 0, failed: 0 };
    for (const [cid, c] of Object.entries(data.stats)) {
      if (f && cid !== f) continue;
      for (const [kk, v] of Object.entries(c)) if (kk in totals) totals[kk] += v;
    }
    const K = [["running", "Rodando", "loader"], ["queued", "Na fila", "clock"], ["waiting_approval", "Para aprovar", "eye"], ["done", "Prontos", "check"], ["failed", "Com falha", "alert"]];
    $("#kpis").innerHTML = K.map(([kk, l, ic]) => `<div class="card kpi ${kk}"><div class="top">${l}<span class="ic">${icon(ic, "sm" + (kk === "running" && totals.running ? " spin" : ""))}</span></div><b>${totals[kk]}</b></div>`).join("");

    const jobs = data.jobs;
    if (!jobs.length) {
      $("#jobs").innerHTML = `<div class="empty-state"><div class="ic">${icon("inbox", "lg")}</div><h3>Nada por aqui ainda</h3>
        <p>Crie um short, um vídeo longo ou mande um vídeo para virar cortes.</p><button class="btn primary" id="emptyNew" style="margin-top:8px">${icon("plus")}Criar</button></div>`;
      $("#emptyNew").onclick = () => openNewDialog(f, k === "long" ? "long" : k ? "cortes" : "short");
      return;
    }
    $("#jobs").innerHTML = jobs.map((j) => {
      const script = j.data.script || {};
      const img = j.data.cover?.image || j.data.images?.[0];
      const st = j.stage ? j.stages[j.stage] : null;
      const now = j.status === "running" && j.stage ? `${META.stage_labels[j.stage]}${st?.detail ? " · " + st.detail : ""}` : "";
      let subText = script.title ? j.topic || "" : (j.kind === "fonte" ? "" : "Gerando pauta…");
      if (j.kind === "fonte") subText = j.data.clips ? `${j.data.clips.length} cortes criados` : (j.data.source?.duration ? `${Math.round(j.data.source.duration / 60)} min de vídeo` : "Vídeo de origem");
      if (j.kind === "corte") subText = `${Math.round(j.data.clip.end - j.data.clip.start)}s · nota ${j.data.clip.score ?? "—"} · de "${j.data.source_title || "fonte"}"`;
      const sub = j.error ? `<div class="sub err ellipsis">${esc(j.error)}</div>` : `<div class="sub ellipsis">${esc(subText)}</div>`;
      const wide = j.kind === "long" || j.kind === "fonte";
      return `<a class="trow" href="#job/${j.id}">
        <div class="lead"><div class="thumb ${wide ? "wide" : ""}" style="${img ? `background-image:url('${fileUrl(j, relPath(j, img))}')` : ""}">${img ? "" : icon(j.kind === "fonte" ? "scissors" : "film", "sm")}</div>
          <div style="min-width:0"><div class="title ellipsis">${kindTag(j.kind)}${esc(script.title || j.data.source?.title || j.topic || "Novo")}</div>${sub}</div></div>
        <div class="c-chan">${chanChip(j.channel)}</div>
        <div>${badge(j.status)}</div>
        <div class="c-steps">${segs(j)}<div class="stage-now ellipsis">${esc(now)}</div></div>
        <div class="when">${ago(j.created_at)}</div>
      </a>`;
    }).join("");
  }
  await load().catch((e) => toast(e.message, true));
  timer = setInterval(() => load().catch(() => {}), 2000);
}

// ------------------------------------------------------------------ detalhe
const fmtTime = (t) => { t = Math.max(0, Math.round(t)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
const fmtTimeMs = (t) => { t = Math.max(0, t || 0); const m = Math.floor(t / 60); const s = Math.floor(t % 60); const ms = Math.floor((t % 1) * 10); return `${m}:${String(s).padStart(2, "0")}.${ms}`; };

async function pageJob(id) {
  const app = $("#app");
  app.innerHTML = `<div class="skeleton" style="height:28px;width:320px;margin-bottom:24px"></div><div class="card skeleton" style="height:120px"></div>`;
  let job = null, children = [], parent = null;
  let lastSig = "";
  let lastLogId = 0;
  let logs = [];
  let tab = null;
  let transcript = null;
  const TYPING = ["apTitle", "apDesc", "apWhen", "apMode", "covText", "clipStart", "clipEnd"];

  async function load(force = false) {
    const r = await api(`/api/jobs/${id}?after=${lastLogId}`);
    job = r.job;
    children = r.children || [];
    parent = r.parent || null;
    if (r.logs.length) {
      logs = logs.concat(r.logs);
      lastLogId = r.logs[r.logs.length - 1].id;
    }
    const sig = JSON.stringify([job.status, job.stages, job.data, job.topic, children.map((c) => [c.id, c.status, c.stage])]);
    const editing = $("#scriptEdit") && !$("#scriptEdit").hidden;
    const typing = document.activeElement && TYPING.includes(document.activeElement.id);
    if (force || (sig !== lastSig && !editing && !typing)) {
      lastSig = sig;
      render();
    } else if (r.logs.length) {
      appendLogs(r.logs);
    }
  }

  const logLine = (l) => `<div class="${l.level}"><span class="ts">${new Date(l.ts * 1000).toLocaleTimeString()}</span><span class="lst">${esc(META.stage_labels[l.stage] || l.stage || "")}</span><span class="m">${esc(l.message)}</span></div>`;

  function appendLogs(items) {
    const box = $("#logs");
    if (!box) return;
    const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
    box.insertAdjacentHTML("beforeend", items.map(logLine).join(""));
    if (stick) box.scrollTop = box.scrollHeight;
    const n = $("#logCount");
    if (n) n.textContent = logs.length;
  }

  function tabsFor(kind) {
    const d = job.data, script = d.script || {};
    const imgs = (d.images || []).filter(Boolean).length;
    const hasTimeline = Boolean((script.scenes && script.scenes.length) || d.clip || d.words);
    const T = {
      timeline: `${icon("sliders", "sm")}Timeline`,
      roteiro: `${icon("file", "sm")}Roteiro`,
      capa: `${icon("cover", "sm")}Capa`,
      cenas: `${icon("image", "sm")}Cenas<span class="n">${imgs}/${script.scenes?.length || 0}</span>`,
      cortes: `${icon("scissors", "sm")}Cortes<span class="n">${children.length}</span>`,
      transcricao: `${icon("wave", "sm")}Transcrição`,
      corte: `${icon("scissors", "sm")}Corte`,
      log: `${icon("term", "sm")}Log<span class="n" id="logCount">${logs.length}</span>`,
    };
    const order = {
      fonte: ["cortes", "transcricao", "log"],
      corte: hasTimeline ? ["timeline", "corte", "capa", "log"] : ["corte", "capa", "log"],
    }[kind] || (hasTimeline ? ["timeline", "roteiro", "capa", "cenas", "log"] : ["roteiro", "capa", "cenas", "log"]);
    return order.map((k) => [k, T[k]]);
  }

  function render() {
    const d = job.data, script = d.script || {}, ch = CFG.channels[job.channel] || {};
    const kind = job.kind;
    const order = stagesOf(job);
    const isLong = kind === "long", isFonte = kind === "fonte", isCorte = kind === "corte";
    const wide = isLong || isFonte;
    const videoPath = isFonte ? relPath(job, d.source?.path) : (d.video ? "final.mp4" : null);
    const video = videoPath ? fileUrl(job, videoPath) : null;
    const firstPending = order.find((s) => job.stages[s].status !== "done") || order[0];
    const title = script.title || d.source?.title || job.topic || "Novo";
    const tabs = tabsFor(kind);
    if (!tab || !tabs.some(([k]) => k === tab)) {
      tab = (job.status === "waiting_approval" && job.stage === "render" && tabs.some(([k]) => k === "timeline")) ? "timeline" : tabs[0][0];
    }
    const facts = isFonte ? [
      ["Duração", d.source?.duration ? fmtTime(d.source.duration) : "—"], ["Cortes", children.length || "—"],
      ["Transcrição", d.transcript?.provider || "—"], ["Palavras", d.transcript?.words?.toLocaleString() || "—"],
    ] : isCorte ? [
      ["Duração", d.duration ? `${d.duration}s` : `${Math.round(d.clip.end - d.clip.start)}s`], ["Nota", d.clip.score ?? "—"],
      ["Trecho", `${fmtTime(d.clip.start)}–${fmtTime(d.clip.end)}`], ["Enquadramento", { face: "rosto", blur: "desfocado", center: "centro" }[d.reframe_mode] || "—"],
    ] : [
      ["Duração", d.duration ? (isLong ? fmtTime(d.duration) : `${d.duration}s`) : "—"], ["Cenas", script.scenes?.length || "—"],
      ["Voz", d.narration?.provider || "—"], ["Caracteres", d.narration?.chars?.toLocaleString() || "—"],
    ];
    const what = { short: "short", long: "vídeo", fonte: "fonte e o vídeo de origem", corte: "corte" }[kind];

    app.innerHTML = `
      <div class="crumbs"><a href="#painel">Pipeline</a>${parent ? `${icon("chev", "sm")}<a href="#job/${parent.id}" class="ellipsis" style="max-width:240px">${esc(parent.topic || "Fonte")}</a>` : ""}${icon("chev", "sm")}<span class="ellipsis">${esc(title)}</span></div>
      <div class="detail-head">
        <div class="grow" style="min-width:280px">
          <h1>${esc(title)}</h1>
          <div class="meta">${kindTag(kind)}${chanChip(job.channel)}${badge(job.status)}<span class="faint small">Criado ${ago(job.created_at)}</span><span class="faint mono">${job.id}</span></div>
        </div>
        <div class="row">
          <select id="retryFrom" style="width:auto" title="Refazer a partir de">${order.map((s) => `<option value="${s}" ${s === firstPending ? "selected" : ""}>A partir de: ${META.stage_labels[s]}</option>`).join("")}</select>
          <button class="btn" id="retry">${icon("refresh")}Refazer</button>
          ${["running", "queued"].includes(job.status) ? `<button class="btn" id="cancel">${icon("x")}Cancelar</button>` : ""}
          <button class="btn danger icon" id="del" title="Excluir">${icon("trash")}</button>
        </div>
      </div>

      <div class="card">${stepper(job)}</div>
      ${job.error ? `<div class="banner err" style="margin-top:16px"><span class="ic">${icon("alert")}</span><div><b>Falha na etapa ${esc(META.stage_labels[job.stage] || "")}</b><div class="small muted" style="margin-top:2px;overflow-wrap:anywhere">${esc(job.error)}</div></div></div>` : ""}
      ${publishedBanner(job)}
      ${job.status === "waiting_approval" ? (job.stage === "render" ? renderApproveCard(job) : approveCard(script, ch)) : ""}

      <div class="detail-grid ${wide ? "wide" : ""}">
        <div class="phone">
          <div class="frame">${video
            ? `<video src="${video}?v=${job.stages.render?.ended || ""}" controls playsinline preload="metadata" id="mainVideo"></video>`
            : (d.images?.some(Boolean) || d.cover?.image
              ? `<div class="phone-live-player" id="phoneLivePlayer">
                  <img id="plpImg" src="${fileUrl(job, relPath(job, (d.images?.find(Boolean) || d.cover?.image)))}" alt="">
                  <div class="caption-overlay" id="plpCaption"></div>
                  <div class="meter-overlay" id="plpMeter" style="display:none">
                    <span class="muted small" id="plpMeterLabel">${esc(ch.creative?.rating_label || "NOTA")}</span>
                    <b style="font-size:16px;color:var(--warn)" id="plpMeterScore">${esc(script.rating != null ? script.rating + "/10" : "")}</b>
                  </div>
                </div>`
              : `<div class="empty">${job.status === "running" ? icon("loader", "lg spin") : icon("film", "lg")}<span>${job.status === "running" ? "O vídeo aparece aqui quando estiver pronto" : "Sem vídeo ainda"}</span></div>`)}</div>
          ${video && !isFonte ? `<div class="row" style="margin-top:12px"><a class="btn grow" href="${video}?download=1">${icon("download")}Baixar MP4</a>
            ${job.status === "done" && d.publish?.mode === "manual" ? `<button class="btn grow" id="pubNow">${icon("yt")}Enviar ao YouTube</button><button class="btn grow" id="pubDraft" title="Sobe privado, sem avisar inscritos">${icon("yt")}Rascunho</button>` : ""}</div>` : ""}
          ${isFonte && d.source?.url ? `<div class="row" style="margin-top:12px"><a class="btn grow" href="${esc(d.source.url)}" target="_blank" rel="noreferrer">${icon("ext")}Abrir original</a></div>` : ""}
          <dl class="facts">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd class="ellipsis">${esc(v)}</dd></div>`).join("")}</dl>
        </div>

        <div class="card" style="min-width:0">
          <div class="tabs-line">${tabs.map(([k, l]) => `<button data-tab="${k}">${l}</button>`).join("")}</div>
          <div id="tabBody"></div>
        </div>
      </div>`;

    $("#retry").onclick = () => act(async () => { await api(`/api/jobs/${id}/retry`, { method: "POST", body: { from_stage: $("#retryFrom").value } }); load(true); }, "Refazendo a partir da etapa escolhida");
    $("#cancel") && ($("#cancel").onclick = () => act(async () => { await api(`/api/jobs/${id}/cancel`, { method: "POST" }); load(true); }, "Cancelado"));
    $("#del").onclick = () => confirm(`Excluir este ${what} e todos os arquivos?`) && act(async () => { await api(`/api/jobs/${id}`, { method: "DELETE" }); location.hash = parent ? `#job/${parent.id}` : "#painel"; }, "Excluído");
    $("#pubDraft") && ($("#pubDraft").onclick = () => act(async () => { await api(`/api/jobs/${id}/publish`, { method: "POST", body: { draft: true } }); load(true); }, "Enviando como rascunho"));
    $("#pubNow") && ($("#pubNow").onclick = () => act(async () => { await api(`/api/jobs/${id}/publish`, { method: "POST", body: {} }); load(true); }, "Enviando ao YouTube"));
    $("#reuploadThumb") && ($("#reuploadThumb").onclick = () => act(async () => { await api(`/api/jobs/${id}/upload-thumbnail`, { method: "POST" }); load(true); }, "Capa reenviada ao YouTube como thumbnail"));
    $("#btnPublishTikTok") && ($("#btnPublishTikTok").onclick = () => act(async () => {
      await api(`/api/jobs/${id}/publish-tiktok`, { method: "POST", body: {} });
      load(true);
    }, "Enviando vídeo para o TikTok"));
    $("#btnPublishIg") && ($("#btnPublishIg").onclick = () => act(async () => {
      await api(`/api/jobs/${id}/publish-instagram`, { method: "POST", body: {} });
      load(true);
    }, "Enviando vídeo para o Instagram Reels"));
    if (job.status === "waiting_approval") bindApprove();
    $$(".tabs-line button").forEach((b) => b.onclick = () => { tab = b.dataset.tab; renderTab(); });
    renderTab();
  }

  async function renderTimeline(body, job, load) {
    body.innerHTML = `<div class="card-body"><div class="skeleton" style="height:260px"></div></div>`;
    let tl;
    try {
      tl = await api(`/api/jobs/${job.id}/timeline`);
    } catch (e) {
      body.innerHTML = emptyTab("alert", `Falha ao carregar timeline: ${e.message}`);
      return;
    }

    if (!tl.scenes?.length && !tl.total_duration) {
      body.innerHTML = emptyTab("sliders", "A timeline de faixas estará disponível assim que o roteiro e a narração forem gerados.");
      return;
    }

    let pxPerSec = 24;
    let currentTime = 0;
    let isPlaying = false;
    let selectedIdx = 0;
    let voiceMuted = false;
    let sfxMuted = false;
    let playTimer = null;

    let audioNarration = null;
    let audioSfx = null;
    let videoEl = $("#mainVideo");

    if (tl.audio?.narration_url) {
      audioNarration = new Audio(tl.audio.narration_url);
      audioNarration.preload = "auto";
    }
    if (tl.audio?.sfx_url) {
      audioSfx = new Audio(tl.audio.sfx_url);
      audioSfx.preload = "auto";
    }

    function cleanupAudio() {
      if (audioNarration) { audioNarration.pause(); audioNarration = null; }
      if (audioSfx) { audioSfx.pause(); audioSfx = null; }
      if (playTimer) { cancelAnimationFrame(playTimer); playTimer = null; }
    }

    const typeIcons = {
      whoosh: "💨",
      impact: "⚡",
      riser: "📈",
      sfx: "🔔",
      blip: "⭐",
      sonic_logo: "🎵"
    };

    body.innerHTML = `
      <div class="card-body stack" style="gap:16px">
        <div class="ai-correct-drawer" id="tlAiDrawer" hidden>
          <div class="row" style="justify-content:space-between;margin-bottom:8px">
            <div class="row" style="gap:8px">
              <span style="color:var(--accent)">${icon("wand")}</span>
              <b style="font-size:13.5px">Assistente de Correção com IA</b>
            </div>
            <button class="btn ghost icon sm" id="tlCloseAi" title="Fechar">${icon("x", "sm")}</button>
          </div>
          <p class="small muted" style="margin-bottom:10px">
            Peça qualquer correção antes de renderizar (ex.: mudar imagem de uma cena, reescrever fala, alterar efeitos ou capa). A IA aplica e refaz o que for necessário.
          </p>
          <div class="ai-chips">
            <span class="ai-chip" data-tpl="A imagem da cena {n} não ficou boa, troque por ">🎨 Mudar imagem da cena...</span>
            <span class="ai-chip" data-tpl="Reescreva a narração da cena {n} para: ">✍️ Ajustar narração...</span>
            <span class="ai-chip" data-tpl="Remova o efeito de susto/impacto da cena {n}">🔊 Tirar susto/impacto...</span>
            <span class="ai-chip" data-tpl="Mude o texto da capa para: ">🖼️ Trocar texto da capa...</span>
          </div>
          <textarea id="tlAiInput" class="prose" style="min-height:76px;margin-bottom:10px" placeholder="Ex.: A imagem da cena 2 não combinou, troque por um laboratório escuro e chuvoso..."></textarea>
          <div class="row" style="justify-content:flex-end;gap:10px">
            <button class="btn sm" id="tlCancelAi">Cancelar</button>
            <button class="btn sm primary" id="tlApplyAi">${icon("check", "sm")}Aplicar correção e refazer</button>
          </div>
        </div>

        <div class="ai-correct-drawer" id="tlSfxDrawer" hidden style="border-color:#38bdf8;background:color-mix(in srgb, #0284c7 15%, var(--surface-2))">
          <div class="row" style="justify-content:space-between;margin-bottom:8px">
            <div class="row" style="gap:8px">
              <span style="color:#38bdf8">${icon("volume")}</span>
              <b style="font-size:13.5px">Adicionar Efeito Sonoro no Cursor (<span id="sfxTimeLabel">0.0s</span>)</b>
            </div>
            <button class="btn ghost icon sm" id="tlCloseSfx" title="Fechar">${icon("x", "sm")}</button>
          </div>
          <p class="small muted" style="margin-bottom:10px">
            Escolha o tipo de efeito para inserir no momento exato da agulha. O áudio é remixado na hora.
          </p>
          <div class="row wrap" style="gap:8px">
            <button class="btn sm" data-sfx="whoosh">💨 Whoosh (Transição)</button>
            <button class="btn sm" data-sfx="impact">⚡ Impacto / Susto</button>
            <button class="btn sm" data-sfx="riser">📈 Riser (Tensão)</button>
            <button class="btn sm" data-sfx="blip">⭐ Blip / Pop</button>
            <button class="btn sm" data-sfx="sfx">🔔 Efeito geral</button>
          </div>
        </div>

        <div class="ai-correct-drawer" id="tlMixerDrawer" hidden style="border-color:var(--warn);background:color-mix(in srgb, var(--warn-soft) 25%, var(--surface-2))">
          <div class="row" style="justify-content:space-between;margin-bottom:8px">
            <div class="row" style="gap:8px">
              <span style="color:var(--warn)">${icon("sliders")}</span>
              <b style="font-size:13.5px">Mixer de Níveis de Áudio</b>
            </div>
            <button class="btn ghost icon sm" id="tlCloseMixer" title="Fechar">${icon("x", "sm")}</button>
          </div>
          <p class="small muted" style="margin-bottom:12px">
            Ajuste o equilíbrio entre a voz da narração, a trilha sonora de fundo e os efeitos sonoros.
          </p>
          <div class="fields" style="grid-template-columns:repeat(3, 1fr);gap:16px">
            <label class="field"><span>🎤 Narração (Voz)</span>
              <input type="range" id="mixVoice" min="0" max="2" step="0.05" value="${job.data?.audio_levels?.voice ?? 1.0}">
              <div class="small faint text-right" id="lblMixVoice">${Math.round((job.data?.audio_levels?.voice ?? 1.0) * 100)}%</div>
            </label>
            <label class="field"><span>🎵 Trilha / Ambiência</span>
              <input type="range" id="mixBgm" min="0" max="2" step="0.05" value="${job.data?.audio_levels?.bgm ?? 1.0}">
              <div class="small faint text-right" id="lblMixBgm">${Math.round((job.data?.audio_levels?.bgm ?? 1.0) * 100)}%</div>
            </label>
            <label class="field"><span>🔔 Efeitos (SFX)</span>
              <input type="range" id="mixSfx" min="0" max="2" step="0.05" value="${job.data?.audio_levels?.sfx ?? 1.0}">
              <div class="small faint text-right" id="lblMixSfx">${Math.round((job.data?.audio_levels?.sfx ?? 1.0) * 100)}%</div>
            </label>
          </div>
          <div class="row" style="justify-content:flex-end;margin-top:10px">
            <button class="btn sm primary" id="btnSaveMixer">${icon("check", "sm")}Salvar Níveis</button>
          </div>
        </div>

        <div class="timeline-card">
          <div class="tl-toolbar">
            <div class="tl-controls">
              <button class="btn icon sm" id="tlPlayBtn" title="Play/Pause (Espaço)">${icon("play", "sm")}</button>
              <button class="btn icon sm" id="tlStopBtn" title="Voltar ao início">${icon("back", "sm")}</button>
              <div class="tl-timer" id="tlTimer">00:00.0 / ${fmtTimeMs(tl.total_duration)}</div>
              ${tl.audio?.narration_url ? `<button class="btn sm ghost" id="tlToggleVoice">${icon("mic", "sm")} <span id="lblVoice">Voz</span></button>` : ""}
              ${tl.audio?.sfx_url ? `<button class="btn sm ghost" id="tlToggleSfx">${icon("volume", "sm")} <span id="lblSfx">Som</span></button>` : ""}
            </div>

            <div class="row" style="gap:8px">
              <button class="btn sm icon" id="tlZoomOut" title="Diminuir escala">${icon("down", "sm")}</button>
              <button class="btn sm" id="tlZoomFit" title="Ajustar à tela">Ajustar</button>
              <button class="btn sm icon" id="tlZoomIn" title="Aumentar escala">${icon("up", "sm")}</button>
              <button class="btn sm" id="tlAddSfxBtn">${icon("plus", "sm")}Adicionar SFX</button>
              <button class="btn sm" id="tlMixerBtn">${icon("sliders", "sm")}Mixer de Áudio</button>
              <button class="btn sm" id="tlOpenAiBtn">${icon("wand", "sm")}Pedir correção</button>
              ${tl.status.is_waiting_render ? `<button class="btn sm primary" id="tlDirectRender">${icon("play", "sm")}Aprovar e Renderizar</button>` : ""}
            </div>
          </div>

          <div class="tl-workspace">
            <div class="tl-headers">
              <div class="tl-hdr-ruler">TEMPO</div>
              <div class="tl-hdr-track tl-hdr-video">${icon("film", "sm")}Vídeo / Cenas</div>
              <div class="tl-hdr-track tl-hdr-captions">${icon("cc", "sm")}Legendas</div>
              <div class="tl-hdr-track tl-hdr-narration">${icon("mic", "sm")}Narração</div>
              <div class="tl-hdr-track tl-hdr-sfx" id="tlHdrSfx">${icon("volume", "sm")}Efeitos (SFX)</div>
              <div class="tl-hdr-track tl-hdr-ambience" id="tlHdrAmbience">🌊 Ambiência</div>
            </div>

            <div class="tl-body" id="tlBody">
              <div class="tl-inner" id="tlInner">
                <div class="tl-ruler" id="tlRuler"></div>
                <div class="tl-playhead" id="tlPlayhead"></div>
                <div class="tl-tracks">
                  <div class="tl-track tl-track-video" id="tlTrackVideo"></div>
                  <div class="tl-track tl-track-captions" id="tlTrackCaptions"></div>
                  <div class="tl-track tl-track-narration" id="tlTrackNarration"></div>
                  <div class="tl-track tl-track-sfx" id="tlTrackSfx"></div>
                  <div class="tl-track tl-track-ambience" id="tlTrackAmbience"></div>
                </div>
              </div>
            </div>
          </div>

          <div class="tl-item-action" id="tlItemAction" hidden></div>
          <div class="tl-inspector" id="tlInspector"></div>
        </div>
      </div>
    `;

    function updateScale() {
      const w = Math.max(700, Math.round(tl.total_duration * pxPerSec));
      $("#tlInner").style.width = `${w}px`;
      drawRuler();
      drawTracks();
      updatePlayhead();
    }

    function drawRuler() {
      const ruler = $("#tlRuler");
      if (!ruler) return;
      let html = "";
      const step = pxPerSec < 15 ? 10 : pxPerSec < 35 ? 5 : 2;
      for (let s = 0; s <= tl.total_duration; s += 1) {
        const x = Math.round(s * pxPerSec);
        if (s % step === 0) {
          html += `<div class="tl-mark" style="left:${x}px">${fmtTime(s)}</div>`;
        } else {
          html += `<div class="tl-submark" style="left:${x}px"></div>`;
        }
      }
      ruler.innerHTML = html;
    }

    function drawTracks() {
      const trVideo = $("#tlTrackVideo");
      let vidHtml = "";
      const covSec = tl.cover?.in_video_seconds || 0;
      if (covSec > 0) {
        const covW = Math.max(16, Math.round(covSec * pxPerSec));
        vidHtml += `<div class="tl-block tl-cover-blk" style="left:0px;width:${covW}px" title="Capa (${covSec}s)">CAPA</div>`;
      }
      tl.scenes.forEach((sc, i) => {
        const left = Math.round((sc.start + covSec) * pxPerSec);
        const width = Math.max(24, Math.round(sc.duration * pxPerSec));
        const bg = sc.image_url ? `background-image:url('${sc.image_url}')` : "";
        vidHtml += `
          <div class="tl-block tl-scene-blk ${i === selectedIdx ? "selected" : ""}" data-idx="${i}" style="left:${left}px;width:${width}px;${bg}" title="Cena ${sc.scene_num}: ${esc(sc.narration)}">
            <div class="tl-scene-top">
              <span class="tl-scene-num">${sc.scene_num}</span>
              <span class="tl-scene-dur">${sc.duration}s</span>
            </div>
            <div class="tl-scene-txt">${esc(sc.narration)}</div>
            ${(sc.shots || []).slice(0, -1).map((sDur, sIdx) => {
              const cutPct = (sc.shots.slice(0, sIdx + 1).reduce((a, b) => a + b, 0) / sc.duration) * 100;
              return `<div class="tl-cut-line" style="left:${cutPct.toFixed(1)}%" title="Corte de plano (${cutPct.toFixed(0)}%)"></div>`;
            }).join("")}
          </div>
        `;
      });
      if (tl.meter) {
        const mLeft = Math.round(tl.meter.start * pxPerSec);
        vidHtml += `<div class="tl-meter-badge" style="left:${mLeft}px">${esc(tl.meter.label)} ${esc(tl.meter.score)}/10</div>`;
      }
      trVideo.innerHTML = vidHtml;

      const trCaptions = $("#tlTrackCaptions");
      let capHtml = "";
      (tl.captions || []).forEach((c) => {
        const left = Math.round(c.start * pxPerSec);
        const width = Math.max(16, Math.round((c.end - c.start) * pxPerSec));
        capHtml += `
          <div class="tl-block tl-cap-blk" style="left:${left}px;width:${width}px" title="[${c.start.toFixed(1)}s - ${c.end.toFixed(1)}s] ${esc(c.text)}">
            <span class="ellipsis">${esc(c.text)}</span>
          </div>
        `;
      });
      trCaptions.innerHTML = capHtml;

      const trNarr = $("#tlTrackNarration");
      let narrHtml = "";
      tl.scenes.forEach((sc, i) => {
        const left = Math.round((sc.start + covSec) * pxPerSec);
        const width = Math.max(20, Math.round(sc.duration * pxPerSec));
        narrHtml += `
          <div class="tl-block tl-speech-blk" data-idx="${i}" style="left:${left}px;width:${width}px" title="Narração cena ${sc.scene_num} (${sc.duration}s)">
            <span class="ellipsis" style="max-width:85%">${esc(sc.narration)}</span>
            <div class="wave"><span></span><span></span><span></span></div>
          </div>
        `;
      });
      trNarr.innerHTML = narrHtml;

      // --- FAIXA DE EFEITOS (SFX) ---
      const hdrSfx = $("#tlHdrSfx");
      const trSfx = $("#tlTrackSfx");
      const sfxEvents = [...(tl.sound_events || [])].sort((a, b) => a.at - b.at);

      function formatEventLabel(ev) {
        const raw = (ev.label || ev.sound || "Som").trim();
        if (ev.type === "whoosh") return "Whoosh";
        if (ev.type === "sonic_logo") return "Assinatura";
        if (ev.type === "blip") return "Selo de nota";
        if (ev.type === "impact") {
          if (/susto/i.test(raw)) return "Susto";
          if (/revela/i.test(raw)) return "Revelação";
          return "Impacto";
        }
        let s = raw.replace(/^[\(\[\"\'\s]+|[\)\]\"\'\s]+$/g, "");
        if (s.length > 15) return s.slice(0, 13) + "…";
        return s;
      }

      function getPillWidth(label) {
        return Math.max(54, Math.min(94, Math.round((label || "").length * 5.8 + 24)));
      }

      const sfxLanes = [];
      const placedSfx = sfxEvents.map((ev) => {
        const left = Math.round(ev.at * pxPerSec);
        const label = formatEventLabel(ev);
        const width = getPillWidth(label);
        const right = left + width;

        let laneIdx = -1;
        for (let i = 0; i < sfxLanes.length; i++) {
          if (left >= sfxLanes[i] + 4) {
            laneIdx = i;
            break;
          }
        }
        if (laneIdx === -1) {
          laneIdx = sfxLanes.length;
          sfxLanes.push(right);
        } else {
          sfxLanes[laneIdx] = right;
        }
        return { ev, label, left, width, lane: laneIdx };
      });

      const numSfxLanes = Math.max(1, sfxLanes.length);
      const SFX_LANE_H = 24;
      const SFX_GAP = 4;
      const totalSfxH = numSfxLanes * SFX_LANE_H + (numSfxLanes - 1) * SFX_GAP + 10;

      if (hdrSfx) hdrSfx.style.height = `${totalSfxH}px`;
      if (trSfx) {
        trSfx.style.height = `${totalSfxH}px`;
        let sfxHtml = "";
        if (!placedSfx.length) {
          sfxHtml = `<div class="tl-empty-hint">Nenhum efeito sonoro cadastrado</div>`;
        } else {
          placedSfx.forEach(({ ev, label, left, width, lane }) => {
            const top = 5 + lane * (SFX_LANE_H + SFX_GAP);
            const ic = typeIcons[ev.type] || "🔔";
            const fullDesc = ev.label || ev.sound || "Som";
            const scIdx = ev.scene ? ev.scene - 1 : -1;
            sfxHtml += `
              <div class="tl-sfx-pill tl-sfx-${ev.type || "sfx"}"
                   data-at="${ev.at}" data-scene="${scIdx}"
                   data-label="${esc(fullDesc)}" data-type="${ev.type || "sfx"}"
                   style="left:${left}px;top:${top}px;width:${width}px"
                   title="[${ev.at}s] ${esc(fullDesc)}">
                <span class="sfx-ic">${ic}</span>
                <span class="sfx-txt">${esc(label)}</span>
              </div>
            `;
          });
        }
        trSfx.innerHTML = sfxHtml;
      }

      // --- FAIXA DE AMBIÊNCIA ---
      const hdrAmb = $("#tlHdrAmbience");
      const trAmb = $("#tlTrackAmbience");
      const beds = (tl.sound_beds || []).slice().sort((a, b) => a.start - b.start);

      if (beds.length === 0) {
        if (hdrAmb) hdrAmb.style.display = "none";
        if (trAmb) trAmb.style.display = "none";
      } else {
        if (hdrAmb) hdrAmb.style.display = "";
        if (trAmb) trAmb.style.display = "";

        const ambLanes = [];
        const placedBeds = beds.map((b) => {
          const left = Math.round(b.start * pxPerSec);
          const width = Math.max(30, Math.round(b.dur * pxPerSec));
          const right = left + width;
          let laneIdx = -1;
          for (let i = 0; i < ambLanes.length; i++) {
            if (left >= ambLanes[i]) {
              laneIdx = i;
              break;
            }
          }
          if (laneIdx === -1) {
            laneIdx = ambLanes.length;
            ambLanes.push(right);
          } else {
            ambLanes[laneIdx] = right;
          }
          return { b, left, width, lane: laneIdx };
        });

        const numAmbLanes = Math.max(1, ambLanes.length);
        const AMB_LANE_H = 24;
        const AMB_GAP = 4;
        const totalAmbH = numAmbLanes * AMB_LANE_H + (numAmbLanes - 1) * AMB_GAP + 8;

        if (hdrAmb) hdrAmb.style.height = `${totalAmbH}px`;
        if (trAmb) {
          trAmb.style.height = `${totalAmbH}px`;
          let ambHtml = "";
          placedBeds.forEach(({ b, left, width, lane }) => {
            const top = 4 + lane * (AMB_LANE_H + AMB_GAP);
            const scIdx = b.scene ? b.scene - 1 : -1;
            ambHtml += `
              <div class="tl-bed-bar" data-start="${b.start}" data-scene="${scIdx}" data-sound="${esc(b.sound)}"
                   style="left:${left}px;top:${top}px;width:${width}px"
                   title="Ambiente: ${esc(b.sound)} (${b.dur}s)">
                <span class="ellipsis">🌊 ${esc(b.sound)}</span>
              </div>
            `;
          });
          trAmb.innerHTML = ambHtml;
        }
      }

      $$(".tl-scene-blk, .tl-speech-blk", $("#tlInner")).forEach((el) => {
        el.onclick = (e) => {
          e.stopPropagation();
          const idx = +el.dataset.idx;
          selectScene(idx);
          seekTo(tl.scenes[idx].start);
        };
      });

      function hideItemAction() {
        const el = $("#tlItemAction");
        if (el) el.hidden = true;
      }

      function showItemAction(kind, item) {
        const box = $("#tlItemAction");
        if (!box) return;
        if (kind === "sfx") {
          const ic = typeIcons[item.type] || "🔔";
          box.innerHTML = `
            <div class="row" style="gap:10px">
              <span style="font-size:18px">${ic}</span>
              <div>
                <div style="font-weight:600;font-size:13px">${esc(item.label || "Efeito sonoro")}</div>
                <div class="small muted">Efeito pontual aos ${item.at}s</div>
              </div>
            </div>
            <div class="row" style="gap:8px">
              <button class="btn sm ghost" id="tlItemClose">${icon("x", "sm")}</button>
              <button class="btn sm danger" id="tlDelSfxBtn">${icon("trash", "sm")}Remover este efeito</button>
            </div>
          `;
          box.hidden = false;
          $("#tlItemClose").onclick = hideItemAction;
          $("#tlDelSfxBtn").onclick = () => {
            if (confirm(`Remover o efeito "${item.label}" aos ${item.at}s? A trilha de som será remixada.`)) {
              act(async () => {
                await api(`/api/jobs/${job.id}/delete-sfx`, { method: "POST", body: { at: item.at, label: item.label } });
                await renderTimeline(body, job, load);
              }, "Efeito sonoro removido");
            }
          };
        } else if (kind === "ambience") {
          box.innerHTML = `
            <div class="row" style="gap:10px">
              <span style="font-size:18px">🌊</span>
              <div>
                <div style="font-weight:600;font-size:13px">Ambiente: ${esc(item.sound || "Fundo")}</div>
                <div class="small muted">Inicia aos ${item.start}s</div>
              </div>
            </div>
            <div class="row" style="gap:8px">
              <button class="btn sm ghost" id="tlItemClose">${icon("x", "sm")}</button>
              <button class="btn sm danger" id="tlDelAmbBtn">${icon("trash", "sm")}Remover ambiente</button>
            </div>
          `;
          box.hidden = false;
          $("#tlItemClose").onclick = hideItemAction;
          $("#tlDelAmbBtn").onclick = () => {
            if (confirm(`Remover o som ambiente "${item.sound}"? A trilha será remixada.`)) {
              act(async () => {
                await api(`/api/jobs/${job.id}/delete-ambience`, { method: "POST", body: { start: item.start, sound: item.sound } });
                await renderTimeline(body, job, load);
              }, "Som ambiente removido");
            }
          };
        }
      }

      if (trSfx) {
        $$(".tl-sfx-pill", trSfx).forEach((el) => {
          el.onclick = (e) => {
            e.stopPropagation();
            const at = parseFloat(el.dataset.at);
            seekTo(at);
            const scIdx = +el.dataset.scene;
            if (!isNaN(scIdx) && scIdx >= 0) selectScene(scIdx, false);
            showItemAction("sfx", { at, label: el.dataset.label, type: el.dataset.type });
          };
        });
      }

      if (trAmb) {
        $$(".tl-bed-bar", trAmb).forEach((el) => {
          el.onclick = (e) => {
            e.stopPropagation();
            const start = parseFloat(el.dataset.start);
            seekTo(start);
            const scIdx = +el.dataset.scene;
            if (!isNaN(scIdx) && scIdx >= 0) selectScene(scIdx, false);
            showItemAction("ambience", { start, sound: el.dataset.sound });
          };
        });
      }
    }

    function selectScene(idx, clearAction = true) {
      if (idx < 0 || idx >= tl.scenes.length) return;
      selectedIdx = idx;
      if (clearAction) {
        const box = $("#tlItemAction");
        if (box) box.hidden = true;
      }
      $$(".tl-scene-blk").forEach((el) => el.classList.toggle("selected", +el.dataset.idx === selectedIdx));
      renderInspector();
    }

    function renderInspector() {
      const insp = $("#tlInspector");
      if (!insp) return;
      const sc = tl.scenes[selectedIdx];
      if (!sc) { insp.innerHTML = ""; return; }

      insp.innerHTML = `
        <div class="tl-insp-preview">
          ${sc.image_url ? `<a href="${sc.image_url}" target="_blank"><img src="${sc.image_url}" alt="Cena ${sc.scene_num}"></a>` : icon("image", "lg")}
        </div>
        <div class="tl-insp-body">
          <div class="tl-insp-head">
            <div>
              <h3 style="font-size:15px">Cena ${sc.scene_num} <span class="muted small">(${fmtTimeMs(sc.start)} – ${fmtTimeMs(sc.end)} · ${sc.duration}s)</span></h3>
              ${sc.beat ? `<span class="tag beat" style="margin-top:4px">Momento de ${sc.beat === "scare" ? "susto" : "revelação"}</span>` : ""}
            </div>
            <div class="row" style="gap:8px">
              ${sc.audio_url ? `<button class="btn sm icon" id="tlPlaySolo" title="Ouvir cena">${icon("volume", "sm")}</button>` : ""}
              <button class="btn sm" id="tlAskSceneAi">${icon("wand", "sm")}Pedir correção</button>
              ${tl.scenes.length > 1 ? `<button class="btn sm danger" id="tlDeleteSceneBtn" title="Excluir esta cena do vídeo">${icon("trash", "sm")}Excluir cena</button>` : ""}
            </div>
          </div>

          <div class="fields two">
            <label class="field">
              <span>Prompt da Imagem</span>
              <textarea id="tlInspPrompt" class="prose" style="min-height:64px">${esc(sc.image_prompt || "")}</textarea>
              <div class="row" style="margin-top:4px">
                <button class="btn sm primary" id="tlRegenImg">${icon("refresh", "sm")}Regerar imagem</button>
              </div>
            </label>

            <label class="field">
              <span>Texto da Narração</span>
              <textarea id="tlInspNarration" class="prose" style="min-height:64px">${esc(sc.narration || "")}</textarea>
              <div class="row" style="margin-top:4px">
                <button class="btn sm" id="tlSaveNarration">${icon("check", "sm")}Salvar narração</button>
              </div>
            </label>
          </div>

          ${(sc.sfx || []).length || sc.ambience ? `
            <div class="row wrap" style="gap:8px;font-size:12px">
              ${sc.ambience ? `<span class="tag">${icon("wave", "sm")}Ambiente: ${esc(sc.ambience)}</span>` : ""}
              ${(sc.sfx || []).map((x) => `<span class="tag">${icon("volume", "sm")}“${esc(x.word)}” → ${esc(x.sound)}</span>`).join("")}
            </div>
          ` : ""}
        </div>
      `;

      $("#tlRegenImg").onclick = () => {
        const prompt = $("#tlInspPrompt").value;
        cleanupAudio();
        act(async () => {
          await api(`/api/jobs/${job.id}/regenerate-image/${selectedIdx}`, { method: "POST", body: { image_prompt: prompt } });
          load(true);
        }, `Regerando imagem da cena ${sc.scene_num}`);
      };

      $("#tlSaveNarration").onclick = () => {
        const text = $("#tlInspNarration").value;
        const script = JSON.parse(JSON.stringify(job.data.script || {}));
        if (script.scenes?.[selectedIdx]) {
          script.scenes[selectedIdx].narration = text;
          cleanupAudio();
          act(async () => {
            await api(`/api/jobs/${job.id}/script`, { method: "PUT", body: script });
            load(true);
          }, `Narração atualizada; refazendo`);
        }
      };

      $("#tlAskSceneAi").onclick = () => {
        const drawer = $("#tlAiDrawer");
        drawer.hidden = false;
        $("#tlAiInput").value = `Na cena ${sc.scene_num}: `;
        $("#tlAiInput").focus();
      };

      if ($("#tlDeleteSceneBtn")) {
        $("#tlDeleteSceneBtn").onclick = () => {
          if (confirm(`Excluir a Cena ${sc.scene_num}? O roteiro será recalculado e a narração reajustada.`)) {
            cleanupAudio();
            act(async () => {
              await api(`/api/jobs/${job.id}/delete-scene`, { method: "POST", body: { scene_num: sc.scene_num } });
              load(true);
            }, "Cena excluída com sucesso");
          }
        };
      }

      if ($("#tlPlaySolo") && sc.audio_url) {
        $("#tlPlaySolo").onclick = () => {
          const a = new Audio(sc.audio_url);
          a.play();
        };
      }
    }

    function updatePlayhead() {
      const ph = $("#tlPlayhead");
      const tm = $("#tlTimer");
      if (ph) ph.style.left = `${Math.round(currentTime * pxPerSec)}px`;
      if (tm) tm.textContent = `${fmtTimeMs(currentTime)} / ${fmtTimeMs(tl.total_duration)}`;

      const plpImg = $("#plpImg");
      const plpCaption = $("#plpCaption");
      const plpMeter = $("#plpMeter");

      const covSec = tl.cover?.in_video_seconds || 0;
      if (covSec > 0 && currentTime < covSec && tl.cover?.image_url) {
        if (plpImg) plpImg.src = tl.cover.image_url;
      } else {
        const activeSc = tl.scenes.find((s) => currentTime >= s.start + covSec && currentTime <= s.end + covSec) || tl.scenes[selectedIdx];
        if (activeSc && plpImg && activeSc.image_url) {
          plpImg.src = activeSc.image_url;
        }
      }

      const activeCap = (tl.captions || []).find((c) => currentTime >= c.start && currentTime <= c.end);
      if (plpCaption) plpCaption.textContent = activeCap ? activeCap.text : "";

      if (plpMeter && tl.meter) {
        plpMeter.style.display = currentTime >= tl.meter.start ? "flex" : "none";
      }
    }

    function seekTo(t) {
      currentTime = Math.max(0, Math.min(tl.total_duration, t));
      if (audioNarration) audioNarration.currentTime = currentTime;
      if (audioSfx) audioSfx.currentTime = currentTime;
      if (videoEl) videoEl.currentTime = currentTime;
      updatePlayhead();
    }

    function togglePlay() {
      if (isPlaying) {
        pausePlayback();
      } else {
        startPlayback();
      }
    }

    function startPlayback() {
      if (currentTime >= tl.total_duration - 0.1) seekTo(0);
      isPlaying = true;
      $("#tlPlayBtn").innerHTML = icon("pause", "sm");

      if (audioNarration) {
        audioNarration.muted = voiceMuted;
        audioNarration.play().catch(() => {});
      }
      if (audioSfx) {
        audioSfx.muted = sfxMuted;
        audioSfx.play().catch(() => {});
      }
      if (videoEl) {
        videoEl.play().catch(() => {});
      }

      function loop() {
        if (!isPlaying) return;
        if (audioNarration && !audioNarration.paused) {
          currentTime = audioNarration.currentTime;
        } else if (videoEl && !videoEl.paused) {
          currentTime = videoEl.currentTime;
        } else {
          currentTime += 0.05;
        }

        if (currentTime >= tl.total_duration) {
          pausePlayback();
          seekTo(tl.total_duration);
          return;
        }
        updatePlayhead();
        playTimer = requestAnimationFrame(loop);
      }
      playTimer = requestAnimationFrame(loop);
    }

    function pausePlayback() {
      isPlaying = false;
      if (playTimer) cancelAnimationFrame(playTimer);
      if ($("#tlPlayBtn")) $("#tlPlayBtn").innerHTML = icon("play", "sm");
      if (audioNarration) audioNarration.pause();
      if (audioSfx) audioSfx.pause();
      if (videoEl) videoEl.pause();
    }

    updateScale();
    selectScene(0);

    $("#tlPlayBtn").onclick = togglePlay;
    $("#tlStopBtn").onclick = () => { pausePlayback(); seekTo(0); };

    if ($("#tlToggleVoice")) {
      $("#tlToggleVoice").onclick = () => {
        voiceMuted = !voiceMuted;
        if (audioNarration) audioNarration.muted = voiceMuted;
        $("#lblVoice").textContent = voiceMuted ? "Voz (Muda)" : "Voz";
      };
    }

    if ($("#tlToggleSfx")) {
      $("#tlToggleSfx").onclick = () => {
        sfxMuted = !sfxMuted;
        if (audioSfx) audioSfx.muted = sfxMuted;
        $("#lblSfx").textContent = sfxMuted ? "Som (Mudo)" : "Som";
      };
    }

    $("#tlZoomIn").onclick = () => { pxPerSec = Math.min(70, Math.round(pxPerSec * 1.3)); updateScale(); };
    $("#tlZoomOut").onclick = () => { pxPerSec = Math.max(10, Math.round(pxPerSec / 1.3)); updateScale(); };
    $("#tlZoomFit").onclick = () => {
      const bodyW = $("#tlBody").clientWidth;
      pxPerSec = Math.max(10, Math.round((bodyW - 40) / tl.total_duration));
      updateScale();
    };

    function onRulerClick(e) {
      const rect = $("#tlRuler").getBoundingClientRect();
      const clickX = e.clientX - rect.left + $("#tlBody").scrollLeft;
      const t = clickX / pxPerSec;
      seekTo(t);
    }
    $("#tlRuler").onclick = onRulerClick;

    $("#tlOpenAiBtn").onclick = () => {
      const d = $("#tlAiDrawer");
      d.hidden = !d.hidden;
      if (!d.hidden) $("#tlAiInput").focus();
    };
    $("#tlCloseAi").onclick = () => { $("#tlAiDrawer").hidden = true; };
    $("#tlCancelAi").onclick = () => { $("#tlAiDrawer").hidden = true; };

    $$(".ai-chip").forEach((chip) => {
      chip.onclick = () => {
        const scNum = tl.scenes[selectedIdx]?.scene_num || 1;
        const tpl = chip.dataset.tpl.replace("{n}", scNum);
        const input = $("#tlAiInput");
        input.value = tpl;
        input.focus();
      };
    });

    $("#tlApplyAi").onclick = () => {
      const instruction = $("#tlAiInput").value.trim();
      if (!instruction) return alert("Por favor digite o que deseja corrigir.");
      cleanupAudio();
      act(async () => {
        await api(`/api/jobs/${job.id}/ai-correct`, { method: "POST", body: { instruction } });
        load(true);
      }, "Aplicando correção com IA");
    };

    $("#tlAddSfxBtn") && ($("#tlAddSfxBtn").onclick = () => {
      const d = $("#tlSfxDrawer");
      d.hidden = !d.hidden;
      if (!d.hidden) {
        $("#sfxTimeLabel").textContent = `${currentTime.toFixed(1)}s`;
      }
    });
    $("#tlCloseSfx") && ($("#tlCloseSfx").onclick = () => { $("#tlSfxDrawer").hidden = true; });

    $$("[data-sfx]").forEach((b) => {
      b.onclick = () => {
        const sfxType = b.dataset.sfx;
        cleanupAudio();
        act(async () => {
          await api(`/api/jobs/${job.id}/add-sfx`, { method: "POST", body: { at: currentTime, type: sfxType } });
          $("#tlSfxDrawer").hidden = true;
          await renderTimeline(body, job, load);
        }, `Efeito '${sfxType}' adicionado aos ${currentTime.toFixed(1)}s`);
      };
    });

    $("#tlMixerBtn") && ($("#tlMixerBtn").onclick = () => {
      const d = $("#tlMixerDrawer");
      d.hidden = !d.hidden;
    });
    $("#tlCloseMixer") && ($("#tlCloseMixer").onclick = () => { $("#tlMixerDrawer").hidden = true; });

    $("#mixVoice") && ($("#mixVoice").oninput = (e) => { $("#lblMixVoice").textContent = `${Math.round(e.target.value * 100)}%`; });
    $("#mixBgm") && ($("#mixBgm").oninput = (e) => { $("#lblMixBgm").textContent = `${Math.round(e.target.value * 100)}%`; });
    $("#mixSfx") && ($("#mixSfx").oninput = (e) => { $("#lblMixSfx").textContent = `${Math.round(e.target.value * 100)}%`; });

    $("#btnSaveMixer") && ($("#btnSaveMixer").onclick = () => {
      const voice = parseFloat($("#mixVoice").value);
      const bgm = parseFloat($("#mixBgm").value);
      const sfx = parseFloat($("#mixSfx").value);
      act(async () => {
        await api(`/api/jobs/${job.id}/adjust-audio-levels`, { method: "POST", body: { voice, bgm, sfx } });
        $("#tlMixerDrawer").hidden = true;
        load(true);
      }, "Níveis de áudio salvos");
    });

    if ($("#tlDirectRender")) {
      $("#tlDirectRender").onclick = () => {
        cleanupAudio();
        act(async () => {
          await api(`/api/jobs/${job.id}/start-render`, { method: "POST" });
          load(true);
        }, "Iniciando renderização");
      };
    }
  }

  function renderTab() {
    $$(".tabs-line button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    const body = $("#tabBody");
    const d = job.data, script = d.script || {};
    if (tab === "timeline") {
      renderTimeline(body, job, load);
      return;
    }
    if (tab === "log") {
      body.innerHTML = `<div class="logs" id="logs">${logs.map(logLine).join("")}</div>`;
      const box = $("#logs"); box.scrollTop = box.scrollHeight;
      return;
    }
    if (tab === "cortes") {
      if (!children.length) { body.innerHTML = emptyTab("scissors", job.status === "running" ? "Os cortes aparecem aqui quando a seleção terminar." : "Nenhum corte criado ainda."); return; }
      body.innerHTML = `<div>${children.map((c) => {
        const cl = c.data.clip || {};
        const img = c.data.cover?.image;
        return `<a class="trow clip-row" href="#job/${c.id}">
          <div class="lead"><div class="thumb" style="${img ? `background-image:url('${fileUrl(c, relPath(c, img))}')` : ""}">${img ? "" : icon("scissors", "sm")}</div>
            <div style="min-width:0"><div class="title ellipsis">${esc(c.data.script?.title || c.topic)}</div>
            <div class="sub ellipsis">${fmtTime(cl.start)}–${fmtTime(cl.end)} · ${Math.round(cl.end - cl.start)}s · ${esc(cl.reason || "")}</div></div></div>
          <div><span class="score">${cl.score ?? "—"}</span></div>
          <div>${badge(c.status)}</div>
          <div class="c-steps">${segs(c)}</div>
        </a>`;
      }).join("")}</div>`;
      return;
    }
    if (tab === "transcricao") {
      if (!d.transcript) { body.innerHTML = emptyTab("wave", "A transcrição aparece aqui quando a etapa terminar."); return; }
      const draw = () => {
        body.innerHTML = `<div class="logs transcript">${transcript.lines.map((l) => `<div><span class="ts">${fmtTime(l.start)}</span><span class="m">${esc(l.text)}</span></div>`).join("")}</div>`;
      };
      if (transcript) draw();
      else {
        body.innerHTML = `<div class="card-body"><div class="skeleton" style="height:200px"></div></div>`;
        api(`/api/jobs/${id}/transcript`).then((t) => { transcript = t; if (tab === "transcricao") draw(); }).catch((e) => { body.innerHTML = emptyTab("alert", e.message); });
      }
      return;
    }
    if (tab === "corte") {
      const cl = d.clip || {};
      const text = (d.words || []).map((w) => w.text).join(" ");
      body.innerHTML = `<div class="card-body stack">
        <dl class="kv">
          <dt>Nota</dt><dd><span class="score">${cl.score ?? "—"}</span></dd>
          <dt>Por quê</dt><dd>${esc(cl.reason || "—")}</dd>
          <dt>Origem</dt><dd>${parent ? `<a href="#job/${parent.id}" class="row" style="gap:6px">${icon("scissors", "sm")}<span class="ellipsis">${esc(d.source_title || parent.topic)}</span></a>` : esc(d.source_title || "—")}</dd>
          <dt>Título</dt><dd style="font-weight:550">${esc(script.title || "—")}</dd>
          <dt>Descrição</dt><dd class="muted" style="white-space:pre-wrap">${esc(script.description || "—")}</dd>
        </dl>
        <div style="border-top:1px solid var(--border);padding-top:16px" class="stack">
          <h3 style="font-size:14px">Ajustar trecho</h3>
          <div class="row wrap" style="align-items:flex-end">
            <label class="field" style="width:140px"><span>Início (s)</span><input id="clipStart" type="number" step="0.1" value="${cl.start}"></label>
            <label class="field" style="width:140px"><span>Fim (s)</span><input id="clipEnd" type="number" step="0.1" value="${cl.end}"></label>
            <button class="btn" id="clipApply">${icon("scissors")}Aplicar e refazer</button>
          </div>
          <p class="small faint">Use a aba Transcrição da fonte para achar os tempos. Ajustar refaz recorte, capa, legenda e render.</p>
        </div>
        <div style="border-top:1px solid var(--border);padding-top:16px"><h3 style="font-size:14px;margin-bottom:8px">Fala do corte</h3><p style="line-height:1.65">${esc(text || "—")}</p></div>
      </div>`;
      $("#clipApply").onclick = () => act(async () => {
        await api(`/api/jobs/${id}/clip`, { method: "PUT", body: { start: +$("#clipStart").value, end: +$("#clipEnd").value } });
        document.activeElement?.blur();
        load(true);
      }, "Refazendo o corte");
      return;
    }
    if (tab === "capa") {
      const cov = d.cover;
      const chCov = CFG.channels[job.channel]?.cover || {};
      const isLong = job.kind === "long";
      if (!chCov.enabled && !cov) { body.innerHTML = emptyTab("cover", "A capa está desligada para este canal (Canais → Capa)."); return; }
      const src = cov?.image ? `${fileUrl(job, relPath(job, cov.image))}?v=${job.stages.capa?.ended || ""}` : null;
      const text = d.cover_text_override ?? cov?.text ?? script.cover_text ?? "";
      const bgDesc = job.kind === "corte" ? "Frame do próprio corte" : chCov.source === "scene" ? `Imagem da cena ${chCov.scene || 1}` : "Imagem própria gerada por IA";
      body.innerHTML = `<div class="card-body"><div class="cover-wrap ${isLong ? "wide" : ""}">
        ${src ? `<a href="${src}" target="_blank"><img class="cover-img" src="${src}" alt="Capa"></a>` : `<div class="cover-img">${icon("cover", "lg")}</div>`}
        <div class="stack">
          <label class="field"><span>Texto da ${isLong ? "thumbnail" : "capa"}</span><input id="covText" value="${esc(text)}" placeholder="Sem texto">
            <span class="hint">Coloque a palavra de destaque entre [colchetes]. Deixe vazio para não ter texto.</span></label>
          <div class="row wrap">
            <button class="btn primary" id="covApply">${icon("check")}Aplicar texto</button>
            <button class="btn" id="covNew">${icon("refresh")}Novo fundo</button>
            ${cov?.jpg ? `<a class="btn" href="${fileUrl(job, relPath(job, cov.jpg))}?download=1">${icon("download")}Baixar JPG</a>` : ""}
          </div>
          <dl class="kv small">
            <dt>Fundo</dt><dd>${bgDesc}</dd>
            ${isLong ? `<dt>Formato</dt><dd>Thumbnail 1280×720</dd>` : `<dt>No vídeo</dt><dd>${chCov.in_video ? `Primeiros ${chCov.in_video_seconds || 0.3}s (frame usado no feed de Shorts)` : "Não"}</dd>`}
            <dt>Thumbnail</dt><dd>${chCov.upload_thumbnail ? "Enviada junto no upload automático" : "Não enviada"}</dd>
            ${script.cover_prompt && job.kind !== "corte" ? `<dt>Prompt</dt><dd class="faint">${esc(script.cover_prompt)}</dd>` : ""}
          </dl>
          <p class="small faint">Mudar a capa refaz legendas e render e pede nova aprovação.</p>
        </div></div></div>`;
      $("#covApply").onclick = () => act(async () => { await api(`/api/jobs/${id}/cover`, { method: "POST", body: { text: $("#covText").value } }); load(true); }, "Refazendo a capa");
      $("#covNew").onclick = () => act(async () => { await api(`/api/jobs/${id}/cover`, { method: "POST", body: { text: $("#covText").value, new_image: true } }); load(true); }, "Gerando novo fundo");
      return;
    }
    if (tab === "cenas") {
      if (!script.scenes) { body.innerHTML = emptyTab("image", "As cenas aparecem depois do roteiro."); return; }
      body.innerHTML = `<div class="card-body"><div class="scenes ${job.kind === "long" ? "wide" : ""}">${script.scenes.map((s, i) => {
        const img = d.images?.[i];
        const src = img ? `${fileUrl(job, relPath(job, img))}?v=${job.stages.imagens.ended || ""}` : null;
        return `<div class="scene"><div class="img">${src ? `<a href="${src}" target="_blank"><img src="${src}" loading="lazy" alt=""></a>` : icon("image", "lg")}
            <span class="num">${i + 1}</span>
            ${src ? `<button class="btn icon sm regen" data-i="${i}" title="Gerar nova imagem">${icon("refresh", "sm")}</button>` : ""}</div>
          ${s.chapter ? `<div class="chapter">${esc(s.chapter)}</div>` : ""}
          <div class="txt">${esc(s.narration)}</div>
          ${s.beat || s.ambience || (s.sfx || []).length ? `<div class="sfx-list">
            ${s.beat ? `<span class="tag beat">${s.beat === "scare" ? "susto" : "revelação"}</span>` : ""}
            ${s.ambience ? `<span class="tag" title="Ambiente">${icon("wave", "sm")}${esc(s.ambience)}</span>` : ""}
            ${(s.sfx || []).map((x) => `<span class="tag" title="Efeito na palavra “${esc(x.word)}”">${icon("volume", "sm")}${esc(x.word)} → ${esc(x.sound)}</span>`).join("")}</div>` : ""}
          <div class="prompt" title="${esc(s.image_prompt || "")}">${esc(s.image_prompt || "")}</div></div>`;
      }).join("")}</div></div>`;
      $$(".regen", body).forEach((b) => b.onclick = () => {
        const i = +b.dataset.i;
        const p = prompt("Prompt da imagem (edite se quiser):", script.scenes[i].image_prompt || "");
        if (p === null) return;
        act(async () => { await api(`/api/jobs/${id}/regenerate-image/${i}`, { method: "POST", body: { image_prompt: p } }); load(true); }, `Gerando nova imagem para a cena ${i + 1}`);
      });
      return;
    }
    // roteiro
    const chapters = d.chapters || [];
    body.innerHTML = `<div class="card-body stack">
      <dl class="kv">
        ${d.format ? `<dt>Formato</dt><dd>${esc(d.format)}</dd>` : ""}
        ${d.series_no ? `<dt>Série</dt><dd>#${esc(d.series_no)}</dd>` : ""}
        ${script.rating != null ? `<dt>${esc(CFG.channels[job.channel]?.creative?.rating_label || "Nota")}</dt><dd><span class="score">${esc(script.rating)}/10</span></dd>` : ""}
        ${d.critique?.rounds?.length ? `<dt>Revisor</dt><dd>${critiqueView(d.critique)}</dd>` : ""}
        ${(script.characters || []).length ? `<dt>Personagens</dt><dd class="stack" style="gap:4px">${script.characters.map((c) => `<div><b>${esc(c.name)}</b> <span class="muted small">${esc(c.look || "")}</span></div>`).join("")}</dd>` : ""}
        <dt>Pauta</dt><dd>${esc(job.topic || "—")}${d.source?.link ? `<div><a class="small faint row" style="gap:4px;margin-top:4px" href="${esc(d.source.link)}" target="_blank" rel="noreferrer">${icon("ext", "sm")}<span class="ellipsis">${esc(d.source.link)}</span></a></div>` : ""}</dd>
        ${script.title ? `<dt>Título</dt><dd style="font-weight:550">${esc(script.title)}</dd>
        <dt>Descrição</dt><dd style="white-space:pre-wrap" class="muted">${esc(script.description || "—")}</dd>
        <dt>Tags</dt><dd><div class="tags">${(script.tags || []).map((t) => `<span class="tag">#${esc(t)}</span>`).join("") || "—"}</div></dd>` : ""}
        ${chapters.length ? `<dt>Capítulos</dt><dd class="stack" style="gap:4px">${chapters.map((c) => `<div class="row" style="gap:10px"><span class="mono faint">${fmtTime(c.start)}</span>${esc(c.title)}</div>`).join("")}</dd>` : ""}
      </dl>
      ${script.scenes ? `
        <div class="row" style="border-top:1px solid var(--border);padding-top:16px"><h3 class="grow" style="font-size:14px">Narração</h3>
          <button class="btn sm" id="editScript">${icon("edit", "sm")}Editar roteiro</button></div>
        <div id="scriptView" class="stack" style="gap:10px">${script.scenes.map((s, i) => `${s.chapter ? `<div class="chapter">${esc(s.chapter)}</div>` : ""}<div class="row" style="align-items:flex-start;gap:12px"><span class="tag" style="flex:none">${i + 1}</span><p style="line-height:1.6">${esc(s.narration)}</p></div>`).join("")}</div>
        <div id="scriptEdit" hidden><textarea id="scriptJson" style="min-height:380px">${esc(JSON.stringify(script, null, 2))}</textarea>
          <div class="row" style="margin-top:12px;justify-content:flex-end"><button class="btn" id="cancelEdit">Cancelar</button><button class="btn primary" id="saveScript">Salvar e refazer da narração</button></div></div>`
      : emptyTab("file", "O roteiro aparece aqui quando a etapa terminar.")}
    </div>`;
    $("#editScript") && ($("#editScript").onclick = () => { $("#scriptEdit").hidden = false; $("#scriptView").hidden = true; });
    $("#cancelEdit") && ($("#cancelEdit").onclick = () => { $("#scriptEdit").hidden = true; $("#scriptView").hidden = false; });
    $("#saveScript") && ($("#saveScript").onclick = () => act(async () => {
      let s;
      try { s = JSON.parse($("#scriptJson").value); } catch { throw new Error("JSON inválido no roteiro"); }
      await api(`/api/jobs/${id}/script`, { method: "PUT", body: s });
      $("#scriptEdit").hidden = true;
      load(true);
    }, "Roteiro salvo; refazendo a partir da narração"));
  }

  const emptyTab = (ic, msg) => `<div class="empty-state"><div class="ic">${icon(ic, "lg")}</div><p>${esc(msg)}</p></div>`;

  function renderApproveCard(job) {
    return `<div class="card approve render-approve" style="margin-top:16px">
      <div class="card-head"><span class="ic">${icon("sliders")}</span><h3 class="grow">Pronto para renderizar</h3><span class="small muted">Confira a timeline com todas as faixas antes de iniciar o render</span></div>
      <div class="card-body stack">
        <p style="line-height:1.6">Todas as etapas anteriores (roteiro, narração, imagens, capa, legendas e som) foram concluídas.
        Você pode conferir a timeline abaixo com todas as faixas sincronizadas, dar play para ouvir e ver a prévia ao vivo, clicar em qualquer cena para inspecionar ou regerar, ou pedir correções para a IA antes de renderizar.</p>
        <div class="row wrap" style="justify-content:flex-end;gap:12px">
          <button class="btn" id="tlTopAi">${icon("wand")}Pedir correção para IA</button>
          <button class="btn primary" id="tlTopRender">${icon("play")}Aprovar e Iniciar Render</button>
        </div>
      </div></div>`;
  }

  function approveCard(script, ch) {
    const mode = ch.upload?.mode || "manual";
    return `<div class="card approve" style="margin-top:16px">
      <div class="card-head"><span class="ic">${icon("eye")}</span><h3 class="grow">Revisar e aprovar</h3><span class="small muted">Assista ao vídeo abaixo antes de aprovar</span></div>
      <div class="card-body stack">
        <div class="fields two">
          <label class="field"><span>Título</span><input id="apTitle" value="${esc(script.title || "")}" maxlength="100"></label>
          <label class="field"><span>Publicação</span><select id="apMode">
            <option value="manual" ${mode === "manual" ? "selected" : ""}>Manual: eu baixo e posto</option>
            <option value="draft" ${mode === "draft" ? "selected" : ""}>Rascunho: subir privado e terminar no Studio</option>
            <option value="auto" ${mode === "auto" ? "selected" : ""}>Automática: enviar ao YouTube</option></select></label>
        </div>
        <label class="field"><span>Descrição</span><textarea id="apDesc" class="prose">${esc(script.description || "")}</textarea></label>
        <div class="row wrap">
          <label class="field" style="width:260px"><span>Agendar publicação</span><input id="apWhen" type="datetime-local"><span class="hint">Opcional, só no modo automático</span></label>
          <div class="grow"></div>
          <button class="btn danger" id="apNo">${icon("x")}Rejeitar</button>
          <button class="btn" id="apDraft" title="Sobe privado, sem avisar inscritos; você termina no YouTube Studio">${icon("yt")}Enviar como rascunho</button>
          <button class="btn success" id="apOk">${icon("check")}Aprovar</button>
        </div>
      </div></div>`;
  }

  function bindApprove() {
    if (job.status === "waiting_approval" && job.stage === "render") {
      $("#tlTopRender") && ($("#tlTopRender").onclick = () => act(async () => {
        await api(`/api/jobs/${id}/start-render`, { method: "POST" });
        load(true);
      }, "Iniciando renderização"));
      $("#tlTopAi") && ($("#tlTopAi").onclick = () => {
        tab = "timeline";
        renderTab();
        const drawer = $("#tlAiDrawer");
        if (drawer) {
          drawer.hidden = false;
          $("#tlAiInput")?.focus();
        }
      });
      return;
    }
    $("#apOk").onclick = () => act(async () => {
      const when = $("#apWhen").value;
      await api(`/api/jobs/${id}/approve`, { method: "POST", body: {
        title: $("#apTitle").value, description: $("#apDesc").value, upload_mode: $("#apMode").value,
        publish_at: when ? new Date(when).toISOString() : null } });
      document.activeElement?.blur();
      load(true);
    }, "Aprovado");
    $("#apDraft").onclick = () => act(async () => {
      await api(`/api/jobs/${id}/approve`, { method: "POST", body: {
        title: $("#apTitle").value, description: $("#apDesc").value, upload_mode: "draft" } });
      document.activeElement?.blur();
      load(true);
    }, "Enviando como rascunho");
    $("#apNo").onclick = () => confirm("Rejeitar este vídeo?") && act(async () => { await api(`/api/jobs/${id}/reject`, { method: "POST" }); load(true); }, "Rejeitado");
  }

  function publishedBanner(job) {
    const p = job.data.publish;
    if (job.kind === "fonte" && job.status === "done") return `<div class="banner ok" style="margin-top:16px"><span class="ic">${icon("scissors")}</span><div><b>${children.length} cortes criados</b>
      <div class="small muted">Cada corte segue pelo pipeline como um short. Veja a aba Cortes.</div></div></div>`;
    if (!p || job.status !== "done") return "";
    const ttInfo = p.tiktok ? `<div class="small muted" style="margin-top:4px"><b>TikTok:</b> ${esc(p.tiktok.status || "Enviado")} (${esc(p.tiktok.privacy || "SELF_ONLY")})</div>` : (p.tiktok_error ? `<div class="small" style="color:var(--err);margin-top:4px">Aviso TikTok: ${esc(p.tiktok_error)}</div>` : "");
    const igInfo = p.instagram ? `<div class="small muted" style="margin-top:4px"><b>Instagram:</b> <a href="${esc(p.instagram.permalink)}" target="_blank" rel="noreferrer">Ver Reel</a></div>` : (p.instagram_error ? `<div class="small" style="color:var(--err);margin-top:4px">Aviso Instagram: ${esc(p.instagram_error)}</div>` : "");
    const ttBtn = `<button class="btn sm" id="btnPublishTikTok" title="Enviar para o TikTok">${icon("play", "sm")}Enviar para o TikTok</button>`;
    const igBtn = `<button class="btn sm" id="btnPublishIg" title="Publicar no Instagram Reels">${icon("play", "sm")}Publicar no Reels</button>`;
    if (p.mode === "draft" && p.video_id) return `<div class="banner ok" style="margin-top:16px"><span class="ic">${icon("yt")}</span><div class="grow"><b>Rascunho no YouTube</b>
      <div class="small muted">Subiu como privado, sem avisar os inscritos. Termine e publique pelo YouTube Studio.</div>
      ${p.thumbnail_error ? `<div class="small" style="color:var(--err);margin-top:4px">Aviso na capa: ${esc(p.thumbnail_error)}</div>` : ""}
      ${ttInfo}${igInfo}</div>
      <div class="row" style="gap:8px">
        ${ttBtn}
        ${igBtn}
        <button class="btn sm" id="reuploadThumb" title="Reenviar thumbnail para o YouTube">${icon("upload", "sm")}Reenviar capa</button>
        <a class="btn sm primary" href="${esc(p.studio_url || `https://studio.youtube.com/video/${p.video_id}/edit`)}" target="_blank" rel="noreferrer">${icon("ext", "sm")}Abrir no Studio</a>
      </div></div>`;
    if (p.mode === "auto" && p.url) return `<div class="banner ok" style="margin-top:16px"><span class="ic">${icon("yt")}</span><div class="grow"><b>Publicado no YouTube</b>
      <div class="small muted">${esc(p.privacy)}${p.publish_at ? ` · agendado para ${new Date(p.publish_at).toLocaleString()}` : ""}</div>
      ${p.thumbnail_error ? `<div class="small" style="color:var(--err);margin-top:4px">Aviso na capa: ${esc(p.thumbnail_error)}</div>` : ""}
      ${ttInfo}${igInfo}</div>
      <div class="row" style="gap:8px">
        ${ttBtn}
        ${igBtn}
        <button class="btn sm" id="reuploadThumb" title="Reenviar thumbnail para o YouTube">${icon("upload", "sm")}Reenviar capa</button>
        <a class="btn sm" href="${esc(p.url)}" target="_blank" rel="noreferrer">${icon("ext", "sm")}Abrir</a>
      </div></div>`;
    if (p.mode === "manual") return `<div class="banner ok" style="margin-top:16px"><span class="ic">${icon("check")}</span><div class="grow"><b>Pronto para postar</b>
      <div class="small muted">Baixe o MP4 e use o título e a descrição do roteiro.</div>
      ${ttInfo}${igInfo}</div>
      <div class="row" style="gap:8px">
        ${ttBtn}
        ${igBtn}
      </div></div>`;
    return "";
  }

  try { await load(true); } catch (e) {
    app.innerHTML = `<div class="card empty-state"><div class="ic">${icon("alert", "lg")}</div><h3>Não encontrado</h3><p>${esc(e.message)}</p><a class="btn" href="#painel">${icon("back")}Voltar ao pipeline</a></div>`;
    return;
  }
  timer = setInterval(() => load().catch(() => {}), 1500);
}

function critiqueView(cq) {
  const LBL = { hook: "Gancho", entrega: "Entrega", ritmo: "Ritmo", final: "Final", titulo: "Título" };
  return `<div class="stack" style="gap:10px">${cq.rounds.map((r, i) => `<div class="critique">
    <div class="row" style="gap:10px"><span class="score ${r.score >= cq.min_score ? "ok" : "low"}">${r.score}/10</span>
      <span class="small muted">${cq.rounds.length > 1 ? `Rodada ${i + 1}` : ""}${r.rewritten ? " · reescrito" : r.score >= cq.min_score ? " · aprovado" : ""}</span></div>
    ${Object.keys(r.scores || {}).length ? `<div class="tags" style="margin-top:6px">${Object.entries(r.scores).map(([k, v]) => `<span class="tag">${esc(LBL[k] || k)} ${esc(v)}</span>`).join("")}</div>` : ""}
    ${(r.issues || []).length ? `<ul class="small muted" style="margin:6px 0 0 18px">${r.issues.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`).join("")}</div>`;
}

async function learnBox(cid, el) {
  if (!el) return;
  let r;
  try { r = await api(`/api/learn/${cid}`); } catch (e) { el.innerHTML = `<p class="small muted">${esc(e.message)}</p>`; return; }
  const when = r.learned_at ? new Date(r.learned_at * 1000).toLocaleString() : null;
  const scores = Object.entries(r.format_scores || {}).sort((a, b) => b[1] - a[1]);
  el.innerHTML = `
    <div class="row" style="gap:10px;align-items:center">
      <div class="grow small ${when ? "muted" : "faint"}">${r.running ? "Analisando o Analytics…" : when ? `Última análise: ${esc(when)} · ${r.videos} vídeos, ${r.days} dias` : "Ainda não analisado. Precisa do YouTube conectado com Analytics."}</div>
      <button class="btn sm" data-learn ${r.running ? "disabled" : ""}>${icon(r.running ? "loader" : "refresh", r.running ? "sm spin" : "sm")}Analisar agora</button>
    </div>
    ${r.error ? `<p class="small" style="color:var(--warn);margin-top:8px">Última tentativa falhou: ${esc(r.error)}</p>` : ""}
    ${r.summary ? `<p style="margin-top:10px;font-weight:550">${esc(r.summary)}</p>` : ""}
    ${r.insights ? `<pre class="learn-text">${esc(r.insights)}</pre>` : ""}
    ${scores.length ? `<div class="hbars" style="margin-top:10px">${scores.map(([f, v]) => `<div class="hbar" title="${esc(f)}: ${(v * 100).toFixed(0)}"><span class="ellipsis">${esc(f)}</span><div class="track"><div class="fill" style="width:${(v * 100).toFixed(0)}%"></div></div><span class="v">${(v * 100).toFixed(0)}</span></div>`).join("")}</div>
      <p class="small faint" style="margin-top:6px">Nota de cada formato (0–100): quanto mais alta, mais vezes ele volta.</p>` : ""}`;
  $("[data-learn]", el).onclick = () => {
    el.querySelector("[data-learn]").disabled = true;
    el.querySelector(".grow").textContent = "Analisando o Analytics… (leva 1 a 2 minutos)";
    act(async () => { try { await api(`/api/learn/${cid}`, { method: "POST" }); } finally { await learnBox(cid, el); } }, "Aprendizado atualizado");
  };
}

// ------------------------------------------------------------------ analytics
const nf = new Intl.NumberFormat("pt-BR");
const nfc = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
const fmtNum = (n) => (Math.abs(n) >= 10000 ? nfc.format(n) : nf.format(Math.round(n * 10) / 10));
const fmtDur = (s) => { s = Math.round(s || 0); return s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`; };
const fmtDay = (iso, long = false) => new Date(iso + "T12:00:00").toLocaleDateString("pt-BR", long ? { day: "2-digit", month: "short", year: "numeric" } : { day: "2-digit", month: "short" });
let anaChannel = null;
let anaDays = 28;
let anaMetric = "views";

function niceTicks(max, count = 4) {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const ticks = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function lineChart(el, points, { label, format = fmtNum }) {
  const draw = () => {
    const W = Math.max(320, el.clientWidth - 16), H = 260;
    const m = { l: 48, r: 12, t: 12, b: 28 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const ys = points.map((p) => p.y);
    const minY = Math.min(0, ...ys);
    const ticks = niceTicks(Math.max(...ys, 1) - minY).map((t) => t + minY);
    const top = ticks[ticks.length - 1];
    const x = (i) => m.l + (points.length < 2 ? iw / 2 : (i / (points.length - 1)) * iw);
    const y = (v) => m.t + ih - ((v - minY) / (top - minY || 1)) * ih;
    const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join("");
    const area = `${path}L${x(points.length - 1).toFixed(1)},${y(Math.max(minY, 0)).toFixed(1)}L${x(0).toFixed(1)},${y(Math.max(minY, 0)).toFixed(1)}Z`;
    const every = Math.max(1, Math.ceil(points.length / 7));
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(label)} por dia">
      <g class="grid">${ticks.map((t) => `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}"/>`).join("")}</g>
      <g class="axis">${ticks.map((t) => `<text x="${m.l - 8}" y="${y(t) + 4}" text-anchor="end">${fmtNum(t)}</text>`).join("")}
        ${points.map((p, i) => (i % every === 0 || i === points.length - 1) && (i === points.length - 1 || points.length - 1 - i >= every / 2)
          ? `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${fmtDay(p.x)}</text>` : "").join("")}</g>
      <path class="area" d="${area}"/><path class="line" d="${path}"/>
      <line class="xhair" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/><circle class="dot" r="5" visibility="hidden"/>
      <rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent" class="hit"/>
    </svg><div class="tip" hidden></div>`;
    const svg = el.querySelector("svg"), tip = el.querySelector(".tip");
    const xh = svg.querySelector(".xhair"), dot = svg.querySelector(".dot");
    const move = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const i = Math.max(0, Math.min(points.length - 1, Math.round(((px - m.l) / iw) * (points.length - 1))));
      const p = points[i];
      xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(p.y)); dot.setAttribute("visibility", "visible");
      tip.hidden = false;
      tip.style.left = `${(x(i) / W) * r.width + 4}px`;
      tip.style.top = `${(y(p.y) / H) * r.height + 8}px`;
      tip.replaceChildren();
      const d = document.createElement("div"); d.className = "small faint"; d.textContent = fmtDay(p.x, true);
      const b = document.createElement("b"); b.textContent = format(p.y);
      const s = document.createElement("div"); s.className = "small muted";
      s.innerHTML = `<span class="sw" style="background:var(--series-1)"></span>`; s.append(label);
      tip.append(d, b, s);
    };
    const leave = () => { tip.hidden = true; xh.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); };
    const hit = svg.querySelector(".hit");
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerleave", leave);
  };
  draw();
  const ro = new ResizeObserver(() => draw());
  ro.observe(el);
  return () => ro.disconnect();
}

function delta(cur, prev, invert = false) {
  if (!prev) return `<span class="delta">sem período anterior</span>`;
  const pct = ((cur - prev) / Math.abs(prev)) * 100;
  if (!isFinite(pct) || Math.abs(pct) < 0.5) return `<span class="delta">${icon("chev", "sm")}estável</span>`;
  const up = pct > 0;
  const good = invert ? !up : up;
  return `<span class="delta ${good ? "up" : "down"}">${icon(up ? "up" : "down", "sm")}${Math.abs(pct).toFixed(pct > 10 ? 0 : 1)}% vs período anterior</span>`;
}

async function pageAnalytics(arg) {
  const ids = chanIds();
  anaChannel = arg && CFG.channels[arg] ? arg : (anaChannel && CFG.channels[anaChannel] ? anaChannel : ids[0]);
  const app = $("#app");
  const head = () => `
    <div class="page-head">
      <div class="grow"><h1>Analytics</h1><p>Desempenho dos canais no YouTube.</p></div>
      <button class="btn" id="anaRefresh" title="Buscar de novo no YouTube">${icon("refresh")}Atualizar</button>
    </div>
    <div class="toolbar">
      <div class="segmented" id="anaCh">${ids.map((c) => `<button data-c="${c}" class="${c === anaChannel ? "active" : ""}"><span class="av c${chanIdx(c)}" style="width:14px;height:14px;border-radius:4px;display:grid;place-items:center;font-size:9px;font-weight:700;color:#fff">${esc(chanName(c).slice(0, 1))}</span>${esc(chanName(c))}</button>`).join("")}</div>
      <div class="grow"></div>
      <div class="segmented" id="anaDays">${[[7, "7 dias"], [28, "28 dias"], [90, "90 dias"], [365, "12 meses"]].map(([d, l]) => `<button data-d="${d}" class="${d === anaDays ? "active" : ""}">${l}</button>`).join("")}</div>
    </div>`;
  let disposeChart = null;

  async function load(refresh = false) {
    disposeChart?.();
    app.innerHTML = head() + `<div class="card skeleton" style="height:90px"></div><div class="stat-grid">${Array(6).fill('<div class="card stat"><div class="skeleton" style="height:56px"></div></div>').join("")}</div><div class="card skeleton" style="height:300px"></div>`;
    bindHead();
    let r;
    try {
      r = await api(`/api/analytics/${anaChannel}?days=${anaDays}${refresh ? "&refresh=1" : ""}`);
    } catch (e) {
      app.innerHTML = head() + `<div class="card empty-state"><div class="ic">${icon("alert", "lg")}</div><h3>Não deu para buscar os dados</h3><p>${esc(e.message)}</p></div>`;
      bindHead();
      return;
    }
    if (r.state === "disconnected" || r.state === "needs_reconnect") {
      const recon = r.state === "needs_reconnect";
      app.innerHTML = head() + `<div class="card empty-state"><div class="ic">${icon("yt", "lg")}</div>
        <h3>${recon ? "Reconecte o canal para liberar o Analytics" : `${esc(chanName(anaChannel))} não está conectado ao YouTube`}</h3>
        <p>${recon ? "A conexão atual foi feita antes da permissão de Analytics. Reconecte e aceite a nova permissão de leitura de métricas." : "Conecte o canal para ver views, retenção, inscritos e fontes de tráfego."}</p>
        <a class="btn primary" href="/api/youtube/connect/${anaChannel}" style="margin-top:8px">${icon("yt")}${recon ? "Reconectar" : "Conectar"} ${esc(chanName(anaChannel))}</a></div>`;
      bindHead();
      return;
    }
    render(r);
  }

  function bindHead() {
    $$("#anaCh button").forEach((b) => b.onclick = () => { location.hash = `#analytics/${b.dataset.c}`; });
    $$("#anaDays button").forEach((b) => b.onclick = () => { anaDays = +b.dataset.d; load(); });
    $("#anaRefresh").onclick = () => load(true);
  }

  function render(r) {
    const t = r.totals || {}, p = r.previous || {}, c = r.channel;
    const net = (o) => (o.subscribersGained || 0) - (o.subscribersLost || 0);
    const stats = [
      ["Views", fmtNum(t.views || 0), delta(t.views, p.views)],
      ["Horas assistidas", fmtNum((t.estimatedMinutesWatched || 0) / 60), delta(t.estimatedMinutesWatched, p.estimatedMinutesWatched)],
      ["Inscritos (líquido)", `${net(t) >= 0 ? "+" : ""}${fmtNum(net(t))}`, delta(net(t), net(p))],
      ["Duração média", fmtDur(t.averageViewDuration), delta(t.averageViewDuration, p.averageViewDuration)],
      ["% assistida", `${(t.averageViewPercentage || 0).toFixed(1)}%`, delta(t.averageViewPercentage, p.averageViewPercentage)],
      ["Curtidas", fmtNum(t.likes || 0), delta(t.likes, p.likes)],
    ];
    const METRIC = { views: ["Views", (d) => d.views, fmtNum], minutes: ["Minutos assistidos", (d) => d.minutes, fmtNum], subs: ["Inscritos (líquido)", (d) => d.subs, (v) => `${v >= 0 ? "+" : ""}${nf.format(v)}`] };
    const contentTotal = r.content.reduce((a, x) => a + x.views, 0);
    const content = r.content.filter((x) => x.views > 0).sort((a, b) => b.views - a.views);
    const cColor = (i) => (i === 0 ? "var(--series-1)" : i === 1 ? "var(--series-2)" : "var(--text-3)");
    const traffic = r.traffic.slice(0, 8);
    const tMax = Math.max(1, ...traffic.map((x) => x.views));
    const thumb = (v, isShort) => v.thumbnail ? `<img src="${esc(v.thumbnail)}" class="${isShort ? "short" : ""}" alt="" loading="lazy">` : `<img alt="">`;
    const jobLink = (v) => v.job_id ? `<a class="tag kind-corte" href="#job/${v.job_id}" title="Feito pelo pipeline" style="margin-left:6px">pipeline</a>` : "";

    app.innerHTML = head() + `
      <div class="card ch-strip">
        ${c.thumbnail ? `<img src="${esc(c.thumbnail)}" alt="">` : ""}
        <div class="grow"><div style="font-weight:650;font-size:16px">${esc(c.title)}</div>
          <div class="small faint">${fmtDay(r.range.start, true)} – ${fmtDay(r.range.end, true)} · atualizado ${new Date(r.fetched_at * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })} · dados do YouTube têm 1–3 dias de atraso</div></div>
        <div><div class="big">${c.hidden_subscribers ? "oculto" : fmtNum(c.subscribers)}</div><div class="lbl">inscritos</div></div><div class="sep"></div>
        <div><div class="big">${fmtNum(c.views)}</div><div class="lbl">views totais</div></div><div class="sep"></div>
        <div><div class="big">${nf.format(c.videos)}</div><div class="lbl">vídeos</div></div>
      </div>

      <div class="stat-grid">${stats.map(([l, v, dl]) => `<div class="card stat"><div class="lbl">${l}</div><div class="val">${v}</div>${dl}</div>`).join("")}</div>

      <div class="card">
        <div class="card-head"><h3 class="grow" id="chartTitle">${METRIC[anaMetric][0]} por dia</h3>
          <div class="segmented" id="anaMetric">${Object.entries(METRIC).map(([k, [l]]) => `<button data-m="${k}" class="${k === anaMetric ? "active" : ""}">${l}</button>`).join("")}</div>
          <button class="btn sm ghost" id="anaTableBtn">Tabela</button></div>
        <div class="chart" id="anaChart"></div>
        <div id="anaTable" hidden class="table-scroll" style="max-height:320px;overflow:auto"></div>
      </div>

      <div class="two-col">
        <div class="card"><div class="card-head"><h3 class="grow">Views por formato</h3></div><div class="card-body">
          ${content.length ? `<div class="split" role="img" aria-label="Divisão de views por formato">${content.map((x, i) => `<div style="flex:${x.views};background:${cColor(i)}" title="${esc(x.type)}: ${nf.format(x.views)} views"></div>`).join("")}</div>
          <div class="legend">${content.map((x, i) => `<div class="row"><span class="sw" style="background:${cColor(i)}"></span><span class="grow">${esc(x.type)}</span>
            <span class="muted" style="font-variant-numeric:tabular-nums">${nf.format(x.views)}</span><span class="faint" style="width:52px;text-align:right">${((x.views / (contentTotal || 1)) * 100).toFixed(0)}%</span></div>`).join("")}</div>`
          : `<p class="faint small">Sem dados de formato para este período.</p>`}
        </div></div>
        <div class="card"><div class="card-head"><h3 class="grow">Fontes de tráfego</h3><span class="small faint">views</span></div><div class="card-body">
          ${traffic.length ? `<div class="hbars">${traffic.map((x) => `<div class="hbar" title="${esc(x.source)}: ${nf.format(x.views)} views"><span class="ellipsis">${esc(x.source)}</span>
            <div class="track"><div class="fill" style="width:${(x.views / tMax) * 100}%"></div></div><span class="v">${fmtNum(x.views)}</span></div>`).join("")}</div>`
          : `<p class="faint small">Sem dados de tráfego para este período.</p>`}
        </div></div>
      </div>

      <div class="card" style="margin-top:16px"><div class="card-head"><span class="ic">${icon("bulb")}</span><h3 class="grow">O que o canal aprendeu</h3><span class="small faint">vai para os prompts de pauta, roteiro e revisor</span></div>
        <div class="card-body"><div id="anaLearn" class="learn-box"><div class="skeleton" style="height:60px"></div></div></div></div>

      <div class="card" style="margin-top:16px"><div class="card-head"><h3 class="grow">Top vídeos no período</h3></div>
        ${r.top.length ? `<div class="table-scroll"><table class="vtable"><thead><tr><th>Vídeo</th><th>Views</th><th>% assistida</th><th>Duração média</th><th>Curtidas</th><th>Inscritos</th></tr></thead><tbody>
          ${r.top.map((v) => `<tr><td><div class="vthumb">${thumb(v, v.seconds && v.seconds <= 180)}<div style="min-width:0"><a class="t" href="https://youtube.com/watch?v=${esc(v.id)}" target="_blank" rel="noreferrer">${esc(v.title || v.id)}</a>
            <div class="small faint">${v.seconds && v.seconds <= 180 ? "Short" : "Vídeo"}${v.published ? " · " + fmtDay(v.published.slice(0, 10), true) : ""}${jobLink(v)}</div></div></div></td>
            <td>${nf.format(v.views)}</td><td>${(v.avg_percent || 0).toFixed(0)}%</td><td>${fmtDur(v.avg_duration)}</td><td>${nf.format(v.likes)}</td><td>${nf.format(v.subs)}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="empty-state"><p>Nenhum vídeo com views neste período.</p></div>`}
      </div>

      <div class="card" style="margin-top:16px"><div class="card-head"><h3 class="grow">Publicados pelo pipeline</h3><span class="small faint">totais desde a publicação</span></div>
        ${r.pipeline.length ? `<div class="table-scroll"><table class="vtable"><thead><tr><th>Vídeo</th><th>Publicado</th><th>Views</th><th>Curtidas</th><th>Comentários</th></tr></thead><tbody>
          ${r.pipeline.map((v) => `<tr><td><div class="vthumb">${thumb(v, v.kind !== "long")}<div style="min-width:0"><a class="t" href="#job/${v.job_id}">${esc(v.title)}</a>
            <div class="small faint">${esc(META.kind_labels[v.kind] || "Short")} · <a href="https://youtube.com/watch?v=${esc(v.id)}" target="_blank" rel="noreferrer">abrir no YouTube</a></div></div></div></td>
            <td>${v.published ? fmtDay(v.published.slice(0, 10), true) : "—"}</td><td>${nf.format(v.total_views)}</td><td>${nf.format(v.total_likes)}</td><td>${nf.format(v.total_comments)}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="empty-state"><p>Nenhum vídeo enviado pelo upload automático ainda. Os publicados manualmente não aparecem aqui.</p></div>`}
      </div>`;
    bindHead();
    learnBox(anaChannel, $("#anaLearn"));

    const drawMetric = () => {
      disposeChart?.();
      const [label, get, fmt] = METRIC[anaMetric];
      $("#chartTitle").textContent = `${label} por dia`;
      const pts = r.daily.map((d) => ({ x: d.day, y: get(d) }));
      disposeChart = lineChart($("#anaChart"), pts, { label, format: fmt });
      $("#anaTable").innerHTML = `<table class="vtable"><thead><tr><th>Dia</th><th>Views</th><th>Minutos</th><th>Inscritos</th></tr></thead><tbody>
        ${[...r.daily].reverse().map((d) => `<tr><td>${fmtDay(d.day, true)}</td><td>${nf.format(d.views)}</td><td>${nf.format(d.minutes)}</td><td>${d.subs >= 0 ? "+" : ""}${nf.format(d.subs)}</td></tr>`).join("")}</tbody></table>`;
    };
    $$("#anaMetric button").forEach((b) => b.onclick = () => {
      anaMetric = b.dataset.m;
      $$("#anaMetric button").forEach((x) => x.classList.toggle("active", x === b));
      drawMetric();
    });
    $("#anaTableBtn").onclick = () => {
      const show = $("#anaTable").hidden;
      $("#anaTable").hidden = !show; $("#anaChart").hidden = show;
      $("#anaTableBtn").textContent = show ? "Gráfico" : "Tabela";
    };
    drawMetric();
  }

  await load();
}

// ------------------------------------------------------------------ campos de configuração
const get = (obj, path) => path.split(".").reduce((o, k) => o?.[k], obj);
function set(obj, path, val) {
  const ks = path.split(".");
  const last = ks.pop();
  const t = ks.reduce((o, k) => (o[k] ??= {}), obj);
  t[last] = val;
}
const key = (base, path) => `${base === CFG ? "" : "ch:"}${path}`;

function field(base, path, label, type = "text", extra = "", hint = "") {
  const v = get(base, path);
  const k = key(base, path);
  const h = hint ? `<span class="hint">${hint}</span>` : "";
  if (type === "switch") return `<label class="switch"><input type="checkbox" data-p="${k}" ${v ? "checked" : ""}><span class="track"></span><span>${label}</span></label>`;
  if (type === "textarea") return `<label class="field"><span>${label}</span><textarea data-p="${k}" ${extra}>${esc(v)}</textarea>${h}</label>`;
  if (type === "range") {
    const [min, max, step] = extra.split(",");
    return `<label class="field"><span>${label}</span><div class="range"><input type="range" data-p="${k}" data-t="number" min="${min}" max="${max}" step="${step}" value="${v ?? 0}"><output>${v ?? 0}</output></div>${h}</label>`;
  }
  return `<label class="field"><span>${label}</span><input type="${type}" data-p="${k}" ${type === "number" ? 'data-t="number"' : ""} value="${esc(v ?? "")}" ${extra}>${h}</label>`;
}

function select(base, path, label, options, hint = "") {
  const v = get(base, path) ?? "";
  return `<label class="field"><span>${label}</span><select data-p="${key(base, path)}">${options.map(([val, lbl]) => `<option value="${esc(val)}" ${val === v ? "selected" : ""}>${esc(lbl)}</option>`).join("")}</select>${hint ? `<span class="hint">${hint}</span>` : ""}</label>`;
}

const section = (title, desc, body) => `<section class="section"><div class="section-info"><h2>${title}</h2><p>${desc}</p></div><div class="card">${body}</div></section>`;

function bindFields(root, chId, onChange) {
  $$("[data-p]", root).forEach((el) => {
    const handler = () => {
      let p = el.dataset.p, base = CFG;
      if (p.startsWith("ch:")) { p = p.slice(3); base = CFG.channels[chId]; }
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (el.dataset.t === "number") v = v === "" ? null : +v;
      if (el.dataset.t === "lines") v = el.value.split("\n").map((s) => s.trim()).filter(Boolean);
      if (el.dataset.t === "csv") v = el.value.split(",").map((s) => s.trim()).filter(Boolean);
      set(base, p, v);
      if (el.type === "range") el.nextElementSibling.textContent = v;
      markDirty();
      onChange?.(p, v);
    };
    el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", handler);
  });
}

function markDirty() {
  CFG_DIRTY = true;
  $("#savebar") && ($("#savebar").hidden = false);
}

const saveBar = () => `<div class="savebar" id="savebar" hidden><span class="dot"></span><span class="small" style="font-weight:500">Alterações não salvas</span>
  <button class="btn sm ghost" id="discard">Descartar</button><button class="btn sm primary" id="save">Salvar alterações</button></div>`;

function bindSaveBar(rerender) {
  if (CFG_DIRTY) $("#savebar").hidden = false;
  $("#save").onclick = () => act(async () => {
    CFG = await api("/api/config", { method: "PUT", body: CFG });
    CFG_DIRTY = false;
    $("#savebar").hidden = true;
    renderSidebar();
  }, "Configurações salvas");
  $("#discard").onclick = async () => { CFG = await api("/api/config"); CFG_DIRTY = false; rerender(); };
}

// ------------------------------------------------------------------ canais
async function pageChannels(tab) {
  const ids = chanIds();
  channelTab = tab && CFG.channels[tab] ? tab : (channelTab && CFG.channels[channelTab] ? channelTab : ids[0]);
  const [yt, tt] = await Promise.all([
    api("/api/youtube").catch(() => ({})),
    api("/api/tiktok").catch(() => ({})),
  ]);
  const app = $("#app");
  const id = channelTab;
  const ch = CFG.channels[id];
  const n = ch.models.narracao;
  const ytc = yt[id] || {};
  const ttc = tt[id] || {};
  const igc = { configured: Boolean((ch.instagram?.access_token || CFG.instagram?.access_token) && (ch.instagram?.account_id || CFG.instagram?.account_id)) };
  const providerOpts = (stage) => META.model_stages[stage].map((p) => [p, META.provider_labels[p]]);

  const modelRow = (stage) => {
    const m = ch.models[stage];
    return `<div class="model-row">
      <div class="name">${icon(STAGE_ICON[stage])}${META.stage_labels[stage]}</div>
      ${select(ch, `models.${stage}.provider`, "Provedor", providerOpts(stage))}
      ${field(ch, `models.${stage}.model`, stage === "narracao" ? "Modelo" : "Modelo", "text", `list="dl-${stage}" placeholder="padrão da CLI"`)}
      ${select(ch, `models.${stage}.fallback_provider`, "Reserva", [["", "Nenhuma"], ...providerOpts(stage)])}
      ${field(ch, `models.${stage}.fallback_model`, "Modelo da reserva", "text", `list="dlf-${stage}" placeholder="padrão"`)}
      <datalist id="dl-${stage}">${(META.model_suggestions[m.provider] || []).filter(Boolean).map((s) => `<option value="${esc(s)}">`).join("")}</datalist>
      <datalist id="dlf-${stage}">${(META.model_suggestions[m.fallback_provider] || []).filter(Boolean).map((s) => `<option value="${esc(s)}">`).join("")}</datalist>
    </div>`;
  };

  const voiceBody = n.provider === "elevenlabs" ? `
    <div class="card-body stack">
      <div class="voice-current"><span class="av">${esc((n.voice_name || "?").slice(0, 1))}</span>
        <div class="grow"><div style="font-weight:600">${esc(n.voice_name || "Nenhuma voz escolhida")}</div><div class="faint mono">${esc(n.voice_id || "")}</div></div>
        <button class="btn sm" id="loadVoices">${icon("mic", "sm")}Trocar voz</button>
        <button class="btn sm" id="preview">${icon("volume", "sm")}Ouvir</button></div>
      <div id="voices"></div>
      <div class="fields">
        ${field(ch, "models.narracao.stability", "Estabilidade", "range", "0,1,0.05", "Menor = mais emoção e variação")}
        ${field(ch, "models.narracao.similarity_boost", "Similaridade", "range", "0,1,0.05", "Fidelidade à voz original")}
        ${field(ch, "models.narracao.style", "Estilo", "range", "0,1,0.05", "Exagero da interpretação")}
        ${field(ch, "models.narracao.speed", "Velocidade", "range", "0.7,1.2,0.01", "1 = normal")}
      </div>
      <audio id="audio" controls hidden style="width:100%"></audio>
    </div>` : `
    <div class="card-body stack">
      <div class="fields">${field(ch, "models.narracao.rate", "Velocidade", "text", "", "ex.: -8% ou +10%")}${field(ch, "models.narracao.pitch", "Tom", "text", "", "ex.: -12Hz")}</div>
      <div><button class="btn sm" id="preview">${icon("volume", "sm")}Ouvir teste</button></div>
      <audio id="audio" controls hidden style="width:100%"></audio>
    </div>`;

  app.innerHTML = `
    <div class="page-head">
      <div class="grow"><h1>Canais</h1><p>Como cada canal escreve, narra, ilustra e publica.</p></div>
      <button class="btn" id="addCh">${icon("plus")}Novo canal</button>
    </div>
    <div class="toolbar"><div class="segmented">${ids.map((c) => `<button data-tab="${c}" class="${c === id ? "active" : ""}"><span class="av c${chanIdx(c)}" style="width:14px;height:14px;border-radius:4px;display:grid;place-items:center;font-size:9px;font-weight:700;color:#fff">${esc(chanName(c).slice(0, 1))}</span>${esc(CFG.channels[c].name)}</button>`).join("")}</div></div>

    <div class="settings">
      ${section("Geral", "Nome, idioma e nicho. O nicho é enviado para a IA em todos os prompts.", `<div class="card-body stack">
        <div class="row">${field(ch, "enabled", "Canal ativo", "switch")}<div class="grow"></div><button class="btn sm danger" id="delCh">${icon("trash", "sm")}Remover canal</button></div>
        <div class="fields two">${field(ch, "name", "Nome")}${field(ch, "language", "Idioma do roteiro")}</div>
        ${field(ch, "niche", "Nicho e descrição", "textarea", 'class="prose"')}</div>`)}

      ${section("Modelos por etapa", "Claude, Codex e Gemini (agy) rodam pelas CLIs logadas com a sua conta, via OAuth. Se o principal falhar por cota ou erro, a reserva assume.",
        `<div class="models">${["ideia", "roteiro", "critica", "selecao", "imagens", "narracao"].map(modelRow).join("")}</div>`)}

      ${section("Voz", n.provider === "elevenlabs" ? "Voz do ElevenLabs. Se faltar crédito, a narração usa a reserva (Edge TTS) com a voz do campo \"Modelo da reserva\"." : "Voz do Edge TTS (grátis). O nome da voz fica no campo Modelo da narração.", voiceBody)}

      ${section("Pauta", "De onde vem o assunto de cada short quando você não digita uma pauta.", `<div class="card-body stack">
        ${select(ch, "idea.source", "Origem", [["llm", "IA sugere (sem repetir títulos)"], ["rss", "Notícias de RSS (IA como reserva)"]])}
        <label class="field"><span>Feeds RSS</span><textarea data-p="ch:idea.rss_urls" data-t="lines" style="min-height:90px">${esc((ch.idea.rss_urls || []).join("\n"))}</textarea><span class="hint">Um endereço por linha</span></label></div>`)}

      ${section("Prompts", "Variáveis: <code>{channel}</code> <code>{niche}</code> <code>{language}</code> <code>{topic}</code> <code>{scenes}</code> <code>{seconds}</code> <code>{words}</code> <code>{history}</code>. Use <code>{{ }}</code> para chaves literais.", `<div class="card-body stack">
        ${field(ch, "prompts.idea", "Prompt da pauta", "textarea", 'style="min-height:160px"')}
        ${field(ch, "prompts.script", "Prompt do roteiro (shorts)", "textarea", 'style="min-height:300px"')}
        ${field(ch, "prompts.long_script", "Prompt do roteiro (vídeo longo)", "textarea", 'style="min-height:300px"', "Variáveis extras: {minutes}")}
        ${field(ch, "prompts.clip_select", "Prompt da seleção de cortes", "textarea", 'style="min-height:300px"', "Variáveis extras: {transcript} {count} {min_seconds} {max_seconds} {source_title} {instructions}")}
        ${field(ch, "prompts.image_style", "Estilo visual", "textarea", 'style="min-height:70px"', "Adicionado ao final de cada prompt de imagem")}
        <div><button class="btn sm" id="resetPrompts">${icon("refresh", "sm")}Restaurar padrões</button></div></div>`)}

      ${section("Vídeo", `Formato, legendas e efeitos. Música de fundo: coloque arquivos MP3 em <code>assets/music/${esc(id)}/</code>.`, `<div class="card-body stack">
        <div class="fields">
          ${field(ch, "video.scenes", "Cenas", "number", 'min="2" max="15"')}
          ${field(ch, "video.target_seconds", "Duração alvo (s)", "number", 'min="10" max="180"')}
          ${select(ch, "video.effects", "Efeito visual", META.effects.map((e) => [e, { none: "Nenhum", terror: "Terror (granulado e vinheta)", vibrante: "Vibrante" }[e] || e]))}
          ${field(ch, "video.music_volume", "Volume da música", "number", 'step="0.01" min="0" max="1"', "0 a 1")}
        </div>
        <div class="fields">
          ${select(ch, "video.caption_font", "Fonte da legenda", META.fonts.map((f) => [f, f]))}
          ${field(ch, "video.caption_size", "Tamanho", "number")}
          ${field(ch, "video.words_per_caption", "Palavras por bloco", "number", 'min="1" max="6"')}
          <div class="row" style="gap:16px">${field(ch, "video.caption_color", "Texto", "color")}${field(ch, "video.highlight_color", "Destaque", "color")}</div>
        </div>
        <div class="fields">
          ${select(ch, "video.transition_style", "Transição de Cenas", [
            ["dynamic", "Dinâmica (Alterna estilos cinematográficos)"],
            ["cut", "Corte Seco (Rápido / Padrão)"],
            ["whip_pan", "Whip Pan (Chicote lateral veloz)"],
            ["zoom_punch", "Zoom Punch (Impacto de aproximação)"],
            ["cinematic", "Cinematográfica (Dissolve suave)"],
            ["glitch", "Glitch (Tech / Distorção)"]
          ])}
          ${field(ch, "video.dynamic_emojis", "Emojis dinâmicos nas legendas", "switch")}
        </div>
        ${field(ch, "video.caption_uppercase", "Legenda em maiúsculas", "switch")}</div>`)}

      ${section("Direção criativa", "Ritmo, som e narrativa. A IA marca no roteiro onde entram efeitos sonoros, ambiente e momentos de impacto; o render corta a cena em vários planos e a música abaixa quando a voz fala.", `<div class="card-body stack">
        <div class="fields">
          ${field(ch, "creative.cut_every", "Trocar de plano a cada (s)", "number", 'min="0" max="10" step="0.5"', "Shorts. 0 = um plano por cena")}
          ${field(ch, "creative.cut_every_long", "Planos no vídeo longo (s)", "number", 'min="0" max="20" step="0.5"')}
          ${select(ch, "creative.sound_style", "Estilo de som", [["neutro", "Neutro (suave, serve para qualquer nicho)"], ["terror", "Terror (impactos, tensão, flash)"], ["tech", "Tech (swooshes limpos)"]])}
          ${field(ch, "creative.max_sfx", "Máx. efeitos por vídeo", "number", 'min="0" max="20"', "Cada efeito gasta créditos do ElevenLabs (com cache)")}
        </div>
        <div class="fields">
          ${field(ch, "creative.sfx_volume", "Volume dos efeitos", "range", "0,1,0.05")}
          ${field(ch, "creative.ambience_volume", "Volume do ambiente", "range", "0,0.5,0.01")}
        </div>
        <div class="row wrap" style="gap:24px">
          ${field(ch, "creative.sound", "Desenho de som", "switch")}
          ${field(ch, "creative.whoosh", "Whoosh nas transições", "switch")}
          ${field(ch, "creative.beat_fx", "Impacto nos sustos/revelações", "switch")}
          ${field(ch, "creative.emotion_tags", "Emoção na voz (eleven_v3)", "switch")}
          ${field(ch, "creative.loop_ending", "Final em loop", "switch")}
        </div>
        <div class="sub-head">Marca do canal</div>
        <label class="field"><span>Narrador fixo</span><textarea data-p="ch:creative.persona" class="prose" style="min-height:70px" placeholder="Ex.: uma professora animada que explica tudo com analogias do dia a dia">${esc(ch.creative?.persona || "")}</textarea>
          <span class="hint">Personagem que narra todos os vídeos. Vazio = sem narrador fixo.</span></label>
        <div class="fields">
          ${field(ch, "creative.signoff", "Bordão final", "text", 'placeholder="Ex.: E essa você não sabia."', "Última frase de todo vídeo")}
          ${field(ch, "creative.series_name", "Série (na descrição)", "text", 'placeholder="Ex.: Curiosidades — Episódio #{n}"', "{n} = número; {nnn} = com zeros")}
          ${field(ch, "creative.series_badge", "Selo na capa", "text", 'placeholder="Ex.: EP. #{nnn}"')}
          ${field(ch, "creative.series_start", "Começar a série em", "number", 'min="1"', "Usado só no primeiro vídeo da série")}
        </div>
        <div class="row wrap" style="gap:24px;align-items:flex-end">
          ${field(ch, "creative.sonic_logo", "Assinatura sonora no loop", "switch")}
          <div class="grow" style="min-width:280px">${field(ch, "creative.sonic_logo_prompt", "Som da assinatura (inglês)", "text", 'placeholder="Ex.: short bright two-note chime"', "Gerado uma vez no ElevenLabs e reaproveitado")}</div>
        </div>
        <div class="row wrap" style="gap:24px;align-items:flex-end">
          ${field(ch, "creative.rating_meter", "Selo de nota no fim do vídeo", "switch")}
          ${field(ch, "creative.rating_label", "Texto do selo", "text", 'placeholder="Ex.: NOTA, DIFICULDADE, HYPE REAL"')}
          ${field(ch, "creative.rating_seconds", "Duração (s)", "number", 'min="1" max="5" step="0.2"')}
        </div>
        ${field(ch, "creative.rating_criteria", "A nota mede", "text", 'placeholder="Ex.: o quanto a receita é fácil de fazer em casa"', "A IA dá a nota de 0 a 10 no roteiro; uma barra animada mostra a nota nos últimos segundos do short")}
        <div class="sub-head">Revisor de roteiro</div>
        <div class="row wrap" style="gap:24px;align-items:flex-end">
          ${field(ch, "creative.review_script", "Revisar o roteiro antes da narração", "switch")}
          ${field(ch, "creative.review_min_score", "Nota mínima (0–10)", "number", 'min="0" max="10"', "Abaixo disso, reescreve")}
          ${field(ch, "creative.review_rounds", "Máx. reescritas", "number", 'min="1" max="3"')}
        </div>
        <p class="small faint" style="margin-top:-4px">Uma segunda IA (Modelos por etapa → Revisor de roteiro) dá nota ao gancho, à entrega, ao ritmo, ao final e ao título.</p>
        <div class="sub-head">Personagens</div>
        <div class="row wrap" style="gap:24px">
          ${field(ch, "creative.characters", "Personagens com aparência fixa", "switch")}
          ${field(ch, "creative.character_refs", "Usar a 1ª imagem como referência", "switch")}
        </div>
        <p class="small faint" style="margin-top:-4px">O roteiro descreve cada personagem uma vez; as cenas seguintes recebem a imagem em que ele apareceu primeiro como referência (codex e agy).</p>
        ${ch.models.narracao.provider === "elevenlabs" && !(ch.models.narracao.model || "").startsWith("eleven_v3") && ch.creative?.emotion_tags ? `<p class="small" style="color:var(--warn)">As marcações de emoção só funcionam com o modelo <b>eleven_v3</b> na narração (Modelos por etapa).</p>` : ""}
        <label class="field"><span>Formatos (um por linha)</span><textarea data-p="ch:creative.formats" data-t="lines" class="prose" style="min-height:120px">${esc((ch.creative?.formats || []).join("\n"))}</textarea>
          <span class="hint">O pipeline alterna entre eles; com o aprendizado ligado, os que rendem mais voltam mais vezes.</span></label>
        <label class="field"><span>O que funciona no canal (escrito por você)</span><textarea data-p="ch:creative.insights" class="prose" style="min-height:120px">${esc(ch.creative?.insights || "")}</textarea>
          <span class="hint">Vai para os prompts de pauta, roteiro e revisor, junto com o aprendizado automático abaixo.</span></label>
        <div class="sub-head">Aprendizado automático</div>
        <div class="row wrap" style="gap:24px;align-items:flex-end">
          ${field(ch, "creative.auto_learn", "Aprender com o Analytics", "switch")}
          ${field(ch, "creative.learn_every_days", "Reanalisar a cada (dias)", "number", 'min="1" max="60"')}
        </div>
        <div id="learnBox" class="learn-box"><div class="skeleton" style="height:60px"></div></div>
      </div>`)}

      ${section("Vídeo longo", "Vídeos horizontais (16:9) gerados do zero, com capítulos na descrição e thumbnail 1280×720. Usa a mesma voz, os mesmos modelos e o mesmo estilo visual do canal.", `<div class="card-body stack">
        <div class="fields">
          ${field(ch, "long.target_minutes", "Duração alvo (min)", "number", 'min="1" max="60" step="0.5"')}
          ${field(ch, "long.seconds_per_image", "Segundos por imagem", "number", 'min="5" max="60"', "Menos imagens = mais rápido e menos cota")}
          ${field(ch, "long.caption_size", "Tamanho da legenda", "number", 'min="30" max="140"')}
        </div>
        <div class="row wrap" style="gap:24px">
          ${field(ch, "long.captions", "Legenda no vídeo longo", "switch")}
          ${field(ch, "long.chapters", "Capítulos na descrição", "switch")}
        </div>
        <p class="small faint">Estimativa: ${Math.ceil(((ch.long?.target_minutes || 8) * 60) / (ch.long?.seconds_per_image || 15))} imagens e ~${Math.round((ch.long?.target_minutes || 8) * 900).toLocaleString()} caracteres de narração por vídeo.</p></div>`)}

      ${section("Cortes", "Transforma um vídeo longo (link ou arquivo) em vários shorts: transcreve, a IA escolhe os melhores trechos e cada corte é reenquadrado para 9:16.", `<div class="card-body stack">
        <div class="fields">
          ${field(ch, "clips.count", "Cortes por vídeo", "number", 'min="1" max="20"')}
          ${field(ch, "clips.min_seconds", "Duração mínima (s)", "number", 'min="5" max="170"')}
          ${field(ch, "clips.max_seconds", "Duração máxima (s)", "number", 'min="10" max="180"')}
          ${select(ch, "clips.reframe", "Enquadramento", [["face", "Seguir o rosto"], ["blur", "Fundo desfocado"], ["center", "Recorte central"]], "Sem rosto, o modo rosto cai para desfocado")}
        </div>
        <div class="row wrap" style="gap:24px">
          ${field(ch, "clips.captions", "Legenda nos cortes", "switch")}
          ${field(ch, "clips.cover_from_frame", "Capa com frame do próprio corte", "switch")}
        </div></div>`)}

      ${section("Capa", "Imagem de capa com título curto e chamativo. Ela entra nos primeiros frames do vídeo (o YouTube usa esse frame no feed de Shorts) e vai como thumbnail no upload automático (exige canal verificado por telefone).", `<div class="card-body stack">
        ${field(ch, "cover.enabled", "Gerar capa", "switch")}
        <div class="fields">
          ${select(ch, "cover.source", "Fundo", [["ai", "Imagem própria (IA)"], ["scene", "Imagem de uma cena"]])}
          ${field(ch, "cover.scene", "Cena usada", "number", 'min="1" max="15"', "Quando o fundo é uma cena")}
          ${select(ch, "cover.position", "Posição do texto", [["top", "Topo"], ["center", "Centro"], ["bottom", "Embaixo"]])}
          ${field(ch, "cover.darken", "Escurecer fundo", "range", "0,0.7,0.05")}
        </div>
        <div class="fields">
          ${select(ch, "cover.font", "Fonte", META.fonts.map((f) => [f, f]))}
          ${field(ch, "cover.font_size", "Tamanho", "number", 'min="0" max="260"', "0 = automático")}
          <div class="row" style="gap:16px">${field(ch, "cover.text_color", "Texto", "color")}${field(ch, "cover.highlight_color", "Destaque", "color")}</div>
          ${field(ch, "cover.in_video_seconds", "Tempo no vídeo (s)", "number", 'step="0.05" min="0.05" max="2"')}
        </div>
        <div class="row wrap" style="gap:24px">
          ${field(ch, "cover.text_enabled", "Texto na capa", "switch")}
          ${field(ch, "cover.in_video", "Capa no início do vídeo", "switch")}
          ${field(ch, "cover.upload_thumbnail", "Enviar como thumbnail", "switch")}
        </div></div>`)}

      ${section("Revisão e publicação", "Com a aprovação ligada, o short espera você conferir a timeline antes de renderizar e aprovar antes de publicar. Até o Google auditar o app, uploads pela API ficam privados.", `<div class="card-body stack">
        <div class="row wrap" style="gap:24px">
          ${field(ch, "review.approve_before_render", "Pausar antes do render para conferir a timeline", "switch")}
          ${field(ch, "review.require_approval", "Exigir minha aprovação antes de publicar", "switch")}
        </div>
        <div class="fields">
          ${select(ch, "upload.mode", "Publicação", [["manual", "Manual: eu baixo e posto"], ["draft", "Rascunho no YouTube (privado)"], ["auto", "Automática: API do YouTube"]])}
          ${select(ch, "upload.privacy", "Visibilidade", [["private", "Privado"], ["unlisted", "Não listado"], ["public", "Público"]])}
          ${select(ch, "upload.category_id", "Categoria", [["24", "Entretenimento"], ["28", "Ciência e tecnologia"], ["22", "Pessoas e blogs"], ["27", "Educação"], ["20", "Jogos"], ["1", "Filmes e animação"]])}
        </div>
        <div class="voice-current"><span class="status-dot ${ytc.connected ? "on" : "off"}"></span>
          <div class="grow"><div style="font-weight:550">${ytc.connected ? `YouTube conectado${ytc.channel_title ? `: ${esc(ytc.channel_title)}` : ""}` : "YouTube não conectado"}</div>
            <div class="small faint">${!ytc.client_secret ? "Falta o client_secret.json (veja Provedores)" : ytc.connected ? (ytc.analytics ? "Upload automático e Analytics liberados" : "Reconecte para liberar o Analytics") : "Conecte para habilitar o upload automático e o Analytics"}</div></div>
          ${ytc.connected ? `<button class="btn sm" id="ytTest">${icon("refresh", "sm")}Testar v3</button><button class="btn sm danger" id="ytOff">Desconectar</button>` : ""}
          <a class="btn sm ${ytc.connected ? "" : "primary"}" href="/api/youtube/connect/${id}">${icon("yt", "sm")}${ytc.connected ? "Reconectar" : "Conectar"}</a></div>

        <div class="voice-current" style="margin-top:12px"><span class="status-dot ${ttc.connected ? "on" : "off"}"></span>
          <div class="grow"><div style="font-weight:550">${ttc.connected ? `TikTok conectado${ttc.display_name ? `: @${esc(ttc.username || ttc.display_name)}` : ""}` : "TikTok não conectado"}</div>
            <div class="small faint">${!ttc.client_configured ? "Falta o Client Key / Secret (veja Provedores)" : ttc.connected ? "Upload automático e rascunhos no TikTok liberados" : "Conecte para habilitar o envio direto para o TikTok"}</div></div>
          ${ttc.connected ? `<button class="btn sm" id="ttTest">${icon("refresh", "sm")}Testar v2</button><button class="btn sm danger" id="ttOff">Desconectar</button>` : ""}
          <a class="btn sm ${ttc.connected ? "" : "primary"}" href="/api/tiktok/connect/${id}">${icon("play", "sm")}${ttc.connected ? "Reconectar" : "Conectar TikTok"}</a></div>
        <div class="fields" style="margin-top:8px">
          ${select(ch, "upload.tiktok_privacy", "Visibilidade no TikTok", [["SELF_ONLY", "Privado / Rascunho (Recomendado)"], ["MUTUAL_FOLLOW_FRIENDS", "Amigos mútuos"], ["PUBLIC_TO_EVERYONE", "Público"]])}
        </div>

        <div class="voice-current" style="margin-top:12px"><span class="status-dot ${igc.configured ? "on" : "off"}"></span>
          <div class="grow"><div style="font-weight:550">${igc.configured ? "Instagram Reels configurado" : "Instagram Reels não configurado"}</div>
            <div class="small faint">${igc.configured ? "Upload de Reels via Meta Graph API v21.0 liberado" : "Configure o Access Token e Account ID do Instagram em Provedores"}</div></div>
          ${igc.configured ? `<button class="btn sm" id="igTest">${icon("refresh", "sm")}Testar Graph v21</button>` : ""}
        </div>
        <div class="fields" style="margin-top:8px">
          ${field(ch, "upload.publish_to_instagram", "Publicar Reels automaticamente junto com o upload", "switch")}
        </div></div>`)}

      ${section("Agenda", "Cria shorts automaticamente nos horários definidos, todos os dias.", `<div class="card-body stack">
        ${field(ch, "schedule.enabled", "Agenda automática ligada", "switch")}
        <label class="field" style="max-width:360px"><span>Horários</span><input data-p="ch:schedule.times" data-t="csv" value="${esc((ch.schedule.times || []).join(", "))}"><span class="hint">HH:MM separados por vírgula, ex.: 10:00, 19:00</span></label></div>`)}
    </div>
    ${saveBar()}`;

  bindFields(app, id, (p) => { if (p.endsWith("provider")) pageChannels(id); });
  bindSaveBar(() => pageChannels(id));
  $$("[data-tab]").forEach((b) => b.onclick = () => { location.hash = `#canais/${b.dataset.tab}`; });
  $("#addCh").onclick = () => {
    const name = prompt("Nome do novo canal:");
    if (name) act(async () => { const r = await api("/api/channels", { method: "POST", body: { name } }); CFG = await api("/api/config"); renderSidebar(); location.hash = `#canais/${r.id}`; }, "Canal criado");
  };
  $("#delCh").onclick = () => confirm(`Remover o canal ${ch.name}? Os shorts já feitos continuam.`) && act(async () => {
    await api(`/api/channels/${id}`, { method: "DELETE" }); CFG = await api("/api/config"); channelTab = null; renderSidebar(); location.hash = "#canais";
  }, "Canal removido");
  learnBox(id, $("#learnBox"));
  $("#ytOff") && ($("#ytOff").onclick = () => act(async () => { await api(`/api/youtube/${id}`, { method: "DELETE" }); pageChannels(id); }, "YouTube desconectado"));
  $("#ttOff") && ($("#ttOff").onclick = () => act(async () => { await api(`/api/tiktok/${id}`, { method: "DELETE" }); pageChannels(id); }, "TikTok desconectado"));
  $("#ytTest") && ($("#ytTest").onclick = async () => {
    const b = $("#ytTest");
    b.disabled = true;
    b.textContent = "Testando v3...";
    try {
      const res = await api(`/api/diagnostics?channel_id=${id}`);
      const info = res.youtube?.[id];
      if (info?.status === "ok") {
        toast(`YouTube Data API v3 OK! Respondendo em ${info.latency_ms}ms (${info.channel_title})`);
      } else {
        toast(`Erro no YouTube: ${info?.error || "Desconectado"}`, true);
      }
    } catch (e) {
      toast(`Falha ao testar YouTube: ${e.message}`, true);
    } finally {
      b.disabled = false;
      b.innerHTML = `${icon("refresh", "sm")}Testar v3`;
    }
  });
  $("#ttTest") && ($("#ttTest").onclick = async () => {
    const b = $("#ttTest");
    b.disabled = true;
    b.textContent = "Testando v2...";
    try {
      const res = await api(`/api/diagnostics?channel_id=${id}`);
      const info = res.tiktok?.[id];
      if (info?.status === "ok") {
        toast(`TikTok API v2 OK! Respondendo em ${info.latency_ms}ms (@${info.username || info.display_name})`);
      } else {
        toast(`Erro no TikTok: ${info?.error || "Desconectado"}`, true);
      }
    } catch (e) {
      toast(`Falha ao testar TikTok: ${e.message}`, true);
    } finally {
      b.disabled = false;
      b.innerHTML = `${icon("refresh", "sm")}Testar v2`;
    }
  });
  $("#igTest") && ($("#igTest").onclick = async () => {
    const b = $("#igTest");
    b.disabled = true;
    b.textContent = "Testando Graph v21...";
    try {
      const res = await api(`/api/diagnostics?channel_id=${id}`);
      const info = res.instagram;
      if (info?.status === "ok") {
        toast(`Instagram Graph API v21 OK! Respondendo em ${info.latency_ms}ms (@${info.username || info.name || id})`);
      } else {
        toast(`Erro no Instagram: ${info?.error || "Desconectado"}`, true);
      }
    } catch (e) {
      toast(`Falha ao testar Instagram: ${e.message}`, true);
    } finally {
      b.disabled = false;
      b.innerHTML = `${icon("refresh", "sm")}Testar Graph v21`;
    }
  });
  $("#resetPrompts").onclick = () => act(async () => {
    for (const k of ["idea", "script", "long_script", "clip_select", "image_style"]) ch.prompts[k] = (await api(`/api/config/reset-prompt/${id}/${k}`, { method: "POST" })).value;
    markDirty();
    pageChannels(id);
  }, "Prompts padrão restaurados (salve para aplicar)");
  $("#preview").onclick = () => act(async () => {
    const b = $("#preview");
    b.disabled = true;
    try {
      const r = await api("/api/tts/preview", { method: "POST", body: { channel: id, opts: ch.models.narracao } });
      const a = $("#audio");
      a.src = URL.createObjectURL(await r.blob());
      a.hidden = false;
      a.play();
    } finally { b.disabled = false; }
  });
  $("#loadVoices") && ($("#loadVoices").onclick = () => act(async () => {
    const { voices } = await api("/api/elevenlabs/voices");
    $("#voices").innerHTML = `<div class="voices">${voices.map((v) => `<div class="voice ${v.voice_id === n.voice_id ? "sel" : ""}">
      <button class="btn icon sm" data-play="${esc(v.preview_url || "")}" ${v.preview_url ? "" : "disabled"} title="Ouvir amostra">${icon("play", "sm")}</button>
      <div class="grow" style="min-width:0"><div style="font-weight:550">${esc(v.name)}</div><div class="small faint ellipsis">${esc([v.category, v.description].filter(Boolean).join(" · "))}</div></div>
      <button class="btn sm ${v.voice_id === n.voice_id ? "" : "primary"}" data-pick="${esc(v.voice_id)}" data-name="${esc(v.name)}" ${v.voice_id === n.voice_id ? "disabled" : ""}>${v.voice_id === n.voice_id ? "Em uso" : "Usar"}</button></div>`).join("")}</div>`;
    $$("[data-play]", $("#voices")).forEach((b) => b.onclick = () => { const a = $("#audio"); a.src = b.dataset.play; a.hidden = false; a.play(); });
    $$("[data-pick]", $("#voices")).forEach((b) => b.onclick = () => { n.voice_id = b.dataset.pick; n.voice_name = b.dataset.name; markDirty(); pageChannels(id); });
  }));
}

// ------------------------------------------------------------------ provedores
function renderDiagnostics(data, container) {
  const yt = data.youtube || {};
  const tt = data.tiktok || {};
  const el = data.elevenlabs || {};
  const cli = data.cli || {};

  const ytItems = Object.entries(yt);
  const ttItems = Object.entries(tt);
  const igItems = Object.entries(data.instagram || {});

  container.innerHTML = `
    <div class="diag-panel">
      <div class="diag-head">
        <div>
          <h3 style="margin:0 0 4px;font-size:15px;display:flex;align-items:center;gap:8px">
            <svg class="i" style="color:var(--accent)"><use href="#i-cpu"/></svg>Saúde & Conexão das APIs em Tempo Real
          </h3>
          <span class="small faint">Última checagem: ${new Date(data.timestamp).toLocaleTimeString()} • Chamadas executadas diretamente nos servidores oficiais</span>
        </div>
        <button class="btn xs" id="diagClose">Fechar diagnóstico</button>
      </div>

      <div class="diag-grid">
        <!-- YouTube -->
        <div class="diag-card">
          <div class="diag-card-top">
            <span class="diag-card-title"><svg class="i" style="color:#ef4444"><use href="#i-yt"/></svg>YouTube Data API</span>
            <span class="diag-badge ${ytItems.some(([, r]) => r.status === 'ok') ? 'ok' : 'warn'}">v3 Oficial</span>
          </div>
          <div class="diag-card-desc">
            ${ytItems.length === 0 ? '<span class="faint">Nenhum canal configurado</span>' : ytItems.map(([cid, r]) => `
              <div class="diag-sub-item">
                <span style="display:flex;align-items:center;gap:6px">
                  <span class="status-dot ${r.status === 'ok' ? 'on' : r.status === 'disconnected' ? 'paused' : 'off'}"></span>
                  <b>${esc(r.channel_title || cid)}</b>
                </span>
                <span class="small mono ${r.status === 'ok' ? '' : 'faint'}">${r.status === 'ok' ? `${r.latency_ms} ms` : esc(r.error || r.status)}</span>
              </div>
            `).join('')}
          </div>
          <div class="diag-card-meta">
            <span>Status: ${ytItems.every(([, r]) => r.status === 'ok') ? '🟢 Todas contas ativas' : '🟡 Verifique as conexões'}</span>
            <span>Google Cloud</span>
          </div>
        </div>

        <!-- TikTok -->
        <div class="diag-card">
          <div class="diag-card-top">
            <span class="diag-card-title"><svg class="i" style="color:#06b6d4"><use href="#i-play"/></svg>TikTok Content Posting</span>
            <span class="diag-badge ${ttItems.some(([, r]) => r.status === 'ok') ? 'ok' : 'warn'}">v2 Oficial</span>
          </div>
          <div class="diag-card-desc">
            ${ttItems.length === 0 ? '<span class="faint">Nenhum canal configurado</span>' : ttItems.map(([cid, r]) => `
              <div class="diag-sub-item">
                <span style="display:flex;align-items:center;gap:6px">
                  <span class="status-dot ${r.status === 'ok' ? 'on' : r.status === 'disconnected' ? 'paused' : 'off'}"></span>
                  <b>${esc(r.display_name || r.username || cid)}</b>
                </span>
                <span class="small mono ${r.status === 'ok' ? '' : 'faint'}">${r.status === 'ok' ? `${r.latency_ms} ms` : esc(r.error || r.status)}</span>
              </div>
            `).join('')}
          </div>
          <div class="diag-card-meta">
            <span>Status: ${ttItems.every(([, r]) => r.status === 'ok') ? '🟢 Conectado' : ttItems.some(([, r]) => r.status === 'ok') ? '🟢 Parcial' : '🟡 Não conectado'}</span>
            <span>ByteDance</span>
          </div>
        </div>

        <!-- ElevenLabs -->
        <div class="diag-card">
          <div class="diag-card-top">
            <span class="diag-card-title"><svg class="i" style="color:#a855f7"><use href="#i-volume"/></svg>ElevenLabs TTS</span>
            <span class="diag-badge ${el.status === 'ok' ? 'ok' : 'err'}">v1 Oficial</span>
          </div>
          <div class="diag-card-desc">
            ${el.status === 'ok' ? `
              <div class="small">Plano: <b>${esc(el.tier)}</b></div>
              <div class="small faint">Cota: ${el.used?.toLocaleString()} / ${el.limit?.toLocaleString()} caracteres</div>
              <div class="small" style="color:var(--ok)">✓ Autenticação válida e ativa</div>
            ` : `
              <div class="small err">${esc(el.error || 'Não configurado')}</div>
            `}
          </div>
          <div class="diag-card-meta">
            <span>Latência: <b>${el.latency_ms ? `${el.latency_ms} ms` : '—'}</b></span>
            <span>api.elevenlabs.io</span>
          </div>
        </div>

        <!-- Instagram Reels -->
        <div class="diag-card">
          <div class="diag-card-top">
            <span class="diag-card-title"><svg class="i" style="color:#e1306c"><use href="#i-instagram"/></svg>Instagram Reels</span>
            <span class="diag-badge ${igItems.some(([, r]) => r.status === 'ok') ? 'ok' : 'warn'}">Graph v21</span>
          </div>
          <div class="diag-card-desc">
            ${igItems.length === 0 ? '<span class="faint">Nenhum canal configurado</span>' : igItems.map(([cid, r]) => `
              <div class="diag-sub-item">
                <span style="display:flex;align-items:center;gap:6px">
                  <span class="status-dot ${r.status === 'ok' ? 'on' : r.status === 'unconfigured' ? 'off' : 'paused'}"></span>
                  <b>${esc(r.username || r.name || cid)}</b>
                </span>
                <span class="small mono ${r.status === 'ok' ? '' : 'faint'}">${r.status === 'ok' ? `${r.latency_ms} ms` : esc(r.error || r.status)}</span>
              </div>
            `).join('')}
          </div>
          <div class="diag-card-meta">
            <span>Status: ${igItems.every(([, r]) => r.status === 'ok') ? '🟢 Conectado' : igItems.some(([, r]) => r.status === 'ok') ? '🟢 Parcial' : '🟡 Não configurado'}</span>
            <span>Meta Graph API</span>
          </div>
        </div>

        <!-- Notificações (Telegram & Discord) -->
        <div class="diag-card">
          <div class="diag-card-top">
            <span class="diag-card-title"><svg class="i" style="color:#38bdf8"><use href="#i-bell"/></svg>Notificações</span>
            <span class="diag-badge ${(data.notifications?.telegram || data.notifications?.discord) ? 'ok' : 'faint'}">Webhooks</span>
          </div>
          <div class="diag-card-desc">
            <div class="diag-sub-item">
              <span style="display:flex;align-items:center;gap:6px">
                <span class="status-dot ${data.notifications?.telegram ? 'on' : 'off'}"></span>
                <b>Telegram Bot</b>
              </span>
              <span class="small faint mono">${data.notifications?.telegram ? 'ativo' : 'inativo'}</span>
            </div>
            <div class="diag-sub-item">
              <span style="display:flex;align-items:center;gap:6px">
                <span class="status-dot ${data.notifications?.discord ? 'on' : 'off'}"></span>
                <b>Discord Webhook</b>
              </span>
              <span class="small faint mono">${data.notifications?.discord ? 'ativo' : 'inativo'}</span>
            </div>
          </div>
          <div class="diag-card-meta">
            <span>Alertas de revisão e publicação</span>
            <span>Push Webhooks</span>
          </div>
        </div>

        <!-- Motores e CLIs -->
        <div class="diag-card">
          <div class="diag-card-top">
            <span class="diag-card-title"><svg class="i"><use href="#i-cpu"/></svg>Motores Locais</span>
            <span class="diag-badge ok">CLI / PATH</span>
          </div>
          <div class="diag-card-desc">
            ${['ffmpeg', 'claude', 'codex', 'agy'].map((k) => `
              <div class="diag-sub-item">
                <span style="display:flex;align-items:center;gap:6px">
                  <span class="status-dot ${cli[k]?.status === 'ok' ? 'on' : 'off'}"></span>
                  <b>${k}</b>
                </span>
                <span class="small faint mono">${cli[k]?.status === 'ok' ? 'pronto' : 'ausente'}</span>
              </div>
            `).join('')}
          </div>
          <div class="diag-card-meta">
            <span>Render & IAs locais</span>
            <span>Sistema</span>
          </div>
        </div>
      </div>
    </div>`;

  const btnClose = $("#diagClose");
  if (btnClose) btnClose.onclick = () => { container.innerHTML = ''; };
}

async function pageProviders() {
  const app = $("#app");
  const [usage, yt, tt] = await Promise.all([
    api("/api/elevenlabs/usage").catch((e) => ({ error: e.message })),
    api("/api/youtube").catch(() => ({})),
    api("/api/tiktok").catch(() => ({})),
  ]);
  const hasSecret = Object.values(yt)[0]?.client_secret;
  const hasTikTokConfig = Boolean(CFG.tiktok?.client_key && CFG.tiktok?.client_secret);
  const cli = META.cli;
  const pct = usage.limit ? Math.min(100, Math.round((usage.used / usage.limit) * 100)) : 0;
  const CLIS = [
    ["claude", "Claude Code", "claude → /login"],
    ["codex", "Codex", "codex login"],
    ["agy", "Gemini / Antigravity", "agy (login na primeira execução)"],
    ["ffmpeg", "ffmpeg", "render do vídeo"],
  ];
  app.innerHTML = `
    <div class="page-head">
      <div class="grow">
        <h1>Provedores</h1>
        <p>Contas, chaves e limites de execução.</p>
      </div>
      <div>
        <button class="btn sm" id="btnDiagnose">${icon("refresh", "sm")}Diagnóstico das APIs</button>
      </div>
    </div>
    <div id="diagContainer"></div>
    <div class="settings">
      ${section("CLIs de IA", "As IAs usam o login OAuth da sua conta. Variáveis *_API_KEY são removidas do ambiente delas, então nunca há cobrança por API.", `
        <div class="cli-list">${CLIS.map(([k, name, how]) => `<div class="cli"><span class="status-dot ${cli[k] ? "on" : "off"}"></span>
          <b>${name}</b><span class="mono faint ellipsis">${esc(cli[k] || "não encontrado no PATH")}</span><span class="small faint">${esc(how)}</span></div>`).join("")}</div>
        <div class="card-body" style="border-top:1px solid var(--border)"><div class="fields">
          ${field(CFG, "providers.claude.bin", "Binário claude")}${field(CFG, "providers.codex.bin", "Binário codex")}${field(CFG, "providers.agy.bin", "Binário agy")}</div></div>`)}

      ${section("ElevenLabs", "Narração. Um short de 45s gasta cerca de 600 a 800 caracteres.", `<div class="card-body stack">
        ${field(CFG, "providers.elevenlabs.api_key", "API key", "password", 'autocomplete="off" placeholder="sk_…"', "Também pode vir da variável ELEVENLABS_API_KEY")}
        ${usage.error ? `<div class="banner err" style="margin:0"><span class="ic">${icon("alert")}</span><div class="small">${esc(usage.error)}</div></div>`
          : `<div><div class="row small"><span class="grow">Plano <b>${esc(usage.tier)}</b></span><span class="muted">${usage.used?.toLocaleString()} / ${usage.limit?.toLocaleString()} caracteres</span></div>
             <div class="meter"><div style="width:${pct}%"></div></div>
             ${usage.reset_unix ? `<div class="tiny faint" style="margin-top:6px">Renova em ${new Date(usage.reset_unix * 1000).toLocaleDateString()}</div>` : ""}</div>`}
      </div>`)}

      ${section("Transcrição", "Usada nos cortes. O Whisper roda na CPU, de graça; o Scribe do ElevenLabs é mais rápido, mas gasta créditos proporcionais à duração do vídeo.", `<div class="card-body"><div class="fields">
        ${select(CFG, "transcription.provider", "Provedor", [["whisper", "Whisper local (grátis)"], ["elevenlabs", "ElevenLabs Scribe"]])}
        ${field(CFG, "transcription.model", "Modelo do Whisper", "text", 'list="dl-whisper"', "small = equilíbrio; medium/large-v3 = mais preciso e lento")}
        ${select(CFG, "transcription.fallback_provider", "Reserva", [["", "Nenhuma"], ["elevenlabs", "ElevenLabs Scribe"], ["whisper", "Whisper local"]])}
        ${field(CFG, "transcription.language", "Idioma", "text", "", "pt, en, es… vazio = detectar")}
        <datalist id="dl-whisper">${(META.model_suggestions.whisper || []).map((m) => `<option value="${m}">`).join("")}</datalist>
      </div></div>`)}

      ${section("Execução", "Quantos shorts e imagens rodam ao mesmo tempo, e quanto tempo cada chamada pode levar.", `<div class="card-body"><div class="fields">
        ${field(CFG, "general.max_parallel_jobs", "Shorts em paralelo", "number", 'min="1" max="4"')}
        ${field(CFG, "general.image_concurrency", "Imagens em paralelo", "number", 'min="1" max="6"', "Por short")}
        ${field(CFG, "general.llm_timeout", "Limite do texto (s)", "number")}
        ${field(CFG, "general.image_timeout", "Limite por imagem (s)", "number")}</div></div>`)}

      ${section("YouTube", "Necessário só para o upload automático. Cada canal se conecta separadamente na aba Canais.", `<div class="card-body stack">
        <div class="voice-current"><span class="status-dot ${hasSecret ? "on" : "off"}"></span><div class="grow" style="font-weight:550">${hasSecret ? "Credencial OAuth encontrada" : "Credencial OAuth não encontrada"}</div></div>
        ${field(CFG, "youtube.client_secret_path", "Caminho do client_secret.json")}
        <ol class="steps-list">
          <li>Em console.cloud.google.com, crie um projeto e ative a <b>YouTube Data API v3</b>.</li>
          <li>Em <b>Google Auth Platform → Público-alvo</b>, clique em <b>Publicar app</b> (evita o login expirar a cada 7 dias).</li>
          <li>Em <b>Clientes</b>, crie um cliente OAuth do tipo <b>App para computador</b> e baixe o JSON para o caminho acima.</li>
          <li>Em <b>Canais</b>, clique em <b>Conectar</b> e escolha a conta e o canal certos. No aviso "app não verificado", vá em Avançado → Acessar.</li>
        </ol></div>`)}

      ${section("TikTok", "Publicação de Shorts e vídeos verticais via Content Posting API v2 do TikTok.", `
        <div class="card-body stack">
          <div class="voice-current">
            <span class="status-dot ${hasTikTokConfig ? "on" : "off"}"></span>
            <div class="grow" style="font-weight:550">${hasTikTokConfig ? "Credenciais do TikTok configuradas" : "Credenciais do TikTok não configuradas"}</div>
          </div>
          <div class="fields">
            ${field(CFG, "tiktok.client_key", "Client Key do TikTok")}
            ${field(CFG, "tiktok.client_secret", "Client Secret do TikTok", "password", 'autocomplete="off"')}
          </div>
          <ol class="steps-list">
            <li>Em <b>developers.tiktok.com</b>, crie um aplicativo.</li>
            <li>Adicione os produtos <b>TikTok Login Kit</b> e <b>Content Posting API</b>.</li>
            <li>Em <b>Redirect URI</b>, cadastre: <code>http://localhost:8765/api/tiktok/callback</code></li>
            <li>Copie o <b>Client Key</b> e <b>Client Secret</b> nos campos acima e salve.</li>
            <li>Na aba <b>Canais</b>, clique em <b>Conectar TikTok</b> para autorizar a conta do canal.</li>
          </ol>
        </div>`)}

      ${section("Instagram Reels", "Publicação de Reels via Meta Graph API v21.0 com upload binário resumível direto.", `
        <div class="card-body stack">
          <div class="voice-current">
            <span class="status-dot ${Boolean(CFG.instagram?.access_token && CFG.instagram?.account_id) ? "on" : "off"}"></span>
            <div class="grow" style="font-weight:550">${Boolean(CFG.instagram?.access_token && CFG.instagram?.account_id) ? "Instagram Reels configurado" : "Instagram Reels não configurado"}</div>
          </div>
          <div class="fields">
            ${field(CFG, "instagram.access_token", "Access Token (Long-Lived)", "password", 'autocomplete="off" placeholder="EAAB..."')}
            ${field(CFG, "instagram.account_id", "Instagram Business Account ID", "text", 'placeholder="178414..."')}
          </div>
          <ol class="steps-list">
            <li>Em <b>developers.facebook.com</b>, crie um app Empresarial e adicione a <b>Instagram Graph API</b>.</li>
            <li>Gere um token com <code>instagram_basic</code>, <code>instagram_content_publish</code> e converta para <b>Long-Lived Token</b> (válido por 60 dias).</li>
            <li>Obtenha o <b>Instagram Account ID</b> associado e preencha acima.</li>
          </ol>
        </div>`)}

      ${section("Notificações (Telegram & Discord)", "Receba avisos instantâneos quando um short estiver pronto para revisão ou for publicado.", `
        <div class="card-body stack">
          <div class="sub-head">Telegram Bot</div>
          <div class="row wrap" style="gap:24px">
            ${field(CFG, "notifications.telegram.enabled", "Ativar alertas no Telegram", "switch")}
          </div>
          <div class="fields">
            ${field(CFG, "notifications.telegram.bot_token", "Bot Token (do @BotFather)", "password", 'autocomplete="off" placeholder="123456:ABC-DEF..."')}
            ${field(CFG, "notifications.telegram.chat_id", "Chat ID", "text", 'placeholder="123456789 ou -100..."')}
          </div>
          <div><button class="btn sm" id="btnTestTg">${icon("bell", "sm")}Enviar teste no Telegram</button></div>

          <div class="sub-head" style="margin-top:16px">Discord Webhook</div>
          <div class="row wrap" style="gap:24px">
            ${field(CFG, "notifications.discord.enabled", "Ativar alertas no Discord", "switch")}
          </div>
          <div class="fields">
            ${field(CFG, "notifications.discord.webhook_url", "URL do Webhook do Discord", "password", 'autocomplete="off" placeholder="https://discord.com/api/webhooks/..."')}
          </div>
          <div><button class="btn sm" id="btnTestDc">${icon("bell", "sm")}Enviar teste no Discord</button></div>
        </div>`)}
    </div>
    ${saveBar()}`;
  bindFields(app);
  bindSaveBar(pageProviders);

  $("#btnTestTg") && ($("#btnTestTg").onclick = () => act(async () => {
    await api("/api/notifications/test", { method: "POST", body: { service: "telegram" } });
  }, "Mensagem de teste enviada ao Telegram!"));

  $("#btnTestDc") && ($("#btnTestDc").onclick = () => act(async () => {
    await api("/api/notifications/test", { method: "POST", body: { service: "discord" } });
  }, "Mensagem de teste enviada ao Discord!"));

  const diagContainer = $("#diagContainer");
  const btnDiagnose = $("#btnDiagnose");
  if (btnDiagnose) {
    btnDiagnose.onclick = async () => {
      btnDiagnose.disabled = true;
      btnDiagnose.innerHTML = `${icon("refresh", "sm")}Testando APIs...`;
      diagContainer.innerHTML = `
        <div class="diag-panel">
          <div class="row" style="gap:12px;color:var(--text-2);font-size:13px">
            <span class="status-dot paused"></span>
            <span>Enviando requisições em tempo real para YouTube Data API v3, TikTok API v2, ElevenLabs e CLIs...</span>
          </div>
        </div>`;
      try {
        const data = await api("/api/diagnostics");
        renderDiagnostics(data, diagContainer);
      } catch (e) {
        diagContainer.innerHTML = `<div class="banner err"><span class="ic">${icon("alert")}</span><div class="small">Falha no diagnóstico: ${esc(e.message)}</div></div>`;
      } finally {
        btnDiagnose.disabled = false;
        btnDiagnose.innerHTML = `${icon("refresh", "sm")}Diagnóstico das APIs`;
      }
    };
  }
}

// ------------------------------------------------------------------ início
(async () => {
  try {
    [META, CFG] = await Promise.all([api("/api/meta"), api("/api/config")]);
  } catch (e) {
    $("#app").innerHTML = `<div class="card empty-state"><div class="ic">${icon("alert", "lg")}</div><h3>Servidor indisponível</h3><p>${esc(e.message)}</p></div>`;
    return;
  }
  renderWorker();
  renderSidebar();
  route();
})();
