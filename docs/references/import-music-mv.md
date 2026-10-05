# 导入音乐与音乐 MV（子项目 4B 实测记录）

用途：子项目 4B 的上传、预览、成片与真实歌曲冒烟。歌曲只记文件名与时长，不记歌词或其他受版权保护的内容；
文件在本机 `docs/temp/`（已被 `.gitignore` 忽略），不入库。

状态标记见 [README](README.md)。除特别注明，来源均为 2026-10-05 的实测（macOS arm64、Python 3.12、
本地 Claude 登录、真实 Chromium 与 ffmpeg；证据在 `data/evidence/import-music/smoke/`，已被忽略）。

## 真实歌曲冒烟（`海阔天空.mp3`，324.8 秒，mp3）

- ✅ `concept → music → beatsheet → animation_html` 四个阶段在本地 Claude 登录下全部一次走完，
  再由 worker 出成片；用例 `tests/smoke/test_music_video_smoke.py::test_music_video_claude_login`
  通过，总耗时约 1005 秒（含四个阶段的真实模型轮次，音乐阶段的分析冷启动约 27 秒）。
- ✅ **拟合读数**（`analyze_song`，与 4B 设计里的摸底读数一致，可复现）：BPM 76.94、第一个强拍
  `offset` 1.409 秒、置信度 0.84、拟合残差 14.1 ms、没有警告。
- ✅ 候选段落边界 11 个：1.41、17.01、94.99、138.66、141.78、157.38、194.81、226.01、235.36、263.44、316.47 秒；
  agent 取其中 9 个写成 8 个段落（前奏、主歌一、副歌一、主歌二、副歌二、桥段、副歌三、尾声），
  整曲区间 1.41–316.47 秒（没有写 `range`）。
- ⚠️ **待负责人试听核对**：强拍相位（`offset` 是不是真正的"一拍"）、BPM 是否正确（76.9 偏慢，
  不能排除应为 153.9 的倍频误判）、段落边界是否落在歌曲的结构点上。agent 听不到，上面这些只是读数与
  结构检查通过，不代表听感正确。试听用的成片保存在 `data/evidence/import-music/smoke/music-video-final.mp4`。
- ✅ **成片**：时长 315.07 秒（等于时间轴时长，误差 < 0.01 秒）、一条 AAC 音轨、`final.json` 的
  `audio_sources` 只有 `music`（`hash` 为源文件哈希、`range` 为 `[1.41, 316.47]`），没有 `music_hash`。
- ✅ **出帧耗时**：315 秒、30 fps（约 9450 帧）的成片整段渲染加混音约 161 秒，约为片长的一半；
  文件约 136 MB（约 3.5 Mbps）。总设计 §12 与 4 设计 §8 的"长歌出帧时长"风险在这个量级下可以接受，
  不需要另列优化项。
- ⚠️ 淡入淡出：`MV_FADE_IN`/`MV_FADE_OUT` 仍是 15 ms，只防爆音；歌曲在区间终点被截断处是否生硬，
  由试听判断，需要时只改 `engines/render/mix.py` 里这两个常量。

## 上传

- ✅ `POST /api/projects/{id}/music/source` 用 `python_multipart` 的流式解析器直接解析请求体，
  不经 Starlette 的 `UploadFile`：后者先把整个文件落到临时文件才进入端点，无法在读取中途按上限中止。
  边读边算 sha256、边计数，超过 150 MB 立即以 422 结束；文件先写到 `.cache/tmp/upload-*`，
  `ffprobe` 通过后才原子改名为 `music/source.<ext>`，失败不留残留。
- ✅ `ffprobe -select_streams a:0 -show_entries stream=codec_name:format=duration -of json`：
  文本伪装成 `.mp3`、零字节文件、没有音频流的文件都以非零退出或空 `streams` 报错，不需要靠扩展名判断。

## 预览与混音

- ✅ 预览的音频时间 = 预览时间 + `music.offset`（`offset` 取有效截取区间起点）。内置浏览器实测：
  起播时音频被设到 `offset`，播放中音频时间减 `offset` 与预览时钟一致（显示有小于 0.3 秒的刷新滞后），
  拖动进度条后音频跳到 `offset + t`。
- ✅ 混音从原曲的某一秒起读，用 `atrim=start=…,asetpts=PTS-STARTPTS`，毫秒级精确；细节与越界行为见
  [ffmpeg.md](ffmpeg.md)。
- ✅ `worker_html` 把源文件复制到 `.cache/tmp` 的私有目录并边拷边算哈希，哈希与 `analysis.json` 的
  `source_hash` 比对；混音与 `final.json` 用的是这份拷贝（与合成配乐同一套防"检查之后又被换"）。
