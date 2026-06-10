#!/usr/bin/env python3
"""curator: branch 上の status: raw ファイルを curated に変換する。

schema.yaml v2.0 準拠版。
- frontmatter は確定的 Python ロジックで処理（LLM不使用）
- LLM には body のみ渡し、結果を curated_body / system_tags / system_summary として frontmatter に格納
- curation_profile に応じてプロンプトを切り替え
- ユーザーの body（原文）は一切変更しない（modifies_body: false）

Usage:
    python3 curator.py /tmp/llm-wiki-work --branch connector/entity/platform-team-20260608
"""

import argparse, subprocess, sys, os, json, datetime
from pathlib import Path
from io import StringIO

from ruamel.yaml import YAML
from openai import OpenAI

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_URL = os.path.join(_BASE, "test/wiki-remote.git")
CURATOR_NAME  = "curator-bot"
CURATOR_EMAIL = "curator@llm-wiki.internal"
OLLAMA_BASE_URL = "http://100.75.63.85:11434/v1"
OLLAMA_MODEL    = "gemma4:12b"


# ──────────────────────────────────────────
# プロンプトテンプレート（5種）
# body のみを渡す。frontmatter は絶対に出力させない。
# ──────────────────────────────────────────

_PROMPT_BASE = """\
あなたはナレッジベースのキュレーターだ。以下のMarkdown本文に対して指定の処理を行い、\
**結果をJSON形式のみで出力せよ**。説明文・前置き・コードブロック記法は不要。

出力形式（必ずこのJSONのみ）:
{{
  "curated_body": "整形済みMarkdown本文",
  "system_tags": ["タグ1", "タグ2", ...],
  "system_summary": "100字以内の要約"
}}

frontmatterは出力しないこと。JSONのキー以外のテキストは出力しないこと。
"""

PROMPT_TEMPLATES = {
    "auto": _PROMPT_BASE + """
### 処理内容（auto: フルキュレーション）
1. 口語・箇条書きの羅列を技術文書らしく整形
2. 不足している情報は「※未確認」「※要確認」と注記
3. 内容の削除は行わない
4. system_tags: タイトル・本文のキーワードから3〜7個
5. system_summary: 本文の内容を100字以内で要約

本文:
{body}
""",

    "minimal": _PROMPT_BASE + """
### 処理内容（minimal: 誤字脱字・表記ゆれのみ）
1. 誤字脱字を修正する
2. 表記ゆれを統一する（例: 「ウィキ」「wiki」→「Wiki」）
3. 文体・構造は変更しない
4. system_tags: 本文のキーワードから3〜5個
5. system_summary: 本文の内容を100字以内で要約

本文:
{body}
""",

    "restyle": _PROMPT_BASE + """
### 処理内容（restyle: 文体・構造の整理）
1. 文体を技術文書らしく整える（事実・内容の変更は絶対禁止）
2. 見出し構造を整理する
3. 箇条書きの粒度を統一する
4. system_tags: 本文のキーワードから3〜7個
5. system_summary: 本文の内容を100字以内で要約

本文:
{body}
""",

    "verify": _PROMPT_BASE + """
### 処理内容（verify: ファクトチェック）
1. 本文の内容は変更しない（curated_bodyは原文のまま）
2. 事実として怪しい箇所に「⚠ 要確認:」の注記を追加
3. system_tags: 確認済みトピックのタグ3〜5個
4. system_summary: ファクトチェック結果の要約（問題点があれば明記）

本文:
{body}
""",
}

# skip プロファイルは LLM を呼ばない


# ──────────────────────────────────────────
# frontmatter / body 分離パーサ（ruamel.yaml）
# ──────────────────────────────────────────

_yaml = YAML()
_yaml.preserve_quotes = True

def parse_md(content: str) -> tuple[dict, str]:
    """
    Markdownファイルを frontmatter dict と body str に分離する。
    ruamel.yaml を使うことで既存の型・コメントを保持。
    """
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    fm = _yaml.load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return fm, body


def render_md(fm: dict, body: str) -> str:
    """
    frontmatter dict と body str を Markdown 文字列に結合する。
    curated_body のような長文フィールドは literal block scalar（|）で出力。
    """
    buf = StringIO()
    _yaml.dump(fm, buf)
    fm_str = buf.getvalue()
    return f"---\n{fm_str}---\n\n{body}"


# ──────────────────────────────────────────
# frontmatter の確定的処理
# ──────────────────────────────────────────

def process_frontmatter(fm: dict, curation_profile: str, llm_result: dict | None) -> dict:
    """
    frontmatter を確定的ロジックで更新する。LLM は使わない。

    - status: raw → curated（llm_result がある場合）/ skip はそのまま
    - curator / curated_at を注入
    - curated_body / system_tags / system_summary を格納
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    fm["updated_at"] = now

    if "created_at" not in fm:
        fm["created_at"] = now

    if llm_result is not None:
        # curated_body は literal block scalar で保存
        from ruamel.yaml.scalarstring import LiteralScalarString
        fm["status"]         = "curated"
        fm["curator"]        = CURATOR_NAME
        fm["curated_at"]     = now
        fm["curated_body"]   = LiteralScalarString(llm_result.get("curated_body", ""))
        fm["system_tags"]    = llm_result.get("system_tags", [])
        fm["system_summary"] = llm_result.get("system_summary", "")
        # verify プロファイルの confidence はルールベースで計算
        if curation_profile == "verify":
            fm["confidence"] = _calc_confidence(llm_result.get("curated_body", ""))
    else:
        # skip: タイムスタンプのみ更新、status は変えない
        pass

    return fm


def _calc_confidence(body: str) -> float:
    """
    verify プロファイル用: 本文の confidence スコアをルールベースで計算する。
    LLM に数値を出力させない（安定しないため）。
    """
    score = 0.85  # ベーススコア
    # 「⚠ 要確認」の数が多いほど低下
    warn_count = body.count("⚠ 要確認")
    score -= warn_count * 0.05
    # リンク切れマーカーがあれば低下
    score -= body.count("ページ未作成") * 0.03
    return round(max(0.0, min(1.0, score)), 2)


# ──────────────────────────────────────────
# LLM 呼び出し
# ──────────────────────────────────────────

def call_llm(body: str, curation_profile: str) -> dict | None:
    """
    curation_profile に応じたプロンプトで LLM を呼び出し、
    {"curated_body": ..., "system_tags": [...], "system_summary": ...} を返す。
    skip の場合は None を返す（LLM 呼び出しなし）。
    """
    if curation_profile == "skip":
        print(f"[curator] skip profile — LLM呼び出しをスキップ")
        return None

    template = PROMPT_TEMPLATES.get(curation_profile, PROMPT_TEMPLATES["auto"])
    prompt = template.format(body=body)

    print(f"[curator] Calling Ollama ({OLLAMA_MODEL}) profile={curation_profile}")

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    response = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    raw = (response.choices[0].message.content or "").strip()

    # コードブロック除去
    if raw.startswith("```"):
        lines = raw.split("\n")
        start = 1 if lines[0].startswith("```") else 0
        end   = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        raw   = "\n".join(lines[start:end]).strip()

    # JSON パース
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ERROR] LLM output is not valid JSON: {e}\n{raw[:300]}")
        return None

    # 必須キーの確認
    for key in ("curated_body", "system_tags", "system_summary"):
        if key not in result:
            print(f"[WARN] LLM output missing key: {key}")
            result.setdefault(key, "" if key != "system_tags" else [])

    return result


# ──────────────────────────────────────────
# ファイル処理
# ──────────────────────────────────────────

def find_raw_files(repo_path: str) -> list[dict]:
    """status: raw の .md ファイルを列挙する。"""
    raw_files = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in (".git", "meta")]
        for f in files:
            if not f.endswith(".md"):
                continue
            fpath = os.path.join(root, f)
            with open(fpath) as fh:
                content = fh.read()
            fm, body = parse_md(content)
            if fm.get("status") == "raw":
                raw_files.append({
                    "path":      os.path.relpath(fpath, repo_path),
                    "full_path": fpath,
                    "frontmatter": fm,
                    "body":      body,
                    "content":   content,
                })
    return raw_files


def curate_file(file_info: dict) -> bool:
    """1ファイルをキュレーションして上書き保存する。"""
    fm      = file_info["frontmatter"]
    body    = file_info["body"]
    profile = str(fm.get("curation_profile", "auto"))

    # LLM 呼び出し
    llm_result = call_llm(body, profile)

    # frontmatter を確定的に更新
    fm = process_frontmatter(fm, profile, llm_result)

    # body は原文のまま（modifies_body: false）
    new_content = render_md(fm, body)

    with open(file_info["full_path"], "w") as f:
        f.write(new_content)

    return True


# ──────────────────────────────────────────
# Git
# ──────────────────────────────────────────

def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        print(f"[ERROR] {cmd}\n{result.stderr}")
        sys.exit(1)
    return result.stdout.strip()


# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="llm-wiki curator (schema.yaml v2.0)")
    parser.add_argument("repo",     help="作業リポジトリのパス")
    parser.add_argument("--branch", help="ブランチ名（コミットメッセージ用）")
    args = parser.parse_args()

    repo_path = args.repo
    branch    = args.branch or "curator/auto"

    raw_files = find_raw_files(repo_path)
    if not raw_files:
        print("[curator] No raw files found. Nothing to curate.")
        return

    print(f"[curator] Found {len(raw_files)} raw file(s):")
    for f in raw_files:
        profile = f["frontmatter"].get("curation_profile", "auto")
        print(f"  - {f['path']} (profile={profile})")

    curated = 0
    for f_info in raw_files:
        try:
            if curate_file(f_info):
                curated += 1
                print(f"[curator] Done: {f_info['path']}")
        except Exception as e:
            print(f"[ERROR] Failed to curate {f_info['path']}: {e}")

    if curated > 0:
        run("git add -A", cwd=repo_path)
        run(
            f'git commit -m "[curator] curate {curated} file(s) (schema v2.0: body preserved, curated_body added)" '
            f'--author="{CURATOR_NAME} <{CURATOR_EMAIL}>"',
            cwd=repo_path,
        )
        run("git push origin HEAD", cwd=repo_path)
        print(f"[curator] Committed and pushed {curated} file(s)")
    else:
        print("[curator] No files were curated successfully.")
        sys.exit(1)


if __name__ == "__main__":
    main()
