#!/usr/bin/env python3
"""
matrix_reader.py — Matrix ルームの全ログを取得するツール
============================================================
Synapse Phase 1: リーディングシュタイナー Ver.Matrix

円卓会議の全発言（メンション有無関係なく）を取得し、
議事録書記が全文脈を把握するためのツール。

使い方:
    python3 pipeline/matrix_reader.py                          # 直近200件
    python3 pipeline/matrix_reader.py --limit 500              # 500件
    python3 pipeline/matrix_reader.py --since "2026-06-12T00:00:00"  # 指定時刻以降
    python3 pipeline/matrix_reader.py --format json            # JSON出力
    python3 pipeline/matrix_reader.py --format markdown        # Markdown出力（デフォルト）
"""

import os
import sys
import json
import argparse
import datetime
import urllib.request
import urllib.error
from pathlib import Path

# ── .env 自己ロード ──────────────────────────────────────
def _load_dotenv():
    candidates = []
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        candidates.append(Path(hermes_home) / ".env")
    candidates += [
        Path.home() / ".hermes" / "profiles" / "itaru-hashida" / ".env",
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
MATRIX_BASE = os.environ.get("MATRIX_HOMESERVER", "http://127.0.0.1:6167")
MATRIX_TOKEN = os.environ.get("MATRIX_ACCESS_TOKEN", "")
ROOM_ID = os.environ.get(
    "SYNAPSE_ROOM_ID",
    "!91rYdG5X0A_jlB7vqgymeDAKkFrK583LtnyleNigQBg"
)

# ── Matrix API ──────────────────────────────────────────

def _matrix_get(path: str) -> dict:
    """Matrix API に GET リクエスト"""
    url = MATRIX_BASE + path
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {MATRIX_TOKEN}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def read_room_history(room_id: str = None, limit: int = 200,
                      since_ts: str = None, direction: str = "b") -> list:
    """
    指定ルームのメッセージ履歴を取得する。

    Args:
        room_id: ルームID（デフォルト: 円卓会議）
        limit: 取得上限数
        since_ts: ISO形式のタイムスタンプ（この時刻以降のみ）
        direction: "b"（新しい順）または "f"（古い順）

    Returns:
        [{sender, body, timestamp, event_id, msgtype}, ...]
    """
    if room_id is None:
        room_id = ROOM_ID

    params = {
        "dir": direction,
        "limit": str(min(limit, 500)),
    }

    qs = "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in params.items())
    path = f"/_matrix/client/v3/rooms/{room_id}/messages?{qs}"

    data = _matrix_get(path)

    messages = []
    for ev in data.get("chunk", []):
        if ev.get("type") != "m.room.message":
            continue
        content = ev.get("content", {})
        body = content.get("body", "").strip()
        if not body:
            continue

        sender = ev.get("sender", "").replace(":localhost", "")
        ts_ms = ev.get("origin_server_ts", 0)
        dt = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.timezone.utc)

        messages.append({
            "sender": sender,
            "body": body,
            "timestamp": dt.isoformat(),
            "event_id": ev.get("event_id", ""),
            "msgtype": content.get("msgtype", "m.text"),
        })

    # since フィルタ（パラメータ版が効かない場合のフォールバック）
    if since_ts:
        try:
            cutoff = datetime.datetime.fromisoformat(since_ts)
            messages = [m for m in messages
                        if datetime.datetime.fromisoformat(m["timestamp"]) >= cutoff]
        except (ValueError, TypeError):
            pass

    return messages


# ── フォーマット ────────────────────────────────────────

def _format_markdown(messages: list) -> str:
    """Markdown 形式で出力"""
    lines = [
        "# 円卓会議ログ",
        f"取得時刻: {datetime.datetime.now().isoformat()[:19]}",
        f"メッセージ数: {len(messages)}",
        "",
    ]
    prev_sender = None
    for m in messages:
        ts = m["timestamp"]
        # タイムスタンプから読みやすい形式に
        try:
            dt = datetime.datetime.fromisoformat(ts)
            time_str = dt.astimezone().strftime("%m/%d %H:%M")
        except Exception:
            time_str = ts[:16]

        # 発言者
        if m["sender"] != prev_sender:
            lines.append(f"\n### {m['sender']}")
            prev_sender = m["sender"]

        lines.append(f"**[{time_str}]** {m['body']}")

    return "\n".join(lines)


def _format_json(messages: list) -> str:
    """JSON 形式で出力"""
    return json.dumps(messages, indent=2, ensure_ascii=False)


# ── メイン ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Matrix ルームの全ログを取得（Synapse Phase 1）")
    parser.add_argument("--room", type=str, default=None,
                        help="ルームID（デフォルト: 円卓会議）")
    parser.add_argument("--limit", type=int, default=200,
                        help="取得上限数（デフォルト: 200）")
    parser.add_argument("--since", type=str, default=None,
                        help="ISO形式の開始時刻（例: 2026-06-12T00:00:00）")
    parser.add_argument("--format", type=str, default="markdown",
                        choices=["markdown", "json"],
                        help="出力形式（デフォルト: markdown）")
    args = parser.parse_args()

    if not MATRIX_TOKEN:
        print("[ERROR] MATRIX_ACCESS_TOKEN が未設定", file=sys.stderr)
        sys.exit(1)

    try:
        messages = read_room_history(
            room_id=args.room,
            limit=args.limit,
            since_ts=args.since,
        )
    except Exception as e:
        print(f"[ERROR] Matrix API 失敗: {e}", file=sys.stderr)
        sys.exit(1)

    if args.format == "json":
        print(_format_json(messages))
    else:
        print(_format_markdown(messages))


if __name__ == "__main__":
    main()
