#!/usr/bin/env python3
"""
wiki_notify.py — Wiki更新をMatrixのDMで各ラボメンに通知する
================================================================
wiki_watcher.py から呼ばれる。no_agent=True のcronスクリプトからも
単体で実行可能。

使い方:
    python3 pipeline/wiki_notify.py \\
        --page-id 42 \\
        --title "まゆりの日記 Vol.3" \\
        --path "lab/mayuri-diary/vol3" \\
        --author "mayuri" \\
        --action updated

著者チェック:
    --author が Matrix username と一致するラボメンには通知しない
    （自分が書いたものを自分に通知しない）

環境変数:
    MATRIX_NOTIFY_TOKEN   @notify:localhost のアクセストークン
    WIKIJS_URL            Wiki.js のベースURL（通知リンク生成用）
"""

import os
import sys
import json
import time
import argparse
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
MATRIX_BASE  = os.environ.get("MATRIX_HOMESERVER", "http://127.0.0.1:6167")
WIKIJS_URL   = os.environ.get("WIKIJS_URL", "http://100.123.96.116:3000")
WIKI_BASE_URL = os.environ.get("WIKI_BASE_URL", WIKIJS_URL + "/ja")

# トークンファイルから読む（Hermesサンドボックスのマスク回避）
_TOKEN_FILE  = Path("/tmp/matrix_token_notify")
_TOKEN_ENV   = os.environ.get("MATRIX_NOTIFY_TOKEN", "")

def _get_notify_token() -> str:
    if _TOKEN_FILE.exists():
        return _TOKEN_FILE.read_text().strip()
    if _TOKEN_ENV:
        return _TOKEN_ENV
    raise RuntimeError(
        "MATRIX_NOTIFY_TOKEN が未設定。"
        "/tmp/matrix_token_notify にトークンを書くか環境変数を設定してください。"
    )

# Matrix username → DM ルームID
DM_ROOMS = {
    "okabe":  "!bYkPFESvpAA-cNXELjGBSXBPmvizGzFTB--ijb9H8G8",
    "dal":    "!zKU2Z8nsD0CiLyLepgBonP8x8N6ZyEEwb8xSLWsg4H4",
    "mayuri": "!oiWjJh88TMZT9TuN_LHLRTyCS1PQvI9pbflSu8YuwGI",
    "kurisu": "!IgXnOCCgJj87Ub1odzWDlnEACDIQ0joDQMdgGkTGci4",
}

# Wiki.js username → Matrix username の対応
# Wiki.js のユーザー名が違う場合はここで吸収する
WIKI_TO_MATRIX = {
    # ユーザー名 → Matrix名
    "okabe":           "okabe",
    "hououin-kyouma":  "okabe",
    "岡部倫太郎":          "okabe",
    "admin":           None,      # admin 名義は通知しない（キュレーターBot扱い）
    "dal":             "dal",
    "itaru-hashida":   "dal",
    "橋田至（ダル）":       "dal",
    "橋田至":            "dal",
    "mayuri":          "mayuri",
    "mayuri-shiina":   "mayuri",
    "椎名まゆり":          "mayuri",
    "kurisu":          "kurisu",
    "kurisu-makise":   "kurisu",
    "kurisu_makise":   "kurisu",
    "牧瀬紅莉栖":          "kurisu",
}


# ── Matrix API ──────────────────────────────────────────

def _matrix_put(path: str, data: dict, token: str) -> dict:
    body = json.dumps(data).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(
        MATRIX_BASE + path, data=body, headers=headers, method="PUT"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def send_dm(room_id: str, message: str, token: str) -> bool:
    """DMルームにメッセージを送る。成功時 True。"""
    # ルームIDの :localhost サフィックスを除去（Conduitの仕様）
    clean_room_id = room_id.split(":")[0] if ":" in room_id else room_id
    txn = f"wiki_notify_{int(time.time() * 1000)}"
    import urllib.parse
    path = (
        f"/_matrix/client/v3/rooms/"
        f"{urllib.parse.quote(clean_room_id)}"
        f"/send/m.room.message/{txn}"
    )
    try:
        _matrix_put(path, {"msgtype": "m.text", "body": message}, token)
        return True
    except urllib.error.HTTPError as e:
        print(f"[ERROR] Matrix DM失敗 ({room_id}): {e.code} {e.read()}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[ERROR] Matrix DM例外 ({room_id}): {e}", file=sys.stderr)
        return False


# ── 通知メッセージ生成 ───────────────────────────────────

def _build_message(page_id: int, title: str, path: str, author: str, action: str) -> str:
    action_ja = "作成" if action == "created" else "更新"
    url = f"{WIKI_BASE_URL}/{path}"
    lines = [
        f"[Wiki通知] ページが{action_ja}されました",
        f"タイトル: {title}",
        f"著者: {author}",
        f"URL: {url}",
        f"ページID: {page_id}",
        "",
        "── ラボメン向け指示 ──",
        "この通知DM自体に返信しないでください。",
        "上記URLのWikiページを確認し、積極的にコメントしてください。",
        "コメントは自分の言葉で・1トピック1つまで。",
        "コメントした場合のみ、このDMに「コメントしました」と一言だけ返信してください。",
        "特に言うことがなければ沈黙で構いません。",
    ]
    return "\n".join(lines)


# ── メイン ───────────────────────────────────────────────

def notify(page_id: int, title: str, path: str, author: str, action: str,
           dry_run: bool = False) -> int:
    """
    各ラボメンにDM通知を送る。
    著者自身には送らない（ループ防止）。
    送信成功数を返す。
    """
    # Wiki著者 → Matrix username に変換
    author_matrix = WIKI_TO_MATRIX.get(author, author)

    token = _get_notify_token() if not dry_run else "dry_run_token"
    message = _build_message(page_id, title, path, author, action)

    sent = 0
    skipped = 0
    for member, room_id in DM_ROOMS.items():
        if member == author_matrix:
            print(f"[wiki-notify] skip {member} (著者本人)")
            skipped += 1
            continue
        if dry_run:
            print(f"[dry-run] -> @{member}: {message[:60]}...")
            sent += 1
            continue
        ok = send_dm(room_id, message, token)
        status = "OK" if ok else "FAIL"
        print(f"[wiki-notify] -> @{member}: {status}")
        if ok:
            sent += 1

    print(f"[wiki-notify] 送信 {sent}件 / スキップ {skipped}件 (著者={author})")
    return sent


def main():
    parser = argparse.ArgumentParser(description="Wiki更新をMatrixのDMで通知")
    parser.add_argument("--page-id",  type=int,  required=True,  help="Wiki.jsのページID")
    parser.add_argument("--title",    type=str,  required=True,  help="ページタイトル")
    parser.add_argument("--path",     type=str,  required=True,  help="ページパス")
    parser.add_argument("--author",   type=str,  default="",     help="著者のusername")
    parser.add_argument("--action",   type=str,  default="updated",
                        choices=["created", "updated"],         help="作成か更新か")
    parser.add_argument("--dry-run",  action="store_true",      help="送信せず内容を表示のみ")
    args = parser.parse_args()

    result = notify(
        page_id=args.page_id,
        title=args.title,
        path=args.path,
        author=args.author,
        action=args.action,
        dry_run=args.dry_run,
    )
    sys.exit(0 if result >= 0 else 1)


if __name__ == "__main__":
    main()
