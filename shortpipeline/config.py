"""Configuração editável pelo painel: data/config.json.

Na primeira execução o arquivo é criado com os padrões abaixo. Depois disso o
arquivo é a fonte da verdade; chaves novas dos padrões são mescladas quando
faltam (para atualizações do código não quebrarem configs antigas).
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SHORTPIPELINE_DATA", ROOT / "data"))
JOBS_DIR = DATA_DIR / "jobs"
CONFIG_PATH = DATA_DIR / "config.json"
ASSETS_DIR = ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
MUSIC_DIR = ASSETS_DIR / "music"
YOUTUBE_DIR = DATA_DIR / "youtube"

STAGES = ["ideia", "roteiro", "narracao", "imagens", "capa", "legendas", "som", "render", "revisao", "upload"]

# Cada tipo de job tem a sua sequência de etapas.
#   short: short gerado do zero (9:16)        long: vídeo longo gerado do zero (16:9)
#   fonte: vídeo longo que vira cortes        corte: um short recortado de uma fonte
KIND_STAGES = {
    "short": STAGES,
    "long": STAGES,
    "fonte": ["download", "transcricao", "selecao"],
    "corte": ["recorte", "capa", "legendas", "render", "revisao", "upload"],
}
KIND_LABELS = {"short": "Short", "long": "Vídeo longo", "fonte": "Fonte de cortes", "corte": "Corte"}
ALL_STAGES = list(dict.fromkeys(s for stages in KIND_STAGES.values() for s in stages))
REVIEW_AFTER_STAGES = ("roteiro", "narracao", "imagens", "capa", "legendas", "som",
                       "render", "download", "transcricao", "recorte")

STAGE_LABELS = {
    "ideia": "Ideia",
    "roteiro": "Roteiro",
    "critica": "Revisor de roteiro",
    "narracao": "Narração",
    "imagens": "Imagens",
    "capa": "Capa",
    "legendas": "Legendas",
    "som": "Som",
    "render": "Render",
    "revisao": "Revisão",
    "upload": "Publicação",
    "download": "Download",
    "transcricao": "Transcrição",
    "selecao": "Seleção",
    "recorte": "Recorte",
}


def stages_for(kind: str | None) -> list[str]:
    return KIND_STAGES.get(kind or "short", STAGES)


# Etapas que usam um modelo configurável e quais provedores cada uma aceita.
MODEL_STAGES = {
    "ideia": ["claude", "codex", "agy"],
    "roteiro": ["claude", "codex", "agy"],
    "critica": ["claude", "codex", "agy"],
    "selecao": ["claude", "codex", "agy"],
    "imagens": ["agy", "codex", "placeholder"],
    "narracao": ["elevenlabs", "edge"],
}

PROVIDER_LABELS = {
    "claude": "Claude (CLI claude)",
    "codex": "Codex (CLI codex)",
    "agy": "Gemini / Antigravity (CLI agy)",
    "placeholder": "Placeholder (teste, sem IA)",
    "edge": "Edge TTS (grátis)",
    "whisper": "Whisper local (grátis)",
    "elevenlabs": "ElevenLabs (API)",
}

# Sugestões exibidas no painel; qualquer nome de modelo aceito pela CLI funciona.
MODEL_SUGGESTIONS = {
    "claude": ["opus", "sonnet", "haiku", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
    "codex": ["", "gpt-5.5", "gpt-5.5-mini"],
    "agy": ["", "gemini-3.8-flash-high", "gemini-3.8-flash-medium", "claude-sonnet-4-6"],
    "placeholder": [""],
    "edge": ["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural"],
    "whisper": ["small", "medium", "large-v3", "base", "turbo"],
    "elevenlabs": ["eleven_multilingual_v2", "eleven_v3", "eleven_turbo_v2_5", "eleven_flash_v2_5"],
}

TERROR_SCRIPT_PROMPT = """Você escreve roteiros para o canal de YouTube Shorts "{channel}".
Nicho: {niche}

Escreva uma historinha de terror ORIGINAL, em {language}, sobre: {topic}

Regras:
- {scenes} cenas, narração total de uns {seconds} segundos (cerca de {words} palavras no total).
- A primeira frase é o gancho: precisa prender nos 2 primeiros segundos.
- Frases curtas, linguagem falada, tensão crescente e um final com reviravolta ou frase arrepiante.
- Nada de gore explícito; o medo vem do suspense.
- Para cada cena, escreva um image_prompt EM INGLÊS descrevendo uma imagem vertical cinematográfica
  daquela cena (personagens, ambiente, luz, enquadramento). Mantenha os personagens consistentes
  entre as cenas (descreva roupa/aparência igual sempre). Sem texto na imagem.

Responda SOMENTE com JSON válido, sem markdown, neste formato:
{{"title": "título curto e curioso (máx 70 caracteres, com #shorts no fim)",
  "description": "descrição de 2-3 linhas com hashtags",
  "tags": ["tag1", "tag2"],
  "cover_text": "texto da capa: 2 a 5 palavras de impacto, com a palavra mais forte entre [colchetes]",
  "cover_prompt": "english prompt for a striking cover image of the short",
  "scenes": [{{"narration": "texto narrado", "image_prompt": "english prompt"}}]}}"""

TECH_SCRIPT_PROMPT = """Você escreve roteiros para o canal de YouTube Shorts "{channel}".
Nicho: {niche}

Escreva um short em {language} sobre: {topic}

Regras:
- {scenes} cenas, narração total de uns {seconds} segundos (cerca de {words} palavras no total).
- A primeira frase é o gancho, com uma informação surpreendente.
- Tom animado e direto, como quem conta uma novidade para um amigo. Explique termos técnicos rápido.
- Termine logo depois da revelação principal, sem resumo e sem pedir comentário.
- Não invente números, datas ou especificações: se não tiver certeza, não cite.
- Para cada cena, escreva um image_prompt EM INGLÊS descrevendo uma imagem vertical ilustrativa
  (produto, conceito, metáfora visual). Sem logotipos de marcas e sem texto na imagem.

Responda SOMENTE com JSON válido, sem markdown, neste formato:
{{"title": "título curto e chamativo (máx 70 caracteres, com #shorts no fim)",
  "description": "descrição de 2-3 linhas com hashtags",
  "tags": ["tag1", "tag2"],
  "cover_text": "texto da capa: 2 a 5 palavras de impacto, com a palavra mais forte entre [colchetes]",
  "cover_prompt": "english prompt for a striking cover image of the short",
  "scenes": [{{"narration": "texto narrado", "image_prompt": "english prompt"}}]}}"""

IDEA_PROMPT = """Você sugere pautas para o canal de YouTube Shorts "{channel}".
Nicho: {niche}

Títulos já publicados (não repita nem faça variações próximas):
{history}

Busque assuntos concretos dentro do nicho, com uma descoberta que sustente o vídeo."""

LONG_PROMPT_TERROR = """Você escreve roteiros de VÍDEOS LONGOS para o canal de YouTube "{channel}".
Nicho: {niche}

Escreva uma história de terror ORIGINAL e longa, em {language}, sobre: {topic}

Regras:
- Cerca de {minutes} minutos de narração (umas {words} palavras no total), dividida em {scenes} cenas.
- Abertura forte nos primeiros 15 segundos, prometendo o que vem pela frente.
- Construa personagens, ambiente e tensão crescente, com 2 ou 3 viradas e um clímax marcante.
- Linguagem falada e envolvente; nada de gore explícito.
- Marque o início de cada parte da história com "chapter" (3 a 6 capítulos; a primeira cena sempre tem chapter).
- Para cada cena, um image_prompt EM INGLÊS para uma imagem horizontal cinematográfica, mantendo os
  personagens consistentes entre as cenas. Sem texto na imagem.

Responda SOMENTE com JSON válido, sem markdown:
{{"title": "título forte para vídeo longo (máx 90 caracteres, sem #shorts)",
  "description": "descrição de 3-5 linhas com hashtags",
  "tags": ["tag1", "tag2"],
  "cover_text": "2 a 4 palavras para a thumbnail, com a palavra mais forte entre [colchetes]",
  "cover_prompt": "english prompt for a striking horizontal thumbnail image",
  "scenes": [{{"chapter": "nome do capítulo (só quando começa um)", "narration": "texto", "image_prompt": "english"}}]}}"""

LONG_PROMPT_TECH = """Você escreve roteiros de VÍDEOS LONGOS para o canal de YouTube "{channel}".
Nicho: {niche}

Escreva um vídeo explicativo em {language} sobre: {topic}

Regras:
- Cerca de {minutes} minutos de narração (umas {words} palavras no total), dividida em {scenes} cenas.
- Abertura com gancho e promessa clara do que a pessoa vai entender até o fim.
- Organize em 3 a 6 capítulos ("chapter" na cena que começa cada um; a primeira cena sempre tem chapter).
- Tom animado e didático; explique termos técnicos; use exemplos e comparações.
- Não invente números, datas ou especificações: se não tiver certeza, não cite.
- Termine com um resumo e uma pergunta para os comentários.
- Para cada cena, um image_prompt EM INGLÊS para uma imagem horizontal ilustrativa. Sem logotipos e sem texto.

Responda SOMENTE com JSON válido, sem markdown:
{{"title": "título forte para vídeo longo (máx 90 caracteres, sem #shorts)",
  "description": "descrição de 3-5 linhas com hashtags",
  "tags": ["tag1", "tag2"],
  "cover_text": "2 a 4 palavras para a thumbnail, com a palavra mais forte entre [colchetes]",
  "cover_prompt": "english prompt for a striking horizontal thumbnail image",
  "scenes": [{{"chapter": "nome do capítulo (só quando começa um)", "narration": "texto", "image_prompt": "english"}}]}}"""

CRITIC_PROMPT = """Você é o editor-chefe do canal de YouTube "{channel}" (nicho: {niche}). Avalie o roteiro abaixo
como um especialista em retenção de {kind}. A maior perda de público acontece nos primeiros 3 a 10 segundos e no final.

Critérios (nota de 0 a 10 cada):
- hook: o primeiro quadro, a fala e o som previsto criam uma pergunta concreta logo no início?
- entrega: há uma primeira resposta, evidência ou pista cedo? O final entrega o que a abertura promete?
- ritmo: cada cena traz informação nova? Imagem e som ajudam a narrar em vez de repetir a fala?
- final: termina forte, logo após a revelação, sem resumo e sem pedir like/comentário?
- titulo: título curto, específico e curioso, no padrão do que funciona no canal?
{insights}
Roteiro (JSON):
{script}

Responda SOMENTE com JSON:
{{"score": nota geral 0-10 (inteiro), "scores": {{"hook": n, "entrega": n, "ritmo": n, "final": n, "titulo": n}},
 "issues": ["problema concreto 1", "..."],
 "script": null ou o roteiro REESCRITO}}

Se a nota geral for menor que {min_score}, devolva em "script" o roteiro reescrito corrigindo os problemas: mesmo JSON,
mesmos campos (title, description, tags, scenes com narration, image_prompt e os campos extras que existirem, cover_text,
cover_prompt, characters...), mesmo número aproximado de cenas e duração parecida. Em "sfx", a "word" precisa existir na
narração reescrita. Atualize direction (visual, audio, reveal), image_prompt e o plano sonoro das cenas que reescrever.
Em temas factuais, mantenha a distinção entre evidência e hipótese e preserve as fontes fornecidas. Se a nota for
{min_score} ou mais, "script" deve ser null.
"""

LEARN_PROMPT = """Você é analista de crescimento do canal de YouTube "{channel}" (nicho: {niche}).
Abaixo estão os dados reais dos vídeos do canal nos últimos {days} dias: título, duração, views, % média assistida,
duração média assistida, e (quando o vídeo foi feito pelo pipeline) o formato usado e a primeira frase (gancho).
"retencao" mostra a % do público que ainda assistia em 10%, 25%, 50%, 75% e 95% do vídeo (acima de 100% = reassistiram).

{videos}

Formatos disponíveis no canal: {formats}
{rules}

Escreva o que o canal deve REPETIR e EVITAR, com base só nesses números. Responda SOMENTE com JSON:
{{"insights": "5 a 8 linhas curtas começando com '- ', concretas e acionáveis (temas, padrão de título, duração ideal,
como abrir o vídeo, como terminar). Cite números quando ajudar.",
 "format_scores": {{"nome exato do formato": nota de 0 a 1 de quanto vale repetir (0.5 se não há dados)}},
 "summary": "1 frase com a principal conclusão"}}
"""


CLIP_SELECT_PROMPT = """Você é editor de cortes do canal de YouTube Shorts "{channel}".
Nicho do canal: {niche}

Abaixo está a transcrição de um vídeo longo ("{source_title}"), com o tempo em segundos do início de cada trecho.
Escolha os {count} melhores trechos para virar Shorts.

Regras:
- Cada corte entre {min_seconds} e {max_seconds} segundos.
- Começa com um gancho forte: uma frase que prende sem precisar de contexto anterior.
- Termina numa conclusão, punchline ou revelação, nunca no meio de uma frase.
- Os cortes não podem se sobrepor.
- Prefira momentos de emoção, humor, opinião forte, revelação ou informação surpreendente.
{instructions}

Transcrição:
{transcript}

Responda SOMENTE com JSON válido, sem markdown:
{{"clips": [{{"start": 123.4, "end": 170.2,
  "title": "título curto e curioso em {language} (máx 70 caracteres, com #shorts no fim)",
  "description": "descrição de 2-3 linhas com hashtags",
  "tags": ["tag1", "tag2"],
  "cover_text": "2 a 5 palavras de impacto, com a palavra mais forte entre [colchetes]",
  "score": 87,
  "reason": "por que esse trecho funciona como short"}}]}}"""

DEFAULT_CONFIG: dict = {
    "general": {
        "max_parallel_jobs": 1,
        "image_concurrency": 2,
        "llm_timeout": 300,
        "image_timeout": 420,
    },
    "transcription": {
        "provider": "whisper",
        "model": "small",
        "fallback_provider": "elevenlabs",
        "language": "pt",
    },
    "providers": {
        "claude": {"bin": "claude"},
        "codex": {"bin": "codex"},
        "agy": {"bin": "agy"},
        "elevenlabs": {"api_key": ""},  # ou variável de ambiente ELEVENLABS_API_KEY
    },
    "youtube": {
        "client_secret_path": str(YOUTUBE_DIR / "client_secret.json"),
    },
    "instagram": {
        "access_token": "",
        "account_id": "",
    },
    "notifications": {
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "discord": {"enabled": False, "webhook_url": ""},
    },
    "channels": {
        "terror": {
            "name": "Canal de Terror",
            "enabled": True,
            "language": "português do Brasil",
            "niche": "Historinhas curtas de terror originais, narradas com voz grave, ilustradas com imagens sombrias.",
            "idea": {"source": "llm", "rss_urls": [], "explore": [], "avoid": [], "tone": "", "require_approval": False},
            "models": {
                "ideia": {"provider": "claude", "model": "sonnet", "fallback_provider": "", "fallback_model": ""},
                "roteiro": {"provider": "claude", "model": "opus", "fallback_provider": "codex", "fallback_model": ""},
                "selecao": {"provider": "claude", "model": "sonnet", "fallback_provider": "codex", "fallback_model": ""},
                "critica": {"provider": "claude", "model": "sonnet", "fallback_provider": "codex", "fallback_model": ""},
                "imagens": {"provider": "codex", "model": "", "fallback_provider": "agy", "fallback_model": ""},
                "narracao": {"provider": "elevenlabs", "model": "eleven_multilingual_v2",
                             "voice_id": "pNInz6obpgDQGcFmaJgB", "voice_name": "Adam",
                             "stability": 0.45, "similarity_boost": 0.8, "style": 0.35, "speed": 0.95,
                             "fallback_provider": "edge", "fallback_model": "pt-BR-AntonioNeural",
                             "rate": "-8%", "pitch": "-12Hz"},
            },
            "prompts": {
                "idea": IDEA_PROMPT,
                "script": TERROR_SCRIPT_PROMPT,
                "long_script": LONG_PROMPT_TERROR,
                "clip_select": CLIP_SELECT_PROMPT,
                "image_style": "dark cinematic horror illustration, eerie atmosphere, muted desaturated colors, "
                               "deep shadows, volumetric fog, film grain, vertical 9:16 composition, no text",
            },
            "video": {
                "scenes": 6,
                "target_seconds": 45,
                "caption_font": "Anton",
                "caption_size": 130,
                "caption_color": "#FFFFFF",
                "highlight_color": "#E11D2A",
                "caption_uppercase": True,
                "words_per_caption": 3,
                "effects": "terror",
                "camera_motion": "",
                "music_volume": 0.10,
            },
            "creative": {
                "cut_every": 2.5, "cut_every_long": 5, "sound": True, "sound_style": "terror",
                "sfx_volume": 0.55, "ambience_volume": 0.16, "whoosh": True, "beat_fx": True, "max_sfx": 8,
                "emotion_tags": True, "loop_ending": True,
                "formats": [
                    "história clássica narrada em terceira pessoa",
                    "POV em segunda pessoa (\"você acorda e...\")",
                    "regras para sobreviver a um lugar (\"regra número 1...\")",
                    "relato de um seguidor contado em primeira pessoa",
                    "mensagens ou ligações que chegam de madrugada",
                    "lenda urbana brasileira reinventada",
                ],
                "insights": "",
                "review_script": True, "review_min_score": 8, "review_rounds": 1,
                "characters": True, "character_refs": True,
                "auto_learn": True, "learn_every_days": 7,
                # marca do canal
                "persona": "", "signoff": "",
                "series_name": "", "series_badge": "", "series_start": 1,
                "sonic_logo": False, "sonic_logo_prompt": "",
                "rating_meter": False, "rating_label": "NOTA", "rating_seconds": 2.4,
                "rating_criteria": "o quanto o tema é surpreendente ou relevante de verdade para o público do canal",
            },
            "cover": {
                "enabled": True, "source": "ai", "scene": 1, "text_enabled": True,
                "font": "Anton", "font_size": 0, "text_color": "#FFFFFF", "highlight_color": "#E11D2A",
                "position": "top", "darken": 0.25, "in_video": True, "in_video_seconds": 0.3,
                "upload_thumbnail": True,
            },
            "long": {
                "target_minutes": 8, "seconds_per_image": 15, "captions": False, "caption_size": 72,
                "chapters": True,
            },
            "clips": {
                "count": 5, "min_seconds": 25, "max_seconds": 60, "reframe": "face", "captions": True,
                "cover_from_frame": True,
                "review_selection": False, "media_cues": False,
            },
            "review": {"require_approval": True, "approve_before_render": True, "after": {}},
            "upload": {"mode": "manual", "privacy": "private", "category_id": "24", "made_for_kids": False},
            "schedule": {"enabled": False, "times": ["10:00", "19:00"]},
        },
        "tech": {
            "name": "Canal de Tecnologia",
            "enabled": True,
            "language": "português do Brasil",
            "niche": "Novidades e curiosidades de tecnologia: lançamentos, IA, gadgets, games e ciência.",
            "idea": {"source": "rss", "explore": [], "avoid": [], "tone": "", "require_approval": False, "rss_urls": [
                "https://www.theverge.com/rss/index.xml",
                "https://techcrunch.com/feed/",
                "https://tecnoblog.net/feed/",
            ]},
            "models": {
                "ideia": {"provider": "claude", "model": "sonnet", "fallback_provider": "", "fallback_model": ""},
                "roteiro": {"provider": "claude", "model": "sonnet", "fallback_provider": "agy", "fallback_model": ""},
                "selecao": {"provider": "claude", "model": "sonnet", "fallback_provider": "codex", "fallback_model": ""},
                "critica": {"provider": "claude", "model": "sonnet", "fallback_provider": "codex", "fallback_model": ""},
                "imagens": {"provider": "codex", "model": "", "fallback_provider": "agy", "fallback_model": ""},
                "narracao": {"provider": "elevenlabs", "model": "eleven_multilingual_v2",
                             "voice_id": "nPczCjzI2devNBz1zQrb", "voice_name": "Brian",
                             "stability": 0.4, "similarity_boost": 0.8, "style": 0.3, "speed": 1.08,
                             "fallback_provider": "edge", "fallback_model": "pt-BR-AntonioNeural",
                             "rate": "+12%", "pitch": "+0Hz"},
            },
            "prompts": {
                "idea": IDEA_PROMPT,
                "script": TECH_SCRIPT_PROMPT,
                "long_script": LONG_PROMPT_TECH,
                "clip_select": CLIP_SELECT_PROMPT,
                "image_style": "vibrant modern tech illustration, neon accents, clean 3D render style, "
                               "high contrast, vertical 9:16 composition, no text, no logos",
            },
            "video": {
                "scenes": 6,
                "target_seconds": 40,
                "caption_font": "Anton",
                "caption_size": 130,
                "caption_color": "#FFFFFF",
                "highlight_color": "#22D3EE",
                "caption_uppercase": True,
                "words_per_caption": 3,
                "effects": "none",
                "camera_motion": "",
                "music_volume": 0.08,
            },
            "creative": {
                "cut_every": 2.5, "cut_every_long": 5, "sound": True, "sound_style": "tech",
                "sfx_volume": 0.55, "ambience_volume": 0.08, "whoosh": True, "beat_fx": True, "max_sfx": 8,
                "emotion_tags": True, "loop_ending": True,
                "formats": [
                    "você sabia? (curiosidade surpreendente)",
                    "X vs Y (comparação direta com um vencedor)",
                    "mito ou verdade",
                    "3 coisas que quase ninguém sabe sobre o tema",
                    "notícia explicada como se fosse para um amigo",
                    "o lado ruim que ninguém conta",
                ],
                "insights": "",
                "review_script": True, "review_min_score": 8, "review_rounds": 1,
                "characters": True, "character_refs": True,
                "auto_learn": True, "learn_every_days": 7,
                # marca do canal
                "persona": "", "signoff": "",
                "series_name": "", "series_badge": "", "series_start": 1,
                "sonic_logo": False, "sonic_logo_prompt": "",
                "rating_meter": False, "rating_label": "NOTA", "rating_seconds": 2.4,
                "rating_criteria": "o quanto o tema é surpreendente ou relevante de verdade para o público do canal",
            },
            "cover": {
                "enabled": True, "source": "ai", "scene": 1, "text_enabled": True,
                "font": "Anton", "font_size": 0, "text_color": "#FFFFFF", "highlight_color": "#22D3EE",
                "position": "top", "darken": 0.25, "in_video": True, "in_video_seconds": 0.3,
                "upload_thumbnail": True,
            },
            "long": {
                "target_minutes": 8, "seconds_per_image": 15, "captions": False, "caption_size": 72,
                "chapters": True,
            },
            "clips": {
                "count": 5, "min_seconds": 25, "max_seconds": 60, "reframe": "face", "captions": True,
                "cover_from_frame": True,
                "review_selection": False, "media_cues": False,
            },
            "review": {"require_approval": True, "approve_before_render": True, "after": {}},
            "upload": {"mode": "manual", "privacy": "private", "category_id": "28", "made_for_kids": False},
            "schedule": {"enabled": False, "times": ["12:00"]},
        },
    },
}

_lock = threading.Lock()


def _merge_defaults(cfg: dict, defaults: dict) -> dict:
    for key, value in defaults.items():
        if key not in cfg:
            cfg[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(cfg[key], dict) and key != "channels":
            _merge_defaults(cfg[key], value)
    return cfg


LEGACY_CREATIVE = {"hype_meter": "rating_meter", "hype_label": "rating_label", "hype_seconds": "rating_seconds"}


def _migrate_channel(ch: dict) -> None:
    """Renomeia chaves antigas da configuração (ex.: hype_meter → rating_meter)."""
    cr = ch.get("creative") or {}
    for old, new in LEGACY_CREATIVE.items():
        if old in cr:
            cr.setdefault(new, cr.pop(old))


def _channel_template(ch: dict | None = None) -> dict:
    """Padrões de um canal sem modelo próprio: usa o de tecnologia se o canal for no estilo tech, senão o de terror."""
    style = ((ch or {}).get("creative") or {}).get("sound_style")
    return DEFAULT_CONFIG["channels"]["tech" if style == "tech" else "terror"]


def channel_defaults(cid: str, ch: dict | None = None) -> dict:
    return DEFAULT_CONFIG["channels"].get(cid) or _channel_template(ch)


def _remove_legacy_tiktok(cfg: dict) -> None:
    cfg.pop("tiktok", None)
    for ch in cfg.get("channels", {}).values():
        opts = ch.get("upload")
        if isinstance(opts, dict):
            opts.pop("tiktok_privacy", None)
            opts.pop("publish_to_tiktok", None)


def load() -> dict:
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_PATH.exists():
            CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2))
            return copy.deepcopy(DEFAULT_CONFIG)
        cfg = json.loads(CONFIG_PATH.read_text())
        _remove_legacy_tiktok(cfg)
        _merge_defaults(cfg, DEFAULT_CONFIG)
        for cid, ch in cfg.get("channels", {}).items():
            _migrate_channel(ch)
            _merge_defaults(ch, channel_defaults(cid, ch))
        return cfg


def save(cfg: dict) -> None:
    with _lock:
        _remove_legacy_tiktok(cfg)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        tmp.replace(CONFIG_PATH)


def channel(cfg: dict, channel_id: str) -> dict:
    try:
        return cfg["channels"][channel_id]
    except KeyError:
        raise KeyError(f"Canal desconhecido: {channel_id}")


def new_channel_config(name: str) -> dict:
    ch = copy.deepcopy(_channel_template())
    ch["name"] = name
    ch["niche"] = ""
    return ch
