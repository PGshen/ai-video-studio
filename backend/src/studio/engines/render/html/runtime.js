/* HTML 引擎页面运行时（系统所有，agent 不可改）。
 * 把镜头模块挂到画布上，暴露 window.renderAt(t) 与 window.ready。
 * 画面是 t 的纯函数：每次调用都从头绘制，不保留任何跨帧状态。 */
(function () {
  var W = 1920, H = 1080;
  var canvas = document.getElementById('c');
  var ctx = canvas.getContext('2d');
  var scenes = window.__SCENES__;
  var post = window.__GLOBAL__ || null;
  var assetUrls = window.__ASSETS__ || [];
  var assets = {};

  function tl() { return window.__TIMELINE__; }  // probe 会在不重载页面的情况下替换它

  function beatsOf(sectionId) {
    var entry = tl().narration.find(function (n) { return n.scene_id === sectionId; });
    return entry ? entry.beats : [];
  }

  var assetProxy = new Proxy(assets, {
    get: function (target, key) {
      if (typeof key !== 'string' || key === 'then' || key === 'toJSON') return target[key];
      if (!(key in target)) {
        throw new Error('env.assets: 没有资源 "' + key + '"（已有：' + (Object.keys(target).join(', ') || '无') + '）');
      }
      return target[key];
    },
  });

  function makeEnv(sec, index, t) {
    var timeline = tl();
    var grid = timeline.grid;
    var beats = beatsOf(sec.id).map(function (b) {
      return { start: b.start - sec.start, end: b.end - sec.start, text: b.cue_text };
    });
    function needGrid() {
      if (!grid) throw new Error('env: 本项目没有节拍网格，请用 cue(i) 驱动节奏');
    }
    return {
      W: W, H: H, CX: W / 2, CY: H / 2,
      t: t, start: sec.start, end: sec.end, len: sec.end - sec.start, duration: timeline.duration,
      section: { id: sec.id, label: sec.label, index: index }, sections: timeline.sections,
      beats: beats,
      cue: function (i) {
        if (!beats[i]) throw new RangeError('env.cue(' + i + '): 本镜头只有 ' + beats.length + ' 个 beat');
        return beats[i].start;
      },
      cueEnd: function (i) {
        if (!beats[i]) throw new RangeError('env.cueEnd(' + i + '): 本镜头只有 ' + beats.length + ' 个 beat');
        return beats[i].end;
      },
      grid: grid,
      assets: assetProxy,
      bt: function (n) { needGrid(); return grid.beats[0] + n * 60 / grid.bpm - sec.start; },
      bar: function (n) { needGrid(); return grid.beats[0] + n * 240 / grid.bpm - sec.start; },
      hit: function () { return 0; },
      energy: function () { return 0; },
      moment: function () { return undefined; },
    };
  }

  function reset() {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  window.renderAt = function (t) {
    var timeline = tl();
    t = Math.min(Math.max(t, 0), timeline.duration - 1e-6);
    reset();
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, W, H);
    timeline.sections.forEach(function (sec, i) {
      var scene = scenes[sec.id];
      if (!scene) return;
      var pad = scene.pad || {};
      var lo = sec.start - (pad.in || 0), hi = sec.end + (pad.out || 0);
      if (!(t >= lo && t < hi)) return;
      var lt = t - sec.start;
      if (typeof scene.draw !== 'function') {
        throw new Error('[scene ' + sec.id + '] 没有导出 draw 函数（需要 module.exports = { draw(ctx, lt, env) {} }）');
      }
      ctx.save();
      try {
        scene.draw(ctx, lt, makeEnv(sec, i, t));
      } catch (e) {
        throw new Error('[scene ' + sec.id + ' @lt=' + lt.toFixed(3) + '] ' + ((e && e.stack) || e));
      } finally {
        ctx.restore();
        reset();
      }
    });
    if (post) {
      ctx.save();
      var first = timeline.sections[0];
      post(ctx, t, makeEnv(first, 0, t));
      ctx.restore();
      reset();
    }
  };

  function loadAsset(url) {
    var name = url.replace(/^assets\//, '');
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { assets[name] = img; resolve(); };
      img.onerror = function () { reject(new Error('资产加载失败：' + name)); };
      img.src = url;
    });
  }

  // 所有 @font-face（内置字体和风格目录字体）都要加载完才算就绪；
  var fontLoads = Array.from(document.fonts).map(function (face) { return face.load(); });
  window.ready = Promise.all(fontLoads.concat(assetUrls.map(loadAsset))).then(function () {
    if (window.__LOAD_ERRORS__ && window.__LOAD_ERRORS__.length) {
      throw new Error('脚本加载出错：' + window.__LOAD_ERRORS__.join('；'));
    }
  });
})();
