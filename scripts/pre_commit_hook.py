#!/usr/bin/env python3
"""
EAS Git Pre-Commit Hook

Enforces TASK_ID pattern in commit messages.
Install: python scripts/install_hook.py
"""
import re
import subprocess
import sys

TASK_ID_PATTERN = re.compile(r'\[EAS-[a-f0-9\-]{8,}\]', re.IGNORECASE)
BYPASS_FLAG = "--no-eas"  # git commit --no-verify bypasses all hooks


def get_commit_message() -> str:
    try:
        # Read from COMMIT_EDITMSG
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=True
        )
        git_dir = result.stdout.strip()
        with open(f"{git_dir}/COMMIT_EDITMSG", "r") as f:
            return f.read().strip()
    except Exception:
        return ""


def main():
    msg = get_commit_message()

    # Allow merge commits, WIP, and empty messages to pass
    lower = msg.lower()
    if any(lower.startswith(prefix) for prefix in ("merge", "wip", "revert", "fixup!", "squash!")):
        sys.exit(0)

    if not msg:
        sys.exit(0)

    if TASK_ID_PATTERN.search(msg):
        print(f"✅ EAS: TASK_ID found in commit message.")
        sys.exit(0)

    # No TASK_ID found — show helpful error
    print("\n❌ EAS COMMIT REJECTED: Missing TASK_ID\n")
    print("Your commit message:")
    print(f"  {msg[:100]}")
    print("\nRequired format:")
    print("  <message> [EAS-<task-id>]")
    print("\nExample:")
    print("  fix: resolve JWT expiry bug [EAS-abc12345]")
    print("\nGet your active task IDs:")
    print("  curl http://localhost:8000/task/?status=active")
    print("\nTo bypass (not recommended):")
    print("  git commit --no-verify")
    print()
    sys.exit(1)


if __name__ == "__main__":
    main()
