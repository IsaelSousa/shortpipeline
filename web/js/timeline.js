// ShortPipeline — painel: timeline de faixas antes do render

// cena selecionada na timeline; volta a 0 ao abrir outro job (pageJob)
let timelineScene = 0;

async function renderTimeline(body, job, load, initialScene = timelineScene) {
  stopTimelineAudio?.();
  body.innerHTML = `<div class="card-body"><div class="skeleton" style="height:260px"></div></div>`;
  const loading = body.firstElementChild;
  let tl;
  try {
    tl = await api(`/api/jobs/${job.id}/timeline`);
  } catch (e) {
    if (!loading.isConnected) return;
    body.innerHTML = emptyTab("alert", `Falha ao carregar timeline: ${e.message}`);
    return;
  }
  if (!loading.isConnected) return;

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
  let soloAudio = null;
  let soloUrl = null;
  let videoEl = $("#mainVideo");

  // se o player não carregar o arquivo (proxy, pedido parcial), baixa inteiro e toca da memória
  function trackAudio(url) {
    const a = new Audio(url);
    a.preload = "auto";
    a.addEventListener("error", async () => {
      try {
        const res = await fetch(url, { cache: "no-store" });
        if (res.ok) a.src = URL.createObjectURL(await res.blob());
        else console.error("Timeline: faixa não carregou", url, res.status);
      } catch (e) { console.error("Timeline: faixa não carregou", url, e); }
    }, { once: true });
    return a;
  }
  if (tl.audio?.narration_url) audioNarration = trackAudio(tl.audio.narration_url);
  if (tl.audio?.sfx_url) audioSfx = trackAudio(tl.audio.sfx_url);

  function cleanupAudio() {
    pausePlayback();
    if (audioNarration) { audioNarration.pause(); audioNarration = null; }
    if (audioSfx) { audioSfx.pause(); audioSfx = null; }
    if (playTimer) { cancelAnimationFrame(playTimer); playTimer = null; }
    if (stopTimelineAudio === cleanupAudio) stopTimelineAudio = null;
  }
  stopTimelineAudio = cleanupAudio;

  function stopSolo() {
    soloAudio?.pause();
    soloAudio = null;
    soloUrl = null;
  }

  function playSolo(url) {
    if (!url) return;
    const wasPlaying = soloUrl === url;
    pausePlayback();
    if (wasPlaying) return;
    soloUrl = url;
    const mine = () => soloUrl === url;

    // toca um endereço; resolve quando o som começa de fato. O Chrome às vezes rejeita o play() com AbortError
    // e toca mesmo assim, então só conta como falha um erro de carregamento, o bloqueio de som ou a demora.
    const attempt = (src) => new Promise((resolve, reject) => {
      soloAudio?.pause();
      const clip = new Audio(src);
      soloAudio = clip;
      let settled = false;
      const done = (fn, value) => { if (!settled) { settled = true; clearTimeout(timer); fn(value); } };
      const timer = setTimeout(() => {
        clip.pause();
        done(reject, new Error("o som não começou em 10 s"));
      }, 10000);
      clip.onended = () => { if (soloAudio === clip) stopSolo(); };
      clip.onplaying = () => done(resolve);
      clip.onerror = () => done(reject, clip.error || new Error("erro de mídia"));
      clip.play().catch((e) => { if (e?.name !== "AbortError") done(reject, e); });
    });
    const describe = (e) => {
      if (typeof MediaError !== "undefined" && e instanceof MediaError) {
        return `mídia ${e.code}${e.message ? `: ${e.message}` : ""}`;
      }
      return e?.name && e.name !== "Error" ? `${e.name}: ${e.message}` : (e?.message || String(e));
    };
    const pcm = url.includes("/timeline/audio/") ? `${url}${url.includes("?") ? "&" : "?"}pcm=true` : null;

    (async () => {
      const errors = [];
      try { await attempt(url); return; } catch (e) {
        if (!mine()) return;
        if (e?.name === "NotAllowedError") {
          stopSolo();
          toast("O navegador bloqueou o som desta página. Libere o som do site e clique de novo.", true);
          return;
        }
        errors.push(e);
      }
      // plano B: baixa o arquivo inteiro e toca da memória (contorna proxy e pedidos parciais);
      // se o formato não tocar, pede a versão em WAV
      for (const src of [url, pcm].filter(Boolean)) {
        let res;
        try { res = await fetch(src, { cache: "no-store" }); } catch (e) { errors.push(e); continue; }
        if (!mine()) return;
        if (res.status === 410) {
          stopSolo();
          toast("Este som mudou desde que você abriu a página. Recarreguei a timeline.", true);
          cleanupAudio();
          renderTimeline(body, job, load, timelineScene);
          return;
        }
        if (!res.ok) { errors.push(new Error(`HTTP ${res.status}`)); continue; }
        const blobUrl = URL.createObjectURL(await res.blob());
        if (!mine()) { URL.revokeObjectURL(blobUrl); return; }
        try { await attempt(blobUrl); return; } catch (e) {
          URL.revokeObjectURL(blobUrl);
          if (!mine()) return;
          errors.push(e);
        }
      }
      if (!mine()) return;
      stopSolo();
      console.error("Timeline: som não tocou", url, errors);
      toast(`Não foi possível ouvir este item (${errors.map(describe).join(" · ")}).`, true);
    })();
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
        <div id="tlLibSounds" class="stack" style="gap:6px;margin-top:10px" hidden></div>
        ${job.kind === "short" || job.kind === "long" ? `
        <form id="tlImportAudio" class="stack" style="gap:8px;margin-top:12px">
          <div class="fields">
            <label class="field"><span>Arquivo de áudio</span><input name="audio" type="file" accept=".mp3,.wav,.ogg,.opus,.flac,.m4a,.aac"></label>
            <label class="field"><span>Ou link direto HTTPS</span><input name="url" type="url" placeholder="https://…/som.mp3"></label>
            <label class="field"><span>Faixa</span><select name="track"><option value="events">Efeito sonoro</option><option value="beds">Ambiência em loop</option></select></label>
          </div>
          <div class="row wrap" style="justify-content:space-between;gap:8px">
            <span class="small muted">Até 25 MiB. Links precisam permitir download pelo navegador.</span>
            <button class="btn sm" type="submit">${icon("plus", "sm")}Importar áudio</button>
          </div>
        </form>` : ""}
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
        <div class="fields mixer-fields">
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
            ${tl.status?.is_rendered ? `<button class="btn sm" id="tlCheckRender">${icon("check", "sm")}Checar render</button>` : ""}
            <button class="btn sm" id="tlOpenAiBtn">${icon("wand", "sm")}Pedir correção</button>
            ${tl.status.is_waiting_render ? `<button class="btn sm primary" id="tlDirectRender">${icon("play", "sm")}Aprovar e Renderizar</button>` : ""}
            ${tl.status.is_rendered && !tl.status.is_waiting_render && !["running", "queued"].includes(job.status) ? `<button class="btn sm ${tl.status.needs_render ? "primary" : ""}" id="tlDirectRender">${icon("refresh", "sm")}Renderizar de novo</button>` : ""}
          </div>
        </div>
        ${tl.status.needs_render && !["running", "queued"].includes(job.status) ? `<p class="small" style="color:var(--warn);margin:8px 0 0">Você mudou a timeline depois do último render. As mudanças só entram no vídeo quando você clicar em <b>Renderizar de novo</b>.</p>` : ""}

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
              <div class="tl-playhead" id="tlPlayhead">
                <div class="tl-playhead-handle" id="tlPlayheadHandle" role="slider" tabindex="0"
                     aria-label="Posição na timeline" aria-valuemin="0" aria-valuemax="${tl.total_duration}"
                     aria-valuenow="0" title="Arraste para mover o cursor"></div>
              </div>
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

        <div class="card-body stack" id="tlQualityReport" hidden></div>
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
        <button type="button" class="tl-block tl-cap-blk" style="left:${left}px;width:${width}px" title="[${c.start.toFixed(1)}s - ${c.end.toFixed(1)}s] ${esc(c.text)}">
          <span class="ellipsis">${esc(c.text)}</span>
        </button>
      `;
    });
    trCaptions.innerHTML = capHtml;
    $$(".tl-cap-blk", trCaptions).forEach((block, index) => {
      block.onclick = () => {
        const caption = tl.captions[index];
        const scene = tl.scenes.findIndex((item) => item.start <= caption.start && caption.start <= item.end);
        if (scene < 0) return;
        selectScene(scene);
        seekTo(caption.start);
        const input = $("#tlInspNarration");
        if (!input || job.kind === "corte") return;
        input.focus();
        const start = input.value.toLocaleLowerCase().indexOf(caption.text.toLocaleLowerCase());
        if (start >= 0) input.setSelectionRange(start, start + caption.text.length);
      };
    });

    const trNarr = $("#tlTrackNarration");
    let narrHtml = "";
    tl.scenes.forEach((sc, i) => {
      const left = Math.round((sc.start + covSec) * pxPerSec);
      const width = Math.max(20, Math.round(sc.duration * pxPerSec));
      narrHtml += `
        <button type="button" class="tl-block tl-speech-blk" data-idx="${i}" style="left:${left}px;width:${width}px" title="${sc.audio_url ? "Ouvir" : "Selecionar"} narração da cena ${sc.scene_num}">
          <span class="ellipsis" style="max-width:85%">${esc(sc.narration)}</span>
          <div class="wave"><span></span><span></span><span></span></div>
        </button>
      `;
    });
    trNarr.innerHTML = narrHtml;

    // --- FAIXA DE EFEITOS (SFX) ---
    const hdrSfx = $("#tlHdrSfx");
    const trSfx = $("#tlTrackSfx");
    const sfxEvents = [...(tl.sound_events || [])].sort((a, b) => a.at - b.at);

    function formatEventLabel(ev) {
      const raw = (ev.label || ev.text || ev.sound || "Som").trim();
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
          const fullDesc = ev.label || ev.text || ev.sound || "Som";
          const scIdx = ev.scene ? ev.scene - 1 : -1;
          sfxHtml += `
            <button type="button" class="tl-sfx-pill tl-sfx-${ev.type || "sfx"}"
                 data-at="${ev.at}" data-scene="${scIdx}"
                 data-audio="${esc(ev.audio_url || "")}"
                 data-label="${esc(fullDesc)}" data-type="${ev.type || "sfx"}"
                 style="left:${left}px;top:${top}px;width:${width}px"
                 title="${ev.audio_url ? "Ouvir · " : ""}[${ev.at}s] ${esc(fullDesc)}">
              <span class="sfx-ic">${ic}</span>
              <span class="sfx-txt">${esc(label)}</span>
            </button>
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
            <button type="button" class="tl-bed-bar" data-start="${b.start}" data-scene="${scIdx}" data-sound="${esc(b.sound)}" data-audio="${esc(b.audio_url || "")}"
                 style="left:${left}px;top:${top}px;width:${width}px"
                 title="${b.audio_url ? "Ouvir · " : ""}Ambiente: ${esc(b.sound)} (${b.dur}s)">
              <span class="ellipsis">🌊 ${esc(b.sound)}</span>
            </button>
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
        if (el.classList.contains("tl-speech-blk")) playSolo(tl.scenes[idx].audio_url);
      };
    });

    function hideItemAction() {
      stopSolo();
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
          playSolo(el.dataset.audio);
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
          playSolo(el.dataset.audio);
        };
      });
    }
  }

  function selectScene(idx, clearAction = true) {
    if (idx < 0 || idx >= tl.scenes.length) return;
    selectedIdx = idx;
    timelineScene = idx;
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
    const direction = [
      ["Ver", sc.direction?.visual],
      ["Ouvir", sc.direction?.audio],
      ["Descobrir", sc.direction?.reveal],
    ].filter(([, value]) => typeof value === "string" && value.trim());

    insp.innerHTML = `
      <div class="tl-insp-preview">
        ${sc.media?.kind === "video" ? `<video src="${esc(sc.media.url)}" controls muted playsinline style="width:100%;max-height:240px"></video>`
          : sc.image_url ? `<a href="${sc.image_url}" target="_blank"><img src="${sc.image_url}" alt="Cena ${sc.scene_num}"></a>` : icon("image", "lg")}
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

        ${direction.length ? `
          <dl class="kv" aria-label="Direção da cena">
            ${direction.map(([label, value]) => `<dt>${label}</dt><dd>${esc(value)}</dd>`).join("")}
          </dl>` : ""}

        ${sc.original_image_url ? `
          <details class="tl-visual-tools">
            <summary>Imagem e animação</summary>
            <div class="stack" style="margin-top:10px">
              <form id="tlSceneMedia" class="stack">
                ${sc.media ? `<div class="row wrap" style="gap:8px">
                  <span class="small">${esc(sc.media.name)}${sc.media.credit ? ` · ${esc(sc.media.credit)}` : ""}</span>
                  ${/^https?:\/\//i.test(sc.media.source_url || "") ? `<a class="small" href="${esc(sc.media.source_url)}" target="_blank" rel="noopener noreferrer">Fonte</a>` : ""}
                  <button class="btn sm" type="button" id="tlRemoveMedia">Voltar à imagem gerada</button>
                </div>` : ""}
                <label class="field"><span>Foto, diagrama ou vídeo</span><input name="file" type="file" required accept=".jpg,.jpeg,.png,.webp,.mp4,.mov,.webm,.mkv"></label>
                <div class="fields two">
                  <label class="field"><span>Crédito</span><input name="credit" maxlength="240" value="${esc(sc.media?.credit || "")}"></label>
                  <label class="field"><span>Link da fonte</span><input name="source_url" type="url" maxlength="1000" value="${esc(sc.media?.source_url || "")}"></label>
                </div>
                <div class="row wrap" style="gap:8px">
                  <button class="btn sm" type="submit">Usar mídia na cena</button>
                  <span class="small muted">Até 100 MiB. Vídeos entram sem áudio.</span>
                </div>
              </form>
              <div class="row wrap" style="gap:8px">
                <button class="btn sm" id="tlUpscalePreview">Prévia Real-ESRGAN</button>
                ${sc.upscale_active ? `<button class="btn sm" id="tlUpscaleReset">Voltar à imagem original</button>` : ""}
              </div>
              <div id="tlUpscaleCompare" hidden></div>
              <form id="tlMotionForm" class="stack">
                <label class="field"><span>Motion Canvas</span>
                  <select name="template">
                    <option value="highlight">Imagem com destaque</option>
                    <option value="comparison">Comparação animada</option>
                    <option value="reveal">Revelação em close</option>
                  </select>
                </label>
                <div class="fields two">
                  <label class="field"><span id="tlMotionTitleLabel">Texto opcional</span><input name="title" maxlength="80" value="${esc(sc.motion?.title || "")}"></label>
                  <label class="field" id="tlMotionDetail"><span>Segundo valor</span><input name="detail" maxlength="80" value="${esc(sc.motion?.detail || "")}"></label>
                </div>
                <div class="fields two" id="tlMotionFocus">
                  <label class="field"><span>Foco horizontal</span><input type="range" name="focus_x" min="0" max="1" step="0.01" value="${sc.motion?.focus_x ?? 0.5}"></label>
                  <label class="field"><span>Foco vertical</span><input type="range" name="focus_y" min="0" max="1" step="0.01" value="${sc.motion?.focus_y ?? 0.5}"></label>
                </div>
                <div class="row wrap" style="gap:8px">
                  <button type="button" class="btn sm" id="tlMotionPreview">Prévia da animação</button>
                  <button class="btn sm primary" type="submit">Usar animação</button>
                  ${sc.motion ? `<button type="button" class="btn sm" id="tlMotionReset">Remover animação</button>` : ""}
                </div>
                <video class="tl-motion-preview" id="tlMotionVideo" controls muted playsinline hidden></video>
              </form>
              <p class="small muted">Refaça a partir de Render para aplicar ao vídeo final.</p>
            </div>
          </details>` : ""}

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
              <button class="btn sm" id="tlSaveNarration" ${sc.audio_url ? "" : "disabled"}>${icon("check", "sm")}Refazer voz da cena</button>
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
      const button = $("#tlSaveNarration");
      button.disabled = true;
      pausePlayback();
      act(async () => {
        await api(`/api/jobs/${job.id}/scenes/${sc.index}/narration`, { method: "PUT", body: {text} });
        await load(true);
      }, "Refazendo somente a voz desta cena").finally(() => { button.disabled = false; });
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
      $("#tlPlaySolo").onclick = () => playSolo(sc.audio_url);
    }

    const motionForm = $("#tlMotionForm");
    if (motionForm) {
      const base = `/api/jobs/${job.id}/scenes/${sc.index}`;
      const mediaForm = $("#tlSceneMedia");
      mediaForm.onsubmit = async (event) => {
        event.preventDefault();
        const button = mediaForm.querySelector('[type="submit"]');
        button.disabled = true;
        await act(async () => {
          await api(`${base}/media`, {method:"POST", body:new FormData(mediaForm)});
          if (mediaForm.isConnected) await renderTimeline(body, job, load, sc.index);
        }, "Mídia selecionada para o próximo render");
        button.disabled = false;
      };
      const removeMedia = $("#tlRemoveMedia");
      if (removeMedia) removeMedia.onclick = () => act(async () => {
        await api(`${base}/media`, {method:"DELETE"});
        if (mediaForm.isConnected) await renderTimeline(body, job, load, sc.index);
      }, "Imagem gerada selecionada");
      function saveVisuals(settings, message) {
        return act(async () => {
          await api(`${base}/visuals`, {method: "PUT", body: settings});
          if (motionForm.isConnected) await renderTimeline(body, job, load, sc.index);
        }, message);
      }
      const fields = motionForm.elements;
      fields.template.value = sc.motion?.template || "highlight";
      function updateMotionFields() {
        const comparison = fields.template.value === "comparison";
        $("#tlMotionTitleLabel").textContent = comparison ? "Primeiro valor" : "Texto opcional";
        $("#tlMotionDetail").hidden = !comparison;
        $("#tlMotionFocus").hidden = comparison;
        fields.title.required = fields.detail.required = comparison;
      }
      updateMotionFields();
      fields.template.onchange = updateMotionFields;
      const settings = () => ({
        template: fields.template.value, title: fields.title.value, detail: fields.detail.value,
        focus_x: Number(fields.focus_x.value), focus_y: Number(fields.focus_y.value),
      });
      motionForm.onsubmit = (e) => {
        e.preventDefault();
        saveVisuals({motion: settings()}, "Animação selecionada para o próximo render");
      };
      const motionReset = $("#tlMotionReset");
      if (motionReset) motionReset.onclick = () => saveVisuals({motion: null}, "Animação removida");
      const upscaleReset = $("#tlUpscaleReset");
      if (upscaleReset) upscaleReset.onclick = () => saveVisuals({upscale: false}, "Imagem original selecionada");

      const motionPreview = $("#tlMotionPreview"), video = $("#tlMotionVideo");
      motionPreview.onclick = async () => {
        if (!motionForm.reportValidity()) return;
        motionPreview.disabled = true;
        await act(async () => {
          const { url } = await api(`${base}/motion-preview`, {method: "POST", body: settings()});
          if (!video.isConnected) return;
          pausePlayback();
          video.src = url;
          video.hidden = false;
        });
        motionPreview.disabled = false;
      };
      const upscalePreview = $("#tlUpscalePreview"), compare = $("#tlUpscaleCompare");
      upscalePreview.onclick = async () => {
        upscalePreview.disabled = true;
        await act(async () => {
          const result = await api(`${base}/upscale-preview`, {method: "POST"});
          if (!compare.isConnected) return;
          compare.innerHTML = `<div class="tl-upscale-compare">
            <figure><a href="${esc(result.original)}" target="_blank"><img src="${esc(result.original)}" alt="Imagem original"></a><figcaption>Original</figcaption></figure>
            <figure><a href="${esc(result.url)}" target="_blank"><img src="${esc(result.url)}" alt="Imagem ampliada"></a><figcaption>Real-ESRGAN</figcaption></figure>
          </div><button class="btn sm primary" type="button">Usar imagem ampliada</button>`;
          compare.querySelector("button").onclick = () => saveVisuals({upscale: true}, "Imagem ampliada selecionada");
          compare.hidden = false;
        });
        upscalePreview.disabled = false;
      };
    }
  }

  function updatePlayhead() {
    const ph = $("#tlPlayhead");
    const tm = $("#tlTimer");
    if (ph) ph.style.left = `${Math.round(currentTime * pxPerSec)}px`;
    const handle = $("#tlPlayheadHandle");
    if (handle) {
      handle.setAttribute("aria-valuenow", currentTime.toFixed(2));
      handle.setAttribute("aria-valuetext", fmtTimeMs(currentTime));
    }
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
    stopSolo();
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
    stopSolo();
    isPlaying = false;
    if (playTimer) cancelAnimationFrame(playTimer);
    if ($("#tlPlayBtn")) $("#tlPlayBtn").innerHTML = icon("play", "sm");
    if (audioNarration) audioNarration.pause();
    if (audioSfx) audioSfx.pause();
    if (videoEl) videoEl.pause();
  }

  updateScale();
  selectScene(Math.min(initialScene, tl.scenes.length - 1));

  $("#tlPlayBtn").onclick = togglePlay;
  $("#tlStopBtn").onclick = () => { pausePlayback(); seekTo(0); };
  const checkRender = $("#tlCheckRender");
  if (checkRender) checkRender.onclick = async () => {
    checkRender.disabled = true;
    const box = $("#tlQualityReport");
    box.hidden = false;
    box.textContent = "Analisando áudio e imagem…";
    try {
      const report = await api(`/api/jobs/${job.id}/check-render`, {method: "POST"});
      if (!box.isConnected) return;
      const audio = report.lufs == null ? "" : ` · ${report.lufs} LUFS`;
      const peak = report.peak == null ? "" : ` · pico ${report.peak} dBFS`;
      box.innerHTML = `
        <strong>Checagem do render</strong>
        <div class="small muted">${report.width ?? "—"}×${report.height ?? "—"} · ${fmtTimeMs(report.duration)}${audio}${peak}</div>
        ${report.warnings.length ? report.warnings.map((item) => `
          <div class="row wrap" style="gap:8px">
            ${item.at == null ? "" : `<button class="btn sm" data-check-time="${item.at}">${fmtTimeMs(item.at)}</button>`}
            <span class="small">${esc(item.message)}</span>
          </div>`).join("") : `<span class="small muted">Nenhum alerta nos itens verificados.</span>`}`;
      $$("[data-check-time]", box).forEach((button) => {
        button.onclick = () => { pausePlayback(); seekTo(Number(button.dataset.checkTime)); };
      });
    } catch (error) {
      box.textContent = error.message;
    } finally {
      checkRender.disabled = false;
    }
  };

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

  const ruler = $("#tlRuler");
  const handle = $("#tlPlayheadHandle");
  const timeline = $("#tlInner");
  let drag = null;
  const pointerX = (event) => event.clientX - ruler.getBoundingClientRect().left;

  timeline.onpointerdown = (event) => {
    if (drag || event.button !== 0 || (event.target !== handle && !ruler.contains(event.target))) return;
    const fromHandle = event.target === handle;
    drag = { id: event.pointerId, offset: fromHandle ? pointerX(event) - currentTime * pxPerSec : 0 };
    timeline.setPointerCapture(event.pointerId);
    if (!fromHandle) seekTo(pointerX(event) / pxPerSec);
  };
  timeline.onpointermove = (event) => {
    if (drag?.id === event.pointerId) seekTo((pointerX(event) - drag.offset) / pxPerSec);
  };
  timeline.onpointerup = (event) => {
    if (drag?.id === event.pointerId) drag = null;
  };
  timeline.onlostpointercapture = timeline.onpointerup;
  handle.onkeydown = (event) => {
    const step = event.shiftKey ? 5 : 1;
    const positions = {
      ArrowLeft: currentTime - step, ArrowDown: currentTime - step,
      ArrowRight: currentTime + step, ArrowUp: currentTime + step,
      Home: 0, End: tl.total_duration,
    };
    if (!Object.hasOwn(positions, event.key)) return;
    event.preventDefault();
    seekTo(positions[event.key]);
  };

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

  const bindSfxButtons = (root) => $$("[data-sfx]", root).forEach((b) => {
    b.onclick = () => {
      const sfxType = b.dataset.sfx;
      cleanupAudio();
      act(async () => {
        await api(`/api/jobs/${job.id}/add-sfx`, { method: "POST", body: { at: currentTime, type: sfxType } });
        $("#tlSfxDrawer").hidden = true;
        await renderTimeline(body, job, load);
      }, `Efeito '${sfxType.replace(/^lib:/, "")}' adicionado aos ${currentTime.toFixed(1)}s`);
    };
  });
  bindSfxButtons($("#tlSfxDrawer") || document);

  // sons da sua biblioteca (data/sound-packs) para o estilo do vídeo
  const libBox = $("#tlLibSounds");
  if (libBox) {
    const style = job.data?.sound?.style || "";
    api(`/api/sound-library?style=${encodeURIComponent(style)}`).then(({ sounds }) => {
      if (!sounds.length || !libBox.isConnected) return;
      libBox.innerHTML = `<div class="row" style="gap:8px;align-items:center"><span class="small muted grow">Sua biblioteca · ${sounds.length} tipos</span>
        ${sounds.length > 12 ? `<input id="tlLibFilter" placeholder="Buscar som (ex.: door, glass)" style="max-width:220px">` : ""}</div>
        <div class="row wrap" id="tlLibList" style="gap:8px;max-height:150px;overflow-y:auto">${sounds.map((x) =>
        `<button class="btn sm" data-sfx="lib:${esc(x.name)}" data-name="${esc(x.name)}" title="${x.variants > 1 ? `${x.variants} variações, uma é sorteada` : "1 arquivo"}">${icon("volume", "sm")}${esc(x.name)}${x.variants > 1 ? ` <span class="faint">×${x.variants}</span>` : ""}</button>`).join("")}</div>`;
      libBox.hidden = false;
      bindSfxButtons(libBox);
      const filter = $("#tlLibFilter", libBox);
      if (filter) filter.oninput = () => {
        const q = filter.value.trim().toLowerCase();
        $$("#tlLibList [data-name]", libBox).forEach((b) => { b.hidden = q && !b.dataset.name.includes(q); });
      };
    }).catch(() => {});
  }

  const importAudio = $("#tlImportAudio");
  if (importAudio) {
    importAudio.onsubmit = async (event) => {
      event.preventDefault();
      const button = importAudio.querySelector('button[type="submit"]');
      const at = currentTime;
      const { audio, url, track } = importAudio.elements;
      button.disabled = true;
      try {
        let file = audio.files[0];
        const limit = 25 * 1024 * 1024;
        if (!file && url.value.trim()) {
          const source = new URL(url.value.trim());
          if (source.protocol !== "https:" || source.username || source.password) {
            throw new Error("Use um link HTTPS direto para um arquivo de áudio.");
          }
          const response = await fetch(source, {
            credentials: "omit", referrerPolicy: "no-referrer", signal: AbortSignal.timeout(45000),
          }).catch(() => { throw new Error("O navegador não conseguiu baixar o link. Baixe o áudio e selecione o arquivo."); });
          if (!response.ok || !response.body) throw new Error("Não foi possível baixar o áudio desse link.");
          const reader = response.body.getReader();
          const chunks = [];
          let size = 0;
          try {
            while (true) {
              const { value, done } = await reader.read();
              if (done) break;
              size += value.length;
              if (size > limit) {
                await reader.cancel();
                throw new Error("O áudio deve ter até 25 MiB.");
              }
              chunks.push(value);
            }
          } finally {
            reader.releaseLock();
          }
          const name = decodeURIComponent(source.pathname.split("/").pop() || "audio");
          file = new File(chunks, name);
        }
        if (!file?.size) throw new Error("Selecione um arquivo de áudio ou cole um link direto.");
        if (file.size > limit) throw new Error("O áudio deve ter até 25 MiB.");
        const data = new FormData();
        data.append("file", file);
        data.append("at", at);
        data.append("track", track.value);
        await api(`/api/jobs/${job.id}/import-audio`, { method: "POST", body: data });
        if (importAudio.isConnected) await renderTimeline(body, job, load);
        toast("Áudio importado na timeline");
      } catch (error) {
        toast(error.message, true);
      } finally {
        button.disabled = false;
      }
    };
  }

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
