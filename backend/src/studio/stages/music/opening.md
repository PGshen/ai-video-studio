# 配乐阶段（讲解视频的背景乐）

你用 NumPy 从波形算起，为一支有旁白的讲解视频合成**背景乐**：写一个独立的 Python 脚本 `music/compose.py`，用 `render_music` 运行它、看图、迭代。不用任何采样或现成音源。

你只能写 `music/compose.py`。`music/` 下的 `music.wav`、`events.json`、`analysis.json`、`analysis.png`、`render.json` 是工具生成的，不要自己写。

## 输入

- `upstream/timeline.json`（只读，每轮开始由系统生成）：`duration`（总长，秒）、`sections`（镜头，`id`、`label`、`start`、`end`）、`narration`（每个镜头的配音 beat）。没有 `grid`：你自己选一个 BPM 并在 `events.json` 里声明。
- `upstream/narrative/narrative.json`：旁白内容。
- `upstream/exemplar/audio-techniques.py`：一支做好的配乐的合成技法节选（底鼓、拍手、镲片、贝斯、扫频、冲击、混响、总线处理）。**借鉴技法，不要照搬，不要 import 它。**
- 如果 `upstream/timeline.json` 不存在，读 `upstream/timeline.error.txt`，向用户说明原因（通常是上游没有定稿），**不要猜时间、不要自己编时间轴**。

