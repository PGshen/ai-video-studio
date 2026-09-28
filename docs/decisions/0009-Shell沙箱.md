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
  - `(deny network*)`：包括本机回环；
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

- 好处：OpenAI 路径 Shell 读不到仓库（含 `backend/.env`）、`studio.db`、其他项目；写不出当前工作区；没有网络。与 Claude 路径的边界一致。
- `sandbox-exec` 已被 Apple 在手册页中标为 DEPRECATED（`man sandbox-exec`："execute within a sandbox (DEPRECATED)"），但本机 macOS 15.6.1（Darwin 24.6）上仍可用（2026-09-28 实测）。将来被移除时 `sandbox_available()` 返回假，运行时自动失败关闭（不提供 Shell），不会在无沙箱下执行；届时按上面"容器"方案迁移。
- 非 macOS 平台不提供 OpenAI 原生 Shell。
- 残余风险：用 `setsid` 等方式主动脱离进程组的后台进程仍不会被 `killpg` 杀掉（TD-14 保留登记）。沙箱之后它的危害降为"在轮末 `guard`/快照之后继续改当前工作区"，读不到仓库、写不出工作区、也不能联网。
- 位于仓库内的工具（`backend/.venv`、`frontend/node_modules`）在 Shell 里不可用：`uv run` 启动的后端 PATH 以 `backend/.venv/bin` 开头，沙箱内 `/bin/sh` 查找命令时跳过这个读不到的目录，落到下一个 PATH 项（本机 `~/miniconda3/bin/python3`），项目依赖（如 `pydantic`）因此不可用。M2 若需要，按需把具体路径加进放回列表。
- macOS 的 `mktemp`（不带模板）不看 `TMPDIR`，用 `confstr(_CS_DARWIN_USER_TEMP_DIR)` 的 `/var/folders/...`，在沙箱里写入失败；`mktemp "$TMPDIR/x.XXXX"` 与 Python `tempfile` 正常。
- 工作区内、但不在阶段可写范围的路径 Shell 仍能写，照旧由轮末 `guard` 还原。
