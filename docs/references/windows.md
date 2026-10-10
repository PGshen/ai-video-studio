# Windows 11 原生环境：实测结论

windows-native 计划在负责人的 Windows 11 Pro（10.0.26200，中文系统，代码页 936）上实测得到的结论。写代码、写测试、写环境说明时以这里为准。设计见 [windows-native-support](../design/2026-10-09-windows-native-support.md)，决定见 [ADR 0024](../decisions/0024-无隔离执行开关.md)、[ADR 0025](../decisions/0025-Python任务脚本.md)。

## 编码与换行

| 状态 | 结论 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-09） | 默认编码是 GBK（cp936）：`open()`/`read_text()` 不写 `encoding` 时按 GBK 读写，读 UTF-8 中文 JSON 会出乱码或报错。产品代码一律写 `encoding="utf-8"`（ruff `PLW1514` + `tests/test_lint_rules.py` 的 AST 检查）；测试必须在 UTF-8 模式下跑（`PYTHONUTF8=1`，`tasks.py` 会设置，`conftest.py` 在 Windows 上发现没开就报错） | 基线：113 个失败里有 16 个在 `PYTHONUTF8=1` 下通过 |
| ✅ 已验证（2026-10-10） | 文本模式写文件会把 `\n` 写成 `\r\n`，同一次编辑在 Windows 和 macOS 上存下不同的字节、得到不同的快照哈希。产品代码的文本写入一律加 `newline=""`（`tests/test_lint_rules.py` 守住） | `test_runner.py::TestPreambleAcrossTurns` 在 Windows 上失败 |
| ✅ 已验证（2026-10-09） | Git for Windows 的系统级配置默认 `core.autocrlf=true`，工作区是 CRLF；仓库已有 `.gitattributes`（`* text=auto eol=lf`），本仓库另设 `core.autocrlf false` | 本机 `git config --show-origin` |
| ✅ 已验证（2026-10-10） | 子进程（ffmpeg、vite 等）输出里有 GBK 编码不了的字符（如 Vite 的 `➜`）时，往 GBK 的 stdout 打印会抛 `UnicodeEncodeError`；转发线程要用 `errors="replace"` 兜住，否则管道没人读、子进程卡死 | `tasks.py dev` 实测 |
| ✅ 已验证（2026-10-10） | `python -I` 会忽略 `PYTHONUTF8` 等环境变量；要在 `-I` 下用 UTF-8 模式，写 `python -I -X utf8` | 本机实测 |
| ✅ 已验证（2026-10-09） | Git Bash 里 `lint-imports`、`check_docs.py` 等的中文输出是乱码（控制台代码页 936）；PowerShell 里正常。日常命令在 PowerShell 里跑 | 本机实测 |

## 进程

| 状态 | 结论 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-10） | `os.kill(pid, 0)` **不是探活，而是结束进程**（除 CTRL_C/CTRL_BREAK 外的信号都变成 `TerminateProcess`）。判断进程是否还在用 `tasklist /FI "PID eq N"` 或 CIM（`tests/fixtures/processes.py`） | Python 文档 `os.kill`；实测 |
| ✅ 已验证（2026-10-10） | `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F /PID <pid>` 能结束整棵进程树（含孙进程、uvicorn reloader、Playwright 的 Chromium）；父进程已退出时 `/T` 找不到它的后代，且 PID 可能已被复用，所以只对还在运行的子进程这样做（`studio.proc`） | `tests/test_proc.py`、`tasks.py dev` 实测 |
| ✅ 已验证（2026-10-10） | 拿别的进程的命令行：`tasklist` 没有，`wmic` 已弃用，用 PowerShell `Get-CimInstance Win32_Process`（`ProcessId`、`ParentProcessId`、`CommandLine`） | `tasks.py dev`、`tests/fixtures/processes.py` |
| ✅ 已验证（2026-10-10） | 白名单环境变量里没有 `SYSTEMROOT` 时，Windows 上的 Python 子进程启动即失败；`studio.proc.child_env` 在 Windows 上补 `SYSTEMROOT`、`WINDIR`、`COMSPEC`、`PATHEXT` | 配乐脚本、歌曲分析的测试 |
| ✅ 已验证（2026-10-10） | 不能直接执行 `#!/bin/sh` 脚本（`OSError: %1 不是有效的 Win32 应用程序`）；测试里的假程序用 Python 写，经 `sys.executable` 运行 | `test_html_video.py` |
| ✅ 已验证（2026-10-10） | `pnpm` 是 `pnpm.CMD`（批处理），`Popen` 启动它时顶层进程是 `cmd.exe`；`shutil.which("pnpm")` 能按 `PATHEXT` 找到它 | `tasks.py dev` |
| ✅ 已验证（2026-10-10） | 在新进程组里的子进程收不到控制台的 Ctrl+C；`tasks.py dev` 自己处理 Ctrl+C 和 Ctrl+Break（`SIGBREAK`，关闭控制台窗口也会发）后结束三棵树 | 实测（发 `CTRL_BREAK_EVENT`） |
| ✅ 已验证（2026-10-10） | `time.monotonic()`/定时器精度约 15.6 ms：`asyncio.sleep(0.05)` 量出来可能是 47 ms | `test_fake.py` 偶发失败 |

## 文件系统

| 状态 | 结论 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-10） | 打开开发者模式后，Python 的 `os.symlink` 不用提权就能建符号链接；**PowerShell 5.1 的 `New-Item -ItemType SymbolicLink` 仍然要求管理员**（它不带 `SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE`）。验证开发者模式用 Python。没有权限时 `os.symlink` 抛 `OSError`，`winerror == 1314` | 本机实测 |
| ✅ 已验证（2026-10-10） | `chmod(0)` 不会让文件不可读（Windows 只有只读属性） | `test_upstream.py` |
| ✅ 已验证（2026-10-10） | 文件名不能含 `<>:"|?*`，结尾的 `.` 和空格会被悄悄去掉，`CON`、`aux.txt` 等是设备名；模型给出的路径按两套规则一起校验（`workspace.files.check_model_path`） | 设计 §5、`test_model_path.py` |
| ✅ 已验证（2026-10-10） | 被其他进程（编辑器、索引）映射着的文件，改写时可能报 `os error 1224`（"请求的操作无法在使用用户映射区域打开的文件上执行"），重试即可 | `ruff --fix` 偶发 |

## 工具链

| 状态 | 结论 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-10） | Claude 桌面版的 `preview_start` 能直接按 `.claude/launch.json` 起 `uv run uvicorn --reload` 和 `pnpm run dev`；`preview_stop` 后没有残留进程 | T6 实测 |
| ✅ 已验证（2026-10-10） | 内置浏览器面板隐藏时，坐标点击和截图会因"页面没有绘制"超时；`form_input`、`javascript_tool`、`get_page_text` 不受影响 | T6 实测 |
| ✅ 已验证（2026-10-09） | 本机的 Git Bash 里 nvm4w 的 `pnpm` sh 启动脚本解析错路径（指向 Anaconda 目录），PowerShell 里正常 | 本机实测（和 Anaconda 的 PATH 顺序有关，不是通用结论） |
| ✅ 已验证（2026-10-10） | vitest 首次转换整个工作台页面依赖图要 5 秒以上（紧接后端测试之后更慢），`router.spec.ts` 的这个用例单独放宽了超时 | T9 实测 |
| ✅ 已验证（2026-10-10） | Windows 版 Claude CLI：命令工具名是 `PowerShell` 和 `Bash`（Git Bash），`disallowed_tools` 生效，不传 sandbox 时正常启动；详见 [claude-agent-sdk.md](claude-agent-sdk.md) 末节 | T10 登录冒烟 |
| ✅ 已验证（2026-10-10） | 别的句柄开着文件时，`os.replace` 覆盖它报 `WinError 5`、删除它报 `WinError 32`；读者关闭后立即成功。产品代码里成片、配乐、工作区还原和删除改用 `studio.fsretry`（只在 Windows 上对 `PermissionError` 重试约 1 秒） | P12 实验、`tests/test_fsretry.py` |
