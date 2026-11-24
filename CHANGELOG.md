# Changelog

All notable changes to ShortPipeline are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-11-24

### Added
- **Instagram Reels Publishing**:
  - Direct video uploads via Meta Graph API v21.0 using resumable binary chunking (`rupload.facebook.com`).
  - Works locally without public IP, domain, or ngrok tunnels.
  - Automated publishing in pipeline upload stage and manual "Publicar no Reels" button in job modal.
- **TikTok Content Posting**:
  - Integrated TikTok Content Posting API v2 with OAuth 2.0 flow and automated draft uploads.
  - Automatic thumbnail extraction and cover frame upload.
- **Real-Time Push Notifications (Webhooks)**:
  - Telegram Bot alerts with cover photo preview, job metadata, and review links.
  - Discord Webhooks rich embeds with status colors and direct video links.
  - Triggered on review ready (`waiting_approval`), upload success, and pipeline errors.
- **Google Trends Live Radar**:
  - Instant viral topic discovery in the "Novo Short" dialog via official Google Trends Brasil RSS.
  - One-click topic selection with real-time search volume badges and related news titles.
- **Timeline Studio & Audio Mixer**:
  - Multi-track timeline (Video/Scenes, Captions, Narration, SFX, Ambience) with collision-free lane assignment.
  - Live audio mixer with independent sliders (0% to 200%) for Voice, Background Music (BGM), and Sound Effects (SFX).
  - Manual SFX inserter at the playhead position (Whoosh, Impact, Riser, Blip, custom SFX) with on-the-fly audio remixing.
- **Cinematic Scene Transitions & Animated Subtitles**:
  - 6 transition styles: `dynamic`, `whip_pan`, `zoom_punch`, `cinematic`, `glitch`, `cut`.
  - Dynamic keyword-based emoji pop animations inside styled ASS subtitles.
- **Real-Time Diagnostics Panel**:
  - Live latency and connection status checks for YouTube Data API v3, TikTok API v2, Instagram Graph v21, ElevenLabs TTS, and local CLIs (`ffmpeg`, `claude`, `codex`, `agy`).

### Changed
- Refactored SFX and Ambience rendering into distinct dedicated tracks with dynamic vertical lane calculation.
- Improved pipeline approval workflows with optional pre-render review stage.

---

## [0.1.0] - 2026-11-22

### Added
- Initial release of ShortPipeline.
- Automated creation of vertical YouTube Shorts and long horizontal videos.
- Video generation pipeline: Idea, Script, Critique, Narration, Images, Cover, Subtitles, Sound, Render, Review, and YouTube Upload.
- Multi-provider AI support (Claude Code, Codex, Gemini/agy CLI via OAuth).
- Local Edge TTS and ElevenLabs voice generation.
- Faster-Whisper and ElevenLabs Scribe transcription for video clipping.
- Automated YouTube Data API v3 and YouTube Analytics integration.
