#!/usr/bin/env python3
"""PreToolUse guard: agents may read .claude/rules/ but never modify it (or this guard).

Exit 2 blocks the tool call and shows stderr to the agent. Humans edit the rules directly.
"""

import json
import os
import re
import sys

PROJECT = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
PROTECTED = [
    os.path.join(PROJECT, ".claude", "rules"),
    os.path.join(PROJECT, ".claude", "hooks", "protect_rules.py"),
]
PROTECTED_RE = re.compile(r"\.claude/(rules\b|hooks/protect_rules\.py)")
# Anything that can write, move, delete, or change permissions in a shell command.
WRITE_RE = re.compile(
    r"(>|\btee\b|\bsed\s+(-\w*\s+)*-i|\bperl\s+(-\w*\s+)*-i|\brm\b|\bmv\b|\bcp\b|\brsync\b"
    r"|\bln\b|\btouch\b|\btruncate\b|\bchmod\b|\bchown\b|\bdd\b|\binstall\b|\bunlink\b"
    r"|\bgit\s+(checkout|restore|rm|mv|reset|stash|clean|apply)\b|\bpython3?\b|\bnode\b|\bruby\b)"
)
MESSAGE = (
    "Blocked: .claude/rules/ holds the accounting rules and is read-only for agents. "
    "If a rule needs to change, stop and ask a human to edit it."
)


def is_protected(path: str) -> bool:
    full = os.path.realpath(path if os.path.isabs(path) else os.path.join(PROJECT, path))
    return any(full == p or full.startswith(p + os.sep) for p in PROTECTED)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}

    if tool == "Bash":
        command = args.get("command", "")
        if PROTECTED_RE.search(command) and WRITE_RE.search(command):
            print(MESSAGE, file=sys.stderr)
            return 2
        return 0

    path = args.get("file_path") or args.get("notebook_path") or args.get("path")
    if path and is_protected(path):
        print(MESSAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
