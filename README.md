# llm-wiki-platform

Wiki.js を基盤に llm-wiki パターンを実装するエンタープライズナレッジ基盤。

## ステータス

**Phase 0 検証完了（2026-06-03）**

| # | 検証項目 | 結果 |
|---|---------|------|
| 0.1 | Wiki.js ローカルデプロイ + Git 連携 | ✅ |
| 0.2 | Markdown push → Wiki.js 反映（ラウンドトリップ） | ✅ |
| 0.4 | Page Rules（パスベース ACL） | ✅ |
| 0.5 | CI 環境（ローカルパイプライン） | ✅ |
| 0.6 | connector → curator → lint → merge 連鎖 | ✅ |
| 0.3 | OIDC 認証 | 後回し |
| 0.7 | Confluence 実データ | 後回し |

## コンセプト

- **Wiki.js = 表示 + ACL 層**（人間向け UI、パスベース権限、全文検索）
- **Git = ソース・オブ・トゥルース**（エージェントの作業場、バージョン管理）
- **llm-wiki エージェント = 編纂層**（自動構造化、相互参照、鮮度チェック）

`raw` は「場所」ではなく frontmatter の `status: raw` という「状態」。同一ファイル・同一パスで状態だけが遷移する。

## アーキテクチャ

```
Git リポジトリ（llm-wiki Markdown 群）
  ├── entities/*.md       # 人物・組織・プロジェクト・技術
  ├── concepts/*.md       # 概念・ベストプラクティス
  ├── comparisons/*.md    # 比較表・選定資料
  └── meta/schema.yaml    # スキーマ定義
      ↕ Git 双方向同期（SSH, 5分間隔）
Wiki.js（UI + ACL + 全文検索）
      ↕ GraphQL API
CI パイプライン（connector → curator → lint → merge）
```

## 環境構築

### 前提

- Docker
- Python 3.11+
- Git

### Wiki.js の起動

```bash
# bare repo の作成（初回のみ）
mkdir -p test/wiki-remote.git
cd test/wiki-remote.git && git init --bare && cd ../..

# SSH キー生成（初回のみ）
mkdir -p test/ssh-key
ssh-keygen -t rsa -b 4096 -f test/ssh-key/git-ssh -N ""

# Wiki.js コンテナ起動
docker run -d --name wikijs-test \
  --network host \
  -v $(pwd)/test/wikijs-data:/wiki/data \
  -v $(pwd)/test/wiki-remote.git:/wiki/remote.git \
  -v $(pwd)/test/ssh-key:/wiki/data/secure \
  requarks/wiki:2

# アクセス
# http://localhost:3000
# 管理者: admin@llm-wiki.internal / admin123
```

設定ファイルは `test/wikijs-data/config.yml`。`storage.git.authType: ssh` 必須（ローカル bare repo では basic 認証不可）。

### 初回コンテンツ投入

```bash
# bare repo に初期コンテンツを push
TMPDIR=$(mktemp -d)
git clone test/wiki-remote.git $TMPDIR
cp -r test/wiki-content/* $TMPDIR/
cd $TMPDIR
git add -A && git commit -m "initial wiki content" && git push
```

> **注意**: Wiki.js の初回 init では既存ファイルが自動インポートされない。push 後に以下のいずれかを行う:
> - 5分待つ（定期 sync で取り込まれる）
> - 手動トリガー: `python3 pipeline/trigger-sync.py`

### パイプラインの実行

```bash
cd pipeline
./run-pipeline.sh --type entity --entity-type team --title "Platform Team" --author "bob@company.com"
```

フロー: connector（branch 作成 + raw commit）→ curator（raw→curated 変換）→ lint-checker（schema 検証）→ merge（master にマージ）

各スクリプトの詳細は `pipeline/README.md` を参照。

## ページ命名規則

| 種類 | パス | frontmatter |
|------|------|------------|
| 人物 | `entities/people/{name}.md` | `type: entity`, `entity_type: person` |
| チーム | `entities/teams/{name}.md` | `type: entity`, `entity_type: team` |
| プロジェクト | `entities/projects/{name}.md` | `type: entity`, `entity_type: project` |
| 技術 | `entities/technologies/{name}.md` | `type: entity`, `entity_type: technology` |
| 概念 | `concepts/{name}.md` | `type: concept` |
| 比較 | `comparisons/{name}.md` | `type: comparison` |

## 権限モデル

Wiki.js の Page Rules（パスベース ACL）で制御。グループ単位で設定可能。

- マッチタイプ: `Path Starts With`, `Path Ends With`, `Path Matches Regex`, `Tag Matches`, `Path Is Exactly`
- より具体的なパスが優先。DENY は ALLOW を上書き
- デフォルトは全拒否（明示的に許可したもののみアクセス可）
- **カスタム frontmatter（`type`, `entity_type`, `status`）は直接参照不可**。タグベースルールで代替

## 技術的知見

- **カスタム frontmatter はラウンドトリップで保持される**（Wiki.js が未知のキーを無視し、エクスポート時に再出力）
- **`[[wikilink]]` 記法は Wiki.js でリンクにならない**。標準 Markdown `[text](path)` を使用する
- **ローカル bare repo は SSH モード必須**（basic 認証は HTTP(S) のみ）
- **初回 init 時に既存ファイルは自動インポートされない**。ダミー commit で回避

詳細は `docs/design-deep-dive.md` および `docs/design-notes/` を参照。

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| `docs/design-deep-dive.md` | 設計詳細（エージェント、メタデータ、パイプライン、ACL） |
| `docs/architecture.md` | アーキテクチャ概要 |
| `docs/design-notes/2026-06-03-wikijs-git-sync-roundtrip.md` | Wiki.js Git 同期ラウンドトリップ検証 |
| `docs/design-notes/2026-06-03-wikijs-page-rules.md` | Page Rules（ACL）検証 |
| `docs/design-notes/2026-06-03-llm-wiki-pipeline-prototype.md` | CI パイプラインプロトタイプ検証 |
| `pipeline/README.md` | パイプライン各スクリプトの説明 |
| `test/README.md` | テスト環境の詳細 |
