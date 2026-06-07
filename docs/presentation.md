# Cognitive Ark — Against Oblivion.

## Wiki.js + GitOps + LLM による知識循環エンジン

---

# 1. 我々が解決する課題

## 知識の死──3つの病理

> 「夢はなくなったらね、おそらく生きる屍だな」—— 本田宗一郎

組織のWikiは、**書かれた瞬間から腐敗が始まる。**

| 病理 | 現象 | 結果 |
|------|------|------|
| **腐敗（Rot）** | API変更・手順陳腐化・前提消失 | 「このWiki、古すぎて使えない」 |
| **散逸（Scatter）** | タグ不在・リンク切れ・属人分類 | 「情報はあるのに見つからない」 |
| **沈黙（Silence）** | 「どうせ腐るから書かない」心理 | 知識が外在化されず消滅 |

**メンテされないWikiは、知識の墓場である。**

## 根本原因

人間は「書く」ことはできても「メンテ」はできない。これは人類の仕様バグ。既存のConfluenceもSharePointも、この問題を解決できない。移行しても同じ墓場ができるだけ。

---

# 2. Cognitive Ark とは

## Cognitive Ark — 知の箱舟

**Cognitive Ark（コグニティブ・アーク）**は、**Wiki.js** を基盤に **GitOps × LLM** で知識を循環・維持・再生するエンタープライズナレッジ基盤。
ギリシャ神話の記憶の女神 *Mnemosyne* に着想を得た、「知の箱舟」。

## コンポーネント

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Wiki.js    │←──→│   Git Repository │←──→│  LLM Agents     │
│  表示 + ACL  │     │  Source of Truth │     │  編纂レイヤー    │
│  全文検索     │     │  バージョン管理   │     │  自動化パイプライン│
└──────────────┘     └──────────────────┘     └─────────────────┘
  · Page Rules       · entities/              · connector
  · GraphQL API      · concepts/              · curator
  · OIDC/SAML        · comparisons/           · lint-checker
  · PostgreSQL FTS   · meta/schema.yaml       · freshness-checker
```

## 5つのエージェント

| エージェント | 役割 | トリガー | 実装 |
|------------|------|----------|------|
| **connector** | SharePoint/Confluence → `status: raw` で commit | 定期スケジュール | Hermes skill |
| **curator** | `status: raw` → `status: curated` 変換・構造化・wikilink | connector の push | Hermes skill（LLM必須） |
| **lint-checker** | schema検証・重複・wikilink切れチェック | curator の push | **Python スクリプト（LLM不要）** |
| **freshness-checker** | 鮮度評価・更新branch作成 | 日次 | Hermes skill |
| **exporter** | 任意形式への出力（PDF/HTML/PPTX） | 手動 or 定期 | 既存Hermesスキル |

## パイプライン（CI 駆動）

```
connector が branch 作成 → status: raw commit
         │
         ▼
curator が同一 branch 上で status: raw → curated 変換
         │
         ▼
lint-checker が検証
    │            │
  失敗         成功
    │            │
 PRブロック    auto-merge → Wiki.js 反映（5分以内）
 curator再処理  │
                ▼
          source_author に事後通知
          「AIが整理しました。問題あれば直接編集を」
                │
                ▼
          freshness-checker（日次）
          鮮度低下 → 更新 branch → 同フロー
```

---

# 3. 中核設計思想

## 3.1 raw は「場所」ではなく「状態」

**raw ディレクトリは存在しない。** `status: raw` は frontmatter の一時的な値。
connector が最初から正しいパス（`entities/projects/foo.md`）に配置し、curator がその場で内容を改善する。

- ファイルが移動しない → Wiki.js の ACL が一貫
- Git の working tree が作業場 → 外部ステージング領域不要
- 同一ファイル・同一パスで状態だけが遷移

## 3.2 事前レビュー不要・事後通知モデル

**Confluence が死んだのと同じ理由**で、全件事前承認は回らない。

| | 従来モデル | Cognitive Ark |
|---|---|---|
| **レビュー** | 事前（人間が全PRを見る） | **事後通知**（著者に「整理しました」と通知） |
| **公開** | 承認待ち滞留 | **即公開**（lint 通過 = auto-merge） |
| **修正** | レビューアが指摘 | **著者が自分で編集**（curator は上書きしない） |
| **放置** | そのまま腐敗 | **未確認バッジ表示**（1週間後にリマインド） |

## 3.3 AI と人間の境界

```
人間（Creator）               AI（Curator = 司書）
─────────────────────────────────────────────────
· 書く                         · 要約する
· 判断する                     · タグ付けする
· マージする                   · 相互参照を構築する
                               · リンク切れを検出する
                               · PR を投げる（上書きはしない）
```

**AIは人間の文章を「書き換える」のではない。人間の「怠惰」を補填する。**

## 3.4 競合解決

1. curator がページを生成 → `status: curated`
2. 人間が編集 → curator はそのページの更新対象から外れる
3. 人間の編集は Git diff で検出可能（curator-bot 以外の committer）
4. 人間が明示的に「再編成してほしい」と要求した場合のみ curator が再介入

---

# 4. Markdown メタデータ設計

```yaml
---
title: "プロジェクト X アーキテクチャ概要"
type: entity
entity_type: project
status: curated       # raw → curated → stale → verified
source_url: https://confluence.internal/...  # 元文書
source_author: alice@company.com             # 通知先
last_curated: 2026-06-03T14:00:00Z
curated_by: curator-bot
confidence: 0.85
tags: [architecture, microservices]
related: [[entities/teams/platform]], [[concepts/k8s-best-practices]]
---
```

- **来歴追跡**: `source_url` で元文書を参照可能
- **鮮度判断**: `last_curated` と元文書の更新日を比較
- **信頼度**: `confidence` が低いものは人間レビュー推奨
- **著者追跡**: `source_author` を通知先として使用

---

# 5. 鮮度判定

| 状態 | 閾値 | アクション |
|------|------|-----------|
| 🟢 **fresh** | 1ヶ月未満 | なし |
| 🟡 **aging** | 1〜3ヶ月 | freshness-checker が確認 |
| 🟠 **stale** | 3〜6ヶ月 | 更新PRを自動生成 |
| 🔴 **critical** | 6ヶ月以上 | 人間レビュー必須 |
| ⚡ **依存先更新** | 即時 | 要確認フラグ |

シグナル: `last_curated` 経過日数 + 元文書の更新 + wikilink 先の更新 + 人間の確認マーク

---

# 6. 実装戦略

Git イベント駆動の CI パイプライン。Hermes の `chat` コマンドでスキル呼び出し。

```yaml
# .github/workflows/curator.yml
curate:
  steps:
    - run: |
        hermes chat \
          --profile llm-wiki \
          --skill llm-wiki-curator \
          -q "branch 上の status: raw の全ファイルを curated に変換せよ"
```

| レベル | 方式 | 用途 |
|--------|------|------|
| **Lv1 軽量** | `hermes chat` ワンライナー | 単発変換 |
| **Lv2 標準** | スキル + プロファイル分離 | curator/connector 分離運用 |
| **Lv3 本格** | Hermes SDK（Python） | バッチ処理・状態管理 |

---

# 7. 技術スタック

| 層 | 技術 |
|----|------|
| **表示 + ACL** | Wiki.js（Page Rules / OIDC / GraphQL API） |
| **バージョン管理** | Git（bare repo, SSH 双方向同期） |
| **CI/CD** | GitHub Actions / GitLab CI / Gitea Actions |
| **LLM** | DeepSeek V4 Pro（curator）, DeepSeek V4 Flash（connector） |
| **エージェント** | Hermes（chat + skills） |
| **検索** | PostgreSQL FTS / Elasticsearch |

---

# 8. ロードマップ

| Phase | 内容 | ステータス |
|-------|------|-----------|
| **Phase 0** | Wiki.js検証（Git同期・Page Rules・パイプライン連鎖） | ✅ 完了（2026-06-03） |
| **Phase 1** | 基盤構築（Wiki.jsフォーク・リポジトリ構造・CI/CD骨格） | 次 |
| **Phase 2** | エージェント実装（connector・curator・lint-checker） | |
| **Phase 3** | 運用（定期実行・通知・ダッシュボード） | |
| **Phase 4** | エコシステム（外部連携・マルチテナント） | |

---

# 9. 市場の追い風

## 2026年6月3日、OpenAIが「Dreaming V3」を発表。

ChatGPTの記憶アーキテクチャを根底から再設計。**3年・3世代の進化**の集大成：

| 世代 | 時期 | 方式 |
|------|------|------|
| **Saved Memories** | 2024年4月 | 明示的指示でのみ記憶（「〜を覚えて」） |
| **Dreaming V0** | 2025年4月 | バックグラウンドで自動キュレーション開始 |
| **Dreaming V3** | 2026年6月 | 完全なスタンドアロン記憶システム |

Dreaming V3 の中核：
- **Dynamic Synthesis**：全チャット履歴から非同期的に記憶を合成。静的な事実リストではない
- **Auto-Updating Context**：時間依存情報を自動更新（「7月にシンガポールに行く」→「行った」に自動遷移）

OpenAI が掲げる記憶の3つの評価基準：
1. **有用なコンテキストの持ち越し** — 一度話したことを次の会話で活かす
2. **好みと制約の追従** — 「ベジタリアン」と言えば以降ずっとその前提で応答
3. **時間経過に応じた鮮度維持** — 「来週の土曜が誕生日」→ 日曜が来たら更新

これは **「人間はメンテできない、AIが補填すべき」という Cognitive Ark の前提が、世界最大のAI企業によって3年かけて検証・証明された** ことを意味する。

| | OpenAI Dreaming V3 | Cognitive Ark |
|---|---|---|
| **対象** | 個人の記憶 | **組織の集合知** |
| **鮮度** | 時間依存の自動更新 | **5段階鮮度シグナル＋閾値設計** |
| **更新** | 自動合成 | **PR→人間レビュー→マージ** |
| **信頼性** | ブラックボックス | **GitOpsで全変更が追跡可能** |
| **スケール** | 1ユーザー | **複数部署・全社** |

> *「OpenAIは個人の記憶を救う。Cognitive Arkは組織の知識を救う。」*

個人の記憶さえAIのメンテ対象になる時代に、組織の知識を放置することはもはや許されない。**Cognitive Arkの市場は、今まさに証明されつつある。**

---

# 10. Cognitive Ark が目指す世界

> *「知識は書かれた瞬間から腐敗する。ならば、AIが循環させて『生かす』しかない。」*

**Cognitive Ark** は、人類の集合知を「生きる屍」から救う装置である。

- **書くことは墓標を建てることではない** —— AI がメンテするなら、書くことが習慣になる
- **AI は司書であり著者ではない** —— 知識の所有権は常に人間にある
- **事前承認ではなく事後通知** —— レビュー滞留を廃し、著者の ownership を活かす

**Against Oblivion.**  
忘却に抗う、すべての知識のために。

---

> 未来ガジェット研究所  
> 「夢は追えてくんでね」——本田宗一郎の精神を継ぐものとして
