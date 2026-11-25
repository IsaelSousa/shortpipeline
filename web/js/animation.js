// ShortPipeline — painel: aba "Animação" do Short animado (preview, qualidade, pesquisa e storyboard)

async function renderAnimation(body, job, load) {
  const d = job.data || {};
  const qa = d.qa || {};
  const research = d.research || {};
  const waitingRender = job.status === "waiting_approval" && job.stage === "render";
  const kindTag = { verified: "verificado", calculation: "cálculo", estimate: "estimativa", illustrative: "ilustração" };
  const issues = [...(qa.auto || []).map((i) => ({ ...i, who: "checagem" })), ...(qa.ai || []).map((i) => ({ ...i, who: "IA" }))];
  body.innerHTML = `<div class="card-body stack">
    ${waitingRender ? `<div class="banner"><span class="ic">${icon("eye")}</span><div class="grow"><b>Confira o preview antes do render final</b>
      <div class="small muted">O render final usa a resolução cheia (1080×1920, 30 fps). Cenas que não mudaram vêm do cache.</div></div>
      <button class="btn primary" id="animRender">${icon("play", "sm")}Aprovar e renderizar</button></div>` : ""}
    ${d.preview && !d.video ? `<video src="${fileUrl(job, "preview.mp4")}?v=${job.stages.preview?.ended || ""}" controls playsinline preload="metadata" style="max-height:520px;align-self:center;border-radius:12px"></video>` : ""}
    ${qa.score != null || issues.length ? `<div class="sub-head">Qualidade${qa.score != null ? ` · nota ${esc(qa.score)}/10` : ""}</div>
      ${issues.length ? `<ul class="small" style="margin:0 0 0 18px">${issues.map((i) => `<li><b>${esc(i.scene)}</b> (${i.who}): ${esc(i.problem || "")}${i.fix ? ` <span class="muted">— ${esc(i.fix)}</span>` : ""}</li>`).join("")}</ul>` : `<p class="small muted">Nenhum problema encontrado.</p>`}
      ${(qa.fixed || []).length ? `<p class="small">Cenas refeitas automaticamente: ${qa.fixed.map(esc).join(", ")}</p>` : ""}` : ""}
    ${research.facts?.length ? `<div class="sub-head">Pesquisa</div>
      ${research.question ? `<p style="margin:0 0 6px;font-weight:550">${esc(research.question)}</p>` : ""}
      <ul class="small" style="margin:0 0 0 18px">${research.facts.map((f) => `<li><span class="tag">${esc(kindTag[f.kind] || f.kind)}</span> ${esc(f.claim)}${f.assumptions ? ` <span class="muted">(${esc(f.assumptions)})</span>` : ""}</li>`).join("")}</ul>
      ${research.safety ? `<p class="small" style="margin-top:6px">${icon("alert", "sm")} ${esc(research.safety)}</p>` : ""}` : ""}
    <div class="sub-head">Storyboard</div>
    <div id="animScenes"><div class="skeleton" style="height:60px"></div></div>
  </div>`;
  const btn = $("#animRender", body);
  if (btn) btn.onclick = () => act(async () => { await api(`/api/jobs/${job.id}/start-render`, { method: "POST" }); load(true); }, "Renderizando a animação");
  const box = $("#animScenes", body);
  if (!d.storyboard) { box.innerHTML = `<p class="small faint">O storyboard aparece depois da narração.</p>`; return; }
  let sb;
  try { sb = await (await fetch(fileUrl(job, "storyboard.json") + `?v=${d.storyboard.saved_at || ""}`)).json(); }
  catch (e) { box.innerHTML = `<p class="small muted">${esc(e.message)}</p>`; return; }
  if (!box.isConnected) return;
  const list = (els, key) => els.map((e) => `${esc(e[key])}${(e.actions || []).length ? ` (${e.actions.map((a) => esc(a.type)).join(", ")})` : ""}`).join(" · ");
  box.innerHTML = `<div class="stack" style="gap:8px">${sb.scenes.map((s, i) => `<div class="card" style="padding:10px 12px">
    <div class="row" style="gap:8px;align-items:center"><b>${i + 1}. ${esc(s.id)}</b><span class="small muted">${(s.end - s.start).toFixed(1)} s · ${esc(s.environment?.type || "city")} · entra ${esc(s.enter?.type || "cut")}</span></div>
    <div class="small" style="margin-top:4px">${esc(s.narration || "")}</div>
    <div class="small muted" style="margin-top:4px">
      ${(s.characters || []).length ? `Pessoas: ${list(s.characters, "ref")}<br>` : ""}
      ${(s.objects || []).length ? `Objetos: ${list(s.objects, "id")}<br>` : ""}
      Câmera: ${(s.camera?.moves || []).map((m) => esc(m.type + (m.target ? `→${m.target}` : ""))).join(", ") || "fixa"}
      ${(s.overlays || []).length ? `<br>Informativos: ${s.overlays.map((o) => esc(o.type + (o.text ? `: ${o.text}` : ""))).join(" · ")}` : ""}
      ${(s.effects || []).length ? `<br>Efeitos: ${s.effects.map((e) => esc(e.type)).join(", ")}` : ""}
    </div></div>`).join("")}</div>
    ${(sb.facts || []).some((f) => f.kind === "calculation") ? `<p class="small faint" style="margin-top:8px">Cálculos usados: ${sb.facts.filter((f) => f.kind === "calculation").map((f) => esc(f.claim)).join("; ")}</p>` : ""}`;
}
