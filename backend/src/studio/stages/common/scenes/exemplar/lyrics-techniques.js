// EXEMPLAR (lyric-driven scene for a music video). Study the TECHNIQUES, not the look:
//   - subtitle bar that follows env.lyric() (text, progress) and lingers 1 s after a line ends
//   - keyword emphasis: pick a word of the current line and pop it on every beat (env.hit('beat'))
//   - number roller, curve draw-on, terminal typing, full-screen "slam" word on a downbeat
// Every effect is a pure function of (lt, env): no state kept between frames. Times come from
// env.lyric() / env.lyrics / env.hit(...), never from literal seconds. Do not copy it; your scenes
// follow the brief's 「歌词意象」 and its visual language. Fonts: Anton, Space Mono, Noto Sans SC.
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const outExpo = t => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
const outBack = (t, s = 1.9) => 1 + (s + 1) * Math.pow(t - 1, 3) + s * Math.pow(t - 1, 2);
const C = { ink: '#0b0b0d', paper: '#f2eee6', accent: '#ff5a1f', dim: '#8a8680' };

// Subtitle bar: fades in over the first 15% of the line, out during the 1 s linger.
function subtitle(ctx, env, line) {
  if (!line) return;
  const inA = clamp(line.progress / 0.15);
  const outA = line.progress >= 1 ? clamp(1 - (env.t - env.start - line.end) / 1) : 1;
  ctx.save();
  ctx.globalAlpha = inA * outA;
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(env.CX - 560, env.H - 150, 1120, 84);
  ctx.fillStyle = C.paper;
  ctx.font = '700 40px "Noto Sans SC"';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(line.text, env.CX, env.H - 108);
  ctx.restore();
}

// Keyword: the last word of the line (split on spaces), popped by every beat.
function keyword(ctx, env, line) {
  if (!line) return;
  const words = line.text.split(/\s+/);
  const word = words[words.length - 1];
  const pop = env.hit('beat');                       // 1 at the beat, decays to 0
  const enter = outBack(clamp(line.progress / 0.2)); // springs in when the line starts
  ctx.save();
  ctx.translate(env.CX, env.CY - 60);
  ctx.scale(enter * (1 + 0.12 * pop), enter * (1 + 0.12 * pop));
  ctx.fillStyle = pop > 0.5 ? C.accent : C.paper;
  ctx.font = '700 220px "Noto Sans SC"';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(word, 0, 0);
  ctx.restore();
}

// Number roller: digits spin to `value` as `p` goes 0 → 1 (eased), like a counter.
function roller(ctx, x, y, value, p) {
  const digits = String(value).padStart(6, '0').split('');
  ctx.save();
  ctx.font = '700 72px "Space Mono"';
  ctx.textAlign = 'center';
  digits.forEach((d, i) => {
    const settle = clamp(p * 1.4 - i * 0.08);
    const shown = Math.round(lerp(Math.floor(((i * 7 + p * 40) % 10)), +d, outExpo(settle)));
    ctx.fillStyle = settle >= 1 ? C.accent : C.dim;
    ctx.fillText(String(shown % 10), x + i * 56, y);
  });
  ctx.restore();
}

// Curve draw-on: y = exp growth, revealed left to right as p goes 0 → 1.
function curve(ctx, x, y, w, h, p) {
  ctx.save();
  ctx.strokeStyle = C.accent;
  ctx.lineWidth = 6;
  ctx.beginPath();
  const steps = Math.floor(120 * p);
  for (let i = 0; i <= steps; i++) {
    const u = i / 120;
    const px = x + u * w, py = y + h - (Math.exp(4 * u) - 1) / (Math.exp(4) - 1) * h;
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  }
  ctx.stroke();
  ctx.restore();
}

// Terminal typing: reveal characters by progress, blinking caret.
function typing(ctx, env, x, y, text, p) {
  const n = Math.floor(text.length * clamp(p));
  const caret = Math.floor(env.t * 2) % 2 === 0 ? '▌' : ' ';
  ctx.save();
  ctx.font = '400 40px "Space Mono"';
  ctx.fillStyle = C.paper;
  ctx.textAlign = 'left';
  ctx.fillText('> ' + text.slice(0, n) + caret, x, y);
  ctx.restore();
}

// Full-screen slam: a huge glyph on an accent background for the first moments of a downbeat.
function slam(ctx, env, glyph) {
  const k = env.hit('downbeat');
  if (k < 0.35) return;
  ctx.save();
  ctx.fillStyle = C.accent;
  ctx.fillRect(0, 0, env.W, env.H);
  ctx.fillStyle = C.ink;
  ctx.font = '700 760px "Noto Sans SC"';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(glyph, env.CX, env.CY);
  ctx.restore();
}

module.exports = {
  draw(ctx, lt, env) {
    ctx.fillStyle = C.ink;
    ctx.fillRect(0, 0, env.W, env.H);
    const line = env.lyric();                 // null before the first line / after the linger
    const p = line ? line.progress : 0;
    curve(ctx, 160, 200, 520, 300, p);        // draws on while the line is sung
    roller(ctx, 1240, 300, 120000 + (line ? line.i * 1000 : 0), p);
    typing(ctx, env, 160, 640, line ? line.text : '', clamp(p / 0.8));
    keyword(ctx, env, line);
    slam(ctx, env, line ? line.text.slice(0, 1) : '');
    subtitle(ctx, env, line);
    // env.lyrics lists every line that touches this shot (local seconds): use it to look ahead,
    // e.g. start a build-up 0.5 s before the next line begins.
    const next = env.lyrics.find(l => l.start > lt);
    if (next) {
      const lead = clamp(1 - (next.start - lt) / 0.5);
      ctx.fillStyle = C.accent;
      ctx.fillRect(0, env.H - 6, env.W * lead, 6);
    }
  },
};
