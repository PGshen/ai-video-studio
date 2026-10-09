# 原生支持 Windows

状态：待批准（2026-10-09）。本文不修改已批准的设计；涉及 [ADR 0009 Shell 沙箱](../decisions/0009-Shell沙箱.md) 和 [ADR 0006 纯本地 SOP](../decisions/0006-纯本地SOP.md) 的地方，按本文 §10 新增 ADR，不改旧 ADR 的正文。

## 1. 背景与目标

项目一直在 macOS 上开发和使用，多处代码依赖 POSIX，有的只在 macOS 上有：bash 写的 `Makefile`、`scripts/dev.sh` 和 pre-commit hook；`/bin/sh -c 'ulimit …'`；`os.killpg`；`start_new_session`；macOS 的 `sandbox-exec`；Claude Code 的 Bash sandbox。所以 Windows 原生环境现在跑不起来。

负责人有一台 Windows 电脑，要在上面**既用这个工具，也开发这个项目**。

**目标**：

1. 在 Windows 11 原生环境（不用 WSL）上，按文档装好依赖，能启动 api、worker 和前端三个进程，在浏览器里完整走完一个项目：选题 → 叙事 → 动画 → 成片。讲解类、短片和 MV 三种形态都要能走通。
2. 在 Windows 上能运行完整的质量关口（等价于 `make check`），并且全部通过；pre-commit hook 能用。负责人可以在 Windows 上开 Claude Code 或 Codex 会话，按 SOP 继续开发。
3. macOS 上的行为和安全性不倒退：`make check`、`make dev`、`make smoke` 用法不变，Seatbelt 和 Claude sandbox 照常生效。

**不做**：

- Linux 和 WSL 的正式支持。改动以后它们大概率也能跑，但不验证，也不写进文档。
- 在 Windows 上实现自己的进程读隔离（AppContainer、受限 token、Windows Sandbox 虚拟机），见 §4.1。
- 一键安装器或打包成 exe。
- 旧项目一次性迁移脚本的 Windows 版：`export_legacy_styles.sh` 已经执行过，`build_fonts.sh` 的产物已经入库，这两个脚本仍然只支持 macOS。
- GitHub Actions 等 CI。ADR 0006 不变，Windows 上的验证由 Windows 本机的会话完成，见 §9。

## 2. 已确认的决定

| 项 | 决定 | 来源 |
|---|---|---|
| 支持范围 | Windows 上既能用也能开发（`check` 全绿，可以开 AI 会话） | 负责人，2026-10-08 |
| Windows 上 agent 执行命令 | 先调研有没有现成的隔离方案（结论：没有，见 §4.1）；采用"默认失败关闭 + 显式开关放开无隔离执行" | 负责人选 B，2026-10-08 |
| 开发工具链 | 逻辑改写成 Python 任务脚本 `scripts/tasks.py`，Makefile 保留为调用它的薄壳 | 负责人，2026-10-09 |
| Windows 上的验证 | 在负责人的 Windows 电脑上开 Claude Code 会话，自己跑、自己修；两台机器通过 git 交接 | 负责人选 C，2026-10-09 |
| 新依赖 | 不引入。进程树清理在 Windows 上用系统自带的 `taskkill /T /F`，不用 `psutil` | 本文 |

## 3. 现状清单（2026-10-09 在 macOS 上排查）

| # | 位置 | 依赖 | 在 Windows 上的后果 |
|---|---|---|---|
| P1 | `Makefile`、`scripts/dev.sh`、`.githooks/pre-commit` | bash、`set -m` 进程组、`lsof`、`ps`、`pgrep`、`kill -- -pid`、`env -i`、`compgen` | 质量关口、启动、冒烟测试和 pre-commit 都用不了 |
| P2 | `engines/audio/runner.py`：`limited_argv`、`kill_group` | `/bin/sh -c 'ulimit -t/-f'`、`os.killpg`、`signal.SIGKILL` | 配乐脚本和歌曲分析启动不了；超时时清理不掉进程（`AttributeError`） |
| P3 | `engines/audio/song_job.py`、`agent/shell.py` | `start_new_session=True` + `killpg` | 同上 |
| P4 | `agent/shell_sandbox.py`、`stages/common/score/tool.py` | macOS `sandbox-exec` | 不是 macOS 时，OpenAI 路径不给 Shell，**合成配乐（`render_music`）直接报错"当前平台没有沙箱"**，短片的配乐用不了 |
| P5 | `agent/claude_scope.py: sandbox_settings`、`claude_runtime.py: BUILTIN_TOOLS` 含 `Bash` | Claude Code sandbox（只支持 macOS、Linux 和 WSL2） | Windows 上 Bash 没有隔离；Windows 版 Claude Code 还有 PowerShell 工具，现在没考虑到 |
| P6 | `workspace/files.py: normalize_relpath/safe_path`、`agent/apply_patch.py: to_workspace_relpath`、`agent/claude_scope.py` 的读写 hook | 用 `PurePosixPath` 判断路径是不是绝对路径、有没有 `..` | `C:\x`、`..\x`、`\\server\share` 会被当成"相对路径里的一段"；拼接后在 Windows 上指向工作区外。现在靠 `resolve` 后的范围检查兜底，但第一道检查已经失效（安全项，§5） |
| P7 | `workspace/upstream.py` | 用 `chmod` 把 `upstream/` 设成只读 | Windows 上目录的权限位不起作用，文件只有"只读"属性；只读保护变弱，要靠事后的漂移检查 |
| P8 | `agent/sandbox_paths.py` | 拒读清单是 macOS 和 Linux 的目录 | Windows 上没有 sandbox，这份清单用不上；不需要改，但要写清楚 |
| P9 | 文本编码 | 项目代码基本都显式写了 `encoding="utf-8"`；子进程（manim、agent 写的脚本、`score/exemplar/audio-techniques.py` 的 `open()`）用的是系统默认编码 | Windows 中文系统默认是 GBK（cp936），子进程读写中文 JSON 或打印中文会出乱码或报 `UnicodeError` |
| P10 | 行尾 | 仓库没有 `.gitattributes` | Git for Windows 默认 `autocrlf=true`，检出后变成 CRLF：bash hook 跑不了，有些逐字节比较的测试会失败 |
| P11 | 测试 | 28 个测试文件用到 `killpg`、`sandbox-exec`、`/bin/sh`、`chmod`、符号链接 | Windows 上会大面积失败；创建符号链接需要开发者模式或管理员权限 |
| P12 | 文件占用 | `os.replace`、快照还原、`guard` 还原时会删除或覆盖文件 | Windows 上文件被其他进程打开（Chromium、ffmpeg、编辑器、杀毒软件扫描）时，删除或改名会报 `PermissionError` |
| P13 | uvicorn `--reload` 与 asyncio 子进程 | — | 有些版本的 uvicorn 在 Windows 上用 `--reload` 时会改用 `SelectorEventLoop`，导致 `create_subprocess_exec` 报 `NotImplementedError`。**要在 Windows 上实测** |
| P14 | `.claude/launch.json` | `runtimeExecutable: uv/pnpm` | Windows 上 pnpm 是 `pnpm.cmd`，桌面版能不能直接启动要实测 |

另外记录一个**与平台无关的现状**：manim 的 dry-run 和渲染直接用 `sys.executable` 执行 agent 写的场景代码，**在 macOS 上也没有 sandbox**（迁移自旧项目）。本文不改这一点，但 §4 的开关不会让它变得更糟。它作为已有风险登记为技术债，见 §10。

## 4. agent 执行命令与代码：失败关闭 + 显式开关

### 4.1 调研结论（2026-10-08）

- **Claude Code**：sandbox 支持 macOS、Linux 和 WSL2。官方文档原话是 "On native Windows, Claude Code runs commands unsandboxed"。CLI 有 `sandbox.failIfUnavailable`：sandbox 不可用时 CLI 拒绝启动。来源：[code.claude.com/docs/en/sandboxing](https://code.claude.com/docs/en/sandboxing)。
- **OpenAI Codex**：Windows sandbox 是 Codex CLI 内部的实现（基于 AppContainer 的受限 token、写限制 SID、ACL），重点是**限制写入和断网**，不提供"拒读指定目录"，也不是 OpenAI Agents SDK 能直接复用的库。来源：[Building the Codex Windows sandbox](https://openai.com/index/building-codex-windows-sandbox/)。
- **自己实现**（AppContainer、受限 token、Windows Sandbox 虚拟机、把命令转到 WSL2 执行）：要写 Win32 安全代码或者维护跨系统的执行链，工作量和风险都远大于本项目的其他部分，所以不做。以后 Claude Code 或 OpenAI 提供 Windows 读隔离时，只要在 `exec_policy` 里加一个平台分支就能接上（§4.2）。

我们关心的主要风险是**提示注入后读取敏感文件，再把内容发出去**。在默认的 `tools` 联网模式下，只有选题和头脑风暴两个阶段能联网，而且 `fetch_url` 受"URL 来源"规则限制（[ADR 0010](../decisions/0010-联网模式开关.md)）。所以在 Windows 上打开开关之后，主要的剩余风险是：在选题或头脑风暴阶段被注入，然后通过 Shell 自己发起网络请求（例如 `curl`）。macOS 的 Seatbelt 会禁网，Windows 上没有这一层。

### 4.2 执行策略：`agent/exec_policy.py`（新模块）

把"本机能不能、以什么方式执行 agent 的命令或代码"收拢到一个纯函数里，各运行时和 `render_music` 都只问它，不再各自判断 `sys.platform`：

```
ExecMode = Literal["sandboxed", "unsandboxed", "disabled"]

def exec_mode(*, platform: str, sandbox_available: bool, allow_unsandboxed: bool) -> ExecMode
```

| 平台 | 有 sandbox | 开关 | 结果 |
|---|---|---|---|
| macOS（有 `sandbox-exec`） | 是 | 不论开关 | `sandboxed`（开关在 macOS 上无效，不能用它关掉隔离） |
| Windows 或其他没有 sandbox 的平台 | 否 | 关（默认） | `disabled` |
| 同上 | 否 | 开 | `unsandboxed` |

Linux 这次不做正式支持，按上表的"没有 sandbox"处理，行为和现在一样，都是失败关闭。

**开关**：`STUDIO_ALLOW_UNSANDBOXED_EXEC`，布尔值，默认 `false`。讨论时暂称它为 `STUDIO_UNSANDBOXED_SHELL`；因为它同时管 Shell 和合成配乐脚本（P4），所以改成现在这个名字。和联网模式一样，设置页可以覆盖它（`db/repo/settings.py` 新增键 `allow_unsandboxed_exec`，"清除界面设置"后回到环境变量的值），**下一轮对话起生效**。

### 4.3 各执行点在三种模式下的行为

| 执行点 | `sandboxed` | `disabled` | `unsandboxed` |
|---|---|---|---|
| Claude 路径：Bash（以及 Windows 上的 PowerShell 工具） | 照旧：`sandbox_settings` 生效 | 从 `allowed_tools` 去掉 `Bash`，并把 `Bash`、`PowerShell` 放进 `disallowed_tools`；**不传** `sandbox`（传 `enabled: true` 加 `failIfUnavailable` 会让 Windows 上的 CLI 拒绝启动，反而整轮都失败） | 放行 `Bash`（Windows 上由 Git Bash 执行）和 `PowerShell`；不传 `sandbox`；写入仍有 hook 拦截和 `guard` 兜底 |
| OpenAI 路径：原生 Shell（只在官方 API 上提供） | 照旧：用 `sandbox-exec` 包裹 | 不提供（和现在一样） | 提供；executor 不包裹 `sandbox-exec`，其余照旧：环境变量里的 key 过滤、超时、结束时清理进程树（§6） |
| `render_music`：执行 agent 写的配乐脚本 | 照旧：Seatbelt | 返回错误，说明这台机器上没有 sandbox，并指出可以在设置页打开开关（不再只说"当前平台没有沙箱"） | 直接运行；保留环境变量白名单、超时、输出大小检查（§6.2） |
| manim 渲染、歌曲分析（项目自己的代码） | 不受开关影响 | 不受开关影响 | 不受开关影响 |

**界面**：

- 设置 → 通用里新增"允许在无隔离环境执行 agent 命令"开关。只在后端报告 `sandbox_available=false` 时显示，旁边写明风险（参照 §4.1 的最后一段）。
- 每轮的执行模式是 `unsandboxed` 时，对话里这一轮显示"命令未隔离"标记，复用现有的轮次标记位置。实现计划里要确认具体走哪个事件或字段。
- 健康检查或配置接口返回 `exec_mode`，前端据此决定显示哪些提示。

### 4.4 测试

- `exec_mode` 用参数注入覆盖整张表（macOS 上就能跑）。
- Claude 运行时测试断言三种模式下 `ClaudeAgentOptions` 的 `allowed_tools`、`disallowed_tools`、`sandbox`。
- OpenAI 运行时和 `render_music` 测试注入 `exec_mode`，断言是否提供 Shell，以及包裹函数是哪一种。
- Windows 本机实测（§9）：开关关闭时，agent 在 Claude 和 OpenAI 两条路径上都拿不到 Shell；打开后能执行 `echo`，并且 `guard` 能还原越界写入。

## 5. 路径安全：统一的模型路径校验

第一道检查（P6）改成**同时按 POSIX 和 Windows 两套规则拒绝**，不依赖当前平台：

- `files.normalize_relpath`、`files.safe_path`、`apply_patch.to_workspace_relpath`、`claude_scope` 的读写 hook 和 Glob 模式检查，都调用同一个函数（放在 `workspace/files.py`，例如 `check_model_path`）。
- 拒绝条件：路径为空；含 `\`（统一要求模型用 `/`）；含 `:`（盘符和 NTFS 备用数据流）；以 `/` 或 `//` 开头；按 `PureWindowsPath` 解析后有 drive 或 root（`C:`、`\\server\share`）；任何一段是 `..`；任何一段以空格或 `.` 结尾（Windows 会悄悄去掉，变成另一个文件）；任何一段是 Windows 保留名（`CON`、`NUL`、`COM1` 等，不分大小写，带扩展名也算）。
- **绝对路径**（Claude 的 Read、Write 工具会给出绝对路径）：先用当前平台的 `Path` 解析，再判断是否在工作区内。Windows 上的比较要统一大小写（`os.path.normcase`），因为 NTFS 默认不区分大小写。
- 这些规则在 macOS 上同样生效。按理不会影响现有合法路径：工作区里本来就没有这类文件名。如果实现时发现有冲突，要停下来记录。
- 测试：一张参数化的表，列出所有恶意写法，在 macOS 上就能跑。

## 6. 进程管理：`studio/proc.py`（新模块）

把"启动受控子进程、超时或取消时结束整棵进程树"收拢到一处，替代 `runner.kill_group`、`shell._kill_group` 以及散落各处的 `start_new_session=True`。

### 6.1 接口

```
def spawn_kwargs() -> dict[str, Any]
    # POSIX: {"start_new_session": True}
    # Windows: {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}

async def kill_tree(proc: asyncio.subprocess.Process) -> None
    # POSIX: os.killpg(proc.pid, SIGKILL)，忽略 ProcessLookupError/PermissionError
    # Windows: `taskkill /T /F /PID <pid>`（系统自带），失败时退回 proc.kill()
```

- 所有现在用到 `start_new_session` 或 `killpg` 的地方（P2、P3、Shell executor）都改用这两个函数。
- manim、ffmpeg、ffprobe 现在超时时只 `proc.kill()`。manim 会派生 ffmpeg 子进程，所以也改用 `spawn_kwargs()` + `kill_tree()`，避免 Windows 上留下 ffmpeg 占着文件（P12）。

### 6.2 资源限制（`limited_argv`）

- **POSIX**：保持现状，`/bin/sh -c 'ulimit -t …; ulimit -f …; exec "$@"'`。
- **Windows**：没有 `ulimit`，直接执行 argv，限制改为：
  - CPU 时间：只靠墙钟超时（已有）加上 `kill_tree`。
  - 输出文件大小：子进程结束后检查 `music.wav` 等产物的大小，超过 `_MAX_FILE_BYTES` 就当作失败。这个检查**两个平台都做**，作为兜底。
  - 这是功能上的降级，写进 ADR（§10），并登记技术债。如果以后需要严格限制，可以用 Job Object（`ctypes`，不需要新依赖）。

## 7. 编码与行尾

- **`.gitattributes`**：`* text=auto eol=lf`；二进制资产（`*.woff2`、`*.png`、`*.jpg`、`*.wav`、`*.mp3`、`*.mp4`）标为 `binary`；如果以后有 `*.ps1`、`*.cmd`，单独标成 `eol=crlf`。加上之后在 macOS 上重新规范化一次（`git add --renormalize .`），确认没有内容变化。
- **UTF-8 模式**：
  - `tasks.py` 启动的所有进程，以及后端启动的所有 Python 子进程（manim dry-run 和渲染、配乐脚本、歌曲分析、Shell），环境变量里都加上 `PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8`。
  - 对外部程序（ffmpeg、ffprobe）的输出，统一用 `decode("utf-8", errors="replace")` 解码，不依赖系统编码。
- **机器检查**：在 ruff 里启用 `PLW1514`（`open()`、`read_text()`、`write_text()` 等没有显式写 `encoding` 时报错），把"文本 IO 一律写 UTF-8"这条文字约定改成 lint 规则（SOP §10）。`score/exemplar/audio-techniques.py` 是给模型看的示例脚本，同样补上 `encoding`。

## 8. 开发工具链：`scripts/tasks.py`

### 8.1 形态

- 单个 Python 文件，**只用标准库**，用仓库根目录的 Python 运行：`uv run --project backend python scripts/tasks.py <task>`。在 Windows 上这就是主入口；README 和 AGENTS.md 里给出 PowerShell 写法。
- 子命令和现在的 Makefile 目标一一对应：`setup`、`check`、`check-fast`、`check-docs`、`check-backend`、`check-frontend`、`dev`、`smoke`、`import-legacy-styles`。`export-legacy-styles` 不迁移（§1 不做）。
- **Makefile 变薄**：每个目标只有一行，调用 `tasks.py` 的同名子命令。macOS 上的用法完全不变。
- 定位 `uv`、`pnpm` 的逻辑搬进 `tasks.py`：先 `shutil.which`，再看常见安装位置（macOS：`~/.local/bin/uv`、nvm；Windows：`%USERPROFILE%\.local\bin\uv.exe`、`pnpm.cmd`）。
- pre-commit hook 改成调用 `tasks.py check-fast`。Git for Windows 用自带的 sh 执行 hook，所以 hook 文件本身仍然是 sh 脚本。

### 8.2 `dev`：启动三个进程

- 用 `subprocess.Popen` 启动 api（`uvicorn --reload --reload-dir backend/src`）、worker 和前端，参数和 `proc.spawn_kwargs()` 相同。`tasks.py` 不 import 后端代码，要保持"只用标准库、单文件"，所以在 `tasks.py` 里复制一份 `spawn_kwargs` 和 `kill_tree` 的同步版本（约 20 行），两份的注释里互相指向对方。stdin 一律是 `DEVNULL`。三个进程的输出加上 `[api]`、`[worker]`、`[web]` 前缀后合并输出。
- **按 pid 文件清理旧进程**，替代 `lsof`、`ps` 那套启发式逻辑：启动后把 pid 写进 `<仓库根>/.dev/pids.json`（加进 `.gitignore`，**不放在 `data/` 下**）。下次启动时，先结束文件里还活着的进程树。端口仍被占用时直接报错退出，提示占用者的 pid（POSIX 用 `lsof`，Windows 用 `netstat -ano`），**不去结束别人的进程**，原则和现在一样。
- 用 Ctrl+C 或关闭终端退出时，对三个进程逐个 `kill_tree`。
- 导出 `backend/.env`：`tasks.py` 自己按 shell 语法的子集解析（`KEY=VALUE`、引号、`#` 注释），合并进子进程的环境变量。现在 `.env` 是用 `set -a; . backend/.env` 解析的，计划第一个任务要先确认现有 `.env` 只用了这个子集。
- 绑定地址仍然从 `python -m studio.config` 读取（TD-2），并导出 `STUDIO_BIND_PORT` 给 vite。

### 8.3 `smoke`

在 Python 里实现现在的 `env -i` + 白名单：从 `backend/.env` 和当前环境中只挑出 `SMOKE_KEYS`、`STUDIO_*` 以及运行必需的变量（POSIX：`HOME`、`PATH`、`USER`、`LANG`、`TMPDIR`、`SHELL`；Windows：`USERPROFILE`、`APPDATA`、`LOCALAPPDATA`、`PATH`、`SYSTEMROOT`、`TEMP`、`TMP`、`COMSPEC`、`PATHEXT`），然后运行 `pytest -m smoke`。

### 8.4 测试

`tasks.py` 里的纯逻辑（`.env` 解析、环境变量白名单、查找可执行文件、pid 文件读写）放进可以 import 的函数，在 `backend/tests/scripts/` 下写单元测试。进程的启动和清理在两个平台上实测（§9）。

## 9. 测试策略与 Windows 上的工作方式

### 9.1 测试的平台标记

- 本来就只适用于 POSIX 的测试（`sandbox-exec`、`killpg`、`ulimit`、Unix 权限位），在 `conftest.py` 里统一定义标记 `posix_only`、`macos_only`，按平台跳过。**这是计划里写明理由的跳过**，符合 AGENTS.md 的红线要求。每个标记都要在 docstring 里写明原因，而且必须有对应的 Windows 测试，或者说明 Windows 上这个功能本来就没有。
- 需要创建符号链接的测试：用一个探测 fixture，在 `tmp_path` 里试着建一次符号链接，建不了（Windows 没开开发者模式）就跳过，并给出提示。Windows 验收要求**开着开发者模式**跑一遍，确认符号链接相关的安全测试在 Windows 上真的执行过。
- 和平台有关的逻辑（`exec_mode`、路径校验、`spawn_kwargs`）用参数注入的方式测，两个平台都跑。

### 9.2 两台机器的分工

- **macOS 会话**能做的：§5 路径校验、§4.2 `exec_mode` 及各运行时的接线、§6 `proc.py` 的 POSIX 部分、§7 编码和行尾、§8 `tasks.py` 及 Makefile 改薄。这些在 macOS 上 `make check` 全绿就能提交。
- **Windows 会话**负责：§6 的 Windows 分支实测、P12 文件占用、P13 uvicorn 事件循环、P14 launch.json、`tasks.py` 在 PowerShell 下运行、Windows 下的安装文档、完整走一遍项目。
- 计划里按任务写明在哪台机器上做。负责人决定先在 Windows 上跑全部任务，所以所有任务也必须能在 Windows 上完成。如果某个任务在 Windows 上做不了（例如验证 macOS 的 Seatbelt 没有倒退），就在计划的「下一步」里写明，回到 macOS 再补。
- 交接全靠 git 和计划文件：分支 `windows-native`。两台机器都要能 push 到 `origin`，或者用其他方式同步，由负责人决定。会话开始时先 `git pull`，结束时更新计划，再 commit 和 push。

### 9.3 Windows 环境（写进 `docs/runbooks/dev-setup.md` 的 Windows 一节）

| 依赖 | 安装方式（推荐 winget） | 说明 |
|---|---|---|
| Git for Windows | `winget install Git.Git` | 提供 Git Bash，用来跑 hook，也是开关打开时 Claude Bash 的执行环境 |
| uv | `winget install astral-sh.uv` | 会自动下载 Python 3.12 |
| Node 22+ 和 pnpm | `winget install OpenJS.NodeJS.LTS`；`corepack enable` | |
| ffmpeg | `winget install Gyan.FFmpeg` | 要能在 PATH 里找到 `ffmpeg` 和 `ffprobe` |
| LaTeX | MiKTeX（`winget install MiKTeX.MiKTeX`），装 `ctex`；或者 TeX Live | manim 渲染公式要用 |
| Claude Code | 官方 Windows 安装方式 | 开发会话用；`claude-login` 模型配置也依赖它的登录状态 |
| 开发者模式 | 设置 → 系统 → 开发者选项 | 允许不提权就创建符号链接，安全测试要用 |

manim 在 Windows 上的 cairo、pango 依赖由 wheel 自带，不需要另外装。这一点**要在 Windows 上实测确认**，确认后写进 `docs/references/manim.md`。

## 10. 文档、ADR 与技术债

- **ADR 0024 无隔离执行开关**：说明 Windows 上为什么不做隔离（§4.1）、开关的语义、剩余风险，以及开关在 macOS 上不生效。引用 0009 和 0010。
- **ADR 0025 Python 任务脚本**：说明 `tasks.py` 成为工具链的唯一逻辑来源，Makefile 只是薄壳；`make check` 仍然是质量关口的名字，Windows 上的等价写法是 `tasks.py check`。
- 需要更新的文档：`AGENTS.md`「常用命令」加上 Windows 写法；`docs/runbooks/dev-setup.md` 加 Windows 一节；`docs/runbooks/verification.md`；`docs/ARCHITECTURE.md`（新增 `agent/exec_policy.py`、`studio/proc.py` 两个模块，并更新 import-linter 规则）；`docs/references/claude-agent-sdk.md`（Windows 上 CLI 的 Bash 和 PowerShell 工具、`disallowed_tools`、不传 sandbox 时的实测行为）。
- 需要登记的技术债：manim 执行 agent 代码没有 sandbox（与平台无关，§3）；Windows 上没有 CPU 时间和文件大小的硬限制（§6.2）；Windows 上 `upstream/` 目录的只读保护变弱（P7）。

## 11. 验收标准

1. macOS：`make check` 全绿；`make dev` 能启动并正常退出，退出后不留下孤儿进程；在 Seatbelt 下 OpenAI Shell 和 `render_music` 的行为不变（已有测试通过）；`make smoke SMOKE_ARGS="-k claude_login"` 通过。
2. Windows：在 PowerShell 里运行 `uv run --project backend python scripts/tasks.py check` 全绿，并且是在**开发者模式开启**的情况下跑的，符号链接相关测试真的执行过；pre-commit hook 能在 `git commit` 时运行。
3. Windows：`tasks.py dev` 能启动三个进程；Ctrl+C 退出后，任务管理器里没有残留的 python、node、ffmpeg 或 chromium 进程；再次启动不会报"端口被占用"。
4. Windows：开关关闭时，Claude 和 OpenAI 两条路径的 agent 都拿不到 Shell，`render_music` 返回的错误说明了原因；打开开关后，下一轮 agent 能执行命令，界面显示"命令未隔离"，越界写入能被 `guard` 还原。
5. Windows：用 `claude-login` 模型完整走一个讲解类项目（选题 → 叙事 → 动画 → 成片，manim 引擎）和一个短片（`concept → produce`，HTML 引擎 + 合成配乐，开关打开），成片能播放，中文显示正常。
6. Windows：§5 列出的恶意路径写法在 Windows 上全部被拒绝（测试覆盖，并且在 Windows 上运行过）。
7. 文档、ADR 和技术债按 §10 更新完毕。

## 12. 风险与需要实测的项

| 项 | 风险 | 处理 |
|---|---|---|
| P13 uvicorn reload 的事件循环 | 子进程全部失败 | Windows 会话的第一批任务里实测；如果有问题，调整 uvicorn 版本或启动方式（例如 `--loop` 参数），不改业务代码 |
| Windows 上 Claude CLI 的工具名和行为 | `PowerShell` 工具的名字、`disallowed_tools` 是否生效、不传 sandbox 时是否有提示，都没有验证过 | 实测后写进 references；和 §4.3 不一致时按升级条件停下来 |
| P12 文件占用 | 快照还原、`guard` 还原、成片覆盖时报 `PermissionError` | 先实测再决定；需要的话对删除和改名加有限次重试（只针对 `PermissionError`，最多约 1 秒），写进决策记录 |
| manim 在 Windows 上的安装 | wheel 不带 cairo 或者 LaTeX 配置繁琐 | 实测；装不上时停下来升级，讲解类形态在 Windows 上可能要降级 |
| Chromium（playwright）和字体 | HTML 引擎已经随包带了字体，风险低 | 走一遍短片验证 |
| 路径长度 | 工作区路径太深时超过 260 字符 | 文档里建议把仓库放在较短的路径下（如 `C:\dev\ai-video-studio`）；不主动处理，遇到再登记 |
