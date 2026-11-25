// ShortPipeline — painel: inicialização

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
