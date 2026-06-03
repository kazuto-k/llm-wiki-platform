# llm-wiki-platform

Wiki.js を基盤に llm-wiki パターンを実装するエンタープライズナレッジ基盤。

## コンセプト

- **Wiki.js = 表示 + ACL 層**（人間向け UI、パスベース権限、全文検索）
- **Git = ソース・オブ・トゥルース**（エージェントの作業場、バージョン管理、PR レビュー）
- **llm-wiki エージェント = 編纂層**（自動構造化、相互参照、鮮度チェック、コネクタ）

## アーキテクチャ

```
Git リポジトリ（llm-wiki schema の Markdown 群）
  ├── entities/*.md
  ├── concepts/*.md
  └── raw/*.md（コネクタの作業ディレクトリ）
      ↓ Git 双方向同期（Deploy Key）
Wiki.js（人間向け UI + ACL + 全文検索）
      ↕ GraphQL API
llm-wiki エージェント（CI lint、自動編纂、鮮度チェック）
```

## 権限モデル

Wiki.js の Page Rules（パスベース ACL）により、ディレクトリ構造 = 権限構造。

- デフォルト全 deny。明示的に Allow したグループのみアクセス可
- パスの特異性順にルール評価（`/entities/private` > `/entities`）
- Markdown frontmatter に権限情報は持たない。権限は Wiki.js 管理画面で一元管理

## リポジトリ

- Wiki.js フォーク: （未作成）
- llm-wiki エージェント: （未作成）
