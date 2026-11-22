<img src="assets/icon.svg" width="64" height="64" alt="">

# ShortPipeline

**English** · [Português](README.md)

A video factory for YouTube: it automatically makes **Shorts**, **long-form videos** and **clips** cut from long videos, for as many channels as you want, with a web dashboard that shows which stage each video is in and lets you choose which AI does what.

Text and image AIs run through **CLIs logged in with your own account** (`claude`, `codex` and `agy`), with no API keys. Narration uses ElevenLabs, with the free Edge TTS as a fallback.

> The dashboard and the default prompts are in Brazilian Portuguese. The language of the videos is set per channel.

```
Idea → Script → Narration → Images → Cover → Captions → Sound → Render → Review → Publish
```

![Pipeline dashboard: each video and the stage it is in](docs/pipeline.png)

## Screenshots

| | |
|---|---|
| ![A finished video with its generated scenes and the sound effects of each one](docs/video-cenas.png) | ![Review before publishing, with the script critic's scores](docs/video-roteiro.png) |
| **Video**: player, stages with timings, scenes with sound effects and ambience | **Approval**: title, description, publish, schedule or upload as a draft; script critic scores |
| ![Channel analytics](docs/analytics.png) | ![Channel creative direction settings](docs/canais.png) |
| **Analytics**: views, retention, subscribers, traffic sources and what the channel has learned | **Channels**: model per stage, voice, prompts and creative direction |

<sub>Screenshots from a demo environment: channels, videos and numbers are fictional.</sub>

## What it does

| Stage | What happens | Providers |
|---|---|---|
| Idea | picks the topic: the AI suggests one without repeating past titles, or takes a fresh story from an RSS feed | Claude / Codex / Gemini (agy) |
| Script | title, description, tags and scenes (narration + image prompt); then a **critic** scores the hook, pacing, ending and title, and rewrites the script if it falls below the bar | Claude / Codex / Gemini (agy) |
| Narration | voice per scene with timing for every word; with `eleven_v3`, emotion tags (`[whispers]`, `[scared]`…) | ElevenLabs / Edge TTS |
| Images | one image per scene; characters keep a fixed look, using each one's first image as a reference for the next scenes | Codex / Gemini (agy) / placeholder |
| Cover | image with short text; shown in the first frames and uploaded as the thumbnail | AI or a scene image |
| Captions | karaoke style, highlighting the spoken word | — |
| Sound | sound effects on the right word, ambience per scene, whooshes on transitions and impacts on scares/reveals | ElevenLabs (cached) or synthesized sounds |
| Render | several shots per scene (cuts that follow the speech), transitions, channel effects, flash/shake on impacts, music that ducks under the voice | ffmpeg |
| Review | waits for your approval in the dashboard (optional per channel) | — |
| Publish | manual (download the MP4), **draft** (uploads as private without notifying subscribers, so you finish it in YouTube Studio) or automatic, with scheduling | YouTube Data API |

Every AI stage has a main provider and a fallback that takes over when the main one fails (quota, errors). `*_API_KEY` variables are removed from the CLIs' environment, so usage never falls back to paid API billing.

### Creative direction

Per channel: cut pacing, sound design, emotion in the voice, loop endings (the last line flows into the first) and a list of **formats** the pipeline rotates through (e.g. "second-person POV", "myth or fact").

### Learning from Analytics

Once the channel is connected, the pipeline periodically reads how the videos actually performed (views, % watched, retention curve) and an AI sums up **what to repeat and what to avoid**. These learnings go into the idea, script and critic prompts, and the formats that perform best get picked more often. The dashboard's **Analytics** page shows views, retention, subscribers, traffic sources and the videos published by the pipeline.

### Long-form videos

The same flow in 16:9: a long script with chapters, one image every N seconds, a 1280×720 thumbnail and chapters in the description. The length is configurable.

### Clips

Turns a long video (link or file) into several shorts:

```
Download → Transcription → Selection  ⟶  one job per segment: Crop → Cover → Captions → Render → Review → Publish
```

- **Transcription** with word timings: local Whisper (CPU, free) or ElevenLabs Scribe.
- **Selection**: the AI picks the segments with the best hooks and explains why; clips start and end on whole words.
- **Crop**: reframes to 9:16 following the speaker's face (OpenCV/YuNet), with a blurred background or a center crop as alternatives.

Only use videos you own or have permission to clip.

## Installation

Requirements:

- [`uv`](https://docs.astral.sh/uv/) and Python 3.12
- `ffmpeg` with libass
- At least one AI CLI, logged in: [`claude`](https://docs.claude.com/en/docs/claude-code), [`codex`](https://github.com/openai/codex) or `agy` (Google Antigravity)
- Optional: an [ElevenLabs](https://elevenlabs.io) API key (without it, narration uses Edge TTS and sound design uses synthesized effects)

```bash
git clone https://github.com/IsaelSousa/shortpipeline
cd shortpipeline
uv run shortpipeline          # opens at http://localhost:8765
```

In the dashboard:

- **Pipeline**: create shorts, long-form videos or clips and follow each stage live. In a video you can see the script, critic scores, images, sound and log, approve it, edit the script, regenerate an image or redo it from any stage.
- **Analytics**: channel metrics and what the pipeline has learned.
- **Canais** (Channels): model per stage, voice, prompts, creative direction, visual style, captions, cover, review, publishing and automatic schedule.
- **Provedores** (Providers): CLI status, ElevenLabs API key, transcription and YouTube connection.

Background music: put MP3s in `assets/music/<channel-id>/`. One is picked at random per video.

## Connecting YouTube (upload, drafts and Analytics)

1. In the [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **YouTube Data API v3** and the **YouTube Analytics API**.
2. In *Google Auth Platform*, set up the consent screen and add your email as a test user.
3. Create an OAuth client of type **Desktop app** and save the JSON to `data/youtube/client_secret.json` (or set the path in the dashboard).
4. In the dashboard, under **Canais**, click **Conectar YouTube** and pick the channel's account. Do it on the machine running the server (`localhost`), because the login redirect points to `localhost`.

Until your Google app is verified, videos uploaded through the API stay private.

## Network access

By default the dashboard only accepts connections from the machine it runs on. To open it on your phone:

```bash
SHORTPIPELINE_HOST=0.0.0.0 uv run shortpipeline
```

The dashboard **has no login**: anyone who can reach it sees the settings (including the ElevenLabs API key) and can create or publish videos. Only use it on a trusted network, or use a VPN such as Tailscale.

## Data

Everything of yours lives in `data/`, which is not tracked by git: `config.json` (edited from the dashboard, includes the API key), `pipeline.db` (queue and logs), `jobs/<id>/` (script, audio, images, captions and `final.mp4`), `youtube/` (OAuth tokens), `learn/` (learnings) and `sfx_cache/`.

Optional environment variables: `SHORTPIPELINE_PORT`, `SHORTPIPELINE_HOST`, `SHORTPIPELINE_DATA`, `ELEVENLABS_API_KEY`.

## Responsible use

- Follow YouTube's policies on AI-generated content and label altered or synthetic content when the platform asks.
- YouTube limits monetization of repetitive or reused content without your own contribution; review what goes live.
- For clips, only use material you own or are authorized to use.

## Credits

- [Anton](https://fonts.google.com/specimen/Anton), [Creepster](https://fonts.google.com/specimen/Creepster), [Montserrat](https://fonts.google.com/specimen/Montserrat) and [Inter](https://fonts.google.com/specimen/Inter) fonts, under the [SIL Open Font License 1.1](https://openfontlicense.org).
- [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) face detector from OpenCV Zoo, under the MIT license.
