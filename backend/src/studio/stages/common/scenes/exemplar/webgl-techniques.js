// EXEMPLAR (one complete 3D scene with three.js). Study the TECHNIQUES, do not copy the look:
// - build the scene graph ONCE at module load (seeded rng for anything "random");
// - in draw(), set every pose (objects, camera, light) from lt / env only — no THREE.Clock,
//   no requestAnimationFrame, no state carried from the previous frame;
// - render with the page's shared renderer env.three(), then ctx.drawImage it onto the 2D frame;
// - draw 2D text and labels AFTER the 3D layer (crisper, uses the bundled fonts).
// The renderer state is reset before each scene: set clear color / tone mapping here every frame.
// Use 3D only when space matters (rotation, depth, camera moves, light); flat graphics stay in 2D.
// Mentioning THREE anywhere in your scripts is what makes the page load three.js.

const TAU = Math.PI * 2;
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const inv = (a, b, x) => clamp((x - a) / (b - a));
const outCubic = t => 1 - Math.pow(1 - t, 3);
const inOutCubic = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), s | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------- scene graph (module load, runs once) ----------
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 16 / 9, 0.1, 100);

const globe = new THREE.Group();
globe.position.set(1.5, -0.15, 0); // composition: globe right of center, title space on the left
scene.add(globe);

// Solid core with soft lighting.
const core = new THREE.Mesh(
  new THREE.SphereGeometry(1.6, 96, 64),
  new THREE.MeshStandardMaterial({ color: 0x1d3557, roughness: 0.8, metalness: 0.05 }),
);
globe.add(core);

// Latitude rings as thin lines.
const ringMaterial = new THREE.LineBasicMaterial({ color: 0x3a86ff, transparent: true, opacity: 0.35 });
for (let i = 1; i < 8; i++) {
  const lat = -Math.PI / 2 + (i * Math.PI) / 8;
  const r = 1.62 * Math.cos(lat), y = 1.62 * Math.sin(lat);
  const pts = [];
  for (let k = 0; k <= 128; k++) pts.push(new THREE.Vector3(r * Math.cos((k / 128) * TAU), y, r * Math.sin((k / 128) * TAU)));
  globe.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), ringMaterial));
}

// Seeded "cities": points on the sphere, each with a stable phase for twinkling.
const rand = rng(7);
const N = 1400;
const positions = new Float32Array(N * 3);
const phases = [];
for (let i = 0; i < N; i++) {
  const u = rand() * 2 - 1, a = rand() * TAU, s = Math.sqrt(1 - u * u);
  positions.set([1.64 * s * Math.cos(a), 1.64 * u, 1.64 * s * Math.sin(a)], i * 3);
  phases.push(rand() * TAU);
}
const cityGeometry = new THREE.BufferGeometry();
cityGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
const cityMaterial = new THREE.PointsMaterial({ color: 0xffd166, size: 0.035, transparent: true });
globe.add(new THREE.Points(cityGeometry, cityMaterial));

// One arc per narration beat: a great-circle path that grows while its beat is spoken.
function arcPoints(r, seed) {
  const g = rng(seed);
  const a = new THREE.Vector3(g() - 0.5, g() - 0.5, g() - 0.5).normalize();
  const b = new THREE.Vector3(g() - 0.5, g() - 0.5, g() - 0.5).normalize();
  const pts = [];
  for (let k = 0; k <= 64; k++) {
    const p = a.clone().lerp(b, k / 64).normalize();
    pts.push(p.multiplyScalar(r + 0.25 * Math.sin((k / 64) * Math.PI)));
  }
  return pts;
}
const arcs = [];
for (let i = 0; i < 8; i++) {
  const line = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(arcPoints(1.64, 100 + i)),
    new THREE.LineBasicMaterial({ color: 0xef476f }),
  );
  line.visible = false;
  globe.add(line);
  arcs.push(line);
}

const key = new THREE.DirectionalLight(0xffffff, 2.2);
const rim = new THREE.DirectionalLight(0x3a86ff, 1.4);
rim.position.set(-4, 1, -3);
scene.add(key, rim, new THREE.AmbientLight(0xffffff, 0.25));

// ---------- draw: everything is a function of lt / env ----------
module.exports = {
  draw(ctx, lt, env) {
    const p = lt / env.len; // 0..1 across the scene

    // 2D background first.
    const bg = ctx.createRadialGradient(env.CX, env.CY, 100, env.CX, env.CY, 1200);
    bg.addColorStop(0, '#0b1324');
    bg.addColorStop(1, '#03060c');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, env.W, env.H);

    // Poses: slow spin, camera dolly-in with easing, key light orbiting.
    globe.rotation.y = lt * 0.25;
    globe.rotation.x = 0.35;
    const dolly = inOutCubic(inv(0, 0.6, p));
    camera.position.set(0, 0.2, 11 - 2.5 * dolly);
    camera.lookAt(0.6, 0, 0);
    key.position.set(Math.cos(lt * 0.3) * 5 - 2, 3, Math.sin(lt * 0.3) * 3 + 5);

    // Twinkle is a pure function of lt (no per-frame state).
    cityMaterial.opacity = 0.65 + 0.25 * Math.sin(lt * 2.0);

    // Beat-driven arcs: arc i grows during beat i and stays drawn afterwards.
    arcs.forEach((arc, i) => {
      const beat = env.beats[i];
      arc.visible = !!beat && lt >= beat.start;
      if (!arc.visible) return;
      const grow = outCubic(inv(beat.start, beat.end, lt));
      arc.geometry.setDrawRange(0, Math.max(2, Math.round(65 * grow)));
    });

    // Shared renderer: set what this scene relies on every frame, render, composite.
    const renderer = env.three();
    renderer.setClearColor(0x000000, 0); // transparent: the 2D background shows through
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.render(scene, camera);
    ctx.drawImage(renderer.domElement, 0, 0);

    // 2D overlay after the 3D layer.
    const fade = outCubic(inv(0, 0.15, p));
    ctx.globalAlpha = fade;
    ctx.fillStyle = '#f1faee';
    ctx.font = "700 72px 'Noto Sans SC'";
    ctx.fillText('连接世界的航线', 120, 160);
    ctx.font = "400 32px 'Space Mono'";
    ctx.fillStyle = '#a8dadc';
    ctx.fillText(`${arcs.filter(a => a.visible).length} ROUTES`, 124, 220);
    ctx.globalAlpha = 1;
  },
};
