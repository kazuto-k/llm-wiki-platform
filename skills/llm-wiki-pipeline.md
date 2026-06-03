---
name: llm-wiki-pipeline
description: "Wiki.js Git-based content pipeline. Build/debug/operate connector→curator→lint→merge CI pipeline, Wiki.js Git storage setup, Page Rules ACL, GraphQL sync trigger. Non-trigger: simple Wiki.js UI operations or page editing."
---

# llm-wiki-pipeline

Wiki.js + Git ストレージによるコンテンツパイプラインの構築・運用。

## パイプラインアーキテクチャ

```
connector  ──→  curator  ──→  lint-checker  ──→  merge
(branch作成)    (raw→curated)  (schema検証)       (master merge)
```

### 各コンポーネント

| コンポーネント | 役割 | LLM | 入力 | 出力 |
|--------------|------|-----|------|------|
| connector | 外部ソースから取り込み、branch に `status: raw` で commit | 不要 | 外部データ（SharePoint/Confluence） | Git branch |
| curator | `status: raw` → `curated` に変換。構造化、wikilink 付与、タグ補完、品質評価 | 要 | branch 上の raw ファイル | curated に書き換えた commit |
| lint-checker | schema.yaml 検証。必須フィールド、entity_type、status、wikilink | 不要 | branch の全ファイル | PASS/FAIL + 警告 |
| merge | lint 通過 branch を master にマージ | 不要 | branch 名 | merged master |

### curator が行うこと

1. 文体の整形（口語→技術文書）
2. 構造化（箇条書き→表、階層整理）
3. 不足情報の注記（伝聞・未確認の明示）
4. 既存ページへの wikilink 付与（存在確認付き）
5. 未作成参照先の警告（⚠ ページ未作成）
6. 不適切内容のフィルタリング（削除理由を注記）
7. description, tags, confidence の設定
8. curator traceability（curator-bot, curated_at）

## Wiki.js Git ストレージ設定

### ローカル bare repo の最小設定

```yaml
# config.yml
storage:
  git:
    authType: ssh          # ローカル bare repo は SSH 必須（basic は HTTP(S) のみ）
    repoUri: /wiki/remote.git
    branch: master
    defaultAuthorEmail: wiki@llm-wiki.internal
    defaultAuthorName: Wiki.js
    localRepoPath: /wiki/data/repo
    syncDirection: bi       # 双方向
    syncInterval: 5         # 分
    verifySSL: false
```

### Docker 起動例

```bash
docker run -d --name wikijs-test --network host \
  -v /path/to/wikijs-data:/wiki/data \
  -v /path/to/wiki-remote.git:/wiki/remote.git \
  -v /path/to/ssh-key:/wiki/data/secure \
  requarks/wiki:2
```

## 重要なピットフォール

### 初回 init 時の既存ファイル非インポート

**症状**: bare repo に事前 commit されたファイルが Wiki.js にインポートされない
**原因**: `init()` → `sync()` で `currentCommitLog.hash` が undefined のため `git diffSummary` が空になる
**回避策**: 初期セットアップ後、全ファイルにダミー commit（frontmatter 調整など）を push。次の定期 sync でインポートされる

### `published` vs `isPublished` 非対称性

- エクスポート時: `injectPageMetadata()` が `published` を書き出す
- インポート時: `processPage()` が `isPublished` を読み取る
- **Git から投入するファイルで非公開にしたい場合は `isPublished: false` が必要**

### ローカル bare repo の認証モード

- **SSH モード必須** — `basic` 認証は HTTP(S) のみ対応。`file://` パスは `https://:@file://...` に変換され失敗

### カスタム frontmatter の保持

- Wiki.js の `parseMetadata()` は YAML を `yaml.safeLoad()` で全解析
- 未知のキーは無視されるが、エクスポート時に再書き出しされるため **Git 上のファイルでは保持される**
- `type`, `entity_type`, `status`, `source_url`, `source_author`, `curator`, `curated_at`, `confidence` 等すべて使用可能

### `[[wikilink]]` は Wiki.js でリンク表示されない

- Wiki.js は `[[wikilink]]` 記法を解釈しない。標準 Markdown `[text](path)` のみクリック可能
- 内部表現（lint-checker, freshness-checker）には wikilink 形式を維持し、Wiki.js 表示用に curator が `[title](rel-path)` に変換するハイブリッド方式を推奨

## GraphQL sync トリガー

```python
import urllib.request, json

def gql(query, jwt=None):
    data = json.dumps({"query": query}).encode()
    headers = {"Content-Type": "application/json"}
    if jwt: headers["Authorization"] = "Bearer " + jwt
    r = urllib.request.urlopen(urllib.request.Request("http://localhost:3000/graphql", data=data, headers=headers))
    return json.loads(r.read())

# Login
r = gql('mutation { authentication { login(username:"admin@...", password:"...", strategy:"local") { jwt } } }')
jwt = r["data"]["authentication"]["login"]["jwt"]

# Trigger sync
r = gql('mutation { storage { executeAction(targetKey:"git", handler:"sync") { responseResult { succeeded } } } }', jwt)
```

## Page Rules ACL

### マッチタイプ（優先度: 低→高）

| タイプ | GraphQL 値 | 説明 |
|--------|-----------|------|
| Path Starts With | `START` | パスプレフィックス |
| Path Ends With | `END` | パスサフィックス |
| Path Matches Regex | `REGEX` | 正規表現 |
| Tag Matches | `TAG` | タグ一致 |
| Path Is Exactly | `EXACT` | 完全一致 |

### GraphQL による Page Rules 設定

```graphql
mutation {
  groups {
    update(
      id: 3
      permissions: ["read:pages", "read:assets"]
      pageRules: [
        { id: "entities-rule", deny: false, match: START, roles: ["read:pages"], path: "entities", locales: [] }
      ]
    ) { responseResult { succeeded } }
  }
}
```

### 制約

- カスタム frontmatter（`type`, `entity_type`, `status`）は Page Rules で直接参照不可
- タグベースルール（`match: TAG`）で代替可能
- パスが変わらなければ `status: raw` → `curated` でも ACL は一貫

## プロジェクトファイル構成

```
llm-wiki-platform/
├── pipeline/
│   ├── connector.py       # 外部コンテンツ取り込み + branch 作成
│   ├── curator.py         # raw → curated 変換（プロトタイプはルールベース）
│   ├── lint-checker.py    # schema.yaml 検証（errors=blocking, warnings=non-blocking）
│   ├── merge.py           # master へのマージ
│   ├── run-pipeline.sh    # オーケストレーター
│   └── README.md
├── test/
│   ├── wikijs-data/       # Wiki.js 永続データ
│   │   ├── config.yml
│   │   └── repo/          # Wiki.js ローカル作業ディレクトリ
│   ├── wiki-remote.git/   # bare repo（Git リモート）
│   └── wiki-content/      # 非 Wiki.js 管理のコンテンツ（手動テンプレート等）
├── docs/
│   ├── design-deep-dive.md
│   └── architecture.md
└── Design Notes/          # Obsidian vault 内
    └── 2026/experiments/
        ├── 2026-06-03-wikijs-git-sync-roundtrip.md
        ├── 2026-06-03-wikijs-page-rules.md
        └── 2026-06-03-llm-wiki-pipeline-prototype.md
```

## lint-checker のエラー/警告分離

- **Errors**（exit code 1, merge ブロック）: 必須フィールド欠落、entity_type 不正、status 不正、YAML パースエラー
- **Warnings**（exit code 0, merge 許可）: wikilink 切れ

wikilink は絶対パス（repo ルートから）→ 相対パス（現在ファイルのディレクトリから）の順で解決を試みる。
