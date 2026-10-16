"""`codex exec --json` 的命令行（codex-runtime T3；行为依据 docs/references/codex.md）。

- 收口：`--ignore-user-config`、`--ignore-rules` 和 `LOCKDOWN_ARGS`（关掉仓库 AGENTS.md、用户
  skills、插件、记忆、网页搜索、多 agent 等注入），每次都带。
- 阶段系统提示经 `developer_instructions` 注入，只在新建会话时生效（续会话时 codex 不读它，
  变更由运行时并进用户消息）。多 agent 工具关不掉，只能在提示末尾禁止（`NO_SUBAGENTS_NOTE`）。
- 续会话：exec 级选项都放在 `resume <thread_id>` 之前（`-m` 换模型、`-c` 覆盖项照样生效）。
- 提示词一律从 stdin 读（参数 `-`）：没有命令行长度限制，也不会被可变参数的 `-i` 吞掉；
  图片用 `--image=<路径>` 的单值写法。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from studio.agent.runtime import Effort

LOCKDOWN_ARGS: tuple[str, ...] = (
    "-c", "project_doc_max_bytes=0",
    "-c", "skills.include_instructions=false",
    "-c", "skills.bundled.enabled=false",
    "-c", "include_apps_instructions=false",
    "-c", "include_collaboration_mode_instructions=false",
    "-c", 'web_search="disabled"',
    "-c", "tools.update_plan.enabled=false",
    "--disable", "multi_agent",
    "--disable", "plugins",
    "--disable", "apps",
    "--disable", "memories",
    "--disable", "skill_search",
    "--disable", "tool_suggest",
    "--disable", "image_generation",
    "--disable", "browser_use",
    "--disable", "computer_use",
    "--disable", "goals",
)  # fmt: skip
"""最小上下文参数组合（codex.md「注入的上下文与收口」）。"""

NO_SUBAGENTS_NOTE = (
    "\n\n不要派生子 agent，也不要使用 spawn_agent、send_message、wait_agent 等协作工具；"
    "所有工作都在当前会话里完成。"
)
"""这个版本关不掉 `collaboration.*` 工具（codex.md），只能在提示里禁止。"""


def toml_string(value: str) -> str:
    """`-c key=<值>` 里的 TOML 字符串；JSON 字符串转义是合法的 TOML basic string。"""
    return json.dumps(value)


def build_args(
    *,
    workdir: Path,
    model: str,
    resume_ref: str | None,
    system_prompt: str | None,
    effort: Effort | None,
    image_paths: Sequence[Path],
    extra: Sequence[str],
) -> list[str]:
    """完整参数（不含可执行文件本身）。`extra` 是 MCP、沙箱等其他模块给的 `-c`/`-s` 参数。"""
    args = [
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "-C",
        str(workdir),
        *LOCKDOWN_ARGS,
        "-m",
        model,
    ]
    if effort is not None:
        args += ["-c", f"model_reasoning_effort={toml_string(effort)}"]
    if resume_ref is None:
        # None: codex's own instructions only (open-mode design §5.1); the note stays because
        # this version cannot turn the collaboration tools off.
        if system_prompt is None:
            instructions = NO_SUBAGENTS_NOTE.strip()
        else:
            instructions = system_prompt + NO_SUBAGENTS_NOTE
        args += ["-c", f"developer_instructions={toml_string(instructions)}"]
    args += list(extra)
    if resume_ref is not None:
        args += ["resume", resume_ref]
    args += [f"--image={path}" for path in image_paths]
    args.append("-")
    return args
