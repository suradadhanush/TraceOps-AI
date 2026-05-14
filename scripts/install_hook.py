#!/usr/bin/env python3
"""Install TraceOps AI pre-commit hook into current git repo."""
import os
import shutil
import stat
import subprocess
import sys

HOOK_SOURCE = os.path.join(os.path.dirname(__file__), "pre_commit_hook.py")
HOOK_CONTENT = f"""#!/bin/sh
# TraceOps AI pre-commit hook (auto-installed)
python3 "{os.path.abspath(HOOK_SOURCE)}"
"""


def main():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=True
        )
        git_dir = result.stdout.strip()
    except subprocess.CalledProcessError:
        print("❌ Not a git repository.")
        sys.exit(1)

    hook_path = os.path.join(git_dir, "hooks", "commit-msg")

    # Backup existing hook
    if os.path.exists(hook_path):
        backup = hook_path + ".bak"
        shutil.copy2(hook_path, backup)
        print(f"📦 Backed up existing hook to {backup}")

    with open(hook_path, "w") as f:
        f.write(HOOK_CONTENT)

    # Make executable
    st = os.stat(hook_path)
    os.chmod(hook_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print(f"✅ TraceOps commit-msg hook installed at {hook_path}")
    print("   Commits without [TRO-<task_id>] will now be rejected.")


if __name__ == "__main__":
    main()
