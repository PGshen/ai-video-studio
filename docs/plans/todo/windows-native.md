# windows-native：原生支持 Windows

<!-- 本计划实现 docs/design/2026-10-09-windows-native-support.md。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已批准（暂缓） |
| 里程碑 | 平台支持（不在架构设计 §10 的编号里程碑中） |
| 设计依据 | [windows-native-support 设计](../../design/2026-10-09-windows-native-support.md)（负责人 2026-10-09 批准） |
| 分支 | `windows-native`，从 main 切出；两台机器通过 `origin` 同步 |
| 批准记录 | 2026-10-09：负责人批准计划；D1 选备选方案（T1–T11 全部在 Windows 上做），会话内直接执行 |
| 执行方式 | 会话内直接执行（不派子代理），完成后由一个独立评审检查整个分支；T1–T11 在 Windows 上，T12 回到 macOS |

## 目标

负责人在自己的 Windows 11 电脑上（原生环境，不用 WSL）能装好依赖、启动三个进程、在浏览器里完整做出讲解类和短片的成片；同时能在 Windows 上跑完整的质量关口（`tasks.py check`），开 Claude Code 会话按 SOP 继续开发。macOS 上的用法、行为和安全性都不倒退。

## 范围

**包含：** `.gitattributes` 与 UTF-8 规则；统一的模型路径校验；跨平台进程管理 `studio/proc.py`；执行策略 `agent/exec_policy.py` 与开关 `STUDIO_ALLOW_UNSANDBOXED_EXEC`（含设置页、轮次标记）；`scripts/tasks.py` 替代 bash 工具链（Makefile 改成薄壳）；测试的平台标记；Windows 上的实测、修复与安装文档；ADR 0024、0025；相关技术债登记。

**不包含：** Linux 和 WSL 的正式支持；Windows 上自建的读隔离；安装器或打包成 exe；`export_legacy_styles.sh` 和 `build_fonts.sh` 的 Windows 版；CI；给 manim 执行 agent 代码加 sandbox（只登记技术债）。

## 全局约束

- 设计 §2：**不引入新依赖**（Python 和前端都不加）；Windows 上结束进程树用系统自带的 `taskkill /T /F`。
- 开关名是 `STUDIO_ALLOW_UNSANDBOXED_EXEC`，默认 `false`；**在 macOS 上无效**，`sandboxed` 永远优先（设计 §4.2 的表）。
- 开关关闭时 Claude 路径**不传** `sandbox` 设置（不用 `failIfUnavailable`），只靠 `allowed_tools` 和 `disallowed_tools` 把 `Bash`、`PowerShell` 去掉（设计 §4.3）。
- 模型路径的校验规则两个平台一样，不按 `sys.platform` 分支（设计 §5）。
- `scripts/tasks.py` **只用标准库**，不 import `studio`；Makefile 各目标只有一行，转调 `tasks.py`；`make check` 仍然是质量关口的名字。
- `.dev/`（pid 文件）不放在 `data/` 下，并加进 `.gitignore`。工作区仍然不能在 uvicorn reload 的监听范围内（AGENTS.md 红线）。
- 平台相关的跳过只能用 `conftest.py` 里统一定义的 `posix_only`、`macos_only` 标记和"能否建符号链接"的探测 fixture，每处写明原因。不用 `xfail`、`# type: ignore`、`noqa`。
- **质量关口（D1）**：T1–T8 在 Windows 上做，此时 `tasks.py check` 还不可能全绿。开工前在「意外与发现」里记一份 **Windows 基线失败清单**（失败的测试 id 和失败原因的类别）；每个任务的完成标准改为"和基线比没有新增失败，并且本任务负责修复的那些失败已经消失"，提交时在「进度」里写明剩余失败数。T1 完成之前用 `cd backend; uv run pytest` 和 `uv run ruff check .` 代替。macOS 上的回归统一在 T12 补上；POSIX 分支的真实测试（例如 `killpg` 清理孙进程）在 Windows 上会被跳过，T12 必须在 macOS 上确认它们执行过并且通过。T9 结束时 Windows 上必须全绿。
- 每个任务结束时跑完质量关口并读完结果；至少一个 commit，格式 `<type>(<scope>): <中文说明>`；结束会话前 push，让另一台机器能接着做。
- 外部行为以 `docs/references/` 为准；在 Windows 上实测的新结论补进 references，注明日期和"Windows 11 实测"。

## 审查重点

设计隐含、但各任务测试不一定覆盖的输入或状态，每条都在对应任务里有一条测试：

1. **模型给出混合写法的路径**：`notes\..\..\x`、`C:/x`、`c:x`（盘符相对路径）、`\\?\C:\x`、`a/b:stream`、`CON.txt`、`aux`、`dir./x`、`x ` 结尾有空格。在两个平台上都要被拒绝；`narrative/./timing.json` 这类现有合法写法仍然通过（T3）。
2. **pid 文件过期、pid 已被别的进程复用**：`tasks.py dev` 绝不能结束不属于本项目的进程。POSIX 上看命令行里有没有仓库路径；Windows 上用 `tasklist` 看映像名是不是 `python.exe`、`uv.exe`、`node.exe`，并且命令行里有仓库路径（T7）。
3. **开关在一轮对话进行中被切换**：只从下一轮生效，本轮的工具集和沙箱不变；macOS 上切换开关不改变任何行为（T5）。
4. **子进程输出中文**：在系统编码不是 UTF-8 的环境里，manim 的 dry-run 报错、配乐脚本读取中文 JSON、Shell 的 `echo 中文` 都不出乱码（T4 断言子进程环境里有 `PYTHONUTF8=1`；T10 在 Windows 上实测）。
5. **`backend/.env` 的写法**：引号里有空格、`#` 注释、空行、`export KEY=...`、值里有 `=`，`tasks.py` 解析出的结果要和 `set -a; . backend/.env` 一致；遇到不支持的写法（变量展开 `$X`、命令替换）时明确报错，不静默错读（T6）。
6. **Ctrl+C 时正在渲染**：worker 正在跑 ffmpeg 和 Chromium 时退出 `tasks.py dev`，不留下孤儿进程（T7 在 macOS 上测；T11 在 Windows 上测）。

## 验收标准

- [ ] AC1：macOS 不倒退。`make check` 全绿；`make dev` 启动、退出后没有孤儿进程；`make smoke SMOKE_ARGS="-k claude_login"` 通过；Seatbelt 下 OpenAI Shell 和 `render_music` 的已有测试通过。（验证：命令输出、`ps` 检查）
- [ ] AC2：Windows 上在开发者模式开启的情况下，`uv run --project backend python scripts/tasks.py check` 全绿，测试报告里符号链接相关的用例是执行了而不是被跳过；`git commit` 时 pre-commit hook 能运行。（验证：完整输出、`pytest -rs` 的跳过列表）
- [ ] AC3：Windows 上 `tasks.py dev` 能启动三个进程；Ctrl+C 退出后任务管理器里没有残留的 python、node、ffmpeg 或 chromium 进程；再次启动不会报"端口被占用"。（验证：`tasklist` 输出）
- [ ] AC4：Windows 上开关关闭时，Claude 和 OpenAI 两条路径都拿不到 Shell，`render_music` 返回的错误里提到设置页开关；打开开关后，下一轮能执行命令，界面显示"命令未隔离"，越界写入被 `guard` 还原。（验证：Fake 运行时的集成测试 + Windows 上用 `claude-login` 实测 + 截图）
- [ ] AC5：Windows 上用 `claude-login` 完整做一个讲解类项目（manim）和一个短片（HTML 引擎 + 合成配乐，开关打开），成片能播放，中文显示正常。（验证：成片文件、关键帧截图）
- [ ] AC6：设计 §5 列出的恶意路径在 Windows 上全部被拒绝。（验证：T3 的测试在 Windows 上运行过）
- [ ] AC7：ADR 0024 和 0025 已写；AGENTS.md、dev-setup（Windows 一节）、verification、ARCHITECTURE、references、tech-debt、QUALITY 已同步。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞。「机器」= 该任务的质量关口在哪台机器上跑。 -->

### T1：任务脚本骨架与行尾（待开始，机器：Windows，按基线对比）

- **目标**：`scripts/tasks.py` 接管除 `dev` 以外的全部命令；Makefile 变成薄壳；仓库行尾统一为 LF。完成后 Windows 上就有了能跑的质量关口入口（结果暂时是红的）。
- **涉及文件**：新增 `scripts/tasks.py`、`.gitattributes`、`backend/tests/scripts/test_tasks.py`（以及 `__init__.py`）、`docs/decisions/0025-Python任务脚本.md`；修改 `Makefile`、`.githooks/pre-commit`、`AGENTS.md`「常用命令」、`docs/runbooks/dev-setup.md`（命令写法）。
- **接口与要点**：
  - 子命令：`setup`、`check`、`check-fast`、`check-docs`、`check-backend`、`check-frontend`、`smoke`、`import-legacy-styles`（`dev` 留到 T7，Makefile 的 `dev` 暂时仍然调用 `scripts/dev.sh`）。命令内容和现在的 Makefile 一致，任意一步失败就以非零码退出，并打印失败的是哪一步。
  - 可以 import 的纯函数（供测试使用）：`find_uv() -> str`、`find_pnpm() -> str`（先 `shutil.which`，再看各平台的常见安装位置，找不到就报错并给出安装提示）；`parse_dotenv(text: str) -> dict[str, str]`；`smoke_env(base: Mapping[str, str], dotenv: Mapping[str, str], keys: Sequence[str], platform: str) -> dict[str, str]`。
  - `parse_dotenv` 支持的写法：`KEY=VALUE`、单引号和双引号、`#` 整行注释和行尾注释（引号外）、空行、`export ` 前缀、值里有 `=`。遇到 `$`（引号外或双引号内）、反引号时抛 `ValueError`，并指出是第几行。
  - `smoke_env` 的白名单见设计 §8.3；`SMOKE_KEYS` 从 Makefile 搬过来。
  - Makefile：每个目标一行，形如 `@$(UV) run --project backend python scripts/tasks.py check`；`UV` 的定位逻辑保留，因为它是调用 `tasks.py` 的前提。
  - `.gitattributes`：`* text=auto eol=lf`，二进制资产标为 `binary`（设计 §7）。提交前运行 `git add --renormalize .`，确认 `git status` 里没有内容变化；如果有，就停下来记录。
  - pre-commit hook：调用 `tasks.py check-fast`；先找 `uv`（PATH 里没有就试 `~/.local/bin/uv`），保持 sh 语法。
  - ADR 0025：`tasks.py` 是工具链逻辑的唯一来源，Makefile 只是薄壳；Windows 上的写法；不迁移 `export-legacy-styles`。
- **测试**：先写 `test_tasks.py`，用 `importlib` 按文件路径加载 `scripts/tasks.py`。覆盖：`parse_dotenv` 的全部写法和报错（审查重点 5，另外用一份夹具在 macOS 上和 `bash -c 'set -a; . file; env'` 的结果逐项比较，这条用例标 `posix_only`，T8 之前先用 `sys.platform` 判断）；`smoke_env` 两个平台的白名单；`find_uv` 在 PATH 里没有时会去找候选位置。
- **完成标准**：Windows 上 `tasks.py check`、`check-fast` 能运行（结果对照基线），提交时 hook 能运行；Makefile 薄壳在 macOS 上的等价性（`make check` 与 `tasks.py check` 结果一致、`make smoke` 照常）留到 T12 确认。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）；`uv run --project backend python scripts/tasks.py check-docs`。

### T2：文本 IO 一律 UTF-8（待开始，机器：Windows，按基线对比）

- **目标**：把"文本 IO 显式写 UTF-8"变成 lint 规则，并修好现有的违规。
- **涉及文件**：`backend/pyproject.toml`（ruff 的 `select` 加上 `PLW1514`）；所有被报出来的位置，已知的有 `stages/common/score/exemplar/audio-techniques.py`；`scripts/tasks.py`、`scripts/check_docs.py`。
- **接口与要点**：
  - 只加 `PLW1514`，不打开整个 `PL` 规则集。
  - `scripts/` 下的 Python 文件不在 `backend` 的 ruff 检查范围内。`tasks.py check-backend` 额外对 `scripts/*.py` 跑一次 `ruff check --select PLW1514`，或者在 `scripts/` 下加一份 ruff 配置，二选一并写进决策记录。
  - 范例脚本 `audio-techniques.py` 是给模型照抄的，改完后要确认对应的提示词和测试没有逐字依赖原来的写法。
- **测试**：lint 规则本身就是检查；另外加一条测试，在一个临时文件里写入没有 `encoding` 的 `open()`，确认 ruff 会报出来，防止以后有人把规则删掉。
- **完成标准**：质量关口满足 D1，`ruff check` 报告里有这条规则。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）。

### T3：统一的模型路径校验（待开始，机器：Windows，按基线对比）

- **目标**：设计 §5——不管在哪个平台，盘符、反斜杠、UNC、保留名之类的路径都在第一道检查就被拒绝。
- **涉及文件**：`backend/src/studio/workspace/files.py`（新增 `check_model_path`，`normalize_relpath` 和 `safe_path` 改成调用它）、`backend/src/studio/agent/apply_patch.py`（`to_workspace_relpath`）、`backend/src/studio/agent/claude_scope.py`（读写 hook、Glob 模式检查）、`backend/src/studio/agent/fallback_tools.py`（如果它有自己的路径判断，同样接入）；测试 `backend/tests/workspace/test_model_path.py`，以及 `test_files.py`、`test_apply_patch.py`、`test_claude_runtime.py` 里相关的用例。
- **接口与要点**：
  - `check_model_path(relpath: str) -> PurePosixPath`：相对路径的规范化加校验，失败时抛 `ScopeError`，消息里带上原始路径。拒绝规则严格按设计 §5 列的清单。
  - 绝对路径的入口（Claude 的 `file_path`、`apply_patch` 的绝对路径）：判断"是否在工作区内"时，两边都先 `resolve()` 再 `os.path.normcase`，然后才比较。这个比较集中写在一个函数里（例如 `workspace.files.relpath_within(workdir, raw) -> str`），hook 和 `apply_patch` 共用，不各写一份。
  - Glob 模式：在现有检查（`/`、`~`、`..`）的基础上，同样拒绝盘符、`\` 和 `:`。
- **测试**：参数化表格覆盖设计 §5 的所有写法和审查重点 1，每条都断言抛 `ScopeError`；另有一组现有的合法写法断言能通过。hook 测试要模拟 Windows 风格的绝对路径（用 `PureWindowsPath` 构造的输入），断言被拒绝。
- **完成标准**：质量关口满足 D1，已有的路径相关测试不需要修改就能通过。如果需要修改，就停下来，在「意外与发现」里说明原因。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）。

### T4：跨平台进程管理 `studio/proc.py`（待开始，机器：Windows，按基线对比）

- **目标**：设计 §6——统一启动受控子进程的参数、结束整棵进程树的方式和 UTF-8 环境；替换所有 `killpg`、`start_new_session` 和只结束顶层进程的 `proc.kill()`。
- **涉及文件**：新增 `backend/src/studio/proc.py`、`backend/tests/test_proc.py`；修改 `engines/audio/runner.py`（`limited_argv` 按平台分支，删除 `kill_group`）、`engines/audio/song_job.py`、`engines/audio/song.py`（同步的 `subprocess.run`）、`engines/audio/probe.py`、`engines/render/manim/process.py`、`engines/render/manim/engine.py`、`engines/render/manim/keyframes.py`、`engines/render/html/video.py`、`engines/render/mix.py`、`agent/shell.py`；`backend/pyproject.toml`（新增 import-linter 契约：`studio.proc` 不依赖任何其他 `studio` 模块）；`docs/ARCHITECTURE.md`。
- **接口与要点**：
  - `spawn_kwargs(platform: str | None = None) -> dict[str, Any]`；`async kill_tree(proc: asyncio.subprocess.Process, *, platform: str | None = None) -> None`；`kill_tree_sync(pid: int, *, platform: str | None = None) -> None`（供 `subprocess.run` 超时的情况以及 T7 使用）；`child_env(base: Mapping[str, str]) -> dict[str, str]`（复制一份，并加上 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`）。
  - Windows 分支：`creationflags=CREATE_NEW_PROCESS_GROUP`；`taskkill /T /F /PID <pid>`，输出丢弃，失败时退回 `proc.kill()`。
  - `limited_argv(argv, cpu_seconds, *, platform=None)`：POSIX 保持现状；Windows 原样返回 `argv`。`run_compose` 结束后检查 `music.wav` 的大小，超过 `_MAX_FILE_BYTES` 就当作失败。这个检查两个平台都做。
  - 现在所有向子进程传 `env=` 的地方都改成经过 `child_env`；没有传 `env` 的地方（继承父进程的环境）保持继承，但也要加上 UTF-8 变量。逐处判断，写进决策记录。
  - 外部程序的输出统一用 `decode("utf-8", errors="replace")`。
- **测试**：`spawn_kwargs`、`limited_argv` 用参数注入测两个分支；`kill_tree` 在 POSIX 上真实测试：启动一个会派生孙进程的 Python 子进程，`kill_tree` 之后孙进程也不在了；Windows 分支 mock `taskkill` 的调用，断言参数正确。已有的 `test_audio_runner.py`、`test_shell.py` 等对 `killpg` 的 mock 改为针对 `kill_tree`。审查重点 4：断言 manim dry-run、`run_compose`、Shell executor 收到的环境里有 `PYTHONUTF8=1`。
- **完成标准**：`grep -rn "killpg\|start_new_session" backend/src` 只剩 `proc.py` 里的结果；质量关口满足 D1。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）；`cd backend && uv run pytest -m slow -k "manim or html_video or mix"`（真实子进程，确认没有倒退）。

### T5：执行策略与开关（待开始，机器：Windows，按基线对比）

- **目标**：设计 §4.2、§4.3 的后端部分：`exec_mode` 决定两条运行时路径和 `render_music` 的行为；开关来自环境变量，设置页可以覆盖。
- **涉及文件**：新增 `backend/src/studio/agent/exec_policy.py`、`backend/tests/agent/test_exec_policy.py`、`docs/decisions/0024-无隔离执行开关.md`；修改 `config.py`（`allow_unsandboxed_exec: bool = False`）、`db/repo/settings.py`（新键 `allow_unsandboxed_exec`，以及 `effective_allow_unsandboxed_exec`，仿照 `effective_web_mode`）、`agent/runner.py`（每轮开始时计算 `exec_mode`，放进 `TurnContext`）、`agent/claude_runtime.py` 和 `claude_scope.py`、`agent/openai_runtime.py`（`native_shell_supported` 改为根据 `exec_mode` 判断）、`agent/shell.py`（`LocalShellExecutor` 支持不包裹 sandbox 的模式）、`stages/common/score/tool.py`（`sandbox_wrapper` 改为根据 `exec_mode` 判断，三种模式三种行为）、`agent/events.py` 或轮次元数据（记录本轮的 `exec_mode`，供 T6 显示）。
- **接口与要点**：
  - `ExecMode = Literal["sandboxed", "unsandboxed", "disabled"]`；`exec_mode(*, platform: str, sandbox_available: bool, allow_unsandboxed: bool) -> ExecMode`，严格按设计 §4.2 的表。
  - "Claude 路径有没有 sandbox"的判断：`sys.platform in ("darwin", "linux")`。注意 Linux 这次不做正式支持，但 Claude sandbox 在 Linux 上可用，所以 Linux 走 `sandboxed`；OpenAI Shell 和 `render_music` 用的是 `sandbox-exec`，Linux 上仍然没有。因此**每个执行点各自传入"本执行点有没有 sandbox"**，`exec_mode` 只负责做决定。这一条写进决策记录。
  - Claude：`disabled` 时 `allowed_tools` 里没有 `Bash`，`disallowed_tools` 里有 `Bash` 和 `PowerShell`，不传 `sandbox`；`unsandboxed` 时放行 `Bash` 和 `PowerShell`，不传 `sandbox`；`sandboxed` 和现在完全一样。
  - `render_music` 在 `disabled` 时的错误文案要说明"这台机器上没有 sandbox"，并指出设置 → 通用里的开关。
  - 开关在本轮开始时读取一次，本轮之内不变（审查重点 3）。
  - ADR 0024 按设计 §10 撰写。
- **测试**：`exec_mode` 的完整真值表；Claude 运行时三种模式下的 `ClaudeAgentOptions`（`allowed_tools`、`disallowed_tools`、`sandbox`）；OpenAI 运行时三种模式下是否提供 Shell；`render_music` 三种模式下各自的包裹函数和错误；设置覆盖的优先级（界面设置 > 环境变量 > 默认值）；本轮进行中修改设置不影响本轮（审查重点 3）；在 macOS 上把开关设为 `true`，结果仍然是 `sandboxed`。
- **完成标准**：质量关口满足 D1；macOS 上的已有行为不变（已有的运行时测试不需要修改就能通过）。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）。

### T6：设置页开关与"命令未隔离"标记（待开始，机器：Windows，按基线对比）

- **目标**：设计 §4.3 的界面部分。
- **涉及文件**：`backend/src/studio/api/`（设置接口和"通用"那一组：读写 `allow_unsandboxed_exec`，返回 `sandbox_available` 和当前生效的 `exec_mode`）；`frontend/src/` 中设置 → 通用的组件、轮次标记组件、API 类型；对应的后端接口测试和 vitest。
- **接口与要点**：
  - 开关只在 `sandbox_available=false` 时显示；文案说明风险（参照设计 §4.1 最后一段），并注明"下一轮对话起生效"；和联网模式共用"清除界面设置"。
  - `exec_mode == "unsandboxed"` 的轮次显示"命令未隔离"标记，放在轮次元信息里现有标记的旁边。T5 已经把 `exec_mode` 记进轮次数据。
  - 这一步要先读现有的联网模式设置和轮次标记的实现，照着它们的结构来写，不新建一套模式。
- **测试**：接口测试（读写、清除、`sandbox_available` 为真或假时的返回）；vitest：开关的显示条件、标记的显示条件。
- **完成标准**：质量关口满足 D1；在 Windows 上用 Fake 运行时在内置浏览器里看一眼（Windows 上 `sandbox_available` 本来就是 `false`），开关和标记都能显示，并截图。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）；L4 截图。

### T7：`tasks.py dev`（待开始，机器：Windows，按基线对比）

- **目标**：设计 §8.2——用 Python 启动 api、worker 和前端三个进程，基于 pid 文件清理旧进程，退出时结束整棵进程树；删除 `scripts/dev.sh`。
- **涉及文件**：`scripts/tasks.py`（`dev` 子命令）、`.gitignore`（`.dev/`）、`Makefile`（`dev` 改为一行）、删除 `scripts/dev.sh`、`.claude/launch.json`（如果需要调整）、`docs/runbooks/dev-setup.md`；测试 `backend/tests/scripts/test_tasks_dev.py`。
- **接口与要点**：
  - `spawn_kwargs` 和 `kill_tree` 的同步版本复制进 `tasks.py`，注释里指向 `backend/src/studio/proc.py`（设计 §8.2）。
  - pid 文件：`<仓库根>/.dev/pids.json`，内容是 `[{"name", "pid", "cmd"}]`。启动前，对其中每个还活着的 pid 确认属于本项目（审查重点 2）后才结束它；不属于本项目的就跳过，并提示一句。
  - 端口仍被占用时，报错并给出占用者的 pid（POSIX：`lsof -nP -iTCP:<port> -sTCP:LISTEN -t`；Windows：解析 `netstat -ano`），不结束它。
  - 三路输出加上 `[api]`、`[worker]`、`[web]` 前缀，用线程转发到当前终端；stdin 一律 `DEVNULL`（保留 `dev.sh` 里关于 SIGTTIN 的教训，写进注释）。
  - `.env` 用 T1 的 `parse_dotenv` 解析；绑定地址仍然来自 `python -m studio.config`；导出 `STUDIO_BIND_PORT`。
  - 退出：处理 `KeyboardInterrupt`（POSIX 上还要处理 SIGTERM），对三个进程逐个 `kill_tree`，然后删除 pid 文件。任意一个子进程意外退出时，整体退出并报告是哪一个。
- **测试**：pid 文件读写；"是否属于本项目"的判断（注入 `ps`、`tasklist` 的输出）；`netstat -ano` 的解析（夹具）；审查重点 2 的场景。启动和结束用一个假的子命令（例如三个 `python -c "sleep"`）在 POSIX 上做真实测试，断言退出后进程树清空（审查重点 6 的 macOS 部分）。
- **完成标准**：Windows 上 `tasks.py dev` 能启动，Ctrl+C 后 `tasklist` 里没有本项目残留的进程；连续启动两次第二次能正常清理；质量关口满足 D1。macOS 上的 `make dev` 验证在 T12 做。
- **验证命令**：`tasks.py check`；手动 `tasks.py dev` → Ctrl+C → `tasklist /FI "IMAGENAME eq python.exe"`、`tasklist /FI "IMAGENAME eq node.exe"`。

### T8：测试的平台标记（待开始，机器：Windows，按基线对比）

- **目标**：只适用于 POSIX 或 macOS 的测试在 Windows 上被有理由地跳过；需要符号链接的测试在没有权限时跳过并给出提示；其余测试在 Windows 上都应该能跑。
- **涉及文件**：`backend/tests/conftest.py`（`posix_only`、`macos_only` 标记的注册和跳过逻辑，`symlinks_supported` fixture）、`backend/pyproject.toml`（`markers`）；设计 §3 P11 提到的约 28 个测试文件（用 `grep -rlE "killpg|sandbox-exec|/bin/sh|chmod|symlink_to|os\.symlink" backend/tests` 找出来）。
- **接口与要点**：
  - 每个标记的 docstring 都写明原因，并且必须有对应的 Windows 测试（T3、T4、T5 已经写了参数注入的版本），或者说明 Windows 上这个功能本来就没有。
  - 涉及 `chmod` 的测试（`upstream` 只读）：Windows 上能测的部分（文件只读属性）保留，测目录权限位的部分标 `posix_only`。
  - 测试里的路径断言如果用了 `str(path)` 拼接 `/`，改成 `as_posix()` 或 `Path` 比较。逐个文件 grep 检查，但不在 macOS 上猜测 Windows 的失败；没有把握的留到 T9 实测。
- **测试**：这个任务本身就是改测试；另外加一条元测试：确认 `posix_only` 在 `sys.platform == "win32"` 时确实会跳过（用 `pytester` 或直接调用 hook 函数）。
- **完成标准**：Windows 上原本因 POSIX 依赖失败的测试变成"有理由的跳过"，`pytest -rs` 的跳过列表逐条有理由；macOS 上一个都不应该跳过，这一点在 T12 确认。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）；`cd backend && uv run pytest -rs | tail -20`。

### T9：Windows 首次跑通质量关口（待开始，机器：Windows）

- **目标**：在 Windows 上装好环境，让 `tasks.py check` 全绿。
- **涉及文件**：按实测结果修改；`docs/runbooks/dev-setup.md`（新增 Windows 一节，按设计 §9.3 的表，写成实测确认过的版本）；`docs/references/`（新增或补充 Windows 相关的实测结论）。
- **接口与要点**：
  - 先按设计 §9.3 安装依赖，打开开发者模式，把仓库放在较短的路径下（如 `C:\dev\ai-video-studio`），运行 `git config core.autocrlf false`，然后 `tasks.py setup`。
  - 跑 `tasks.py check`，逐个修失败。原则：Windows 特有的问题修代码；确实是平台差异的，按 T8 的规则加标记，每加一处都写进决策记录。
  - **P13**：确认 uvicorn `--reload` 下 asyncio 子进程能用。写一条测试，或者启动后触发一次 ffprobe。有问题按设计 §12 处理。
  - **P14**：确认桌面版 `preview_start` 能启动 `launch.json` 里的 api 和 frontend；不能启动就调整 `launch.json`（例如改用 `pnpm.cmd`，或者改用 `uv run` 来启动），并确认 macOS 上还能用。
  - 确认 manim 的安装情况（wheel 是否自带 cairo、pango；MiKTeX 能否找到 `ctex`），写进 `docs/references/manim.md`。
- **测试**：Windows 上 `tasks.py check` 全绿；`uv run pytest -rs` 的跳过列表逐条都有理由；`uv run pytest -m slow` 也在 Windows 上跑一遍，失败的修掉或者登记。
- **完成标准**：AC2；回到 macOS 后 `make check` 仍然全绿（如果这个任务改了代码，下一次在 macOS 上的会话先确认这一点）。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`；`cd backend; uv run pytest -m slow`。

### T10：Windows 上的执行策略实测（待开始，机器：Windows）

- **目标**：验证设计 §4.3 在真实的 Windows 版 Claude CLI 和 OpenAI 路径上成立，并处理文件占用（P12）。
- **涉及文件**：按实测结果修改 `agent/claude_runtime.py`、`agent/shell.py` 等；`docs/references/claude-agent-sdk.md`（Windows 上的工具名、`disallowed_tools`、不传 sandbox 时的行为、Bash 是否需要 Git Bash）；如果需要加重试，修改 `workspace/` 中的删除和改名逻辑。
- **接口与要点**：
  - 用 `claude-login` 实测：开关关闭时，让 agent 执行命令，确认它没有 Bash 或 PowerShell 工具可用；打开后能执行 `echo 中文` 并且没有乱码；让它往可写范围外写一个文件，确认 `guard` 能还原。
  - 实测结果和设计 §4.3 不一致（例如 PowerShell 工具名不同，或者 `disallowed_tools` 没有生效），按 SOP §6 第 1 条停下来升级。
  - P12：在 Windows 上反复执行回滚、`guard` 还原、重新渲染成片覆盖旧文件，看会不会出 `PermissionError`。出了就按设计 §12 加有限次重试，并写测试（用一个打开着的文件句柄来模拟占用）。
  - OpenAI 路径只有在官方 API 上才提供 Shell。负责人没有官方 key 时，这部分用 Fake 运行时的集成测试代替，并在验证记录里写明。
- **测试**：实测记录写进「验证记录」；为发现的每个问题补测试。
- **完成标准**：AC4。
- **验证命令**：`tasks.py check`；实测截图。

### T11：Windows 上完整走一遍（待开始，机器：Windows）

- **目标**：AC3、AC5——在 Windows 上用 `tasks.py dev` 启动，完整做出讲解类和短片两条成片。
- **涉及文件**：按实测结果修改；`docs/runbooks/verification.md`（Windows 上怎么自验证）。
- **接口与要点**：
  - `tasks.py dev` 启动，内置浏览器打开 `http://127.0.0.1:5173`。
  - 讲解类：选题 → 叙事 → 动画（manim）→ 成片。短片：`concept → produce`（HTML 引擎 + 合成配乐，开关打开）。检查成片的中文显示和配乐。
  - 渲染过程中按 Ctrl+C 退出，用 `tasklist` 确认没有残留的 python、node、ffmpeg 或 chromium；重新启动，确认 worker 能恢复或者把中断的任务标记为失败，和 macOS 上的行为一致（审查重点 6）。
- **测试**：发现问题就先补测试再修。
- **完成标准**：AC3、AC5，附截图和成片路径。
- **验证命令**：`tasks.py check`；`tasklist /FI "IMAGENAME eq python.exe"` 等。

### T12：收尾：macOS 回归与文档（待开始，机器：macOS）

- **目标**：AC1、AC7。
- **涉及文件**：`docs/quality/tech-debt.md`（manim 执行 agent 代码没有 sandbox；Windows 上没有 CPU 时间和文件大小的硬限制；Windows 上 `upstream/` 的只读保护变弱）、`docs/quality/QUALITY.md`、`docs/ARCHITECTURE.md`、`AGENTS.md`、`docs/plans/TODO.md`。
- **接口与要点**：在 macOS 上拉取 Windows 会话的全部改动；先确认 T1–T8 里在 Windows 上被跳过的 POSIX 测试在 macOS 上都执行了而且通过（`pytest -rs` 不应该有任何跳过），修掉 macOS 上的回归；然后跑 `make check`、`make dev`、`make smoke SMOKE_ARGS="-k claude_login"`；逐条核对 AC7 的文档清单；整理「意外与发现」，把应该改成机器检查的约定挑出来。
- **完成标准**：AC1、AC7；计划状态改为"待验收"。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k claude_login"`。

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 无

## 下一步

本计划已批准、暂缓执行，放在 `docs/plans/todo/`。负责人决定开工时，在 Windows 电脑上开 Claude Code 会话，按顺序执行：

0. `git mv docs/plans/todo/windows-native.md docs/plans/active/`，状态改为「执行中」，同步 TODO.md 里的链接，commit。

1. 按设计 §9.3 装好依赖（Git for Windows、uv、Node 22+ 和 pnpm、ffmpeg、MiKTeX、Claude Code），在 设置 → 系统 → 开发者选项 里打开开发者模式。
2. `git config --global core.autocrlf false`，然后把仓库 clone 到短路径下（例如 `C:\dev\ai-video-studio`），`git checkout windows-native`（分支已在 `origin` 上）。
3. 复制 `backend/.env`（从 Mac 上拷贝，不进仓库）。
4. 先手动装依赖：`cd backend; uv sync; uv run playwright install chromium`，`cd ..\frontend; pnpm install`。
5. 记录 Windows 基线：`cd backend; uv run pytest -p no:cacheprovider -q 2>&1 | Tee-Object ..\.dev-baseline.txt`（文件不入库），把失败数和按原因归类的清单写进「意外与发现」，commit。
6. 从 T1 开始，按任务循环（SOP §4）执行；每个任务结束时 commit 并 push。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-10-09 — **D1（负责人已决定：采用备选方案，T1–T11 全部在 Windows 上做，T12 回到 macOS）**。原推荐方案：T1–T8 的质量关口在 macOS 上跑。理由：T8 完成之前，Windows 上的 `tasks.py check` 必然大面积失败，在 Windows 上做 T1–T8 就没有可用的"绿色基线"来判断改动是否引入了回归。**备选**：T1–T8 也在 Windows 上做，开工前先记录一份 Windows 基线失败清单，每个任务的完成标准改为"没有新增失败，并且本任务负责修复的那些失败已经消失"。这样不用来回切换机器，但判断依据更弱，macOS 上的回归要等到 T12 才能发现。
- 2026-10-09 — 计划任务的顺序是先做工具链（T1），这样 Windows 上尽早有可以运行的 `tasks.py check`；`dev` 放在 T7，等 `proc.py`（T4）稳定之后再做。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 无

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无

## 验证记录

<!-- 自验证阶段填写：每条验收标准对应的命令、输出摘要、截图路径。 -->

- 无
