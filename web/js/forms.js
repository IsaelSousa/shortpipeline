// ShortPipeline — painel: campos de configuração

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
