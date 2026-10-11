/* HTML 引擎的确定性兜底（系统所有，agent 不可改；ADR 0028）。
 * 在页面里所有其他脚本之前运行。agent 自己的脚本仍由静态检查禁止这些 API；这里兜住的是内置库
 * （three.js 内部会调用 Math.random、performance.now、requestAnimationFrame）：
 * - Math.random：固定种子的 mulberry32，每次 renderAt 开头由运行时调用 __RESEED__() 重置，
 *   所以渲染期间消耗的随机数与渲染顺序无关；
 * - Date / Date.now / performance.now：冻结在 0；
 * - requestAnimationFrame / setTimeout / setInterval：返回句柄，但永远不执行回调。
 * 系统自己的预览脚本要用真正的帧回调，原始函数保存在 __RAF__ / __CAF__。 */
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
