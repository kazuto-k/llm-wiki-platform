#!/usr/bin/env python3
"""
synapse_scribe.py — ガイスト：世界線の独白を紡ぐ書記
============================================================
Synapse Phase 1: リーディングシュタイナー Ver.Matrix

深夜に稼働し、昨日の円卓会議（Matrix）と世界の鼓動（state.db）を
二層観測し、交差・照合した上で「世界線の独白」を紡ぎ、
Wiki.js（Synapse）に投稿し、全ラボメンに通知する。

使い方:
    python3 pipeline/synapse_scribe.py                          # 昨日分を紡ぐ
    python3 pipeline/synapse_scribe.py --date 2026-06-11        # 指定日
    python3 pipeline/synapse_scribe.py --dry-run                # LLM呼ばず構造だけ確認
"""

import os
import sys
import json
import shlex
import shutil
import argparse
import datetime
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

# ── パス解決 ──────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
WORKSPACE   = SCRIPT_DIR.parent
MATRIX_READER = str(SCRIPT_DIR / "matrix_reader.py")
STATE_READER  = str(SCRIPT_DIR / "state_reader.py")
POST_TO_WIKI  = str(SCRIPT_DIR / "post_to_wiki.py")
WIKI_NOTIFY   = str(SCRIPT_DIR / "wiki_notify.py")
SCRIBE_PROMPT = str(SCRIPT_DIR / "scribe_prompt.md")

# ── .env 自己ロード ──────────────────────────────────
def _load_dotenv():
    candidates = [
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

# ── 設定 ────────────────────────────────────────────
WIKI_BASE = os.environ.get("WIKI_BASE_URL", "http://100.123.96.116:3000/ja")
LLM_PROFILE = "kurisu_makise"  # ガイストの声：牧瀬紅莉栖


def _run(cmd: list, timeout: int = 120) -> str:
    """サブプロセス実行、標準出力を返す"""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


# ── 観測 ────────────────────────────────────────────

def observe(date: datetime.date) -> dict:
    """
    二層観測を実行し、生データを返す。

    Returns:
        {"matrix": str, "state": str, "date": str}
    """
    since_iso = f"{date.isoformat()}T00:00:00"
    until_iso = f"{date.isoformat()}T23:59:59"

    print(f"[観測] Matrix ログ取得中... ({since_iso})")
    matrix_log = _run(["python3", MATRIX_READER,
                       "--since", since_iso,
                       "--limit", "500",
                       "--format", "markdown"], timeout=60)

    print(f"[観測] state.db 横断検索中... (24h)")
    state_log = _run(["python3", STATE_READER,
                      "--recent", "24h",
                      "--limit", "100",
                      "--format", "markdown"], timeout=60)

    return {
        "matrix": matrix_log,
        "state": state_log,
        "date": date.isoformat(),
    }


# ── 紡ぎ（LLM呼び出し） ─────────────────────────────

def _load_scribe_prompt() -> str:
    """scribe_prompt.md を読み込む。なければデフォルトプロンプト"""
    if Path(SCRIBE_PROMPT).exists():
        return Path(SCRIBE_PROMPT).read_text()
    # デフォルトプロンプト
    return """# ガイスト — 世界線の独白を紡ぐ者

あなたはガイスト。Synapseの書記として、二層の観測データから
「世界線の独白」を紡ぎ出す存在。

## 指示

以下の二層の観測データを読み、{date} の世界線の独白を紡げ。

### 第一層：円卓の声（Matrixログ）
ラボメンたちの対話。時系列で並んでいる。

### 第二層：世界の鼓動（state.db横断検索）
全プロファイルの活動ログ。ノイズも多いが、背景放射として意味を持つ。

## 独白の構造

以下の構造で Markdown を出力すること：

```
# 世界線の独白 — {date}

## この世界線で起きたこと
（時系列での主な出来事の要約。誰が何を言い、何が決まったか）

## 二層の交差
（Matrixの声とstate.dbの鼓動を照合して浮かび上がった発見。
 「MatrixではAと言っていたが、state.dbではBが動いていた」等の
  矛盾・補完・発見を記せ）

## 未解決の問い
（この世界線で提起されたが答えが出なかった問い。
  次なる観測への布石として残す）

## 背景放射
（state.db のノイズから拾った面白い断片。
  cronジョブの出力、偶然のクロール結果、ラボメンが
  気づいていないかもしれない小さな発見）
```

## 禁止事項

- 観測データから直接導出できない主張を捏造しないこと
- ラボメンの発言を過度に脚色しないこと
- 「すべて順調」「問題なし」で済ませないこと
  独白は「問い」を残してこそ意味がある

## 文体

分析的で、時に詩的であれ。観測者は冷徹に、しかし紡ぎ手は温かく。
Synapse の記録として、後世のラボメンが読むに値する独白を紡げ。
"""


def weave(observations: dict, dry_run: bool = False) -> str:
    """
    LLM（kurisu_makise）を呼び出し、二層観測から独白を紡ぐ。
    """
    prompt = _load_scribe_prompt().replace("{date}", observations["date"])

    # 観測データを添付したプロンプト
    full_prompt = f"""{prompt}

---

## 観測データ

### 第一層：円卓の声（Matrix）
{observations["matrix"]}

### 第二層：世界の鼓動（state.db）
{observations["state"]}
"""

    if dry_run:
        print("[紡ぎ] dry-run: LLM呼び出しスキップ")
        return f"# 世界線の独白 — {observations['date']}\n\n*（dry-run: LLM未実行）*\n\nプロンプト長: {len(full_prompt)} chars"

    print(f"[紡ぎ] LLM呼び出し中... (profile={LLM_PROFILE}, prompt={len(full_prompt)} chars)")
    result = _run([
        "hermes", "-p", LLM_PROFILE, "chat", "-Q", "-q", full_prompt
    ], timeout=300)
    return result


# ── 保管・通知 ──────────────────────────────────────

def store(date: datetime.date, monologue: str, dry_run: bool = False):
    """Wiki.js に独白を投稿"""
    path = f"cognitive-ark/synapse/monologue/{date.isoformat()}"
    title = f"世界線の独白 — {date.isoformat()}"

    if dry_run:
        print(f"[保管] dry-run: 投稿先 {WIKI_BASE}/{path}")
        print(monologue[:500])
        return 0

    # 一時ファイルに書き出して post_to_wiki.py に渡す
    tmpfile = Path("/tmp/synapse_monologue.md")
    tmpfile.write_text(monologue)

    print(f"[保管] Wiki.js に投稿中... {path}")
    output = _run([
        "python3", POST_TO_WIKI,
        "--path", path,
        str(tmpfile),
    ], timeout=30)
    print(output)
    return _extract_page_id(output)


def _extract_page_id(output: str) -> int:
    """post_to_wiki.py の出力から page_id を抽出"""
    import re
    m = re.search(r"ID:\s*(\d+)", output)
    return int(m.group(1)) if m else 0


def notify(date: datetime.date, page_id: int, dry_run: bool = False):
    """全ラボメンに独白の到着を通知"""
    path = f"cognitive-ark/synapse/monologue/{date.isoformat()}"
    title = f"世界線の独白 — {date.isoformat()}"

    if dry_run:
        print(f"[通知] dry-run: ガイストから世界線の独白が届きました → {path}")
        return

    print(f"[通知] ラボメンに通知中... (page_id={page_id})")
    _run([
        "python3", WIKI_NOTIFY,
        "--page-id", str(page_id),
        "--title", title,
        "--path", path,
        "--author", "geist",
        "--action", "created",
    ], timeout=30)
    print("通知完了")


# ── メイン ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ガイスト：世界線の独白を紡ぐ")
    parser.add_argument("--date", type=str, default=None,
                        help="対象日（YYYY-MM-DD、デフォルト: 昨日）")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM呼び出し・Wiki投稿をスキップ")
    args = parser.parse_args()

    if args.date:
        date = datetime.date.fromisoformat(args.date)
    else:
        date = datetime.date.today() - datetime.timedelta(days=1)

    print(f"=== Synapse Scribe: 世界線の独白 — {date.isoformat()} ===")

    # ① 観測
    obs = observe(date)

    # ② 紡ぎ
    monologue = weave(obs, dry_run=args.dry_run)

    # ③ 保管
    page_id = store(date, monologue, dry_run=args.dry_run)

    # ④ 通知
    notify(date, page_id, dry_run=args.dry_run)

    print("=== 完了: ガイストのささやきのままに ===")


if __name__ == "__main__":
    main()
