"""A stand-in for `codex exec --json` used by the CodexRuntime tests.

Behaviour comes from environment variables set by the test:

- `FAKE_CODEX_SCRIPT`: a JSONL file whose lines are printed to stdout.
- `FAKE_CODEX_RECORD`: where to write argv, stdin, cwd, env keys and whether `--image=` files exist.
- `FAKE_CODEX_STDERR`: text written to stderr.
- `FAKE_CODEX_EXIT`: exit code (default 0).
- `FAKE_CODEX_HANG`: after the script, start `sleep 60` in its own process group (as codex does
  for commands), write its pid to `FAKE_CODEX_CHILD_PID`, and wait. `handle`: on SIGINT kill that
  child and exit 1 (codex's behaviour); `ignore`: ignore SIGINT.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    stdin = sys.stdin.read()
    record = os.environ.get("FAKE_CODEX_RECORD")
    images = [arg.split("=", 1)[1] for arg in sys.argv[1:] if arg.startswith("--image=")]
    if record:
        Path(record).write_text(
            json.dumps(
                {
                    "argv": sys.argv[1:],
                    "stdin": stdin,
                    "env": sorted(os.environ),
                    "images_exist": [Path(p).is_file() for p in images],
                    "cwd": os.getcwd(),
                }
            ),
            encoding="utf-8",
        )
    script = os.environ.get("FAKE_CODEX_SCRIPT")
    if script:
        sys.stdout.write(Path(script).read_text(encoding="utf-8"))
        sys.stdout.flush()
    sys.stderr.write(os.environ.get("FAKE_CODEX_STDERR", ""))
    hang = os.environ.get("FAKE_CODEX_HANG")
    if hang:
        child = subprocess.Popen(["sleep", "60"], start_new_session=True)
        Path(os.environ["FAKE_CODEX_CHILD_PID"]).write_text(str(child.pid), encoding="utf-8")
        if hang == "ignore":
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        else:

            def on_int(*_: object) -> None:
                child.kill()
                child.wait()
                sys.exit(1)

            signal.signal(signal.SIGINT, on_int)
        print(
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "id": "item_9",
                        "type": "command_execution",
                        "command": "sleep 60",
                        "status": "in_progress",
                    },
                }
            ),
            flush=True,
        )
        while True:
            time.sleep(0.05)
    return int(os.environ.get("FAKE_CODEX_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
