# Changelog

All notable changes to ShortPipeline are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Render check**: the timeline's "Checar render" inspects the final MP4 (resolution, duration, loudness) and flags dark, static or silent sections.
- **Scene media tools**: replace a scene's image or video, preview a Real-ESRGAN upscale and Motion Canvas templates before rendering.
- **Camera motion presets** per channel (smooth zoom, horizontal pan, vertical pan or automatic).
- **Offline sound packs** (CC0, Kenney and OpenGameArt) used when ElevenLabs is unavailable.
- **Story-matched music**: a `music.json` in a channel's music folder describes when special tracks fit; the script AI picks one only when the story matches, otherwise a regular track (or none) is used.
- **Your own sound library** in `data/sound-packs/` (outside git): per-style packs (`pack.json`), random variations (`scream-1`, `scream-2`), keyword matching against effect and ambience descriptions in English or Portuguese, priority over ElevenLabs, a "Sua biblioteca" row in the timeline's Add SFX drawer, and the script prompt lists the available sounds.
- Notification when a job fails, as documented in 0.2.0 (the event existed but was never sent).
- Test suite (pytest): config migration, sound mix, captions, cover, API routes and a full short from script to `final.mp4` with mocked AI and voice; GitHub Actions workflow running lint and tests.

### Changed
- `server.py` split into `shortpipeline/routes/` (`jobs`, `timeline`, `channels`, `integrations`); the API is unchanged.
- `pipeline.py` split into the `shortpipeline/pipeline/` package (`writing`, `media`, `assembly`, `clips`, `runner`).
- `web/app.js` split into `web/js/`, one file per page; the timeline is now its own file.
- Errors that were silently ignored (Analytics, YouTube token, Instagram permalink, notifications, timeline remix) are now logged.
- README reorganized: features, setup of each integration, development and credits.

### Fixed
- Notification links opened the job list instead of the job (`#jobs/<id>` instead of `#job/<id>`).

### Removed
- TikTok account connections, publishing, and diagnostics. The TikTok entry in 0.2.0 no longer applies.

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
