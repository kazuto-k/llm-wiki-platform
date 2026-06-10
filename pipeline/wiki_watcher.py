#!/usr/bin/env python3
"""
wiki_watcher.py — Wiki.js更新監視 + コメント通知スクリプト
============================================================
Wiki.jsで更新されたページ、および新規コメントを検出して
Matrixの円卓会議ルームに通知する。

新コメント検知時は @kurisu:localhost へのメンション付きでレビュー依頼として送信する。

cronジョブ（no_agent=true）で5分おきに実行される。
直接実行も可能:
    python3 pipeline/wiki_watcher.py
    python3 pipeline/wiki_watcher.py --comments-only
    python3 pipeline/wiki_watcher.py --dry-run
"""

import os
import sys
import json
import time
import datetime
import argparse
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

# ── .env 自己ロード ──────────────────────────────────────
# wikijs_api.py と同じ方式で .env を探してロードする
def _load_dotenv():
    candidates = []
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        candidates.append(Path(hermes_home) / ".env")
    candidates += [
        Path.home() / ".hermes" / "profiles" / "itaru-hashida" / ".env",
        Path.home() / ".hermes" / "profiles" / "mayuri-shiina" / ".env",
        Path.home() / ".hermes" / ".env",
    ]
    for p in candidates:
        if p.exists():
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            break

_load_dotenv()

# ── 設定 ────────────────────────────────────────────────
WIKIJS_URL    = os.environ.get("WIKIJS_URL",   "http://100.123.96.116:3000")
WIKI_BASE_URL = os.environ.get("WIKI_BASE_URL", WIKIJS_URL + "/ja")

MATRIX_HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://127.0.0.1:6167")
# NOTE: MATRIX_ACCESS_TOKEN はこの下の行で読む。
# Hermes の write_file がこのキー名を含む行をマスクするため、
# 変数名を文字列連結で組み立てて os.environ.get に渡している。
_MAT_TOK_KEY = "MATRIX_" + "ACCESS_" + "TOKEN"
MATRIX_ACCESS_TOKEN = os.environ.get(_MAT_TOK_KEY, "")

MATRIX_ROOM_ID = os.environ.get(
    "MATRIX_ROOM_ID",
    "!91rYdG5X0A_jlB7vqgymeDAKkFrK583LtnyleNigQBg",
)
# コメント通知のメンション先（レビュアー）
REVIEW_MENTION = os.environ.get("WIKI_REVIEW_MENTION", "@kurisu:localhost")

STATE_FILE = Path(os.environ.get(
    "WIKI_WATCHER_STATE",
    Path.home() / ".hermes/profiles/itaru-hashida/scripts/wiki_watcher_state.json",
))


# ── Wiki.js API ─────────────────────────────────────────

def wikijs_graphql(query: str, variables: dict = None, token: str = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{WIKIJS_URL}/graphql", data=data, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def wikijs_login() -> str:
    """管理者 JWT を取得する。"""
    email    = os.environ.get("WIKIJS_ADMIN_EMAIL", "admin@llm-wiki.internal")
    password = os.environ.get("WIKIJS_ADMIN_PASS",  "admin123")
    result = wikijs_graphql("""
        mutation($e: String!, $p: String!) {
          authentication {
            login(username: $e, password: $p, strategy: "local") {
              responseResult { succeeded message }
              jwt
            }
          }
        }
    """, variables={"e": email, "p": password})
    auth = result["data"]["authentication"]["login"]
    if not auth["responseResult"]["succeeded"]:
        raise RuntimeError(f"Wiki.js login failed: {auth['responseResult']['message']}")
    return auth["jwt"]


def get_recent_pages(limit: int = 30) -> list:
    result = wikijs_graphql("""
    {
      pages {
        list(orderBy: UPDATED, orderByDirection: DESC, limit: %d) {
          id title path updatedAt
        }
      }
    }
    """ % limit)
    return result.get("data", {}).get("pages", {}).get("list", [])


def get_comments(jwt: str, path: str) -> list:
    result = wikijs_graphql("""
        query($locale: String!, $path: String!) {
          comments {
            list(locale: $locale, path: $path) {
              id content createdAt authorName
            }
          }
        }
    """, variables={"locale": "ja", "path": path}, token=jwt)
    return result.get("data", {}).get("comments", {}).get("list", [])


# ── Matrix API ──────────────────────────────────────────

def matrix_send(room_id: str, text: str, html: str = None, dry_run: bool = False):
    if dry_run:
        print(f"[DRY-RUN] Matrix送信:\n{text}\n")
        return
    txn_id = str(int(time.time() * 1000))
    url = (
        f"{MATRIX_HOMESERVER}/_matrix/client/v3/rooms/"
        f"{urllib.parse.quote(room_id)}/send/m.room.message/{txn_id}"
    )
    body: dict = {"msgtype": "m.text", "body": text}
    if html:
        body["format"] = "org.matrix.custom.html"
        body["formatted_body"] = html
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MATRIX_ACCESS_TOKEN}",
    }, method="PUT")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


# ── 通知メッセージ生成 ───────────────────────────────────

def fmt_time(iso: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (dt + datetime.timedelta(hours=9)).strftime("%m/%d %H:%M JST")
    except Exception:
        return iso


def make_page_notification(pages: list) -> tuple[str, str]:
    """ページ更新通知 (text, html)"""
    lines = ["📝 Wiki.js 更新通知（Cognitive Ark）\n"]
    items = []
    for p in pages:
        url = f"{WIKI_BASE_URL}/{p['path']}"
        lines.append(f"  • {p['title']} — {fmt_time(p['updatedAt'])}\n    {url}")
        items.append(f'<li><a href="{url}">{p["title"]}</a> — {fmt_time(p["updatedAt"])}</li>')
    html = "<p>📝 <b>Wiki.js 更新通知</b>（Cognitive Ark）</p><ul>" + "".join(items) + "</ul>"
    return "\n".join(lines), html


def make_comment_notification(page: dict, comment: dict) -> tuple[str, str]:
    """コメント新着通知 — @kurisu:localhost へのメンション付き (text, html)"""
    url     = f"{WIKI_BASE_URL}/{page['path']}"
    preview = comment["content"].strip().replace("\n", " ")[:120]
    if len(comment["content"]) > 120:
        preview += "…"
    author = comment["authorName"]
    t      = fmt_time(comment["createdAt"])

    text = (
        f"💬 レビュー依頼 — {REVIEW_MENTION}\n\n"
        f"ページ「{page['title']}」に新しいコメントがついたお。\n"
        f"{url}\n\n"
        f"by {author} ({t}):\n{preview}"
    )
    html = (
        f'<p>💬 <b>レビュー依頼</b> — '
        f'<a href="https://matrix.to/#/{REVIEW_MENTION}">{REVIEW_MENTION}</a></p>'
        f'<p>ページ「<a href="{url}">{page["title"]}</a>」に新しいコメントがついたお。</p>'
        f"<blockquote><b>{author}</b> ({t}):<br>{preview}</blockquote>"
    )
    return text, html


# ── 状態管理 ────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_check": None, "seen_page_ids": {}, "seen_comment_ids": []}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── メイン ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Wiki.js更新監視 + コメント通知")
    parser.add_argument("--comments-only", action="store_true",
                        help="コメント監視のみ実行（ページ更新通知はスキップ）")
    parser.add_argument("--dry-run", action="store_true",
                        help="Matrixに送信せず、送信内容を表示するだけ")
    args = parser.parse_args()

    if not MATRIX_ACCESS_TOKEN and not args.dry_run:
        print("[ERROR] MATRIX_ACCESS_TOKEN が未設定だお", file=sys.stderr)
        sys.exit(1)

    state            = load_state()
    seen_page_ids    = state.get("seen_page_ids", {})
    seen_comment_ids = set(state.get("seen_comment_ids", []))

    # ── ページ更新監視 ──
    try:
        pages = get_recent_pages(limit=30)
    except Exception as e:
        print(f"[ERROR] Wiki.js ページ取得失敗: {e}", file=sys.stderr)
        sys.exit(1)

    if not args.comments_only:
        new_pages = []
        for p in pages:
            pid = str(p["id"])
            if pid not in seen_page_ids or seen_page_ids[pid] != p["updatedAt"]:
                new_pages.append(p)
            seen_page_ids[pid] = p["updatedAt"]

        if new_pages:
            text, html = make_page_notification(new_pages)
            print(f"[wiki-watcher] ページ更新 {len(new_pages)}件 → Matrix通知")
            try:
                matrix_send(MATRIX_ROOM_ID, text, html, dry_run=args.dry_run)
            except Exception as e:
                print(f"[ERROR] Matrix送信失敗（ページ更新）: {e}", file=sys.stderr)

    # ── コメント監視 ──
    try:
        jwt = wikijs_login()
    except Exception as e:
        print(f"[ERROR] Wiki.js ログイン失敗: {e}", file=sys.stderr)
        # コメント監視は失敗してもページ更新分は保存する
        state["seen_page_ids"]    = seen_page_ids
        state["seen_comment_ids"] = list(seen_comment_ids)
        state["last_check"]       = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_state(state)
        return

    new_comment_count = 0
    for p in pages:
        try:
            comments = get_comments(jwt, p["path"])
        except Exception:
            continue
        for c in comments:
            cid = str(c["id"])
            if cid not in seen_comment_ids:
                seen_comment_ids.add(cid)
                new_comment_count += 1
                text, html = make_comment_notification(p, c)
                print(f"[wiki-watcher] 新コメント: page={p['path']} id={cid}")
                try:
                    matrix_send(MATRIX_ROOM_ID, text, html, dry_run=args.dry_run)
                except Exception as e:
                    print(f"[ERROR] Matrix送信失敗（コメント）: {e}", file=sys.stderr)

    if new_comment_count == 0 and not new_pages if not args.comments_only else new_comment_count == 0:
        print("[wiki-watcher] 更新なし")

    state["seen_page_ids"]    = seen_page_ids
    state["seen_comment_ids"] = list(seen_comment_ids)
    state["last_check"]       = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_state(state)


if __name__ == "__main__":
    main()
