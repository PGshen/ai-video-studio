# Volcengine（火山引擎）TTS

## ✅ 已验证：真实合成返回逐字时间戳，`beat_aligner` 在真实时间戳上完全对齐

日期：2026-09-29（M3 T13 冒烟）。来源：实测，`make smoke SMOKE_ARGS="-k volcengine_tts"`
（`backend/tests/smoke/test_smoke.py::test_volcengine_tts`），证据在
`data/evidence/m3-narrative/smoke/`（不进 git）。配置：`build_tts_engine()`（`seed-tts-2.0` /
`doubao_2.0`）、音色别名 `zizi`、语速 1.0。

输入：`这是一次语音合成测试`（10 个汉字、无标点），beats 为 `这是一次` / `语音合成测试`。

| 观察 | 值 |
|---|---|
| 合成结果 | `success=True`，音频 21357 字节，`duration_seconds=2.664`（`mutagen` 解析 mp3） |
| 时间戳粒度 | 每个汉字一条（10 条），字段 `word`/`start`/`end`，单位秒，单调 |
| 首字起点 | 0.255 秒——开头有约 0.25 秒静音，不是从 0 开始 |
| 末字终点 | 2.445 秒，比音频总时长短约 0.22 秒——结尾也有静音 |
| 停顿 | 两个 beat 之间"次"（→1.045）到"语"（1.145）有 0.1 秒空隙 |
| 对齐 | 两个 beat 都是 `alignment_status="aligned"`，`alignment_coverage=1.0`；`speech_start/end` 分别是 0.255–1.045、1.145–2.445 |

**含义**：
- `timing.json` 的 `beats[].start_seconds/end_seconds` 取 `speech_start/end`（紧邻发言边界，不含开头/结尾静音），所以第一个 beat 的起点不是 0，最后一个 beat 的终点小于 `duration_seconds`。动画阶段按 beat 窗口排时间时要能接受这一点。
- 整个冒烟用例（含 pytest 启动）约 4.7 秒，费用很小。

## ⚠️ 待验证

- **带标点的文本**：这次输入没有标点，所以没有观察到 TTS 是否为标点返回时间戳、`beat_aligner` 对"时间戳里没有标点字符"的处理是否在真实数据上成立（单测用的是逐字含标点的替身数据）。叙事阶段的 `cue_text` 必须带标点（见计划 M3「意外与发现」），真实叙事跑第一遍时留意 `synthesize_tts` 返回的对齐覆盖率。
- **长文本**（一个镜头几十到上百字）下的时间戳精度、分片顺序、重试行为没有测过。
- **其它音色/语速下的逐字时间戳与 beat 对齐**：M5 T8 的试听（见下一节）只验证了合成成功和时长，没有验证 `synthesize_tts` 依赖的逐字时间戳、对齐覆盖率在其它音色/语速下的表现。

## ✅ 已验证：音色与语速范围（M5 T8 试听）

日期：2026-09-30。来源：实测，`make smoke SMOKE_ARGS="-k tts_preview_real"`（`backend/tests/smoke/test_smoke.py::test_tts_preview_real`，经 `POST /api/tts/preview`，引擎 `doubao_2.0`），证据 `data/evidence/m5-polish/smoke/20260930T132651Z-tts-preview-real.json` 和同目录的五个 mp3。

固定示例文本（`api/tts.py::PREVIEW_TEXT`，约 30 个汉字）：

| 音色 | 倍速 | 结果 | mp3 时长 |
|---|---|---|---|
| `zizi`（清澈梓梓） | 1.0 | 成功 | 6.43 秒 |
| `zizi` | **0.5** | 成功 | 11.69 秒 |
| `zizi` | **2.0** | 成功 | 2.95 秒 |
| `xiaohe`（小禾） | 1.2 | 成功 | 4.92 秒 |
| `yunzhou`（云舟，男声） | 1.0 | 成功 | 7.06 秒 |

**含义**：

- 项目倍速 0.5–2.0（对应火山引擎相对值 -50 至 100，`engines/tts/volcengine.py`）两端都被供应商接受，并且真实生效：同一段话 0.5 倍速约是 1.0 倍速的 1.8 倍长，2.0 倍速约一半。`db/repo/settings.py` 的 `SPEECH_RATE_MIN/MAX` 就是这个范围。
- `xiaohe`、`yunzhou` 和之前验证过的 `zizi` 都能合成；`xiaozhupeiqi`、`xiaoxinjiejie` 没有实际合成过（旧库里 `xiaozhupeiqi`（小猪佩奇）标为未启用）。
- 音色的中文名和性别取自旧项目 dev DB 的 `tts_voices` 表（2026-09-30 只读查证，`speaker_id` 与 `engines/tts/voice_map.py` 一一对应）。
