#!/usr/bin/env python3
"""merge: lint 通過済みの branch を master にマージする。

Usage:
    python3 merge.py /tmp/llm-wiki-connector --branch connector/entity/platform-team-20260603
"""

import argparse, subprocess, sys, os

REPO_URL = os.path.expanduser("~/projects/llm-wiki-platform/test/wiki-remote.git")

def run(cmd, cwd=None):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"[ERROR] {cmd}\n{result.stderr}")
        sys.exit(1)
    return result.stdout.strip()

def main():
    parser = argparse.ArgumentParser(description="llm-wiki merge")
    parser.add_argument("repo", help="Path to the repository working directory")
    parser.add_argument("--branch", required=True, help="Branch to merge into master")
    args = parser.parse_args()

    repo_path = args.repo
    branch = args.branch

    print(f"[merge] Merging {branch} → master...")

    # Fetch latest
    run("git fetch origin", cwd=repo_path)

    # Checkout master
    run("git checkout master", cwd=repo_path)
    run("git pull origin master", cwd=repo_path)

    # Merge
    run(f"git merge origin/{branch} --no-ff -m '[merge] auto-merge {branch} (lint passed)'", cwd=repo_path)

    # Push
    run("git push origin master", cwd=repo_path)

    # Delete remote branch (optional - keep for audit trail)
    print(f"[merge] Successfully merged {branch} → master")

if __name__ == "__main__":
    main()
