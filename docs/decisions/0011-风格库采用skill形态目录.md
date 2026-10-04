# 0011：风格库采用 skill 形态的目录，不用 SDK 的 skill 加载机制

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已采纳（存储方式已被 [ADR 0019](0019-风格库改用磁盘目录存储.md) 取代，其余约定仍有效） |
| 日期 | 2026-09-30 |
| 相关 | [M5 计划 D1/D2](../plans/completed/m5-polish.md)、[架构设计 §3.2、§5.5](../design/2026-09-26-architecture.md)、[legacy-assets.md](../references/legacy-assets.md)、[ADR 0004](0004-原生工具优先.md) |

## 背景

设计 §3.2 规定项目工作区里有一份 `style/STYLE.md`，创建项目时从风格库复制，叙事、动画、选题三个 agent 都读它；§5.5 说风格库「支持附带范例（金样本）」。旧项目的一套风格却由四类组件组成——叙事蓝图（叙事风格、节奏、镜头结构）、配色、动画风格、金样本——加起来一套 6–13 千字。全部塞进一份 `STYLE.md` 会让每个阶段每一轮都读一大堆和自己无关的内容，金样本也没法单独替换。

负责人在批准 M5 时问：能不能做成 skill？skill 的特点正好是**入口很短、细节按需读取**。

## 决定

**借用 skill 的目录形态，不用 SDK 的 skill 加载机制。**

一套风格是工作区 `style/` 下的一个目录（创建项目时复制进去，之后与风格库脱钩）：

```
style/STYLE.md                    # 入口：frontmatter（name、description）+ 简介 + 文件索引（每个文件什么时候读）
style/references/*.md             # 叙事蓝图、配色方案、动画风格等
style/exemplars/*.json | *.md     # 金样本
```

- 入口 `STYLE.md` 每轮先读；三个阶段的提示词分别说明**动笔之前**该读哪些文件（叙事：蓝图 + 金样本；动画：配色 + 动画风格；选题：只读入口），文件不存在时跳过；风格文件里的字段名或写法与提示词冲突时**以提示词为准**。
- `style_presets` 表存这套目录：`content` = 入口全文，`exemplars` = `[{name, text}]`，新增 `reference_files` = `[{name, text}]`（对外叫 `references`，列名避开 SQL 保留字）和 `description`（迁移 0004，均可空，旧行兼容）。
- 写入前统一校验（`db/repo/style_presets.py::validate_style_preset`，前端 `styleDraft.ts` 镜像同一组规则）：入口要有 `name`/`description` 的 frontmatter；文件名只允许普通字符、不以点开头、不重名；`references/` 只能 `.md`，`exemplars/` 只能 `.json`/`.md`，`.json` 必须是合法 JSON；入口里引用的 `references/x`、`exemplars/y` 必须存在；大小和数量有上限。
- `workspace/style_files.py::render_style_files` 把预设渲染成 `{相对路径: 文本}`，创建项目时经 `init_workspace` 写入并进入 `init` 快照。`style/` 仍然对所有阶段只读。

## 考虑过的其他方案

- **用 SDK 的 skill 加载器**：Claude 的 `ClaudeAgentOptions.skills` 靠文件系统发现，要打开设置来源，和现在 `setting_sources=[]` 的隔离冲突，skill 目录落在工作区里还会被快照扫描；OpenAI 的 skill 只挂在 `ShellTool` 的 `local`/`container` 环境上，而本项目在非官方 `base_url` 或非 macOS 上不提供 Shell，LiteLLM 接入的模型没有 skill。（核实自已安装的 `claude-agent-sdk 0.2.160`、`openai-agents 0.22.3` 的源码，2026-09-30。）不能作为三个运行时统一的机制。以后若要接 Claude 原生 skill，是一个独立的小改动。
- **所有内容合并成一份 `STYLE.md`**：不选的原因：每轮都读全部内容；金样本不能单独替换。
- **按阶段拆成 `STYLE-narrative.md`、`STYLE-visual.md`**：不选的原因：偏离设计里「单一 `STYLE.md`」的约定，要让每个 agent 找对文件；入口 + 各阶段提示词点名读哪些文件，效果一样而且更灵活。

## 影响

- **依赖提示词里的强指令让 agent 去读文件。** 已用本机 Claude 登录实测（`make smoke SMOKE_ARGS="-k style_claude_login"`，2026-09-30）：叙事一轮先读入口和简报、再读蓝图与金样本、之后才写 `narrative.json` 并通过 `validate_narrative`；动画一轮先读入口、再读配色与动画风格、之后才写镜头代码并通过 `validate_scenes`。只验证了「概念传记·纸上溯源」这一套；弱模型（DeepSeek 等）可能跳过按需读取，没有实测。
- **旧风格里的字段名。** 旧项目导入的 9 套风格里，叙事蓝图 8 个中有 6 个、金样本 5 个全部使用旧系统的镜头字段（`scene_index`、`beat_index`、`estimated_duration_seconds`）。导入不改写正文，入口 `STYLE.md` 里加「旧格式提示」，叙事提示词写明 `narrative.json` 的字段以提示词为准；一次真实冒烟里产物通过了 `validate_narrative`。其余 8 套没有逐个跑真实模型（TD-42）。
- 偏离设计 §3.2 的 `style/` 内容约定（多了 `references/`、`exemplars/`）和 §3.1 的 `style_presets` 列；设计文档按红线不修改，本 ADR 记录偏离。
- 风格是**复制**进项目的：改风格库或删预设不影响已有项目；给已有项目换风格不在本里程碑范围内（要改就在项目里编辑 `style/`）。
