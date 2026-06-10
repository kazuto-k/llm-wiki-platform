#!/usr/bin/env python3
"""
l-mail — ラボメン向け軽量通知 CLI

未来ガジェット研究所の通知をSQLiteに記録・管理するだお。
Wiki、curator、wiki_watcherなどが書き込み、ラボメンが読みに来る（プル型）。

使い方:
  l-mail list                      # open な通知一覧
  l-mail list --status assigned    # assigned 一覧
  l-mail list --all                # 全ステータス
  l-mail show <id>                 # 1件の詳細
  l-mail add <page> <summary>      # 通知を追加（wiki_watcher等から）
  l-mail assign <id> [assignee]    # 自分（または指定者）にアサイン
  l-mail done <id>                 # 完了マーク
  l-mail unassign <id>             # アサイン解除（open に戻す）
"""

import argparse
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# DB パス: llm-wiki-platform/data/l_mail.db（環境変数で上書き可）
_DEFAULT_DB = Path(__file__).parent.parent / "data" / "l_mail.db"
DB_PATH = Path(os.environ.get("L_MAIL_DB", str(_DEFAULT_DB)))

# デフォルトのアサイニー（呼び出し元プロファイルか環境変数で設定）
DEFAULT_ASSIGNEE = os.environ.get("HERMES_PROFILE", os.environ.get("L_MAIL_ASSIGNEE", "unknown"))


# ──────────────────────────────────────────
# DB
# ──────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    _init(conn)
    return conn


def _init(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS notifications (
            id          TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            page_path   TEXT NOT NULL,
            summary     TEXT NOT NULL,
            detail      TEXT DEFAULT '',
            created_at  TEXT NOT NULL,
            assignee    TEXT DEFAULT NULL,
            status      TEXT NOT NULL DEFAULT 'open',
            done_at     TEXT DEFAULT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_status ON notifications(status);
        CREATE INDEX IF NOT EXISTS idx_created ON notifications(created_at DESC);
    """)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short(id_: str) -> str:
    """IDの先頭8文字を返す（表示用）。"""
    return id_[:8]


# ──────────────────────────────────────────
# コマンド実装
# ──────────────────────────────────────────

def cmd_add(args):
    """通知を追加する。wiki_watcher等のスクリプトから呼ぶ。"""
    conn = _connect()
    nid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO notifications(id, source, page_path, summary, detail, created_at) VALUES(?,?,?,?,?,?)",
        (nid, args.source, args.page, args.summary, args.detail or "", _now()),
    )
    conn.commit()
    conn.close()
    print(f"added: {_short(nid)}  [{args.source}] {args.page}")
    print(f"  {args.summary}")
    return nid


def cmd_list(args):
    """通知一覧を表示する。"""
    conn = _connect()

    if args.all:
        statuses = ("open", "assigned", "done")
    elif args.status:
        statuses = (args.status,)
    else:
        statuses = ("open", "assigned")

    placeholders = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT * FROM notifications WHERE status IN ({placeholders}) ORDER BY created_at DESC LIMIT ?",
        (*statuses, args.limit),
    ).fetchall()
    conn.close()

    if not rows:
        print("(通知なし)")
        return

    for r in rows:
        assignee_tag = f" @{r['assignee']}" if r["assignee"] else ""
        status_icon = {"open": "○", "assigned": "●", "done": "✓"}.get(r["status"], "?")
        ts = r["created_at"][:16].replace("T", " ")
        print(f"{status_icon} {_short(r['id'])}  {ts}{assignee_tag}")
        print(f"  [{r['source']}] {r['page_path']}")
        print(f"  {r['summary']}")
        print()


def cmd_show(args):
    """1件の詳細を表示する。"""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM notifications WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    conn.close()

    if not row:
        print(f"not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    print(f"id       : {row['id']}")
    print(f"status   : {row['status']}")
    print(f"source   : {row['source']}")
    print(f"page     : {row['page_path']}")
    print(f"summary  : {row['summary']}")
    if row["detail"]:
        print(f"detail   :\n{row['detail']}")
    print(f"assignee : {row['assignee'] or '(未アサイン)'}")
    print(f"created  : {row['created_at']}")
    if row["done_at"]:
        print(f"done     : {row['done_at']}")


def cmd_assign(args):
    """通知を自分（または指定したアサイニー）にアサインする。"""
    assignee = args.assignee or DEFAULT_ASSIGNEE
    conn = _connect()
    cur = conn.execute(
        "UPDATE notifications SET status='assigned', assignee=? WHERE id LIKE ? AND status != 'done'",
        (assignee, args.id + "%"),
    )
    conn.commit()

    if cur.rowcount == 0:
        # ID が見つからないか done 済み
        row = conn.execute("SELECT status FROM notifications WHERE id LIKE ?", (args.id + "%",)).fetchone()
        conn.close()
        if row and row["status"] == "done":
            print(f"skip: {args.id} はすでに done だお", file=sys.stderr)
        else:
            print(f"not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    conn.close()
    print(f"assigned: {args.id[:8]} → @{assignee}")


def cmd_done(args):
    """通知を完了マークにする。"""
    conn = _connect()
    cur = conn.execute(
        "UPDATE notifications SET status='done', done_at=? WHERE id LIKE ?",
        (_now(), args.id + "%"),
    )
    conn.commit()

    if cur.rowcount == 0:
        conn.close()
        print(f"not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    conn.close()
    print(f"done: {args.id[:8]}")


def cmd_unassign(args):
    """アサインを解除して open に戻す。"""
    conn = _connect()
    cur = conn.execute(
        "UPDATE notifications SET status='open', assignee=NULL WHERE id LIKE ? AND status='assigned'",
        (args.id + "%",),
    )
    conn.commit()

    if cur.rowcount == 0:
        conn.close()
        print(f"not found or not assigned: {args.id}", file=sys.stderr)
        sys.exit(1)

    conn.close()
    print(f"unassigned: {args.id[:8]} → open")


# ──────────────────────────────────────────
# CLI エントリポイント
# ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="l-mail",
        description="未来ガジェット研究所 軽量通知 CLI",
    )
    parser.add_argument("--db", help="DB パス（デフォルト: data/l_mail.db）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # add
    p_add = sub.add_parser("add", help="通知を追加する")
    p_add.add_argument("page", help="ページパス（例: cognitive-ark/lab/golden-rules）")
    p_add.add_argument("summary", help="1行サマリー")
    p_add.add_argument("--source", default="wiki_watcher", help="通知元（デフォルト: wiki_watcher）")
    p_add.add_argument("--detail", default="", help="詳細テキスト（省略可）")

    # list
    p_list = sub.add_parser("list", help="通知一覧（デフォルト: open + assigned）")
    p_list.add_argument("--status", choices=["open", "assigned", "done"], help="ステータスで絞り込み")
    p_list.add_argument("--all", action="store_true", help="全ステータスを表示")
    p_list.add_argument("--limit", type=int, default=20, help="表示件数（デフォルト: 20）")

    # show
    p_show = sub.add_parser("show", help="1件の詳細を表示")
    p_show.add_argument("id", help="通知ID（先頭8文字でも可）")

    # assign
    p_assign = sub.add_parser("assign", help="自分にアサイン")
    p_assign.add_argument("id", help="通知ID（先頭8文字でも可）")
    p_assign.add_argument("assignee", nargs="?", help="アサイニー（省略時は $HERMES_PROFILE）")

    # done
    p_done = sub.add_parser("done", help="完了マークをつける")
    p_done.add_argument("id", help="通知ID（先頭8文字でも可）")

    # unassign
    p_unassign = sub.add_parser("unassign", help="アサインを解除して open に戻す")
    p_unassign.add_argument("id", help="通知ID（先頭8文字でも可）")

    args = parser.parse_args()

    if args.db:
        global DB_PATH
        DB_PATH = Path(args.db)

    dispatch = {
        "add": cmd_add,
        "list": cmd_list,
        "show": cmd_show,
        "assign": cmd_assign,
        "done": cmd_done,
        "unassign": cmd_unassign,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
