#!/usr/bin/env python3
"""curator: branch 上の status: raw ファイルを curated に変換する。

hermes --profile llm-wiki-curator chat --skill llm-wiki-curator を呼び出して変換する。

Usage:
    python3 curator.py /tmp/llm-wiki-work --branch connector/entity/platform-team-20260608
"""

import argparse, subprocess, sys, os, yaml, json, datetime
from pathlib import Path

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_URL = os.path.join(_BASE, "test/wiki-remote.git")
CURATOR_NAME = "curator-bot"
CURATOR_EMAIL = "curator@llm-wiki.internal"
HERMES_PROFILE = "llm-wiki-curator"
HERMES_SKILL = "llm-wiki-curator"


def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        print(f"[ERROR] {cmd}\n{result.stderr}")
        sys.exit(1)
    return result.stdout.strip()


def find_raw_files(repo_path):
    """Find all .md files with status: raw in frontmatter."""
    raw_files = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in (".git", "meta")]
        for f in files:
            if not f.endswith(".md"):
                continue
            fpath = os.path.join(root, f)
            with open(fpath) as fh:
                content = fh.read()
            if not content.startswith("---"):
                continue
            parts = content.split("---", 2)
            if len(parts) < 3:
                continue
            try:
                fm = yaml.safe_load(parts[1])
            except yaml.YAMLError:
                continue
            if fm and fm.get("status") == "raw":
                raw_files.append({
                    "path": os.path.relpath(fpath, repo_path),
                    "full_path": fpath,
                    "frontmatter": fm,
                    "body": parts[2]
                })
    return raw_files


def get_existing_pages(repo_path):
    """Get list of existing page paths for wikilink reference."""
    pages = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in (".git", "meta")]
        for f in files:
            if f.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, f), repo_path)
                pages.append(rel.replace(".md", ""))
    return pages


def curate_file_with_hermes(file_info, repo_path):
    """hermes chat でLLMを呼び出してファイルをcurateする。"""
    existing_pages = get_existing_pages(repo_path)

    prompt_data = {
        "path": file_info["path"],
        "frontmatter": file_info["frontmatter"],
        "body": file_info["body"],
        "existing_pages": existing_pages,
    }
    prompt = json.dumps(prompt_data, ensure_ascii=False)

    print(f"[curator] Calling hermes for: {file_info['path']}")
    result = subprocess.run(
        [
            "hermes",
            "chat",
            "--skill", HERMES_SKILL,
            "-q", prompt,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HERMES_HOME": os.path.expanduser(f"~/.hermes/profiles/{HERMES_PROFILE}")},
    )

    if result.returncode != 0:
        print(f"[ERROR] hermes call failed:\n{result.stderr}")
        return False

    output = result.stdout.strip()

    # hermesの出力からMarkdown部分を抽出
    # ボックス描画文字や装飾行を除去して---で始まる部分を探す
    lines = output.split("\n")
    start_idx = None
    for i, line in enumerate(lines):
        # 制御文字・ボックス描画文字を除去してチェック
        clean = line.strip().replace("\r", "")
        if clean == "---":
            start_idx = i
            break

    if start_idx is not None:
        output = "\n".join(lines[start_idx:])
        # セッション情報などの末尾ゴミを除去
        end_markers = ["hermes --resume", "Session:", "Duration:", "Messages:"]
        end_idx = len(output.split("\n"))
        for j, line in enumerate(output.split("\n")):
            if any(m in line for m in end_markers):
                end_idx = j
                break
        output = "\n".join(output.split("\n")[:end_idx]).strip()

    if not output.startswith("---"):
        print(f"[ERROR] Could not find frontmatter in output:\n{output[:300]}")
        return False

    # ファイルに書き戻す
    with open(file_info["full_path"], "w") as f:
        f.write(output)

    return True


def main():
    parser = argparse.ArgumentParser(description="llm-wiki curator")
    parser.add_argument("repo", help="Path to the repository working directory")
    parser.add_argument("--branch", help="Branch name (for commit message)")
    args = parser.parse_args()

    repo_path = args.repo
    branch = args.branch or "curator/auto"

    # Find raw files
    raw_files = find_raw_files(repo_path)
    if not raw_files:
        print("[curator] No raw files found. Nothing to curate.")
        return

    print(f"[curator] Found {len(raw_files)} raw file(s):")
    for f in raw_files:
        print(f"  - {f['path']}")

    # Curate each file
    curated = 0
    for f_info in raw_files:
        if curate_file_with_hermes(f_info, repo_path):
            curated += 1
            print(f"[curator] Curated: {f_info['path']} (raw → curated)")
        else:
            print(f"[ERROR] Failed to curate: {f_info['path']}")

    if curated > 0:
        run("git add -A", cwd=repo_path)
        run(
            f'git commit -m "[curator] transform {curated} file(s): raw → curated" '
            f'--author="{CURATOR_NAME} <{CURATOR_EMAIL}>"',
            cwd=repo_path,
        )
        run("git push origin HEAD", cwd=repo_path)
        print(f"[curator] Committed and pushed {curated} curated file(s)")
    else:
        print("[curator] No files were curated successfully.")
        sys.exit(1)


if __name__ == "__main__":
    main()
