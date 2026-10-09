"""Isolated song analysis (4A T3): decode, analyse and draw in a subprocess with a timeout.

Parent side: `run_song_analysis` (async, process-tree kill via `studio.proc`, CPU/file limits
from `runner` on POSIX).
Child side: `python -m studio.engines.audio.song_job <source> <out_dir>` decodes once and shares the
samples between the analysis and the picture. This is our own code, so no sandbox; the child only
reads `source` and writes `analysis.json` / `analysis.png` into `out_dir`. The caller moves them
into place after success. The first librosa call in a fresh environment takes ~27 s (numba JIT),
so keep `timeout` at 60 s or more.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from studio import proc
from studio.engines.audio.runner import drain, limited_argv, tail_lines
from studio.engines.audio.wav import AudioError

DEFAULT_TIMEOUT = 120.0
_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "HOME", "PYTHONPATH", "VIRTUAL_ENV")
_ARTIFACTS = ("analysis.json", "analysis.png")


class SongJobError(RuntimeError):
    """Analysis failed, timed out or produced no artifact; the message is Chinese, for the agent."""


@dataclass(frozen=True, slots=True)
class SongJobResult:
    analysis_path: Path
    picture_path: Path
    elapsed: float


def _command(source: Path, out_dir: Path, timeout: float) -> list[str]:
    argv = [sys.executable, "-m", "studio.engines.audio.song_job", str(source), str(out_dir)]
    return limited_argv(argv, int(timeout) + 10)


async def run_song_analysis(
    source: Path, out_dir: Path, *, timeout: float = DEFAULT_TIMEOUT
) -> SongJobResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = proc.child_env({key: os.environ[key] for key in _ENV_KEYS if key in os.environ})
    env.update(TMPDIR=str(out_dir), PYTHONDONTWRITEBYTECODE="1")
    started = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *_command(source, out_dir, timeout),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        cwd=out_dir,
        env=env,
        **proc.spawn_kwargs(),
    )

    def clean() -> None:
        for name in _ARTIFACTS:
            (out_dir / name).unlink(missing_ok=True)

    try:
        stderr, _ = await asyncio.wait_for(
            asyncio.gather(drain(process.stderr, 16000), process.wait()), timeout
        )
    except TimeoutError:
        await proc.kill_tree(process)
        await process.wait()
        clean()
        raise SongJobError(
            f"歌曲分析超过 {timeout:g} 秒被终止（超时）；歌曲过长或机器过忙，可稍后重试"
        ) from None
    except BaseException:
        proc.kill_proc_tree(process)  # sync: an await here could be cancelled again
        with contextlib.suppress(Exception):
            await process.wait()
        clean()
        raise
    await proc.kill_tree(process)  # leftover children of a job that exited normally (POSIX)
    if process.returncode != 0:
        clean()
        raise SongJobError(f"歌曲分析失败（退出码 {process.returncode}）：\n{tail_lines(stderr)}")
    for name in _ARTIFACTS:
        if not (out_dir / name).is_file():
            clean()
            raise SongJobError(f"歌曲分析没有写出 {name}")
    return SongJobResult(
        analysis_path=out_dir / "analysis.json",
        picture_path=out_dir / "analysis.png",
        elapsed=time.monotonic() - started,
    )


def _main(argv: list[str]) -> int:
    from studio.engines.audio.picture import render_song_png
    from studio.engines.audio.song import analyze_samples, decode_song, file_hash

    source, out_dir = Path(argv[1]), Path(argv[2])
    try:
        samples = decode_song(source)
        analysis = analyze_samples(samples, source_hash=file_hash(source))
        picture = render_song_png(analysis, samples)
    except AudioError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    # Picture first: the JSON is the last artifact to appear, and a failure leaves nothing behind.
    (out_dir / "analysis.png").write_bytes(picture)
    (out_dir / "analysis.json").write_text(
        json.dumps(analysis.to_document(), ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
