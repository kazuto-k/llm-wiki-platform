# llm-wiki-platform テスト環境

## 起動方法

```bash
docker run -d --name wikijs-test \
  --network host \
  -v /home/kazuto/projects/llm-wiki-platform/test/wikijs-data:/wiki/data \
  -v /home/kazuto/projects/llm-wiki-platform/test/wiki-remote.git:/wiki/remote.git \
  -v /home/kazuto/projects/llm-wiki-platform/test/ssh-key:/wiki/data/secure \
  requarks/wiki:2
```

## アクセス

- URL: `http://localhost:3000`
- 管理者: `admin@llm-wiki.internal` / `admin123`

## ディレクトリ構成

```
test/
├── wikijs-data/          # Wiki.js 永続データ（コンテナの /wiki/data）
│   ├── config.yml        # Wiki.js 設定ファイル
│   ├── wiki.sqlite       # SQLite データベース
│   ├── cache/            # ページキャッシュ
│   └── repo/             # Git ローカルリポジトリ（Wiki.js 作業ディレクトリ）
│       ├── home.md
│       ├── entities/projects/test-project.md
│       └── meta/schema.yaml
├── wiki-remote.git/      # bare repo（Wiki.js の Git リモート）
├── wiki-content/         # テスト用コンテンツ（手動管理）
└── ssh-key/              # SSH 秘密鍵（Git 認証用）
```

## 同期フロー

```
[bare repo: wiki-remote.git]
       ↕ SSH（双方向、5分間隔）
[Wiki.js local repo: /wiki/data/repo]
       ↕ DB
[Wiki.js UI: localhost:3000]
```

## 手動 sync トリガー

```bash
# GraphQL API 経由で即時 sync
python3 /tmp/sync_wikijs.py
```

## コンテンツ投入テスト

```bash
# 1. bare repo を clone
git clone /home/kazuto/projects/llm-wiki-platform/test/wiki-remote.git /tmp/test-wiki

# 2. Markdown ファイルを作成/編集
cat > /tmp/test-wiki/entities/teams/example.md << 'EOF'
---
title: サンプルチーム
type: entity
entity_type: team
status: raw
---
# サンプルチーム
EOF

# 3. commit + push
cd /tmp/test-wiki
git add . && git commit -m "add example team" && git push

# 4. 5分待つか、手動 sync をトリガー
```

## 注意点

- **初回 init 後のファイルは自動インポートされない**: Wiki.js 起動後に commit したファイルのみ同期対象。既存ファイルのインポートにはダミー commit が必要
- **SSH モード必須**: ローカル bare repo では basic 認証が使えない
- **`published` ではなく `isPublished`**: 強制非公開にする場合は frontmatter に `isPublished: false` を書く
