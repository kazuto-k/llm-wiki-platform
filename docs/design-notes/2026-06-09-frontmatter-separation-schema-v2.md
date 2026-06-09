---
type: concept
status: curated
date: 2026-06-09
author: 牧瀬紅莉栖
tags: schema, frontmatter, curator, design, v2.0
curation_profile: auto
---

# Cognitive Ark フロントマター分離設計 — schema.yaml v2.0

## 概要

Cognitive Ark の AI 処理パイプライン（connector → curator → lint → merge）における
frontmatter の扱いを根本的に見直し、**LLM の不確実性から frontmatter を分離する**
設計を策定した。

本ドキュメントは schema.yaml v2.0 の設計意図と各セクションの解説を記す。

## 設計原則

1. **frontmatter は確定的 Python ロジックで処理する** — 状態遷移、日付注入、バリデーションは LLM を経由しない
2. **LLM は本文 (body) の品質向上のみ担当する** — frontmatter の書き換えによるハルシネーション事故を根本防止
3. **Git が SSOT（Single Source of Truth）** — Wiki.js は表示ミラー
4. **「表と裏」の分離** — ユーザーに見せる情報と、システムが蓄積する情報を明確に分ける

## schema.yaml の構造

6 セクションで構成される。

### 1. フィールド定義 (`field_definitions`)

全ドキュメントタイプで利用可能な全フィールドを定義。
各フィールドに `managed_by` 属性を付与し、変更権限を明示する。

| managed_by | 意味 |
|---|---|
| `system` | Python の確定的ロジックのみが変更可能。LLM 絶対不可 |
| `user` | ユーザーの主観的判断に依存。最終決定権はユーザー |
| `llm_assisted` | LLM が提案、Python がバリデーション後に採用 |

### 2. ドキュメントタイプ定義 (`document_types`)

4 種のタイプを定義。各タイプの必須フィールドと任意フィールドを明示。

| タイプ | 必須フィールド |
|---|---|
| `entity` | title, type, entity_type, status |
| `concept` | title, type, status |
| `meeting` | title, type, status, date, meeting_type |
| `comparison` | title, type, status, items |

### 3. 状態遷移ステートマシン (`status_machine`)

7 状態を定義。各遷移のトリガーを明示。

```
raw ─→ curated ─→ lint ─→ merge ─→ protected
 │        │         │        │
 ├→ draft │         │        └→ stale
 └→ stale └→ raw    └→ curated
           └→ stale
```

| 状態 | アイコン | 意味 |
|---|---|---|
| `raw` | 🔴 | 初期保存状態。未キュレーション |
| `draft` | 📝 | 下書き。ユーザーが作業中とマーク |
| `curated` | 🟢 | curator 処理済み。curated_body が裏側に保存済み |
| `lint` | ✅ | lint-checker 検証済み |
| `merge` | 📦 | master ブランチにマージ済み |
| `protected` | 🔒 | 保護済み。変更不可 |
| `stale` | ⏳ | 陳腐化。再キュレーション必要 |

### 4. LLM 境界定義 (`llm_boundary`)

frontmatter と本文の間に明確な境界線を引く。

- **deterministic_fields**（12 フィールド）: Python のみが管理。curated_body, system_tags, system_summary は LLM が出力した内容を Python が frontmatter に書き込む
- **llm_editable_fields**: `body` のみ
- **llm_assisted_fields**: `tags`, `title`（LLM が提案、Python が検証後に採用）

### 5. キュレーションプロファイル (`curation_profiles`)

ユーザーが保存時に選択できる curation の種別。`auto` がデフォルト。

| プロファイル | 内容 | 出力先 |
|---|---|---|
| `auto` | フル curation（現行プロンプト） | curated_body, system_tags, system_summary, tags |
| `skip` | なにもしない | （なし） |
| `minimal` | 誤字脱字・表記ゆれのみ修正 | curated_body, system_tags |
| `restyle` | 文体・構造の整理（事実変更なし） | curated_body, system_tags, system_summary |
| `verify` | ファクトチェック＋リンク切れ検出 | system_tags, system_summary, confidence |

**全プロファイルで `modifies_body: false`** — ユーザーの本文は一切書き換えない。
curation の結果は `curated_body` に裏側保存される。

### 6. 表示ルール (`display`)

Wiki.js 上の表示制御を定義。

- **hidden**（10 フィールド）: ユーザーに表示しない
- **badge**: status をアイコンバッジとして表示
- **chips**: tags, entity_type をタグチップで表示
- **meta_info**: source_author, meeting_type, date 等をサイドバー表示

## 「表と裏」の分離

本設計の核心。ユーザーが `skip` を選んでも、システムは裏側で AI 処理を継続できる。

```
【表】ユーザーに見える領域          【裏】ユーザーから隠蔽される領域
─────────────────────────────    ────────────────────────────────
  title                            status
  tags                             curator / curated_at / confidence
  body（元のまま、不変）            curation_profile
  entity_type（バッジ表示）         created_at / updated_at
                                   curated_body（AI 整理済み本文）
                                   system_tags（AI 自動タグ）
                                   system_summary（AI 要約）
```

この分離により：
- **ユーザー体験を損なわない** — 自分の書いた本文はそのまま
- **システムの知能は落ちない** — 検索・分類・分析は裏側の構造化データを参照
- **非強制の知能補助** — AI は提案するが、ユーザーの表現を上書きしない

## 実装への影響

### curator.py の改修

現行の curator.py は frontmatter と本文を一体で処理している。
v2.0 では以下の分離が必要：

1. **frontmatter_processor.py**（新規）: ステートマシンによる状態遷移、日付注入、バリデーション
2. **curator.py**（改修）: 本文のみを LLM に渡し、結果を `curated_body` に格納
3. **プロンプト切り替え**: `curation_profile` に応じて `llm_prompt` テンプレートを選択

### lint-checker.py の改修

- schema.yaml の `document_types[type].required` を参照するよう修正
- 新フィールド（curated_body, system_tags, system_summary）を許容
- `rstrip("s")` のバグ修正（`removesuffix("s")` に）

## 参考

- 本設計は 2026-06-09 の岡部倫太郎との円卓会議（Matrix）にて策定
- schema.yaml 実体: `meta/schema.yaml`（本リポジトリ）
- curator プロンプト設計: `docs/curator-prompt-design.md`
- 初回 curator 実験: `docs/meeting-minutes/2026-06-08-curator-experiment.md`

---

**策定: 牧瀬紅莉栖**
**日付: 2026-06-09**
**バージョン: schema.yaml v2.0**
