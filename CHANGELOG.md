# Changelog

All notable changes to ShortPipeline are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Animated Shorts** (new `animado` job type): 2D/2.5D motion graphics drawn by code from a validated, versioned JSON (`docs/motion/schema.v1.json`). New stages: research (facts tagged as verified, calculation, estimate or illustration), storyboard (AI picks catalog components and syncs actions to narration words; validation errors go back to the AI), assets (catalog report), preview (low resolution, per scene, cached) and quality (static-stretch detection, numbers not shown on screen, AI review that redoes only weak scenes). The engine (`motion-canvas/engine`) has an articulated character (walk, run, reactions, expressions, accessories), layered parallax scenery (city, nature, room, studio), objects with gravity and impact, camera follow/focus/shake/slow motion, speed and distance indicators tied to the physics, counters, callouts, bars and word-synced captions that avoid on-screen info. Only changed scenes are re-rendered. Plan and decisions in `docs/motion/PLANO.md`.
- **Analytics-driven topics**: the learning step scores the channel's themes by real views, watch % and subscribers, stores each video's numbers and suggests new topics; the idea stage uses this as its main criterion (candidates in the best themes, weak themes dropped). Toggle per channel; suggested topics can be queued from the dashboard.
- **Render check**: the timeline's "Checar render" inspects the final MP4 (resolution, duration, loudness) and flags dark, static or silent sections.
- **Scene media tools**: replace a scene's image or video, preview a Real-ESRGAN upscale and Motion Canvas templates before rendering.
- **Camera motion presets** per channel (smooth zoom, horizontal pan, vertical pan or automatic).
- **Offline sound packs** (CC0, Kenney and OpenGameArt) used when ElevenLabs is unavailable.
- **Story-matched music**: a `music.json` in a channel's music folder describes when special tracks fit; the script AI picks one only when the story matches, otherwise a regular track (or none) is used.
- **Your own sound library** in `data/sound-packs/` (outside git): per-style packs (`pack.json`), random variations (`applause-1`, `applause-2`), keyword matching against effect and ambience descriptions in English or Portuguese, priority over ElevenLabs, a "Sua biblioteca" row in the timeline's Add SFX drawer, and the script prompt lists the available sounds.
- Notification when a job fails, as documented in 0.2.0 (the event existed but was never sent).
- Test suite (pytest): config migration, sound mix, captions, cover, API routes and a full short from script to `final.mp4` with mocked AI and voice; GitHub Actions workflow running lint and tests.

### Changed
- New channels start from a neutral template (generic script and long-video prompts, neutral image style, formats, sound style and no visual effect) instead of copying the horror example. Existing channels keep the defaults of their sound style.
- `server.py` split into `shortpipeline/routes/` (`jobs`, `timeline`, `channels`, `integrations`); the API is unchanged.
- `pipeline.py` split into the `shortpipeline/pipeline/` package (`writing`, `media`, `assembly`, `clips`, `runner`).
- `web/app.js` split into `web/js/`, one file per page; the timeline is now its own file.
- Errors that were silently ignored (Analytics, YouTube token, Instagram permalink, notifications, timeline remix) are now logged.
- README reorganized: features, setup of each integration, development and credits.

### Fixed
- Ambience was too quiet to hear in the final video: beds are now leveled to a common loudness before the channel's ambience volume is applied (the synthesized fallback sat around 30 dB below the voice). Mixes made before this are rebuilt automatically when the timeline is opened or the video is rendered, using the channel's current ambience volume, and the tech and neutral defaults go from 0.08 and 0.10 to 0.14.
- Timeline edits made after a render (removing or adding sounds, scene media, audio levels) never reached the video: a "Renderizar de novo" button re-renders it, and the panel flags pending changes.
- Timeline sound previews failed after the sound list changed, or when Chrome rejected `play()` while still playing; they now fall back to downloading the file.
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
