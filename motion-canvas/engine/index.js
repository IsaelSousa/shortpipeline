// Motor de composição: interpreta o JSON de vídeo (schema em shortpipeline/motion/schema.py) e desenha qualquer
// quadro como função pura do tempo. Não há timers nem estado entre quadros: o quadro N sai sempre igual.
//
// Unidades do JSON: posições em metros (x para a direita, `height` para cima a partir do chão), tempos em
// segundos relativos ao início da cena, posições de tela em frações (0–1). A engine converte para unidades do
// mundo (upm = unidades por metro) no carregamento.
import { cameraAt, defaultStart, DESIGN } from './camera.js';
import { drawCaptions, groupWords } from './captions.js';
import { characterState, drawCharacter } from './character.js';
import { drawScreenEffect, drawWorldEffect, SCREEN_EFFECTS } from './effects.js';
import { drawEnvironment, drawForeground, layerTransform } from './environment.js';
import { ASSETS, drawObject, objectState } from './objects.js';
import { drawOverlay, project } from './overlays.js';
import { createThreeLayer } from './three-layer.js';
import { clamp, ease, lerp } from './util.js';

const DEFAULT_THEME = { accent: '#F97316', accent2: '#FDE047', locale: 'pt-BR' };

function warp(t, segments) {
  // câmera lenta: o tempo da animação anda `rate` vezes a velocidade real dentro de cada trecho
  let out = 0, last = 0;
  for (const s of [...(segments || [])].sort((a, b) => a.start - b.start)) {
    if (t <= s.start) break;
    out += s.start - last;
    const seg = Math.min(t, s.end) - s.start;
    out += seg * s.rate;
    last = Math.min(t, s.end);
  }
  return out + Math.max(0, t - last);
}

function normalize(spec) {
  const upm = spec.upm || 200;
  const decl = Object.fromEntries((spec.characters || []).map((c) => [c.id, c]));
  const fx = (f, size) => (f == null ? undefined : f * size);
  const scenes = (spec.scenes || []).map((sc) => {
    const characters = (sc.characters || []).map((c) => ({
      ...c, id: c.ref, look: { ...(decl[c.ref]?.look || {}), ...(c.look || {}) },
      x: (c.x || 0) * upm, y: -(c.height || 0) * upm,
      actions: (c.actions || []).map((a) => ({ ...a, to_x: a.to_x == null ? undefined : a.to_x * upm })),
    }));
    const objects = (sc.objects || []).map((o) => {
      const [wm, hm] = o.size || ASSETS[o.asset]?.size || [0.6, 0.6];
      const h = hm * upm * (o.scale || 1);
      return {
        ...o, x: (o.x || 0) * upm, y: -(o.height || 0) * upm - h / 2, size: [wm, hm],
        actions: (o.actions || []).map((a) => ({
          ...a, to_x: a.to_x == null ? undefined : a.to_x * upm,
          to_y: a.to_height == null ? undefined : -a.to_height * upm - h / 2,
          ground_y: -(a.ground || 0) * upm,
        })),
      };
    });
    const camPoint = (c) => (c ? { ...c, x: c.x == null ? undefined : c.x * upm, y: c.height == null ? undefined : -c.height * upm } : c);
    const cam = sc.camera || {};
    const start = { ...defaultStart(), ...Object.fromEntries(Object.entries(camPoint(cam.start || {})).filter(([, v]) => v !== undefined)) };
    const moves = (cam.moves || []).map((m) => Object.fromEntries(Object.entries(camPoint(m)).filter(([, v]) => v !== undefined)));
    const env = { ...(sc.environment || { type: 'city' }) };
    if (env.hero_building) env.hero_building = { ...env.hero_building, x: env.hero_building.x * upm };
    // posições de tela em frações; só a seta tem pontas (from/to) que podem ser posições
    const point = (p) => (p && typeof p === 'object' && !p.target ? { x: p.x * DESIGN.W, y: p.y * DESIGN.H } : p);
    const screen = (o) => ({ ...o, x: fx(o.x, DESIGN.W), y: fx(o.y, DESIGN.H),
      ...(o.type === 'arrow' ? { from: point(o.from), to: point(o.to) } : {}) });
    const effects = (sc.effects || []).map((e) => (SCREEN_EFFECTS.includes(e.type) ? e
      : { ...e, x: (e.x || 0) * upm, y: -(e.height || 0) * upm }));
    return { ...sc, characters, objects, camera: { start, moves }, environment: env, overlays: (sc.overlays || []).map(screen), effects };
  });
  return { ...spec, upm, scenes, theme: { ...DEFAULT_THEME, ...(spec.theme || {}) },
           captionGroups: groupWords(spec.captions?.words || [], spec.captions?.max_words || 3) };
}

let SPEC = null;
let canvas = null;
let ctx = null;
let drawThreeLayer = null;

async function loadFonts(fonts) {
  for (const [name, url] of Object.entries(fonts || {})) {
    try {
      const face = new FontFace(name, `url(${url})`);
      await face.load();
      document.fonts.add(face);
    } catch (e) { console.warn('fonte não carregou', name, e); }
  }
}

export async function init(spec, { width, height } = {}) {
  SPEC = normalize(spec);
  canvas = document.createElement('canvas');
  canvas.width = width || spec.width || 1080;
  canvas.height = height || spec.height || 1920;
  document.body.appendChild(canvas);
  ctx = canvas.getContext('2d');
  await loadFonts(spec.fonts);
  return { scenes: SPEC.scenes.length, duration: duration() };
}

export function duration() {
  return Math.max(...SPEC.scenes.map((s) => s.end), 0);
}

function sceneAt(T) {
  const scenes = SPEC.scenes;
  return scenes.find((s) => T >= s.start && T < s.end) || scenes[scenes.length - 1];
}

/** Desenha o quadro do instante T (segundos do vídeo). Devolve o que foi desenhado, para a checagem. */
export function draw(T) {
  const W = canvas.width, H = canvas.height;
  const base = W / DESIGN.W;
  const sc = sceneAt(T);
  const local = T - sc.start;
  const t = warp(local, sc.time_warp);
  const upm = SPEC.upm;
  const theme = SPEC.theme;

  const cache = new Map();
  const resolve = (id, time = t) => {
    const key = id + '@' + time.toFixed(4);
    if (cache.has(key)) return cache.get(key);
    let out = null;
    const o = sc.objects.find((x) => x.id === id);
    if (o) {
      const s = objectState(o, time, upm);
      const prev = objectState(o, time - 1 / 60, upm);
      out = { ...s, vx: s.vx || (s.x - prev.x) * 60, vy: s.vy || (s.y - prev.y) * 60 };
    }
    const c = sc.characters.find((x) => x.id === id);
    if (c) {
      const s = characterState(c, time, upm);
      const prev = characterState(c, time - 1 / 60, upm);
      const hgt = (c.look.height || 1.75) * upm * (c.scale || 1);
      out = { x: s.x, y: c.y - hgt * 0.55, w: hgt * 0.35, h: hgt, vx: (s.x - prev.x) * 60, vy: 0 };
    }
    cache.set(key, out);
    return out;
  };

  const cam = cameraAt(sc.camera, t, resolve, W);
  // entrada da cena
  const enter = sc.enter || { type: 'cut' };
  const ep = ease('out', clamp(local / (enter.dur || 0.35)));
  if (enter.type === 'zoom') cam.zoom *= lerp(1.25, 1, ep);
  if (enter.type === 'whip' || enter.type === 'slide') cam.x += lerp((enter.dir || 1) * 3 * upm, 0, ep);

  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.filter = enter.type === 'whip' && ep < 1 ? `blur(${Math.round(lerp(16, 0, ep) * base)}px)` : 'none';
  drawEnvironment(ctx, sc.environment, cam, W, H, t, upm);

  layerTransform(ctx, cam, 1, W, H);
  const items = [
    ...sc.characters.map((c) => ({ kind: 'c', z: c.z || 0, y: c.y, el: c })),
    ...sc.objects.map((o) => ({ kind: 'o', z: o.z || 0, y: o.y, el: o })),
  ].sort((a, b) => a.z - b.z || a.y - b.y);
  const drawn = { characters: {}, objects: {} };
  for (const it of items) {
    layerTransform(ctx, cam, 1, W, H);
    if (it.kind === 'c') drawn.characters[it.el.id] = drawCharacter(ctx, it.el, t, upm);
    else drawn.objects[it.el.id] = drawObject(ctx, it.el, t, upm);
  }
  for (const e of sc.effects.filter((x) => !SCREEN_EFFECTS.includes(x.type))) {
    layerTransform(ctx, cam, 1, W, H);
    drawWorldEffect(ctx, e, t, resolve, upm);
  }
  drawForeground(ctx, sc.environment, cam, W, H, t, upm);
  ctx.filter = 'none';
  if (sc.layer_3d) {
    drawThreeLayer ??= createThreeLayer(W, H);
    drawThreeLayer(ctx, sc.layer_3d, t, local);
  }

  // tela: informativos, efeitos de tela e legendas (em coordenadas de design)
  ctx.setTransform(base, 0, 0, base, 0, 0);
  const boxes = [];
  // objetos importantes também reservam a área deles na tela (a legenda não os cobre)
  for (const o of sc.objects.filter((x) => x.important)) {
    const st = drawn.objects[o.id];
    if (!st || st.opacity <= 0) continue;
    const p = project(cam, st.x, st.y);
    const w = st.w * cam.zoom, h = st.h * cam.zoom;
    boxes.push({ x: p.x - w * 0.6, y: p.y - h * 0.6, w: w * 1.2, h: h * 1.2 });
  }
  for (const o of sc.overlays) drawOverlay(ctx, o, t, cam, resolve, upm, theme, boxes);
  for (const e of sc.effects.filter((x) => SCREEN_EFFECTS.includes(x.type))) drawScreenEffect(ctx, e, t);
  let caption = null;
  if (SPEC.captions?.enabled !== false) caption = drawCaptions(ctx, SPEC.captionGroups, T, SPEC.captions || {}, boxes, theme);
  if (enter.type === 'fade' && ep < 1) {
    ctx.globalAlpha = 1 - ep; ctx.fillStyle = '#000'; ctx.fillRect(0, 0, DESIGN.W, DESIGN.H); ctx.globalAlpha = 1;
  }
  ctx.restore();
  return { scene: sc.id, t, camera: { x: cam.x, y: cam.y, zoom: cam.zoom }, boxes, caption };
}

export function frameJPEG(T, quality = 0.9) {
  const info = draw(T);
  return { jpeg: canvas.toDataURL('image/jpeg', quality).split(',')[1], info };
}

window.SPEngine = { init, draw, frameJPEG, duration };
