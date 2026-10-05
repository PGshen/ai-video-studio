# librosa（歌曲节拍分析）

用途：子项目 4 的 `engines.audio.song`（导入歌曲分析）。版本：librosa 0.11.0、numba 0.68.0、
scikit-learn 1.9.1、soundfile 0.14.0、soxr 1.1.0（`uv add "librosa>=0.10,<1"` 解析结果）。

所有条目均为 ✅ 已验证，日期 2026-10-05，来源：实测（macOS arm64、Python 3.12、`backend/.venv`）。

## 安装与冷启动

- ✅ `uv add` 安装（含解析、下载、构建）约 23 秒，新增 numba、llvmlite、scikit-learn、soundfile、soxr、pooch 等十余个包。
- ✅ `import librosa` 只要约 0.03 秒：用了 lazy_loader，子模块在首次访问时才导入。
- ✅ numba 的冷启动在**第一次调用** `librosa.beat.beat_track` 时发生：**约 27 秒**（JIT 编译，缓存尚空）；
  同一进程第二次约 0.014 秒；新进程（numba 磁盘缓存已有）首次调用约 2 秒。
  含义：隔离子进程必须给足超时（首次运行至少 60 秒），测试里第一次调用会慢，之后正常。
- ✅ 性能：4 分钟音频 `beat_track` 约 0.19 秒、`onset_strength` 约 0.13 秒（缓存热之后）。

## `beat_track` 的返回

- ✅ `librosa.beat.beat_track(y=, sr=, units="time")` 返回 `(tempo, beats)`：`tempo` 是**形状 `(1,)` 的 ndarray**
  （不是 float，取值要 `float(tempo[0])`），`beats` 是 float64 的一维数组（秒）。
- ✅ 速度被量化、与真实值有偏差：合成 120 BPM 的 click 得 117.45，96 得 95.70，140 得 143.55。
  所以不直接用 `tempo`，而是对拍点序号做线性最小二乘（`fit_grid`），实测误差在 0.5% 内。
- ✅ 拍点落在 hop（512 采样，约 23 ms）的整数倍上，第一个拍点约 0.0929 s（真值 0.08 s）；
  拟合 offset 要对「模一拍」比较，因为 `beat_track` 的第 0 个拍点不一定是歌曲的第 0 拍。

## `load` 与解码

- ✅ `librosa.load(path, sr=22050)` 返回 float32 单声道，重采样用 soxr；wav 之外的格式走 soundfile/audioread，
  平台差异大。`audioread` 在 Python 3.12 下导入时会发 `aifc`/`audioop`/`sunau` 的 DeprecationWarning。
- ✅ 我们的做法：自己用 ffmpeg 解成 22050 Hz 单声道 `f32le` 管道再交给 librosa，不调用 `librosa.load`，
  既统一 mp3/m4a/flac/ogg/wav，也绕开 audioread 的警告。ffmpeg 加 `-t 601` 限制最长读入。
- ✅ 项目现有的 `pydub` 导入也有 `audioop` 的 DeprecationWarning（manim 引入），与 librosa 无关；pytest 下只显示 1 条。
