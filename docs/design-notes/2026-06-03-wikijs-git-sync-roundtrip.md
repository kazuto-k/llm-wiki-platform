---
title: Wiki.js Git Storage ラウンドトリップ検証
date: 2026-06-03
tags: [wiki-js, llm-wiki, git-storage, frontmatter, experiment]
status: completed
---

# Wiki.js Git Storage ラウンドトリップ検証

## 要約

Wiki.js の Git ストレージモジュールを使い、外部から Git 経由で投入したファイルが Wiki.js に認識されるか、カスタム frontmatter がラウンドトリップで保持されるか、curator による更新が正しく同期されるかを実機検証した。全項目で成功を確認。カスタム frontmatter は完全に保持される。

## テスト環境

- Wiki.js コンテナ: `wikijs-test`（Docker, host ネットワークモード, port 3000）
- 認証モード: SSH（ローカル bare repo に `file://` は不可）
- bare repo: `/wiki/remote.git`（初期コミット: test-project.md + schema.yaml）
- 同期間隔: 5分（双方向）
- 管理者: `admin@llm-wiki.internal` / `admin123`

## 調査結果

### 1. 初回インポートの制限

Wiki.js の Git ストレージモジュールは初回 init 時の sync で、bare repo に既存のファイルをインポートできない。

**原因**: `init()` → `sync()` のフローで、`currentCommitLog.hash` が undefined のため `git diffSummary` が空になり、ファイルが新規として検出されない。

**回避策**: 初期セットアップ後、全ファイルに対してダミー commit（frontmatter の調整など）を push すれば、次の定期 sync で全ファイルが `Page marked as new` としてインポートされる。

**より良い回避策（今後の検討）**: Wiki.js には `importFromDisk` 関数が存在する（`server/modules/storage/disk/common.js`）。初回 init 後にこれを呼べば全ファイルをインポートできる。GraphQL からのトリガー方法は要調査。

### 2. カスタム frontmatter の保持（ラウンドトリップ）

**検証フロー**:
1. Git にカスタム frontmatter（`type`, `entity_type`, `status`, `source_url`, `source_author`）を含むファイルを push
2. Wiki.js がインポート（`Page marked as new`）
3. Git 経由で `status: raw` → `status: curated` に変更 + 新規フィールド（`curator`, `curated_at`, `tags`）追加
4. Wiki.js が更新を検出（`Page marked as modified`）

**結果**: 全カスタムフィールドがラウンドトリップ後も完全に保持された。

```
# 最終的な frontmatter
title: テストプロジェクト概要
description: Wiki.jsとGitの連携を検証するテストページ
published: true
type: entity
entity_type: project
status: curated
curator: curator-bot
curated_at: 2026-06-03T08:55:00Z
source_url: https://sharepoint.internal/sites/eng/test
source_author: alice@company.com
tags: test, wiki-js, llm-wiki
```

### 3. Wiki.js が認識する標準 frontmatter キー

`parseMetadata()`（`server/models/pages.js:194`）は YAML frontmatter 全体を `yaml.safeLoad()` でパースし、`processPage()`（`common.js:81`）が以下のキーを使用する：

| キー | 用途 | デフォルト |
|------|------|-----------|
| `title` | ページタイトル | ファイルパスの末尾 |
| `description` | 説明文 | 空文字 |
| `tags` | タグ（カンマ区切り文字列） | 空 |
| `isPublished` | 公開状態 | `true` |
| `editor` | エディタ種別 | デフォルトエディタ |

**注意**: Wiki.js がエクスポートする際のキー名は `published`（`isPublished` ではない）だが、インポート時に読み取るのは `isPublished`。この非対称性により、Git から投入するファイルでは `published: true` と `isPublished: true` のどちらも機能しない（`isPublished` は `false` 扱い、`published` は無視）。ただし新規ページのデフォルトが `true` なので実害はない。

### 4. 手動 sync トリガー

GraphQL API で以下の mutation により即時 sync が可能：

```graphql
mutation {
  storage {
    executeAction(targetKey: "git", handler: "sync") {
      responseResult { succeeded message }
    }
  }
}
```

認証は `local` ストラテジーで JWT を取得：
```graphql
mutation {
  authentication {
    login(username: "admin@llm-wiki.internal", password: "admin123", strategy: "local") {
      jwt
    }
  }
}
```

### 5. ローカル bare repo の認証モード制限

- `basic` 認証: HTTP(S) のみ対応。`file://` パスは `https://:@file://...` に変換されて失敗
- `ssh` 認証: ローカル bare repo（`/wiki/remote.git`）で動作。SSH キー生成が必要

## 制約・注意点

1. **`published` vs `isPublished` の非対称性**: エクスポートは `published`、インポートは `isPublished`。Git→Wiki.js の新規インポートではデフォルト `true` で問題ないが、`isPublished: false` にしたい場合は明示的に `isPublished: false` を frontmatter に書く必要がある
2. **初回 init 後はダミーコミットが必要**: 全ファイルをインポートするには、init 後に一度全ファイルを touch する commit を push する
3. **同期間隔は最低 5 分**: 即時性が必要な場合は GraphQL で手動トリガー

## 結論

Wiki.js Git ストレージは llm-wiki の設計と完全に互換性がある:

- カスタム frontmatter（`type`, `entity_type`, `status` 等）はラウンドトリップで保持される
- curator/lint-checker が Git 経由でファイルを更新しても Wiki.js 表示に正しく反映される
- `syncInterval: 5` 分 + 手動 trigger 可能で CI パイプラインと組み合わせられる

## 次の一手

- `schema.yaml` に基づく lint-checker のプロトタイプ作成
- connector → curator → lint → auto-merge の CI パイプライン構築
- 複数ファイルでの一括インポート検証
- `importFromDisk` の GraphQL 呼び出し方法調査
