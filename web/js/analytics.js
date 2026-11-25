// ShortPipeline — painel: analytics do canal

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
