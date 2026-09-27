# 技术债登记表

发现暂时不处理的问题时登记在这里。每个里程碑收尾时，挑一两项处理，或者排进下一个计划。处理完的条目移到「已处理」。

| # | 登记日期 | 位置 | 问题 | 影响 | 建议的处理方式 | 来源 |
|---|---|---|---|---|---|---|
| TD-1 | 2026-09-28 | `backend/src/studio/agent/claude_runtime.py`（`WEB_TOOLS`、`SANDBOX`） | Claude agent 开联网时 WebFetch/WebSearch 放行所有域名；SDK sandbox 只管 Bash 且默认不限制读，Bash 能读工作区外文件（如 `backend/.env`），再经 WebFetch 外发 | 提示注入场景下本机文件可能外泄（密钥类环境变量已置空、Read/Glob/Grep 已限制在工作区内，见 references/claude-agent-sdk.md） | sandbox `filesystem.denyRead` 拒读仓库与 `data/`；WebFetch 域名白名单或按阶段默认关闭联网 | M1 最终审查 I5 |

## 已处理

| # | 处理日期 | 说明 |
|---|---|---|
| — | — | — |
