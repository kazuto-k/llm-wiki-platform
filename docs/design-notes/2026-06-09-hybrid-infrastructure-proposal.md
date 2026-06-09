---
type: concept
status: curated
date: 2026-06-09
author: 牧瀬紅莉栖
tags: architecture, infrastructure, hybrid, ollama, linux
curation_profile: auto
ref: [[frontmatter-separation-schema-v2]]
---

# Cognitive Ark ハイブリッド実行構成の提案

## 背景

現在、Cognitive Ark の全コンポーネント（Wiki.js, Matrix, Ollama, curator パイプライン）は
ダルの MacBook Pro（128GB ユニファイドメモリ）上で稼働している。
しかし、MacBook にプチフリーズが散発し、開発・運用の安定性に懸念がある。

一方、牧瀬の Linux ホストは高い安定性を持つが、GPU を搭載しておらず
LLM 推論には不向きである。

## 提案構成: ハイブリッド実行

```
┌── Linux（牧瀬ホスト）────────────┐    ┌── MacBook（ダル）──────────────┐
│                                    │    │                                │
│  curator.py（パイプライン制御）     │    │  Ollama（gemma4:12b 推論のみ）  │
│  frontmatter_processor.py          │    │  Wiki.js（表示/UI）             │
│  lint-checker.py                   │◄───│  Matrix サーバー                │
│  Git 操作 / GitHub 連携            │Tail│  Docker                        │
│  Wiki.js GraphQL API 操作          │scale│                                │
│                                    │    │                                │
└────────────────────────────────────┘    └────────────────────────────────┘
```

- **MacBook → 推論専用**: Ollama の OpenAI 互換 API を Tailscale 経由で Linux から叩く
- **Linux → パイプライン制御**: curator / lint / merge / Git 操作はすべて Linux 側で実行
- **Wiki.js は MacBook に維持**: 既存の表示・UI・Docker 設定を変更しない

## メリット

| 観点 | 効果 |
|---|---|
| **MacBook 負荷軽減** | curator.py のファイル走査・Git 操作・Python プロセスを Linux に移行。VRAM も推論時以外解放可能 |
| **開発の安定性** | プチフリーズ中でも Linux 側で curator 実験・開発を継続可能 |
| **既存環境を壊さない** | Wiki.js / Matrix / Docker は MacBook にそのまま。LLM モデルも移動不要 |
| **実証済み** | 2026-06-08 の curator 実験で Ollama API 直叩き方式は動作確認済み |

## 必要な変更

### curator.py（1行変更）

```python
# 変更前
OLLAMA_URL = "http://localhost:11434/v1"

# 変更後
OLLAMA_URL = "http://100.75.63.85:11434/v1"
```

### MacBook 側: 使わないモデルのアンロード

```bash
# gemma4:12b 以外をアンロードして VRAM 解放
ollama stop gpt-oss:20b
ollama stop qwen3:14b
```

### 新規: frontmatter_processor.py

schema.yaml v2.0 に基づく確定的 frontmatter 処理モジュール。
Linux 上で稼働。ステートマシンによる状態遷移、日付注入、バリデーションを担当。

## 非変更項目

- MacBook の Ollama モデル（gemma4:12b）はそのまま
- Wiki.js / Matrix / Docker の構成変更なし
- Git bare repo は継続して MacBook 上（Wiki.js の Git 同期のため）

## リスク

| リスク | 対策 |
|---|---|
| Tailscale 経由のレイテンシ | curator はリアルタイム処理不要。1-2秒の遅延は許容範囲 |
| MacBook スリープ時に API 不通 | スリープ時は curator 実行をスキップ（またはスリープ抑止） |
| ネットワーク断 | ローカルネットワーク内のため低リスク。フォールバックは不要 |

## 次のステップ

1. ダルのレビュー・承認
2. curator.py の OLLAMA_URL 変更（1行）
3. Linux 側で curator.py の動作確認
4. MacBook の未使用モデルアンロード
5. 安定稼働確認（1週間）

---

**提案: 牧瀬紅莉栖**
**日付: 2026-06-09**
