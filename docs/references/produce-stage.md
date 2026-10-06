# produce 阶段的真实模型冒烟实测

只记实测事实，不写推测。来源：`make smoke SMOKE_ARGS="-k <用例>"`（Claude 本地登录，`env -i` 白名单环境），2026-10-06。

## 动态图形短片（`test_motion_reel_claude_login`）

- 结果：通过，整条用例 26 分 19 秒（含 `concept` 对话、`produce` 对话、成片渲染）。
- `produce` 阶段的 CLI 会话记录（5438cab4…）：569 行，助手消息 183 条，输出 token 合计约 21.9 万。
- 工具调用次数：`render_preview_html` 25、`validate_scenes_html` 15、`render_music` 3、Edit 23、Write 19、Read 12、Bash 10。
- **1 MiB 问题（T1）**：会话记录里最长一行 565 778 字节（< 1 048 576），修复前同类会话出现过 1 054 050 / 1 054 379 字节的行。该次运行没有再触发缓冲区上限。
- 没有被门禁拦下的失败：冒烟用例通过即代表 `validate_scenes_html` 无错误、成片渲染成功。

## 音乐 MV（`test_music_video_claude_login`）

- 结果：通过（第二次运行；第一次失败是冒烟用例自己在 `concept` 之后就读 `animation/shots.json`，已修用例，不是产品问题），整条用例 14 分 13 秒。
- 歌曲：海阔天空，324.8 秒；分析 BPM 76.94、置信度 0.84、拟合残差 14.1 ms，无警告。
- `concept`：1 轮、3 步（`analyze_music`、Write、`check_concept`），费用约 $0.11。
- `produce`：1 轮、42 步，费用约 $1.20，输出约 3.8 万 token；模型写了 6 个镜头。工具调用：`validate_scenes_html` 9、`render_preview_html` 7、Write 12、Edit 3、Bash 10、Read 1。
- 成片渲染 225.7 秒，时长 324.833 秒（时间轴 324.825 秒），165 MB，一条音轨，音频区间 [0, 324.825]。
- **1 MiB 观察**：`produce` 会话记录里有一行 1 065 448 字节（> 1 048 576）——是模型用内置 `Read` 读 `music/analysis.png` 得到的一条 `tool_result`（单份约 53 万字节，CLI 写两份）。这条不经过 `invoke_tool` 的图片预算（预算只管我们自己的 MCP 工具），本次靠 `max_buffer_size` 提到 8 MiB 才没出错；若仍是 1 MiB 缓冲，这次运行会撞上限。因此 T1 的 8 MiB 缓冲不是冗余保险，而是实际起作用的那一层。
- 听感（对拍、段落、淡入淡出）智能体听不到，需负责人试听，成片已保留在 `data/evidence/import-music/smoke/music-video-final.mp4`。
