# ffmpeg（本机 Homebrew 安装）

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
