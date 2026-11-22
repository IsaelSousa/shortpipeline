"""Reenquadramento de vídeo horizontal para vertical 9:16.

Modos:
  face   — detecta rostos (YuNet/OpenCV) e move o recorte suavemente acompanhando o rosto principal;
           cai para "blur" quando quase não há rostos.
  blur   — vídeo inteiro no centro, com uma cópia ampliada e desfocada atrás.
  center — recorte fixo no centro.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import config

OUT_W, OUT_H = 1080, 1920
YUNET = config.ASSETS_DIR / "models" / "face_detection_yunet_2023mar.onnx"


def _ffmpeg(args: list[str]) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-v", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr[-600:]}")


def reframe_blur(src: Path, dst: Path) -> None:
    vf = (f"[0:v]split[a][b];[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
          f"boxblur=24:2,eq=brightness=-0.10[bg];[b]scale={OUT_W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    _ffmpeg(["-i", str(src), "-filter_complex", vf, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(dst)])


def reframe_center(src: Path, dst: Path) -> None:
    _ffmpeg(["-i", str(src), "-vf", f"crop='min(iw,ih*9/16)':ih,scale={OUT_W}:{OUT_H},setsar=1", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(dst)])


def _face_track(src: Path, sample_fps: float = 4.0):
    """Devolve (tempos, centros_x normalizados, fração de amostras com rosto, fps, largura, altura)."""
    import cv2

    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = 640 / w if w > 640 else 1.0
    sw, sh = int(w * scale), int(h * scale)
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (sw, sh), score_threshold=0.6, nms_threshold=0.3, top_k=20)
    step = max(1, round(fps / sample_fps))
    times, xs = [], []
    i = 0
    found = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            small = cv2.resize(frame, (sw, sh)) if scale != 1.0 else frame
            _, faces = det.detect(small)
            cx = None
            if faces is not None and len(faces):
                # rosto principal = o maior (mais perto da câmera); empate leve favorece o mais central
                best = max(faces, key=lambda f: f[2] * f[3] * (1.0 - 0.3 * abs((f[0] + f[2] / 2) / sw - 0.5)))
                cx = float((best[0] + best[2] / 2) / sw)
                found += 1
            times.append(i / fps)
            xs.append(cx)
        i += 1
    cap.release()
    ratio = found / len(times) if times else 0.0
    return times, xs, ratio, fps, w, h


def _smooth(xs: list[float | None]) -> list[float]:
    """Preenche buracos e suaviza: câmera com zona morta, para não ficar tremendo."""
    filled, last = [], None
    for x in xs:
        last = x if x is not None else last
        filled.append(last)
    first = next((x for x in filled if x is not None), 0.5)
    filled = [first if x is None else x for x in filled]
    # mediana curta remove detecções erradas isoladas
    med = []
    for i in range(len(filled)):
        win = sorted(filled[max(0, i - 2): i + 3])
        med.append(win[len(win) // 2])
    cam, out = med[0], []
    for x in med:
        if abs(x - cam) > 0.06:  # zona morta: só move se o rosto saiu do centro do quadro
            cam += (x - cam) * 0.35
        out.append(cam)
    return out


def reframe_face(src: Path, dst: Path, log=None) -> str:
    import cv2
    import numpy as np

    times, xs, ratio, fps, w, h = _face_track(src)
    if ratio < 0.2 or not times:
        if log:
            log(f"Poucos rostos detectados ({ratio:.0%}); usando fundo desfocado")
        reframe_blur(src, dst)
        return "blur"
    if log:
        log(f"Rosto encontrado em {ratio:.0%} das amostras; seguindo o rosto")
    track = _smooth(xs)
    cw = int(h * 9 / 16) // 2 * 2
    if cw >= w:  # vídeo já é vertical (ou quase)
        reframe_blur(src, dst)
        return "blur"
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-v", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{cw}x{h}", "-r", f"{fps:.3f}", "-i", "-",
         "-i", str(src), "-map", "0:v", "-map", "1:a?",
         "-vf", f"scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(dst)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    cap = cv2.VideoCapture(str(src))
    n = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            cx = float(np.interp(n / fps, times, track)) * w
            x = int(min(max(cx - cw / 2, 0), w - cw))
            enc.stdin.write(np.ascontiguousarray(frame[:, x:x + cw]).tobytes())
            n += 1
    finally:
        cap.release()
        enc.stdin.close()
        err = enc.stderr.read().decode(errors="replace")
        enc.wait()
    if enc.returncode != 0:
        raise RuntimeError(f"ffmpeg (reenquadramento) falhou: {err[-600:]}")
    return "face"


def reframe(src: Path, dst: Path, mode: str = "face", log=None) -> str:
    if mode == "center":
        reframe_center(src, dst)
        return "center"
    if mode == "blur":
        reframe_blur(src, dst)
        return "blur"
    return reframe_face(src, dst, log)
