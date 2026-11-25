// ShortPipeline — painel: provedores e diagnóstico

// ------------------------------------------------------------------ provedores
function renderDiagnostics(data, container) {
  const yt = data.youtube || {};
  const el = data.elevenlabs || {};
  const cli = data.cli || {};

  const ytItems = Object.entries(yt);
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
  const [usage, yt] = await Promise.all([
    api("/api/elevenlabs/usage").catch((e) => ({ error: e.message })),
    api("/api/youtube").catch(() => ({})),
  ]);
  const hasSecret = Object.values(yt)[0]?.client_secret;
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
            <span>Enviando requisições em tempo real para YouTube Data API v3, ElevenLabs e CLIs...</span>
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
