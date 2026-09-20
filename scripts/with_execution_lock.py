#!/usr/bin/env python3
"""Hold a local advisory lock across a command, including exec/child processes."""

import argparse
import fcntl
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Probe without running a command"
    )
    parser.add_argument("lock_file", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not args.check and not command:
        parser.error("supply a command after --, or use --check")
    if args.check and command:
        parser.error("--check does not accept a command")

    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                f"Execution already locked: {args.lock_file}. No command started.",
                file=sys.stderr,
            )
            return 75
        if args.check:
            return 0
        # Never unlink the file: a new inode could let a second owner bypass it.
        # Inherit the descriptor so the lock survives shell/caffeinate exec.
        os.set_inheritable(lock.fileno(), True)
        os.execvp(command[0], command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
