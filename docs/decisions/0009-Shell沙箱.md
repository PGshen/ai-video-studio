# 0009：OpenAI 路径 Shell 用 macOS sandbox-exec 包裹

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已采纳 |
| 日期 | 2026-09-28 |
| 相关 | [M1x 计划 T9](../plans/active/m1x-tech-debt.md)、[tech-debt TD-20/TD-14](../quality/tech-debt.md)、[openai-agents-sdk.md](../references/openai-agents-sdk.md)、[claude-agent-sdk.md](../references/claude-agent-sdk.md)（T8 的 denyRead/allowRead）、设计 §4.3 |

## 背景

OpenAI Agents SDK 的 `ShellTool` 在本地执行命令（`LocalShellExecutor`）。M1 时没有沙箱：命令能读本机任意文件（包括 `backend/.env` 里的密钥、其他项目的工作区、`studio.db`），能写任何有权限的位置，也能联网。工作区内的越界改动靠轮末 `guard` 还原，工作区外没有任何防线。提示注入（例如上游产物或网页内容里夹带指令）时，这条路径的风险明显高于 Claude 路径——后者的 Bash 已由 CLI sandbox 拒读仓库与数据目录（T8，TD-1）。

约束：单人本地使用，主要运行在 macOS；不引入新依赖；Shell 仍须能跑 `python3`、`ls`、`cat` 工作区文件、在工作区里写文件。

## 决定

- `LocalShellExecutor` 的每条命令都经 `/usr/bin/sandbox-exec -p <profile> /bin/sh -c <command>` 执行（`create_subprocess_exec`，`start_new_session=True` 不变；`sandbox-exec` 调 `sandbox_init` 后 exec `/bin/sh`，PID 与进程组不变，超时/取消/后台进程的 `killpg` 语义照旧）。
- Seatbelt 配置由 `agent/shell_sandbox.seatbelt_profile(workdir, deny_read)` 生成，路径全部取真实路径：
  - `(allow default)` 为基础；
  - `(deny network*)`：包括本机回环；另加 `(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd"))`、`(deny appleevent-send)`、`(deny process-exec (literal "/usr/bin/open") (literal "/usr/bin/osascript"))`——堵住经 LaunchServices/Apple Event/`open`/`osascript` 间接联网或跳出沙箱的旁路（最终复核发现，详见下方残余风险）；
  - `(deny file-read* <仓库根> <data_dir>)` 后 `(allow file-read* <当前工作区>)`——与 Claude 路径的 denyRead/allowRead 同一策略。Seatbelt 对同一操作后写的规则优先，2026-09-28 本机（Darwin 24.6）实测"拒父目录、放回子目录"成立；
  - `(deny file-write*)` 后只放回当前工作区、`<workdir>/.cache/tmp`、`/dev/null`、`/dev/tty`、`/dev/fd`（`/dev/stdout`、`/dev/stderr` 经它解析）。
- 子进程的 `TMPDIR` 指向 `<workdir>/.cache/tmp`（`.cache/` 不参与快照、不对前端列出）。
- `native_shell_supported` 增加条件：`sys.platform == "darwin"` 且 `/usr/bin/sandbox-exec` 存在，否则**失败关闭**——不提供 Shell，改给兜底只读工具 `list_files`/`read_file`。
- `OpenAIRuntime` 新增可选参数 `repo_root`（缺省 `studio.config.repo_root()`）与 `sandbox_available`（缺省检测本机，测试注入），拒读列表为 `[repo_root, data_dir]`。

## 考虑过的其他方案

- **容器（Docker/Podman、Apple `container`）**：隔离更彻底，也能跨平台，还能顺带解决 `setsid` 逃逸（容器停掉即全部回收）。不选的原因：需要额外安装运行时（相当于新依赖），每条命令起容器的延迟与挂载工作区的文件权限、路径映射都要额外处理；对单人本地工具而言成本过高。`sandbox-exec` 失效时这是首选替代。
- **默认关闭 Shell、只给兜底文件工具**：最安全，但 OpenAI 模型失去执行脚本、跑 `python3` 做校验的能力，动画阶段（M2 起）尤其需要。作为非 macOS 平台的行为保留。
- **只过滤环境变量（M1 现状）**：挡不住直接读 `backend/.env`，不是安全边界。
- **按命令字符串做黑名单**：可以被任意改写绕过，不可靠。

## 影响

- 好处：OpenAI 路径 Shell 读不到仓库（含 `backend/.env`）、`studio.db`、其他项目；写不出当前工作区；没有直接的网络出站（`(deny network*)`），且堵上了经 `mach-lookup`/`launchservicesd`/Apple Event/`open`/`osascript` 间接指使沙箱外进程联网的旁路（见下方最终复核残余风险）。与 Claude 路径的边界一致。
- `sandbox-exec` 已被 Apple 在手册页中标为 DEPRECATED（`man sandbox-exec`："execute within a sandbox (DEPRECATED)"），但本机 macOS 15.6.1（Darwin 24.6）上仍可用（2026-09-28 实测）。将来被移除时 `sandbox_available()` 返回假，运行时自动失败关闭（不提供 Shell），不会在无沙箱下执行；届时按上面"容器"方案迁移。
- 非 macOS 平台不提供 OpenAI 原生 Shell。
- 残余风险：用 `setsid` 等方式主动脱离进程组的后台进程仍不会被 `killpg` 杀掉（TD-14 保留登记）。沙箱之后它的危害降为"在轮末 `guard`/快照之后继续改当前工作区"，读不到仓库、写不出工作区、也不能联网。
- 位于仓库内的工具（`backend/.venv`、`frontend/node_modules`）在 Shell 里不可用：`uv run` 启动的后端 PATH 以 `backend/.venv/bin` 开头，沙箱内 `/bin/sh` 查找命令时跳过这个读不到的目录，落到下一个 PATH 项（本机 `~/miniconda3/bin/python3`），项目依赖（如 `pydantic`）因此不可用。M2 若需要，按需把具体路径加进放回列表。
- macOS 的 `mktemp`（不带模板）不看 `TMPDIR`，用 `confstr(_CS_DARWIN_USER_TEMP_DIR)` 的 `/var/folders/...`，在沙箱里写入失败；`mktemp "$TMPDIR/x.XXXX"` 与 Python `tempfile` 正常。
- 工作区内、但不在阶段可写范围的路径 Shell 仍能写，照旧由轮末 `guard` 还原。
- 残余风险（T10 复核，2026-09-28）：Seatbelt 的 `(allow default)` 只针对仓库根与 `data_dir` 拒读，主目录下的 `~/.ssh`、`~/.config`、keychain 列表等仍可读；Shell 本身没有网络，但命令的 stdout 会作为工具结果回给模型，等于多了一条经模型通道外泄的路径（提示注入场景下 `cat ~/.ssh/id_ed25519` 之类命令会成功）。与 Claude 路径（`claude_scope.sandbox_settings` 的 denyRead 同样只拒仓库根与 `data_dir`）风险等级一致，未在本次范围内处理，登记为 TD-27，需要时再追加 `~/.ssh`、`~/.aws` 等 denyRead。登录模式下两条路径还都读得到 `~/.claude/projects/<编码后的路径>/`——本机**所有** studio 项目的会话 transcript，不只当前项目，比 `~/.ssh` 更窄但同样是真实缺口，一并登记进 TD-27；本轮复核判断给它加 denyRead 有影响 Claude CLI 自身会话记账的风险，需要专门的真机验证，不在本次修复范围内。
- 残余风险（最终复核，2026-09-28）：`(allow default)` 下 mach IPC 默认放行，`lsappinfo front`/`open <url>`/`osascript -e '...'` 能经 `mach-lookup` 联系 `launchservicesd`、把 URL 交给未被沙箱管住的默认浏览器打开，或发送 Apple Event，绕开 `(deny network*)`（沙箱本身没有联网，但能间接指使沙箱外的进程联网）。已加三条 SBPL 规则堵上：`(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd"))`、`(deny appleevent-send)`、`(deny process-exec (literal "/usr/bin/open") (literal "/usr/bin/osascript"))`；真实执行测试见 `backend/tests/agent/test_shell_sandbox.py`。
- setuid 二进制（如 `/bin/ps`）在 Seatbelt 沙箱里无法执行（`Operation not permitted`），因为 Seatbelt 阻止 exec setuid 程序；连同 `mktemp` 的限制一起，是 agent 在 Shell 里可能遇到的使用侧限制，已写入 `docs/references/openai-agents-sdk.md`。
