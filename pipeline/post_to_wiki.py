#!/usr/bin/env python3
"""
post_to_wiki.py — Wiki.js への投稿・更新ワンライナーCLI
=========================================================
Markdownファイルを渡すだけで Wiki.js に投稿・更新できる。
frontmatter から title / tags / description を自動抽出。

使い方:
  # 新規作成
  python3 pipeline/post_to_wiki.py --path "cognitive-ark/system/my-doc" my_doc.md

  # 既存ページを更新（IDで指定）
  python3 pipeline/post_to_wiki.py --id 44 my_doc.md

  # タイトルを上書き
  python3 pipeline/post_to_wiki.py --path "cognitive-ark/system/my-doc" --title "別タイトル" my_doc.md

  # 標準入力から受け取る
  cat my_doc.md | python3 pipeline/post_to_wiki.py --path "cognitive-ark/system/my-doc" -

  # ページ一覧を表示
  python3 pipeline/post_to_wiki.py --list

作成者: 橋田至（ダル）
"""

import argparse
import os
import sys
import re
from pathlib import Path

# wikijs_api は自分で .env をロードする
sys.path.insert(0, str(Path(__file__).parent))
from wikijs_api import login_wiki, create_page_with_parents, update_page, list_pages, page_exists


# ──────────────────────────────────────────
# frontmatter パーサ（依存ライブラリなし）
# ──────────────────────────────────────────

def parse_frontmatter(text):
    """
    Markdownのfrontmatter（---で囲まれたYAMLブロック）を簡易パースする。
    戻り値: (frontmatter_dict, body_text)
    frontmatterがない場合は ({}, text) を返す。
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_text = text[3:end].strip()
    body = text[end + 4:].strip()

    fm = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        # リスト形式: "tag1, tag2, tag3"
        if key == "tags" and val:
            fm[key] = [t.strip() for t in re.split(r"[,\s]+", val) if t.strip()]
        else:
            fm[key] = val

    return fm, body


def get_title_from_body(body):
    """Markdownの最初の # 見出しからタイトルを抽出する。"""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Wiki.js にMarkdownファイルを投稿・更新する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("file", nargs="?", default="-",
                        help="投稿するMarkdownファイル（省略または - で標準入力）")
    parser.add_argument("--path", "-p",
                        help="Wiki.js上のパス（例: cognitive-ark/system/my-doc）")
    parser.add_argument("--id", "-i", type=int,
                        help="更新対象のページID（指定時は更新モード）")
    parser.add_argument("--title", "-t",
                        help="タイトルを上書き（省略時はfrontmatterまたは#見出しから取得）")
    parser.add_argument("--tags", nargs="+",
                        help="タグを上書き（省略時はfrontmatterから取得）")
    parser.add_argument("--description", "-d",
                        help="説明文を上書き（省略時はfrontmatterから取得）")
    parser.add_argument("--locale", default="ja",
                        help="ロケール（デフォルト: ja）")
    parser.add_argument("--list", "-l", action="store_true",
                        help="ページ一覧を表示して終了")
    parser.add_argument("--dry-run", action="store_true",
                        help="実際には投稿せず、投稿内容を表示するだけ")
    args = parser.parse_args()

    # 認証
    email = os.environ.get("WIKIJS_EMAIL", "admin@llm-wiki.internal")
    password = os.environ.get("WIKIJS_PASSWORD", "admin123")
    jwt = login_wiki(email, password)

    # --list モード
    if args.list:
        pages = list_pages(jwt)
        pages.sort(key=lambda p: p["path"])
        print(f"{'ID':>5}  {'パス':<60}  タイトル")
        print("-" * 100)
        for p in pages:
            print(f"{p['id']:>5}  {p['path']:<60}  {p['title']}")
        print(f"\n合計 {len(pages)} ページ")
        return

    # Markdown 読み込み
    if args.file == "-" or args.file is None:
        content = sys.stdin.read()
    else:
        content = Path(args.file).read_text(encoding="utf-8")

    # frontmatter 解析
    fm, body = parse_frontmatter(content)

    # タイトル決定（優先度: --title > frontmatter > # 見出し > ファイル名）
    title = (
        args.title
        or fm.get("title")
        or get_title_from_body(body)
        or (Path(args.file).stem if args.file and args.file != "-" else "Untitled")
    )

    # タグ決定
    tags = args.tags or fm.get("tags") or ["cognitive-ark"]

    # 説明文決定
    description = args.description or fm.get("description", "")

    # dry-run
    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"タイトル  : {title}")
        print(f"パス      : {args.path or '(--path 未指定)' }")
        print(f"ID        : {args.id or '(新規作成)'}")
        print(f"タグ      : {tags}")
        print(f"説明      : {description}")
        print(f"本文 ({len(body)} 文字):")
        print(body[:300] + ("..." if len(body) > 300 else ""))
        return

    # 更新モード
    if args.id:
        from wikijs_api import WIKIJS_URL
        update_page(jwt, args.id, body, title=title,
                    description=description, tags=tags, locale=args.locale)
        print(f"✅ 更新完了: ID={args.id}  タイトル={title}")
        print(f"   {WIKIJS_URL}/ja/...")
        return

    # 新規作成モード
    if not args.path:
        print("❌ エラー: --path を指定してください（例: --path cognitive-ark/system/my-doc）")
        sys.exit(1)

    from wikijs_api import WIKIJS_URL
    page = create_page_with_parents(
        jwt, args.path, title, body,
        description=description, tags=tags, locale=args.locale,
    )
    print(f"✅ 作成完了: {title}")
    print(f"   {WIKIJS_URL}/ja/{page['path']}")
    print(f"   ID: {page['id']}")


if __name__ == "__main__":
    main()
