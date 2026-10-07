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

  var LYRIC_LINGER = 1;  // 一句唱完后 lyric() 还继续返回它的秒数

  function lyricsOf(sec) {
    var out = [];
    (tl().lyrics || []).forEach(function (l, i) {
      if (l.start < sec.end && l.end > sec.start) {
        out.push({ i: i, text: l.text, start: l.start - sec.start, end: l.end - sec.start });
      }
    });
    return out;
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
      if (!grid) throw new Error('env: 本项目没有节拍网格（bt/bar 不可用），请用 env.hit(name)、env.span(name)、env.energy() 取音乐事件；有旁白的项目用 cue(i) 驱动节奏');
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
      // 配乐相关：timeline.music 为 null（无配乐的讲解）时保持中性值，不抛错。
      hit: function (name) {
        var music = timeline.music;
        // 导入歌曲（MV）没有命名事件：事件列表为空时保持中性，不报错。
        if (!music || !(music.events || []).length) return 0;
        var named = (music.events || []).filter(function (e) { return e.name === name; });
        if (!named.length) {
          var names = Array.from(new Set((music.events || []).map(function (e) { return e.name; })));
          throw new Error('env.hit("' + name + '")：没有这个事件，已有：' + (names.join(', ') || '无'));
        }
        if (named.every(function (e) { return e.kind === 'sweep'; })) {
          throw new Error('env.hit("' + name + '")：这是持续的扫频事件（sweep），用 env.span("' + name + '") 取它的起止');
        }
        var best = -Infinity;
        named.forEach(function (e) {
          if (e.kind === 'onset' && e.start <= t && e.start > best) best = e.start;
        });
        return best === -Infinity ? 0 : Math.exp(-(t - best) / 0.18);
      },
      span: function (name) {
        var music = timeline.music;
        if (!music) return [];
        return (music.events || [])
          .filter(function (e) { return e.name === name; })
          .map(function (e) { return { start: e.start - sec.start, end: e.end - sec.start }; });
      },
      energy: function (lt) {
        var music = timeline.music;
        if (!music) return 0;
        var en = music.energy;
        var x = (lt === undefined ? t : lt + sec.start) / en.hop;
        var i = Math.max(0, Math.min(en.values.length - 1, Math.floor(x)));
        var j = Math.min(en.values.length - 1, i + 1);
        var f = Math.max(0, Math.min(1, x - i));
        return en.values[i] + (en.values[j] - en.values[i]) * f;
      },
      // 歌词（MV）：`lyrics` 是与本镜头有交集的行（镜头局部秒，`i` 为本片歌词列表（按截取区间裁剪后）里的序号）；
      // `lyric()` 是正在唱或 1 秒内刚唱完的一句（同一时刻取开始最晚的，并列取文件里靠前的）。
      lyrics: lyricsOf(sec),
      lyric: function () {
        var all = timeline.lyrics || [];
        var best = -1;
        for (var k = 0; k < all.length; k++) {
          var l = all[k];
          if (!(l.start <= t && t < l.end + LYRIC_LINGER)) continue;
          if (best < 0 || l.start > all[best].start) best = k;
        }
        if (best < 0) return null;
        var line = all[best];
        var span = line.end - line.start;
        var progress = span > 0 ? Math.min(1, Math.max(0, (t - line.start) / span)) : 1;
        return { i: best, text: line.text, start: line.start - sec.start, end: line.end - sec.start, progress: progress };
      },
      moment: function (i) {
        var list = timeline.moments.filter(function (m) { return m.section_id === sec.id; });
        if (!list.length && !timeline.music) return undefined;
        if (!list[i]) {
          var hint = timeline.moments.length ? '' : '（本项目没有节拍脚本点，请用 env.hit/span/energy）';
          throw new RangeError('env.moment(' + i + '): 本镜头只有 ' + list.length + ' 个 moment' + hint);
        }
        return { at: list[i].at, t: list[i].t - sec.start, action: list[i].visual_action };
      },
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
      img.src = (window.__ASSET_SRC__ && window.__ASSET_SRC__[name]) || url;
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
