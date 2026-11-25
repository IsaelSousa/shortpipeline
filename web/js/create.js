// ShortPipeline — painel: diálogo de novo vídeo

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
