// EXEMPLAR (excerpt of a finished 15s motion reel at 128 BPM, beat-grid style).
// Study the TECHNIQUES: easing, shape morphing, echoes, springs, closed-form physics, seeded rng,
// layered compositing. It uses global time t and a beat grid, while YOUR scenes receive
// section-local time lt and narration cues. Do not copy its look and do not import it.
const W = 1920, H = 1080, CX = W / 2, CY = H / 2;
const BPM = 128, B = 60 / BPM, BAR = 4 * B, DUR = 15;
const C = { ink: '#0d0d10', paper: '#f2eee6', red: '#ff3d1f', blue: '#2536ff', acid: '#d7ff3b' };
const DISPLAY = 'Anton', MONO = '"Space Mono", monospace';

// ---------- math ----------
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const inv = (a, b, x) => clamp((x - a) / (b - a));
const TAU = Math.PI * 2;
const E = {
  outExpo: t => t >= 1 ? 1 : 1 - Math.pow(2, -10 * t),
  inExpo: t => t <= 0 ? 0 : Math.pow(2, 10 * t - 10),
  inOutExpo: t => t <= 0 ? 0 : t >= 1 ? 1 : t < .5 ? Math.pow(2, 20 * t - 10) / 2 : (2 - Math.pow(2, -20 * t + 10)) / 2,
  outCubic: t => 1 - Math.pow(1 - t, 3),
  inCubic: t => t * t * t,
  inOutCubic: t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2,
  outQuart: t => 1 - Math.pow(1 - t, 4),
  outBack: (t, s = 1.9) => 1 + (s + 1) * Math.pow(t - 1, 3) + s * Math.pow(t - 1, 2),
  inBack: (t, s = 1.7) => (s + 1) * t * t * t - s * t * t,
  outElastic: t => t <= 0 ? 0 : t >= 1 ? 1 : Math.pow(2, -10 * t) * Math.sin((t * 10 - .75) * TAU / 3) + 1,
};
// damped spring: 0 → 1 with overshoot
const spring = (t, f = 3, d = 7) => t <= 0 ? 0 : 1 - Math.exp(-d * t) * Math.cos(f * TAU * t);
// impulse envelope that fires at t0 and decays
const hit = (t, t0, k = 8) => t < t0 ? 0 : Math.exp(-(t - t0) * k);
const bt = n => n * B;          // beat → seconds
const barT = n => n * BAR;      // bar → seconds
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

// ---------- canvases ----------
const out = document.getElementById('c'), ctx = out.getContext('2d');
const mk = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c; };
const sceneC = mk(), g = sceneC.getContext('2d');
const tintA = mk(), ta = tintA.getContext('2d'), tintB = mk(), tb = tintB.getContext('2d');
const grain = document.createElement('canvas'); grain.width = grain.height = 256;
{ const gc = grain.getContext('2d'), id = gc.createImageData(256, 256), r = rng(3);
  for (let i = 0; i < id.data.length; i += 4) { const v = r() * 255; id.data[i] = id.data[i + 1] = id.data[i + 2] = v; id.data[i + 3] = 255; }
  gc.putImageData(id, 0, 0); }
const grainPat = ctx.createPattern(grain, 'repeat');

// ---------- shape library (sampled perimeters so any shape morphs into any other) ----------
const NP = 180;
function polyPts(verts) {
  const segs = [], n = verts.length; let total = 0;
  for (let i = 0; i < n; i++) { const a = verts[i], b = verts[(i + 1) % n], l = Math.hypot(b[0] - a[0], b[1] - a[1]); segs.push([a, b, l]); total += l; }
  const pts = []; let si = 0, acc = 0;
  for (let k = 0; k < NP; k++) {
    const d = k / NP * total;
    while (acc + segs[si][2] < d) { acc += segs[si][2]; si++; }
    const [a, b, l] = segs[si], u = (d - acc) / l;
    pts.push([lerp(a[0], b[0], u), lerp(a[1], b[1], u)]);
  }
  return pts;
}
const regular = (n, r = 1, rot = -Math.PI / 2) => Array.from({ length: n }, (_, i) => [Math.cos(rot + i / n * TAU) * r, Math.sin(rot + i / n * TAU) * r]);
const star = (n, ri) => Array.from({ length: n * 2 }, (_, i) => { const a = -Math.PI / 2 + i / (n * 2) * TAU, r = i % 2 ? ri : 1; return [Math.cos(a) * r, Math.sin(a) * r]; });
const SHAPES = [
  Array.from({ length: NP }, (_, k) => { const a = -Math.PI / 2 + k / NP * TAU; return [Math.cos(a), Math.sin(a)]; }), // circle
  polyPts([[0, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]].map(([x, y]) => [x * .86, y * .86])),                        // square (starts top-center)
  polyPts(regular(3, 1.15, -Math.PI / 2).map(([x, y]) => [x, y + .18])),                                                 // triangle
  polyPts(star(5, .44).map(([x, y]) => [x * 1.12, y * 1.12])),                                                          // star
  polyPts([[0, -1], [.33, -1], [.33, -.33], [1, -.33], [1, .33], [.33, .33], [.33, 1], [-.33, 1], [-.33, .33], [-1, .33], [-1, -.33], [-.33, -.33], [-.33, -1]]), // plus
];
function morphPath(c, a, b, u, r, rot = 0, x = 0, y = 0) {
  const A = SHAPES[a], Bs = SHAPES[b], cs = Math.cos(rot), sn = Math.sin(rot);
  c.beginPath();
  for (let k = 0; k < NP; k++) {
    const px = lerp(A[k][0], Bs[k][0], u) * r, py = lerp(A[k][1], Bs[k][1], u) * r;
    const X = x + px * cs - py * sn, Y = y + px * sn + py * cs;
    k ? c.lineTo(X, Y) : c.moveTo(X, Y);
  }
  c.closePath();
}

// ---------- text helpers ----------
function font(c, px, fam = DISPLAY, w = '') { c.font = `${w} ${px}px ${fam}`; }
function monoLabel(c, s, x, y, px = 20, col = C.paper, align = 'left', track = 3) {
  font(c, px, MONO, '700'); c.fillStyle = col; c.textBaseline = 'alphabetic';
  if ('letterSpacing' in c) { c.letterSpacing = track + 'px'; c.textAlign = align; c.fillText(s, x, y); c.letterSpacing = '0px'; }
  else { c.textAlign = align; c.fillText(s, x, y); }
}
// text typing reveal with a block cursor
function typed(c, s, x, y, p, px = 20, col = C.paper, align = 'left') {
  const n = Math.floor(s.length * clamp(p)); const str = s.slice(0, n);
  monoLabel(c, str + (p > 0 && p < 1 ? '█' : ''), x, y, px, col, align);
}

// Wordmark "M◯TI◯N": O's are geometric rings. Returns glyph layout.
const WM = { size: 470, letters: 'MOTION'.split('') };
function wordLayout(c, size, gap = 14) {
  font(c, size); const ring = size * 0.365; const items = []; let x = 0;
  for (const ch of WM.letters) {
    const w = ch === 'O' ? ring * 2 : c.measureText(ch).width;
    items.push({ ch, x, w }); x += w + gap;
  }
  const total = x - gap; items.forEach(it => it.x -= total / 2);
  return { items, total, ring, cap: size * 0.735 };
}

/* =========================================================
   SCENES — each draws a full frame into g for global time t
   ========================================================= */
// 01 — ORIGIN: a heartbeat dot, anticipation, stretches into a line, splits into a grid, blinds to paper
function sOrigin(t) {
  g.fillStyle = C.ink; g.fillRect(-200, -200, W + 400, H + 400);
  const pulse = 1 + .55 * hit(t, 0, 9) + .45 * hit(t, bt(1), 9);
  let r = 16 * E.outBack(inv(0, .22, t), 3) * pulse;
  const tS = bt(2), tL = bt(3);
  // grid verticals
  for (let i = 1; i < 16; i++) {
    const p = E.outExpo(inv(tL + .05 + Math.abs(i - 8) * .018, tL + .45, t));
    if (p <= 0) continue;
    g.fillStyle = 'rgba(242,238,230,.18)';
    const len = H * p; g.fillRect(i * 120 - 1, CY - len / 2, 2, len);
  }
  if (t < tS - .12) { // heartbeat
    g.fillStyle = C.paper; g.beginPath(); g.arc(CX, CY, r, 0, TAU); g.fill();
    // sonar ring on each beat
    for (const t0 of [0, bt(1)]) { const p = inv(t0, t0 + .45, t); if (p > 0 && p < 1) { g.strokeStyle = `rgba(242,238,230,${1 - p})`; g.lineWidth = 2; g.beginPath(); g.arc(CX, CY, 16 + 160 * E.outExpo(p), 0, TAU); g.stroke(); } }
    return;
  }
  if (t < tS) { // anticipation squash
    const p = E.outCubic(inv(tS - .12, tS, t));
    g.fillStyle = C.paper; g.beginPath(); g.ellipse(CX, CY, 16 * (1 - .45 * p), 16 * (1 + .35 * p), 0, 0, TAU); g.fill(); return;
  }
  // stretch into a line, then split into 9 rules, which thicken into blinds
  const pS = E.outExpo(inv(tS, tS + .34, t));
  const half = lerp(10, 1100, pS), thick0 = lerp(26, 4, pS);
  for (let i = 0; i < 9; i++) {
    const k = i - 4;
    const sp = E.outExpo(inv(tL + Math.abs(k) * .02, tL + .38, t));
    const y = CY + k * 120 * sp;
    const bl = E.inOutCubic(inv(bt(3.5) + (8 - i) * .014, BAR - .02, t));
    const th = lerp(thick0, 122, bl);
    // leading-edge overshoot for the stretch (squash & stretch — thin in the middle, rounded ends)
    g.fillStyle = C.paper;
    g.beginPath(); g.roundRect(CX - half, y - th / 2, half * 2, th, Math.min(th / 2, 13 * (1 - bl))); g.fill();
  }
}

// 02 — MOTION wordmark: masked rises, squash wave, stacked echoes, letters fall, O becomes a portal
function sMotion(t) {
  const lt = t - barT(1);
  g.fillStyle = C.paper; g.fillRect(-200, -200, W + 400, H + 400);
  const L = wordLayout(g, WM.size);
  const baseY = CY + L.cap / 2;
  const portalIdx = 4;
  const tFall = bt(3), tZoom = bt(3) + .06;
  // zoom camera about portal O
  const zp = E.inExpo(inv(tZoom, BAR, lt));
  const zoom = 1 + zp * 26;
  const P = L.items[portalIdx]; const pcx = P.x + P.w / 2, pcy = baseY - L.cap / 2;
  const camX = lerp(0, -pcx, E.inOutCubic(inv(tZoom - .15, BAR, lt)));
  g.save();
  g.translate(CX, CY); g.scale(zoom, zoom); g.translate(camX, lerp(0, -(pcy - CY), E.inOutCubic(inv(tZoom - .15, BAR, lt)))); g.translate(0, -CY);
  // stacked outline echoes (beat 2)
  const echoP = E.outExpo(inv(bt(2), bt(2) + .32, lt)) * (1 - E.inCubic(inv(tFall - .1, tFall + .1, lt)));
  const drawWord = (mode, dy, alpha, dropOK) => {
    L.items.forEach((it, i) => {
      const s0 = i * B / 4;
      let rise = 1 - E.outExpo(inv(s0, s0 + .5, lt));
      const wave = .22 * hit(lt, bt(1) + i * .035, 9) + .16 * hit(lt, bt(1.5) + (5 - i) * .035, 9);
      let fy = 0, rot = 0, fx = 0;
      if (dropOK && i !== portalIdx && lt > tFall) {
        const r = rng(i * 17 + 3), ft = Math.max(0, lt - tFall - Math.abs(i - portalIdx) * .03);
        fy = -380 * ft + .5 * 7200 * ft * ft; fx = (r() - .5) * 700 * ft; rot = (r() - .5) * 7 * ft;
      }
      g.save();
      g.globalAlpha = alpha;
      // mask band: letters rise from behind the baseline
      g.beginPath(); g.rect(-W, baseY - L.cap - 40 + dy - (lt > tFall ? 4000 : 0), W * 2, L.cap + 44 + (lt > tFall ? 8000 : 0)); g.clip();
      g.translate(it.x + it.w / 2 + fx, baseY + dy + rise * (L.cap + 60) + fy);
      g.rotate(rot); g.scale(1 - wave * .4, 1 + wave);
      if (it.ch === 'O') {
        const rr = L.ring, lw = rr * .42;
        const pop = E.outBack(inv(s0, s0 + .4, lt), 2.4);
        g.beginPath(); g.ellipse(0, -L.cap / 2, (rr - lw / 2) * pop, (L.cap / 2 - lw / 2) * pop, 0, 0, TAU);
        g.lineWidth = lw * pop;
        if (mode === 'fill') {
          if (i === portalIdx && lt > tZoom - .1) { g.fillStyle = C.blue; g.fill(); }
          g.strokeStyle = C.ink; g.stroke();
        } else { g.lineWidth = 3 / zoom; g.strokeStyle = C.ink; g.stroke(); }
      } else {
        font(g, WM.size); g.textAlign = 'center'; g.textBaseline = 'alphabetic';
        if (mode === 'fill') { g.fillStyle = C.ink; g.fillText(it.ch, 0, 0); }
        else { g.lineWidth = 3; g.strokeStyle = C.ink; g.strokeText(it.ch, 0, 0); }
      }
      g.restore();
    });
  };
  if (echoP > 0.001) for (let k = 3; k >= 1; k--) { drawWord('line', -k * 150 * echoP, 1 - k * .22, false); drawWord('line', k * 150 * echoP, 1 - k * .22, false); }
  drawWord('fill', 0, 1, true);
  g.restore();
  // side notes
  if (zp < .05) {
    typed(g, 'KINETIC TYPE / 01', 120, 170, inv(.2, .7, lt), 20, C.ink);
    typed(g, '[ M◯TI◯N ]', W - 120, 170, inv(.3, .8, lt), 20, C.ink, 'right');
  }
}

// 03 — FORM: shape morphs with overshoot, follow-through trails, orbiting satellites, ripples, colour wipes
function formState(lt) {
  let idx = 0, u = 0, rot = 0;
  for (let k = 0; k < 4; k++) { const p = inv(bt(k) - .02, bt(k) + .36, lt); if (lt >= bt(k) - .02) { idx = k; u = E.outBack(p, 2.6); } }
  for (let k = 0; k < 4; k++) rot += E.outBack(inv(bt(k), bt(k) + .4, lt), 1.6) * (Math.PI / 2);
  return { a: idx, b: idx + 1, u, rot };
}
function sForm(t) {
  const lt = t - barT(2);
  g.fillStyle = C.blue; g.fillRect(-200, -200, W + 400, H + 400);
  // circular colour wipes on beat 2 (red) and 3.5 (ink → tunnel)
  const w1 = E.outExpo(inv(bt(2), bt(2) + .45, lt)); if (w1 > 0) { g.fillStyle = C.red; g.beginPath(); g.arc(CX, CY, 1200 * w1, 0, TAU); g.fill(); }
  const w2 = E.inOutCubic(inv(bt(3.5), BAR, lt)); if (w2 > 0) { g.fillStyle = C.ink; g.beginPath(); g.arc(CX, CY, 1150 * w2, 0, TAU); g.fill(); }
  // ripples
  for (let k = 0; k < 4; k++) {
    const p = inv(bt(k), bt(k) + .9, lt); if (p <= 0 || p >= 1) continue;
    g.strokeStyle = `rgba(242,238,230,${(1 - p) * .8})`; g.lineWidth = 3 + 10 * (1 - p);
    g.beginPath(); g.arc(CX, CY, 260 + 900 * E.outExpo(p), 0, TAU); g.stroke();
  }
  const kick = hit(lt, Math.floor(lt / B) * B, 10);
  const R = 250 * (1 + .08 * kick) * (1 - .2 * w2);
  // follow-through echoes: same shape evaluated in the past
  for (let e = 4; e >= 1; e--) {
    const s = formState(lt - e * .045);
    morphPath(g, s.a, s.b, s.u, R, s.rot, CX, CY); g.strokeStyle = `rgba(242,238,230,${.5 - e * .1})`; g.lineWidth = 3; g.stroke();
  }
  const s = formState(lt);
  morphPath(g, s.a, s.b, s.u, R, s.rot, CX, CY); g.fillStyle = C.paper; g.fill();
  // inner counter-rotating mini shape (ink)
  morphPath(g, (s.a + 2) % 5, (s.b + 2) % 5, s.u, R * .28, -s.rot * 1.5, CX, CY); g.fillStyle = w1 > .5 && w2 < .5 ? C.red : C.blue; if (w2 > .5) g.fillStyle = C.ink; g.fill();
  // satellites with lag + overshoot
  const orbitJ = [0, 1, 2, 3].reduce((a, k) => a + E.outBack(inv(bt(k) + .05, bt(k) + .5, lt), 2.2) * (TAU / 12), 0);
  for (let i = 0; i < 12; i++) {
    const a = i / 12 * TAU + orbitJ + lt * .4;
    const rr = 430 + 40 * Math.sin(i * 2 + lt * 6) * kick + 60 * hit(lt, bt(Math.floor(lt / B)) + i * .01, 7);
    const sz = i % 3 === 0 ? 14 : 6;
    g.fillStyle = i % 3 === 0 ? C.acid : C.paper;
    g.save(); g.translate(CX + Math.cos(a) * rr * (1 - w2 * .6), CY + Math.sin(a) * rr * (1 - w2 * .6)); g.rotate(a + s.rot);
    g.fillRect(-sz / 2, -sz / 2, sz, sz); g.restore();
  }
  g.save(); g.translate(CX, CY); g.restore();
  // label with shape name ticker
  const names = ['CIRCLE', 'SQUARE', 'TRIANGLE', 'STAR', 'CROSS'];
  monoLabel(g, '02 — FORM', 120, 170, 20, C.paper);
  monoLabel(g, `${names[s.a]} → ${names[s.b]}  ${(s.u * 100 | 0).toString().padStart(3, '0')}%`, W - 120, 170, 20, C.paper, 'right');
}

// 04 — DEPTH: a fly-through of every shape we just met, speed-ramped, then light at the end → hard black
function sDepth(t) {
  const lt = t - barT(3);
  g.fillStyle = C.ink; g.fillRect(-200, -200, W + 400, H + 400);
  if (t >= 7.3) { // breath hold: silence + a single dot
    g.fillStyle = C.paper; g.beginPath(); g.arc(CX, CY, 9 + 3 * Math.sin((t - 7.3) * 40), 0, TAU); g.fill();
    return;
  }
  const zc = 900 * lt + 1500 * lt * lt * lt;           // accelerating camera
  const speed = 900 + 4500 * lt * lt;
  const F = 700, sway = Math.sin(lt * 2.2) * 60 * (1 - lt / 2);
  const rR = rng(99);
  // speed streaks
  for (let i = 0; i < 180; i++) {
    const ang = rR() * TAU, rad = 500 + rR() * 1800, z0 = rR() * 6000;
    let z = ((z0 - zc) % 6000 + 6000) % 6000 + 20;
    const len = Math.min(900, speed * .12);
    const z2 = z + len;
    const x1 = CX + Math.cos(ang) * rad * F / z + sway, y1 = CY + Math.sin(ang) * rad * F / z;
    const x2 = CX + Math.cos(ang) * rad * F / z2 + sway, y2 = CY + Math.sin(ang) * rad * F / z2;
    g.strokeStyle = i % 7 === 0 ? C.acid : `rgba(242,238,230,${clamp(1.2 - z / 5000) * .7})`;
    g.lineWidth = clamp(F / z * 3, .5, 6);
    g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
  }
  // rings (back to front)
  const beatN = Math.floor(lt / B), kick = hit(lt, beatN * B, 9);
  for (let i = 60; i >= 0; i--) {
    const d = i * 260 + 200 - zc; if (d < 30 || d > 9000) continue;
    const sc = F / d; const r = 330 * sc;
    const fog = clamp(1 - d / 8000);
    const rot = i * .2 + lt * (1 + lt * 1.6);
    const acc = i % 8 === 0;
    const u = (Math.sin(i * .7 + lt * 3) + 1) / 2;
    morphPath(g, i % 5, (i + 1) % 5, u, r, rot, CX + sway * sc * 2, CY);
    g.lineWidth = clamp((acc ? 16 : 5) * sc, .5, 60);
    g.strokeStyle = acc ? C.red : `rgba(242,238,230,${fog * (.55 + .45 * kick)})`;
    g.stroke();
  }
  // light at the end of the tunnel
  const glow = E.inExpo(inv(6.95, 7.3, t));
  if (glow > 0) { const gr = g.createRadialGradient(CX, CY, 0, CX, CY, 1300 * glow + 20); gr.addColorStop(0, `rgba(255,255,255,${glow})`); gr.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = gr; g.fillRect(0, 0, W, H); }
  monoLabel(g, '03 — DEPTH', 120, 170, 20, C.paper);
  monoLabel(g, `Z ${(zc | 0).toString().padStart(6, '0')}  V ${(speed | 0).toString().padStart(5, '0')}`, W - 120, 170, 20, C.paper, 'right');
}

