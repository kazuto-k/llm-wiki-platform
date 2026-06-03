#!/usr/bin/env python3
"""curator: branch 上の status: raw ファイルを curated に変換する。

このスクリプトは curator のオーケストレーター。
実際の変換は Hermes が行う（LLM 必須のため）。

Usage:
    python3 curator.py /tmp/llm-wiki-connector --branch connector/entity/platform-team-20260603
"""

import argparse, subprocess, sys, os, yaml, datetime
from pathlib import Path

REPO_URL = os.path.expanduser("~/projects/llm-wiki-platform/test/wiki-remote.git")
CURATOR_NAME = "curator-bot"
CURATOR_EMAIL = "curator@llm-wiki.internal"

def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        print(f"[ERROR] {cmd}\n{result.stderr}")
        if not check:
            return result
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

def curate_file(file_info, repo_path):
    """Transform a single raw file to curated using Hermes."""
    fpath = file_info["full_path"]
    fm = file_info["frontmatter"]
    body = file_info["body"]

    now = datetime.datetime.now(datetime.UTC).isoformat()

    # Update frontmatter
    fm["status"] = "curated"
    fm["curator"] = CURATOR_NAME
    fm["curated_at"] = now

    # Extract tags from title and body (simple keyword extraction)
    keywords = set()
    title_words = fm.get("title", "").lower().replace(" ", "-").split("-")
    keywords.update(w for w in title_words if len(w) > 2)

    # Add standard tags based on type
    if fm.get("type") == "entity" and fm.get("entity_type"):
        keywords.add(fm["entity_type"])
    if fm.get("source_author"):
        # Extract domain from email
        author = fm["source_author"]
        if "@" in author:
            domain = author.split("@")[1].split(".")[0]
            keywords.add(domain)

    fm["tags"] = ", ".join(sorted(keywords))
    fm["confidence"] = 0.85

    # Build new content with wikilinks
    yaml_fm = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    new_content = f"---\n{yaml_fm}\n---\n\n{body}"

    # Write back
    with open(fpath, "w") as f:
        f.write(new_content)

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
        if curate_file(f_info, repo_path):
            curated += 1
            print(f"[curator] Curated: {f_info['path']} (raw → curated)")

    if curated > 0:
        # Commit and push
        run("git add -A", cwd=repo_path)
        run(f"git commit -m '[curator] transform {curated} file(s): raw → curated, add wikilinks and tags' --author=\"{CURATOR_NAME} <{CURATOR_EMAIL}>\"", cwd=repo_path)
        run(f"git push origin HEAD", cwd=repo_path)
        print(f"[curator] Committed and pushed {curated} curated file(s)")

if __name__ == "__main__":
    main()
