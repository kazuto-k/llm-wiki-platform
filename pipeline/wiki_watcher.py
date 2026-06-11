#!/usr/bin/env python3
"""
wiki_watcher.py — Wiki.js 更新監視 + l-mail 書き込み
==========================================================
Wiki.js で更新されたページ・新規コメントを検出して
l_mail.py の SQLite DB に記録する（プル型通知）。

cronジョブ（no_agent=true）で5分おきに実行される。
直接実行も可能:
    python3 pipeline/wiki_watcher.py
    python3 pipeline/wiki_watcher.py --comments-only
    python3 pipeline/wiki_watcher.py --dry-run
"""

import os
import sys
import json
import datetime
import argparse
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

# ── .env 自己ロード ──────────────────────────────────────
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

STATE_FILE = Path(os.environ.get(
    "WIKI_WATCHER_STATE",
    Path.home() / ".hermes/profiles/itaru-hashida/scripts/wiki_watcher_state.json",
))

# l_mail.py / wiki_notify.py のパス（このスクリプトと同ディレクトリ）
_SCRIPT_DIR  = Path(__file__).parent
L_MAIL       = str(_SCRIPT_DIR / "l_mail.py")
WIKI_NOTIFY  = str(_SCRIPT_DIR / "wiki_notify.py")
L_MAIL_DB = os.environ.get(
    "L_MAIL_DB",
    str(Path("/home/kazuto/workspace/llm-wiki-platform/data/l_mail.db")),
)


# ── Wiki.js API ─────────────────────────────────────────

def wikijs_graphql(query: str, variables: dict = None, token: str = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{WIKIJS_URL}/graphql", data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def wikijs_login() -> str:
    email    = os.environ.get("WIKIJS_ADMIN_EMAIL", "admin@llm-wiki.internal")
    password = os.environ.get("WIKIJS_ADMIN_PASSWORD", "")
    data = wikijs_graphql("""
        mutation($email: String!, $password: String!) {
          authentication { login(username: $email, password: $password, strategy: "local") {
            jwt
          }}
        }
    """, {"email": email, "password": password})
    jwt = data["data"]["authentication"]["login"]["jwt"]
    if not jwt:
        raise RuntimeError(f"jwt=Null: {email} でのログイン失敗。WIKIJS_ADMIN_PASSWORD を確認してください")
    return jwt


def get_recent_pages(limit: int = 30) -> list:
    data = wikijs_graphql("""
        query { pages { list(orderBy: UPDATED) {
          id path title updatedAt
        }}}
    """)
    pages = data["data"]["pages"]["list"]
    # Wiki.js は古い順で返すため末尾 limit 件が最新。全件渡して状態管理する
    return pages


def get_comments(jwt: str, path: str) -> list:
    data = wikijs_graphql("""
        query($path: String!) { comments { list(locale: "ja", path: $path) {
          id content authorName createdAt
        }}}
    """, {"path": path}, token=jwt)
    return data["data"]["comments"]["list"]


# ── l-mail 書き込み ──────────────────────────────────

def l_mail_add(page_path: str, summary: str, source: str = "wiki_watcher",
                   detail: str = "", dry_run: bool = False, upsert: bool = False):
    """l_mail.py の add コマンドを呼ぶ。upsert=True のとき同ページの open 通知を上書き。"""
    if dry_run:
        print(f"[dry-run] l-mail add '{page_path}' '{summary}' --source {source}" +
              (" [upsert]" if upsert else ""))
        return
    cmd = [
        sys.executable, L_MAIL,
        "--db", L_MAIL_DB,
        "add", page_path, summary,
        "--source", source,
    ]
    if detail:
        cmd += ["--detail", detail]
    if upsert:
        cmd += ["--upsert"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print(f"[ERROR] l-mail add 失敗: {result.stderr}", file=sys.stderr)
        else:
            print(result.stdout.strip())
    except Exception as e:
        print(f"[ERROR] l-mail add 例外: {e}", file=sys.stderr)


def wiki_notify_send(page_id: int, title: str, path: str, author: str, action: str,
                     dry_run: bool = False):
    """wiki_notify.py を呼んで各ラボメンにMatrix DM通知を送る。"""
    cmd = [
        sys.executable, WIKI_NOTIFY,
        "--page-id", str(page_id),
        "--title",   title,
        "--path",    path,
        "--author",  author,
        "--action",  action,
    ]
    if dry_run:
        cmd.append("--dry-run")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.stdout:
            print(result.stdout.strip())
        if result.returncode != 0:
            print(f"[ERROR] wiki_notify 失敗: {result.stderr}", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] wiki_notify 例外: {e}", file=sys.stderr)


# ── 状態管理 ────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── ユーティリティ ───────────────────────────────────────

def fmt_time(iso: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return iso[:16]


# ── パス別通知ルール ─────────────────────────────────────
# "new_only" : 新規作成のみ通知、更新はスキップ
# "ignore"   : 通知しない
# "upsert"   : 同じページの open 通知を上書き（デフォルト）
PATH_RULES = [
    ("cognitive-ark/round-table/", "upsert"),
    ("cognitive-ark/sandbox/",     "ignore"),
]

def _page_rule(path: str) -> str:
    for prefix, rule in PATH_RULES:
        if path.startswith(prefix):
            return rule
    return "upsert"



def main():
    parser = argparse.ArgumentParser(description="Wiki.js 更新監視 + l-mail 書き込み")
    parser.add_argument("--comments-only", action="store_true",
                        help="コメント監視のみ実行")
    parser.add_argument("--dry-run", action="store_true",
                        help="l-mail に書き込まず内容を表示するだけ")
    args = parser.parse_args()

    state            = load_state()
    seen_page_ids    = state.get("seen_page_ids", {})
    seen_comment_ids = set(state.get("seen_comment_ids", []))

    # ── ページ更新監視 ──
    try:
        pages = get_recent_pages(limit=30)
    except Exception as e:
        print(f"[ERROR] Wiki.js ページ取得失敗: {e}", file=sys.stderr)
        sys.exit(1)

    new_page_count = 0
    if not args.comments_only:
        for p in pages:
            pid  = str(p["id"])
            rule = _page_rule(p["path"])
            is_new = pid not in seen_page_ids
            is_updated = not is_new and seen_page_ids[pid] != p["updatedAt"]

            if rule == "ignore":
                seen_page_ids[pid] = p["updatedAt"]
                continue

            if rule == "new_only" and not is_new:
                seen_page_ids[pid] = p["updatedAt"]
                continue

            if is_new or is_updated:
                new_page_count += 1
                action    = "created" if is_new else "updated"
                summary   = f"ページ{'作成' if is_new else '更新'}: {p['title']} ({fmt_time(p['updatedAt'])})"
                detail    = f"{WIKI_BASE_URL}/{p['path']}"
                author    = p.get("authorName", p.get("creatorName", ""))
                print(f"[wiki-watcher] {summary}")
                l_mail_add(p["path"], summary, source="wiki_watcher",
                           detail=detail, dry_run=args.dry_run,
                           upsert=(rule == "upsert" and is_updated))
                wiki_notify_send(
                    page_id=int(p["id"]),
                    title=p["title"],
                    path=p["path"],
                    author=author,
                    action=action,
                    dry_run=args.dry_run,
                )
            seen_page_ids[pid] = p["updatedAt"]

    # ── コメント監視 ──
    try:
        jwt = wikijs_login()
    except Exception as e:
        print(f"[ERROR] Wiki.js ログイン失敗: {e}", file=sys.stderr)
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
            if not c or c.get("id") is None:
                continue
            cid = str(c["id"])
            if cid not in seen_comment_ids:
                seen_comment_ids.add(cid)
                new_comment_count += 1
                summary = f"新コメント: {p['title']} by {c['authorName']}"
                detail  = (f"{WIKI_BASE_URL}/{p['path']}\n"
                           f"{c['content']}")
                print(f"[wiki-watcher] {summary}")
                l_mail_add(p["path"], summary, source="wiki_watcher_comment",
                               detail=detail, dry_run=args.dry_run)

    if new_page_count == 0 and new_comment_count == 0:
        print("[wiki-watcher] 更新なし")

    state["seen_page_ids"]    = seen_page_ids
    state["seen_comment_ids"] = list(seen_comment_ids)
    state["last_check"]       = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_state(state)


if __name__ == "__main__":
    main()
