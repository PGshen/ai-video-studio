# windows-native：原生支持 Windows

<!-- 本计划实现 docs/design/2026-10-09-windows-native-support.md。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | 平台支持（不在架构设计 §10 的编号里程碑中） |
| 设计依据 | [windows-native-support 设计](../../design/2026-10-09-windows-native-support.md)（负责人 2026-10-09 批准） |
| 分支 | `windows-native`，2026-10-09 在 Windows 机器上从 main（`13fcef0`）切出；两台机器通过 `origin` 同步 |
| 批准记录 | 2026-10-09：负责人批准计划；D1 选备选方案（T1–T11 全部在 Windows 上做），会话内直接执行 |
| 执行方式 | 会话内直接执行（不派子代理），完成后由一个独立评审检查整个分支；T1–T11 在 Windows 上，T12 回到 macOS |

## 目标

负责人在自己的 Windows 11 电脑上（原生环境，不用 WSL）能装好依赖、启动三个进程、在浏览器里完整做出讲解类和短片的成片；同时能在 Windows 上跑完整的质量关口（`tasks.py check`），开 Claude Code 会话按 SOP 继续开发。macOS 上的用法、行为和安全性都不倒退。

## 范围

**包含：** `.gitattributes` 与 UTF-8 规则；统一的模型路径校验；跨平台进程管理 `studio/proc.py`；执行策略 `agent/exec_policy.py` 与开关 `STUDIO_ALLOW_UNSANDBOXED_EXEC`（含设置页、轮次标记）；`scripts/tasks.py` 替代 bash 工具链（Makefile 改成薄壳）；测试的平台标记；Windows 上的实测、修复与安装文档；ADR 0024、0025；相关技术债登记。

**不包含：** Linux 和 WSL 的正式支持；Windows 上自建的读隔离；安装器或打包成 exe；`export_legacy_styles.sh` 和 `build_fonts.sh` 的 Windows 版；CI。

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
4. **子进程输出中文**：在系统编码不是 UTF-8 的环境里，配乐脚本读取中文 JSON、Shell 的 `echo 中文` 都不出乱码（T4 断言子进程环境里有 `PYTHONUTF8=1`；T10 在 Windows 上实测）。
5. **`backend/.env` 的写法**：引号里有空格、`#` 注释、空行、`export KEY=...`、值里有 `=`，`tasks.py` 解析出的结果要和 `set -a; . backend/.env` 一致；遇到不支持的写法（变量展开 `$X`、命令替换）时明确报错，不静默错读（T6）。
6. **Ctrl+C 时正在渲染**：worker 正在跑 ffmpeg 和 Chromium 时退出 `tasks.py dev`，不留下孤儿进程（T7 在 macOS 上测；T11 在 Windows 上测）。

## 验收标准

- [ ] AC1：macOS 不倒退。`make check` 全绿；`make dev` 启动、退出后没有孤儿进程；`make smoke SMOKE_ARGS="-k claude_login"` 通过；Seatbelt 下 OpenAI Shell 和 `render_music` 的已有测试通过。（验证：命令输出、`ps` 检查）
- [ ] AC2：Windows 上在开发者模式开启的情况下，`uv run --project backend python scripts/tasks.py check` 全绿，测试报告里符号链接相关的用例是执行了而不是被跳过；`git commit` 时 pre-commit hook 能运行。（验证：完整输出、`pytest -rs` 的跳过列表）
- [ ] AC3：Windows 上 `tasks.py dev` 能启动三个进程；Ctrl+C 退出后任务管理器里没有残留的 python、node、ffmpeg 或 chromium 进程；再次启动不会报"端口被占用"。（验证：`tasklist` 输出）
- [ ] AC4：Windows 上开关关闭时，Claude 和 OpenAI 两条路径都拿不到 Shell，`render_music` 返回的错误里提到设置页开关；打开开关后，下一轮能执行命令，界面显示"命令未隔离"，越界写入被 `guard` 还原。（验证：Fake 运行时的集成测试 + Windows 上用 `claude-login` 实测 + 截图）
- [ ] AC5：Windows 上用 `claude-login` 完整做一个讲解类项目（HTML 引擎）和一个短片（HTML 引擎 + 合成配乐，开关打开），成片能播放，中文显示正常。（验证：成片文件、关键帧截图）
- [ ] AC6：设计 §5 列出的恶意路径在 Windows 上全部被拒绝。（验证：T3 的测试在 Windows 上运行过）
- [ ] AC7：ADR 0024 和 0025 已写；AGENTS.md、dev-setup（Windows 一节）、verification、ARCHITECTURE、references、tech-debt、QUALITY 已同步。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞。「机器」= 该任务的质量关口在哪台机器上跑。 -->

### T1：任务脚本骨架与行尾（完成，机器：Windows，按基线对比）

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

### T2：文本 IO 一律 UTF-8（完成，机器：Windows，按基线对比）

- **目标**：把"文本 IO 显式写 UTF-8"变成 lint 规则，并修好现有的违规。
- **涉及文件**：`backend/pyproject.toml`（ruff 的 `select` 加上 `PLW1514`）；所有被报出来的位置，已知的有 `stages/common/score/exemplar/audio-techniques.py`；`scripts/tasks.py`、`scripts/check_docs.py`。
- **接口与要点**：
  - 只加 `PLW1514`，不打开整个 `PL` 规则集。
  - `scripts/` 下的 Python 文件不在 `backend` 的 ruff 检查范围内。`tasks.py check-backend` 额外对 `scripts/*.py` 跑一次 `ruff check --select PLW1514`，或者在 `scripts/` 下加一份 ruff 配置，二选一并写进决策记录。
  - 范例脚本 `audio-techniques.py` 是给模型照抄的，改完后要确认对应的提示词和测试没有逐字依赖原来的写法。
- **测试**：lint 规则本身就是检查；另外加一条测试，在一个临时文件里写入没有 `encoding` 的 `open()`，确认 ruff 会报出来，防止以后有人把规则删掉。
- **完成标准**：质量关口满足 D1，`ruff check` 报告里有这条规则。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）。

### T3：统一的模型路径校验（完成，机器：Windows，按基线对比）

- **目标**：设计 §5——不管在哪个平台，盘符、反斜杠、UNC、保留名之类的路径都在第一道检查就被拒绝。
- **涉及文件**：`backend/src/studio/workspace/files.py`（新增 `check_model_path`，`normalize_relpath` 和 `safe_path` 改成调用它）、`backend/src/studio/agent/apply_patch.py`（`to_workspace_relpath`）、`backend/src/studio/agent/claude_scope.py`（读写 hook、Glob 模式检查）、`backend/src/studio/agent/fallback_tools.py`（如果它有自己的路径判断，同样接入）；测试 `backend/tests/workspace/test_model_path.py`，以及 `test_files.py`、`test_apply_patch.py`、`test_claude_runtime.py` 里相关的用例。
- **接口与要点**：
  - `check_model_path(relpath: str) -> PurePosixPath`：相对路径的规范化加校验，失败时抛 `ScopeError`，消息里带上原始路径。拒绝规则严格按设计 §5 列的清单。
  - 绝对路径的入口（Claude 的 `file_path`、`apply_patch` 的绝对路径）：判断"是否在工作区内"时，两边都先 `resolve()` 再 `os.path.normcase`，然后才比较。这个比较集中写在一个函数里（例如 `workspace.files.relpath_within(workdir, raw) -> str`），hook 和 `apply_patch` 共用，不各写一份。
  - Glob 模式：在现有检查（`/`、`~`、`..`）的基础上，同样拒绝盘符、`\` 和 `:`。
- **测试**：参数化表格覆盖设计 §5 的所有写法和审查重点 1，每条都断言抛 `ScopeError`；另有一组现有的合法写法断言能通过。hook 测试要模拟 Windows 风格的绝对路径（用 `PureWindowsPath` 构造的输入），断言被拒绝。
- **完成标准**：质量关口满足 D1，已有的路径相关测试不需要修改就能通过。如果需要修改，就停下来，在「意外与发现」里说明原因。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）。

### T4：跨平台进程管理 `studio/proc.py`（完成，机器：Windows，按基线对比）

- **目标**：设计 §6——统一启动受控子进程的参数、结束整棵进程树的方式和 UTF-8 环境；替换所有 `killpg`、`start_new_session` 和只结束顶层进程的 `proc.kill()`。
- **涉及文件**：新增 `backend/src/studio/proc.py`、`backend/tests/test_proc.py`；修改 `engines/audio/runner.py`（`limited_argv` 按平台分支，删除 `kill_group`）、`engines/audio/song_job.py`、`engines/audio/song.py`（同步的 `subprocess.run`）、`engines/audio/probe.py`、`engines/render/html/video.py`、`engines/render/mix.py`、`agent/shell.py`；`backend/pyproject.toml`（新增 import-linter 契约：`studio.proc` 不依赖任何其他 `studio` 模块）；`docs/ARCHITECTURE.md`。
- **接口与要点**：
  - `spawn_kwargs(platform: str | None = None) -> dict[str, Any]`；`async kill_tree(proc: asyncio.subprocess.Process, *, platform: str | None = None) -> None`；`kill_tree_sync(pid: int, *, platform: str | None = None) -> None`（供 `subprocess.run` 超时的情况以及 T7 使用）；`child_env(base: Mapping[str, str]) -> dict[str, str]`（复制一份，并加上 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`）。
  - Windows 分支：`creationflags=CREATE_NEW_PROCESS_GROUP`；`taskkill /T /F /PID <pid>`，输出丢弃，失败时退回 `proc.kill()`。
  - `limited_argv(argv, cpu_seconds, *, platform=None)`：POSIX 保持现状；Windows 原样返回 `argv`。`run_compose` 结束后检查 `music.wav` 的大小，超过 `_MAX_FILE_BYTES` 就当作失败。这个检查两个平台都做。
  - 现在所有向子进程传 `env=` 的地方都改成经过 `child_env`；没有传 `env` 的地方（继承父进程的环境）保持继承，但也要加上 UTF-8 变量。逐处判断，写进决策记录。
  - 外部程序的输出统一用 `decode("utf-8", errors="replace")`。
- **测试**：`spawn_kwargs`、`limited_argv` 用参数注入测两个分支；`kill_tree` 在 POSIX 上真实测试：启动一个会派生孙进程的 Python 子进程，`kill_tree` 之后孙进程也不在了；Windows 分支 mock `taskkill` 的调用，断言参数正确。已有的 `test_audio_runner.py`、`test_shell.py` 等对 `killpg` 的 mock 改为针对 `kill_tree`。审查重点 4：断言 `run_compose`、Shell executor 收到的环境里有 `PYTHONUTF8=1`。
- **完成标准**：`grep -rn "killpg\|start_new_session" backend/src` 只剩 `proc.py` 里的结果；质量关口满足 D1。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`（对照基线，见全局约束 D1）；`cd backend && uv run pytest -m slow -k "html_video or mix"`（真实子进程，确认没有倒退）。

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
  - 讲解类：选题 → 叙事 → 动画（HTML 引擎）→ 成片。短片：`concept → produce`（HTML 引擎 + 合成配乐，开关打开）。检查成片的中文显示和配乐。
  - 渲染过程中按 Ctrl+C 退出，用 `tasklist` 确认没有残留的 python、node、ffmpeg 或 chromium；重新启动，确认 worker 能恢复或者把中断的任务标记为失败，和 macOS 上的行为一致（审查重点 6）。
- **测试**：发现问题就先补测试再修。
- **完成标准**：AC3、AC5，附截图和成片路径。
- **验证命令**：`tasks.py check`；`tasklist /FI "IMAGENAME eq python.exe"` 等。

### T12：收尾：macOS 回归与文档（待开始，机器：macOS）

- **目标**：AC1、AC7。
- **涉及文件**：`docs/quality/tech-debt.md`（Windows 上没有 CPU 时间和文件大小的硬限制；Windows 上 `upstream/` 的只读保护变弱）、`docs/quality/QUALITY.md`、`docs/ARCHITECTURE.md`、`AGENTS.md`、`docs/plans/TODO.md`。
- **接口与要点**：在 macOS 上拉取 Windows 会话的全部改动；先确认 T1–T8 里在 Windows 上被跳过的 POSIX 测试在 macOS 上都执行了而且通过（`pytest -rs` 不应该有任何跳过），修掉 macOS 上的回归；然后跑 `make check`、`make dev`、`make smoke SMOKE_ARGS="-k claude_login"`；逐条核对 AC7 的文档清单；整理「意外与发现」，把应该改成机器检查的约定挑出来。
- **完成标准**：AC1、AC7；计划状态改为"待验收"。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k claude_login"`。

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-10-09 — 开工准备：分支、计划移入 active、工作区刷成 LF、装依赖、记录 Windows 基线（见「意外与发现」）
- 2026-10-09 — T1 完成：`scripts/tasks.py`（除 `dev`）、Makefile 薄壳、`.gitattributes`、pre-commit 改调 `tasks.py check-fast`、ADR 0025。Windows 上 `tasks.py check` 能运行，按基线在 pyright 一步失败（8 个错误，和基线相同）；新增 `tests/scripts/test_tasks.py` 31 通过、1 跳过（与 bash 比较的用例，Windows 上另用 Git Bash 手动比过，一致）；pytest 其余部分不受影响（本任务没动 `backend/src`）。剩余失败数：pytest 113 失败 + 30 error + 1 挂住，pyright 8
- 2026-10-09 — T2 完成：ruff 启用 `PLW1514`（预览规则，`explicit-preview-rules`），`scripts/` 纳入 ruff 检查，补一个 AST 测试覆盖 ruff 认不出的 `x.read_text()`；`tasks.py` 的所有步骤以 UTF-8 模式运行，Windows 上没开 UTF-8 模式时 pytest 直接报错提示。和基线比没有新增失败，12 个用例函数转为通过。剩余失败数：pytest 101 失败 + 30 error + 1 挂住，pyright 8
- 2026-10-09 — T3 完成：`workspace.files.check_model_path`、`relpath_within`；`normalize_relpath`、`safe_path`、`apply_patch.to_workspace_relpath`、Claude 读写 hook（含 Glob 模式）改为共用它们；附件文件名去掉 Windows 不允许的字符和结尾的 `.`/空格。新增约 140 个用例（`tests/workspace/test_model_path.py`、hook 和 apply_patch 的 Windows 写法），已有的路径测试没有修改。和基线比没有新增失败，`apply_patch` 的 3 个基线失败转为通过。剩余失败数：pytest 98 失败 + 30 error + 1 挂住，pyright 8
- 2026-10-10 — T4 完成：新模块 `studio.proc`（`spawn_kwargs`、`kill_tree`/`kill_proc_tree`/`kill_tree_sync`、`run_killing_tree`、`child_env`）及 import-linter 契约；配乐脚本、歌曲分析、ffprobe、ffmpeg 解码/出片/混音、Shell executor 全部改用它；Windows 上 `limited_argv` 原样返回，`run_compose` 事后检查 `music.wav` 大小（两个平台都查）。测试里的假 ffmpeg 改成 Python 脚本，挂住的取消用例随之修好；`os.kill(pid, 0)` 探活改为共用的 `fixtures.processes.pid_alive`。Windows 上 `tasks.py check` 第一次跑到 pytest：pyright 0 错误，pytest **6 失败**（3007 通过），全部属于 T8、T9。剩余失败数：pytest 6，pyright 0

## 下一步

T1–T4 已完成（见「进度」）。Windows 上 `tasks.py check` 已能完整跑完，只剩 6 个失败（见 T4 的进度行）。接下来做 **T5：执行策略与开关**：

1. 计划里 T5 状态改为「进行中」；先读设计 §4（尤其 §4.2 的表、§4.3），以及 `config.py`、`db/repo/settings.py`（照着 `effective_web_mode` 写）、`agent/runner.py`（`TurnContext` 的构造）、`agent/claude_runtime.py` 和 `claude_scope.py`（`allowed_tools`、`disallowed_tools`、`sandbox_settings`）、`agent/openai_runtime.py`（`native_shell_supported`）、`agent/shell.py`、`stages/common/score/tool.py`（`sandbox_wrapper`）、`agent/events.py`。
2. 先写 `backend/tests/agent/test_exec_policy.py`（`exec_mode` 真值表）和三种模式下 Claude/OpenAI/`render_music` 的测试，再实现；ADR 0024 按设计 §10 写。
3. Windows 上用 Fake 运行时跑的测试可以覆盖 `disabled`/`unsandboxed` 两种模式；`sandboxed` 的真实行为留到 T12 在 macOS 上确认。
4. 验证：`uv run --project backend python scripts/tasks.py check`（PowerShell，已不需要 `--deselect`），和 T4 的 6 个失败比较。
5. commit 并 push。

## 决策记录

- 2026-10-09 — Manim 引擎下线（[ADR 0027](../../decisions/0027-下线Manim引擎.md)）后，删去本计划里 manim 相关的文件、验证项和 MiKTeX 依赖；讲解类验收改用 HTML 引擎。设计文档 §9.3 中的 MiKTeX 由该 ADR 取代，不再需要。
- 2026-10-09 — **开工前复核 Manim 下线的影响**：计划正文里已经没有 manim 相关的文件、任务和验收项（`grep -i manim` 只剩上一条决策记录）。设计文档里还留着的 manim 内容（§3 关于 manim 无 sandbox 的现状说明、§4.2 表格里的"manim 渲染"一行、§6 关于 manim 派生 ffmpeg 的段落、§6.4 子进程列表里的 manim、§9.3 的 LaTeX 和 manim wheel 说明、§10 的"manim 执行 agent 代码没有 sandbox"技术债、§11 第 5 条的"manim 引擎"、§12 的 manim 安装风险）都已被 ADR 0027 取代。按红线不改已批准的设计，执行时以本计划为准：T4 的 `kill_tree` 和 `child_env` 只覆盖现有的子进程（配乐脚本、歌曲分析、ffmpeg/ffprobe、HTML 成片、Shell）；T12 不登记 manim 的技术债；T9 写 dev-setup 的 Windows 一节时不包含 LaTeX。`backend/src` 里剩下的 `manim` 字样都是老项目只读兼容的代码，不属于本计划。
- 2026-10-09 — **开工时的环境调整**（本机实测，和原「下一步」的假设不一致的地方）：
  - 仓库不 clone 到 `C:\dev`，保留在现有的 `C:\Users\pp\AI\agent\ai-video-studio`（路径 36 个字符，比设计 §12 担心的深度短得多）；如果 T9 或 T11 遇到 260 字符的问题再处理。
  - `origin` 上的 `windows-native` 分支还停在计划入库时的 `1709e95`（早已包含在 main 里），没有带上 remove-manim 之后的 main；改为在 Windows 上从最新 main 切出，push 时快进覆盖了旧的远端分支（没有丢提交）。
  - Git for Windows 的系统级配置里有 `core.autocrlf=true`（`C:/Program Files/Git/etc/gitconfig`），工作区里的文件是 CRLF。不改系统和全局配置，只在仓库里设置 `core.autocrlf false`，并把工作区刷成 LF（见「下一步」第 2 步）；T1 的 `.gitattributes` 之后会让这件事不再依赖本机配置。
  - 本机的 `uv` 来自 Anaconda（`~/anaconda3/Scripts/uv`，0.11.3），`node` 和 `pnpm` 来自 nvm4w（`C:\nvm4w\nodejs`，Node 22.17.0）；另外通过 scoop 装了 `make`。T1 的 `find_uv`、`find_pnpm` 先找 PATH，所以这些位置不需要写死；`make` 在 Windows 上不作为正式入口（Makefile 用的是 `SHELL := /bin/bash`），Windows 上的入口仍然是 `tasks.py`。
  - 本机 PATH 里没有 `claude` 命令（桌面版自带的 CLI 不在 PATH 里）。T10 的 `claude-login` 实测依赖 claude-agent-sdk 自带的 CLI，到时候先确认它能用。
<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-10-09 — **D1（负责人已决定：采用备选方案，T1–T11 全部在 Windows 上做，T12 回到 macOS）**。原推荐方案：T1–T8 的质量关口在 macOS 上跑。理由：T8 完成之前，Windows 上的 `tasks.py check` 必然大面积失败，在 Windows 上做 T1–T8 就没有可用的"绿色基线"来判断改动是否引入了回归。**备选**：T1–T8 也在 Windows 上做，开工前先记录一份 Windows 基线失败清单，每个任务的完成标准改为"没有新增失败，并且本任务负责修复的那些失败已经消失"。这样不用来回切换机器，但判断依据更弱，macOS 上的回归要等到 T12 才能发现。
- 2026-10-09 — 计划任务的顺序是先做工具链（T1），这样 Windows 上尽早有可以运行的 `tasks.py check`；`dev` 放在 T7，等 `proc.py`（T4）稳定之后再做。
- 2026-10-09 — T1：`tasks.py` 的子命令把 `smoke` 和 `import-legacy-styles` 后面的参数原样传下去（`argparse.REMAINDER`），所以 Makefile 仍然写 `smoke $(SMOKE_ARGS)`、`import-legacy-styles <文件> $(IMPORT_ARGS)`；`check-docs` 改用运行 `tasks.py` 的那个 Python（`sys.executable`），不再依赖 `python3`。`find_uv`、`find_pnpm` 为了测试加了关键字参数 `home`、`platform`（`find_pnpm` 还有 `environ`），不传时取当前机器的值。
- 2026-10-09 — T1：`.gitignore` 的 `.dev/` 从 T7 提前到 T1 加，Windows 基线的原始输出放在 `.dev/` 里（不入库）。`.gitattributes` 除了设计 §7 列的类型，还把 `*.webp`、`*.gif`、`*.ico`、`*.pdf`、字体标成 `binary`（仓库里已有 13 个 webp）；`git add --renormalize .` 后没有任何已有文件的内容变化。
- 2026-10-09 — T1：`.env` 解析遵循 bash 的规则：`#` 只有在引号外、前面是空白时才是注释（`a#b` 的值是 `a#b`）；引号外有空白、后面又不是注释时报错（bash 会把它当成命令执行）；单引号内的 `$` 是字面量，允许。本机的 `backend/.env` 只用了 `KEY=VALUE`，在支持的子集内。
- 2026-10-09 — T2：`PLW1514` 在 ruff 0.16.9 里还是**预览规则**，只写进 `select` 不生效。做法：`[tool.ruff.lint]` 加 `preview = true` 和 `explicit-preview-rules = true`，只有点名的预览规则生效；打开后除了 `PLW1514` 没有新增任何报错。预览模式下 `--output-format concise` 输出的是规则名（`unspecified-encoding`）而不是代码，测试按规则名断言。
- 2026-10-09 — T2：`scripts/` 的 lint 选了"加一份配置"：`scripts/ruff.toml` 只写 `extend = "../backend/pyproject.toml"`，`tasks.py` 的 `check-backend` 对 `. ../scripts` 跑 `ruff check` 和 `ruff format --check`，`check-fast` 跑 `ruff check`。这样 scripts 和后端完全同一套规则（顺手修了 `check_docs.py` 一处超长行的格式）。
- 2026-10-09 — T2：`PLW1514` 只认得出能推断为 `Path` 的值，`(workdir / "x").read_text()`、`Path` 参数上的调用都漏掉（`src` 里没有漏网的，`tests` 里约 220 处）。补救分两部分：① `tests/test_lint_rules.py` 用 AST 检查 `src`、`scripts` 里所有 `.read_text()`（无位置参数）和 `.write_text(x)`（一个位置参数）都带 `encoding`；② 测试代码不逐处改，改为要求测试在 UTF-8 模式下运行：`tasks.py` 给它启动的所有进程加 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`（设计 §7，`utf8_env`，T4 的 `studio.proc.child_env` 要在注释里互相指向），`tests/conftest.py` 在 Windows 上发现没有 UTF-8 模式时以 `UsageError` 退出并给出命令。理由：测试的职责是验证产品代码，产品代码的编码已经由 lint 保证；逐处改 220 处测试收益小、噪声大。代价：Windows 上直接 `uv run pytest` 要先设 `PYTHONUTF8=1`。
- 2026-10-09 — T3：`check_model_path` 严格按设计 §5 的清单，另外两处补充：拒绝 NUL 字符（`Path` 操作遇到它会抛 `ValueError` 而不是 `ScopeError`）；保留设备名除了 `CON/PRN/AUX/NUL/COM0–9/LPT0–9`，还有 `CONIN$`、`CONOUT$` 和上标数字的 `COM¹` 等（Windows 文档列出的完整集合）。`console.md`、`COM10.txt` 这类只是前缀相同的名字不受影响。没有拒绝 `<>"|?*`：它们不改变路径指向哪里，Windows 上写入时会直接报 `OSError`。
- 2026-10-09 — T3：`relpath_within(workdir, raw) -> str` 同时处理相对路径（先过 `check_model_path`，`.` 表示工作区本身，返回 `""`）和绝对路径（当前平台的 `Path.is_absolute()`）。解析符号链接和 `..` 之后用 `os.path.normcase` 比较前缀，得到的相对路径再过一次 `check_model_path`（拦下 `C:\ws\CON.txt` 这类绝对写法）。所以 Windows 上 `/etc/passwd` 不算绝对路径，按相对路径被拒；macOS 上 `C:\x` 同理。`apply_patch` 给出工作区本身（`""`）时按错误处理。
- 2026-10-09 — T3：Glob 模式不是路径（含 `*`、`{a,b}`），不整体套 `check_model_path`；在原有检查（`/`、`~`、`..`、首尾空白）上加拒绝 `\` 和 `:`，抽成 `claude_scope._bad_glob`。
- 2026-10-09 — T3：**和现有行为的冲突**（设计 §5 要求发现冲突时记录）：对话附件的文件名（ADR 0026，`uploads/<前缀>-<原名>`）原来只去掉控制字符，原名里的 `:` 或结尾的 `.` 会让 agent 之后按路径读它时被新规则拒绝。改为在 `api.attachments.safe_name` 里把 `<>:"|?*` 换成 `_`、去掉结尾的 `.` 和空格；加了一条测试保证 `safe_name` 的结果总能通过 `check_model_path`。已有上传的文件不迁移（本机数据里没有这类文件名）。
- 2026-10-09 — T3：`symlinks_supported` fixture 提前在 T3 加进 `conftest.py`（T3 的符号链接用例要用）；`test_windows_compares_case_insensitively` 暂时用 `os.name` 的 `skipif`，T8 统一换成 conftest 的标记。
- 2026-10-10 — T4：`studio.proc` 的接口在计划之外多了三样：`kill_proc_tree(process)`（同步版，给不能 await 的回调和 `except BaseException` 分支用——取消已经发生时再 await 有可能被再次取消，杀不干净）、`run_killing_tree(argv, timeout=...)`（给 `song.decode_song` 这种同步调用用，超时杀整棵树）、`ProcessLike` 协议（`kill_tree` 只要 `pid`/`returncode`/`kill()`，测试里的假进程不需要 `type: ignore`）。
- 2026-10-10 — T4：**Windows 上子进程退出后不再按 PID 结束进程树**：退出后 PID 可能已被别的进程复用，`taskkill /T` 会误杀别人的整棵树；而且父进程退出后 `/T` 也找不到它的后代。POSIX 上保持原样（退出后照样 `killpg`，清理留在进程组里的后台进程）。代价：Windows 上"脚本正常退出但留下后台子进程"的情况清理不到，T12 登记技术债（以后可以用 Job Object 解决）。
- 2026-10-10 — T4：`child_env` 在 Windows 上还会补 `SYSTEMROOT`、`WINDIR`、`COMSPEC`、`PATHEXT`（从父进程环境取，基础环境里已有的不覆盖）：配乐脚本和歌曲分析用的是白名单环境，没有 `SYSTEMROOT` 的话 Windows 上的 Python 启动就会失败。这几个变量不含密钥。
- 2026-10-10 — T4：子进程的 `env` 逐处判断（计划要求写进决策记录）：配乐脚本（`runner._SAFE_ENV` 白名单）、歌曲分析（`song_job._ENV_KEYS` 白名单）、Shell（去掉密钥名后的父进程环境）——原来就传 `env` 的，都改为经过 `child_env`；ffprobe、ffmpeg 解码/出片/混音原来继承父进程环境，改为传 `child_env(os.environ)`，内容仍是继承，只是多了 UTF-8 变量。没有哪一处从"继承"变成"白名单"或反过来。
- 2026-10-10 — T4：测试里用 `#!/bin/sh` 写的假 ffmpeg 改成 Python 脚本，并通过替换 `video.build_encode_command` 接进去（保留真实参数、只换程序），两个平台都能跑；没有用 T8 的标记跳过。基线里"挂住"的取消用例就是因为假 ffmpeg 在 Windows 上起不来、`started` 事件永远不会被设置。
- 2026-10-10 — T4：**`os.kill(pid, 0)` 在 Windows 上不是探活，而是结束进程**（除 CTRL_C/CTRL_BREAK 以外的信号都会变成 `TerminateProcess`），用它判断"孙进程是否已被杀掉"的测试在 Windows 上会自己把进程杀掉而虚假通过。新增 `tests/fixtures/processes.py`（`pid_alive`、`wait_gone`，Windows 上用 `tasklist`），`test_proc`、`test_audio_runner`、`test_audio_song_job` 改用它。只在 POSIX 上跑的用例（`_group_gone`、Seatbelt 相关）里的 `os.killpg`/`signal.SIGKILL` 前面加了 `sys.platform` 判断，pyright 在 Windows 上就不再报错，不用 `type: ignore`。
- 2026-10-10 — T4：`test_audio_runner.py::test_a_script_cannot_fill_the_disk` 依赖 `ulimit -f`，Windows 上暂时用 `skipif(sys.platform == "win32")`（T8 换成 `posix_only`）；另加 `test_an_oversized_wav_is_refused` 覆盖两个平台都有的事后大小检查。`test_fake.py::TestFakeDelay::test_register_fake_passes_delay` 在 Windows 上偶发失败（50 ms 的 sleep 量出来 47 ms，Windows 计时器精度约 15.6 ms），断言放宽一个时钟刻度。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 2026-10-09 — **Windows 基线**（开工前、`backend/src` 未改动；开发者模式已开；原始输出在本机 `.dev/baseline-pytest.txt`、`.dev/baseline-failures.txt`，不入库）：
  - 通过：`check_docs`、`ruff check`、`ruff format --check`、`lint-imports`（25 个契约）、前端 `lint`、`typecheck`、vitest（1242 通过）。
  - pyright：8 个错误，都是 `os.killpg`、`signal.SIGKILL` 在 Windows 上不存在——`agent/shell.py:44`、`engines/audio/runner.py:72`（T4），`tests/agent/test_openai_runtime.py:927`、`tests/agent/test_shell.py:95`、`tests/engines/test_html_pool_recovery.py:67,82`（T4 改 mock 或 T8 加标记）。
  - pytest：2673 通过、**113 失败、30 error**、30 跳过、89 个按默认标记排除；另有 **1 条会挂住**：`tests/engines/test_html_video.py::test_cancellation_stops_ffmpeg_and_removes_the_temp_file`（取消后等待 ffmpeg 退出，一直不返回），基线和之后的对比都先用 `--deselect` 排除它，T4 负责修。按原因分类（数字是 `--tb=line` 统计到的条目，参数化用例会重复计数）：
    1. **`/bin/sh` 不存在**（约 66 条 `FileNotFoundError` + 由它引起的 30 个 fixture error，以及十余条"脚本执行出错/配乐脚本无法使用 [WinError 2]"断言）：`engines/audio/runner.py` 的 `limited_argv` 用 `/bin/sh -c 'ulimit …'` 包裹配乐脚本和歌曲分析。涉及 `test_worker_html_music`、`api/test_music`、`test_audio_runner`、`test_music_render(_free)`、`test_produce_stage/_pipeline`、`test_music_stage`、`test_synth_music_flow`、`test_audio_song_job`、`test_music_import_tools`、`test_produce_music_tools`、`test_music_tool`。→ T4（Windows 上 `limited_argv` 原样返回）。
    2. **`os.killpg` 不存在**（1 条，`engines/audio/runner.py:72`）→ T4。
    3. **测试用 `#!/bin/sh` 写的假 ffmpeg**（7 条 `OSError: %1 不是有效的 Win32 应用程序`，`test_html_video.py`）→ T4 或 T8（改成 Python 写的假程序，或标 `posix_only`）。
    4. **路径分隔符和绝对路径**：`apply_patch` 的 `to_workspace_relpath` 对 Windows 绝对路径返回原样（`test_apply_patch.py:42,173`、`test_openai_runtime.py:992`）→ T3；`test_html_video.py:60` 期望 `/tmp/o.tmp.mp4` 得到 `\tmp\o.tmp.mp4`（测试里的路径断言）→ T8。
    5. **Seatbelt 配置的断言**（`test_shell_sandbox.py:76,100,316`，Windows 路径拼进 profile、`StopIteration`）→ T8 标 `macos_only`。
    6. **Windows 不允许的文件名**（`"` 出现在文件名里，`test_shell_sandbox` 的 `test_quotes_and_backslashes…`）→ T8。
    7. **只读权限**（`test_upstream.py::test_unreadable_file_counts_as_drift`，靠 `chmod 000`）→ T8 标 `posix_only`。
    8. **排序或时间相关**（`test_repo_projects.py:74` 最新的排在前面、`test_repo_turns` 最近一轮、`test_snapshot` 回滚后不多建快照、`test_runner.py:846` 前言 diff、`test_model_switch`、`test_runner_style`、`styles/test_store` 的 prune）：原因未确认，疑似 Windows 上时钟精度低导致时间戳相同，或文件 mtime 精度；→ T9 逐条确认。
    9. **编码**：同一批失败用例在设置 `PYTHONUTF8=1` 后重跑，有 16 条变成通过（`read_text()` 走 `encoding='locale'`，即 GBK）→ T2、T4。
  - T2 之后复核：第 8 类里的 `test_repo_projects`、`test_repo_turns`、`test_snapshot`、`test_model_switch`、`test_runner_style`、`styles/test_store` 在 UTF-8 模式下都通过了，所以至少在这次运行里它们属于编码问题而不是时钟精度；`test_runner.py::TestPreambleAcrossTurns` 仍然失败，留给 T9。
- 2026-10-09 — 开发者模式打开后，Python 的 `os.symlink` 不需要提权就能建符号链接；但 **Windows PowerShell 5.1 的 `New-Item -ItemType SymbolicLink` 仍然报"需要管理员权限"**（它没有用 `SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE`）。dev-setup 的 Windows 一节（T9）里验证开发者模式要用 Python，不要用 PowerShell。
- 2026-10-09 — 本机 Git Bash 里的 `pnpm`（nvm4w 的 sh 启动脚本）把路径解析成 `C:\Users\pp\anaconda3\Library\c\nvm4w\...`，运行失败；PowerShell 里的 `pnpm`（`pnpm.ps1`/`pnpm.cmd`）正常。`tasks.py` 用 `shutil.which("pnpm")` 找到的是 `pnpm.CMD`，不受影响。
- 2026-10-09 — 本机 npm 镜像源（清华 tuna）缺 `@codemirror/lang-javascript-6.2.5.tgz`（404），`pnpm install` 失败；这次用 `pnpm install --registry=https://registry.npmmirror.com/` 装好，没有改全局配置，lockfile 没有变化。
- 2026-10-09 — Git Bash 里 `lint-imports`、`check_docs.py` 等的中文输出是乱码（控制台代码页是 GBK）；PowerShell 里显示正常。不影响结果，T9 写 dev-setup 时提一句"在 PowerShell 里跑"。

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无

## 验证记录

<!-- 自验证阶段填写：每条验收标准对应的命令、输出摘要、截图路径。 -->

- 无
