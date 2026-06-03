---
title: Wiki.js Page Rules（パスベース ACL）検証
date: 2026-06-03
tags: [wiki-js, llm-wiki, acl, page-rules, experiment]
status: completed
---

# Wiki.js Page Rules（パスベース ACL）検証

## 要約

Wiki.js の Page Rules 機能を実機検証し、llm-wiki のパスベース ACL 設計との整合性を確認した。パスベースの許可/拒否は期待通り動作。カスタム frontmatter の直接参照は不可だが、タグベースルールで代替可能。

## 検証環境

- Wiki.js コンテナ: `wikijs-test`（Docker, port 3000）
- 認証: local ストラテジー
- テストグループ: "Test Group - Platform Team" (ID 3)
- テストユーザー: `testuser@llm-wiki.internal` / `test1234`

## ACL モデル

Wiki.js の権限制御は **グループ** 単位で構成される：

1. **グローバル権限** — マスタースイッチ（`read:pages`, `write:pages`, `manage:system` 等）
2. **Page Rules** — 権限の適用範囲を指定（パス / タグ / 正規表現）

Page Rules のマッチタイプ（優先度: 低 → 高）:

| マッチタイプ | GraphQL 値 | 説明 |
|-------------|-----------|------|
| Path Starts With... | `START` | パスが指定文字列で始まる |
| Path Ends With... | `END` | パスが指定文字列で終わる |
| Path Matches Regex... | `REGEX` | 正規表現マッチ |
| Tag Matches... | `TAG` | タグが一致 |
| Path Is Exactly... | `EXACT` | パスが完全一致 |

ルールの優先順位:
- より具体的なパスが優先
- 同じ具体性なら `EXACT` > `TAG` > `REGEX` > `END` > `START`
- 同じ具体性 + 同じマッチタイプなら `DENY` が `ALLOW` を上書き
- デフォルトは拒否（明示的に許可しない限りアクセス不可）

## 検証結果

### 1. パスベース ACL の動作確認

| ルール | Home ページ | entities ページ | 結果 |
|--------|------------|----------------|------|
| `path: ""` (全許可) | ✅ 表示 | ✅ 表示 | 期待通り |
| `path: "entities"` (制限) | ❌ Unauthorized | ✅ 表示 | 期待通り |

**結論: パスベース ACL は llm-wiki のディレクトリ構造と完全互換。** `entities/teams/*` のようなパスプレフィックスでグループごとのアクセス制御が可能。

### 2. カスタム frontmatter の参照可否

**結論: Page Rules はカスタム frontmatter キー（`type`, `entity_type`, `status`）を直接参照できない。** マッチ対象は「パス」と「タグ」のみ。

`status: raw` → `status: curated` の状態遷移はパスを変えないため、ACL への影響はない。これは設計の前提「同一パスで状態だけ変わるファイルの権限は一貫する」を裏付ける。

### 3. タグベースルール（代替手段）

`match: TAG` を使えば frontmatter の `tags` フィールドに基づくルールが可能。例えば：
- `tags: confidential` → deny guests
- `tags: public` → allow all

これは llm-wiki の curator が追加するタグと連携可能。

### 4. 正規表現ルール

`match: REGEX` で柔軟なパスマッチングが可能。例：
- `entities/teams/.*` → 全チームページにマッチ
- `concepts/.*/index` → concept のインデックスページにマッチ

### 5. GraphQL API 経由の設定

Page Rules は GraphQL `groups.update` ミューテーションで設定可能：

```graphql
mutation {
  groups {
    update(
      id: 3
      permissions: ["read:pages", "read:assets"]
      pageRules: [
        {
          id: "entities-rule"
          deny: false
          match: START
          roles: ["read:pages"]
          path: "entities"
          locales: []
        }
      ]
    ) {
      responseResult { succeeded }
    }
  }
}
```

各ルールには一意の `id` が必要。同じ `id` で更新すると置き換えられる。

## 設計への影響

| 設計要素 | 評価 | 詳細 |
|----------|------|------|
| パスベース ACL | ✅ 完全互換 | `entities/teams/*` → Platform Team のみ許可 等が可能 |
| 状態遷移と ACL の一貫性 | ✅ 問題なし | パスが変わらないため `raw` → `curated` で ACL 不変 |
| カスタム frontmatter 連携 | ❌ 直接不可 | `type`, `entity_type` は参照不可。タグで代替 |
| 管理の自動化 | ✅ API 完備 | GraphQL ですべての操作が可能、CI/CD 連携も容易 |
| マルチテナント | ✅ 可能 | グループ + Page Rules の組み合わせでテナント分離 |

## 結論

Wiki.js の Page Rules は llm-wiki の要件を満たす。パスベース ACL は設計と完全互換で、同一パスでの状態遷移（`raw` → `curated`）も ACL の一貫性を保つ。カスタム frontmatter の直接参照不可はタグベースルールで代替可能。

Phase 0.4 の懸念事項「パスベース ACL が期待通り動作するか」→ **解決**。
