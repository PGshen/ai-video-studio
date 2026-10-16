# open-mode：完全自由模式（运行时原生的单阶段项目）

<!-- 本计划实现 docs/design/2026-10-15-open-mode.md。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | 完全自由模式（非编号） |
| 设计依据 | [完全自由模式设计](../../design/2026-10-15-open-mode.md)（2026-10-16 负责人批准） |
| 分支 | `feat/open-mode`（从 `main` 的 `dc05403` 切出，设计文档已在其上） |
| 批准记录 | 2026-10-16：负责人批准设计；2026-10-16：负责人批准计划 |
| 执行方式 | 本会话内联（Native），完成后一个独立评审检查整个分支；worktree `.claude/worktrees/open-mode` |

## 目标

用户可以新建「完全自由」项目（项目页直接建，或从选题卡建），工作区初始只有 `style/` 与 `project.md`。对话时 agent 使用运行时自己的默认系统提示词（Claude 为 Claude Code 默认提示词），可以读写整个工作区，Bash 可以联网，只额外多一个 `tts` 配音工具；画布只有「文件」，能预览 HTML、图片、音频、视频；项目可以手动标记完成、重新打开。其他模式的行为不变。

## 范围

**包含：**

- `mode="open"`、`VideoKind="open"`、`OPEN_KIND`、预设卡片、创建接口（`theme`、`project.md`）。
- 快照与文件树排除任意深度的 `node_modules`、`.venv`、`__pycache__`。
- 阶段协议：`system_prompt() -> str | None`、新属性 `exec_network`；`TurnContext`/`ToolContext` 同步。
- 三个运行时：默认提示词与 Bash/Shell 联网；Claude 的 `open` 内置工具集与禁用名单。
- `tts` 工具、`open` 阶段、完成 / 重新打开时的项目完成标记、渲染类接口对 `open` 的拒绝。
- 前端：创建入口、工作台 `open` 画布、`FileCanvas` 的 HTML 预览、标记与文案。
- 测试、真实模型冒烟、L4 浏览器验收、ADR 0031 与文档同步。

**不包含：**

- worker 成片、「成片」标签页、定稿前检查；与其他模式互相转换；除 `tts` 外的自建工具。
- 现有自由模式（`free_explainer`/`free_produce`）与多阶段模式的任何行为改动。

## 全局约束

- 设计 §2 已确认的决定全部适用：运行时默认提示词；三个运行时都支持；保留读写隔离、放开 Bash/Shell 联网；只给 `tts`；整个工作区可写（含 `style/`、`project.md`），只保护 `uploads/` 与 `upstream/ output/ .cache/`；手动完成；画布只有 `FileCanvas`。
- 阶段名 `open`，界面名「完全自由」；流水线 `["open"]`；`OPEN_KIND = ProjectKind("html", False, "none", "open")`，形态字段是占位，代码一律按 `mode == "open"` 分支。
- 现有阶段的 `system_prompt()` 返回值与 `exec_network=False` 不变；它们传给三个运行时的参数与改动前完全相同（现有运行时测试不改断言即通过）。
- 读隔离（拒读仓库、数据目录、凭据目录）与写隔离（只写当前工作区）在所有阶段都不放宽；`exec_mode` 与「无隔离执行」开关逻辑不变；Seatbelt 的 LaunchServices/Apple Event/`open`/`osascript` 三条规则在 `network=True` 时保留。
- 各阶段之间互不 import（import-linter）；`agent` 不 import `stages`。
- 不用 `skip`、`xfail`、`# type: ignore`、`noqa` 绕过失败；每个任务结束 `make check` 为绿，至少一个 commit，格式 `<type>(<scope>): <中文说明>`。
- 不引入新依赖；工作区里不用 git。

## 审查重点

设计隐含、但各任务的直接测试不一定覆盖的输入或状态；每条都在对应任务里有一条测试：

1. **现有阶段被连带改变**：`system_prompt` 类型放宽、`exec_network` 新增后，`topic`/`free_produce` 等阶段传给 Claude/Codex/OpenAI 的提示词、sandbox、Seatbelt 配置必须逐字不变（T3、T4、T5、T6：各加一条"现有阶段参数快照"测试）。
2. **深层依赖目录与同名普通文件**：`a/b/node_modules/x.js` 不进快照、回滚不删它；但名叫 `node_modules.md` 的文件、或 `notes/venv/` 目录照常进快照（T2）。
3. **`open` 项目误入渲染路径**：对 `open` 项目调用 `POST .../render`、`finalize-render`、场景检查接口，返回明确的 409（"完全自由项目没有成片渲染"），而不是 Manim 下线提示或 500（T7）。
4. **`tts` 的路径输入**：`out_path` 为 `../x.mp3`、绝对路径、`uploads/a.mp3`、`.cache/a.mp3`、`a.txt` 时报错且不写文件；`deep/new/dir/a.mp3` 自动建目录（T7）。
5. **重新打开后再完成、以及老项目**：`open` 项目完成 → 重新打开 → 再完成，`completed_at` 依次设置、清除、再设置；settings 里 `mode` 缺失或为非法值的老项目照旧按 `staged`，不会被识别成 `open`（T1、T7）。

## 验收标准

- [ ] AC1：`POST /projects` 用 `mode=open` 创建项目（带或不带 `idea_id`、`theme`），工作区只有 `style/**` 与 `project.md`，内容符合设计 §3.2；带形态字段返回 422 且没有副作用；`GET /api/video-kinds` 出现「完全自由」卡片。（验证：`tests/stages/test_pipeline.py`、`tests/api/test_projects.py`、`tests/api/test_video_kinds.py`）
- [ ] AC2：任意深度的 `node_modules`、`.venv`、`__pycache__` 不进快照与文件树，回滚不触碰它们。（验证：`tests/workspace/test_snapshot.py`、`tests/workspace/test_files.py`）
- [ ] AC3：`open` 阶段下三个运行时都使用默认提示词、Bash/Shell 可联网；现有阶段的运行时参数不变。（验证：`tests/agent/test_claude_runtime.py`、`test_openai_runtime.py`、`test_codex_runtime.py`、`test_codex_sandbox.py`、`test_shell_sandbox.py`）
- [ ] AC4：`open` 阶段的可写范围、工具清单、前言内容符合设计 §4；`tts` 按设计 §4.2 工作；完成 / 重新打开设置与清除项目完成标记；渲染类接口拒绝 `open`。（验证：`tests/stages/test_open_stage.py`、`tests/stages/test_tts_tool.py`、`tests/api/test_open_flow.py`）
- [ ] AC5：前端可以新建「完全自由」项目（含主题输入）；工作台只显示 `FileCanvas` 与完成按钮，不显示阶段条；`FileCanvas` 对 `.html` 提供预览 / 源码切换。（验证：vitest 用例）
- [ ] AC6：真实模型冒烟：Claude 本机登录下，`open` 项目做出 `out.mp4`，Bash 联网成功，系统提示词为 Claude Code 默认；Codex 本机登录验证提示词与联网。（验证：`make smoke SMOKE_ARGS="-k open"`）
- [ ] AC7：L4：浏览器里新建 → 对话 → 预览 HTML、播放 mp4 → 标记完成 → 重新打开，附截图。
- [ ] AC8：`make check` 全绿；ADR 0031、ARCHITECTURE、glossary、references、QUALITY、TODO 已同步。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：项目模型与创建接口（完成）

- **目标**：`open` 进入项目类型；能创建 `open` 项目，初始文件只有 `style/**` 与 `project.md`。此时 `open` 阶段还没注册，`video-kinds` 显示为不可用、创建返回 422（现有"未注册阶段"逻辑），T7 注册后自动变为可用；测试里用一个注册了假 `open` 阶段的 registry 覆盖创建成功的路径。
- **涉及文件**：`backend/src/studio/stages/pipeline.py`、`backend/src/studio/api/schemas.py`（`ProjectCreate.mode` 加 `"open"`、新增 `theme: str | None`，`max_length=2000`）、`backend/src/studio/api/projects.py`、`backend/src/studio/api/video_kinds.py`（`STAGE_TITLES["open"] = "完全自由"`）、`backend/tests/stages/test_pipeline.py`、`backend/tests/api/test_projects.py`、`backend/tests/api/test_video_kinds.py`。
- **接口与要点**：
  - `Mode = Literal["staged", "free", "open"]`；`VideoKind` 加 `"open"`；`OPEN_STAGE = "open"`；`OPEN_KIND = ProjectKind("html", False, "none", "open")`。
  - `kind_errors(kind)`：`mode == "open"` 时 `kind != OPEN_KIND` 报"完全自由项目没有形态配置"，且不再跑其它形态规则。
  - `video_kind_of`：`open` → `"open"`；`build_pipeline`：`open` → `["open"]`；`valid_kinds()` 追加 `OPEN_KIND`；`PRESETS` 追加「完全自由」卡片（文案见设计 §3.1，`music_choices=("none",)`，`default=OPEN_KIND`）。
  - `kind_from_settings`：`settings["mode"] == "open"` 时直接返回 `OPEN_KIND`，**先于**形态字段的合法性判断；`mode` 缺失或非法照旧按 `staged`。
  - `_kind_for_new_project`：`body.mode == "open"` 时三个形态字段任一非 `None` → 422；否则用 `OPEN_KIND`。
  - `_seed_files`：`open` 时只返回 `{"project.md": open_project_markdown(title, theme, idea, style_name)}`；新函数 `open_project_markdown(title: str, theme: str | None, idea: IdeaValue | None, style_name: str | None) -> str`，格式见设计 §3.2（主题优先级：`theme` > 卡片内容 > "（未填写）"；无风格时风格段写"项目风格在 `style/`，入口 `style/STYLE.md`（未选择风格）"）。需要把 `_style_for_new_project` 的风格名传给它。
  - 卡片照旧标记为已用、项目记 `idea_id`（与现有自由模式相同）。
- **测试**：`OPEN_KIND` 的流水线与 `video_kind`；`ProjectKind("html", True, "none", "open")` 报错；`kind_from_settings({"mode": "open"})` 与 `{"mode": "open", "engine": "manim", ...}` 都返回 `OPEN_KIND`；`{"mode": "bogus", ...}` 与缺失 `mode` 按 `staged`（审查重点 5）；创建 `open` 项目后工作区文件列表恰为 `style/**` + `project.md`；带 `theme`、带 `idea_id`、都不带三种 `project.md` 内容；`open` + `narration=true` 返回 422 且没有项目行、没有工作区；`theme` 超长 422；`video-kinds` 出现新卡片且在未注册时不可用。
- **完成标准**：上述测试通过；现有自由模式与多阶段创建测试不变。
- **验证命令**：`make check`

### T2：依赖目录不进快照与文件树（完成）

- **目标**：设计 §4.0。
- **涉及文件**：`backend/src/studio/workspace/layout.py`（新常量 `EXCLUDED_DIR_NAMES = {"node_modules", ".venv", "__pycache__"}`）、`backend/src/studio/workspace/snapshot.py`（扫描时 `dirnames` 过滤；回滚时跳过这些目录及其内容）、`backend/src/studio/workspace/files.py`（`list_tree` 跳过；`read`/`write` 不另加限制）、`backend/src/studio/workspace/scope.py`（若越界防线的扫描与快照扫描不共用一个函数，同步跳过，避免 guard 去还原 `node_modules`）、`backend/tests/workspace/test_snapshot.py`、`backend/tests/workspace/test_files.py`。
- **接口与要点**：名字精确匹配目录名，任意深度；只匹配目录，不匹配同名文件；与 `EXCLUDED_TOP_DIRS` 语义一致（不参与快照，回滚不触碰）。先 grep 所有使用 `EXCLUDED_TOP_DIRS`/`HIDDEN_TOP_DIRS` 的地方，逐个判断是否需要同步。
- **测试**：`a/b/node_modules/x.js`、`.venv/bin/python`、`src/__pycache__/m.pyc` 不在清单；回滚到不含它们的快照后它们仍在磁盘上；`node_modules.md` 文件、`notes/venv/` 目录照常进清单（审查重点 2）；文件树不列出依赖目录；guard 不报告、不还原依赖目录里的改动。
- **完成标准**：上述测试通过；现有快照、回滚、guard 测试不变。
- **验证命令**：`make check`

### T3：阶段协议扩展（完成）

- **目标**：协议能表达"用运行时默认提示词"和"命令可联网"，现有阶段不受影响。
- **涉及文件**：`backend/src/studio/agent/stage.py`、`backend/src/studio/agent/runtime.py`（`TurnContext.system_prompt: str | None`、新增 `exec_network: bool = False` 并透传进 `tool_context()`）、`backend/src/studio/agent/tools.py`（`ToolContext.exec_network: bool = False`）、`backend/src/studio/agent/runner.py`（三处构造 `TurnContext` 时传 `exec_network=job.stage.exec_network`）、`backend/src/studio/agent/fake.py`（若读 `system_prompt`）、所有现有阶段类（加 `exec_network = False`）、`backend/tests/agent/test_stage.py`、`backend/tests/agent/test_runner.py`。
- **接口与要点**：
  - `StageDefinition.system_prompt(self) -> str | None`，文档字符串写明 `None` 的含义；`exec_network: bool` 属性，文档写明"只放开命令执行的网络，读写隔离不变"。
  - 三个运行时在本任务里**只做类型适配**：遇到 `None` 暂时抛 `NotImplementedError("运行时默认提示词尚未实现")`，T4–T6 逐个实现。这样 T3 结束时 `make check` 为绿，且不会悄悄传空串。
  - 结构测试：遍历 `main` 注册的全部阶段，断言除 `open` 外 `exec_network is False` 且 `system_prompt()` 返回非空 `str`（`open` 在 T7 才注册，测试写成"若存在则……"）。
- **测试**：runner 把阶段的 `exec_network` 传进 `TurnContext` 与 `ToolContext`；现有阶段的结构测试；mypy 通过。
- **完成标准**：上述测试通过；现有运行时测试不改断言即通过。
- **验证命令**：`make check`

### T4：Claude 运行时（完成）

- **目标**：`system_prompt is None` 时用 `claude_code` preset；`open` 的内置工具集；`exec_network` 时沙箱放开出站。
- **涉及文件**：`backend/src/studio/agent/claude_runtime.py`、`backend/src/studio/agent/claude_scope.py`（`sandbox_settings(..., network: bool = False)`）、可能的 `backend/src/studio/agent/sandbox_paths.py`（白名单回退）、`backend/tests/agent/test_claude_runtime.py`、`docs/references/claude-agent-sdk.md`。
- **接口与要点**：
  - 先实测（本机 Claude 登录，写一个一次性脚本放 scratchpad，不进仓库）：① `network.allowedDomains=["*"]` 是否放行任意域名（`curl https://example.com`）；不行再试 `"*.*"`，都不行就用常用域名白名单（npm、PyPI、files.pythonhosted.org、GitHub 及其 raw/objects 域、jsDelivr、unpkg、cdnjs、Google Fonts），写进 `sandbox_paths.OPEN_NETWORK_DOMAINS`；② 内置 CLI 版本的完整工具名单（init 消息的 `tools` 字段），确定要禁用的工具（预期 `AskUserQuestion`、`EnterPlanMode`、`ExitPlanMode`、`Skill`、`SlashCommand`；`Task` 观察事件流是否能正常展示，能就保留）。结论与日期写进 `references/claude-agent-sdk.md`，实测命令写进决策记录。
  - `system_prompt=None` → `{"type": "preset", "preset": "claude_code"}`；否则原样字符串。
  - 工具：`ctx.system_prompt is None` 时内置工具为 `OPEN_BUILTIN_TOOLS`（Read/Write/Edit/MultiEdit/Glob/Grep/Bash/TodoWrite，加上实测保留的工具），`disallowed_tools` 加 `OPEN_DISALLOWED_TOOLS`；`exec_mode == "disabled"` 时照旧去掉 Bash。写入 hook 的 matcher 覆盖 MultiEdit（`GUARDED_WRITE_TOOLS` 已含则不改）。
  - `ctx.exec_network` 为真且 `mode == "sandboxed"` 时 `sandbox_settings(..., network=True)`，`filesystem` 部分不变。
- **测试**：`None` → preset、`open` 工具集与禁用名单、`exec_network` 时的 sandbox JSON；**现有阶段**（用 `topic` 与 `free_produce` 的真实定义构造 ctx）的 `system_prompt`、`tools`、`disallowed_tools`、`sandbox` 与改动前快照逐字相同（审查重点 1）。
- **完成标准**：上述测试通过；references 已更新。
- **验证命令**：`make check`；实测脚本的输出摘要记进「意外与发现」。

### T5：OpenAI 运行时与 Seatbelt（完成）

- **目标**：`system_prompt is None` 时 `instructions=None`；`exec_network` 时 Shell 可联网。
- **涉及文件**：`backend/src/studio/agent/openai_runtime.py`、`backend/src/studio/agent/shell_sandbox.py`（`seatbelt_profile(workdir, deny_read, *, network: bool = False)`）、`backend/src/studio/agent/shell.py`（executor 从 ctx 取 `exec_network`）、`backend/tests/agent/test_openai_runtime.py`、`backend/tests/agent/test_shell_sandbox.py`、`docs/references/openai-agents-sdk.md`。
- **接口与要点**：`network=True` 只去掉 `(deny network*)` 一行，三条逃逸规则保留；先确认 Agents SDK 的 `Agent(instructions=None)` 合法（读 SDK 源码，结论写进 references）。
- **测试**：profile 文本在 `network=True` 时不含 `deny network*`、仍含三条规则；`network=False` 时与改动前逐字相同（审查重点 1）；真实执行测试（macOS，沿用现有真实执行测试的跳过条件）：沙箱内 `curl` 连本机回环上由测试启动的 HTTP 服务器，`network=True` 成功、`False` 失败；`instructions` 为 `None`；现有阶段传给 `Agent` 的 instructions 不变。
- **完成标准**：上述测试通过。
- **验证命令**：`make check`

### T6：Codex 运行时（完成）

- **目标**：`system_prompt is None` 时不传阶段指令、不触发 `PROMPT_UPDATE`；`exec_network` 时沙箱联网。
- **涉及文件**：`backend/src/studio/agent/codex_runtime.py`（`prompt_digest(prompt: str | None)`，`None` 返回固定值 `"default"`；`_message` 在 `None` 时不拼 `PROMPT_UPDATE`）、`backend/src/studio/agent/codex_args.py`（`build_args(system_prompt: str | None, ...)`，`None` 时不加指令参数）、`backend/src/studio/agent/codex_sandbox.py`（`permission_args(..., network: bool = False)`、`sandbox_args(..., network: bool = False)`）、`backend/tests/agent/test_codex_args.py`、`test_codex_runtime.py`、`test_codex_sandbox.py`、`docs/references/codex.md`。
- **接口与要点**：先在本机 codex 版本上实测 permissions profile 打开网络的配置键（候选：`permissions.<profile>.network`、`sandbox_workspace_write.network_access=true`），用 `curl https://example.com` 验证；结论写进 `references/codex.md`。会话中途从有提示词切到 `None` 不会发生（阶段固定），不需处理。
- **测试**：`None` 时参数里没有指令项；`prompt_digest(None)` 稳定；resume 时不拼 `PROMPT_UPDATE`；`network=True` 时多出实测确定的配置项、`False` 时参数与改动前逐字相同（审查重点 1）。
- **完成标准**：上述测试通过；references 已更新。
- **验证命令**：`make check`

### T7：`tts` 工具、`open` 阶段与完成流程（完成）

- **目标**：注册 `open` 阶段；`tts` 可用；完成 / 重新打开维护项目完成标记；渲染类接口拒绝 `open`。
- **涉及文件**：`backend/src/studio/stages/common/narration/tts.py`（新）、`backend/src/studio/stages/common/narration/synthesize_tts.py`（抽出共用的 TTS 调用与 `_project_voice_and_speed`，行为不变）、`backend/src/studio/stages/open/__init__.py`（新）、`backend/src/studio/main.py`（注册）、`backend/src/studio/api/projects.py`（`finalize`/`reopen` 端点对 `open` 设置 / 清除 `completed_at`）、`backend/src/studio/api/animation_stage.py`（见下）、`backend/tests/stages/test_open_stage.py`、`backend/tests/stages/test_tts_tool.py`、`backend/tests/api/test_open_flow.py`、`.importlinter`（若需为 `stages.open` 加契约条目）。
- **接口与要点**：
  - `TTS_TOOL = ToolSpec(name="tts", stages={"open"}, ...)`；参数 `text: str`（非空，长度上限沿用 `synthesize_tts` 的单镜头上限）、`out_path: str`（`.mp3`/`.wav`）、`voice: str | None`、`speed: float | None`（范围同项目设置）；路径用 `workspace` 现有的安全路径函数校验，再用阶段 `write_scope` 判可写；写入后 `record_tool_write`；返回 `{"path", "duration_s"}`。
  - `OpenStage`：属性见设计 §4 表格；`write_scope()` 为 `WriteScope(writable=["*"], tool_managed=["upstream/*", "output/*", ".cache/*"])`。
  - 完成：`finalize_stage_endpoint` 在 `stage == OPEN_STAGE` 且项目流水线为 `["open"]` 时，定稿后调用 `mark_project_completed`；`reopen_stage_endpoint` 同条件调用 `clear_project_completed`。
  - 渲染类接口：`animation_stage_of` 对含 `open` 的流水线返回 `OPEN_STAGE`；`require_live_animation_stage` 遇到 `OPEN_STAGE` 抛 409"完全自由项目没有成片渲染"。逐个确认调用它的接口（渲染任务、`finalize-render`、场景检查、HTML 预览）都走到这条检查（与设计 §6"返回 `None`"的写法不同，理由见决策记录 D1）。
- **测试**：阶段属性、可写范围（`style/STYLE.md`、`project.md`、`a/b/c.mp4` 可写；`uploads/x`、`.cache/x` 不可写）、工具只有 `tts`、`system_prompt() is None`、`exec_network is True`、`status_summary == ""`、前言在只有用户修改时只含那一节；`tts` 的正常写入、默认音色语速、`deep/new/dir/a.mp3` 建目录、五种非法路径不写文件（审查重点 4，TTS 客户端用替身）；fake 运行时下创建 `open` 项目 → 一轮对话写文件 → 完成 → 重新打开 → 再完成，`completed_at` 依次变化（审查重点 5）；`open` 项目调渲染、`finalize-render`、场景检查返回 409 与指定文案（审查重点 3）；多阶段与现有自由项目的完成逻辑测试不变。
- **完成标准**：上述测试通过；`video-kinds` 中「完全自由」变为可用。
- **验证命令**：`make check`

### T8：前端创建入口与标记（待开始）

- **目标**：能从项目页与选题卡创建「完全自由」项目；各处认识 `open`。
- **涉及文件**：`frontend/src/features/projects/NewFreeProjectDialog.vue`（+ spec）、`frontend/src/features/ideas/CreateProjectDialog.vue`（+ spec，若需要为 `open` 卡片隐藏配乐选择与传 `theme`）、`frontend/src/composables/videoKindChoice.ts`、`frontend/src/composables/stageTitles.ts`（+ spec）、`frontend/src/features/projects/ProjectCard.vue`、`frontend/src/features/projects/projectView.ts`（+ spec）、`frontend/src/api/types.ts` 或等价类型文件（`mode` 加 `'open'`、`ProjectCreate.theme`）、`frontend/src/test/videoKindsFixture.ts`。
- **接口与要点**：选中「完全自由」时隐藏形态控件、显示可选多行"主题"输入（`maxlength=2000`），请求体 `{mode: "open", title, theme?, style_preset_id?, effort?}`，不带形态字段；`stageTitles.open = "完全自由"`；项目卡片显示「完全自由」标记，与「自由」标记区分；阶段筛选包含 `open`。
- **测试**（vitest）：对话框选「完全自由」后请求体正确、主题框出现、配乐控件隐藏；选题卡创建 `open` 的请求体；`stageTitles` 与项目卡片标记。
- **完成标准**：上述测试通过。
- **验证命令**：`make check`

### T9：前端工作台与 HTML 预览（待开始）

- **目标**：`open` 工作台只有 `FileCanvas` 与完成按钮；`FileCanvas` 预览 HTML。
- **涉及文件**：`frontend/src/pages/ProjectWorkbenchPage.vue`、`frontend/src/features/workbench/StageNav.vue`（+ spec）、`frontend/src/features/canvas/generic/FileCanvas.vue`、`frontend/src/features/canvas/generic/fileKind.ts`（+ spec，新增 `isHtmlFile(path)`）、新组件 `frontend/src/features/canvas/open/OpenCanvasHeader.vue`（+ spec：标记 + 「标记完成 / 重新打开」，调用现有 finalize / reopen mutation）、`ProjectWorkbenchPage` 顶部注释与 `STAGES_WITH_OWN_ACTIONS`。
- **接口与要点**：
  - `stage === 'open'` 分支：`OpenCanvasHeader` + `FileCanvas`，没有标签栏；按钮状态来自阶段 `status`（`finalized` 显示「重新打开」）；运行中（`busy`）时禁用。
  - `StageNav`：流水线为 `["open"]` 时显示"完全自由模式"，不显示阶段条（复用现有单阶段分支）。
  - `FileCanvas`：选中 `.html`/`.htm` 时顶部出现「预览 / 源码」切换，默认预览；预览为 `<iframe :src="workspaceFileUrl(..., version)" sandbox="allow-scripts">`，版本号跟随文件树刷新（同图片规则）；源码即现有编辑器（可编辑保存）。切换状态按文件路径记在组件内，不持久化。
  - 保存 403 文案改为"保存失败：不在可写范围内"。
- **测试**（vitest）：`open` 分支只渲染 `FileCanvas` 与头部、不渲染标签栏；完成 / 重新打开按钮调用对应 mutation；`StageNav` 单阶段文案；`isHtmlFile`；HTML 文件默认显示 iframe、`sandbox` 恰为 `allow-scripts`、切到源码出现编辑器；403 文案。
- **完成标准**：上述测试通过。
- **验证命令**：`make check`

### T10：冒烟、L4 验收与文档（待开始）

- **目标**：真实模型与浏览器验证；文档同步。
- **涉及文件**：`backend/tests/smoke/test_open_mode_smoke.py`（新，`-k open` 可选中；Claude 用例用本机登录，Codex 用例用本机 ChatGPT 登录，缺登录时按现有冒烟惯例跳过）、`docs/decisions/0031-完全自由模式.md`、`docs/ARCHITECTURE.md`、`docs/glossary.md`、`docs/quality/QUALITY.md`、`docs/quality/tech-debt.md`（视频反复生成撑大快照库，设计 §10）、`docs/plans/TODO.md`、`docs/runbooks/verification.md`（若冒烟命令有新增）。
- **接口与要点**：
  - Claude 冒烟：创建 `open` 项目，消息"按 style 做一个 10 秒的标题动画，用 HTML 写，最后用 ffmpeg 导出 `out.mp4`；开始前先运行 `npm view left-pad version` 并告诉我结果"。断言：工作区有 `out.mp4` 且 ffprobe 时长 > 0；工具结果里 `npm view` 成功；会话 init 消息里 `tools` 含 TodoWrite、不含禁用工具（佐证 preset 与工具集）。
  - Codex 冒烟：消息"运行 `curl -sI https://example.com` 并告诉我状态码"，断言回复含 `200`。
  - L4：`make dev`，浏览器走设计 §8 的手动验收，截图存 `docs/plans/active/open-mode-l4/`（收尾时随计划移动）。
  - ADR 0031 内容见设计 §9；ARCHITECTURE 模块表加 `stages.open`、`stages.common.narration.tts`，更新阶段协议说明与 `workspace` 排除规则。
- **测试**：冒烟本身。
- **完成标准**：AC6、AC7 有证据；AC8 文档项全部完成。
- **验证命令**：`make smoke SMOKE_ARGS="-k open"`、`make check`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-10-16 — 计划草稿完成，负责人批准，选择内联执行
- 2026-10-16 — T1 — `OPEN_KIND`/`OPEN_STAGE`、预设卡片、`theme` 与 `project.md`、video-kinds 标题；make check 绿

- 2026-10-16 — T2 — `EXCLUDED_DIR_NAMES` + `layout.in_excluded_dir`；快照扫描、文件树、guard 的符号链接清理、空目录清理都跳过依赖目录；make check 绿

- 2026-10-16 — T3 — 协议 `system_prompt() -> str | None`、`exec_network`；所有阶段与测试替身补 `exec_network = False`；三个运行时遇到 `None` 暂时抛 `NotImplementedError`（D2）；make check 绿

- 2026-10-16 — T4 — Claude：`None` → `claude_code` preset；`sandbox_settings(network=True)` 加 `allowedDomains=["*"]`；实测结论进 references（D3、D4）；make check 绿

- 2026-10-16 — T5 — OpenAI：`None` → 不发 instructions；`seatbelt_profile(network=True)`、`LocalShellExecutor(network=)`；回环真实执行测试；make check 绿

- 2026-10-16 — T6 — Codex：`None` 时 `developer_instructions` 只剩"不要派生子 agent"一句（D5）；`prompt_digest(None)="default"`、不拼 `PROMPT_UPDATE`；`permissions.studio.network.enabled=true`（实测）；make check 绿

- 2026-10-16 — T7 — `tts` 工具（`stages/common/narration/tts.py`）、`stages.common.open_scope`、`stages.open` 注册；`open` 定稿即标记项目完成、重新打开清除；渲染与 `finalize-render` 返回 409（D1、D6、D7）；make check 绿

## 下一步

- T8：前端创建入口与标记。先写 `NewFreeProjectDialog.spec.ts`（选「完全自由」后请求体 `{mode:"open", title, theme?}`、主题框出现、配乐控件隐藏）与 `stageTitles.spec.ts` 的失败用例。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- D1（2026-10-16，写计划时）— `animation_stage_of` 对 `open` 返回 `OPEN_STAGE`，由 `require_live_animation_stage` 统一拒绝（409），而不是设计 §6 写的"返回 `None`"。理由：现有函数返回 `str` 且以 Manim 下线阶段为兜底，改成可空会波及所有调用方；集中在一个检查点拒绝更不容易漏，文案也更准确（不会误报"Manim 已下线"）。不改变设计意图（`open` 没有渲染、`finalize-render`、场景检查）。
- D3（2026-10-16，T4）— 完全自由阶段的 Claude 内置工具**沿用现有的显式列表**（Read/Write/Edit/Glob/Grep/Bash，`allow_web` 时加 WebSearch/WebFetch），不扩展、不用 tools preset，也不需要 `disallowed_tools` 名单。理由：实测本机 CLI 2.1.283 的 preset 工具名单里没有 Glob/Grep/TodoWrite/MultiEdit，多出来的是 Cron/Worktree/Workflow/SendMessage/Skill 等依赖宿主 UI 或会改变会话的工具，事件流和画布都接不住；系统提示词已经是 Claude Code 默认，这些工具缺席时模型会退回用 Bash。代价：子 agent（`Task`）不可用；以后需要时按需加入列表并验证事件流。
- D4（2026-10-16，T4）— Claude 沙箱联网用 `network.allowedDomains=["*"]`（实测可行），不需要域名白名单回退，`sandbox_paths` 不加 `OPEN_NETWORK_DOMAINS`。
- D5（2026-10-16，T6）— Codex 在 `system_prompt is None` 时仍传 `developer_instructions`，内容只有现有的"不要派生子 agent、不要用协作工具"一句。理由：这个 codex 版本关不掉 `collaboration.*` 工具（references/codex.md），子 agent 的事件本项目接不住；这句话是运行时的接入约束，不是阶段提示词。代价：与设计 §5.1"不传阶段指令"字面上略有出入，但不含任何阶段内容。
- D6（2026-10-16，T7）— `tts` 只接受 `.mp3`（计划写的是 `.mp3`/`.wav`）。理由：TTS 引擎只产出 mp3 字节，转成 wav 要再调 ffmpeg，agent 需要 wav 时可以自己在 Bash 里转。可写判断用新模块 `stages.common.open_scope.OPEN_WRITE_SCOPE`（`open` 阶段与 `tts` 共用），因为 `ToolContext` 不带可写范围、`common` 也不能 import 具体阶段。`open` 阶段的工具除 `tts` 外还带自建 `web_search`/`fetch_url`：只在 `tools` 联网模式下保留（native 模式 runner 会滤掉），否则 `tools` 模式下完全自由阶段没有联网工具。
- D7（2026-10-16，T7）— 场景检查接口（GET `.../scene-checks`）对 `open` 项目不返回 409，而是照现有逻辑返回"未检查"（`_CHECKED_STAGES` 不含 `open`）：它是只读查询，不算渲染路径。`html-preview` 对 `open` 项目因为没有时间轴返回 409（现有 `TimelineError` 分支），前端也不会调用它。
- D2（2026-10-16，写计划时）— T3 中三个运行时遇到 `system_prompt=None` 先显式抛 `NotImplementedError`，T4–T6 逐个实现。理由：每个任务结束都要 `make check` 绿，又不能让 `None` 被悄悄当成空串传下去。

## 意外与发现

- 2026-10-16（T2）— guard 的 `_find_symlinks` 会删掉工作区里所有符号链接，`npm install` 生成的 `node_modules/.bin/*` 会被当成越界还原掉；计划只写了快照与文件树，这里一并让它跳过依赖目录（有测试 `test_dependency_dirs_keep_their_symlinks_and_files`）。`prune_empty_dirs` 同理，不清理依赖目录里的空目录。

## 阻塞

- 无

## 验证记录

- 无
