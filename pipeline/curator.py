#!/usr/bin/env python3
"""curator: branch 上の status: raw ファイルを curated に変換する。

Ollama の OpenAI 互換エンドポイントを直接 Python から呼び出して変換する。

Usage:
    python3 curator.py /tmp/llm-wiki-work --branch connector/entity/platform-team-20260608
"""

import argparse, subprocess, sys, os, yaml, json, datetime
from pathlib import Path
from openai import OpenAI

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_URL = os.path.join(_BASE, "test/wiki-remote.git")
CURATOR_NAME = "curator-bot"
CURATOR_EMAIL = "curator@llm-wiki.internal"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "gemma4:12b"

# llm-wiki-curator スキルのプロンプト（system prompt として使用）
SYSTEM_PROMPT = """\
以下の処理を行い、**変換後のMarkdown全文**のみを出力せよ。説明文や前置きは不要。

### 1. frontmatterの更新
- `status`: `raw` → `curated`
- `description`: 本文から100字以内で要約して設定
- `tags`: タイトル・本文のキーワードからカンマ区切りで設定（3〜7個）
- `curator`: `curator-bot`
- `curated_at`: 現在日時（ISO8601）
- `confidence`: 変換品質の自己評価（0.0〜1.0）

### 2. 本文の整形
- 口語・箇条書きの羅列を技術文書らしく整形
- 不足している情報は「※未確認」「※要確認」と注記
- 内容の削除は行わない（削除理由を注記する）
- Markdown の見出し（#/##/###）・太字（**）・水平線（---）は維持すること

### 3. wikilinkの付与
- 既存ページ（`existing_pages`として渡される）への参照は `[[ページパス|表示名]]` 形式でリンク
- 未作成ページへの参照は `⚠ [[ページ名]]（ページ未作成）` と注記

## 出力形式

必ず以下の形式で出力すること：

```
---
title: ...
type: ...
status: curated
description: ...
tags: ...
curator: curator-bot
curated_at: ...
confidence: ...
---

# タイトル

本文...
```

**frontmatterと本文のみ。説明・前置き・後書き一切不要。出力の先頭は必ず `---` から始めること。**
"""


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


def curate_file_with_ollama(file_info, repo_path):
    """Ollama OpenAI互換エンドポイントを直接呼び出してファイルをcurateする。"""
    existing_pages = get_existing_pages(repo_path)

    # ユーザーメッセージ：frontmatter + body + existing_pages を渡す
    # frontmatterのdateなどをJSONシリアライズ可能な形式に変換
    import datetime as _dt
    def _json_safe(obj):
        if isinstance(obj, (_dt.date, _dt.datetime)):
            return obj.isoformat()
        return str(obj)

    user_message = json.dumps({
        "path": file_info["path"],
        "frontmatter": file_info["frontmatter"],
        "body": file_info["body"],
        "existing_pages": existing_pages,
    }, ensure_ascii=False, indent=2, default=_json_safe)

    print(f"[curator] Calling Ollama ({OLLAMA_MODEL}) for: {file_info['path']}")

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    response = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
    )

    output = response.choices[0].message.content.strip()

    # コードブロックで囲まれている場合は除去
    if output.startswith("```"):
        lines = output.split("\n")
        # 先頭の ``` 行と末尾の ``` 行を除去
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        output = "\n".join(lines[start:end]).strip()

    if not output.startswith("---"):
        print(f"[ERROR] LLM output does not start with '---':\n{output[:300]}")
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
        if curate_file_with_ollama(f_info, repo_path):
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
