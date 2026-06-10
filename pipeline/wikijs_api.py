"""
wikijs_api.py — Wiki.js GraphQL API ヘルパー
=============================================
未来ガジェット研究所 Cognitive Ark 用。

使い方:
    from wikijs_api import login_wiki, get_page, create_page, update_page
    from wikijs_api import create_page_with_parents, page_exists, list_pages

作成者: 橋田至（ダル）
作成日: 2026-06-08
"""

import urllib.request
import json
import os
from pathlib import Path


# ──────────────────────────────────────────
# .env 自己ロード（未設定の環境変数のみ補完）
# ──────────────────────────────────────────

def _load_dotenv():
    """
    .env ファイルを探してロードする。
    優先順位:
      1. HERMES_HOME 環境変数が指すディレクトリの .env
      2. ~/.hermes/profiles/itaru-hashida/.env（ダルのデフォルト）
      3. ~/.hermes/.env
    既にセットされている環境変数は上書きしない。
    """
    candidates = []
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        candidates.append(Path(hermes_home) / ".env")
    candidates += [
        Path.home() / ".hermes" / "profiles" / "itaru-hashida" / ".env",
        Path.home() / ".hermes" / "profiles" / "mayuri-shiina" / ".env",
        Path.home() / ".hermes" / ".env",
    ]
    for dotenv_path in candidates:
        if dotenv_path.exists():
            with open(dotenv_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
            break  # 最初に見つかったファイルだけ読む

_load_dotenv()

# デフォルトエンドポイント（環境変数で上書き可能）
WIKIJS_URL = os.environ.get("WIKIJS_URL", "http://100.123.96.116:3000")
GRAPHQL_ENDPOINT = WIKIJS_URL + "/graphql"
DEFAULT_LOCALE = "ja"


# ──────────────────────────────────────────
# 内部ヘルパー
# ──────────────────────────────────────────

def _graphql(query, variables=None, token=None):
    """GraphQLリクエストを送信して結果を返す。エスケープ不要。"""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        GRAPHQL_ENDPOINT, data=data, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    if "errors" in result:
        raise RuntimeError("GraphQL error: %s" % result["errors"])
    return result["data"]


# ──────────────────────────────────────────
# 認証
# ──────────────────────────────────────────

def login_wiki(email, password):
    """ログインしてJWTトークンを返す。"""
    data = _graphql(
        """
        mutation($email: String!, $password: String!) {
          authentication {
            login(username: $email, password: $password, strategy: "local") {
              responseResult { succeeded message }
              jwt
            }
          }
        }
        """,
        variables={"email": email, "password": password},
    )
    result = data["authentication"]["login"]
    if not result["responseResult"]["succeeded"]:
        raise RuntimeError("Login failed: %s" % result["responseResult"]["message"])
    return result["jwt"]


# ──────────────────────────────────────────
# ページ読み取り
# ──────────────────────────────────────────

def list_pages(jwt):
    """全ページの一覧を返す。"""
    data = _graphql(
        "{ pages { list { id path title updatedAt } } }",
        token=jwt,
    )
    return data["pages"]["list"]


def get_page(jwt, page_id):
    """IDでページを取得する。"""
    data = _graphql(
        """
        query($id: Int!) {
          pages { single(id: $id) { id path title content updatedAt extra curationProfile } }
        }
        """,
        variables={"id": page_id},
        token=jwt,
    )
    return data["pages"]["single"]


def page_exists(jwt, path, locale=None):
    """指定パスのページが存在すればTrue、なければFalseを返す。"""
    locale = locale or DEFAULT_LOCALE
    pages = list_pages(jwt)
    for p in pages:
        if p["path"] == path:
            return True
    return False


# ──────────────────────────────────────────
# ページ作成・更新
# ──────────────────────────────────────────

def create_page(jwt, path, title, content, description="", tags=None, locale=None):
    """ページを作成して作成されたページ情報を返す。"""
    locale = locale or DEFAULT_LOCALE
    tags = tags or ["cognitive-ark"]
    data = _graphql(
        """
        mutation($path: String!, $title: String!, $content: String!, $description: String!, $tags: [String]!, $locale: String!) {
          pages {
            create(
              path: $path
              title: $title
              content: $content
              description: $description
              editor: "markdown"
              isPublished: true
              isPrivate: false
              locale: $locale
              tags: $tags
            ) {
              responseResult { succeeded message }
              page { id path title }
            }
          }
        }
        """,
        variables={
            "path": path,
            "title": title,
            "content": content,
            "description": description,
            "tags": tags,
            "locale": locale,
        },
        token=jwt,
    )
    result = data["pages"]["create"]
    if not result["responseResult"]["succeeded"]:
        raise RuntimeError("create_page failed: %s" % result["responseResult"]["message"])
    return result["page"]


def update_page(jwt, page_id, content, title=None, description="", tags=None, locale=None):
    """ページ内容を更新する。"""
    locale = locale or DEFAULT_LOCALE
    tags = tags or ["cognitive-ark"]

    # titleが省略された場合は既存のtitleを維持
    if title is None:
        existing = get_page(jwt, page_id)
        title = existing["title"]

    data = _graphql(
        """
        mutation($id: Int!, $title: String!, $content: String!, $description: String!, $tags: [String]!, $locale: String!) {
          pages {
            update(
              id: $id
              title: $title
              content: $content
              description: $description
              editor: "markdown"
              isPublished: true
              isPrivate: false
              locale: $locale
              tags: $tags
            ) {
              responseResult { succeeded message }
            }
          }
        }
        """,
        variables={
            "id": page_id,
            "title": title,
            "content": content,
            "description": description,
            "tags": tags,
            "locale": locale,
        },
        token=jwt,
    )
    result = data["pages"]["update"]
    if not result["responseResult"]["succeeded"]:
        raise RuntimeError("update_page failed: %s" % result["responseResult"]["message"])
    return True


# ──────────────────────────────────────────
# Ph1.1: 親ページ自動生成
# ──────────────────────────────────────────

def _make_index_content(path):
    """中間インデックスページの最低限の内容を生成する。"""
    name = path.split("/")[-1]
    parent = "/".join(path.split("/")[:-1])
    lines = ["# %s" % name, ""]
    if parent:
        lines.append("← [上へ](/ja/%s)" % parent)
    return "\n".join(lines)


def create_page_with_parents(jwt, path, title, content, description="", tags=None, locale=None):
    """
    ページを作成する。途中の親パスが存在しない場合は自動でインデックスページを作成する。

    例:
        create_page_with_parents(jwt, "cognitive-ark/projects/new-project/overview", "概要", "# 概要")
        → cognitive-ark/projects/new-project が存在しなければ自動作成してから overview を作成
    """
    parts = path.split("/")

    # 親パスを上から順にチェック・作成
    for i in range(1, len(parts)):
        parent_path = "/".join(parts[:i])
        if not page_exists(jwt, parent_path):
            parent_title = parts[i - 1]
            index_content = _make_index_content(parent_path)
            print("  [auto] 親ページ作成: %s" % parent_path)
            create_page(jwt, parent_path, parent_title, index_content, tags=tags or ["cognitive-ark"])

    # 本命ページを作成
    return create_page(jwt, path, title, content, description=description, tags=tags, locale=locale)


# ──────────────────────────────────────────
# コメント
# ──────────────────────────────────────────

def list_comments(jwt, path, locale=None):
    """指定パスのページについたコメント一覧を返す。"""
    locale = locale or DEFAULT_LOCALE
    data = _graphql(
        """
        query($locale: String!, $path: String!) {
          comments {
            list(locale: $locale, path: $path) {
              id content createdAt updatedAt authorName authorEmail
            }
          }
        }
        """,
        variables={"locale": locale, "path": path},
        token=jwt,
    )
    return data["comments"]["list"]


def list_all_recent_comments(jwt, locale=None):
    """全ページの最新コメントを返す（Wiki.js APIが対応している場合）。"""
    locale = locale or DEFAULT_LOCALE
    data = _graphql(
        """
        query($locale: String!) {
          comments {
            list(locale: $locale, path: "") {
              id pageId content createdAt authorName
            }
          }
        }
        """,
        variables={"locale": locale},
        token=jwt,
    )
    return data["comments"]["list"]


# ──────────────────────────────────────────
# 動作確認用
# ──────────────────────────────────────────

if __name__ == "__main__":
    import sys
    email = sys.argv[1] if len(sys.argv) > 1 else "admin@llm-wiki.internal"
    password = sys.argv[2] if len(sys.argv) > 2 else "admin123"

    print("Login as %s ..." % email)
    jwt = login_wiki(email, password)
    print("OK")

    pages = list_pages(jwt)
    print("\n全ページ一覧 (%d件):" % len(pages))
    for p in pages:
        print("  [%d] %s — %s" % (p["id"], p["path"], p["title"]))
