"""Montagem: som, render, revisão e publicação."""

from __future__ import annotations


import time
from pathlib import Path

from .. import render, sound, upload
from ..providers import ProviderError, tts
from .core import Ctx, WaitingApproval
from .writing import rating_on
from .media import find_word_time, plan_shots, scene_words


async def stage_som(c: Ctx) -> None:
    cr = c.creative()
    if c.kind == "corte" or not cr.get("sound", True):
        c.save(sound=None)
        c.log("Desenho de som desligado")
        return
    style = cr.get("sound_style") or ("terror" if c.ch["video"].get("effects") == "terror" else "neutro")
    scenes = c.data["script"]["scenes"]
    durations = c.data["durations"]
    timings = scene_words(c)
    total = sum(durations)
    events, beds, beats = [], [], []
    sfx_vol = float(cr.get("sfx_volume") or 0.55)
    amb_setting = cr.get("ambience_volume")
    amb_vol = float(amb_setting if amb_setting is not None else 0.15)
    have_key = bool(tts.elevenlabs_key(c.cfg["providers"]))
    if not have_key:
        c.log("Sem API key do ElevenLabs: usando cache e sons disponíveis localmente", "warn")
    offset = 0.0
    budget = int(cr.get("max_sfx") or 8)
    failed = 0
    fallback_beds = 0
    from_library = 0
    for i, (sc, d) in enumerate(zip(scenes, durations)):
        words = timings[i] if i < len(timings) else []
        c.detail(f"cena {i + 1}/{len(scenes)}")
        if i > 0 and cr.get("whoosh", True):
            events.append({"file": await sound.library_sound("whoosh", style, c.cfg["providers"]),
                           "at": offset - 0.3, "volume": sfx_vol * 0.8,
                           "type": "whoosh", "label": "Whoosh (transição)", "scene": i + 1})
        beat = (sc.get("beat") or "").lower()
        if beat in ("scare", "reveal") and cr.get("beat_fx", True):
            first_sfx = next((x for x in sc.get("sfx") or [] if x.get("word")), None)
            rel = find_word_time(words, first_sfx["word"]) if first_sfx else None
            if rel is None:
                rel = words[len(words) // 2]["start"] if words else d / 2
            at = offset + rel
            beats.append(round(at, 3))
            events.append({"file": await sound.library_sound("impact", style, c.cfg["providers"]),
                           "at": at - 0.05, "volume": sfx_vol * 1.2,
                           "type": "impact", "label": f"Impacto ({'susto' if beat == 'scare' else 'revelação'})",
                           "scene": i + 1})
            if at > 2.5:
                events.append({"file": await sound.library_sound("riser", style, c.cfg["providers"]),
                               "at": at - 2.3, "volume": sfx_vol * 0.6,
                               "type": "riser", "label": "Tensão / Riser", "scene": i + 1})
        for x in (sc.get("sfx") or [])[:2]:
            if budget <= 0 or not x.get("sound"):
                continue
            rel = find_word_time(words, x.get("word") or "")
            if rel is None:
                continue
            # a sua biblioteca vem antes do ElevenLabs (ex.: "woman screaming" usa um scream-N.mp3 seu)
            f = sound.match_sound(x["sound"], style)
            if f:
                from_library += 1
            elif have_key:
                try:
                    f = await sound.generate(x["sound"], c.cfg["providers"], duration=2.0)
                except ProviderError as e:
                    failed += 1
                    c.log(f"Efeito \"{x['sound']}\" falhou: {e}", "warn")
            if f:
                events.append({"file": f, "at": offset + rel - 0.1, "volume": sfx_vol,
                               "type": "sfx", "label": x["sound"], "word": x.get("word"), "scene": i + 1})
                budget -= 1
        ambience = (sc.get("ambience") or "").strip()
        if ambience and amb_vol > 0:
            try:
                f = sound.match_sound(ambience, style, prefix="ambience")
                if f:
                    from_library += 1
                else:
                    try:
                        f = await sound.generate(ambience, c.cfg["providers"], duration=10.0, loop=True)
                    except ProviderError as e:
                        if have_key:
                            c.log(f"Ambiente da cena {i + 1}: ElevenLabs indisponível, usando reserva local ({e})",
                                  "warn")
                        f = await sound.fallback_ambience(style, ambience)
                        fallback_beds += 1
                beds.append({"file": f, "start": offset, "dur": d + (render.XFADE if i < len(scenes) - 1 else 0),
                             "volume": amb_vol, "sound": ambience, "scene": i + 1})
            except ProviderError as e:
                failed += 1
                c.log(f"Ambiente da cena {i + 1} falhou: {e}", "warn")
        offset += d
    script = c.data["script"]
    if rating_on(c) and script.get("rating") is not None:
        at = max(0.0, total - float(cr.get("rating_seconds") or 2.4))
        events.append({"file": await sound.library_sound("blip", style, c.cfg["providers"]), "at": at,
                       "volume": sfx_vol, "type": "blip", "label": "Selo de nota"})
    if cr.get("sonic_logo") and cr.get("sonic_logo_prompt") and have_key:
        try:  # assinatura sonora no ponto do loop (fim → começo)
            f = await sound.generate(cr["sonic_logo_prompt"], c.cfg["providers"], duration=0.8)
            events.append({"file": f, "at": max(0.0, total - 0.75), "volume": sfx_vol * 1.1,
                           "type": "sonic_logo", "label": "Assinatura sonora"})
        except ProviderError as e:
            c.log(f"Assinatura sonora falhou: {e}", "warn")
    previous_sound = c.data.get("sound") or {}
    imported_events = [
        e for e in previous_sound.get("events") or []
        if e.get("imported") and e["at"] < total and Path(e.get("file") or "").is_file()
    ]
    imported_beds = [
        {**b, "dur": min(b["dur"], total - b["start"])} for b in previous_sound.get("beds") or []
        if b.get("imported") and b["start"] < total and Path(b.get("file") or "").is_file()
    ]
    mix = c.dir / "sfx.wav"
    c.detail("mixando")
    await sound.build_mix(events + imported_events, beds + imported_beds, total, mix)
    clean_events = [
        {"type": e.get("type", "sfx"), "label": e.get("label", "Efeito"), "at": round(e["at"], 2),
         "volume": round(e.get("volume", 0.5), 2), "word": e.get("word"), "scene": e.get("scene"),
         "file": str(e["file"]) if e.get("file") else None}
        for e in events
    ]
    clean_beds = [
        {"sound": b.get("sound", "Ambiente"), "start": round(b["start"], 2), "dur": round(b["dur"], 2),
         "volume": round(b.get("volume", 0.15), 2), "scene": b.get("scene"),
         "file": str(b["file"]) if b.get("file") else None}
        for b in beds
    ]
    c.save(sound={"mix": str(mix) if mix.exists() else None, "beats": beats,
                  "events": sorted(clean_events + imported_events, key=lambda e: e["at"]),
                  "beds": sorted(clean_beds + imported_beds, key=lambda b: b["start"]), "style": style,
                  "mix_version": sound.MIX_VERSION})
    c.log(f"Som: {len(events)} efeitos, {len(beds)} ambientes, {len(beats)} momentos de impacto"
          + (f" ({fallback_beds} ambientes locais)" if fallback_beds else "")
          + (f" ({from_library} da sua biblioteca)" if from_library else "")
          + (f" ({failed} falharam)" if failed else ""))


async def stage_render(c: Ctx) -> None:
    if c.ch.get("review", {}).get("approve_before_render", True):
        if not c.data.get("approved_render"):
            c.log("Pausado antes do render para conferência da timeline")
            raise WaitingApproval()
    out = c.dir / "final.mp4"
    cover = c.data.get("cover")
    cov = c.ch.get("cover") or {}
    caps = c.data.get("captions", str(c.dir / "captions.ass"))
    ass = Path(caps) if caps and Path(caps).exists() else None
    cover_png = Path(cover["image"]) if cover and cov.get("in_video") and not c.is_long else None
    log = lambda m: (c.log(m), c.detail(m))
    if c.kind == "animado":
        from .animated import render_final
        await render_final(c, log)
        c.save(video=str(out))
        c.log(f"Vídeo pronto: {out.stat().st_size / 1e6:.1f} MB")
        return
    if c.kind == "corte":
        c.detail("renderizando")
        await render.render_clip(Path(c.data["reframed"]), ass, out, cover_png,
                                 float(cov.get("in_video_seconds") or 0.3))
    else:
        cr = c.creative()
        every = float(cr.get("cut_every_long" if c.is_long else "cut_every") or 0)
        timings = scene_words(c)
        shots = [plan_shots(timings[i] if i < len(timings) else [], d, every)
                 for i, d in enumerate(c.data["durations"])] if every > 0 else None
        snd = c.data.get("sound") or {}
        if (snd.get("events") or snd.get("beds")) and snd.get("mix_version") != sound.MIX_VERSION:
            # mix feito com uma versão antiga da mixagem: refaz com os sons salvos e o volume de ambiente atual
            c.detail("mixando efeitos")
            snd = await sound.remix_saved(snd, sum(c.data["durations"]), c.dir / "sfx.wav",
                                          cr.get("ambience_volume"))
            c.save(sound=snd)
            c.log("Trilha de efeitos refeita com a mixagem atual")
        sfx = Path(snd["mix"]) if snd.get("mix") and Path(snd["mix"]).exists() else None
        style = snd.get("style") or cr.get("sound_style")
        meter = None
        rating = c.data["script"].get("rating")
        if rating_on(c) and rating is not None:
            total = sum(c.data["durations"])
            meter = {"score": rating, "label": cr.get("rating_label") or "NOTA",
                     "start": max(0.0, total - float(cr.get("rating_seconds") or 2.4)), "end": total,
                     "color": c.ch["video"].get("highlight_color")}
        from ..quality import scene_image

        scenes = c.data["script"]["scenes"]
        visuals = []
        videos = []
        for path, scene in zip(c.data["images"], scenes, strict=True):
            media = scene.get("media") or {}
            replacement = render.scene_media_path(c.dir, media.get("file"))
            videos.append(replacement if media.get("kind") == "video" else None)
            visuals.append(replacement if replacement and media.get("kind") == "image"
                           else scene_image(Path(path), c.dir, scene))
        music = render.pick_music(c.channel_id, c.data["script"].get("music"))
        log(f"Música: {music.name}" if music else "Sem música de fundo")
        await render.render_video(c.dir, visuals, c.data["durations"],
                                  c.dir / "narration.wav", ass, c.ch["video"], c.channel_id, out, log=log,
                                  cover=cover_png, cover_seconds=float(cov.get("in_video_seconds") or 0.3),
                                  frame=c.frame, shots=shots, beats=snd.get("beats") or [], sfx=sfx,
                                  flash=style == "terror" and cr.get("beat_fx", True), meter=meter,
                                  motions=[scene.get("motion") for scene in scenes], scene_videos=videos,
                                  music=music)
    size = out.stat().st_size / 1e6
    c.save(video=str(out))
    c.log(f"Vídeo pronto: {size:.1f} MB")


async def stage_revisao(c: Ctx) -> None:
    if not c.ch["review"].get("require_approval"):
        c.log("Aprovação desligada para este canal; seguindo direto")
        return
    if c.data.get("approved"):
        c.log("Aprovado no painel")
        return
    if not c.data.get("review_notified"):
        from .. import notify
        c.save(review_notified=True)
        try:
            await notify.notify_event(c.cfg, "review_ready", c.job)
        except Exception as e:
            c.log(f"Aviso de revisão não enviado: {e}", "warn")
    raise WaitingApproval()


def chapters_text(chapters: list[dict]) -> str:
    """Capítulos no formato do YouTube (precisa começar em 0:00 e ter pelo menos 3)."""
    if len(chapters) < 3:
        return ""
    lines = []
    for i, ch in enumerate(chapters):
        t = 0 if i == 0 else int(ch["start"])
        lines.append(f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d} {ch['title']}" if t >= 3600
                     else f"{t // 60}:{t % 60:02d} {ch['title']}")
    return "\n".join(lines)


async def stage_upload(c: Ctx) -> None:
    up = c.ch["upload"]
    mode = c.data.get("upload_mode_override") or up.get("mode") or "manual"
    if mode not in ("auto", "draft"):
        c.save(publish={"mode": "manual", "ready_at": time.time()})
        c.log("Modo manual: vídeo pronto para você baixar e postar")
        return
    opts = dict(up)
    if mode == "draft":
        # a API do YouTube não cria rascunho de verdade: sobe como privado, sem avisar inscritos,
        # e você termina no Studio (o vídeo fica lá como privado até você publicar)
        opts.update(privacy="private", draft=True)
    elif c.data.get("publish_at"):
        opts["publish_at"] = c.data["publish_at"]
    c.log("Enviando para o YouTube como rascunho (privado)" if mode == "draft"
          else f"Enviando para o YouTube ({opts.get('privacy')})")
    cover = c.data.get("cover") or {}
    cov_path = cover.get("jpg") or cover.get("image")
    thumb = Path(cov_path) if cov_path and Path(cov_path).exists() and (c.ch.get("cover") or {}).get("upload_thumbnail", True) else None
    meta = dict(c.data["script"])
    if c.is_long and c.data.get("chapters") and c.long_opts().get("chapters", True):
        meta["description"] = (meta.get("description") or "") + "\n\n" + chapters_text(c.data["chapters"])
    opts["is_short"] = not c.is_long
    result = await upload.upload(c.channel_id, Path(c.data["video"]), meta, opts,
                                 progress=lambda p: c.detail(f"{p}%"), thumbnail=thumb)
    c.save(publish={"mode": mode, **result})
    c.log(f"Rascunho no YouTube: {result['studio_url']}" if mode == "draft" else f"Publicado: {result['url']}")
    if result.get("thumbnail_error"):
        c.log(f"Thumbnail não enviada: {result['thumbnail_error']}", "warn")
    elif thumb:
        c.log("Capa enviada como thumbnail")

    # Upload para o Instagram Reels
    from .. import instagram
    ig_status = instagram.status(c.cfg, c.channel_id)
    send_ig = bool(ig_status.get("configured") and (opts.get("publish_to_instagram") or c.data.get("publish_to_instagram")))
    if send_ig and not c.is_long:
        try:
            c.log("Enviando para o Instagram Reels...")
            ig_res = await instagram.upload(
                c.channel_id,
                Path(c.data["video"]),
                meta,
                opts,
                progress=lambda p: c.detail(f"Instagram: {p}%"),
            )
            result["instagram"] = ig_res
            c.save(publish={"mode": mode, **result})
            c.log(f"Enviado para o Instagram Reels: {ig_res.get('permalink')}")
        except Exception as e:
            c.log(f"Falha ao enviar para o Instagram Reels: {e}", "warn")
            result["instagram_error"] = str(e)[:300]
            c.save(publish={"mode": mode, **result})

    # Disparar notificação de publicação concluída
    from .. import notify
    try:
        await notify.notify_event(c.cfg, "published", c.job)
    except Exception as e:
        c.log(f"Aviso de publicação não enviado: {e}", "warn")
