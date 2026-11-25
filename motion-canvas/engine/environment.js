// Cenários em camadas com parallax. O mundo tem o chão em y = 0 (para cima é negativo) e cada camada se move
// com a câmera multiplicada pelo seu fator de profundidade: 0 = infinito (céu), 1 = plano da ação, >1 = frente.
import { lerp, rng, roundRect, shade } from './util.js';

export const FLOOR_M = 3.2; // altura de um andar

const SKIES = {
  day: ['#7CC4F2', '#CDEBFA'], sunset: ['#F28C6B', '#FBD38D'], night: ['#0F1B3D', '#2B3A67'], overcast: ['#9AA9B8', '#D3DBE3'],
};

export const PALETTE = {
  building: ['#E9D8C4', '#D9C2A7', '#C8D3DC', '#E4C9B5', '#BFC9D6', '#D6D1C4'],
  window: '#8FB7D6', windowLit: '#FCE7A6', frame: '#F7F2EA', road: '#4B5563', sidewalk: '#CBD5E1', curb: '#94A3B8',
  grass: '#7BC67E', tree: '#3F9B57', trunk: '#8B5E3C', hill: ['#9AD29C', '#76B97C', '#5FA46B'], wall: '#F3E7D3',
  floor: '#C9A27E', accent: '#F97316',
};

/** Aplica a transformação da câmera para uma camada de profundidade `depth`. */
export function layerTransform(ctx, cam, depth, W, H) {
  const z = 1 + (cam.zoom - 1) * depth;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.translate(W / 2 + cam.shakeX * depth, H / 2 + cam.shakeY * depth);
  ctx.rotate(cam.roll * depth);
  ctx.scale(z * cam.base, z * cam.base);
  ctx.translate(-cam.x * depth, -cam.y * depth);
}

function sky(ctx, env, cam, W, H, t) {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  const [top, bottom] = SKIES[env.time_of_day] || SKIES.day;
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, top);
  g.addColorStop(1, bottom);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  // sol ou lua, quase parados
  const night = env.time_of_day === 'night';
  ctx.fillStyle = night ? '#F1F5F9' : env.time_of_day === 'sunset' ? '#FDBA74' : '#FFF4C2';
  ctx.globalAlpha = 0.9;
  ctx.beginPath();
  ctx.arc(W * 0.78 - cam.x * 0.01, H * 0.16 - cam.y * 0.01, W * 0.06, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
  // nuvens em deriva lenta
  const r = rng('clouds' + (env.seed || ''));
  ctx.fillStyle = night ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.85)';
  for (let i = 0; i < 5; i++) {
    const x = ((r() * W * 1.6 + t * (8 + r() * 10) - cam.x * 0.05) % (W * 1.6)) - W * 0.3;
    const y = H * (0.08 + r() * 0.3) - cam.y * 0.04;
    const s = W * (0.08 + r() * 0.08);
    for (const [dx, dy, rr] of [[0, 0, 1], [s * 0.8, -s * 0.25, 0.8], [s * 1.5, 0, 0.9], [s * 0.7, s * 0.15, 0.9]]) {
      ctx.beginPath(); ctx.arc(x + dx, y + dy, s * 0.5 * rr, 0, Math.PI * 2); ctx.fill();
    }
  }
  if (night) {
    const rs = rng('stars');
    ctx.fillStyle = 'rgba(255,255,255,0.7)';
    for (let i = 0; i < 60; i++) ctx.fillRect(rs() * W, rs() * H * 0.6, 2, 2);
  }
}

function skyline(ctx, env, cam, W, H, depth, color, seed, maxH, upm) {
  layerTransform(ctx, cam, depth, W, H);
  ctx.fillStyle = color;
  // vãos fixos de 1,1 m, cada um com a sua semente: o horizonte não muda quando a câmera anda
  const slot = 1.1 * upm;
  const span = (W * 2) / (cam.base * Math.max(0.3, 1 + (cam.zoom - 1) * depth));
  const first = Math.floor((cam.x * depth - span) / slot);
  const last = Math.ceil((cam.x * depth + span) / slot);
  for (let i = first; i <= last; i++) {
    const rr = rng(seed + ':' + i);
    const w = slot * (0.7 + rr() * 0.5);
    const h = maxH * (0.35 + rr() * 0.65);
    const x = i * slot;
    ctx.fillRect(x, -h, w + 2, h + 60 * upm);
    if (rr() > 0.6) ctx.fillRect(x + w * 0.4, -h - 0.2 * upm, 8, 0.2 * upm); // antena
  }
}

function building(ctx, x, w, floors, upm, color, seed, lit) {
  const fh = FLOOR_M * upm;
  const h = floors * fh;
  const r = rng(seed);
  ctx.fillStyle = color;
  ctx.fillRect(x, -h, w, h);
  // lateral em perspectiva (2.5D): uma faixa mais escura
  ctx.fillStyle = shade(color, -0.16);
  ctx.beginPath();
  ctx.moveTo(x + w, -h); ctx.lineTo(x + w + w * 0.08, -h + w * 0.05); ctx.lineTo(x + w + w * 0.08, 0); ctx.lineTo(x + w, 0);
  ctx.closePath(); ctx.fill();
  // cornija
  ctx.fillStyle = shade(color, -0.08);
  ctx.fillRect(x - 6, -h - 14, w + 12, 18);
  const cols = Math.max(2, Math.round(w / (1.6 * upm)));
  const ww = (w / cols) * 0.55;
  for (let f = 0; f < floors; f++) {
    const fy = -h + f * fh;
    ctx.fillStyle = shade(color, -0.05);
    ctx.fillRect(x, fy + fh - 6, w, 6);
    if (f === floors - 1) continue; // térreo tem porta
    for (let c = 0; c < cols; c++) {
      const wx = x + (c + 0.5) * (w / cols) - ww / 2;
      const wy = fy + fh * 0.22;
      const whh = fh * 0.5;
      ctx.fillStyle = PALETTE.frame;
      ctx.fillRect(wx - 5, wy - 5, ww + 10, whh + 10);
      ctx.fillStyle = lit && r() > 0.55 ? PALETTE.windowLit : PALETTE.window;
      ctx.fillRect(wx, wy, ww, whh);
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.beginPath(); ctx.moveTo(wx, wy + whh * 0.7); ctx.lineTo(wx + ww * 0.45, wy); ctx.lineTo(wx + ww * 0.65, wy); ctx.lineTo(wx, wy + whh); ctx.fill();
      if (r() > 0.82) { // ar-condicionado decorativo na fachada
        ctx.fillStyle = '#E5E7EB'; ctx.fillRect(wx + ww * 0.1, wy + whh + 8, ww * 0.8, fh * 0.16);
        ctx.fillStyle = '#9CA3AF'; ctx.fillRect(wx + ww * 0.1, wy + whh + 8 + fh * 0.16, ww * 0.8, 4);
      }
    }
  }
  // porta do térreo
  ctx.fillStyle = shade(color, -0.35);
  ctx.fillRect(x + w / 2 - 0.6 * upm, -fh * 0.85, 1.2 * upm, fh * 0.85);
  return h;
}

function lamp(ctx, x, upm, t, night) {
  const h = 4.6 * upm;
  ctx.fillStyle = '#374151';
  ctx.fillRect(x - 5, -h, 10, h);
  ctx.fillRect(x - 5, -h, 0.9 * upm, 8);
  ctx.fillStyle = night ? '#FDE68A' : '#E5E7EB';
  roundRect(ctx, x + 0.75 * upm, -h - 4, 0.45 * upm, 18, 6); ctx.fill();
  void t;
}

function tree(ctx, x, upm, s, sway) {
  ctx.fillStyle = PALETTE.trunk;
  ctx.fillRect(x - 0.12 * upm * s, -2.6 * upm * s, 0.24 * upm * s, 2.6 * upm * s);
  ctx.fillStyle = PALETTE.tree;
  for (const [dx, dy, r] of [[0, -3.6, 1.2], [-0.8, -2.9, 0.9], [0.8, -2.9, 0.9], [0, -2.6, 1]]) {
    ctx.beginPath(); ctx.arc(x + (dx + sway) * upm * s, dy * upm * s, r * upm * s, 0, Math.PI * 2); ctx.fill();
  }
  ctx.fillStyle = 'rgba(255,255,255,0.12)';
  ctx.beginPath(); ctx.arc(x + (0.35 + sway) * upm * s, -4 * upm * s, 0.5 * upm * s, 0, Math.PI * 2); ctx.fill();
}

function city(ctx, env, cam, W, H, t, upm) {
  const E = 100 * upm;
  const night = env.time_of_day === 'night';
  skyline(ctx, env, cam, W, H, 0.2, night ? '#1E2A4A' : '#B8CCDD', 'far', 6.5 * upm, upm);
  skyline(ctx, env, cam, W, H, 0.45, night ? '#25335A' : '#9DB4C8', 'mid', 9.5 * upm, upm);
  layerTransform(ctx, cam, 1, W, H);
  // prédios da rua (o "hero" pode ter andares e posição definidos pela cena)
  const hero = env.hero_building;
  const r = rng('street' + (env.seed || ''));
  let x = -40 * upm;
  while (x < 40 * upm) {
    const w = (6 + r() * 6) * upm;
    let floors = Math.round(3 + r() * 5);
    if (hero && x <= hero.x && hero.x < x + w) floors = hero.floors || 10;
    building(ctx, x, w - 14, floors, upm, PALETTE.building[Math.floor(r() * PALETTE.building.length)], 'b' + x, night);
    x += w;
  }
  // calçada, meio-fio e rua
  const sw = 3.2 * upm;
  ctx.fillStyle = PALETTE.sidewalk;
  ctx.fillRect(-E, 0, 2 * E, sw);
  ctx.fillStyle = 'rgba(0,0,0,0.06)';
  for (let px = -E; px < E; px += 1.2 * upm) ctx.fillRect(px, 0, 3, sw);
  ctx.fillStyle = PALETTE.curb;
  ctx.fillRect(-E, sw, 2 * E, 0.25 * upm);
  ctx.fillStyle = PALETTE.road;
  ctx.fillRect(-E, sw + 0.25 * upm, 2 * E, E);
  ctx.fillStyle = '#F8FAFC';
  for (let px = -E; px < E; px += 3 * upm) ctx.fillRect(px, sw + 2.4 * upm, 1.6 * upm, 0.16 * upm);
  for (const lx of env.lamps || [-9, 9]) lamp(ctx, lx * upm, upm, t, night);
  for (const tx of env.trees || [-14, 15]) tree(ctx, tx * upm, upm, 1, Math.sin(t * 1.2 + tx) * 0.05);
}

function nature(ctx, env, cam, W, H, t, upm) {
  const E = 100 * upm;
  const hills = PALETTE.hill;
  [0.2, 0.45, 0.7].forEach((depth, i) => {
    layerTransform(ctx, cam, depth, W, H);
    ctx.fillStyle = hills[i];
    ctx.beginPath();
    ctx.moveTo(-E, E);
    for (let x = -E; x <= E; x += 200) {
      ctx.lineTo(x, -(Math.sin(x / (900 + i * 300) + i) * 0.5 + 0.7) * (900 - i * 200));
    }
    ctx.lineTo(E, E);
    ctx.fill();
  });
  layerTransform(ctx, cam, 1, W, H);
  ctx.fillStyle = PALETTE.grass;
  ctx.fillRect(-E, 0, 2 * E, E);
  ctx.fillStyle = shade(PALETTE.grass, -0.12);
  const r = rng('grass');
  for (let i = 0; i < 160; i++) ctx.fillRect(-E / 2 + r() * E, r() * 2 * upm, 6, 18);
  for (const tx of env.trees || [-12, -5, 7, 13]) tree(ctx, tx * upm, upm, 1.2, Math.sin(t * 1.4 + tx) * 0.06);
}

function room(ctx, env, cam, W, H, t, upm) {
  const E = 100 * upm;
  layerTransform(ctx, cam, 1, W, H);
  ctx.fillStyle = env.wall || PALETTE.wall;
  ctx.fillRect(-E, -E, 2 * E, E);
  ctx.fillStyle = shade(env.wall || PALETTE.wall, -0.06);
  ctx.fillRect(-E, -0.12 * upm, 2 * E, 0.12 * upm); // rodapé
  // janela com céu
  const wx = (env.window_x ?? 2) * upm;
  ctx.fillStyle = PALETTE.frame; ctx.fillRect(wx - 12, -2.4 * upm - 12, 1.8 * upm + 24, 1.4 * upm + 24);
  ctx.fillStyle = '#A5D8F3'; ctx.fillRect(wx, -2.4 * upm, 1.8 * upm, 1.4 * upm);
  ctx.fillStyle = PALETTE.frame; ctx.fillRect(wx + 0.9 * upm - 5, -2.4 * upm, 10, 1.4 * upm);
  // quadro
  ctx.fillStyle = '#8B5E3C'; ctx.fillRect(-2.6 * upm, -2.3 * upm, 1.2 * upm, 0.9 * upm);
  ctx.fillStyle = '#FCD34D'; ctx.fillRect(-2.5 * upm, -2.2 * upm, 1.0 * upm, 0.7 * upm);
  // piso de tábuas
  ctx.fillStyle = env.floor || PALETTE.floor;
  ctx.fillRect(-E, 0, 2 * E, E);
  ctx.fillStyle = 'rgba(0,0,0,0.07)';
  for (let y = 0.4; y < 12; y += 0.55) ctx.fillRect(-E, y * upm, 2 * E, 3);
  void t;
}

function studio(ctx, env, cam, W, H, t, upm) {
  const E = 100 * upm;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  const g = ctx.createRadialGradient(W / 2, H * 0.45, 0, W / 2, H * 0.45, H * 0.8);
  g.addColorStop(0, env.color || '#1E293B');
  g.addColorStop(1, shade(env.color || '#1E293B', -0.55));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  layerTransform(ctx, cam, 1, W, H);
  ctx.strokeStyle = 'rgba(255,255,255,0.07)';
  ctx.lineWidth = 2;
  for (let x = -E; x <= E; x += upm) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x * 1.6, 8 * upm); ctx.stroke(); }
  for (let y = 0; y < 8; y += 0.8) { ctx.beginPath(); ctx.moveTo(-E, y * upm); ctx.lineTo(E, y * upm); ctx.stroke(); }
  void t;
}

export const ENVIRONMENTS = { city, street: city, nature, room, studio };

export function drawEnvironment(ctx, env, cam, W, H, t, upm) {
  if (env.type !== 'studio') sky(ctx, env, cam, W, H, t);
  (ENVIRONMENTS[env.type] || city)(ctx, env, cam, W, H, t, upm);
}

/** Primeiro plano (passa mais rápido que a ação): dá a sensação de profundidade. */
export function drawForeground(ctx, env, cam, W, H, t, upm) {
  if (!env.foreground) return;
  layerTransform(ctx, cam, 1.35, W, H);
  ctx.fillStyle = 'rgba(30,41,59,0.85)';
  for (const fx of env.foreground_x || [-7, 8]) {
    if (env.type === 'nature') {
      ctx.fillStyle = 'rgba(47,111,63,0.9)';
      ctx.beginPath(); ctx.arc(fx * upm, 0.8 * upm, 1.6 * upm, 0, Math.PI * 2); ctx.fill();
    } else {
      ctx.fillRect(fx * upm, -6 * upm, 0.35 * upm, 9 * upm); // poste em primeiro plano
    }
  }
  void lerp; void t;
}
