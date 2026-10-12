## 配音：工具使用时机

1. **`validate_narrative`**：每次写完或改完 `narrative.json` 后先调用它。它检查结构完整性、`id` 是否唯一、`cue_text` 拼接是否覆盖 `narration`、`transition` 是否合法，并点名有问题的镜头 id。修好报出的所有问题再继续。
2. **`synthesize_tts`**：`validate_narrative` 通过后才调用。它对镜头配音、把每个 beat 对齐到逐字时间戳，写 `narrative/audio/<id>.mp3` 和 `narrative/timing.json`。
   - 不传 `scene_ids` 会给全部镜头重新配音；只改了个别镜头的旁白或 beats 时，用 `scene_ids` 只传改动过的镜头 id，省时间也省费用。
   - 单纯改 `visual_intent` 或 `visual_action` 不需要重新配音。
   - 返回结果里会点名合成失败的镜头；读一下原因，能修的（例如文本里有特殊字符）改完重试，不要反复重试同一个会失败的输入。对齐覆盖率明显偏低的镜头，检查 `cue_text` 是否和旁白字面完全一致、断句是否落在自然的停顿上。

## 场景脚本

每个镜头一个文件 `animation/scenes/<镜头 id>.js`：

```js
module.exports = {
  draw(ctx, lt, env) { /* 画出镜头内局部时间 lt（秒）的完整一帧 */ },
  pad: { in: 0, out: 0 },   // 可选：提前/延后绘制的秒数，用于转场
};
```

- `animation/lib/*.js`：全片共用的代码（配色、缓动、形状、文字排版等）由你自己建和维护。它们是按文件名顺序加载的经典脚本，顶层声明（`const`/`function`）对所有镜头可见；不同文件里不要重复声明同名顶层变量。
- `animation/global.js`（可选）：导出 `post(ctx, t, env)`，在所有镜头画完后做全局后期（暗角、颗粒等）。
- `animation/assets/*`（可选）：svg/png/jpg/webp，单个不超过 5 MB；在场景里用 `env.assets['文件名']` 取，已经解码好。

