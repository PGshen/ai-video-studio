/* Determinism shim for the HTML engine (system-owned; ADR 0028). Runs before every other script.
 * Agent scripts are still barred from these APIs by the static check; this covers the bundled
 * libraries (three.js calls Math.random, performance.now and requestAnimationFrame internally):
 * - Math.random: seeded mulberry32, reset by the runtime (__RESEED__) at the start of each
 *   renderAt, so random numbers drawn while rendering do not depend on render order;
 * - Date / Date.now / performance.now: frozen at 0;
 * - requestAnimationFrame / setTimeout / setInterval: return a handle, never run the callback.
 * The system preview script needs real frame callbacks, so the originals stay in __RAF__/__CAF__. */
(function () {
  window.__RAF__ = window.requestAnimationFrame.bind(window);
  window.__CAF__ = window.cancelAnimationFrame.bind(window);

  var SEED = 0x2545f491;
  var state = SEED;
  function random() {
    state = (state + 0x6d2b79f5) >>> 0;
    var t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  Math.random = random;
  window.__RESEED__ = function () { state = SEED; };

  var RealDate = Date;
  function FrozenDate() {
    var args = Array.prototype.slice.call(arguments);
    if (!new.target) return new RealDate(0).toString();
    return args.length ? new (Function.prototype.bind.apply(RealDate, [null].concat(args)))() : new RealDate(0);
  }
  FrozenDate.prototype = RealDate.prototype;
  FrozenDate.now = function () { return 0; };
  FrozenDate.parse = RealDate.parse;
  FrozenDate.UTC = RealDate.UTC;
  window.Date = FrozenDate;
  Object.defineProperty(performance, 'now', { value: function () { return 0; }, configurable: true });

  var nextHandle = 1;
  function never() { return nextHandle++; }
  function noop() {}
  window.requestAnimationFrame = never;
  window.cancelAnimationFrame = noop;
  window.setTimeout = never;
  window.clearTimeout = noop;
  window.setInterval = never;
  window.clearInterval = noop;
})();
