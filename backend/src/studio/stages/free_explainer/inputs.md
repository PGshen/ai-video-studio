## 先读什么

- `notes/project.md`：创建项目时系统生成的项目说明（形态、有没有背景乐、成片需要哪些文件）。**每个新会话开始先读它。**
- 用户的需求就在对话里，没有选题简报。事实、数据要自己查证（可以联网），关键事实写进 `notes/` 留底，不确定的如实告诉用户。用户上传的参考资料在 `uploads/`（只读）。
- `style/STYLE.md`：本项目的风格入口，**动笔前先读**。风格库里只有 `STYLE.md` 一定存在，其他文件叫什么、在哪、有没有，一律以它的索引为准，不要猜文件名；按索引读叙事蓝图、配色方案、动画风格、金样本（`style/exemplars/`）。风格文件只用来学写法、语感、配色和节奏，字段名以本提示词为准；索引里没有列出可读文件（占位风格）就跳过。风格决定画面长什么样，本提示词决定代码怎么写，冲突时以本提示词为准。
- `upstream/exemplar/canvas-techniques.js`、`upstream/exemplar/webgl-techniques.js`：系统自带的 2D 与 3D 画面技法金样本，借鉴技法，不要照抄外观，不要 import；带背景乐时还有 `upstream/exemplar/audio-techniques.py`（合成技法）。

## 成片读哪些文件

预览和成片只读这些：`narrative/narrative.json`（叙事）、`narrative/timing.json` 与 `narrative/audio/*`（配音，只能由 `synthesize_tts` 写）、`animation/scenes/<镜头 id>.js`、`animation/lib/*.js`、`animation/global.js`、`animation/assets/*`；带背景乐时还有 `music/compose.py` 和 `render_music` 生成的 `music/` 产物。其他文件（笔记、大纲、草稿）随你放。

## 时间轴从哪里来

没有 `upstream/timeline.json`：时间轴由 `narrative.json` 加配音结果（`timing.json`）即时生成，镜头就是 `narrative.json` 的 `scenes`，**镜头的时长和 beat 的时刻都来自配音**。所以：

- 场景文件名 `animation/scenes/<镜头 id>.js` 里的 id 就是 `narrative.json` 里镜头的 `id`。
- 改了某个镜头的 `narration` 或 `cue_text` 后要重新配音这个镜头，否则时间轴和旁白对不上，场景工具会报"timing.json 缺少对应记录"或"beat 数不一致"。
- 重新配音会改变时刻：场景里的时刻都从 `env.cue(i)` 推出，就不用改；带背景乐时要重新 `render_music`。

