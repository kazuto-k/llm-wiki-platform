#!/usr/bin/env python3
"""
state_reader.py — 全世界線の state.db を横断観測するツール
============================================================
Synapse Phase 1: リーディングシュタイナー Ver.Matrix — 世界観測層

全ラボメン＋パーソナルエージェントの state.db を横断検索し、
「ラボ全体の鼓動」を観測する。

使い方:
    python3 pipeline/state_reader.py --query "Synapse 命名"
    python3 pipeline/state_reader.py --recent 3h          # 直近3時間
    python3 pipeline/state_reader.py --since "2026-06-12T00:00:00"
    python3 pipeline/state_reader.py --profile dal --limit 20
"""

import os
import sys
import json
import sqlite3
import argparse
import datetime
from pathlib import Path

PROFILES_DIR = Path.home() / ".hermes" / "profiles"

# 観測対象のプロファイル
LAB_MEMBERS = ["itaru-hashida", "mayuri-shiina", "kurisu_makise", "hououin-kyouma"]
# パーソナルエージェント（必要に応じて追加）
PERSONAL_AGENTS = ["default"]

ALL_PROFILES = LAB_MEMBERS + PERSONAL_AGENTS


def _parse_dt(s: str):
    """ISOタイムスタンプ文字列をパース"""
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def _fmt_dt(dt):
    """datetime → 読みやすい文字列"""
    return dt.strftime("%m/%d %H:%M") if dt else "?"


def _human_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}分"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}時間{mins}分" if mins else f"{hours}時間"


def read_sessions(profile: str, since: datetime.datetime = None,
                  limit: int = 50) -> list:
    """指定プロファイルのセッション一覧を取得"""
    db_path = PROFILES_DIR / profile / "state.db"
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = """
        SELECT id, title, source, started_at, message_count
        FROM sessions
    """
    params = []

    if since:
        query += " WHERE started_at >= ?"
        params.append(since.timestamp())

    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for r in rows:
        dt = datetime.datetime.fromtimestamp(r["started_at"], tz=datetime.timezone.utc)
        results.append({
            "profile": profile,
            "session_id": r["id"],
            "title": r["title"] or "(無題)",
            "source": r["source"],
            "started_at": dt.isoformat(),
            "message_count": r["message_count"],
        })

    return results


def search_all(query: str, profiles: list = None, limit: int = 20) -> list:
    """全プロファイルの state.db を FTS5 検索"""
    if profiles is None:
        profiles = ALL_PROFILES

    results = []
    for p in profiles:
        db_path = PROFILES_DIR / p / "state.db"
        if not db_path.exists():
            continue

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # FTS5 全文検索（messages_fts 仮想テーブル経由）
        try:
            rows = conn.execute("""
                SELECT m.session_id, m.content, m.timestamp, m.role,
                       s.title, s.source
                FROM messages_fts f
                JOIN messages m ON m.id = f.rowid
                JOIN sessions s ON s.id = m.session_id
                WHERE messages_fts MATCH ?
                ORDER BY m.timestamp DESC
                LIMIT ?
            """, (query, limit)).fetchall()
        except sqlite3.OperationalError:
            conn.close()
            continue

        for r in rows:
            dt = datetime.datetime.fromtimestamp(r["timestamp"], tz=datetime.timezone.utc)
            results.append({
                "profile": p,
                "session_id": r["session_id"],
                "title": r["title"] or "(無題)",
                "source": r["source"],
                "role": r["role"],
                "timestamp": dt.isoformat(),
                "content": r["content"][:200],
            })

        conn.close()

    results.sort(key=lambda x: x["timestamp"], reverse=True)
    return results[:limit]


# ── フォーマット ────────────────────────────────────────

def _format_sessions(sessions: list) -> str:
    """セッション一覧を Markdown で"""
    lines = [
        "## プロファイル別セッション一覧",
        f"取得時刻: {datetime.datetime.now().isoformat()[:19]}",
        f"セッション数: {len(sessions)}",
        "",
    ]
    prev_profile = None
    for s in sessions:
        if s["profile"] != prev_profile:
            lines.append(f"### {s['profile']}")
            prev_profile = s["profile"]
        lines.append(
            f"- [{_fmt_dt(datetime.datetime.fromisoformat(s['started_at']))}] "
            f"({s['source']}) {s['title'][:60]} ({s['message_count']}msg)"
        )
    return "\n".join(lines)


def _format_search(results: list) -> str:
    """検索結果を Markdown で"""
    lines = [
        "## 世界線横断検索結果",
        f"取得時刻: {datetime.datetime.now().isoformat()[:19]}",
        f"結果数: {len(results)}",
        "",
    ]
    for r in results:
        lines.append(f"### {r['profile']} [{_fmt_dt(datetime.datetime.fromisoformat(r['timestamp']))}]")
        lines.append(f"- ソース: {r['source']}")
        lines.append(f"- 役割: {r['role']}")
        lines.append(f"- セッション: {r['title'][:60]}")
        lines.append(f"> {r['content'][:200]}")
        lines.append("")
    return "\n".join(lines)


# ── メイン ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="全世界線の state.db を横断観測（Synapse Phase 1）")
    parser.add_argument("--query", type=str, default=None,
                        help="FTS5全文検索キーワード")
    parser.add_argument("--recent", type=str, default=None,
                        help="直近の期間（例: 3h, 1d, 30m）")
    parser.add_argument("--since", type=str, default=None,
                        help="ISO形式の開始時刻")
    parser.add_argument("--profile", type=str, default=None,
                        help="特定プロファイルのみ")
    parser.add_argument("--limit", type=int, default=30,
                        help="取得上限数")
    parser.add_argument("--format", type=str, default="markdown",
                        choices=["markdown", "json"])
    args = parser.parse_args()

    profiles = [args.profile] if args.profile else ALL_PROFILES

    # --query: 全文検索
    if args.query:
        results = search_all(args.query, profiles=profiles, limit=args.limit)
        if args.format == "json":
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print(_format_search(results))
        return

    # --recent / --since: セッション一覧
    since = None
    if args.recent:
        import re
        m = re.match(r"(\d+)([hmd])", args.recent.lower())
        if m:
            val, unit = int(m.group(1)), m.group(2)
            if unit == "h":
                delta = datetime.timedelta(hours=val)
            elif unit == "m":
                delta = datetime.timedelta(minutes=val)
            else:
                delta = datetime.timedelta(days=val)
            since = datetime.datetime.now(tz=datetime.timezone.utc) - delta
    elif args.since:
        since = _parse_dt(args.since)

    all_sessions = []
    for p in profiles:
        all_sessions.extend(read_sessions(p, since=since, limit=args.limit))

    all_sessions.sort(key=lambda x: x["started_at"], reverse=True)

    if args.format == "json":
        print(json.dumps(all_sessions, indent=2, ensure_ascii=False))
    else:
        print(_format_sessions(all_sessions))


if __name__ == "__main__":
    main()
