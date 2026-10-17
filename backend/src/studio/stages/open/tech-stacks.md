# 常见视频技术栈参考（优先级最低）

> **这份文档只是兜底参考，优先级最低。** 用什么技术、做成什么样，按这个顺序决定：
>
> 1. **用户**在对话里说的（技术、工具、画面做法、参考样片）；
> 2. **`style/`** 里写明的（`style/STYLE.md` 及它引用的文件：比如手绘、像素、实拍拼贴、指定的库或字体）；
> 3. 前两者都没提到技术栈时，才参考这里。
>
> 有冲突时以前两者为准。不要因为这里推荐了某种做法，就改变用户或风格要的视觉效果；拿不准就先问用户。这份文件可以随意修改或删除。

## 按想要的效果选路线

| 想要的效果 | 常见做法 | 注意 |
|---|---|---|
| 排版、图文、数据图表、标题动画 | HTML/CSS/SVG/Canvas 写画面，无头浏览器逐帧截图，ffmpeg 编码 | 没有其它线索时的默认选择，见下一节 |
| 3D 场景、镜头运动 | three.js（同上的逐帧管线） | 软件渲染较慢，控制分辨率和时长 |
| 数学、几何推导、公式 | Manim Community（Python）；轻量时用 HTML + KaTeX | Manim 依赖多（LaTeX、cairo），装不上就退回 HTML |
| 组件化、多场景的较长片子 | Remotion（React） | 要装不少 npm 依赖；注意它的许可条款 |
| 剪辑现成素材：拼接、裁切、转场、加字幕 | ffmpeg（`filter_complex`）或 MoviePy | 素材必须是用户提供的或来源可用的 |
| 粒子、生成艺术、程序化图形 | p5.js 或原生 Canvas | 用固定随机种子，保证每次渲染一致 |
| 现成的矢量动效 | Lottie（lottie-web 渲染后逐帧截图） | — |

## 默认管线（没有其它线索时）

1. 页面提供一个 `renderAt(t)`：输入时间（秒），画出这一刻的画面。画面只由 `t` 决定，不依赖真实时间、`requestAnimationFrame` 或网络。
2. 用 Playwright 或 Puppeteer 以 `file://` 打开页面，按帧率逐帧调用 `renderAt(t)` 并截图（PNG）。
3. 用 ffmpeg 把帧序列编码成 H.264，例如：`ffmpeg -framerate 30 -i frames/%05d.png -c:v libx264 -pix_fmt yuv420p -crf 18 final.mp4`。
4. 有声音就再混进去（见下文）。

不要用实时录屏代替逐帧渲染：容易掉帧，结果每次都不一样。

## 声音

- **旁白**：用 `tts` 工具，一段文字生成一个 mp3；用 `ffprobe` 取时长，按旁白长度安排画面。
- **音乐、音效**：用用户提供的，或者用代码自己合成（例如 Python 生成 wav）；不要下载来源不明、可能有版权的音乐。
- **混音**：ffmpeg 的 `adelay`、`amix`、`volume`；最后 `-c:a aac` 和画面合成。

## 这个环境里的注意事项

- **依赖**：装在工作区里（`npm install`、`python -m venv .venv`）。npm/pip 的缓存已经指向工作区的 `.cache/`；`node_modules`、`.venv` 不进快照。
- **不能访问本机服务**：命令可以访问外网，但访问不了 `localhost`/`127.0.0.1`。浏览器预览请用 `file://` 打开页面，不要起本地 HTTP 服务器。
- **先确认工具能力**：比如 `ffmpeg -filters | grep drawtext`。有些 ffmpeg 没有 `drawtext`/`subtitles`，这时用 HTML 或 Pillow 把文字画成图片再叠加。
- **中文字体**：先确认系统里有哪些字体（macOS 常见 PingFang、Hiragino、STHeiti；Linux 常见 Noto Sans CJK），网页里写好字体回退链；渲染后抽帧检查有没有方框乱码。
- **浏览器**：先找已经装好的 Chromium（例如 Playwright 的缓存），没有再下载（约一两百 MB）。
- **成片放哪**：放在工作区里的普通目录（例如根目录的 `final.mp4`），用户在「文件」里能直接播放。**不要**放进 `output/`、`.cache/`、`upstream/`：这几个是系统目录，「文件」里看不到，也可能被清掉。
- **交付前自查**：用 `ffprobe` 看时长、分辨率、编码；抽几帧截图看一眼，再告诉用户结果。
