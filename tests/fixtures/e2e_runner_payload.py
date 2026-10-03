"""CLI lifecycle fixture; substitutes payload work, not directory ownership."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("driver", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fail", action="store_true")
    parser.add_argument("--race-ready", type=Path)
    args = parser.parse_args()
    if args.race_ready:
        mkdir = Path.mkdir

        def concurrent_mkdir(path, *positional, **keywords):
            if path == args.output:
                (args.race_ready / str(os.getpid())).write_text("ready\n")
                deadline = time.monotonic() + 45
                while len(list(args.race_ready.iterdir())) < 2:
                    if time.monotonic() > deadline:
                        raise TimeoutError("Other CLI did not reach directory claim")
                    time.sleep(0.01)
            return mkdir(path, *positional, **keywords)

        Path.mkdir = concurrent_mkdir

    def payload(root, **_):
        # Old runners claimed inside their payload; corrected CLIs already own it.
        # This allows the same adversarial fixture to demonstrate both versions.
        if not root.exists():
            root.mkdir(parents=True, exist_ok=False)
        (root / "fixture-payload.json").write_text(
            json.dumps({"owner_pid": os.getpid(), "value": "synthetic"}) + "\n"
        )
        if args.fail:
            raise RuntimeError("Deliberate synthetic post-claim payload failure")
        return {"status": "passed", "exit_status": 0}

    namespace = runpy.run_path(str(args.driver))
    entrypoint = namespace["main"]
    entrypoint.__globals__["run"] = payload
    sys.argv = [str(args.driver), str(args.output)]
    return entrypoint()


if __name__ == "__main__":
    raise SystemExit(main())
