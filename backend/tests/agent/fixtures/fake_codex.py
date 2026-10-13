"""A stand-in for `codex exec --json` used by the CodexRuntime tests.

Behaviour comes from environment variables set by the test:

- `FAKE_CODEX_SCRIPT`: a JSONL file whose lines are printed to stdout.
- `FAKE_CODEX_RECORD`: where to write argv, stdin, cwd, env keys and whether `--image=` files exist.
- `FAKE_CODEX_STDERR`: text written to stderr.
- `FAKE_CODEX_EXIT`: exit code (default 0).
"""

from __future__ import annotations

import json
import os
import sys
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
    return int(os.environ.get("FAKE_CODEX_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
