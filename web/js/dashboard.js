// ShortPipeline — painel: lista de jobs

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
