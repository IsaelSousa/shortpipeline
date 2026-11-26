// Personagem articulado em camadas: cabeça, tronco, braço/antebraço/mão, coxa/canela/pé, olhos, boca, cabelo
// e acessórios, cada um girando no seu pivô. O desenho é feito num personagem de 175 unidades de altura e
// escalado pela altura real (metros × unidades por metro).
import { clamp, invLerp, lerp, noise1, roundRect, shade, window01 } from './util.js';

const P = { hip: 88, shoulder: 146, neck: 150, head: 162, headR: 14, thigh: 45, shin: 43, upper: 30, fore: 28 };
export const WALK_SPEED = 1.35; // m/s
export const RUN_SPEED = 4.2;

export const DEFAULT_LOOK = {
  skin: '#E8B48F', hair: '#3B2A20', hair_style: 'short', shirt: '#3B82F6', pants: '#1F2937', shoes: '#111827',
  build: 'regular', height: 1.75, accessories: [],
};

const MOVES = new Set(['walk', 'run']);

/** Posição x, direção e a ação ativa do personagem no tempo t (segundos da cena). */
export function characterState(ch, t, upm) {
  let x = ch.x;
  let facing = ch.facing || 1;
  let active = null;
  const actions = [...(ch.actions || [])].sort((a, b) => a.start - b.start);
  let traveled = 0;
  for (const a of actions) {
    if (t < a.start) break;
    const end = a.end ?? a.start + 1.2;
    if (MOVES.has(a.type)) {
      const speed = (a.type === 'run' ? RUN_SPEED : WALK_SPEED) * upm;
      const to = a.to_x ?? x + speed * (end - a.start) * facing;
      if (to !== x) facing = Math.sign(to - x);
      const p = invLerp(a.start, end, t);
      const nx = lerp(x, to, p);
      traveled += Math.abs(nx - x);
      x = nx;
      if (t < end) active = { ...a, traveled, distance: Math.abs(to - x) };
    } else {
      if (a.facing) facing = a.facing;
      if (t < end || a.hold) active = { ...a, local: t - a.start, end };
    }
  }
  return { x, facing, active, traveled };
}

function pose(state, t, ch, upm) {
  const a = state.active;
  const seed = ch.id || 'c';
  // idle: respiração e peso mudando de perna, sempre um pouco vivo
  const breath = Math.sin(t * 2.1) * 0.8;
  const sway = noise1(seed, t * 0.4) * 0.05;
  const p = {
    lean: sway * 0.4, bob: breath * 0.4, hipF: 0.03 + sway, hipB: -0.03 + sway, kneeF: 0.05, kneeB: 0.05,
    shF: 0.08 + Math.sin(t * 1.3) * 0.03, shB: -0.06 - Math.sin(t * 1.3) * 0.03, elF: 0.25, elB: 0.2,
    headTilt: noise1(seed + 'h', t * 0.3) * 0.05, look: { x: 0, y: 0 }, expression: ch.expression || 'neutral',
    mouth: 0, hop: 0,
  };
  if (!a) return p;
  if (MOVES.has(a.type)) {
    const run = a.type === 'run';
    const stride = (run ? 1.6 : 0.78) * upm * (ch.look?.height || 1.75) / 1.75;
    const ph = (a.traveled / stride) * Math.PI;
    const s = Math.sin(ph);
    const amp = run ? 0.75 : 0.42;
    p.hipF = amp * s; p.hipB = -amp * s;
    p.kneeF = (run ? 1.3 : 0.5) * Math.max(0, -Math.cos(ph)) + 0.08;
    p.kneeB = (run ? 1.3 : 0.5) * Math.max(0, Math.cos(ph)) + 0.08;
    p.shF = -(run ? 0.85 : 0.35) * s; p.shB = (run ? 0.85 : 0.35) * s;
    p.elF = run ? 1.45 : 0.3 + 0.15 * Math.max(0, s); p.elB = run ? 1.45 : 0.3 + 0.15 * Math.max(0, -s);
    p.lean = run ? 0.2 : 0.04;
    p.bob = -Math.abs(Math.cos(ph)) * (run ? 6 : 3);
    p.expression = a.expression || (run ? 'scared' : p.expression);
    return p;
  }
  const k = a.local;
  const into = window01(k, 0, 0.35, 'back');
  if (a.type === 'reaction') {
    const kind = a.style || 'surprised';
    const startle = window01(k, 0, 0.18, 'out') * (1 - window01(k, 0.5, 0.6));
    p.hop = startle * 10;
    if (kind === 'jump_back') {
      p.lean = lerp(p.lean, -0.25, into);
      p.shF = lerp(p.shF, 2.5, into); p.shB = lerp(p.shB, 2.2, into); p.elF = p.elB = lerp(0.2, 0.5, into);
      p.kneeF = p.kneeB = lerp(0.05, 0.35, into); p.hipF = lerp(p.hipF, 0.25, into); p.hipB = lerp(p.hipB, -0.15, into);
    } else if (kind === 'cover') {
      p.lean = lerp(p.lean, 0.15, into);
      p.shF = lerp(p.shF, 2.9, into); p.shB = lerp(p.shB, 2.7, into); p.elF = p.elB = lerp(0.2, 1.9, into);
      p.kneeF = p.kneeB = lerp(0.05, 0.5, into);
    } else {
      p.lean = lerp(p.lean, -0.1, into);
      p.shF = lerp(p.shF, 1.0, into); p.shB = lerp(p.shB, -0.9, into); p.elF = p.elB = lerp(0.2, 1.2, into);
    }
    p.expression = a.expression || (kind === 'cover' ? 'scared' : 'surprised');
  } else if (a.type === 'look_up') {
    p.headTilt = lerp(p.headTilt, -0.35, into);
    p.look = { x: 0.3, y: -1 };
    p.expression = a.expression || 'worried';
  } else if (a.type === 'use_phone') {
    p.headTilt = lerp(p.headTilt, 0.24, into);
    p.look = { x: 0.65, y: 0.8 };
    p.shF = lerp(p.shF, 0.40, into);
    p.elF = lerp(p.elF, 1.25, into);
    p.phone = true;
  } else if (a.type === 'point') {
    p.shF = lerp(p.shF, a.up ? 2.4 : 1.6, into); p.elF = lerp(p.elF, 0.05, into);
    p.expression = a.expression || 'neutral';
  } else if (a.type === 'talk') {
    p.mouth = 0.5 + 0.5 * Math.sin(k * 17) * Math.sin(k * 5.3);
    p.shF = lerp(p.shF, 0.7 + Math.sin(k * 3) * 0.2, into); p.elF = lerp(p.elF, 1.1, into);
    p.expression = a.expression || 'smile';
  } else if (a.type === 'shrug') {
    p.shF = lerp(p.shF, 0.7, into); p.shB = lerp(p.shB, -0.7, into); p.elF = p.elB = lerp(0.2, 1.7, into);
    p.headTilt = lerp(p.headTilt, 0.15, into);
    p.expression = a.expression || 'worried';
  } else if (a.type === 'expression') {
    p.expression = a.expression || 'neutral';
  }
  return p;
}

function limb(ctx, x, y, a1, a2, l1, l2, w1, w2, color, endFn) {
  // a1/a2: ângulos a partir da vertical para baixo; positivo = para a frente
  const x1 = x + Math.sin(a1) * l1;
  const y1 = y + Math.cos(a1) * l1;
  const x2 = x1 + Math.sin(a2) * l2;
  const y2 = y1 + Math.cos(a2) * l2;
  ctx.strokeStyle = color;
  ctx.lineCap = 'round';
  ctx.lineWidth = w1;
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x1, y1); ctx.stroke();
  ctx.lineWidth = w2;
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  if (endFn) endFn(x2, y2, a2);
}

function drawHead(ctx, look, p, t, seed) {
  const r = P.headR;
  const blinkPhase = (t + (seed % 997) / 331) % 3.7;
  const blink = blinkPhase < 0.12 ? 0.15 : 1;
  // pescoço
  ctx.fillStyle = shade(look.skin, -0.08);
  ctx.fillRect(-3.5, -P.neck - 4, 7, 8);
  ctx.save();
  ctx.translate(0, -P.head);
  ctx.rotate(p.headTilt);
  // cabelo de trás
  ctx.fillStyle = look.hair;
  if (look.hair_style === 'long') { roundRect(ctx, -r - 1, -r - 1, r * 2 + 2, r * 2.6, 9); ctx.fill(); }
  if (look.hair_style === 'bun') { ctx.beginPath(); ctx.arc(-r * 0.7, -r * 0.9, 6, 0, Math.PI * 2); ctx.fill(); }
  // rosto
  ctx.fillStyle = look.skin;
  ctx.beginPath(); ctx.ellipse(0, 0, r * 0.92, r, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = shade(look.skin, -0.12);
  ctx.beginPath(); ctx.ellipse(-r * 0.75, 1, 3, 4, 0, 0, Math.PI * 2); ctx.fill(); // orelha
  // cabelo da frente
  ctx.fillStyle = look.hair;
  if (look.hair_style !== 'bald') {
    ctx.beginPath();
    ctx.ellipse(-1, -r * 0.45, r * 0.98, r * 0.62, 0, Math.PI, Math.PI * 2);
    ctx.fill();
    if (look.hair_style === 'curly') {
      for (let i = 0; i < 6; i++) { ctx.beginPath(); ctx.arc(-r + i * 5.4, -r * 0.62, 4.6, 0, Math.PI * 2); ctx.fill(); }
    }
    if (look.hair_style === 'short' || look.hair_style === 'curly') { ctx.fillRect(-r * 0.95, -r * 0.5, 5, 9); }
  }
  // olhos (olham para p.look)
  const ex = 5.2 + p.look.x * 1.5;
  const ey = -1.5 + p.look.y * 1.6;
  const wide = p.expression === 'surprised' || p.expression === 'scared' ? 1.35 : 1;
  ctx.fillStyle = '#FFFFFF';
  for (const dx of [0, 7.5]) {
    ctx.beginPath(); ctx.ellipse(dx + 1, -2, 2.9 * wide, 3.3 * wide * blink, 0, 0, Math.PI * 2); ctx.fill();
  }
  ctx.fillStyle = '#1B1B1F';
  for (const dx of [0, 7.5]) {
    ctx.beginPath(); ctx.ellipse(dx + ex - 4.2, ey, 1.6, 1.9 * blink, 0, 0, Math.PI * 2); ctx.fill();
  }
  // sobrancelhas
  ctx.strokeStyle = shade(look.hair, -0.2);
  ctx.lineWidth = 1.6;
  const brow = { surprised: -3, scared: -2.5, worried: -1.5, smile: -0.5, neutral: 0 }[p.expression] ?? 0;
  const tilt = p.expression === 'worried' || p.expression === 'scared' ? 1.6 : 0;
  ctx.beginPath(); ctx.moveTo(-1.5, -7 + brow + tilt); ctx.lineTo(3.5, -7.5 + brow); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(6, -7.5 + brow); ctx.lineTo(11, -7 + brow + tilt); ctx.stroke();
  // boca
  ctx.fillStyle = '#7A2E2E';
  ctx.strokeStyle = '#7A2E2E';
  ctx.lineWidth = 1.6;
  const open = Math.max(p.mouth, p.expression === 'surprised' ? 0.9 : p.expression === 'scared' ? 0.7 : 0);
  if (open > 0.1) {
    ctx.beginPath(); ctx.ellipse(6, 7, 2.6, 1 + open * 2.6, 0, 0, Math.PI * 2); ctx.fill();
  } else if (p.expression === 'smile') {
    ctx.beginPath(); ctx.arc(6, 4.5, 3.6, 0.2, Math.PI - 0.2); ctx.stroke();
  } else if (p.expression === 'worried') {
    ctx.beginPath(); ctx.arc(6, 10, 3, Math.PI + 0.4, -0.4); ctx.stroke();
  } else {
    ctx.beginPath(); ctx.moveTo(3.5, 7); ctx.lineTo(8.5, 7); ctx.stroke();
  }
  // acessórios do rosto
  const acc = look.accessories || [];
  if (acc.includes('glasses')) {
    ctx.strokeStyle = '#111827'; ctx.lineWidth = 1.3;
    for (const dx of [1, 8.5]) { ctx.beginPath(); ctx.arc(dx, -2, 4, 0, Math.PI * 2); ctx.stroke(); }
    ctx.beginPath(); ctx.moveTo(5, -2); ctx.lineTo(4.5, -2); ctx.stroke();
  }
  if (acc.includes('cap') || look.hair_style === 'cap') {
    ctx.fillStyle = look.cap || '#DC2626';
    ctx.beginPath(); ctx.ellipse(0, -r * 0.5, r, r * 0.7, 0, Math.PI, Math.PI * 2); ctx.fill();
    roundRect(ctx, 2, -r * 0.62, r * 1.2, 4, 2); ctx.fill();
  }
  if (acc.includes('headphones')) {
    ctx.strokeStyle = '#111827'; ctx.lineWidth = 2.4;
    ctx.beginPath(); ctx.arc(0, -1, r + 1, Math.PI * 1.05, Math.PI * 1.95); ctx.stroke();
    ctx.fillStyle = '#111827'; roundRect(ctx, -r - 3, -4, 6, 10, 2); ctx.fill();
  }
  ctx.restore();
}

/** Desenha o personagem com os pés em (x, groundY). `scale` multiplica a altura (perspectiva 2.5D). */
export function drawCharacter(ctx, ch, t, upm) {
  const look = { ...DEFAULT_LOOK, ...(ch.look || {}) };
  const state = characterState(ch, t, upm);
  const p = pose(state, t, ch, upm);
  const heightUnits = look.height * upm * (ch.scale || 1);
  const k = heightUnits / 175;
  const widthMul = { slim: 0.86, regular: 1, broad: 1.2 }[look.build] || 1;
  const y = ch.y - p.hop * k;
  // sombra no chão (diminui no pulo)
  ctx.save();
  const shadowWidth = 30 * (1 - clamp(p.hop / 30));
  ctx.translate(state.x, ch.y + 2 * k);
  ctx.scale(k, k * 0.24);
  const shadow = ctx.createRadialGradient(0, 0, 1, 0, 0, shadowWidth);
  shadow.addColorStop(0, 'rgba(17,24,39,0.38)');
  shadow.addColorStop(1, 'rgba(17,24,39,0)');
  ctx.fillStyle = shadow;
  ctx.fillRect(-shadowWidth, -shadowWidth, shadowWidth * 2, shadowWidth * 2);
  ctx.restore();

  ctx.save();
  ctx.translate(state.x, y);
  ctx.scale(k * state.facing, k);
  ctx.translate(0, p.bob);
  const hipY = -P.hip;
  const shY = -P.shoulder;
  const back = shade(look.skin, -0.12);
  const shoe = (color) => (x, yy, ang) => {
    ctx.save(); ctx.translate(x, yy); ctx.rotate(-ang * 0.25);
    ctx.fillStyle = color; roundRect(ctx, -5, -3, 17, 7, 3); ctx.fill(); ctx.restore();
  };
  const hand = (color) => (x, yy) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, yy, 4.2, 0, Math.PI * 2); ctx.fill(); };

  // perna e braço de trás (mais escuros: dá profundidade)
  limb(ctx, -2, hipY, p.hipB, p.hipB - p.kneeB, P.thigh, P.shin, 13, 11, shade(look.pants, -0.25), shoe(shade(look.shoes, -0.2)));
  ctx.save();
  ctx.rotate(p.lean);
  limb(ctx, -4, shY + 4, p.shB, p.shB + p.elB, P.upper, P.fore, 9, 8, shade(look.shirt, -0.25), hand(back));
  if ((look.accessories || []).includes('backpack')) {
    ctx.fillStyle = shade(look.backpack || '#F59E0B', -0.05);
    roundRect(ctx, -26, shY + 2, 14, 42, 5); ctx.fill();
  }
  ctx.restore();

  // tronco
  ctx.save();
  ctx.rotate(p.lean);
  const tw = 30 * widthMul;
  ctx.fillStyle = look.pants;
  roundRect(ctx, -tw / 2, hipY - 10, tw, 18, 6); ctx.fill();
  ctx.fillStyle = look.shirt;
  roundRect(ctx, -tw / 2 - 1, shY - 2, tw + 2, P.shoulder - P.hip + 6, 11); ctx.fill();
  ctx.fillStyle = 'rgba(255,255,255,0.12)';
  roundRect(ctx, tw * 0.05, shY + 2, tw * 0.35, P.shoulder - P.hip - 8, 8); ctx.fill();
  drawHead(ctx, look, p, t, (ch.id || '').length * 131);
  ctx.restore();

  // perna e braço da frente
  limb(ctx, 3, hipY, p.hipF, p.hipF - p.kneeF, P.thigh, P.shin, 13, 11, look.pants, shoe(look.shoes));
  ctx.save();
  ctx.rotate(p.lean);
  const frontHand = hand(look.skin);
  limb(ctx, 5, shY + 4, p.shF, p.shF + p.elF, P.upper, P.fore, 9.5, 8.5, look.shirt, (x, yy) => {
    if (p.phone) {
      ctx.save();
      ctx.translate(x + 2, yy - 3);
      ctx.rotate(-0.24);
      ctx.fillStyle = '#172333';
      roundRect(ctx, -3.8, -12, 8.5, 16, 2); ctx.fill();
      ctx.fillStyle = '#87C6DA';
      roundRect(ctx, -2.7, -10.5, 6.3, 11, 1); ctx.fill();
      ctx.restore();
    }
    frontHand(x, yy);
  });
  ctx.restore();
  ctx.restore();
  return { x: state.x, y: ch.y, top: ch.y - heightUnits, height: heightUnits };
}
