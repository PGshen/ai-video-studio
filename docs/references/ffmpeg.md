# ffmpeg（本机 Homebrew 安装）

> 注：worker 已不再叠字幕、不再拼接（ADR 0015/0016），下面的字幕叠加与 concat 记录保留为已验证的参考，当前代码不使用。

## ✅ 已验证：本机 ffmpeg 编译时没有 `drawtext`/`subtitles` 滤镜（无 libass/freetype）

日期：2026-09-28（M2 T5 自验证时发现）。来源：实测，`ffmpeg -filters` 的输出里
（`ffmpeg version 8.0.1`，`brew install ffmpeg` 默认配置）没有 `drawtext`、
`subtitles`、`ass` 这几个滤镜；`ffmpeg -version` 的 `configuration:` 一行也没有
`--enable-libfreetype`/`--enable-libass`。

**影响**：worker 的成片渲染（design §5.3/§10 的"加字幕"）不能走"生成 SRT/ASS
+ `-vf subtitles=...`"或"`-vf drawtext=text=...`"这两条最常见的路子。

**验证过的替代方案**：用 Pillow（已经是 manim 的直接依赖，`manim` 的
`pyproject.toml` 声明了 `pillow>=11.0`，backend 这边显式加成自己的直接依赖，
不是新引入的包，见 M2 计划决策记录）把每条字幕文字画成一张跟成片同分辨率的
透明 PNG（黑边白字，居中偏下），再用 ffmpeg 的 `overlay` 滤镜按时间窗口叠加
到视频上：

```
ffmpeg -y -i base.mp4 -loop 1 -i sub1.png \
  -filter_complex "[0:v][1:v]overlay=enable='between(t,0.5,1.5)'[vout]" \
  -map "[vout]" -c:v libx264 -pix_fmt yuv420p -t <总时长> out.mp4
```

要点（都已实测确认，不是从文档推断）：
- 静态图片输入要加 `-loop 1`，否则 ffmpeg 只把它当一帧处理，`overlay` 拿不到
  后续帧。
- 多条字幕按时间窗口错开时，链式多个 `overlay`（`[0:v][1:v]overlay=...[v1]`
  → `[v1][2:v]overlay=...[v2]` → …），每个 `overlay` 用自己的 `enable`
  表达式控制显示区间，互不冲突。
- 必须显式传 `-t <总时长>`（用 `ffprobe -select_streams v:0` 探测，参考
  `manim.md` 里"选视频流而不是容器整体"的理由）：`-loop 1` 的图片输入是
  无限长的，不传 `-t` 时输出时长不会被主视频的实际时长限制住。
- `-pix_fmt yuv420p` 建议保留，避免部分播放器（包括 `<video>` 标签）对其它
  像素格式的兼容性问题。

## ✅ 已验证：`overlay` 滤镜可用，`concat` demuxer（`-f concat -safe 0`）流复制可用

日期：2026-09-28。来源：本机 `ffmpeg -filters` 输出确认 `overlay`（`VV->V`）
存在；worker 用 `-f concat -safe 0 -i list.txt -c copy` 把逐镜头单独渲染出的
小片段（相同分辨率/帧率/编码参数，因为都是同一个 `ManimRenderEngine` 用相同
参数渲染出来的）拼接成一条视频，实测可行，不需要重新编码。

## ✅ 已验证：旁白侧链压低背景乐（`sidechaincompress`）

日期：2026-10-05（子项目 3B T1）。来源：本机 `ffmpeg 8.0.1` 实测，扫描脚本思路见下，定值在 `engines/render/mix.py` 的 `_DUCK`。

- **图结构**：旁白总线 `asplit=2`，一路进成片，一路作 `sidechaincompress` 的侧链输入（第二个输入）；配乐是第一个输入（被压的信号）。`asplit` 的每个输出都必须接上，否则报 `output unconnected`（实验里没用到的一路要接 `anullsink`）。
- **定值**：`threshold=0.03:ratio=6:attack=10:release=400:makeup=1`。
- **实验设置**：旁白是 200 Hz 加噪声的类语音段（说话段 RMS 约 −21.7 dBFS），配乐是低频加中频持续音（RMS −19 dBFS）；测"说话段的配乐电平 − 无侧链电平"（压低量）和"停说话后 0.1–0.4 秒"的恢复。
- **扫描结论（说话段 RMS −21.7 dBFS）**：压低量主要由 `threshold` 和 `release` 决定。

| threshold | ratio | attack (ms) | release (ms) | 压低量 (dB) | 停后 0.1–0.4 s 的差 (dB) |
|---|---|---|---|---|---|
| 0.01 | 8 | 5 | 400 | −21.0 | −7.7（压过头、回升慢） |
| 0.02 | 8 | 20 | 400 | −14.6 | −2.6 |
| 0.05 | 8 | 10 | 400 | −8.2 | −0.3 |
| 0.04 | 8 | 10 | 400 | −9.9 | −0.7 |
| **0.03** | **6** | **10** | **400** | **−11.6** | **−1.3** |

- **对旁白电平的敏感度**：同一组参数，旁白 −29.6 dBFS 时压低量降到 −4.9 dB，−15.7 dBFS 时升到 −16.6 dB（停后 0.1–0.4 秒差 −4.3 dB）。所以旁白音量差别大时要调 `threshold`；本机 Volcengine TTS 的电平落在中间档（具体电平未逐条测，听感由负责人验收）。
- **验收标准（本项目）**：说话段压低 ≥ 6 dB；停说话 1 秒后回到不压的电平 −2 dB 以内。`tests/engines/test_mix.py` 里的 `test_music_is_ducked_while_the_narration_speaks_and_recovers_after` 用 FFT 在配乐自己的频率上量，跟这条一致。
- **配乐淡变**：只有配乐时首尾各 15 ms（防爆音）；讲解背景乐首淡入 1 秒、尾淡出 1.5 秒。`afade` 放在 `atrim` 之后、`apad` 之前，淡出起点 = 总长 − 淡出时长。
- ⚠️ 待验证：旁白音量变化很大的项目（逐条 TTS 未归一化）压低量会不一致；若负责人验收时听出来，改成给旁白总线先加 `loudnorm` 或 `dynaudnorm` 再侧链。
