codex `exec --json` 输出的回放用例，裁剪自 codex-login-spike 与 codex-runtime 的实测证据
（`data/evidence/codex-spike/`，不入库）。本机路径已替换为 `/repo`、`/work/ws`、`/home/user`。

| 文件 | 来源 | 内容 |
|---|---|---|
| `minimal.jsonl` | `r1g-effort-high` | 最小一轮 |
| `mcp_image.jsonl` | `r2a-http-mcp` | MCP 工具调用，结果含图片 |
| `command.jsonl` | `t4a-workspace-write` | 命令执行 |
| `file_change.jsonl` | `t4d-apply-patch` | apply_patch 改文件 |
| `cancelled.jsonl` | `t2g-cancel-INT-solo` | 命令执行中被 SIGINT 取消（没有终止事件） |
| `model_not_found.jsonl` | `t1c-model-bogus` | 配置警告 + 400 失败 |
| `not_logged_in.jsonl` | `t1d-codex-home-empty` | 未登录：401 重连后失败 |
| `reconnect_then_done.jsonl` | `t2f-cancel-TERM-solo` 前 9 行 + 手写结尾 | 重连 `error` 后照常完成 |
