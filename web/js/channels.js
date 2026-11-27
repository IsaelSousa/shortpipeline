// ShortPipeline — painel: configuração dos canais

// ------------------------------------------------------------------ canais
async function pageChannels(tab) {
  const ids = chanIds();
  channelTab = tab && CFG.channels[tab] ? tab : (channelTab && CFG.channels[channelTab] ? channelTab : ids[0]);
  const yt = await api("/api/youtube").catch(() => ({}));
  const app = $("#app");
  const id = channelTab;
  const ch = CFG.channels[id];
  const n = ch.models.narracao;
  const ytc = yt[id] || {};
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

      ${section("Pauta", "Compare candidatas com as pautas recentes antes de gerar o roteiro.", `<div class="card-body stack">
        ${select(ch, "idea.source", "Origem", [["llm", "IA sugere e revisa candidatas"], ["rss", "Notícias de RSS (IA como reserva)"]])}
        <div class="fields two">
          <label class="field"><span>Temas a explorar</span><textarea data-p="ch:idea.explore" data-t="lines" placeholder="Um tema por linha">${esc((ch.idea.explore || []).join("\n"))}</textarea></label>
          <label class="field"><span>Temas a evitar</span><textarea data-p="ch:idea.avoid" data-t="lines" placeholder="Um tema ou nome por linha">${esc((ch.idea.avoid || []).join("\n"))}</textarea></label>
        </div>
        ${field(ch, "idea.tone", "Tom desejado", "textarea", 'placeholder="Ex.: curioso, direto e sem exagero"')}
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
          ${select(ch, "video.camera_motion", "Movimento de câmera", [
            ["", "Automático"],
            ["smooth_zoom", "Aproximação suave"],
            ["smooth_pan", "Panorâmica lateral suave"],
            ["smooth_tilt", "Panorâmica vertical suave"]
          ], "Aplicado às cenas geradas a partir de imagens")}
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
          <div class="grow sonic-logo-field">${field(ch, "creative.sonic_logo_prompt", "Som da assinatura (inglês)", "text", 'placeholder="Ex.: short bright two-note chime"', "Gerado uma vez no ElevenLabs e reaproveitado")}</div>
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
          ${field(ch, "creative.learn_topics", "Escolher temas pelo Analytics", "switch")}
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
          ${field(ch, "clips.media_cues", "Analisar mudanças de plano e picos de áudio", "switch")}
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

      ${section("Etapas para revisar", "Defina onde o pipeline deste canal deve esperar pela sua aprovação.", `<div class="card-body stack">
        <div class="row wrap" style="gap:24px">
          ${field(ch, "idea.require_approval", "Aprovar pauta antes do roteiro", "switch")}
          ${field(ch, "clips.review_selection", "Aprovar sugestões antes de criar cortes", "switch")}
          ${field(ch, "review.approve_before_render", "Pausar antes do render para conferir a timeline", "switch")}
          ${field(ch, "review.require_approval", "Exigir minha aprovação antes de publicar", "switch")}
        </div>
        <h3 style="font-size:13px">Revisar depois de concluir</h3>
        <div class="row wrap" style="gap:16px">
          ${(META.review_after_stages || []).map((stage) => field(ch, `review.after.${stage}`, META.stage_labels[stage], "switch")).join("")}
        </div>
        <p class="small muted">Cada trabalho pausa nas etapas marcadas que fazem parte do seu fluxo.</p>
      </div>`)}
      ${section("Publicação", "Configure como o ShortPipeline envia os vídeos deste canal.", `<div class="card-body stack">
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
