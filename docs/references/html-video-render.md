# HTML 成片渲染：出帧、编码、混音与浏览器池的实测

日期：2026-10-05。来源：实测（macOS arm64、Chromium 由 `playwright install chromium` 安装、系统 ffmpeg），计划 2B T8。对应设计 [子项目 2 设计](../design/2026-10-04-timeline-html-engine.md) §5.4、§5.5、§8、§13。

## ✅ 出帧速度

方法：6 秒时间轴（180 帧，1920×1080，30fps）、单个镜头、`render_silent_video` 全流程（逐帧 `toDataURL('image/jpeg', 0.92)` → `image2pipe` → libx264 CRF 15），测墙钟。

| 场景 | 帧率 | 相对实时 | 视频体积 |
|---|---|---|---|
| 简单（一个色块） | 约 135 帧/秒 | 0.22× | 0.03 MB |
| 中等（渐变背景、120 个圆、中英文字、6 行等宽文字） | 约 63 帧/秒 | 0.47× | 4.8 MB |
| 重（160 个带 `shadowBlur` 的圆、`filter: blur`） | 约 30 帧/秒 | 0.98× | 8.8 MB |

- 结论：成片耗时约等于视频时长的 0.2–1 倍；一支 3 分钟的重场景片子约 3 分钟。**瓶颈在 Canvas 绘制（`shadowBlur`、`filter`）而不是 JPEG 编码或 ffmpeg。**
- 进度回调每帧触发；worker 里按整百分比或每 10 秒才写库并续心跳，避免 1800 次数据库写入。

## ✅ 编码细节（踩过的坑）

- Canvas 的 JPEG 是全色域（`yuvj420p`）。直接 `-pix_fmt yuv420p` 输出的流仍被标成 `yuvj420p`，部分播放器和剪辑软件当成非标准格式。解法：`-vf scale=in_range=pc:out_range=tv,format=yuv420p`，ffprobe 报 `yuv420p`，实测背景色 `#204060` 经 JPEG→H.264 往返后误差小于 8。
- 帧数 `ceil(duration × fps)`（先减 1e-6 抵消浮点误差，`3.3 × 30` 不能变成 100 帧）。第 i 帧取时刻 `i / fps`。

## ✅ 混音：`apad` 必须有限

- `amix=normalize=0` 后接**裸 `apad`** 再加输出选项 `-t <duration>`、`-c:v copy`：遇到引擎自己编码出的视频时，ffmpeg 不会停，一直写（实测几分钟内写出 64 MB 仍不结束），而用 lavfi 生成的测试视频则正常结束，所以单元测试没拦住。
- 解法：`apad=whole_dur=<D>,atrim=end=<D>`（补静音到至少 D、再裁到 D），外加 `-t <D>`。回归测试用 `render_silent_video` 产出的视频和总长恰好等于时间轴的两段 24 kHz 单声道 wav 复现。
- 无旁白轨时补一条 `anullsrc` 静音 AAC，成片总有音轨。

## ✅ 浏览器池：真实 SIGKILL 恢复与资源占用

- 杀掉池里的 Chromium 主进程后，下一次 `acquire` 自动重建并成功；在页面使用中途被杀，下一次 `render_jpeg` 抛 `BrowserClosed`（调用方重试一次），释放后池里的浏览器已换新（`tests/engines/test_html_pool_recovery.py`，`-m slow`）。
- 常驻内存（Chromium 进程树 RSS，中等场景）：首个页面后约 340 MB；连续 40 次预览会话（200 帧）后约 550 MB，没有持续线性增长；空闲超时关闭后回到约 2 MB（进程全部退出）。api 进程里池只在 agent 调用工具时才启动，空闲 10 分钟自动关闭，目前不需要改成按需启动。
- worker 每个任务单独启动浏览器、结束即关，不常驻。
