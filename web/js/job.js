// ShortPipeline — painel: página do job

const emptyTab = (ic, msg) => `<div class="empty-state"><div class="ic">${icon(ic, "lg")}</div><p>${esc(msg)}</p></div>`;

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
  timelineScene = 0;
  const TYPING = ["apTitle", "apDesc", "apWhen", "apMode", "covText", "clipStart", "clipEnd", "tlInspNarration", "clipFrameX", "clipFrameY"];

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
    const stageReview = job.status === "waiting_approval" && job.stages[job.stage]?.status === "review_pending";
    const stageReviewTab = {roteiro:"roteiro", imagens:"cenas", capa:"capa", transcricao:"transcricao", recorte:"corte",
      narracao:"timeline", som:"timeline", legendas:"timeline", render:"timeline"}[job.stage];
    const videoPath = isFonte ? relPath(job, d.source?.path)
      : stageReview && job.stage === "recorte" && d.reframed ? "reframed.mp4" : (d.video ? "final.mp4" : null);
    const video = videoPath ? fileUrl(job, videoPath) : null;
    const firstPending = order.find((s) => job.stages[s].status !== "done") || order[0];
    const title = script.title || d.source?.title || job.topic || "Novo";
    const tabs = tabsFor(kind);
    if (!tab || !tabs.some(([k]) => k === tab)) {
      const suggested = stageReview ? stageReviewTab : job.status === "waiting_approval" && job.stage === "render" ? "timeline" : null;
      tab = tabs.some(([key]) => key === suggested) ? suggested : tabs[0][0];
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

    stopTimelineAudio?.();
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
      ${stageReview ? `<section class="card stack" style="margin-top:16px;padding:16px">
        <h2>Revisar ${esc(META.stage_labels[job.stage])}</h2>
        <div class="row wrap" style="gap:8px">
          ${tabs.some(([key]) => key === stageReviewTab) ? '<button class="btn" id="viewStageReview">Ver resultado</button>' : ""}
          <button class="btn primary" id="approveStage">Aprovar e continuar</button>
        </div></section>`
        : job.status === "waiting_approval" ? (job.stage === "ideia" ? ideaApprovalCard(job) : job.stage === "selecao" ? clipApprovalCard(job) : job.stage === "render" ? renderApproveCard(job) : approveCard(script, ch)) : ""}

      <div class="detail-grid ${wide ? "wide" : ""}">
        <div class="phone">
          <div class="frame">${video
            ? `<video src="${video}?v=${job.stages[videoPath === "reframed.mp4" ? "recorte" : "render"]?.ended || ""}" controls playsinline preload="metadata" id="mainVideo"></video>`
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
    $("#btnPublishIg") && ($("#btnPublishIg").onclick = () => act(async () => {
      await api(`/api/jobs/${id}/publish-instagram`, { method: "POST", body: {} });
      load(true);
    }, "Enviando vídeo para o Instagram Reels"));
    if (stageReview) {
      const view = $("#viewStageReview");
      if (view) view.onclick = () => { tab = stageReviewTab; renderTab(); $("#tabBody").scrollIntoView({block:"nearest"}); };
      $("#approveStage").onclick = () => act(async () => {
        await api(`/api/jobs/${id}/approve-stage`, {method:"POST", body:{stage:job.stage}});
        await load(true);
      }, "Revisão aprovada");
    } else if (job.status === "waiting_approval" && job.stage === "ideia") {
      const form = $("#ideaApproval");
      const options = job.data.idea_options || [];
      if (form) {
        form.onchange = (event) => {
          if (event.target.name === "candidate") form.elements.topic.value = options[Number(event.target.value)].topic;
        };
        form.onsubmit = (event) => {
          event.preventDefault();
          act(async () => {
            await api(`/api/jobs/${id}/approve-idea`, {method:"POST", body:{
              index: Number(form.elements.candidate.value), topic: form.elements.topic.value,
            }});
            await load(true);
          }, "Pauta aprovada");
        };
      }
      $("#ideaRetry").onclick = () => act(async () => {
        await api(`/api/jobs/${id}/retry`, {method:"POST", body:{from_stage:"ideia"}});
        await load(true);
      }, "Gerando novas candidatas");
    } else if (job.status === "waiting_approval" && job.stage === "selecao") {
      const form = $("#clipApproval");
      form.onsubmit = (event) => {
        event.preventDefault();
        const indices = new FormData(form).getAll("candidate").map(Number);
        act(async () => {
          await api(`/api/jobs/${id}/approve-clips`, {method:"POST", body:{indices}});
          await load(true);
        }, "Cortes aprovados");
      };
      $("#clipRetry").onclick = () => act(async () => {
        await api(`/api/jobs/${id}/retry`, {method:"POST", body:{from_stage:"selecao"}});
        await load(true);
      }, "Buscando outros cortes");
      $$("[data-clip-context]", form).forEach((button) => bindClipContext(button, Number(button.dataset.clipContext)));
    } else if (job.status === "waiting_approval") bindApprove();
    $$(".tabs-line button").forEach((b) => b.onclick = () => { tab = b.dataset.tab; renderTab(); });
    renderTab();
  }
  function renderTab() {
    stopTimelineAudio?.();
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
      const framing = cl.framing || {};
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
            <label class="field"><span>Enquadramento</span><select id="clipFrameMode">
              ${[["channel","Padrão do canal"],["face","Seguir rosto"],["blur","Fundo desfocado"],["center","Centro"],["manual","Manual"]]
                .map(([mode,label]) => `<option value="${mode}" ${mode === (framing.mode || "channel") ? "selected" : ""}>${label}</option>`).join("")}
            </select></label>
            <button class="btn" id="clipApply">${icon("scissors")}Aplicar e refazer</button>
          </div>
          <div class="fields two" id="clipFrameControls" hidden>
            <label class="field"><span>Posição horizontal</span><input type="range" id="clipFrameX" min="0" max="1" step="0.01" value="${framing.x ?? 0.5}"></label>
            <label class="field"><span>Posição vertical</span><input type="range" id="clipFrameY" min="0" max="1" step="0.01" value="${framing.y ?? 0.5}"></label>
          </div>
          <div class="clip-context stack">
            <div><button class="btn sm" id="clipContext">Ouvir e ver com contexto</button></div>
            <div class="clip-source-preview" hidden>
              <video controls playsinline preload="metadata"></video>
              <div class="clip-crop-guide" hidden></div>
            </div>
            <span class="small muted" data-context-times></span>
          </div>
        </div>
        <div style="border-top:1px solid var(--border);padding-top:16px"><h3 style="font-size:14px;margin-bottom:8px">Fala do corte</h3><p style="line-height:1.65">${esc(text || "—")}</p></div>
      </div>`;
      const frameMode = $("#clipFrameMode"), x = $("#clipFrameX"), y = $("#clipFrameY");
      const preview = $(".clip-source-preview", body), video = $("video", preview), guide = $(".clip-crop-guide", preview);
      function updateCrop() {
        const manual = frameMode.value === "manual";
        $("#clipFrameControls").hidden = !manual;
        guide.hidden = !manual || !video.videoWidth;
        if (!video.videoWidth) return;
        preview.style.maxWidth = `${320 * video.videoWidth / video.videoHeight}px`;
        const width = Math.min(1, video.videoHeight * 9 / 16 / video.videoWidth);
        const height = Math.min(1, video.videoWidth * 16 / 9 / video.videoHeight);
        guide.style.width = `${width * 100}%`;
        guide.style.height = `${height * 100}%`;
        guide.style.left = `${(1 - width) * Number(x.value) * 100}%`;
        guide.style.top = `${(1 - height) * Number(y.value) * 100}%`;
      }
      frameMode.onchange = x.oninput = y.oninput = video.onloadedmetadata = updateCrop;
      updateCrop();
      bindClipContext($("#clipContext"));
      $("#clipApply").onclick = () => act(async () => {
        await api(`/api/jobs/${id}/clip`, { method: "PUT", body: {
          start: +$("#clipStart").value, end: +$("#clipEnd").value,
          framing: {mode: frameMode.value, x: +x.value, y: +y.value},
        } });
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
        ${script.music ? `<dt>Música</dt><dd>${icon("volume", "sm")} ${esc(script.music)} <span class="muted small">(escolhida pelo roteiro)</span></dd>` : ""}
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

  function bindClipContext(button, index) {
    button.onclick = async () => {
      const section = button.closest(".clip-context");
      const preview = $(".clip-source-preview", section), video = $("video", preview);
      const times = $("[data-context-times]", section);
      button.disabled = true;
      await act(async () => {
        const suffix = index == null ? "" : `?index=${index}`;
        const result = await api(`/api/jobs/${id}/clip-context${suffix}`, {method:"POST"});
        if (!section.isConnected) return;
        video.src = result.url;
        preview.hidden = false;
        times.textContent = `Contexto na fonte: ${fmtTimeMs(result.start)}–${fmtTimeMs(result.end)}`;
      });
      button.disabled = false;
    };
  }

  function clipApprovalCard(job) {
    return `<section class="card stack" style="margin-top:16px;padding:16px">
      <h2>Revisar cortes propostos</h2>
      <form id="clipApproval" class="stack">
        <div class="idea-options">
          ${(job.data.clip_candidates || []).map((clip, index) => `<div class="clip-context clip-candidate stack">
            <label class="row" style="gap:8px"><input type="checkbox" name="candidate" value="${index}" checked>
              <strong>${esc(clip.title || "Corte")}</strong></label>
            <div class="small muted">${fmtTimeMs(clip.start)}–${fmtTimeMs(clip.end)} · nota ${esc(clip.score ?? "—")}</div>
            ${clip.reason ? `<div class="small">${esc(clip.reason)}</div>` : ""}
            <div><button class="btn sm" type="button" data-clip-context="${index}">Ver com contexto</button></div>
            <div class="clip-source-preview" hidden><video controls playsinline preload="metadata"></video></div>
            <span class="small muted" data-context-times></span>
          </div>`).join("")}
        </div>
        <div class="row wrap" style="gap:8px">
          <button class="btn primary" type="submit">Criar cortes escolhidos</button>
          <button class="btn sm" id="clipRetry" type="button">Buscar outros cortes</button>
        </div>
      </form>
    </section>`;
  }

  function ideaApprovalCard(job) {
    const ideas = job.data.idea_options || [];
    return `<section class="card stack" style="margin-top:16px;padding:16px">
      <h2>Escolher pauta</h2>
      ${ideas.length ? `<form id="ideaApproval" class="stack">
        <div class="idea-options">
          ${ideas.map((idea, index) => `<label class="idea-option">
            <input type="radio" name="candidate" value="${index}" ${index === 0 ? "checked" : ""}>
            <span>
              <strong>${esc(idea.topic)}</strong>
              ${idea.reason ? `<span class="small" style="color:var(--accent)">Recomendada · ${esc(idea.reason)}</span>` : ""}
              ${[["Recorte", idea.angle], ["Primeiro quadro", idea.opening], ["Entrega", idea.payoff]].map(([label, text]) =>
                text ? `<span class="small muted">${label} · ${esc(text)}</span>` : "").join("")}
            </span>
          </label>`).join("")}
        </div>
        <label class="field"><span>Pauta para o roteiro</span><textarea name="topic" maxlength="900" required>${esc(ideas[0].topic)}</textarea></label>
        <div><button class="btn primary" type="submit">Aprovar e gerar roteiro</button></div>
      </form>` : `<p class="small muted">Nenhuma candidata disponível.</p>`}
      <div><button class="btn sm" id="ideaRetry">Gerar outras pautas</button></div>
    </section>`;
  }

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
    const igInfo = p.instagram ? `<div class="small muted" style="margin-top:4px"><b>Instagram:</b> <a href="${esc(p.instagram.permalink)}" target="_blank" rel="noreferrer">Ver Reel</a></div>` : (p.instagram_error ? `<div class="small" style="color:var(--err);margin-top:4px">Aviso Instagram: ${esc(p.instagram_error)}</div>` : "");
    const igBtn = `<button class="btn sm" id="btnPublishIg" title="Publicar no Instagram Reels">${icon("play", "sm")}Publicar no Reels</button>`;
    if (p.mode === "draft" && p.video_id) return `<div class="banner ok" style="margin-top:16px"><span class="ic">${icon("yt")}</span><div class="grow"><b>Rascunho no YouTube</b>
      <div class="small muted">Subiu como privado, sem avisar os inscritos. Termine e publique pelo YouTube Studio.</div>
      ${p.thumbnail_error ? `<div class="small" style="color:var(--err);margin-top:4px">Aviso na capa: ${esc(p.thumbnail_error)}</div>` : ""}
      ${igInfo}</div>
      <div class="row" style="gap:8px">
        ${igBtn}
        <button class="btn sm" id="reuploadThumb" title="Reenviar thumbnail para o YouTube">${icon("upload", "sm")}Reenviar capa</button>
        <a class="btn sm primary" href="${esc(p.studio_url || `https://studio.youtube.com/video/${p.video_id}/edit`)}" target="_blank" rel="noreferrer">${icon("ext", "sm")}Abrir no Studio</a>
      </div></div>`;
    if (p.mode === "auto" && p.url) return `<div class="banner ok" style="margin-top:16px"><span class="ic">${icon("yt")}</span><div class="grow"><b>Publicado no YouTube</b>
      <div class="small muted">${esc(p.privacy)}${p.publish_at ? ` · agendado para ${new Date(p.publish_at).toLocaleString()}` : ""}</div>
      ${p.thumbnail_error ? `<div class="small" style="color:var(--err);margin-top:4px">Aviso na capa: ${esc(p.thumbnail_error)}</div>` : ""}
      ${igInfo}</div>
      <div class="row" style="gap:8px">
        ${igBtn}
        <button class="btn sm" id="reuploadThumb" title="Reenviar thumbnail para o YouTube">${icon("upload", "sm")}Reenviar capa</button>
        <a class="btn sm" href="${esc(p.url)}" target="_blank" rel="noreferrer">${icon("ext", "sm")}Abrir</a>
      </div></div>`;
    if (p.mode === "manual") return `<div class="banner ok" style="margin-top:16px"><span class="ic">${icon("check")}</span><div class="grow"><b>Pronto para postar</b>
      <div class="small muted">Baixe o MP4 e use o título e a descrição do roteiro.</div>
      ${igInfo}</div>
      <div class="row" style="gap:8px">
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
