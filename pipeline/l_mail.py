#!/usr/bin/env python3
"""
l-mail — ラボメン向け軽量通知 CLI

未来ガジェット研究所の通知をSQLiteに記録・管理するだお。
Wiki、curator、wiki_watcherなどが書き込み、ラボメンが読みに来る（プル型）。

使い方:
  l-mail list                        # open/assigned な通知一覧
  l-mail list --mine                 # 自分宛の通知
  l-mail list --status assigned      # assigned 一覧
  l-mail list --all                  # 全ステータス
  l-mail show <id>                   # 1件の詳細
  l-mail add <page> <summary>        # 通知を追加（wiki_watcher等から）
  l-mail create --title <title> ...  # 手動通知作成
  l-mail assign <id> [assignee]      # 自分（または指定者）にアサイン
  l-mail ack <id>                    # 既読確認（ack_required 通知用）
  l-mail done <id>                   # 完了マーク
  l-mail unassign <id>               # アサイン解除（open に戻す）

assignees の挙動:
  (未指定)    自分がアサインするなら l-mail assign で取る（現行仕様と同じ）
  all         全員が返答義務あり。各自が l-mail assign <id> <自分> で担当宣言
  noreply     見るだけ。l-mail ack で全員確認済みになったら自動 done
  [dal,kurisu] 指定ラボメンへの依頼。各自が assign で担当宣言
"""

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# DB パス: llm-wiki-platform/data/l_mail.db（環境変数で上書き可）
_DEFAULT_DB = Path(__file__).parent.parent / "data" / "l_mail.db"
DB_PATH = Path(os.environ.get("L_MAIL_DB", str(_DEFAULT_DB)))

# デフォルトのラボメン（呼び出し元プロファイルか環境変数で設定）
DEFAULT_MEMBER = os.environ.get("HERMES_PROFILE", os.environ.get("L_MAIL_MEMBER", "unknown"))

# 既知のラボメン一覧（ack_map の初期化に使う）
ALL_MEMBERS = ["okabe", "dal", "kurisu", "mayuri"]


# ──────────────────────────────────────────
# DB
# ──────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 複数プロファイルからの同時アクセス対応
    _init(conn)
    return conn


def _init(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS notifications (
            id           TEXT PRIMARY KEY,
            source       TEXT NOT NULL,
            page_path    TEXT NOT NULL,
            summary      TEXT NOT NULL,
            detail       TEXT DEFAULT '',
            created_at   TEXT NOT NULL,
            assignee     TEXT DEFAULT NULL,
            assignees    TEXT DEFAULT NULL,
            ack_required INTEGER DEFAULT 0,
            ack_map      TEXT DEFAULT NULL,
            noreply      INTEGER DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'open',
            done_at      TEXT DEFAULT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_status ON notifications(status);
        CREATE INDEX IF NOT EXISTS idx_created ON notifications(created_at DESC);
    """)
    # 旧DBからの移行: カラムが存在しない場合だけ追加
    existing = {row[1] for row in conn.execute("PRAGMA table_info(notifications)")}
    for col, definition in [
        ("assignees",    "TEXT DEFAULT NULL"),
        ("ack_required", "INTEGER DEFAULT 0"),
        ("ack_map",      "TEXT DEFAULT NULL"),
        ("noreply",      "INTEGER DEFAULT 0"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE notifications ADD COLUMN {col} {definition}")
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short(id_: str) -> str:
    """IDの先頭8文字を返す（表示用）。"""
    return id_[:8]


def _parse_assignees(raw: str | None) -> tuple[list[str] | None, bool, bool]:
    """
    assignees 文字列を解析して (members, is_all, is_noreply) を返す。
      "all"         → (ALL_MEMBERS, True, False)
      "noreply"     → (ALL_MEMBERS, False, True)
      "dal,kurisu"  → (["dal","kurisu"], False, False)
      None/""       → (None, False, False)
    """
    if not raw:
        return None, False, False
    raw = raw.strip()
    if raw == "all":
        return list(ALL_MEMBERS), True, False
    if raw == "noreply":
        return list(ALL_MEMBERS), False, True
    members = [m.strip() for m in raw.split(",") if m.strip()]
    return members, False, False


def _build_ack_map(members: list[str]) -> str:
    return json.dumps({m: False for m in members})


def _check_auto_done(conn: sqlite3.Connection, nid: str) -> bool:
    """ack_map が全員 True なら自動 done にする。True を返したら done した。"""
    row = conn.execute(
        "SELECT ack_map, ack_required FROM notifications WHERE id=?", (nid,)
    ).fetchone()
    if not row or not row["ack_required"] or not row["ack_map"]:
        return False
    ack_map = json.loads(row["ack_map"])
    if all(ack_map.values()):
        conn.execute(
            "UPDATE notifications SET status='done', done_at=? WHERE id=?",
            (_now(), nid),
        )
        conn.commit()
        return True
    return False


# ──────────────────────────────────────────
# コマンド実装
# ──────────────────────────────────────────

def cmd_add(args):
    """通知を追加する。wiki_watcher等のスクリプトから呼ぶ。"""
    members, is_all, is_noreply = _parse_assignees(getattr(args, "assignees", None))

    ack_required = 1 if is_noreply else 0
    ack_map = _build_ack_map(members) if (ack_required and members) else None
    assignees_json = json.dumps(members) if members else None

    conn = _connect()
    nid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO notifications
           (id, source, page_path, summary, detail, created_at,
            assignees, ack_required, ack_map, noreply)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (nid, args.source, args.page, args.summary, args.detail or "", _now(),
         assignees_json, ack_required, ack_map, 1 if is_noreply else 0),
    )
    conn.commit()
    conn.close()

    tag = ""
    if is_noreply:
        tag = " [noreply/全員既読待ち]"
    elif is_all:
        tag = " [all/全員返答]"
    elif members:
        tag = f" [{','.join(members)}]"
    print(f"added: {_short(nid)}  [{args.source}] {args.page}{tag}")
    print(f"  {args.summary}")
    return nid


def cmd_create(args):
    """手動で通知を作成する。kanban的な依頼・タスク連絡に使う。"""
    members, is_all, is_noreply = _parse_assignees(getattr(args, "assignees", None))

    ack_required = 1 if is_noreply else 0
    ack_map = _build_ack_map(members) if (ack_required and members) else None
    assignees_json = json.dumps(members) if members else None

    conn = _connect()
    nid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO notifications
           (id, source, page_path, summary, detail, created_at,
            assignees, ack_required, ack_map, noreply)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (nid, DEFAULT_MEMBER, args.page or "", args.title, args.body or "", _now(),
         assignees_json, ack_required, ack_map, 1 if is_noreply else 0),
    )
    conn.commit()
    conn.close()

    tag = ""
    if is_noreply:
        tag = " [noreply/全員既読待ち]"
    elif is_all:
        tag = " [all/全員返答]"
    elif members:
        tag = f" [{','.join(members)}]"
    print(f"created: {_short(nid)}  {args.title}{tag}")
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

    # --mine フィルタ
    if args.mine:
        me = DEFAULT_MEMBER
        def _is_mine(r):
            if not r["assignees"]:
                return False
            members = json.loads(r["assignees"])
            return me in members
        rows = [r for r in rows if _is_mine(r)]

    if not rows:
        print("(通知なし)")
        return

    for r in rows:
        # assignee 表示
        assignee_tag = ""
        if r["assignees"]:
            members = json.loads(r["assignees"])
            if r["noreply"]:
                # ack_map から未確認者を表示
                ack_map = json.loads(r["ack_map"]) if r["ack_map"] else {}
                pending = [m for m, v in ack_map.items() if not v]
                assignee_tag = f" [noreply, 未確認: {','.join(pending) or 'なし'}]"
            else:
                assignee_tag = f" [{','.join(members)}]"
        elif r["assignee"]:
            assignee_tag = f" @{r['assignee']}"

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

    if row["assignees"]:
        members = json.loads(row["assignees"])
        mode = "noreply(全員既読)" if row["noreply"] else "all" if len(members) == len(ALL_MEMBERS) else "指定"
        print(f"assignees: {', '.join(members)}  ({mode})")
    elif row["assignee"]:
        print(f"assignee : {row['assignee']}")
    else:
        print(f"assignee : (未アサイン)")

    if row["ack_map"]:
        ack_map = json.loads(row["ack_map"])
        ack_str = "  ".join(f"{m}:{'✓' if v else '○'}" for m, v in ack_map.items())
        print(f"ack      : {ack_str}")

    print(f"created  : {row['created_at']}")
    if row["done_at"]:
        print(f"done     : {row['done_at']}")


def cmd_assign(args):
    """通知を自分（または指定したアサイニー）にアサインする。"""
    assignee = args.assignee or DEFAULT_MEMBER
    conn = _connect()

    row = conn.execute(
        "SELECT * FROM notifications WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    if not row:
        conn.close()
        print(f"not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    if row["status"] == "done":
        conn.close()
        print(f"skip: {args.id} はすでに done だお", file=sys.stderr)
        sys.exit(1)

    if row["noreply"]:
        conn.close()
        print(f"skip: {args.id} は noreply 通知だお。l-mail ack で確認してくれだお", file=sys.stderr)
        sys.exit(1)

    # assignees が指定されている場合、対象者チェック
    if row["assignees"]:
        members = json.loads(row["assignees"])
        if assignee not in members:
            print(f"warn: {assignee} はこの通知の assignees ({', '.join(members)}) に含まれていないだお")

    conn.execute(
        "UPDATE notifications SET status='assigned', assignee=? WHERE id LIKE ?",
        (assignee, args.id + "%"),
    )
    conn.commit()
    conn.close()
    print(f"assigned: {args.id[:8]} → @{assignee}")


def cmd_ack(args):
    """既読確認をつける（noreply / ack_required 通知用）。全員確認で自動 done。"""
    me = args.member or DEFAULT_MEMBER
    conn = _connect()

    row = conn.execute(
        "SELECT * FROM notifications WHERE id LIKE ?", (args.id + "%",)
    ).fetchone()
    if not row:
        conn.close()
        print(f"not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    if not row["ack_required"]:
        conn.close()
        print(f"skip: {args.id} は ack_required ではないだお。l-mail done を使ってくれだお", file=sys.stderr)
        sys.exit(1)

    ack_map = json.loads(row["ack_map"]) if row["ack_map"] else {}
    if me not in ack_map:
        print(f"warn: {me} は ack_map に含まれていないだお（追加するだお）")
        ack_map[me] = False

    ack_map[me] = True
    nid = row["id"]

    conn.execute(
        "UPDATE notifications SET ack_map=? WHERE id=?",
        (json.dumps(ack_map), nid),
    )
    conn.commit()

    pending = [m for m, v in ack_map.items() if not v]
    if not pending:
        conn.execute(
            "UPDATE notifications SET status='done', done_at=? WHERE id=?",
            (_now(), nid),
        )
        conn.commit()
        conn.close()
        print(f"ack: {_short(nid)} @{me} ✓  → 全員確認済み、自動 done だお")
    else:
        conn.close()
        print(f"ack: {_short(nid)} @{me} ✓  残: {', '.join(pending)}")


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
    p_add.add_argument("--assignees", default=None,
                       help="宛先: all / noreply / dal,kurisu など（カンマ区切り）")

    # create
    p_create = sub.add_parser("create", help="手動通知を作成する（kanban的な依頼・連絡）")
    p_create.add_argument("--title", required=True, help="通知タイトル（1行）")
    p_create.add_argument("--page", default="", help="関連ページパス（省略可）")
    p_create.add_argument("--body", default="", help="詳細本文（省略可）")
    p_create.add_argument("--assignees", default=None,
                          help="宛先: all / noreply / dal,kurisu など")

    # list
    p_list = sub.add_parser("list", help="通知一覧（デフォルト: open + assigned）")
    p_list.add_argument("--status", choices=["open", "assigned", "done"], help="ステータスで絞り込み")
    p_list.add_argument("--all", action="store_true", help="全ステータスを表示")
    p_list.add_argument("--mine", action="store_true", help="自分宛（assigneesに自分が含まれる）のみ表示")
    p_list.add_argument("--limit", type=int, default=20, help="表示件数（デフォルト: 20）")

    # show
    p_show = sub.add_parser("show", help="1件の詳細を表示")
    p_show.add_argument("id", help="通知ID（先頭8文字でも可）")

    # assign
    p_assign = sub.add_parser("assign", help="自分にアサイン")
    p_assign.add_argument("id", help="通知ID（先頭8文字でも可）")
    p_assign.add_argument("assignee", nargs="?", help="アサイニー（省略時は $HERMES_PROFILE）")

    # ack
    p_ack = sub.add_parser("ack", help="既読確認（noreply 通知用）。全員確認で自動 done")
    p_ack.add_argument("id", help="通知ID（先頭8文字でも可）")
    p_ack.add_argument("--member", default=None, help="確認者（省略時は $HERMES_PROFILE）")

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
        "add":      cmd_add,
        "create":   cmd_create,
        "list":     cmd_list,
        "show":     cmd_show,
        "assign":   cmd_assign,
        "ack":      cmd_ack,
        "done":     cmd_done,
        "unassign": cmd_unassign,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
